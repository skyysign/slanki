// The real helper server wired to the fake CLI, for browser tests.
// Prints {"code": "..."} on its first line. Env: FAKE_CLI_MODE, FAKE_CLI_SLEEP, FAKE_CLI_LOG.
import { randomBytes } from "node:crypto";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { Catalogs, claudeStatus, codexStatus, generate, type Commands } from "../src/providers.ts";
import { createHelper } from "../src/server.ts";

const FAKE = fileURLToPath(new URL("./fixtures/fake-cli.mjs", import.meta.url));
const commands: Commands = { codex: () => [process.execPath, FAKE], claude: () => [process.execPath, FAKE] };
const home = mkdtempSync(join(tmpdir(), "slanki-fake-helper-"));
const work = join(home, "work");
const catalogs = new Catalogs(home, commands);
const port = 47213;
const { server, pairing } = createHelper({
  port,
  origins: [process.env.SLANKI_TEST_ORIGIN ?? "http://127.0.0.1:4173", `http://127.0.0.1:${port}`],
  token: randomBytes(32).toString("hex"),
  staticRoot: null,
  generate: (request, signal) => generate(request, work, signal, commands),
  status: async () => ({ codex: await codexStatus(work, commands), claude: await claudeStatus(work, commands) }),
  models: async (provider, refresh) => (!refresh && catalogs.read(provider)) || catalogs.refresh(provider, work),
  checkSettings: (provider, model, effort) => catalogs.checked(provider, model, effort, work),
});
server.listen(port, "127.0.0.1", () => console.log(JSON.stringify({ code: pairing.issue() })));
process.on("SIGTERM", () => server.close(() => process.exit(0)));
