import { signal } from "@preact/signals";
import { useEffect, useState } from "preact/hooks";
import {
  API_VERSION,
  PROVIDER_LABELS,
  cancelLogin,
  forgetHelper,
  helperStatus,
  helperToken,
  listModels,
  pair,
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
  const ready = phase === "ready" && providerReady(provider);
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
        <li>
          Open a terminal and run <code>npx slanki@1</code>. It needs Node.js 22 or newer.
        </li>
        <li>It opens Slanki with a connection link. If that opened a different browser, type the code it shows here:</li>
      </ol>
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
      <p class="muted small">
        Chrome and Edge ask once whether this site may access apps on your device. Choose <strong>Allow</strong>. In Safari, use the copy of
        Slanki that the helper opens at <code>http://127.0.0.1:47213</code>.
      </p>
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
  const account = prefs.provider === "codex" ? "ChatGPT" : "Claude";
  useEffect(() => {
    setModels(null);
    if (status?.installed) void load(false);
  }, [prefs.provider, status?.installed]);
  const model = models?.find((m) => m.id === prefs.model) ?? models?.[0];
  return (
    <div class="stack">
      <label class="field">
        <span>AI</span>
        <select
          class="input"
          value={prefs.provider}
          onChange={(event) => savePreferences({ provider: event.currentTarget.value as Provider, model: "", effort: "low" })}
        >
          {SUPPORTED_PROVIDERS.map((provider) => (
            <option key={provider} value={provider}>
              {PROVIDER_LABELS[provider]}
              {helper.value.status?.providers[provider]?.installed === false ? " (not installed)" : ""}
            </option>
          ))}
        </select>
      </label>
      {status && (
        <p class={`banner ${status.installed && status.signedIn !== "no" ? "ok" : "warn"} small`} style={{ margin: 0 }}>
          {status.message}
          {status.loggingIn ? (
            <>
              {" "}Finish signing in in the browser window that opened.{" "}
              <button class="btn small" onClick={() => void cancelLogin(prefs.provider).then(checkHelper, (e) => notify(errorMessage(e), true))}>
                Cancel
              </button>
            </>
          ) : (
            status.installed &&
            status.signedIn !== "yes" && (
              <>
                {" "}
                <button
                  class="btn small primary"
                  onClick={() => void startLogin(prefs.provider).then(checkHelper, (e) => notify(errorMessage(e), true))}
                >
                  Sign in with {account}
                </button>
              </>
            )
          )}
        </p>
      )}
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
      {phase === "offline" && <p class="banner warn small">{message} Start it again with <code>npx slanki@1</code>.</p>}
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
