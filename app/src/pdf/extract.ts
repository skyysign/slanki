// In-browser PDF processing with pdf.js: per-page text and a bounded PNG.
// Nothing leaves the device. Mirrors converter/services/pdf_worker.py limits.
import { WorkflowError } from "../core/errors.ts";
import { cpLength, pyStrip } from "../core/py.ts";
import type { ExtractedPage } from "../store/library.ts";

export const MAX_PDF_BYTES = 100 * 1024 * 1024;
export const MAX_PDF_PAGES = 100;
const PAGE_TIMEOUT_MS = 60_000;
export const NO_TEXT_WARNING =
  "No usable text found. This page needs manual cards; scans and diagrams are not interpreted.";

export interface ExtractProgress {
  page: number;
  pages: number;
}

type PdfJs = typeof import("pdfjs-dist");
let loading: Promise<PdfJs> | null = null;

async function pdfjs(): Promise<PdfJs> {
  loading ??= (async () => {
    const [library, worker] = await Promise.all([
      import("pdfjs-dist"),
      import("pdfjs-dist/build/pdf.worker.min.mjs?url"),
    ]);
    library.GlobalWorkerOptions.workerSrc = worker.default;
    return library;
  })();
  return loading;
}

function assetBase(): string {
  return new URL("pdfjs/", document.baseURI).href;
}

function withTimeout<T>(promise: Promise<T>, onTimeout: () => void): Promise<T> {
  let timer: ReturnType<typeof setTimeout>;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      onTimeout();
      reject(new WorkflowError("A page took too long to process. Split the PDF and try again."));
    }, PAGE_TIMEOUT_MS);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

interface PositionedText {
  str: string;
  x: number;
  y: number;
  width: number;
  size: number;
}

const Y_TOLERANCE = 3;

/**
 * Join pdf.js text items in visual reading order, like pdfplumber's
 * extract_text(): lines top to bottom by glyph top (3 pt tolerance), items
 * left to right, and a space wherever the gap between items shows one.
 */
export function joinTextItems(items: readonly unknown[]): string {
  const positioned: PositionedText[] = [];
  for (const item of items) {
    if (!item || typeof item !== "object" || !("str" in item)) continue;
    const { str, transform, width, height } = item as { str: string; transform?: number[]; width?: number; height?: number };
    if (!str.trim()) continue;
    const [a = 1, b = 0, , , x = 0, baseline = 0] = transform ?? [];
    const size = Math.hypot(a, b) || 10;
    // Group by the top of the glyphs (as pdfplumber does), so sub- and superscripts stay inline.
    positioned.push({ str, x, y: baseline + (height || size), width: width ?? 0, size });
  }
  positioned.sort((p, q) => q.y - p.y || p.x - q.x);
  const lines: PositionedText[][] = [];
  for (const item of positioned) {
    const line = lines.at(-1);
    if (line && Math.abs(line[0]!.y - item.y) <= Y_TOLERANCE) line.push(item);
    else lines.push([item]);
  }
  return lines
    .map((line) => {
      line.sort((p, q) => p.x - q.x);
      let text = "";
      let end = -Infinity;
      for (const item of line) {
        const gap = item.x - end;
        if (text && !/\s$/u.test(text) && !/^\s/u.test(item.str) && gap > Math.max(1, item.size * 0.1)) text += " ";
        text += item.str;
        end = Math.max(end, item.x + item.width);
      }
      return text.replace(/\s+$/u, "");
    })
    .join("\n")
    .trim();
}

export function isPdf(bytes: Uint8Array): boolean {
  const head = new TextDecoder("latin1").decode(bytes.subarray(0, 1024));
  return head.includes("%PDF-");
}

async function canvasPng(canvas: HTMLCanvasElement | OffscreenCanvas): Promise<Uint8Array> {
  const blob =
    "convertToBlob" in canvas
      ? await canvas.convertToBlob({ type: "image/png" })
      : await new Promise<Blob>((resolve, reject) =>
          canvas.toBlob((value) => (value ? resolve(value) : reject(new Error("PNG encoding failed"))), "image/png"),
        );
  return new Uint8Array(await blob.arrayBuffer());
}

function makeCanvas(width: number, height: number): HTMLCanvasElement | OffscreenCanvas {
  if (typeof OffscreenCanvas === "function") return new OffscreenCanvas(width, height);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  return canvas;
}

export async function extractPdf(
  bytes: Uint8Array,
  onProgress: (progress: ExtractProgress) => void = () => undefined,
): Promise<ExtractedPage[]> {
  if (bytes.length > MAX_PDF_BYTES) throw new WorkflowError("Choose a PDF smaller than 100 MB.");
  if (!isPdf(bytes)) throw new WorkflowError("This file is not a PDF. Export your slides as a PDF first.");
  const library = await pdfjs();
  const base = assetBase();
  const task = library.getDocument({
    data: bytes.slice(),
    cMapUrl: base + "cmaps/",
    cMapPacked: true,
    standardFontDataUrl: base + "standard_fonts/",
    wasmUrl: base + "wasm/",
    useSystemFonts: false,
  });
  let document_: Awaited<typeof task.promise>;
  try {
    document_ = await task.promise;
  } catch (error) {
    if ((error as { name?: string })?.name === "PasswordException") {
      throw new WorkflowError("This PDF is password-protected. Remove the password and try again.");
    }
    throw new WorkflowError("The PDF could not be processed. Check that it is a normal, unencrypted PDF.");
  }
  try {
    const count = document_.numPages;
    if (count < 1 || count > MAX_PDF_PAGES) {
      throw new WorkflowError(`Use a PDF containing between 1 and ${MAX_PDF_PAGES} pages.`);
    }
    const pages: ExtractedPage[] = [];
    for (let number = 1; number <= count; number++) {
      onProgress({ page: number, pages: count });
      const page = await document_.getPage(number);
      try {
        const content = await withTimeout(page.getTextContent(), () => undefined);
        const text = joinTextItems(content.items);
        if (cpLength(text) > 25000) {
          throw new WorkflowError(`Page ${number} contains too much text. Split this PDF into smaller pages.`);
        }
        const base = page.getViewport({ scale: 1 });
        if (!(base.width > 0 && base.width <= 15000 && base.height > 0 && base.height <= 15000)) {
          throw new WorkflowError(`Page ${number} has unsupported dimensions.`);
        }
        const scale = Math.min(1.7, 1500 / Math.max(base.width, base.height));
        const viewport = page.getViewport({ scale });
        const width = Math.min(1500, Math.max(1, Math.round(viewport.width)));
        const height = Math.min(1500, Math.max(1, Math.round(viewport.height)));
        const canvas = makeCanvas(width, height);
        const context = canvas.getContext("2d") as CanvasRenderingContext2D | null;
        if (!context) throw new WorkflowError("This browser cannot render PDF pages.");
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, width, height);
        const render = page.render({ canvas: canvas as HTMLCanvasElement, canvasContext: context, viewport });
        await withTimeout(render.promise, () => render.cancel());
        pages.push({
          number,
          text,
          width,
          height,
          warning: cpLength(pyStrip(text)) < 15 ? NO_TEXT_WARNING : "",
          png: await canvasPng(canvas),
        });
      } finally {
        page.cleanup();
      }
      // Let the interface update between pages.
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
    return pages;
  } finally {
    await task.destroy();
  }
}
