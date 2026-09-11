"""Bounded Gemini/Kimi ACP sessions. Authentication stays with each CLI."""

import json
import os
import queue
import subprocess
import threading
import time
import tomllib
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings

from .cli import node_cli_command, stop_process
from .files import WorkflowError


class AuthenticationRequired(WorkflowError):
    pass


GEMINI_SETTINGS = {
    # ACP owns the authenticate handshake. Defer the CLI's eager startup login.
    "security": {"auth": {"useExternal": True}},
    "advanced": {"ignoreLocalEnv": True, "autoConfigureMemory": False},
    "tools": {"core": ["recalloom_no_tools"], "allowed": []},
    "hooksConfig": {"enabled": False},
    "skills": {"enabled": False},
    "admin": {"extensions": {"enabled": False}, "mcp": {"enabled": False}},
    "context": {"fileName": [], "includeDirectories": []},
    "general": {"enableAutoUpdate": False},
    "experimental": {"enableAgents": False, "autoMemory": False},
    "telemetry": {"enabled": False},
    "model": {"maxSessionTurns": 3},
}
KIMI_SETTINGS = """# Recalloom profile. Credentials are managed by kimi login.
telemetry = false
hooks = []
merge_all_available_skills = false
[tools]
enabled = ["recalloom_no_tools"]
[[permission.rules]]
decision = "deny"
pattern = "*"
[loop_control]
max_steps_per_turn = 3
max_retries_per_step = 0
[background]
keep_alive_on_exit = false
"""


def profile_path(provider):
    if provider not in ("gemini", "kimi"):
        raise WorkflowError("Unsupported ACP provider.")
    return Path(settings.CLI_PROFILE_ROOT) / provider


def prepare_profile(provider):
    """Create only our profile configuration; never read/copy a credential file."""
    root = profile_path(provider)
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".gemini/settings.json" if provider == "gemini" else root / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as output:
            output.write(json.dumps(GEMINI_SETTINGS) if provider == "gemini" else KIMI_SETTINGS)
    except FileExistsError:
        pass
    # The CLI may add its own managed model/auth references to this configuration.
    # Refuse changed safety settings instead of overwriting user configuration.
    if path.stat().st_size > 256 * 1024:
        raise WorkflowError("The Recalloom CLI profile configuration is too large.")
    try:
        config = (
            json.loads(path.read_text(encoding="utf-8"))
            if provider == "gemini"
            else tomllib.loads(path.read_text(encoding="utf-8"))
        )
        if provider == "gemini":
            valid = (
                config.get("tools", {}).get("core") == ["recalloom_no_tools"]
                and config.get("hooksConfig", {}).get("enabled") is False
                and config.get("security", {}).get("auth", {}).get("selectedType")
                in (None, "oauth-personal")
                and config.get("security", {}).get("auth", {}).get("useExternal") is True
                and config.get("skills", {}).get("enabled") is False
                and config.get("advanced", {}).get("ignoreLocalEnv") is True
            )
        else:
            valid = (
                config.get("tools", {}).get("enabled") == ["recalloom_no_tools"]
                and config.get("hooks", []) == []
                and any(
                    rule.get("decision") == "deny" and rule.get("pattern") == "*"
                    for rule in config.get("permission", {}).get("rules", [])
                )
            )
        if not valid:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise WorkflowError(
            "Recalloom's CLI profile settings have changed. Restore its restricted settings before connecting; your credentials have not been changed."
        ) from exc
    return root


def acp_environment(provider, *, login=False):
    root = profile_path(provider)
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("GEMINI_", "KIMI_")) or key in (
            "NODE_OPTIONS",
            "NODE_PATH",
            "GOOGLE_API_KEY",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "GOOGLE_GENAI_USE_VERTEXAI",
            "GOOGLE_GENAI_USE_GCA",
            "GOOGLE_CLOUD_ACCESS_TOKEN",
            "GOOGLE_GEMINI_BASE_URL",
            "GOOGLE_VERTEX_BASE_URL",
            "CLOUD_SHELL",
            "SANDBOX",
            "NO_BROWSER",
            "BROWSER",
            "BROWSER_CMD",
            "OAUTH_CALLBACK_HOST",
            "OAUTH_CALLBACK_PORT",
        ):
            env.pop(key)
    if provider == "gemini":
        env.update(
            GEMINI_CLI_HOME=str(root), GEMINI_CLI_NO_RELAUNCH="1", GEMINI_TELEMETRY_ENABLED="false"
        )
        if not login:
            env["NO_BROWSER"] = "true"
    else:
        env.update(
            KIMI_CODE_HOME=str(root),
            KIMI_DISABLE_TELEMETRY="1",
            KIMI_DISABLE_CRON="1",
            KIMI_LOG_LEVEL="off",
            KIMI_CODE_BACKGROUND_KEEP_ALIVE_ON_EXIT="0",
            KIMI_CODE_BUILTIN_PRODUCT_SKILLS="0",
        )
    env["NO_COLOR"] = "1"
    return env


def check_cancelled(cancelled):
    if cancelled():
        from .generation import Cancelled

        raise Cancelled()


class AcpClient:
    """One JSON-RPC subprocess; no filesystem/terminal capabilities or approvals."""

    def __init__(self, command, directory, env, *, timeout, cancelled):
        self.process = subprocess.Popen(
            command,
            cwd=directory,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.deadline = time.monotonic() + timeout
        self.cancelled = cancelled
        self.messages = queue.Queue(maxsize=512)
        self.outgoing = queue.Queue(maxsize=2)
        self.closed = threading.Event()
        self.number = 0
        self.session_id = None
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.writer = threading.Thread(target=self._write, daemon=True)
        self.writer.start()

    def _write(self):
        try:
            while not self.closed.is_set():
                try:
                    data = self.outgoing.get(timeout=0.1)
                except queue.Empty:
                    continue
                self.process.stdin.write(data)
                self.process.stdin.flush()
        except (OSError, ValueError):
            self.closed.set()

    def _read(self):
        total = 0
        try:
            while not self.closed.is_set():
                line = self.process.stdout.readline(1024 * 1024 + 1)
                total += len(line)
                if not line or len(line) > 1024 * 1024 or total > 8 * 1024 * 1024:
                    self.messages.put(None, timeout=0.2)
                    return
                value = json.loads(line)
                # Backpressure keeps streamed token output bounded without dropping it.
                while not self.closed.is_set():
                    try:
                        self.messages.put(value, timeout=0.2)
                        break
                    except queue.Full:
                        continue
        except (OSError, ValueError, RecursionError, queue.Full):
            self.closed.set()

    def send(self, message):
        check_cancelled(self.cancelled)
        try:
            self.outgoing.put_nowait((json.dumps(message) + "\n").encode("utf-8"))
        except queue.Full as exc:
            raise WorkflowError("The CLI stopped accepting requests.") from exc

    def request(self, method, params, on_update=None):
        self.number += 1
        request_id = self.number
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while time.monotonic() < self.deadline:
            check_cancelled(self.cancelled)
            try:
                message = self.messages.get(timeout=0.1)
            except queue.Empty:
                if self.closed.is_set():
                    break
                continue
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                break
            if "method" in message and "id" in message:
                # Even read requests may refer to private files outside this lecture.
                if message["method"] == "session/request_permission":
                    self.send(
                        {
                            "jsonrpc": "2.0",
                            "id": message["id"],
                            "result": {"outcome": {"outcome": "cancelled"}},
                        }
                    )
                else:
                    self.send(
                        {
                            "jsonrpc": "2.0",
                            "id": message["id"],
                            "error": {"code": -32601, "message": "Host tools are disabled."},
                        }
                    )
                raise WorkflowError(
                    "The CLI requested a tool while creating cards. No tool was approved; this batch was stopped."
                )
            if message.get("method") == "session/update":
                payload = message.get("params", {})
                if not isinstance(payload, dict):
                    raise WorkflowError("The CLI returned malformed session output.")
                if self.session_id and payload.get("sessionId") != self.session_id:
                    raise WorkflowError("The CLI returned output for a different session.")
                update = payload.get("update", {})
                if not isinstance(update, dict):
                    raise WorkflowError("The CLI returned malformed session output.")
                if update.get("sessionUpdate") in ("tool_call", "tool_call_update"):
                    raise WorkflowError(
                        "The CLI attempted to use a tool. Card generation was stopped."
                    )
                if on_update:
                    on_update(update)
            if message.get("id") == request_id:
                if "error" in message:
                    error = message["error"]
                    if isinstance(error, dict) and error.get("code") == -32000:
                        raise AuthenticationRequired(
                            "Connect this CLI in AI connections before generating or refreshing models."
                        )
                    raise WorkflowError(
                        "The CLI could not complete this request. Check its version, connection, model, and allowance."
                    )
                if "result" not in message:
                    raise WorkflowError("The CLI returned an incomplete protocol response.")
                result = message.get("result")
                if result is None:
                    return {}
                if not isinstance(result, dict):
                    raise WorkflowError("The CLI returned malformed protocol output.")
                return result
        raise WorkflowError(
            "The CLI timed out or closed before finishing. Completed batches are preserved."
        )

    def close(self):
        self.closed.set()
        stop_process(self.process)
        self.writer.join(timeout=2)
        try:
            self.process.stdin.close()
        except OSError:
            pass
        self.reader.join(timeout=2)
        self.process.stdout.close()


@contextmanager
def acp_client(provider, *, timeout=25, cancelled=lambda: False, login=False):
    command = node_cli_command(provider)
    prepare_profile(provider)
    with TemporaryDirectory(dir=settings.WORK_DIR) as directory:
        args = (
            ["--acp", "--extensions", "none", "--allowed-mcp-server-names", "recalloom_no_mcp"]
            if provider == "gemini"
            else ["acp"]
        )
        client = AcpClient(
            [*command, *args],
            directory,
            acp_environment(provider, login=login),
            timeout=timeout,
            cancelled=cancelled,
        )
        try:
            result = client.request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientInfo": {"name": "recalloom", "version": "0.1.0"},
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                        "terminal": False,
                    },
                },
            )
            expected = "gemini" if provider == "gemini" else "kimi"
            agent = result.get("agentInfo")
            name = agent.get("name") if isinstance(agent, dict) else None
            if (
                result.get("protocolVersion") != 1
                or not isinstance(name, str)
                or expected not in name.casefold()
            ):
                raise WorkflowError(
                    "This executable did not identify itself as the selected CLI. Check its installation."
                )
            yield client, directory
        finally:
            client.close()


def new_session(client, directory):
    session = client.request("session/new", {"cwd": str(directory), "mcpServers": []})
    identifier = session.get("sessionId")
    if not isinstance(identifier, str) or not 1 <= len(identifier) <= 200:
        raise WorkflowError("The CLI returned an invalid session identity.")
    client.session_id = identifier
    return session


def login_status(provider):
    try:
        node_cli_command(provider)
    except WorkflowError:
        return {
            "state": "missing",
            "message": f"{provider.title()} CLI is not installed or could not be found on this computer.",
        }
    if not profile_path(provider).exists():
        return {
            "state": "signed_out",
            "message": "Connect your account to Recalloom's separate local CLI profile.",
        }
    if provider == "gemini":
        # Gemini has no side-effect-free authentication-status RPC. Its newSession
        # can start OAuth when credentials expire. GET status must never do that.
        ready = (profile_path(provider) / "recalloom-signed-in").is_file()
        return {
            "state": "connected" if ready else "signed_out",
            "message": "Signed in through Recalloom. Generation will check whether account access is still valid."
            if ready
            else "Sign in to Gemini CLI's Recalloom profile to continue.",
        }
    try:
        with acp_client(provider, timeout=12) as (client, _):
            client.request("authenticate", {"methodId": "login"})
        return {
            "state": "connected",
            "message": "Your CLI sign-in is ready. Model access and allowance still depend on your account.",
        }
    except AuthenticationRequired:
        return {
            "state": "signed_out",
            "message": "Sign in to this CLI's Recalloom profile to continue.",
        }
    except (OSError, WorkflowError):
        return {
            "state": "unknown",
            "message": "Could not verify this CLI connection. Check its installation or reconnect.",
        }


def login(provider, cancelled, *, region=""):
    if region not in ("", "global", "mainland-cn") or (region and provider != "kimi"):
        raise WorkflowError("Choose a supported Kimi account website.")
    prepare_profile(provider)
    if provider == "gemini":
        # An expired saved selection makes this CLI try OAuth before ACP starts.
        # Reset only our profile's auth-method preference for explicit reconnect;
        # the CLI remains solely responsible for its credential store.
        path = profile_path(provider) / ".gemini/settings.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config["security"]["auth"].pop("selectedType", None)
        path.write_text(json.dumps(config), encoding="utf-8")
        with acp_client(provider, timeout=600, cancelled=cancelled, login=True) as (client, _):
            client.request("authenticate", {"methodId": "oauth-personal"})
        (profile_path(provider) / "recalloom-signed-in").write_text(
            "Authentication completed through the CLI.\n", encoding="utf-8"
        )
        return
    with TemporaryDirectory(dir=settings.WORK_DIR) as directory:
        process = subprocess.Popen(
            [*node_cli_command(provider), "login", *(["--region", region] if region else [])],
            cwd=directory,
            env=acp_environment(provider, login=True),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + 600
        try:
            while process.poll() is None:
                check_cancelled(cancelled)
                if time.monotonic() > deadline:
                    raise WorkflowError("Sign-in timed out. Connect again to retry.")
                time.sleep(0.1)
            if process.returncode != 0:
                raise WorkflowError("Sign-in did not finish. Retry the official browser sign-in.")
        finally:
            stop_process(process)


def config_options(session):
    options = session.get("configOptions", [])
    if (
        not isinstance(options, list)
        or len(options) > 30
        or any(not isinstance(item, dict) for item in options)
    ):
        raise WorkflowError("The CLI returned invalid model settings.")
    return options


def kimi_efforts(session):
    from .providers import EFFORTS

    thinking = next(
        (item for item in config_options(session) if item.get("id") == "thinking"), None
    )
    if not thinking:
        return [""]
    rows = thinking.get("options", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise WorkflowError("Kimi returned invalid thinking choices.")
    values = [row.get("value") for row in rows]
    return ["", *[value for value, _ in EFFORTS if value and value in values]]


def model_rows(provider, session):
    from .providers import checked_model_id

    if provider == "gemini":
        model_data = session.get("models", {})
        if not isinstance(model_data, dict):
            raise WorkflowError("Gemini returned invalid model metadata.")
        rows = model_data.get("availableModels", [])
        current = model_data.get("currentModelId")
        choices = (
            [(row.get("modelId"), row.get("name")) for row in rows if isinstance(row, dict)]
            if isinstance(rows, list)
            else []
        )
    else:
        option = next(
            (item for item in config_options(session) if item.get("category") == "model"), {}
        )
        rows = option.get("options", [])
        current = option.get("currentValue")
        choices = (
            [(row.get("value"), row.get("name")) for row in rows if isinstance(row, dict)]
            if isinstance(rows, list)
            else []
        )
    if not 1 <= len(choices) <= 40:
        raise WorkflowError(
            "This CLI did not return a usable model list. Sign in and update it if needed."
        )
    result = []
    for model, label in choices:
        checked_model_id(model)
        if not model or not isinstance(label, str) or not 1 <= len(label) <= 150:
            raise WorkflowError("The CLI returned invalid model metadata.")
        # Never route Kimi consent through a custom model provider.
        if provider == "kimi" and not model.startswith("kimi-code/"):
            continue
        result.append({"id": model, "label": label, "efforts": [""], "default_effort": ""})
    if current not in [row["id"] for row in result]:
        raise WorkflowError(
            "The CLI's default model is not available through this account integration."
        )
    return result, current


def select_kimi_model(client, model):
    return client.request(
        "session/set_config_option",
        {"sessionId": client.session_id, "configId": "model", "value": model},
    )


def discover_acp_models(provider):
    if not profile_path(provider).exists():
        raise AuthenticationRequired("Connect this CLI in AI connections, then refresh models.")
    if provider == "gemini" and not (profile_path(provider) / "recalloom-signed-in").is_file():
        raise AuthenticationRequired("Connect Gemini CLI in AI connections, then refresh models.")
    with acp_client(provider, timeout=35) as (client, directory):
        session = new_session(client, directory)
        rows, current = model_rows(provider, session)
        if provider == "kimi":
            for row in rows:
                row["efforts"] = kimi_efforts(select_kimi_model(client, row["id"]))
        default = next(row for row in rows if row["id"] == current)
        return [{**default, "id": "", "label": "CLI default"}, *rows]


def generate_acp(
    provider,
    pages,
    cancelled=lambda: False,
    *,
    card_limit=None,
    existing_questions=(),
    reasoning_effort="",
    learning_focus="balanced",
    card_format="basic",
    model="",
):
    from .generation import prompt_for
    from .providers import checked_model_settings

    checked_model_settings(provider, model, reasoning_effort)
    if sum(len(page.text) for page in pages) > 200000:
        raise WorkflowError(
            "This batch contains too much text. Select fewer pages or raise the card limit."
        )
    with acp_client(provider, timeout=settings.GENERATION_TIMEOUT, cancelled=cancelled) as (
        client,
        directory,
    ):
        session = new_session(client, directory)
        rows, current = model_rows(provider, session)
        chosen = model or current
        if chosen not in [row["id"] for row in rows]:
            raise WorkflowError(
                "The saved model is no longer available. Refresh models before starting a new run."
            )
        if provider == "kimi":
            selected = select_kimi_model(client, chosen)
            if reasoning_effort not in kimi_efforts(selected):
                raise WorkflowError("Kimi no longer reports support for the saved thinking level.")
            if reasoning_effort:
                client.request(
                    "session/set_config_option",
                    {
                        "sessionId": client.session_id,
                        "configId": "thinking",
                        "value": reasoning_effort,
                    },
                )
        elif model:
            client.request("session/set_model", {"sessionId": client.session_id, "modelId": model})
        chunks, size = [], 0

        def collect(update):
            nonlocal size
            if update.get("sessionUpdate") == "agent_message_chunk":
                content = update.get("content", {})
                if (
                    not isinstance(content, dict)
                    or content.get("type") != "text"
                    or not isinstance(content.get("text"), str)
                ):
                    raise WorkflowError("The CLI returned non-text card output.")
                size += len(content["text"])
                if size > 2 * 1024 * 1024:
                    raise WorkflowError("The CLI returned too much card output.")
                chunks.append(content["text"])

        text = prompt_for(
            pages,
            card_limit,
            existing_questions,
            learning_focus=learning_focus,
            card_format=card_format,
        )
        result = client.request(
            "session/prompt",
            {"sessionId": client.session_id, "prompt": [{"type": "text", "text": text}]},
            collect,
        )
        if result.get("stopReason") != "end_turn":
            raise WorkflowError(
                "The CLI stopped before completing this batch. Completed batches are preserved."
            )
        try:
            payload = json.loads("".join(chunks))
            if not isinstance(payload, dict):
                raise ValueError
            return payload
        except ValueError as exc:
            raise WorkflowError(
                "The CLI did not return valid card JSON. No drafts from this batch were imported."
            ) from exc
