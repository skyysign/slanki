// Build a double-clickable Slanki executable for this platform: Node, the
// helper and the whole web app in one file (Node single-executable app).
// Run `npm run build` first. Output: helper/dist/exe/Slanki(.exe).
// On Windows it gets the Slanki icon and runs without a console window
// (pass --console to keep one for debugging).
import { execFileSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { rcedit } from "rcedit";

const here = (path: string) => fileURLToPath(new URL(path, import.meta.url));
const app = here("./dist/app");
if (!existsSync(join(app, "index.html"))) throw new Error("Run `npm run build` first.");
const out = here("./dist/exe");
rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });

const main = join(out, "slanki.cjs");
await build({
  entryPoints: [here("./src/main.ts")],
  outfile: main,
  bundle: true,
  platform: "node",
  format: "cjs",
  target: "node24",
  legalComments: "none",
  logLevel: "error",
});

const assets: Record<string, string> = {};
const walk = (dir: string) => {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full);
    else assets[relative(app, full).split("\\").join("/")] = full;
  }
};
walk(app);

const blob = join(out, "sea.blob");
const config = join(out, "sea-config.json");
writeFileSync(config, JSON.stringify({ main, output: blob, disableExperimentalSEAWarning: true, useCodeCache: false, useSnapshot: false, assets }));
execFileSync(process.execPath, ["--experimental-sea-config", config], { stdio: "inherit" });

const mac = process.platform === "darwin";
const exe = join(out, process.platform === "win32" ? "Slanki.exe" : "slanki");
copyFileSync(process.execPath, exe);
if (mac) execFileSync("codesign", ["--remove-signature", exe]);
const windows = process.platform === "win32";
if (windows) {
  const version = JSON.parse(readFileSync(here("./package.json"), "utf8")).version as string;
  await rcedit(exe, {
    icon: here("./slanki.ico"),
    "file-version": version,
    "product-version": version,
    "version-string": { ProductName: "Slanki", FileDescription: "Slanki", OriginalFilename: "Slanki.exe", InternalName: "Slanki", CompanyName: "Slanki", LegalCopyright: "" },
  });
}
execFileSync(
  process.execPath,
  [
    here("../node_modules/postject/dist/cli.js"),
    exe,
    "NODE_SEA_BLOB",
    blob,
    "--sentinel-fuse",
    "NODE_SEA_FUSE_fce680ab2cc467b6e072b8b5df1996b2",
    ...(mac ? ["--macho-segment-name", "NODE_SEA"] : []),
  ],
  { stdio: "inherit" },
);
if (mac) execFileSync("codesign", ["--sign", "-", exe]);
if (windows && !process.argv.includes("--console")) {
  // PE optional header Subsystem: 2 = Windows GUI (no console window), 3 = console.
  const bytes = readFileSync(exe);
  const pe = bytes.readUInt32LE(0x3c);
  if (bytes.readUInt32LE(pe) !== 0x4550) throw new Error("Not a PE file");
  bytes.writeUInt16LE(2, pe + 24 + 68);
  writeFileSync(exe, bytes);
}
for (const temp of [main, blob, config]) rmSync(temp);
console.log(`built ${exe} (${Math.round(statSync(exe).size / 1e6)} MB, ${Object.keys(assets).length} app files embedded)`);
