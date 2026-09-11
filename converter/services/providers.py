"""Two local CLI integrations with provider-reported model capabilities."""

import json
import re
import threading
import time

from django.conf import settings

from .cli import (
    claude_environment,
    claude_executable,
    claude_is_external,
    claude_isolation_args,
    codex_executable,
    metadata_process,
)
from .files import WorkflowError

PROVIDERS = [("codex", "Codex"), ("claude", "Claude Code")]
EFFORTS = [
    ("", "CLI default"),
    ("none", "None"),
    ("minimal", "Minimal"),
    ("low", "Low"),
    ("medium", "Medium"),
    ("high", "High"),
    ("xhigh", "Extra high"),
    ("max", "Max"),
]
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\[\]-]{0,99}\Z")
_refresh_lock = threading.Lock()


def checked_provider(provider):
    if provider not in dict(PROVIDERS):
        raise WorkflowError("Choose Codex or Claude Code.")
    return provider


def checked_model_id(model):
    if not isinstance(model, str) or (model and not MODEL_ID.fullmatch(model)):
        raise WorkflowError("Choose a model from this CLI's model list.")
    return model


def default_model():
    return {"id": "", "label": "CLI default", "efforts": [""], "default_effort": ""}


def normalize_models(rows, provider):
    if not isinstance(rows, list) or not rows or len(rows) > 200:
        raise WorkflowError("The CLI did not return a usable model list.")
    result, seen, default = [], set(), default_model()
    for row in rows:
        if not isinstance(row, dict):
            raise WorkflowError("The CLI returned malformed model metadata.")
        if row.get("hidden"):
            continue
        model = row.get("model") if provider == "codex" else row.get("value")
        if provider == "claude" and model == "default":
            model = ""
        checked_model_id(model)
        label = row.get("displayName") or model or "CLI default"
        if not isinstance(label, str) or not 1 <= len(label) <= 150:
            raise WorkflowError("The CLI returned an invalid model label.")
        levels = (
            row.get("supportedReasoningEfforts", [])
            if provider == "codex"
            else row.get("supportedEffortLevels", [])
        )
        if not isinstance(levels, list):
            raise WorkflowError("The CLI returned invalid reasoning options.")
        if provider == "codex":
            levels = [entry.get("reasoningEffort") for entry in levels if isinstance(entry, dict)]
        if provider == "claude" and row.get("supportsEffort") is False:
            levels = []
        levels = [value for value, _ in EFFORTS if value and value in levels]
        item = {
            "id": model,
            "label": label,
            "efforts": ["", *levels],
            "default_effort": row.get("defaultReasoningEffort", ""),
        }
        if item["default_effort"] not in item["efforts"]:
            item["default_effort"] = ""
        if model == "" or row.get("isDefault"):
            default = {**item, "id": "", "label": "CLI default" + (f" ({label})" if model else "")}
        if model and model not in seen:
            result.append(item)
            seen.add(model)
    if not result:
        raise WorkflowError("No selectable models were returned by this CLI.")
    return [default, *result]


def discover_models(provider):
    checked_provider(provider)
    if provider == "codex":
        command = [
            codex_executable(),
            "-c",
            'model_provider="openai"',
            "--disable",
            "apps",
            "--disable",
            "multi_agent",
            "app-server",
            "--listen",
            "stdio://",
        ]
        with metadata_process(command) as (send, receive):
            send(
                {
                    "id": 1,
                    "method": "initialize",
                    "params": {"clientInfo": {"name": "recalloom", "version": "0.1.0"}},
                }
            )
            initialized = receive(lambda value: value.get("id") == 1)
            if "error" in initialized:
                raise WorkflowError(
                    "Codex could not initialize model discovery. Update Codex and try again."
                )
            send({"method": "initialized", "params": {}})
            rows, cursor = [], None
            for number in range(2, 7):
                send(
                    {
                        "id": number,
                        "method": "model/list",
                        "params": {"limit": 100, "includeHidden": False, "cursor": cursor},
                    }
                )
                response = receive(lambda value: value.get("id") == number).get("result", {})
                rows.extend(response.get("data", []))
                cursor = response.get("nextCursor")
                if not cursor:
                    break
            else:
                raise WorkflowError("Codex returned too many model pages.")
        return normalize_models(rows, provider)
    if claude_is_external():
        raise WorkflowError(
            "Claude Code is configured for an API or another service. Use its normal Claude sign-in for this integration."
        )
    command = [
        claude_executable(),
        "-p",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--verbose",
        *claude_isolation_args(),
    ]
    with metadata_process(command, env=claude_environment()) as (send, receive):
        # Same metadata-only initialize handshake as the official Agent SDK.
        # No user message, query, or model turn is ever submitted here.
        send(
            {
                "type": "control_request",
                "request_id": "models",
                "request": {"subtype": "initialize", "hooks": {}, "agents": {}, "skills": []},
            }
        )
        response = receive(
            lambda value: (
                value.get("type") == "control_response"
                and value.get("response", {}).get("request_id") == "models"
            )
        )
        payload = response.get("response", {}).get("response", {})
        return normalize_models(payload.get("models"), provider)


def catalog_path(provider):
    return settings.DATA_DIR / f"models-{checked_provider(provider)}.json"


def model_catalog(provider):
    path = catalog_path(provider)
    try:
        if path.stat().st_size > 256 * 1024:
            raise ValueError
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data["models"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 201:
            raise ValueError
        for row in rows:
            checked_model_id(row["id"])
            if (
                not isinstance(row["label"], str)
                or len(row["label"]) > 150
                or not isinstance(row["efforts"], list)
                or any(level not in dict(EFFORTS) for level in row["efforts"])
                or row["default_effort"] not in row["efforts"]
            ):
                raise ValueError
        return {
            "models": rows,
            "updated_at": data["updated_at"],
            "message": "Models reported by your local CLI. Account access and organization limits still apply.",
        }
    except (OSError, ValueError, KeyError, TypeError, WorkflowError):
        return {
            "models": [default_model()],
            "updated_at": None,
            "message": "Refresh models to read the choices supported by your local CLI.",
        }


def refresh_models(provider):
    with _refresh_lock:
        try:
            models = discover_models(provider)
        except WorkflowError:
            raise
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise WorkflowError(
                "Could not read the CLI's models. Check its installation and sign-in, then try again."
            ) from exc
        path = catalog_path(provider)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"models": models, "updated_at": time.time()}), encoding="utf-8"
        )
        temporary.replace(path)
    return model_catalog(provider)


def checked_model_settings(provider, model, effort):
    checked_provider(provider)
    checked_model_id(model)
    if effort not in dict(EFFORTS):
        raise WorkflowError("Choose a supported reasoning level.")
    catalog = model_catalog(provider)
    if model or catalog["updated_at"] or provider == "claude":
        item = next((row for row in catalog["models"] if row["id"] == model), None)
        if item is None:
            raise WorkflowError("Refresh models and choose a model supported by this CLI.")
        if effort not in item["efforts"]:
            raise WorkflowError(
                "This model does not support that reasoning level. Choose one of its displayed levels."
            )
    return provider, model, effort
