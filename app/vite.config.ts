import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";

const PDFJS = fileURLToPath(new URL("../node_modules/pdfjs-dist/", import.meta.url));
const ASSET_DIRS = ["cmaps", "standard_fonts", "wasm"];
// PDF scripting (QuickJS) and no-wasm fallbacks are never used by Slanki.
const SKIP = /quickjs|nowasm_fallback/;
const TYPES: Record<string, string> = { ".wasm": "application/wasm", ".bcmap": "application/octet-stream" };

/** Serve and emit pdf.js fonts, CMaps and wasm decoders from the app's own origin. */
function pdfjsAssets(): Plugin {
  return {
    name: "slanki-pdfjs-assets",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = req.url?.split("?")[0] ?? "";
        if (!url.startsWith("/pdfjs/")) return next();
        const file = normalize(join(PDFJS, url.slice("/pdfjs/".length)));
        if (!file.startsWith(normalize(PDFJS)) || !existsSync(file) || !statSync(file).isFile()) return next();
        res.setHeader("Content-Type", TYPES[extname(file)] ?? "application/octet-stream");
        res.end(readFileSync(file));
      });
    },
    generateBundle() {
      for (const dir of ASSET_DIRS) {
        for (const name of readdirSync(join(PDFJS, dir))) {
          const file = join(PDFJS, dir, name);
          if (statSync(file).isFile() && !SKIP.test(name)) {
            this.emitFile({ type: "asset", fileName: `pdfjs/${dir}/${name}`, source: readFileSync(file) });
          }
        }
      }
    },
  };
}

export default defineConfig({
  root: fileURLToPath(new URL(".", import.meta.url)),
  base: "./",
  plugins: [pdfjsAssets()],
  oxc: {
    jsx: { runtime: "automatic", importSource: "preact" },
  },
  build: {
    target: "es2022",
    outDir: "dist",
    emptyOutDir: true,
    assetsInlineLimit: 0,
    sourcemap: false,
  },
  server: { port: 5173, strictPort: true },
});
