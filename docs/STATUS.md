# Development handoff

Updated: 2026-09-09. Compact generation limits and local course-logistics cleanup.

## What exists

A working local personal-use alpha using Python 3.12, Django 5.2, SQLite, server-rendered pages, and local media. Run start.cmd and open http://127.0.0.1:8000. Setup and checks are in README.md.

- PDF upload: signature check, 25 MB/100-page limits, native text extraction and source rendering in a subprocess with a timeout. Identical uploads reuse the existing lecture. No-text pages are flagged.
- Lecture library and responsive editor with source viewer, manual cards, accept/set-aside, quick Accept & next, persistent edits, optimistic version checks, and revision history.
- Local Codex CLI integration: existing authentication, explicit text-sharing consent, normally three-page batches, five-minute per-batch timeout, progress, cancellation, and preservation of completed batches. CLI discovery includes the VS Code extension.
- Compact generation: new runs default to ceil(selected readable pages / 2) new cards, with a custom 1–500 ceiling. The prompt prioritizes concepts/methods and avoids logistics/repeated numerical examples. Application-side limits apply after validation, logistics filtering, and exact deduplication. Budgets carry forward unused room and reserve room for later pages; small limits widen batches. Runs retain their limit and filter/overflow counts across resume and backups. The download-prompt route uses the same limit.
- New generation sends up to 200 recent existing questions as untrusted context to discourage repeated concepts. Consent and README describe this additional data. Old runs with no saved limit do not send existing questions. Exact deduplication also recognizes the current text of edited questions.
- A conservative English/German local filter removes clear exam/course logistics from generated candidates. Existing untouched drafts can be set aside with a local POST action, retaining IDs and revisions. Accepted/edited cards and restored drafts are protected.
- Generation recovery: invalid individual drafts are retained as visible skipped-draft details while valid drafts and later batches continue. Strict source validation remains in place. Resume continues unprocessed pages of a failed/cancelled run; attempt tokens prevent a cancelled worker from writing late results into a resumed run. Repeated resume submissions do not start duplicate workers.
- Alternative generation: download a source-text prompt and import JSON drafts from an existing chat. Validation checks page membership and an exact supporting excerpt. Cards remain drafts for human checking.
- Normalized exact-question deduplication preserves existing edits. Paraphrased duplicates still need manual review.
- Anki export: accepted basic Q/A notes, stable GUIDs/model/deck identity, escaped text, bundled source PNGs, and monotonic modification values for same-second edits.
- Per-lecture ZIP backup/restore: PDF, source text/images, all card states and IDs, edit revisions/timestamps, and generation metadata. Restores refuse existing lectures, reject arbitrary/duplicate paths and corrupt assets, validate record structure, and roll back on failure.
- Backup format 3 includes card ceilings, selection counts, and skipped-draft details. Formats 1 and 2 remain readable. Worker tokens are transient process ownership and are recreated on restore.
- Synthetic sample: three text slides and one image-only page, plus five hand-written drafts. The sample button does not call a model.
- Loopback-only middleware, CSRF protection, restrictive content security policy, local frontend assets, ignored private data, and pinned runtime/development requirements.

## Verification completed

- 36 Django tests passed, including the existing Anki backend check. New compact-generation tests cover hard ceilings despite excess output, deduplication/logistics before counting, context and budgets sent to the provider boundary, limits across resume, budget reserved for the final short batch, small limits retaining later pages, invalid limits, clinical/subject-matter counterexamples, reversible cleanup with protected edits, and all three backup versions.
- Anki 26.8.1 Python/Rust backend imported an exported deck into an isolated collection. Re-import and an edited question preserved card ID, interval, due date, review count, and lapse count. Source media had no missing references. This is backend verification, not manual desktop/mobile UI testing.
- Headless Chrome exercised PDF upload, prompt download, JSON draft import, sample reuse, source rendering, edit/accept, Anki and backup downloads, page switching, and desktop/mobile widths. Recovery controls, escaped skipped-draft details, and the source-page button were checked with synthetic data. No JavaScript errors or horizontal overflow. The recovery mobile screenshot in data/screenshots/ was visually inspected.
- The browser check additionally filled a custom card limit and verified it in the downloaded prompt, then filtered a synthetic logistics draft and found it recoverable under Set aside. No JavaScript errors or horizontal overflow were reported.
- One live Codex CLI 0.153.0 check used three synthetic pages and the existing sign-in: eight validated drafts. Its isolated data is under data/live-checks/f1a9436e-573c-4d3c-b920-413118704c11/. No personal lectures were sent. This establishes integration, not general card quality.
- Django system and migration-drift checks passed. Dependency consistency checks passed. Ruff lint/format checks are configured in pyproject.toml.
- The user resumed the original real lecture themselves; all 85 pages completed with 98 cards. They reported excessive volume and pointless exam-logistics questions. Before this change there were 89 drafts, 7 accepted, and 2 set aside. A fresh database snapshot and lecture ZIP are under ignored data/backups/before-compact-cards-20260909-195730/. Earlier recovery backups remain intact.
- Migration 0004 was applied and the local app restarted. Two untouched exam-logistics drafts were set aside locally: now 87 drafts, 7 accepted, 4 set aside. Comparison with the snapshot verified all IDs and question/answer/excerpt text were preserved, and all accepted cards were unchanged. The live page returns HTTP 200 and displays the 43-card default. No new lecture generation or live provider check was run during this change.

## Next concrete task

When the user has allowance and explicitly wants another live check, evaluate the compact prompt on a representative selection or a new lecture. Compare coverage of learning objectives and correction effort, not just card count. Do not regenerate this existing lecture expecting its 98 stored notes to shrink: the ceiling governs new additions. Semantic consolidation of an existing deck is not implemented. The existing notes can still be reviewed and set aside locally, and accepted cards exported without model usage.

Fix observed failures before expanding scope. If diagrams dominate, the next narrow feature should be manual rectangular source crops attached to basic cards. Simple cloze is another planned follow-up; neither is implemented.

## Limits to preserve in communication

- Personal alpha, not beta/public-release ready. Full gates remain in MVP_BUILD_PLAN.md.
- Native-text PDFs and basic Q/A only. No OCR, diagram interpretation, crops/occlusion, cloze, PPTX, Anki import, scheduler, accounts, payments, native apps, or mobile sync.
- An excerpt matching a page does not establish correctness. No real lecture quality/time-saving benchmark exists.
- The new compact prompt has only offline provider-boundary tests so far; card quality and allowance savings are unmeasured. Selection is prioritized within batches, not globally across the lecture. Logistics rules are deliberately narrow and can miss paraphrases. The stored note count includes Set aside cards.
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
