# Working in this repository

## Start here

- Read `docs/STATUS.md` for implemented behavior, verification, and the next task.
- Read `MVP_BUILD_PLAN.md` for the current scope and release gates.
- Use `README.md` for commands and the file map. Search the long founder analysis only when a specific decision needs its context.
- User instructions take precedence. Make routine, reversible implementation decisions autonomously within the requested task.

## Product direction

The first product is a local PDF-to-Anki converter with a small browser interface. The user needs it for their own lectures soon. Prioritize a usable end-to-end path and fast correction.

First path: native-text PDF -> source-linked basic card drafts -> accept/edit -> `.apkg` with media. Use Anki for scheduling and mobile study initially.

Current stack choice: Python, Django with server-rendered pages, SQLite, local media, and limited JavaScript for interactive editing. Add dependencies only when an implemented feature needs them. Pin a reproducible dependency set when application setup begins.

Defer an internal SRS, native mobile apps, accounts, billing, course discovery, OCR, automatic acceptance of masks, broad Anki import, and two-way sync. Graph/formula visual questions are a main generation checkbox: editable source crop, optional text covers hidden together on one question, original image revealed on its answer. They share the text-card budget and require explicit acceptance. Label-recall occlusion lives separately in Anatomy & diagrams; manual drawing, one-slide temporary previews, and persistent accept/edit/discard suggestions remain supported. Lecture rundown is a separate source-linked reading guide with saved versions, section-based resume, Markdown download, and no card creation. Backups use format 12 and preserve all of these (reading 1-11). The user authorized local Codex, Claude Code, Gemini CLI, and Kimi Code with model/effort choices. Text generation/rundowns support all four; image attachments currently support Codex only. Cursor and further candidates are researched in docs/CLI_PROVIDERS.md. The build plan contains later milestones; it is not a request to implement them all at once.

The 2026-10-26 workspace redesign is implemented in the local edition: library-first home; Cards/Study guide navigation; compact creation with Q/A+cloze defaults for new lectures; advanced reverse/visual choices; source-context image tools; live previews; keyboard keep/set-aside and version-checked undo. AI preferences alone use tab-scoped sessionStorage. Preserve existing runs and stable note identities. The user confirmed a future Vercel Hobby static browser edition with temporary on-device study data, followed by a persistent desktop edition. See docs/ARCHITECTURE.md: the current Django edition is persistent and not a ready-to-deploy static website. Browser processing/export/session cleanup and paired native generation remain separate milestones. Do not upload lecture data to the host or loosen local CSRF/CSP/origin protections to connect a remote frontend.

## Code structure

- Keep a single application and straightforward modules. Suggested initial layout: `config/` for Django settings, `converter/` for the application, and `tests/fixtures/synthetic/` for reproducible examples. Create these when implementation starts.
- Separate document extraction/rendering, generation/validation, and Anki export from HTTP views. Make those operations usable by commands and tests.
- Keep external generation behind a small replaceable boundary so offline tests can supply saved synthetic output. Build one real integration first.
- Prefer explicit data structures and small functions to general frameworks, provider registries, or speculative extension systems.
- Use migrations for persisted model changes. Preserve existing projects and backups when changing their formats.

## Data invariants

- Every accepted note retains a stable ID, immutable source-document identity, valid page references, and references to any image assets. Store crop coordinates with their page when used.
- Preserve edits. Regeneration creates a draft revision; it must not silently overwrite an accepted or exported note.
- Treat AI output as untrusted data. Validate structure and source references before saving accepted output. Schema validity does not establish factual correctness. Overview generation selects exact excerpt IDs and checkpoints up to 12 pages; preserve valid older partitions on resume/restore. Overview, visual, persisted occlusion and rundown validation retries are capped at three total attempts per request. Do not retry account/allowance errors or bypass evidence checks.
- Show unreadable/skipped pages and generation failures. A partial lecture must not appear fully processed.
- Retain IDs on repeated exports. Test duplicate prevention and preservation of existing Anki scheduling in the supported import workflow.
- Bundle source evidence as media where needed for offline access. Do not depend on expiring URLs for exported card content.
- A converter backup preserves its own notes and source assets; it does not automatically back up reviews conducted in Anki.

## Files, credentials, and generation

- Put real lectures, generated decks, databases, and backups under the ignored `data/` directory. Commit only synthetic fixtures or material explicitly approved for inclusion.
- Keep credentials with the provider's supported authentication mechanism. Do not copy CLI authentication files into this repository, logs, or exported artifacts. Gemini/Kimi use their own separate Recalloom profiles outside the lecture directory.
- Local storage does not imply local model inference. Document what leaves the machine when generation runs.
- Keep document content out of executable instructions and shell command construction. Use bounded parser work, restricted generation permissions, and argument arrays for subprocesses.
- Personal local agent access and hosted generation are separate integrations. Do not assume personal subscription authentication authorizes a shared service.

## Validation and handoff

- Before editing, inspect relevant files and Git changes. Preserve the user's work and avoid unrelated refactors.
- Use existing checks appropriate to the change. Application, browser, Anki backend, and research checks are documented in `README.md`. Live provider checks are separate and consume allowance.
- Prioritize meaningful checks for source mapping, malformed generation output, edits surviving retries, stable export IDs/media, and backup restoration. Do not add tests that merely repeat trivial implementation details.
- Routine tests should run without provider credentials or paid inference. Run live generation only when needed for the authorized task; report it separately from offline tests.
- Verify exported decks in actual Anki clients before claiming compatibility. A successfully constructed archive is not sufficient evidence.
- At a meaningful stopping point, update `docs/STATUS.md` with what exists, checks actually run, limitations, and the next concrete step. Update `README.md` whenever setup/run/test commands change.
- Keep handoffs short. Do not re-open product strategy or read the full research report at the start of every session.
- Never describe planned features as implemented, synthetic fixtures as real lecture validation, or unrun checks as passing.

## Existing research

The `study-srs-*` files and the two research scripts remain at the repository root. Preserve their links. The large founder analysis is historical exploration; `MVP_BUILD_PLAN.md` governs the narrower first build. Cost figures in the research are assumptions, not production measurements.
