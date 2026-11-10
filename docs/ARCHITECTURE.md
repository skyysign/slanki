# Browser and desktop boundaries

Updated 2026-10-26. The user wants a free website hosted on Vercel Hobby with temporary local study data, and a later installed desktop product with a persistent library alongside Anki. The current running application is the persistent local Python/Django edition. A static browser edition, hosted companion and desktop installer are not implemented by the workspace redesign.

## Two storage lifetimes, one study workflow

| | Browser session target | Desktop target / current local edition |
| --- | --- | --- |
| Delivery | Static HTML/CSS/JavaScript from Vercel | Local application and optional dedicated window |
| Lecture processing | Browser workers; optional paired local helper for native features | Local PDF renderer, local task workers |
| Study data | Memory and explicitly temporary device storage for the active session | Local SQLite, source files, saved runs and revisions |
| Persistence | User downloads the deck or backup; no automatic retained library | Local library and converter backups |
| Generation | External-chat JSON workflow, a browser-compatible provider route, or an optional paired CLI helper | Existing supported CLI adapters and native authentication |
| Export | Created locally and downloaded | Created locally and downloaded or saved |

The website host serves public application assets. It must not receive PDFs, page images, card content, CLI credentials, generation output or task databases. Local preprocessing is distinct from inference: material is still sent to the user's selected AI provider when generation is authorised. Ordinary webpages cannot launch native CLIs directly. Hosting the Django app on Vercel would not implement this browser-only product.

For the installation-free route, the current Download prompt / JSON import path is a useful fallback. A ChatGPT/Claude subscription is not automatically a browser API credential. Preserve explicit sharing consent and provider/account ownership; do not introduce a shared inference proxy.

## Boundaries maintained by the redesign

1. **Presentation:** `converter/static/converter/workspace.css`, `workspace.js`, and the existing browser scripts handle layout, editing controls, queues and dialogs. They receive URLs/data from their host. They do not read filesystem paths, import Python services, invoke a CLI, or perform SQL. The current HTML is still rendered by Django; it needs a client renderer before a complete static build is possible.
2. **Browser I/O:** `transport.js` owns the JSON request helper and the small AI-preference store. Requests use supplied URLs; preferences contain only provider, model and effort in `sessionStorage`. No lecture text, card fields, file blobs, credentials, source IDs or job results are written to browser persistence by these modules. Storage-disabled browsers continue to work. Tab preferences are convenience state, not a task database or authentication mechanism.
3. **HTTP adapter:** views translate form/JSON requests into service calls and supply endpoint URLs to the interface. They own CSRF/local-origin protections and redirects. Existing local-only middleware remains in force. Do not make the current server accessible to arbitrary websites as a shortcut to browser delivery.
4. **Operations:** PDF extraction/rendering, validated generation, note editing/revisions, image operations, export and converter backups remain service operations callable outside views. The current implementation uses Django/SQLite and native Python packages. These are not secretly browser-compatible; a browser worker/storage/export implementation is later work.
5. **Generator adapters:** keep native authentication with Codex/Claude/Gemini/Kimi. No adapter receives authority to turn lecture content into executable host instructions. A future companion exposes bounded task operations, not a shell endpoint.

Use existing stable document/page/note identities, validated source evidence, cloze ordinals and versioned converter backups as interchange anchors. Reuse synthetic fixtures and contract checks across future implementations. Avoid a general plugin registry or an unused storage framework until the second concrete implementation exists.

## Later browser implementation

- Render and extract PDFs in browser workers with bounded resources. Choose and pin actual browser libraries when implementing this feature. Keep parsed text, rendered images and task state in the session; design large-file spill storage explicitly rather than silently retaining a permanent library.
- Implement the supported Anki note types/media locally, checked against the same export/re-import cases and actual clients. A browser ZIP builder alone does not establish Anki compatibility.
- Provide an explicit **End session** operation: cancel owned tasks, terminate workers, drop document/card state, revoke object URLs, and delete owned temporary database/cache entries. Cache only public app assets across sessions. Do not claim secure erasure of browser/OS caches. User-requested downloads and provider-owned history are outside app cleanup.
- A desktop shell can keep the present local services and library while loading the same UI assets. A temporary browser session and a persistent desktop library should share domain rules and import/export contracts, not an assumption that every UI needs a database-backed lecture library.
- If native subscription-backed generation is offered from the hosted UI, implement pairing, approved origins, a scoped short-lived connection and explicit data flow. Browser local-network permissions/CORS and lifecycle need real verification at that stage. Do not disable CSRF/CSP or accept any origin on port 8000.

## Vercel target

Use Vercel for static assets, not file processing, model requests, task state, or SQLite. The user plans Hobby rather than a paid service. The official [Hobby plan](https://vercel.com/docs/plans/hobby) describes non-commercial personal use and resource limits; [fair-use guidance](https://vercel.com/docs/limits/fair-use-guidelines) explicitly excludes asking for donations from commercial use. Checked 2026-10-26. This is a suitable architecture target for the stated free/donation direction, not a traffic forecast or an unconditional entitlement to the plan. Advertising or paid access needs another review. No deployment, account connection or plan purchase is part of this redesign.

## Current scope

This change ships the workspace redesign, tab-scoped AI preferences, live local previews and version-checked undo in the existing local edition. It does not ship browser PDF processing/export, an ephemeral task store, a pairing service, a desktop wrapper or a Vercel deployment. Those are separate executable milestones; documenting them does not mark them implemented.
