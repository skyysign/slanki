import io
import json
import os
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, override_settings
from django.urls import reverse

from converter.models import Card, Lecture
from converter.services.backups import export_backup, restore_backup
from converter.services.cards import update_card
from converter.services.cli import claude_executable, metadata_process
from converter.services.connection import CodexConnection, claude_login_status
from converter.services.files import WorkflowError
from converter.services.generation import (
    Cancelled,
    claude_generate,
    codex_generate,
    perform_run,
    resume_generation,
    start_generation,
)
from converter.services.providers import (
    catalog_path,
    checked_model_settings,
    discover_models,
    model_catalog,
    normalize_models,
    refresh_models,
)

from .test_workflow import WorkflowFixture

CLAUDE_MODELS = [
    {
        "value": "default",
        "displayName": "Default",
        "supportsEffort": True,
        "supportedEffortLevels": ["low", "high"],
    },
    {
        "value": "sonnet",
        "displayName": "Sonnet",
        "supportsEffort": True,
        "supportedEffortLevels": ["low", "medium", "high"],
    },
    {"value": "haiku", "displayName": "Haiku", "supportsEffort": False},
]
CODEX_MODELS = [
    {
        "model": "synthetic-codex",
        "displayName": "Synthetic Codex",
        "isDefault": True,
        "supportedReasoningEfforts": [
            {"reasoningEffort": level} for level in ("low", "high", "xhigh")
        ],
    },
]


class ProviderTests(WorkflowFixture):
    def setUp(self):
        for provider, rows in [("claude", CLAUDE_MODELS), ("codex", CODEX_MODELS)]:
            catalog_path(provider).write_text(
                json.dumps({"models": normalize_models(rows, provider), "updated_at": 1}),
                encoding="utf-8",
            )

    def test_model_capabilities_and_invalid_combinations_are_validated_before_generation(self):
        self.assertEqual(model_catalog("claude")["models"][-1]["efforts"], [""])
        self.assertEqual(checked_model_settings("claude", "haiku", ""), ("claude", "haiku", ""))
        for provider, model, effort in [
            ("claude", "haiku", "high"),
            ("claude", "sonnet", "xhigh"),
            ("codex", "sonnet", "low"),
            ("arbitrary", "", ""),
            ("claude", "--tools Bash", ""),
            ("claude", "sonnet", "ultracode"),
            ("claude", "", "xhigh"),
        ]:
            with (
                self.subTest(provider=provider, model=model, effort=effort),
                patch("converter.views.start_generation") as start,
            ):
                response = self.client.post(
                    reverse("generate", args=[self.lecture.pk]),
                    {
                        "pages": [1],
                        "provider": provider,
                        "model": model,
                        "reasoning_effort": effort,
                        "consent": "yes",
                    },
                )
                self.assertEqual(response.status_code, 400)
                start.assert_not_called()
        with patch("converter.views.start_generation") as start:
            self.assertEqual(
                self.client.post(
                    reverse("generate", args=[self.lecture.pk]),
                    {"pages": [1], "provider": "claude", "model": "haiku", "consent": "yes"},
                ).status_code,
                302,
            )
            self.assertEqual(start.call_args.kwargs["reasoning_effort"], "")

    def test_refresh_is_local_csrf_protected_and_keeps_only_model_metadata(self):
        url = reverse("refresh_provider_models", args=["claude"])
        with patch(
            "converter.services.providers.discover_models",
            return_value=normalize_models(CLAUDE_MODELS, "claude"),
        ) as discover:
            self.assertEqual(self.client.get(url).status_code, 405)
            self.assertEqual(Client(enforce_csrf_checks=True).post(url).status_code, 403)
            self.assertEqual(self.client.post(url, REMOTE_ADDR="203.0.113.1").status_code, 403)
            self.assertEqual(
                self.client.get(reverse("provider_models", args=["claude"])).status_code, 200
            )
            discover.assert_not_called()
            self.assertEqual(self.client.post(url).status_code, 200)
            discover.assert_called_once_with("claude")
        previous = catalog_path("claude").read_bytes()
        with patch(
            "converter.services.providers.discover_models",
            side_effect=WorkflowError("Update your CLI"),
        ):
            self.assertEqual(self.client.post(url).status_code, 400)
        self.assertEqual(catalog_path("claude").read_bytes(), previous)
        self.assertEqual(
            self.client.post(reverse("refresh_provider_models", args=["invalid"])).status_code, 404
        )

    @patch("converter.services.providers.codex_executable", return_value="codex.exe")
    @patch("converter.services.providers.claude_executable", return_value="claude.exe")
    @patch("converter.services.providers.claude_is_external", return_value=False)
    @patch("converter.services.providers.metadata_process")
    def test_metadata_protocol_never_submits_a_prompt_and_discards_account_data(
        self, exchange, external, claude, codex
    ):
        send, receive = Mock(), Mock()
        exchange.return_value.__enter__.return_value = (send, receive)
        receive.side_effect = [
            {"id": 1, "result": {}},
            {"id": 2, "result": {"data": CODEX_MODELS, "nextCursor": None}},
        ]
        self.assertEqual(discover_models("codex")[1]["id"], "synthetic-codex")
        self.assertEqual(
            [call.args[0]["method"] for call in send.call_args_list],
            ["initialize", "initialized", "model/list"],
        )
        send.reset_mock()
        receive.side_effect = [
            {
                "type": "control_response",
                "response": {
                    "request_id": "models",
                    "response": {
                        "models": CLAUDE_MODELS,
                        "account": {"email": "private@example.invalid", "token": "private-token"},
                    },
                },
            }
        ]
        result = refresh_models("claude")
        self.assertNotIn("private", str(result) + catalog_path("claude").read_text())
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0]["request"]["subtype"], "initialize")
        command = exchange.call_args.args[0]
        self.assertIn("--safe-mode", command)
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertNotIn("--bare", command)

    def test_malformed_metadata_is_rejected_without_exposing_or_executing_it(self):
        for rows in [
            [],
            [None],
            [{"value": "--tools=all"}],
            [{"value": "sonnet", "supportedEffortLevels": "max"}],
        ]:
            with self.subTest(rows=rows), self.assertRaises(WorkflowError):
                normalize_models(rows, "claude")
        catalog_path("claude").write_text('{"models": "bad"}', encoding="utf-8")
        self.assertEqual(model_catalog("claude")["models"][0]["efforts"], [""])

    @patch("converter.services.generation.claude_executable", return_value="claude.exe")
    @patch("converter.services.connection.claude_login_status", return_value={"state": "connected"})
    @patch("converter.services.generation.subprocess.Popen")
    def test_claude_generation_uses_selected_model_effort_stdin_and_restricted_tools(
        self, popen, status, executable
    ):
        envelope = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "structured_output": self.payload,
        }

        def finish(command, **kwargs):
            self.assertIn("LECTURE PAGE DATA", kwargs["stdin"].read().decode())
            self.assertNotIn(self.lecture.pages.first().text, " ".join(command))
            self.assertEqual(command[command.index("--model") + 1], "sonnet")
            self.assertEqual(command[command.index("--effort") + 1], "low")
            self.assertEqual(command[command.index("--tools") + 1], "")
            self.assertEqual(command[command.index("--setting-sources") + 1], "")
            self.assertIn("--strict-mcp-config", command)
            self.assertIn("--safe-mode", command)
            self.assertIn("--no-session-persistence", command)
            self.assertNotIn("--bare", command)
            self.assertFalse(kwargs.get("shell", False))
            self.assertNotIn("CLAUDE_CODE_EFFORT_LEVEL", kwargs["env"])
            kwargs["stdout"].write(json.dumps(envelope).encode())
            return Mock(returncode=0, poll=Mock(return_value=0))

        popen.side_effect = finish
        with patch.dict(os.environ, {"CLAUDE_CODE_EFFORT_LEVEL": "max"}):
            self.assertEqual(
                claude_generate(
                    list(self.lecture.pages.all()), model="sonnet", reasoning_effort="low"
                ),
                self.payload,
            )
        envelope["is_error"] = True
        with self.assertRaises(WorkflowError):
            claude_generate([], model="sonnet", reasoning_effort="low")
        status.return_value = {"state": "signed_out"}
        popen.reset_mock()
        with self.assertRaisesMessage(WorkflowError, "Connect Claude Code"):
            claude_generate([], model="sonnet", reasoning_effort="low")
        popen.assert_not_called()

    @patch("converter.services.generation.claude_executable", return_value="claude.exe")
    @patch("converter.services.connection.claude_login_status", return_value={"state": "connected"})
    @patch("converter.services.generation.subprocess.Popen")
    def test_claude_cancel_and_timeout_stop_the_owned_process(self, popen, status, executable):
        process = popen.return_value
        process.poll.return_value = None
        with self.assertRaises(Cancelled):
            claude_generate([], cancelled=lambda: True)
        process.terminate.assert_called_once()
        process.reset_mock()
        with (
            override_settings(GENERATION_TIMEOUT=0),
            self.assertRaisesMessage(WorkflowError, "timed out"),
        ):
            claude_generate([])
        process.terminate.assert_called_once()

    @patch("converter.services.generation.codex_executable", return_value="codex.exe")
    @patch("converter.services.generation.subprocess.Popen")
    def test_codex_model_is_one_argument_and_overrides_legacy_environment_default(
        self, popen, executable
    ):
        def finish(command, **kwargs):
            self.assertEqual(command[command.index("--model") + 1], "synthetic-codex")
            Path(command[command.index("--output-last-message") + 1]).write_text('{"cards": []}')
            return Mock(returncode=0, poll=Mock(return_value=0))

        popen.side_effect = finish
        with patch.dict(os.environ, {"SLIDES_CODEX_MODEL": "another-model"}):
            self.assertEqual(codex_generate([], model="synthetic-codex"), {"cards": []})

    @patch("converter.services.generation.launch_worker")
    @patch("converter.services.generation.claude_executable", return_value="claude.exe")
    @patch("converter.services.connection.claude_login_status", return_value={"state": "connected"})
    @patch("converter.services.generation.codex_generate")
    @patch("converter.services.generation.claude_generate")
    def test_provider_model_resume_edits_and_backup_survive_without_switching(
        self, claude, codex, status, executable, launch
    ):
        page4 = self.lecture.pages.get(number=4)
        page4.text, page4.warning = "A final concept.", ""
        page4.save()
        run = start_generation(
            self.lecture,
            [1, 2, 3, 4],
            card_limit=10,
            provider="claude",
            model="sonnet",
            reasoning_effort="low",
        )
        claude.side_effect = [self.payload, WorkflowError("Synthetic quota")]
        perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        card = self.lecture.cards.first()
        card = update_card(
            card.pk, card.version, "My edited question?", card.back, card.source_quote, "accepted"
        )
        self.assertContains(
            self.client.get(self.lecture.get_absolute_url()), 'value="claude" selected'
        )
        self.assertContains(
            self.client.get(self.lecture.get_absolute_url()), 'value="sonnet" selected'
        )
        resume_generation(run)
        claude.side_effect = None
        claude.return_value = {"cards": []}
        perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, "completed")
        self.assertTrue(
            all(
                call.kwargs["model"] == "sonnet" and call.kwargs["reasoning_effort"] == "low"
                for call in claude.call_args_list
            )
        )
        codex.assert_not_called()
        card.refresh_from_db()
        self.assertEqual((card.front, card.status), ("My edited question?", "accepted"))
        backup = export_backup(self.lecture)
        with zipfile.ZipFile(io.BytesIO(backup)) as archive:
            self.assertNotIn("models-claude.json", archive.namelist())
        Card.objects.all().delete()
        Lecture.objects.all().delete()
        destination = Path(self.directory.name) / str(uuid.uuid4())
        destination.mkdir()
        with override_settings(MEDIA_ROOT=destination):
            restored = restore_backup(SimpleUploadedFile("backup.zip", backup))
        saved = restored.runs.get(pk=run.pk)
        self.assertEqual(
            (saved.provider, saved.model, saved.reasoning_effort), ("claude", "sonnet", "low")
        )

    def test_metadata_timeout_and_unexpected_host_request_are_bounded(self):
        for script in [
            "import time; time.sleep(30)",
            'import json; print(json.dumps({"type":"control_request","request_id":"unexpected"}), flush=True); import time; time.sleep(30)',
        ]:
            with self.subTest(script=script), self.assertRaises(WorkflowError):
                with metadata_process([sys._base_executable, "-u", "-c", script], timeout=0.3) as (
                    _,
                    receive,
                ):
                    receive(lambda message: message.get("id") == "models")


@override_settings(ALLOWED_HOSTS=["testserver"])
class ClaudeConnectionTests(SimpleTestCase):
    @patch("converter.services.connection.claude_executable", return_value="claude.exe")
    @patch("converter.services.connection.claude_is_external", return_value=False)
    @patch("converter.services.connection.subprocess.run")
    def test_status_redacts_identity_and_classifies_subscription_vs_api(
        self, run, external, executable
    ):
        for logged, method, code, expected in [
            (True, "claude.ai", 0, "connected"),
            (False, "none", 1, "signed_out"),
            (True, "api_key", 0, "external"),
        ]:
            run.return_value = subprocess.CompletedProcess(
                [],
                code,
                json.dumps(
                    {
                        "loggedIn": logged,
                        "authMethod": method,
                        "apiProvider": "firstParty",
                        "email": "private",
                        "token": "private",
                    }
                ),
                "private",
            )
            state = claude_login_status()
            self.assertEqual(state["state"], expected)
            self.assertNotIn("private", str(state))
        external.return_value = True
        run.reset_mock()
        self.assertEqual(claude_login_status()["state"], "external")
        run.assert_not_called()

    @patch("converter.services.connection.threading.Timer")
    @patch("converter.services.connection.subprocess.Popen")
    @patch("converter.services.connection.claude_executable", return_value="claude.exe")
    @patch(
        "converter.services.connection.claude_login_status", return_value={"state": "signed_out"}
    )
    def test_claude_login_reuses_attempt_and_cancels_without_logging_out(
        self, status, executable, popen, timer
    ):
        manager = CodexConnection("claude")
        popen.return_value.poll.return_value = None
        self.addCleanup(manager.cancel)
        self.assertEqual(manager.start()["state"], "waiting")
        manager.start()
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], ["claude.exe", "auth", "login"])
        manager.cancel()
        popen.return_value.terminate.assert_called_once()
        status.return_value = {"state": "connected"}
        manager.start()
        popen.assert_called_once()

    @patch("converter.views.claude_connection")
    @patch("converter.views.connection")
    def test_provider_routes_keep_connections_separate_and_protect_sign_in(self, codex, claude):
        claude.status.return_value = {"state": "signed_out", "message": "Connect Claude"}
        self.assertContains(
            self.client.get(reverse("provider_connection", args=["claude"])), "Connect Claude Code"
        )
        codex.status.assert_not_called()
        for name in ("connect_provider", "cancel_provider_login"):
            url = reverse(name, args=["claude"])
            self.assertEqual(self.client.get(url).status_code, 405)
            self.assertEqual(Client(enforce_csrf_checks=True).post(url).status_code, 403)
            self.assertEqual(self.client.post(url).status_code, 302)
        claude.start.assert_called_once()
        claude.cancel.assert_called_once()
        codex.start.assert_not_called()
        self.assertEqual(
            self.client.post(reverse("connect_provider", args=["arbitrary"])).status_code, 404
        )

    @override_settings(CLAUDE_BINARY="custom.cmd")
    @patch("converter.services.cli.shutil.which", return_value="C:/untrusted/custom.cmd")
    def test_shell_wrapper_is_never_executed(self, which):
        with self.assertRaises(WorkflowError):
            claude_executable()
