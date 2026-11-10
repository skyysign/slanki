// Starting and resuming generation with the user's AI (API key or helper).
import { generateWithKey, isKeyProvider } from "../ai/apiKeys.ts";
import { startJob, waitForJob, type Provider } from "../ai/helper.ts";
import { WorkflowError } from "../core/errors.ts";
import type { CardFormat } from "../core/noteTypes.ts";
import { generationRequest } from "../core/prompts.ts";
import { cpLength, pyStrip } from "../core/py.ts";
import { checkedCardLimit } from "../core/selection.ts";
import { getLecture, getRun, putRun, type LectureBundle } from "../store/library.ts";
import { newRun } from "../services/runs.ts";
import { launchRun, resumeRun, type Generator } from "./orchestrator.ts";

export function helperGenerator(provider: Provider, model: string, effort: string): Generator {
  return async (call, key, signal) => {
    if (call.pages.reduce((sum, page) => sum + cpLength(page.text), 0) > 200000) {
      throw new WorkflowError("This batch contains too much text. Select fewer pages or increase the card limit.");
    }
    const [prompt, schema] = generationRequest(call.pages, call.cardLimit, call.existingQuestions, {
      task: call.task,
      cardFormat: call.cardFormat,
      learningFocus: call.learningFocus,
      lectureContext: call.lectureContext,
      sections: call.sections,
      validationFeedback: call.validationFeedback,
    });
    if (isKeyProvider(provider)) return generateWithKey(provider, model, effort, prompt, schema, signal);
    const job = await startJob({ key, provider, model, effort, task: call.task, prompt, schema }, signal);
    return waitForJob(job, signal);
  };
}

export interface GenerationSettings {
  pages: readonly number[];
  cardLimit: number | string | null;
  reverse: boolean;
  provider: Provider;
  model: string;
  effort: string;
}

/** Create and launch a run. Whole-lecture context is always used when there is text. */
export async function startGeneration(bundle: LectureBundle, settings: GenerationSettings): Promise<string> {
  if (bundle.runs.some((run) => run.status === "queued" || run.status === "running")) {
    throw new WorkflowError("This lecture already has a generation in progress. Wait or stop it first.");
  }
  const readable = bundle.pages.filter((page) => !page.warning && pyStrip(page.text) && settings.pages.includes(page.number));
  if (!readable.length) throw new WorkflowError("Select at least one usable source page.");
  const cardFormat: CardFormat = settings.reverse ? "all" : "mixed";
  const cardLimit = checkedCardLimit(settings.cardLimit, readable.length, { cardFormat });
  const run = newRun(bundle.lecture.id, {
    provider: settings.provider,
    model: settings.model,
    reasoning_effort: settings.effort,
    page_numbers: readable.map((page) => page.number),
    card_limit: cardLimit,
    card_format: cardFormat,
    learning_focus: "balanced",
    context_enabled: true,
  });
  await putRun(run);
  void launchRun(run, helperGenerator(settings.provider, settings.model, settings.effort));
  return run.id;
}

/** Continue the remaining pages with the run's original provider and settings. */
export async function resumeGeneration(runId: string): Promise<void> {
  const run = await resumeRun(runId);
  const lecture = await getLecture(run.lecture_id);
  if (!lecture) throw new WorkflowError("This lecture is no longer in your library.");
  if (!["codex", "claude", "openai", "anthropic"].includes(run.provider)) {
    throw new WorkflowError("This run used an AI that Slanki cannot resume yet. Start a new run instead.");
  }
  void launchRun(run, helperGenerator(run.provider as Provider, run.model, run.reasoning_effort));
}

export { getRun };
