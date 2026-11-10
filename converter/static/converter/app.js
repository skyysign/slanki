"use strict";
import {requestJson, readAiPreferences, writeAiPreferences} from "./transport.js";
import {initWorkspace} from "./workspace.js";

const providerSettings = document.querySelector("[data-provider-settings]");
if (providerSettings) {
  const catalogs = JSON.parse(document.getElementById("model-catalogs").textContent);
  const labels = JSON.parse(document.getElementById("effort-labels").textContent);
  const providers = JSON.parse(document.getElementById("provider-details").textContent);
  const provider = providerSettings.querySelector("[data-provider-select]");
  const model = providerSettings.querySelector("[data-model-select]");
  const effort = providerSettings.querySelector("[data-effort-select]");
  const message = providerSettings.querySelector("[data-model-message]");
  const refresh = providerSettings.querySelector("[data-refresh-models]");
  const form = providerSettings.closest("form");
  const savedPreferences = readAiPreferences();
  const useSaved = savedPreferences && [...provider.options].some(option => option.value === savedPreferences.provider);
  if (useSaved) provider.value = savedPreferences.provider;
  const formatInputs = [...form.querySelectorAll('input[name="formats"]')];
  const updateMinimumCards = () => {
    if (!form.elements.card_limit) return;
    const chosen = formatInputs.filter(input => input.checked && !["occlusion", "visual"].includes(input.value));
    const images = form.querySelector("[data-image-format]")?.checked;
    const textMinimum = chosen.length ? (chosen.length === 1 && chosen[0].value === "reversed" ? 2 : 1) : 0;
    form.elements.card_limit.min = String(Math.max(1, textMinimum + Number(Boolean(images))));
  };
  formatInputs.forEach(input => input.addEventListener("change", updateMinimumCards));
  updateMinimumCards();
  const remembered = {};
  let activeProvider = provider.value, requestNumber = 0;
  const selected = () => catalogs[provider.value].models.find(item => item.id === model.value);
  const showEfforts = (wanted) => {
    const item = selected();
    const levels = item?.efforts || [""];
    effort.replaceChildren(...levels.map(level => new Option(labels[level] || level, level)));
    effort.value = levels.includes(wanted) ? wanted : (levels.includes("low") ? "low" : "");
    // Keep the default value submitted even when the model has no effort control.
    effort.disabled = levels.length === 1;
  };
  const showModels = (wantedModel, wantedEffort) => {
    const data = catalogs[provider.value];
    model.replaceChildren(...data.models.map(item => new Option(item.label, item.id)));
    if (wantedModel && !data.models.some(item => item.id === wantedModel)) {
      model.add(new Option(`Saved model: ${wantedModel} (refresh to verify)`, wantedModel));
    }
    model.value = wantedModel || "";
    showEfforts(wantedEffort);
    message.textContent = data.message;
    providerSettings.querySelector("[data-provider-connect]").href = providers[provider.value].connect_url;
    form.querySelector("[data-consent-provider]").textContent = `${providers[provider.value].company} through ${providers[provider.value].label}`;
    showSummary();
  };
  const showSummary = () => {
    const summary = form.querySelector("[data-ai-summary]");
    if (summary) summary.textContent = `${providers[provider.value].label} · ${model.selectedOptions[0]?.textContent || "CLI default"} · ${labels[effort.value] || "CLI default"}`;
  };
  const remember = () => { writeAiPreferences(provider.value, model.value, effort.value); showSummary(); };
  const loadModels = async (initialEffort) => {
    const requestedProvider = provider.value, number = ++requestNumber;
    refresh.disabled = true;
    message.textContent = "Reading model choices from your local CLI… No generation is running.";
    try {
      const response = await fetch(providers[requestedProvider].refresh_url, {
        method: "POST", headers: { "X-CSRFToken": form.elements.csrfmiddlewaretoken.value },
      });
      const data = await response.json();
      if (number !== requestNumber || requestedProvider !== provider.value) return;
      if (!response.ok) throw new Error(data.error || "Could not read models. Check your CLI installation and sign-in.");
      // Preserve the requested first-run level while discovery temporarily shows
      // a disabled default-only control. Later refreshes retain the user's choice.
      const nextEffort = effort.disabled && !catalogs[requestedProvider].updated_at
        ? (initialEffort ?? effort.value) : effort.value;
      catalogs[requestedProvider] = data;
      showModels(model.value, nextEffort);
    } catch (error) {
      if (number === requestNumber) message.textContent = error.message;
    } finally {
      if (number === requestNumber) refresh.disabled = false;
    }
  };
  provider.addEventListener("change", () => {
    remembered[activeProvider] = [model.value, effort.value];
    activeProvider = provider.value;
    requestNumber += 1;
    refresh.disabled = false;
    // Changing who receives lecture text always clears the sharing confirmation.
    form.elements.consent.checked = false;
    const choices = remembered[activeProvider] || ["", "low"];
    showModels(...choices);
    remember();
    if (!catalogs[activeProvider].updated_at) loadModels(choices[1]);
  });
  model.addEventListener("change", () => { showEfforts(effort.value); remember(); });
  effort.addEventListener("change", remember);
  form.addEventListener("submit", remember);
  refresh.addEventListener("click", () => loadModels());
  showModels(useSaved ? savedPreferences.model : providerSettings.dataset.selectedModel, useSaved ? savedPreferences.effort : providerSettings.dataset.selectedEffort);
  if (!catalogs[activeProvider].updated_at) loadModels(useSaved ? savedPreferences.effort : providerSettings.dataset.selectedEffort);
}

document.querySelectorAll("[data-crop-stage]").forEach((stage) => {
  const form = stage.closest("form");
  const image = stage.querySelector("img");
  const overlay = stage.querySelector("[data-crop-selection]");
  const enabled = form.elements.crop_enabled;
  const width = Number(stage.dataset.width), height = Number(stage.dataset.height);
  const fields = Object.fromEntries(["left", "top", "right", "bottom"].map(key => [key, form.elements[`crop_${key}`]]));
  let start = null;
  const draw = () => {
    stage.classList.toggle("crop-active", enabled.checked);
    Object.values(fields).forEach(field => { field.disabled = !enabled.checked; });
    form.elements.crop_on_question.disabled = !enabled.checked;
    const values = Object.fromEntries(Object.entries(fields).map(([key, field]) => [key, Number(field.value)]));
    const valid = values.left >= 0 && values.top >= 0 && values.right <= width && values.bottom <= height && values.right > values.left && values.bottom > values.top;
    overlay.hidden = !enabled.checked || !valid;
    if (valid) {
      overlay.style.left = `${100 * values.left / width}%`;
      overlay.style.top = `${100 * values.top / height}%`;
      overlay.style.width = `${100 * (values.right - values.left) / width}%`;
      overlay.style.height = `${100 * (values.bottom - values.top) / height}%`;
    }
  };
  const position = (event) => {
    const box = image.getBoundingClientRect();
    return [
      Math.round(Math.max(0, Math.min(width, (event.clientX - box.left) * width / box.width))),
      Math.round(Math.max(0, Math.min(height, (event.clientY - box.top) * height / box.height))),
    ];
  };
  const move = (event) => {
    if (!start) return;
    const end = position(event);
    [fields.left.value, fields.top.value, fields.right.value, fields.bottom.value] = [Math.min(start[0], end[0]), Math.min(start[1], end[1]), Math.max(start[0], end[0]), Math.max(start[1], end[1])];
    fields.left.dispatchEvent(new Event("input", { bubbles: true }));
    draw();
  };
  stage.addEventListener("pointerdown", (event) => {
    if (!enabled.checked || !image.complete || event.button !== 0) return;
    event.preventDefault();
    stage.setPointerCapture(event.pointerId);
    start = position(event);
    move(event);
  });
  stage.addEventListener("pointermove", move);
  stage.addEventListener("pointerup", (event) => { move(event); start = null; });
  stage.addEventListener("pointercancel", () => { start = null; });
  enabled.addEventListener("change", draw);
  Object.values(fields).forEach(field => field.addEventListener("input", draw));
  draw();
});

document.querySelectorAll("[data-occlusion-editor]").forEach((editor) => {
  const form = editor.closest("form"), stage = editor.querySelector("[data-mask-stage]");
  const image = stage.querySelector("img"), overlays = editor.querySelector("[data-mask-overlays]");
  const list = editor.querySelector("[data-mask-list]"), status = editor.querySelector("[data-mask-status]");
  const fields = Object.fromEntries([...editor.querySelectorAll("input[data-mask-edge]")].map(field => [field.dataset.maskEdge, field]));
  const drawButton = editor.querySelector("[data-draw-mask]"), undoButton = editor.querySelector("[data-undo-mask]");
  const width = Number(editor.dataset.width), height = Number(editor.dataset.height), page = Number(editor.dataset.page);
  const visual = editor.dataset.visual === "yes";
  const single = editor.dataset.single === "yes", limit = single ? 1 : 20;
  const handles = {nw: [0, 0], n: [50, 0], ne: [100, 0], e: [100, 50], se: [100, 100], s: [50, 100], sw: [0, 100], w: [0, 50]};
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  let masks = [], selected = 0, gesture = null, pending = null, drawing = false;
  const history = [];
  try { const saved = JSON.parse(form.elements.masks.value); if (Array.isArray(saved)) masks = saved.slice(0, limit); } catch { /* The server displays invalid input. */ }
  const valid = mask => mask && mask.page === page && ["left", "top", "right", "bottom"].every(key => Number.isInteger(mask[key])) && mask.left >= 0 && mask.top >= 0 && mask.right <= width && mask.bottom - mask.top >= 2 && mask.bottom <= height && mask.right - mask.left >= 2;
  masks = masks.filter(valid);
  const snapshot = () => ({masks: masks.map(mask => ({...mask})), selected});
  const restore = state => { masks = state.masks; selected = state.selected; };
  const remember = before => {
    if (JSON.stringify(before.masks) === JSON.stringify(masks)) return false;
    history.push(before);
    if (history.length > 30) history.shift();
    return true;
  };
  const draw = () => {
    overlays.replaceChildren();
    stage.classList.toggle("drawing", drawing || gesture?.mode === "draw");
    stage.classList.toggle("dragging", gesture?.mode === "move");
    [...masks, ...(pending ? [pending] : [])].forEach((mask, index) => {
      const box = document.createElement("span");
      const isPending = index === masks.length;
      box.className = "occlusion-mask" + (index === selected ? " selected" : "") + (isPending ? " pending" : "");
      box.dataset.maskIndex = index;
      box.style.left = `${100 * mask.left / width}%`; box.style.top = `${100 * mask.top / height}%`;
      box.style.width = `${100 * (mask.right - mask.left) / width}%`; box.style.height = `${100 * (mask.bottom - mask.top) / height}%`;
      box.textContent = String(index + 1);
      if (index === selected && !isPending && !drawing) {
        Object.entries(handles).forEach(([edge, [left, top]]) => {
          const handle = document.createElement("span");
          handle.className = "mask-handle"; handle.dataset.maskEdge = edge;
          handle.style.left = `${left}%`; handle.style.top = `${top}%`;
          handle.setAttribute("aria-hidden", "true");
          box.append(handle);
        });
      }
      overlays.append(box);
    });
  };
  const sync = (changed = false) => {
    form.elements.masks.value = JSON.stringify(masks);
    form.elements.preview_index.value = selected;
    list.replaceChildren();
    masks.forEach((mask, index) => {
      const button = document.createElement("button");
      button.type = "button"; button.className = "button secondary";
      button.textContent = `Region ${index + 1}`;
      button.setAttribute("aria-pressed", String(index === selected));
      button.addEventListener("click", () => { selected = index; drawing = false; sync(); stage.focus({preventScroll: true}); });
      list.append(button);
    });
    const current = masks[selected] || {left: 0, top: 0, right: Math.min(100, width), bottom: Math.min(60, height)};
    Object.entries(fields).forEach(([key, field]) => { field.value = current[key]; field.setCustomValidity(""); });
    status.textContent = drawing ? "Drag on the slide to draw a region. Escape returns to moving and resizing." : masks.length ? `${masks.length} region${masks.length === 1 ? "" : "s"} / ${masks.length} Anki card${masks.length === 1 ? "" : "s"}. Region ${selected + 1} selected.` : "Draw a rectangle or use Add region, then adjust it on the slide.";
    if (visual && !drawing) status.textContent = `${masks.length} optional text cover(s) on one card. Keep the figure readable; the answer reveals all covers.`;
    editor.querySelector("[data-remove-mask]")?.toggleAttribute("disabled", !masks.length);
    editor.querySelector("[data-add-mask]")?.toggleAttribute("disabled", masks.length >= limit);
    drawButton.setAttribute("aria-pressed", String(drawing));
    undoButton.disabled = !history.length;
    draw();
    if (changed) form.elements.masks.dispatchEvent(new Event("input", {bubbles: true}));
  };
  const add = mask => {
    if (!valid(mask)) { status.textContent = "Keep the region within the slide and at least 2 pixels wide and high."; return false; }
    if (single) { masks = [mask]; selected = 0; }
    else if (masks.length < limit) { masks.push(mask); selected = masks.length - 1; }
    else { status.textContent = "Save these 20 regions before adding more."; return false; }
    drawing = false;
    return true;
  };
  editor.addEventListener("use-suggested-mask", event => {
    if (single || gesture || !valid(event.detail)) { event.preventDefault(); return; }
    const duplicate = masks.findIndex(mask => ["page", "left", "top", "right", "bottom"].every(key => mask[key] === event.detail[key]));
    if (duplicate >= 0) { selected = duplicate; sync(); return; }
    const before = snapshot();
    if (add({...event.detail})) sync(remember(before));
    else event.preventDefault();
  });
  Object.values(fields).forEach(field => field.addEventListener("change", () => {
    const mask = {page, ...Object.fromEntries(Object.entries(fields).map(([edge, input]) => [edge, input.value === "" ? NaN : Number(input.value)]))};
    Object.values(fields).forEach(input => input.setCustomValidity(""));
    if (!valid(mask)) { status.textContent = "Keep the region within the slide and at least 2 pixels wide and high."; field.setCustomValidity(status.textContent); return; }
    const before = snapshot();
    if (!masks.length) add(mask);
    else masks[selected] = mask;
    sync(remember(before));
  }));
  editor.querySelector("[data-add-mask]")?.addEventListener("click", () => {
    const before = snapshot();
    if (add({page, left: 0, top: 0, right: Math.min(100, width), bottom: Math.min(60, height)})) sync(remember(before));
  });
  editor.querySelector("[data-remove-mask]")?.addEventListener("click", () => {
    const before = snapshot(); masks.splice(selected, 1); selected = Math.max(0, Math.min(selected, masks.length - 1)); sync(remember(before));
  });
  drawButton.addEventListener("click", () => { drawing = !drawing; sync(); stage.focus({preventScroll: true}); });
  undoButton.addEventListener("click", () => { const previous = history.pop(); if (previous) { restore(previous); drawing = false; sync(true); } });
  const position = event => {
    const rect = image.getBoundingClientRect();
    return [Math.round((event.clientX - rect.left) * width / rect.width), Math.round((event.clientY - rect.top) * height / rect.height)];
  };
  const translated = (mask, dx, dy) => {
    dx = clamp(dx, -mask.left, width - mask.right); dy = clamp(dy, -mask.top, height - mask.bottom);
    return {...mask, left: mask.left + dx, right: mask.right + dx, top: mask.top + dy, bottom: mask.bottom + dy};
  };
  const move = event => {
    if (!gesture || event.pointerId !== gesture.pointer) return;
    const end = position(event), [x, y] = gesture.start;
    if (gesture.mode === "draw") {
      pending = {page, left: clamp(Math.min(x, end[0]), 0, width), top: clamp(Math.min(y, end[1]), 0, height), right: clamp(Math.max(x, end[0]), 0, width), bottom: clamp(Math.max(y, end[1]), 0, height)};
    } else {
      const original = gesture.original, dx = end[0] - x, dy = end[1] - y;
      const mask = {...original};
      if (gesture.mode === "move") masks[selected] = translated(original, dx, dy);
      else {
        if (gesture.edge.includes("w")) mask.left = clamp(original.left + dx, 0, original.right - 2);
        if (gesture.edge.includes("e")) mask.right = clamp(original.right + dx, original.left + 2, width);
        if (gesture.edge.includes("n")) mask.top = clamp(original.top + dy, 0, original.bottom - 2);
        if (gesture.edge.includes("s")) mask.bottom = clamp(original.bottom + dy, original.top + 2, height);
        masks[selected] = mask;
      }
      Object.entries(fields).forEach(([key, field]) => { field.value = masks[selected][key]; });
    }
    draw();
  };
  const finish = cancelled => {
    if (!gesture) return;
    const previous = gesture; gesture = null;
    if (cancelled) restore(previous.before);
    else if (previous.mode === "draw" && valid(pending)) add(pending);
    pending = null;
    if (stage.hasPointerCapture(previous.pointer)) stage.releasePointerCapture(previous.pointer);
    sync(!cancelled && remember(previous.before));
  };
  stage.addEventListener("pointerdown", event => {
    if (gesture || !event.isPrimary || event.button !== 0 || !image.complete || !image.naturalWidth) return;
    const region = !drawing && event.target.closest("[data-mask-index]");
    const edge = region && event.target.closest(".mask-handle")?.dataset.maskEdge;
    const mode = region ? (edge ? "resize" : "move") : "draw";
    if (mode === "draw" && !single && masks.length >= limit) { status.textContent = "Save these 20 regions before adding more. Existing regions can still be moved or resized."; return; }
    event.preventDefault(); stage.focus({preventScroll: true});
    const before = snapshot();
    if (region) selected = Number(region.dataset.maskIndex);
    gesture = {mode, edge, pointer: event.pointerId, start: position(event), original: masks[selected] && {...masks[selected]}, before};
    stage.setPointerCapture(event.pointerId);
    sync(); move(event);
  });
  stage.addEventListener("pointermove", move);
  stage.addEventListener("pointerup", event => { if (gesture?.pointer !== event.pointerId) return; move(event); finish(false); });
  stage.addEventListener("pointercancel", event => { if (gesture?.pointer === event.pointerId) finish(true); });
  stage.addEventListener("lostpointercapture", event => { if (gesture?.pointer === event.pointerId) finish(true); });
  stage.addEventListener("keydown", event => {
    if (event.key === "Escape") { event.preventDefault(); finish(true); drawing = false; sync(); return; }
    if (gesture || drawing || !masks[selected] || event.altKey || event.ctrlKey || event.metaKey) return;
    const delta = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]}[event.key];
    if (!delta) return;
    event.preventDefault(); const before = snapshot(), step = event.shiftKey ? 10 : 1;
    masks[selected] = translated(masks[selected], delta[0] * step, delta[1] * step);
    sync(remember(before));
  });
  sync();
});

document.querySelectorAll("[data-note-form]").forEach((form) => {
  const type = form.elements.note_type;
  const front = form.elements.front;
  const output = form.querySelector("[data-preview-output]");
  const updateLabels = () => {
    const cloze = type.value === "cloze";
    const reversed = type.value === "reversed";
    const occlusion = type.value === "occlusion";
    form.querySelectorAll("[data-reverse-help]").forEach(help => { help.hidden = !reversed; });
    const clozeControls = form.querySelector("[data-cloze-controls]");
    if (clozeControls) clozeControls.hidden = !cloze;
    form.querySelector("[data-front-label]").textContent = cloze ? "Cloze text" : reversed ? "Front (prompt for card 1)" : occlusion ? "Prompt" : "Question";
    form.querySelector("[data-back-label]").textContent = (cloze || occlusion) ? "Extra explanation (optional)" : reversed ? "Back (prompt for card 2)" : "Answer";
    form.elements.back.required = !(cloze || occlusion);
  };
  updateLabels();
  form.querySelectorAll('[name="note_type"]').forEach(input => input.addEventListener("change", updateLabels));
  form.querySelector("[data-add-cloze]")?.addEventListener("click", () => {
    const number = form.querySelector("[data-cloze-number]");
    const start = front.selectionStart, end = front.selectionEnd;
    if (!number.checkValidity() || start === end) {
      output.textContent = "Select the words to hide and choose a blank number from 1 to 20.";
      return;
    }
    const selection = front.value.slice(start, end);
    front.setRangeText(`{{c${Number(number.value)}::${selection}}}`, start, end, "select");
    front.dispatchEvent(new Event("input", { bubbles: true }));
    front.focus();
  });
  const previewButton = form.querySelector("[data-preview-note]");
  let previewNumber = 0, previewController = null, previewTimer = null;
  const preview = async (automatic = false) => {
    const button = previewButton;
    if (!(automatic ? form.checkValidity() : form.reportValidity())) return;
    const requestNumber = ++previewNumber;
    previewController?.abort();
    previewController = new AbortController();
    button.disabled = true;
    output.setAttribute("aria-busy", "true");
    try {
      const {response, data} = await requestJson(form.dataset.previewUrl, { method: "POST", body: new FormData(form), signal: previewController.signal });
      if (requestNumber !== previewNumber) return;
      output.replaceChildren();
      if (!response.ok) {
        output.textContent = data.error || "Could not preview this note.";
        return;
      }
      const count = document.createElement("p");
      count.className = "form-note";
      count.setAttribute("role", "status");
      count.textContent = data.caption || `${data.study_cards} Anki review card${data.study_cards === 1 ? "" : "s"} from this note. Preview only; edits have not been saved.`;
      output.append(count);
      data.previews.forEach((preview, index) => {
        const card = document.createElement("article");
        card.className = "preview-card";
        const title = document.createElement("p");
        title.className = "eyebrow";
        title.textContent = `Card ${index + 1} of ${data.study_cards}${preview.direction ? " · " + preview.direction : ""}`;
        const question = document.createElement("div");
        question.className = "preview-question";
        // This endpoint only returns escaped text plus fixed cloze markup.
        question.innerHTML = preview.question;
        const details = document.createElement("details");
        details.open = form.hasAttribute("data-auto-preview");
        const summary = document.createElement("summary");
        summary.textContent = "Show answer";
        const answer = document.createElement("div");
        answer.className = "preview-answer";
        answer.innerHTML = preview.answer;
        for (const [key, target, description] of [["question_image", question, "Slide with one region hidden"], ["answer_image", answer, "Slide with the region revealed"]]) {
          if (!preview[key]) continue;
          const image = document.createElement("img");
          image.src = preview[key];
          image.className = "source-crop";
          image.alt = description;
          target.append(image);
        }
        if (data.crop_image) {
          const crop = document.createElement("img");
          crop.src = data.crop_image;
          crop.className = "source-crop";
          crop.alt = "Selected source crop";
          (data.crop_on_question ? question : answer).append(crop);
        }
        details.append(summary, answer);
        card.append(title, question, details);
        output.append(card);
      });
    } catch (error) {
      if (error.name !== "AbortError" && requestNumber === previewNumber) output.textContent = "Could not reach the local app. Try the preview again.";
    } finally {
      if (requestNumber === previewNumber) { button.disabled = false; output.setAttribute("aria-busy", "false"); }
    }
  };
  previewButton.addEventListener("click", () => { clearTimeout(previewTimer); preview(); });
  if (form.hasAttribute("data-auto-preview")) form.addEventListener("input", event => {
    if (!event.target.name || event.target.name === "preview_index") return;
    clearTimeout(previewTimer);
    previewTimer = setTimeout(() => preview(true), 500);
  });
});

const connectionPanel = document.querySelector('[data-connection-state="waiting"]');
if (connectionPanel) {
  let failures = 0;
  const checkConnection = async () => {
    try {
      const response = await fetch(connectionPanel.dataset.connectionUrl);
      if (!response.ok) throw new Error("Connection check failed");
      const state = await response.json();
      if (state.state !== "waiting") {
        window.location.reload();
        return;
      }
      failures = 0;
    } catch {
      failures += 1;
      if (failures >= 5) {
        connectionPanel.querySelector("[data-connection-message]").textContent = "Could not reach the local app. Refresh this page to check your connection.";
        return;
      }
    }
    window.setTimeout(checkConnection, 1500);
  };
  window.setTimeout(checkConnection, 1500);
}

let dirty = false;
const dirtyForms = new Set();
document.querySelectorAll("[data-note-form]").forEach(form => {
  form.addEventListener("input", event => {
    if (!event.target.name || ["preview_index", "note_type", "page"].includes(event.target.name)) return;
    dirtyForms.add(form);
    dirty = dirtyForms.size > 0;
    const state = form.querySelector("[data-save-state]");
    if (state) state.textContent = "Unsaved changes. Save before moving to another card.";
  });
  form.addEventListener("submit", () => { dirtyForms.delete(form); dirty = dirtyForms.size > 0; });
});
window.addEventListener("beforeunload", event => {
  if (dirty) { event.preventDefault(); event.returnValue = ""; }
});

document.querySelectorAll("form[data-busy]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (event.submitter?.hasAttribute("data-download")) return;
    const button = event.submitter;
    if (button) { button.setAttribute("aria-disabled", "true"); button.textContent = form.dataset.busy; }
    const status = form.querySelector("[data-busy-status]");
    if (status) status.textContent = form.dataset.busy;
  });
});

document.querySelector("[data-toggle-pages]")?.addEventListener("click", (event) => {
  const inputs = [...event.target.closest("form").querySelectorAll('input[name="pages"]:not(:disabled)')];
  const allSelected = inputs.every((input) => input.checked);
  inputs.forEach((input) => { input.checked = !allSelected; });
});

document.querySelector("[data-page-select]")?.addEventListener("change", (event) => {
  const option = event.target.selectedOptions[0];
  const image = document.querySelector("[data-source-image]");
  image.src = option.value;
  image.alt = `Source slide, page ${option.dataset.page}`;
  document.querySelector("[data-source-link]").href = option.value;
  document.querySelectorAll("[data-page-text]").forEach((element) => {
    element.hidden = element.dataset.pageText !== option.dataset.page;
  });
});

const progress = document.querySelector("[data-run-url]");
document.querySelectorAll("[data-view-source]").forEach((button) => {
  button.addEventListener("click", () => {
    const select = document.querySelector("[data-page-select]");
    const option = [...select.options].find((item) => item.dataset.page === button.dataset.viewSource);
    if (!option) return;
    select.value = option.value;
    select.dispatchEvent(new Event("change"));
    document.querySelector(".source-panel").scrollIntoView({ behavior: "smooth", block: "start" });
    select.focus({ preventScroll: true });
  });
});

if (progress) {
  const message = progress.querySelector("[data-run-message]");
  let failures = 0;
  const poll = async () => {
    try {
      const response = await fetch(progress.dataset.runUrl);
      if (!response.ok) throw new Error("Could not get progress");
      const run = await response.json();
      failures = 0;
      const meter = progress.querySelector("progress");
      const context = run.context;
      const readingContext = context?.enabled && !context.ready;
      progress.querySelector("[data-run-heading]").textContent = run.purpose === "rundown" ? "Writing the lecture rundown…" : readingContext ? "Reading the lecture…" : run.image_phase ? (run.visual_enabled ? "Drafting graph/formula questions…" : "Suggesting image regions…") : "Drafting cards…";
      meter.max = readingContext ? (context.total || 1) : run.total;
      meter.value = readingContext ? context.read : run.completed;
      const skipped = run.issues ? ` ${run.issues} drafts skipped; refresh to review the details.` : "";
      const selection = run.purpose === "rundown" ? "" : ` ${run.filtered_count || 0} logistics candidates filtered; ${run.over_limit_count || 0} excluded by the card limit.`;
      const limit = run.card_limit ? ` (maximum ${run.card_limit})` : "";
      const reasoning = `${run.provider} · ${run.model} · ${run.reasoning_effort} reasoning · `;
      const focus = `${run.learning_focus} · ${run.card_format} · `;
      message.textContent = `${reasoning}${focus}${run.completed} of ${run.total} pages processed · ${run.cards_added} draft notes / ${run.study_cards_added} Anki review cards saved${limit}.${skipped}${selection}`;
      if (readingContext) {
        message.textContent = context.stage === "organizing"
          ? `${run.provider}: combining the saved sections into a lecture overview. Cards will follow.`
          : `${run.provider}: reading lecture context, ${context.read} of ${context.total || "all"} readable pages saved. Cards will follow.`;
      }
      if (run.image_phase && !readingContext) message.textContent = `${reasoning}${run.completed} of ${run.total} slide images processed · ${run.suggestions} suggestions saved for review. Text cards follow when selected.`;
      if (run.image_phase && run.visual_enabled && !readingContext) message.textContent = `${reasoning}${run.completed} of ${run.total} slide images processed. ${run.cards_added} visual drafts saved; text cards follow when selected.`;
      if (run.purpose === "rundown") message.textContent = `${reasoning}${run.completed} of ${run.total} readable pages saved to your lecture rundown.`;
      if (run.status === "running" && run.error) {
        progress.querySelector("[data-run-heading]").textContent = "Correcting generated output…";
        message.textContent = run.error;
      }
      if (!["queued", "running"].includes(run.status)) {
        progress.querySelector("[data-run-heading]").textContent = `Generation ${run.status}`;
        message.textContent = (run.error || `Generation ${run.status}. Your ${run.purpose === "rundown" ? "rundown sections" : "drafts"} are saved.`) + skipped + selection;
        const link = document.createElement("a");
        link.href = window.location.href;
        link.textContent = run.purpose === "rundown" ? " Refresh for saved sections and recovery" : " Refresh to see drafts and recovery options →";
        message.append(link);
        if ((run.suggestions || run.purpose === "rundown") && run.review_url) {
          const review = document.createElement("a");
          review.href = run.review_url; review.textContent = run.purpose === "rundown" ? " Open lecture rundown" : ` Review ${run.suggestions} image suggestions →`;
          message.append(review);
          if (run.status === "completed" && !dirty) { window.location.assign(run.review_url); return; }
        }
        // Never reload an editor automatically: there may be unsaved work.
        return;
      }
    } catch {
      failures += 1;
      message.textContent = "Waiting for the local app to reconnect. Saved drafts are safe.";
      if (failures >= 10) return;
    }
    window.setTimeout(poll, 2000);
  };
  window.setTimeout(poll, 1000);
}


const suggestionForm = document.querySelector("[data-suggestion-form]");
if (suggestionForm) {
  const panel = suggestionForm.closest("details"), editor = document.querySelector("[data-occlusion-editor]");
  const start = suggestionForm.querySelector("[data-start-suggestions]"), stop = suggestionForm.querySelector("[data-stop-suggestions]");
  const message = suggestionForm.querySelector("[data-suggestion-status]"), results = panel.querySelector("[data-suggestion-results]");
  let current = null, timer = null, requestNumber = 0;
  const statusUrl = id => `${suggestionForm.action}${id}/`;
  const busy = value => { start.disabled = value; stop.hidden = !value; };
  const render = job => {
    results.replaceChildren();
    if (job.status !== "completed") return;
    message.textContent = job.suggestions.length
      ? `${job.suggestions.length} suggestions ready. Choose regions to add to the editor, then check their placement. No cards have been created.`
      : "No suitable regions were suggested. You can still draw a region yourself.";
    job.suggestions.forEach((suggestion, index) => {
      const article = document.createElement("article"), title = document.createElement("h3"), reason = document.createElement("p"), use = document.createElement("button");
      article.className = "suggested-region";
      title.textContent = `${index + 1}. ${suggestion.label}`; reason.textContent = suggestion.reason;
      use.type = "button"; use.className = "button secondary"; use.textContent = `Use suggestion ${index + 1}`;
      use.addEventListener("click", () => {
        const event = new CustomEvent("use-suggested-mask", {detail: suggestion.mask, cancelable: true});
        if (editor.dispatchEvent(event)) {
          message.textContent = `Region ${index + 1} is in the editor. Move or resize it as needed, then add drafts to save.`;
          editor.scrollIntoView({behavior: "smooth", block: "start"});
        } else message.textContent = "Finish the current drag or remove a region before adding this suggestion.";
      });
      article.append(title, reason, use); results.append(article);
    });
  };
  const poll = async (id, number) => {
    try {
      const response = await fetch(statusUrl(id));
      const job = await response.json();
      if (number !== requestNumber) return;
      if (!response.ok) throw new Error(job.error || "Could not read suggestions.");
      if (job.status === "running") {
        message.textContent = `Analysing this slide with Codex (${job.model || "CLI default"}, ${job.reasoning_effort || "default"} reasoning)${job.context_used ? " and the saved overview" : ""}. You can keep editing or stop the request.`;
        timer = window.setTimeout(() => poll(id, number), 1000);
      } else {
        current = null; busy(false);
        message.textContent = job.error || "Suggestions stopped. Your regions and cards are unchanged.";
        render(job);
      }
    } catch (error) {
      if (number !== requestNumber) return;
      message.textContent = `Could not read progress. ${error.message} Use Stop suggestions before trying again.`;
      // Keep the active request and Stop control: a dropped poll must not start another model call.
    }
  };
  suggestionForm.elements.overview?.addEventListener("change", () => { suggestionForm.elements.consent.checked = false; });
  suggestionForm.addEventListener("submit", async event => {
    event.preventDefault();
    if (start.disabled || !suggestionForm.reportValidity()) return;
    const number = ++requestNumber;
    busy(true); results.replaceChildren(); message.textContent = "Starting image suggestions…";
    // Until the server returns a job ID, there is no request we can cancel.
    stop.hidden = true;
    try {
      const response = await fetch(suggestionForm.action, {method: "POST", body: new FormData(suggestionForm)});
      const job = await response.json();
      if (!response.ok) throw new Error(job.error || "Could not start image suggestions.");
      current = job.id; stop.hidden = false;
      await poll(job.id, number);
    } catch (error) {
      busy(false); message.textContent = error.message;
    }
  });
  stop.addEventListener("click", async () => {
    if (!current) return;
    stop.disabled = true;
    try {
      const response = await fetch(`${statusUrl(current)}cancel/`, {method: "POST", headers: {"X-CSRFToken": suggestionForm.elements.csrfmiddlewaretoken.value}});
      if (!response.ok) throw new Error("Could not stop the request. Try again.");
      requestNumber += 1; window.clearTimeout(timer); current = null; busy(false);
      message.textContent = "Suggestions stopped. Your regions and cards are unchanged.";
    } catch (error) { message.textContent = error.message; }
    finally { stop.disabled = false; }
  });
  window.addEventListener("pagehide", () => {
    if (current) {
      const body = new FormData(); body.set("csrfmiddlewaretoken", suggestionForm.elements.csrfmiddlewaretoken.value);
      navigator.sendBeacon(`${statusUrl(current)}cancel/`, body);
    }
  });
}

document.querySelectorAll("[data-image-format]").forEach(input => {
  const form = input.closest("form"), provider = form.querySelector("[data-provider-select]");
  const update = () => {
    input.setCustomValidity(input.checked && provider.value !== "codex" ? "Choose Codex for visual questions, or untick this format." : "");
    form.querySelector("[data-image-sharing]").hidden = !input.checked;
    form.querySelector("[data-download]").disabled = input.checked;
    form.querySelectorAll("[data-image-only]").forEach(page => {
      if (page.disabled && input.checked) page.checked = true;
      page.disabled = !input.checked;
      if (!input.checked) page.checked = false;
    });
  };
  input.addEventListener("change", () => { form.elements.consent.checked = false; update(); });
  provider.addEventListener("change", update);
  update();
});

document.querySelectorAll("[data-lecture-context]").forEach(input => {
  const form = input.closest("form");
  const showScope = () => { form.querySelector("[data-context-sharing]").textContent = input.checked ? "text from all readable slides" : "selected slide text"; };
  input.addEventListener("change", () => { form.elements.consent.checked = false; showScope(); });
  showScope();
});

initWorkspace(() => dirty);
