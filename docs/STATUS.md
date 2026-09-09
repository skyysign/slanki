# Development handoff

Updated: 2026-09-09. Generation recovery after the first real-lecture failure.

## What exists

A working local personal-use alpha using Python 3.12, Django 5.2, SQLite, server-rendered pages, and local media. Run start.cmd and open http://127.0.0.1:8000. Setup and checks are in README.md.

- PDF upload: signature check, 25 MB/100-page limits, native text extraction and source rendering in a subprocess with a timeout. Identical uploads reuse the existing lecture. No-text pages are flagged.
- Lecture library and responsive editor with source viewer, manual cards, accept/set-aside, quick Accept & next, persistent edits, optimistic version checks, and revision history.
- Local Codex CLI integration: existing authentication, explicit text-sharing consent, three-page batches, five-minute per-batch timeout, progress, cancellation, and preservation of completed batches. CLI discovery includes the VS Code extension.
- Generation recovery: invalid individual drafts are retained as visible skipped-draft details while valid drafts and later batches continue. Strict source validation remains in place. Resume continues unprocessed pages of a failed/cancelled run; attempt tokens prevent a cancelled worker from writing late results into a resumed run. Repeated resume submissions do not start duplicate workers.
- Alternative generation: download a source-text prompt and import JSON drafts from an existing chat. Validation checks page membership and an exact supporting excerpt. Cards remain drafts for human checking.
- Normalized exact-question deduplication preserves existing edits. Paraphrased duplicates still need manual review.
- Anki export: accepted basic Q/A notes, stable GUIDs/model/deck identity, escaped text, bundled source PNGs, and monotonic modification values for same-second edits.
- Per-lecture ZIP backup/restore: PDF, source text/images, all card states and IDs, edit revisions/timestamps, and generation metadata. Restores refuse existing lectures, reject arbitrary/duplicate paths and corrupt assets, validate record structure, and roll back on failure.
- Backup format 2 includes skipped-draft details and validates their page references. Format 1 remains readable. Worker tokens are transient process ownership and are recreated on restore.
- Synthetic sample: three text slides and one image-only page, plus five hand-written drafts. The sample button does not call a model.
- Loopback-only middleware, CSRF protection, restrictive content security policy, local frontend assets, ignored private data, and pinned runtime/development requirements.

## Verification completed

- 25 Django tests passed: source mapping, malformed output, same-document reuse, conflicting edits, interrupted/cancelled generation, export/media identities, backup integrity/rollback, and local-access/CSRF restrictions. New recovery checks cover mixed valid/invalid output, later-batch continuation, idempotent resume, late output/errors from cancelled workers, worker startup failure, and old/new backup versions.
- Anki 26.8.1 Python/Rust backend imported an exported deck into an isolated collection. Re-import and an edited question preserved card ID, interval, due date, review count, and lapse count. Source media had no missing references. This is backend verification, not manual desktop/mobile UI testing.
- Headless Chrome exercised PDF upload, prompt download, JSON draft import, sample reuse, source rendering, edit/accept, Anki and backup downloads, page switching, and desktop/mobile widths. Recovery controls, escaped skipped-draft details, and the source-page button were checked with synthetic data. No JavaScript errors or horizontal overflow. The recovery mobile screenshot in data/screenshots/ was visually inspected.
- One live Codex CLI 0.153.0 check used three synthetic pages and the existing sign-in: eight validated drafts. Its isolated data is under data/live-checks/f1a9436e-573c-4d3c-b920-413118704c11/. No personal lectures were sent. This establishes integration, not general card quality.
- Django system and migration-drift checks passed. Dependency consistency checks passed. Ruff lint/format checks are configured in pyproject.toml.
- The user's 85-page real lecture stopped at a nonmatching excerpt on page 59: 57 pages processed and 64 drafts saved. The previous worker discarded the failing batch output, so its exact excerpt could not be inspected. A database snapshot and lecture ZIP were saved under ignored data/backups/before-generation-recovery-20260909-193450/. Migration 0003 was applied and the loopback server restarted. Live resumption of pages 58–85 was blocked by automatic approval review, which requires explicit authorization for sending the remaining private page text to Codex. The generation has not been resumed by the agent; the resume button is available to the user. No new model allowance was consumed by these recovery checks.
- Read-only checks against the running app returned HTTP 200 with “Resume 28 remaining pages”. All 64 saved card IDs, questions, answers, excerpts, states, versions, and Anki modification values matched the pre-migration snapshot. No generation run was active at handoff.

## Next concrete task

Resume the remaining real-lecture pages after explicit user authorization, or let the user click the app's resume button. Check any skipped-draft details. Then evaluate extraction, answer quality, missing learning objectives, correction time, and export in the user's actual Anki clients. A real lecture is now present in ignored local data; its quality and coverage have not been benchmarked.

Fix observed failures before expanding scope. If diagrams dominate, the next narrow feature should be manual rectangular source crops attached to basic cards. Simple cloze is another planned follow-up; neither is implemented.

## Limits to preserve in communication

- Personal alpha, not beta/public-release ready. Full gates remain in MVP_BUILD_PLAN.md.
- Native-text PDFs and basic Q/A only. No OCR, diagram interpretation, crops/occlusion, cloze, PPTX, Anki import, scheduler, accounts, payments, native apps, or mobile sync.
- An excerpt matching a page does not establish correctness. No real lecture quality/time-saving benchmark exists.
- The responsive UI remains local to the desktop; another device cannot connect.
- Generation adds drafts; it does not automatically revise accepted notes. Resume preserves saved batches. Skipped-draft details are historical, not automatically resolved by later attempts; recreate corrected cards manually or select those pages for generation again. Manual JSON imports still fail atomically on any invalid draft.
- Exports are one-way additions/updates. Setting a card aside does not delete an earlier Anki copy. Backups do not contain Anki review history.
- Restore intentionally refuses existing lectures. Use a different SLIDES_DATA_DIR to inspect an older backup. Limits: 200 MB uncompressed, 100 pages, 10,000 cards, 1,000 generation records, and 1,000 revisions per card.
- Parser isolation is a subprocess plus input/render/time limits, not a hardened public upload service.

## Working notes

- Source lives in config/, converter/, tests/, and tools/. Services remain callable without web views.
- requirements.txt pins runtime dependencies; requirements-dev.txt adds Ruff, fixture generation, Playwright, and the Anki backend. Browser checks use installed Chrome.
- The Codex Windows sandbox cannot use Python TemporaryDirectory paths with their restrictive ACL. Tests and browser/live checks succeeded with normal unsandboxed permissions. Do not weaken application permissions to accommodate this harness.
- SQLite connection context managers commit but do not close. Explicitly close temporary export database connections on Windows.
- Research artifacts remain at the root with their links preserved. They are planning, not production measurements.
