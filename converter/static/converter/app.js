"use strict";

document.querySelectorAll("[data-note-form]").forEach((form) => {
  const type = form.elements.note_type;
  const front = form.elements.front;
  const output = form.querySelector("[data-preview-output]");
  const updateLabels = () => {
    const cloze = type.value === "cloze";
    form.querySelector("[data-cloze-controls]").hidden = !cloze;
    form.querySelector("[data-front-label]").textContent = cloze ? "Cloze text" : "Question";
    form.querySelector("[data-back-label]").textContent = cloze ? "Extra explanation (optional)" : "Answer";
    form.elements.back.required = !cloze;
  };
  updateLabels();
  type.addEventListener("change", updateLabels);
  form.querySelector("[data-add-cloze]").addEventListener("click", () => {
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
  form.querySelector("[data-preview-note]").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const response = await fetch(form.dataset.previewUrl, { method: "POST", body: new FormData(form) });
      const data = await response.json();
      output.replaceChildren();
      if (!response.ok) {
        output.textContent = data.error || "Could not preview this note.";
        return;
      }
      const count = document.createElement("p");
      count.className = "form-note";
      count.setAttribute("role", "status");
      count.textContent = `${data.study_cards} Anki review card${data.study_cards === 1 ? "" : "s"} from this note. Preview only; edits have not been saved.`;
      output.append(count);
      data.previews.forEach((preview, index) => {
        const card = document.createElement("article");
        card.className = "preview-card";
        const title = document.createElement("p");
        title.className = "eyebrow";
        title.textContent = `Card ${index + 1} of ${data.study_cards}`;
        const question = document.createElement("div");
        question.className = "preview-question";
        // This endpoint only returns escaped text plus fixed cloze markup.
        question.innerHTML = preview.question;
        const details = document.createElement("details");
        const summary = document.createElement("summary");
        summary.textContent = "Show answer";
        const answer = document.createElement("div");
        answer.className = "preview-answer";
        answer.innerHTML = preview.answer;
        details.append(summary, answer);
        card.append(title, question, details);
        output.append(card);
      });
    } catch {
      output.textContent = "Could not reach the local app. Try the preview again.";
    } finally {
      button.disabled = false;
    }
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
const cardForm = document.querySelector("[data-card-form]");
if (cardForm) {
  cardForm.addEventListener("input", () => {
    dirty = true;
    document.querySelector("[data-save-state]").textContent = "Unsaved changes. Save before moving to another card.";
  });
  cardForm.addEventListener("submit", () => { dirty = false; });
  window.addEventListener("beforeunload", (event) => {
    if (dirty) { event.preventDefault(); event.returnValue = ""; }
  });
}

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
      progress.querySelector("progress").value = run.completed;
      const skipped = run.issues ? ` ${run.issues} drafts skipped; refresh to review the details.` : "";
      const selection = ` ${run.filtered_count || 0} logistics candidates filtered; ${run.over_limit_count || 0} excluded by the card limit.`;
      const limit = run.card_limit ? ` (maximum ${run.card_limit})` : "";
      const reasoning = run.reasoning_effort ? `${run.reasoning_effort} reasoning · ` : "";
      const focus = `${run.learning_focus} · ${run.card_format} · `;
      message.textContent = `${reasoning}${focus}${run.completed} of ${run.total} pages processed · ${run.cards_added} draft notes / ${run.study_cards_added} Anki review cards saved${limit}.${skipped}${selection}`;
      if (!["queued", "running"].includes(run.status)) {
        message.textContent = (run.error || `Generation ${run.status}. Your drafts are saved.`) + skipped + selection;
        const link = document.createElement("a");
        link.href = window.location.href;
        link.textContent = " Refresh to see drafts and recovery options →";
        message.append(link);
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
