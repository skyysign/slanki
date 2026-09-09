# Development handoff

Updated: 2026-09-09.

## Current state

- The user will primarily develop this project with Codex and wants to minimize repeated planning and setup.
- Immediate objective: a local tool useful for the user's own lecture preparation. Follow `MVP_BUILD_PLAN.md`; the broader founder analysis describes later possibilities.
- This repository contains research artifacts and working instructions. There is no application code, dependency manifest, browser application, or exporter yet.
- Local Git has been initialized on `main`. No remote has been configured by this setup.
- `AGENTS.md` defines implementation and handoff conventions; `README.md` indexes the files and actual commands.
- `.gitignore` excludes local lecture data, credentials, generated decks, databases, environments, and browser artifacts. `.gitattributes` defines consistent text line endings.

## Next concrete task

Implement one native-text PDF -> source-linked basic card drafts -> `.apkg` path, then add the source-and-card correction interface.

Start with a small synthetic PDF fixture for reproducible development. No real lecture PDF has been supplied in this workspace yet. Use a real lecture when available to assess usefulness; synthetic success alone cannot establish card quality.

Create the Python/Django project and its dependency manifest only as part of that implementation. Keep document processing, generation validation, and Anki export callable independently from web views. Use SQLite and `data/` for local persistence.

Manual generation through the existing agent environment can establish the first useful deck. The first automated generation route is intended to use the user's local Codex CLI; it has not been installed, configured, or tested as part of this project setup.

## Decisions to preserve

- First input: PDFs with selectable text. PPTX, scans, and advanced visual processing wait unless the user's actual material requires them.
- First output: basic cards with bundled source evidence. Simple cloze and manual crops follow.
- Anki handles scheduling and mobile study initially.
- Stable note IDs, reliable source references, preserved edits, recoverable generation, and working local backups are foundational.
- Anki export and a complete local backup are separate promises. The converter has no Anki review history of its own.
- Defer accounts, subscriptions, hosted inference, native mobile apps, an internal SRS, course discovery, and broad provider support.

## Verification

Environment observed during setup: Python 3.12.10, Node.js 24.16.0, Git 2.54.0.windows.1, and ripgrep 15.2.0. These observations are not application version requirements.

- `python verify_research_artifacts.py` passed: all 17 report topics and the JSON example, report/calculator anchors and local links, and calculator baseline, sensitivity, zero-value, validation, and output checks.
- Git ignore checks passed for representative private documents, generated decks, credentials, databases, environments, and browser artifacts. `.env.example` and synthetic PDF fixtures remain eligible for tracking.
- Local links in the new working documentation resolve correctly.
- The ignore check uses NUL-delimited binary input to Git; text-mode subprocess input on Windows adds carriage returns and produces misleading path matches.

## Known limitations

- No application functionality or real lecture workflow has been tested.
- No Anki client compatibility or card-generation quality has been demonstrated.
- Research costs and quality thresholds are proposed assumptions, not measured production results.
- The earlier report's browser screenshot check did not complete; do not claim visual browser verification.
