// Minimal deterministic PNG codec for slide images. Pure TypeScript so derived
// Anki media (crops, masks, covers) has identical pixels in browsers and Node.
import { unzlibSync, zlibSync } from "fflate";
import { WorkflowError } from "../core/errors.ts";

/** 8-bit interleaved samples: 1 = L, 2 = LA, 3 = RGB, 4 = RGBA. */
export interface Raster {
  width: number;
  height: number;
  channels: 1 | 2 | 3 | 4;
  data: Uint8Array;
}

const SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10];
const MAX_PIXELS = 40_000_000;

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(bytes: Uint8Array, start = 0, end = bytes.length): number {
  let c = 0xffffffff;
  for (let i = start; i < end; i++) c = CRC_TABLE[(c ^ bytes[i]!) & 0xff]! ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function fail(): never {
  throw new WorkflowError("Could not read this source image. Restore a backup before exporting.");
}

function paeth(a: number, b: number, c: number): number {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
}

/** Read width/height without decoding pixel data. */
export function pngSize(bytes: Uint8Array): { width: number; height: number } {
  if (bytes.length < 24 || SIGNATURE.some((value, i) => bytes[i] !== value)) fail();
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (String.fromCharCode(...bytes.subarray(12, 16)) !== "IHDR") fail();
  return { width: view.getUint32(16), height: view.getUint32(20) };
}

export function decodePng(bytes: Uint8Array): Raster {
  if (bytes.length < 8 || SIGNATURE.some((value, i) => bytes[i] !== value)) fail();
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let offset = 8;
  let width = 0;
  let height = 0;
  let depth = 0;
  let colorType = 0;
  let palette: Uint8Array | null = null;
  let transparency: Uint8Array | null = null;
  const idat: Uint8Array[] = [];
  let sawEnd = false;
  while (offset + 12 <= bytes.length) {
    const length = view.getUint32(offset);
    const type = String.fromCharCode(...bytes.subarray(offset + 4, offset + 8));
    const dataStart = offset + 8;
    const dataEnd = dataStart + length;
    if (dataEnd + 4 > bytes.length) fail();
    if (crc32(bytes, offset + 4, dataEnd) !== view.getUint32(dataEnd)) fail();
    const chunk = bytes.subarray(dataStart, dataEnd);
    if (type === "IHDR") {
      if (length !== 13) fail();
      width = view.getUint32(dataStart);
      height = view.getUint32(dataStart + 4);
      depth = chunk[8]!;
      colorType = chunk[9]!;
      if (chunk[10] !== 0 || chunk[11] !== 0 || chunk[12] !== 0) fail(); // interlaced or unknown methods
    } else if (type === "PLTE") {
      palette = chunk;
    } else if (type === "tRNS") {
      transparency = chunk;
    } else if (type === "IDAT") {
      idat.push(chunk);
    } else if (type === "IEND") {
      sawEnd = true;
      break;
    }
    offset = dataEnd + 4;
  }
  if (!sawEnd || !width || !height || width * height > MAX_PIXELS || !idat.length) fail();
  const samples = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 }[colorType as 0 | 2 | 3 | 4 | 6];
  if (!samples || ![1, 2, 4, 8, 16].includes(depth)) fail();
  if ((colorType === 2 || colorType === 4 || colorType === 6) && depth < 8) fail();
  if (colorType === 3 && (depth === 16 || !palette)) fail();
  const joined = new Uint8Array(idat.reduce((sum, part) => sum + part.length, 0));
  let position = 0;
  for (const part of idat) {
    joined.set(part, position);
    position += part.length;
  }
  let raw: Uint8Array;
  try {
    raw = unzlibSync(joined);
  } catch {
    fail();
  }
  const bitsPerPixel = samples * depth;
  const rowBytes = Math.ceil((width * bitsPerPixel) / 8);
  const bpp = Math.max(1, bitsPerPixel >> 3);
  if (raw.length < height * (rowBytes + 1)) fail();
  const scan = new Uint8Array(height * rowBytes);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (rowBytes + 1)]!;
    const source = y * (rowBytes + 1) + 1;
    const target = y * rowBytes;
    for (let x = 0; x < rowBytes; x++) {
      const value = raw[source + x]!;
      const left = x >= bpp ? scan[target + x - bpp]! : 0;
      const up = y ? scan[target - rowBytes + x]! : 0;
      const upLeft = y && x >= bpp ? scan[target - rowBytes + x - bpp]! : 0;
      let out: number;
      if (filter === 0) out = value;
      else if (filter === 1) out = value + left;
      else if (filter === 2) out = value + up;
      else if (filter === 3) out = value + ((left + up) >> 1);
      else if (filter === 4) out = value + paeth(left, up, upLeft);
      else fail();
      scan[target + x] = out & 0xff;
    }
  }
  const sample = (row: number, index: number): number => {
    if (depth === 8) return scan[row * rowBytes + index]!;
    if (depth === 16) return scan[row * rowBytes + index * 2]!;
    const perByte = 8 / depth;
    const byte = scan[row * rowBytes + Math.floor(index / perByte)]!;
    const shift = 8 - depth * ((index % perByte) + 1);
    return (byte >> shift) & ((1 << depth) - 1);
  };
  if (colorType === 3) {
    const alpha = transparency !== null;
    const channels = alpha ? 4 : 3;
    const data = new Uint8Array(width * height * channels);
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const index = sample(y, x);
        const out = (y * width + x) * channels;
        if (index * 3 + 2 >= palette!.length) fail();
        data[out] = palette![index * 3]!;
        data[out + 1] = palette![index * 3 + 1]!;
        data[out + 2] = palette![index * 3 + 2]!;
        if (alpha) data[out + 3] = index < transparency!.length ? transparency![index]! : 255;
      }
    }
    return { width, height, channels: channels as 3 | 4, data };
  }
  const data = new Uint8Array(width * height * samples);
  const scale = depth < 8 ? 255 / ((1 << depth) - 1) : 1;
  for (let y = 0; y < height; y++) {
    for (let i = 0; i < width * samples; i++) {
      data[y * width * samples + i] = depth < 8 ? Math.round(sample(y, i) * scale) : sample(y, i);
    }
  }
  return { width, height, channels: samples as 1 | 2 | 3 | 4, data };
}

function chunk(type: string, data: Uint8Array): Uint8Array {
  const out = new Uint8Array(12 + data.length);
  const view = new DataView(out.buffer);
  view.setUint32(0, data.length);
  for (let i = 0; i < 4; i++) out[4 + i] = type.charCodeAt(i);
  out.set(data, 8);
  view.setUint32(8 + data.length, crc32(out, 4, 8 + data.length));
  return out;
}

/**
 * Encode RGB/RGBA/L/LA 8-bit pixels. Filters are chosen per row with the
 * minimum-sum-of-absolute-differences heuristic and zlib level 6, so equal
 * pixels always give equal bytes (and therefore stable media names).
 */
export function encodePng(image: Raster): Uint8Array {
  const { width, height, channels, data } = image;
  const colorType = { 1: 0, 2: 4, 3: 2, 4: 6 }[channels];
  const rowBytes = width * channels;
  const filtered = new Uint8Array(height * (rowBytes + 1));
  const candidate = new Uint8Array(rowBytes);
  const best = new Uint8Array(rowBytes);
  for (let y = 0; y < height; y++) {
    const row = y * rowBytes;
    let bestFilter = 0;
    let bestScore = Infinity;
    for (let filter = 0; filter <= 4; filter++) {
      let score = 0;
      for (let x = 0; x < rowBytes; x++) {
        const value = data[row + x]!;
        const left = x >= channels ? data[row + x - channels]! : 0;
        const up = y ? data[row - rowBytes + x]! : 0;
        const upLeft = y && x >= channels ? data[row - rowBytes + x - channels]! : 0;
        const predicted =
          filter === 0 ? 0 : filter === 1 ? left : filter === 2 ? up : filter === 3 ? (left + up) >> 1 : paeth(left, up, upLeft);
        const out = (value - predicted) & 0xff;
        candidate[x] = out;
        score += out < 128 ? out : 256 - out;
      }
      if (score < bestScore) {
        bestScore = score;
        bestFilter = filter;
        best.set(candidate);
      }
    }
    filtered[y * (rowBytes + 1)] = bestFilter;
    filtered.set(best, y * (rowBytes + 1) + 1);
  }
  const header = new Uint8Array(13);
  const view = new DataView(header.buffer);
  view.setUint32(0, width);
  view.setUint32(4, height);
  header[8] = 8;
  header[9] = colorType;
  const parts = [
    new Uint8Array(SIGNATURE),
    chunk("IHDR", header),
    chunk("IDAT", zlibSync(filtered, { level: 6 })),
    chunk("IEND", new Uint8Array(0)),
  ];
  const out = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let position = 0;
  for (const part of parts) {
    out.set(part, position);
    position += part.length;
  }
  return out;
}
