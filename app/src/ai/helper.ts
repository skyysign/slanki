// Client for the local Slanki helper (`npx slanki`). The browser never starts
// processes itself; the helper runs the user's CLI with restricted settings.
import { GenerationOutputError, WorkflowError } from "../core/errors.ts";

export const HELPER_PORT = 47213;
export const HELPER_ORIGIN = `http://127.0.0.1:${HELPER_PORT}`;
export const API_VERSION = 1;
const TOKEN_KEY = "slanki:helper-token";

/** CLI providers run through the helper; "openai" and "anthropic" use an API key in the browser. */
export type Provider = "codex" | "claude" | "gemini" | "kimi" | "openai" | "anthropic";
export const PROVIDER_LABELS: Record<Provider, string> = {
  codex: "Codex",
  claude: "Claude Code",
  gemini: "Gemini CLI",
  kimi: "Kimi Code",
  openai: "OpenAI API",
  anthropic: "Anthropic API",
};

export interface ProviderStatus {
  loggingIn?: boolean;
  installed: boolean;
  signedIn: "yes" | "no" | "unknown";
  message: string;
  login: string;
}

export interface HelperStatus {
  apiVersion: number;
  version: string;
  providers: Partial<Record<Provider, ProviderStatus>>;
}

export interface ModelChoice {
  id: string;
  label: string;
  efforts: string[];
  default_effort: string;
}

export type JobState =
  | { id: string; key: string; status: "running" }
  | { id: string; key: string; status: "done"; result: unknown }
  | { id: string; key: string; status: "failed" | "canceled"; error: { code: string; message: string } };

export class HelperUnavailable extends WorkflowError {
  override name = "HelperUnavailable";
}

export class Cancelled extends Error {
  override name = "Cancelled";
}

function storage(): Storage | null {
  try {
    return localStorage;
  } catch {
    return null;
  }
}

export function helperToken(): string | null {
  return storage()?.getItem(TOKEN_KEY) ?? null;
}

export function forgetHelper(): void {
  storage()?.removeItem(TOKEN_KEY);
}

/** Same-origin when the app is served by the helper itself (Safari fallback). */
export function helperBase(): string {
  return location.origin === HELPER_ORIGIN ? "" : HELPER_ORIGIN;
}

async function call(path: string, init: RequestInit = {}, timeoutMs = 15000): Promise<Response> {
  const token = helperToken();
  const controller = new AbortController();
  const outer = init.signal;
  const abort = () => controller.abort();
  outer?.addEventListener("abort", abort);
  const timer = setTimeout(abort, timeoutMs);
  try {
    return await fetch(helperBase() + path, {
      ...init,
      signal: controller.signal,
      credentials: "omit",
      cache: "no-store",
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
  } catch (error) {
    if (outer?.aborted) throw new Cancelled();
    throw new HelperUnavailable(
      "The Slanki helper is not reachable. Start it with `npx slanki@1` and keep that window open. If your browser asked whether this site may access apps on your device, choose Allow (site settings → Local network access).",
      { cause: error },
    );
  } finally {
    clearTimeout(timer);
    outer?.removeEventListener("abort", abort);
  }
}

async function json<T>(response: Response): Promise<T> {
  const body = (await response.json().catch(() => ({}))) as { error?: { code?: string; message?: string } } & T;
  if (response.status === 401) {
    forgetHelper();
    throw new HelperUnavailable("This browser is not paired with the helper anymore. Run `npx slanki` again and use the link it opens.");
  }
  if (!response.ok) throw jobError(body.error?.code ?? "helper", body.error?.message ?? "The helper refused this request.");
  return body;
}

export async function pair(code: string): Promise<void> {
  const response = await call("/v1/pair", { method: "POST", body: JSON.stringify({ code }) });
  const { token } = await json<{ token: string }>(response);
  if (typeof token !== "string" || token.length < 32) throw new HelperUnavailable("Pairing failed. Run `npx slanki` again.");
  storage()?.setItem(TOKEN_KEY, token);
}

/** Start (or cancel) the CLI's own browser sign-in with OpenAI / Anthropic. */
export async function startLogin(provider: Provider): Promise<void> {
  await json(await call(`/v1/providers/${provider}/login`, { method: "POST" }));
}

export async function cancelLogin(provider: Provider): Promise<void> {
  await json(await call(`/v1/providers/${provider}/login`, { method: "DELETE" }));
}

export async function helperStatus(): Promise<HelperStatus> {
  return json<HelperStatus>(await call("/v1/status"));
}

export async function listModels(provider: Provider, refresh = false): Promise<ModelChoice[]> {
  const response = await call(`/v1/providers/${provider}/models${refresh ? "?refresh=1" : ""}`, {}, 60000);
  return (await json<{ models: ModelChoice[] }>(response)).models;
}

export interface JobRequest {
  key: string;
  provider: Provider;
  model: string;
  effort: string;
  task: "cards" | "overview";
  prompt: string;
  schema: object;
}

export async function startJob(request: JobRequest, signal?: AbortSignal): Promise<JobState> {
  return json<JobState>(await call("/v1/jobs", { method: "POST", body: JSON.stringify(request), signal }, 30000));
}

export async function jobByKey(key: string): Promise<JobState | null> {
  const response = await call(`/v1/jobs/by-key/${encodeURIComponent(key)}`);
  if (response.status === 404) return null;
  return json<JobState>(response);
}

export async function cancelJob(id: string): Promise<void> {
  await call(`/v1/jobs/${encodeURIComponent(id)}`, { method: "DELETE" }).catch(() => undefined);
}

/** Long-poll until the job finishes; resolves with its parsed JSON result. */
export async function waitForJob(job: JobState, signal: AbortSignal, onPoll: () => void = () => undefined): Promise<unknown> {
  let state = job;
  while (state.status === "running") {
    if (signal.aborted) throw new Cancelled();
    onPoll();
    const response = await call(`/v1/jobs/${encodeURIComponent(state.id)}?wait=25`, { signal }, 40000);
    state = await json<JobState>(response);
  }
  if (state.status === "done") {
    void call(`/v1/jobs/${encodeURIComponent(state.id)}`, { method: "DELETE" }).catch(() => undefined);
    return state.result;
  }
  if (state.status === "canceled") throw new Cancelled();
  throw jobError(state.error.code, state.error.message);
}

/** Map helper error codes to the messages users saw in Recalloom. */
export function jobError(code: string, message: string): Error {
  switch (code) {
    case "invalid_output":
      return new GenerationOutputError(message || "The AI returned invalid JSON. No cards from this batch were imported.");
    case "canceled":
      return new Cancelled();
    default:
      return new WorkflowError(message || "The helper could not finish. Completed drafts are preserved.");
  }
}
