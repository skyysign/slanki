// Small shared interface state: hash route and notifications.
import { signal } from "@preact/signals";
import { WorkflowError } from "../core/errors.ts";

export type Route = { name: "library" } | { name: "lecture"; id: string };

function parse(): Route {
  const match = /^#\/lecture\/([0-9a-f-]{36})/.exec(location.hash);
  return match ? { name: "lecture", id: match[1]! } : { name: "library" };
}

export const route = signal<Route>(parse());
addEventListener("hashchange", () => {
  route.value = parse();
});

export function openLecture(id: string): void {
  location.hash = `#/lecture/${id}`;
}

export function openLibrary(): void {
  location.hash = "#/";
}

export interface Toast {
  message: string;
  error: boolean;
}

export const toast = signal<Toast | null>(null);
let toastTimer: ReturnType<typeof setTimeout> | undefined;

export function notify(message: string, error = false): void {
  toast.value = { message, error };
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toast.value = null), error ? 8000 : 3500);
}

/** User-facing text for an error; unexpected errors never expose internals. */
export function errorMessage(error: unknown): string {
  if (error instanceof WorkflowError) return error.message;
  console.error(error);
  if (error instanceof DOMException && error.name === "QuotaExceededError") {
    return "This browser is out of storage space. Delete a lecture or free up disk space.";
  }
  return "Something went wrong. Your saved work is unchanged.";
}

export function reportError(error: unknown): void {
  notify(errorMessage(error), true);
}
