// Note content validation and generated-batch checks (port of cards.py).
import { WorkflowError } from "./errors.ts";
import { formatTypes, plainFront, studyCardCount, type CardFormat, type NoteType } from "./noteTypes.ts";
import { casefold, cpLength, cpSlice, hasExactKeys, isInt, isPlainObject, normalized, pyStrip } from "./py.ts";
import { sha256Hex } from "./sha256.ts";

export interface PageText {
  number: number;
  text: string;
}

export interface Draft {
  page: number;
  front: string;
  back: string;
  sourceQuote: string;
  noteType: NoteType;
}

export interface GenerationIssue {
  page: number | null;
  batch_pages: number[];
  reason: string;
  front: string;
  back: string;
  source_quote: string;
}

export { normalized };

export function fingerprint(front: string, noteType: string = "basic"): string {
  return sha256Hex(casefold(normalized(plainFront(front, noteType))));
}

export function validateContent(
  front: unknown,
  back: unknown,
  quote: unknown,
  page: PageText,
  { requireQuote = false, noteType = "basic" }: { requireQuote?: boolean; noteType?: string } = {},
): [string, string, string] {
  for (const [label, value, limit] of [
    ["Question", front, 1000],
    ["Answer", back, 5000],
    ["Source excerpt", quote, 2500],
  ] as const) {
    if (typeof value !== "string" || cpLength(value) > limit || value.includes("\x00")) {
      throw new WorkflowError(`${label} is invalid or too long.`);
    }
  }
  const f = front as string;
  const b = back as string;
  const q = quote as string;
  studyCardCount(f, noteType);
  if (!pyStrip(f) || (noteType !== "cloze" && noteType !== "occlusion" && !pyStrip(b))) {
    throw new WorkflowError("Both a question and an answer are required.");
  }
  if (noteType === "reversed" && casefold(normalized(f)) === casefold(normalized(b))) {
    throw new WorkflowError("Use different text on the two sides of a reverse note.");
  }
  if (requireQuote && !pyStrip(q)) {
    throw new WorkflowError("Each generated card needs an exact supporting source excerpt.");
  }
  if (pyStrip(q) && !normalized(page.text).includes(normalized(q))) {
    throw new WorkflowError(
      `The source excerpt is not present on page ${page.number}. Check the page and excerpt.`,
    );
  }
  return [pyStrip(f), pyStrip(b), pyStrip(q)];
}

export function payloadItems(payload: unknown): unknown[] {
  if (!hasExactKeys(payload, ["cards"]) || !Array.isArray(payload.cards)) {
    throw new WorkflowError('Expected a JSON object containing a "cards" array.');
  }
  if (payload.cards.length > 500) {
    throw new WorkflowError("Import at most 500 draft cards at a time.");
  }
  return payload.cards;
}

const REQUIRED = ["front", "back", "page", "source_quote"] as const;

export function validateItem(
  item: unknown,
  pages: ReadonlyMap<number, PageText>,
  index: number,
  cardFormat: CardFormat | string = "all",
): Draft {
  if (!hasExactKeys(item, REQUIRED) && !hasExactKeys(item, [...REQUIRED, "note_type"])) {
    throw new WorkflowError(`Card ${index} must contain front, back, page and source_quote.`);
  }
  if (!isInt(item.page) || !pages.has(item.page)) {
    throw new WorkflowError(`Card ${index} refers to a page outside the selected lecture pages.`);
  }
  const page = pages.get(item.page)!;
  const noteType = Object.hasOwn(item, "note_type") ? item.note_type : "basic";
  if (typeof noteType !== "string" || !(formatTypes(cardFormat) as readonly string[]).includes(noteType)) {
    throw new WorkflowError(`Card ${index} does not use the requested ${cardFormat} format.`);
  }
  const [front, back, quote] = validateContent(item.front, item.back, item.source_quote, page, {
    requireQuote: true,
    noteType,
  });
  return { page: page.number, front, back, sourceQuote: quote, noteType: noteType as NoteType };
}

/** Explicit file imports stay atomic: the first invalid draft rejects the file. */
export function validatePayload(payload: unknown, pages: ReadonlyMap<number, PageText>): Draft[] {
  return payloadItems(payload).map((item, i) => validateItem(item, pages, i + 1));
}

/** Keep good drafts and report individual failures without trusting bad source links. */
export function validateGeneratedBatch(
  payload: unknown,
  pages: ReadonlyMap<number, PageText>,
  cardFormat: CardFormat | string = "mixed",
): { validated: Draft[]; issues: GenerationIssue[] } {
  const validated: Draft[] = [];
  const issues: GenerationIssue[] = [];
  payloadItems(payload).forEach((item, i) => {
    try {
      validated.push(validateItem(item, pages, i + 1, cardFormat));
    } catch (error) {
      if (!(error instanceof WorkflowError)) throw error;
      const data = isPlainObject(item) ? item : {};
      const number = data.page;
      const bounded = (key: string, limit: number) => {
        const value = data[key];
        return typeof value === "string" ? cpSlice(value, 0, limit).replaceAll("\x00", "") : "";
      };
      issues.push({
        page: isInt(number) && pages.has(number) ? number : null,
        batch_pages: [...pages.keys()],
        reason: error.message,
        front: bounded("front", 1000),
        back: bounded("back", 5000),
        source_quote: bounded("source_quote", 2500),
      });
    }
  });
  return { validated, issues };
}
