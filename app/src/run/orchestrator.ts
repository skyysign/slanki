// Generation runs in the browser (port of generation.py perform_run,
// prepare_lecture_context and generate_validated for text cards).
import { Cancelled } from "../ai/helper.ts";
import { validateGeneratedBatch, type PageText } from "../core/cards.ts";
import { GenerationOutputError, WorkflowError } from "../core/errors.ts";
import { studyCardCount, type CardFormat } from "../core/noteTypes.ts";
import {
  checkedContext,
  contextSections,
  newContext,
  resolveOverview,
  type ContextPage,
  type LectureContext,
  type Section,
  type Topic,
} from "../core/overview.ts";
import { batches, batchLimit, batchSize, minimumCards } from "../core/plan.ts";
import { filterGeneratedLogistics, recentQuestions, selectDrafts } from "../core/selection.ts";
import { compareNewest } from "../core/time.ts";
import { request, store, transaction } from "../store/db.ts";
import {
  getLecture,
  getRun,
  insertDrafts,
  notifyChanged,
  nowIso,
  onLibraryChange,
  type StoredNote,
  type StoredPage,
  type StoredRun,
} from "../store/library.ts";

export interface GenerationCall {
  task: "cards" | "overview";
  pages: readonly PageText[];
  cardLimit: number | null;
  existingQuestions: readonly string[];
  lectureContext: readonly Topic[] | null;
  sections: readonly Section[] | null;
  validationFeedback: string;
  cardFormat: CardFormat | string;
  learningFocus: string;
}

/** Runs one model request; `key` is stable for the same request so retries can reattach. */
export type Generator = (call: GenerationCall, key: string, signal: AbortSignal) => Promise<unknown>;

const LIMITED =
  "The remaining card budget cannot fit another note. Some selected pages were not processed.";
const UNEXPECTED = "Generation stopped unexpectedly. Completed drafts are saved. Retry the remaining pages.";

async function patchRun(runId: string, changes: Partial<StoredRun>, requireRunning = true): Promise<StoredRun> {
  const updated = await transaction(["runs"], "readwrite", async (tx) => {
    const run = (await request(store(tx, "runs").get(runId))) as StoredRun | undefined;
    if (!run || (requireRunning && run.status !== "running")) throw new Cancelled();
    const next = { ...run, ...changes, updated_at: nowIso() };
    store(tx, "runs").put(next);
    return next;
  });
  notifyChanged(updated.lecture_id);
  return updated;
}

const existingNotes = (notes: readonly StoredNote[]) =>
  notes.map((note) => ({ fingerprint: note.fingerprint, front: note.front, back: note.back, noteType: note.note_type }));

const questionsFrom = (notes: readonly StoredNote[]) =>
  recentQuestions([...notes].sort(compareNewest).map((note) => ({ front: note.front, back: note.back, noteType: note.note_type })));

/** Retry only invalid output, never account, quota, cancellation or transport failures. */
async function generateValidated<T>(
  run: StoredRun,
  call: Omit<GenerationCall, "validationFeedback" | "cardFormat" | "learningFocus">,
  validate: (payload: unknown) => T,
  generate: Generator,
  signal: AbortSignal,
  keyBase: string,
): Promise<T> {
  let feedback = "";
  for (let number = 1; number <= 3; number++) {
    if (signal.aborted) throw new Cancelled();
    try {
      const payload = await generate(
        { ...call, validationFeedback: feedback, cardFormat: run.card_format, learningFocus: run.learning_focus },
        `${keyBase}/try${number}`,
        signal,
      );
      if (signal.aborted) throw new Cancelled();
      let result: T;
      try {
        result = validate(payload);
      } catch (error) {
        if (error instanceof WorkflowError && !(error instanceof GenerationOutputError)) {
          throw new GenerationOutputError(error.message);
        }
        throw error;
      }
      await patchRun(run.id, { error: "" });
      return result;
    } catch (error) {
      if (!(error instanceof GenerationOutputError)) throw error;
      if (signal.aborted) throw new Cancelled();
      if (number === 3) {
        throw new WorkflowError(
          `Could not validate the lecture overview after 3 attempts. ${error.message} Completed sections and drafts are saved.`,
        );
      }
      feedback = error.message;
      await patchRun(run.id, {
        error: `Correcting the lecture overview automatically (attempt ${number + 1} of 3). Saved work is kept.`,
      });
    }
  }
  throw new WorkflowError(UNEXPECTED);
}

async function prepareContext(
  initial: StoredRun,
  sha256: string,
  pages: readonly StoredPage[],
  generate: Generator,
  signal: AbortSignal,
): Promise<Topic[]> {
  let run = initial;
  const contextPages: ContextPage[] = pages.map((page) => ({ number: page.number, text: page.text, warning: page.warning }));
  const sections = contextSections(contextPages);
  const saved = checkedContext(run.context_data, true, sha256, contextPages);
  const data: LectureContext = Object.keys(saved).length ? (saved as LectureContext) : newContext(sha256, contextPages);
  if (!sections.length) throw new WorkflowError("This lecture has no readable text for an overview.");
  const save = async () => {
    run = await patchRun(run.id, { context_data: data as unknown as Record<string, unknown> });
  };
  if (!Object.keys(run.context_data).length) await save();
  if (data.outline !== null) return data.outline;
  const done = new Set(data.sections.flatMap((section) => section.pages));
  for (const source of contextSections(contextPages.filter((page) => !done.has(page.number)))) {
    if (signal.aborted) throw new Cancelled();
    const sourceMap = new Map(source.map((page) => [page.number, page]));
    const topics = await generateValidated(
      run,
      { task: "overview", pages: source, cardLimit: null, existingQuestions: [], lectureContext: null, sections: null },
      (payload) => resolveOverview(payload, sourceMap),
      generate,
      signal,
      `${run.id}/overview/${source[0]!.number}-${source.at(-1)!.number}`,
    );
    data.sections.push({ pages: source.map((page) => page.number), topics });
    await save();
  }
  if (signal.aborted) throw new Cancelled();
  if (data.sections.length === 1) {
    data.outline = data.sections[0]!.topics;
  } else {
    const all = new Map(contextPages.map((page) => [page.number, page]));
    data.outline = await generateValidated(
      run,
      { task: "overview", pages: [], cardLimit: null, existingQuestions: [], lectureContext: null, sections: data.sections },
      (payload) => resolveOverview(payload, all, { sections: data.sections }),
      generate,
      signal,
      `${run.id}/overview/combine`,
    );
  }
  checkedContext(data, true, sha256, contextPages);
  await save();
  return data.outline;
}

/** Execute a queued run until it completes, stops, fails or is cancelled. */
export async function performRun(runId: string, generate: Generator, controller: AbortController): Promise<void> {
  const signal = controller.signal;
  const queued = await getRun(runId);
  if (!queued || queued.status !== "queued") return;
  let run = await patchRun(runId, { status: "running" }, false);
  // A stop requested in another tab changes the stored status; abort the in-flight request.
  const unsubscribe = onLibraryChange((lectureId) => {
    if (lectureId !== run.lecture_id) return;
    void getRun(runId).then((latest) => {
      if (latest && latest.status !== "running") controller.abort();
    });
  });
  try {
    const bundle = await getLecture(run.lecture_id);
    if (!bundle) throw new Cancelled();
    const selected = new Set(run.page_numbers);
    const pages = run.text_enabled
      ? bundle.pages.filter((page) => selected.has(page.number) && !run.completed_pages.includes(page.number))
      : [];
    const minimum = minimumCards(run.card_format);
    const size = batchSize(run.page_numbers.length, run.card_limit, run.card_format);
    const overview = run.context_enabled
      ? await prepareContext(run, bundle.lecture.sha256, bundle.pages, generate, signal)
      : null;
    run = (await getRun(runId))!;
    for (const batch of batches(pages, size)) {
      if (signal.aborted) throw new Cancelled();
      const limit =
        run.card_limit === null
          ? null
          : batchLimit(run.card_limit, run.completed_pages.length, batch.length, run.page_numbers.length, run.study_cards_added);
      if (limit !== null && limit < minimum) {
        await patchRun(runId, { status: "limited", error: LIMITED });
        return;
      }
      const notes = (await getLecture(run.lecture_id))?.notes ?? [];
      const payload = await generate(
        {
          task: "cards",
          pages: batch,
          cardLimit: limit,
          existingQuestions: run.card_limit !== null ? questionsFrom(notes) : [],
          lectureContext: run.context_enabled ? overview : null,
          sections: null,
          validationFeedback: "",
          cardFormat: run.card_format,
          learningFocus: run.learning_focus,
        },
        `${run.id}/cards/${batch[0]!.number}-${batch.at(-1)!.number}`,
        signal,
      );
      const [filteredPayload, prefiltered] = filterGeneratedLogistics(payload);
      const { validated, issues } = validateGeneratedBatch(
        filteredPayload,
        new Map(batch.map((page) => [page.number, page])),
        run.card_format,
      );
      // Store this batch and its progress atomically; a stopped run saves nothing late.
      run = await transaction(["lectures", "pages", "notes", "runs"], "readwrite", async (tx) => {
        const current = (await request(store(tx, "runs").get(runId))) as StoredRun | undefined;
        if (!current || current.status !== "running" || signal.aborted) throw new Cancelled();
        const existing = (await request(store(tx, "notes").index("lecture_id").getAll(current.lecture_id))) as StoredNote[];
        const { selected: chosen, filtered, overLimit } = selectDrafts(existingNotes(existing), validated, limit);
        const added = await insertDrafts(tx, current.lecture_id, chosen, current.id);
        const next: StoredRun = {
          ...current,
          cards_added: current.cards_added + added,
          study_cards_added: current.study_cards_added + chosen.reduce((sum, d) => sum + studyCardCount(d.front, d.noteType), 0),
          filtered_count: current.filtered_count + prefiltered + filtered,
          over_limit_count: current.over_limit_count + overLimit,
          completed_pages: [...current.completed_pages, ...batch.map((page) => page.number)],
          issues: [...current.issues, ...(issues as unknown as Record<string, unknown>[])],
          updated_at: nowIso(),
        };
        store(tx, "runs").put(next);
        return next;
      });
      notifyChanged(run.lecture_id);
    }
    await patchRun(runId, { status: "completed" });
  } catch (error) {
    const stopped = error instanceof Cancelled || signal.aborted;
    const status = stopped ? "cancelled" : "failed";
    const message = stopped ? "" : error instanceof WorkflowError ? error.message : UNEXPECTED;
    if (!stopped && !(error instanceof WorkflowError)) console.error(error);
    await patchRun(runId, stopped ? { status } : { status, error: message }).catch(() => undefined);
  } finally {
    unsubscribe();
  }
}

export function remainingPages(run: StoredRun): number[] {
  return run.page_numbers.filter((number) => run.text_enabled && !run.completed_pages.includes(number));
}

/** Requeue a failed or stopped run with its original settings and saved progress. */
export async function resumeRun(runId: string): Promise<StoredRun> {
  const updated = await transaction(["runs"], "readwrite", async (tx) => {
    const run = (await request(store(tx, "runs").get(runId))) as StoredRun | undefined;
    if (!run) throw new WorkflowError("This run no longer exists.");
    if (run.status === "queued" || run.status === "running") return run;
    if (!["failed", "cancelled"].includes(run.status) || !remainingPages(run).length || run.provider === "json-import") {
      throw new WorkflowError("This run has no remaining pages to resume.");
    }
    const next = { ...run, status: "queued", error: "", updated_at: nowIso() };
    store(tx, "runs").put(next);
    return next;
  });
  notifyChanged(updated.lecture_id);
  return updated;
}

/** Ask a run to stop; the runner saves nothing after this point. */
export async function stopRun(runId: string): Promise<void> {
  controllers.get(runId)?.abort();
  await transaction(["runs"], "readwrite", async (tx) => {
    const run = (await request(store(tx, "runs").get(runId))) as StoredRun | undefined;
    if (run && (run.status === "queued" || run.status === "running")) {
      store(tx, "runs").put({ ...run, status: "cancelled", updated_at: nowIso() });
      notifyChanged(run.lecture_id);
    }
  });
}

const controllers = new Map<string, AbortController>();

function lockName(lectureId: string): string {
  return `slanki-run-${lectureId}`;
}

/** Run in this tab unless another tab already runs this lecture's generation. */
export async function launchRun(run: StoredRun, generate: Generator): Promise<void> {
  const execute = async () => {
    const controller = new AbortController();
    controllers.set(run.id, controller);
    try {
      await performRun(run.id, generate, controller);
    } finally {
      controllers.delete(run.id);
    }
  };
  if (typeof navigator !== "undefined" && navigator.locks) {
    await navigator.locks.request(lockName(run.lecture_id), { ifAvailable: true }, async (lock) => {
      if (lock) await execute();
    });
  } else {
    await execute();
  }
}

export function isRunningHere(runId: string): boolean {
  return controllers.has(runId);
}

/** Runs left "running" by a closed tab become resumable failures. */
export async function recoverStaleRuns(): Promise<void> {
  const held = new Set<string>();
  try {
    const state = await navigator.locks?.query();
    for (const lock of state?.held ?? []) if (lock.name) held.add(lock.name);
  } catch {
    return;
  }
  const stale = await transaction(["runs"], "readwrite", async (tx) => {
    const runs = (await request(store(tx, "runs").getAll())) as StoredRun[];
    const changed: string[] = [];
    for (const run of runs) {
      if ((run.status === "running" || run.status === "queued") && !held.has(lockName(run.lecture_id)) && !controllers.has(run.id)) {
        store(tx, "runs").put({
          ...run,
          status: "failed",
          error: "Generation stopped because the page was closed. Resume to continue the remaining pages.",
          updated_at: nowIso(),
        });
        changed.push(run.lecture_id);
      }
    }
    return changed;
  });
  for (const lectureId of new Set(stale)) notifyChanged(lectureId);
}
