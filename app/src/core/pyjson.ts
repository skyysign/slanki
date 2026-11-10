// Python json.dumps() output with default separators (", " and ": ").
// Prompts and Anki collection JSON embed this exact text.

export interface DumpOptions {
  /** Python's ensure_ascii (default true). */
  ensureAscii?: boolean;
}

const SHORT_ESCAPES: Record<string, string> = {
  '"': '\\"',
  "\\": "\\\\",
  "\n": "\\n",
  "\r": "\\r",
  "\t": "\\t",
  "\b": "\\b",
  "\f": "\\f",
};

function unicodeEscape(unit: number): string {
  return "\\u" + unit.toString(16).padStart(4, "0");
}

export function dumpString(text: string, ensureAscii = true): string {
  let out = '"';
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]!;
    const unit = text.charCodeAt(i);
    const short = SHORT_ESCAPES[ch];
    if (short) out += short;
    else if (unit < 0x20) out += unicodeEscape(unit);
    else if (ensureAscii && unit > 0x7e) out += unicodeEscape(unit);
    else out += ch;
  }
  return out + '"';
}

function dumpNumber(value: number): string {
  if (!Number.isFinite(value)) throw new TypeError("Non-finite numbers are not JSON");
  if (Number.isInteger(value)) return String(value);
  // Python repr() and JavaScript share shortest round-trip formatting for
  // ordinary fractional values; exponent formatting differs but is unused.
  return String(value);
}

export function dumps(value: unknown, options: DumpOptions = {}): string {
  const ensureAscii = options.ensureAscii ?? true;
  const encode = (item: unknown): string => {
    if (item === null || item === undefined) return "null";
    if (item === true) return "true";
    if (item === false) return "false";
    if (typeof item === "number") return dumpNumber(item);
    if (typeof item === "string") return dumpString(item, ensureAscii);
    if (Array.isArray(item)) return "[" + item.map(encode).join(", ") + "]";
    // Maps keep insertion order even for integer-like keys, unlike plain objects.
    if (item instanceof Map) {
      return (
        "{" +
        [...item].map(([key, val]) => dumpString(String(key), ensureAscii) + ": " + encode(val)).join(", ") +
        "}"
      );
    }
    if (typeof item === "object") {
      const entries = Object.entries(item as Record<string, unknown>);
      return (
        "{" + entries.map(([key, val]) => dumpString(key, ensureAscii) + ": " + encode(val)).join(", ") + "}"
      );
    }
    throw new TypeError(`Cannot serialize ${typeof item}`);
  };
  return encode(value);
}
