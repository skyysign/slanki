// Bounded child processes: argument arrays only (never a shell), stdin for
// prompts, output caps, deadlines, and whole-tree termination on Windows.
import { execFile, spawn } from "node:child_process";
import { existsSync, readdirSync, rmSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { delimiter, extname, join } from "node:path";

export class HelperError extends Error {
  code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

const WRAPPERS = new Set([".cmd", ".bat", ".ps1"]);

/** Find an executable on PATH like shutil.which (respecting PATHEXT on Windows). */
export function which(name: string, env: NodeJS.ProcessEnv = process.env): string | null {
  if (name.includes("/") || name.includes("\\")) return existsSync(name) ? name : null;
  const extensions = process.platform === "win32" ? ["", ...(env.PATHEXT ?? ".EXE;.CMD;.BAT").toLowerCase().split(";")] : [""];
  for (const dir of (env.PATH ?? env.Path ?? "").split(delimiter)) {
    if (!dir) continue;
    for (const extension of extensions) {
      const candidate = join(dir, name + extension);
      try {
        if (statSync(candidate).isFile()) return candidate;
      } catch {
        // not here
      }
    }
  }
  return null;
}

function newest(paths: string[]): string | null {
  return paths.sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs)[0] ?? null;
}

/** Native Codex: PATH, or the copy bundled with the VS Code extension. Wrappers are rejected. */
export function codexExecutable(env: NodeJS.ProcessEnv = process.env): string {
  const configured = env.SLANKI_CODEX_BINARY || env.SLIDES_CODEX_BINARY;
  let executable = which(configured || "codex", env);
  if (!configured && (!executable || WRAPPERS.has(extname(executable).toLowerCase()))) {
    const root = join(homedir(), ".vscode", "extensions");
    const candidates: string[] = [];
    try {
      for (const extension of readdirSync(root)) {
        if (!extension.startsWith("openai.chatgpt-")) continue;
        const bin = join(root, extension, "bin");
        for (const platform of existsSync(bin) ? readdirSync(bin) : []) {
          const file = join(bin, platform, process.platform === "win32" ? "codex.exe" : "codex");
          if (platform.startsWith(process.platform === "win32" ? "windows-" : process.platform) && existsSync(file)) {
            candidates.push(file);
          }
        }
      }
    } catch {
      // no VS Code extensions
    }
    executable = newest(candidates) ?? executable;
  }
  if (!executable) {
    throw new HelperError("cli_missing", "Codex was not found. Install the Codex CLI and sign in, or use another chat.");
  }
  if (WRAPPERS.has(extname(executable).toLowerCase())) {
    throw new HelperError("cli_missing", "Set SLANKI_CODEX_BINARY to the native codex executable, not a .cmd wrapper.");
  }
  return executable;
}

/** Native Claude Code: ~/.local/bin, PATH, or the binary inside the npm package. */
export function claudeExecutable(env: NodeJS.ProcessEnv = process.env): string {
  const configured = env.SLANKI_CLAUDE_BINARY || env.SLIDES_CLAUDE_BINARY;
  let executable = which(configured || "claude", env);
  if (!configured) {
    const native = process.platform === "win32" ? "claude.exe" : "claude";
    const candidates = [join(homedir(), ".local", "bin", native)];
    if (executable) {
      // npm installs wrap the native executable; resolve that known package path.
      candidates.push(join(executable, "..", "node_modules", "@anthropic-ai", "claude-code", "bin", native));
    }
    executable = candidates.find((path) => existsSync(path)) ?? executable;
  }
  if (!executable || WRAPPERS.has(extname(executable).toLowerCase())) {
    throw new HelperError("cli_missing", "Claude Code was not found as a native executable. Install Claude Code or set SLANKI_CLAUDE_BINARY.");
  }
  return executable;
}

export interface RunOptions {
  command: string;
  args: readonly string[];
  stdin?: string;
  cwd: string;
  env?: NodeJS.ProcessEnv;
  timeoutMs: number;
  /** Maximum captured stdout bytes. */
  stdoutLimit: number;
  /** Maximum total stdout+stderr bytes (diagnostics are counted, not kept). */
  totalLimit: number;
  /** Keep stderr too (appended to stdout), e.g. for status commands. */
  captureStderr?: boolean;
  signal?: AbortSignal;
}

export interface RunResult {
  code: number | null;
  stdout: Buffer;
}

/** Terminate a process and its children (Windows needs taskkill /T). */
export function killTree(pid: number | undefined): void {
  if (!pid) return;
  if (process.platform === "win32") {
    execFile("taskkill", ["/PID", String(pid), "/T", "/F"], { windowsHide: true }, () => undefined);
  } else {
    try {
      process.kill(-pid, "SIGKILL");
    } catch {
      try {
        process.kill(pid, "SIGKILL");
      } catch {
        // already gone
      }
    }
  }
}

export function runProcess(options: RunOptions): Promise<RunResult> {
  return new Promise((resolve, reject) => {
    if (options.signal?.aborted) {
      reject(new HelperError("canceled", "Stopped."));
      return;
    }
    const child = spawn(options.command, [...options.args], {
      cwd: options.cwd,
      env: options.env ?? process.env,
      shell: false,
      windowsHide: true,
      detached: process.platform !== "win32",
      stdio: ["pipe", "pipe", "pipe"],
    });
    const chunks: Buffer[] = [];
    let captured = 0;
    let total = 0;
    let failure: HelperError | null = null;
    const stop = (error: HelperError) => {
      if (!failure) failure = error;
      killTree(child.pid);
    };
    const timer = setTimeout(
      () => stop(new HelperError("timeout", "The AI took too long (5 minutes). Completed batches are saved; try fewer pages.")),
      options.timeoutMs,
    );
    const onAbort = () => stop(new HelperError("canceled", "Stopped."));
    options.signal?.addEventListener("abort", onAbort);
    child.stdout.on("data", (chunk: Buffer) => {
      total += chunk.length;
      captured += chunk.length;
      if (captured > options.stdoutLimit || total > options.totalLimit) {
        stop(new HelperError("output_too_large", "The AI returned too much output. Try fewer pages."));
      } else {
        chunks.push(chunk);
      }
    });
    child.stderr.on("data", (chunk: Buffer) => {
      total += chunk.length;
      if (total > options.totalLimit) stop(new HelperError("output_too_large", "The AI produced too much diagnostic output. Try fewer pages."));
      else if (options.captureStderr) chunks.push(chunk);
    });
    child.on("error", (error: NodeJS.ErrnoException) => {
      stop(new HelperError(error.code === "ENOENT" ? "cli_missing" : "failed", "The AI command could not be started."));
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      options.signal?.removeEventListener("abort", onAbort);
      if (failure) reject(failure);
      else resolve({ code, stdout: Buffer.concat(chunks) });
    });
    child.stdin.on("error", () => undefined);
    child.stdin.end(options.stdin ?? "", "utf8");
  });
}

export interface LineSession {
  send(message: unknown): void;
  receive(matches: (message: Record<string, unknown>) => boolean): Promise<Record<string, unknown>>;
  /** Stop the CLI and wait (briefly) until it has exited. */
  close(): Promise<void>;
}

/** Remove a temporary directory; Windows may hold it briefly after a kill. Never throws. */
export function removeDir(path: string): void {
  try {
    rmSync(path, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
  } catch {
    // Left for the next start-up cleanup.
  }
}

/**
 * NDJSON metadata exchange (model discovery). The CLI may not ask us to do
 * anything: any request from it ends the session. Bounded lines and time.
 */
export function lineSession(command: string, args: readonly string[], options: { cwd: string; env?: NodeJS.ProcessEnv; timeoutMs?: number }): LineSession {
  const child = spawn(command, [...args], {
    cwd: options.cwd,
    env: options.env ?? process.env,
    shell: false,
    windowsHide: true,
    detached: process.platform !== "win32",
    stdio: ["pipe", "pipe", "ignore"],
  });
  const deadline = Date.now() + (options.timeoutMs ?? 15000);
  const queue: Record<string, unknown>[] = [];
  let waiting: (() => void) | null = null;
  let ended = false;
  let exited = false;
  const exit = new Promise<void>((resolve) => child.on("close", () => {
    exited = true;
    resolve();
  }));
  let buffer = "";
  let total = 0;
  const finish = () => {
    ended = true;
    waiting?.();
  };
  child.stdout.setEncoding("utf8");
  child.stdout.on("data", (text: string) => {
    total += text.length;
    buffer += text;
    if (total > 2 * 1024 * 1024 || buffer.length > 1024 * 1024) {
      finish();
      killTree(child.pid);
      return;
    }
    let newline: number;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (!line) continue;
      try {
        const value = JSON.parse(line);
        if (value && typeof value === "object" && !Array.isArray(value)) queue.push(value);
      } catch {
        finish();
      }
    }
    waiting?.();
  });
  child.on("close", finish);
  child.on("error", finish);
  child.stdin.on("error", () => undefined);
  const failure = () =>
    new HelperError("failed", "Could not read the CLI's model list. Check its installation and sign-in, then refresh models.");
  return {
    send(message) {
      if (!ended) child.stdin.write(JSON.stringify(message) + "\n");
    },
    async receive(matches) {
      for (;;) {
        while (queue.length) {
          const message = queue.shift()!;
          if (matches(message)) return message;
          // No host action or approval is part of model discovery.
          if (message.type === "control_request" || ("method" in message && "id" in message)) throw failure();
        }
        if (ended || Date.now() > deadline) throw failure();
        await new Promise<void>((resolve) => {
          waiting = resolve;
          setTimeout(resolve, Math.max(10, Math.min(200, deadline - Date.now())));
        });
        waiting = null;
      }
    },
    async close() {
      ended = true;
      child.stdin.end();
      if (!exited) killTree(child.pid);
      await Promise.race([exit, new Promise((resolve) => setTimeout(resolve, 3000))]);
    },
  };
}
