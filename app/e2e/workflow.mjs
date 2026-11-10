// End-to-end check of the static build in installed Chrome with production headers.
// Start the server first: node app/scripts/serve.ts 4173
// Usage: node app/e2e/workflow.mjs [output-dir]
import { mkdirSync } from "node:fs";
import { chromium } from "playwright";

const out = process.argv[2] ?? "data/e2e";
mkdirSync(out, { recursive: true });
const base = process.env.SLANKI_URL ?? "http://127.0.0.1:4173/";
const failures = [];
const check = (condition, message) => {
  if (!condition) failures.push(message);
  console.log(`${condition ? "  ok  " : "  FAIL"} ${message}`);
};

const browser = await chromium.launch({ channel: "chrome" });
const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true });
const page = await context.newPage();
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(e.message));

const tab = async (name) => Number((await page.textContent(`.tab:has-text("${name}") .muted`)) ?? "-1");
const counts = async () => ({ review: await tab("To review"), ready: await tab("Ready"), aside: await tab("Set aside") });
const body = () => page.click("h1");

await page.goto(base);
check((await page.textContent(".pill"))?.includes("Connect your AI"), "AI pill invites connecting when no helper is paired");
await page.click("text=Try a sample lecture");
await page.waitForSelector(".card-pane textarea.question", { timeout: 30000 });
check((await counts()).review === 5, "sample lecture imports 5 drafts validated against pdf.js text");

await body();
await page.keyboard.press("a");
await page.waitForFunction(() => document.querySelector(".banner.ok")?.textContent?.includes("Kept"));
check((await counts()).ready === 1, "A keeps the card and moves on");
await page.keyboard.press("z");
await page.waitForFunction(() => document.querySelector(".toast")?.textContent?.includes("undone"));
check((await counts()).review === 5 && (await counts()).ready === 0, "Z undoes the last change");

await page.fill(".card-pane textarea.question", "What is retrieval practice, in one sentence?");
await page.click("button:has-text('Keep & next')");
await page.waitForFunction(() => document.querySelector(".tab:nth-child(2) .muted")?.textContent === "1");
await page.click(".tab:has-text('Ready')");
const saved = await page
  .waitForFunction(() => document.querySelector(".card-pane textarea.question")?.value.includes("in one sentence"), null, { timeout: 5000 })
  .then(() => true, () => false);
check(saved, "an edited card is saved when kept");

await page.click(".tab:has-text('To review')");
await body();
await page.keyboard.press("s");
await page.waitForFunction(() => document.querySelector(".banner.ok")?.textContent?.includes("Set aside"));
check((await counts()).aside === 1, "S sets a card aside");

await page.click("button:has-text('Keep all')");
await page.click("dialog[open] button:has-text('Keep all')");
await page.waitForFunction(() => document.querySelector(".toast")?.textContent?.includes("kept"));
const afterKeep = await counts();
check(afterKeep.review === 0 && afterKeep.ready === 4 && afterKeep.aside === 1, "Keep all keeps the remaining drafts only");

await page.click("button[aria-label='More actions']");
await page.click("text=Write a card yourself");
await page.click("dialog[open] button:has-text('Fill in the blank')");
await page.fill("dialog[open] textarea >> nth=0", "Spaced practice distributes study sessions over time.");
await page.evaluate(() => {
  const area = document.querySelector("dialog[open] textarea");
  const start = area.value.indexOf("study sessions");
  area.focus();
  area.setSelectionRange(start, start + "study sessions".length);
});
await page.click("dialog[open] button:has-text('Hide selected words')");
check((await page.inputValue("dialog[open] textarea >> nth=0")).includes("{{c1::study sessions}}"), "Hide selected words makes a cloze");
check(await page.isVisible("dialog[open] .preview-card .cloze"), "manual card shows a live Anki preview");
await page.click("dialog[open] button:has-text('Add card')");
await page.waitForFunction(() => document.querySelector(".toast")?.textContent?.includes("Card added"));
check((await counts()).review === 1, "manual card is added for review");

await page.click("button:has-text('Make cards')");
const chatShown = await page
  .waitForSelector("dialog[open] details[open] summary:has-text('Use any chat')", { timeout: 5000 })
  .then(() => true, () => false);
check(chatShown, "without a helper, the chat route is shown");
await page.fill(
  "dialog[open] textarea",
  '```json\n{"cards": [{"front": "Who reviews cards on a schedule?", "back": "A review schedule decides.", "page": 2, "source_quote": "A review schedule decides when a card should be studied again."}, {"front": "When is the exam?", "back": "Friday", "page": 2, "source_quote": "A review schedule decides when a card should be studied again."}]}\n```',
);
await page.click("dialog[open] button:has-text('Add drafts')");
await page.waitForFunction(() => document.querySelector(".toast")?.textContent?.includes("Added 1 draft"));
check((await page.textContent(".toast")).includes("course logistics"), "chat import skips course logistics");

await page.click("button:has-text('Export to Anki')");
const [deck] = await Promise.all([page.waitForEvent("download"), page.click("dialog[open] button:has-text('Download .apkg')")]);
await deck.saveAs(`${out}/sample.apkg`);
check(deck.suggestedFilename().endsWith(".apkg"), "deck downloads as .apkg");

await page.click("button[aria-label='More actions']");
const [backup] = await Promise.all([page.waitForEvent("download"), page.click("text=Save backup")]);
await backup.saveAs(`${out}/sample-backup.zip`);
check(backup.suggestedFilename().includes("Slanki backup"), "backup downloads");

const before = await counts();
await page.click("button[aria-label='More actions']");
await page.click("text=Delete lecture");
await page.check("dialog[open] input[type=checkbox]");
await page.click("dialog[open] button:has-text('Delete lecture')");
await page.waitForSelector("text=No lectures yet.");
check(true, "lecture deleted after confirmation");
await page.setInputFiles("input[accept='.zip,application/zip']", `${out}/sample-backup.zip`);
await page.waitForSelector(".card-pane, .empty");
const restored = await counts();
check(JSON.stringify(restored) === JSON.stringify(before), "restoring the backup brings back every card and status");

await page.screenshot({ path: `${out}/workspace-desktop.png`, fullPage: true });
await page.setViewportSize({ width: 390, height: 844 });
await page.click(".mobile-switch .tab:has-text('Slide')");
check(await page.isVisible(".slide-pane"), "phone layout switches to the slide");
check(!(await page.isVisible(".card-pane")), "phone layout hides the card while showing the slide");
check(!(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)), "no horizontal overflow on a phone");
await page.screenshot({ path: `${out}/workspace-mobile-slide.png`, fullPage: true });

check(errors.length === 0, `no console errors${errors.length ? ": " + errors.join(" | ") : ""}`);
await browser.close();
if (failures.length) {
  console.error(`${failures.length} check(s) failed`);
  process.exit(1);
}
console.log("Browser workflow passed.");
