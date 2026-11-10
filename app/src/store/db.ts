// IndexedDB access. Versioned upgrades replace Django migrations: add a new
// `if (oldVersion < N)` block for every schema change and never edit old ones.

export const DB_NAME = "slanki";
export const DB_VERSION = 1;

export type StoreName = "lectures" | "pages" | "images" | "files" | "notes" | "revisions" | "runs" | "meta";

let opening: Promise<IDBDatabase> | null = null;

export function request<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export function openDb(factory: IDBFactory = indexedDB): Promise<IDBDatabase> {
  if (opening) return opening;
  opening = new Promise((resolve, reject) => {
    const open = factory.open(DB_NAME, DB_VERSION);
    open.onupgradeneeded = (event) => {
      const db = open.result;
      if (event.oldVersion < 1) {
        const lectures = db.createObjectStore("lectures", { keyPath: "id" });
        lectures.createIndex("sha256", "sha256", { unique: true });
        const pages = db.createObjectStore("pages", { keyPath: ["lecture_id", "number"] });
        pages.createIndex("lecture_id", "lecture_id");
        pages.createIndex("image_sha", "image_sha");
        db.createObjectStore("images", { keyPath: "sha" });
        db.createObjectStore("files", { keyPath: "sha" });
        const notes = db.createObjectStore("notes", { keyPath: "id" });
        notes.createIndex("lecture_id", "lecture_id");
        notes.createIndex("lecture_fingerprint", ["lecture_id", "fingerprint"], { unique: true });
        const revisions = db.createObjectStore("revisions", { keyPath: ["card_id", "version"] });
        revisions.createIndex("card_id", "card_id");
        const runs = db.createObjectStore("runs", { keyPath: "id" });
        runs.createIndex("lecture_id", "lecture_id");
        db.createObjectStore("meta", { keyPath: "key" });
      }
    };
    open.onsuccess = () => {
      const db = open.result;
      // Another tab upgraded the schema: close so it can proceed; this tab must reload.
      db.onversionchange = () => {
        db.close();
        opening = null;
        dispatchEvent(new CustomEvent("slanki:reload-required"));
      };
      resolve(db);
    };
    open.onerror = () => {
      opening = null;
      reject(open.error);
    };
    open.onblocked = () => dispatchEvent(new CustomEvent("slanki:close-other-tabs"));
  });
  return opening;
}

/** Test hook: forget the cached connection (fake-indexeddb). */
export function resetDbConnection(): void {
  opening = null;
}

/**
 * Run `work` in one transaction and resolve after it commits. Only await IDB
 * requests inside `work`; awaiting anything else lets the transaction commit early.
 */
export async function transaction<T>(
  stores: StoreName[],
  mode: IDBTransactionMode,
  work: (tx: IDBTransaction) => Promise<T>,
): Promise<T> {
  const db = await openDb();
  const tx = db.transaction(stores, mode);
  const done = new Promise<void>((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onabort = () => reject(tx.error ?? new DOMException("Transaction aborted", "AbortError"));
    tx.onerror = () => reject(tx.error);
  });
  let result: T;
  try {
    result = await work(tx);
  } catch (error) {
    try {
      tx.abort();
    } catch {
      // already finished
    }
    await done.catch(() => undefined);
    throw error;
  }
  await done;
  return result;
}

export function store(tx: IDBTransaction, name: StoreName): IDBObjectStore {
  return tx.objectStore(name);
}
