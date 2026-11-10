# Status

Updated 2026-11-10. Personal alpha, branch `slanki`. The old Django app (Recalloom) is removed; it is recoverable from the tag `recalloom-django-final`. Snapshot of the 3 real lectures (format-12 backups) in ignored `data/backups/pre-slanki-20261110/`.

## Works

- **Library and lectures.** PDF import in the browser; IndexedDB library; review workspace with keyboard shortcuts; manual cards; "Attach part of slide"; Keep all; Undo.
- **Making cards.** Generation through the `npx slanki` helper (Codex, Claude Code), or the copy/paste chat route. The whole lecture is read first; stop and resume are supported.
- **Anki export.** Answers show only the slide. Note identity and schedules are compatible with Recalloom exports.
- **Backups.** Per-lecture and whole-library backups; reads Recalloom backups v1–12.
- **Deployment.** Vercel-ready static build (Node 24, strict CSP, `.vercelignore`).

## Verified

- **Unit tests.** `npm test`: 267 tests, including parity with the frozen Recalloom fixtures.
- **Anki import check.** `tools/check_anki.py` on Anki 26.8.1, including the 2 real lectures with kept cards: schedules preserved and layout updated.
- **Browser tests.** Both workflows pass in Chrome, Firefox and WebKit.
- **Clean deploy check.** A clean-room build of exactly what Vercel would receive passes the browser workflow.

## Not done

- **Releases:** no GitHub remote yet, no Vercel deployment, no npm publish, no license chosen.
- **Untested:**
  - live AI generation through the helper;
  - real Safari;
  - Anki desktop and mobile apps.
- **Missing features:** Gemini and Kimi are not supported in the helper.

## Next

1. Push to GitHub and deploy on Vercel.
2. Import the backups into the deployed site, export one lecture, and confirm that reviewed cards keep their schedule in Anki.
3. Run one live generation.
