import io
import json
import uuid
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, override_settings
from django.urls import reverse

from converter.models import Card, GenerationRun, Lecture
from converter.services.backups import export_backup, restore_backup
from converter.services.cards import (
    add_drafts,
    update_card,
    validate_generated_batch,
    validate_payload,
)
from converter.services.exporting import export_deck
from converter.services.files import WorkflowError
from converter.services.generation import (
    codex_generate,
    perform_run,
    prompt_for,
    resume_generation,
    start_generation,
)
from converter.services.note_types import (
    CARD_FORMATS,
    LEARNING_FOCUSES,
    study_card_count,
    study_previews,
)
from tests.test_workflow import WorkflowFixture

CLOZE_TEXT = (
    "Retrieval practice means trying to {{c1::recall}} information from {{c2::memory::where?}}."
)


class ClozeParsingTests(SimpleTestCase):
    def test_grouped_blanks_and_nonconsecutive_numbers_match_anki_ordinals(self):
        text = "{{c1::First}} and {{c1::second}} versus {{c7::third::hint}}."
        self.assertEqual(study_card_count(text, "cloze"), 2)
        previews = study_previews(text, "Extra", "cloze")
        self.assertEqual([p["number"] for p in previews], [1, 7])
        self.assertEqual(previews[0]["question"].count("[...]"), 2)
        self.assertNotIn("First", previews[0]["question"])
        self.assertIn("First", previews[1]["question"])
        self.assertIn("[hint]", previews[1]["question"])
        self.assertNotIn("third", previews[1]["question"])
        self.assertIn("third", previews[1]["answer"])
        self.assertEqual(study_card_count(text, "basic"), 1)

    def test_malformed_nested_or_unsupported_clozes_are_rejected(self):
        for text in (
            "No blank",
            "{{c0::zero}}",
            "{{c21::too high}}",
            "{{c1::}}",
            "{{c1::   }}",
            "{{c1::unfinished}",
            "{{c1::one {{c2::two}}}}",
            "{{c01::zero prefix}}",
            "{{c1::a::b::c}}",
            "{{c1::good}} {{cX::bad}}",
        ):
            with self.subTest(text=text), self.assertRaises(WorkflowError):
                study_card_count(text, "cloze")

    def test_preview_escapes_every_untrusted_field(self):
        text = "<script>x()</script> {{c1::<img src=x onerror=x()>::<b>hint</b>}}"
        preview = study_previews(text, '<svg onload="x()">', "cloze")[0]
        self.assertIn("&lt;script&gt;", preview["question"])
        self.assertIn("&lt;b&gt;hint", preview["question"])
        self.assertIn("&lt;img", preview["answer"])
        self.assertNotIn("<script>", str(preview))
        self.assertNotIn("<img", str(preview))
        self.assertNotIn("<svg", str(preview))


class ClozeWorkflowTests(WorkflowFixture):
    def candidate(self, front=CLOZE_TEXT):
        return {**self.payload["cards"][0], "note_type": "cloze", "front": front, "back": ""}

    def cloze_note(self):
        validated = validate_payload(
            {"cards": [self.candidate()]}, {p.number: p for p in self.lecture.pages.all()}
        )
        add_drafts(self.lecture, validated)
        return self.lecture.cards.get(note_type="cloze")

    def test_legacy_json_and_cloze_import_are_supported_and_atomic(self):
        url = reverse("import_cards", args=[self.lecture.pk])
        payload = {"cards": [self.payload["cards"][0], self.candidate()]}
        response = self.client.post(
            url, {"cards": SimpleUploadedFile("cards.json", json.dumps(payload).encode())}
        )
        self.assertEqual(response.status_code, 302)
        run = self.lecture.runs.get()
        self.assertEqual((run.cards_added, run.study_cards_added), (2, 3))
        payload["cards"].append(self.candidate("{{c1::broken"))
        response = self.client.post(
            url, {"cards": SimpleUploadedFile("cards.json", json.dumps(payload).encode())}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.lecture.cards.count(), 2)
        self.assertEqual(self.lecture.runs.count(), 1)

    def test_wrong_format_and_wrong_source_are_visible_skipped_candidates(self):
        pages = {p.number: p for p in self.lecture.pages.all()}
        candidate = self.candidate()
        good, issues = validate_generated_batch({"cards": [candidate]}, pages, card_format="basic")
        self.assertEqual(len(good), 0)
        self.assertIn("requested basic", issues[0]["reason"])
        candidate["source_quote"] = "This text is not on the source page."
        good, issues = validate_generated_batch({"cards": [candidate]}, pages, card_format="cloze")
        self.assertFalse(good)
        self.assertIn("excerpt is not present", issues[0]["reason"])

    def test_card_budget_counts_cloze_siblings_and_continues_with_smaller_candidates(self):
        run = GenerationRun.objects.create(
            lecture=self.lecture, page_numbers=[1, 2, 3], card_format="mixed", card_limit=3
        )
        candidates = [
            self.candidate(),
            self.candidate("Another {{c1::idea}} with {{c2::two}} blanks."),
            self.payload["cards"][1],
        ]
        perform_run(run.pk, lambda *_: {"cards": candidates})
        run.refresh_from_db()
        self.assertEqual(
            (run.status, run.cards_added, run.study_cards_added, run.over_limit_count),
            ("completed", 2, 3, 1),
        )
        self.assertEqual(sum(c.study_card_count for c in self.lecture.cards.all()), 3)

    def test_cloze_logistics_are_filtered_before_becoming_drafts(self):
        run = GenerationRun.objects.create(
            lecture=self.lecture, page_numbers=[1], card_format="cloze", card_limit=3
        )
        perform_run(
            run.pk,
            lambda *_: {
                "cards": [self.candidate("Exam duration is {{c1::90 minutes}}."), self.candidate()]
            },
        )
        run.refresh_from_db()
        self.assertEqual((run.filtered_count, run.cards_added, run.study_cards_added), (1, 1, 2))

    def test_cloze_deduplication_ignores_numbering_and_keeps_existing_edits(self):
        card = self.cloze_note()
        card = update_card(
            card.pk, card.version, card.front, "My explanation", card.source_quote, "accepted"
        )
        run = GenerationRun.objects.create(
            lecture=self.lecture, page_numbers=[1], card_format="cloze", card_limit=5
        )
        perform_run(run.pk, lambda *_: {"cards": [self.candidate(CLOZE_TEXT.replace("c2", "c1"))]})
        run.refresh_from_db()
        self.assertEqual((run.cards_added, run.study_cards_added), (0, 0))
        card.refresh_from_db()
        self.assertEqual(
            (card.back, card.status, card.study_card_count), ("My explanation", "accepted", 2)
        )

    def test_edits_keep_note_type_cloze_ordinals_revision_and_stable_export_guid(self):
        card = self.cloze_note()
        card = update_card(card.pk, card.version, card.front, "", card.source_quote, "accepted")
        before = self.archive_db(export_deck(self.lecture))[0][0]
        changed = card.front.replace("recall", "retrieve")
        response = self.client.post(
            reverse("save_card", args=[card.pk]),
            {
                "version": card.version,
                "front": changed,
                "back": "",
                "source_quote": card.source_quote,
                "status": "accepted",
                "note_type": "basic",
            },
        )
        self.assertEqual(response.status_code, 302)
        card.refresh_from_db()
        self.assertEqual(card.note_type, "cloze")
        self.assertEqual(card.revisions.last().front, CLOZE_TEXT)
        self.assertEqual(card.revisions.last().note_type, "cloze")
        after = self.archive_db(export_deck(self.lecture))[0][0]
        self.assertEqual(before[:2], after[:2])
        self.assertGreater(after[2], before[2])
        with self.assertRaises(WorkflowError):
            update_card(
                card.pk,
                card.version,
                changed.replace("c2", "c1"),
                "",
                card.source_quote,
                "accepted",
            )
        with self.assertRaises(WorkflowError):
            update_card(card.pk, card.version - 1, changed, "", card.source_quote, "accepted")

    def test_preview_does_not_save_or_generate_and_export_preview_excludes_drafts(self):
        card = self.cloze_note()
        url = reverse("preview_note", args=[self.lecture.pk])
        with patch("converter.services.generation.subprocess.Popen") as process:
            response = self.client.post(
                url, {"front": CLOZE_TEXT, "back": "", "note_type": "cloze"}
            )
            self.assertEqual(response.json()["study_cards"], 2)
            process.assert_not_called()
        card.refresh_from_db()
        self.assertEqual((card.version, card.status), (1, "draft"))
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(Client(enforce_csrf_checks=True).post(url).status_code, 403)
        self.assertEqual(self.client.post(url, REMOTE_ADDR="203.0.113.1").status_code, 403)
        preview = reverse("preview_export", args=[self.lecture.pk])
        self.assertContains(self.client.get(preview), "0 review cards from 0 accepted notes")
        update_card(card.pk, card.version, card.front, "", card.source_quote, "accepted")
        self.assertContains(self.client.get(preview), "2 review cards from 1 accepted note")
        self.assertContains(self.client.get(self.lecture.get_absolute_url()), "Export 2 to Anki")

    def test_backup_preserves_clozes_revisions_and_generation_settings(self):
        card = self.cloze_note()
        card = update_card(card.pk, card.version, card.front, "", card.source_quote, "accepted")
        run = GenerationRun.objects.create(
            lecture=self.lecture,
            status="completed",
            learning_focus="application",
            card_format="cloze",
            cards_added=1,
            study_cards_added=2,
            card_limit=4,
        )
        data = export_backup(self.lecture)
        Card.objects.all().delete()
        Lecture.objects.all().delete()
        destination = Path(self.directory.name) / str(uuid.uuid4())
        destination.mkdir()
        with override_settings(MEDIA_ROOT=destination):
            restored = restore_backup(SimpleUploadedFile("backup.zip", data))
            saved = restored.cards.get(pk=card.pk)
            self.assertEqual(
                (saved.note_type, saved.front, saved.back, saved.study_card_count),
                ("cloze", CLOZE_TEXT, "", 2),
            )
            self.assertEqual(saved.revisions.get().note_type, "cloze")
            self.assertEqual(len(self.archive_db(export_deck(restored))[1]), 2)
            restored_run = restored.runs.get(pk=run.pk)
            self.assertEqual(
                (
                    restored_run.learning_focus,
                    restored_run.card_format,
                    restored_run.study_cards_added,
                ),
                ("application", "cloze", 2),
            )

    def test_invalid_cloze_backup_rolls_back_without_partial_restore(self):
        self.cloze_note()
        data = export_backup(self.lecture)
        Card.objects.all().delete()
        Lecture.objects.all().delete()
        output = io.BytesIO()
        with (
            zipfile.ZipFile(io.BytesIO(data)) as source,
            zipfile.ZipFile(output, "w") as destination,
        ):
            for name in source.namelist():
                content = source.read(name)
                if name == "manifest.json":
                    manifest = json.loads(content)
                    manifest["cards"][0]["front"] = "{{c0::invalid}}"
                    content = json.dumps(manifest).encode()
                destination.writestr(name, content)
        folder = Path(self.directory.name) / str(uuid.uuid4())
        folder.mkdir()
        with override_settings(MEDIA_ROOT=folder), self.assertRaises(WorkflowError):
            restore_backup(SimpleUploadedFile("invalid.zip", output.getvalue()))
        self.assertFalse(Lecture.objects.exists())
        self.assertFalse(Card.objects.exists())
        self.assertEqual(list(folder.iterdir()), [])


class LearningFocusTests(WorkflowFixture):
    @patch("converter.views.start_generation")
    def test_each_focus_and_format_reaches_download_and_generation(self, start):
        for focus, label in LEARNING_FOCUSES:
            for card_format, _ in CARD_FORMATS:
                values = {
                    "pages": [1],
                    "consent": "yes",
                    "learning_focus": focus,
                    "card_format": card_format,
                    "card_limit": 3,
                }
                response = self.client.post(reverse("prompt", args=[self.lecture.pk]), values)
                self.assertEqual(response.status_code, 200)
                self.assertIn(f"LEARNING FOCUS: {label}", response.content.decode())
                self.assertIn(f"CARD FORMAT: {card_format}", response.content.decode())
                self.assertEqual(
                    self.client.post(
                        reverse("generate", args=[self.lecture.pk]), values
                    ).status_code,
                    302,
                )
                self.assertEqual(start.call_args.kwargs["learning_focus"], focus)
                self.assertEqual(start.call_args.kwargs["card_format"], card_format)
        start.reset_mock()
        for field in ("learning_focus", "card_format"):
            response = self.client.post(
                reverse("generate", args=[self.lecture.pk]),
                {"pages": [1], "consent": "yes", field: "untrusted instructions"},
            )
            self.assertEqual(response.status_code, 400)
        start.assert_not_called()

    @patch("converter.services.generation.codex_executable", return_value="codex.exe")
    @patch("converter.services.generation.subprocess.Popen")
    def test_real_provider_boundary_uses_typed_schema_and_selected_prompt(
        self, process, executable
    ):
        def finish(command, **kwargs):
            self.assertEqual(
                json.loads(Path(command[command.index("--output-schema") + 1]).read_text())[
                    "properties"
                ]["cards"]["items"]["properties"]["note_type"]["enum"],
                ["basic", "cloze"],
            )
            content = kwargs["stdin"].read().decode()
            self.assertIn("LEARNING FOCUS: Understanding", content)
            self.assertIn("CARD FORMAT: cloze", content)
            Path(command[command.index("--output-last-message") + 1]).write_text('{"cards": []}')
            return Mock(returncode=0, poll=Mock(return_value=0))

        process.side_effect = finish
        codex_generate(
            list(self.lecture.pages.all()), learning_focus="understanding", card_format="cloze"
        )
        with self.assertRaises(WorkflowError):
            codex_generate([], learning_focus="unsupported")
        self.assertEqual(process.call_count, 1)

    @patch("converter.services.generation.launch_worker")
    @patch("converter.services.generation.codex_executable", return_value="codex.exe")
    @patch("converter.services.generation.codex_generate")
    def test_resume_keeps_focus_format_and_consumed_review_card_budget(
        self, provider, executable, launch
    ):
        page4 = self.lecture.pages.get(number=4)
        page4.text, page4.warning = "A final concept.", ""
        page4.save()
        run = start_generation(
            self.lecture, [1, 2, 3, 4], 4, learning_focus="understanding", card_format="mixed"
        )
        provider.side_effect = [
            {
                "cards": [
                    {
                        **self.payload["cards"][0],
                        "front": CLOZE_TEXT,
                        "note_type": "cloze",
                        "back": "",
                    }
                ]
            },
            WorkflowError("Quota"),
        ]
        perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual((run.status, run.cards_added, run.study_cards_added), ("failed", 1, 2))
        resume_generation(run)
        provider.side_effect = None
        provider.return_value = {
            "cards": [
                {
                    "front": "A {{c1::final}} {{c2::concept}}.",
                    "back": "",
                    "note_type": "cloze",
                    "source_quote": page4.text,
                    "page": 4,
                }
            ]
        }
        perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual((run.status, run.cards_added, run.study_cards_added), ("completed", 2, 4))
        self.assertEqual(provider.call_args.kwargs["card_limit"], 2)
        self.assertEqual(provider.call_args.kwargs["learning_focus"], "understanding")
        self.assertEqual(provider.call_args.kwargs["card_format"], "mixed")
        response = self.client.get(self.lecture.get_absolute_url())
        self.assertContains(response, 'value="understanding" selected')
        self.assertContains(response, 'value="mixed" selected')
        self.assertIn("Do not invent exercises", prompt_for([page4], learning_focus="application"))
