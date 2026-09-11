"""Reuse Codex's own local sign-in; never read, copy, or return its credentials."""

import atexit
import json
import subprocess
import threading

from django.conf import settings

from .cli import claude_environment, claude_executable, claude_is_external
from .files import WorkflowError
from .generation import codex_executable

LOGIN_TIMEOUT = 10 * 60


def login_status():
    try:
        executable = codex_executable()
    except WorkflowError:
        return {
            "state": "missing",
            "message": "Codex is not installed or could not be found on this computer.",
        }
    try:
        result = subprocess.run(
            [executable, "login", "status"],
            cwd=settings.WORK_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return {
            "state": "unknown",
            "message": "Could not check Codex. Try again or check your Codex installation.",
        }
    # Some CLI versions print part of an API key in status output. Classify it,
    # then discard it. Raw output must never reach a page, log, or backup.
    output = (result.stdout + result.stderr).casefold()
    if result.returncode == 0 and "logged in using chatgpt" in output:
        return {"state": "connected", "message": "Your existing ChatGPT sign-in is ready to use."}
    if result.returncode == 0 and "api key" in output:
        return {
            "state": "api_key",
            "message": "Codex currently uses an API key, billed separately from your ChatGPT subscription.",
        }
    if "not logged in" in output:
        return {
            "state": "signed_out",
            "message": "Connect your ChatGPT account to generate cards with Codex.",
        }
    return {
        "state": "unknown",
        "message": "Codex did not report a recognized sign-in. Check your installation or sign in again.",
    }


def claude_login_status():
    try:
        executable = claude_executable()
    except WorkflowError:
        return {
            "state": "missing",
            "message": "Claude Code is not installed or could not be found on this computer.",
        }
    if claude_is_external():
        return {
            "state": "external",
            "message": "Claude Code is configured for an API or another service. This integration uses your Claude subscription sign-in. Start Recalloom without those API overrides to connect.",
        }
    try:
        result = subprocess.run(
            [executable, "auth", "status"],
            cwd=settings.WORK_DIR,
            env=claude_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if len(result.stdout) > 64 * 1024:
            raise ValueError
        data = json.loads(result.stdout)
        if not isinstance(data, dict):
            raise ValueError
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {
            "state": "unknown",
            "message": "Could not check Claude Code sign-in. Update Claude Code if needed, then try again.",
        }
    # Discard account identifiers and every raw output field after classification.
    if result.returncode == 0 and data.get("loggedIn") is True:
        if data.get("authMethod") in ("claude.ai", "oauth") and data.get("apiProvider") in (
            None,
            "firstParty",
        ):
            return {"state": "connected", "message": "Your saved Claude sign-in is ready to use."}
        return {
            "state": "external",
            "message": "Claude Code reported API or external-provider authentication. Connect with its Claude subscription sign-in for this integration.",
        }
    if data.get("loggedIn") is False:
        return {
            "state": "signed_out",
            "message": "Connect your Claude account to generate cards with Claude Code.",
        }
    return {
        "state": "unknown",
        "message": "Claude Code did not report a recognized sign-in. Check your installation and try again.",
    }


class CodexConnection:
    """One pending login in the single-process local app, bounded and cancellable."""

    def __init__(self, provider="codex"):
        self.provider = provider
        self.label = "Claude Code" if provider == "claude" else "Codex"
        self._lock = threading.RLock()
        self._process = None
        self._timer = None
        self._error = ""

    def _clear_timer(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _stop(self):
        self._clear_timer()
        process, self._process = self._process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

    def _expire(self, process):
        with self._lock:
            if self._process is process:
                self._stop()
                self._error = f"Sign-in timed out. Choose Connect {self.label} to try again."

    def status(self):
        with self._lock:
            if self._process is not None:
                code = self._process.poll()
                if code is None:
                    return {
                        "state": "waiting",
                        "message": f"Finish signing in in the browser window opened by {self.label}, then return here.",
                    }
                self._process = None
                self._clear_timer()
                if code != 0:
                    self._error = (
                        "Sign-in did not finish. Try again and complete the browser sign-in."
                    )
            state = claude_login_status() if self.provider == "claude" else login_status()
            if state["state"] == "connected":
                self._error = ""
            elif self._error:
                return {"state": "failed", "message": self._error}
            return state

    def start(self):
        with self._lock:
            state = self.status()
            if state["state"] in ("connected", "waiting", "missing", "external"):
                return state
            self._error = ""
            try:
                # The supported CLI login opens the official browser flow and
                # stores the resulting sign-in itself. No shell or token copying.
                self._process = subprocess.Popen(
                    [claude_executable(), "auth", "login"]
                    if self.provider == "claude"
                    else [codex_executable(), "login"],
                    cwd=settings.WORK_DIR,
                    env=claude_environment() if self.provider == "claude" else None,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                self._timer = threading.Timer(LOGIN_TIMEOUT, self._expire, args=[self._process])
                self._timer.daemon = True
                self._timer.start()
            except (OSError, WorkflowError):
                self._process = None
                self._error = (
                    f"Could not open {self.label} sign-in. Check its installation and try again."
                )
                return {"state": "failed", "message": self._error}
            return {
                "state": "waiting",
                "message": f"Finish signing in in the browser window opened by {self.label}, then return here.",
            }

    def cancel(self):
        with self._lock:
            self._stop()
            self._error = ""


connection = CodexConnection()
claude_connection = CodexConnection("claude")
atexit.register(connection.cancel)
atexit.register(claude_connection.cancel)
