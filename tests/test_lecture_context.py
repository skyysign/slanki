import copy
import io
import json
import uuid
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from converter.models import Card, GenerationRun, Lecture
from converter.services.backups import export_backup, restore_backup
from converter.services.cards import update_card
from converter.services.files import WorkflowError
from converter.services.generation import (
    claude_generate,
    codex_generate,
    generation_request,
    perform_run,
    prompt_for,
    resume_generation,
)
from converter.services.lecture_context import (
    OVERVIEW_SCHEMA,
    checked_context,
    context_progress,
    context_sections,
)

from .test_workflow import WorkflowFixture


class LectureContextTests(WorkflowFixture):
    def topic(self, page):
        return {
            "title": f"Topic {page.number}",
            "summary": page.text[:100],
            "priority": "core",
            "page": page.number,
            "source_quote": page.text[:60],
        }

    def run_record(self, pages=None):
        return GenerationRun.objects.create(
            lecture=self.lecture, page_numbers=pages or [1], card_limit=3, context_enabled=True
        )

    def resume(self, run):
        with (
            patch("converter.services.generation.checked_model_settings"),
            patch("converter.services.generation.codex_executable"),
            patch("converter.services.generation.launch_worker"),
        ):
            return resume_generation(run)

    def test_overview_reads_whole_lecture_but_cards_remain_scoped_to_selection(self):
        run = self.run_record()
        calls = []

        def generate(pages, cancelled, **kwargs):
            calls.append(([p.number for p in pages], kwargs))
            if kwargs.get("task") == "overview":
                return {"topics": [self.topic(p) for p in pages]}
            self.assertEqual(len(kwargs["lecture_context"]), 3)
            good = self.payload["cards"][0]
            other = {**good, "page": 3, "front": "Not selected"}
            return {"cards": [good, other]}

        with patch("converter.services.generation.codex_generate", side_effect=generate):
            perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual([row[0] for row in calls], [[1, 2, 3], [1]])
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.completed_pages, [1])
        self.assertEqual(run.cards_added, 1)
        self.assertEqual(len(run.issues), 1)
        self.assertEqual(run.context_data["pages"], [1, 2, 3])
        self.assertTrue(context_progress(run)["ready"])
        text = prompt_for(
            [self.lecture.pages.get(number=1)], lecture_context=run.context_data["outline"]
        )
        self.assertIn("NOT evidence", text)
        self.assertIn("CURRENT supplied batch", text)
        self.assertEqual(
            [p["page"] for p in json.loads(text.split("LECTURE PAGE DATA (JSON):\n")[1])], [1]
        )
        response = self.client.get(self.lecture.get_absolute_url())
        self.assertContains(response, "Lecture overview")
        self.assertContains(response, "Topic 3")

    def test_sections_resume_without_repeating_saved_work_or_overwriting_edits(self):
        accepted = self.accepted_card()
        pages = list(self.lecture.pages.filter(warning=""))
        ceiling = max(len(page.text) for page in pages)
        run = self.run_record()
        calls = []
        fail = True
        fail_merge = True

        def generate(source, cancelled, **kwargs):
            nonlocal fail, fail_merge
            numbers = [p.number for p in source]
            calls.append((kwargs.get("task", "cards"), numbers))
            if kwargs.get("task") == "overview":
                if numbers == [2] and fail:
                    fail = False
                    raise WorkflowError("Synthetic usage interruption")
                if kwargs.get("sections") is not None:
                    if fail_merge:
                        fail_merge = False
                        raise WorkflowError("Synthetic merge interruption")
                    return {"topics": [s["topics"][0] for s in kwargs["sections"]]}
                return {"topics": [self.topic(p) for p in source]}
            return {"cards": []}

        with (
            patch("converter.services.lecture_context.SECTION_CHARACTERS", ceiling),
            patch("converter.services.generation.codex_generate", side_effect=generate),
        ):
            self.assertEqual(len(context_sections(pages)), 3)
            perform_run(run.pk)
            run.refresh_from_db()
            self.assertEqual(run.status, "failed")
            self.assertEqual(len(run.context_data["sections"]), 1)
            self.assertIsNone(run.context_data["outline"])
            self.assertEqual(run.completed_pages, [])
            update_card(
                accepted.pk, accepted.version, "Keep my edit", accepted.back, "", "accepted"
            )
            self.resume(run)
            perform_run(run.pk)
            run.refresh_from_db()
            self.assertEqual(run.status, "failed")
            progress = self.client.get(reverse("run_status", args=[run.pk])).json()["context"]
            self.assertEqual(
                (progress["stage"], progress["read"], progress["total"]), ("organizing", 3, 3)
            )
            self.assertIsNone(run.context_data["outline"])
            with zipfile.ZipFile(io.BytesIO(export_backup(self.lecture))) as backup:
                saved = json.loads(backup.read("manifest.json"))["runs"][0]["context_data"]
                self.assertEqual(saved, run.context_data)
            self.resume(run)
            perform_run(run.pk)
            run.refresh_from_db()
            self.assertEqual(run.status, "completed")
            self.assertEqual(len(run.context_data["outline"]), 3)
        self.assertEqual(
            calls,
            [
                ("overview", [1]),
                ("overview", [2]),
                ("overview", [2]),
                ("overview", [3]),
                ("overview", []),
                ("overview", []),
                ("cards", [1]),
            ],
        )
        accepted.refresh_from_db()
        self.assertEqual((accepted.front, accepted.status), ("Keep my edit", "accepted"))

    def test_late_overview_cannot_write_into_cancelled_and_resumed_attempt(self):
        run = self.run_record()

        def late(pages, cancelled, **kwargs):
            GenerationRun.objects.filter(pk=run.pk).update(status="cancelled")
            run.refresh_from_db()
            self.resume(run)
            self.assertTrue(cancelled())
            return {"topics": [self.topic(pages[0])]}

        with patch("converter.services.generation.codex_generate", side_effect=late):
            perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, "queued")
        self.assertEqual(run.context_data["sections"], [])
        self.assertIsNone(run.context_data["outline"])
        self.assertFalse(Card.objects.exists())

    def test_ready_overview_is_reused_after_card_failure_and_empty_outline_is_valid(self):
        run = self.run_record()
        with patch(
            "converter.services.generation.codex_generate",
            side_effect=[{"topics": []}, WorkflowError("Card failure")],
        ) as generate:
            perform_run(run.pk)
            self.assertEqual(generate.call_count, 2)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertTrue(context_progress(run)["ready"])
        self.resume(run)
        with patch(
            "converter.services.generation.codex_generate", return_value={"cards": []}
        ) as generate:
            perform_run(run.pk)
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(generate.call_args.kwargs["lecture_context"], [])
        run.refresh_from_db()
        self.assertEqual(run.status, "completed")

    def test_malformed_overview_stops_before_cards_and_incomplete_context_is_not_ready(self):
        pages = list(self.lecture.pages.all())
        topic = self.topic(pages[0])
        bad = [
            {},
            {"topics": "wrong"},
            {"topics": [topic] * 9},
            *[
                {"topics": [{**topic, **change}]}
                for change in (
                    {"page": True},
                    {"page": 99},
                    {"source_quote": "invented"},
                    {"summary": ""},
                    {"priority": "highest"},
                    {"title": "x" * 101},
                )
            ],
        ]
        for payload in bad:
            with self.subTest(payload=payload):
                run = self.run_record()
                with patch(
                    "converter.services.generation.codex_generate", return_value=payload
                ) as generate:
                    perform_run(run.pk)
                run.refresh_from_db()
                self.assertEqual((run.status, run.completed_pages), ("failed", []))
                self.assertEqual(generate.call_count, 3)
                self.assertFalse(context_progress(run)["ready"])
                self.assertFalse(Card.objects.exists())
        data = run.context_data
        for mutation in ({"outline": []}, {"source_sha256": "0" * 64}, {"pages": [True, 2, 3]}):
            with self.assertRaises(WorkflowError):
                checked_context({**data, **mutation}, True, self.lecture, pages)
        with self.assertRaises(WorkflowError):
            checked_context({}, "yes", self.lecture, pages)

    def test_scope_consent_and_download_include_context_only_pages_without_inference(self):
        url = reverse("generate", args=[self.lecture.pk])
        with patch("converter.views.start_generation") as start:
            values = {"pages": [1], "lecture_context": "yes"}
            self.assertEqual(self.client.post(url, values).status_code, 400)
            start.assert_not_called()
            self.assertEqual(self.client.post(url, {**values, "consent": "yes"}).status_code, 302)
            self.assertIs(start.call_args.kwargs["context_enabled"], True)
            self.assertEqual(
                self.client.post(url, {"pages": [1], "consent": "yes"}).status_code, 302
            )
            self.assertNotIn("context_enabled", start.call_args.kwargs)
        url = reverse("prompt", args=[self.lecture.pk])
        with patch("converter.services.generation.codex_generate") as generate:
            full = self.client.post(url, {"pages": [1], "lecture_context": "yes"}).content.decode()
            selected = self.client.post(url, {"pages": [1]}).content.decode()
            generate.assert_not_called()
        self.assertIn("context_only_pages", full)
        self.assertNotIn("context_only_pages", selected)
        context_only = json.loads(full.splitlines()[1])["context_only_pages"]
        self.assertEqual([page["page"] for page in context_only], [2, 3])
        self.assertEqual(context_only[0]["text"], self.lecture.pages.get(number=2).text)
        self.assertEqual(
            [p["page"] for p in json.loads(full.split("LECTURE PAGE DATA (JSON):\n")[1])], [1]
        )

    def test_backup_restores_overview_identity_and_rejects_corrupted_context(self):
        run = self.run_record()
        topic = self.topic(self.lecture.pages.first())
        with patch(
            "converter.services.generation.codex_generate",
            side_effect=[{"topics": [topic]}, {"cards": [self.payload["cards"][0]]}],
        ):
            perform_run(run.pk)
        run.refresh_from_db()
        expected = copy.deepcopy(run.context_data)
        data = export_backup(self.lecture)
        Card.objects.all().delete()
        Lecture.objects.all().delete()
        for valid in (False, True):
            output = io.BytesIO()
            with (
                zipfile.ZipFile(io.BytesIO(data)) as source,
                zipfile.ZipFile(output, "w") as target,
            ):
                manifest = json.loads(source.read("manifest.json"))
                self.assertEqual(manifest["version"], 12)
                if not valid:
                    manifest["runs"][0]["context_data"]["outline"][0]["source_quote"] = "bad"
                for name in source.namelist():
                    target.writestr(
                        name, json.dumps(manifest) if name == "manifest.json" else source.read(name)
                    )
            destination = Path(self.directory.name) / str(uuid.uuid4())
            destination.mkdir()
            with override_settings(MEDIA_ROOT=destination):
                if valid:
                    restored = restore_backup(SimpleUploadedFile("backup.zip", output.getvalue()))
                    saved = restored.runs.get(pk=run.pk)
                    self.assertEqual(saved.context_data, expected)
                    self.assertTrue(saved.context_enabled)
                else:
                    with self.assertRaises(WorkflowError):
                        restore_backup(SimpleUploadedFile("bad.zip", output.getvalue()))
                    self.assertFalse(Lecture.objects.exists())
                    self.assertEqual(list(destination.iterdir()), [])

    def test_native_adapters_use_overview_schema_and_keep_sources_in_stdin(self):
        page = self.lecture.pages.first()
        topic = self.topic(page)
        payload = {
            "topics": [
                {k: topic[k] for k in ("title", "summary", "priority")} | {"source_id": "p1:e1"}
            ]
        }
        for provider, generate in (("codex", codex_generate), ("claude", claude_generate)):

            def finish(command, **kwargs):
                text = kwargs["stdin"].read().decode()
                self.assertIn("planning pass, NOT card creation", text)
                sources = json.loads(text.split("UNTRUSTED SOURCE DATA (JSON):\n")[1])
                self.assertEqual(sources[0]["page"], page.number)
                for excerpt in sources[0]["excerpts"]:
                    self.assertIn(excerpt["text"], page.text)
                    self.assertLessEqual(len(excerpt["text"]), 240)
                    self.assertTrue(excerpt["source_id"].startswith("p1:e"))
                self.assertNotIn(page.text, " ".join(command))
                if provider == "codex":
                    schema = json.loads(
                        Path(command[command.index("--output-schema") + 1]).read_text()
                    )
                    Path(command[command.index("--output-last-message") + 1]).write_text(
                        json.dumps(payload)
                    )
                else:
                    schema = json.loads(command[command.index("--json-schema") + 1])
                    kwargs["stdout"].write(
                        json.dumps(
                            {"type": "result", "subtype": "success", "structured_output": payload}
                        ).encode()
                    )
                self.assertEqual(schema, OVERVIEW_SCHEMA)
                return Mock(returncode=0, poll=Mock(return_value=0))

            with (
                self.subTest(provider=provider),
                patch("converter.services.generation.subprocess.Popen", side_effect=finish),
                patch("converter.services.generation.codex_executable", return_value="codex.exe"),
                patch("converter.services.generation.claude_executable", return_value="claude.exe"),
                patch("converter.services.generation.checked_model_settings"),
                patch(
                    "converter.services.connection.claude_login_status",
                    return_value={"state": "connected"},
                ),
            ):
                self.assertEqual(generate([page], task="overview"), payload)
        with self.assertRaises(WorkflowError):
            generation_request([], task="overview", sections=[{"text": "x" * 200001}])

    def test_custom_card_generator_never_causes_unmocked_overview_calls(self):
        run = self.run_record()
        with patch("converter.services.generation.codex_generate") as generate:
            perform_run(run.pk, lambda *_: {"cards": []})
            generate.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
