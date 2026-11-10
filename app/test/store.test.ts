import { IDBFactory } from "fake-indexeddb";
import { beforeEach, describe, expect, it } from "vitest";
import { readBackup, writeBackup } from "../src/backup/backup.ts";
import { resetDbConnection, transaction } from "../src/store/db.ts";
import {
  addBackup,
  addDrafts,
  backupContents,
  deleteLecture,
  getLecture,
  getRevisions,
  keepDrafts,
  listLectures,
  undoNote,
  updateNote,
} from "../src/store/library.ts";
import { importChatDrafts } from "../src/services/lectures.ts";
import { goldenBytes } from "./golden.ts";

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  resetDbConnection();
});

async function restoreGolden() {
  const contents = readBackup(goldenBytes("backup-v12.zip"));
  const id = await addBackup(contents);
  return { id, contents };
}

describe("library store", () => {
  it("restores a backup losslessly and writes it back identically", async () => {
    const { id, contents } = await restoreGolden();
    const again = readBackup(writeBackup(await backupContents(id)));
    expect(again.manifest.lecture).toEqual(contents.manifest.lecture);
    expect(again.manifest.pages).toEqual(contents.manifest.pages);
    expect(again.manifest.cards).toEqual(contents.manifest.cards);
    expect(again.manifest.runs).toEqual(contents.manifest.runs);
    expect(again.pdf).toEqual(contents.pdf);
    expect([...again.pages.keys()]).toEqual([...contents.pages.keys()]);
    const [summary] = await listLectures();
    expect(summary!.ready).toBe(contents.manifest.cards.filter((card) => card.status === "accepted").length);
  });

  it("refuses to restore a lecture that is already present", async () => {
    await restoreGolden();
    await expect(addBackup(readBackup(goldenBytes("backup-v12.zip")))).rejects.toThrow("already in your library");
  });

  it("saves edits with revisions, stale-version protection and monotonic Anki times", async () => {
    const { id } = await restoreGolden();
    const note = (await getLecture(id))!.notes.find((n) => n.note_type === "basic" && n.status === "accepted")!;
    const edited = await updateNote(note.id, note.version, {
      front: "Edited question?",
      back: note.back,
      source_quote: note.source_quote,
      status: "accepted",
    });
    expect(edited.version).toBe(note.version + 1);
    expect(edited.anki_modified).toBeGreaterThan(note.anki_modified);
    expect(edited.id).toBe(note.id);
    expect(edited.fingerprint).toBe(note.fingerprint);
    await expect(
      updateNote(note.id, note.version, { front: "Stale", back: note.back, source_quote: "", status: "draft" }),
    ).rejects.toThrow("changed in another tab");
    const revisions = await getRevisions(note.id);
    expect(revisions.at(-1)!.front).toBe(note.front);

    const undone = await undoNote(note.id, edited.version);
    expect(undone.front).toBe(note.front);
    expect(undone.version).toBe(edited.version + 1);
    expect(undone.anki_modified).toBeGreaterThan(edited.anki_modified);
  });

  it("keeps cloze numbers fixed and validates evidence", async () => {
    const { id } = await restoreGolden();
    const cloze = (await getLecture(id))!.notes.find((n) => n.note_type === "cloze")!;
    await expect(
      updateNote(cloze.id, cloze.version, { front: "Only {{c9::new}} number", back: "", source_quote: "", status: "draft" }),
    ).rejects.toThrow("existing cloze numbers");
    await expect(
      updateNote(cloze.id, cloze.version, { front: cloze.front, back: "", source_quote: "Invented evidence", status: "draft" }),
    ).rejects.toThrow("not present on page");
  });

  it("keeps all displayed drafts atomically", async () => {
    const { id } = await restoreGolden();
    const drafts = (await getLecture(id))!.notes.filter((n) => n.status === "draft");
    expect(drafts.length).toBeGreaterThan(1);
    const versions = Object.fromEntries(drafts.map((n) => [n.id, n.version]));
    const stale = { ...versions, [drafts[0]!.id]: drafts[0]!.version + 5 };
    await expect(keepDrafts(id, stale)).rejects.toThrow("Nothing was kept");
    expect((await getLecture(id))!.notes.filter((n) => n.status === "draft").length).toBe(drafts.length);
    expect(await keepDrafts(id, versions)).toBe(drafts.length);
    expect((await getLecture(id))!.notes.filter((n) => n.status === "draft").length).toBe(0);
  });

  it("does not duplicate an existing question", async () => {
    const { id } = await restoreGolden();
    const note = (await getLecture(id))!.notes.find((n) => n.note_type === "basic")!;
    const added = await addDrafts(id, [
      { page: note.page, front: note.front, back: "Other", sourceQuote: "", noteType: "basic" },
      { page: note.page, front: "A completely new question?", back: "Yes.", sourceQuote: "", noteType: "basic" },
    ]);
    expect(added).toBe(1);
  });

  it("imports chat output atomically with logistics and duplicate filtering", async () => {
    const { id, contents } = await restoreGolden();
    const page = contents.manifest.pages[0]!;
    const quote = page.text.split("\n")[2]!;
    const payload = {
      cards: [
        { front: "New chat question?", back: "Answer.", page: 1, source_quote: quote },
        { front: "When is the exam?", back: "Friday.", page: 1, source_quote: quote },
        { front: contents.manifest.cards[0]!.front, back: "Dup.", page: contents.manifest.cards[0]!.page, source_quote: "" },
      ],
    };
    // The third item lacks a quote: file imports are all-or-nothing.
    await expect(importChatDrafts(id, payload)).rejects.toThrow("exact supporting source excerpt");
    payload.cards.pop();
    const result = await importChatDrafts(id, payload);
    expect(result).toEqual({ added: 1, filtered: 1, duplicates: 0 });
    const bundle = (await getLecture(id))!;
    const run = bundle.runs.find((r) => r.provider === "json-import")!;
    expect(run.cards_added).toBe(1);
    expect(bundle.notes.find((n) => n.front === "New chat question?")!.run).toBe(run.id);
    // The new run and note survive a backup round trip.
    expect(() => readBackup(writeBackup(contents.manifest.cards.length ? { ...contents } : contents))).not.toThrow();
    const round = readBackup(writeBackup(await backupContents(id)));
    expect(round.manifest.runs.some((r) => r.id === run.id)).toBe(true);
  });

  it("deletes every record of a lecture", async () => {
    const { id } = await restoreGolden();
    await deleteLecture(id);
    const counts = await transaction(
      ["lectures", "pages", "images", "files", "notes", "revisions", "runs"],
      "readonly",
      async (tx) => {
        const result: Record<string, number> = {};
        for (const name of tx.objectStoreNames) {
          result[name] = await new Promise((resolve) => {
            const request = tx.objectStore(name).count();
            request.onsuccess = () => resolve(request.result);
          });
        }
        return result;
      },
    );
    expect(Object.values(counts).every((count) => count === 0)).toBe(true);
  });
});
