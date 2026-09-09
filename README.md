# Slides to Anki

A planned local tool for turning lecture PDFs into editable Anki cards with source-slide evidence.

**Current state:** project setup and research only. The converter, browser interface, generation integration, and Anki exporter have not been implemented.

## Resume development

1. Read [the current status](docs/STATUS.md).
2. Follow [the MVP build plan](MVP_BUILD_PLAN.md).
3. Implement the first complete path: one PDF to editable basic cards and an `.apkg` with source media.

[AGENTS.md](AGENTS.md) contains the working conventions for coding assistants.

The initial implementation will use Python, Django, SQLite, local files, and a small browser interface. Scheduling and mobile study will initially happen in Anki. The first supported development environment is Windows with PowerShell.

## Available commands

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

Application installation, run, and test commands will be added when application code exists.

## Files

| File | Purpose |
| --- | --- |
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

An ignored directory is not a backup. The application must implement and verify its own backup/restore workflow before it is used for important study work.
