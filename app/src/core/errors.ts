/** An error that can be shown to the user without exposing internals. */
export class WorkflowError extends Error {
  override name = "WorkflowError";
}

/** A completed model response was unreadable; safe to retry within a fixed limit. */
export class GenerationOutputError extends WorkflowError {
  override name = "GenerationOutputError";
}
