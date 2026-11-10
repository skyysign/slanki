// Browser-only I/O. Task data stays with the selected local backend; this module
// stores only AI preferences for the current tab, never lecture/card content.
const preferenceKey = "recalloom:ai-preferences:v1";

export async function requestJson(url, options = {}) {
  const response = await fetch(url, {credentials: "same-origin", cache: "no-store", ...options});
  return {response, data: await response.json()};
}

export function readAiPreferences() {
  try {
    const value = JSON.parse(sessionStorage.getItem(preferenceKey));
    if (!value || !["codex", "claude", "gemini", "kimi"].includes(value.provider) ||
        typeof value.model !== "string" || value.model.length > 100 ||
        typeof value.effort !== "string" || value.effort.length > 12) return null;
    return {provider: value.provider, model: value.model, effort: value.effort};
  } catch { return null; }
}

export function writeAiPreferences(provider, model, effort) {
  try { sessionStorage.setItem(preferenceKey, JSON.stringify({provider, model, effort})); }
  catch { /* The interface also works when browser storage is disabled. */ }
}
