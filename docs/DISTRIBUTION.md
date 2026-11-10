# Distribution direction

Updated 2026-10-26: free software with optional donations, a planned Vercel Hobby static browser edition using temporary device storage, and a later desktop edition with a persistent local library. The current implementation is still the persistent local Django application. See [the browser/desktop boundaries](ARCHITECTURE.md) for what the redesign separates and what remains to be implemented.

The product name is **Recalloom**, combining recall and loom. The user delegated the choice and asked for a name between study-focused and abstract. An exact-name web search found no results on 2026-09-09; domain availability and trademark clearance have not been checked. Historical research and compatibility identifiers retain their original names.

The current product is installed locally and used in a browser at 127.0.0.1. Django, PDF parsing/rendering, SQLite, media, backups, and Anki export all run on the user's computer. The chosen local CLI sends generation input to its selected provider; model inference is cloud compute, not on-device inference.

## Confirmed delivery direction

1. Finish the shared study workspace and correction flow in the working local edition. Keep presentation, browser I/O, HTTP adapter and processing/generation/storage services distinct. The October redesign uses host-supplied URLs and a small browser transport/preferences module; it does not port the complete engine to JavaScript.
2. Build a static browser client for Vercel Hobby: process PDFs and make decks on the device, use temporary session data, and offer explicit download/end-session actions. No lecture uploads, task database, PDF/image processing or model proxy on Vercel. A browser worker, temporary store and browser-compatible export implementation are needed before this can ship. The existing local Django application is not a ready-to-deploy static site.
3. Package a persistent desktop edition alongside Anki, reusing the UI and the existing local engine/library where possible. The browser interface and a desktop window are two shells; temporary sessions and persistent libraries have different storage lifetimes. Installer, desktop window, clean-machine onboarding and upgrade recovery remain future work.

Native subscription-backed CLI generation from the hosted frontend needs an optional paired helper. A completely installation-free route can use Download prompt / JSON import until a suitable browser-compatible connection exists. See ARCHITECTURE.md for privacy, cleanup, pairing and interface boundaries. None of the hosted browser engine, helper or desktop wrapper has been deployed.

An ordinary webpage cannot directly start the installed Codex executable. It needs an installed bridge, such as a local companion or an extension with a registered native host. Chrome documents [native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging) and [local-network access permissions](https://developer.chrome.com/blog/local-network-access). Any future companion should require explicit pairing and approved origins; do not expose the existing loopback app or remove its CSRF/CSP checks to make a remote frontend connect.

A completely installation-free browser version would require porting the Python processing/storage/export path to browser technology and changing how generation connects. It is a separate build, not a deployment switch for this Django app. A fully offline AI mode would also require a local model integration, which is outside the current scope.

## CLI onboarding

The local app has **AI connections** screens for Codex and Claude Code. Each detects its own saved sign-in or starts the official CLI's browser login after a CSRF-protected button press. Users sign in with the chosen provider, then return to a page that updates automatically. Recalloom never reads or copies the authentication store and does not receive passwords. The integrations follow [Codex authentication](https://developers.openai.com/codex/auth) and [Claude CLI authentication](https://code.claude.com/docs/en/cli-reference); generation uses each user's own access and allowance. Actual Claude login/inference remains to be verified; see [CLI support](CLI_PROVIDERS.md).

For a later packaged release, aim for **install Recalloom → choose CLI → connect → add a lecture**. The installer should include or set up the required native runtime/CLI and check that installation succeeded. That installer is still pending; this development build detects existing native CLIs and links to setup when missing. The connection managers assume a single local server process. A hosted website would still need the installed local companion to perform this flow; there is no central subscription login or generation service.

## Hosting scope

For a static frontend and local companion, hosting traffic is mainly interface assets rather than lecture processing. This could fit a small non-commercial site's free hosting allowance, but it is not a measured deployment estimate. Vercel's [Hobby plan](https://vercel.com/docs/plans/hobby) restricts that plan to personal, non-commercial use. Its [fair-use rules](https://vercel.com/docs/limits/fair-use-guidelines) explicitly say that asking for donations does not count as commercial usage.

The product is entirely free and supported by optional donations, such as Patreon. Paid app access, supporter-only features, subscription tiers, sold generation credits, and a hosted generation service are outside the current direction. Users bring their own supported AI access. A free static app/distribution/support website remains the target. Vercel’s Hobby and fair-use pages were checked again on 2026-10-26: non-commercial personal-use restrictions apply, asking for donations is excluded from commercial use, and resource limits still apply. Static delivery is an architecture choice, not a measured guarantee that a given traffic level fits the plan. The user previously allowed for a hosting budget of approximately $20/month if needed; that remains a planning preference, not authorization to purchase a plan. No deployment or paid subscription has been created.

## Next product work

Evaluate compact card quality and missing learning objectives on a small representative selection when the user authorizes live usage. Simple cloze, learning focuses, card-count-aware previews, manual source-image crops, and confirmed set deletion are implemented with offline checks. Validate their real-lecture usefulness and Anki client rendering, then prioritize installation, upgrade/backup recovery, and a small classmate pilot. Keep scheduling and mobile study in Anki for this release. The user's reported successful Anki check is useful validation; the client/version and edited re-import behavior were not specified.
