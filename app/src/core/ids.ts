// Stable Anki identities. These must match genanki and the Recalloom exporter
// exactly so re-exports update existing notes and keep review history.
import { sha256 } from "./sha256.ts";

const BASE91 =
  "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!#$%&()*+,-./:;<=>?@[]^_`{|}~";

/** genanki.guid_for(value) for a single value. */
export function guidFor(value: string): string {
  const digest = sha256(value);
  let number = 0n;
  for (let i = 0; i < 8; i++) number = (number << 8n) + BigInt(digest[i]!);
  let result = "";
  while (number > 0n) {
    result = BASE91[Number(number % 91n)] + result;
    number /= 91n;
  }
  return result;
}

/** int.from_bytes(sha256(str(lecture_id)).digest()[:6], "big") */
export function deckId(lectureId: string): number {
  const digest = sha256(lectureId);
  let number = 0;
  for (let i = 0; i < 6; i++) number = number * 256 + digest[i]!;
  return number;
}

/** uuid.UUID(value).hex */
export function uuidHex(value: string): string {
  return value.replaceAll("-", "").toLowerCase();
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export function isUuid(value: unknown): value is string {
  return typeof value === "string" && UUID.test(value);
}

export function newUuid(): string {
  return crypto.randomUUID();
}
