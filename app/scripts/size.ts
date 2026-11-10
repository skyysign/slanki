// Fails when the build grows past the budgets in the Slanki plan.
// Run after `npm run build`: node app/scripts/size.ts
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const dist = fileURLToPath(new URL("../dist/", import.meta.url));
const files: string[] = [];
const walk = (dir: string) => {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    statSync(path).isDirectory() ? walk(path) : files.push(path);
  }
};
walk(dist);
const total = files.reduce((sum, file) => sum + statSync(file).size, 0);
const html = readFileSync(join(dist, "index.html"), "utf8");
const initial = [...html.matchAll(/(?:src|href)="\.\/(assets\/[^"]+\.(?:js|css))"/g)].map((m) => join(dist, m[1]!));
const initialGzip = initial.reduce((sum, file) => sum + gzipSync(readFileSync(file)).length, 0);
const kb = (bytes: number) => `${(bytes / 1024).toFixed(1)} KB`;
console.log(`initial download (gzip): ${kb(initialGzip)} in ${initial.length} files`);
console.log(`whole deployment: ${kb(total)} in ${files.length} files`);
const problems = [
  initialGzip > 150 * 1024 && `initial download exceeds 150 KB gzip`,
  total > 6 * 1024 * 1024 && `deployment exceeds 6 MB`,
].filter(Boolean);
if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
