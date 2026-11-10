// Small, conservative content rules; no provider calls (port of selection.py).
import { fingerprint, payloadItems, type Draft } from "./cards.ts";
import { WorkflowError } from "./errors.ts";
import { plainQuestions, studyCardCount } from "./noteTypes.ts";
import { casefold, isPlainObject, normalized, pyRegex } from "./py.ts";

export function defaultCardLimit(pageCount: number): number {
  return Math.max(1, Math.floor((pageCount + 1) / 2));
}

export function checkedCardLimit(
  value: unknown,
  pageCount: number,
  {
    cardFormat = "basic",
    textEnabled = true,
    occlusionEnabled = false,
  }: { cardFormat?: string; textEnabled?: boolean; occlusionEnabled?: boolean } = {},
): number {
  let minimum = textEnabled ? (cardFormat === "reversed" ? 2 : 1) : 0;
  minimum = Math.max(1, minimum + Number(occlusionEnabled));
  if (value === null || value === undefined || value === "") {
    return Math.max(minimum, defaultCardLimit(pageCount));
  }
  if (typeof value === "boolean" || !/^[0-9]{1,3}$/.test(String(value))) {
    throw new WorkflowError("Choose a card limit from 1 to 500.");
  }
  const limit = Number.parseInt(String(value), 10);
  if (!(limit >= 1 && limit <= 500)) {
    throw new WorkflowError("Choose a card limit from 1 to 500.");
  }
  if (limit < minimum) {
    if (occlusionEnabled) {
      throw new WorkflowError(
        `The selected formats need room for at least ${minimum} cards, including an image suggestion.`,
      );
    }
    throw new WorkflowError("Basic + reverse needs room for two cards. Set Maximum new cards to at least 2.");
  }
  return limit;
}

// An examination can itself be course content (e.g. a clinical examination).
const SUBJECT_EXAMINATION = pyRegex(
  String.raw`\b(?:clinical|physical|medical|neurological|patient|klinisch\w*|körperlich\w*|medizinisch\w*)\b`,
);
const LOGISTICS_QUESTIONS = [
  String.raw`\b(?:exam|examination|midterm)\s+(?:duration|date|location|format)\b`,
  String.raw`\b(?:prüfungs|pruefungs|klausur)(?:dauer|termin|ort|format)\b`,
  String.raw`^(?:how long|when|where|what (?:date|time|duration|format))\b.{0,55}\b(?:the|this|our|final|midterm|written|oral)\s+(?:exam|examination)\b`,
  String.raw`\b(?:exam|examination|midterm)\b.{0,35}\b(?:take place|scheduled|lasts?|start|end)\b`,
  String.raw`\b(?:materials|tools|aids|calculators|books|notes)\b.{0,55}\b(?:allowed|permitted)\b.{0,35}\bexam\b`,
  String.raw`\bwhat (?:material|topics|content|chapters)\b.{0,35}\bexam\b.{0,20}\bcover`,
  String.raw`\bexpected exam difficulty\b|\bhow difficult\b.{0,35}\b(?:the|this) exam\b`,
  String.raw`\b(?:course|exam|module)\b.{0,25}\b(?:graded|weighted|grading)\b`,
  String.raw`^(?:wie lange|wann|wo)\b.{0,45}\b(?:prüfung|pruefung|klausur)\w*\b`,
  String.raw`\b(?:hilfsmittel|materialien|themen|stoff)\b.{0,55}\b(?:prüfung|pruefung|klausur)\w*\b`,
].map((pattern) => pyRegex(pattern));
const LOGISTICS_TOPICS = pyRegex(
  String.raw`\b(?:office hours|sprechstunde\w*|course registration|course timetable|lecture schedule)\b` +
    String.raw`|\b(?:course|module|kurs|modul)\b.{0,40}\b(?:graded|grading|credits|ects|benotet|anmeldung)\b` +
    String.raw`|\b(?:email|e-mail|contact)\b.{0,35}\b(?:lecturer|instructor|professor|teaching assistant)\b`,
);

export function isCourseLogistics(front: string, sourceQuote = ""): boolean {
  const question = casefold(normalized(front));
  const context = question + " " + casefold(normalized(sourceQuote));
  if (SUBJECT_EXAMINATION.test(context)) return false;
  if (LOGISTICS_QUESTIONS.some((pattern) => pattern.test(question))) return true;
  return LOGISTICS_TOPICS.test(question);
}

export interface ExistingNote {
  fingerprint: string;
  front: string;
  back: string;
  noteType: string;
}

/** Filter clear logistics, then keep unique drafts in the model's priority order. */
export function selectDrafts(
  existing: readonly ExistingNote[],
  validated: readonly Draft[],
  limit: number | null = null,
): { selected: Draft[]; filtered: number; overLimit: number } {
  const seen = new Set(existing.map((note) => note.fingerprint));
  // An edited question may differ from its immutable generation fingerprint.
  for (const note of existing) {
    for (const question of plainQuestions(note.front, note.back, note.noteType)) seen.add(fingerprint(question));
  }
  const selected: Draft[] = [];
  let filtered = 0;
  let overLimit = 0;
  let selectedCards = 0;
  for (const item of validated) {
    const questions = plainQuestions(item.front, item.back, item.noteType);
    if (questions.some((question) => isCourseLogistics(question, item.sourceQuote))) {
      filtered += 1;
      continue;
    }
    const keys = questions.map((question) => fingerprint(question));
    if (keys.some((key) => seen.has(key))) continue;
    const count = studyCardCount(item.front, item.noteType);
    if (limit !== null && selectedCards + count > limit) {
      overLimit += 1;
    } else {
      for (const key of keys) seen.add(key);
      selected.push(item);
      selectedCards += count;
    }
  }
  return { selected, filtered, overLimit };
}

/** Up to 200 plain questions from the newest notes first. */
export function recentQuestions(
  newestFirst: readonly { front: string; back: string; noteType: string }[],
): string[] {
  const questions: string[] = [];
  for (const note of newestFirst.slice(0, 200)) {
    questions.push(...plainQuestions(note.front, note.back, note.noteType));
  }
  return questions.slice(0, 200);
}

export function filterGeneratedLogistics(payload: unknown): [{ cards: unknown[] }, number] {
  const cards: unknown[] = [];
  let filtered = 0;
  for (const item of payloadItems(payload)) {
    if (
      isPlainObject(item) &&
      typeof item.front === "string" &&
      typeof item.back === "string" &&
      typeof item.source_quote === "string" &&
      plainQuestions(item.front, item.back, typeof item.note_type === "string" ? item.note_type : "basic").some(
        (question) => isCourseLogistics(question, item.source_quote as string),
      )
    ) {
      filtered += 1;
    } else {
      cards.push(item);
    }
  }
  return [{ cards }, filtered];
}
