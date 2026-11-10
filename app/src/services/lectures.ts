// Lecture-level actions used by the interface: import, export, backup, chat import.
import { readBackup, writeBackup } from "../backup/backup.ts";
import { validatePayload } from "../core/cards.ts";
import { WorkflowError } from "../core/errors.ts";
import { formatTypes, type CardFormat } from "../core/noteTypes.ts";
import { contextDownload } from "../core/overview.ts";
import { promptFor } from "../core/prompts.ts";
import { pyStrip } from "../core/py.ts";
import { recentQuestions, selectDrafts } from "../core/selection.ts";
import { compareNewest } from "../core/time.ts";
import { buildApkg } from "../export/anki.ts";
import { exportInput } from "../export/fromRecords.ts";
import { extractPdf, type ExtractProgress } from "../pdf/extract.ts";
import { transaction } from "../store/db.ts";
import {
  addBackup,
  addLecture,
  backupContents,
  getImage,
  getLecture,
  insertDrafts,
  markBackedUp,
  notifyChanged,
  nowIso,
  requestPersistentStorage,
  type LectureBundle,
  type StoredNote,
  type StoredPage,
} from "../store/library.ts";
import { download, safeFileName } from "./files.ts";
import { newRun } from "./runs.ts";

export async function importPdfFile(
  file: File,
  onProgress: (progress: ExtractProgress) => void,
): Promise<{ id: string; created: boolean }> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const pages = await extractPdf(bytes, onProgress);
  const result = await addLecture(bytes, file.name, file.name.replace(/\.pdf$/i, ""), pages);
  void requestPersistentStorage();
  return result;
}

export async function restoreBackupFile(file: File): Promise<string> {
  const contents = readBackup(new Uint8Array(await file.arrayBuffer()));
  const id = await addBackup(contents);
  void requestPersistentStorage();
  return id;
}

export async function saveBackup(lectureId: string): Promise<void> {
  const contents = await backupContents(lectureId);
  const bytes = writeBackup(contents);
  download(bytes, `${safeFileName(contents.manifest.lecture.title)} - Slanki backup.zip`, "application/zip");
  await markBackedUp(lectureId);
}

type SqlJs = Awaited<ReturnType<typeof import("sql.js")["default"]>>;
let sqlLoading: Promise<SqlJs> | null = null;

function loadSql(): Promise<SqlJs> {
  sqlLoading ??= (async () => {
    const [{ default: initSqlJs }, { default: wasmUrl }] = await Promise.all([
      import("sql.js"),
      import("sql.js/dist/sql-wasm.wasm?url"),
    ]);
    return initSqlJs({ locateFile: () => wasmUrl });
  })();
  return sqlLoading;
}

/** Build and download the .apkg of accepted notes. */
export async function exportDeck(lectureId: string): Promise<void> {
  const bundle = await getLecture(lectureId);
  if (!bundle) throw new WorkflowError("This lecture is no longer in your library.");
  const accepted = bundle.notes.filter((note) => note.status === "accepted");
  if (!accepted.length) throw new WorkflowError("Keep at least one card before exporting.");
  const images = new Map<number, Uint8Array>();
  for (const page of bundle.pages) {
    if (!accepted.some((note) => note.page === page.number)) continue;
    const bytes = await getImage(page.image_sha);
    if (bytes) images.set(page.number, bytes);
  }
  const SQL = await loadSql();
  const apkg = buildApkg(SQL, exportInput(bundle.lecture, accepted.map((note) => ({ ...note, revisions: [] })), images));
  download(apkg, `${safeFileName(bundle.lecture.title)}.apkg`, "application/octet-stream");
}

export function readablePages(pages: readonly StoredPage[]): StoredPage[] {
  return pages.filter((page) => !page.warning && pyStrip(page.text));
}

export function newestFirst(notes: readonly StoredNote[]): StoredNote[] {
  return [...notes].sort(compareNewest);
}

const asQuestion = (note: StoredNote) => ({ front: note.front, back: note.back, noteType: note.note_type });

/** Prompt for an external chat: selected pages plus the rest of the lecture as context. */
export function externalChatPrompt(
  bundle: LectureBundle,
  selected: readonly number[],
  cardLimit: number | string | null,
  cardFormat: CardFormat,
): string {
  const chosen = readablePages(bundle.pages).filter((page) => selected.includes(page.number));
  if (!chosen.length) throw new WorkflowError("Select at least one slide with readable text.");
  const questions = recentQuestions(newestFirst(bundle.notes).map(asQuestion));
  const prompt = promptFor(chosen, cardLimit, questions, { cardFormat });
  return contextDownload(bundle.pages, new Set(chosen.map((page) => page.number)), prompt);
}

/** Parse pasted chat output; tolerates a surrounding ```json fence. */
export function parseChatJson(text: string): unknown {
  const trimmed = text.trim().replace(/^﻿/, "");
  const fenced = /^```(?:json)?\s*([\s\S]*?)\s*```$/i.exec(trimmed);
  try {
    return JSON.parse(fenced ? fenced[1]! : trimmed);
  } catch {
    throw new WorkflowError('Paste the JSON from the chat. It should start with {"cards": [');
  }
}

/** Import drafts from an external chat atomically (like Recalloom's JSON import). */
export async function importChatDrafts(
  lectureId: string,
  payload: unknown,
): Promise<{ added: number; filtered: number; duplicates: number }> {
  const bundle = await getLecture(lectureId);
  if (!bundle) throw new WorkflowError("This lecture is no longer in your library.");
  const validated = validatePayload(payload, new Map(bundle.pages.map((page) => [page.number, page])));
  const existing = bundle.notes.map((note) => ({
    fingerprint: note.fingerprint,
    front: note.front,
    back: note.back,
    noteType: note.note_type,
  }));
  const { selected, filtered } = selectDrafts(existing, validated);
  const run = newRun(lectureId, {
    status: "completed",
    provider: "json-import",
    page_numbers: [...new Set(selected.map((draft) => draft.page))].sort((a, b) => a - b),
    filtered_count: filtered,
  });
  // Notes and their run record commit together, so a note never references a missing run.
  const added = await transaction(["lectures", "pages", "notes", "runs"], "readwrite", async (tx) => {
    const count = await insertDrafts(tx, lectureId, selected, run.id);
    tx.objectStore("runs").put({ ...run, cards_added: count, study_cards_added: 0, updated_at: nowIso() });
    return count;
  });
  notifyChanged(lectureId);
  return { added, filtered, duplicates: validated.length - filtered - added };
}

export { formatTypes };
