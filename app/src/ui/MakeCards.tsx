import { useEffect, useMemo, useState } from "preact/hooks";
import { PROVIDER_LABELS } from "../ai/helper.ts";
import { isKeyProvider } from "../ai/apiKeys.ts";
import { aiPreferences, savePreferences } from "../ai/settings.ts";
import { pyStrip } from "../core/py.ts";
import { defaultCardLimit } from "../core/selection.ts";
import { startGeneration } from "../run/start.ts";
import { download, safeFileName } from "../services/files.ts";
import { externalChatPrompt, importChatDrafts, parseChatJson } from "../services/lectures.ts";
import type { LectureBundle } from "../store/library.ts";
import { aiDialogOpen, EFFORT_LABELS, helper, providerReady } from "./ai/AiStatus.tsx";
import { Dialog, plural, useBusy } from "./components.tsx";
import { errorMessage, notify, reportError } from "./state.ts";

export function MakeCardsDialog({ open, bundle, onClose }: { open: boolean; bundle: LectureBundle; onClose: () => void }) {
  const readable = useMemo(() => bundle.pages.filter((p) => !p.warning && pyStrip(p.text)), [bundle.pages]);
  const [allSlides, setAllSlides] = useState(true);
  const [chosen, setChosen] = useState<number[]>([]);
  const [limit, setLimit] = useState("");
  const [reverse, setReverse] = useState(false);
  const [pasted, setPasted] = useState("");
  const [showChat, setShowChat] = useState(false);
  const [busy, run] = useBusy();
  useEffect(() => {
    if (!open) return;
    setAllSlides(true);
    setChosen(readable.map((p) => p.number));
    setLimit("");
    setPasted("");
    setShowChat(!providerReady(aiPreferences.value.provider));
  }, [open]);
  const pages = allSlides ? readable.map((p) => p.number) : chosen;
  const suggested = defaultCardLimit(pages.length) + (reverse && defaultCardLimit(pages.length) < 2 ? 1 : 0);
  const prefs = aiPreferences.value;
  const ready = providerReady(prefs.provider);
  const consented = prefs.consented.includes(prefs.provider);
  const running = bundle.runs.some((r) => r.status === "queued" || r.status === "running");

  const generate = () =>
    run(async () => {
      try {
        await startGeneration(bundle, {
          pages,
          cardLimit: limit || null,
          reverse,
          provider: prefs.provider,
          model: prefs.model,
          effort: prefs.effort,
        });
        notify("Making cards. You can keep reviewing while they arrive.");
        onClose();
      } catch (error) {
        reportError(error);
      }
    });

  const prompt = () => externalChatPrompt(bundle, pages, limit || null, reverse ? "all" : "mixed");

  return (
    <Dialog open={open} onClose={onClose} label="Make cards" wide>
      <h2>Make cards</h2>
      {!readable.length ? (
        <p class="banner warn">None of these slides has readable text, so the AI has nothing to work with. Write cards yourself beside the slides instead.</p>
      ) : (
        <>
          <div class="stack">
            <div class="field">
              <span>Slides</span>
              <label class="check">
                <input type="radio" name="slides" checked={allSlides} onChange={() => setAllSlides(true)} />
                <span>All {plural(readable.length, "slide")} with text</span>
              </label>
              <label class="check">
                <input type="radio" name="slides" checked={!allSlides} onChange={() => setAllSlides(false)} />
                <span>Choose slides</span>
              </label>
              {!allSlides && (
                <>
                  <div class="row small">
                    <button class="btn small ghost" onClick={() => setChosen(readable.map((p) => p.number))}>
                      Select all
                    </button>
                    <button class="btn small ghost" onClick={() => setChosen([])}>
                      Clear
                    </button>
                    <span class="muted">{plural(chosen.length, "slide")} selected</span>
                  </div>
                  <div class="page-grid">
                    {bundle.pages.map((p) => {
                      const usable = readable.includes(p);
                      const on = chosen.includes(p.number);
                      return (
                        <button
                          key={p.number}
                          class="page-chip"
                          aria-pressed={on}
                          disabled={!usable}
                          title={usable ? `Slide ${p.number}` : "No readable text"}
                          onClick={() => setChosen(on ? chosen.filter((n) => n !== p.number) : [...chosen, p.number].sort((a, b) => a - b))}
                        >
                          {p.number}
                        </button>
                      );
                    })}
                  </div>
                </>
              )}
            </div>
            <label class="field" style={{ maxWidth: "320px" }}>
              <span>Number of cards (at most)</span>
              <input
                class="input"
                type="number"
                min={1}
                max={500}
                placeholder={String(suggested)}
                value={limit}
                onInput={(event) => setLimit(event.currentTarget.value)}
              />
              <span class="muted small" style={{ fontWeight: 400 }}>
                Leave empty for about one card per two slides ({suggested}). The AI picks the most important ideas.
              </span>
            </label>
            <label class="check">
              <input type="checkbox" checked={reverse} onChange={(event) => setReverse(event.currentTarget.checked)} />
              <span>
                Also make reverse cards
                <span class="muted small" style={{ display: "block" }}>
                  For clear term ↔ definition pairs. Each one becomes two Anki cards.
                </span>
              </span>
            </label>
          </div>

          <div class="pane" style={{ boxShadow: "none" }}>
            <div class="row">
              <strong>With your AI</strong>
              <span class="spacer" />
              {ready ? (
                <span class="muted small">
                  {PROVIDER_LABELS[prefs.provider]} · {prefs.model || "default model"} · {EFFORT_LABELS[prefs.effort] ?? prefs.effort}
                </span>
              ) : (
                <span class="muted small">{!isKeyProvider(prefs.provider) && helper.value.phase === "ready" ? "Sign in needed" : "Not connected"}</span>
              )}
              <button class="btn small" onClick={() => (aiDialogOpen.value = true)}>
                {ready ? "Change" : "Connect"}
              </button>
            </div>
            {ready && (
              <label class="check" style={{ marginTop: "12px" }}>
                <input
                  type="checkbox"
                  checked={consented}
                  onChange={(event) =>
                    savePreferences({
                      consented: event.currentTarget.checked
                        ? [...new Set([...prefs.consented, prefs.provider])]
                        : prefs.consented.filter((provider) => provider !== prefs.provider),
                    })
                  }
                />
                <span class="small">
                  Send the text of this lecture's slides, and up to 200 of its existing questions, to {PROVIDER_LABELS[prefs.provider]}{" "}
                  {isKeyProvider(prefs.provider) ? "with my API key" : "through my own account"}. The PDF and slide images stay on this device.
                </span>
              </label>
            )}
            <div class="dialog-actions" style={{ marginTop: "12px" }}>
              <button class="btn primary" disabled={busy || !ready || !consented || running || !pages.length} onClick={generate}>
                {running ? "Already making cards…" : "Make cards"}
              </button>
            </div>
          </div>

          <details open={showChat} onToggle={(event) => setShowChat((event.currentTarget as HTMLDetailsElement).open)}>
            <summary>
              <strong>No AI connected? Use any chat</strong> <span class="muted small">(ChatGPT, Claude, Gemini…)</span>
            </summary>
            <div class="stack" style={{ marginTop: "12px" }}>
              <p class="small muted">
                Copy the prompt into a chat, then paste its answer here. The prompt contains this lecture's slide text.
              </p>
              <div class="row">
                <button
                  class="btn"
                  disabled={!pages.length}
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(prompt());
                      notify("Prompt copied. Paste it into your chat.");
                    } catch (error) {
                      notify(errorMessage(error) || "Copying failed. Use Download instead.", true);
                    }
                  }}
                >
                  1. Copy prompt
                </button>
                <button
                  class="btn ghost"
                  disabled={!pages.length}
                  onClick={() => {
                    try {
                      download(prompt(), `${safeFileName(bundle.lecture.title)} prompt.txt`, "text/plain;charset=utf-8");
                    } catch (error) {
                      reportError(error);
                    }
                  }}
                >
                  Download as text
                </button>
              </div>
              <label class="field">
                <span>2. Paste the chat's answer</span>
                <textarea class="input" rows={5} placeholder='{"cards": [ … ]}' value={pasted} onInput={(event) => setPasted(event.currentTarget.value)} />
              </label>
              <div class="dialog-actions">
                <button
                  class="btn primary"
                  disabled={busy || !pasted.trim()}
                  onClick={() =>
                    run(async () => {
                      try {
                        const result = await importChatDrafts(bundle.lecture.id, parseChatJson(pasted));
                        const extra = [
                          result.filtered ? `${result.filtered} about course logistics skipped` : "",
                          result.duplicates ? `${result.duplicates} already existed` : "",
                        ].filter(Boolean);
                        notify(`Added ${plural(result.added, "draft")}${extra.length ? ` (${extra.join(", ")})` : ""}.`);
                        onClose();
                      } catch (error) {
                        reportError(error);
                      }
                    })
                  }
                >
                  Add drafts
                </button>
              </div>
            </div>
          </details>
        </>
      )}
    </Dialog>
  );
}
