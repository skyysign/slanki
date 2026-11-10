import io
import json
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from converter.models import Card, GenerationRun, Lecture
from converter.services.backups import export_backup, restore_backup
from converter.services.cards import (
    add_drafts,
    update_card,
    validate_generated_batch,
    validate_payload,
)
from converter.services.exporting import REVERSED_MODEL_ID, export_deck
from converter.services.files import WorkflowError
from converter.services.generation import (
    perform_run,
    prompt_for,
    resume_generation,
    start_generation,
)
from converter.services.note_types import FORMAT_TYPES, study_previews
from converter.services.selection import recent_questions

from .test_workflow import WorkflowFixture


class ReverseCardTests(WorkflowFixture):
    def candidate(self, **overrides):
        return {
            **self.payload["cards"][0],
            "note_type": "reversed",
            "front": "Retrieval practice",
            "back": "Trying to recall information from memory",
            **overrides,
        }

    def note(self):
        add_drafts(
            self.lecture,
            validate_payload(
                {"cards": [self.candidate()]}, {p.number: p for p in self.lecture.pages.all()}
            ),
        )
        return self.lecture.cards.get(note_type="reversed")

    def test_import_checks_both_sides_source_and_allowed_formats(self):
        pages = {p.number: p for p in self.lecture.pages.all()}
        for changes in (
            {"front": ""},
            {"back": " "},
            {"back": " retrieval PRACTICE "},
            {"page": 99},
            {"source_quote": "Not in the lecture"},
        ):
            with self.subTest(changes=changes), self.assertRaises(WorkflowError):
                validate_payload({"cards": [self.candidate(), self.candidate(**changes)]}, pages)
        for card_format, allowed in FORMAT_TYPES.items():
            good, issues = validate_generated_batch(
                {"cards": [self.candidate()]}, pages, card_format
            )
            self.assertEqual(bool(good), "reversed" in allowed)
            self.assertEqual(bool(issues), "reversed" not in allowed)
        url = reverse("import_cards", args=[self.lecture.pk])
        invalid = {"cards": [self.candidate(), self.candidate(back="")]}
        self.assertEqual(
            self.client.post(
                url, {"cards": SimpleUploadedFile("drafts.json", json.dumps(invalid).encode())}
            ).status_code,
            400,
        )
        self.assertFalse(self.lecture.cards.exists())
        response = self.client.post(
            url,
            {
                "cards": SimpleUploadedFile(
                    "drafts.json", json.dumps({"cards": [self.candidate()]}).encode()
                )
            },
        )
        self.assertEqual(response.status_code, 302)
        run = self.lecture.runs.get()
        self.assertEqual(
            (run.card_format, run.cards_added, run.study_cards_added), ("reversed", 1, 2)
        )

    def test_preview_swaps_escaped_sides_without_saving_and_manual_note_has_two_cards(self):
        front, back = "<script>Term</script>", "<img src=x onerror=x()>Meaning"
        previews = study_previews(front, back, "reversed")
        self.assertEqual(previews[0]["question"], previews[1]["answer"])
        self.assertEqual(previews[0]["answer"], previews[1]["question"])
        self.assertNotIn("<script>", str(previews))
        self.assertNotIn("<img", str(previews))
        with patch("converter.services.generation.subprocess.Popen") as process:
            result = self.client.post(
                reverse("preview_note", args=[self.lecture.pk]),
                {"note_type": "reversed", "front": front, "back": back},
            )
            self.assertEqual(result.json()["study_cards"], 2)
            self.assertFalse(self.lecture.cards.exists())
            process.assert_not_called()
        self.client.post(
            reverse("add_card", args=[self.lecture.pk]),
            {"page": 1, "front": front, "back": back, "note_type": "reversed"},
        )
        note = self.lecture.cards.get()
        self.assertEqual(note.study_card_count, 2)
        self.assertContains(
            self.client.get(self.lecture.get_absolute_url()), "Front (prompt for card 1)"
        )
        update_card(note.pk, note.version, note.front, note.back, "", "accepted")
        self.assertContains(
            self.client.get(reverse("preview_export", args=[self.lecture.pk])),
            "2 review cards from 1 accepted note",
        )
        self.assertContains(self.client.get(self.lecture.get_absolute_url()), "Export 2 to Anki")

    @patch("converter.services.generation.launch_worker")
    @patch("converter.services.generation.codex_executable", return_value="codex.exe")
    def test_reverse_only_default_and_explicit_limits_allow_complete_pairs(
        self, executable, launch
    ):
        request = {"pages": [1], "formats_present": "yes", "formats": ["reversed"]}
        prompt = self.client.post(reverse("prompt", args=[self.lecture.pk]), request)
        self.assertContains(prompt, "at most 2 cards TOTAL")
        self.assertContains(prompt, "each reversed note costs 2")
        self.assertContains(prompt, "Do not reverse ordinary why/how questions")
        for route in ("prompt", "generate"):
            self.assertEqual(
                self.client.post(
                    reverse(route, args=[self.lecture.pk]),
                    {**request, "card_limit": 1, "consent": "yes"},
                ).status_code,
                400,
            )
        launch.assert_not_called()
        with self.assertRaises(WorkflowError):
            start_generation(self.lecture, [1], 1, card_format="reversed")
        run = start_generation(self.lecture, [1], card_format="reversed")
        self.assertEqual(run.card_limit, 2)

    def test_batches_reserve_two_slots_and_mixed_budget_can_use_smaller_notes(self):
        page4 = self.lecture.pages.get(number=4)
        page4.text, page4.warning = "One more concept.", ""
        page4.save()
        run = GenerationRun.objects.create(
            lecture=self.lecture, page_numbers=[1, 2, 3, 4], card_format="reversed", card_limit=2
        )
        seen = []

        def generate(pages, cancelled):
            seen.append([page.number for page in pages])
            return {"cards": [self.candidate()]}

        perform_run(run.pk, generate)
        run.refresh_from_db()
        self.assertEqual(seen, [[1, 2, 3, 4]])
        self.assertEqual((run.cards_added, run.study_cards_added, run.status), (1, 2, "completed"))
        self.assertEqual(run.completed_pages, [1, 2, 3, 4])
        # An oversized two-card note must not prevent a one-card fallback fitting.
        candidate = self.candidate(front="Spaced practice", back="Study across separated sessions")
        run2 = GenerationRun.objects.create(
            lecture=self.lecture, page_numbers=[1], card_format="basic_reversed", card_limit=1
        )
        perform_run(run2.pk, lambda *_: {"cards": [candidate, {**candidate, "note_type": "basic"}]})
        run2.refresh_from_db()
        self.assertEqual((run2.study_cards_added, run2.over_limit_count), (1, 1))

    def test_swapped_pairs_and_reverse_logistics_are_filtered_before_saving(self):
        note = self.note()
        note = update_card(
            note.pk, note.version, note.front, "My edited definition", note.source_quote, "accepted"
        )
        run = GenerationRun.objects.create(
            lecture=self.lecture, page_numbers=[1], card_format="all", card_limit=10
        )
        perform_run(
            run.pk,
            lambda *_: {
                "cards": [
                    self.candidate(front=note.back, back=note.front),
                    self.candidate(front=note.back, note_type="basic"),
                    self.candidate(front="90 minutes", back="Exam duration"),
                    self.candidate(front="When is the final exam?", back="Tomorrow"),
                ]
            },
        )
        run.refresh_from_db()
        self.assertEqual((run.cards_added, run.study_cards_added, run.filtered_count), (0, 0, 2))
        note.refresh_from_db()
        self.assertEqual((note.back, note.status), ("My edited definition", "accepted"))
        self.assertIn(note.front, recent_questions(self.lecture))
        self.assertIn(note.back, recent_questions(self.lecture))

    @patch("converter.services.generation.launch_worker")
    @patch("converter.services.generation.codex_executable", return_value="codex.exe")
    @patch("converter.services.generation.codex_generate")
    def test_resume_keeps_reverse_format_edits_and_remaining_pair_budget(
        self, provider, executable, launch
    ):
        page4 = self.lecture.pages.get(number=4)
        page4.text, page4.warning = "Spaced practice means study across separated sessions.", ""
        page4.save()
        run = start_generation(self.lecture, [1, 2, 3, 4], 4, card_format="reversed")
        provider.side_effect = [
            {"cards": [self.candidate()]},
            WorkflowError("Synthetic interruption"),
        ]
        perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual((run.status, run.study_cards_added), ("failed", 2))
        note = self.lecture.cards.get()
        note = update_card(
            note.pk, note.version, note.front, "My edited definition", note.source_quote, "accepted"
        )
        resume_generation(run)
        provider.side_effect = None
        provider.return_value = {
            "cards": [
                self.candidate(
                    front="Spaced practice",
                    back="Study across separated sessions",
                    page=4,
                    source_quote=page4.text,
                )
            ]
        }
        perform_run(run.pk)
        run.refresh_from_db()
        note.refresh_from_db()
        self.assertEqual((run.status, run.cards_added, run.study_cards_added), ("completed", 2, 4))
        self.assertEqual(provider.call_args.kwargs["card_format"], "reversed")
        self.assertEqual(provider.call_args.kwargs["card_limit"], 2)
        self.assertIn(note.back, provider.call_args.kwargs["existing_questions"])
        self.assertEqual((note.back, note.status), ("My edited definition", "accepted"))
        self.assertContains(
            self.client.get(self.lecture.get_absolute_url()),
            'name="formats" value="reversed" checked',
        )

    def test_backup_preserves_reverse_identity_crops_revisions_and_format_combination(self):
        note = self.note()
        crop = dict(page=note.page.number, left=10, top=20, right=100, bottom=100, on_question=True)
        note = update_card(
            note.pk,
            note.version,
            note.front,
            "My edited definition",
            note.source_quote,
            "accepted",
            source_crop=crop,
        )
        run = GenerationRun.objects.create(
            lecture=self.lecture,
            status="completed",
            card_format="cloze_reversed",
            page_numbers=[1],
            completed_pages=[1],
        )
        original = self.archive_db(export_deck(self.lecture))[0][0]
        data = export_backup(self.lecture)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(json.loads(archive.read("manifest.json"))["version"], 12)
        Card.objects.all().delete()
        Lecture.objects.all().delete()
        destination = Path(self.directory.name) / str(uuid.uuid4())
        destination.mkdir()
        with self.settings(MEDIA_ROOT=destination):
            restored = restore_backup(SimpleUploadedFile("backup.zip", data))
            saved = restored.cards.get(pk=note.pk)
            self.assertEqual(
                (saved.note_type, saved.study_card_count, saved.source_crop), ("reversed", 2, crop)
            )
            self.assertEqual(saved.revisions.get().note_type, "reversed")
            self.assertEqual(restored.runs.get(pk=run.pk).card_format, "cloze_reversed")
            exported, cards, _ = self.archive_db(export_deck(restored))
            self.assertEqual(exported[0], original)
            self.assertEqual(exported[0][1], REVERSED_MODEL_ID)
            self.assertEqual(sorted(row[1] for row in cards), [0, 1])
        self.assertIn(
            '"note_type": "cloze"',
            prompt_for(list(restored.pages.all()), card_format="cloze_reversed"),
        )

    def test_invalid_reverse_backup_rolls_back(self):
        self.note()
        data = export_backup(self.lecture)
        Card.objects.all().delete()
        Lecture.objects.all().delete()
        corrupt = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(corrupt, "w") as target:
            for name in source.namelist():
                contents = source.read(name)
                if name == "manifest.json":
                    manifest = json.loads(contents)
                    manifest["cards"][0]["back"] = ""
                    contents = json.dumps(manifest).encode()
                target.writestr(name, contents)
        destination = settings.WORK_DIR / str(uuid.uuid4())
        destination.mkdir()
        with self.settings(MEDIA_ROOT=destination), self.assertRaises(WorkflowError):
            restore_backup(SimpleUploadedFile("invalid.zip", corrupt.getvalue()))
        self.assertFalse(Lecture.objects.exists())
        self.assertEqual(list(destination.iterdir()), [])
