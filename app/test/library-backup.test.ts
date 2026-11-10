import { unzipSync } from "fflate";
import { IDBFactory } from "fake-indexeddb";
import { beforeEach, describe, expect, it } from "vitest";
import { readBackup, writeBackup } from "../src/backup/backup.ts";
import { zipEntries } from "../src/core/zip.ts";
import { buildLibraryBackup, restoreBackupBytes } from "../src/services/lectures.ts";
import { resetDbConnection } from "../src/store/db.ts";
import { addBackup, addLecture, backupContents, deleteLecture, listLectures } from "../src/store/library.ts";
import { goldenBytes } from "./golden.ts";

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  resetDbConnection();
});

async function twoLectures(): Promise<string[]> {
  const golden = await addBackup(readBackup(goldenBytes("backup-v12.zip")));
  const pages = [1, 2].map((number) => ({
    number,
    text: `Slide ${number} explains spaced practice in enough words.`,
    width: 100,
    height: 60,
    warning: "",
    png: goldenBytes(`pages/${number}.png`),
  }));
  const { id } = await addLecture(new TextEncoder().encode("%PDF-second"), "second.pdf", "Second lecture", pages);
  return [golden, id];
}

const snapshot = async (id: string) => {
  const { manifest, pdf, pages } = await backupContents(id);
  return { manifest, pdf, pages: [...pages.entries()] };
};

describe("whole-library backups", () => {
  it("restores every lecture with all records", async () => {
    const ids = await twoLectures();
    const before = await Promise.all(ids.map(snapshot));
    const { bytes, count } = await buildLibraryBackup();
    expect(count).toBe(2);
    for (const id of ids) await deleteLecture(id);
    expect(await listLectures()).toHaveLength(0);

    expect(await restoreBackupBytes(bytes)).toEqual({ opened: null, restored: 2, skipped: 0 });
    expect(await Promise.all(ids.map(snapshot))).toEqual(before);

    // Restoring again leaves the existing lectures alone.
    expect(await restoreBackupBytes(bytes)).toEqual({ opened: null, restored: 0, skipped: 2 });
  });

  it("restores nothing from a damaged library backup", async () => {
    const ids = await twoLectures();
    const { bytes } = await buildLibraryBackup();
    for (const id of ids) await deleteLecture(id);
    const files = Object.entries(unzipSync(bytes));
    const damaged = files.map(([name, data]): [string, Uint8Array] =>
      name.endsWith(".zip") && name.includes("002-") ? [name, data.slice(0, data.length - 40)] : [name, data],
    );
    await expect(restoreBackupBytes(zipEntries(damaged))).rejects.toThrow();
    expect(await listLectures()).toHaveLength(0);
    await expect(restoreBackupBytes(zipEntries([...files, ["extra.txt", new Uint8Array(1)]]))).rejects.toThrow("unexpected files");
    expect(await listLectures()).toHaveLength(0);
  });

  it("still restores a single-lecture backup and opens it", async () => {
    const [id] = await twoLectures();
    const single = writeBackup(await backupContents(id!));
    await deleteLecture(id!);
    expect(await restoreBackupBytes(single)).toEqual({ opened: id, restored: 1, skipped: 0 });
  });
});
