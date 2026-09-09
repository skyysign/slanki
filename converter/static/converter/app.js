"use strict";

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
      message.textContent = `${run.completed} of ${run.total} pages processed · ${run.cards_added} new drafts saved.${skipped}`;
      if (!["queued", "running"].includes(run.status)) {
        message.textContent = (run.error || `Generation ${run.status}. Your drafts are saved.`) + skipped;
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
