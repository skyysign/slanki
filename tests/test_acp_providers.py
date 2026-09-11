import json
import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from converter.services.acp import (
    AcpClient,
    AuthenticationRequired,
    acp_environment,
    discover_acp_models,
    generate_acp,
    login,
    login_status,
    model_rows,
    prepare_profile,
    profile_path,
)
from converter.services.backups import export_backup, restore_backup
from converter.services.cli import node_cli_command
from converter.services.connection import AcpConnection
from converter.services.files import WorkflowError
from converter.services.generation import (
    Cancelled,
    perform_run,
    resume_generation,
    start_generation,
)
from converter.services.providers import checked_model_settings, refresh_models

from .test_workflow import WorkflowFixture

FAKE = Path(__file__).parent / "fixtures/synthetic/acp_cli.py"


class AcpProviderTests(WorkflowFixture):
    def setUp(self):
        self.record = settings.WORK_DIR / "acp-requests.jsonl"
        self.record.write_text("", encoding="utf-8")
        for provider in ("gemini", "kimi"):
            prepare_profile(provider)
        (profile_path("gemini") / "recalloom-signed-in").write_text("synthetic", encoding="utf-8")

    def fake(self, provider, scenario="success"):
        return [sys._base_executable, str(FAKE), provider, scenario, str(self.record)]

    def requests(self):
        return [json.loads(line) for line in self.record.read_text(encoding="utf-8").splitlines()]

    def catalog(self, provider):
        with patch("converter.services.acp.node_cli_command", return_value=self.fake(provider)):
            return refresh_models(provider)

    def test_discovery_uses_no_prompts_and_scopes_models_and_efforts(self):
        gemini = self.catalog("gemini")
        self.assertEqual(gemini["models"][1]["efforts"], [""])
        kimi = self.catalog("kimi")
        self.assertEqual(
            [row["id"] for row in kimi["models"]], ["", "kimi-code/advanced", "kimi-code/toggle"]
        )
        self.assertEqual(kimi["models"][1]["efforts"], ["", "low", "high", "max"])
        self.assertEqual(kimi["models"][2]["efforts"], ["", "off", "on"])
        self.assertNotIn("session/prompt", [row["method"] for row in self.requests()])
        for provider, model, effort in [
            ("gemini", "gemini-synthetic", "high"),
            ("kimi", "kimi-code/toggle", "high"),
            ("kimi", "custom/other", ""),
            ("codex", "", "on"),
        ]:
            with (
                self.subTest(provider=provider, model=model, effort=effort),
                self.assertRaises(WorkflowError),
            ):
                checked_model_settings(provider, model, effort)

    def test_generation_streams_json_and_keeps_source_out_of_command_arguments(self):
        for provider, model, effort in [
            ("gemini", "gemini-synthetic", ""),
            ("kimi", "kimi-code/advanced", "high"),
            ("kimi", "kimi-code/toggle", "off"),
        ]:
            self.catalog(provider)
            with patch("converter.services.acp.node_cli_command", return_value=self.fake(provider)):
                payload = generate_acp(
                    provider,
                    list(self.lecture.pages.filter(number=1)),
                    model=model,
                    reasoning_effort=effort,
                )
            self.assertEqual(len(payload["cards"]), 1)
        prompts = [row for row in self.requests() if row["method"] == "session/prompt"]
        self.assertEqual(len(prompts), 3)
        self.assertIn("LECTURE PAGE DATA", prompts[0]["params"]["prompt"][0]["text"])
        self.assertTrue(
            any(
                row["params"].get("configId") == "thinking" and row["params"].get("value") == "off"
                for row in self.requests()
            )
        )

    def test_malformed_partial_wrong_session_and_tool_output_never_becomes_cards(self):
        self.catalog("gemini")
        for scenario in (
            "malformed-json",
            "truncated",
            "closed",
            "wrong-session",
            "permission",
            "file-request",
            "tool-call",
        ):
            with (
                self.subTest(scenario=scenario),
                patch(
                    "converter.services.acp.node_cli_command",
                    return_value=self.fake("gemini", scenario),
                ),
                self.assertRaises(WorkflowError),
            ):
                generate_acp(
                    "gemini", list(self.lecture.pages.filter(number=1)), model="gemini-synthetic"
                )

    def test_real_transport_timeout_includes_blocked_stdin_and_cancellation(self):
        before = time.monotonic()
        client = AcpClient(
            self.fake("gemini", "blocked-input"),
            settings.WORK_DIR,
            os.environ.copy(),
            timeout=0.2,
            cancelled=lambda: False,
        )
        try:
            with self.assertRaises(WorkflowError):
                client.request("session/prompt", {"text": "x" * 2000000})
        finally:
            client.close()
        self.assertLess(time.monotonic() - before, 4)
        self.assertIsNotNone(client.process.poll())
        self.catalog("kimi")
        with (
            patch("converter.services.acp.node_cli_command", return_value=self.fake("kimi")),
            self.assertRaises(Cancelled),
        ):
            generate_acp("kimi", [], cancelled=lambda: True, model="kimi-code/advanced")

    def test_profile_has_no_copied_credentials_and_rejects_relaxed_tool_settings(self):
        config = profile_path("gemini") / ".gemini/settings.json"
        data = json.loads(config.read_text(encoding="utf-8"))
        self.assertTrue(data["security"]["auth"]["useExternal"])
        self.assertEqual(data["tools"]["core"], ["recalloom_no_tools"])
        data["tools"]["core"] = []
        config.write_text(json.dumps(data), encoding="utf-8")
        try:
            with self.assertRaises(WorkflowError):
                prepare_profile("gemini")
            self.assertEqual(json.loads(config.read_text(encoding="utf-8"))["tools"]["core"], [])
        finally:
            data["tools"]["core"] = ["recalloom_no_tools"]
            config.write_text(json.dumps(data), encoding="utf-8")
        self.assertFalse(
            any(
                "token" in path.name or "credential" in path.name
                for path in settings.CLI_PROFILE_ROOT.rglob("*")
            )
        )
        with patch.dict(
            os.environ,
            {
                "KIMI_MODEL_API_KEY": "private",
                "GEMINI_API_KEY": "private",
                "GOOGLE_GEMINI_BASE_URL": "https://other.invalid",
                "NODE_OPTIONS": "--require=untrusted",
                "KIMI_CODE_HOME": "other-profile",
            },
        ):
            for provider in ("gemini", "kimi"):
                env = acp_environment(provider)
                for key in (
                    "KIMI_MODEL_API_KEY",
                    "GEMINI_API_KEY",
                    "GOOGLE_GEMINI_BASE_URL",
                    "NODE_OPTIONS",
                ):
                    self.assertNotIn(key, env)

    def test_status_never_starts_gemini_auth_and_kimi_errors_are_redacted(self):
        marker = profile_path("gemini") / "recalloom-signed-in"
        marker.unlink()
        with (
            patch("converter.services.acp.node_cli_command", return_value=self.fake("gemini")),
            patch("converter.services.acp.acp_client") as launch,
        ):
            self.assertEqual(login_status("gemini")["state"], "signed_out")
            launch.assert_not_called()
            with self.assertRaises(AuthenticationRequired):
                discover_acp_models("gemini")
            launch.assert_not_called()
        with patch(
            "converter.services.acp.node_cli_command", return_value=self.fake("kimi", "signed-out")
        ):
            state = login_status("kimi")
        self.assertEqual(state["state"], "signed_out")
        self.assertNotIn("private account", json.dumps(state))

    def test_gemini_login_uses_only_explicit_authenticate_and_sets_status_marker(self):
        with patch("converter.services.acp.node_cli_command", return_value=self.fake("gemini")):
            login("gemini", lambda: False)
        self.assertEqual([row["method"] for row in self.requests()], ["initialize", "authenticate"])
        self.assertEqual(self.requests()[1]["params"], {"methodId": "oauth-personal"})
        self.assertTrue((profile_path("gemini") / "recalloom-signed-in").is_file())

    def test_connection_deduplicates_cancels_and_allows_explicit_reconnect(self):
        manager = AcpConnection("gemini")
        started = threading.Event()

        def pending(provider, cancelled):
            started.set()
            while not cancelled():
                time.sleep(0.01)

        with (
            patch(
                "converter.services.acp.login_status",
                return_value={"state": "signed_out", "message": "Sign in"},
            ),
            patch("converter.services.acp.login", side_effect=pending) as login_mock,
        ):
            manager.start()
            self.assertTrue(started.wait(2))
            self.assertEqual(manager.start()["state"], "waiting")
            self.assertEqual(login_mock.call_count, 1)
            manager.cancel()
            self.assertFalse(manager._thread.is_alive())
        manager._cached = {"state": "connected", "message": "Connected"}
        manager._checked_at = time.monotonic()
        with patch("converter.services.acp.login", return_value=None) as login_mock:
            manager.start()
            login_mock.assert_not_called()
            manager.start(force=True)
            manager._thread.join(timeout=2)
            login_mock.assert_called_once()

    def test_http_choices_recovery_and_backup_keep_provider_model_and_thinking(self):
        for provider in ("gemini", "kimi"):
            self.catalog(provider)
            with patch(
                f"converter.views.{provider}_connection.status",
                return_value={"state": "signed_out", "message": "Sign in"},
            ):
                response = self.client.get(reverse("provider_connection", args=[provider]))
                self.assertContains(response, "separate local CLI profile")
                if provider == "kimi":
                    self.assertContains(response, 'name="region"')
                    self.assertContains(response, 'value="global"')
            secure = Client(enforce_csrf_checks=True)
            self.assertEqual(
                secure.post(reverse("connect_provider", args=[provider])).status_code, 403
            )
        accepted = self.accepted_card()
        with (
            patch(
                "converter.services.generation.acp_login_status",
                return_value={"state": "connected"},
            ),
            patch("converter.services.generation.launch_worker"),
        ):
            run = start_generation(
                self.lecture, [1], provider="kimi", model="kimi-code/toggle", reasoning_effort="off"
            )
        with patch(
            "converter.services.generation.generate_acp", side_effect=WorkflowError("Interrupted")
        ):
            perform_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        with (
            patch(
                "converter.services.generation.acp_login_status",
                return_value={"state": "connected"},
            ),
            patch("converter.services.generation.launch_worker"),
        ):
            resume_generation(run)
        with patch("converter.services.acp.node_cli_command", return_value=self.fake("kimi")):
            perform_run(run.pk)
        run.refresh_from_db()
        accepted.refresh_from_db()
        self.assertEqual(run.status, "completed")
        self.assertEqual(
            (run.provider, run.model, run.reasoning_effort), ("kimi", "kimi-code/toggle", "off")
        )
        self.assertEqual(accepted.status, "accepted")
        backup = export_backup(self.lecture)
        original = self.lecture.pk
        self.lecture.cards.all().delete()
        self.lecture.delete()
        destination = settings.WORK_DIR / "restored-media"
        destination.mkdir(exist_ok=True)
        with self.settings(MEDIA_ROOT=destination):
            restored = restore_backup(SimpleUploadedFile("backup.zip", backup))
        self.assertEqual(restored.pk, original)
        restored_run = restored.runs.get(pk=run.pk)
        self.assertEqual(
            (restored_run.provider, restored_run.model, restored_run.reasoning_effort),
            ("kimi", "kimi-code/toggle", "off"),
        )
        self.assertEqual(restored.cards.get(pk=accepted.pk).status, "accepted")

    def test_kimi_account_region_reaches_login_and_rejects_invalid_input(self):
        manager = AcpConnection("kimi")
        manager._cached = {"state": "signed_out", "message": "Sign in"}
        manager._checked_at = time.monotonic()
        with (
            patch("converter.views.kimi_connection", manager),
            patch("converter.services.acp.login") as signin,
        ):
            response = self.client.post(
                reverse("connect_provider", args=["kimi"]), {"region": "global"}
            )
            self.assertEqual(response.status_code, 302)
            manager._thread.join(timeout=2)
            self.assertEqual(signin.call_args.kwargs, {"region": "global"})
            signin.reset_mock()
            response = self.client.post(
                reverse("connect_provider", args=["kimi"]), {"region": "global --other"}
            )
            self.assertEqual(response.status_code, 400)
            signin.assert_not_called()
        for region in ("global", "mainland-cn"):
            with (
                patch("converter.services.acp.node_cli_command", return_value=["node", "kimi.mjs"]),
                patch(
                    "converter.services.acp.subprocess.Popen",
                    return_value=Mock(returncode=0, poll=Mock(return_value=0)),
                ) as spawn,
            ):
                login("kimi", lambda: False, region=region)
                self.assertEqual(
                    spawn.call_args.args[0], ["node", "kimi.mjs", "login", "--region", region]
                )
                self.assertNotIn("shell", spawn.call_args.kwargs)

    def test_invalid_metadata_and_legacy_shell_wrappers_fail_closed(self):
        for session in (
            {"models": []},
            {"models": {"availableModels": []}},
            {"models": {"availableModels": [{"modelId": "--shell", "name": "invalid"}]}},
        ):
            with self.assertRaises(WorkflowError):
                model_rows("gemini", session)
        with (
            self.settings(KIMI_BINARY="kimi"),
            patch(
                "converter.services.cli.shutil.which",
                return_value=str(settings.WORK_DIR / "kimi.cmd"),
            ),
            self.assertRaises(WorkflowError),
        ):
            node_cli_command("kimi")
