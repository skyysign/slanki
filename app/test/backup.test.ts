import { unzipSync } from "fflate";
import { describe, expect, it } from "vitest";
import { readBackup, writeBackup } from "../src/backup/backup.ts";
import { upgradeManifest } from "../src/backup/manifest.ts";
import { sha256Hex } from "../src/core/sha256.ts";
import { zipEntries } from "../src/core/zip.ts";
import { fixtureBytes, golden, goldenBytes } from "./golden.ts";

const byId = <T extends { id: string }>(items: T[]) => [...items].sort((a, b) => a.id.localeCompare(b.id));

function assets(): [string, Uint8Array][] {
  const files = unzipSync(goldenBytes("backup-v12.zip"));
  return Object.entries(files).filter(([name]) => name !== "manifest.json");
}

function zipWith(manifest: unknown, extra: [string, Uint8Array][] = assets()): Uint8Array {
  return zipEntries([["manifest.json", new TextEncoder().encode(JSON.stringify(manifest))], ...extra]);
}

describe("Recalloom backups", () => {
  for (let version = 1; version <= 12; version++) {
    it(`reads format ${version} like the Django restore`, () => {
      const restored = golden(`manifests/v${version}.restored.json`);
      const { manifest, pdf, pages } = readBackup(zipWith(golden(`manifests/v${version}.json`)));
      expect(manifest.lecture).toEqual(restored.lecture);
      expect(manifest.pages).toEqual(restored.pages);
      expect(byId(manifest.cards)).toEqual(byId(restored.cards));
      expect(byId(manifest.runs)).toEqual(byId(restored.runs));
      expect(sha256Hex(pdf)).toBe(restored.lecture.sha256);
      expect(pages.size).toBe(restored.pages.length);
    });
  }

  it("keeps the original PDF identical to the synthetic fixture", () => {
    expect(sha256Hex(readBackup(goldenBytes("backup-v12.zip")).pdf)).toBe(sha256Hex(fixtureBytes("lecture.pdf")));
  });

  it("round-trips through a Slanki backup without losing records", () => {
    const first = readBackup(goldenBytes("backup-v12.zip"));
    const written = writeBackup({ manifest: first.manifest, pdf: first.pdf, pages: first.pages });
    const second = readBackup(written);
    expect(second.manifest).toEqual({ ...first.manifest, assets: second.manifest.assets });
    const raw = JSON.parse(new TextDecoder().decode(unzipSync(written)["manifest.json"]));
    expect([raw.format, raw.version]).toEqual(["slanki", 1]);
    expect(second.manifest.runs.some((run) => run.purpose === "rundown" && Object.keys(run.rundown_data).length)).toBe(true);
    expect(second.manifest.runs.some((run) => run.suggestions.length > 0)).toBe(true);
  });

  it("marks interrupted runs as failed", () => {
    const manifest = golden("manifests/v12.json");
    manifest.runs[0].status = "running";
    const run = readBackup(zipWith(manifest)).manifest.runs.find((r) => r.id === manifest.runs[0].id)!;
    expect(run.status).toBe("failed");
    expect(run.error).toBe("Generation was interrupted by backup/restore. Saved drafts are intact.");
  });

  it.each([
    ["unknown format", (m: any) => (m.format = "other"), "not a supported"],
    ["future version", (m: any) => (m.version = 13), "not a supported"],
    ["extra key", (m: any) => (m.cards[0].extra = 1), "invalid record structure"],
    ["missing key", (m: any) => delete m.cards[0].fingerprint, "invalid record structure"],
    ["bad quote", (m: any) => (m.cards.find((c: any) => c.source_quote).source_quote = "Not on the page"), "not present on page"],
    ["crop outside", (m: any) => (m.cards.find((c: any) => c.source_crop.page).source_crop.right = 99999), "inside this note's source slide"],
    ["unknown run", (m: any) => (m.cards[0].run = "00000000-0000-4000-8000-000000000000"), "invalid generation reference"],
    ["duplicate fingerprint", (m: any) => (m.cards[1].fingerprint = m.cards[0].fingerprint), "invalid record structure"],
    ["naive timestamp", (m: any) => (m.cards[0].created_at = "2026-01-01T00:00:00"), "invalid timestamp"],
    ["page gap", (m: any) => (m.pages[1].number = 9), "page numbers are invalid"],
    ["bad card limit", (m: any) => (m.runs[0].card_limit = 0), "invalid card limit"],
  ])("rejects %s", (_name, change, message) => {
    const manifest = golden("manifests/v12.json");
    change(manifest);
    expect(() => readBackup(zipWith(manifest))).toThrow(message);
  });

  it("rejects tampered and unexpected files", () => {
    const manifest = golden("manifests/v12.json");
    const files = assets();
    const tampered = files.map(([name, bytes]): [string, Uint8Array] => [name, name === "pages/1.png" ? bytes.slice(0, -1) : bytes]);
    expect(() => readBackup(zipWith(manifest, tampered))).toThrow("integrity check");
    expect(() => readBackup(zipWith(manifest, [...files, ["extra.txt", new Uint8Array(1)]]))).toThrow("unexpected or missing");
    expect(() => readBackup(zipWith(manifest, files.slice(1)))).toThrow("unexpected or missing");
    expect(() => readBackup(new Uint8Array([1, 2, 3]))).toThrow("not a readable backup");
  });

  it("validates manifests without the ZIP", () => {
    expect(() => upgradeManifest({})).toThrow("invalid record structure");
  });
});
