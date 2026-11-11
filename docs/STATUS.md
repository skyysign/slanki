# Status

Updated 2026-11-11. Personal alpha. Main delivery is now the local Windows app `Slanki.exe` (`npm run build:exe`), branch `main`. The old Django app (Recalloom) is removed; it is recoverable from the tag `recalloom-django-final`. Snapshot of the 3 real lectures (format-12 backups) in ignored `data/backups/pre-slanki-20261110/`.

## Works

- **Library and lectures.** PDF import in the browser; delete a lecture from the home page (trash button, same confirmation as in the lecture); IndexedDB library; review workspace with keyboard shortcuts; manual cards; "Attach part of slide"; Keep all; Undo.
- **Local app.** `Slanki.exe` is a Node single-executable app (Node 24 + postject) with the web app embedded as SEA assets, the Slanki icon and version info (rcedit), and the Windows GUI subsystem, so no console window appears. It opens the local copy at `http://127.0.0.1:47213` already paired. It logs metadata to `~/.slanki/slanki.log` and shows startup errors in a message box. Open tabs ping `/v1/ping` every minute; after 5 minutes without requests, with no job or sign-in running, it exits. A second launch of the same version asks the running copy for a fresh pairing code (`/v1/pairing-code`, token required) and reopens the browser. A different version replaces the running copy: `/v1/shutdown` (token required), or for copies up to 0.2.1 it ends the process listening on the port, found through netstat by remote address `0.0.0.0:0` because the state column is localized. Tested 0.2.1 → 0.2.2 on Windows (German). `npm run build:exe -- --console` keeps a console for debugging. The AI dialog there offers one-click choices: ChatGPT (Codex) or Claude (Claude Code), each with an Install / Sign in / Use button.
- **Visible text.** The UI no longer mentions Recalloom. Internal names stay: the Anki note-type names, backup format ids and code comments.
- **Making cards.** Through the helper (Codex, Claude Code), or copy/paste with any chat. The browser API-key route was removed on 2026-11-11. The whole lecture is read first; stop and resume are supported.
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
  - live AI generation through the helper;
  - real Safari;
  - Anki desktop and mobile apps.
- **Missing features:** Gemini and Kimi are not supported in the helper.

## Next

1. Run one live generation in `Slanki.exe`.
2. Import the backups into the local app, export one lecture, and confirm that reviewed cards keep their schedule in Anki.
