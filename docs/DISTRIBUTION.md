# Distribution direction

Recorded 2026-09-09 following the user's request to keep processing off a hosted server.

The current product is installed locally and used in a browser at 127.0.0.1. Django, PDF parsing/rendering, SQLite, media, backups, and Anki export all run on the user's computer. The local Codex CLI sends generation input to OpenAI; model inference is cloud compute, not on-device inference.

## Proposed order

1. Package the existing app with an installer/launcher that starts the local service and opens the browser. Keep one copy of the services and local data. This is the shortest path from the current implementation to an independently installable product.
2. Optionally put the same interface in a dedicated desktop window. This changes distribution and presentation; it does not require a second implementation of document processing or export.
3. Consider a hosted static interface with a paired local companion if browser delivery provides enough value to justify splitting the current server-rendered UI. The host would deliver HTML, CSS, and JavaScript; the companion would retain lecture assets, database operations, export, and the user's native Codex connection locally. These hosted/desktop-wrapper modes are not implemented yet.

An ordinary webpage cannot directly start the installed Codex executable. It needs an installed bridge, such as a local companion or an extension with a registered native host. Chrome documents [native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging) and [local-network access permissions](https://developer.chrome.com/blog/local-network-access). Any future companion should require explicit pairing and approved origins; do not expose the existing loopback app or remove its CSRF/CSP checks to make a remote frontend connect.

A completely installation-free browser version would require porting the Python processing/storage/export path to browser technology and changing how generation connects. It is a separate build, not a deployment switch for this Django app. A fully offline AI mode would also require a local model integration, which is outside the current scope.

## Hosting scope

For a static frontend and local companion, hosting traffic is mainly interface assets rather than lecture processing. This could fit a small non-commercial site's free hosting allowance, but it is not a measured deployment estimate. Vercel's [Hobby plan](https://vercel.com/docs/plans/hobby) and [fair-use rules](https://vercel.com/docs/limits/fair-use-guidelines) currently restrict that plan to personal, non-commercial use. A paid product must use an eligible plan or host even if compute usage is low. No deployment has been created.

## Next product work

Evaluate compact card quality and missing learning objectives on a small representative selection when the user authorizes live usage. Then prioritize simple cloze and manual source-image crops according to the actual lecture material, followed by installation, upgrade/backup recovery, and a small classmate pilot. Keep scheduling and mobile study in Anki for this release. The user's reported successful Anki check is useful validation; the client/version and edited re-import behavior were not specified.
