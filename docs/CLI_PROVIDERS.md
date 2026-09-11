# Local CLI support

Checked 2026-09-11. Recalloom is free software with optional donations. Users connect their own supported AI access; Recalloom does not sell inference or operate a shared account. Local document processing does not make the provider's model inference local.

## Implemented

| Integration | Sign-in | Model and reasoning discovery | Verification |
| --- | --- | --- | --- |
| Codex | Saved CLI authentication; official browser login from the connection screen | App-server initialization followed by `model/list`; no thread or model turn | Actual metadata discovery on 0.153.4; existing ChatGPT sign-in previously checked; earlier live generation on 0.153.0 |
| Claude Code | Saved Claude subscription authentication; `claude auth login` from its separate connection screen | Stream-JSON initialization, using the official SDK's control protocol; no user message | Actual metadata discovery and signed-out status on 2.1.175; simulated login/generation/cancellation/retry checks; real login and inference still pending |

The protocols come from the [Codex app-server reference](https://developers.openai.com/codex/app-server/), [Claude CLI reference](https://code.claude.com/docs/en/cli-reference), and Anthropic's [official SDK initialization implementation](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/_internal/query.py). There is no new SDK dependency: the app invokes native executables with argument arrays and uses their supported authentication stores.

Provider, model, and reasoning are dropdowns. Card formats remain checkboxes; learning focus remains a single visible choice. Model/effort combinations are validated before generation, and provider/model/effort are retained on retry and in version-7 backups. Changing providers clears consent to share the lecture text. No failure silently switches providers.

Models are discovered instead of maintained as a hardcoded list. In this installation, Codex reported Astra/Sol/Terra/Luna plus GPT-5.5; Claude reported its default, Opus, Fable, Sonnet variants, and Haiku aliases. Their reasoning capabilities differed: some included Extra high and Max, while Haiku reported no effort control. These are observations from the installed CLI, not a guarantee of account entitlement, model quality, or the latest provider catalog. Refresh after CLI/account changes. Recognized effort values are default, none, minimal, low, medium, high, xhigh, and max, restricted to what each model reports. Agent-orchestration modes are excluded.

Only sanitized model IDs, labels, effort capabilities, and a refresh timestamp are cached under ignored `data/models-*.json`. Metadata exchanges have bounded time/output and reject host action requests. Refreshing submits no inference prompt; CLIs may contact their provider for metadata or authentication. Passwords, tokens, raw authentication responses, and account details are not cached or included in backups.

Claude generation uses safe mode with custom settings, hooks, memory, normal tools, and MCP integrations disabled. It retains supported subscription login; `--bare` would bypass that login, as explained in [Claude's headless guide](https://code.claude.com/docs/en/headless). Detected custom endpoints/API credentials and Bedrock/Vertex/Foundry profiles are rejected by this integration. It does not change those profiles. Source text goes through stdin; result envelopes and source references are validated separately. Account restrictions and managed CLI policies still apply.

## Other commonly used options researched

These integrations are **not implemented**. Findings concern authentication and integration feasibility, not a generation-quality or cost comparison.

| CLI / provider | Official route found | Fit for a later addition |
| --- | --- | --- |
| Gemini CLI | Google browser sign-in, with existing cached authentication usable in headless mode; Pro/Flash/Auto model choices | A strong next candidate for the same local login experience. Effort controls need their own capability mapping, plus verification of tool/extension isolation and structured output. [Authentication](https://geminicli.com/docs/get-started/authentication/), [model selection](https://geminicli.com/docs/cli/model/) |
| Kimi Code CLI | Official `kimi login` device flow and Kimi account access; the current docs describe the Rust CLI | Another candidate. Its current command protocol, installation path, permissions, and model effort support need a dedicated adapter and tests. [Overview](https://www.kimi.com/code/docs/en/), [command reference](https://www.kimi.com/code/docs/en/kimi-code-cli/reference/kimi-command) |
| DeepSeek | The official Claude Code integration uses a DeepSeek API key and a custom endpoint | This is a separately billed API integration, not evidence that a DeepSeek chat subscription supplies the requested CLI sign-in. Recalloom's Claude subscription adapter intentionally does not enable this route. [Official integration guide](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code/) |
| Qwen Code | Current documentation says Qwen OAuth has been discontinued; it lists coding-plan/token-plan and API-key routes | Do not advertise the former free OAuth login as a working connection option. Reassess if adding explicit API access later. [Current authentication documentation](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/) |

Gemini would be the next integration to evaluate, followed by Kimi. Before adding either, verify native process startup on the supported OS, official sign-in/status/cancellation, metadata discovery without inference, tool restrictions, bounded generation, malformed-output handling, retries preserving edits, and a small explicitly authorized live check. This order is an implementation judgment based on the documented login routes; it is not a commitment to add both before testing the current product.
