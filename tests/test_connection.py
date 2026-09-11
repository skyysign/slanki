import subprocess
from unittest.mock import Mock, patch

from django.test import Client, SimpleTestCase, override_settings
from django.urls import reverse

from converter.services.connection import LOGIN_TIMEOUT, CodexConnection, login_status
from converter.services.files import WorkflowError


@override_settings(ALLOWED_HOSTS=["testserver"])
class ConnectionTests(SimpleTestCase):
    def setUp(self):
        self.connection = CodexConnection()
        self.status = self.enterContext(
            patch(
                "converter.services.connection.login_status", return_value={"state": "signed_out"}
            )
        )
        self.executable = self.enterContext(
            patch(
                "converter.services.connection.codex_executable", return_value="C:/Codex/codex.exe"
            )
        )
        self.launch = self.enterContext(patch("converter.services.connection.subprocess.Popen"))
        self.process = self.launch.return_value
        self.process.poll.return_value = None
        self.timer = self.enterContext(patch("converter.services.connection.threading.Timer"))
        self.addCleanup(self.connection.cancel)

    def test_existing_sign_in_is_reused_without_starting_login(self):
        self.status.return_value = {"state": "connected"}
        self.assertEqual(self.connection.start()["state"], "connected")
        self.launch.assert_not_called()

    def test_missing_cli_does_not_start_a_process(self):
        self.status.return_value = {"state": "missing"}
        self.assertEqual(self.connection.start()["state"], "missing")
        self.launch.assert_not_called()

    def test_browser_login_is_bounded_and_repeated_clicks_reuse_it(self):
        self.assertEqual(self.connection.start()["state"], "waiting")
        self.assertEqual(self.connection.start()["state"], "waiting")
        self.assertEqual(self.connection.status()["state"], "waiting")
        self.launch.assert_called_once()
        args, kwargs = self.launch.call_args
        self.assertEqual(args[0], ["C:/Codex/codex.exe", "login"])
        self.assertFalse(kwargs.get("shell", False))
        for stream in ("stdin", "stdout", "stderr"):
            self.assertEqual(kwargs[stream], subprocess.DEVNULL)
        self.assertEqual(self.timer.call_args.args[0], LOGIN_TIMEOUT)
        self.assertTrue(self.timer.return_value.daemon)
        self.timer.return_value.start.assert_called_once()

    def test_completed_login_updates_status_and_clears_timeout(self):
        self.connection.start()
        self.process.poll.return_value = 0
        self.status.return_value = {"state": "connected"}
        self.assertEqual(self.connection.status()["state"], "connected")
        self.timer.return_value.cancel.assert_called_once()
        self.process.terminate.assert_not_called()

    def test_failed_login_can_be_retried(self):
        self.connection.start()
        self.process.poll.return_value = 1
        self.assertEqual(self.connection.status()["state"], "failed")
        self.process.poll.return_value = None
        self.assertEqual(self.connection.start()["state"], "waiting")
        self.assertEqual(self.launch.call_count, 2)

    def test_launch_errors_are_safe_to_display(self):
        self.launch.side_effect = OSError("private path or credential text")
        state = self.connection.start()
        self.assertEqual(state["state"], "failed")
        self.assertNotIn("private", state["message"])

    def test_timeout_stops_only_the_owned_login_and_allows_retry(self):
        self.connection.start()
        self.connection._expire(self.process)
        self.process.terminate.assert_called_once()
        self.assertEqual(self.connection.status()["state"], "failed")
        self.assertIn("timed out", self.connection.status()["message"])
        next_process = Mock()
        next_process.poll.return_value = None
        self.launch.return_value = next_process
        self.connection.start()
        # A callback from a cancelled timer must not stop a newer login.
        self.connection._expire(self.process)
        next_process.terminate.assert_not_called()
        self.assertEqual(self.connection.status()["state"], "waiting")

    def test_cancel_does_not_log_out_the_shared_account(self):
        self.connection.start()
        self.connection.cancel()
        self.connection.cancel()
        self.process.terminate.assert_called_once()
        self.timer.return_value.cancel.assert_called_once()
        self.assertEqual(self.connection.status()["state"], "signed_out")
        self.launch.assert_called_once()

    def test_unresponsive_login_is_killed_after_a_bounded_wait(self):
        self.connection.start()
        self.process.wait.side_effect = [subprocess.TimeoutExpired("codex", 2), 0]
        self.connection.cancel()
        self.process.kill.assert_called_once()
        self.assertEqual(self.process.wait.call_count, 2)


class LoginStatusTests(SimpleTestCase):
    @patch("converter.services.connection.codex_executable", return_value="codex.exe")
    @patch("converter.services.connection.subprocess.run")
    def test_cli_output_is_classified_without_exposing_credentials(self, run, executable):
        examples = [
            (0, "Logged in using ChatGPT", "connected"),
            (0, "Logged in using an API key - sk-private-example", "api_key"),
            (1, "Not logged in", "signed_out"),
            (1, "unexpected private diagnostic", "unknown"),
        ]
        for code, output, expected in examples:
            with self.subTest(expected=expected):
                run.return_value = subprocess.CompletedProcess([], code, "", output)
                state = login_status()
                self.assertEqual(state["state"], expected)
                self.assertNotIn("private", str(state))
                self.assertEqual(run.call_args.args[0], ["codex.exe", "login", "status"])
                self.assertEqual(run.call_args.kwargs["timeout"], 8)

    @patch("converter.services.connection.codex_executable")
    @patch("converter.services.connection.subprocess.run")
    def test_missing_cli_and_status_failures_are_actionable(self, run, executable):
        executable.side_effect = WorkflowError("private installation path")
        self.assertEqual(login_status()["state"], "missing")
        run.assert_not_called()
        executable.side_effect = None
        executable.return_value = "codex.exe"
        for error in (OSError("private details"), subprocess.TimeoutExpired("codex", 8)):
            run.side_effect = error
            state = login_status()
            self.assertEqual(state["state"], "unknown")
            self.assertNotIn("private", str(state))


@override_settings(ALLOWED_HOSTS=["testserver"])
class ConnectionViewTests(SimpleTestCase):
    @patch("converter.views.connection")
    def test_connection_states_render_and_status_does_not_start_login(self, connection):
        for state in ("connected", "signed_out", "waiting", "missing", "api_key", "failed"):
            with self.subTest(state=state):
                connection.status.return_value = {"state": state, "message": "Safe status"}
                response = self.client.get(reverse("codex_connection"))
                self.assertContains(response, "Recalloom")
                self.assertContains(response, f'data-connection-state="{state}"')
                self.assertEqual(
                    self.client.get(reverse("codex_connection_status")).json(),
                    {"state": state, "message": "Safe status"},
                )
                if state == "missing":
                    self.assertContains(response, "Open the Codex setup guide")
                    self.assertNotContains(response, 'action="/codex/connect/"')
                elif state == "waiting":
                    self.assertContains(response, "Stop sign-in")
                elif state == "connected":
                    self.assertNotContains(response, 'action="/codex/connect/"')
        connection.start.assert_not_called()
        connection.cancel.assert_not_called()

    @patch("converter.views.connection")
    def test_start_and_cancel_require_local_csrf_protected_posts(self, connection):
        protected = Client(enforce_csrf_checks=True)
        for name, method in (
            ("connect_codex", connection.start),
            ("cancel_codex_login", connection.cancel),
        ):
            url = reverse(name)
            self.assertEqual(self.client.get(url).status_code, 405)
            self.assertEqual(protected.post(url).status_code, 403)
            self.assertEqual(self.client.post(url, REMOTE_ADDR="203.0.113.1").status_code, 403)
            method.assert_not_called()
            self.assertRedirects(
                self.client.post(url),
                reverse("provider_connection", args=["codex"]),
                fetch_redirect_response=False,
            )
            method.assert_called_once()
