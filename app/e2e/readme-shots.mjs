// Screenshots for the README, taken from the built Slanki executable with the
// synthetic lecture (no real data). Usage: npm run build:exe && node app/e2e/readme-shots.mjs
import { spawn } from "node:child_process";
import { copyFileSync, mkdtempSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright";
import { CARDS } from "./fixture.mjs";

const exe = process.platform === "win32" ? "helper/dist/exe/Slanki.exe" : "helper/dist/exe/slanki";
const out = "docs/screenshots";
mkdirSync(out, { recursive: true });

const child = spawn(exe, ["--no-open"], { env: { ...process.env, SLANKI_HOME: mkdtempSync(join(tmpdir(), "slanki-")) } });
const code = await new Promise((resolve, reject) => {
  let text = "";
  child.stdout.on("data", (chunk) => {
    text += chunk;
    const match = /#pair=47213\.([A-Za-z0-9_-]+)/.exec(text);
    if (match) resolve(match[1]);
  });
  child.on("exit", () => reject(new Error(`Slanki exited:\n${text}`)));
});

const browser = await chromium.launch({ channel: "chrome" });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 1 });
  await page.goto(`http://127.0.0.1:47213/#pair=47213.${code}`);
  await page.waitForSelector("text=Drop a lecture PDF", { timeout: 20000 }).catch(() => undefined);
  await page.screenshot({ path: `${out}/library.png` });
  const pdf = join(mkdtempSync(join(tmpdir(), "slanki-pdf-")), "Memory and learning.pdf");
  copyFileSync("tests/fixtures/synthetic/lecture.pdf", pdf);
  await page.setInputFiles("input[accept='application/pdf,.pdf']", pdf);
  await page.click(".ws-head button:has-text('Make cards')", { timeout: 30000 });
  if ((await page.locator("dialog[open] details").getAttribute("open")) === null) await page.click("dialog[open] details summary");
  await page.fill("dialog[open] details textarea", CARDS);
  await page.click("dialog[open] button:has-text('Add drafts')");
  await page.waitForSelector(".card-pane textarea.question", { timeout: 30000 });
  await page.click(".tab:has-text('To review')");
  await page.waitForFunction(() => !document.body.textContent.includes("Added 5 drafts"), null, { timeout: 20000 });
  await page.screenshot({ path: `${out}/review.png` });
  await page.click(".pill");
  await page.waitForSelector("dialog[open] .choice", { timeout: 20000 });
  await page.waitForFunction(() => !document.querySelector("dialog[open]")?.textContent?.includes("Checking…"), null, { timeout: 30000 });
  await page.locator("dialog[open]").screenshot({ path: `${out}/connect-ai.png` });
  console.log(`screenshots written to ${out}/`);
} finally {
  await browser.close();
  child.kill();
}
