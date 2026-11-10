// AI preferences remembered in this browser (no lecture content, no credentials).
import { signal } from "@preact/signals";
import type { Provider } from "./helper.ts";

export interface AiPreferences {
  provider: Provider;
  model: string;
  effort: string;
  /** Providers the user agreed to send slide text to. */
  consented: Provider[];
}

const KEY = "slanki:ai";
const DEFAULTS: AiPreferences = { provider: "codex", model: "", effort: "low", consented: [] };

function load(): AiPreferences {
  try {
    const stored = JSON.parse(localStorage.getItem(KEY) ?? "{}") as Partial<AiPreferences>;
    return {
      provider: ["codex", "claude", "gemini", "kimi"].includes(stored.provider as string) ? (stored.provider as Provider) : DEFAULTS.provider,
      model: typeof stored.model === "string" ? stored.model : DEFAULTS.model,
      effort: typeof stored.effort === "string" ? stored.effort : DEFAULTS.effort,
      consented: Array.isArray(stored.consented) ? stored.consented.filter((p) => typeof p === "string") : [],
    };
  } catch {
    return { ...DEFAULTS };
  }
}

export const aiPreferences = signal<AiPreferences>(load());

export function savePreferences(changes: Partial<AiPreferences>): void {
  aiPreferences.value = { ...aiPreferences.value, ...changes };
  try {
    localStorage.setItem(KEY, JSON.stringify(aiPreferences.value));
  } catch {
    // Storage may be unavailable (private mode); preferences then last for this visit.
  }
}
