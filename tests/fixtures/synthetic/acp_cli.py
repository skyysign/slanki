"""Synthetic ACP peer for offline subprocess/protocol tests; never calls a model."""

import json
import sys
import time
from pathlib import Path

provider, scenario, record = sys.argv[1:4]
if scenario == "blocked-input":
    time.sleep(15)
    sys.exit()
current = "kimi-code/advanced" if provider == "kimi" else "gemini-synthetic"
session_id = "synthetic-session"


def send(value):
    print(json.dumps(value), flush=True)


def configuration():
    return {
        "configOptions": [
            {
                "id": "model",
                "category": "model",
                "type": "select",
                "currentValue": current,
                "options": [
                    {"value": "kimi-code/advanced", "name": "Synthetic reasoning"},
                    {"value": "kimi-code/toggle", "name": "Synthetic thinking toggle"},
                    {"value": "custom/other", "name": "Different service"},
                ],
            },
            {
                "id": "thinking",
                "type": "select",
                "options": [
                    {"value": level, "name": level}
                    for level in (
                        ["low", "high", "max"] if current.endswith("advanced") else ["off", "on"]
                    )
                ],
            },
        ]
    }


for line in sys.stdin:
    request = json.loads(line)
    with Path(record).open("a", encoding="utf-8") as output:
        output.write(json.dumps(request) + "\n")
    method = request.get("method")
    if not method:
        continue
    result = {}
    if method == "initialize":
        result = {"protocolVersion": 1, "agentInfo": {"name": provider, "version": "synthetic"}}
    elif method == "authenticate" and scenario == "signed-out":
        send(
            {
                "jsonrpc": "2.0",
                "id": request["id"],
                "error": {"code": -32000, "message": "private account details must not escape"},
            }
        )
        continue
    elif method == "session/new":
        result = {"sessionId": session_id}
        if provider == "kimi":
            result.update(configuration())
        else:
            result["models"] = {
                "currentModelId": current,
                "availableModels": [{"modelId": current, "name": "Synthetic Gemini"}],
            }
    elif method == "session/set_config_option":
        if request["params"]["configId"] == "model":
            current = request["params"]["value"]
        result = configuration()
    elif method == "session/prompt":
        if scenario == "permission":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": "host-request",
                    "method": "session/request_permission",
                    "params": {"options": []},
                }
            )
            continue
        if scenario == "file-request":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": "host-request",
                    "method": "fs/read_text_file",
                    "params": {"path": "private.txt"},
                }
            )
            continue
        if scenario == "tool-call":
            send(
                {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {"sessionId": session_id, "update": {"sessionUpdate": "tool_call"}},
                }
            )
            continue
        if scenario == "closed":
            sys.exit(1)
        payload = json.loads(Path(__file__).with_name("cards.json").read_text(encoding="utf-8"))
        payload["cards"] = payload["cards"][:1]
        text = (
            json.dumps(payload) if scenario != "malformed-json" else "```json\nnot card JSON\n```"
        )
        target = "wrong-session" if scenario == "wrong-session" else session_id
        for chunk in (text[:17], text[17:]):
            send(
                {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": target,
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": chunk},
                        },
                    },
                }
            )
        result = {"stopReason": "max_tokens" if scenario == "truncated" else "end_turn"}
    send({"jsonrpc": "2.0", "id": request["id"], "result": result})
