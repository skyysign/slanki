# Recalloom

A local tool for turning lecture PDFs into editable Anki cards with source-slide evidence.

**Project direction:** free software supported by optional donations. There are no plans for app subscriptions, paid features, sold generation credits, or a hosted generation service. Users supply their own supported AI access; further expansion will follow demonstrated demand.

**Current state:** a working personal-use alpha. Import a PDF, generate or import basic Q/A, cloze, and optional reverse-card drafts, edit and accept notes beside their source slide, and export an Anki deck with bundled source images. Manual image occlusion can turn hidden slide regions into cards, including on image-only pages. Per-lecture backup and restore are included. Use “Try a sample lecture” to exercise the workflow without spending AI allowance.

This first version supports PDFs up to 25 MB and 100 pages. Automatic Q/A, cloze, and reverse generation uses selectable text; pages without usable text are flagged. Manual source crops and image occlusion work on rendered slides, and Codex can suggest occlusion regions from one selected slide image. Whole-lecture visual generation, PPTX, an internal reviewer, and mobile sync are not implemented yet.

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
2. Open **Create cards**. Tick any combination of Basic Q/A, Cloze, and Basic + reverse, then choose a learning focus. Choose **AI provider**, **Model**, and **Reasoning level** from the dropdowns. Select pages and maximum new Anki cards. Whole-lecture context is on by default: it reads all readable slides to guide cards from your selected pages. Untick it to use selected text only. Use either **Generate drafts** or **Download prompt**. For the prompt route, ask your existing chat to return the requested JSON, save it as a `.json` file, and use **Import drafts**.
3. Check each draft against its source page, edit it, and choose **Accept & next**. You can also write a card manually. Inputs are plain text.
4. **Preview export** shows the accepted notes and their actual Anki review-card count. **Export to Anki** downloads an `.apkg` of accepted cards. Source-page images are bundled, so they remain available offline in Anki.
5. **Save backup** downloads the original PDF, page images/text, all drafts and accepted/rejected notes, edit history, and generation-run metadata. Restore from the home page into an installation that does not already contain that lecture.

Anki export adds or updates notes using stable identities. Setting a card aside does not delete an earlier copy in Anki. This is one-way content export, not synchronization or an import of reviews from Anki. Local backups do not contain reviews performed in Anki.

Anki backend 26.8.1 has been tested for repeated imports, question edits, bundled media, and preservation of an existing review schedule. The user also reported that the real lecture worked correctly in their Anki client; its version/platform and repeat-import behavior were not specified. Broader desktop/mobile checks remain necessary before beta use.

## Learning focus, formats, and preview

**Learning focus** offers Balanced, Core knowledge, Understanding, and Application as visible single-choice options. Balanced is the starting choice. Focus changes the requested learning task within the same card budget; Application stays within methods/examples supported by the source and does not request invented exercises. **Card formats** has independent Basic Q/A, Cloze, and Basic + reverse checkboxes: tick any combination, with at least one selected. Basic Q/A remains the initial format; reverse cards are opt-in. These selections apply to generation and downloaded prompts, are saved with CLI runs, and survive resume and backup. Older saved Mixed runs still mean Q/A + cloze.

Cloze hides parts of a statement. For example, `Retrieval practice means trying to {{c1::recall}} information from {{c2::memory::where?}}.` produces two Anki cards. Reusing `c1` for both blanks produces one card hiding both together. The app supports flat, non-nested clozes numbered 1–20, with an optional hint after another `::`. Extra explanation is optional. Nested clozes and braces inside a blank are not supported.

**Basic + reverse** creates two separately scheduled cards from one note: front → back and back → front. Use short terms, definitions, or clear paired facts for which either side is a useful prompt. Both sides are required and cannot be identical. Under **Write a card yourself**, select Basic + reverse and preview both directions before accepting. Edits update both cards. The generation prompt requests reverse notes only when both directions are supported and unambiguous; that judgment still needs human review. The layout follows Anki's [basic and reversed card behavior](https://docs.ankiweb.net/getting-started.html#note-types), with an additional source field on both answers.

Under **Write a card yourself**, choose Cloze, select words in the text, and use **Hide selected text**. Choose the same blank number for grouped blanks. **Preview cards** checks your unsaved text without saving or generating. Existing notes offer **Preview current text**. Reveal each answer to check what Anki will ask. The preview shows content and blank grouping; it is not an embedded Anki client or a scheduler.

One note can produce several Anki review cards. The generation limit counts one per basic note, two per reverse note, and one per distinct cloze number. It is shared across all selected formats. Oversized candidates are excluded as a whole; smaller later candidates can still fit. Reverse-only generation requires room for at least two cards, and its automatic limit starts at two for short selections. Odd limits may leave one unused slot. Batches reserve room for complete pairs; if the remaining budget cannot fit a note, unprocessed pages remain visible. Sidebar entries, export, and **Preview export** show actual review-card counts. Manual edits/imports are outside the generation ceiling.

To preserve scheduling identities, existing note types and the set of cloze numbers cannot be changed through ordinary edits. You can edit their text, answers, hints, and status. Create a new note if you need a different format or number of review cards. This avoids silently replacing an already studied card with another identity.

JSON drafts may include `"note_type": "basic"`, `"note_type": "cloze"`, or `"note_type": "reversed"`. Cloze statements use `front` and optional extra explanation uses `back` (include an empty string if unused). Reverse notes require nonempty `front` and `back`. Earlier four-field JSON defaults to basic. All formats need a valid page and exact source excerpt for generated/imported drafts. Generation/import selection checks both reverse prompts for exact duplicates and course logistics; swapped pairs do not add another two cards. This is exact-text filtering, not semantic consolidation.

Mixed basic/cloze/reverse export was checked with Anki's 26.8.1 backend: cloze ordinals, both reverse directions, rendered questions/answers, repeated import, edits preserving each card's schedule, and bundled source media. Adding reverse notes preserves existing basic/cloze schedules. Manual desktop/mobile checks for these formats and crops remain pending. The new focus/format prompts have only offline tests; their generation quality has not been measured with live lectures.

Converter backups now use format **10**, which preserves saved lecture overviews as well as image occlusion regions and edit history. Formats 1–9 remain readable. Restore format-10 backups with this version or newer; older Recalloom builds cannot read them.

## Image occlusion

Open **Create cards → Create image occlusion**, choose a source page, and press **Use page**. Draw a rectangle over each label or detail to recall, up to 20 regions per submission. You can also press **Add region** and adjust the four pixel fields with a keyboard. Select a region from the numbered buttons to adjust, preview, or remove it before saving. Image-only slides work here. Manual drawing uses no model or OCR.

For help choosing regions, expand **Suggest regions with AI**. Choose a Codex model and reasoning level, optionally include an existing completed lecture overview, and confirm sharing the selected slide image and text. **Suggest regions** makes one model request and returns up to six labelled suggestions with reasons. **Use suggestion** adds a region to the editor; it does not save a card or replace your existing regions. Adjust its geometry, preview it, then use **Add drafts**. Exact duplicate suggestions select the existing region instead of adding it again. A slide with no useful candidates can return no suggestions.

Image suggestions currently support **Codex only**, through its ChatGPT sign-in. They attach just the selected source PNG and send that page's extracted text plus the overview if selected. They do not run a new lecture overview or send other slide images. Keep the page open while waiting, or use **Stop suggestions**. Requests have the existing five-minute timeout; repeated clicks reuse a running request. Suggestions are temporary previews held by the local server for up to fifteen minutes, lost on restart, and excluded from backups. Only regions saved as notes are backed up. Normal page navigation requests cancellation. If the browser disappears, the local server still enforces the request timeout. A forced server termination can leave its CLI child running; normal shutdown requests cancellation and waits briefly for cleanup. Whole-lecture automatic masking and image-based Q/A generation remain future work.

Drag inside a region to move it; drag any of its eight corner/edge handles to resize it. Regions stay inside the slide and retain at least a two-pixel width and height. Drag empty slide space to add a region, or use **Draw new region** when it overlaps an existing one. **Undo** restores up to 30 region changes in the current page session, including drawing, moving, resizing, and removal. **Escape** cancels an active drag. With the slide focused, arrow keys move the selected region by one source pixel; Shift moves by ten. Mouse and touch input share the same controls. Preview and save after adjusting.

Each region becomes one independent draft note and one Anki card. Only that card's region is hidden; other parts of the slide remain visible. **Preview selected region** shows the actual masked question and revealed answer, with a green outline identifying the answer region. **Add drafts** applies the prompt and optional explanation to all submitted regions. Check and edit each draft before accepting it. Exact regions already represented on that source page are skipped, including previously edited regions, so repeated submission preserves existing work.

An existing image occlusion note has the same move/resize/pixel controls in the lecture editor. **Redraw region** replaces its rectangle; saving retains its ID and Anki review card. Its source page stays fixed. Use **Set aside** when a card should no longer be exported; an earlier copy in Anki remains there. Adding another region creates a new card. Save before changing pages.

Export uses a dedicated note type with bundled PNG question/answer images and the original source slide on the answer. Masks are opaque pixels in the question image; no JavaScript is needed to hide them during study. Edit regions in Recalloom and re-export. These exports do not use Anki's native image-occlusion editor; Anki describes its own [image-occlusion workflow](https://docs.ankiweb.net/editing.html#image-occlusion). Recalloom supports rectangular hide-one/reveal-one cards, without grouped masks or hide-all mode. Source crops belong to the text formats; occlusion uses the full slide.

Actual Anki 26.8.1 backend tests verify rendering/media, repeated imports, mask/text edits preserving separate review schedules, and adding regions without replacing existing cards. Backup restoration retains masks, IDs, revision history, and equivalent export media. Manual desktop/mobile client checks remain pending.

## Source image crops

Open an existing note's **Source image crop** section, tick **Include a source crop on this note**, and drag a rectangle over its source slide. The four pixel fields also let you adjust the rectangle with a keyboard. Tick **Show the crop on the question too** when the image is part of the question; otherwise it appears with the answer. Use **Preview current text**, then **Save changes** or **Accept & next**. To remove a crop, untick Include and save. For a new manual note, add its draft first, then open it to attach a crop.

Each basic, cloze, or reverse note supports one rectangle on its original source page. For reverse notes, the crop appears on both answers, or on both questions when that option is ticked. Crops are bundled as PNG media alongside the complete source slide. Backups preserve coordinates, placement, and revision history plus the source image used to reconstruct the crop. Editing or removing a crop retains the note's identity. Anki 26.8.1 backend checks cover crop rendering and edited reimports preserving review schedules. Cropping runs locally without model usage; it does not hide image labels or interpret diagrams.

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

Text-card generation sends extracted text, page numbers, and recent existing questions to the selected provider through its CLI. With whole-lecture context enabled, this includes text from all readable slides, even pages not selected for cards. Image-occlusion suggestions separately send one selected source PNG and its text to Codex, plus the saved overview when selected, after explicit consent. PDF extraction, rendering, editing, storage, backups, and export run locally. Model inference uses the user's own cloud access, not on-device inference or a shared Recalloom generation service. A downloaded prompt cannot configure another chat's model or reasoning; select those in the chat itself.

Gemini and Kimi use bounded ACP subprocesses with disabled host file/terminal capabilities, restricted CLI profiles, no approved tools, and temporary working directories. Source text travels through stdin, and generated JSON must pass the same source checks as Codex/Claude output. These restrictions are application/CLI controls, not an OS sandbox. Their CLIs may retain session history in the separate profile. Lecture backups exclude those profiles and credentials; deleting a lecture does not erase provider-side or CLI session history.

Actual model metadata discovery was checked with Codex 0.153.4 and Claude Code 2.1.175 without inference. Gemini 0.59.0 and Kimi 0.42.0 both passed real ACP initialization and fresh signed-out checks on Windows using Node 24.16.0. Their authenticated model discovery, completed browser login, and live card generation are still pending; synthetic subprocess tests cover those workflows and failure handling. Earlier live Codex checks used the CLI default and did not record effective effort. See [CLI support and researched alternatives](docs/CLI_PROVIDERS.md), including Cursor feasibility and remaining checks.

Before a new generation, the app asks for consent to send the indicated slide text and up to 200 recent existing questions through that account. Changing the whole-lecture checkbox clears consent and updates its scope. The questions help avoid repeating concepts across batches. Generation consumes the account's normal allowance. PDF files and rendered images remain local in this text-only route. A source excerpt must match its cited page before a draft is saved; that check does **not** establish answer correctness. Older runs without a saved card limit do not send existing questions when resumed.

**Use the whole lecture to guide card selection** is checked for new runs. Before drafting cards, the selected CLI reads all readable slide text and produces a compact overview of core and supporting concepts with source-page links. Typical lectures use one overview request; long lectures are read in sections of up to 120,000 source characters, followed by a request to combine the section notes. Each section has at most eight topics; a combined outline has at most twenty. These requests use the chosen model, reasoning level, and learning focus, and add time and allowance use before cards appear. Progress distinguishes reading the lecture from drafting cards. Expand **Lecture overview** to inspect its summaries and sources.

Each card batch then receives that overview, its own numbered source text, focus/formats, card budget, and recent questions in a fresh request/session. The overview guides priorities and repetition avoidance; it is not evidence for an answer. Cards may cite only their current selected source pages. Quotes in overview topics are checked against their pages, and a combined outline must retain evidence from the saved sections. An invalid overview stops the run visibly before cards are generated. Summaries can still be incomplete or incorrect, so review both the overview and the cards. No images or previous answer conversation are passed to the model.

Completed overview sections are saved with the run and included in backups. Resume reuses them, including when only the combining step failed. Starting a new run creates a new overview. Untick whole-lecture context to use selected text only; runs created before this feature keep that narrower scope when resumed. **Download prompt** includes all selected readable pages together and, when the checkbox is on, adds the remaining readable pages as context only. It makes no model call and does not create a saved overview. Full-lecture downloads above 200,000 characters fail with guidance to use automatic section processing or turn off context.

New runs default to a compact ceiling of one card per two selected readable pages, rounded up: 85 pages gives a maximum of 43 new cards. **Maximum new cards** accepts a custom limit from 1 to 500; leaving it blank calculates the ceiling from the actual selection. The limit also appears in downloaded prompts. The application enforces it on live generation even if the model returns too many candidates; manual JSON imports are not capped. This limits additions in one run, not the size of an existing deck. Generating again does not compact or replace existing notes.

The prompt prioritizes core concepts, rules, distinctions, and methods over repeated numerical examples. It asks for one coherent question with a short answer, rather than combining unrelated facts into a long card. Cards are requested in importance order within each batch; there is no global semantic ranking or automatic merging of an existing deck. The ceiling is distributed across batches with unused room carried forward and room reserved for later pages. A smaller deck can omit useful material; neither coverage nor improved quality has been measured with the new prompt yet.

Runs normally draft cards from three pages at a time, saving each processed batch. Very small card limits increase the batch size so later pages can still be considered. Requests exceeding 200,000 characters, including instructions and context, fail visibly. Each request has a five-minute timeout. **Stop generation** preserves completed overview sections and drafts. After an interruption, **Resume remaining pages** continues the original selection, context setting, and saved limit without repeating saved work. Resuming retains the provider/model/effort and uses that CLI's current signed-in account and allowance. Exact repeated questions are skipped, including matches to edited questions. Paraphrased duplicates still need manual review.

Course logistics such as exam duration, permitted materials, dates, grading, and staff office hours are excluded by the prompt and a conservative local English/German rule filter. Clear matches are counted separately and never become generated drafts. Subject-matter questions about clinical examinations and concepts such as bond duration are retained. These rules cannot recognize every paraphrase or language. For existing cards, **Set aside logistics drafts** moves matching untouched drafts to **Set aside**, preserving IDs and recording a revision. Accepted and edited cards are left alone; restoring a filtered card to draft prevents repeat automatic cleanup. This cleanup runs locally with no model call.

An invalid generated draft, including “The source excerpt is not present on page…”, appears under **skipped drafts · review details**. Other valid drafts are saved and later pages continue. Inspect the flagged question, answer, and unverified excerpt with **View source page**, then write a corrected card or generate just those pages again. Skipped drafts are excluded from cards and Anki exports; their history remains visible after later runs and is included in backups. A page being processed does not mean every learning objective is covered. Malformed JSON or a provider failure still stops the run and leaves its remaining pages available to resume. Manually imported JSON files remain all-or-nothing so you can correct the file before importing.

Format-10 backups retain complete or interrupted overview data and its source-document identity alongside all existing note, source, and run metadata. Versions 1–9 remain readable and restore with whole-lecture context disabled; versions 1–5 have no crops, and versions 1–4 restore as basic notes. Runs without a recorded model or effort restore with CLI default for the missing field. A backup contains no CLI credentials or account connection, and restoration requires no CLI installation. Backups preserve Recalloom content, not reviews performed in Anki.

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

For one explicitly live **image-suggestion** check, using a generated synthetic neuron diagram and no real lecture material:

```powershell
.\.venv\Scripts\python.exe tools/check_occlusion_generation.py --live
```

This uses Codex's requested CLI-default model and Low reasoning; optional `--model` and `--reasoning` flags override them. The isolated folder contains the source PNG, model output, known label bounds, and masked question PNGs for inspection. One check on CLI 0.154.0-alpha.6.2 returned three regions fully covering the three labels. This is an integration/placement check on a simple synthetic diagram, not a real-slide accuracy benchmark.

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
