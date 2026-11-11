// The helper's local HTTP API. Bound to 127.0.0.1 only; every request is
// checked for the exact Host, an allowed Origin and the pairing token.
import { randomBytes, timingSafeEqual } from "node:crypto";
import { existsSync, readFileSync, statSync } from "node:fs";
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { extname, join, normalize } from "node:path";
import { Jobs, type JobView } from "./jobs.ts";
import { HelperError } from "./processes.ts";
import { PROVIDERS, type GenerationRequest, type ModelRow, type Provider, type ProviderStatus } from "./providers.ts";

export const API_VERSION = 1;
export const VERSION = "0.1.0";
const MAX_BODY = 1024 * 1024;
const MAX_PROMPT = 200_000;
const MAX_SCHEMA = 16 * 1024;
const KEY = /^[A-Za-z0-9:/._-]{1,200}$/;
const CODE_TTL_MS = 120_000;

export interface HelperOptions {
  port: number;
  origins: string[];
  token: string;
  staticRoot: string | null;
  /** Single-executable build: reads app files embedded in the binary. */
  readAsset?: (path: string) => Buffer | null;
  generate: (request: GenerationRequest, signal: AbortSignal) => Promise<unknown>;
  status: () => Promise<Partial<Record<Provider, ProviderStatus>>>;
  models: (provider: Provider, refresh: boolean) => Promise<ModelRow[]>;
  checkSettings: (provider: Provider, model: string, effort: string) => Promise<void>;
  /** Start or cancel the CLI's own browser sign-in. */
  login?: { start: (provider: Provider) => void; cancel: (provider: Provider) => void };
  log?: (line: string) => void;
  now?: () => number;
}

export class Pairing {
  private codes = new Map<string, number>();
  private now: () => number;

  constructor(now: () => number = Date.now) {
    this.now = now;
  }

  issue(): string {
    const code = randomBytes(9).toString("base64url");
    this.codes.set(code, this.now() + CODE_TTL_MS);
    return code;
  }

  consume(code: unknown): boolean {
    if (typeof code !== "string") return false;
    const expires = this.codes.get(code);
    this.codes.delete(code);
    return expires !== undefined && expires >= this.now();
  }
}

const STATUS: Record<string, number> = {
  invalid_request: 400,
  unauthorized: 401,
  forbidden: 403,
  not_found: 404,
  busy: 409,
  too_large: 413,
  rate_limited: 429,
  cli_missing: 424,
  auth_required: 424,
};

const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".json": "application/json",
  ".pdf": "application/pdf",
  ".wasm": "application/wasm",
  ".ttf": "font/ttf",
};

const STATIC_CSP =
  "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; img-src 'self' blob: data:; font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'";

function sameToken(given: string, expected: string): boolean {
  const a = Buffer.from(given);
  const b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}

function readBody(req: IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const type = (req.headers["content-type"] ?? "").split(";")[0]!.trim().toLowerCase();
    if (type !== "application/json") {
      reject(new HelperError("invalid_request", "Send JSON."));
      return;
    }
    const chunks: Buffer[] = [];
    let size = 0;
    req.on("data", (chunk: Buffer) => {
      size += chunk.length;
      if (size > MAX_BODY) {
        reject(new HelperError("too_large", "The request is too large."));
        req.destroy();
      } else {
        chunks.push(chunk);
      }
    });
    req.on("end", () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")));
      } catch {
        reject(new HelperError("invalid_request", "Send valid JSON."));
      }
    });
    req.on("error", () => reject(new HelperError("invalid_request", "The request could not be read.")));
  });
}

const exactKeys = (value: unknown, keys: string[]): value is Record<string, unknown> =>
  !!value &&
  typeof value === "object" &&
  !Array.isArray(value) &&
  Object.keys(value).length === keys.length &&
  keys.every((key) => Object.hasOwn(value, key));

function codePoints(text: string): number {
  let count = 0;
  for (const _ of text) count++;
  return count;
}

export function createHelper(options: HelperOptions): { server: Server; pairing: Pairing; jobs: Jobs } {
  const now = options.now ?? Date.now;
  const pairing = new Pairing(now);
  const jobs = new Jobs(now);
  const origins = new Set(options.origins);
  const host = `127.0.0.1:${options.port}`;
  let failures: number[] = [];
  const log = options.log ?? (() => undefined);

  const send = (res: ServerResponse, status: number, body: unknown) => {
    res.statusCode = status;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.end(JSON.stringify(body));
  };
  const fail = (res: ServerResponse, error: HelperError) =>
    send(res, STATUS[error.code] ?? 502, { error: { code: error.code, message: error.message } });

  const readStatic = (path: string): Buffer | null => {
    const relative = path === "/" ? "index.html" : decodeURIComponent(path).replace(/^\/+/, "");
    if (options.readAsset) return relative.split("/").includes("..") ? null : options.readAsset(relative);
    const root = options.staticRoot;
    const file = root && normalize(join(root, relative));
    if (!root || !file || !file.startsWith(normalize(root)) || !existsSync(file) || statSync(file).isDirectory()) return null;
    return readFileSync(file);
  };

  const serveStatic = (path: string, res: ServerResponse) => {
    const body = readStatic(path);
    if (!body) {
      res.statusCode = 404;
      res.end("Not found");
      return;
    }
    res.setHeader("Content-Type", TYPES[extname(path === "/" ? "index.html" : path)] ?? "application/octet-stream");
    res.setHeader("Content-Security-Policy", STATIC_CSP);
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Referrer-Policy", "no-referrer");
    res.setHeader("Cache-Control", path.startsWith("/assets/") ? "public, max-age=31536000, immutable" : "no-cache");
    res.end(body);
  };

  const authorized = (req: IncomingMessage): boolean => {
    const header = req.headers.authorization ?? "";
    const ok = header.startsWith("Bearer ") && sameToken(header.slice(7), options.token);
    if (!ok) failures.push(now());
    return ok;
  };

  const api = async (req: IncomingMessage, res: ServerResponse, url: URL) => {
    failures = failures.filter((time) => now() - time < 60_000);
    if (failures.length >= 10) throw new HelperError("rate_limited", "Too many attempts. Wait a minute and try again.");
    const { pathname } = url;
    if (pathname === "/v1/pair" && req.method === "POST") {
      const body = await readBody(req);
      if (!exactKeys(body, ["code"]) || !pairing.consume(body.code)) {
        failures.push(now());
        throw new HelperError("forbidden", "This connection code is wrong or expired. Press Enter in the helper window for a new one.");
      }
      send(res, 200, { token: options.token });
      return;
    }
    if (!authorized(req)) throw new HelperError("unauthorized", "Pair this browser with the helper first.");
    if (pathname === "/v1/status" && req.method === "GET") {
      send(res, 200, { apiVersion: API_VERSION, version: VERSION, providers: await options.status() });
      return;
    }
    const models = /^\/v1\/providers\/([a-z]+)\/models$/.exec(pathname);
    if (models && req.method === "GET") {
      const provider = models[1] as Provider;
      if (!PROVIDERS.includes(provider)) throw new HelperError("not_found", "Unknown AI.");
      send(res, 200, { models: await options.models(provider, url.searchParams.get("refresh") === "1") });
      return;
    }
    const login = /^\/v1\/providers\/([a-z]+)\/login$/.exec(pathname);
    if (login && (req.method === "POST" || req.method === "DELETE")) {
      const provider = login[1] as Provider;
      if (!PROVIDERS.includes(provider) || !options.login) throw new HelperError("not_found", "Unknown AI.");
      if (req.method === "POST") options.login.start(provider);
      else options.login.cancel(provider);
      send(res, 200, { ok: true });
      return;
    }
    if (pathname === "/v1/jobs" && req.method === "POST") {
      const body = await readBody(req);
      if (!exactKeys(body, ["key", "provider", "model", "effort", "task", "prompt", "schema"])) {
        throw new HelperError("invalid_request", "Unexpected request fields.");
      }
      const { key, provider, model, effort, task, prompt, schema } = body;
      if (typeof key !== "string" || !KEY.test(key)) throw new HelperError("invalid_request", "Invalid job key.");
      if (typeof provider !== "string" || !PROVIDERS.includes(provider as Provider)) throw new HelperError("invalid_request", "Unknown AI.");
      if (task !== "cards" && task !== "overview") throw new HelperError("invalid_request", "Unknown task.");
      if (typeof prompt !== "string" || !prompt || codePoints(prompt) > MAX_PROMPT) {
        throw new HelperError("too_large", "This generation request is too large. Saved progress is preserved.");
      }
      if (!schema || typeof schema !== "object" || Array.isArray(schema) || JSON.stringify(schema).length > MAX_SCHEMA) {
        throw new HelperError("invalid_request", "Invalid output schema.");
      }
      await options.checkSettings(provider as Provider, model as string, effort as string);
      const existing = jobs.byKey(key);
      const job =
        existing && existing.status !== "failed" && existing.status !== "canceled"
          ? existing
          : jobs.start(key, provider, (signal) =>
              options.generate({ provider: provider as Provider, model: model as string, effort: effort as string, prompt, schema }, signal),
            );
      send(res, 200, jobs.view(job));
      return;
    }
    const byKey = /^\/v1\/jobs\/by-key\/(.+)$/.exec(pathname);
    if (byKey && req.method === "GET") {
      const job = jobs.byKey(decodeURIComponent(byKey[1]!));
      if (!job) throw new HelperError("not_found", "No such job.");
      send(res, 200, jobs.view(job));
      return;
    }
    const jobPath = /^\/v1\/jobs\/([0-9a-f-]{36})$/.exec(pathname);
    if (jobPath) {
      const job = jobs.get(jobPath[1]!);
      if (!job) throw new HelperError("not_found", "No such job.");
      if (req.method === "GET") {
        const wait = Math.min(25, Math.max(0, Number(url.searchParams.get("wait") ?? 0) || 0));
        if (wait) await jobs.wait(job, wait * 1000);
        send(res, 200, jobs.view(job) satisfies JobView);
        return;
      }
      if (req.method === "DELETE") {
        jobs.cancel(job.id);
        send(res, 200, { ok: true });
        return;
      }
    }
    throw new HelperError("not_found", "Unknown request.");
  };

  const server = createServer((req, res) => {
    const started = now();
    const url = new URL(req.url ?? "/", `http://${host}`);
    const route = url.pathname.replace(/[0-9a-f-]{36}/g, ":id").replace(/by-key\/.+/, "by-key/:key");
    res.on("finish", () => {
      if (url.pathname.startsWith("/v1/")) log(`${req.method} ${route} ${res.statusCode} ${now() - started}ms`);
    });
    // Only this exact host: blocks DNS-rebinding pages that resolve to 127.0.0.1.
    if (req.headers.host !== host) {
      res.statusCode = 421;
      res.end("Wrong host");
      return;
    }
    const origin = req.headers.origin;
    if (origin !== undefined && !origins.has(origin)) {
      res.statusCode = 403;
      res.end("Origin not allowed");
      return;
    }
    if (origin) {
      res.setHeader("Access-Control-Allow-Origin", origin);
      res.setHeader("Vary", "Origin");
    }
    if (req.method === "OPTIONS") {
      if (!origin) {
        res.statusCode = 403;
        res.end();
        return;
      }
      res.statusCode = 204;
      res.setHeader("Access-Control-Allow-Methods", "GET, POST, DELETE");
      res.setHeader("Access-Control-Allow-Headers", "Authorization, Content-Type");
      res.setHeader("Access-Control-Max-Age", "600");
      res.setHeader("Access-Control-Allow-Private-Network", "true");
      res.end();
      return;
    }
    if (!url.pathname.startsWith("/v1/")) {
      if (req.method !== "GET" && req.method !== "HEAD") {
        res.statusCode = 405;
        res.end();
        return;
      }
      serveStatic(url.pathname, res);
      return;
    }
    api(req, res, url).catch((error: unknown) => {
      fail(res, error instanceof HelperError ? error : new HelperError("failed", "The helper hit an unexpected problem."));
    });
  });
  server.on("close", () => jobs.cancelAll());
  return { server, pairing, jobs };
}
