import copy
import io
import json
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse

from converter.models import Card, GenerationRun, Lecture
from converter.services.backups import export_backup, restore_backup
from converter.services.files import WorkflowError
from converter.services.generation import perform_run, resume_generation

from .test_workflow import WorkflowFixture


class GenerationRecoveryTests(WorkflowFixture):
    def failed_run(self):
        return GenerationRun.objects.create(
            lecture=self.lecture,
            status="failed",
            page_numbers=[1, 2, 3],
            completed_pages=[1],
            cards_added=2,
            error="The source excerpt is not present on page 2.",
        )

    def bad_payload(self):
        item = copy.deepcopy(self.payload["cards"][0])
        item.update(front="<script>Bad question</script>", source_quote="Invented supporting quote")
        return {"cards": [item]}

    def test_bad_drafts_are_reported_without_losing_good_cards_or_later_batches(self):
        run = GenerationRun.objects.create(lecture=self.lecture, page_numbers=[1, 2, 3, 4])
        page4 = self.lecture.pages.get(number=4)
        page4.text = "Sleep supports memory consolidation."
        page4.save()
        visited = []

        def generator(pages, cancelled):
            visited.append([p.number for p in pages])
            if pages[0].number == 4:
                return {
                    "cards": [
                        {
                            "front": "What supports consolidation?",
                            "back": "Sleep.",
                            "page": 4,
                            "source_quote": page4.text,
                        }
                    ]
                }
            return {
                "cards": self.payload["cards"]
                + self.bad_payload()["cards"]
                + [{**self.payload["cards"][0], "page": 999}, "malformed card"]
            }

        perform_run(run.pk, generator)
        run.refresh_from_db()
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.completed_pages, [1, 2, 3, 4])
        self.assertEqual(visited, [[1, 2, 3], [4]])
        self.assertEqual(run.cards_added, 6)
        self.assertEqual(Card.objects.count(), 6)
        self.assertEqual(len(run.issues), 3)
        self.assertEqual(run.issues[0]["page"], 1)
        self.assertEqual(run.issues[0]["source_quote"], "Invented supporting quote")
        self.assertEqual(run.issues[1]["page"], None)
        self.assertEqual(run.issues[1]["batch_pages"], [1, 2, 3])
        self.assertFalse(Card.objects.filter(front__contains="Bad question").exists())
        response = self.client.get(self.lecture.get_absolute_url())
        self.assertContains(response, "3 skipped drafts")
        self.assertContains(response, "View source page 1")
        self.assertContains(response, "&lt;script&gt;Bad question&lt;/script&gt;")
        self.assertNotContains(response, "<script>Bad question</script>")
        self.assertEqual(self.client.get(reverse("run_status", args=[run.pk])).json()["issues"], 3)

    def test_all_invalid_batch_continues_but_malformed_envelope_fails(self):
        run = GenerationRun.objects.create(lecture=self.lecture, page_numbers=[1, 2, 3, 4])
        perform_run(
            run.pk, lambda pages, _: self.bad_payload() if pages[0].number == 1 else {"cards": []}
        )
        run.refresh_from_db()
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.completed_pages, [1, 2, 3, 4])
        self.assertEqual(len(run.issues), 1)
        self.assertEqual(Card.objects.count(), 0)
        malformed = GenerationRun.objects.create(lecture=self.lecture, page_numbers=[1])
        perform_run(malformed.pk, lambda *_: {"wrong_key": []})
        malformed.refresh_from_db()
        self.assertEqual(malformed.status, "failed")
        self.assertEqual(malformed.completed_pages, [])
        self.assertIn('"cards" array', malformed.error)

    @patch("converter.services.generation.launch_worker")
    @patch("converter.services.generation.codex_executable", return_value="codex.exe")
    def test_resume_skips_saved_pages_is_idempotent_and_preserves_edits(self, executable, launch):
        card = self.accepted_card()
        snapshot = (card.id, card.front, card.status, card.version, card.anki_modified)
        run = self.failed_run()
        original_token = run.worker_token
        response = self.client.get(self.lecture.get_absolute_url())
        self.assertContains(response, "Resume 2 remaining pages")
        url = reverse("resume_run", args=[run.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(Client(enforce_csrf_checks=True).post(url).status_code, 403)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(self.client.post(url).status_code, 302)
        launch.assert_called_once()
        run.refresh_from_db()
        self.assertNotEqual(run.worker_token, original_token)
        self.assertEqual(run.error, "")
        visited = []

        def generator(pages, _):
            visited.extend(p.number for p in pages)
            return {"cards": [c for c in self.payload["cards"] if c["page"] in visited]}

        perform_run(run.pk, generator)
        run.refresh_from_db()
        card.refresh_from_db()
        self.assertEqual(visited, [2, 3])
        self.assertEqual(run.completed_pages, [1, 2, 3])
        self.assertEqual(run.cards_added, 2)  # All remaining questions already existed.
        self.assertEqual(Card.objects.count(), 5)
        self.assertEqual(
            (card.id, card.front, card.status, card.version, card.anki_modified), snapshot
        )
        self.assertEqual(self.client.post(url).status_code, 400)

    @patch("converter.services.generation.launch_worker")
    @patch("converter.services.generation.codex_executable", return_value="codex.exe")
    def test_cancel_then_resume_rejects_output_and_errors_from_old_worker(self, executable, launch):
        for late_error in (False, True):
            with self.subTest(late_error=late_error):
                run = GenerationRun.objects.create(lecture=self.lecture, page_numbers=[1, 2, 3])
                old_token = run.worker_token

                def generator(pages, cancelled):
                    GenerationRun.objects.filter(pk=run.pk).update(status="cancelled")
                    resume_generation(run)
                    self.assertTrue(cancelled())
                    if late_error:
                        raise WorkflowError("Old worker failed")
                    return self.payload

                perform_run(run.pk, generator, worker_token=old_token)
                run.refresh_from_db()
                self.assertEqual(run.status, "queued")
                self.assertEqual(run.completed_pages, [])
                self.assertEqual(run.error, "")
                self.assertEqual(Card.objects.count(), 0)
                with patch("converter.services.generation.codex_generate") as provider:
                    perform_run(run.pk, provider, worker_token=old_token)
                    provider.assert_not_called()
                perform_run(run.pk, lambda *_: self.payload, worker_token=run.worker_token)
                self.assertEqual(Card.objects.count(), 5)
                Card.objects.all().delete()

    @patch("converter.services.generation.launch_worker")
    @patch("converter.services.generation.codex_executable", return_value="codex.exe")
    def test_resume_refuses_other_active_run(self, executable, launch):
        run = self.failed_run()
        GenerationRun.objects.create(lecture=self.lecture, page_numbers=[2])
        with self.assertRaisesRegex(WorkflowError, "already has a generation"):
            resume_generation(run)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.completed_pages, [1])
        launch.assert_not_called()

    @patch("converter.services.generation.subprocess.Popen", side_effect=OSError("start failed"))
    @patch("converter.services.generation.codex_executable", return_value="codex.exe")
    def test_resume_worker_start_failure_preserves_progress(self, executable, popen):
        card = self.accepted_card()
        run = self.failed_run()
        with self.assertRaisesRegex(WorkflowError, "Could not start generation"):
            resume_generation(run)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.completed_pages, [1])
        self.assertEqual(run.cards_added, 2)
        self.assertTrue(Card.objects.filter(pk=card.pk, status="accepted").exists())

    def test_backup_roundtrip_keeps_issues_and_restores_legacy_version(self):
        run = GenerationRun.objects.create(lecture=self.lecture, page_numbers=[1, 2, 3])
        perform_run(run.pk, lambda *_: self.bad_payload())
        run.refresh_from_db()
        data = export_backup(self.lecture)
        for version in (5, 4, 3, 2, 1):
            with self.subTest(version=version):
                output = io.BytesIO()
                with (
                    zipfile.ZipFile(io.BytesIO(data)) as source,
                    zipfile.ZipFile(output, "w") as dest,
                ):
                    for name in source.namelist():
                        contents = source.read(name)
                        if name == "manifest.json":
                            manifest = json.loads(contents)
                            manifest["version"] = version
                            self.assertNotIn("worker_token", manifest["runs"][0])
                            if version < 5:
                                for record in manifest["runs"]:
                                    for key in (
                                        "study_cards_added",
                                        "learning_focus",
                                        "card_format",
                                    ):
                                        record.pop(key)
                                for record in manifest["cards"]:
                                    record.pop("note_type")
                                    for revision in record["revisions"]:
                                        revision.pop("note_type")
                            if version < 4:
                                for record in manifest["runs"]:
                                    record.pop("reasoning_effort")
                            if version < 3:
                                for record in manifest["runs"]:
                                    for key in ("card_limit", "filtered_count", "over_limit_count"):
                                        record.pop(key)
                            if version == 1:
                                for record in manifest["runs"]:
                                    record.pop("issues")
                            contents = json.dumps(manifest).encode()
                        dest.writestr(name, contents)
                Card.objects.all().delete()
                Lecture.objects.all().delete()
                destination = Path(self.directory.name) / str(uuid.uuid4())
                destination.mkdir()
                with override_settings(MEDIA_ROOT=destination):
                    restored = restore_backup(SimpleUploadedFile("backup.zip", output.getvalue()))
                restored_run = restored.runs.get(pk=run.pk)
                self.assertEqual(restored_run.issues, run.issues if version >= 2 else [])
                self.assertEqual(restored_run.reasoning_effort, "")
                self.assertEqual(restored_run.completed_pages, [1, 2, 3])
                self.assertEqual(Card.objects.count(), 0)

    def test_json_import_still_rejects_the_whole_file(self):
        payload = {"cards": self.payload["cards"] + self.bad_payload()["cards"]}
        response = self.client.post(
            reverse("import_cards", args=[self.lecture.pk]),
            {"cards": SimpleUploadedFile("cards.json", json.dumps(payload).encode())},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Card.objects.count(), 0)
        self.assertEqual(GenerationRun.objects.count(), 0)
