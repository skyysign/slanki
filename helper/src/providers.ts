// Codex and Claude Code integrations (port of generation.py, cli.py,
// providers.py and connection.py). Prompts travel on stdin; tools are disabled.
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, existsSync, statSync, renameSync } from "node:fs";
import { join } from "node:path";
import { dumps } from "../../app/src/core/pyjson.ts";
import { HelperError, claudeExecutable, codexExecutable, lineSession, removeDir, runProcess } from "./processes.ts";

export type Provider = "codex" | "claude";

/** How to start each CLI: native executable plus any leading arguments (tests use fakes). */
export interface Commands {
  codex: () => string[];
  claude: () => string[];
}
export const nativeCommands: Commands = {
  codex: () => [codexExecutable()],
  claude: () => [claudeExecutable()],
};
export const PROVIDERS: Provider[] = ["codex", "claude"];
export const EFFORTS = ["", "none", "minimal", "low", "medium", "high", "xhigh", "max", "off", "on"] as const;
export const EFFORT_LABELS: Record<string, string> = {
  "": "CLI default",
  none: "None",
  minimal: "Minimal",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra high",
  max: "Max",
  off: "Thinking off",
  on: "Thinking on",
};
const MODEL_ID = /^[A-Za-z0-9][A-Za-z0-9._:/[\]-]{0,99}$/;
const GENERATION_TIMEOUT_MS = 300_000;
const OUTPUT_LIMIT = 2 * 1024 * 1024;
const DIAGNOSTIC_LIMIT = 5 * 1024 * 1024;

export function checkedModelId(model: unknown): string {
  if (typeof model !== "string" || (model && !MODEL_ID.test(model))) {
    throw new HelperError("invalid_request", "Choose a model from this CLI's model list.");
  }
  return model;
}

export interface ModelRow {
  id: string;
  label: string;
  efforts: string[];
  default_effort: string;
}

export function defaultModel(): ModelRow {
  return { id: "", label: "CLI default", efforts: [""], default_effort: "" };
}

/** Port of providers.normalize_models. */
export function normalizeModels(rows: unknown, provider: Provider): ModelRow[] {
  if (!Array.isArray(rows) || !rows.length || rows.length > 200) {
    throw new HelperError("failed", "The CLI did not return a usable model list.");
  }
  const result: ModelRow[] = [];
  const seen = new Set<string>();
  let fallback = defaultModel();
  for (const row of rows) {
    if (!row || typeof row !== "object" || Array.isArray(row)) {
      throw new HelperError("failed", "The CLI returned malformed model metadata.");
    }
    const data = row as Record<string, unknown>;
    if (data.hidden) continue;
    let model = provider === "codex" ? data.model : data.value;
    if (provider === "claude" && model === "default") model = "";
    checkedModelId(model);
    const id = model as string;
    const label = (data.displayName as string) || id || "CLI default";
    if (typeof label !== "string" || label.length < 1 || label.length > 150) {
      throw new HelperError("failed", "The CLI returned an invalid model label.");
    }
    let levels: unknown = provider === "codex" ? (data.supportedReasoningEfforts ?? []) : (data.supportedEffortLevels ?? []);
    if (!Array.isArray(levels)) throw new HelperError("failed", "The CLI returned invalid reasoning options.");
    if (provider === "codex") {
      levels = levels
        .filter((entry) => entry && typeof entry === "object" && !Array.isArray(entry))
        .map((entry) => (entry as Record<string, unknown>).reasoningEffort);
    }
    if (provider === "claude" && data.supportsEffort === false) levels = [];
    const supported = EFFORTS.filter((value) => value && (levels as unknown[]).includes(value));
    const item: ModelRow = {
      id,
      label,
      efforts: ["", ...supported],
      default_effort: (data.defaultReasoningEffort as string) ?? "",
    };
    if (!item.efforts.includes(item.default_effort)) item.default_effort = "";
    if (id === "" || data.isDefault) fallback = { ...item, id: "", label: "CLI default" + (id ? ` (${label})` : "") };
    if (id && !seen.has(id)) {
      result.push(item);
      seen.add(id);
    }
  }
  if (!result.length) throw new HelperError("failed", "No selectable models were returned by this CLI.");
  return [fallback, ...result];
}

// --- Claude isolation ----------------------------------------------------

export function claudeIsolationArgs(): string[] {
  // --bare deliberately ignores subscription login. --safe-mode retains it.
  return [
    "--safe-mode",
    "--setting-sources",
    "",
    "--settings",
    dumps({ disableAllHooks: true, autoMemoryEnabled: false, permissions: { defaultMode: "dontAsk" } }),
    "--tools",
    "",
    "--disallowedTools",
    "mcp__*",
    "--strict-mcp-config",
    "--mcp-config",
    '{"mcpServers":{}}',
    "--disable-slash-commands",
    "--no-chrome",
    "--no-session-persistence",
  ];
}

/** Normal local Claude sign-in; inherited toggles must not change model, effort or tools. */
export function claudeEnvironment(env: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv {
  const result: NodeJS.ProcessEnv = {};
  for (const [key, value] of Object.entries(env)) {
    if (
      ["ANTHROPIC_DEFAULT_", "CLAUDE_CODE_EFFORT", "CLAUDE_CODE_SUBAGENT", "CLAUDE_CODE_EXPERIMENTAL_"].some((prefix) =>
        key.startsWith(prefix),
      ) ||
      ["ANTHROPIC_MODEL", "CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_BARE", "CLAUDECODE"].includes(key)
    ) {
      continue;
    }
    result[key] = value;
  }
  return result;
}

export function claudeIsExternal(env: NodeJS.ProcessEnv = process.env): boolean {
  return [
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
  ].some((key) => env[key]);
}

export function codexArgs(options: { model: string; effort: string; schemaPath: string; outputPath: string }): string[] {
  const args = [
    "-a",
    "never",
    "exec",
    "--ignore-user-config",
    "--ephemeral",
    "--skip-git-repo-check",
    "--sandbox",
    "read-only",
    "--color",
    "never",
    "--disable",
    "shell_tool",
    "--disable",
    "unified_exec",
    "--disable",
    "apps",
    "--disable",
    "multi_agent",
    "-c",
    'web_search="disabled"',
    "-c",
    "project_doc_max_bytes=0",
  ];
  if (options.model) args.push("--model", options.model);
  if (options.effort) args.push("-c", `model_reasoning_effort="${options.effort}"`);
  args.push("--output-schema", options.schemaPath, "--output-last-message", options.outputPath, "-");
  return args;
}

export function claudeArgs(options: { model: string; effort: string; schema: object }): string[] {
  const args = ["-p", "--output-format", "json", "--json-schema", dumps(options.schema), "--max-turns", "3", ...claudeIsolationArgs()];
  if (options.model) args.push("--model", options.model);
  if (options.effort) args.push("--effort", options.effort);
  return args;
}

/** Port of the claude_generate result envelope checks. */
export function parseClaudeEnvelope(text: string): Record<string, unknown> {
  let envelope: unknown;
  try {
    envelope = JSON.parse(text);
  } catch {
    throw new HelperError("invalid_output", "Claude Code returned invalid result JSON.");
  }
  const data = envelope as Record<string, unknown>;
  if (
    !envelope ||
    typeof envelope !== "object" ||
    Array.isArray(envelope) ||
    data.type !== "result" ||
    data.is_error === true ||
    data.subtype !== "success"
  ) {
    throw new HelperError("failed", "Claude Code did not return a successful JSON result. Check your connection and allowance.");
  }
  const bad = () =>
    new HelperError("invalid_output", "Claude Code did not return a successful JSON result. No cards from this batch were imported.");
  let payload = data.structured_output;
  if (payload === undefined || payload === null) {
    if (typeof data.result !== "string") throw bad();
    try {
      payload = JSON.parse(data.result);
    } catch {
      throw bad();
    }
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw bad();
  return payload as Record<string, unknown>;
}

// --- Generation ------------------------------------------------------------

export interface GenerationRequest {
  provider: Provider;
  model: string;
  effort: string;
  prompt: string;
  schema: object;
}

function tempDir(work: string): string {
  mkdirSync(work, { recursive: true });
  return mkdtempSync(join(work, "job-"));
}

export async function generate(
  request: GenerationRequest,
  work: string,
  signal: AbortSignal,
  commands: Commands = nativeCommands,
): Promise<unknown> {
  const directory = tempDir(work);
  try {
    if (request.provider === "codex") {
      if (request.effort === "on" || request.effort === "off") {
        throw new HelperError("invalid_request", "Codex does not use a thinking on/off setting.");
      }
      const schemaPath = join(directory, "schema.json");
      const outputPath = join(directory, "cards.json");
      writeFileSync(schemaPath, dumps(request.schema), "utf8");
      const [codex, ...prefix] = commands.codex();
      const result = await runProcess({
        command: codex!,
        args: [...prefix, ...codexArgs({ model: request.model, effort: request.effort, schemaPath, outputPath })],
        stdin: request.prompt,
        cwd: directory,
        timeoutMs: GENERATION_TIMEOUT_MS,
        stdoutLimit: DIAGNOSTIC_LIMIT,
        totalLimit: DIAGNOSTIC_LIMIT,
        signal,
      });
      if (result.code !== 0 || !existsSync(outputPath)) {
        throw new HelperError(
          "failed",
          request.effort
            ? `Codex could not finish with ${EFFORT_LABELS[request.effort] ?? request.effort} reasoning. Check your sign-in and allowance, and that the selected model supports this level. You can retry with Codex default. Completed drafts are preserved.`
            : "Codex could not finish. Check `codex login status` and your usage limit in a terminal, then retry. Completed drafts are preserved.",
        );
      }
      if (statSync(outputPath).size > OUTPUT_LIMIT) {
        throw new HelperError("output_too_large", "Generated output was too large. Try fewer pages.");
      }
      try {
        return JSON.parse(readFileSync(outputPath, "utf8"));
      } catch {
        throw new HelperError("invalid_output", "Codex returned invalid JSON. No cards from this batch were imported.");
      }
    }
    if (claudeIsExternal()) {
      throw new HelperError("auth_required", "Claude Code is configured for an API or another service. Use its normal Claude sign-in.");
    }
    const status = await claudeStatus(work, commands);
    if (status.signedIn !== "yes") {
      throw new HelperError("auth_required", "Connect Claude Code with your Claude account before generating.");
    }
    const [claude, ...prefix] = commands.claude();
    const result = await runProcess({
      command: claude!,
      args: [...prefix, ...claudeArgs(request)],
      stdin: request.prompt,
      cwd: directory,
      env: claudeEnvironment(),
      timeoutMs: GENERATION_TIMEOUT_MS,
      stdoutLimit: OUTPUT_LIMIT,
      totalLimit: DIAGNOSTIC_LIMIT,
      signal,
    });
    if (result.code !== 0) {
      throw new HelperError(
        "failed",
        "Claude Code could not finish. Check your sign-in, allowance, and selected model/effort. Completed drafts are preserved.",
      );
    }
    return parseClaudeEnvelope(result.stdout.toString("utf8"));
  } finally {
    removeDir(directory);
  }
}

/** The CLI's own browser sign-in command (never logout). */
export function loginCommand(provider: Provider, commands: Commands = nativeCommands): { command: string; args: string[]; env?: NodeJS.ProcessEnv } {
  if (provider === "codex") {
    const [codex, ...prefix] = commands.codex();
    return { command: codex!, args: [...prefix, "login"] };
  }
  if (claudeIsExternal()) {
    throw new HelperError("auth_required", "Claude Code is configured for an API or another service. Use its normal Claude sign-in.");
  }
  const [claude, ...prefix] = commands.claude();
  return { command: claude!, args: [...prefix, "auth", "login"], env: claudeEnvironment() };
}

// --- Status and models ---------------------------------------------------

export interface ProviderStatus {
  loggingIn?: boolean;
  installed: boolean;
  signedIn: "yes" | "no" | "unknown";
  message: string;
  login: string;
}

async function quick(command: string, args: string[], work: string, env?: NodeJS.ProcessEnv): Promise<{ code: number | null; text: string }> {
  const directory = tempDir(work);
  try {
    const result = await runProcess({ command, args, cwd: directory, env, timeoutMs: 8000, stdoutLimit: 64 * 1024, totalLimit: 256 * 1024, captureStderr: !env });
    return { code: result.code, text: result.stdout.toString("utf8") };
  } finally {
    removeDir(directory);
  }
}

export async function codexStatus(work: string, commands: Commands = nativeCommands): Promise<ProviderStatus> {
  let command: string[];
  try {
    command = commands.codex();
  } catch {
    return { installed: false, signedIn: "unknown", message: "Codex is not installed or could not be found on this computer.", login: "" };
  }
  try {
    // Raw output may contain parts of an API key: classify, then discard it.
    const { code, text } = await quick(command[0]!, [...command.slice(1), "login", "status"], work);
    const output = text.toLowerCase();
    if (code === 0 && output.includes("logged in using chatgpt")) {
      return { installed: true, signedIn: "yes", message: "Your existing ChatGPT sign-in is ready to use.", login: "" };
    }
    if (code === 0 && output.includes("api key")) {
      return { installed: true, signedIn: "yes", message: "Codex uses an API key, billed separately from your ChatGPT subscription.", login: "" };
    }
    if (output.includes("not logged in")) {
      return { installed: true, signedIn: "no", message: "Sign in to Codex with your ChatGPT account.", login: "codex login" };
    }
  } catch {
    // fall through
  }
  return { installed: true, signedIn: "unknown", message: "Codex did not report a recognized sign-in. Generation may still work.", login: "codex login" };
}

export async function claudeStatus(work = defaultWork(), commands: Commands = nativeCommands): Promise<ProviderStatus> {
  let command: string[];
  try {
    command = commands.claude();
  } catch {
    return { installed: false, signedIn: "unknown", message: "Claude Code is not installed or could not be found on this computer.", login: "" };
  }
  if (claudeIsExternal()) {
    return {
      installed: true,
      signedIn: "no",
      message: "Claude Code is configured for an API or another service. Slanki uses your Claude subscription sign-in.",
      login: "",
    };
  }
  try {
    const { code, text } = await quick(command[0]!, [...command.slice(1), "auth", "status"], work, claudeEnvironment());
    const data = JSON.parse(text) as Record<string, unknown>;
    if (code === 0 && data.loggedIn === true) {
      if (["claude.ai", "oauth"].includes(data.authMethod as string) && [undefined, null, "firstParty"].includes(data.apiProvider as string)) {
        return { installed: true, signedIn: "yes", message: "Your saved Claude sign-in is ready to use.", login: "" };
      }
      return { installed: true, signedIn: "no", message: "Claude Code uses API or external-provider authentication. Sign in with your Claude account instead.", login: "claude auth login" };
    }
    if (data.loggedIn === false) {
      return { installed: true, signedIn: "no", message: "Sign in to Claude Code with your Claude account.", login: "claude auth login" };
    }
  } catch {
    // fall through
  }
  return { installed: true, signedIn: "unknown", message: "Could not check Claude Code sign-in. Update Claude Code if needed.", login: "claude auth login" };
}

export async function discoverModels(provider: Provider, work: string, commands: Commands = nativeCommands): Promise<ModelRow[]> {
  const directory = tempDir(work);
  try {
    if (provider === "codex") {
      const [codex, ...prefix] = commands.codex();
      const session = lineSession(
        codex!,
        [...prefix, "-c", 'model_provider="openai"', "--disable", "apps", "--disable", "multi_agent", "app-server", "--listen", "stdio://"],
        { cwd: directory },
      );
      try {
        session.send({ id: 1, method: "initialize", params: { clientInfo: { name: "slanki", version: "0.1.0" } } });
        const initialized = await session.receive((value) => value.id === 1);
        if ("error" in initialized) throw new HelperError("failed", "Codex could not initialize model discovery. Update Codex and try again.");
        session.send({ method: "initialized", params: {} });
        const rows: unknown[] = [];
        let cursor: unknown = null;
        for (let id = 2; id <= 6; id++) {
          session.send({ id, method: "model/list", params: { limit: 100, includeHidden: false, cursor } });
          const response = ((await session.receive((value) => value.id === id)).result ?? {}) as Record<string, unknown>;
          rows.push(...((response.data as unknown[]) ?? []));
          cursor = response.nextCursor;
          if (!cursor) return normalizeModels(rows, provider);
        }
        throw new HelperError("failed", "Codex returned too many model pages.");
      } finally {
        await session.close();
      }
    }
    if (claudeIsExternal()) {
      throw new HelperError("auth_required", "Claude Code is configured for an API or another service. Use its normal Claude sign-in.");
    }
    const [claude, ...prefix] = commands.claude();
    const session = lineSession(
      claude!,
      [...prefix, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose", ...claudeIsolationArgs()],
      { cwd: directory, env: claudeEnvironment() },
    );
    try {
      // Metadata-only initialize handshake, as the official Agent SDK sends; no model turn.
      session.send({ type: "control_request", request_id: "models", request: { subtype: "initialize", hooks: {}, agents: {}, skills: [] } });
      const response = await session.receive(
        (value) => value.type === "control_response" && (value.response as Record<string, unknown>)?.request_id === "models",
      );
      const payload = ((response.response as Record<string, unknown>)?.response ?? {}) as Record<string, unknown>;
      return normalizeModels(payload.models, provider);
    } finally {
      await session.close();
    }
  } finally {
    removeDir(directory);
  }
}

// --- Model catalogs (sanitized IDs/labels/efforts only) ---------------------

export function defaultWork(): string {
  return join(process.env.SLANKI_HOME ?? join(process.env.USERPROFILE ?? process.env.HOME ?? ".", ".slanki"), "work");
}

export class Catalogs {
  private home: string;
  private commands: Commands;

  constructor(home: string, commands: Commands = nativeCommands) {
    this.home = home;
    this.commands = commands;
  }

  private path(provider: Provider): string {
    return join(this.home, `models-${provider}.json`);
  }

  read(provider: Provider): ModelRow[] | null {
    try {
      const data = JSON.parse(readFileSync(this.path(provider), "utf8")) as { models: ModelRow[] };
      if (!Array.isArray(data.models) || !data.models.length || data.models.length > 201) return null;
      for (const row of data.models) {
        checkedModelId(row.id);
        if (
          typeof row.label !== "string" ||
          !Array.isArray(row.efforts) ||
          row.efforts.some((effort) => !(EFFORTS as readonly string[]).includes(effort)) ||
          !row.efforts.includes(row.default_effort)
        ) {
          return null;
        }
      }
      return data.models;
    } catch {
      return null;
    }
  }

  async refresh(provider: Provider, work: string): Promise<ModelRow[]> {
    const models = await discoverModels(provider, work, this.commands);
    mkdirSync(this.home, { recursive: true });
    const temporary = this.path(provider) + ".tmp";
    writeFileSync(temporary, JSON.stringify({ models, updated_at: Date.now() / 1000 }), "utf8");
    renameSync(temporary, this.path(provider));
    return models;
  }

  /** Port of checked_model_settings: the model and effort must be ones this CLI reported. */
  async checked(provider: Provider, model: unknown, effort: unknown, work: string): Promise<void> {
    checkedModelId(model);
    if (typeof effort !== "string" || !(EFFORTS as readonly string[]).includes(effort)) {
      throw new HelperError("invalid_request", "Choose a supported reasoning level.");
    }
    if (effort === "on" || effort === "off") {
      throw new HelperError("invalid_request", "Thinking on/off is only available for Kimi models that report it.");
    }
    let catalog = this.read(provider);
    if (!catalog && (model || effort)) {
      try {
        catalog = await this.refresh(provider, work);
      } catch {
        catalog = null;
      }
    }
    if (!catalog) {
      // Like Recalloom: Codex's default model needs no catalog; anything else must be reported by the CLI.
      if ((provider === "codex" && !model) || (!model && !effort)) return;
      throw new HelperError("invalid_request", "Refresh models and choose a model supported by this CLI.");
    }
    const item = catalog.find((row) => row.id === model);
    if (!item) throw new HelperError("invalid_request", "Refresh models and choose a model supported by this CLI.");
    if (!item.efforts.includes(effort)) {
      throw new HelperError("invalid_request", "This model does not support that reasoning level. Choose one of its displayed levels.");
    }
  }
}
