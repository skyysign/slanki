// Anki package writer reproducing genanki 0.13.1 and Recalloom's exporter
// (exporting.py), so re-exports update the same notes and keep schedules.
import type { BindParams, Database, SqlJsStatic } from "sql.js";
import { WorkflowError } from "../core/errors.ts";
import { deckId, guidFor, uuidHex } from "../core/ids.ts";
import { studyCardCount, textHtml, type NoteType } from "../core/noteTypes.ts";
import { dumps } from "../core/pyjson.ts";
import { sha256Hex } from "../core/sha256.ts";
import { timeKey } from "../core/time.ts";
import { zipEntries } from "../core/zip.ts";
import { APKG_COL, APKG_SCHEMA } from "./genankiSql.ts";
import { crop, occlusionImage, visualImage, type Rect } from "./images.ts";
import { decodePng, encodePng, type Raster } from "./png.ts";

export const CSS = `.card { font-family: Arial, sans-serif; font-size: 22px; text-align: left;
color: #20342e; background: #fafbf7; padding: 24px; line-height: 1.5; }
.nightMode.card { color: #e7eee8; background: #202825; }
.source { font-size: 14px; opacity: .85; margin-top: 24px; }
.source img, .source-crop { max-width: 100%; height: auto; margin-top: 12px; }
hr { border: 0; border-top: 1px solid #aebdb2; margin: 20px 0; }
.cloze { font-weight: bold; color: #235945; }
.nightMode .cloze { color: #9bcfb5; }`;

const LATEX_PRE =
  "\\documentclass[12pt]{article}\n\\special{papersize=3in,5in}\n\\usepackage[utf8]{inputenc}\n" +
  "\\usepackage{amssymb,amsmath}\n\\pagestyle{empty}\n\\setlength{\\parindent}{0in}\n" +
  "\\begin{document}\n";
const LATEX_POST = "\\end{document}";

type Requirement = [number, "all" | "any", number[]];

interface ModelDefinition {
  id: number;
  name: string;
  type: 0 | 1;
  fields: string[];
  templates: { name: string; qfmt: string; afmt: string }[];
  /** genanki Model._req, computed by chevron for these exact templates. */
  req: Requirement[];
}

const ANSWER = '<hr id="answer">';
const SOURCE = '<div class="source">{{Source}}</div>';

// Names and IDs are frozen: existing Anki collections match note types by them.
export const MODELS: Record<NoteType, ModelDefinition> = {
  basic: {
    id: 1890487183,
    name: "Slides to Anki — Basic v1",
    type: 0,
    fields: ["Question", "Answer", "Source"],
    templates: [{ name: "Card", qfmt: "{{Question}}", afmt: `{{FrontSide}}${ANSWER}{{Answer}}${SOURCE}` }],
    req: [[0, "all", [0]]],
  },
  cloze: {
    id: 1890487184,
    name: "Recalloom — Cloze v1",
    type: 1,
    fields: ["Text", "Extra", "Source"],
    templates: [{ name: "Cloze", qfmt: "{{cloze:Text}}", afmt: `{{cloze:Text}}${ANSWER}{{Extra}}${SOURCE}` }],
    req: [[0, "all", [0, 1, 2]]],
  },
  reversed: {
    id: 1890487185,
    name: "Recalloom — Basic + reverse v1",
    type: 0,
    fields: ["Front", "Back", "Source", "QuestionImage"],
    templates: [
      { name: "Front → back", qfmt: "{{Front}}{{QuestionImage}}", afmt: `{{FrontSide}}${ANSWER}{{Back}}${SOURCE}` },
      { name: "Back → front", qfmt: "{{Back}}{{QuestionImage}}", afmt: `{{FrontSide}}${ANSWER}{{Front}}${SOURCE}` },
    ],
    req: [
      [0, "any", [0, 3]],
      [1, "any", [1, 3]],
    ],
  },
  occlusion: {
    id: 1890487186,
    name: "Recalloom — Image occlusion v1",
    type: 0,
    fields: ["Prompt", "Hidden", "Revealed", "Extra", "Source"],
    templates: [
      {
        name: "Hidden region",
        qfmt: "{{Prompt}}<br>{{Hidden}}",
        afmt: `{{Prompt}}<br>{{Revealed}}${ANSWER}{{Extra}}${SOURCE}`,
      },
    ],
    req: [[0, "any", [0, 1]]],
  },
  visual: {
    id: 1890487187,
    name: "Recalloom - Graph and formula v1",
    type: 0,
    fields: ["Question", "Answer", "Hidden", "Revealed", "Source"],
    templates: [
      {
        name: "Interpret the figure",
        qfmt: "{{Question}}<br>{{Hidden}}",
        afmt: `{{Question}}<br>{{Revealed}}${ANSWER}{{Answer}}${SOURCE}`,
      },
    ],
    req: [[0, "any", [0, 2]]],
  },
};

/** genanki Model.to_json() with its exact key order. */
export function modelJson(model: ModelDefinition, deck: number, timestamp: number): object {
  return {
    css: CSS,
    did: deck,
    flds: model.fields.map((name, ord) => ({
      name,
      ord,
      font: "Liberation Sans",
      media: [],
      rtl: false,
      size: 20,
      sticky: false,
    })),
    id: String(model.id),
    latexPost: LATEX_POST,
    latexPre: LATEX_PRE,
    latexsvg: false,
    mod: Math.floor(timestamp),
    name: model.name,
    req: model.req,
    sortf: 0,
    tags: [],
    tmpls: model.templates.map((template, ord) => ({
      ...template,
      ord,
      bafmt: "",
      bqfmt: "",
      bfont: "",
      bsize: 0,
      did: null,
    })),
    type: model.type,
    usn: -1,
    vers: [],
  };
}

/** genanki Deck.to_json() */
function deckJson(id: number, name: string): object {
  return {
    collapsed: false,
    conf: 1,
    desc: "",
    dyn: 0,
    extendNew: 0,
    extendRev: 50,
    id,
    lrnToday: [163, 2],
    mod: 1425278051,
    name,
    newToday: [163, 2],
    revToday: [163, 0],
    timeToday: [163, 23598],
    usn: -1,
  };
}

/**
 * When the exported field layout last changed (Unix seconds). Notes exported
 * earlier carry an older `mod`, so Anki's "update if newer" import refreshes
 * them once with the new layout; card IDs and review schedules are unaffected.
 * 2026-11-10: the source block on the answer shows only the slide (no title,
 * page or excerpt text).
 */
export const EXPORT_LAYOUT_REVISION = 1794344946;

export interface SourceCrop extends Rect {
  page: number;
  on_question: boolean;
}

export interface ExportNote {
  id: string;
  page: number;
  front: string;
  back: string;
  sourceQuote: string;
  noteType: NoteType;
  sourceCrop: SourceCrop | null;
  occlusion: Rect | null;
  visualMasks: readonly Rect[];
  ankiModified: number;
  createdAt: string;
}

export interface ExportInput {
  lecture: { id: string; title: string };
  /** Accepted notes only. */
  notes: readonly ExportNote[];
  /** Stored PNG bytes of a source page. */
  pageImage: (page: number) => Uint8Array;
}

interface BuiltNote {
  model: ModelDefinition;
  fields: string[];
  guid: string;
  modified: number;
}

/** Note fields and media exactly as exporting.py assembles them. */
export function buildNotes(input: ExportInput): { notes: BuiltNote[]; media: Map<string, Uint8Array> } {
  const ordered = [...input.notes].sort(
    (a, b) => a.page - b.page || timeKey(a.createdAt) - timeKey(b.createdAt),
  );
  if (!ordered.length) throw new WorkflowError("Accept at least one card before exporting.");
  const lectureHex = uuidHex(input.lecture.id);
  const media = new Map<string, Uint8Array>();
  const decoded = new Map<number, Raster>();
  const raster = (page: number) => {
    if (!decoded.has(page)) decoded.set(page, decodePng(input.pageImage(page)));
    return decoded.get(page)!;
  };
  const derived = (prefix: string, noteHex: string, image: Raster) => {
    const png = encodePng(image);
    const name = `${prefix}_${noteHex}_${sha256Hex(png).slice(0, 16)}.png`;
    media.set(name, png);
    return name;
  };
  const notes = ordered.map((note): BuiltNote => {
    studyCardCount(note.front, note.noteType);
    let slide: Uint8Array;
    try {
      slide = input.pageImage(note.page);
    } catch {
      throw new WorkflowError(
        `Source image for page ${note.page} is missing. Restore a backup before exporting.`,
      );
    }
    const noteHex = uuidHex(note.id);
    const filename = `slides_${lectureHex}_${note.page}.png`;
    media.set(filename, slide);
    // The answer shows the slide itself; title, page and excerpt text would only repeat it.
    let source = "";
    let front = textHtml(note.front);
    let questionImage = "";
    if (note.sourceCrop && note.noteType !== "visual") {
      const name = derived("crop", noteHex, crop(raster(note.page), note.sourceCrop));
      const cropHtml = `<br><img class="source-crop" src="${name}">`;
      if (note.sourceCrop.on_question) {
        if (note.noteType === "reversed") questionImage = cropHtml;
        else front += cropHtml;
      } else {
        source += `<img class="source-crop" src="${name}"><br>`;
      }
    }
    source += `<img src="${filename}">`;
    let fields = [front, textHtml(note.back), source];
    if (note.noteType === "reversed") {
      fields.push(questionImage);
    } else if (note.noteType === "visual") {
      const images = [false, true].map((answer) => {
        const name = derived("visual", noteHex, visualImage(raster(note.page), note.sourceCrop, note.visualMasks, answer));
        return `<img class="source-crop" src="${name}">`;
      });
      fields = [front, textHtml(note.back), ...images, source];
    } else if (note.noteType === "occlusion") {
      if (!note.occlusion) throw new WorkflowError("Draw a region to hide on this note's source slide.");
      const images = [false, true].map((answer) => {
        const name = derived("occlusion", noteHex, occlusionImage(raster(note.page), note.occlusion!, answer));
        return `<img class="source-crop" src="${name}">`;
      });
      fields = [front, ...images, textHtml(note.back), source];
    }
    return {
      model: MODELS[note.noteType],
      fields,
      guid: guidFor(note.id),
      modified: Math.max(note.ankiModified, EXPORT_LAYOUT_REVISION),
    };
  });
  return { notes, media };
}

/** genanki Note.cards: ordinals for one note. */
export function cardOrdinals(model: ModelDefinition, fields: readonly string[]): number[] {
  if (model.type === 1) {
    const ords = new Set<number>();
    for (const match of fields[0]!.matchAll(/\{\{c(\d+)::[\s\S]+?\}\}/g)) {
      const number = Number.parseInt(match[1]!, 10);
      if (number > 0) ords.add(number - 1);
    }
    return [...ords].sort((a, b) => a - b);
  }
  return model.req
    .filter(([, mode, required]) =>
      mode === "all" ? required.every((i) => fields[i] !== "") : required.some((i) => fields[i] !== ""),
    )
    .map(([ord]) => ord);
}

function firstValue(db: Database, sql: string): string {
  return db.exec(sql)[0]!.values[0]![0] as string;
}

/** Write genanki's collection.anki2 for these notes. */
export function writeCollection(
  SQL: SqlJsStatic,
  lecture: { id: string; title: string },
  notes: readonly BuiltNote[],
  timestamp: number,
): Uint8Array {
  const deck = deckId(lecture.id);
  const db = new SQL.Database();
  try {
    db.exec(APKG_SCHEMA);
    db.exec(APKG_COL);
    const decks = new Map(Object.entries(JSON.parse(firstValue(db, "SELECT decks FROM col")) as object));
    decks.set(String(deck), deckJson(deck, lecture.title.replaceAll("::", " — ")));
    db.run("UPDATE col SET decks = ?", [dumps(decks)]);
    const models = new Map(Object.entries(JSON.parse(firstValue(db, "SELECT models from col")) as object));
    for (const note of notes) {
      if (!models.has(String(note.model.id))) models.set(String(note.model.id), modelJson(note.model, deck, timestamp));
    }
    db.run("UPDATE col SET models = ?", [dumps(models)]);
    let nextId = BigInt(Math.floor(timestamp * 1000));
    const insertNote = db.prepare("INSERT INTO notes VALUES(?,?,?,?,?,?,?,?,?,?,?);");
    const insertCard = db.prepare("INSERT INTO cards VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);");
    try {
      for (const note of notes) {
        const noteId = nextId++;
        const modified = BigInt(Math.floor(note.modified));
        // sql.js binds BigInt as 64-bit integers; its typings predate that support.
        const row = [noteId, note.guid, BigInt(note.model.id), modified, -1, "  ", note.fields.join("\x1f"), note.fields[0]!, 0, 0, ""];
        insertNote.run(row as unknown as BindParams);
        for (const ord of cardOrdinals(note.model, note.fields)) {
          insertCard.run([nextId++, noteId, BigInt(deck), ord, modified, -1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, ""] as unknown as BindParams);
        }
      }
    } finally {
      insertNote.free();
      insertCard.free();
    }
    return db.export();
  } finally {
    db.close();
  }
}

export function buildApkg(SQL: SqlJsStatic, input: ExportInput, timestamp = Date.now() / 1000): Uint8Array {
  const { notes, media } = buildNotes(input);
  const collection = writeCollection(SQL, input.lecture, notes, timestamp);
  const names = [...media.keys()];
  return zipEntries([
    ["collection.anki2", collection],
    ["media", new TextEncoder().encode(dumps(Object.fromEntries(names.map((name, i) => [String(i), name]))))],
    ...names.map((name, i): [string, Uint8Array] => [String(i), media.get(name)!]),
  ]);
}
