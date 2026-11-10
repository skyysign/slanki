// Presentation behavior only: source data and persisted edits remain backend operations.
import {initSlideViewer} from "./slide-viewer.js";

export function initWorkspace(isDirty) {
  initSlideViewer();
  document.querySelectorAll("[data-open-dialog]").forEach(button => button.addEventListener("click", () => {
    const dialog = document.getElementById(button.dataset.openDialog);
    if (!dialog.open) dialog.showModal();
    button.closest(".workspace-menu")?.removeAttribute("open");
    if (dialog.id === "keep-drafts") {
      const unsaved = isDirty();
      dialog.querySelector("[data-keep-all-unsaved]").hidden = !unsaved;
      dialog.querySelector("[data-keep-all-submit]").disabled = unsaved;
    }
    if (dialog.id === "manual-card") {
      const page = document.querySelector("[data-page-select]")?.selectedOptions[0]?.dataset.page;
      if (page) dialog.querySelector('[name="page"]').value = page;
    }
  }));
  document.querySelectorAll("[data-close-dialog]").forEach(button => button.addEventListener("click", () => button.closest("dialog").close()));
  document.querySelector("[data-keep-all-form]")?.addEventListener("submit", event => {
    if (isDirty()) {
      event.preventDefault();
      event.currentTarget.querySelector("[data-keep-all-submit]").disabled = true;
      event.currentTarget.closest("dialog").querySelector("[data-keep-all-unsaved]").hidden = false;
    }
  });
  document.querySelectorAll(".workspace-menu a").forEach(link => link.addEventListener("click", () => link.closest("details").removeAttribute("open")));

  const workspace = document.querySelector(".lecture-workspace"), form = document.querySelector("[data-card-form]");
  if (workspace) {
    const show = () => workspace.classList.add("viewing-source");
    document.querySelectorAll("[data-show-source],[data-view-source]").forEach(button => button.addEventListener("click", show));
    document.querySelectorAll("[data-hide-source]").forEach(button => button.addEventListener("click", () => workspace.classList.remove("viewing-source")));
  }
  if (workspace && form) {
    const editFields = form.querySelector("[data-edit-fields]");
    form.addEventListener("invalid", event => { if (editFields?.contains(event.target)) editFields.open = true; }, true);
    document.addEventListener("keydown", event => {
      if (event.ctrlKey || event.metaKey || event.altKey || event.target.closest("input,textarea,select,[contenteditable=true],[data-mask-stage],[data-crop-stage]") || document.querySelector("dialog[open]")) return;
      const key = event.key.toLowerCase();
      if (key === "e") { event.preventDefault(); editFields.open = true; form.elements.front.focus(); }
      if (key === "a" || key === "s") {
        const button = form.querySelector(key === "a" ? "[data-keep-next]" : "[data-set-aside]");
        if (button) { event.preventDefault(); form.requestSubmit(button); }
      }
      if (key === "z" && !isDirty()) {
        const undo = document.querySelector("[data-undo-review]");
        if (undo) { event.preventDefault(); undo.form.requestSubmit(undo); }
      }
    });
    const sourceTools = [...form.querySelectorAll("[data-source-tool]")];
    sourceTools.forEach(tool => tool.addEventListener("toggle", () => {
      if (tool.open) sourceTools.forEach(other => { if (other !== tool) other.open = false; });
      form.querySelector(".source-panel").classList.toggle("editing-source", sourceTools.some(item => item.open));
    }));
  }
  const generation = document.querySelector("[data-generation-form]");
  if (generation) {
    generation.addEventListener("invalid", event => {
      let details = event.target.closest("details");
      while (details && generation.contains(details)) { details.open = true; details = details.parentElement.closest("details"); }
    }, true);
    const update = () => {
      const selected = [...generation.querySelectorAll('[name="pages"]:checked:not(:disabled)')];
      generation.querySelector("[data-scope-summary]").textContent = `Source slides · ${selected.length} selected`;
      const formats = [...generation.querySelectorAll('[name="formats"]:checked')].map(input => input.value);
      generation.querySelector("[data-formats-summary]").textContent = formats.length === 2 && formats.includes("basic") && formats.includes("cloze")
        ? "Automatic · Q/A or cloze" : formats.map(value => ({basic: "Q/A", cloze: "Cloze", reversed: "Reverse", visual: "Figures"})[value]).join(" + ") || "Choose formats";
    };
    generation.addEventListener("change", update);
    generation.querySelector("[data-toggle-pages]").addEventListener("click", update);
    update();
    document.querySelector("[data-figure-question]")?.addEventListener("click", () => {
      const dialog = generation.closest("dialog");
      const image = generation.querySelector('[name="formats"][value="visual"]');
      const page = document.querySelector("[data-page-select]")?.selectedOptions[0]?.dataset.page;
      generation.querySelectorAll('[name="formats"]').forEach(input => { input.checked = input === image; });
      image.dispatchEvent(new Event("change", {bubbles: true}));
      generation.querySelectorAll('[name="pages"]').forEach(input => { input.checked = input.value === page; });
      generation.querySelector(".advanced-generation").open = true;
      generation.elements.consent.checked = false;
      update();
      document.querySelectorAll(".source-tools details").forEach(item => { item.open = false; });
      dialog.showModal();
    });
  }
  document.querySelector("[data-page-select]")?.addEventListener("change", event => {
    const tool = document.querySelector("[data-label-tool]");
    if (!tool) return;
    const url = new URL(tool.href);
    url.searchParams.set("page", event.target.selectedOptions[0].dataset.page);
    tool.href = url.href;
  });
  document.querySelectorAll("[data-search-library]").forEach(input => input.addEventListener("input", () => {
    const term = input.value.trim().toLocaleLowerCase();
    document.querySelectorAll(".lecture-tile").forEach(tile => { tile.hidden = !tile.textContent.toLocaleLowerCase().includes(term); });
  }));
  document.querySelectorAll("dialog[data-open-on-load]").forEach(dialog => dialog.showModal());
}
