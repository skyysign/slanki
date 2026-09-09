# Recalloom

A local tool for turning lecture PDFs into editable Anki cards with source-slide evidence.

**Current state:** a working personal-use alpha. Import a PDF, generate or import basic Q/A drafts, edit and accept cards beside their source slide, and export an Anki deck with bundled source images. Per-lecture backup and restore are included. Use “Try a sample lecture” to exercise the workflow without spending AI allowance.

This first version supports selectable-text PDFs up to 25 MB and 100 pages. Scans and diagram-only pages are flagged. Generation uses text, not visual interpretation. Cloze, image crops/occlusion, PPTX, an internal reviewer, and mobile sync are not implemented yet.

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
2. Open **Create cards**. Select pages and use either **Generate drafts** or **Download prompt**. For the prompt route, ask your existing chat to return the requested JSON, save it as a `.json` file, and use **Import drafts**.
3. Check each draft against its source page, edit it, and choose **Accept & next**. You can also write a card manually. Inputs are plain text.
4. **Export to Anki** downloads an `.apkg` of accepted cards. Source-page images are bundled, so they remain available offline in Anki.
5. **Save backup** downloads the original PDF, page images/text, all drafts and accepted/rejected notes, edit history, and generation-run metadata. Restore from the home page into an installation that does not already contain that lecture.

Anki export adds or updates notes using stable identities. Setting a card aside does not delete an earlier copy in Anki. This is one-way content export, not synchronization or an import of reviews from Anki. Local backups do not contain reviews performed in Anki.

Anki backend 26.8.1 has been tested for repeated imports, question edits, bundled media, and preservation of an existing review schedule. The user also reported that the real lecture worked correctly in their Anki client; its version/platform and repeat-import behavior were not specified. Broader desktop/mobile checks remain necessary before beta use.

## Codex generation

Generation uses the installed native Codex CLI and its existing sign-in. The application finds `codex` on PATH or the native CLI bundled with the VS Code Codex extension. It does not request, copy, or store account credentials.

Open **Codex connection** in the header. If Codex already has a ChatGPT sign-in, it is ready to use. Otherwise choose **Connect Codex**, complete the official ChatGPT sign-in in the browser opened by Codex, and return to Recalloom. The page updates when sign-in finishes. This uses Codex's supported `codex login` flow; there is no password or API-key field in Recalloom. Connecting does not run generation. Your account needs Codex access and available allowance. See [OpenAI's authentication guide](https://developers.openai.com/codex/auth).

The page distinguishes an existing API-key sign-in, which is billed separately from a ChatGPT subscription. Sign-in is shared with other local Codex tools. **Stop sign-in** cancels only the pending login started here; it does not log out that shared account. Login attempts time out after ten minutes, and repeated clicks reuse the pending attempt. Status output is reduced to a safe message rather than displayed or stored, since some CLI versions include part of an API key in their output.

This development build still requires Codex to be installed separately. If it is missing, the connection page links to the official setup guide and offers **Check again**. An installer that includes the needed runtime and Codex setup is planned, not implemented. PDF import, sample cards, manual editing, JSON import, and export remain available without a Codex sign-in.

If automatic detection fails, set the native executable path before starting the app:

```powershell
$env:SLIDES_CODEX_BINARY = 'C:\path\to\codex.exe'
.\start.cmd
```

The connection page replaces the need to run `codex login` manually; that command and `codex login status` remain useful for troubleshooting. Live generation was tested with CLI 0.153.0; the current local CLI is 0.153.4. Older versions may not support the required flags. During generation, the app ignores the Codex user configuration, excludes repository instruction text, and disables connected apps, shell execution, web search, and multi-agent tools. It uses saved authentication and the CLI's default model; `SLIDES_CODEX_MODEL` can explicitly select a model available to the account.

**Reasoning level** offers **Codex default**, **Low**, **Medium**, **High**, **Extra high** (`xhigh`), and **Max**. Low is the initial choice for a lecture with no earlier Codex run; otherwise the form reuses its last run's selection. Explicit levels are passed through `-c model_reasoning_effort="..."`. Codex default omits that override. The requested setting is saved in the run, displayed in progress/history, and retained on resume and backup. Higher levels can increase time and allowance use; support depends on the selected model and CLI. The selector applies to **Generate drafts**. A downloaded prompt cannot configure another chat's reasoning setting; select it in that chat instead.

The previously run live checks used Codex's default, without an explicit effort setting; their effective level was not recorded. The earlier and current regression tests use synthetic output without live inference. Local CLI 0.153.4 and its cached model capabilities were inspected without generation when adding this control; its current models advertise Max, with availability varying by model. Ultra can include agent delegation in some Codex surfaces; the converter keeps its single-worker, tools-disabled generation route. See [official reasoning guidance](https://learn.chatgpt.com/docs/agent-configuration/subagents#choosing-models-and-reasoning) and the [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

Before a new generation, the app asks for consent to send selected slide text and up to 200 recent existing questions through that account. The questions help avoid repeating concepts across batches. It consumes the account's normal allowance. PDF files and rendered images remain local in this initial text-only route. A source excerpt must match its cited page before a draft is saved; that check does **not** establish answer correctness. Older runs without a saved card limit do not send existing questions when resumed.

New runs default to a compact ceiling of one card per two selected readable pages, rounded up: 85 pages gives a maximum of 43 new cards. **Maximum new cards** accepts a custom limit from 1 to 500; leaving it blank calculates the ceiling from the actual selection. The limit also appears in downloaded prompts. The application enforces it on live generation even if the model returns too many candidates; manual JSON imports are not capped. This limits additions in one run, not the size of an existing deck. Generating again does not compact or replace existing notes.

The prompt prioritizes core concepts, rules, distinctions, and methods over repeated numerical examples. It asks for one coherent question with a short answer, rather than combining unrelated facts into a long card. Cards are requested in importance order within each batch; there is no global semantic ranking or automatic merging of an existing deck. The ceiling is distributed across batches with unused room carried forward and room reserved for later pages. A smaller deck can omit useful material; neither coverage nor improved quality has been measured with the new prompt yet.

Runs normally process three pages at a time, saving each processed batch. Very small card limits increase the batch size so later pages can still be considered. Batches exceeding 200,000 source characters fail visibly; select fewer pages or raise the limit. A batch has a five-minute timeout. **Stop generation** preserves completed drafts. After an interruption, **Resume remaining pages** continues the original selection and saved limit without repeating saved batches. Resuming uses the same Codex account and allowance. Exact repeated questions are skipped, including matches to edited questions. Paraphrased duplicates still need manual review.

Course logistics such as exam duration, permitted materials, dates, grading, and staff office hours are excluded by the prompt and a conservative local English/German rule filter. Clear matches are counted separately and never become generated drafts. Subject-matter questions about clinical examinations and concepts such as bond duration are retained. These rules cannot recognize every paraphrase or language. For existing cards, **Set aside logistics drafts** moves matching untouched drafts to **Set aside**, preserving IDs and recording a revision. Accepted and edited cards are left alone; restoring a filtered card to draft prevents repeat automatic cleanup. This cleanup runs locally with no model call.

An invalid generated draft, including “The source excerpt is not present on page…”, appears under **skipped drafts · review details**. Other valid drafts are saved and later pages continue. Inspect the flagged question, answer, and unverified excerpt with **View source page**, then write a corrected card or generate just those pages again. Skipped drafts are excluded from cards and Anki exports; their history remains visible after later runs and is included in backups. A page being processed does not mean every learning objective is covered. Malformed JSON or a provider failure still stops the run and leaves its remaining pages available to resume. Manually imported JSON files remain all-or-nothing so you can correct the file before importing.

Backups now use format version 4 to retain the reasoning selection, card limit, filtering counts, and skipped-draft details. Versions 1–3 still restore; older application versions cannot read version 4 backups. Old generation runs restore with Codex default because their effective reasoning level is unknown.

Recalloom was previously named Slides to Anki. The rename preserves the backup format marker, Anki note type name/IDs, media names, and `SLIDES_*` environment variables so existing data and re-imports continue to match. Historical research filenames remain unchanged.

Technical reference: [official OpenAI documentation for non-interactive Codex](https://developers.openai.com/codex/noninteractive).

## Resume development

[Distribution direction](docs/DISTRIBUTION.md) describes packaging the local browser app first, a possible desktop window, and an optional hosted static UI with a local companion. PDF/storage/export processing should remain on the user's computer; Codex inference remains on OpenAI's infrastructure. These additional distribution modes are proposals, not implemented deployments.

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

The browser check needs installed Google Chrome and uses an isolated temporary database. It writes screenshots under `data/screenshots/`. The Anki backend check uses a temporary collection, never the user's Anki profile. Normal checks do not call a model. Python's temporary directories may require an unsandboxed test run in the Codex Windows environment; this is separate from running the application normally.

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
