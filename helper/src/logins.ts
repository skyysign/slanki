// Start each CLI's own browser sign-in (OpenAI / Anthropic) on request.
// One attempt per provider, cancellable, ten-minute limit. Never logs out.
import { spawn } from "node:child_process";
import { killTree } from "./processes.ts";
import type { Provider } from "./providers.ts";

export interface LoginCommand {
  command: string;
  args: string[];
  env?: NodeJS.ProcessEnv;
}

const LIMIT_MS = 10 * 60 * 1000;

export class Logins {
  private active = new Map<Provider, { pid: number | undefined; timer: ReturnType<typeof setTimeout> }>();
  private resolve: (provider: Provider) => LoginCommand;
  private cwd: string;

  constructor(resolve: (provider: Provider) => LoginCommand, cwd: string) {
    this.resolve = resolve;
    this.cwd = cwd;
  }

  isActive(provider: Provider): boolean {
    return this.active.has(provider);
  }

  start(provider: Provider): void {
    if (this.active.has(provider)) return;
    const { command, args, env } = this.resolve(provider);
    const child = spawn(command, args, {
      cwd: this.cwd,
      env: env ?? process.env,
      shell: false,
      windowsHide: true,
      detached: process.platform !== "win32",
      stdio: "ignore",
    });
    const timer = setTimeout(() => this.cancel(provider), LIMIT_MS);
    const done = () => {
      clearTimeout(timer);
      if (this.active.get(provider)?.pid === child.pid) this.active.delete(provider);
    };
    child.on("exit", done);
    child.on("error", done);
    this.active.set(provider, { pid: child.pid, timer });
  }

  cancel(provider: Provider): void {
    const attempt = this.active.get(provider);
    if (!attempt) return;
    clearTimeout(attempt.timer);
    killTree(attempt.pid);
    this.active.delete(provider);
  }

  stopAll(): void {
    for (const provider of [...this.active.keys()]) this.cancel(provider);
  }
}
