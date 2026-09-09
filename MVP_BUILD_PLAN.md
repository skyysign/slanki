# First build and release checkpoints

This narrows the earlier founder analysis around the immediate need: use the tool for real lectures before building the integrated study service. These are proposed scope and acceptance criteria, not completed features or measured results.

## First deliverable

A local desktop tool with a browser interface:

PDF lecture -> source-linked draft cards -> human correction -> Anki deck with media.

Use Anki for scheduling and mobile study initially. The local tool is the first open-source product; hosted generation and the integrated reviewer are later milestones.

## Implementation order

1. **One real lecture end to end.** Start with a PDF containing selectable text. Save the original, extract page text, render page images, generate basic question/answer drafts, validate them, and export an `.apkg`. It is acceptable to run generation manually through the existing Codex environment for this first milestone.
2. **A useful correction interface.** Add a lecture list, page selection, a card editor beside its source page, accept/reject, basic cloze, a manual rectangular image crop, and an export action. Keep generated cards as drafts until accepted. Show skipped/unreadable pages explicitly.
3. **Reliable repeated use.** Persist edits, make retries bounded, preserve partial results, expose cancel/retry, retain stable note IDs across exports, and implement a complete local backup and restore.
4. **Local generation integration.** Automate one supported route, initially the user's installed Codex CLI. Keep credentials with the CLI. Codex non-interactive execution supports saved CLI authentication and schema-constrained output; enforce separate application-side validation. Process lecture content with restricted permissions, as source data rather than instructions to execute.
5. **Independent installation and pilot.** Package the supported desktop environment, document the actual AI/data path and limits, and invite five classmates after the beta checkpoints pass.

Do not turn a personal Codex integration into a shared hosted subscription backend. The hosted product will use a separately authorized and metered generation service.

## Storage and implementation decisions

- Python application, SQLite, local media folders, and a small browser interface. Start with Django and server-rendered pages; use limited JavaScript for page selection, cropping, and editing.
- Keep document processing, card generation/validation, and export callable independently of the interface. Avoid designing a general plugin/provider framework.
- Give each document version, page, note, and asset a stable ID. Save source page references and crop coordinates with cards. Keep model/provider details inside generation-run records.
- A generated revision must never silently replace an accepted or exported note. Preserve edits and explicitly select changes for later export.
- Put source thumbnails/crops into the deck media so evidence remains viewable without the local application. Keep original PDFs in the complete local backup.
- Retain a versioned internal export containing notes, IDs, sources, and media alongside the Anki export. This first converter has no review history of its own; do not claim it backs up reviews performed in Anki.

## Initial boundaries

- Support native-text PDFs first, with a documented file/page limit. PPTX users export a PDF before importing.
- Start with basic Q/A, then simple cloze. A manually selected crop is an attached image, not automatic image occlusion.
- Show the full source page whenever a smaller reliable region is unavailable.
- Explicitly identify scans and slides whose meaning cannot be captured by the supported extraction path. Do not quietly present partial extraction as complete lecture coverage.
- Defer native mobile apps, an internal SRS, Anki import, two-way Anki sync, accounts, payments, course search/scraping, automatic occlusion, OCR, tutoring, and multiple AI providers.

If most of the user's actual lectures are scans or diagram-only material, revise the input scope first; a text-only prototype would not meet the personal need.

## Ready for personal daily use

- Three real lectures have completed the entire workflow and have been studied in Anki.
- Accepted answers were checked against their actual source pages; errors can be fixed without regenerating the deck.
- Questions, answers, cloze rendering, source images, and attached figures render correctly in the Anki clients actually used.
- Edits survive a restart. An interrupted generation run does not destroy accepted work.
- Re-exporting unchanged notes does not create duplicates or reset their existing Anki progress in the supported workflow.
- A local backup restores onto an empty installation with all notes and media.

## Ready for a private beta

- Five intended users can install, generate, correct, and export without code changes by the developer.
- At least ten representative lectures from the supported course/material category have been exercised, including a long lecture, complex layout, unsupported scan, malformed generation output, and a simulated provider interruption/quota failure.
- Every accepted card has a valid source reference. Known source-mapping, answer-quality, missing-media, and data-loss defects in the evaluated examples are fixed before inviting users to rely on those cases.
- As provisional product targets, at least 80% of generated cards are useful without substantive editing, and active preparation time is roughly half the user's usual method. Count checking and correction time. These targets do not establish general factual accuracy or learning effectiveness.
- Compare a handful of actual learning objectives against generated cards so low card counts do not hide missing essential material.
- Failed/unsupported pages are visible; retries have a limit; users can stop work and recover saved results.
- Repeated export, edited-note import, existing Anki scheduling, and backup restoration have meaningful regression checks. Explain any unsupported behavior.

## Ready for a public converter release

- Beta users have returned with several lectures across at least two teaching weeks; observe repeated use, not just first-run success.
- A fresh installation and the documented example work on each advertised operating system. Initially advertising only one supported desktop OS is acceptable.
- Version upgrades preserve existing projects and backups. No known data-loss, duplicate-import, or wrong-source blocker remains in the supported workflow.
- Include a license, dependency notices, setup/troubleshooting instructions, realistic input limitations, a synthetic example lecture, and a way to report defects.
- Clearly explain that local storage does not mean local model inference, what gets sent for generation, and which separate AI access is required.

## Additional gates for an integrated paid beta

Only start this phase after the converter demonstrates repeated usefulness. Add hosted generation and a minimal mobile-friendly reviewer before native apps.

- Review grading, due dates, undo, suspension, and daily limits behave consistently; review records survive duplicate requests, reconnects, and day/timezone boundaries.
- Authentication, private document access, account isolation, and deletion work.
- Generation usage is measured, bounded, and shown before spending. Failed jobs and repeated callbacks cannot double-charge users.
- Subscription cancellation and credit balances behave predictably. Existing data remains exportable after cancellation under the published retention policy.
- Backups are actually restorable. Anki content export and transfer of learning progress have separately stated, tested support; do not claim complete progress portability prematurely.
- Measure processing and operating cost on actual light and heavy users before promising included allowances.
- Native mobile/offline sync is a later release with its own conflict-resolution and cross-device review-state checks.

## Next development task

Take one lecture PDF that the user needs to study now. Produce an Anki deck with editable basic cards and bundled source-page evidence. That is the first useful deliverable; all other work follows its observed failures.

## Technical references

- [Official OpenAI documentation: Codex non-interactive mode](https://developers.openai.com/codex/noninteractive): scripted execution, output schemas, and reuse of saved CLI authentication. This supports the proposed local integration; the application has not been implemented or tested here.
- [Anki exporting](https://docs.ankiweb.net/exporting.html): deck packages, media, scheduling options, and repeated imports. Compatibility of this proposed converter still needs implementation and real-client tests.
