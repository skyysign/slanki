import { describe, expect, it } from "vitest";
import { fingerprint, validateContent, validateGeneratedBatch, type Draft } from "../src/core/cards.ts";
import { deckId, guidFor, uuidHex } from "../src/core/ids.ts";
import { clozeMatches, plainFront, plainQuestions, studyCardCount, studyPreviews, textHtml } from "../src/core/noteTypes.ts";
import {
  OVERVIEW_SCHEMA,
  contextDownload,
  contextInstructions,
  contextSections,
  overviewPrompt,
  overviewSources,
  resolveOverview,
  validateTopics,
} from "../src/core/overview.ts";
import { SCHEMA, generationRequest, promptFor } from "../src/core/prompts.ts";
import { casefold, cpLength, normalized, pySplit, pyStrip } from "../src/core/py.ts";
import { dumps } from "../src/core/pyjson.ts";
import { PY_UNICODE_VERSION, SPACE_CODES } from "../src/core/pyunicode.ts";
import { checkedCardLimit, defaultCardLimit, filterGeneratedLogistics, isCourseLogistics } from "../src/core/selection.ts";
import { golden, outcome } from "./golden.ts";

const unicode = golden("unicode.json");
const text = golden("text.json");
const prompts = golden("prompts.json");
const short = (value: unknown) => JSON.stringify(value).slice(0, 50);

describe("Python text semantics", () => {
  it("uses the frozen Unicode tables", () => {
    expect(PY_UNICODE_VERSION).toBe(unicode.unidata_version);
    expect([...SPACE_CODES]).toEqual(unicode.space);
  });

  for (const row of text.strings as any[]) {
    it(`normalizes ${short(row.text)} like Python`, () => {
      expect(normalized(row.text)).toBe(row.normalized);
      expect(casefold(normalized(row.text))).toBe(row.casefold);
      expect(fingerprint(row.text)).toBe(row.fingerprint);
      expect(pySplit(row.text)).toEqual(row.split);
      expect(pyStrip(row.text)).toBe(row.strip);
      expect(textHtml(row.text)).toBe(row.text_html);
      expect(cpLength(row.text)).toBe(row.length);
    });
  }

  it("casefolds every code point like Python", () => {
    for (const [cp, folded] of unicode.casefold as [number, string][]) {
      expect(casefold(String.fromCodePoint(cp))).toBe(folded);
    }
  });
});

describe("Anki identities", () => {
  for (const row of text.identity as any[]) {
    it(`derives GUID and deck ID for ${row.uuid}`, () => {
      expect(guidFor(row.uuid)).toBe(row.guid);
      expect(deckId(row.uuid)).toBe(row.deck_id);
      expect(uuidHex(row.uuid)).toBe(row.hex);
    });
  }
});

describe("note types", () => {
  for (const row of text.cloze as any[]) {
    it(`parses cloze ${short(row.front)}`, () => {
      const front: string = row.front;
      if (row.matches_error) {
        expect(() => clozeMatches(front)).toThrow(row.matches_error);
      } else {
        const matches = clozeMatches(front).map((m) => ({
          number: m.number,
          body: m.body,
          start: cpLength(front.slice(0, m.index)),
          end: cpLength(front.slice(0, m.end)),
        }));
        expect(matches).toEqual(row.matches);
      }
      expect(outcome(() => studyCardCount(front, "cloze"))).toEqual(row.count);
      expect(plainFront(front, "cloze")).toBe(row.plain_front);
      expect(fingerprint(front, "cloze")).toBe(row.fingerprint);
      expect(outcome(() => studyPreviews(front, "Extra & <b>back</b>\nline", "cloze"))).toEqual(row.previews);
      expect(outcome(() => studyPreviews(front, "", "cloze"))).toEqual(row.previews_no_back);
    });
  }

  for (const row of text.note_types as any[]) {
    it(`counts and previews ${row.note_type}`, () => {
      expect(outcome(() => studyCardCount(row.front, row.note_type))).toEqual(row.count);
      if (row.plain_questions) expect(plainQuestions(row.front, row.back, row.note_type)).toEqual(row.plain_questions);
      expect(outcome(() => studyPreviews(row.front, row.back, row.note_type))).toEqual(row.previews);
    });
  }
});

describe("content validation", () => {
  for (const [index, row] of (text.validate_content as any[]).entries()) {
    it(`validates content case ${index}`, () => {
      const result = outcome(() =>
        validateContent(row.front, row.back, row.quote, { number: row.page_number, text: row.page_text }, {
          requireQuote: row.require_quote,
          noteType: row.note_type,
        }),
      );
      expect(result).toEqual(row.result);
    });
  }

  it("checks card limits", () => {
    for (const row of text.card_limits) {
      expect(outcome(() => checkedCardLimit(row.value, row.page_count, { cardFormat: row.card_format })), JSON.stringify(row)).toEqual(row.result);
    }
    for (const [count, expected] of Object.entries(text.default_card_limit)) {
      expect(defaultCardLimit(Number(count))).toBe(expected);
    }
  });

  it("recognizes course logistics", () => {
    for (const row of text.logistics) {
      expect(isCourseLogistics(row.front, row.quote), row.front).toBe(row.result);
    }
  });

  it("filters generated logistics", () => {
    for (const row of text.filter_generated_logistics) {
      expect(outcome(() => filterGeneratedLogistics(row.payload))).toEqual(row.result);
    }
  });

  it("validates generated batches item by item", () => {
    const data = golden("batches.json");
    const pages = new Map(Object.entries(data.pages).map(([n, t]) => [Number(n), { number: Number(n), text: t as string }]));
    for (const row of data.cases) {
      const result = outcome(() => {
        const { validated, issues } = validateGeneratedBatch(row.payload, pages, row.card_format);
        return {
          validated: validated.map((d: Draft) => ({
            page: d.page,
            front: d.front,
            back: d.back,
            source_quote: d.sourceQuote,
            note_type: d.noteType,
          })),
          issues,
        };
      });
      expect(result, row.card_format).toEqual(row.result);
    }
  });
});

describe("prompts and overview", () => {
  const pages = prompts.pages as { number: number; text: string; warning: string }[];
  const byNumber = new Map(pages.map((p) => [p.number, p]));

  it("serializes schemas exactly", () => {
    expect(SCHEMA).toEqual(prompts.schemas.cards);
    expect(OVERVIEW_SCHEMA).toEqual(prompts.schemas.overview);
    expect(dumps(SCHEMA)).toBe(prompts.schemas.cards_json);
    expect(dumps(OVERVIEW_SCHEMA)).toBe(prompts.schemas.overview_json);
  });

  for (const [index, row] of (prompts.prompt_for as any[]).entries()) {
    it(`builds card prompt ${index} (${row.card_format})`, () => {
      const result = outcome(() =>
        promptFor(row.pages.map((n: number) => byNumber.get(n)!), row.card_limit, row.existing_questions, {
          cardFormat: row.card_format,
          lectureContext: row.lecture_context,
        }),
      );
      expect(result).toEqual(row.result);
    });
  }

  it("builds generation requests", () => {
    for (const row of prompts.generation_request) {
      let selected = (row.pages ?? []).map((n: number) => byNumber.get(n)!);
      const options = { ...row.kwargs } as any;
      if (row.spec) {
        const [ch, count] = row.spec.page_text;
        selected = [{ number: 1, text: ch.repeat(count), warning: "" }];
        if (row.spec.sections_text) {
          const [s, n] = row.spec.sections_text;
          options.sections = [{ t: s.repeat(n) }];
        }
      }
      const result = outcome(() =>
        generationRequest(selected, row.args[0] ?? null, row.args[1] ?? [], {
          task: row.task,
          cardFormat: options.card_format,
          lectureContext: options.lecture_context ?? null,
          sections: options.sections ?? null,
          validationFeedback: options.validation_feedback ?? "",
        }),
      );
      expect(result, row.task).toEqual(row.result);
    }
  });

  it("partitions overview sections by code points", () => {
    for (const row of prompts.context_sections) {
      const testPages = row.lengths.map((size: number | string, i: number) =>
        size === "warn"
          ? { number: i + 1, text: "text", warning: "No usable text" }
          : { number: i + 1, text: ((i + 1) % 2 ? "𝑥" : "a").repeat(size as number), warning: "" },
      );
      expect(outcome(() => contextSections(testPages).map((s) => s.map((p) => p.number)))).toEqual(row.result);
    }
  });

  it("catalogues excerpts and builds overview prompts", () => {
    expect(outcome(() => overviewSources(pages))).toEqual(prompts.overview_sources.pages);
    expect(outcome(() => overviewSources([], prompts.sections))).toEqual(prompts.overview_sources.sections);
    expect(overviewPrompt(pages)).toBe(prompts.overview_prompt.section);
    expect(overviewPrompt([], "balanced", { sections: prompts.sections })).toBe(prompts.overview_prompt.merge);
  });

  it("resolves overview output strictly", () => {
    for (const row of prompts.resolve_overview) {
      expect(outcome(() => resolveOverview(row.payload, byNumber, { sections: row.sections })), short(row.payload)).toEqual(row.result);
    }
    expect(
      outcome(() => validateTopics({ topics: [{ ...prompts.topics[0], source_quote: "x".repeat(241) }] }, byNumber)),
    ).toEqual(prompts.validate_topics_long_quote);
  });

  it("adds overview instructions and context-only downloads", () => {
    expect(contextInstructions(null)).toBe(prompts.context_instructions.none);
    expect(contextInstructions(prompts.topics)).toBe(prompts.context_instructions.topics);
    expect(outcome(() => contextDownload(pages, new Set([1, 2]), "CARD PROMPT"))).toEqual(prompts.context_download);
    expect(
      outcome(() => contextDownload([{ number: 1, text: "x".repeat(200001), warning: "" }], new Set(), "CARD PROMPT")),
    ).toEqual(prompts.context_download_too_large);
  });
});
