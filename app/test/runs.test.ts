import { IDBFactory } from "fake-indexeddb";
import { beforeEach, describe, expect, it } from "vitest";
import { GenerationOutputError, WorkflowError } from "../src/core/errors.ts";
import { generationRequest } from "../src/core/prompts.ts";
import { sha256Hex } from "../src/core/sha256.ts";
import { performRun, resumeRun, type Generator } from "../src/run/orchestrator.ts";
import { newRun } from "../src/services/runs.ts";
import { request, resetDbConnection, transaction } from "../src/store/db.ts";
import { addLecture, getLecture, getRun, nowIso, putRun, type StoredNote } from "../src/store/library.ts";
import { golden } from "./golden.ts";

const NO_TEXT = "No usable text found on this page. Check the slide image.";

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  resetDbConnection();
});

async function lectureFor(name: string, scenario: any): Promise<string> {
  const pages = (scenario.texts as string[]).map((text, i) => ({
    number: i + 1,
    text,
    width: 1500,
    height: 844,
    warning: scenario.warnings.includes(i + 1) ? NO_TEXT : "",
    png: new TextEncoder().encode(`png-${name}-${i}`),
  }));
  const { id } = await addLecture(new TextEncoder().encode(`%PDF-${name}`), `${name}.pdf`, name, pages);
  // Notes that existed before the run, with their stored (possibly pre-edit) fingerprints.
  const prior = (scenario.notes as any[]).filter((note) => !note.from_run);
  await transaction(["notes"], "readwrite", async (tx) => {
    for (const note of prior) {
      const now = nowIso();
      const record: StoredNote = {
        id: crypto.randomUUID(),
        lecture_id: id,
        page: note.page,
        front: note.front,
        note_type: note.note_type,
        back: note.back,
        source_quote: note.source_quote,
        source_crop: {},
        occlusion: {},
        visual_masks: [],
        status: note.status,
        fingerprint: note.fingerprint,
        version: 1,
        anki_modified: 1,
        run: null,
        created_at: now,
        updated_at: now,
      };
      await request(tx.objectStore("notes").add(record));
    }
  });
  return id;
}

function replay(scenario: any, pagesById: Map<number, { number: number; text: string }>): Generator {
  let index = 0;
  return async (call) => {
    const expected = scenario.calls[index++];
    expect(expected, `unexpected extra call ${index}`).toBeDefined();
    expect(call.task).toBe(expected.task);
    expect(call.pages.map((p) => p.number)).toEqual(expected.pages);
    expect(call.cardLimit ?? null).toEqual(expected.card_limit);
    expect([...call.existingQuestions]).toEqual(expected.existing_questions);
    expect(call.lectureContext ?? null).toEqual(expected.lecture_context);
    expect(call.sections ?? null).toEqual(expected.sections);
    expect(call.validationFeedback).toBe(expected.validation_feedback);
    const [prompt] = generationRequest(
      call.pages.map((p) => pagesById.get(p.number)!),
      call.cardLimit,
      call.existingQuestions,
      {
        task: call.task,
        cardFormat: call.cardFormat,
        lectureContext: call.lectureContext,
        sections: call.sections,
        validationFeedback: call.validationFeedback,
      },
    );
    expect(prompt).toBe(expected.prompt.ok);
    if (expected.raises) {
      throw expected.raises.type === "GenerationOutputError"
        ? new GenerationOutputError(expected.raises.message)
        : new WorkflowError(expected.raises.message);
    }
    return expected.response;
  };
}

const STATE_KEYS = [
  "status",
  "page_numbers",
  "completed_pages",
  "cards_added",
  "study_cards_added",
  "filtered_count",
  "over_limit_count",
  "issues",
  "error",
  "context_enabled",
  "context_data",
  "card_limit",
  "card_format",
] as const;

describe("generation runs replay the Recalloom transcripts", () => {
  const scenarios = golden("runs.json") as Record<string, any>;
  for (const [name, scenario] of Object.entries(scenarios)) {
    it(name, async () => {
      const lectureId = await lectureFor(name, scenario);
      const bundle = (await getLecture(lectureId))!;
      const sha = bundle.lecture.sha256;
      expect(sha).toBe(sha256Hex(new TextEncoder().encode(`%PDF-${name}`)));
      // Context data embeds the document identity; compare it against this lecture's.
      const expectedStates = scenario.states.map((state: any) => ({
        ...state,
        context_data: state.context_data?.source_sha256 ? { ...state.context_data, source_sha256: sha } : state.context_data,
      }));
      const run = newRun(lectureId, {
        status: "queued",
        provider: "codex",
        model: scenario.run.model ?? "",
        page_numbers: scenario.run.page_numbers,
        card_limit: scenario.run.card_limit,
        card_format: scenario.run.card_format,
        context_enabled: scenario.run.context_enabled ?? false,
        reasoning_effort: scenario.run.reasoning_effort ?? "",
      });
      await putRun(run);
      const generate = replay(scenario, new Map(bundle.pages.map((p) => [p.number, p])));
      for (let attempt = 0; attempt < expectedStates.length; attempt++) {
        if (attempt) await resumeRun(run.id);
        await performRun(run.id, generate, new AbortController());
        const stored = (await getRun(run.id))!;
        const actual = Object.fromEntries(STATE_KEYS.map((key) => [key, stored[key]]));
        expect(actual).toEqual(expectedStates[attempt]);
      }
      const notes = (await getLecture(lectureId))!.notes
        .sort((a, b) => a.created_at.localeCompare(b.created_at))
        .map((note) => ({
          front: note.front,
          back: note.back,
          page: note.page,
          note_type: note.note_type,
          source_quote: note.source_quote,
          fingerprint: note.fingerprint,
          status: note.status,
          from_run: note.run === run.id,
        }));
      expect(notes).toEqual(scenario.notes);
    });
  }
});
