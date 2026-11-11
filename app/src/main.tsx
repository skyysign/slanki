import { render } from "preact";
import { helperToken } from "./ai/helper.ts";
import { recoverStaleRuns } from "./run/orchestrator.ts";
import { App } from "./ui/App.tsx";
import { checkHelper, keepLocalAppAlive, pairFromLocation } from "./ui/ai/AiStatus.tsx";
import "./ui/styles.css";

async function start() {
  // The pairing code is removed from the address bar before anything else runs.
  const pairing = location.hash.startsWith("#pair=") ? pairFromLocation() : null;
  render(<App />, document.getElementById("app")!);
  await pairing;
  if (!pairing && helperToken()) void checkHelper();
  void recoverStaleRuns().catch(() => undefined);
  keepLocalAppAlive();
}

void start();
