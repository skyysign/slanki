import io
import json
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse

from converter.models import Card, GenerationRun, Lecture, OcclusionSuggestion
from converter.services.backups import export_backup, restore_backup
from converter.services.deletion import delete_lecture
from converter.services.exporting import export_deck
from converter.services.files import WorkflowError
from converter.services.generation import (
    perform_run,
    remaining_pages,
    resume_generation,
    start_generation,
)
from converter.services.occlusion import add_occlusions
from converter.services.occlusion_review import review_suggestion

from .test_workflow import WorkflowFixture


class OcclusionRunTests(WorkflowFixture):
    def image_output(self, number=1):
        return {
            "suggestions": [
                {
                    "label": f"Label {number}",
                    "reason": "Recall the labelled structure.",
                    "left": 20,
                    "top": 30,
                    "right": 180,
                    "bottom": 100,
                }
            ]
        }

    def run_record(self, **kwargs):
        return GenerationRun.objects.create(
            lecture=self.lecture,
            page_numbers=[1, 2, 3, 4],
            occlusion_enabled=True,
            text_enabled=False,
            card_limit=4,
            **kwargs,
        )

    def generate(self, run):
        with patch(
            "converter.services.generation.codex_generate",
            side_effect=lambda pages, *args, **kwargs: self.image_output(pages[0].number),
        ):
            perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, "completed", run.error)
        return list(run.suggestions.all())

    def resume(self, run):
        with (
            patch("converter.services.generation.checked_model_settings"),
            patch("converter.services.generation.codex_executable"),
            patch("converter.services.generation.launch_worker"),
        ):
            resume_generation(run)

    @patch("converter.views.start_generation")
    def test_checkbox_modes_image_only_page_and_invalid_provider(self, start):
        url = reverse("generate", args=[self.lecture.pk])
        values = {
            "pages": [1, 4],
            "formats_present": "yes",
            "consent": "yes",
            "formats": ["occlusion"],
        }
        for formats, text, expected in [
            (["occlusion"], False, "basic"),
            (["cloze", "occlusion"], True, "cloze"),
            (["basic", "reversed", "cloze", "occlusion"], True, "all"),
        ]:
            with self.subTest(formats=formats):
                response = self.client.post(url, {**values, "formats": formats})
                self.assertEqual(response.status_code, 302)
                self.assertEqual(start.call_args.args[1], [1, 4])
                self.assertEqual(start.call_args.kwargs["text_enabled"], text)
                self.assertTrue(start.call_args.kwargs["occlusion_enabled"])
                self.assertEqual(start.call_args.kwargs["card_format"], expected)
        start.reset_mock()
        for extra in (
            {"provider": "claude"},
            {"formats": ["occlusion", "occlusion"]},
            {"formats": ["unknown", "occlusion"]},
            {"formats": ["basic"]},
            {"consent": ""},
            {"formats": ["reversed", "occlusion"], "card_limit": "2"},
        ):
            self.assertEqual(self.client.post(url, {**values, **extra}).status_code, 400)
        start.assert_not_called()
        self.assertEqual(
            self.client.post(reverse("prompt", args=[self.lecture.pk]), values).status_code, 400
        )

    @patch("converter.services.generation.launch_worker")
    @patch("converter.services.generation.codex_executable")
    @patch("converter.services.generation.checked_model_settings")
    @patch("converter.services.connection.login_status", return_value={"state": "connected"})
    def test_start_persists_modes_and_image_only_lecture_has_no_text_overview(self, *mocks):
        self.lecture.pages.update(text="", warning="No usable text")
        run = start_generation(
            self.lecture, [4], text_enabled=False, occlusion_enabled=True, context_enabled=True
        )
        self.assertFalse(run.context_enabled)
        self.assertFalse(run.text_enabled)
        self.assertTrue(run.occlusion_enabled)
        self.assertEqual(run.page_numbers, [4])
        self.assertEqual(run.format_label, "Image occlusion")
        self.assertEqual(self.client.get(self.lecture.get_absolute_url()).status_code, 200)
        with self.assertRaises(WorkflowError):
            start_generation(self.lecture, [4], provider="claude", occlusion_enabled=True)

    def test_overview_all_images_then_text_share_budget_and_keep_source_scope(self):
        run = GenerationRun.objects.create(
            lecture=self.lecture,
            page_numbers=[1, 2, 3, 4],
            context_enabled=True,
            occlusion_enabled=True,
            card_limit=6,
            reasoning_effort="high",
            model="synthetic",
        )
        calls = []

        def generate(pages, cancelled, **kwargs):
            calls.append((kwargs.get("task", "cards"), [page.number for page in pages]))
            self.assertEqual(kwargs["reasoning_effort"], "high")
            self.assertEqual(kwargs["model"], "synthetic")
            if kwargs.get("task") == "overview":
                return {
                    "topics": [
                        {
                            "title": "Memory",
                            "summary": "Recall concepts.",
                            "priority": "core",
                            "page": 1,
                            "source_quote": pages[0].text[:50],
                        }
                    ]
                }
            self.assertEqual(len(kwargs["lecture_context"]), 1)
            if kwargs.get("task") == "occlusion":
                return self.image_output(pages[0].number)
            self.assertNotIn(4, [page.number for page in pages])
            return {"cards": [self.payload["cards"][0]]}

        with patch("converter.services.generation.codex_generate", side_effect=generate):
            perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, "completed", run.error)
        self.assertEqual(
            calls,
            [
                ("overview", [1, 2, 3]),
                ("occlusion", [1]),
                ("occlusion", [2]),
                ("occlusion", [3]),
                ("occlusion", [4]),
                ("cards", [1, 2, 3]),
            ],
        )
        self.assertEqual(run.image_completed_pages, [1, 2, 3, 4])
        self.assertEqual(run.completed_pages, [1, 2, 3, 4])
        self.assertEqual(run.suggestions.count(), 2)
        self.assertFalse(self.lecture.cards.filter(note_type="occlusion").exists())
        self.assertLessEqual(run.study_cards_added + run.suggestions.count(), 6)
        self.assertEqual(remaining_pages(run), [])
        status = self.client.get(reverse("run_status", args=[run.pk])).json()
        self.assertEqual(status["suggestions"], 2)
        self.assertEqual(status["review_url"], reverse("review_occlusions", args=[self.lecture.pk]))

    def test_failure_resume_preserves_edits_discard_and_completed_image_pages(self):
        run = self.run_record()

        def generate(pages, *args, **kwargs):
            if pages[0].number == 2:
                first = run.suggestions.get()
                edited = review_suggestion(
                    first.pk,
                    first.version,
                    "save",
                    front="Edited prompt",
                    back="Saved explanation",
                    mask={**first.mask, "right": 220},
                )
                review_suggestion(edited.pk, edited.version, "discard")
                raise WorkflowError("Synthetic image failure")
            return self.image_output()

        with patch("converter.services.generation.codex_generate", side_effect=generate):
            perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.image_completed_pages, [1])
        self.assertEqual(remaining_pages(run), [2, 3, 4])
        first = run.suggestions.get()
        self.resume(run)
        with patch(
            "converter.services.generation.codex_generate", return_value={"suggestions": []}
        ) as generate:
            perform_run(run.pk)
        self.assertEqual([call.args[0][0].number for call in generate.call_args_list], [2, 3, 4])
        first.refresh_from_db()
        self.assertEqual(
            (first.front, first.mask["right"], first.status), ("Edited prompt", 220, "discarded")
        )
        self.assertEqual(run.suggestions.count(), 1)
        self.assertFalse(Card.objects.exists())

    def test_cancelled_and_replaced_worker_cannot_save_late_masks(self):
        run = self.run_record()
        old_token = run.worker_token

        def cancel(*args, **kwargs):
            GenerationRun.objects.filter(pk=run.pk).update(status="cancelled")
            self.resume(run)
            return self.image_output()

        with patch("converter.services.generation.codex_generate", side_effect=cancel):
            perform_run(run.pk, worker_token=old_token)
        run.refresh_from_db()
        self.assertEqual(run.status, "queued")
        self.assertNotEqual(run.worker_token, old_token)
        self.assertFalse(run.suggestions.exists())
        perform_run(run.pk, worker_token=old_token)
        self.assertFalse(run.suggestions.exists())
        self.generate(run)

    def test_malformed_masks_fail_visibly_and_empty_slide_is_completed(self):
        run = self.run_record()
        with patch(
            "converter.services.generation.codex_generate",
            side_effect=[
                {"suggestions": []},
                {"suggestions": [{**self.image_output()["suggestions"][0], "right": 99999}]},
            ],
        ):
            perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertTrue(run.error)
        self.assertEqual(run.image_completed_pages, [1])
        self.assertFalse(run.suggestions.exists())

    def test_review_accept_edit_discard_stale_submission_and_duplicate_preservation(self):
        run = self.run_record()
        first, second, third, _ = self.generate(run)
        url = reverse("review_occlusions", args=[self.lecture.pk])
        data = {
            "suggestion": str(first.pk),
            "version": first.version,
            "action": "save",
            "front": "My prompt",
            "back": "Explanation",
            "masks": json.dumps([{**first.mask, "right": 210}]),
        }
        self.assertEqual(Client(enforce_csrf_checks=True).post(url, data).status_code, 403)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertFalse(Card.objects.exists())
        self.assertEqual(self.client.post(url, {**data, "action": "accept"}).status_code, 400)
        first.refresh_from_db()
        data["version"] = first.version
        self.assertEqual(self.client.post(url, {**data, "action": "accept"}).status_code, 302)
        first.refresh_from_db()
        self.assertEqual(first.card.status, "accepted")
        self.assertEqual(first.card.front, "My prompt")
        self.assertEqual(first.card.occlusion["right"], 210)
        self.assertEqual(self.client.post(url, {**data, "action": "accept"}).status_code, 400)
        self.assertEqual(Card.objects.count(), 1)
        self.assertEqual(
            self.client.post(
                url, {"suggestion": str(second.pk), "version": 1, "action": "discard"}
            ).status_code,
            302,
        )
        second.refresh_from_db()
        self.assertEqual(second.status, "discarded")
        self.assertEqual(
            self.client.post(
                url, {"suggestion": str(second.pk), "version": second.version, "action": "restore"}
            ).status_code,
            302,
        )
        card = add_occlusions(
            self.lecture, third.page, "Existing prompt", "Keep this", [third.mask]
        )[0]
        result = review_suggestion(
            third.pk, third.version, "accept", front="Replace?", back="", mask=third.mask
        )
        self.assertEqual(result.card_id, card.pk)
        card.refresh_from_db()
        self.assertEqual(
            (card.front, card.back, card.status), ("Existing prompt", "Keep this", "draft")
        )

    def test_backup_keeps_pending_edits_discarded_and_accepted_card_identity(self):
        run = self.run_record()
        first, second, third, _ = self.generate(run)
        accepted = review_suggestion(
            first.pk, 1, "accept", front=first.front, back="", mask=first.mask
        )
        review_suggestion(
            second.pk,
            1,
            "save",
            front="Edited pending",
            back="",
            mask={**second.mask, "right": 230},
        )
        review_suggestion(third.pk, 1, "discard")
        before = export_deck(self.lecture)
        backup = export_backup(self.lecture)
        OcclusionSuggestion.objects.all().delete()
        Card.objects.all().delete()
        Lecture.objects.all().delete()
        destination = Path(self.directory.name) / str(uuid.uuid4())
        with override_settings(MEDIA_ROOT=destination):
            restored = restore_backup(SimpleUploadedFile("backup.zip", backup))
            saved = OcclusionSuggestion.objects.get(pk=first.pk)
            self.assertEqual(saved.card_id, accepted.card_id)
            self.assertEqual(OcclusionSuggestion.objects.get(pk=second.pk).mask["right"], 230)
            self.assertEqual(OcclusionSuggestion.objects.get(pk=third.pk).status, "discarded")
            after_notes, after_cards, after_media = self.archive_db(export_deck(restored))
            before_notes, before_cards, before_media = self.archive_db(before)
            self.assertEqual(
                after_notes, before_notes
            )  # Stable GUID, type, modification time and fields.
            self.assertEqual(after_media, before_media)
            self.assertEqual(
                [ordinal for _, ordinal in after_cards], [ordinal for _, ordinal in before_cards]
            )
            self.assertEqual(
                self.client.get(reverse("review_occlusions", args=[restored.pk])).status_code, 200
            )

    def test_corrupt_backup_rolls_back_suggestions_and_delete_blocks_late_worker(self):
        run = self.run_record()
        self.generate(run)
        backup = export_backup(self.lecture)
        OcclusionSuggestion.objects.all().delete()
        Card.objects.all().delete()
        Lecture.objects.all().delete()
        for field, value in (
            ("mask", {"page": 99, "left": 0, "top": 0, "right": 5, "bottom": 5}),
            ("status", "accepted"),
            ("version", True),
        ):
            output = io.BytesIO()
            with (
                zipfile.ZipFile(io.BytesIO(backup)) as source,
                zipfile.ZipFile(output, "w") as target,
            ):
                manifest = json.loads(source.read("manifest.json"))
                manifest["runs"][0]["suggestions"][0][field] = value
                for name in source.namelist():
                    target.writestr(
                        name,
                        json.dumps(manifest).encode()
                        if name == "manifest.json"
                        else source.read(name),
                    )
            destination = Path(self.directory.name) / str(uuid.uuid4())
            with override_settings(MEDIA_ROOT=destination), self.assertRaises(WorkflowError):
                restore_backup(SimpleUploadedFile("invalid.zip", output.getvalue()))
            self.assertFalse(Lecture.objects.exists())
        with override_settings(MEDIA_ROOT=Path(self.directory.name) / str(uuid.uuid4())):
            self.lecture = restore_backup(SimpleUploadedFile("good.zip", backup))
            with self.captureOnCommitCallbacks(execute=True):
                delete_lecture(self.lecture.pk)
        self.assertFalse(OcclusionSuggestion.objects.exists())
        perform_run(run.pk)
        self.assertFalse(Lecture.objects.exists())
