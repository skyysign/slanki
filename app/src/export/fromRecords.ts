// Map stored note records (Recalloom/Slanki manifest shape) to export input.
import type { CardRecord, LectureRecord } from "../backup/manifest.ts";
import { WorkflowError } from "../core/errors.ts";
import type { ExportInput, ExportNote, SourceCrop } from "./anki.ts";
import type { Rect } from "./images.ts";

const present = (value: object) => Object.keys(value).length > 0;

export function exportNote(card: CardRecord): ExportNote {
  return {
    id: card.id,
    page: card.page,
    front: card.front,
    back: card.back,
    sourceQuote: card.source_quote,
    noteType: card.note_type,
    sourceCrop: present(card.source_crop) ? (card.source_crop as unknown as SourceCrop) : null,
    occlusion: present(card.occlusion) ? (card.occlusion as unknown as Rect) : null,
    visualMasks: card.visual_masks,
    ankiModified: card.anki_modified,
    createdAt: card.created_at,
  };
}

export function exportInput(
  lecture: Pick<LectureRecord, "id" | "title">,
  cards: readonly CardRecord[],
  pages: ReadonlyMap<number, Uint8Array>,
): ExportInput {
  return {
    lecture: { id: lecture.id, title: lecture.title },
    notes: cards.filter((card) => card.status === "accepted").map(exportNote),
    pageImage: (number) => {
      const image = pages.get(number);
      if (!image) {
        throw new WorkflowError(`Source image for page ${number} is missing. Restore a backup before exporting.`);
      }
      return image;
    },
  };
}
