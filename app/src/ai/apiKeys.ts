// Generation with the user's own API key, straight from this browser to
// OpenAI or Anthropic (no helper, no Slanki server). Keys stay in this
// browser's localStorage and are never written to backups or run records.
import { signal } from "@preact/signals";
import { GenerationOutputError, WorkflowError } from "../core/errors.ts";
import { Cancelled, type ModelChoice } from "./helper.ts";

export type KeyProvider = "openai" | "anthropic";
export const KEY_PROVIDERS: KeyProvider[] = ["openai", "anthropic"];
export const KEY_PAGES: Record<KeyProvider, string> = {
  openai: "https://platform.openai.com/api-keys",
  anthropic: "https://platform.claude.com/settings/keys",
};
export const DEFAULT_KEY_MODELS: Record<KeyProvider, string> = { openai: "", anthropic: "claude-opus-5-5" };
const EFFORTS = ["low", "medium", "high"];

export function isKeyProvider(provider: string): provider is KeyProvider {
  return provider === "openai" || provider === "anthropic";
}

const storageKey = (provider: KeyProvider) => `slanki:key:${provider}`;

function readKeys(): Partial<Record<KeyProvider, string>> {
  const keys: Partial<Record<KeyProvider, string>> = {};
  try {
    for (const provider of KEY_PROVIDERS) {
      const value = localStorage.getItem(storageKey(provider));
      if (value) keys[provider] = value;
    }
  } catch {
    // Storage unavailable: keys then last for this visit only.
  }
  return keys;
}

export const apiKeys = signal(readKeys());

export function saveApiKey(provider: KeyProvider, key: string | null): void {
  const next = { ...apiKeys.value };
  if (key) next[provider] = key;
  else delete next[provider];
  apiKeys.value = next;
  try {
    if (key) localStorage.setItem(storageKey(provider), key);
    else localStorage.removeItem(storageKey(provider));
  } catch {
    // See readKeys.
  }
}

function requireKey(provider: KeyProvider): string {
  const key = apiKeys.value[provider];
  if (!key) throw new WorkflowError("Add your API key under “Your AI” first.");
  return key;
}

const anthropicClient = async (key: string) => {
  const sdk = await import("@anthropic-ai/sdk");
  return { sdk, client: new sdk.default({ apiKey: key, dangerouslyAllowBrowser: true, maxRetries: 2 }) };
};

/** Lists usable models; doubles as the key check. */
export async function listKeyModels(provider: KeyProvider, key: string): Promise<ModelChoice[]> {
  if (provider === "anthropic") {
    const { sdk, client } = await anthropicClient(key);
    try {
      const models: ModelChoice[] = [];
      for await (const model of client.models.list({ limit: 100 })) {
        if (/^claude-(opus|sonnet|haiku|fable)-[5-9]/.test(model.id)) {
          models.push({ id: model.id, label: model.display_name || model.id, efforts: EFFORTS, default_effort: "low" });
        }
      }
      return models;
    } catch (error) {
      throw anthropicError(sdk, error);
    }
  }
  const response = await openaiFetch(key, "/v1/models", { method: "GET" });
  const body = (await response.json()) as { data?: { id: string; created?: number }[] };
  return (body.data ?? [])
    .filter((m) => /^(gpt-5|o\d)/.test(m.id) && !/(audio|realtime|tts|transcribe|image|search|codex|chat-latest)/.test(m.id))
    .sort((a, b) => (b.created ?? 0) - (a.created ?? 0))
    .map((m) => ({ id: m.id, label: m.id, efforts: EFFORTS, default_effort: "low" }));
}

/** One generation call; returns the parsed JSON object (validated later by the orchestrator). */
export async function generateWithKey(
  provider: KeyProvider,
  model: string,
  effort: string,
  prompt: string,
  schema: object,
  signal: AbortSignal,
): Promise<unknown> {
  const key = requireKey(provider);
  const chosenEffort = EFFORTS.includes(effort) ? effort : "low";
  const text = provider === "anthropic"
    ? await anthropicText(key, model || DEFAULT_KEY_MODELS.anthropic, chosenEffort, prompt, schema, signal)
    : await openaiText(key, model, chosenEffort, prompt, schema, signal);
  try {
    return JSON.parse(text);
  } catch {
    throw new GenerationOutputError("The AI returned invalid JSON. No cards from this batch were imported.");
  }
}

async function anthropicText(key: string, model: string, effort: string, prompt: string, schema: object, signal: AbortSignal) {
  const { sdk, client } = await anthropicClient(key);
  // Server-side refusal fallback where the model supports it (not Haiku).
  const fallback = /^claude-(opus-5|fable-5|sonnet-5-5)/.test(model);
  try {
    const message = await client.beta.messages
      .stream(
        {
          model,
          max_tokens: 64000,
          messages: [{ role: "user", content: prompt }],
          output_config: { effort: effort as "low" | "medium" | "high", format: { type: "json_schema", schema: schema as Record<string, unknown> } },
          ...(fallback ? { betas: ["server-side-fallback-2026-07-01"], fallbacks: "default" as const } : {}),
        },
        { signal },
      )
      .finalMessage();
    if (message.stop_reason === "refusal") throw new WorkflowError("Claude declined this batch. Completed drafts are preserved.");
    if (message.stop_reason === "max_tokens") throw new GenerationOutputError("The AI's answer was cut off. Select fewer slides per run.");
    return message.content.map((block) => (block.type === "text" ? block.text : "")).join("");
  } catch (error) {
    throw anthropicError(sdk, error, signal);
  }
}

function anthropicError(sdk: typeof import("@anthropic-ai/sdk"), error: unknown, signal?: AbortSignal): Error {
  if (signal?.aborted || error instanceof sdk.APIUserAbortError) return new Cancelled();
  if (error instanceof WorkflowError) return error;
  if (error instanceof sdk.AuthenticationError || error instanceof sdk.PermissionDeniedError) {
    return new WorkflowError("Anthropic rejected this API key. Check it under “Your AI”.");
  }
  if (error instanceof sdk.RateLimitError) return new WorkflowError("Anthropic's rate limit was reached. Wait a minute, then Resume.");
  if (error instanceof sdk.APIConnectionError) return new WorkflowError("Could not reach Anthropic. Check your connection, then Resume.");
  if (error instanceof sdk.APIError) return new WorkflowError(`Anthropic: ${error.message}`);
  return error instanceof Error ? error : new WorkflowError(String(error));
}

async function openaiFetch(key: string, path: string, init: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`https://api.openai.com${path}`, {
      ...init,
      credentials: "omit",
      headers: { Authorization: `Bearer ${key}`, ...(init.body ? { "Content-Type": "application/json" } : {}) },
    });
  } catch (error) {
    if (init.signal?.aborted) throw new Cancelled();
    throw new WorkflowError("Could not reach OpenAI. Check your connection, then Resume.", { cause: error });
  }
  if (response.ok) return response;
  const body = (await response.json().catch(() => ({}))) as { error?: { message?: string; code?: string } };
  if (response.status === 401 || response.status === 403) throw new WorkflowError("OpenAI rejected this API key. Check it under “Your AI”.");
  if (body.error?.code === "insufficient_quota") throw new WorkflowError("Your OpenAI account has no API credit left. Add billing at platform.openai.com.");
  if (response.status === 429) throw new WorkflowError("OpenAI's rate limit was reached. Wait a minute, then Resume.");
  throw new WorkflowError(`OpenAI: ${body.error?.message ?? `request failed (${response.status})`}`);
}

async function openaiText(key: string, model: string, effort: string, prompt: string, schema: object, signal: AbortSignal) {
  if (!model) throw new WorkflowError("Choose an OpenAI model under “Your AI”.");
  const response = await openaiFetch(key, "/v1/responses", {
    method: "POST",
    signal,
    body: JSON.stringify({
      model,
      input: prompt,
      store: false,
      reasoning: { effort },
      text: { format: { type: "json_schema", name: "slanki_output", schema, strict: true } },
    }),
  });
  const body = (await response.json().catch(() => {
    if (signal.aborted) throw new Cancelled();
    throw new GenerationOutputError("OpenAI's answer could not be read.");
  })) as {
    status?: string;
    output?: { type: string; content?: { type: string; text?: string; refusal?: string }[] }[];
  };
  const parts = (body.output ?? []).filter((item) => item.type === "message").flatMap((item) => item.content ?? []);
  if (parts.some((part) => part.type === "refusal")) throw new WorkflowError("The AI declined this batch. Completed drafts are preserved.");
  if (body.status === "incomplete") throw new GenerationOutputError("The AI's answer was cut off. Select fewer slides per run.");
  return parts.map((part) => (part.type === "output_text" ? (part.text ?? "") : "")).join("");
}
