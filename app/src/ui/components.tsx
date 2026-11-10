// Shared interface building blocks.
import type { ComponentChildren } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { getImage } from "../store/library.ts";

const imageUrls = new Map<string, string>();

/** Object URL for a stored page image (cached for the session). */
export function useImageUrl(sha: string | undefined): string | undefined {
  const [url, setUrl] = useState(sha ? imageUrls.get(sha) : undefined);
  useEffect(() => {
    if (!sha) return;
    const cached = imageUrls.get(sha);
    if (cached) {
      setUrl(cached);
      return;
    }
    let live = true;
    void getImage(sha).then((bytes) => {
      if (!bytes || !live) return;
      const value = URL.createObjectURL(new Blob([bytes as BlobPart], { type: "image/png" }));
      imageUrls.set(sha, value);
      setUrl(value);
    });
    return () => {
      live = false;
    };
  }, [sha]);
  return url;
}

export function Dialog(props: {
  open: boolean;
  onClose: () => void;
  label: string;
  wide?: boolean;
  className?: string;
  children: ComponentChildren;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (props.open && !dialog.open) dialog.showModal();
    if (!props.open && dialog.open) dialog.close();
  }, [props.open]);
  return (
    <dialog
      ref={ref}
      class={[props.wide ? "wide" : "", props.className ?? ""].join(" ").trim()}
      aria-label={props.label}
      onCancel={(event) => {
        event.preventDefault();
        props.onClose();
      }}
      onClick={(event) => {
        if (event.target === ref.current) props.onClose();
      }}
    >
      {props.open && <div class="dialog-body">{props.children}</div>}
    </dialog>
  );
}

export function Menu(props: { label: string; children: (close: () => void) => ComponentChildren }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: Event) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
  return (
    <div class="menu" ref={ref}>
      <button class="btn icon" type="button" aria-label={props.label} aria-expanded={open} onClick={() => setOpen(!open)}>
        ···
      </button>
      {open && <div class="menu-list">{props.children(() => setOpen(false))}</div>}
    </div>
  );
}

/** Run an async action once at a time, exposing its busy state. */
export function useBusy(): [boolean, <T>(work: () => Promise<T>) => Promise<T | undefined>] {
  const [busy, setBusy] = useState(false);
  const running = useRef(false);
  const run = async <T,>(work: () => Promise<T>) => {
    if (running.current) return undefined;
    running.current = true;
    setBusy(true);
    try {
      return await work();
    } finally {
      running.current = false;
      setBusy(false);
    }
  };
  return [busy, run];
}

export function plural(count: number, one: string, many = one + "s"): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** Parse "1-3, 7" style page selections. */
export function parsePageList(text: string, max: number): number[] {
  const pages = new Set<number>();
  for (const part of text.split(",")) {
    const range = /^\s*(\d+)\s*(?:-\s*(\d+))?\s*$/.exec(part);
    if (!range) continue;
    const start = Number(range[1]);
    const end = Number(range[2] ?? range[1]);
    for (let n = Math.max(1, Math.min(start, end)); n <= Math.min(max, Math.max(start, end)); n++) pages.add(n);
  }
  return [...pages].sort((a, b) => a - b);
}
