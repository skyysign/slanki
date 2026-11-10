// Bundle the helper into one dependency-free file and include the built web
// app so `npx slanki` can also serve it locally (Safari fallback).
import { cpSync, existsSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const here = (path: string) => fileURLToPath(new URL(path, import.meta.url));
rmSync(here("./dist"), { recursive: true, force: true });
await build({
  entryPoints: [here("./src/main.ts")],
  outfile: here("./dist/slanki.mjs"),
  bundle: true,
  platform: "node",
  format: "esm",
  target: "node22",
  banner: { js: "#!/usr/bin/env node" },
  legalComments: "none",
});
const app = here("../app/dist");
if (!existsSync(app)) throw new Error("Build the web app first: npm run build --workspace app");
cpSync(app, here("./dist/app"), { recursive: true });
console.log("helper built: helper/dist/slanki.mjs + helper/dist/app");
