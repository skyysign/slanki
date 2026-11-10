// Ordered ZIP writing and bounded ZIP reading for decks and backups.
import { Zip, ZipDeflate, unzipSync } from "fflate";
import { WorkflowError } from "./errors.ts";

/** A ZIP with DEFLATE entries in the given order (like Python's zipfile). */
export function zipEntries(entries: readonly [string, Uint8Array][]): Uint8Array {
  const chunks: Uint8Array[] = [];
  let failure: Error | null = null;
  const zip = new Zip((error, data) => {
    if (error) failure = error;
    else chunks.push(data);
  });
  for (const [name, data] of entries) {
    const file = new ZipDeflate(name, { level: 6 });
    zip.add(file);
    file.push(data, true);
  }
  zip.end();
  if (failure) throw failure;
  const out = new Uint8Array(chunks.reduce((sum, chunk) => sum + chunk.length, 0));
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

export interface ZipLimits {
  maxBytes: number;
  maxEntries: number;
  maxTotal: number;
  /** Per-entry uncompressed limits by exact name. */
  entryLimits?: Record<string, number>;
}

/**
 * Read a ZIP without trusting its directory: entry count, declared and actual
 * uncompressed sizes are bounded, and duplicate names are rejected.
 */
export function readZip(data: Uint8Array, limits: ZipLimits, tooLarge: string): Map<string, Uint8Array> {
  if (data.length > limits.maxBytes) throw new WorkflowError(tooLarge);
  const names = new Set<string>();
  const declared = new Map<string, number>();
  let count = 0;
  let total = 0;
  let duplicate = false;
  let oversized = false;
  let files: Record<string, Uint8Array>;
  try {
    files = unzipSync(data, {
      filter(file) {
        count += 1;
        total += file.originalSize;
        if (names.has(file.name)) duplicate = true;
        names.add(file.name);
        declared.set(file.name, file.originalSize);
        const entryLimit = limits.entryLimits?.[file.name];
        if (entryLimit !== undefined && file.originalSize > entryLimit) oversized = true;
        return count <= limits.maxEntries && total <= limits.maxTotal && !oversized && !duplicate;
      },
    });
  } catch {
    throw new WorkflowError("This file is not a readable backup.");
  }
  if (count > limits.maxEntries || total > limits.maxTotal || oversized) throw new WorkflowError(tooLarge);
  if (duplicate) throw new WorkflowError("Backup contains duplicate entries.");
  const result = new Map<string, Uint8Array>();
  for (const [name, content] of Object.entries(files)) {
    if (content.length !== declared.get(name)) throw new WorkflowError("Backup failed its integrity check.");
    result.set(name, content);
  }
  return result;
}
