// Python text semantics used by the original implementation. Lengths, slices,
// whitespace, casefolding and \w/\b follow Python 3.12 so validation, excerpt
// boundaries and fingerprints stay identical for existing lectures.
import { CASEFOLD_CODES, SPACE_CODES, WORD_RANGES } from "./pyunicode.ts";

const SPACE = new Set(SPACE_CODES);
const FOLD = new Map(CASEFOLD_CODES.map(([cp, folded]) => [cp, String.fromCodePoint(...folded)]));

function charClass(codes: Iterable<number> | readonly number[], ranges = false): string {
  const parts: string[] = [];
  const list = Array.from(codes);
  const escape = (cp: number) => `\\u{${cp.toString(16)}}`;
  if (ranges) {
    for (let i = 0; i < list.length; i += 2) {
      const start = list[i]!;
      const end = list[i + 1]!;
      parts.push(start === end ? escape(start) : `${escape(start)}-${escape(end)}`);
    }
  } else {
    for (const cp of list) parts.push(escape(cp));
  }
  return parts.join("");
}

/** Python's Unicode \w for str patterns, as a JavaScript (u-flag) character class body. */
export const PY_WORD_CLASS = charClass(WORD_RANGES, true);
/** Python's Unicode whitespace (str.isspace / \s), as a character class body. */
export const PY_SPACE_CLASS = charClass(SPACE_CODES);

/**
 * Translate a Python regular expression that uses \w, \W, \s, \S and \b into an
 * equivalent JavaScript RegExp (u flag). Other syntax must already be compatible.
 */
export function pyRegex(pattern: string, flags = ""): RegExp {
  const word = `[${PY_WORD_CLASS}]`;
  const boundary = `(?:(?<=${word})(?!${word})|(?<!${word})(?=${word}))`;
  let out = "";
  for (let i = 0; i < pattern.length; i++) {
    const ch = pattern[i];
    if (ch !== "\\") {
      out += ch;
      continue;
    }
    const next = pattern[++i];
    if (next === "w") out += word;
    else if (next === "W") out += `[^${PY_WORD_CLASS}]`;
    else if (next === "s") out += `[${PY_SPACE_CLASS}]`;
    else if (next === "S") out += `[^${PY_SPACE_CLASS}]`;
    else if (next === "b") out += boundary;
    else out += `\\${next ?? ""}`;
  }
  return new RegExp(out, flags.includes("u") ? flags : flags + "u");
}

export function isSpace(ch: string): boolean {
  return SPACE.has(ch.codePointAt(0)!);
}

/** Number of code points, like Python len(str). */
export function cpLength(text: string): number {
  let count = 0;
  for (const _ of text) count++;
  return count;
}

/** Python str[start:end] on code points (non-negative indices). */
export function cpSlice(text: string, start: number, end?: number): string {
  return Array.from(text).slice(start, end).join("");
}

/** Python str.split() with no arguments. */
export function pySplit(text: string): string[] {
  const parts: string[] = [];
  let current = "";
  for (const ch of text) {
    if (SPACE.has(ch.codePointAt(0)!)) {
      if (current) {
        parts.push(current);
        current = "";
      }
    } else {
      current += ch;
    }
  }
  if (current) parts.push(current);
  return parts;
}

/** Python str.strip() with no arguments. */
export function pyStrip(text: string): string {
  const chars = Array.from(text);
  let start = 0;
  let end = chars.length;
  while (start < end && isSpace(chars[start]!)) start++;
  while (end > start && isSpace(chars[end - 1]!)) end--;
  return start === 0 && end === chars.length ? text : chars.slice(start, end).join("");
}

/** Python str.casefold(). */
export function casefold(text: string): string {
  let out = "";
  for (const ch of text) out += FOLD.get(ch.codePointAt(0)!) ?? ch;
  return out;
}

/** Python str.partition(separator). */
export function partition(text: string, separator: string): [string, string, string] {
  const index = text.indexOf(separator);
  if (index < 0) return [text, "", ""];
  return [text.slice(0, index), separator, text.slice(index + separator.length)];
}

/** " ".join(unicodedata.normalize("NFKC", text).split()) */
export function normalized(text: string): string {
  return pySplit(text.normalize("NFKC")).join(" ");
}

export function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Python set(mapping) == set(names): exactly these keys, no more, no fewer. */
export function hasExactKeys(value: unknown, names: readonly string[]): value is Record<string, unknown> {
  if (!isPlainObject(value)) return false;
  const keys = Object.keys(value);
  return keys.length === names.length && names.every((name) => Object.hasOwn(value, name));
}

/** Python `type(value) is int` for values decoded from JSON. */
export function isInt(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}
