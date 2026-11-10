# Recalloom: a simpler lecture workspace

Review date: 2026-10-24. This is a product recommendation and design proposal, not a record of shipped application changes. The accompanying `ux-prototype.html` uses synthetic content and runs without AI, accounts, or a database.

Implementation update (2026-10-26): the first production slice now exists in the working local app, including the new workspace, compact controls, live previews and version-checked undo. This document remains the original proposal for the broader direction; concept mappings, deck consolidation and browser-only processing are still future work. See STATUS.md for checks actually run.

## Recommendation

Keep two principal outputs: **Cards** and **Study guide**. Present one ordinary card-generation workflow. Move specialised image work into source-slide tools, and make AI settings a remembered preference. Invest next in correction speed and useful coverage rather than more generation modes.

The issue is less the number of capabilities than the number of decisions exposed at once. Learning focus, Anki note format, image interpretation, and provider configuration are different dimensions. They currently appear together as if they were comparable study modes.

## Findings in the current application

These findings come from the templates, generation flow, and saved synthetic desktop/mobile screenshots. They are a heuristic review, not a usability study or measured user preference.

| Current friction | Consequence | Proposed change |
| --- | --- | --- |
| Four learning focuses, four generation format choices, page checkboxes, maximum count, provider/model/effort, context choice and consent in one form | Users must configure the machinery before doing their task | Lead with scope and maximum cards; use sensible defaults; put overrides in an expandable area |
| Setup, overview, proposal queue, last-run details and warnings above the review editor | The card and source start far down the page | Keep one compact current-task status; put history/details in an activity drawer |
| Card list, large editing form and source occupy three columns | Reading, correction and source checking compete for space; image controls add substantial scrolling | Two principal panes: card and source; open the queue on demand |
| Anatomy navigation plus a manual builder, temporary suggestions and saved suggestions | A specialised tool gets the prominence of a general study output | A source-slide action, **Hide labels**, with one visible proposal-review entry point |
| Crops and covers each repeat the entire slide in the editing column while a source pane already exists | Visual editing requires moving between several versions of the same image | Draw/select/edit on the source pane, then see the result directly in the card preview |
| Persistent overview and rundown are both visible to the user | Their purpose and completeness can be confused | Call the reading output **Study guide**; show the planning overview only in generation details |
| Notes, cards, drafts, accepted, rejected, set aside and proposals vary across screens | The user has to learn the data model | Use **To review**, **Ready**, **Set aside**; show actual Anki card counts at export |
| The library appears below a large onboarding hero and upload instructions | Returning users scroll past information they already know | Open on the lecture library; keep **Add PDF** prominent and onboarding for the empty state |

## What stays, moves, or stops being a main choice

| Capability | Decision | Reason |
| --- | --- | --- |
| Q/A and cloze | Keep; **Automatic** is the proposed default for new runs | Format should follow the learning task, with optional controls for users who need a specific format |
| Basic + reverse | Keep as an advanced creation option | Useful for genuinely reversible pairs; doubling cards is a poor general default for a compact deck |
| Balanced/Core/Understanding/Application | Retire the four-way selector from the ordinary flow | Ask for compact, useful, source-supported cards; retain legacy run settings and an advanced preference initially |
| Graph/formula questions | Keep as a source tool and optional selected-slide generation | Useful, but current all-slide analysis can be slow and costly. Do not silently enable it for every lecture |
| Label-recall occlusion | Keep under **Hide labels** on a slide | Valuable for anatomy and diagrams without requiring another top-level product area |
| Manual card creation | Keep, near the source | A missing card should be easy to add during correction |
| Lecture rundown | Keep; rename to **Study guide** | A distinct, valuable reading task, separate from Anki |
| Planning overview | Keep internally | Useful for generation; it does not need to be another study destination |
| Provider, model and reasoning | Keep all current integrations and controls; move into remembered settings | Configure once, then show a concise summary with **Change** per task |
| Prompt download/JSON import | Keep under **Tools → Use an external chat** | Useful escape hatch without dominating the main flow |
| Backup, restore, export and deletion | Keep; organise around library/lecture actions | Portability and recovery are core product value. Destructive actions remain explicit |
| Separate temporary versus saved image-suggestion UX | Consolidate the visible workflow later | Users should review a suggestion, not choose a job-persistence mechanism; this needs service work, not only relabelling |

Automatic format selection is a proposal: the current app defaults to Q/A and already supports mixed Q/A/cloze. It needs evaluation before changing the production default. Existing note types and cloze ordinals must stay fixed during edits to preserve Anki scheduling. Simplifying the UI must preserve old settings, cards, proposals, backups and resume paths.

## Proposed ordinary flow

1. **Library:** choose a lecture or add a PDF. Each lecture says what to do next: create cards, continue reviewing, or export.
2. **Create cards:** choose all slides or a subset, set a maximum, and confirm the actual data-sharing scope. The current provider/settings appear as a short summary. Format/focus overrides stay in Advanced. Context stays on by default. Figure analysis is an explicit selected-slide action while its cost/quality are still being evaluated.
3. **Review:** see the question and answer beside their source. Edit inline; **Keep & next**, **Set aside**, and **Undo** are immediately available. Use the queue to jump, rather than permanently shrinking the editor. Support keyboard actions without intercepting typing. Preserve unsaved edits when navigating.
4. **Export:** show the actual Anki card count and which drafts still need review. Preserve the supported one-way export and stable IDs.
5. **Study guide:** browse concepts, jump to sources, see related cards, or add a missing card. Reading the guide is optional; it must not become a mandatory generation step.

The two-pane workspace becomes Card/Source switches on narrow screens. Mobile layout is for the same local interface, not a claim that phones can connect to the desktop server.

## Most useful additions, in order

1. **Correction speed:** keyboard actions, undo, less scrolling, automatic preview, clear unsaved state, source following the selected card, and convenient image tools. These improve the work users already do. The existing backend already supplies many necessary operations.
2. **Concept-to-card links:** connect guide concepts, source pages and cards. Show **Has cards**, **No card yet**, and **Source needs review**. Do not call this a completeness score or infer that every learning objective is covered. The prototype's links are manually authored sample data; production needs persisted mappings and validation.
3. **Improve an oversized set:** find likely duplicates/overlap, propose a smaller set, show the changes, and let the user choose. Accepted or edited cards need explicit decisions. Setting a note aside must not imply deletion of an earlier Anki copy. This is more valuable than adding further learning-focus presets, but requires its own implementation/evaluation.
4. **Formula readability:** improve display of supported formula notation in the guide and cards. Retain original-slide evidence when extraction is broken. Add a renderer only when implemented; this is not an OCR commitment.
5. **Simple library search:** useful as the lecture collection grows; folder hierarchies and course discovery can wait.

## Omit or defer

Do not add a general lecture chatbot, internal SRS, quizzes/exam modes, native mobile applications, hosted generation, accounts, subscriptions, course scraping, more CLI adapters, or automatic acceptance. Each adds a substantial workflow/support surface without addressing the current correction burden. Preserve Anki as the study destination and local processing as the distribution model.

Do not remove recovery, source evidence, consent, backups, manual editing, or export to make the screens look simpler. Present them at the relevant moment. Important unreadable-source warnings stay visible; old run diagnostics move to details.

## Implementation sequence and checks

**First slice: reorganise the existing UI.** Library-first home, Cards/Study guide navigation, generation sheet, remembered-settings summary, two-pane correction view, compact progress and an activity drawer. Use the current Django views/services; retain existing routes as needed. Keep creation-format overrides available. No service rewrite or data migration is justified just for this layout.

**Second slice: improve correction and visual tools.** Add source-pane editing, undo/revision behavior, keyboard actions, mobile pane switching and a clearer image-proposal queue. Test that navigation never loses an edit and stale submissions cannot overwrite another tab. Update synthetic browser checks for the new flows.

**Third slice: connect guide concepts and improve deck size.** Persist concept links, then evaluate suggested omissions/overlaps with previewed decisions. Investigate sharing validated concept analysis between guide creation and card planning, while keeping guide creation optional; never use a guide as source evidence for an answer. Reuse validated source identities. Keep this separate from a cosmetic redesign.

Check the new flow on a short lecture, the existing long lecture, an image-heavy selection, interrupted generation and an old backup. Compare active time and number of corrections for a small fixed set of cards. Pilot criteria: ordinary generation does not require opening Advanced; editing and source checking fit the desktop viewport; Keep/Set aside/Undo work by mouse and keyboard; progress shows the actual stage; no edits, source references, identities or backups are lost. No time-saving claim is established by this proposal.

## Clickable proposal

Open `ux-prototype.html`. It demonstrates the two-pane review, on-demand queue, inline editing, keyboard shortcuts, undo, guide/card links, a missing-concept card, selected-slide figure options, settings and export summary. All state lives in memory and resets on reload. Creation/export actions demonstrate the interaction with synthetic records; they do not generate a deck, run a model, read private files or change the production app.
