// Fake Codex / Claude Code for offline tests. Behaviour: FAKE_CLI_MODE =
// cards (default) | invalid | fail | slow. FAKE_CLI_LOG appends one line per run.
import { appendFileSync, writeFileSync } from "node:fs";
import { createInterface } from "node:readline";

const args = process.argv.slice(2);
const mode = process.env.FAKE_CLI_MODE ?? "cards";
const has = (...values) => values.every((value) => args.includes(value));
const log = (kind) => process.env.FAKE_CLI_LOG && appendFileSync(process.env.FAKE_CLI_LOG, kind + "\n");

async function stdinText() {
  let text = "";
  for await (const chunk of process.stdin) text += chunk;
  return text;
}

function respond(prompt) {
  const marker = (label) => {
    const at = prompt.lastIndexOf(label);
    return at < 0 ? null : JSON.parse(prompt.slice(at + label.length).trim());
  };
  const source = marker("UNTRUSTED SOURCE DATA (JSON):\n");
  if (source) {
    if (source[0]?.topics) {
      return { topics: source.map((section, i) => ({ title: `Theme ${i + 1}`, summary: "Combined idea.", priority: "core", source_id: section.topics[0].source_id })) };
    }
    return {
      topics: source
        .filter((page) => page.excerpts.length)
        .slice(0, 2)
        .map((page) => ({ title: `Topic on slide ${page.page}`, summary: "Main idea.", priority: "core", source_id: page.excerpts[0].source_id })),
    };
  }
  const pages = marker("LECTURE PAGE DATA (JSON):\n") ?? [];
  return {
    cards: pages.map((page) => ({
      note_type: "basic",
      front: `What does slide ${page.page} explain?`,
      back: "The idea shown on that slide.",
      page: page.page,
      source_quote: page.text.split("\n").find((line) => line.trim().length > 15) ?? page.text,
    })),
  };
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

if (has("login", "status")) {
  console.log("Logged in using ChatGPT");
} else if (has("auth", "status")) {
  console.log(JSON.stringify({ loggedIn: true, authMethod: "claude.ai", apiProvider: "firstParty" }));
} else if (args.includes("app-server")) {
  createInterface({ input: process.stdin }).on("line", (line) => {
    const message = JSON.parse(line);
    if (message.method === "initialize") console.log(JSON.stringify({ id: message.id, result: {} }));
    if (message.method === "model/list") {
      console.log(
        JSON.stringify({
          id: message.id,
          result: {
            data: [{ model: "gpt-test", displayName: "GPT Test", supportedReasoningEfforts: [{ reasoningEffort: "low" }, { reasoningEffort: "high" }], isDefault: true }],
            nextCursor: null,
          },
        }),
      );
    }
  });
} else if (has("--input-format", "stream-json")) {
  createInterface({ input: process.stdin }).on("line", () => {
    console.log(
      JSON.stringify({
        type: "control_response",
        response: {
          request_id: "models",
          response: {
            models: [
              { value: "default", displayName: "Default", supportedEffortLevels: ["low", "high"] },
              { value: "claude-test", displayName: "Claude Test", supportedEffortLevels: ["low", "high"] },
            ],
          },
        },
      }),
    );
  });
} else {
  const prompt = await stdinText();
  log(args.includes("exec") ? "codex" : "claude");
  if (mode === "slow") await wait(Number(process.env.FAKE_CLI_SLEEP ?? 3000));
  if (mode === "fail") process.exit(1);
  const payload = mode === "invalid" ? "not json" : JSON.stringify(respond(prompt));
  if (args.includes("exec")) {
    writeFileSync(args[args.indexOf("--output-last-message") + 1], payload);
  } else {
    const envelope = mode === "invalid" ? { type: "result", subtype: "success", result: "not json" } : { type: "result", subtype: "success", is_error: false, structured_output: JSON.parse(payload) };
    process.stdout.write(JSON.stringify(envelope));
  }
}
