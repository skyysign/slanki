// Attach a rectangular part of the source slide to a text note (crop editor).
import { useRef, useState } from "preact/hooks";
import type { Crop } from "../core/geometry.ts";
import { updateNote, type StoredNote, type StoredPage } from "../store/library.ts";
import { reportError, notify } from "./state.ts";

export type Rect = { left: number; top: number; right: number; bottom: number };

export function hasCrop(note: StoredNote): boolean {
  return Object.keys(note.source_crop).length > 0;
}

/** CSS that shows only `rect` of the slide image (no canvas, CSP-safe). */
export function cropStyle(url: string, page: { width: number; height: number }, rect: Rect) {
  const width = rect.right - rect.left;
  const height = rect.bottom - rect.top;
  return {
    backgroundImage: `url("${url}")`,
    backgroundSize: `${(page.width / width) * 100}% auto`,
    backgroundPosition: `${width === page.width ? 0 : (rect.left / (page.width - width)) * 100}% ${
      height === page.height ? 0 : (rect.top / (page.height - height)) * 100
    }%`,
    aspectRatio: `${width} / ${height}`,
  };
}

export function CropPreview({ url, page, crop }: { url: string | undefined; page: StoredPage; crop: Crop }) {
  if (!url) return null;
  return <div class="crop-preview" role="img" aria-label="Attached part of the slide" style={cropStyle(url, page, crop)} />;
}

/** Drag on the slide to choose a region; returns pixel coordinates of the stored image. */
export function useRegionDrag(page: StoredPage) {
  const [rect, setRect] = useState<Rect | null>(null);
  const start = useRef<{ x: number; y: number } | null>(null);
  const point = (event: PointerEvent, element: HTMLElement) => {
    const box = element.getBoundingClientRect();
    const x = Math.round(((event.clientX - box.left) / box.width) * page.width);
    const y = Math.round(((event.clientY - box.top) / box.height) * page.height);
    return { x: Math.min(page.width, Math.max(0, x)), y: Math.min(page.height, Math.max(0, y)) };
  };
  const handlers = {
    onPointerDown(event: PointerEvent) {
      const element = event.currentTarget as HTMLElement;
      element.setPointerCapture(event.pointerId);
      start.current = point(event, element);
      setRect(null);
      event.preventDefault();
    },
    onPointerMove(event: PointerEvent) {
      if (!start.current) return;
      const here = point(event, event.currentTarget as HTMLElement);
      const from = start.current;
      setRect({
        left: Math.min(from.x, here.x),
        top: Math.min(from.y, here.y),
        right: Math.max(from.x, here.x),
        bottom: Math.max(from.y, here.y),
      });
    },
    onPointerUp() {
      start.current = null;
    },
    onPointerCancel() {
      start.current = null;
    },
  };
  return { rect, setRect, handlers };
}

export function CropControls(props: {
  note: StoredNote;
  page: StoredPage;
  rect: Rect | null;
  onDone: () => void;
}) {
  const existing = hasCrop(props.note) ? (props.note.source_crop as Crop) : null;
  const [onQuestion, setOnQuestion] = useState(existing?.on_question ?? false);
  const [busy, setBusy] = useState(false);
  const valid = !!props.rect && props.rect.right - props.rect.left >= 2 && props.rect.bottom - props.rect.top >= 2;
  const save = async (crop: Crop | Record<string, never>) => {
    setBusy(true);
    try {
      await updateNote(props.note.id, props.note.version, {
        front: props.note.front,
        back: props.note.back,
        source_quote: props.note.source_quote,
        status: props.note.status,
        source_crop: crop,
      });
      notify(Object.keys(crop).length ? "Slide region attached." : "Slide region removed.");
      props.onDone();
    } catch (error) {
      reportError(error);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div class="stack" style={{ marginTop: "12px" }}>
      <p class="small muted">Drag over the slide to choose the part to show with this card.</p>
      <label class="check small">
        <input type="checkbox" checked={onQuestion} onChange={(event) => setOnQuestion(event.currentTarget.checked)} />
        <span>Show it on the question (otherwise with the answer)</span>
      </label>
      <div class="row">
        <button
          class="btn primary small"
          disabled={!valid || busy}
          onClick={() => valid && save({ page: props.page.number, ...props.rect!, on_question: onQuestion })}
        >
          Attach region
        </button>
        {existing && (
          <button class="btn small danger" disabled={busy} onClick={() => save({})}>
            Remove region
          </button>
        )}
        <button class="btn small ghost" disabled={busy} onClick={props.onDone}>
          Cancel
        </button>
      </div>
    </div>
  );
}
