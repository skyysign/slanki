// Manual check: model metadata from the installed CLIs (no prompts, no inference).
import { join } from "node:path";
import { tmpdir } from "node:os";
import { Catalogs } from "../src/providers.ts";
const home = join(tmpdir(), "slanki-discovery-check");
const catalogs = new Catalogs(home);
for (const provider of ["codex", "claude"] as const) {
  try {
    const models = await catalogs.refresh(provider, join(home, "work"));
    console.log(`${provider}: ${models.length - 1} models; efforts of first: ${models[1]?.efforts.filter(Boolean).join(", ") || "none"}`);
  } catch (error) {
    console.log(`${provider}: ${(error as Error).message}`);
  }
}
