// Serve app/dist with the same headers as vercel.json (for previews and e2e tests).
// Usage: node app/scripts/serve.ts [port]
import { existsSync, readFileSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../dist/", import.meta.url));
const config = JSON.parse(readFileSync(new URL("../../vercel.json", import.meta.url), "utf8")) as {
  headers: { source: string; headers: { key: string; value: string }[] }[];
};
const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".json": "application/json",
  ".pdf": "application/pdf",
  ".wasm": "application/wasm",
  ".ttf": "font/ttf",
  ".pfb": "application/octet-stream",
  ".bcmap": "application/octet-stream",
};
const port = Number(process.argv[2] ?? 4173);

function matches(source: string, path: string): boolean {
  const pattern = "^" + source.replace(/\(\.\*\)/g, ".*").replace(/\//g, "\\/") + "$";
  return new RegExp(pattern).test(path);
}

createServer((req, res) => {
  const path = decodeURIComponent((req.url ?? "/").split("?")[0]!);
  let file = normalize(join(root, path === "/" ? "index.html" : path));
  if (!file.startsWith(normalize(root)) || !existsSync(file) || statSync(file).isDirectory()) {
    res.writeHead(404).end("Not found");
    return;
  }
  for (const rule of config.headers) {
    if (matches(rule.source, path)) for (const header of rule.headers) res.setHeader(header.key, header.value);
  }
  res.setHeader("Content-Type", TYPES[extname(file)] ?? "application/octet-stream");
  res.end(readFileSync(file));
}).listen(port, "127.0.0.1", () => console.log(`Serving app/dist with production headers at http://127.0.0.1:${port}/`));
