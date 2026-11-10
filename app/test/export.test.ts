import initSqlJs, { type SqlJsStatic } from "sql.js";
import { unzipSync } from "fflate";
import { beforeAll, describe, expect, it } from "vitest";
import { readBackup } from "../src/backup/backup.ts";
import { sha256Hex } from "../src/core/sha256.ts";
import { buildApkg, cardOrdinals, MODELS } from "../src/export/anki.ts";
import { exportInput } from "../src/export/fromRecords.ts";
import { crop, occlusionImage, visualImage } from "../src/export/images.ts";
import { decodePng, encodePng, type Raster } from "../src/export/png.ts";
import { golden, goldenBytes } from "./golden.ts";

let SQL: SqlJsStatic;
beforeAll(async () => {
  SQL = await initSqlJs();
});

const DERIVED = /\b(crop|occlusion|visual)_([0-9a-f]{32})_[0-9a-f]{16}\.png/g;
const mask = (value: string) => value.replace(DERIVED, (_m, kind, id) => `${kind}_${id}_<hash>.png`);

/** TypeScript twin of tools/genanki_ref.py dump_apkg + comparable(). */
function dump(apkg: Uint8Array) {
  const files = unzipSync(apkg);
  const media = JSON.parse(new TextDecoder().decode(files.media)) as Record<string, string>;
  const db = new SQL.Database(files["collection.anki2"]);
  try {
    const rows = (sql: string): any[] => {
      const result = db.exec(sql)[0];
      return result ? result.values.map((values) => Object.fromEntries(result.columns.map((c, i) => [c, values[i]]))) : [];
    };
    const col = rows("SELECT * FROM col")[0]!;
    for (const key of ["conf", "models", "decks", "dconf", "tags"]) col[key] = JSON.parse(col[key] as string);
    for (const model of Object.values(col.models as Record<string, any>)) model.mod = "<export time>";
    const guids = new Map<unknown, string>();
    const notes = rows("SELECT * FROM notes ORDER BY id").map((note) => {
      guids.set(note.id, note.guid as string);
      delete note.id;
      return { ...note, flds: mask(note.flds as string), sfld: mask(String(note.sfld)) };
    });
    const cards = rows("SELECT * FROM cards ORDER BY id").map((card) => {
      const { id: _id, nid, ...rest } = card;
      return { ...rest, note_guid: guids.get(nid) };
    });
    notes.sort((a, b) => String(a.guid).localeCompare(String(b.guid)));
    cards.sort((a, b) => String(a.note_guid).localeCompare(String(b.note_guid)) || Number(a.ord) - Number(b.ord));
    return {
      names: Object.keys(files).sort(),
      media: Object.entries(media).map(([index, name]) =>
        DERIVED.test(name) ? (DERIVED.lastIndex = 0, { index, name: mask(name) }) : { index, name, sha256: sha256Hex(files[index]!) },
      ),
      col,
      notes,
      cards,
      schema: rows("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name").map((row) => row.sql),
    };
  } finally {
    db.close();
  }
}

describe("PNG codec", () => {
  it("decodes the Pillow page images to the same pixels", () => {
    const pixels = golden("pixels.json");
    for (const [page, expected] of Object.entries(pixels.pages) as [string, any][]) {
      const image = decodePng(goldenBytes(`pages/${page}.png`));
      expect([image.width, image.height]).toEqual(expected.size);
      expect(image.channels).toBe(3);
      expect(sha256Hex(image.data)).toBe(expected.sha256);
    }
  });

  it("round-trips and encodes deterministically", () => {
    const image = decodePng(goldenBytes("pages/1.png"));
    const encoded = encodePng(image);
    expect(encodePng(decodePng(encoded))).toEqual(encoded);
    expect(sha256Hex(decodePng(encoded).data)).toBe(sha256Hex(image.data));
    const rgba: Raster = { width: 3, height: 2, channels: 4, data: new Uint8Array(24).map((_, i) => (i * 37) & 255) };
    expect(decodePng(encodePng(rgba))).toEqual(rgba);
  });
});

describe("derived images", () => {
  it("match Pillow pixel for pixel", () => {
    const pixels = golden("pixels.json");
    const pages = new Map<number, Raster>();
    const page = (n: number) => pages.get(n) ?? pages.set(n, decodePng(goldenBytes(`pages/${n}.png`))).get(n)!;
    expect(pixels.derived.length).toBeGreaterThanOrEqual(8);
    for (const item of pixels.derived) {
      const hasCrop = Object.keys(item.source_crop).length > 0;
      const image =
        item.kind === "crop"
          ? crop(page(item.page), item.source_crop)
          : item.kind === "occlusion"
            ? occlusionImage(page(item.page), item.occlusion, item.answer)
            : visualImage(page(item.page), hasCrop ? item.source_crop : null, item.visual_masks, item.answer);
      expect([image.width, image.height], item.name).toEqual(item.size);
      expect(image.channels, item.name).toBe({ RGB: 3, RGBA: 4, L: 1, LA: 2 }[item.mode as string]);
      expect(sha256Hex(image.data), item.name).toBe(item.sha256);
    }
  });
});

describe("Anki package", () => {
  it("reproduces genanki's note type definitions", () => {
    const tables = golden("apkg/tables.json");
    for (const [id, model] of Object.entries(tables.col.models) as [string, any][]) {
      const definition = Object.values(MODELS).find((m) => String(m.id) === id)!;
      expect(definition.name).toBe(model.name);
      expect(definition.req).toEqual(model.req);
      expect(definition.fields).toEqual(model.flds.map((f: any) => f.name));
    }
  });

  it("writes the same Anki tables as the Recalloom exporter", () => {
    const backup = readBackup(goldenBytes("backup-v12.zip"));
    const ours = buildApkg(SQL, exportInput(backup.manifest.lecture, backup.manifest.cards, backup.pages));
    const theirs = goldenBytes("apkg/golden.apkg");
    const a = dump(theirs);
    const b = dump(ours);
    expect(b.schema).toEqual(a.schema);
    expect(b.col).toEqual(a.col);
    expect(b.notes).toEqual(a.notes);
    expect(b.cards).toEqual(a.cards);
    expect(b.media).toEqual(a.media);
    expect(b.names).toEqual(a.names);
  });

  it("creates cards like genanki", () => {
    expect(cardOrdinals(MODELS.cloze, ["{{c2::a}} {{c1::b}} {{c2::c}}", "", "s"])).toEqual([0, 1]);
    expect(cardOrdinals(MODELS.reversed, ["Front", "Back", "s", ""])).toEqual([0, 1]);
    expect(cardOrdinals(MODELS.reversed, ["Front", "", "s", ""])).toEqual([0]);
    expect(cardOrdinals(MODELS.basic, ["", "Back", "s"])).toEqual([]);
    expect(cardOrdinals(MODELS.occlusion, ["", "<img>", "<img>", "", "s"])).toEqual([0]);
  });

  it("refuses an empty export", () => {
    const backup = readBackup(goldenBytes("backup-v12.zip"));
    const drafts = backup.manifest.cards.map((card) => ({ ...card, status: "draft" as const }));
    expect(() => buildApkg(SQL, exportInput(backup.manifest.lecture, drafts, backup.pages))).toThrow(
      "Accept at least one card before exporting.",
    );
  });
});
