# Slanki

Turn lecture PDFs into Anki cards in your browser. Your slides, cards and backups stay on your device; only the slide text you choose goes to *your* AI, through your own account.

## Use it

1. Open the site and drop a lecture PDF (up to 100 slides).
2. **Make cards**: choose slides, how many cards, and optionally reverse cards. Generation uses your Codex or Claude Code (see below). Without them, use **Use any chat** to copy a prompt into ChatGPT, Claude or Gemini and paste the answer back.
3. Review each card beside its slide: **Keep** (A), **Set aside** (S), **Undo** (Z), edit in place, **Keep all drafts**, **Write a card**, **Attach part of slide**.
4. **Export to Anki** downloads an `.apkg`. Re-exports update the same Anki notes and keep your review history.
5. **Back up all lectures** (home page) or **··· → Save backup** (one lecture). Restore on the home page; old Recalloom backups work too.

## Connect your AI

Sign in to your CLI first (`codex login` or `claude auth login`), then run:

```
npx slanki@1
```

It opens Slanki with a one-time connection link. In Chrome or Edge, choose **Allow** when asked about access to apps on your device. Keep the window open while cards are made. `--local` opens the helper's own copy at `http://127.0.0.1:47213` (use this for Safari); `--reset` disconnects paired browsers.

Not published to npm yet. Until then: `npm install`, `npm run build`, `node helper/dist/slanki.mjs --local`.

## Develop

Requires Node.js 24.

```
npm install
npm run dev          # http://localhost:5173 (start the helper with --allow-origin http://localhost:5173)
npm test             # unit tests
npm run build        # app/dist (website) and helper/dist (npx package)
npm run serve        # app/dist with production headers on :4173
node app/e2e/workflow.mjs      # browser test (Chrome; SLANKI_BROWSER=firefox|webkit)
node app/e2e/generation.mjs    # browser + helper + fake AI
python tools/check_anki.py     # Anki import check (pip install -r requirements-dev.txt)
```

## Deploy to Vercel

Push to GitHub, then in Vercel choose **Add New → Project**, import the repo with Framework **Other**, leave everything else empty (`vercel.json` supplies it), and name the project `slanki`. Or run `npx vercel --prod` here. If you use a different domain, update `APP_ORIGIN` in `helper/src/main.ts`.

More: [architecture and privacy](docs/ARCHITECTURE.md), [status](docs/STATUS.md).
