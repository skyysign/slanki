# Development handoff

Updated: 2026-09-09. First implementation session.

## What exists

A working local personal-use alpha using Python 3.12, Django 5.2, SQLite, server-rendered pages, and local media. Run start.cmd and open http://127.0.0.1:8000. Setup and checks are in README.md.

- PDF upload: signature check, 25 MB/100-page limits, native text extraction and source rendering in a subprocess with a timeout. Identical uploads reuse the existing lecture. No-text pages are flagged.
- Lecture library and responsive editor with source viewer, manual cards, accept/set-aside, quick Accept & next, persistent edits, optimistic version checks, and revision history.
- Local Codex CLI integration: existing authentication, explicit text-sharing consent, three-page batches, five-minute per-batch timeout, progress, cancellation, and preservation of completed batches. CLI discovery includes the VS Code extension.
- Alternative generation: download a source-text prompt and import JSON drafts from an existing chat. Validation checks page membership and an exact supporting excerpt. Cards remain drafts for human checking.
- Normalized exact-question deduplication preserves existing edits. Paraphrased duplicates still need manual review.
- Anki export: accepted basic Q/A notes, stable GUIDs/model/deck identity, escaped text, bundled source PNGs, and monotonic modification values for same-second edits.
- Per-lecture ZIP backup/restore: PDF, source text/images, all card states and IDs, edit revisions/timestamps, and generation metadata. Restores refuse existing lectures, reject arbitrary/duplicate paths and corrupt assets, validate record structure, and roll back on failure.
- Synthetic sample: three text slides and one image-only page, plus five hand-written drafts. The sample button does not call a model.
- Loopback-only middleware, CSRF protection, restrictive content security policy, local frontend assets, ignored private data, and pinned runtime/development requirements.

## Verification completed

- 17 Django tests passed: source mapping, malformed output, same-document reuse, conflicting edits, interrupted/cancelled generation, export/media identities, backup integrity/rollback, and local-access/CSRF restrictions.
- Anki 26.8.1 Python/Rust backend imported an exported deck into an isolated collection. Re-import and an edited question preserved card ID, interval, due date, review count, and lapse count. Source media had no missing references. This is backend verification, not manual desktop/mobile UI testing.
- Headless Chrome exercised PDF upload, prompt download, JSON draft import, sample reuse, source rendering, edit/accept, Anki and backup downloads, page switching, and desktop/mobile widths. No JavaScript errors or horizontal overflow. Screenshots in data/screenshots/ were visually inspected.
- One live Codex CLI 0.153.0 check used three synthetic pages and the existing sign-in: eight validated drafts. Its isolated data is under data/live-checks/f1a9436e-573c-4d3c-b920-413118704c11/. No personal lectures were sent. This establishes integration, not general card quality.
- Django system and migration-drift checks passed. Dependency consistency checks passed. Ruff lint/format checks are configured in pyproject.toml.

## Next concrete task

Use a real lecture the user needs now. Check extraction, answer quality, missing learning objectives, correction time, and export in the user's actual Anki clients. No real lecture has been supplied yet.

Fix observed failures before expanding scope. If diagrams dominate, the next narrow feature should be manual rectangular source crops attached to basic cards. Simple cloze is another planned follow-up; neither is implemented.

## Limits to preserve in communication

- Personal alpha, not beta/public-release ready. Full gates remain in MVP_BUILD_PLAN.md.
- Native-text PDFs and basic Q/A only. No OCR, diagram interpretation, crops/occlusion, cloze, PPTX, Anki import, scheduler, accounts, payments, native apps, or mobile sync.
- An excerpt matching a page does not establish correctness. No real lecture quality/time-saving benchmark exists.
- The responsive UI remains local to the desktop; another device cannot connect.
- Generation adds drafts; it does not automatically revise accepted notes. Retry remaining pages explicitly after a failure.
- Exports are one-way additions/updates. Setting a card aside does not delete an earlier Anki copy. Backups do not contain Anki review history.
- Restore intentionally refuses existing lectures. Use a different SLIDES_DATA_DIR to inspect an older backup. Limits: 200 MB uncompressed, 100 pages, 10,000 cards, 1,000 generation records, and 1,000 revisions per card.
- Parser isolation is a subprocess plus input/render/time limits, not a hardened public upload service.

## Working notes

- Source lives in config/, converter/, tests/, and tools/. Services remain callable without web views.
- requirements.txt pins runtime dependencies; requirements-dev.txt adds Ruff, fixture generation, Playwright, and the Anki backend. Browser checks use installed Chrome.
- The Codex Windows sandbox cannot use Python TemporaryDirectory paths with their restrictive ACL. Tests and browser/live checks succeeded with normal unsandboxed permissions. Do not weaken application permissions to accommodate this harness.
- SQLite connection context managers commit but do not close. Explicitly close temporary export database connections on Windows.
- Research artifacts remain at the root with their links preserved. They are planning, not production measurements.
