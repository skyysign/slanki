# Lecture-to-SRS founder assessment

**Recommendation: validate a narrow lecture-to-card workflow before committing to a full study platform.** The strongest version helps students turn their own course materials into a manageable set of accurate cards, verify an answer immediately, and continue studying in either the product or Anki. The broad feature list is already substantially represented in the market. A new entrant needs a measurable advantage in preparation time, card usefulness, or subsequent review workload.

This assessment uses public information checked on September 9, 2026. Competitor features below are documented capabilities or vendor claims, not results of hands-on comparative testing. Proposed prices, performance targets, segment rankings, engineering estimates, and usage assumptions are analytical judgments. Inference costs are calculated scenarios, not measurements on lecture files. The operating assumption is one full-time developer, an adult university audience, one initial teaching language, private student uploads, and USD pricing before tax. Start with the university and language in which recruitment and subject-matter evaluation are easiest.

**1. Product thesis.** The compelling promise is: “Turn this week's lectures into cards you can trust and realistically finish studying.” “Upload a PDF and generate flashcards” is a weak standalone business proposition. A source link makes checking easier, but does not establish that the answer follows from the source, that the source is correct, or that the fact will be examined.

The product should optimize the whole learning task: selecting important material, preparing cards, correcting mistakes, and completing later reviews. Ten minutes saved during generation can be outweighed by hours spent reviewing unnecessary cards. Measure preparation time plus subsequent review time at comparable learning coverage and recall. Counting generated cards rewards the wrong outcome.

The strongest early value is reliable conversion of material that existing decks do not cover: the lecturer's terminology, diagrams, distinctions, and course-specific objectives. Provide a concise default deck with visible omissions and optional additional coverage. A lecturer's spoken emphasis, assessment style, and unpublished expectations cannot reliably be reconstructed from slides alone. Permit optional objectives or selected pages; avoid advertising that AI knows what will be on the exam.

The most plausible defensibility comes from a permissioned evaluation corpus of difficult teaching materials, recurring student corrections, excellent handling of visual evidence, and trusted distribution within specific courses. These assets can improve the production system over time. Prompts, model routing, FSRS, and the presence of a “show source” button are readily reproducible.

A viable small subscription business is plausible. A venture-scale outcome would require stronger distribution, retention across courses, and evidence that the product improves with use. A polished converter alone does not establish those conditions.

**2. Target users.** Target students who already spend substantial time making or repairing cards from their own lectures. Within medicine, start with one preclinical physiology or pathology course whose local material is poorly served by existing decks. Students using diagrams alongside factual content are a better first fit than an anatomy course requiring flawless automatic occlusion from day one.

The following is a prioritization hypothesis; willingness to pay is not established by the sources reviewed.

| Segment | Lecture-to-card pain | Likely willingness to pay | Existing SRS behavior | Main obstacle | Priority |
|---|---|---|---|---|---|
| Preclinical medical students with local course exams | Very high | Medium to high within student budgets | Strong in some programs | Established decks and reluctance to leave Anki | First |
| Dental, veterinary, nursing, allied-health students | High | Medium | Uneven; validate locally | May require teaching a new study habit | Strong adjacent test |
| Biology, neuroscience, fact-heavy STEM | High | Medium | Moderate and variable | More price-sensitive; course heterogeneity | Second |
| Engineering, mathematics, computer science | Medium for facts; lower for full problem-solving tasks | Medium | Variable | Recall cards cannot replace derivations or practice problems | Select courses only |
| Professional certification candidates | High when materials are fragmented | Potentially high | Variable | Question banks and exam simulations may matter more | Later, one certification |
| Law students | Medium to high | Potentially medium to high | Variable | Jurisdiction, exceptions, and application matter; slides may omit essential reading | Later |
| Language learners | Low for this specific ingestion workflow | Medium | Often strong | Lecture slides are a poor acquisition channel; mature alternatives | Do not target first |

There is evidence of existing medical-student behavior: Harris and Chiang's 2022 single-school study recruited 60 first-year students and reported roughly 70% used Anki during an anatomy and physiology module. This supports testing a segment with an existing habit; it does not establish national adoption, current willingness to pay, or the effectiveness of AI-generated cards. [Harris and Chiang, Anki usage study](https://pubmed.ncbi.nlm.nih.gov/35494926/).

The central segment tradeoff is that enthusiastic SRS users are easier to convince about cards and harder to convince about switching review applications. Treat successful Anki export as a valid activation outcome. Measure demand for the in-app reviewer separately. Recruit at two institutions before generalizing from a single lecturer or student society.

**3. Competitive landscape.** The following gaps are opportunities to test, not claims that a competitor lacks an undocumented feature.

| Product | What it already does well or advertises | Implication for this concept |
|---|---|---|
| Anki | Flexible notes and templates, media, established scheduling, portable decks, and a large ecosystem. Modern Anki supports image occlusion natively. | Beat the work needed to create and maintain course-specific cards. The reviewer alone is a difficult reason to switch. [Anki](https://apps.ankiweb.net/), [editing manual](https://docs.ankiweb.net/editing.html). |
| RemNote | AI cards, PDF learning and annotation, image occlusion, notes, and SRS. Its reader already supports text and area references that jump back to a PDF location. | The closest broad incumbent. A simpler upload-to-study workflow could win, but PDF references and integrated SRS are not new. [Pricing and features](https://www.remnote.com/pricing), [PDF reader](https://help.remnote.com/en/articles/6690975-learning-from-pdfs-and-files-with-the-remnote-reader). |
| Quizlet | AI study guides from notes, PDFs, and lecture slides, with flashcards and practice activities. | General-purpose generation competes with an established study destination. Test whether precise visual evidence and portable longitudinal review provide additional value. [Study Guide Maker](https://quizlet.com/features/study-guides/). |
| Knowt | AI-assisted study materials and free flashcard study modes, including spaced repetition. | A substantial price-pressure competitor. “Includes SRS” cannot carry the differentiation. [Flashcards](https://knowt.com/flashcards), [student plan documentation](https://help.knowt.com/en/articles/10298016-what-are-the-differences-between-free-and-paid-accounts-for-students). |
| StudyFetch | Generates cards from lecture material and provides scheduled review alongside a broader study suite. | The combined generation-plus-review proposition already exists. Compare actual correction burden and quality on your target lectures. [Spaced repetition](https://www.studyfetch.com/spaced-repetition-app). |
| AnkiDecks, at anki-decks.com | AI generation, extracted images, image occlusions, Anki export, and its own spaced repetition. | Direct pressure on both conversion features and price. A converter with a reviewer is insufficient positioning. [Plans](https://www.anki-decks.com/payment/pricing/). |
| SlideToAnki | Advertises PDF/PPTX conversion, Q/A, cloze, automatic occlusion, source excerpts, coverage mapping, and feedback-informed generation. | Particularly close overlap with the proposed differentiation. Evaluate it directly before committing engineering time. Its accuracy and time-saving claims remain unverified here. [Product and plans](https://slidetoanki.com/). |
| Clozely | PDF/PowerPoint reading, source-linked AI drafts, image occlusion, and an Anki-focused creation workflow. | Source-linked creation and respect for the Anki workflow are also occupied territory. [Product](https://clozely.app/). |
| NotebookLM | Google has documented flashcards and quizzes generated from selected sources, with topic and difficulty controls. | Source-based AI study can be bundled into a broader tool. Do not infer FSRS or exact-region export compatibility from these features. [Google announcement](https://blog.google/innovation-and-ai/models-and-research/google-labs/notebooklm-app-quizzes-flashcards/). |

Useful published price anchors: RemNote displayed Pro at $96/year and Pro with AI at $216/year, equivalent to $8 and $18 per month with annual payment. AnkiDecks displayed Pro at $60/year and Ultimate at $144/year. SlideToAnki displayed Student at $149/year and Power at $349/year. Clozely advertised optional AI from $9.99/month. These are different products and allowances; annual equivalents are not monthly billing prices. The linked product pages support these amounts.

Knowt's public pricing is insufficiently consistent for a clean student-price comparison: its August 2025 help article says $19.99 monthly or $120 annually, while also giving an inconsistent monthly equivalent; the public plans page exposed another price set alongside teacher-oriented features. Verify the actual student checkout before using a figure in positioning. I would likewise avoid presenting an unverified universal Quizlet or StudyFetch price. [Knowt help article](https://help.knowt.com/en/articles/10298016-what-are-the-differences-between-free-and-paid-accounts-for-students), [plans page](https://knowt.com/plans).

An incumbent could add a source thumbnail, regeneration menu, provider selector, or coverage toggle relatively easily. Consistently choosing the correct visual region and the right set of cards across messy lectures is more demanding, but competitors are already attempting it. The concrete opening is demonstrably lower correction time and lower review burden in a narrow course category. A feature matrix cannot prove that opening exists.

**4. MVP.** Build a six-week private beta, with the two-week prototype included in that period. This is plausible for an experienced developer working full time with access to reviewers and familiar infrastructure. It is not a credible schedule for the complete proposed product.

| Must be in v1 | Should wait | Do not build initially |
|---|---|---|
| Native-text PDF slides; one language; at most 100 pages and 50 MB per file | Native PPTX ingestion and reliable scan/OCR support | Universal document understanding |
| Basic Q/A and simple cloze; optional source figure on either side | Automatic image occlusion and complex card templates | Generative replacement diagrams for factual source evidence |
| Saved page render, page reference, and text/figure region when trustworthy | Sophisticated crop editor and arbitrary polygon masks | Full PDF annotation or note-taking suite |
| Source viewer, edit, dismiss, suspend, and one-card regeneration | AI-assisted splitting, richer course coverage analysis | AI tutor, voice tutor, video generation, lecture recording |
| Small FSRS reviewer with persistent review events and cross-device online access | Offline sync, native apps, advanced analytics | A new scheduling algorithm |
| Basic/cloze Anki export with media; limited content import and clear compatibility report | Broad custom-template import, native IO interchange, scheduling migration | Automatic two-way Anki synchronization |
| One hosted provider; metering, job retries, privacy controls, account deletion | BYOK and multiple provider choices after demand is demonstrated | A provider marketplace or local-model server fleet |

In v1, a cropped figure is an image attached to a Q/A or cloze card; it is not a separate scheduling mechanism. Use full-page evidence when automatic cropping is uncertain. If the input is a scan or a poorly rendered presentation, explain the limitation and allow replacement with a native PDF. Do not silently omit those pages and call the lecture complete.

You should implement simple manual editing immediately. A user can duplicate a card and edit the copies to split it; elaborate AI splitting can wait. Whole-deck regeneration is dangerous once studying begins, so regeneration should create a draft revision and preserve the studied card until the user adopts the change.

The beta must be useful without automatic occlusion. If recruited students mainly need anatomy label masks, either change the first course or substitute a narrow rectangular-occlusion workflow for cloze support. Do not add both branches to the same six-week commitment.

**5. First-use experience.** The default path should require an upload and a single study decision, with optional controls tucked away.

1. The student uploads lecture.pdf. Infer the title and remember the course from prior use. Offer optional objectives or a page range; avoid asking for a target card count.
2. Show a readable preview and any unsupported pages. Display how much included processing the upload will consume before generation begins. Allow cancellation.
3. Process a coherent opening section first. A reasonable engineering target is the first useful cards in under two minutes for a supported 50-page file, with the full set in under five minutes. These are targets to measure, not promised performance.
4. Present an example result such as “32 cards ready; 4 drafts need attention; 3 pages could not be read.” Show represented topics and omissions. The counts are illustrative and must follow actual content.
5. Offer “Start with ready cards” and “Export to Anki.” Let the student inspect three representative samples, including a visual card, without requiring approval of every answer.
6. During review, place the source beside the revealed answer or behind a single click. Make editing and reporting a problem possible without abandoning the session.
7. After a short first session, show what is due next and allow the student to set a daily new-card budget.

Avoid mandatory line-by-line approval of a large generated deck: that can recreate the manual work the product promises to remove. However, automatically activating cards is justified only after an externally assessed quality threshold is met. During the earliest pilot, drafts should remain visibly provisional. Route ambiguous material to a separate queue and explain its exclusion; do not portray model self-confidence as a factual guarantee.

An answer revealed while inspecting its evidence is not a successful retrieval. In-app scheduling should not count previewing a card as a graded review. This small distinction protects both learning records and later personalization.

**6. AI pipeline.** Use a bounded sequence of extraction, selection, drafting, and checking. The following is the full target architecture; v1 uses its native-PDF subset.

**Ingestion and immutable source identity.** Validate the true file type and basic structure; assign a document version and content hash. Store the original privately. Run parsers in a restricted worker with file-size, decompression, page-count, pixel-count, memory, and time limits. Disable document macros and external-resource fetching. Lecture content is untrusted input to both parsers and models; text on a slide must never authorize tool calls or change processing rules.

**PPTX extraction.** Read the Open XML structure with python-pptx, descending into groups. Preserve text runs, paragraphs, tables, picture relationships, shape identifiers, positions, crop settings, slide order, and speaker notes. Record hidden-slide status and treat notes as a distinct evidence channel. Native images may be reused on several slides, so model an asset separately from each placement. python-pptx exposes shapes and pictures but does not cover every PowerPoint feature. [python-pptx shapes](https://python-pptx.readthedocs.io/en/latest/api/shapes.html?highlight=add_picture), [project documentation](https://python-pptx.readthedocs.io/en/stable/).

Render a canonical PDF through a pinned LibreOffice installation in an isolated process. Preserve the rendered result and renderer version. Missing fonts, SmartArt, layering, charts, and animation can change the visible slide; a static render cannot reconstruct the lecturer's animation sequence. If fidelity is poor, request a PowerPoint-exported PDF within the product. LibreOffice documents headless conversion and output parameters. [LibreOffice command-line parameters](https://help.libreoffice.org/latest/gu/text/shared/guide/start_parameters.html).

**PDF extraction and rendering.** Extract text with geometry, rotation, images, vector objects, and page dimensions. Render every page for provenance and visual comparison; rendering locally does not mean sending every render to an expensive model. A PDF figure may consist of vectors, several images, and independent labels. Never equate an embedded image with a complete figure. pdfplumber exposes detailed object geometry but explicitly does not reconstruct image content for you. [pdfplumber](https://github.com/jsvine/pdfplumber).

**Text and OCR routing.** Check text density, plausible reading order, replacement characters, and consistency with the render. OCR missing or corrupt text at page or region level, rather than OCRing an entire native-text lecture. Retain original text and OCR text separately, with engine/version and confidence metadata. Handwriting, mathematical notation, subscripts, and near-identical symbols need separate evaluation. Disagreement between native extraction and visual evidence is a reason to withhold a card.

**Figure candidates.** Deterministically cluster nearby images, vector regions, labels, and captions; detect repeating logos, footers, and decorative assets. Add a cheap visual classifier where geometry alone is insufficient. Keep candidate IDs and coordinates. A useful figure must support an actual question; “large image” is not an adequate relevance rule. Complex scientific charts may need high-resolution inspection even when the rest of the page is text.

**Crop versus native image.** Extract an embedded asset when it contains the complete figure with sufficient resolution and the required labels. Crop the rendered slide when meaning depends on nearby arrows, captions, overlaid annotations, vector elements, or layout. Include axes, units, legends, and enough surrounding context. Store the asset-to-slide transform. On uncertainty, retain a larger crop or the full slide. For occlusion, later, hide the answer label without revealing it in a nearby duplicate label, caption, tooltip, or front-side accessibility text.

**Context and concept planning.** Partition by topic, usually around two to six neighboring slides, with a small context overlap and a bounded lecture outline. Maintain explicit “owned” pages for each chunk so overlap does not duplicate generation. Separate evidence facts, stated objectives, worked examples, and inferred connections. Identify candidate examinable concepts before writing cards. Rank by objectives, explanatory centrality, repeated emphasis, and course-specific user choices; permit zero cards from administrative pages.

**Card drafting.** Ask for one independently gradeable retrieval target per card, with an unambiguous cue and a short expected answer. Preserve necessary conditions, units, and exceptions. Atomic does not always mean one word: one causal relationship can be an appropriate target. Cloze deletions should hide a meaningful concept, not an arbitrary word. Do not force every card to stand entirely alone by bloating it with a paragraph of context; include the minimum necessary subject and conditions.

Use a strict schema. An illustrative output is below; IDs and geometry must resolve to stored source objects. The example is about computing and does not represent content extracted from a supplied lecture.

```json
{
  "schema_version": 1,
  "concept_key": "binary-search.precondition",
  "card_type": "basic",
  "question": "What ordering condition does binary search require?",
  "answer": "The searched sequence must be sorted under the comparison used.",
  "evidence": [{
    "document_version_id": "dv_123",
    "page_id": "p_8",
    "block_ids": ["tb_42"],
    "region_id": "r_14",
    "support_quote": "Binary search requires a sorted sequence."
  }],
  "media": [],
  "validation": {"status": "pending", "issues": []}
}
```

**Bounding boxes.** Have the model select known block or figure IDs whenever possible; derive the region from extraction coordinates. When it proposes a new crop, treat its box as an approximation. Normalize to a top-left coordinate system on the canonical, rotation-corrected page, with x, y, width, height in [0,1]. Validate positive dimensions and bounds, and preserve transforms from PDF points, PPTX units, and image pixels. A crop should be rendered and inspected by the checking stage. Coordinates are meaningful only with the exact source version and render.

**Quality gates.** First validate schema, evidence existence, cloze syntax, media availability, answer leakage, and bounds locally. Then check whether every factual clause is supported by the cited evidence, whether the question has one sensible answer, and whether the content is worth studying. Verify numerical values, negation, units, and qualifiers against the source. A second model can help, but correlated errors mean model agreement is not independent proof. Do not ship a repaired answer if the repair itself is unsupported.

**Hallucinations and unsupported content.** Require evidence for the answer, allow abstention, and keep generation closed to the uploaded material by default. Separate paraphrase from inference. If an answer requires missing context, flag the gap rather than fill it from model memory. External explanation can be a later, explicitly labeled feature with its own citations. A citation proves location, not entailment; entailment proves source support, not external truth.

**Duplicates and final selection.** Begin with normalized question/answer hashes, cloze target comparison, and shared concept/evidence IDs. Add embedding similarity within a user's course as a candidate-retrieval method, followed by a judgment of whether two cards test the same thing. Preserve complementary questions such as definition versus application. Prefer a better existing card or propose a revision instead of adding another. Keep a ledger of selected, omitted, redundant, and unsupported concepts; avoid a misleading “100% exam coverage” label.

**Evaluation and reproducibility.** Build a permissioned benchmark spanning native text, dense slides, equations, charts, diagrams, and scans. Hold out lecturers and courses. Have a subject-qualified reviewer assess factual support, atomicity, usefulness, and crop completeness; use adjudication for disagreements. Track accepted-without-substantive-edit rate, critical error rate, objective coverage, duplicate rate, correction minutes, and downstream review burden. Save prompt, provider, model, schema, extraction, and policy versions for every generation. An automated grader is useful after calibration against human judgments.

One API detail materially affects ingestion: current OpenAI file-input documentation says PDFs provide extracted text and page images to a vision model, while non-PDF documents such as PPTX provide text only. Sending a PPTX directly therefore does not preserve its diagrams in model context. Local extraction and rendering also give you better control of evidence identity and cost. [OpenAI file inputs](https://developers.openai.com/api/docs/guides/file-inputs).

**7. Multi-model and BYOK architecture.** Launch with one provider and a capability-aware interface. Add a second provider after measuring either demand or reliability risk. Multiple providers increase testing, support, security, and billing complexity; they do not automatically improve the cards.

Expose a default Balanced preset. Later, offer Fast and Careful, with an estimated processing charge and expected tradeoff. “Best” implies a quality ranking you may not have established. Advanced settings can expose exact supported models, provider accounts, and region policies. Record the actual model even when the interface uses a preset. Changing a preset should not silently change data-processing jurisdiction.

The provider adapter should accept a task type, canonical text blocks and images, evidence IDs, schema, credential reference, timeout, and maximum spend. It should return validated data or a typed failure, provider request ID, token usage including billable reasoning, latency, model ID, and finish/refusal reason. Maintain a capability registry for vision, structured output, token counting, batch support, context limits, retention options, and supported regions. Use small provider-specific adapters over official SDKs; keep business decisions out of those adapters.

Separate scheduling from model execution. The orchestrator chooses an allowed model for each stage, reserves a usage budget, runs a bounded number of retries, validates output, and reconciles actual spend. Cache extraction by source hash and version; cache generation by source, policy, user context, and model version. Do not reuse personalized results across users merely because they uploaded the same file.

For BYOK, store encrypted credentials server-side using a managed secret or key-encryption service, with tenant-scoped access. Log credential references, never keys. Validate with an explicit low-cost request, provide deletion and rotation, and show estimated provider charges. Avoid browser localStorage for long-lived secrets. BYOK users still consume your rendering, storage, synchronization, and support resources. Never fall back silently to a hosted bill or another provider when their key fails.

BYOK does not mean local processing. Explain where content goes and which system stores the key. OpenAI documents that API data is not used for training by default, while retention still depends on logs and endpoint state. Google's Gemini pricing distinguishes free-tier product-improvement use from paid-tier treatment. Do not make a uniform “nothing is stored or used” promise across arbitrary customer accounts. [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data), [Gemini pricing and data treatment](https://ai.google.dev/gemini-api/docs/pricing).

Local models later fit the same interface through an optional desktop/CLI companion. The companion can hold keys and source files locally, and sync approved cards if requested. Model compatibility requires capability and quality testing; an OpenAI-shaped HTTP API alone does not establish equivalent behavior. Keep hosted workers from calling arbitrary user-supplied internal URLs.

**8. Cost model.** Inference is likely manageable for a constrained workflow, but the model choice and verification strategy can change cost by an order of magnitude. The following published rates were checked for this assessment. They are uncached standard prices per million tokens; specialized modalities, long context, regions, and service tiers may differ.

| Model | Input / million | Output / million | Candidate use, subject to evaluation |
|---|---:|---:|---|
| OpenAI GPT-5.6 Luna | $0.20 | $1.20 | Cheap classification and first-pass drafting |
| OpenAI GPT-5.6 Terra | $2.00 | $12.00 | Routine stronger drafting/checking |
| OpenAI GPT-6 Astra | $10.00 | $50.00 | Expensive difficult-case comparison |
| Anthropic Claude Haiku 4.5 | $1.00 | $5.00 | Alternate inexpensive lane |
| Anthropic Claude Sonnet 5 | $2.00 | $10.00 | Alternate stronger lane |
| Google Gemini 3.5 Flash-Lite | $0.30 | $2.50 | Alternate cheap multimodal lane |

Rates: [OpenAI pricing](https://developers.openai.com/api/docs/pricing), [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing), [Google pricing](https://ai.google.dev/gemini-api/docs/pricing). Luna's current model documentation confirms image input and structured outputs; this does not establish acceptable lecture-card quality. [Luna model documentation](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

The illustrative 50-slide workload assumes 25–50 retained cards, averaging 40 for review-burden illustrations. It includes drafting/checking outputs, schema overhead, and a billable reasoning allowance; retained cards are not the sole source of output tokens. Actual image tokenization depends on the model, resolution, and detail setting, so these totals are workload assumptions rather than a universal tokens-per-slide conversion.

| Pipeline | Assumed total billed tokens per 50 slides before retry allowance |
|---|---|
| Naive, flagship for all slides | 100,000 input and 20,000 output on Astra, across all calls |
| Optimized, selective flagship | 40,000 input and 12,000 output on Luna; 15,000 input and 4,000 output on Astra |
| Optimized, selective mid-cost model | Same optimized token totals, using Terra for the stronger lane |
| All-cheap cost reference | Naive token totals, using Luna throughout; quality unknown |

In the optimized scenario, local parsing eliminates redundant visual input, cheap processing sees the document, and roughly 20% of slides need deeper visual analysis or stronger checking. Those escalation tokens must also cover checks on ordinary cards. If evaluation shows every card needs stronger scrutiny, increase that allocation. The cost calculation includes a 20% allowance for retries and regeneration, and assumes no cache or asynchronous batch discount.

`Inference cost = 1.20 × sum((input tokens × input rate + output tokens × output rate) / 1,000,000)`

| Workload | Naive flagship | Selective flagship | Selective mid-cost | All-cheap reference |
|---|---:|---:|---:|---:|
| 50 slides | $2.40 | $0.45 | $0.12 | $0.053 |
| 100 slides | $4.80 | $0.89 | $0.24 | $0.106 |
| Heavy month: 2,000 slides, or 40 × 50-slide lectures | $96.00 | $17.88 | $4.82 | $2.11 |

These are comparable throughput scenarios, not evidence of equivalent card quality. Savings combine reduced token traffic and cheaper model use. The all-cheap comparison is included because a more elaborate pipeline must earn its complexity through quality or reliability, not merely beat an unnecessarily expensive baseline.

For planning, a native lecture might land around $0.10–$0.60 per 50 slides on an evaluated selective pipeline. This is a budgeting hypothesis. Dense scans, multiple visual passes, expensive reasoning, or whole-deck regeneration can exceed it substantially. At three times the modeled token usage, selective mid-cost processing costs about $14.46 for a 2,000-slide month; selective flagship costs about $53.63. Instrument median and 95th-percentile costs before selling large allowances.

Rendering, OCR, object storage, database access, network traffic, retries unrelated to inference, payment fees, free users, and human support are additional costs. Budgeting $100–$300/month for early managed infrastructure is a planning allowance, not a vendor quote; amortization is $1–$3 at 100 paying users versus $0.20–$0.60 at 500. High-resolution retained media can matter more than card text.

Keep hashing, extraction, rendering, cropping, image compression, coordinate transforms, schema validation, exact deduplication, export, and scheduling deterministic. OCR can use a local pretrained engine without paid model calls. Use model calls for ambiguous relevance, semantic compression, visual interpretation, and evidence-aware quality checking. Never add web search or generated images to ordinary card creation by default.

**9. Pricing.** Start by selling one hosted plan. The following is an eventual plan structure to test; it is not a recommendation to implement four billing tiers before learning whether anyone pays.

| Plan | Proposed price | Included use |
|---|---:|---|
| Free | $0 | One 50-page trial, then 25 processing units/month; ordinary review and export remain available |
| Student Hosted | $12/month | 750 standard processing units/month; source-linked cards, online sync, and SRS |
| Heavy Hosted | $24/month | 2,000 standard processing units/month; same quality policy with more capacity |
| BYOK | $5/month plus direct provider charges | 2,000 ordinary-page ingestion allowance; storage/sync and SRS; supported providers only |
| Annual | Initially one month free: $132, $264, or $55 | Monthly-reset allowances; introduce after retention is observed |

One unit should normally mean one supported slide/page processed with Balanced. If Careful uses materially more expensive models, price it transparently at, for example, four units per page, reflecting the approximate scenario cost ratio above. Show the total before the job starts; do not reveal a surprise surcharge after inspecting the file. Launch with one unit class if that is easier to explain. Add a separate scanned-document class only after scans are supported and measured.

Keep the purchased action tied to input processing, not card count. A lecture is an inconsistent unit; tokens are hard for students to understand; generated cards encourage overproduction; opaque AI credits hide value. Pages are imperfect too, especially multi-slide handouts and dense textbook pages. Publish supported size/density limits and quote exceptional documents before processing. Avoid relying on undefined fair use as the only cost control.

Manual edits, studying, source access, and export should not consume AI units. Include one bounded repair/regeneration allowance; additional explicit AI requests can consume quoted units. Failed jobs should restore the user's allowance, although their infrastructure cost remains yours. Offer capped top-ups rather than uncapped automatic overages. Put separate limits on file bytes, retained originals, concurrency, and storage; BYOK needs these limits too.

At full usage, the modeled Student plan costs $1.81 in inference. Assuming $0.75 allocated infrastructure and an illustrative payment cost of 3% + $0.30, its contribution is $8.78, or 73.2%, before tax, refunds, support, free-tier subsidy, and acquisition. The Heavy plan yields about 71.5% on the same basis with $1 infrastructure. These are optimistic if escalation or support is higher than assumed. Five support minutes valued at $40/hour cost $3.33.

All-flagship generation cannot fit these quotas at these prices. Even selective flagship use for every standard page would materially reduce margins, which is why model policy and premium usage need explicit budgets. Do not promise a flagship provider indefinitely inside a fixed cheap subscription.

The core audience is already students: use a fair student price rather than creating a permanently discounted list price. Offer a limited hardship or pilot scholarship program. Avoid stacking annual and student discounts until real margins are known. Support pause/reactivation and easy cancellation; semester seasonality is a retention problem that annual billing can conceal rather than fix. Consumer tax-inclusive pricing may reduce net revenue relative to this table.

**10. Open-source strategy.** Release a genuinely useful converter after the core pipeline has demonstrated demand: local PDF processing, then PPTX support, BYOK generation, source-region manifests, and .apkg output. Sharing the conversion package between the CLI and hosted worker avoids maintaining two unrelated products.

| Open source | Keep commercial initially |
|---|---|
| Source/document/region schema and portable evidence bundle | Hosted orchestration, capacity management, and billing |
| Local ingestion, cropping, baseline generation, and provider adapters | Managed processing, synchronization, support, and polished hosted workflow |
| Anki exporter, compatibility fixtures, and import/export specifications | Account-specific personalization and operational quality routing |
| Public benchmark harness and licensed sample documents | Private evaluation material and customer data for which redistribution rights are absent |

Include working prompts and useful output quality. An intentionally crippled converter undermines the trust argument. A permissive license such as MIT or Apache-2.0 is a practical default if the purpose is adoption and interoperability. A permissive release also makes commercial forks possible; decide consciously whether distribution is worth that tradeoff.

Expect some cannibalization among technical Anki users; they may also be customers who would never subscribe. Trust and community adoption are plausible benefits, not guaranteed growth channels. Measure installation-to-hosted conversion and maintenance hours. GitHub stars do not establish paying demand. Do not make unsolicited promotion in student communities the distribution strategy.

Anki's desktop code uses AGPL-3.0-or-later with component exceptions. That does not by itself require an independently implemented compatible converter to be open source. Reusing or modifying Anki code raises a different licensing question from exporting compatible files. genanki and py-fsrs have permissive MIT licenses. Preserve notices, review actual dependencies, and avoid implying Anki endorsement. Obtain advice for a particular combined distribution instead of assuming a subprocess or separate repository resolves licensing obligations. [Anki license](https://github.com/ankitects/anki/blob/main/LICENSE), [genanki](https://github.com/kerrickstaley/genanki), [py-fsrs](https://github.com/open-spaced-repetition/py-fsrs).

Respecting the ecosystem also means stable identities, useful exports after cancellation, clear compatibility limitations, and contributing fixes upstream. Open sourcing is a strategic choice, not a substitute for those behaviors.

**11. SRS.** Use an established FSRS implementation. Its availability makes the scheduling mathematics a small part of the work; building a reliable study experience is a larger engineering commitment. Python's py-fsrs is a candidate for the proposed stack. Pin the implementation, parameters, and scheduler version. [py-fsrs](https://github.com/open-spaced-repetition/py-fsrs).

Essential launch behavior includes Again/Hard/Good/Easy grading, learning and relearning, a configurable daily new-card limit, due review before excess new material, undo, suspend, sibling spacing, and a clear completion state. Start around the documented 90% desired-retention default. Teach that Hard means successful but difficult recall, while a forgotten answer is Again. Higher retention creates substantially more reviews. [Anki deck options](https://docs.ankiweb.net/deck-options).

The reliability work includes transactional review writes, idempotency, concurrent-tab conflicts, timezone/day-boundary handling, session resumption, backups, and preserving the exact card revision that was reviewed. Online-only synchronization is enough for the beta. Offline conflict resolution, cross-platform native clients, custom study modes, and automated parameter optimization can follow.

Generation errors can often be withheld or regenerated. A scheduler that loses reviews or silently changes mature cards damages months of work. Test duplicate submissions, undo, clock/day transitions, and restore behavior meaningfully. Do not spend the same effort testing every cosmetic card edit.

Retain a learning mode for basic understanding, but do not force every concept into SRS. Application-heavy material still needs worked problems or cases. A review score shows recall on that item, not comprehensive mastery of its topic.

**12. Data model.** Make provenance an explicit relationship on a card revision. Do not store it as an optional free-text URL on the latest card. Anki's note-versus-card distinction is relevant: one cloze note can generate several independently scheduled cards. [genanki's note model](https://github.com/kerrickstaley/genanki).

| Entity | Key fields and relationships |
|---|---|
| User / workspace | Owner, memberships, processing policy, timezone, quota |
| Course | Owner/workspace, title, language, optional exam date |
| Lecture | Course, title, sequence/date; associates one or more source documents |
| SourceDocument | Logical document identity, owner, original filename, lecture association |
| DocumentVersion | Immutable content hash, object key, upload timestamp, format, parser/renderer versions |
| Page | Document version, index, displayed page label, dimensions, rotation, canonical render asset |
| TextBlock | Page, stable extraction ID within version, text, reading order, native/OCR origin, geometry |
| MediaAsset | Immutable bytes/hash, MIME type, dimensions, storage key |
| Figure / FigurePlacement | Logical figure, page placement, asset links, crop/rotation transforms, caption/label block IDs |
| Region | Page, normalized box or polygon, coordinate-system version, selection method; may refer to a block or figure |
| Concept | Course-scoped learning target and optional objective; relationships may be uncertain |
| Note | Basic/cloze/image content family; groups sibling card variants |
| Card | Stable retrieval identity, note, variant key, active revision, lifecycle status |
| CardRevision | Immutable prompt/answer/media payload, creator, generation run, parent revision, evidence status |
| CardEvidence | Revision-to-source relation; one or more pages, blocks, regions, or notes; support type and source quote |
| UserCardState | User/card, due time, stability, difficulty, stage, lapses, last review, scheduler version, concurrency version |
| ReviewEvent | User/card/revision, timestamp, rating, duration, prior/resulting state, scheduler parameters, idempotency key |
| GenerationRun / UsageEvent | Input versions, prompts, models, stages, failures, tokens, spend, user quota settlement |
| ExternalMapping | Internal note/card IDs, Anki note GUID/model ID/variant, import version, export state |

Use foreign keys and tenant checks. A composite foreign-key or equivalent invariant should prevent evidence for one tenant's card pointing into another tenant's document. Imported cards may legitimately lack lecture provenance; mark their origin as imported instead of inventing a source.

The central graph is `Course → Lecture → DocumentVersion → Page → Block/Figure/Region ← CardEvidence ← CardRevision ← Card`, with `UserCardState` and `ReviewEvent` attached to the stable card identity. `Note → Card` expresses siblings, and one revision may cite multiple sources. Originals, figures, and page renders live in object storage; relational references and state live in PostgreSQL.

A spelling correction can preserve the card's schedule. A change to the retrieval target should create a new card or an explicit relearning decision. Splitting retires the parent and creates children with lineage; do not copy the parent's mature memory state to unrelated new questions. Replacing lecture.pdf creates a new document version, not an overwrite of old evidence. Source deletion requires a clear choice about dependent excerpts/media; privacy deletion may intentionally make old evidence unavailable, which must be shown honestly.

Portability requires more than a hosted link. Export basic/cloze cards with local media, readable source title/page, an evidence crop when appropriate, and stable note IDs. Also provide JSON plus media/originals where authorized, including revisions and review events. Hosted signed URLs expire and cannot be the sole exported evidence. A source bundle can retain full-page provenance without embedding every full original into every .apkg.

For beta import, support a declared subset of basic and simple-cloze notes and media, with a pre-import report. Preserve unsupported raw material for download without executing arbitrary Anki template JavaScript in the web app. Let imported cards start with fresh scheduling only after that choice is explicit. Anki packages can carry scheduling information, but generic export libraries do not guarantee a faithful schedule migration between applications. Content portability, review-history export, and exact scheduling round-trip are separate promises. [Anki export manual](https://docs.ankiweb.net/exporting.html), [packaged-deck import](https://docs.ankiweb.net/importing/packaged-decks.html?highlight=interval).

**13. Pragmatic stack.** I would use a Python-centered modular monolith. One developer should spend most time on card quality and the study workflow, not on coordinating several application frameworks.

| Layer | Recommendation | Reason / boundary |
|---|---|---|
| Frontend | Django templates, HTMX, small TypeScript components, simple CSS | Enough for course lists and a reviewer; use a focused component for regions |
| Source viewer | PDF.js, with an overlay for evidence regions | Browser rendering and navigation; keep stored canonical coordinates authoritative |
| Backend | Django, PostgreSQL ORM, Pydantic for model-output schemas | Accounts, migrations, admin, and explicit domain logic in one codebase |
| Database | Managed PostgreSQL | Transactions, provenance joins, review history; add pgvector only if similarity search needs it |
| Object storage | Private S3-compatible storage | Originals, page renders, crops, exports; short-lived signed access and lifecycle rules |
| PDF | pdfplumber plus pypdfium2 | Geometry extraction and rendering without adopting PyMuPDF by default |
| PPTX, after beta | python-pptx and isolated LibreOffice | Native text/media plus canonical rendering |
| Images / OCR | Pillow, optional OpenCV, Tesseract initially | Deterministic crops and a bounded OCR path; benchmark before adding more engines |
| Background work | RQ with Redis or Valkey; durable job metadata in PostgreSQL | Simple workers, retries, concurrency controls, and resumable stages |
| AI | Official provider SDKs behind a small internal adapter | Avoid an agent framework for a fixed pipeline |
| SRS | py-fsrs | Established scheduling implementation |
| Anki export | genanki for tested basic/cloze templates and media | Stable GUID mapping; native IO and review migration need separate implementation |
| Authentication | Django sessions plus a maintained email/social-auth integration | Avoid inventing password or token handling |
| Payments | Stripe Checkout and customer self-service portal | Hosted payment collection; signed, idempotent webhooks update entitlements |
| Deployment | One web service, one containerized worker, managed DB/queue/storage | Separate CPU-heavy conversion from web requests; no Kubernetes required |

If React/Next.js is already your strongest stack, keep it for the interface and use a Python worker/backend; familiarity can outweigh this recommendation. Do not maintain duplicate domain rules across Python and TypeScript. The selected browser viewer, queue, and payment products document these core roles. [PDF.js](https://mozilla.github.io/pdf.js/), [RQ](https://python-rq.org/docs/), [Stripe Checkout](https://docs.stripe.com/payments/checkout).

Check the actual dependency licenses early. PyMuPDF is available under AGPL or a commercial license; it is technically attractive but not an automatic fit for a proprietary service. pypdfium2 documents Apache/BSD terms for its own code and additional PDFium dependency notices. A license-friendly choice still requires preserving relevant notices in distributions. [PyMuPDF FAQ](https://pymupdf.readthedocs.io/en/latest/faq/index.html), [pypdfium2 licensing](https://github.com/pypdfium2-team/pypdfium2).

**14. Failure modes, ranked.** Priority combines likely business impact and technical consequences for this particular launch. A severe security incident can outrank everything when it occurs.

| Rank | Risk | Leading signal | Practical response |
|---:|---|---|---|
| 1 | Cards require extensive editing or test the wrong things | Low unchanged-acceptance rate; no preparation-time saving | Narrow the course, improve selection, and compare with human cards |
| 2 | Students try one lecture and never return or pay | Low second/third upload and weak paid renewal | Investigate the real study workflow before adding features |
| 3 | Plausible wrong answers, omitted caveats, and overtrust | Unsupported claims in blind audit; source link used as false reassurance | Evidence gates, abstention, explicit uncertainty, and critical-error tracking |
| 4 | Duplicate or excessive cards produce an unmanageable queue | Rising due backlog, mass suspension, low study completion | Conservative selection, objective coverage, deduplication, new-card limits |
| 5 | Bad crops or visually complex slides remove essential meaning | Missing axes/labels, incorrect masks, unusable mobile images | Larger evidence regions, targeted high-resolution review, bounded support |
| 6 | Lost review history or destructive regeneration | State conflicts, surprising due dates, broken exports | Transactional events, stable identities, backups, migration checks |
| 7 | Copyright, personal-data, or credential exposure | Public document leakage, unauthorized sharing, keys in logs | Private defaults, scoped access, deletion, restricted processing, no shared corpus by default |
| 8 | Heavy users and support overwhelm margins | High 95th-percentile cost; frequent repair requests | Visible quotas, hard job budgets, measured premium routing |
| 9 | Provider changes break generation or change quality | Schema/refusal spikes, regression on held-out lectures | Versioned adapters, bounded fallback, canary evaluations |
| 10 | Scope and maintenance overwhelm one developer | More time on imports, mobile sync, and provider quirks than learning quality | Keep the beta boundary; defer generality |

Copyright needs a specific product policy. Students having access to slides does not establish permission to publish their figures, train on them, or redistribute derivative decks. Keep uploads private, collect only the processing permissions needed, provide deletion and a takedown route, and obtain explicit permission for benchmark reuse. Do not offer a public lecture marketplace initially. In the United States, educational purpose is one part of a fact-specific fair-use analysis, not an automatic exemption for a commercial service. Other jurisdictions differ; review the initial launch jurisdiction before commercialization. [U.S. Copyright Office](https://www.copyright.gov/fair-use/).

Medical lectures may contain patient material, and an institution's upload rules may be stricter than a provider's standard terms. Begin with permitted teaching files that do not contain identifiable patient data. This is a product-scope choice, not a claim that standard cloud hosting establishes health-data compliance. File and key handling deserve attention alongside card accuracy because BYOK adds a financially valuable secret to every account.

**15. Differentiation and moat.** Distinguish a valuable feature from a durable advantage. Most of these ideas matter to users, but only some can compound.

| Idea | User value | Defensibility assessment |
|---|---|---|
| Permanent source links | Fast checking and context recovery | Necessary foundation; easy to copy and already present elsewhere |
| Precise source regions | Lower verification effort, especially with diagrams | Harder to implement robustly; defensible only through reliability and accumulated evaluation cases |
| Image/diagram understanding | Makes visual lectures usable | Strong initial specialization if measured; exposed to model improvements and existing competition |
| Regeneration from context | Repairs awkward cards efficiently | Useful convenience; readily copied |
| Generation that avoids already-known material | Reduces repeated study burden across lectures | Potentially strong if based on reliable concept mapping and sufficient personal history |
| Detecting weak areas | Guides what to study next | Generic dashboards are common; actionable, validated diagnosis is harder |
| Adaptive future generation | Can correct misunderstandings without multiplying cards | Promising later; requires experiments showing benefit and safeguards against feedback loops |
| Course-specific quality and distribution | Relevant language, known materials, repeat cohort adoption | Strongest practical early advantage when permissioned and reproducible across courses |

Review history is biased evidence: students may grade inconsistently, a card may be badly written, and recall of a label may not imply understanding. Treat a “weak concept” as a hypothesis and first inspect the existing card. Do not automatically generate five more cards whenever one is missed. A good adaptation might clarify one ambiguous cue or suggest a worked example instead.

A credible compounding system connects a source-supported claim, its card revisions, reason-coded student corrections, and later retrieval outcomes. Test whether it improves the next lecture's cards compared with a non-personalized baseline. Aggregate learning across students requires suitable permissions and careful control of course and content differences. Private uploads are not automatically a legally reusable data moat.

The best defensibility is the combination of trusted course distribution, demonstrated reduction in study work, and a pipeline that improves from real failures. It will take repeated use and careful evaluation to establish; do not put a network-effect claim in the pitch before those loops exist.

**16. Roadmap.** Sequence by learning risk. The six-week beta includes the first two weeks; subsequent dates depend on the quality and demand gates.

| Period | Deliverable | Exit evidence |
|---|---|---|
| Days 1–3 | Recruit 10–15 students; collect permitted PDFs; observe current card-making; define objectives with a subject reviewer | Repeated, substantial pain on a specific course workflow |
| Days 4–7 | Native-PDF extraction/rendering; basic structured drafting; source references; simple .apkg export | End-to-end results on ten varied lecture files |
| Days 8–14 | Evidence viewer; manual correction; measured comparison against a generic baseline and direct competitors | A quality/time advantage worth continuing; no polished subscription app required yet |
| Week 3 | Persistent course/deck interface, revision-aware editing, selective generation, omission reporting | Users can complete the upload-to-useful-cards workflow independently |
| Week 4 | Minimal online FSRS reviewer, transactional review events, undo/suspend/new-card limits | Review state survives retries, concurrent tabs, and restore |
| Week 5 | Limited Anki import, export compatibility fixtures, accounts, usage ledger, basic payments and deletion | Supported data moves correctly; paid quotas and access controls hold |
| Week 6 | Harden jobs, audit quality, improve mobile web usability; invite 20–30 target users | Actual paid use and repeated lectures; treat this as a private beta |
| Month 2 | Repair dominant quality failures; add PPTX only if it blocks active users; rectangular occlusion if visual demand is strongest | Better acceptance/time metrics and an initial paid renewal cohort |
| Month 3 | Release shared converter core/CLI; one additional provider and optional BYOK; bounded OCR | Demand justifies each new processing path and maintenance cost |
| Month 4 | Cross-lecture deduplication, better course coverage, exam workload controls | Lower review burden without lower objective coverage |
| Month 5 | Personalization experiment and improved visual-card quality | Measurable benefit on held-out lectures and later recall |
| Month 6 | Expand to a second subject/institution; improve portability; add offline support only if retention requires it | Positive contribution economics and repeatable acquisition beyond the original cohort |

Do not add native apps, tutoring, recording, and broad scheduling migration merely because six months have elapsed. If the first paid cohort does not repeatedly use the product, the roadmap becomes further customer investigation or a smaller converter business. Allow contingency for complex imports and source rendering; if the six-week deadline becomes unrealistic, reduce supported formats instead of relaxing review-state integrity.

**17. Verdict and first experiments.** I would spend two weeks validating this idea. I would not commit six months to the full product from the current specification. The strongest version is a trusted assistant for course-specific card creation, with excellent visual evidence, a small optional SRS experience, and first-class export.

I would abandon or materially change the direction if the cards require so much checking that preparation time barely improves, if current tools match the quality on the target materials, if students consistently prefer existing course decks, or if repeated use does not convert into payment. I would also reconsider if source rights prevent the required workflow or if the support and processing cost cannot fit student pricing. Strong export demand with weak reviewer adoption would support an Anki companion business; it would be evidence against prioritizing an Anki replacement.

**Experiment 1: a blind card-quality comparison.** Use 12–20 permitted lectures across at least two instructors and several visual formats. Compare a human baseline, a generic model-generated baseline, RemNote, and at least one direct slide-to-Anki competitor with the prototype. Have two knowledgeable reviewers assess a mixed, randomized sample, with adjudication. Measure supported correctness, atomicity, usefulness, duplicate rate, and coverage of agreed objectives. Separate setup time and student repair time from founder repairs.

Suggested continuation gates are at least 85% of cards accepted without substantive edits, no critical error in an initial audit of 300 auto-ready cards, and at least 90% coverage of the agreed essential objectives. These are proposed gates, not industry standards. Zero observed critical errors in 300 independent samples still leaves a rough 95% upper bound near 1% on the underlying error rate; clustered cards make the evidence weaker. Continue auditing after launch rather than declaring the system safe from one test.

**Experiment 2: observe the time-to-study workflow.** Run a randomized crossover with 10–15 students on matched lectures using their normal process and the prototype. Measure active preparation minutes, corrections, cards actually studied, and seven-day recall on externally written questions covering the objectives. Target at least a 50% reduction in active preparation time, with no material loss in coverage or recall. This pilot can detect obvious workflow failure; it is too small to establish learning noninferiority formally.

Record why users edit or reject a card, and whether the source viewer resolves the issue quickly. Count all intervention time. If a founder spends 30 minutes rescuing every lecture behind the scenes, the product has not demonstrated five-minute automation. The seven-day test also checks whether bypassing manual card construction loses a useful learning step.

**Experiment 3: sell a four-week course pilot.** After sufficient quality, recruit 20–30 qualified students and charge approximately $12 for a real month, with clearly explained scope. Compare in-app review adoption with Anki export adoption. A reasonable directional signal would be at least ten paying users, a majority of payers processing three or more distinct lectures, and at least half renewing or paying for the next active teaching month. These are small-sample decision rules, not statistically reliable conversion forecasts.

Track source-specific acquisition effort, contribution after actual provider and support costs, and use outside the immediate exam crunch. Interviews and wait-list signups are useful recruitment tools; repeat paid use is the decisive evidence. Expand engineering effort only if the product wins on real lectures and students return because it makes studying materially easier.

**Sources.** Official product pages and live documentation below were checked September 9, 2026 unless a publication date is stated. Vendor claims establish advertised features, not independently verified quality. Dynamic pricing can vary by billing period, region, account, and later revision.

1. Anki. [Official product site](https://apps.ankiweb.net/). Product scope and ecosystem.
2. Anki. [Adding/Editing manual](https://docs.ankiweb.net/editing.html). Card types and native image occlusion.
3. RemNote. [Pricing](https://www.remnote.com/pricing). Displayed annual plans and included features.
4. RemNote Help Center. [Learning from PDFs and Files with the RemNote Reader](https://help.remnote.com/en/articles/6690975-learning-from-pdfs-and-files-with-the-remnote-reader). Linked text and area references.
5. Quizlet. [AI Study Guide Maker](https://quizlet.com/features/study-guides/). Uploaded course materials and generated study resources.
6. Knowt. [Flashcards](https://knowt.com/flashcards). Study modes and positioning.
7. Abheek Pandoh, Knowt. [Differences between free and paid student accounts](https://help.knowt.com/en/articles/10298016-what-are-the-differences-between-free-and-paid-accounts-for-students), August 8, 2025. Student features; dated and internally inconsistent pricing.
8. Knowt. [Plans](https://knowt.com/plans). Public pricing display and account-type ambiguity.
9. StudyFetch. [Spaced Repetition App](https://www.studyfetch.com/spaced-repetition-app). Advertised generation and scheduled review.
10. AnkiDecks. [Pricing](https://www.anki-decks.com/payment/pricing/). Annual plans, image processing, and study features.
11. SlideToAnki. [Product and pricing](https://slidetoanki.com/). Direct competitor's source, coverage, visual, and feedback claims.
12. Clozely. [Product site](https://clozely.app/). Source-linked drafting and Anki workflow.
13. Google. [Create flashcards and quizzes in the NotebookLM app](https://blog.google/innovation-and-ai/models-and-research/google-labs/notebooklm-app-quizzes-flashcards/), November 6, 2025. Documented flashcard functionality; not proof of scheduler parity.
14. David M. Harris and Michael Chiang. [An Analysis of Anki Usage and Strategy of First-Year Medical Students in a Structure and Function Course](https://pubmed.ncbi.nlm.nih.gov/35494926/), Cureus, March 27, 2022. DOI: 10.7759/cureus.23530. Single-school behavioral evidence.
15. OpenAI. [API pricing](https://developers.openai.com/api/docs/pricing). Current rates used in calculations.
16. Anthropic. [Claude Platform pricing](https://platform.claude.com/docs/en/about-claude/pricing). Alternate-provider rates.
17. Google. [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing). Rates and free/paid data-use distinction.
18. OpenAI. [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna). Documented input and output capabilities.
19. OpenAI. [File inputs](https://developers.openai.com/api/docs/guides/file-inputs). PDF versus non-PDF image handling.
20. OpenAI. [Your data](https://developers.openai.com/api/docs/guides/your-data). Training defaults and retention distinctions.
21. python-pptx maintainers. [Shapes API](https://python-pptx.readthedocs.io/en/latest/api/shapes.html?highlight=add_picture), [project documentation](https://python-pptx.readthedocs.io/en/stable/). Shape/media APIs and format limitations.
22. The Document Foundation. [Starting LibreOffice with parameters](https://help.libreoffice.org/latest/gu/text/shared/guide/start_parameters.html). Headless document conversion.
23. Jeremy Singer-Vine and contributors. [pdfplumber](https://github.com/jsvine/pdfplumber). Geometry extraction and image reconstruction limitations.
24. pypdfium2 maintainers. [Repository and licensing](https://github.com/pypdfium2-team/pypdfium2). Rendering bindings and component licenses.
25. Artifex. [PyMuPDF FAQ](https://pymupdf.readthedocs.io/en/latest/faq/index.html). AGPL/commercial licensing.
26. Open Spaced Repetition. [py-fsrs](https://github.com/open-spaced-repetition/py-fsrs). Scheduler package, MIT license, and usage.
27. Anki. [Deck Options](https://docs.ankiweb.net/deck-options). FSRS behavior, retention, and grading.
28. Anki contributors. [Anki license](https://github.com/ankitects/anki/blob/main/LICENSE). AGPL and component exceptions.
29. Kerrick Staley and contributors. [genanki](https://github.com/kerrickstaley/genanki). Export library, note/card model, and MIT license.
30. Anki. [Exporting](https://docs.ankiweb.net/exporting.html), [Packaged Decks](https://docs.ankiweb.net/importing/packaged-decks.html?highlight=interval). Package and scheduling interchange.
31. Mozilla. [PDF.js](https://mozilla.github.io/pdf.js/). Browser PDF rendering.
32. RQ maintainers. [Documentation](https://python-rq.org/docs/). Python job workers and Redis/Valkey support.
33. Stripe. [Checkout](https://docs.stripe.com/payments/checkout). Hosted payment integration; fee assumptions in this memo are not quoted Stripe rates.
34. U.S. Copyright Office. [Fair Use Index and guidance](https://www.copyright.gov/fair-use/), index updated July 2026. Fact-specific U.S. copyright analysis.
