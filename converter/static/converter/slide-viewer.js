// In-memory image inspection only. No model requests, persistence, or note changes.
export function initSlideViewer() {
  const dialog = document.querySelector("[data-slide-viewer]");
  if (!dialog) return;
  const viewport = dialog.querySelector("[data-slide-viewport]");
  const canvas = dialog.querySelector("[data-slide-canvas]");
  const status = dialog.querySelector("[data-slide-status]");
  const retry = dialog.querySelector("[data-slide-retry]");
  const zoomLabel = dialog.querySelector("[data-slide-zoom]");
  const previous = dialog.querySelector("[data-slide-previous]");
  const next = dialog.querySelector("[data-slide-next]");
  const zoomIn = dialog.querySelector("[data-slide-zoom-in]");
  const zoomOut = dialog.querySelector("[data-slide-zoom-out]");
  const fitButton = dialog.querySelector("[data-slide-fit]");
  const actualButton = dialog.querySelector("[data-slide-actual]");
  const controls = [zoomIn, zoomOut, fitButton, actualButton];
  const pointers = new Map();
  const padding = 20;
  const minimum = 0.1, maximum = 6;
  let image = null, scale = 1, fitted = true, loaded = false;
  let layout = {left: 0, top: 0};
  let pages = [], index = 0, sourceSelect = null, opener = null, gesture = null;

  const fitScale = () => image ? Math.min(
    (viewport.clientWidth - padding * 2) / image.naturalWidth,
    (viewport.clientHeight - padding * 2) / image.naturalHeight,
  ) : 1;
  const clamp = value => Math.max(minimum, Math.min(maximum, value));
  const draw = () => {
    if (!loaded) return;
    const width = image.naturalWidth * scale, height = image.naturalHeight * scale;
    const canvasWidth = Math.max(viewport.clientWidth, width + padding * 2);
    const canvasHeight = Math.max(viewport.clientHeight, height + padding * 2);
    canvas.style.width = `${canvasWidth}px`;
    canvas.style.height = `${canvasHeight}px`;
    layout = {left: (canvasWidth - width) / 2, top: (canvasHeight - height) / 2};
    image.style.width = `${width}px`; image.style.height = `${height}px`;
    image.style.left = `${layout.left}px`; image.style.top = `${layout.top}px`;
    zoomLabel.value = `${Math.round(scale * 100)}%`;
    zoomIn.disabled = scale >= maximum;
    zoomOut.disabled = scale <= minimum;
    viewport.classList.toggle("can-pan", canvasWidth > viewport.clientWidth || canvasHeight > viewport.clientHeight);
  };
  const relative = (clientX, clientY) => {
    const rect = viewport.getBoundingClientRect();
    return {x: clientX - rect.left, y: clientY - rect.top};
  };
  const pointOnImage = point => ({
    x: (viewport.scrollLeft + point.x - layout.left) / scale,
    y: (viewport.scrollTop + point.y - layout.top) / scale,
  });
  const placePoint = (point, imagePoint) => {
    viewport.scrollLeft = layout.left + imagePoint.x * scale - point.x;
    viewport.scrollTop = layout.top + imagePoint.y * scale - point.y;
  };
  const zoom = (value, point = {x: viewport.clientWidth / 2, y: viewport.clientHeight / 2}) => {
    if (!loaded) return;
    const anchor = pointOnImage(point);
    fitted = false; scale = clamp(value); draw(); placePoint(point, anchor);
  };
  const fit = () => {
    if (!loaded) return;
    fitted = true; scale = clamp(fitScale()); draw();
    viewport.scrollLeft = 0; viewport.scrollTop = 0;
  };
  const stopGesture = () => {
    pointers.forEach((_, id) => {
      if (viewport.hasPointerCapture(id)) viewport.releasePointerCapture(id);
    });
    pointers.clear(); gesture = null; viewport.classList.remove("panning");
  };
  const load = () => {
    stopGesture(); loaded = false;
    canvas.style.width = "100%"; canvas.style.height = "100%";
    viewport.scrollLeft = 0; viewport.scrollTop = 0;
    viewport.classList.remove("can-pan"); zoomLabel.value = "—";
    controls.forEach(button => { button.disabled = true; });
    previous.disabled = index === 0; next.disabled = index === pages.length - 1;
    dialog.querySelector("[data-slide-title]").textContent = `Source slide · ${pages[index].label}`;
    status.textContent = "Loading slide…"; status.hidden = false;
    status.setAttribute("role", "status"); retry.hidden = true;
    viewport.setAttribute("aria-busy", "true");
    const candidate = new Image();
    image = candidate; candidate.alt = `Source slide, ${pages[index].label}`;
    candidate.draggable = false; candidate.hidden = true;
    candidate.setAttribute("data-slide-image", "");
    canvas.replaceChildren(candidate);
    candidate.addEventListener("load", () => {
      if (image !== candidate || !dialog.open) return;
      loaded = true; candidate.hidden = false; status.hidden = true;
      viewport.setAttribute("aria-busy", "false");
      controls.forEach(button => { button.disabled = false; });
      fit();
    });
    candidate.addEventListener("error", () => {
      if (image !== candidate || !dialog.open) return;
      status.textContent = "This slide could not be loaded. Try again or return to your card.";
      status.setAttribute("role", "alert"); retry.hidden = false;
      viewport.setAttribute("aria-busy", "false");
    });
    candidate.src = pages[index].url;
  };
  const navigate = step => {
    if (index + step < 0 || index + step >= pages.length) return;
    index += step;
    if (sourceSelect) {
      sourceSelect.value = pages[index].url;
      sourceSelect.dispatchEvent(new Event("change", {bubbles: true}));
    }
    load();
  };

  document.querySelectorAll("[data-slide-open]").forEach(link => link.addEventListener("click", event => {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); opener = link;
    sourceSelect = document.querySelector("[data-page-select]");
    pages = sourceSelect ? [...sourceSelect.options].map(option => ({url: option.value, label: option.textContent.trim()}))
      : [{url: link.href, label: link.querySelector("img")?.alt || "Source"}];
    index = Math.max(0, pages.findIndex(page => page.url === link.getAttribute("href") || new URL(page.url, location.href).href === link.href));
    dialog.showModal(); load();
  }));
  dialog.querySelector("[data-slide-close]").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => {
    stopGesture(); loaded = false;
    if (image) image.removeAttribute("src");
    image = null; canvas.replaceChildren();
    opener?.focus({preventScroll: true});
  });
  dialog.addEventListener("click", event => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  });
  previous.addEventListener("click", () => navigate(-1));
  next.addEventListener("click", () => navigate(1));
  retry.addEventListener("click", load);
  zoomIn.addEventListener("click", () => zoom(scale * 1.25));
  zoomOut.addEventListener("click", () => zoom(scale / 1.25));
  fitButton.addEventListener("click", fit);
  actualButton.addEventListener("click", () => zoom(1));
  viewport.addEventListener("wheel", event => {
    if (!loaded) return;
    event.preventDefault();
    zoom(scale * Math.exp(-event.deltaY * 0.002), relative(event.clientX, event.clientY));
  }, {passive: false});
  viewport.addEventListener("dblclick", event => {
    if (scale > fitScale() * 1.1) fit();
    else zoom(scale * 2, relative(event.clientX, event.clientY));
  });
  const beginGesture = () => {
    const points = [...pointers.values()];
    if (points.length === 2) {
      const midpoint = {x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2};
      gesture = {type: "pinch", distance: Math.max(1, Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y)), scale, anchor: pointOnImage(midpoint)};
    } else if (points.length === 1) gesture = {type: "pan", point: points[0], left: viewport.scrollLeft, top: viewport.scrollTop};
    else gesture = null;
  };
  viewport.addEventListener("pointerdown", event => {
    if (!loaded || pointers.size >= 2 || (event.pointerType === "mouse" && event.button !== 0)) return;
    event.preventDefault();
    pointers.set(event.pointerId, relative(event.clientX, event.clientY));
    viewport.setPointerCapture(event.pointerId); beginGesture();
    viewport.classList.add("panning");
  });
  viewport.addEventListener("pointermove", event => {
    if (!pointers.has(event.pointerId) || !gesture) return;
    pointers.set(event.pointerId, relative(event.clientX, event.clientY));
    if (gesture.type === "pan") {
      const point = pointers.get(event.pointerId);
      viewport.scrollLeft = gesture.left - (point.x - gesture.point.x);
      viewport.scrollTop = gesture.top - (point.y - gesture.point.y);
    } else {
      const points = [...pointers.values()];
      const distance = Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
      const midpoint = {x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2};
      fitted = false; scale = clamp(gesture.scale * distance / gesture.distance);
      draw(); placePoint(midpoint, gesture.anchor);
    }
  });
  const endPointer = event => {
    if (!pointers.delete(event.pointerId)) return;
    beginGesture();
    if (!pointers.size) viewport.classList.remove("panning");
  };
  viewport.addEventListener("pointerup", endPointer);
  viewport.addEventListener("pointercancel", endPointer);
  viewport.addEventListener("lostpointercapture", endPointer);
  dialog.addEventListener("keydown", event => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (["+", "="].includes(event.key)) { event.preventDefault(); zoom(scale * 1.25); }
    if (event.key === "-") { event.preventDefault(); zoom(scale / 1.25); }
    if (event.key === "0") { event.preventDefault(); fit(); }
    if (["ArrowLeft", "ArrowRight"].includes(event.key)) {
      event.preventDefault();
      const step = event.key === "ArrowLeft" ? -1 : 1;
      if (fitted) navigate(step); else viewport.scrollLeft += step * 60;
    }
    if (["ArrowUp", "ArrowDown"].includes(event.key)) { event.preventDefault(); viewport.scrollTop += event.key === "ArrowUp" ? -60 : 60; }
  });
  new ResizeObserver(() => { if (dialog.open && loaded) { if (fitted) fit(); else draw(); } }).observe(viewport);
}
