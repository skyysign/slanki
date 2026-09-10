# Distribution direction

Updated 2026-09-10 following the user's clarification: entirely free software, optional donations, no service or app subscription, and expansion only if demand warrants it.

The product name is **Recalloom**, combining recall and loom. The user delegated the choice and asked for a name between study-focused and abstract. An exact-name web search found no results on 2026-09-09; domain availability and trademark clearance have not been checked. Historical research and compatibility identifiers retain their original names.

The current product is installed locally and used in a browser at 127.0.0.1. Django, PDF parsing/rendering, SQLite, media, backups, and Anki export all run on the user's computer. The local Codex CLI sends generation input to OpenAI; model inference is cloud compute, not on-device inference.

## Proposed order

1. Package the existing app with an installer/launcher that starts the local service and opens the browser. Keep one copy of the services and local data. This is the shortest path from the current implementation to an independently installable product.
2. Optionally put the same interface in a dedicated desktop window. This changes distribution and presentation; it does not require a second implementation of document processing or export.
3. Consider a hosted static interface with a paired local companion if browser delivery provides enough value to justify splitting the current server-rendered UI. The host would deliver HTML, CSS, and JavaScript; the companion would retain lecture assets, database operations, export, and the user's native Codex connection locally. These hosted/desktop-wrapper modes are not implemented yet.

An ordinary webpage cannot directly start the installed Codex executable. It needs an installed bridge, such as a local companion or an extension with a registered native host. Chrome documents [native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging) and [local-network access permissions](https://developer.chrome.com/blog/local-network-access). Any future companion should require explicit pairing and approved origins; do not expose the existing loopback app or remove its CSRF/CSP checks to make a remote frontend connect.

A completely installation-free browser version would require porting the Python processing/storage/export path to browser technology and changing how generation connects. It is a separate build, not a deployment switch for this Django app. A fully offline AI mode would also require a local model integration, which is outside the current scope.

## Codex onboarding

The local app now has a **Codex connection** screen. It detects a saved ChatGPT sign-in, or starts the official CLI's browser login after a CSRF-protected button press. Users sign in with OpenAI, then return to a page that updates automatically. Recalloom never reads or copies the authentication store and does not receive passwords. This follows the [supported Codex authentication flow](https://developers.openai.com/codex/auth); generation uses each user's own Codex access and allowance.

For the first packaged release, aim for **install Recalloom → Connect Codex → sign in → add a lecture**. The installer should include or set up the required native runtime/CLI and check that installation succeeded. That installer is still pending; this development build detects an existing CLI or VS Code extension and links to setup if neither is found. The connection manager assumes a single local server process. A hosted website would still need the installed local companion to perform this flow; there is no central subscription login or generation service.

## Hosting scope

For a static frontend and local companion, hosting traffic is mainly interface assets rather than lecture processing. This could fit a small non-commercial site's free hosting allowance, but it is not a measured deployment estimate. Vercel's [Hobby plan](https://vercel.com/docs/plans/hobby) restricts that plan to personal, non-commercial use. Its [fair-use rules](https://vercel.com/docs/limits/fair-use-guidelines) explicitly say that asking for donations does not count as commercial usage.

The product is entirely free and supported by optional donations, such as Patreon. Paid app access, supporter-only features, subscription tiers, sold generation credits, and a hosted generation service are outside the current direction. Users bring their own supported AI access. A free distribution/support website remains compatible with this scope. The user previously allowed for a hosting budget of approximately $20/month if needed; that remains a planning preference, not authorization to purchase a plan. No deployment or paid subscription has been created.

## Next product work

Evaluate compact card quality and missing learning objectives on a small representative selection when the user authorizes live usage. Simple cloze, learning focuses, and card-count-aware previews are now implemented with offline checks. Validate their real-lecture quality and Anki client rendering, then prioritize manual source-image crops according to the material, followed by installation, upgrade/backup recovery, and a small classmate pilot. Keep scheduling and mobile study in Anki for this release. The user's reported successful Anki check is useful validation; the client/version and edited re-import behavior were not specified.
