# Slanki architecture

Updated 2026-11-10. Slanki replaces the Recalloom Django app. It is a static web app (Vercel Hobby) plus an optional local helper. The Django code stays in the repository, tagged `recalloom-django-final`, as the frozen reference implementation until the user confirms their migrated decks in Anki.

```
slanki.vercel.app: static files only (no Functions, no analytics)
  Browser app (Vite + TypeScript + Preact)
    app/src/core     prompts, schemas, validation, cloze, casefold/fingerprint, logistics,
                     batch math, overview: ports of the Python code with its exact semantics
    app/src/store    IndexedDB library (records keep the backup-manifest field names)
    app/src/pdf      pdf.js text in visual reading order + PNG rendering   [loaded on import]
    app/src/run      generation orchestrator (overview → batches → validate → save)
    app/src/export   PNG codec, Pillow-identical derived images, .apkg writer (sql.js) [loaded on export]
    app/src/backup   reads Recalloom "slides-to-anki" v1–12 and Slanki v1; writes Slanki v1
        ⇅ http://127.0.0.1:47213 (only after pairing / Connect)
Local helper: `npx slanki@1` (helper/, Node ≥ 22.12, no runtime dependencies)
    runs the user's Codex or Claude Code CLI for one prompt at a time and returns its JSON
    also serves the same app at http://127.0.0.1:47213 (Safari / offline fallback)
Without the helper: Make cards → "Use any chat" (copy prompt, paste JSON).
```

## Data flow and privacy

- Vercel serves public assets only. PDFs, page images, cards, backups and model output never go to Vercel.
- Generation sends prompts to the chosen AI, through the user's own CLI login. A prompt contains the selected slide text, the rest of the lecture's text as context for the overview, and up to 200 existing questions. The user consents once per provider.
- The library lives in this browser's IndexedDB. It is persistent (`navigator.storage.persist()` is requested), but it is per-origin and per-device. Backups move it between browsers. The helper-served copy at `127.0.0.1:47213` is a separate origin with its own library.
- AI preferences (provider, model, reasoning, consent) and the helper pairing token are kept in `localStorage`. Lecture content is never put there.

## Helper security model

- Listens only on `127.0.0.1:47213` (fixed, so the local-origin library stays stable). Requires `Host: 127.0.0.1:47213`, which blocks DNS rebinding.
- Accepts an `Origin` only if it is exactly the production app origin (a build constant in `helper/src/main.ts`, overridable for development) or its own origin. Vercel preview URLs are refused. `--allow-origin` exists for development and prints a warning.
- Pairing works like this:
  - The helper prints and opens `<app>/#pair=47213.<code>`. The one-time code expires after 120 s and Enter prints a new one.
  - The app removes the fragment immediately and exchanges the code for the 256-bit token stored in `~/.slanki/helper.json`.
  - `--reset` rotates the token.
- Every API call needs `Authorization: Bearer <token>`. Ten failures within a minute lock the API for a minute.
- Requests must be JSON with exact keys: body ≤ 1 MB, prompt ≤ 200,000 code points, schema ≤ 16 KB. Model IDs and reasoning levels must be ones the CLI reported.
- Jobs:
  - One job runs at a time, at most 60 per hour.
  - Results are kept in memory for 2 hours, at most 20 jobs.
  - A repeated job key returns the same job, so a reloaded tab can resume without paying twice.
  - Results are long-polled for up to 25 s.
- Processes are started from argument arrays with `shell:false` in an empty temporary directory per job. The prompt goes on stdin. Limits: 5-minute timeout, 2 MB output, 5 MB diagnostics. Windows uses `taskkill /T /F`, so stopping kills child processes too. `.cmd` / `.ps1` wrappers are rejected and the native executable is resolved instead.
- Codex and Claude Code run with Recalloom's restrictions:
  - Codex: read-only sandbox, user config ignored, shell/apps/multi-agent/web search disabled.
  - Claude: safe mode, no tools/MCP/hooks/memory/session persistence, sanitized environment, refusal of API-key/Bedrock/Vertex/Foundry setups.
- Logs record method, route, status and duration only, never prompts, outputs or the token.
- Threat model: this protects against websites and other hosts. It does not protect against malware already running as the same user.

## Static site headers (vercel.json)

The CSP is `default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self' http://127.0.0.1:47213; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'`.

Other headers: `no-referrer` and `nosniff`; immutable caching for `/assets/*`, `no-cache` for the page.

pdf.js fonts, CMaps and wasm decoders are served from the app's own origin. `.vercelignore` keeps everything except the app and workspace manifests out of uploads.

## Compatibility contract with Recalloom

Re-exporting an imported lecture updates the same Anki notes and keeps review schedules. These are frozen and golden-tested:

- **Note types:** IDs 1890487183–187, with names, fields, templates, CSS and `req` exactly as genanki wrote them. The legacy names are never rebranded.
- **Identifiers:**
  - The deck ID is the first 6 bytes of `sha256(lecture uuid)`.
  - Note GUIDs use genanki's `guid_for(uuid)`.
  - `notes.mod` is `max(anki_modified, EXPORT_LAYOUT_REVISION)`. `anki_modified` becomes `max(now, prev + 1)` on each change.
- **Answer layout (deliberate change, 2026-11-10):**
  - Below the answer, the Source field shows only the slide, preceded by an attached slide region if the card has one.
  - It no longer shows the lecture title, page number or excerpt text, which only repeated the slide.
  - `EXPORT_LAYOUT_REVISION` (in `app/src/export/anki.ts`) makes Anki update earlier exports once. Card IDs and schedules stay the same.
  - Edits made inside Anki to notes exported before that time are replaced on the next export (export is one-way).
- **Media:**
  - `slides_{lectureHex}_{n}.png` carries the stored page bytes unchanged.
  - Derived crop, occlusion and visual images match Pillow pixel for pixel. Their file names include a content hash, so they change after the port. That is harmless: GUIDs and schedules stay the same.
- **Text rules:**
  - Python code-point lengths and slicing, `str.split`/`strip` whitespace, `casefold`, and Unicode `\w`/`\b` are generated from Python 3.12 tables.
  - Prompts, schemas, batch budgets and the overview are byte-identical to the reference. The one intentional change is the fixed mojibake.
- **Backups:**
  - Slanki v1 uses the Recalloom format-12 record shape and carries study guides, image suggestions and run history verbatim, although they are no longer shown.
  - All Recalloom formats 1–12 can be read.

Golden references live in `tests/fixtures/synthetic/golden/`. `tools/golden.py` generated them from the Django code with every model call mocked. `tools/genanki_ref.py` reproduces the Django exporter without Django, and `tools/check_anki.py` imports decks into a throwaway Anki 26.8.1 collection.

## Not implemented

The following are not implemented:

- Gemini CLI and Kimi Code in the helper (the Django app had adapters for them).
- Image-occlusion drawing and suggestions, graph/formula generation and the study guide (removed by decision; imported notes of these types stay exportable).
- A live AI run with the new helper.
- Checks in real Safari and from the deployed Vercel origin.
