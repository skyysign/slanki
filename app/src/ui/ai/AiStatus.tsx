import { signal } from "@preact/signals";
import { useEffect, useState } from "preact/hooks";
import {
  API_VERSION,
  HELPER_ORIGIN,
  PROVIDER_LABELS,
  cancelLogin,
  forgetHelper,
  helperStatus,
  helperToken,
  listModels,
  pair,
  ping,
  startLogin,
  type HelperStatus,
  type ModelChoice,
  type Provider,
} from "../../ai/helper.ts";
import { aiPreferences, savePreferences } from "../../ai/settings.ts";
import { Dialog, useBusy } from "../components.tsx";
import { errorMessage, notify } from "../state.ts";

export type HelperPhase = "unpaired" | "checking" | "ready" | "offline" | "outdated";
export const helper = signal<{ phase: HelperPhase; status: HelperStatus | null; message: string }>({
  phase: helperToken() ? "checking" : "unpaired",
  status: null,
  message: "",
});
export const aiDialogOpen = signal(false);

export const SUPPORTED_PROVIDERS: Provider[] = ["codex", "claude"];
/** Served by the local app (Slanki.exe or --local) rather than the website. */
export const LOCAL_APP = typeof location !== "undefined" && location.origin === HELPER_ORIGIN;

const CLI_INFO: Record<string, { name: string; account: string; install: string }> = {
  codex: { name: "ChatGPT", account: "ChatGPT", install: "https://developers.openai.com/codex/cli" },
  claude: { name: "Claude", account: "Claude", install: "https://code.claude.com/docs/en/setup" },
};

/** Ask the helper for its status. Only called after the user paired or asked to connect. */
export async function checkHelper(): Promise<void> {
  if (!helperToken()) {
    helper.value = { phase: "unpaired", status: null, message: "" };
    return;
  }
  // Keep showing the current settings while refreshing (sign-in polling).
  if (helper.value.phase !== "ready") helper.value = { ...helper.value, phase: "checking" };
  try {
    const status = await helperStatus();
    helper.value = {
      phase: status.apiVersion === API_VERSION ? "ready" : "outdated",
      status,
      message: status.apiVersion === API_VERSION ? "" : "Update the helper: stop it and run `npx slanki@latest`.",
    };
  } catch (error) {
    helper.value = { phase: helperToken() ? "offline" : "unpaired", status: null, message: errorMessage(error) };
  }
}

/** Handle the one-time pairing link (#pair=PORT.CODE) before routing sees it. */
export async function pairFromLocation(): Promise<void> {
  const match = /^#pair=\d+\.([A-Za-z0-9_-]{8,64})$/.exec(location.hash);
  if (!match) return;
  history.replaceState(null, "", location.pathname + location.search + "#/");
  try {
    await pair(match[1]!);
    await checkHelper();
    notify("Connected to the Slanki helper.");
  } catch (error) {
    notify(errorMessage(error), true);
  }
}

export function providerReady(provider: Provider): boolean {
  const status = helper.value.status?.providers[provider];
  return helper.value.phase === "ready" && !!status?.installed && status.signedIn !== "no";
}

export function AiStatusPill() {
  const { phase, status } = helper.value;
  const provider = aiPreferences.value.provider;
  const ready = providerReady(provider);
  const label =
    phase === "unpaired"
      ? "Connect your AI"
      : phase === "checking"
        ? "Checking AI…"
        : phase === "offline"
          ? "AI helper not running"
          : phase === "outdated"
            ? "Update AI helper"
            : ready
              ? `${PROVIDER_LABELS[provider]} ready`
              : status?.providers[provider]?.installed
                ? `Sign in to ${PROVIDER_LABELS[provider]}`
                : `${PROVIDER_LABELS[provider]} not found`;
  return (
    <>
      <button class={`pill${ready ? " ok" : ""}`} onClick={() => (aiDialogOpen.value = true)}>
        <span class="dot" />
        {label}
      </button>
      <AiDialog open={aiDialogOpen.value} onClose={() => (aiDialogOpen.value = false)} />
    </>
  );
}

function ConnectSteps() {
  const [code, setCode] = useState("");
  const [busy, run] = useBusy();
  return (
    <div class="stack">
      <p>
        Slanki uses the AI you already have (Codex or Claude Code) through a small helper that runs on your computer. Your slides are
        only sent to that AI, through your own account.
      </p>
      <ol class="stack" style={{ paddingLeft: "20px", margin: 0 }}>
        {LOCAL_APP ? (
          <li>Open Slanki again from its icon. It reconnects this browser by itself.</li>
        ) : (
          <>
            <li>
              Download and open Slanki, or run <code>npx slanki@1</code> in a terminal.
            </li>
            <li>It opens Slanki with a connection link. If that opened a different browser, type the code it shows here:</li>
          </>
        )}
      </ol>
      {!LOCAL_APP && (
      <form
        class="row"
        onSubmit={(event) => {
          event.preventDefault();
          void run(async () => {
            try {
              await pair(code.trim());
              await checkHelper();
              notify("Connected to the Slanki helper.");
            } catch (error) {
              notify(errorMessage(error), true);
            }
          });
        }}
      >
        <input class="input" style={{ maxWidth: "220px" }} placeholder="Connection code" value={code} onInput={(e) => setCode(e.currentTarget.value)} />
        <button class="btn" disabled={busy || code.trim().length < 8}>
          Connect
        </button>
      </form>
      )}
      {!LOCAL_APP && (
      <p class="muted small">
        Chrome and Edge ask once whether this site may access apps on your device. Choose <strong>Allow</strong>. In Safari, use the copy of
        Slanki that the helper opens at <code>http://127.0.0.1:47213</code>.
      </p>
      )}
    </div>
  );
}

function ProviderSettings() {
  const prefs = aiPreferences.value;
  const status = helper.value.status?.providers[prefs.provider];
  const [models, setModels] = useState<ModelChoice[] | null>(null);
  const [busy, run] = useBusy();
  const load = (refresh: boolean) =>
    run(async () => {
      try {
        setModels(await listModels(prefs.provider, refresh));
      } catch (error) {
        setModels([]);
        notify(errorMessage(error), true);
      }
    });
  useEffect(() => {
    if (!status?.loggingIn) return;
    const timer = setInterval(() => void checkHelper(), 2000);
    return () => clearInterval(timer);
  }, [status?.loggingIn]);
  useEffect(() => {
    setModels(null);
    if (status?.installed) void load(false);
  }, [prefs.provider, status?.installed]);
  const model = models?.find((m) => m.id === prefs.model) ?? models?.[0];
  return (
    <div class="stack">
      <p class="muted small" style={{ margin: 0 }}>
        Pick the AI you already use. Slanki works through its app on this computer and your own ChatGPT or Claude sign-in. No API key
        needed.
      </p>
      <div class="choices">
        {SUPPORTED_PROVIDERS.map((provider) => (
          <CliChoice key={provider} provider={provider} />
        ))}
      </div>
      {status?.installed && (
        <div class="row" style={{ alignItems: "flex-end" }}>
          <label class="field" style={{ flex: "1 1 200px" }}>
            <span>Model</span>
            <select
              class="input"
              value={model?.id ?? ""}
              disabled={!models?.length}
              onChange={(event) => {
                const chosen = models?.find((m) => m.id === event.currentTarget.value);
                const effort = chosen?.efforts.includes(prefs.effort) ? prefs.effort : chosen?.efforts.includes("low") ? "low" : "";
                savePreferences({ model: event.currentTarget.value, effort });
              }}
            >
              {(models ?? [{ id: "", label: "CLI default", efforts: [""], default_effort: "" }]).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <label class="field" style={{ flex: "1 1 140px" }}>
            <span>Reasoning</span>
            <select
              class="input"
              value={model?.efforts.includes(prefs.effort) ? prefs.effort : ""}
              disabled={!model || model.efforts.length < 2}
              onChange={(event) => savePreferences({ effort: event.currentTarget.value })}
            >
              {(model?.efforts ?? [""]).map((effort) => (
                <option key={effort} value={effort}>
                  {EFFORT_LABELS[effort] ?? effort}
                </option>
              ))}
            </select>
          </label>
          <button class="btn small" disabled={busy} onClick={() => load(true)}>
            Refresh
          </button>
        </div>
      )}
      <p class="muted small">Lower reasoning is faster and uses less of your plan. Higher can be more careful.</p>
    </div>
  );
}

/** One row per CLI with the single next step: install, sign in, use. */
function CliChoice({ provider }: { provider: Provider }) {
  const info = CLI_INFO[provider]!;
  const status = helper.value.status?.providers[provider];
  const selected = aiPreferences.value.provider === provider;
  const choose = () => {
    if (!selected) savePreferences({ provider, model: "", effort: "low" });
  };
  const failed = (error: unknown) => notify(errorMessage(error), true);
  let line = status?.message ?? "Checking…";
  let action = null;
  if (status && !status.installed) {
    line = `The ${PROVIDER_LABELS[provider]} app is not on this computer yet. Install it, then click Check again.`;
    action = (
      <a class="btn small" href={info.install} target="_blank" rel="noreferrer noopener">
        Install
      </a>
    );
  } else if (status?.loggingIn) {
    line = "Finish signing in in the browser window that opened.";
    action = (
      <button class="btn small" onClick={() => void cancelLogin(provider).then(checkHelper, failed)}>
        Cancel
      </button>
    );
  } else if (status && status.signedIn === "no") {
    action = (
      <button
        class="btn small primary"
        onClick={() => {
          choose();
          void startLogin(provider).then(checkHelper, failed);
        }}
      >
        Sign in with {info.account}
      </button>
    );
  } else if (status) {
    action = selected ? (
      <span class="small" style={{ color: "var(--success)", fontWeight: 600 }}>
        ✓ In use
      </span>
    ) : (
      <button class="btn small primary" onClick={choose}>
        Use {info.name}
      </button>
    );
  }
  return (
    <div class={`choice${selected ? " selected" : ""}`}>
      <div style={{ minWidth: 0 }}>
        <strong>{info.name}</strong> <span class="muted small">via {PROVIDER_LABELS[provider]}</span>
        <span class="muted small" style={{ display: "block" }}>
          {line}
        </span>
      </div>
      {action}
    </div>
  );
}

/** The local app closes itself once no Slanki tab has checked in for a few minutes. */
export function keepLocalAppAlive(): void {
  if (!LOCAL_APP) return;
  setInterval(() => {
    if (helperToken()) void ping().catch(() => undefined);
  }, 60_000);
}

export const EFFORT_LABELS: Record<string, string> = {
  "": "CLI default",
  none: "None",
  minimal: "Minimal",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra high",
  max: "Max",
  off: "Thinking off",
  on: "Thinking on",
};

export function AiDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  useEffect(() => {
    if (open && helperToken()) void checkHelper();
  }, [open]);
  const { phase, message } = helper.value;
  return (
    <Dialog open={open} onClose={onClose} label="AI connection">
      <h2>Your AI</h2>
      {phase === "ready" ? <ProviderSettings /> : <ConnectSteps />}
      {phase === "offline" && (
        <p class="banner warn small">
          {LOCAL_APP ? "Slanki is not running. Open it again from its icon." : <>{message} Start it again with <code>npx slanki@1</code>.</>}
        </p>
      )}
      {phase === "outdated" && <p class="banner warn small">{message}</p>}
      <div class="dialog-actions">
        {helperToken() && (
          <button
            class="btn ghost small"
            onClick={() => {
              forgetHelper();
              void checkHelper();
            }}
          >
            Disconnect
          </button>
        )}
        <span class="spacer" />
        {phase !== "unpaired" && (
          <button class="btn" onClick={() => void checkHelper()}>
            Check again
          </button>
        )}
        <button class="btn primary" onClick={onClose}>
          Done
        </button>
      </div>
    </Dialog>
  );
}
