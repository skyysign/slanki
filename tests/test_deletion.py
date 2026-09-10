import json
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client
from django.urls import reverse

from converter.models import Card, CardRevision, GenerationRun, Lecture, Page, PendingFileDeletion
from converter.services.backups import export_backup, restore_backup
from converter.services.deletion import cleanup_deleted_files, delete_lecture
from converter.services.documents import import_pdf
from converter.services.files import WorkflowError
from converter.services.generation import perform_run

from .test_workflow import FIXTURES, WorkflowFixture


class SetDeletionTests(WorkflowFixture):
    @classmethod
    def setUpTestData(cls):
        pass  # Each test needs independent files: filesystem deletion is not rolled back.

    def setUp(self):
        self.lecture, _ = self.import_sample()
        self.payload = json.loads((FIXTURES / "cards.json").read_text())
        self.folder = Path(settings.MEDIA_ROOT) / "documents" / str(self.lecture.pk)

    def import_sample(self):
        return import_pdf(
            SimpleUploadedFile("lecture.pdf", (FIXTURES / "lecture.pdf").read_bytes())
        )

    def test_confirmed_delete_removes_owned_records_and_files_and_allows_fresh_import(self):
        card = self.accepted_card()
        original_id = self.lecture.pk
        outside = Path(settings.MEDIA_ROOT) / "keep-original.pdf"
        outside.write_bytes(b"User's original outside the managed set directory")
        backup = Path(settings.MEDIA_ROOT) / "keep-backup.zip"
        backup.write_bytes(export_backup(self.lecture))
        other = Lecture.objects.create(title="Other set", sha256="a" * 64)
        other_folder = Path(settings.MEDIA_ROOT) / "documents" / str(other.pk)
        other_folder.mkdir()
        other_file = other_folder / "keep.png"
        other_file.write_bytes(b"Separate set")
        # Deletion must not trust a stored path to select a different directory.
        Lecture.objects.filter(pk=original_id).update(original_file="keep-original.pdf")
        url = reverse("delete_set", args=[original_id])
        self.assertContains(
            self.client.get(reverse("confirm_delete", args=[original_id])), "Save backup first"
        )
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(
            Client(enforce_csrf_checks=True).post(url, {"confirm": "yes"}).status_code, 403
        )
        self.assertEqual(self.client.post(url).status_code, 400)
        self.assertTrue(Card.objects.filter(pk=card.pk).exists())
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post(url, {"confirm": "yes"}).status_code, 302)
        self.assertFalse(Lecture.objects.filter(pk=original_id).exists())
        self.assertFalse(Card.objects.exists())
        self.assertFalse(CardRevision.objects.exists())
        self.assertFalse(Page.objects.filter(lecture_id=original_id).exists())
        self.assertFalse(self.folder.exists())
        self.assertFalse(PendingFileDeletion.objects.exists())
        self.assertTrue(outside.exists() and backup.exists() and other_file.exists())
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post(url, {"confirm": "yes"}).status_code, 302)
        fresh, created = self.import_sample()
        self.assertTrue(created)
        self.assertNotEqual(fresh.pk, original_id)
        self.assertEqual(fresh.cards.count(), 0)
        self.assertTrue((Path(settings.MEDIA_ROOT) / fresh.original_file).is_file())

    def test_rollback_preserves_notes_runs_and_files(self):
        card = self.accepted_card()
        run = GenerationRun.objects.create(lecture=self.lecture, page_numbers=[1])
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(RuntimeError), transaction.atomic():
                delete_lecture(self.lecture.pk)
                raise RuntimeError("Transaction rolled back")
        self.assertEqual(callbacks, [])
        card.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(run.status, "queued")
        self.assertEqual(card.status, "accepted")
        self.assertTrue(self.folder.exists())
        self.assertFalse(PendingFileDeletion.objects.exists())

    def test_locked_files_can_be_retried_without_affecting_reuploaded_set(self):
        data = export_backup(self.lecture)
        with (
            patch("converter.services.deletion.shutil.rmtree", side_effect=PermissionError),
            self.captureOnCommitCallbacks(execute=True),
        ):
            delete_lecture(self.lecture.pk)
        self.assertFalse(Lecture.objects.exists())
        self.assertTrue(PendingFileDeletion.objects.filter(pk=self.lecture.pk).exists())
        self.assertTrue(self.folder.exists())
        self.assertContains(self.client.get("/"), "Retry file cleanup")
        with self.assertRaisesMessage(WorkflowError, "pending file cleanup"):
            restore_backup(SimpleUploadedFile("backup.zip", data))
        fresh, created = self.import_sample()
        self.assertTrue(created)
        retry = reverse("retry_file_deletion", args=[self.lecture.pk])
        self.assertEqual(self.client.get(retry).status_code, 405)
        self.assertEqual(Client(enforce_csrf_checks=True).post(retry).status_code, 403)
        self.assertRedirects(self.client.post(retry), "/?cleanup=done")
        self.assertFalse(self.folder.exists())
        self.assertTrue((Path(settings.MEDIA_ROOT) / fresh.original_file).is_file())
        self.assertFalse(PendingFileDeletion.objects.exists())

    def test_cleanup_never_removes_an_existing_lecture_or_redirected_folder(self):
        PendingFileDeletion.objects.create(pk=self.lecture.pk, title="Unexpected stale marker")
        self.assertFalse(cleanup_deleted_files(self.lecture.pk))
        self.assertTrue(self.folder.exists())
        pending_id = uuid.uuid4()
        PendingFileDeletion.objects.create(pk=pending_id, title="Redirected directory")
        original_resolve = Path.resolve
        target = Path(settings.MEDIA_ROOT) / "documents" / str(pending_id)

        def resolve(path, *args, **kwargs):
            if path == target:
                return Path(settings.MEDIA_ROOT) / "unrelated"
            return original_resolve(path, *args, **kwargs)

        with (
            patch.object(Path, "resolve", resolve),
            patch("converter.services.deletion.shutil.rmtree") as remove,
        ):
            self.assertFalse(cleanup_deleted_files(pending_id))
            remove.assert_not_called()
        self.assertTrue(PendingFileDeletion.objects.filter(pk=pending_id).exists())

    def test_delete_during_generation_discards_late_output_and_worker_retries(self):
        run = GenerationRun.objects.create(lecture=self.lecture, page_numbers=[1, 2, 3])

        def generator(pages, cancelled):
            delete_lecture(self.lecture.pk)
            self.assertTrue(cancelled())
            return self.payload

        with self.captureOnCommitCallbacks(execute=True):
            perform_run(run.pk, generator, worker_token=run.worker_token)
        self.assertFalse(GenerationRun.objects.exists())
        self.assertFalse(Card.objects.exists())
        self.assertFalse(Lecture.objects.exists())
        self.assertFalse(self.folder.exists())
        provider = Mock()
        perform_run(run.pk, provider, worker_token=run.worker_token)
        perform_run(run.pk, provider)
        provider.assert_not_called()
