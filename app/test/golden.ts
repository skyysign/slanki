// Helpers for comparing the TypeScript port against frozen Python outputs.
import { readFileSync } from "node:fs";
import { GenerationOutputError, WorkflowError } from "../src/core/errors.ts";

export const GOLDEN = new URL("../../tests/fixtures/synthetic/golden/", import.meta.url);
export const FIXTURES = new URL("../../tests/fixtures/synthetic/", import.meta.url);

export function golden<T = any>(name: string): T {
  return JSON.parse(readFileSync(new URL(name, GOLDEN), "utf8")) as T;
}

export function goldenBytes(name: string): Uint8Array {
  return new Uint8Array(readFileSync(new URL(name, GOLDEN)));
}

export function fixtureBytes(name: string): Uint8Array {
  return new Uint8Array(readFileSync(new URL(name, FIXTURES)));
}

export type Outcome = { ok: unknown } | { error: string } | { output_error: string };

/** Same shape as tools/golden.py outcome(): ok value or the user-facing message. */
export function outcome(run: () => unknown): Outcome {
  try {
    return { ok: run() };
  } catch (error) {
    if (error instanceof GenerationOutputError) return { output_error: error.message };
    if (error instanceof WorkflowError) return { error: error.message };
    throw error;
  }
}
