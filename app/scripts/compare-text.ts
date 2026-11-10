// Read-only quality check: compare pdf.js text with the text stored in a backup
// (pdfplumber in Recalloom), and check that saved source quotes still match.
// Prints aggregate numbers only, never lecture content.
// Usage: node app/scripts/compare-text.ts BACKUP.zip [BACKUP.zip ...]
import { readFileSync } from "node:fs";
import { getDocument } from "pdfjs-dist/legacy/build/pdf.mjs";
import { readBackup } from "../src/backup/backup.ts";
import { normalized } from "../src/core/cards.ts";
import { joinTextItems } from "../src/pdf/extract.ts";

function similarity(a: string, b: string): number {
  const words = (text: string) => normalized(text).toLowerCase().split(" ").filter(Boolean);
  const left = words(a);
  const right = new Map<string, number>();
  for (const word of words(b)) right.set(word, (right.get(word) ?? 0) + 1);
  let shared = 0;
  for (const word of left) {
    const count = right.get(word) ?? 0;
    if (count) {
      shared += 1;
      right.set(word, count - 1);
    }
  }
  const total = Math.max(left.length, words(b).length);
  return total ? shared / total : 1;
}

for (const [index, path] of process.argv.slice(2).entries()) {
  const { manifest, pdf } = readBackup(new Uint8Array(readFileSync(path)));
  const task = getDocument({ data: pdf.slice(), useSystemFonts: false });
  const document = await task.promise;
  const texts = new Map<number, string>();
  for (let number = 1; number <= document.numPages; number++) {
    const page = await document.getPage(number);
    texts.set(number, joinTextItems((await page.getTextContent()).items));
  }
  await task.destroy();
  const scores = manifest.pages.map((page) => similarity(page.text, texts.get(page.number) ?? ""));
  const quotes = manifest.cards.filter((card) => card.source_quote.trim());
  const matching = quotes.filter((card) => normalized(texts.get(card.page) ?? "").includes(normalized(card.source_quote)));
  const accepted = quotes.filter((card) => card.status === "accepted");
  const acceptedMatching = accepted.filter((card) => matching.includes(card));
  const below = scores.filter((score) => score < 0.9).length;
  console.log(
    `lecture-${index + 1}: ${manifest.pages.length} pages, mean word overlap ${(
      (scores.reduce((a, b) => a + b, 0) / scores.length) * 100
    ).toFixed(1)}%, ${below} pages below 90%; quotes still found by pdf.js: ${matching.length}/${quotes.length} (accepted ${acceptedMatching.length}/${accepted.length})`,
  );
}
