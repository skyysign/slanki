import copy
import io
import json
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, override_settings
from django.urls import reverse

from converter.models import Card, GenerationRun, Lecture
from converter.services.backups import export_backup, restore_backup
from converter.services.cards import add_drafts, fingerprint, update_card
from converter.services.files import WorkflowError
from converter.services.generation import perform_run, prompt_for, resume_generation
from converter.services.selection import (
    checked_card_limit,
    is_course_logistics,
    set_aside_logistics,
)

from .test_workflow import WorkflowFixture


class LogisticsRulesTests(SimpleTestCase):
    def test_clear_course_logistics_and_subject_matter_counterexamples(self):
        for question in (
            "How long is the exam?",
            "What material does the exam cover, and which textbook sub-chapters are excluded?",
            "What materials and tools are allowed in the exam?",
            "How does the expected exam difficulty compare with slide questions?",
            "When does the final exam take place?",
            "How is the course graded?",
            "What are the professor's office hours?",
            "Wie lange dauert die Prüfung?",
            "Welche Hilfsmittel sind in der Klausur erlaubt?",
        ):
            with self.subTest(question=question):
                self.assertTrue(is_course_logistics(question))
        for question in (
            "How is bond duration calculated?",
            "In an exam, how is bond duration calculated?",
            "What is the present value of a future cash flow?",
            "When does exam anxiety impair retrieval?",
            "How long is the physical exam?",
            "What materials are used in a neurological exam?",
            "How does a clinical examination assess muscle strength?",
            "Wie lange dauert eine körperliche Prüfung?",
        ):
            with self.subTest(question=question):
                self.assertFalse(is_course_logistics(question))

    def test_limits_are_validated_and_default_to_compact_selection(self):
        self.assertEqual(checked_card_limit(None, 85), 43)
        self.assertEqual(checked_card_limit("", 3), 2)
        self.assertEqual(checked_card_limit("30", 85), 30)
        for value in (-1, 0, 501, True, "1.5", "many"):
            with self.subTest(value=value), self.assertRaises(WorkflowError):
                checked_card_limit(value, 85)


class CompactGenerationTests(WorkflowFixture):
    def test_limit_filters_duplicates_and_logistics_before_counting(self):
        good = copy.deepcopy(self.payload["cards"])
        duplicate = copy.deepcopy(good[0])
        duplicate["front"] = "  " + duplicate["front"].upper() + "  "
        admin = {**good[0], "front": "How long is the exam?", "source_quote": "Not on the page"}
        run = GenerationRun.objects.create(
            lecture=self.lecture, page_numbers=[1, 2, 3], card_limit=2
        )
        perform_run(run.pk, lambda *_: {"cards": [admin, good[0], duplicate, *good[1:]]})
        run.refresh_from_db()
        self.assertEqual(
            (run.status, run.cards_added, run.filtered_count, run.over_limit_count),
            ("completed", 2, 1, 3),
        )
        self.assertEqual(run.issues, [])
        self.assertEqual(Card.objects.count(), 2)
        self.assertEqual(
            set(Card.objects.values_list("front", flat=True)), {c["front"] for c in good[:2]}
        )
        response = self.client.get(self.lecture.get_absolute_url())
        self.assertContains(response, "Maximum 2 new cards")
        self.assertContains(response, "1 course logistics candidates filtered")

    @patch("converter.services.generation.codex_generate")
    def test_provider_gets_compact_budget_and_saved_questions(self, provider):
        self.accepted_card()
        provider.return_value = {"cards": []}
        run = GenerationRun.objects.create(
            lecture=self.lecture, page_numbers=[1, 2, 3], card_limit=2
        )
        perform_run(run.pk)
        self.assertEqual(provider.call_args.kwargs["card_limit"], 2)
        self.assertEqual(len(provider.call_args.kwargs["existing_questions"]), 5)
        prompt = prompt_for(self.lecture.pages.all(), 2, ["Already covered?"])
        self.assertIn("at most 2 cards TOTAL", prompt)
        self.assertIn("Already covered?", prompt)

    @patch("converter.services.generation.launch_worker")
    @patch("converter.services.generation.codex_executable", return_value="codex.exe")
    def test_resume_preserves_limit_counts_and_unused_budget(self, executable, launch):
        page4 = self.lecture.pages.get(number=4)
        page4.text, page4.warning = "A new distinct concept.", ""
        page4.save()
        run = GenerationRun.objects.create(
            lecture=self.lecture, page_numbers=[1, 2, 3, 4], card_limit=3
        )

        def generator(pages, _):
            if pages[0].number == 4:
                raise WorkflowError("Quota reached")
            return {"cards": self.payload["cards"][:1]}

        perform_run(run.pk, generator)
        run.refresh_from_db()
        self.assertEqual(run.completed_pages, [1, 2, 3])
        self.assertEqual(run.cards_added, 1)
        resume_generation(run)
        candidates = [
            {
                "page": 4,
                "front": f"New concept {i}?",
                "back": "A distinct concept.",
                "source_quote": page4.text,
            }
            for i in range(4)
        ]
        perform_run(run.pk, lambda *_: {"cards": candidates})
        run.refresh_from_db()
        self.assertEqual(
            (run.status, run.cards_added, run.card_limit, run.over_limit_count),
            ("completed", 3, 3, 2),
        )
        self.assertEqual(run.completed_pages, [1, 2, 3, 4])

    def test_low_limit_expands_context_instead_of_ignoring_later_pages(self):
        run = GenerationRun.objects.create(
            lecture=self.lecture, page_numbers=[1, 2, 3, 4], card_limit=1
        )
        visited = []

        def generator(pages, _):
            visited.extend(p.number for p in pages)
            return self.payload

        perform_run(run.pk, generator)
        run.refresh_from_db()
        self.assertEqual(visited, [1, 2, 3, 4])
        self.assertEqual(run.completed_pages, visited)
        self.assertEqual(run.cards_added, 1)

    def test_budget_reserves_room_for_the_last_short_batch(self):
        page4 = self.lecture.pages.get(number=4)
        page4.text, page4.warning = "A final important concept.", ""
        page4.save()
        run = GenerationRun.objects.create(
            lecture=self.lecture, page_numbers=[1, 2, 3, 4], card_limit=3
        )

        def generator(pages, _):
            if pages[0].number == 1:
                return self.payload
            return {
                "cards": [
                    {
                        "front": "What is the final concept?",
                        "back": page4.text,
                        "source_quote": page4.text,
                        "page": 4,
                    }
                ]
            }

        perform_run(run.pk, generator)
        run.refresh_from_db()
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.completed_pages, [1, 2, 3, 4])
        self.assertEqual(run.cards_added, 3)
        self.assertTrue(Card.objects.filter(page=page4).exists())

    def test_cleanup_is_reversible_and_preserves_accepted_and_edited_cards(self):
        page = self.lecture.pages.first()
        for front in ("How long is the exam?", "When is the exam?", "Where is the exam?"):
            add_drafts(self.lecture, [(page, front, "90 minutes.", "")])
        accepted = Card.objects.get(front="When is the exam?")
        accepted = update_card(accepted.pk, 1, accepted.front, accepted.back, "", "accepted")
        edited = Card.objects.get(front="Where is the exam?")
        update_card(edited.pk, 1, edited.front, "Edited answer", "", "draft")
        clean = Card.objects.get(front="How long is the exam?")
        url = reverse("filter_logistics", args=[self.lecture.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(Client(enforce_csrf_checks=True).post(url).status_code, 403)
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        clean.refresh_from_db()
        self.assertEqual(clean.status, "rejected")
        self.assertEqual(clean.revisions.get().status, "draft")
        self.assertEqual(Card.objects.get(pk=accepted.pk).status, "accepted")
        self.assertEqual(Card.objects.get(pk=edited.pk).back, "Edited answer")
        self.assertEqual(set_aside_logistics(self.lecture), 0)
        update_card(clean.pk, clean.version, clean.front, clean.back, "", "draft")
        self.assertEqual(set_aside_logistics(self.lecture), 0)

    @patch("converter.views.start_generation")
    def test_generation_and_download_validate_and_use_same_card_limit(self, start):
        url = reverse("generate", args=[self.lecture.pk])
        self.assertEqual(
            self.client.post(
                url, {"pages": [1, 2, 3], "consent": "yes", "card_limit": 0}
            ).status_code,
            400,
        )
        start.assert_not_called()
        self.assertEqual(
            self.client.post(
                url, {"pages": [1, 2, 3], "consent": "yes", "card_limit": 2}
            ).status_code,
            302,
        )
        self.assertEqual(start.call_args.kwargs["card_limit"], 2)
        download = self.client.post(
            reverse("prompt", args=[self.lecture.pk]), {"pages": [1, 2, 3], "card_limit": 2}
        )
        self.assertContains(download, "at most 2 cards TOTAL")

    def test_edited_question_duplicate_does_not_consume_budget(self):
        card = self.accepted_card()
        update_card(
            card.pk, card.version, "My revised question?", card.back, card.source_quote, "accepted"
        )
        run = GenerationRun.objects.create(lecture=self.lecture, page_numbers=[1], card_limit=1)
        item = {
            "front": "My revised question?",
            "back": card.back,
            "source_quote": card.source_quote,
            "page": 1,
        }
        perform_run(run.pk, lambda *_: {"cards": [item, {**item, "front": "A new question?"}]})
        run.refresh_from_db()
        self.assertEqual(run.cards_added, 1)
        self.assertTrue(Card.objects.filter(fingerprint=fingerprint("A new question?")).exists())

    def test_compact_backup_restores_limit_and_selection_counts(self):
        run = GenerationRun.objects.create(
            lecture=self.lecture,
            status="failed",
            page_numbers=[1, 2, 3],
            completed_pages=[1],
            card_limit=2,
            filtered_count=3,
            over_limit_count=4,
        )
        data = export_backup(self.lecture)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(json.loads(archive.read("manifest.json"))["version"], 9)
        Lecture.objects.all().delete()
        destination = Path(self.directory.name) / str(uuid.uuid4())
        destination.mkdir()
        with override_settings(MEDIA_ROOT=destination):
            restored = restore_backup(SimpleUploadedFile("backup.zip", data))
        restored_run = restored.runs.get(pk=run.pk)
        self.assertEqual(
            (restored_run.card_limit, restored_run.filtered_count, restored_run.over_limit_count),
            (2, 3, 4),
        )
