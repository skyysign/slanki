import { chromium } from "playwright";
const shots = process.argv[2] ?? "data/screenshots/slanki";
const browser = await chromium.launch({ channel: "chrome" });
const errors = [];
for (const [name, viewport] of [["desktop", { width: 1280, height: 860 }], ["mobile", { width: 390, height: 844 }]]) {
  const context = await browser.newContext({ viewport, acceptDownloads: true });
  const page = await context.newPage();
  page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") errors.push(`${name} console ${m.type()}: ${m.text()}`); });
  page.on("pageerror", (e) => errors.push(`${name} pageerror: ${e.message}`));
  await page.goto("http://127.0.0.1:4173/");
  await page.waitForSelector("text=Turn lecture slides into Anki cards");
  await page.screenshot({ path: `${shots}/library-empty-${name}.png`, fullPage: true });
  await page.click("text=Try a sample lecture");
  await page.waitForSelector(".card-pane textarea.question", { timeout: 30000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${shots}/workspace-${name}.png`, fullPage: true });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  if (overflow) errors.push(`${name}: horizontal overflow`);
  const counts = await page.textContent(".tabs");
  console.log(name, "tabs:", counts?.replace(/\s+/g, " "));
  await context.close();
}
await browser.close();
console.log(errors.length ? errors.join("\n") : "no console errors");
