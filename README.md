# Recalloom

A local tool for turning lecture PDFs into editable Anki cards with source-slide evidence.

**Project direction:** free software supported by optional donations. There are no plans for app subscriptions, paid features, sold generation credits, or a hosted generation service. Users supply their own supported AI access; further expansion will follow demonstrated demand.

**Current state:** a working personal-use alpha. Import a PDF, generate or import basic Q/A and cloze drafts, edit and accept cards beside their source slide, and export an Anki deck with bundled source images. Per-lecture backup and restore are included. Use “Try a sample lecture” to exercise the workflow without spending AI allowance.

This first version supports selectable-text PDFs up to 25 MB and 100 pages. Scans and diagram-only pages are flagged. Generation uses text, not visual interpretation. You can manually attach a rectangular source-image crop to a note. Image occlusion, PPTX, an internal reviewer, and mobile sync are not implemented yet.

## Install and run (Windows / Python 3.12)

From this folder in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\start.cmd
```

Open **http://127.0.0.1:8000**. Once installed, double-click `start.cmd` to start the application again. The launcher applies database migrations and starts the local Django development server. Leave its terminal open; press Ctrl+C to stop it.

The server only accepts loopback connections. This is a single-user desktop application, not a server to expose to a network. A responsive browser layout is included, but connecting from a separate phone is not supported.

Equivalent direct commands:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --insecure --noreload
```

`--insecure` here enables Django's static file serving with `DEBUG=False`; it does not change the application's loopback restriction.

## Make your first deck

1. Open a lecture PDF, or choose **Try a sample lecture**. Re-uploading an identical PDF opens the existing lecture and preserves edits.
2. Open **Create cards**. Tick Q/A, Cloze, or both formats and choose a learning focus. Choose **AI provider**, **Model**, and **Reasoning level** from the dropdowns. Select pages and maximum new Anki cards. Use either **Generate drafts** or **Download prompt**. For the prompt route, ask your existing chat to return the requested JSON, save it as a `.json` file, and use **Import drafts**.
3. Check each draft against its source page, edit it, and choose **Accept & next**. You can also write a card manually. Inputs are plain text.
4. **Preview export** shows the accepted notes and their actual Anki review-card count. **Export to Anki** downloads an `.apkg` of accepted cards. Source-page images are bundled, so they remain available offline in Anki.
5. **Save backup** downloads the original PDF, page images/text, all drafts and accepted/rejected notes, edit history, and generation-run metadata. Restore from the home page into an installation that does not already contain that lecture.

Anki export adds or updates notes using stable identities. Setting a card aside does not delete an earlier copy in Anki. This is one-way content export, not synchronization or an import of reviews from Anki. Local backups do not contain reviews performed in Anki.

Anki backend 26.8.1 has been tested for repeated imports, question edits, bundled media, and preservation of an existing review schedule. The user also reported that the real lecture worked correctly in their Anki client; its version/platform and repeat-import behavior were not specified. Broader desktop/mobile checks remain necessary before beta use.

## Learning focus, formats, and preview

**Learning focus** offers Balanced, Core knowledge, Understanding, and Application as visible single-choice options. Balanced is the starting choice. Focus changes the requested learning task within the same card budget; Application stays within methods/examples supported by the source and does not request invented exercises. **Card formats** has independent Basic Q/A and Cloze checkboxes: tick either one, or both for mixed generation. At least one must be selected. Basic Q/A remains the initial format. These selections apply to generation and downloaded prompts, are saved with CLI runs, and survive resume and backup.

Cloze hides parts of a statement. For example, `Retrieval practice means trying to {{c1::recall}} information from {{c2::memory::where?}}.` produces two Anki cards. Reusing `c1` for both blanks produces one card hiding both together. The app supports flat, non-nested clozes numbered 1–20, with an optional hint after another `::`. Extra explanation is optional. Nested clozes, braces inside a blank, reverse cards, and image occlusion are not supported yet.

Under **Write a card yourself**, choose Cloze, select words in the text, and use **Hide selected text**. Choose the same blank number for grouped blanks. **Preview cards** checks your unsaved text without saving or generating. Existing notes offer **Preview current text**. Reveal each answer to check what Anki will ask. The preview shows content and blank grouping; it is not an embedded Anki client or a scheduler.

One note can produce several Anki review cards. The generation limit now counts those review cards, shared across basic and cloze notes. A cloze candidate that would exceed the remaining budget is excluded as a whole; smaller later candidates can still fit. Sidebar entries show both format and card count. The export button, lecture summary, and **Preview export** show the actual accepted review-card total. Manual edits/imports are outside the generation ceiling.

To preserve scheduling identities, existing note types and the set of cloze numbers cannot be changed through ordinary edits. You can edit their text, answers, hints, and status. Create a new note if you need a different format or number of review cards. This avoids silently replacing an already studied card with another identity.

JSON drafts may include `"note_type": "basic"` or `"note_type": "cloze"`; cloze statements use `front` and optional extra explanation uses `back` (still include it as an empty string if unused). Earlier four-field JSON defaults to basic. Both formats need the same valid page and exact source excerpt for generated/imported drafts.

Mixed basic/cloze export was checked with Anki's 26.8.1 backend: grouped and nonconsecutive cloze numbers, rendered questions/answers, repeated import, edits preserving each card's schedule, and bundled source media. Manual desktop/mobile checks for cloze and crops remain pending. The new focus/format prompts have only offline tests; their generation quality has not been measured with live lectures.

## Source image crops

Open an existing note's **Source image crop** section, tick **Include a source crop on this note**, and drag a rectangle over its source slide. The four pixel fields also let you adjust the rectangle with a keyboard. Tick **Show the crop on the question too** when the image is part of the question; otherwise it appears with the answer. Use **Preview current text**, then **Save changes** or **Accept & next**. To remove a crop, untick Include and save. For a new manual note, add its draft first, then open it to attach a crop.

Each basic or cloze note supports one rectangle on its original source page. Crops are bundled as PNG media in the Anki export alongside the complete source slide. Backups preserve coordinates, placement, and revision history plus the source image used to reconstruct the crop. Editing or removing a crop retains the note's identity. Anki 26.8.1 backend checks cover crop rendering and edited reimports preserving review schedules. Cropping runs locally without model usage; it does not hide image labels or interpret diagrams.

## Delete a set and test the same slides again

Choose **Delete set** in the library or lecture header. The confirmation page offers **Save backup first**, identifies the set and its note/page counts, and requires a confirmation tick before deletion. Deletion removes its notes, history, imported PDF, and rendered source images and stops generation for that set. Downloaded decks, saved backups, and the original PDF outside the app remain available.

Uploading the same PDF afterward creates a fresh set with new note identities. An earlier exported copy remains in Anki; fresh-set exports can therefore coexist with it. Restore a converter backup instead when you want to recover the original identities and edits. If Windows locks source files, the library shows **Retry file cleanup**; the slides can already be imported as a new set. Finish pending cleanup before restoring that deleted set's backup.

## Connect an AI CLI

Choose **AI connections** in the header, then **Codex**, **Claude Code**, **Gemini CLI**, or **Kimi Code**. Choose **Connect**, finish the official browser sign-in, and return to the page; it updates automatically. Each provider uses your own account and its available CLI allowance. Recalloom has no password or API-key field and does not read or copy authentication files. Connecting does not generate cards. See the [Codex authentication guide](https://developers.openai.com/codex/auth), [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference), [Gemini authentication guide](https://geminicli.com/docs/get-started/authentication/), and [Kimi command reference](https://www.kimi.com/code/docs/en/kimi-code-cli/reference/kimi-command).

Codex and Claude reuse their usual local sign-in. **Gemini and Kimi require one sign-in for Recalloom's separate CLI profile**, even if you already use them for coding. Their own CLIs manage those profiles under `~/.recalloom/cli/`, outside the lecture directory. This lets generation disable tools, hooks, and extensions without changing your coding configuration. Gemini's connected status records a completed Recalloom sign-in; it cannot validate expired tokens without contacting authentication services. Use **Sign in again** if generation or model refresh reports an expired connection.

Each provider has a separate connection and pending login. **Stop sign-in** stops only the attempt started here; it never logs out the shared local account. Attempts time out after ten minutes and repeat clicks reuse the pending attempt. Raw authentication output is discarded. The Codex page identifies API-key authentication, which has separate billing. The Claude integration requires normal Claude subscription sign-in and rejects detected API credentials, custom API endpoints, and Bedrock/Vertex/Foundry profiles. It does not rewrite the user's CLI configuration.

Install the chosen CLI separately for this development build. Missing-installation pages link to official setup. Codex discovery checks PATH and the VS Code Codex extension; Claude discovery checks the native installation and the native executable in the current npm package. Gemini/Kimi support their current official native or npm installations. Shell wrappers are not executed; known npm JavaScript entry points run directly through Node. The legacy Python Kimi CLI is not supported.

With Node.js 22.19 or newer installed, you can install the checked Gemini/Kimi versions locally in this project's ignored data directory:

```powershell
npm.cmd install --prefix data/clis --save-exact --ignore-scripts --no-audit --no-fund --registry=https://registry.npmjs.org @google/gemini-cli@0.59.0 @moonshot-ai/kimi-code@0.42.0
```

Recalloom checks `data/clis/node_modules` when the chosen CLI is absent from PATH. This installation does not change global packages. With a custom `SLIDES_DATA_DIR`, install into that directory's `clis` folder instead. To override executable discovery, set only the relevant path before starting Recalloom:

```powershell
$env:SLIDES_CODEX_BINARY = 'C:\path\to\codex.exe'
$env:SLIDES_CLAUDE_BINARY = 'C:\path\to\claude.exe'
$env:SLIDES_GEMINI_BINARY = 'C:\path\to\@google\gemini-cli\bundle\gemini.js'
$env:SLIDES_KIMI_BINARY = 'C:\path\to\@moonshot-ai\kimi-code\dist\main.mjs'
.\start.cmd
```

For troubleshooting, `codex login status` and `claude auth status` check their respective connections. Use Recalloom's connection pages for Gemini/Kimi because their normal terminal commands use a different profile. Kimi's **Account website** choice supports `kimi.ai` (Global), `kimi.com` (Mainland China), or the CLI's default/saved region. Choose the website where you use your account before connecting. PDF import, sample cards, manual editing, JSON import, crops, and export work without any sign-in. A bundled installer remains future work.

## Model and reasoning dropdowns

In **Create cards**, choose the provider, model, and reasoning level. **Refresh models** asks the installed CLI for model metadata without submitting a prompt or starting inference. The first visit refreshes automatically when there is no saved catalog. Refresh again after updating a CLI or changing accounts. Model names and reasoning capabilities come from the installed CLI; account entitlements and organization restrictions can still limit access. The app does not offer every model the provider markets as if it were available to this account.

Reasoning options adjust to the selected model. The recognized levels are CLI default, None, Minimal, Low, Medium, High, Extra high, and Max, plus **Thinking off/on** for Kimi models that report toggles. Each dropdown shows only the controls reported for that model. The checked Gemini ACP interface does not expose a separate thinking control, so its reasoning selector is disabled at **CLI default**. Kimi model names and thinking options are discovered after sign-in; only its managed Kimi Code models are selectable. New lectures request Low when supported; existing lectures reuse their last AI run's selections. Higher levels can take longer and use more allowance. Ultra workflows are not mapped to a reasoning value.

Provider, requested model, effort, focus, and formats are saved with each run and retained on resume and in backups. **CLI default** omits an explicit override; it does not record a resolved model version or effective effort. The legacy `SLIDES_CODEX_MODEL` environment variable remains a fallback when no explicit Codex model is selected; clear it to use the CLI's normal default. Selecting a model in the dropdown takes precedence. Changing providers clears the lecture-sharing confirmation because it changes who receives the text.

Codex runs with user configuration and repository instructions excluded, read-only permissions, and shell/search/apps/delegation disabled. Claude runs with saved authentication, safe mode, custom setting sources/hooks/memory disabled, no ordinary tools, empty MCP configuration, and no session persistence. A temporary working directory contains bounded prompt/output files for each batch and is removed afterward. Claude's `--bare` mode is deliberately avoided because it bypasses subscription authentication. Organization-managed CLI policies may still apply. See [Codex non-interactive execution](https://developers.openai.com/codex/noninteractive) and [Claude headless mode](https://code.claude.com/docs/en/headless).

Generation sends selected extracted text, page numbers, and recent existing questions to the selected provider through its CLI. PDF extraction, source images/crops, editing, storage, backups, and export remain local. This is cloud model inference through the user's own access, not on-device inference or a shared Recalloom generation service. A downloaded prompt cannot configure another chat's model or reasoning; select those in the chat itself.

Gemini and Kimi use bounded ACP subprocesses with disabled host file/terminal capabilities, restricted CLI profiles, no approved tools, and temporary working directories. Source text travels through stdin, and generated JSON must pass the same source checks as Codex/Claude output. These restrictions are application/CLI controls, not an OS sandbox. Their CLIs may retain session history in the separate profile. Lecture backups exclude those profiles and credentials; deleting a lecture does not erase provider-side or CLI session history.

Actual model metadata discovery was checked with Codex 0.153.4 and Claude Code 2.1.175 without inference. Gemini 0.59.0 and Kimi 0.42.0 both passed real ACP initialization and fresh signed-out checks on Windows using Node 24.16.0. Their authenticated model discovery, completed browser login, and live card generation are still pending; synthetic subprocess tests cover those workflows and failure handling. Earlier live Codex checks used the CLI default and did not record effective effort. See [CLI support and researched alternatives](docs/CLI_PROVIDERS.md), including Cursor feasibility and remaining checks.

Before a new generation, the app asks for consent to send selected slide text and up to 200 recent existing questions through that account. The questions help avoid repeating concepts across batches. It consumes the account's normal allowance. PDF files and rendered images remain local in this initial text-only route. A source excerpt must match its cited page before a draft is saved; that check does **not** establish answer correctness. Older runs without a saved card limit do not send existing questions when resumed.

New runs default to a compact ceiling of one card per two selected readable pages, rounded up: 85 pages gives a maximum of 43 new cards. **Maximum new cards** accepts a custom limit from 1 to 500; leaving it blank calculates the ceiling from the actual selection. The limit also appears in downloaded prompts. The application enforces it on live generation even if the model returns too many candidates; manual JSON imports are not capped. This limits additions in one run, not the size of an existing deck. Generating again does not compact or replace existing notes.

The prompt prioritizes core concepts, rules, distinctions, and methods over repeated numerical examples. It asks for one coherent question with a short answer, rather than combining unrelated facts into a long card. Cards are requested in importance order within each batch; there is no global semantic ranking or automatic merging of an existing deck. The ceiling is distributed across batches with unused room carried forward and room reserved for later pages. A smaller deck can omit useful material; neither coverage nor improved quality has been measured with the new prompt yet.

Runs normally process three pages at a time, saving each processed batch. Very small card limits increase the batch size so later pages can still be considered. Batches exceeding 200,000 source characters fail visibly; select fewer pages or raise the limit. A batch has a five-minute timeout. **Stop generation** preserves completed drafts. After an interruption, **Resume remaining pages** continues the original selection and saved limit without repeating saved batches. Resuming retains the provider/model/effort and uses that CLI's current signed-in account and allowance. Exact repeated questions are skipped, including matches to edited questions. Paraphrased duplicates still need manual review.

Course logistics such as exam duration, permitted materials, dates, grading, and staff office hours are excluded by the prompt and a conservative local English/German rule filter. Clear matches are counted separately and never become generated drafts. Subject-matter questions about clinical examinations and concepts such as bond duration are retained. These rules cannot recognize every paraphrase or language. For existing cards, **Set aside logistics drafts** moves matching untouched drafts to **Set aside**, preserving IDs and recording a revision. Accepted and edited cards are left alone; restoring a filtered card to draft prevents repeat automatic cleanup. This cleanup runs locally with no model call.

An invalid generated draft, including “The source excerpt is not present on page…”, appears under **skipped drafts · review details**. Other valid drafts are saved and later pages continue. Inspect the flagged question, answer, and unverified excerpt with **View source page**, then write a corrected card or generate just those pages again. Skipped drafts are excluded from cards and Anki exports; their history remains visible after later runs and is included in backups. A page being processed does not mean every learning objective is covered. Malformed JSON or a provider failure still stops the run and leaves its remaining pages available to resume. Manually imported JSON files remain all-or-nothing so you can correct the file before importing.

Backups use format version 7 to retain the requested model alongside the provider, source crops/revisions, note formats, focus, review-card counters, reasoning, limits, filtering counts, and skipped-draft details. Versions 1–6 remain readable; versions 1–5 have no crops, and versions 1–4 restore as basic notes. Older application versions cannot read version 7 backups. Runs without a recorded model or effort restore with CLI default for the missing field. A backup contains no CLI credentials or account connection, and restoration does not require either CLI to be installed.

Recalloom was previously named Slides to Anki. The rename preserves the backup format marker, Anki note type name/IDs, media names, and `SLIDES_*` environment variables so existing data and re-imports continue to match. Historical research filenames remain unchanged.

Technical reference: [official OpenAI documentation for non-interactive Codex](https://developers.openai.com/codex/noninteractive).

## Resume development

[Distribution direction](docs/DISTRIBUTION.md) describes packaging the local browser app first, a possible desktop window, and an optional hosted static UI with a local companion. PDF/storage/export processing should remain on the user's computer; inference runs at the selected AI provider. These additional distribution modes are proposals, not implemented deployments.

1. Read [the current status](docs/STATUS.md).
2. Follow [the MVP build plan](MVP_BUILD_PLAN.md).
3. Continue from the next concrete task in the status file; do not restart the completed scaffold.

[AGENTS.md](AGENTS.md) contains the working conventions for coding assistants.

The implementation uses Python, Django, SQLite, local files, and a small browser interface. Scheduling and mobile study happen in Anki.

## Development checks

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test tests
.\.venv\Scripts\python.exe -m ruff check config converter tests tools manage.py
.\.venv\Scripts\python.exe -m ruff format --check config converter tests tools manage.py
.\.venv\Scripts\python.exe tools/check_browser.py
```

The browser check needs installed Google Chrome and uses an isolated temporary database, including for confirmed deletion and reimport of synthetic slides. It covers provider/model/effort dropdowns with synthetic metadata, sharing consent, connection pages, tickable card choices, crop dragging, previews, and exports. Screenshots are written under `data/screenshots/`. Both CLI paths are set to nonexistent test paths, so it cannot use real authentication. The Anki backend check uses a temporary collection, never the user's Anki profile. Normal checks do not call a model. Python's temporary directories may require an unsandboxed test run in the Codex Windows environment; this is separate from running the application normally.

For an explicitly live check using three synthetic pages and the existing Codex allowance:

```powershell
.\.venv\Scripts\python.exe tools/check_generation.py --live
```

The live check saves isolated results under `data/live-checks/`. Rebuild the synthetic PDF with `python tools/make_sample.py` using the virtual environment's Python.

## Research commands

These commands operate on the existing research artifacts. They do not start or test the proposed application.

From the repository root, verify the report's structure and links and exercise the calculator:

```powershell
python verify_research_artifacts.py
```

Python and Node.js are required. The existing scripts use their standard libraries and do not require installing project dependencies.

After editing the research sources, regenerate the research artifacts when needed:

```powershell
python build_research_artifacts.py
python verify_research_artifacts.py
```


## Files

| File | Purpose |
| --- | --- |
| [converter/](converter/) | Models, document/generation/export/backup services, browser interface |
| [config/](config/) | Local-only Django settings and routing |
| [tests/](tests/) | Offline workflow and actual Anki backend checks; synthetic fixtures |
| [tools/](tools/) | Browser/live smoke checks and fixture generator |
| [MVP_BUILD_PLAN.md](MVP_BUILD_PLAN.md) | Current implementation order and release checkpoints |
| [docs/STATUS.md](docs/STATUS.md) | Short handoff and verified project state |
| [docs/CLI_PROVIDERS.md](docs/CLI_PROVIDERS.md) | Implemented CLI support, verification, and researched alternatives |
| [study-srs-founder-analysis.md](study-srs-founder-analysis.md) | Original broad product research; consult selectively |
| [study-srs-founder-analysis.html](study-srs-founder-analysis.html) | Browsable research report |
| [study-srs-cost-calculator.html](study-srs-cost-calculator.html) | Interactive calculator using illustrative assumptions |
| [study-srs-cost-model.csv](study-srs-cost-model.csv) | Cost scenarios |
| [build_research_artifacts.py](build_research_artifacts.py) | Research artifact generator |
| [verify_research_artifacts.py](verify_research_artifacts.py) | Research structure and calculator checks |

## Local data

Use `data/` for lecture files, working databases, generated decks, media, and backups. It is ignored by Git. Real lecture documents and Anki packages are also ignored by file extension; explicitly synthetic fixtures may live in `tests/fixtures/synthetic/`.

Keep API keys and provider authentication outside version control. Local processing can still send selected source material to a cloud model when generation is invoked.

An ignored directory is not a backup. Save downloaded backup ZIPs somewhere separate from the working data. A backup restores a lecture into an empty destination without replacing current work. To inspect an older backup separately, set `SLIDES_DATA_DIR` to a different folder before launching the app; the original workspace remains intact.
