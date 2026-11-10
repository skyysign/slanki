import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { clozeMatches, studyCardCount, studyPreviews } from "../core/noteTypes.ts";
import { exportDeck, saveBackup } from "../services/lectures.ts";
import { addManualNote, deleteLecture, renameLecture, type LectureBundle } from "../store/library.ts";
import { Dialog, plural, useBusy, useImageUrl } from "./components.tsx";
import { errorMessage, notify, openLibrary, reportError } from "./state.ts";

type Props = { open: boolean; bundle: LectureBundle; onClose: () => void };

export function ExportDialog({ open, bundle, onClose }: Props) {
  const [busy, run] = useBusy();
  const ready = bundle.notes.filter((n) => n.status === "accepted");
  const cards = ready.reduce((sum, n) => sum + studyCardCount(n.front, n.note_type), 0);
  const aside = bundle.notes.filter((n) => n.status === "rejected").length;
  const drafts = bundle.notes.filter((n) => n.status === "draft").length;
  return (
    <Dialog open={open} onClose={onClose} label="Export to Anki">
      <h2>Export to Anki</h2>
      <p>
        <strong>{plural(ready.length, "ready note")}</strong> become <strong>{plural(cards, "Anki card")}</strong>, each with its source slide.
      </p>
      {(drafts > 0 || aside > 0) && (
        <p class="muted small">
          Not included: {drafts ? plural(drafts, "draft") + " still to review" : ""}
          {drafts && aside ? ", " : ""}
          {aside ? plural(aside, "card") + " set aside" : ""}.
        </p>
      )}
      <p class="note-box">
        Open the downloaded file with Anki. Cards you exported before are updated in place and keep their review history. Setting a card aside here does not delete it from Anki.
      </p>
      <div class="dialog-actions">
        <button class="btn" onClick={onClose}>
          Close
        </button>
        <button
          class="btn primary"
          disabled={busy || !ready.length}
          onClick={() =>
            run(async () => {
              try {
                await exportDeck(bundle.lecture.id);
                notify("Deck downloaded. Open it with Anki.");
                onClose();
              } catch (error) {
                reportError(error);
              }
            })
          }
        >
          {busy ? "Preparing…" : "Download .apkg"}
        </button>
      </div>
    </Dialog>
  );
}

export function KeepAllDialog(props: Props & { onConfirm: (versions: Record<string, number>) => Promise<void> }) {
  const [busy, run] = useBusy();
  // Freeze the selection when the dialog opens so later drafts are not included.
  const [snapshot, setSnapshot] = useState<Record<string, number>>({});
  useEffect(() => {
    if (props.open) {
      setSnapshot(Object.fromEntries(props.bundle.notes.filter((n) => n.status === "draft").map((n) => [n.id, n.version])));
    }
  }, [props.open]);
  const drafts = props.bundle.notes.filter((n) => n.id in snapshot);
  const cards = drafts.reduce((sum, n) => sum + studyCardCount(n.front, n.note_type), 0);
  return (
    <Dialog open={props.open} onClose={props.onClose} label="Keep all drafts">
      <h2>Keep all {plural(drafts.length, "draft")}?</h2>
      <p>
        They become ready for export ({plural(cards, "Anki card")}). Text, slides and edit history stay as they are. Cards you already kept or set aside are not changed.
      </p>
      <p class="muted small">This skips reviewing each card. The AI can make mistakes, so you might still want to read them later.</p>
      <div class="dialog-actions">
        <button class="btn" onClick={props.onClose}>
          Cancel
        </button>
        <button class="btn success" disabled={busy || !drafts.length} onClick={() => run(() => props.onConfirm(snapshot))}>
          Keep all
        </button>
      </div>
    </Dialog>
  );
}

export function DeleteDialog({ open, bundle, onClose }: Props) {
  const [confirmed, setConfirmed] = useState(false);
  const [busy, run] = useBusy();
  useEffect(() => setConfirmed(false), [open]);
  return (
    <Dialog open={open} onClose={onClose} label="Delete lecture">
      <h2>Delete “{bundle.lecture.title}”?</h2>
      <p>
        This removes {plural(bundle.notes.length, "card")}, their history and {plural(bundle.pages.length, "slide")} from this browser. Decks already in Anki are not affected.
      </p>
      <button class="btn" disabled={busy} onClick={() => run(() => saveBackup(bundle.lecture.id).then(() => notify("Backup downloaded."), reportError))}>
        Save a backup first
      </button>
      <label class="check">
        <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.currentTarget.checked)} />
        <span>I understand this cannot be undone.</span>
      </label>
      <div class="dialog-actions">
        <button class="btn" onClick={onClose}>
          Cancel
        </button>
        <button
          class="btn danger solid"
          disabled={!confirmed || busy}
          onClick={() =>
            run(async () => {
              try {
                await deleteLecture(bundle.lecture.id);
                notify("Lecture deleted.");
                openLibrary();
              } catch (error) {
                reportError(error);
              }
            })
          }
        >
          Delete lecture
        </button>
      </div>
    </Dialog>
  );
}

export function RenameDialog({ open, bundle, onClose }: Props) {
  const [title, setTitle] = useState(bundle.lecture.title);
  useEffect(() => setTitle(bundle.lecture.title), [open]);
  return (
    <Dialog open={open} onClose={onClose} label="Rename lecture">
      <form
        class="stack"
        onSubmit={(event) => {
          event.preventDefault();
          void renameLecture(bundle.lecture.id, title).then(onClose, reportError);
        }}
      >
        <h2>Rename lecture</h2>
        <label class="field">
          <span>Name (also the Anki deck name)</span>
          <input class="input" value={title} maxLength={180} onInput={(event) => setTitle(event.currentTarget.value)} />
        </label>
        <div class="dialog-actions">
          <button type="button" class="btn" onClick={onClose}>
            Cancel
          </button>
          <button class="btn primary">Save</button>
        </div>
      </form>
    </Dialog>
  );
}

type ManualType = "basic" | "cloze" | "reversed";

export function ManualCardDialog(props: Props & { pageNumber: number; onAdded: (front: string) => void }) {
  const [type, setType] = useState<ManualType>("basic");
  const [front, setFront] = useState("");
  const [back, setBack] = useState("");
  const [page, setPage] = useState(props.pageNumber);
  const [busy, run] = useBusy();
  const frontRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (props.open) {
      setFront("");
      setBack("");
      setPage(props.pageNumber);
    }
  }, [props.open]);
  const preview = useMemo(() => {
    if (!front.trim()) return { cards: [], error: "" };
    try {
      return { cards: studyPreviews(front, back, type), error: "" };
    } catch (error) {
      return { cards: [], error: errorMessage(error) };
    }
  }, [front, back, type]);
  const hideSelection = () => {
    const area = frontRef.current;
    if (!area || area.selectionStart === area.selectionEnd) {
      notify("Select the words to hide first.");
      return;
    }
    let used: number[] = [];
    try {
      used = clozeMatches(front).map((m) => m.number);
    } catch {
      used = [];
    }
    const number = Math.min(20, (used.length ? Math.max(...used) : 0) + 1);
    const { selectionStart: start, selectionEnd: end } = area;
    setFront(front.slice(0, start) + `{{c${number}::${front.slice(start, end)}}}` + front.slice(end));
  };
  return (
    <Dialog open={props.open} onClose={props.onClose} label="Write a card">
      <form
        class="stack"
        onSubmit={(event) => {
          event.preventDefault();
          void run(async () => {
            try {
              await addManualNote(props.bundle.lecture.id, page, front, back, type);
              notify("Card added to review.");
              props.onClose();
              props.onAdded(front.trim());
            } catch (error) {
              reportError(error);
            }
          });
        }}
      >
        <h2>Write a card</h2>
        <div class="tabs" role="radiogroup" aria-label="Card type">
          {(
            [
              ["basic", "Question & answer"],
              ["cloze", "Fill in the blank"],
              ["reversed", "Both directions"],
            ] as const
          ).map(([value, label]) => (
            <button type="button" key={value} class="tab" role="radio" aria-checked={type === value} aria-selected={type === value} onClick={() => setType(value)}>
              {label}
            </button>
          ))}
        </div>
        <label class="field">
          <span>{type === "cloze" ? "Sentence (select words and hide them)" : type === "reversed" ? "Term" : "Question"}</span>
          <textarea ref={frontRef} class="input" rows={3} value={front} onInput={(event) => setFront(event.currentTarget.value)} required />
        </label>
        {type === "cloze" && (
          <button type="button" class="btn small" onClick={hideSelection} style={{ width: "fit-content" }}>
            Hide selected words
          </button>
        )}
        <label class="field">
          <span>{type === "cloze" ? "Extra explanation (optional)" : type === "reversed" ? "Definition" : "Answer"}</span>
          <textarea class="input" rows={3} value={back} onInput={(event) => setBack(event.currentTarget.value)} required={type !== "cloze"} />
        </label>
        <label class="field">
          <span>Source slide</span>
          <select class="input" value={page} onChange={(event) => setPage(Number(event.currentTarget.value))}>
            {props.bundle.pages.map((p) => (
              <option key={p.number} value={p.number}>
                Slide {p.number}
              </option>
            ))}
          </select>
        </label>
        {preview.error && <p class="banner error small">{preview.error}</p>}
        {preview.cards.length > 0 && (
          <div class="preview">
            {preview.cards.map((card) => (
              <div class="preview-card" key={card.number}>
                <div dangerouslySetInnerHTML={{ __html: card.question }} />
                <hr />
                <div dangerouslySetInnerHTML={{ __html: card.answer }} />
              </div>
            ))}
          </div>
        )}
        <div class="dialog-actions">
          <button type="button" class="btn" onClick={props.onClose}>
            Cancel
          </button>
          <button class="btn primary" disabled={busy || !!preview.error}>
            Add card
          </button>
        </div>
      </form>
    </Dialog>
  );
}

export function SlideViewer(props: Props & { pageNumber: number; setPage: (page: number) => void }) {
  const page = props.bundle.pages.find((p) => p.number === props.pageNumber) ?? props.bundle.pages[0]!;
  const url = useImageUrl(page.image_sha);
  const [zoom, setZoom] = useState(1);
  useEffect(() => setZoom(1), [props.open, page.number]);
  const step = (delta: number) => {
    const target = page.number + delta;
    if (target >= 1 && target <= props.bundle.pages.length) props.setPage(target);
  };
  return (
    <Dialog open={props.open} onClose={props.onClose} label={`Slide ${page.number}`} className="viewer">
      <div class="row">
        <strong>Slide {page.number}</strong>
        <span class="spacer" />
        <button class="btn small icon" aria-label="Previous slide" onClick={() => step(-1)}>
          ‹
        </button>
        <button class="btn small icon" aria-label="Next slide" onClick={() => step(1)}>
          ›
        </button>
        <button class="btn small icon" aria-label="Zoom out" onClick={() => setZoom(Math.max(0.5, zoom / 1.25))}>
          −
        </button>
        <button class="btn small" onClick={() => setZoom(1)}>
          Fit
        </button>
        <button class="btn small icon" aria-label="Zoom in" onClick={() => setZoom(Math.min(4, zoom * 1.25))}>
          +
        </button>
        <button class="btn small" onClick={props.onClose}>
          Close
        </button>
      </div>
      <div
        class="viewer-stage"
        onWheel={(event) => {
          if (!event.ctrlKey) return;
          event.preventDefault();
          setZoom(Math.min(4, Math.max(0.5, zoom * (event.deltaY < 0 ? 1.1 : 1 / 1.1))));
        }}
      >
        {url && <img src={url} alt={`Slide ${page.number}`} style={{ width: `${zoom * 100}%`, height: "auto" }} />}
      </div>
    </Dialog>
  );
}
