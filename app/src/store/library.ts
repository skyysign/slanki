// The on-device library. Operations mirror the Django services (cards.py,
// documents.py, backups.py, deletion.py) on IndexedDB records that keep the
// backup manifest's field names.
import type { BackupContents } from "../backup/backup.ts";
import type { CardRecord, LectureRecord, PageRecord, RevisionRecord, RunRecord } from "../backup/manifest.ts";
import { fingerprint, validateContent, type Draft } from "../core/cards.ts";
import { WorkflowError } from "../core/errors.ts";
import { checkedCrop, checkedOcclusion, checkedVisualMasks } from "../core/geometry.ts";
import { isUuid, newUuid } from "../core/ids.ts";
import { clozeMatches, studyCardCount, type NoteType } from "../core/noteTypes.ts";
import { sha256Hex } from "../core/sha256.ts";
import { compareNewest, compareNotes } from "../core/time.ts";
import { request, store, transaction } from "./db.ts";

export interface StoredLecture extends LectureRecord {
  page_count: number;
  updated_at: string;
  backed_up_at: string | null;
}
export interface StoredPage extends PageRecord {
  lecture_id: string;
  image_sha: string;
}
export type StoredNote = Omit<CardRecord, "revisions"> & { lecture_id: string };
export type StoredRevision = RevisionRecord & { card_id: string };
export type StoredRun = RunRecord & { lecture_id: string };
export type NoteStatus = CardRecord["status"];

const channel = typeof BroadcastChannel === "function" ? new BroadcastChannel("slanki") : null;
const local = new EventTarget();

/** Notify this and other tabs that a lecture (or the library) changed. */
export function notifyChanged(lectureId: string | null): void {
  changed(lectureId);
}

function changed(lectureId: string | null): void {
  const detail = { lectureId };
  local.dispatchEvent(new CustomEvent("change", { detail }));
  channel?.postMessage(detail);
}

export function onLibraryChange(listener: (lectureId: string | null) => void): () => void {
  const handle = (event: Event) => listener((event as CustomEvent).detail.lectureId);
  const remote = (event: MessageEvent) => listener(event.data?.lectureId ?? null);
  local.addEventListener("change", handle);
  channel?.addEventListener("message", remote);
  return () => {
    local.removeEventListener("change", handle);
    channel?.removeEventListener("message", remote);
  };
}

let lastStamp = 0;
/** Strictly increasing ISO timestamps keep creation order stable within a batch. */
export function nowIso(): string {
  lastStamp = Math.max(Date.now(), lastStamp + 1);
  return new Date(lastStamp).toISOString();
}

export function unixSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

const byPageThenCreated = compareNotes;

// ---------------------------------------------------------------------------
// Reading

export interface LectureSummary {
  lecture: StoredLecture;
  toReview: number;
  ready: number;
  setAside: number;
  readyCards: number;
  running: boolean;
}

export async function listLectures(): Promise<LectureSummary[]> {
  return transaction(["lectures", "notes", "runs"], "readonly", async (tx) => {
    const lectures = (await request(store(tx, "lectures").getAll())) as StoredLecture[];
    const notes = (await request(store(tx, "notes").getAll())) as StoredNote[];
    const runs = (await request(store(tx, "runs").getAll())) as StoredRun[];
    return lectures
      .map((lecture) => {
        const own = notes.filter((note) => note.lecture_id === lecture.id);
        const ready = own.filter((note) => note.status === "accepted");
        return {
          lecture,
          toReview: own.filter((note) => note.status === "draft").length,
          ready: ready.length,
          setAside: own.filter((note) => note.status === "rejected").length,
          readyCards: ready.reduce((sum, note) => sum + studyCardCount(note.front, note.note_type), 0),
          running: runs.some((run) => run.lecture_id === lecture.id && (run.status === "queued" || run.status === "running")),
        };
      })
      .sort((a, b) => Date.parse(b.lecture.updated_at) - Date.parse(a.lecture.updated_at));
  });
}

export interface LectureBundle {
  lecture: StoredLecture;
  pages: StoredPage[];
  notes: StoredNote[];
  runs: StoredRun[];
}

export async function getLecture(id: string): Promise<LectureBundle | null> {
  return transaction(["lectures", "pages", "notes", "runs"], "readonly", async (tx) => {
    const lecture = (await request(store(tx, "lectures").get(id))) as StoredLecture | undefined;
    if (!lecture) return null;
    const pages = (await request(store(tx, "pages").index("lecture_id").getAll(id))) as StoredPage[];
    const notes = (await request(store(tx, "notes").index("lecture_id").getAll(id))) as StoredNote[];
    const runs = (await request(store(tx, "runs").index("lecture_id").getAll(id))) as StoredRun[];
    pages.sort((a, b) => a.number - b.number);
    notes.sort(byPageThenCreated);
    runs.sort(compareNewest);
    return { lecture, pages, notes, runs };
  });
}

export async function getImage(sha: string): Promise<Uint8Array | null> {
  return transaction(["images"], "readonly", async (tx) => {
    const record = (await request(store(tx, "images").get(sha))) as { bytes: Uint8Array } | undefined;
    return record?.bytes ?? null;
  });
}

export async function getRevisions(cardId: string): Promise<StoredRevision[]> {
  return transaction(["revisions"], "readonly", async (tx) => {
    const revisions = (await request(store(tx, "revisions").index("card_id").getAll(cardId))) as StoredRevision[];
    return revisions.sort((a, b) => a.version - b.version);
  });
}

// ---------------------------------------------------------------------------
// Adding lectures

export interface ExtractedPage {
  number: number;
  text: string;
  width: number;
  height: number;
  warning: string;
  png: Uint8Array;
}

/** Store an extracted PDF; an identical PDF reopens the existing lecture. */
export async function addLecture(
  pdf: Uint8Array,
  originalName: string,
  title: string,
  pages: readonly ExtractedPage[],
): Promise<{ id: string; created: boolean }> {
  const sha256 = sha256Hex(pdf);
  const id = newUuid();
  const now = nowIso();
  const result = await transaction(["lectures", "pages", "images", "files"], "readwrite", async (tx) => {
    const existing = (await request(store(tx, "lectures").index("sha256").get(sha256))) as StoredLecture | undefined;
    if (existing) return { id: existing.id, created: false };
    const lecture: StoredLecture = {
      id,
      title: (title.trim() || originalName.replace(/\.pdf$/i, "")).slice(0, 180) || "Lecture",
      sha256,
      original_name: originalName.slice(0, 255) || "lecture.pdf",
      created_at: now,
      page_count: pages.length,
      updated_at: now,
      backed_up_at: null,
    };
    store(tx, "lectures").add(lecture);
    store(tx, "files").put({ sha: sha256, bytes: pdf });
    for (const page of pages) {
      const imageSha = sha256Hex(page.png);
      store(tx, "images").put({ sha: imageSha, bytes: page.png });
      const record: StoredPage = {
        lecture_id: id,
        number: page.number,
        text: page.text,
        width: page.width,
        height: page.height,
        warning: page.warning,
        image_sha: imageSha,
      };
      store(tx, "pages").add(record);
    }
    return { id, created: true };
  });
  changed(result.id);
  return result;
}

/** Whether a lecture with this identity or the same PDF is already in the library. */
export async function hasLecture(id: string, sha256: string): Promise<boolean> {
  return transaction(["lectures"], "readonly", async (tx) => {
    const lectures = store(tx, "lectures");
    return !!(await request(lectures.get(id))) || !!(await request(lectures.index("sha256").get(sha256)));
  });
}

/** Restore a validated backup as a new lecture; never replaces existing work. */
export async function addBackup(contents: BackupContents): Promise<string> {
  const { manifest, pdf, pages } = contents;
  const lectureId = manifest.lecture.id;
  await transaction(["lectures", "pages", "images", "files", "notes", "revisions", "runs"], "readwrite", async (tx) => {
    const lectures = store(tx, "lectures");
    if (
      (await request(lectures.get(lectureId))) ||
      (await request(lectures.index("sha256").get(manifest.lecture.sha256)))
    ) {
      throw new WorkflowError(
        "This lecture is already in your library. Delete it first if you want to restore this backup instead.",
      );
    }
    const now = nowIso();
    lectures.add({ ...manifest.lecture, page_count: manifest.pages.length, updated_at: now, backed_up_at: now } satisfies StoredLecture);
    store(tx, "files").put({ sha: manifest.lecture.sha256, bytes: pdf });
    for (const page of manifest.pages) {
      const png = pages.get(page.number)!;
      const imageSha = sha256Hex(png);
      store(tx, "images").put({ sha: imageSha, bytes: png });
      store(tx, "pages").add({ ...page, lecture_id: lectureId, image_sha: imageSha } satisfies StoredPage);
    }
    for (const run of manifest.runs) store(tx, "runs").add({ ...run, lecture_id: lectureId } satisfies StoredRun);
    for (const { revisions, ...card } of manifest.cards) {
      store(tx, "notes").add({ ...card, lecture_id: lectureId } satisfies StoredNote);
      for (const revision of revisions) store(tx, "revisions").add({ ...revision, card_id: card.id } satisfies StoredRevision);
    }
  });
  changed(lectureId);
  return lectureId;
}

/** Everything a Slanki backup needs, in manifest order. */
export async function backupContents(lectureId: string): Promise<Omit<BackupContents, "manifest"> & { manifest: Omit<BackupContents["manifest"], "assets" | "format" | "version"> }> {
  return transaction(["lectures", "pages", "images", "files", "notes", "revisions", "runs"], "readonly", async (tx) => {
    const lecture = (await request(store(tx, "lectures").get(lectureId))) as StoredLecture | undefined;
    if (!lecture) throw new WorkflowError("This lecture is no longer in your library.");
    const pages = ((await request(store(tx, "pages").index("lecture_id").getAll(lectureId))) as StoredPage[]).sort(
      (a, b) => a.number - b.number,
    );
    const images = new Map<number, Uint8Array>();
    for (const page of pages) {
      const image = (await request(store(tx, "images").get(page.image_sha))) as { bytes: Uint8Array } | undefined;
      if (!image) throw new WorkflowError("Some source files are missing. Restore them before making a new backup.");
      images.set(page.number, image.bytes);
    }
    const file = (await request(store(tx, "files").get(lecture.sha256))) as { bytes: Uint8Array } | undefined;
    if (!file) throw new WorkflowError("The original PDF is missing from this browser's storage.");
    const notes = ((await request(store(tx, "notes").index("lecture_id").getAll(lectureId))) as StoredNote[]).sort(
      byPageThenCreated,
    );
    const cards: CardRecord[] = [];
    for (const { lecture_id: _lecture, ...note } of notes) {
      const revisions = ((await request(store(tx, "revisions").index("card_id").getAll(note.id))) as StoredRevision[])
        .sort((a, b) => a.version - b.version)
        .map(({ card_id: _card, ...revision }) => revision);
      cards.push({ ...note, revisions });
    }
    const runs = ((await request(store(tx, "runs").index("lecture_id").getAll(lectureId))) as StoredRun[])
      .sort(compareNewest)
      .map(({ lecture_id: _lecture, ...run }) => run);
    const { id, title, sha256, original_name, created_at } = lecture;
    return {
      manifest: {
        lecture: { id, title, sha256, original_name, created_at },
        pages: pages.map(({ number, text, width, height, warning }) => ({ number, text, width, height, warning })),
        cards,
        runs,
      },
      pdf: file.bytes,
      pages: images,
    };
  });
}

export async function markBackedUp(lectureId: string): Promise<void> {
  await transaction(["lectures"], "readwrite", async (tx) => {
    const lecture = (await request(store(tx, "lectures").get(lectureId))) as StoredLecture | undefined;
    if (lecture) store(tx, "lectures").put({ ...lecture, backed_up_at: new Date().toISOString() });
  });
  changed(lectureId);
}

export async function deleteLecture(lectureId: string): Promise<void> {
  await transaction(["lectures", "pages", "images", "files", "notes", "revisions", "runs"], "readwrite", async (tx) => {
    const lecture = (await request(store(tx, "lectures").get(lectureId))) as StoredLecture | undefined;
    if (!lecture) return;
    const pages = (await request(store(tx, "pages").index("lecture_id").getAll(lectureId))) as StoredPage[];
    const notes = (await request(store(tx, "notes").index("lecture_id").getAll(lectureId))) as StoredNote[];
    const runs = (await request(store(tx, "runs").index("lecture_id").getAll(lectureId))) as StoredRun[];
    for (const note of notes) {
      const keys = await request(store(tx, "revisions").index("card_id").getAllKeys(note.id));
      for (const key of keys) store(tx, "revisions").delete(key);
      store(tx, "notes").delete(note.id);
    }
    for (const run of runs) store(tx, "runs").delete(run.id);
    for (const page of pages) store(tx, "pages").delete([lectureId, page.number]);
    for (const sha of new Set(pages.map((page) => page.image_sha))) {
      const users = (await request(store(tx, "pages").index("image_sha").getAll(sha))) as StoredPage[];
      if (!users.some((page) => page.lecture_id !== lectureId)) store(tx, "images").delete(sha);
    }
    store(tx, "files").delete(lecture.sha256);
    store(tx, "lectures").delete(lectureId);
  });
  changed(null);
}

export async function renameLecture(lectureId: string, title: string): Promise<void> {
  const clean = title.trim().slice(0, 180);
  if (!clean) throw new WorkflowError("Give the lecture a name.");
  await transaction(["lectures"], "readwrite", async (tx) => {
    const lecture = (await request(store(tx, "lectures").get(lectureId))) as StoredLecture | undefined;
    if (!lecture) throw new WorkflowError("This lecture is no longer in your library.");
    store(tx, "lectures").put({ ...lecture, title: clean, updated_at: nowIso() });
  });
  changed(lectureId);
}

// ---------------------------------------------------------------------------
// Notes

async function touchLecture(tx: IDBTransaction, lectureId: string): Promise<void> {
  const lecture = (await request(store(tx, "lectures").get(lectureId))) as StoredLecture | undefined;
  if (lecture) store(tx, "lectures").put({ ...lecture, updated_at: nowIso() });
}

/** Insert drafts unless the same question already exists (fingerprint per lecture). */
export async function addDrafts(lectureId: string, drafts: readonly Draft[], runId: string | null = null): Promise<number> {
  const count = await transaction(["lectures", "pages", "notes"], "readwrite", (tx) => insertDrafts(tx, lectureId, drafts, runId));
  if (count) changed(lectureId);
  return count;
}

export async function insertDrafts(
  tx: IDBTransaction,
  lectureId: string,
  drafts: readonly Draft[],
  runId: string | null,
): Promise<number> {
  let count = 0;
  for (const draft of drafts) {
    if (draft.noteType === "occlusion" || draft.noteType === "visual") {
      throw new WorkflowError("Image notes can only come from a backup.");
    }
    const page = (await request(store(tx, "pages").get([lectureId, draft.page]))) as StoredPage | undefined;
    if (!page) throw new WorkflowError("Choose a source page from this lecture.");
    validateContent(draft.front, draft.back, draft.sourceQuote, page, { noteType: draft.noteType });
    const key = fingerprint(draft.front, draft.noteType);
    if (await request(store(tx, "notes").index("lecture_fingerprint").getKey([lectureId, key]))) continue;
    const now = nowIso();
    const note: StoredNote = {
      id: newUuid(),
      lecture_id: lectureId,
      page: draft.page,
      front: draft.front,
      note_type: draft.noteType,
      back: draft.back,
      source_quote: draft.sourceQuote,
      source_crop: {},
      occlusion: {},
      visual_masks: [],
      status: "draft",
      fingerprint: key,
      version: 1,
      anki_modified: unixSeconds(),
      run: runId,
      created_at: now,
      updated_at: now,
    };
    store(tx, "notes").add(note);
    count += 1;
  }
  if (count) await touchLecture(tx, lectureId);
  return count;
}

export interface NoteChanges {
  front: string;
  back: string;
  source_quote: string;
  status: NoteStatus;
  source_crop?: unknown;
  occlusion?: unknown;
  visual_masks?: unknown;
}

async function applyUpdate(tx: IDBTransaction, note: StoredNote, version: number, changes: NoteChanges): Promise<StoredNote> {
  if (!["draft", "accepted", "rejected"].includes(changes.status)) {
    throw new WorkflowError("Choose a valid card status.");
  }
  const page = (await request(store(tx, "pages").get([note.lecture_id, note.page]))) as StoredPage;
  const crop = checkedCrop(changes.source_crop === undefined ? note.source_crop : changes.source_crop, page);
  const mask = checkedOcclusion(changes.occlusion === undefined ? note.occlusion : changes.occlusion, page, note.note_type, crop);
  const covers = checkedVisualMasks(
    changes.visual_masks === undefined ? note.visual_masks : changes.visual_masks,
    page,
    note.note_type,
  );
  const [front, back, quote] = validateContent(changes.front, changes.back, changes.source_quote, page, {
    noteType: note.note_type,
  });
  // Keep cloze ordinals stable: they identify separately scheduled Anki cards.
  if (note.note_type === "cloze") {
    const before = new Set(clozeMatches(note.front).map((m) => m.number));
    const after = new Set(clozeMatches(front).map((m) => m.number));
    if (before.size !== after.size || [...after].some((n) => !before.has(n))) {
      throw new WorkflowError(
        "Keep this note's existing cloze numbers when editing. Create a new note for a different set of blanks.",
      );
    }
  }
  if (note.version !== version) {
    throw new WorkflowError("This card changed in another tab. Reload before saving to avoid losing edits.");
  }
  const now = nowIso();
  const revision: StoredRevision = {
    card_id: note.id,
    version,
    front: note.front,
    note_type: note.note_type,
    visual_masks: note.visual_masks,
    back: note.back,
    source_quote: note.source_quote,
    source_crop: note.source_crop,
    occlusion: note.occlusion,
    status: note.status,
    created_at: now,
  };
  const updated: StoredNote = {
    ...note,
    front,
    back,
    source_quote: quote,
    source_crop: crop,
    occlusion: mask,
    visual_masks: covers,
    status: changes.status,
    version: version + 1,
    updated_at: now,
    anki_modified: Math.max(unixSeconds(), note.anki_modified + 1),
  };
  store(tx, "revisions").put(revision);
  store(tx, "notes").put(updated);
  return updated;
}

async function getNote(tx: IDBTransaction, id: string): Promise<StoredNote> {
  const note = (await request(store(tx, "notes").get(id))) as StoredNote | undefined;
  if (!note) throw new WorkflowError("This card no longer exists. Reload the lecture.");
  return note;
}

/** Save an edit with a revision; rejects stale versions from other tabs. */
export async function updateNote(id: string, version: number, changes: NoteChanges): Promise<StoredNote> {
  const updated = await transaction(["lectures", "pages", "notes", "revisions"], "readwrite", async (tx) => {
    const result = await applyUpdate(tx, await getNote(tx, id), version, changes);
    await touchLecture(tx, result.lecture_id);
    return result;
  });
  changed(updated.lecture_id);
  return updated;
}

/** Restore the immediately preceding revision with the same identity. */
export async function undoNote(id: string, version: number): Promise<StoredNote> {
  const updated = await transaction(["lectures", "pages", "notes", "revisions"], "readwrite", async (tx) => {
    const note = await getNote(tx, id);
    if (note.version !== version) throw new WorkflowError("This card changed in another tab. Reload before undoing.");
    const revision = (await request(store(tx, "revisions").get([id, version - 1]))) as StoredRevision | undefined;
    if (!revision || revision.note_type !== note.note_type) {
      throw new WorkflowError("There is no compatible previous edit to undo.");
    }
    const result = await applyUpdate(tx, note, version, {
      front: revision.front,
      back: revision.back,
      source_quote: revision.source_quote,
      status: revision.status as NoteStatus,
      source_crop: revision.source_crop,
      occlusion: revision.occlusion,
      visual_masks: revision.visual_masks,
    });
    await touchLecture(tx, result.lecture_id);
    return result;
  });
  changed(updated.lecture_id);
  return updated;
}

/** Accept the displayed drafts atomically, retaining edits, evidence and revisions. */
export async function keepDrafts(lectureId: string, versions: Record<string, number>): Promise<number> {
  const entries = Object.entries(versions);
  if (!entries.length) throw new WorkflowError("There are no drafts in this selection. Reload the lecture.");
  if (entries.some(([id, version]) => !isUuid(id) || !Number.isInteger(version) || version < 1)) {
    throw new WorkflowError("The draft selection is invalid. Reload the lecture.");
  }
  const count = await transaction(["lectures", "pages", "notes", "revisions"], "readwrite", async (tx) => {
    const notes: StoredNote[] = [];
    for (const [id] of entries) {
      const note = (await request(store(tx, "notes").get(id))) as StoredNote | undefined;
      if (note) notes.push(note);
    }
    if (
      notes.length !== entries.length ||
      notes.some((note) => note.lecture_id !== lectureId || note.status !== "draft" || note.version !== versions[note.id])
    ) {
      throw new WorkflowError("Some drafts changed or were removed. Nothing was kept. Reload the lecture and try again.");
    }
    for (const note of notes) {
      await applyUpdate(tx, note, note.version, {
        front: note.front,
        back: note.back,
        source_quote: note.source_quote,
        status: "accepted",
      });
    }
    await touchLecture(tx, lectureId);
    return notes.length;
  });
  changed(lectureId);
  return count;
}

/** Manual card beside the source; an identical question is not duplicated. */
export async function addManualNote(
  lectureId: string,
  pageNumber: number,
  front: string,
  back: string,
  noteType: Extract<NoteType, "basic" | "cloze" | "reversed">,
): Promise<boolean> {
  const added = await addDrafts(lectureId, [{ page: pageNumber, front, back, sourceQuote: "", noteType }]);
  if (!added) throw new WorkflowError("A card with this question already exists in this lecture.");
  return true;
}

// ---------------------------------------------------------------------------
// Runs

export async function putRun(run: StoredRun): Promise<void> {
  await transaction(["runs"], "readwrite", async (tx) => {
    store(tx, "runs").put(run);
  });
  changed(run.lecture_id);
}

export async function getRun(id: string): Promise<StoredRun | null> {
  return transaction(["runs"], "readonly", async (tx) => ((await request(store(tx, "runs").get(id))) as StoredRun) ?? null);
}

// ---------------------------------------------------------------------------
// Storage

export async function requestPersistentStorage(): Promise<boolean | null> {
  try {
    if (!navigator.storage?.persist) return null;
    return (await navigator.storage.persisted()) || (await navigator.storage.persist());
  } catch {
    return null;
  }
}

export async function storageEstimate(): Promise<{ usage: number; quota: number } | null> {
  try {
    const estimate = await navigator.storage?.estimate?.();
    return estimate ? { usage: estimate.usage ?? 0, quota: estimate.quota ?? 0 } : null;
  } catch {
    return null;
  }
}
