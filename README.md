# Slides to Anki

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

Anki backend 26.8.1 has been tested for repeated imports, question edits, bundled media, and preservation of an existing review schedule. Manual checks in the desktop/mobile client interfaces and testing with real course lectures remain necessary before beta use.

## Codex generation

Generation uses the installed native Codex CLI and its existing sign-in. The application finds `codex` on PATH or the native CLI bundled with the VS Code Codex extension. It does not request, copy, or store account credentials.

If automatic detection fails, set the native executable path before starting the app:

```powershell
$env:SLIDES_CODEX_BINARY = 'C:\path\to\codex.exe'
.\start.cmd
```

Sign in with that CLI first (`codex login`), and check `codex login status` if generation fails. The tested CLI version is 0.153.0; older versions may not support the required flags. The app ignores the Codex user configuration, excludes repository instruction text, and disables connected apps, shell execution, web search, and multi-agent tools. It uses saved authentication and the CLI's default model; `SLIDES_CODEX_MODEL` can explicitly select a model available to the account.

Before generation, the app asks for consent to send selected slide text through that account. It consumes the account's normal allowance. PDF files and rendered images remain local in this initial text-only route. A source excerpt must match its cited page before a draft is saved; that check does **not** establish answer correctness.

Runs process three pages at a time, saving each completed batch. A batch has a five-minute timeout. **Stop generation** preserves completed drafts. On failure, select the remaining pages and generate again. Exact repeated questions are skipped, and existing notes are not overwritten. Paraphrased duplicates still need manual review.

Technical reference: [official OpenAI documentation for non-interactive Codex](https://developers.openai.com/codex/noninteractive).

## Resume development

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
