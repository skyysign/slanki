// Build an .apkg from a Recalloom/Slanki backup with the browser exporter, in Node.
// Used by tools/check_anki.py. Usage:
//   node app/scripts/export-fixture.ts BACKUP.zip OUT.apkg [--timestamp SECONDS]
import { readFileSync, writeFileSync } from "node:fs";
import initSqlJs from "sql.js";
import { readBackup } from "../src/backup/backup.ts";
import { buildApkg } from "../src/export/anki.ts";
import { exportInput } from "../src/export/fromRecords.ts";

const [source, target, flag, value] = process.argv.slice(2);
if (!source || !target || (flag && flag !== "--timestamp")) {
  console.error("Usage: node app/scripts/export-fixture.ts BACKUP.zip OUT.apkg [--timestamp SECONDS]");
  process.exit(2);
}
const SQL = await initSqlJs();
const backup = readBackup(new Uint8Array(readFileSync(source)));
const apkg = buildApkg(
  SQL,
  exportInput(backup.manifest.lecture, backup.manifest.cards, backup.pages),
  value ? Number(value) : Date.now() / 1000,
);
writeFileSync(target, apkg);
console.log(`wrote ${target} (${apkg.length} bytes)`);
