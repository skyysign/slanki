// In-memory generation jobs: one at a time, idempotent by key, results kept
// for two hours so a reloaded or sleeping browser can still collect them.
import { randomUUID } from "node:crypto";
import { HelperError } from "./processes.ts";

export type JobStatus = "running" | "done" | "failed" | "canceled";

export interface Job {
  id: string;
  key: string;
  provider: string;
  status: JobStatus;
  result?: unknown;
  error?: { code: string; message: string };
  created: number;
  finished?: number;
  controller: AbortController;
  waiters: Set<() => void>;
}

export interface JobView {
  id: string;
  key: string;
  status: JobStatus;
  result?: unknown;
  error?: { code: string; message: string };
}

const RETENTION_MS = 2 * 60 * 60 * 1000;
const MAX_JOBS = 20;
const HOURLY_LIMIT = 60;

export class Jobs {
  private jobs = new Map<string, Job>();
  private started: number[] = [];

  private now: () => number;

  constructor(now: () => number = Date.now) {
    this.now = now;
  }

  private prune(): void {
    const now = this.now();
    for (const [id, job] of this.jobs) {
      if (job.finished && now - job.finished > RETENTION_MS) this.jobs.delete(id);
    }
    while (this.jobs.size > MAX_JOBS) {
      const oldest = [...this.jobs.values()].filter((job) => job.status !== "running").sort((a, b) => a.created - b.created)[0];
      if (!oldest) break;
      this.jobs.delete(oldest.id);
    }
    this.started = this.started.filter((time) => now - time < 60 * 60 * 1000);
  }

  view(job: Job): JobView {
    return { id: job.id, key: job.key, status: job.status, ...(job.result !== undefined ? { result: job.result } : {}), ...(job.error ? { error: job.error } : {}) };
  }

  get(id: string): Job | undefined {
    this.prune();
    return this.jobs.get(id);
  }

  byKey(key: string): Job | undefined {
    this.prune();
    return [...this.jobs.values()].find((job) => job.key === key);
  }

  /** Start work unless the same key already exists; refuses a second concurrent job. */
  start(key: string, provider: string, work: (signal: AbortSignal) => Promise<unknown>): Job {
    this.prune();
    const existing = this.byKey(key);
    if (existing && existing.status !== "failed" && existing.status !== "canceled") return existing;
    if ([...this.jobs.values()].some((job) => job.status === "running")) {
      throw new HelperError("busy", "The helper is already running a request. Wait for it to finish.");
    }
    if (this.started.length >= HOURLY_LIMIT) {
      throw new HelperError("busy", "Too many requests this hour. Wait a little before generating more.");
    }
    if (existing) this.jobs.delete(existing.id);
    const job: Job = {
      id: randomUUID(),
      key,
      provider,
      status: "running",
      created: this.now(),
      controller: new AbortController(),
      waiters: new Set(),
    };
    this.jobs.set(job.id, job);
    this.started.push(job.created);
    void work(job.controller.signal).then(
      (result) => this.finish(job, { status: "done", result }),
      (error: unknown) => {
        const failure = error instanceof HelperError ? error : new HelperError("failed", "The helper hit an unexpected problem.");
        if (!(error instanceof HelperError)) console.error("[slanki] unexpected job error");
        this.finish(job, { status: failure.code === "canceled" ? "canceled" : "failed", error: { code: failure.code, message: failure.message } });
      },
    );
    return job;
  }

  private finish(job: Job, outcome: Pick<Job, "status" | "result" | "error">): void {
    if (job.status !== "running") return;
    Object.assign(job, outcome, { finished: this.now() });
    for (const wake of job.waiters) wake();
    job.waiters.clear();
  }

  cancel(id: string): boolean {
    const job = this.jobs.get(id);
    if (!job) return false;
    if (job.status === "running") {
      job.controller.abort();
      this.finish(job, { status: "canceled", error: { code: "canceled", message: "Stopped." } });
    } else {
      // Acknowledged result: free it now.
      this.jobs.delete(id);
    }
    return true;
  }

  /** Wait up to `ms` for the job to finish. */
  wait(job: Job, ms: number): Promise<void> {
    if (job.status !== "running") return Promise.resolve();
    return new Promise((resolve) => {
      const timer = setTimeout(done, ms);
      function done() {
        clearTimeout(timer);
        job.waiters.delete(done);
        resolve();
      }
      job.waiters.add(done);
    });
  }

  busy(): boolean {
    return [...this.jobs.values()].some((job) => job.status === "running");
  }

  cancelAll(): void {
    for (const job of this.jobs.values()) if (job.status === "running") job.controller.abort();
  }
}
