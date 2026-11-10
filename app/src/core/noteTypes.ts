// Supported note formats and actual Anki card counts (port of note_types.py).
import { WorkflowError } from "./errors.ts";
import { partition, pyStrip } from "./py.ts";

export const TEXT_NOTE_TYPES = ["basic", "cloze", "reversed"] as const;
export const NOTE_TYPES = ["basic", "cloze", "reversed", "visual", "occlusion"] as const;
export type NoteType = (typeof NOTE_TYPES)[number];
export type TextNoteType = (typeof TEXT_NOTE_TYPES)[number];

export const NOTE_TYPE_LABELS: Record<NoteType, string> = {
  basic: "Basic Q/A",
  cloze: "Cloze",
  reversed: "Basic + reverse",
  visual: "Graph / formula question",
  occlusion: "Image occlusion",
};

export const FORMAT_TYPES = {
  basic: ["basic"],
  cloze: ["cloze"],
  reversed: ["reversed"],
  mixed: ["basic", "cloze"],
  basic_reversed: ["basic", "reversed"],
  cloze_reversed: ["cloze", "reversed"],
  all: ["basic", "cloze", "reversed"],
} as const satisfies Record<string, readonly TextNoteType[]>;
export type CardFormat = keyof typeof FORMAT_TYPES;
export const CARD_FORMATS = Object.keys(FORMAT_TYPES) as CardFormat[];

export const LEARNING_FOCUSES = {
  balanced: "Balanced",
  core: "Core knowledge",
  understanding: "Understanding",
  application: "Application",
} as const;
export type LearningFocus = keyof typeof LEARNING_FOCUSES;
export const FOCUS_INSTRUCTIONS: Record<LearningFocus, string> = {
  balanced:
    "Balance core knowledge, explanations, distinctions, and applications according to the supplied material.",
  core: "Prioritize essential definitions, terminology, key facts, and formulas with their meaning and conditions.",
  understanding:
    "Prioritize why and how, causal explanations, connections, and distinctions between similar concepts. For cloze, hide a meaningful part of an explanation rather than isolated trivia.",
  application:
    "Prioritize when to choose a method, how to apply a procedure, and the reasoning in supplied worked examples. Do not invent exercises, numerical data, solutions, or prerequisites absent from the source.",
};

const CLOZE_SOURCE = String.raw`\{\{c([1-9]|1[0-9]|20)::([^{}]+)\}\}`;
const clozePattern = () => new RegExp(CLOZE_SOURCE, "gu");

export function checkedChoice<T extends string>(value: unknown, choices: readonly T[], label: string): T {
  if (typeof value !== "string" || !(choices as readonly string[]).includes(value)) {
    throw new WorkflowError(`Choose a supported ${label}.`);
  }
  return value as T;
}

export function formatTypes(cardFormat: unknown): readonly TextNoteType[] {
  return FORMAT_TYPES[checkedChoice(cardFormat, CARD_FORMATS, "card format")];
}

export function formatFromTypes(types: readonly string[]): CardFormat {
  if (!types.length || new Set(types).size !== types.length) {
    throw new WorkflowError("Tick at least one card format, without duplicate choices.");
  }
  for (const [value, members] of Object.entries(FORMAT_TYPES)) {
    if (members.length === types.length && members.every((member) => types.includes(member))) {
      return value as CardFormat;
    }
  }
  throw new WorkflowError("Tick only supported card formats.");
}

export interface ClozeMatch {
  /** Cloze number 1–20. */
  number: number;
  /** Answer with optional ::hint. */
  body: string;
  /** UTF-16 start and end offsets in the source text. */
  index: number;
  end: number;
}

export function clozeMatches(text: string): ClozeMatch[] {
  const matches = Array.from(text.matchAll(clozePattern()), (match) => ({
    number: Number(match[1]),
    body: match[2]!,
    index: match.index,
    end: match.index + match[0].length,
  }));
  const remainder = text.replace(clozePattern(), "");
  if (!matches.length || remainder.includes("{{") || remainder.includes("}}")) {
    throw new WorkflowError(
      "Use flat clozes such as {{c1::answer}} or {{c2::answer::hint}}, numbered 1–20. Nested or incomplete clozes are not supported.",
    );
  }
  for (const match of matches) {
    const [answer, , hint] = partition(match.body, "::");
    if (!pyStrip(answer) || hint.includes("::")) {
      throw new WorkflowError("Each cloze needs a nonempty answer and at most one hint.");
    }
  }
  return matches;
}

export function clozeNumbers(text: string): number[] {
  return [...new Set(clozeMatches(text).map((match) => match.number))].sort((a, b) => a - b);
}

export function studyCardCount(front: string, noteType: string = "basic"): number {
  checkedChoice(noteType, NOTE_TYPES, "note format");
  if (noteType === "basic" || noteType === "occlusion" || noteType === "visual") return 1;
  if (noteType === "reversed") return 2;
  return new Set(clozeMatches(front).map((match) => match.number)).size;
}

export function plainFront(front: string, noteType: string = "basic"): string {
  if (noteType === "cloze") {
    return front.replace(clozePattern(), (_whole, _number, body: string) => body.split("::")[0]!);
  }
  return front;
}

export function plainQuestions(front: string, back: string, noteType: string = "basic"): string[] {
  if (noteType === "occlusion") return [];
  return noteType === "reversed" ? [front, back] : [plainFront(front, noteType)];
}

/** html.escape(text) with "\n" -> "<br>", as stored in Anki fields. */
export function textHtml(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#x27;")
    .replaceAll("\n", "<br>");
}

export interface StudyPreview {
  number: number;
  direction?: string;
  question: string;
  answer: string;
}

/** Escaped question/answer HTML for exactly the ordinals exported to Anki. */
export function studyPreviews(front: string, back: string, noteType: string = "basic"): StudyPreview[] {
  studyCardCount(front, noteType);
  if (noteType === "basic" || noteType === "occlusion" || noteType === "visual") {
    return [{ number: 1, question: textHtml(front), answer: textHtml(back) }];
  }
  if (noteType === "reversed") {
    return [
      { number: 1, direction: "Front → back", question: textHtml(front), answer: textHtml(back) },
      { number: 2, direction: "Back → front", question: textHtml(back), answer: textHtml(front) },
    ];
  }
  const matches = clozeMatches(front);
  return clozeNumbers(front).map((number) => {
    const render = (reveal: boolean) => {
      const chunks: string[] = [];
      let end = 0;
      for (const match of matches) {
        chunks.push(textHtml(front.slice(end, match.index)));
        const [answer, , hint] = partition(match.body, "::");
        if (match.number === number) {
          const value = reveal ? answer : `[${hint || "..."}]`;
          chunks.push(`<span class="cloze">${textHtml(value)}</span>`);
        } else {
          chunks.push(textHtml(answer));
        }
        end = match.end;
      }
      chunks.push(textHtml(front.slice(end)));
      return chunks.join("");
    };
    return {
      number,
      question: render(false),
      answer: render(true) + (back ? "<hr>" + textHtml(back) : ""),
    };
  });
}
