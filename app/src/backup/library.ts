// Whole-library backups: one ZIP holding each lecture's ordinary Slanki
// backup plus a small index. Restoring checks every lecture like a single backup.
import { WorkflowError } from "../core/errors.ts";
import { isUuid } from "../core/ids.ts";
import { hasExactKeys, isPlainObject } from "../core/py.ts";
import { readZip, zipEntries } from "../core/zip.ts";
import { MAX_BACKUP_BYTES } from "./backup.ts";

export const LIBRARY_FORMAT = "slanki-library";
export const LIBRARY_VERSION = 1;
const INDEX = "library.json";
const MAX_LECTURES = 1000;
const MAX_LIBRARY_BYTES = 1024 * 1024 * 1024;

export interface LibraryEntry {
  id: string;
  title: string;
  file: string;
}

export function libraryFileName(index: number, id: string): string {
  return `lectures/${String(index + 1).padStart(3, "0")}-${id}.zip`;
}

export function writeLibraryBackup(lectures: readonly { id: string; title: string; backup: Uint8Array }[]): Uint8Array {
  const entries: LibraryEntry[] = lectures.map((lecture, i) => ({ id: lecture.id, title: lecture.title, file: libraryFileName(i, lecture.id) }));
  const index = { format: LIBRARY_FORMAT, version: LIBRARY_VERSION, created_at: new Date().toISOString(), lectures: entries };
  return zipEntries([
    [INDEX, new TextEncoder().encode(JSON.stringify(index, null, 1))],
    ...lectures.map((lecture, i): [string, Uint8Array] => [entries[i]!.file, lecture.backup]),
  ]);
}

/** True when the ZIP is a whole-library backup (rather than a single lecture). */
export function isLibraryBackup(files: ReadonlyMap<string, Uint8Array>): boolean {
  return files.has(INDEX) && !files.has("manifest.json");
}

export function readLibraryZip(data: Uint8Array): Map<string, Uint8Array> {
  return readZip(
    data,
    {
      maxBytes: MAX_LIBRARY_BYTES,
      maxEntries: MAX_LECTURES + 1,
      maxTotal: MAX_LIBRARY_BYTES,
      entryLimits: { [INDEX]: 1024 * 1024, "manifest.json": 5 * 1024 * 1024 },
    },
    "This backup is too large to restore in the browser.",
  );
}

/** Validate the index and return each lecture's backup bytes in order. */
export function readLibraryBackup(files: ReadonlyMap<string, Uint8Array>): { entry: LibraryEntry; backup: Uint8Array }[] {
  let index: unknown;
  try {
    index = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(files.get(INDEX)));
  } catch {
    throw new WorkflowError("This library backup is damaged.");
  }
  if (
    !hasExactKeys(index, ["format", "version", "created_at", "lectures"]) ||
    index.format !== LIBRARY_FORMAT ||
    index.version !== LIBRARY_VERSION ||
    !Array.isArray(index.lectures) ||
    index.lectures.length > MAX_LECTURES
  ) {
    throw new WorkflowError("This is not a supported Slanki library backup.");
  }
  const seen = new Set<string>();
  const result = (index.lectures as unknown[]).map((entry) => {
    if (
      !isPlainObject(entry) ||
      !hasExactKeys(entry, ["id", "title", "file"]) ||
      !isUuid(entry.id) ||
      typeof entry.title !== "string" ||
      typeof entry.file !== "string" ||
      !files.has(entry.file) ||
      seen.has(entry.file) ||
      files.get(entry.file)!.length > MAX_BACKUP_BYTES
    ) {
      throw new WorkflowError("This library backup is damaged.");
    }
    seen.add(entry.file);
    return { entry: entry as unknown as LibraryEntry, backup: files.get(entry.file)! };
  });
  if (files.size !== result.length + 1) throw new WorkflowError("This library backup contains unexpected files.");
  return result;
}
