import copy
import io
import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from converter.models import Card, GenerationRun, Lecture
from converter.services.backups import export_backup, restore_backup
from converter.services.cards import add_drafts, update_card, validate_payload
from converter.services.documents import import_pdf
from converter.services.exporting import export_deck
from converter.services.files import WorkflowError
from converter.services.generation import perform_run

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"


class WorkflowFixture(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = TemporaryDirectory(dir=settings.WORK_DIR)
        root = Path(cls.directory.name)
        (root / "media").mkdir()
        (root / "work").mkdir()
        cls.overrides = override_settings(
            DATA_DIR=root,
            MEDIA_ROOT=root / "media",
            WORK_DIR=root / "work",
            CLI_PROFILE_ROOT=root / "cli-profiles",
            ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"],
        )
        cls.overrides.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.overrides.disable()
        cls.directory.cleanup()

    @classmethod
    def setUpTestData(cls):
        cls.lecture, _ = import_pdf(
            SimpleUploadedFile("lecture.pdf", (FIXTURES / "lecture.pdf").read_bytes()),
            "Study example",
        )
        cls.payload = json.loads((FIXTURES / "cards.json").read_text())

    def drafts(self):
        return add_drafts(
            self.lecture,
            validate_payload(self.payload, {p.number: p for p in self.lecture.pages.all()}),
        )

    def accepted_card(self):
        self.drafts()
        card = self.lecture.cards.first()
        return update_card(
            card.id, card.version, card.front, card.back, card.source_quote, "accepted"
        )

    def archive_db(self, data):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            db_file = Path(self.directory.name) / "inspect.anki2"
            db_file.write_bytes(archive.read("collection.anki2"))
            with closing(sqlite3.connect(db_file)) as db:
                notes = db.execute(
                    "select guid, mid, mod, flds from notes order by guid"
                ).fetchall()
                cards = db.execute("select nid, ord from cards").fetchall()
            media = json.loads(archive.read("media"))
            for index in media:
                self.assertTrue(archive.read(index).startswith(b"\x89PNG"))
        return notes, cards, media


class WorkflowTests(WorkflowFixture):
    def test_pdf_sources_and_unreadable_pages(self):
        pages = list(self.lecture.pages.all())
        self.assertEqual(len(pages), 4)
        self.assertIn("Retrieval practice means", pages[0].text)
        self.assertFalse(pages[0].warning)
        self.assertTrue(pages[3].warning)
        self.assertEqual(pages[3].text, "")
        for page in pages:
            self.assertTrue((Path(settings.MEDIA_ROOT) / page.image).is_file())

    def test_repeated_pdf_import_preserves_edits_and_identity(self):
        card = self.accepted_card()
        lecture, created = import_pdf(
            SimpleUploadedFile("renamed.pdf", (FIXTURES / "lecture.pdf").read_bytes())
        )
        self.assertFalse(created)
        self.assertEqual(lecture.id, self.lecture.id)
        self.assertEqual(lecture.cards.get(id=card.id).status, "accepted")

    def test_invalid_and_oversize_uploads_leave_no_record(self):
        before = Lecture.objects.count()
        with self.assertRaises(WorkflowError):
            import_pdf(SimpleUploadedFile("lecture.pdf", b"not a PDF"))
        with override_settings(MAX_PDF_BYTES=10), self.assertRaises(WorkflowError):
            import_pdf(SimpleUploadedFile("large.pdf", b"%PDF-" + b"0" * 20))
        self.assertEqual(Lecture.objects.count(), before)

    def test_generation_references_and_atomic_validation(self):
        pages = {p.number: p for p in self.lecture.pages.all()}
        for mutation in (
            {"page": 999},
            {"page": True},
            {"source_quote": "Invented supporting quote"},
            {"back": ""},
        ):
            payload = copy.deepcopy(self.payload)
            payload["cards"][-1].update(mutation)
            with self.assertRaises(WorkflowError):
                add_drafts(self.lecture, validate_payload(payload, pages))
            self.assertEqual(Card.objects.count(), 0)

    def test_regeneration_preserves_accepted_edits_and_revisions(self):
        card = self.accepted_card()
        changed = update_card(
            card.id,
            card.version,
            "My edited question?",
            "My edited answer",
            card.source_quote,
            "accepted",
        )
        self.assertEqual(self.drafts(), 0)
        changed.refresh_from_db()
        self.assertEqual(changed.front, "My edited question?")
        self.assertEqual(changed.revisions.count(), 2)
        self.assertEqual(changed.status, "accepted")

    def test_stale_editor_cannot_overwrite_newer_card(self):
        card = self.accepted_card()
        update_card(card.id, card.version, "New question?", card.back, card.source_quote, "draft")
        with self.assertRaises(WorkflowError):
            update_card(
                card.id, card.version, "Stale question?", card.back, card.source_quote, "accepted"
            )
        card.refresh_from_db()
        self.assertEqual(card.front, "New question?")

    def test_export_only_accepted_stable_guid_and_offline_media(self):
        card = self.accepted_card()
        first, cards, media = self.archive_db(export_deck(self.lecture))
        second, _, second_media = self.archive_db(export_deck(self.lecture))
        self.assertEqual(first, second)
        self.assertEqual(media, second_media)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(cards), 1)
        self.assertIn("Page 1", first[0][3])
        self.assertIn(next(iter(media.values())), first[0][3])
        update_card(
            card.id, card.version, "Changed question", card.back, card.source_quote, "accepted"
        )
        edited, _, _ = self.archive_db(export_deck(self.lecture))
        self.assertEqual(edited[0][0], first[0][0])
        self.assertNotEqual(edited[0][3], first[0][3])

    def test_export_escapes_content_and_rejects_empty_selection(self):
        with self.assertRaises(WorkflowError):
            export_deck(self.lecture)
        card = self.accepted_card()
        update_card(
            card.id,
            card.version,
            '<script>alert("x")</script>',
            "a < b & c",
            card.source_quote,
            "accepted",
        )
        notes, _, _ = self.archive_db(export_deck(self.lecture))
        self.assertNotIn("<script>", notes[0][3])
        self.assertIn("&lt;script&gt;", notes[0][3])

    def test_completed_batch_survives_later_provider_failure(self):
        run = GenerationRun.objects.create(lecture=self.lecture, page_numbers=[1, 2, 3, 4])

        def generator(pages, cancelled):
            if pages[0].number == 4:
                raise WorkflowError("Quota reached")
            return self.payload

        perform_run(run.id, generator)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.completed_pages, [1, 2, 3])
        self.assertEqual(Card.objects.count(), 5)
        self.assertEqual(run.error, "Quota reached")
        perform_run(run.id, generator)
        self.assertEqual(Card.objects.count(), 5)

    def test_cancelled_generation_does_not_import_late_output(self):
        run = GenerationRun.objects.create(lecture=self.lecture, page_numbers=[1, 2, 3])

        def generator(pages, cancelled):
            GenerationRun.objects.filter(pk=run.pk).update(status="cancelled")
            return self.payload

        perform_run(run.id, generator)
        self.assertEqual(Card.objects.count(), 0)
        self.assertEqual(GenerationRun.objects.get(pk=run.pk).status, "cancelled")

    def test_backup_restores_notes_history_media_and_identifiers(self):
        card = self.accepted_card()
        original_updated = card.updated_at
        data = export_backup(self.lecture)
        # Use a fresh database state and media location to simulate a new installation.
        Card.objects.all().delete()
        Lecture.objects.all().delete()
        destination = Path(self.directory.name) / "restored"
        destination.mkdir(exist_ok=True)
        with override_settings(MEDIA_ROOT=destination):
            restored = restore_backup(SimpleUploadedFile("backup.zip", data))
            restored_card = restored.cards.get(pk=card.pk)
            self.assertEqual(restored.id, self.lecture.id)
            self.assertEqual(restored_card.status, "accepted")
            self.assertEqual(restored_card.updated_at, original_updated)
            self.assertEqual(restored_card.revisions.count(), 1)
            self.assertTrue((destination / restored.original_file).is_file())
            self.assertEqual(len(self.archive_db(export_deck(restored))[0]), 1)
            with self.assertRaises(WorkflowError):
                restore_backup(SimpleUploadedFile("same.zip", data))

    def test_backup_rejects_traversal_and_corrupt_media(self):
        self.accepted_card()
        valid = export_backup(self.lecture)
        with zipfile.ZipFile(io.BytesIO(valid)) as source:
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w") as dest:
                for item in source.infolist():
                    dest.writestr(item.filename, source.read(item.filename))
                dest.writestr("../outside.txt", "bad")
        Card.objects.all().delete()
        Lecture.objects.all().delete()
        with self.assertRaisesRegex(WorkflowError, "unexpected or missing"):
            restore_backup(SimpleUploadedFile("bad.zip", output.getvalue()))
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(valid)) as source, zipfile.ZipFile(output, "w") as dest:
            for item in source.infolist():
                dest.writestr(
                    item.filename,
                    b"corrupt" if item.filename == "pages/1.png" else source.read(item.filename),
                )
        with self.assertRaisesRegex(WorkflowError, "integrity check"):
            restore_backup(SimpleUploadedFile("corrupt.zip", output.getvalue()))
        self.assertEqual(Lecture.objects.count(), 0)

    def test_failed_restore_rolls_back_and_preserves_existing_files(self):
        card = self.accepted_card()
        valid = export_backup(self.lecture)
        Card.objects.all().delete()
        Lecture.objects.all().delete()
        original_path = Path(settings.MEDIA_ROOT) / self.lecture.original_file
        with self.assertRaisesRegex(WorkflowError, "Source files with this identity"):
            restore_backup(SimpleUploadedFile("backup.zip", valid))
        self.assertTrue(original_path.exists())
        self.assertEqual(Lecture.objects.count(), 0)
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(valid)) as source, zipfile.ZipFile(output, "w") as dest:
            for item in source.infolist():
                content = source.read(item.filename)
                if item.filename == "manifest.json":
                    manifest = json.loads(content)
                    manifest["cards"][0]["revisions"][0]["card_id"] = str(card.pk)
                    content = json.dumps(manifest).encode()
                dest.writestr(item.filename, content)
        destination = Path(self.directory.name) / "invalid-restore"
        destination.mkdir()
        with (
            override_settings(MEDIA_ROOT=destination),
            self.assertRaisesRegex(WorkflowError, "record structure"),
        ):
            restore_backup(SimpleUploadedFile("invalid.zip", output.getvalue()))
        self.assertEqual(Lecture.objects.count(), 0)
        self.assertEqual(list(destination.iterdir()), [])

    def test_browser_flow_and_edit_validation(self):
        self.drafts()
        card = self.lecture.cards.first()
        response = self.client.get(self.lecture.get_absolute_url())
        self.assertContains(response, card.front)
        self.assertContains(response, "Some pages need manual attention")
        image_response = self.client.get(reverse("page_image", args=[card.page_id]))
        self.assertEqual(image_response.status_code, 200)
        image_response.close()
        response = self.client.post(
            reverse("save_card", args=[card.pk]),
            {
                "version": card.version,
                "front": "Edited in browser?",
                "back": card.back,
                "source_quote": card.source_quote,
                "status": "draft",
                "action": "accept_next",
            },
        )
        self.assertEqual(response.status_code, 302)
        card.refresh_from_db()
        self.assertEqual(card.status, "accepted")
        self.assertEqual(
            self.client.get(reverse("export", args=[self.lecture.pk])).status_code, 200
        )
        self.assertEqual(
            self.client.get(reverse("backup", args=[self.lecture.pk])).status_code, 200
        )

    def test_csrf_and_local_only_access(self):
        protected = Client(enforce_csrf_checks=True)
        self.assertEqual(protected.post(reverse("demo")).status_code, 403)
        self.assertEqual(self.client.get("/", REMOTE_ADDR="192.0.2.5").status_code, 403)
        self.assertEqual(self.client.get("/", HTTP_HOST="attacker.example").status_code, 400)

    @patch("converter.views.start_generation")
    def test_generation_requires_explicit_data_consent(self, start):
        response = self.client.post(reverse("generate", args=[self.lecture.pk]), {"pages": [1]})
        self.assertEqual(response.status_code, 400)
        start.assert_not_called()
        response = self.client.post(
            reverse("generate", args=[self.lecture.pk]), {"pages": [1], "consent": "yes"}
        )
        self.assertEqual(response.status_code, 302)
        start.assert_called_once()
