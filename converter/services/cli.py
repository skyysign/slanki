"""Native CLI discovery and bounded metadata exchanges; never run a model turn."""

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings

from .files import WorkflowError


def codex_executable():
    executable = shutil.which(settings.CODEX_BINARY)
    if settings.CODEX_BINARY == "codex" and (
        not executable or Path(executable).suffix.lower() in (".cmd", ".bat")
    ):
        candidates = list(
            (Path.home() / ".vscode/extensions").glob("openai.chatgpt-*/bin/windows-*/codex.exe")
        )
        if candidates:
            executable = str(max(candidates, key=lambda path: path.stat().st_mtime))
    if not executable:
        raise WorkflowError(
            "Codex CLI was not found. Install it and sign in, or use Import drafts. See the README for setup."
        )
    if Path(executable).suffix.lower() in (".cmd", ".bat", ".ps1"):
        raise WorkflowError(
            "Set SLIDES_CODEX_BINARY to the native codex.exe, rather than a .cmd wrapper. See the README."
        )
    return executable


def claude_executable():
    executable = shutil.which(settings.CLAUDE_BINARY)
    if settings.CLAUDE_BINARY == "claude":
        candidates = [Path.home() / ".local/bin/claude.exe"]
        if executable:
            # Current npm installations wrap the native executable. Resolve that
            # known package path; never execute a shell wrapper or parse its code.
            candidates.append(
                Path(executable).parent / "node_modules/@anthropic-ai/claude-code/bin/claude.exe"
            )
        executable = next((str(path) for path in candidates if path.is_file()), executable)
    if not executable or Path(executable).suffix.lower() in (".cmd", ".bat", ".ps1"):
        raise WorkflowError(
            "Claude Code was not found as a native executable. Install Claude Code or set SLIDES_CLAUDE_BINARY to claude.exe. See the setup guide."
        )
    return executable


def claude_environment():
    # Each process uses the normal local Claude sign-in. Do not let inherited
    # session toggles change the model/effort or opt into tools and workflows.
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(
            (
                "ANTHROPIC_DEFAULT_",
                "CLAUDE_CODE_EFFORT",
                "CLAUDE_CODE_SUBAGENT",
                "CLAUDE_CODE_EXPERIMENTAL_",
            )
        ) or key in (
            "ANTHROPIC_MODEL",
            "CLAUDE_CODE_SIMPLE",
            "CLAUDE_CODE_BARE",
            "CLAUDECODE",
        ):
            env.pop(key)
    return env


def claude_is_external():
    return any(
        os.environ.get(key)
        for key in (
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "CLAUDE_CODE_USE_BEDROCK",
            "CLAUDE_CODE_USE_VERTEX",
            "CLAUDE_CODE_USE_FOUNDRY",
        )
    )


def claude_isolation_args():
    # --bare deliberately ignores subscription login. --safe-mode retains it.
    return [
        "--safe-mode",
        "--setting-sources",
        "",
        "--settings",
        json.dumps(
            {
                "disableAllHooks": True,
                "autoMemoryEnabled": False,
                "permissions": {"defaultMode": "dontAsk"},
            }
        ),
        "--tools",
        "",
        "--disallowedTools",
        "mcp__*",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--disable-slash-commands",
        "--no-chrome",
        "--no-session-persistence",
    ]


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


@contextmanager
def metadata_process(command, *, env=None, timeout=15):
    """Yield send/receive for metadata only, with bounded time, lines and memory."""
    process = subprocess.Popen(
        command,
        cwd=settings.WORK_DIR,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    incoming = queue.Queue(maxsize=100)
    finished = threading.Event()

    def read():
        total = 0
        try:
            while not finished.is_set():
                line = process.stdout.readline(1024 * 1024 + 1)
                total += len(line)
                if not line or total > 2 * 1024 * 1024 or len(line) > 1024 * 1024:
                    incoming.put_nowait(None)
                    return
                incoming.put_nowait(json.loads(line))
        except (ValueError, OSError, queue.Full):
            finished.set()

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout

    def send(message):
        process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        process.stdin.flush()

    def receive(matches):
        while time.monotonic() < deadline and not finished.is_set():
            try:
                message = incoming.get(timeout=min(0.2, max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                continue
            if not isinstance(message, dict):
                break
            if matches(message):
                return message
            # No host action or approval is part of model discovery.
            if message.get("type") == "control_request" or (
                "method" in message and "id" in message
            ):
                break
        raise WorkflowError(
            "Could not read the CLI's model list. Check its installation and sign-in, then refresh models."
        )

    try:
        yield send, receive
    finally:
        finished.set()
        stop_process(process)
        process.stdin.close()
        reader.join(timeout=2)
        process.stdout.close()
