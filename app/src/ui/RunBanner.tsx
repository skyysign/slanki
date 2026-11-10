import { useState } from "preact/hooks";
import { PROVIDER_LABELS, type Provider } from "../ai/helper.ts";
import { remainingPages, stopRun } from "../run/orchestrator.ts";
import { resumeGeneration } from "../run/start.ts";
import type { LectureBundle, StoredRun } from "../store/library.ts";
import { helper } from "./ai/AiStatus.tsx";
import { plural, useBusy } from "./components.tsx";
import { reportError } from "./state.ts";

function progress(run: StoredRun): { label: string; done: number; total: number } {
  const context = run.context_data as { pages?: number[]; sections?: { pages: number[] }[]; outline?: unknown };
  if (run.context_enabled && context.outline == null) {
    const total = context.pages?.length ?? 0;
    const read = (context.sections ?? []).reduce((sum, section) => sum + section.pages.length, 0);
    return read >= total && total
      ? { label: "Connecting the main ideas of the lecture", done: read, total }
      : { label: `Reading the whole lecture first · ${read} of ${total} slides`, done: read, total: total || 1 };
  }
  return {
    label: `Drafting cards · ${run.completed_pages.length} of ${plural(run.page_numbers.length, "slide")}`,
    done: run.completed_pages.length,
    total: run.page_numbers.length || 1,
  };
}

export function RunBanner({ bundle, onOpenMake }: { bundle: LectureBundle; onOpenMake: () => void }) {
  const [dismissed, setDismissed] = useState<string | null>(null);
  const [busy, run] = useBusy();
  const latest = bundle.runs.find((r) => r.provider !== "json-import" && r.purpose === "cards");
  if (!latest || dismissed === `${latest.id}:${latest.status}`) return null;
  const provider = PROVIDER_LABELS[latest.provider as Provider] ?? latest.provider;
  const issues = latest.issues as { page: number | null; reason: string; front: string }[];
  const dismiss = () => setDismissed(`${latest.id}:${latest.status}`);

  if (latest.status === "queued" || latest.status === "running") {
    const state = progress(latest);
    return (
      <div class="banner info" aria-live="polite">
        <div style={{ flex: "1 1 260px" }} class="stack">
          <strong>{state.label}</strong>
          <div class="progress">
            <div style={{ width: `${Math.max(4, (state.done / state.total) * 100)}%` }} />
          </div>
          <span class="muted small">
            {latest.error || `${provider} is working. Cards appear here as each batch finishes. Keep this tab open.`}
          </span>
        </div>
        <button class="btn" disabled={busy} onClick={() => run(() => stopRun(latest.id).catch(reportError))}>
          Stop
        </button>
      </div>
    );
  }

  const remaining = remainingPages(latest);
  const resumable = (latest.status === "failed" || latest.status === "cancelled") && remaining.length > 0;
  const issueList = issues.length > 0 && (
    <details class="small" style={{ flexBasis: "100%" }}>
      <summary>
        {plural(issues.length, "draft")} skipped because the AI's source excerpt did not match the slide
      </summary>
      <ul>
        {issues.slice(0, 50).map((issue, i) => (
          <li key={i}>
            {issue.page ? `Slide ${issue.page}: ` : ""}
            {issue.front || "(no question)"} <span class="muted">— {issue.reason}</span>
          </li>
        ))}
      </ul>
    </details>
  );
  if (resumable) {
    return (
      <div class={`banner ${latest.status === "failed" ? "error" : "warn"}`} role="status">
        <div style={{ flex: "1 1 260px" }}>
          <strong>
            {latest.status === "cancelled" ? "Stopped" : "Stopped early"} · {plural(remaining.length, "slide")} not processed yet
          </strong>
          {latest.error && <div class="small">{latest.error}</div>}
          <div class="muted small">{plural(latest.cards_added, "card")} from this run are saved.</div>
        </div>
        <button
          class="btn primary"
          disabled={busy || helper.value.phase !== "ready"}
          title={helper.value.phase !== "ready" ? "Connect your AI first" : ""}
          onClick={() => run(() => resumeGeneration(latest.id).catch(reportError))}
        >
          Resume
        </button>
        <button class="btn ghost small" onClick={dismiss}>
          Dismiss
        </button>
        {issueList}
      </div>
    );
  }
  if (latest.status === "limited") {
    return (
      <div class="banner warn" role="status">
        <span style={{ flex: "1 1 260px" }}>
          Reached the card limit. {plural(remaining.length, "slide")} were not used. Make more cards for them if you need to.
        </span>
        <button class="btn small" onClick={onOpenMake}>
          Make more cards
        </button>
        <button class="btn ghost small" onClick={dismiss}>
          Dismiss
        </button>
        {issueList}
      </div>
    );
  }
  if (latest.status === "completed" && (issues.length || Date.now() - Date.parse(latest.updated_at) < 10 * 60 * 1000)) {
    return (
      <div class="banner ok" role="status">
        <span style={{ flex: "1 1 260px" }}>
          {provider} drafted {plural(latest.cards_added, "card")}
          {latest.filtered_count ? ` and skipped ${plural(latest.filtered_count, "course-logistics question")}` : ""}. Review them below.
        </span>
        <button class="btn ghost small" onClick={dismiss}>
          Dismiss
        </button>
        {issueList}
      </div>
    );
  }
  return null;
}
