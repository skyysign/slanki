// Read Recalloom/Slanki backup ZIPs and write Slanki backups.
// Layout: manifest.json, original.pdf, pages/{n}.png (unpadded numbers).
import { WorkflowError } from "../core/errors.ts";
import { dumps } from "../core/pyjson.ts";
import { sha256Hex } from "../core/sha256.ts";
import { readZip, zipEntries } from "../core/zip.ts";
import { MAX_PAGES, SLANKI_FORMAT, SLANKI_VERSION, upgradeManifest, type Manifest } from "./manifest.ts";

export const MAX_BACKUP_BYTES = 200 * 1024 * 1024;
const MAX_MANIFEST_BYTES = 5 * 1024 * 1024;

export interface BackupContents {
  manifest: Manifest;
  pdf: Uint8Array;
  pages: Map<number, Uint8Array>;
}

/** Validate a backup completely before anything is stored. */
export function readBackup(data: Uint8Array): BackupContents {
  const files = readZip(
    data,
    {
      maxBytes: MAX_BACKUP_BYTES,
      maxEntries: MAX_PAGES + 2,
      maxTotal: MAX_BACKUP_BYTES,
      entryLimits: { "manifest.json": MAX_MANIFEST_BYTES },
    },
    "Backup exceeds the supported size or page limit.",
  );
  const manifestBytes = files.get("manifest.json");
  if (!manifestBytes) throw new WorkflowError("This is not a supported Slanki or Recalloom backup.");
  let raw: unknown;
  try {
    raw = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(manifestBytes));
  } catch {
    throw new WorkflowError("This backup is invalid or incomplete. Nothing was changed.");
  }
  const manifest = upgradeManifest(raw);
  const expected = new Set(["original.pdf", ...manifest.pages.map((page) => `pages/${page.number}.png`)]);
  const assetNames = Object.keys(manifest.assets);
  const zipNames = [...files.keys()].filter((name) => name !== "manifest.json");
  if (
    assetNames.length !== expected.size ||
    assetNames.some((name) => !expected.has(name)) ||
    zipNames.length !== expected.size ||
    zipNames.some((name) => !expected.has(name))
  ) {
    throw new WorkflowError("Backup contains unexpected or missing files.");
  }
  for (const name of expected) {
    if (sha256Hex(files.get(name)!) !== manifest.assets[name]) {
      throw new WorkflowError("Backup failed its integrity check.");
    }
  }
  const pdf = files.get("original.pdf")!;
  if (sha256Hex(pdf) !== manifest.lecture.sha256) {
    throw new WorkflowError("The original PDF does not match the backup's document identity.");
  }
  const pages = new Map(manifest.pages.map((page) => [page.number, files.get(`pages/${page.number}.png`)!]));
  return { manifest, pdf, pages };
}

/** Write a Slanki backup; the manifest records are already validated. */
export function writeBackup(contents: Omit<BackupContents, "manifest"> & { manifest: Omit<Manifest, "assets" | "format" | "version"> }): Uint8Array {
  const assets: [string, Uint8Array][] = [
    ["original.pdf", contents.pdf],
    ...contents.manifest.pages.map((page): [string, Uint8Array] => {
      const image = contents.pages.get(page.number);
      if (!image) throw new WorkflowError("Some source files are missing. Restore them before making a new backup.");
      return [`pages/${page.number}.png`, image];
    }),
  ];
  const manifest = {
    format: SLANKI_FORMAT,
    version: SLANKI_VERSION,
    lecture: contents.manifest.lecture,
    pages: contents.manifest.pages,
    cards: contents.manifest.cards,
    runs: contents.manifest.runs,
    assets: Object.fromEntries(assets.map(([name, bytes]) => [name, sha256Hex(bytes)])),
  };
  const encoded = new TextEncoder().encode(dumps(manifest, { ensureAscii: false }));
  if (
    encoded.length > MAX_MANIFEST_BYTES ||
    assets.reduce((sum, [, bytes]) => sum + bytes.length, 0) + encoded.length > MAX_BACKUP_BYTES
  ) {
    throw new WorkflowError("This lecture exceeds the current backup limits.");
  }
  return zipEntries([["manifest.json", encoded], ...assets]);
}
