// Browser + real helper server + fake CLI: pairing, making cards, reload and
// resume without paying twice, and stopping. Needs `npm run serve` running.
// Usage: node app/e2e/generation.mjs [output-dir]
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { createInterface } from "node:readline";
import { chromium, firefox, webkit } from "playwright";

const out = process.argv[2] ?? "data/e2e";
mkdirSync(out, { recursive: true });
const log = resolve(`${out}/fake-cli.log`);
writeFileSync(log, "");
const failures = [];
const check = (condition, message) => {
  if (!condition) failures.push(message);
  console.log(`${condition ? "  ok  " : "  FAIL"} ${message}`);
};

const helper = spawn(process.execPath, ["helper/test/fake-helper.ts"], {
  env: { ...process.env, FAKE_CLI_MODE: "slow", FAKE_CLI_SLEEP: "2500", FAKE_CLI_LOG: log },
  stdio: ["ignore", "pipe", "inherit"],
});
const code = await new Promise((resolve, reject) => {
  createInterface({ input: helper.stdout }).once("line", (line) => resolve(JSON.parse(line).code));
  helper.once("exit", () => reject(new Error("fake helper exited")));
});
const calls = () => readFileSync(log, "utf8").split("\n").filter(Boolean).length;

const engine = process.env.SLANKI_BROWSER ?? "chrome";
const browser = engine === "firefox" ? await firefox.launch() : engine === "webkit" ? await webkit.launch() : await chromium.launch({ channel: "chrome" });
console.log(`browser: ${engine}`);
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
try {
  await page.goto(`http://127.0.0.1:4173/#pair=47213.${code}`);
  await page.waitForFunction(() => document.querySelector(".pill")?.textContent?.includes("Codex ready"), null, { timeout: 20000 });
  check(true, "pairing link connects the browser to the helper");
  check(!page.url().includes(code), "the pairing code is removed from the address bar");

  await page.click("text=Try a sample lecture");
  await page.waitForSelector(".card-pane textarea.question", { timeout: 30000 });
  await page.click("button:has-text('Make cards')");
  const shows = await page.waitForSelector("dialog[open] .pane .muted:has-text('Codex')", { timeout: 5000 }).then(() => true, () => false);
  check(shows, "Make cards shows the connected AI");
  await page.check("dialog[open] .pane input[type=checkbox]");
  await page.click("dialog[open] .pane button:has-text('Make cards')");
  await page.waitForSelector(".banner.info", { timeout: 10000 });
  check((await page.textContent(".banner.info")).includes("Reading the whole lecture"), "progress shows the whole-lecture reading step");

  // Reload while the AI is still working, then resume.
  await page.waitForTimeout(1000);
  await page.reload();
  await page.waitForSelector("button:has-text('Resume')", { timeout: 20000 });
  check(true, "a run interrupted by reloading becomes resumable");
  await page.waitForFunction(() => document.querySelector(".pill")?.textContent?.includes("Codex ready"), null, { timeout: 20000 });
  await page.click("button:has-text('Resume')");
  const finished = await page
    .waitForSelector(".banner.ok:has-text('drafted')", { timeout: 60000 })
    .then(() => true, async () => {
      console.log("banner after resume:", await page.textContent(".banner").catch(() => "(none)"));
      await page.screenshot({ path: `${out}/generation-resume-failure.png`, fullPage: true });
      return false;
    });
  check(finished, "the resumed run completes");
  check(calls() === 2, `resume reattached to the finished request instead of calling the AI again (${calls()} CLI calls for overview + 1 batch)`);
  const review = Number(await page.textContent(".tab:has-text('To review') .muted"));
  check(review === 7, `two AI drafts were added within the card limit (to review: ${review})`);

  await page.click("button:has-text('Make cards')");
  await page.click("dialog[open] .pane button:has-text('Make cards')");
  await page.waitForSelector(".banner.info button:has-text('Stop')", { timeout: 10000 });
  await page.click(".banner.info button:has-text('Stop')");
  await page.waitForSelector("button:has-text('Resume')", { timeout: 20000 });
  check((await page.textContent(".banner")).includes("Stopped"), "Stop ends the run and offers Resume");
  await page.screenshot({ path: `${out}/generation-desktop-${engine}.png`, fullPage: true });
  check(errors.length === 0, `no page errors${errors.length ? ": " + errors.join(" | ") : ""}`);
} finally {
  await browser.close();
  helper.kill();
}
if (failures.length) {
  console.error(`${failures.length} check(s) failed`);
  process.exit(1);
}
console.log("Generation workflow passed.");
