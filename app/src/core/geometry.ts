// Rectangle checks for crops, occlusion masks and visual covers (crops.py,
// occlusion.py, visual_cards.py). Coordinates are whole source pixels with
// exclusive right/bottom edges.
import { WorkflowError } from "./errors.ts";
import { hasExactKeys, isInt, isPlainObject } from "./py.ts";

export interface PageSize {
  number: number;
  width: number;
  height: number;
}

export interface Crop {
  page: number;
  left: number;
  top: number;
  right: number;
  bottom: number;
  on_question: boolean;
}

export interface Mask {
  page: number;
  left: number;
  top: number;
  right: number;
  bottom: number;
}

const isEmptyObject = (value: unknown) => isPlainObject(value) && Object.keys(value).length === 0;

export function checkedCrop(value: unknown, page: PageSize): Crop | Record<string, never> {
  if (isEmptyObject(value)) return {};
  const keys = ["page", "left", "top", "right", "bottom", "on_question"];
  if (!hasExactKeys(value, keys)) {
    throw new WorkflowError("Choose a rectangular crop from this note's source page.");
  }
  if (["page", "left", "top", "right", "bottom"].some((key) => !isInt(value[key])) || typeof value.on_question !== "boolean") {
    throw new WorkflowError("Crop coordinates must be whole pixels.");
  }
  const crop = value as unknown as Crop;
  if (
    crop.page !== page.number ||
    !(
      crop.left >= 0 &&
      crop.left < crop.right &&
      crop.right <= page.width &&
      crop.top >= 0 &&
      crop.top < crop.bottom &&
      crop.bottom <= page.height &&
      crop.right - crop.left >= 2 &&
      crop.bottom - crop.top >= 2
    )
  ) {
    throw new WorkflowError("Keep the crop inside this note's source slide and at least 2 pixels wide and high.");
  }
  return { ...crop };
}

export function checkedOcclusion(
  value: unknown,
  page: PageSize,
  noteType = "occlusion",
  sourceCrop: unknown = null,
): Mask | Record<string, never> {
  if (noteType !== "occlusion") {
    if (!isEmptyObject(value)) throw new WorkflowError("Only image occlusion notes can have a hidden region.");
    return {};
  }
  if (isPlainObject(sourceCrop) && Object.keys(sourceCrop).length) {
    throw new WorkflowError("An image occlusion note uses its full source slide, without a crop.");
  }
  if (!hasExactKeys(value, ["page", "left", "top", "right", "bottom"])) {
    throw new WorkflowError("Draw a region to hide on this note's source slide.");
  }
  const rectangle = checkedCrop({ ...value, on_question: false }, page) as Partial<Crop>;
  delete rectangle.on_question;
  return rectangle as Mask;
}

export function checkedVisualMasks(value: unknown, page: PageSize, noteType = "visual"): Mask[] {
  if (noteType !== "visual") {
    if (!(Array.isArray(value) && value.length === 0)) {
      throw new WorkflowError("Only graph/formula questions can have text covers.");
    }
    return [];
  }
  if (!Array.isArray(value) || value.length > 20) {
    throw new WorkflowError("Use at most 20 text covers on a visual question.");
  }
  return value.map((mask) => checkedOcclusion(mask, page) as Mask);
}
