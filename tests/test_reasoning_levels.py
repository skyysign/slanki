import io
import json
import uuid
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from converter.models import GenerationRun, Lecture
from converter.services.backups import export_backup, restore_backup
from converter.services.files import WorkflowError
from converter.services.generation import (
    codex_generate,
    perform_run,
    resume_generation,
    start_generation,
)

from .test_workflow import WorkflowFixture


class ReasoningLevelTests(WorkflowFixture):
    @patch("converter.services.generation.codex_executable", return_value="codex.exe")
    @patch("converter.services.generation.subprocess.Popen")
    def test_each_level_reaches_cli_as_one_config_argument_without_changing_permissions(
        self, popen, executable
    ):
        def completed_process(command, **kwargs):
            output = Path(command[command.index("--output-last-message") + 1])
            output.write_text('{"cards": []}', encoding="utf-8")
            return Mock(returncode=0, poll=Mock(return_value=0))

        popen.side_effect = completed_process
        for level, _ in GenerationRun.REASONING_LEVELS:
            with self.subTest(level=level):
                self.assertEqual(
                    codex_generate(list(self.lecture.pages.all()), reasoning_effort=level),
                    {"cards": []},
                )
                command = popen.call_args.args[0]
                settings = [command[i + 1] for i, arg in enumerate(command) if arg == "-c"]
                effort_settings = [
                    value for value in settings if value.startswith("model_reasoning_effort=")
                ]
                self.assertEqual(
                    effort_settings, [f'model_reasoning_effort="{level}"'] if level else []
                )
                self.assertIn("--ignore-user-config", command)
                self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
                disabled = [command[i + 1] for i, arg in enumerate(command) if arg == "--disable"]
                self.assertIn("multi_agent", disabled)
                self.assertIn("shell_tool", disabled)
                self.assertNotIn("shell", popen.call_args.kwargs)

    @patch("converter.services.generation.subprocess.Popen")
    @patch("converter.views.start_generation")
    def test_invalid_efforts_are_rejected_before_worker_or_provider_start(self, start, popen):
        for effort in ("mid", "ultra", "max -c sandbox_mode=danger-full-access", "unknown"):
            with self.subTest(effort=effort):
                response = self.client.post(
                    reverse("generate", args=[self.lecture.pk]),
                    {"pages": [1], "consent": "yes", "reasoning_effort": effort},
                )
                self.assertEqual(response.status_code, 400)
                with self.assertRaises(WorkflowError):
                    codex_generate([], reasoning_effort=effort)
        start.assert_not_called()
        popen.assert_not_called()

    @patch("converter.services.generation.launch_worker")
    @patch("converter.services.generation.codex_executable", return_value="codex.exe")
    @patch("converter.services.generation.codex_generate")
    def test_selection_is_saved_forwarded_and_retained_on_resume(
        self, provider, executable, launch
    ):
        run = start_generation(self.lecture, [1, 2, 3], reasoning_effort="xhigh")
        self.assertEqual(run.reasoning_effort, "xhigh")
        provider.side_effect = WorkflowError("Quota reached")
        perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        response = self.client.get(self.lecture.get_absolute_url())
        self.assertContains(response, "Reasoning: Extra high")
        self.assertContains(response, 'value="xhigh" checked')
        self.assertEqual(
            self.client.get(reverse("run_status", args=[run.pk])).json()["reasoning_effort"],
            "Extra high",
        )
        resume_generation(run)
        provider.side_effect = None
        provider.return_value = {"cards": []}
        perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, "completed")
        self.assertEqual(
            [call.kwargs["reasoning_effort"] for call in provider.call_args_list],
            ["xhigh", "xhigh"],
        )

    @patch("converter.views.start_generation")
    def test_form_selection_reaches_generation_service(self, start):
        for level, _ in GenerationRun.REASONING_LEVELS:
            response = self.client.post(
                reverse("generate", args=[self.lecture.pk]),
                {"pages": [1], "consent": "yes", "reasoning_effort": level},
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(start.call_args.kwargs["reasoning_effort"], level)

    def test_backup_retains_effort_and_rejects_unknown_effort(self):
        run = GenerationRun.objects.create(
            lecture=self.lecture,
            status="completed",
            page_numbers=[1],
            completed_pages=[1],
            reasoning_effort="max",
        )
        data = export_backup(self.lecture)
        Lecture.objects.all().delete()
        destination = Path(self.directory.name) / str(uuid.uuid4())
        destination.mkdir()
        with override_settings(MEDIA_ROOT=destination):
            restored = restore_backup(SimpleUploadedFile("backup.zip", data))
        self.assertEqual(restored.runs.get(pk=run.pk).reasoning_effort, "max")
        Lecture.objects.all().delete()
        modified = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(modified, "w") as dst:
            for name in src.namelist():
                contents = src.read(name)
                if name == "manifest.json":
                    manifest = json.loads(contents)
                    manifest["runs"][0]["reasoning_effort"] = "invalid"
                    contents = json.dumps(manifest).encode()
                dst.writestr(name, contents)
        destination = Path(self.directory.name) / str(uuid.uuid4())
        destination.mkdir()
        with override_settings(MEDIA_ROOT=destination), self.assertRaises(WorkflowError):
            restore_backup(SimpleUploadedFile("invalid.zip", modified.getvalue()))
        self.assertFalse(Lecture.objects.exists())
