# Status

Updated 2026-11-11. Personal alpha. Main delivery is now the local Windows app `Slanki.exe` (`npm run build:exe`), branch `slanki`. The old Django app (Recalloom) is removed; it is recoverable from the tag `recalloom-django-final`. Snapshot of the 3 real lectures (format-12 backups) in ignored `data/backups/pre-slanki-20261110/`.

## Works

- **Library and lectures.** PDF import in the browser; IndexedDB library; review workspace with keyboard shortcuts; manual cards; "Attach part of slide"; Keep all; Undo.
- **Local app.** `Slanki.exe` is a Node single-executable app (Node 24 + postject) with the web app embedded as SEA assets. It opens the local copy at `http://127.0.0.1:47213` already paired. A second launch just reopens the browser. The AI dialog there offers one-click choices: ChatGPT (Codex) or Claude (Claude Code), each with an Install / Sign in / Use button.
- **Visible text.** The UI no longer mentions Recalloom. Internal names stay: the Anki note-type names, backup format ids and code comments.
- **Making cards.** Three routes: an OpenAI or Anthropic API key used directly from the browser (`app/src/ai/apiKeys.ts`; keys only in localStorage, never in backups), the `npx slanki` helper (Codex, Claude Code), or copy/paste with any chat. The whole lecture is read first; stop and resume are supported.
- **Anki export.** Answers show only the slide. Note identity and schedules are compatible with Recalloom exports.
- **Backups.** Per-lecture and whole-library backups; reads Recalloom backups v1–12.
- **Deployment.** Vercel-ready static build (Node 24, strict CSP, `.vercelignore`).

## Verified

- **Unit tests.** `npm test`: 267 tests, including parity with the frozen Recalloom fixtures.
- **Anki import check.** `tools/check_anki.py` on Anki 26.8.1, including the 2 real lectures with kept cards: schedules preserved and layout updated.
- **Browser tests.** Both workflows pass in Chrome, Firefox and WebKit (Chrome re-run 2026-11-11).
- **Executable.** `Slanki.exe` built on Windows (98 MB). It serves the embedded app, blocks path traversal, pairs, and detected the real signed-in Codex and Claude Code installs (screenshots via `app/e2e/readme-shots.mjs`).
- **Clean deploy check.** A clean-room build of exactly what Vercel would receive passes the browser workflow.

## Not done

- **Releases:** no Vercel deployment, no npm publish, no license chosen. The exe is unsigned (SmartScreen warning) and Windows-only as built; macOS/Linux need `npm run build:exe` on that OS.
- **Untested:**
  - live AI generation through the helper or an API key (the API-key route also needs `https://api.openai.com https://api.anthropic.com` in the CSP `connect-src`, pending approval);
  - real Safari;
  - Anki desktop and mobile apps.
- **Missing features:** Gemini and Kimi are not supported in the helper.

## Next

1. Run one live generation in `Slanki.exe`.
2. Import the backups into the local app, export one lecture, and confirm that reviewed cards keep their schedule in Anki.
