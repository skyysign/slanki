// Derived Anki images, matching Pillow's output pixel for pixel
// (crops.py crop_png, occlusion.py occlusion_png, visual_cards.py visual_png).
import type { Raster } from "./png.ts";

export interface Rect {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

/** Pillow Image.convert("RGB"): drops alpha without blending; grey is replicated. */
export function toRgb(image: Raster): Raster {
  if (image.channels === 3) return { ...image, data: image.data.slice() };
  const { width, height, channels, data } = image;
  const out = new Uint8Array(width * height * 3);
  for (let i = 0, j = 0; i < data.length; i += channels, j += 3) {
    if (channels >= 3) {
      out[j] = data[i]!;
      out[j + 1] = data[i + 1]!;
      out[j + 2] = data[i + 2]!;
    } else {
      out[j] = out[j + 1] = out[j + 2] = data[i]!;
    }
  }
  return { width, height, channels: 3, data: out };
}

/** Pillow Image.crop(box) with exclusive right/bottom edges; keeps the mode. */
export function crop(image: Raster, rect: Rect): Raster {
  const width = rect.right - rect.left;
  const height = rect.bottom - rect.top;
  const { channels } = image;
  const out = new Uint8Array(width * height * channels);
  for (let y = 0; y < height; y++) {
    const source = ((rect.top + y) * image.width + rect.left) * channels;
    out.set(image.data.subarray(source, source + width * channels), y * width * channels);
  }
  return { width, height, channels, data: out };
}

function hexColor(color: string): [number, number, number] {
  const value = Number.parseInt(color.slice(1), 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

/** Fill [x0, x1) x [y0, y1) in an RGB raster, clipped to the image. */
function fill(image: Raster, x0: number, y0: number, x1: number, y1: number, color: string): void {
  const [r, g, b] = hexColor(color);
  const left = Math.max(0, x0);
  const top = Math.max(0, y0);
  const right = Math.min(image.width, x1);
  const bottom = Math.min(image.height, y1);
  for (let y = top; y < bottom; y++) {
    for (let x = left; x < right; x++) {
      const i = (y * image.width + x) * 3;
      image.data[i] = r;
      image.data[i + 1] = g;
      image.data[i + 2] = b;
    }
  }
}

export const MASK_COLOR = "#d9aa54";
export const ANSWER_OUTLINE = "#247c57";
export const COVER_COLOR = "#e5e8e2";

/** Hidden region (question) or 2px outline outside it (answer) on the full slide. */
export function occlusionImage(source: Raster, mask: Rect, answer: boolean): Raster {
  const image = toRgb(source);
  if (answer) {
    // Pillow rectangle((l-2, t-2, r+1, b+1), width=2): the ring hugs the region from outside.
    const { left: l, top: t, right: r, bottom: b } = mask;
    fill(image, l - 2, t - 2, r + 2, t, ANSWER_OUTLINE);
    fill(image, l - 2, b, r + 2, b + 2, ANSWER_OUTLINE);
    fill(image, l - 2, t, l, b, ANSWER_OUTLINE);
    fill(image, r, t, r + 2, b, ANSWER_OUTLINE);
  } else {
    fill(image, mask.left, mask.top, mask.right, mask.bottom, MASK_COLOR);
  }
  return image;
}

/** Graph/formula question: covers on the question only, then the optional crop. */
export function visualImage(source: Raster, frame: Rect | null, covers: readonly Rect[], answer: boolean): Raster {
  const image = toRgb(source);
  if (!answer) {
    for (const cover of covers) fill(image, cover.left, cover.top, cover.right, cover.bottom, COVER_COLOR);
  }
  return frame ? crop(image, frame) : image;
}
