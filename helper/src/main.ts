// `npx slanki`: the local helper that lets the Slanki web app use your own
// Codex or Claude Code sign-in. Lecture files never leave your computer;
// only prompts go to the AI you choose.
import { execFile, execFileSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { request } from "node:http";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { removeDir } from "./processes.ts";
import { API_VERSION, VERSION, createHelper } from "./server.ts";
import { Logins } from "./logins.ts";
import { Catalogs, PROVIDERS, claudeStatus, codexStatus, generate, loginCommand, type Provider } from "./providers.ts";

// Fixed so the browser library (stored per origin) is always found again. SLANKI_PORT is for tests only.
const PORT = Number(process.env.SLANKI_PORT) || 47213;
const APP_ORIGIN = process.env.SLANKI_APP_ORIGIN ?? "https://slanki.vercel.app";
const HELP = `Slanki helper ${VERSION}

Usage: npx slanki@1 [options]

  --local              open the copy of Slanki served by this helper (also for Safari)
  --no-open            do not open the browser
  --reset              forget paired browsers (new connection token)
  --allow-origin URL   also allow this web origin (development only)
  --help               show this help
`;

function nodeOk(): boolean {
  const [major = 0, minor = 0] = process.versions.node.split(".").map(Number);
  return major > 22 || (major === 22 && minor >= 12);
}

function openBrowser(url: string): void {
  const [command, args] =
    process.platform === "win32"
      ? ["rundll32", ["url.dll,FileProtocolHandler", url]]
      : process.platform === "darwin"
        ? ["open", [url]]
        : ["xdg-open", [url]];
  execFile(command, args, { windowsHide: true }, () => undefined);
}

function loadToken(home: string, reset: boolean): string {
  const file = join(home, "helper.json");
  if (!reset && existsSync(file)) {
    try {
      const { token } = JSON.parse(readFileSync(file, "utf8")) as { token?: string };
      if (typeof token === "string" && /^[0-9a-f]{64}$/.test(token)) return token;
    } catch {
      // replaced below
    }
  }
  const token = randomBytes(32).toString("hex");
  writeFileSync(file, JSON.stringify({ token }), { encoding: "utf8", mode: 0o600 });
  return token;
}

/** In the single-executable build (Slanki.exe) the web app is embedded as assets. */
function seaAssets(): ((path: string) => Buffer | null) | undefined {
  const sea = process.getBuiltinModule("node:sea") as typeof import("node:sea") | undefined;
  if (!sea?.isSea()) return undefined;
  return (path) => {
    try {
      return Buffer.from(sea.getAsset(path));
    } catch {
      return null;
    }
  };
}

/** The windowless app has no console: keep the (metadata-only) log in a file instead. */
function logToFile(file: string): void {
  writeFileSync(file, "");
  for (const method of ["log", "warn", "error"] as const) {
    const original = console[method].bind(console);
    console[method] = (...parts: unknown[]) => {
      appendFileSync(file, parts.map(String).join(" ") + "\n");
      original(...parts); // still reaches a parent process that reads stdout
    };
  }
}

/** Without a console, startup errors are shown in a message box. */
function showError(message: string, done: () => void): void {
  if (process.platform !== "win32") return done();
  const script = "Add-Type -AssemblyName PresentationFramework; [void][System.Windows.MessageBox]::Show($env:SLANKI_ERROR, 'Slanki')";
  execFile("powershell", ["-NoProfile", "-NonInteractive", "-Command", script], { env: { ...process.env, SLANKI_ERROR: message }, windowsHide: true }, () => done());
}

/** A request to the copy of Slanki already running on this computer (null when nothing answers). */
function localCall(local: string, method: string, path: string, token: string): Promise<{ status: number; body: any } | null> {
  return new Promise((resolve) => {
    const req = request(`${local}${path}`, { method, headers: token ? { Authorization: `Bearer ${token}` } : {}, timeout: 20000 }, (res) => {
      let text = "";
      res.on("data", (chunk) => (text += chunk));
      res.on("end", () => {
        let body: unknown = null;
        try {
          body = JSON.parse(text);
        } catch {
          // not JSON
        }
        resolve({ status: res.statusCode ?? 0, body });
      });
    });
    req.on("error", () => resolve(null));
    req.on("timeout", () => req.destroy());
    req.end();
  });
}

/** Copies before 0.2.2 have no /v1/shutdown: end the process listening on our port. */
function stopPortOwner(): void {
  if (process.platform !== "win32") return;
  try {
    const table = execFileSync("netstat", ["-ano", "-p", "TCP"], { encoding: "utf8", windowsHide: true });
    // Columns: protocol, local, remote, state (localized, e.g. LISTENING / ABHÖREN), PID.
    // A listening socket is the one whose remote address is 0.0.0.0:0.
    const row = table
      .split(/\r?\n/)
      .map((line) => line.trim().split(/\s+/))
      .find((cols) => cols[1] === `127.0.0.1:${PORT}` && cols[2] === "0.0.0.0:0");
    const pid = Number(row?.at(-1));
    if (pid && pid !== process.pid) execFileSync("taskkill", ["/PID", String(pid), "/F"], { windowsHide: true, stdio: "ignore" });
  } catch {
    // Leave it; the retry below reports the busy port.
  }
}

/**
 * Opened while Slanki already runs. A different (older or newer) version is
 * asked to quit and this copy takes over; the same version is simply shown
 * again in the browser with a fresh pairing link.
 */
async function relaunch(local: string, token: string, takeOver: () => void): Promise<void> {
  const running = await localCall(local, "GET", "/v1/status", token);
  if (running?.status === 200 && running.body?.version !== VERSION) {
    console.log(`Replacing Slanki ${running.body?.version} that is still running.`);
    const quit = await localCall(local, "POST", "/v1/shutdown", token);
    if (quit?.status !== 200) stopPortOwner();
    for (let i = 0; i < 40 && (await localCall(local, "GET", "/", "")); i++) await new Promise((r) => setTimeout(r, 250));
    takeOver();
    return;
  }
  const fresh = await localCall(local, "POST", "/v1/pairing-code", token);
  const code = fresh?.status === 200 && typeof fresh.body?.code === "string" ? fresh.body.code : "";
  openBrowser(`${local}/${code ? `#pair=${PORT}.${code}` : ""}`);
  setTimeout(() => process.exit(0), 1000);
}

function staticRoot(): string | null {
  const here = dirname(fileURLToPath(import.meta.url));
  for (const candidate of [join(here, "app"), join(here, "..", "..", "app", "dist")]) {
    if (existsSync(join(candidate, "index.html"))) return candidate;
  }
  return null;
}

async function main() {
  const args = process.argv.slice(2);
  if (args.includes("--help") || args.includes("-h")) {
    console.log(HELP);
    return;
  }
  if (!nodeOk()) {
    console.error(`Slanki needs Node.js 22.12 or newer (you have ${process.versions.node}). Install it from https://nodejs.org.`);
    process.exit(1);
  }
  const extra: string[] = [];
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--allow-origin" && args[i + 1]) {
      extra.push(new URL(args[++i]!).origin);
    }
  }
  if (extra.length || process.env.SLANKI_APP_ORIGIN) {
    console.warn(`Warning: also accepting requests from ${[...extra, process.env.SLANKI_APP_ORIGIN].filter(Boolean).join(", ")}. Use this for development only.`);
  }
  const home = process.env.SLANKI_HOME ?? join(homedir(), ".slanki");
  const work = join(home, "work");
  removeDir(work); // leftovers from a previous run
  mkdirSync(work, { recursive: true });
  const token = loadToken(home, args.includes("--reset"));
  const catalogs = new Catalogs(home);
  const local = `http://127.0.0.1:${PORT}`;
  const assets = seaAssets();
  if (assets) logToFile(join(home, "slanki.log"));
  const root = assets ? null : staticRoot();
  const logins = new Logins((provider) => loginCommand(provider), work);
  const { server, pairing, jobs, idleMs } = createHelper({
    port: PORT,
    origins: [APP_ORIGIN, local, ...extra],
    token,
    staticRoot: root,
    readAsset: assets,
    generate: (request, signal) => generate(request, work, signal),
    status: async () => {
      const [codex, claude] = await Promise.all([codexStatus(work), claudeStatus(work)]);
      return { codex: { ...codex, loggingIn: logins.isActive("codex") }, claude: { ...claude, loggingIn: logins.isActive("claude") } };
    },
    models: async (provider: Provider, refresh) => (!refresh && catalogs.read(provider)) || catalogs.refresh(provider, work),
    checkSettings: (provider, model, effort) => catalogs.checked(provider, model, effort, work),
    login: { start: (provider) => logins.start(provider), cancel: (provider) => logins.cancel(provider) },
    shutdown: assets ? () => stop() : undefined,
    log: (line) => console.log(`  ${new Date().toLocaleTimeString()}  ${line}`),
  });
  let relaunched = false;
  server.on("error", (error: NodeJS.ErrnoException) => {
    if (assets && error.code === "EADDRINUSE" && !relaunched) {
      relaunched = true;
      // The listen callback below stays registered, so retrying listen() starts this copy normally.
      void relaunch(local, token, () => server.listen(PORT, "127.0.0.1"));
      return;
    }
    const message =
      error.code === "EADDRINUSE"
        ? `Port ${PORT} is already in use. Is the Slanki helper already running in another window? Close it and try again.`
        : `The helper could not start: ${error.message}`;
    console.error(message);
    if (assets) showError(message, () => process.exit(1));
    else process.exit(1);
  });
  server.listen(PORT, "127.0.0.1", async () => {
    const announce = (code: string) => {
      console.log(`\n  Open Slanki:          ${assets ? local : APP_ORIGIN}/#pair=${PORT}.${code}`);
      if (server.listening && root) console.log(`  Or the local copy:    ${local}/#pair=${PORT}.${code}   (for Safari)`);
      console.log(`  Connection code:      ${code}   (valid 2 minutes; press Enter for a new one)\n`);
    };
    console.log(`Slanki helper ${VERSION} (API ${API_VERSION}) is running. Keep this window open while you make cards.`);
    console.log("Your slides stay on this computer; only the prompts go to the AI you choose, through your own account.");
    const code = pairing.issue();
    announce(code);
    const statuses = await Promise.all([codexStatus(work), claudeStatus(work)]);
    PROVIDERS.forEach((provider, i) => {
      const status = statuses[i]!;
      const label = provider === "codex" ? "Codex" : "Claude Code";
      console.log(`  ${label}: ${status.installed ? status.message : "not found"}${status.signedIn === "no" ? "  (sign in from Slanki)" : ""}`);
    });
    if (assets) {
      // No window to close: quit once no Slanki tab has checked in for a while and nothing is running.
      const limit = Number(process.env.SLANKI_IDLE_MS) || 5 * 60_000;
      setInterval(() => {
        if (idleMs() > limit && !jobs.busy() && !PROVIDERS.some((p) => logins.isActive(p))) stop();
      }, Math.min(limit, 30_000));
    }
    console.log("\nPress Ctrl+C to stop.\n");
    const target = assets || (args.includes("--local") && root) ? local : APP_ORIGIN;
    if (!args.includes("--no-open")) openBrowser(`${target}/#pair=${PORT}.${code}`);
    createInterface({ input: process.stdin }).on("line", () => announce(pairing.issue()));
  });
  const stop = () => {
    logins.stopAll();
    jobs.cancelAll();
    server.close();
    process.exit(0);
  };
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);
}

void main();
