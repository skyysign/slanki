import copy
import io
import json
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from converter.models import Card, GenerationRun, Lecture, Page
from converter.services.backups import export_backup, restore_backup
from converter.services.cards import update_card
from converter.services.files import WorkflowError
from converter.services.generation import (
    generation_request,
    perform_run,
    remaining_pages,
    resume_generation,
)
from converter.services.rundown import validate_rundown_section
from converter.services.visual_cards import (
    add_visual_drafts,
    validate_visual_payload,
    visual_png,
)

from .test_workflow import WorkflowFixture


def visual_output(page):
    return {
        "cards": [
            {
                "front": f"What relationship does the figure on page {page.number} illustrate?",
                "back": "The figure connects the concepts shown in this synthetic example.",
                "source_quote": "",
                "crop": dict(left=10, top=20, right=450, bottom=280),
                "masks": [dict(left=20, top=30, right=220, bottom=90)],
            }
        ]
    }


def rundown_output(pages):
    return {
        "title": "Study concepts",
        "topics": [
            {
                "title": f"Concept on page {p.number}",
                "explanation": "A synthetic explanation. <script>alert(1)</script>",
                "key_points": ["A key point from the lecture."],
                "formulas": [
                    {
                        "expression": "x = y",
                        "meaning": "Synthetic equality",
                        "symbols": "x and y are placeholders",
                        "conditions": "Synthetic test only",
                    }
                ],
                "page": p.number,
                "source_quote": p.text[:80],
            }
            for p in pages
        ],
        "skipped": [],
    }


class VisualQuestionTests(WorkflowFixture):
    def make_visual(self):
        page = self.lecture.pages.get(number=4)
        run = GenerationRun.objects.create(
            lecture=self.lecture,
            page_numbers=[4],
            visual_enabled=True,
            text_enabled=False,
            card_limit=1,
            image_completed_pages=[4],
            status="completed",
            cards_added=1,
            study_cards_added=1,
        )
        add_visual_drafts(run, page, validate_visual_payload(visual_output(page), page), 1)
        return self.lecture.cards.get(note_type="visual")

    def test_cropped_question_hides_all_covers_and_answer_reveals_original(self):
        card = self.make_visual()
        second = dict(page=4, left=260, top=40, right=320, bottom=100)
        masks = card.visual_masks + [second]
        question = visual_png(card.page, card.source_crop, masks)
        answer = visual_png(card.page, card.source_crop, masks, answer=True)
        with (
            Image.open(Path(settings.MEDIA_ROOT) / card.page.image) as source,
            Image.open(io.BytesIO(question)) as hidden,
            Image.open(io.BytesIO(answer)) as revealed,
        ):
            self.assertEqual(hidden.size, (440, 260))
            self.assertEqual(
                revealed.tobytes(), source.convert("RGB").crop((10, 20, 450, 280)).tobytes()
            )
            for box in ((10, 10, 210, 70), (250, 20, 310, 80)):
                self.assertEqual(
                    hidden.crop(box).getextrema(), ((229, 229), (232, 232), (226, 226))
                )
        self.assertEqual(card.study_card_count, 1)
        self.assertEqual(
            visual_png(card.page, {}, [], answer=False), visual_png(card.page, {}, [], answer=True)
        )

    def test_generated_coordinates_content_and_source_are_validated_atomically(self):
        page = self.lecture.pages.get(number=4)
        good = visual_output(page)
        for change in (
            {"back": ""},
            {"source_quote": "not on the slide"},
            {"masks": [{}]},
            {"masks": [dict(left=0, top=0, right=50, bottom=50)]},
            {"crop": dict(left=True, top=0, right=500, bottom=200)},
            {"crop": dict(left=0, top=0, right=page.width + 1, bottom=200)},
        ):
            bad = copy.deepcopy(good)
            bad["cards"].append({**bad["cards"][0], **change})
            with self.subTest(change=change), self.assertRaises(WorkflowError):
                validate_visual_payload(bad, page)
        self.assertFalse(Card.objects.exists())
        self.assertEqual(validate_visual_payload({"cards": []}, page), [])

    def test_visual_edits_preview_and_backup_preserve_identity_and_revisions(self):
        card = self.make_visual()
        original = copy.deepcopy(card.visual_masks)
        changed = [{**original[0], "right": 240}]
        edited = update_card(
            card.pk, 1, "Edited figure question", card.back, "", "accepted", visual_masks=changed
        )
        with self.assertRaisesMessage(WorkflowError, "another tab"):
            update_card(card.pk, 1, card.front, card.back, "", "draft", visual_masks=[])
        self.assertEqual(edited.revisions.get().visual_masks, original)
        values = {
            "card_id": card.pk,
            "note_type": "visual",
            "front": card.front,
            "back": card.back,
            "masks": json.dumps(changed),
        }
        preview = self.client.post(reverse("preview_note", args=[self.lecture.pk]), values)
        self.assertEqual(preview.status_code, 200)
        self.assertNotEqual(
            preview.json()["previews"][0]["question_image"],
            preview.json()["previews"][0]["answer_image"],
        )
        self.assertEqual(
            self.client.post(
                reverse("preview_note", args=[self.lecture.pk]), {**values, "card_id": "invalid"}
            ).status_code,
            400,
        )
        self.assertContains(
            self.client.get(self.lecture.get_absolute_url()), "Cover answer-revealing text"
        )
        data = export_backup(self.lecture)
        Card.objects.all().delete()
        Lecture.objects.all().delete()
        destination = Path(self.directory.name) / str(uuid.uuid4())
        destination.mkdir()
        override = override_settings(MEDIA_ROOT=destination)
        override.enable()
        self.addCleanup(override.disable)
        restored = restore_backup(SimpleUploadedFile("visual.zip", data))
        saved = restored.cards.get(pk=card.pk)
        self.assertEqual(
            (saved.front, saved.status, saved.visual_masks, saved.source_crop),
            (edited.front, "accepted", changed, card.source_crop),
        )
        self.assertEqual(saved.revisions.get().visual_masks, original)

    def test_visual_first_then_text_share_budget_and_resume_keeps_edited_cards(self):
        run = GenerationRun.objects.create(
            lecture=self.lecture, page_numbers=[1, 2, 3, 4], visual_enabled=True, card_limit=6
        )
        calls = []

        def generate(pages, *args, **kwargs):
            calls.append((kwargs.get("task", "cards"), [p.number for p in pages]))
            if kwargs.get("task") == "visual":
                return visual_output(pages[0])
            raise WorkflowError("Synthetic interruption")

        with patch("converter.services.generation.codex_generate", side_effect=generate):
            perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed", run.error)
        self.assertEqual(run.image_completed_pages, [1, 2, 3, 4])
        self.assertEqual(run.study_cards_added, 2)
        card = run.card_set.first()
        update_card(card.pk, 1, "My own question", card.back, "", "accepted", visual_masks=[])
        with (
            patch("converter.services.generation.checked_model_settings"),
            patch("converter.services.generation.codex_executable"),
            patch("converter.services.generation.launch_worker"),
        ):
            resume_generation(run)
        calls.clear()

        def finish(pages, *args, **kwargs):
            calls.append(kwargs)
            return {
                "cards": [
                    c for c in self.payload["cards"] if c["page"] in [p.number for p in pages]
                ]
            }

        with patch("converter.services.generation.codex_generate", side_effect=finish):
            perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, "completed", run.error)
        self.assertTrue(all(c.get("task", "cards") == "cards" for c in calls))
        self.assertLessEqual(run.study_cards_added, 6)
        self.assertEqual(remaining_pages(run), [])
        card.refresh_from_db()
        self.assertEqual(
            (card.front, card.status, card.visual_masks), ("My own question", "accepted", [])
        )

    def test_cancellation_discards_late_visual_output_and_modes_are_separate(self):
        run = GenerationRun.objects.create(
            lecture=self.lecture,
            page_numbers=[4],
            visual_enabled=True,
            text_enabled=False,
            card_limit=1,
        )

        def late(pages, *args, **kwargs):
            GenerationRun.objects.filter(pk=run.pk).update(status="cancelled")
            return visual_output(pages[0])

        with patch("converter.services.generation.codex_generate", side_effect=late):
            perform_run(run.pk)
        self.assertFalse(Card.objects.exists())
        values = {"formats_present": "yes", "formats": ["visual"], "pages": [4], "consent": "yes"}
        with patch("converter.views.start_generation") as start:
            response = self.client.post(reverse("generate", args=[self.lecture.pk]), values)
            self.assertEqual(response.status_code, 302)
            self.assertFalse(start.call_args.kwargs["text_enabled"])
            self.assertTrue(start.call_args.kwargs["visual_enabled"])
            for extra in ({"provider": "claude"}, {"formats": ["visual", "occlusion"]}):
                self.assertEqual(
                    self.client.post(
                        reverse("generate", args=[self.lecture.pk]), {**values, **extra}
                    ).status_code,
                    400,
                )
        main = self.client.get(self.lecture.get_absolute_url())
        self.assertContains(main, 'value="visual" data-image-format')
        self.assertNotContains(main, 'value="occlusion" data-image-format')
        self.assertContains(
            self.client.get(reverse("anatomy", args=[self.lecture.pk])), "Draw masks manually"
        )


class LectureRundownTests(WorkflowFixture):
    def run_record(self):
        return GenerationRun.objects.create(
            lecture=self.lecture, purpose="rundown", page_numbers=[1, 2, 3]
        )

    def generate(self, run):
        with patch(
            "converter.services.generation.codex_generate",
            side_effect=lambda pages, *a, **kw: rundown_output(pages),
        ):
            perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, "completed", run.error)

    def test_guide_has_own_view_versions_download_source_links_and_no_cards(self):
        self.accepted_card()
        before = list(Card.objects.values())
        run = self.run_record()
        self.generate(run)
        old = copy.deepcopy(run.rundown_data)
        newer = self.run_record()
        self.generate(newer)
        self.assertEqual(list(Card.objects.values()), before)
        response = self.client.get(
            reverse("lecture_rundown", args=[self.lecture.pk]), {"run": str(run.pk)}
        )
        self.assertContains(response, "Concept on page 1")
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "Symbols:")
        self.assertContains(response, "no usable extracted text")
        self.assertContains(
            response, reverse("page_image", args=[self.lecture.pages.get(number=1).pk])
        )
        downloaded = self.client.get(reverse("download_rundown", args=[run.pk]))
        self.assertContains(downloaded, "Source excerpt:")
        self.assertContains(downloaded, "not included: 4")
        run.refresh_from_db()
        self.assertEqual(run.rundown_data, old)

    def test_rundown_resume_reuses_saved_sections_and_backup_carries_both_versions(self):
        page = self.lecture.pages.get(number=1)
        Page.objects.create(
            lecture=self.lecture,
            number=5,
            text=page.text,
            image=page.image,
            width=page.width,
            height=page.height,
        )
        Page.objects.create(
            lecture=self.lecture,
            number=6,
            text=page.text,
            image=page.image,
            width=page.width,
            height=page.height,
        )
        run = self.run_record()
        run.page_numbers = [1, 2, 3, 5, 6]
        run.save()

        def interrupted(pages, *args, **kwargs):
            if pages[0].number == 6:
                raise WorkflowError("Synthetic pause")
            return rundown_output(pages)

        with patch("converter.services.generation.codex_generate", side_effect=interrupted):
            perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.completed_pages, [1, 2, 3, 5])
        original = copy.deepcopy(run.rundown_data["sections"][0])
        with (
            patch("converter.services.generation.checked_model_settings"),
            patch("converter.services.generation.codex_executable"),
            patch("converter.services.generation.launch_worker"),
        ):
            resume_generation(run)
        calls = []

        def finish(pages, *args, **kwargs):
            calls.append([p.number for p in pages])
            return rundown_output(pages)

        with patch("converter.services.generation.codex_generate", side_effect=finish):
            perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(calls, [[6]])
        self.assertEqual(run.status, "completed", run.error)
        self.assertEqual(run.rundown_data["sections"][0], original)
        # Return to the original four-page document before its asset-count checks.
        self.lecture.pages.filter(number__gt=4).delete()
        run.delete()
        first, second = self.run_record(), None
        self.generate(first)
        second = self.run_record()
        self.generate(second)
        data = export_backup(self.lecture)
        Card.objects.all().delete()
        Lecture.objects.all().delete()
        destination = Path(self.directory.name) / str(uuid.uuid4())
        destination.mkdir()
        override = override_settings(MEDIA_ROOT=destination)
        override.enable()
        self.addCleanup(override.disable)
        restored = restore_backup(SimpleUploadedFile("rundown.zip", data))
        self.assertEqual(restored.runs.count(), 2)
        self.assertEqual(restored.runs.get(pk=first.pk).rundown_data, first.rundown_data)
        self.assertEqual(restored.runs.get(pk=second.pk).purpose, "rundown")

    def test_missing_pages_invented_sources_and_corrupt_backup_are_rejected(self):
        pages = list(self.lecture.pages.filter(number__in=[1, 2, 3]))
        good = rundown_output(pages)
        for change in ("missing", "quote", "page", "formula"):
            bad = copy.deepcopy(good)
            if change == "missing":
                bad["topics"].pop()
            if change == "quote":
                bad["topics"][0]["source_quote"] = "fabricated excerpt"
            if change == "page":
                bad["topics"][0]["page"] = 4
            if change == "formula":
                bad["topics"][0]["formulas"][0]["symbols"] = ""
            with self.subTest(change=change), self.assertRaises(WorkflowError):
                validate_rundown_section(bad, {p.number: p for p in pages})
        run = self.run_record()
        self.generate(run)
        data = export_backup(self.lecture)
        corrupt = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(corrupt, "w") as target:
            for name in source.namelist():
                content = source.read(name)
                if name == "manifest.json":
                    manifest = json.loads(content)
                    manifest["runs"][0]["rundown_data"]["document"] = "wrong identity"
                    content = json.dumps(manifest).encode()
                target.writestr(name, content)
        Card.objects.all().delete()
        Lecture.objects.all().delete()
        destination = Path(self.directory.name) / str(uuid.uuid4())
        destination.mkdir()
        override = override_settings(MEDIA_ROOT=destination)
        override.enable()
        self.addCleanup(override.disable)
        with self.assertRaises(WorkflowError):
            restore_backup(SimpleUploadedFile("bad.zip", corrupt.getvalue()))
        self.assertFalse(GenerationRun.objects.exists())

    def test_cancelled_or_replaced_worker_cannot_publish_late_rundown(self):
        for replace in (False, True):
            run = self.run_record()

            def late(pages, *args, **kwargs):
                changes = (
                    {"worker_token": uuid.uuid4(), "status": "failed"}
                    if replace
                    else {"status": "cancelled"}
                )
                GenerationRun.objects.filter(pk=run.pk).update(**changes)
                return rundown_output(pages)

            with patch("converter.services.generation.codex_generate", side_effect=late):
                perform_run(run.pk)
            run.refresh_from_db()
            self.assertEqual(run.rundown_data, {})
            self.assertEqual(run.completed_pages, [])

    @patch("converter.views.start_generation")
    def test_consent_all_readable_pages_and_provider_neutral_schema(self, start):
        url = reverse("generate_rundown", args=[self.lecture.pk])
        self.assertEqual(self.client.post(url, {}).status_code, 400)
        start.assert_not_called()
        for provider in ("codex", "claude", "gemini", "kimi"):
            self.assertEqual(
                self.client.post(url, {"consent": "yes", "provider": provider}).status_code, 302
            )
            self.assertEqual(start.call_args.args[1], [1, 2, 3])
            self.assertEqual(start.call_args.kwargs["purpose"], "rundown")
            self.assertEqual(start.call_args.kwargs["provider"], provider)
        prompt, schema = generation_request(
            list(self.lecture.pages.filter(number=1)), task="rundown"
        )
        self.assertIn("ALL subject-matter concepts", prompt)
        self.assertIn("formulas", schema["properties"]["topics"]["items"]["properties"])
