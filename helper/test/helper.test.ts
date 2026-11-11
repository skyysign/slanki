import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { request as httpRequest } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { SCHEMA } from "../../app/src/core/prompts.ts";
import { HelperError, runProcess } from "../src/processes.ts";
import {
  Catalogs,
  checkedModelId,
  claudeArgs,
  claudeEnvironment,
  claudeIsolationArgs,
  codexArgs,
  generate,
  normalizeModels,
  parseClaudeEnvelope,
  type Commands,
} from "../src/providers.ts";
import { createHelper } from "../src/server.ts";

const golden = JSON.parse(
  readFileSync(new URL("../../tests/fixtures/synthetic/golden/providers.json", import.meta.url), "utf8"),
);
const FAKE = fileURLToPath(new URL("./fixtures/fake-cli.mjs", import.meta.url));
const fakeCommands: Commands = { codex: () => [process.execPath, FAKE], claude: () => [process.execPath, FAKE] };

function outcome(run: () => unknown) {
  try {
    return { ok: run() };
  } catch (error) {
    if (error instanceof HelperError) return error.code === "invalid_output" ? { output_error: error.message } : { error: error.message };
    throw error;
  }
}

describe("provider command lines match Recalloom", () => {
  it("builds the Codex argument list", () => {
    for (const row of golden.codex.filter((r: any) => r.argv)) {
      const args = codexArgs({ model: row.model, effort: row.effort, schemaPath: "<temp>/schema.json", outputPath: "<temp>/cards.json" });
      expect(["CODEX_EXE", ...args]).toEqual(row.argv);
      expect(row.stdin_is_prompt).toBe(true);
    }
  });

  it("builds the Claude argument list with the inline schema", () => {
    for (const row of golden.claude.filter((r: any) => r.argv)) {
      expect(["CLAUDE_EXE", ...claudeArgs({ model: row.model, effort: row.effort, schema: SCHEMA })]).toEqual(row.argv);
    }
    expect(claudeIsolationArgs()).toEqual(golden.claude_isolation_args);
  });

  it("parses Claude result envelopes like Recalloom", () => {
    for (const row of golden.claude.filter((r: any) => r.envelope !== null && r.model !== "unknown-model")) {
      const text = typeof row.envelope === "string" ? row.envelope : JSON.stringify(row.envelope);
      expect(outcome(() => parseClaudeEnvelope(text)), text).toEqual(row.result);
    }
  });

  it("sanitizes the Claude environment", () => {
    const input = Object.fromEntries(golden.claude_environment.input.map((key: string) => [key, "x"]));
    expect(Object.keys(claudeEnvironment(input)).sort()).toEqual(golden.claude_environment.kept);
  });

  it("normalizes model metadata and IDs", () => {
    for (const row of golden.normalize_models) {
      expect(outcome(() => normalizeModels(row.rows, row.provider))).toEqual(row.result);
    }
    for (const row of golden.model_ids) {
      const result = outcome(() => checkedModelId(row.id));
      expect("ok" in result, row.id).toBe("ok" in row.result);
    }
  });
});

describe("running the CLIs", () => {
  const work = mkdtempSync(join(tmpdir(), "slanki-helper-"));
  const prompt = `x\nLECTURE PAGE DATA (JSON):\n${JSON.stringify([{ page: 1, text: "Retrieval practice means trying to recall information." }])}`;
  afterAll(() => rmSync(work, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }));

  for (const provider of ["codex", "claude"] as const) {
    it(`${provider}: returns validated JSON from the CLI`, async () => {
      const result = (await generate({ provider, model: "", effort: "", prompt, schema: SCHEMA }, work, new AbortController().signal, fakeCommands)) as any;
      expect(result.cards[0].source_quote).toBe("Retrieval practice means trying to recall information.");
    });

    it(`${provider}: reports invalid output as retryable`, async () => {
      process.env.FAKE_CLI_MODE = "invalid";
      try {
        await expect(generate({ provider, model: "", effort: "", prompt, schema: SCHEMA }, work, new AbortController().signal, fakeCommands)).rejects.toMatchObject({
          code: "invalid_output",
        });
      } finally {
        delete process.env.FAKE_CLI_MODE;
      }
    });

    it(`${provider}: reports a failed run without retrying`, async () => {
      process.env.FAKE_CLI_MODE = "fail";
      try {
        await expect(generate({ provider, model: "", effort: "low", prompt, schema: SCHEMA }, work, new AbortController().signal, fakeCommands)).rejects.toMatchObject({
          code: "failed",
        });
      } finally {
        delete process.env.FAKE_CLI_MODE;
      }
    });
  }

  it("stops a process on cancel and on timeout", async () => {
    const controller = new AbortController();
    const started = Date.now();
    const pending = runProcess({
      command: process.execPath,
      args: ["-e", "setTimeout(() => {}, 60000)"],
      cwd: work,
      timeoutMs: 60000,
      stdoutLimit: 1000,
      totalLimit: 1000,
      signal: controller.signal,
    });
    setTimeout(() => controller.abort(), 200);
    await expect(pending).rejects.toMatchObject({ code: "canceled" });
    await expect(
      runProcess({ command: process.execPath, args: ["-e", "setTimeout(() => {}, 60000)"], cwd: work, timeoutMs: 300, stdoutLimit: 1000, totalLimit: 1000 }),
    ).rejects.toMatchObject({ code: "timeout" });
    await expect(
      runProcess({ command: process.execPath, args: ["-e", "process.stdout.write('x'.repeat(5000))"], cwd: work, timeoutMs: 10000, stdoutLimit: 1000, totalLimit: 10000 }),
    ).rejects.toMatchObject({ code: "output_too_large" });
    expect(Date.now() - started).toBeLessThan(20000);
  });

  it("discovers models and validates settings against them", async () => {
    const catalogs = new Catalogs(work, fakeCommands);
    expect((await catalogs.refresh("codex", work)).map((m) => m.id)).toEqual(["", "gpt-test"]);
    await expect(catalogs.checked("codex", "gpt-test", "high", work)).resolves.toBeUndefined();
    await expect(catalogs.checked("codex", "gpt-test", "max", work)).rejects.toMatchObject({ code: "invalid_request" });
    await expect(catalogs.checked("codex", "unknown", "", work)).rejects.toMatchObject({ code: "invalid_request" });
    await expect(catalogs.checked("codex", "-x", "", work)).rejects.toMatchObject({ code: "invalid_request" });
    await expect(catalogs.checked("codex", "", 'low"', work)).rejects.toMatchObject({ code: "invalid_request" });
    expect((await catalogs.refresh("claude", work))[0]).toMatchObject({ id: "", efforts: ["", "low", "high"] });
  });
});

describe("helper HTTP security", () => {
  const port = 41000 + Math.floor(Math.random() * 15000);
  const origin = "https://slanki.example";
  const token = "a".repeat(64);
  let release: (() => void) | null = null;
  let aborted = 0;
  let shutdowns = 0;
  const { server, pairing } = createHelper({
    port,
    origins: [origin],
    token,
    staticRoot: null,
    generate: (request, signal) =>
      new Promise((resolve, reject) => {
        signal.addEventListener("abort", () => {
          aborted += 1;
          reject(new HelperError("canceled", "Stopped."));
        });
        release = () => resolve({ cards: [], echo: request.prompt.length });
      }),
    status: async () => ({}),
    models: async () => [],
    checkSettings: async (_provider, model) => {
      checkedModelId(model);
    },
    shutdown: () => (shutdowns += 1),
  });
  beforeAll(() => new Promise<void>((resolve) => server.listen(port, "127.0.0.1", resolve)));
  afterAll(() => new Promise<void>((resolve) => server.close(() => resolve())));

  function call(method: string, path: string, options: { headers?: Record<string, string>; body?: unknown; host?: string } = {}) {
    return new Promise<{ status: number; headers: Record<string, unknown>; body: any }>((resolve, reject) => {
      const body = options.body === undefined ? undefined : typeof options.body === "string" ? options.body : JSON.stringify(options.body);
      const req = httpRequest(
        {
          host: "127.0.0.1",
          port,
          method,
          path,
          headers: {
            Host: options.host ?? `127.0.0.1:${port}`,
            ...(body ? { "Content-Type": "application/json" } : {}),
            ...options.headers,
          },
        },
        (res) => {
          let text = "";
          res.on("data", (chunk) => (text += chunk));
          res.on("end", () => {
            let parsed: unknown = text;
            try {
              parsed = JSON.parse(text);
            } catch {
              // plain text
            }
            resolve({ status: res.statusCode ?? 0, headers: res.headers, body: parsed });
          });
        },
      );
      req.on("error", reject);
      if (body) req.write(body);
      req.end();
    });
  }
  const auth = { Authorization: `Bearer ${token}` };
  const job = (key: string, extra: Record<string, unknown> = {}) => ({
    key,
    provider: "codex",
    model: "",
    effort: "",
    task: "cards",
    prompt: "Prompt text",
    schema: { type: "object" },
    ...extra,
  });

  it("pairs once with a fresh code", async () => {
    const code = pairing.issue();
    const first = await call("POST", "/v1/pair", { body: { code }, headers: { Origin: origin } });
    expect(first.status).toBe(200);
    expect(first.body.token).toBe(token);
    expect(first.headers["access-control-allow-origin"]).toBe(origin);
    expect((await call("POST", "/v1/pair", { body: { code } })).status).toBe(403);
  });

  it("answers pings and issues fresh pairing codes only with the token", async () => {
    expect((await call("GET", "/v1/ping")).status).toBe(401);
    expect((await call("POST", "/v1/pairing-code")).status).toBe(401);
    expect((await call("GET", "/v1/ping", { headers: auth })).status).toBe(204);
    const fresh = await call("POST", "/v1/pairing-code", { headers: auth });
    expect(fresh.status).toBe(200);
    expect((await call("POST", "/v1/pair", { body: { code: fresh.body.code } })).body.token).toBe(token);
    expect((await call("POST", "/v1/pairing-code", { headers: { ...auth, Origin: "https://evil.example" } })).status).toBe(403);
  });

  it("shuts down for a newer copy only with the token", async () => {
    expect((await call("POST", "/v1/shutdown")).status).toBe(401);
    expect((await call("POST", "/v1/shutdown", { headers: { ...auth, Origin: "https://evil.example" } })).status).toBe(403);
    expect((await call("POST", "/v1/shutdown", { headers: auth })).status).toBe(200);
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(shutdowns).toBe(1);
  });

  it("rejects wrong hosts, origins and tokens", async () => {
    expect((await call("GET", "/v1/status", { headers: auth, host: `localhost:${port}` })).status).toBe(421);
    expect((await call("GET", "/v1/status", { headers: auth, host: `evil.example:${port}` })).status).toBe(421);
    expect((await call("GET", "/v1/status", { headers: { ...auth, Origin: "https://evil.example" } })).status).toBe(403);
    expect((await call("GET", "/v1/status", { headers: { ...auth, Origin: "https://slanki-git-branch.vercel.app" } })).status).toBe(403);
    expect((await call("GET", "/v1/status")).status).toBe(401);
    expect((await call("GET", "/v1/status", { headers: { Authorization: "Bearer " + "b".repeat(64) } })).status).toBe(401);
    expect((await call("GET", "/v1/status", { headers: auth })).status).toBe(200);
  });

  it("answers preflights only for allowed origins", async () => {
    const ok = await call("OPTIONS", "/v1/jobs", { headers: { Origin: origin, "Access-Control-Request-Method": "POST" } });
    expect(ok.status).toBe(204);
    expect(ok.headers["access-control-allow-private-network"]).toBe("true");
    expect(ok.headers["access-control-allow-headers"]).toContain("Authorization");
    expect((await call("OPTIONS", "/v1/jobs", { headers: { Origin: "https://evil.example" } })).status).toBe(403);
  });

  it("validates job requests strictly", async () => {
    expect((await call("POST", "/v1/jobs", { headers: auth, body: { ...job("k1"), extra: 1 } })).status).toBe(400);
    expect((await call("POST", "/v1/jobs", { headers: { ...auth, "Content-Type": "text/plain" }, body: "x" })).status).toBe(400);
    expect((await call("POST", "/v1/jobs", { headers: auth, body: job("k1", { prompt: "x".repeat(200001) }) })).status).toBe(413);
    expect((await call("POST", "/v1/jobs", { headers: auth, body: job("bad key!") })).status).toBe(400);
    expect((await call("POST", "/v1/jobs", { headers: auth, body: job("k1", { model: "-rf" }) })).status).toBe(400);
    expect((await call("POST", "/v1/jobs", { headers: auth, body: job("k1", { provider: "bash" }) })).status).toBe(400);
    expect((await call("POST", "/v1/jobs", { headers: auth, body: job("k1", { schema: { big: "x".repeat(17000) } }) })).status).toBe(400);
  });

  it("runs one job at a time, reattaches by key, long-polls and cancels", async () => {
    const first = await call("POST", "/v1/jobs", { headers: auth, body: job("run/1") });
    expect(first.body.status).toBe("running");
    const again = await call("POST", "/v1/jobs", { headers: auth, body: job("run/1") });
    expect(again.body.id).toBe(first.body.id);
    expect((await call("POST", "/v1/jobs", { headers: auth, body: job("run/2") })).status).toBe(409);
    const polling = call("GET", `/v1/jobs/${first.body.id}?wait=5`, { headers: auth });
    setTimeout(() => release?.(), 100);
    const done = await polling;
    expect(done.body).toMatchObject({ status: "done", result: { cards: [], echo: "Prompt text".length } });
    expect((await call("GET", `/v1/jobs/by-key/${encodeURIComponent("run/1")}`, { headers: auth })).body.status).toBe("done");

    const second = await call("POST", "/v1/jobs", { headers: auth, body: job("run/2") });
    expect(second.body.status).toBe("running");
    await call("DELETE", `/v1/jobs/${second.body.id}`, { headers: auth });
    expect(aborted).toBe(1);
    expect((await call("GET", `/v1/jobs/${second.body.id}`, { headers: auth })).body.status).toBe("canceled");
  });

  it("locks out repeated bad tokens", async () => {
    for (let i = 0; i < 10; i++) await call("GET", "/v1/status", { headers: { Authorization: "Bearer wrong" } });
    expect((await call("GET", "/v1/status", { headers: auth })).status).toBe(429);
  });
});

describe("serving the bundled app", () => {
  const root = mkdtempSync(join(tmpdir(), "slanki-static-"));
  writeFileSync(join(root, "index.html"), "<!doctype html><title>Slanki</title>");
  const port = 41000 + Math.floor(Math.random() * 15000) + 1;
  const { server } = createHelper({
    port,
    origins: [`http://127.0.0.1:${port}`],
    token: "c".repeat(64),
    staticRoot: root,
    generate: async () => ({}),
    status: async () => ({}),
    models: async () => [],
    checkSettings: async () => undefined,
  });
  beforeAll(() => new Promise<void>((resolve) => server.listen(port, "127.0.0.1", resolve)));
  afterAll(() => {
    rmSync(root, { recursive: true, force: true });
    return new Promise<void>((resolve) => server.close(() => resolve()));
  });

  it("serves index.html with a strict CSP and refuses path traversal", async () => {
    const page = await fetch(`http://127.0.0.1:${port}/`);
    expect(page.status).toBe(200);
    expect(page.headers.get("content-security-policy")).toContain("connect-src 'self'");
    expect((await fetch(`http://127.0.0.1:${port}/..%2f..%2fpackage.json`)).status).toBe(404);
  });
});
