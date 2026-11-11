// Shared e2e setup: add the synthetic test lecture through the normal PDF picker
// and its five hand-written drafts through the "Use any chat" route.
import { readFileSync } from "node:fs";

const PDF = "tests/fixtures/synthetic/lecture.pdf";
export const CARDS = readFileSync("tests/fixtures/synthetic/cards.json", "utf8");

export async function addSyntheticLecture(page) {
  await page.setInputFiles("input[accept='application/pdf,.pdf']", PDF);
  await page.waitForSelector(".ws-head button:has-text('Make cards')", { timeout: 30000 });
  await page.click(".ws-head button:has-text('Make cards')");
  const chat = page.locator("dialog[open] details");
  if (!(await chat.getAttribute("open").then((value) => value !== null))) await page.click("dialog[open] details summary");
  await page.fill("dialog[open] details textarea", CARDS);
  await page.click("dialog[open] button:has-text('Add drafts')");
  await page.waitForSelector(".card-pane textarea.question", { timeout: 30000 });
}
