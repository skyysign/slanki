import { useCallback, useEffect, useMemo, useRef, useState } from "preact/hooks";
import { NOTE_TYPE_LABELS, studyCardCount, studyPreviews } from "../core/noteTypes.ts";
import type { Crop } from "../core/geometry.ts";
import { pyStrip } from "../core/py.ts";
import {
  getLecture,
  keepDrafts,
  onLibraryChange,
  undoNote,
  updateNote,
  type LectureBundle,
  type NoteStatus,
  type StoredNote,
  type StoredPage,
} from "../store/library.ts";
import { Menu, plural, useBusy, useImageUrl } from "./components.tsx";
import { DeleteDialog, ExportDialog, KeepAllDialog, ManualCardDialog, RenameDialog, SlideViewer } from "./dialogs.tsx";
import { CropControls, CropPreview, hasCrop, useRegionDrag } from "./CropTool.tsx";
import { MakeCardsDialog } from "./MakeCards.tsx";
import { RunBanner } from "./RunBanner.tsx";
import { notify, openLibrary, reportError } from "./state.ts";
import { saveBackup } from "../services/lectures.ts";

type Filter = "review" | "ready" | "aside" | "all";
const FILTER_STATUS: Record<Filter, NoteStatus | null> = { review: "draft", ready: "accepted", aside: "rejected", all: null };
const FILTER_LABEL: Record<Filter, string> = { review: "To review", ready: "Ready", aside: "Set aside", all: "All" };

export function Workspace({ id }: { id: string }) {
  const [bundle, setBundle] = useState<LectureBundle | null | undefined>(undefined);
  const load = useCallback(async () => {
    const value = await getLecture(id);
    setBundle(value);
    return value;
  }, [id]);
  useEffect(() => {
    void load().catch(reportError);
    return onLibraryChange((changed) => {
      if (changed === null || changed === id) void load().catch(reportError);
    });
  }, [id, load]);
  if (bundle === undefined) return <p class="muted">Loading…</p>;
  if (bundle === null) {
    return (
      <div class="empty">
        <p>
          <strong>This lecture is not in this browser.</strong>
        </p>
        <p class="muted small">Lectures live in the browser where you added them. Restore a backup to bring one here.</p>
        <a class="btn" href="#/">
          Back to your lectures
        </a>
      </div>
    );
  }
  return <LectureView bundle={bundle} reload={load} />;
}

interface Fields {
  front: string;
  back: string;
  quote: string;
}

function isTyping(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  return !!element && (element.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(element.tagName));
}

function LectureView({ bundle, reload }: { bundle: LectureBundle; reload: () => Promise<LectureBundle | null> }) {
  const { lecture, notes, pages } = bundle;
  const counts = useMemo(
    () => ({
      review: notes.filter((n) => n.status === "draft").length,
      ready: notes.filter((n) => n.status === "accepted").length,
      aside: notes.filter((n) => n.status === "rejected").length,
      all: notes.length,
    }),
    [notes],
  );
  const readyCards = useMemo(
    () => notes.filter((n) => n.status === "accepted").reduce((sum, n) => sum + studyCardCount(n.front, n.note_type), 0),
    [notes],
  );
  const [filter, setFilter] = useState<Filter>(counts.review ? "review" : "all");
  const filtered = useMemo(
    () => notes.filter((n) => FILTER_STATUS[filter] === null || n.status === FILTER_STATUS[filter]),
    [notes, filter],
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const current = filtered.find((n) => n.id === selectedId) ?? filtered[0] ?? null;
  const index = current ? filtered.indexOf(current) : -1;

  const [fields, setFields] = useState<Fields>({ front: "", back: "", quote: "" });
  const fieldKey = current ? `${current.id}:${current.version}` : "";
  useEffect(() => {
    setFields(current ? { front: current.front, back: current.back, quote: current.source_quote } : { front: "", back: "", quote: "" });
  }, [fieldKey]);
  const dirty = !!current && (fields.front !== current.front || fields.back !== current.back || fields.quote !== current.source_quote);

  const [slidePage, setSlidePage] = useState(current?.page ?? 1);
  useEffect(() => {
    if (current) setSlidePage(current.page);
  }, [current?.id]);

  const [lastChange, setLastChange] = useState<{ id: string; version: number; label: string } | null>(null);
  const [dialog, setDialog] = useState<null | "make" | "export" | "keep" | "delete" | "rename" | "manual" | "viewer">(null);
  const [show, setShow] = useState<"card" | "slide">("card");
  const [busy, run] = useBusy();
  const question = useRef<HTMLTextAreaElement>(null);

  const persist = (status: NoteStatus, advance: boolean, label: string) =>
    run(async () => {
      if (!current) return;
      const before = filtered.map((n) => n.id);
      try {
        if (dirty || status !== current.status) {
          const updated = await updateNote(current.id, current.version, {
            front: fields.front,
            back: fields.back,
            source_quote: fields.quote,
            status,
          });
          setLastChange({ id: updated.id, version: updated.version, label });
        }
        const fresh = await reload();
        if (advance && fresh) {
          const status_ = FILTER_STATUS[filter];
          const still = new Set(fresh.notes.filter((n) => status_ === null || n.status === status_).map((n) => n.id));
          const at = before.indexOf(current.id);
          const nextId =
            before.slice(at + 1).find((noteId) => still.has(noteId)) ??
            before.slice(0, at).reverse().find((noteId) => still.has(noteId)) ??
            null;
          setSelectedId(status_ === null || still.has(current.id) ? (before[at + 1] ?? current.id) : nextId);
        }
      } catch (error) {
        reportError(error);
      }
    });

  const select = (noteId: string) =>
    run(async () => {
      if (current && dirty) {
        try {
          const updated = await updateNote(current.id, current.version, {
            front: fields.front,
            back: fields.back,
            source_quote: fields.quote,
            status: current.status,
          });
          setLastChange({ id: updated.id, version: updated.version, label: "Edit saved" });
          await reload();
        } catch (error) {
          reportError(error);
          return;
        }
      }
      setSelectedId(noteId);
      setShow("card");
    });

  const undo = () =>
    run(async () => {
      if (!lastChange) return;
      try {
        const restored = await undoNote(lastChange.id, lastChange.version);
        setLastChange(null);
        await reload();
        const matches = FILTER_STATUS[filter] === null || FILTER_STATUS[filter] === restored.status;
        if (!matches) setFilter("all");
        setSelectedId(restored.id);
        notify("Change undone.");
      } catch (error) {
        reportError(error);
      }
    });

  const move = (step: number) => {
    const target = filtered[index + step];
    if (target) void select(target.id);
  };

  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey || isTyping(event.target) || document.querySelector("dialog[open]")) return;
      const key = event.key.toLowerCase();
      if (key === "a" && current) void persist("accepted", true, "Kept");
      else if (key === "s" && current) void persist("rejected", true, "Set aside");
      else if (key === "z" && lastChange) void undo();
      else if (key === "e" && current) question.current?.focus();
      else if (key === "arrowright" || key === "j") move(1);
      else if (key === "arrowleft" || key === "k") move(-1);
      else return;
      event.preventDefault();
    };
    document.addEventListener("keydown", handle);
    return () => document.removeEventListener("keydown", handle);
  });

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    addEventListener("beforeunload", warn);
    return () => removeEventListener("beforeunload", warn);
  }, [dirty]);

  const unreadable = pages.filter((p) => p.warning || !pyStrip(p.text)).length;
  const page = pages.find((p) => p.number === slidePage) ?? pages[0]!;

  return (
    <>
      <div class="ws-head">
        <a class="btn ghost small" href="#/" onClick={(event) => (dirty ? (event.preventDefault(), void select(current!.id).then(openLibrary)) : undefined)}>
          ← Lectures
        </a>
        <h1>{lecture.title}</h1>
        <span class="spacer" />
        <button class="btn primary" onClick={() => setDialog("make")}>
          Make cards
        </button>
        <button class="btn" disabled={!counts.ready} onClick={() => setDialog("export")}>
          Export to Anki{readyCards ? ` · ${readyCards}` : ""}
        </button>
        <Menu label="More actions">
          {(close) => (
            <>
              <button onClick={() => (close(), setDialog("manual"))}>Write a card yourself</button>
              <button
                onClick={() => {
                  close();
                  void saveBackup(lecture.id).then(() => notify("Backup downloaded."), reportError);
                }}
              >
                Save backup
              </button>
              <button onClick={() => (close(), setDialog("rename"))}>Rename lecture</button>
              <button class="danger" onClick={() => (close(), setDialog("delete"))}>
                Delete lecture
              </button>
            </>
          )}
        </Menu>
      </div>
      <p class="muted small">
        {plural(pages.length, "slide")}
        {unreadable ? ` · ${unreadable} without readable text (write those cards yourself)` : ""}
      </p>

      <RunBanner bundle={bundle} onOpenMake={() => setDialog("make")} />

      {notes.length === 0 ? (
        <div class="empty" style={{ marginTop: "16px" }}>
          <p>
            <strong>No cards yet.</strong>
          </p>
          <p class="muted small">Make cards with your AI, or write one yourself beside a slide.</p>
          <div class="row" style={{ justifyContent: "center" }}>
            <button class="btn primary" onClick={() => setDialog("make")}>
              Make cards
            </button>
            <button class="btn" onClick={() => setDialog("manual")}>
              Write a card
            </button>
          </div>
        </div>
      ) : (
        <>
          <div class="row" style={{ marginTop: "8px" }}>
            <div class="tabs" role="tablist" aria-label="Cards">
              {(Object.keys(FILTER_LABEL) as Filter[]).map((key) => (
                <button
                  key={key}
                  class="tab"
                  role="tab"
                  aria-selected={filter === key}
                  onClick={() => {
                    setFilter(key);
                    setSelectedId(null);
                  }}
                >
                  {FILTER_LABEL[key]} <span class="muted">{counts[key]}</span>
                </button>
              ))}
            </div>
            <span class="spacer" />
            {counts.review > 0 && (
              <button class="btn small" disabled={busy || dirty} title={dirty ? "Save your edit first" : ""} onClick={() => setDialog("keep")}>
                Keep all {counts.review} drafts
              </button>
            )}
          </div>
          {lastChange && (
            <div class="banner ok">
              <span>{lastChange.label}.</span>
              <button class="btn small" disabled={busy} onClick={undo}>
                Undo <kbd>Z</kbd>
              </button>
            </div>
          )}
          <div class="row mobile-switch" style={{ marginTop: "10px" }}>
            <div class="tabs">
              <button class="tab" aria-selected={show === "card"} onClick={() => setShow("card")}>
                Card
              </button>
              <button class="tab" aria-selected={show === "slide"} onClick={() => setShow("slide")}>
                Slide {page.number}
              </button>
            </div>
          </div>
          <div class="panes" data-show={show}>
            <section class="pane card-pane" aria-label="Card">
              {current ? (
                <CardEditor
                  note={current}
                  position={`${index + 1} of ${filtered.length}`}
                  fields={fields}
                  setFields={setFields}
                  dirty={dirty}
                  busy={busy}
                  questionRef={question}
                  onKeep={() => persist("accepted", true, "Kept")}
                  onSetAside={() => persist("rejected", true, "Set aside")}
                  onSave={() => persist(current.status, false, "Edit saved")}
                  onRestore={() => persist("draft", false, "Moved back to review")}
                  onShowSlide={() => {
                    setSlidePage(current.page);
                    setShow("slide");
                  }}
                  page={pages.find((p) => p.number === current.page)}
                />
              ) : (
                <div class="stack">
                  <p>
                    <strong>{filter === "review" ? "All caught up." : "Nothing here."}</strong>
                  </p>
                  <p class="muted small">
                    {filter === "review" && counts.ready ? "Every draft has been reviewed. Export your ready cards to Anki." : "Choose another tab to see more cards."}
                  </p>
                  {filter === "review" && counts.ready > 0 && (
                    <button class="btn primary" onClick={() => setDialog("export")}>
                      Export to Anki
                    </button>
                  )}
                </div>
              )}
              {filtered.length > 1 && (
                <details class="page-text" open={filtered.length <= 12}>
                  <summary>All {plural(filtered.length, "card")} in “{FILTER_LABEL[filter]}”</summary>
                  <div class="queue">
                    {filtered.map((note, i) => (
                      <button key={note.id} aria-current={note.id === current?.id} onClick={() => select(note.id)}>
                        <span class={`status-dot ${note.status}`} />
                        <span class="num">p.{note.page}</span>
                        <span class="text">{note.front.replace(/\{\{c\d+::([^}]*?)(::[^}]*)?\}\}/g, "[$1]")}</span>
                        <span class="sr-only">card {i + 1}</span>
                      </button>
                    ))}
                  </div>
                </details>
              )}
            </section>
            <SlidePane
              bundle={bundle}
              note={current}
              pageNumber={page.number}
              setPage={setSlidePage}
              onZoom={() => setDialog("viewer")}
              onWrite={() => setDialog("manual")}
              dirty={dirty}
            />
          </div>
        </>
      )}

      <MakeCardsDialog open={dialog === "make"} bundle={bundle} onClose={() => setDialog(null)} />
      <ExportDialog open={dialog === "export"} bundle={bundle} onClose={() => setDialog(null)} />
      <KeepAllDialog
        open={dialog === "keep"}
        bundle={bundle}
        onClose={() => setDialog(null)}
        onConfirm={async (versions) => {
          try {
            const kept = await keepDrafts(lecture.id, versions);
            setLastChange(null);
            setDialog(null);
            await reload();
            setFilter("ready");
            notify(`${plural(kept, "card")} kept.`);
          } catch (error) {
            reportError(error);
            await reload();
          }
        }}
      />
      <DeleteDialog open={dialog === "delete"} bundle={bundle} onClose={() => setDialog(null)} />
      <RenameDialog open={dialog === "rename"} bundle={bundle} onClose={() => setDialog(null)} />
      <ManualCardDialog
        open={dialog === "manual"}
        bundle={bundle}
        pageNumber={page.number}
        onClose={() => setDialog(null)}
        onAdded={async (front) => {
          const fresh = await reload();
          const added = fresh?.notes.find((n) => n.front === front);
          setFilter("review");
          if (added) setSelectedId(added.id);
        }}
      />
      <SlideViewer open={dialog === "viewer"} bundle={bundle} pageNumber={page.number} setPage={setSlidePage} onClose={() => setDialog(null)} />
    </>
  );
}

function CardEditor(props: {
  note: StoredNote;
  position: string;
  fields: Fields;
  setFields: (fields: Fields) => void;
  dirty: boolean;
  busy: boolean;
  questionRef: { current: HTMLTextAreaElement | null };
  onKeep: () => void;
  onSetAside: () => void;
  onSave: () => void;
  onRestore: () => void;
  onShowSlide: () => void;
  page: StoredPage | undefined;
}) {
  const { note, fields, setFields } = props;
  const crop = hasCrop(note) && note.note_type !== "visual" ? (note.source_crop as Crop) : null;
  const slideUrl = useImageUrl(crop ? props.page?.image_sha : undefined);
  const cropView = crop && props.page ? <CropPreview url={slideUrl} page={props.page} crop={crop} /> : null;
  const image = note.note_type === "occlusion" || note.note_type === "visual";
  const [preview, setPreview] = useState(note.note_type === "cloze");
  const previews = useMemo(() => {
    try {
      return { cards: studyPreviews(fields.front, fields.back, note.note_type), error: "" };
    } catch (error) {
      return { cards: [], error: error instanceof Error ? error.message : String(error) };
    }
  }, [fields.front, fields.back, note.note_type]);
  const frontLabel = note.note_type === "cloze" ? "Cloze text" : note.note_type === "reversed" ? "Front (term)" : image ? "Prompt" : "Question";
  const backLabel = note.note_type === "cloze" ? "Extra (optional)" : note.note_type === "reversed" ? "Back (definition)" : image ? "Explanation" : "Answer";
  const submitOnShortcut = (event: KeyboardEvent) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      props.onKeep();
    }
  };
  return (
    <div class="editor stack">
      <div class="pane-head">
        <span class="kind">{NOTE_TYPE_LABELS[note.note_type]}</span>
        <span class="muted small">· card {props.position}</span>
        <span class="spacer" />
        <button class="btn small ghost" onClick={props.onShowSlide}>
          Slide {note.page}
        </button>
        {note.status === "accepted" && <span class="badge ready">Ready</span>}
        {note.status === "rejected" && <span class="badge">Set aside</span>}
      </div>
      <label class="field">
        <span>{frontLabel}</span>
        <textarea
          ref={props.questionRef}
          class="input question"
          rows={3}
          value={fields.front}
          onInput={(event) => setFields({ ...fields, front: event.currentTarget.value })}
          onKeyDown={submitOnShortcut}
        />
      </label>
      <label class="field">
        <span>{backLabel}</span>
        <textarea
          class="input answer"
          rows={3}
          value={fields.back}
          onInput={(event) => setFields({ ...fields, back: event.currentTarget.value })}
          onKeyDown={submitOnShortcut}
        />
      </label>
      {cropView && crop && (
        <div class="crop-note">
          {cropView}
          <span class="muted small">Part of slide {note.page}, shown {crop.on_question ? "on the question" : "with the answer"}.</span>
        </div>
      )}
      {image && (
        <p class="note-box">Image card from an older backup. Its hidden region stays as it is; you can still edit the text.</p>
      )}
      {(fields.quote || note.source_quote) && (
        <details>
          <summary class="muted small">Source excerpt</summary>
          <textarea
            class="input small"
            rows={2}
            value={fields.quote}
            onInput={(event) => setFields({ ...fields, quote: event.currentTarget.value })}
          />
        </details>
      )}
      {previews.error ? (
        <p class="banner error small">{previews.error}</p>
      ) : (
        <details class="preview" open={preview} onToggle={(event) => setPreview((event.currentTarget as HTMLDetailsElement).open)}>
          <summary class="muted small">
            Anki preview · {plural(previews.cards.length, "card")}
          </summary>
          {previews.cards.map((card) => (
            <div class="preview-card" key={card.number}>
              {card.direction && <div class="kind">{card.direction}</div>}
              <div dangerouslySetInnerHTML={{ __html: card.question }} />
              {crop?.on_question && cropView}
              <hr />
              <div dangerouslySetInnerHTML={{ __html: card.answer }} />
              {crop && !crop.on_question && cropView}
            </div>
          ))}
        </details>
      )}
      <div class="decisions">
        {note.status === "draft" ? (
          <>
            <button class="btn" disabled={props.busy} onClick={props.onSetAside}>
              Set aside <kbd>S</kbd>
            </button>
            <button class="btn success" disabled={props.busy} onClick={props.onKeep}>
              Keep &amp; next <kbd>A</kbd>
            </button>
          </>
        ) : (
          <>
            {props.dirty && (
              <button class="btn primary" disabled={props.busy} onClick={props.onSave}>
                Save edit
              </button>
            )}
            <button class="btn" disabled={props.busy} onClick={props.onRestore}>
              Move back to review
            </button>
            {note.status === "rejected" ? (
              <button class="btn success" disabled={props.busy} onClick={props.onKeep}>
                Keep instead
              </button>
            ) : (
              <button class="btn" disabled={props.busy} onClick={props.onSetAside}>
                Set aside
              </button>
            )}
          </>
        )}
      </div>
      {props.dirty && note.status === "draft" && <p class="muted small">Your edit is saved when you keep, set aside or switch cards.</p>}
    </div>
  );
}

function Overlay({ note, width, height }: { note: StoredNote | null; width: number; height: number }) {
  if (!note) return null;
  const box = (rect: { left: number; top: number; right: number; bottom: number }) => ({
    left: `${(rect.left / width) * 100}%`,
    top: `${(rect.top / height) * 100}%`,
    width: `${((rect.right - rect.left) / width) * 100}%`,
    height: `${((rect.bottom - rect.top) / height) * 100}%`,
  });
  const crop = note.source_crop as { left?: number };
  const occlusion = note.occlusion as { left?: number };
  return (
    <>
      {crop.left !== undefined && <div class="crop" style={box(note.source_crop as never)} />}
      {occlusion.left !== undefined && <div class="mask" style={box(note.occlusion as never)} />}
      {note.visual_masks.map((mask, i) => (
        <div key={i} class="mask" style={box(mask)} />
      ))}
    </>
  );
}

function SlidePane(props: {
  bundle: LectureBundle;
  note: StoredNote | null;
  pageNumber: number;
  setPage: (page: number) => void;
  onZoom: () => void;
  onWrite: () => void;
  dirty: boolean;
}) {
  const { pages } = props.bundle;
  const page = pages.find((p) => p.number === props.pageNumber) ?? pages[0]!;
  const url = useImageUrl(page.image_sha);
  const sameNotePage = props.note?.page === page.number;
  const [cropping, setCropping] = useState(false);
  const drag = useRegionDrag(page);
  useEffect(() => {
    setCropping(false);
    drag.setRect(null);
  }, [props.note?.id, page.number]);
  const canCrop = !!props.note && sameNotePage && ["basic", "cloze", "reversed"].includes(props.note.note_type);
  const step = (delta: number) => {
    const target = page.number + delta;
    if (target >= 1 && target <= pages.length) props.setPage(target);
  };
  const box = (rect: { left: number; top: number; right: number; bottom: number }) => ({
    left: `${(rect.left / page.width) * 100}%`,
    top: `${(rect.top / page.height) * 100}%`,
    width: `${((rect.right - rect.left) / page.width) * 100}%`,
    height: `${((rect.bottom - rect.top) / page.height) * 100}%`,
  });
  const image = url ? (
    <img src={url} alt={`Slide ${page.number}`} width={page.width} height={page.height} draggable={false} />
  ) : (
    <div style={{ aspectRatio: `${page.width} / ${page.height}` }} />
  );
  return (
    <section class="pane slide-pane" aria-label="Source slide">
      <div class="pane-head">
        <button class="btn small icon" aria-label="Previous slide" disabled={page.number <= 1} onClick={() => step(-1)}>
          ‹
        </button>
        <strong>
          Slide {page.number} <span class="muted">of {pages.length}</span>
        </strong>
        <button class="btn small icon" aria-label="Next slide" disabled={page.number >= pages.length} onClick={() => step(1)}>
          ›
        </button>
        {page.warning && <span class="badge warn">No text</span>}
        <span class="spacer" />
        {canCrop && !cropping && (
          <button
            class="btn small"
            disabled={props.dirty}
            title={props.dirty ? "Save your edit first" : "Show part of this slide with the card"}
            onClick={() => setCropping(true)}
          >
            {hasCrop(props.note!) ? "Change slide region" : "Attach part of slide"}
          </button>
        )}
        <button class="btn small" onClick={props.onWrite}>
          Write a card
        </button>
      </div>
      {cropping && props.note ? (
        <div class="slide cropping" {...drag.handlers} aria-label="Drag to choose a region of the slide">
          {image}
          {drag.rect && <div class="crop" style={box(drag.rect)} />}
        </div>
      ) : (
        <button type="button" class="slide" style={{ padding: 0, width: "100%" }} onClick={props.onZoom} aria-label="Enlarge slide">
          {image}
          {sameNotePage && <Overlay note={props.note} width={page.width} height={page.height} />}
        </button>
      )}
      {cropping && props.note && (
        <CropControls
          note={props.note}
          page={page}
          rect={drag.rect}
          onDone={() => {
            setCropping(false);
            drag.setRect(null);
          }}
        />
      )}
      {props.note?.source_quote && sameNotePage && <p class="quote" style={{ marginTop: "12px" }}>{props.note.source_quote}</p>}
      {page.text && (
        <details class="page-text">
          <summary>Text on this slide</summary>
          <pre>{page.text}</pre>
        </details>
      )}
    </section>
  );
}
