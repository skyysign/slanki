# Working in this repository

## Start here

- Read `docs/STATUS.md` for implemented behavior, verification, and the next task.
- Read `docs/ARCHITECTURE.md` for the Slanki browser app, the local helper, its security model and the Recalloom compatibility contract.
- Use `README.md` for commands.
- User instructions take precedence. Make routine, reversible implementation decisions autonomously within the requested task.

## Product direction

**Slanki** (formerly Recalloom) turns lecture PDFs into source-linked Anki cards in the browser.

- **Delivery.** A static site on Vercel Hobby with an on-device library (IndexedDB). There are no accounts, servers, databases or Vercel Functions.
- **Generation.** Uses the user's own CLI through the local helper `npx slanki` (Codex and Claude Code), or a copy/paste route with any chat.
- **Kept features:**
  - Q/A + cloze (chosen automatically) and optional reverse cards.
  - Automatic whole-lecture overview.
  - Two-pane review with Keep / Set aside / Undo / Keep all, and manual cards.
  - `.apkg` export and lossless backups.
- **Removed from the UI by the user's decision:** the study guide (rundown), image-occlusion drawing and suggestions, graph/formula generation, the learning-focus selector and the format checkboxes. Imported notes of every type still keep their identity and re-export.
- **Deferred:** Gemini/Kimi in the helper, a source-crop editor, an internal SRS, native apps, accounts, billing, OCR and sync.
- **Recalloom.** The old Django app was removed at the user's request; it is recoverable from the tag `recalloom-django-final`. Its behaviour lives on as frozen golden fixtures in `tests/fixtures/synthetic/golden/`.

## Code structure

- **`app/src/core`:** pure ports of the Python services with Python text semantics (code points, `casefold`, `\w`). Keep them free of DOM and IndexedDB access.
- **Persistence and documents:**
  - `app/src/store`: IndexedDB. Schema changes go in a new `oldVersion < N` block in `db.ts`; never edit old blocks.
  - `app/src/backup`: backups. `app/src/export`: Anki packages and images. `app/src/pdf`: pdf.js import.
- **Generation:** `app/src/run` (orchestrator) and `app/src/ai` (helper client and preferences).
- **Interface:** `app/src/ui` holds the Preact screens. Keep business rules out of components.
- **Helper:** `helper/src` contains `server.ts` (HTTP and security), `jobs.ts`, `providers.ts` (CLI integrations) and `processes.ts` (spawning and limits). It has no runtime dependencies.
- **Tools:**
  - `tools/genanki_ref.py` is the Django-free reference exporter.
  - `tools/check_anki.py` is the Anki import gate.
- Prefer explicit data and small functions over frameworks, registries or speculative extension points.

## Data invariants

- **Anki identity:** note-type IDs and names, deck ID, GUIDs, monotonic `anki_modified`, fields and templates follow the contract in `docs/ARCHITECTURE.md`. Never rebrand the legacy note-type names.
- **Records and backups:** records keep the backup-manifest field names. Slanki backups (`slanki` v1) must stay a lossless superset of Recalloom format 12. Keep reading Recalloom formats 1–12.
- **Edits:** every edit goes through `updateNote`: a revision, a version compare-and-set and a bumped `anki_modified`. Note types and cloze numbers are fixed. Generation adds drafts; it never overwrites kept or exported notes.
- **AI output is untrusted.**
  - Validate structure, page membership and exact source excerpts before saving.
  - Overview validation retries are capped at three attempts.
  - Never retry `auth_required`, allowance failures or cancellations.
  - Schema validity does not establish correctness.
- **Partial work:** show unreadable pages, skipped drafts and failures. A partial run must never look complete.
- **Parity with Recalloom:** prompt, validation, budget and export behavior is golden-tested against Recalloom. Change it deliberately, and update the goldens or tests with a stated reason.

## Privacy, helper and security

- Never send lecture data to Vercel or any service other than the provider the user chose.
- Do not loosen the CSP, CORS origin list, Host check, token or pairing rules.
- Do not add Vercel Functions or analytics.
- Lecture text stays out of command lines and shell strings. Use argument arrays, prompts on stdin, disabled tools, and output and time caps.
- Log metadata only, never prompts or outputs.
- Keep credentials with each CLI's own login. Never read or copy authentication files.
- Put real lectures, decks, databases and backups under the ignored `data/` directory. Commit only synthetic fixtures.

## Validation and handoff

- Before editing, inspect the relevant files and Git changes. Preserve the user's work and avoid unrelated refactors.
- Routine checks need no credentials or AI allowance:
  - `npm test`;
  - `npx tsc -p app`;
  - `npx tsc -p helper`;
  - `npm run build` and `npm run size`;
  - the browser workflows in `app/e2e` against `npm run serve`;
  - `tools/check_anki.py` for export changes.
- Live provider checks consume allowance. Run them only when the user asks, and report them separately.
- Verify decks in the user's actual Anki clients before claiming client compatibility.
- At a meaningful stopping point, update `docs/STATUS.md` (what exists, checks actually run, limitations, next step) and `README.md` when commands change.
- Never describe planned features as implemented, synthetic fixtures as real-lecture validation, or unrun checks as passing.
