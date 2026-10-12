const STATUS = {
  todo: { label: "Non validée", color: "#777" },
  in_progress: { label: "En cours", color: "#b87800" },
  review: { label: "À relire", color: "#7650a8" },
  done: { label: "Validée", color: "#258044" },
};

const CATEGORY = {
  unclassified: { label: "Non classée" },
  open: { label: "Non colmatée" },
  filled: { label: "Colmatée" },
  mixed: { label: "Mixte" },
  uncertain: { label: "Incertaine" },
};

const state = {
  metadata: null,
  zones: [],
  selectedZoneId: null,
  cracks: [],
  selectedCrackId: null,
  draftCrackId: null,
  pendingStart: null,
  mode: "select",
  finishRequested: false,
  viewer: null,
  zoneOverlays: new Map(),
  crackOverlay: null,
  allCracksOverlay: null,
  allCracks: [],
  allCracksLoaded: false,
  allCracksVisible: false,
  allCracksRequest: 0,
  analysisOverlay: null,
  analysisRequest: 0,
  lengthRequest: 0,
  zoneRequest: 0,
  cracksLoaded: false,
  routing: false,
  dragging: null,
  zonesVisible: false,
  tracesVisible: true,
  preparedZones: new Map(),
  paletteCrackId: null,
  undoStack: [],
  undoRequested: false,
};

const ids = [
  "image-name", "annotator", "server-status", "open-analysis", "insert-node", "mode-select", "mode-draw", "undo-point", "detect-cracks",
  "previous-zone", "current-zone",
  "next-zone", "delete-crack", "toggle-zones", "toggle-traces", "toggle-all-cracks", "all-cracks-opacity", "home",
  "zoom-out", "zoom-in", "brightness", "brightness-value", "contrast",
  "contrast-value", "reset-display", "viewer", "viewer-message",
  "busy-indicator", "busy-text", "action-status", "selection-summary",
  "coordinates", "zone-summary", "image-category-palette", "palette-delete",
];
const elements = Object.fromEntries(ids.map((id) => [id, document.getElementById(id)]));

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try { message = (await response.json()).detail || message; } catch (_) { /* réponse vide */ }
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function selectedZone() {
  return state.zones.find((zone) => zone.id === state.selectedZoneId) || null;
}

function selectedCrack() {
  return state.cracks.find((crack) => crack.id === state.selectedCrackId) || null;
}

function draftCrack() {
  return state.cracks.find((crack) => crack.id === state.draftCrackId) || null;
}

function zoneName(zone) {
  return `L${String(zone.row_index + 1).padStart(2, "0")} · C${String(zone.col_index + 1).padStart(2, "0")}`;
}

function zoneAtPoint(point) {
  return state.zones.find((zone) =>
    point.x >= zone.x && point.x < zone.x + zone.width &&
    point.y >= zone.y && point.y < zone.y + zone.height
  ) || null;
}

function setStatus(message, kind = "") {
  elements["action-status"].textContent = message;
  elements["action-status"].className = kind;
}

function setBusy(visible, message = "Calcul du chemin…") {
  state.routing = visible;
  elements["busy-text"].textContent = message;
  elements["busy-indicator"].classList.toggle("hidden", !visible);
  renderDetectionControl();
  renderUndoPointControl();
  if (!visible && state.finishRequested) {
    state.finishRequested = false;
    finishDraft();
  }
  if (!visible && state.undoRequested) {
    state.undoRequested = false;
    queueMicrotask(undoLastAction);
  }
}

const lengthFormatter = new Intl.NumberFormat("fr-FR", {
  maximumFractionDigits: 1,
});

function loadLengthStatistics() {
  window.dispatchEvent(new Event('crack-data-changed'));
}

function setMode(mode) {
  state.mode = mode;
  elements["mode-select"].classList.toggle("active", mode === "select");
  elements["mode-draw"].classList.toggle("active", mode === "draw");
  elements["insert-node"].classList.toggle("active", mode === "insert");
  elements.viewer.classList.toggle("draw-mode", mode === "draw" || mode === "insert");
  if (mode === "select") {
    state.draftCrackId = null;
    if (state.pendingStart) state.pendingStart = null;
    renderCracks();
    setStatus("Mode Sélection · clique une fissure ; glisse pour naviguer");
  } else if (mode === "insert") {
    setStatus("Cliquer n'importe où sur la fissure sélectionnée pour ajouter un nœud · Échap pour quitter");
  } else {
    setStatus(draftCrack()
      ? "Mode Tracer · clique pour prolonger la fissure en cours"
      : "Mode Tracer · clique pour placer les points de la fissure");
  }
}

function rememberUndo(action) {
  state.undoStack.push(action);
  if (state.undoStack.length > 100) state.undoStack.shift();
}

function tileSource(meta) {
  const source = new OpenSeadragon.TileSource({
    width: meta.width,
    height: meta.height,
    tileSize: meta.tile_size,
    tileOverlap: 0,
    minLevel: meta.min_level,
    maxLevel: meta.max_level,
  });
  source.getTileUrl = (level, x, y) => `/api/tiles/${level}/${x}/${y}.png?v=${encodeURIComponent(meta.tile_cache_key)}`;
  return source;
}

function initializeViewer(meta) {
  state.viewer = OpenSeadragon({
    id: "viewer",
    drawer: "canvas",
    navigatorDrawer: "canvas",
    tileSources: tileSource(meta),
    showNavigationControl: false,
    showNavigator: true,
    navigatorPosition: "BOTTOM_RIGHT",
    navigatorSizeRatio: 0.12,
    animationTime: 0,
    blendTime: 0,
    immediateRender: true,
    maxZoomPixelRatio: 4,
    visibilityRatio: 0.08,
    constrainDuringPan: true,
    gestureSettingsMouse: {
      clickToZoom: false,
      dblClickToZoom: false,
      dragToPan: true,
      scrollToZoom: true,
    },
  });

  state.viewer.addHandler("open", () => {
    elements["viewer-message"].classList.add("hidden");
    addZoneOverlays();
    restoreZone();
    applyDisplayFilters();
    if (state.allCracksVisible) loadAllCracks();
  });
  state.viewer.addHandler("open-failed", (event) => {
    elements["viewer-message"].textContent = event.message || "Impossible d’ouvrir l’image.";
    elements["server-status"].className = "connection error";
  });
  state.viewer.addHandler("canvas-click", (event) => {
    if (state.routing || event.quick === false) return;
    event.preventDefaultAction = true;
    const viewerRect = elements.viewer.getBoundingClientRect();
    handleCanvasClick(webToImage(event.position), {
      clientX: viewerRect.left + event.position.x,
      clientY: viewerRect.top + event.position.y,
      shiftKey: Boolean(event.originalEvent?.shiftKey),
    });
  });
  state.viewer.addHandler("zoom", () => updateCoordinates());
  state.viewer.addHandler("animation", () => updateCoordinates());

  new OpenSeadragon.MouseTracker({
    element: state.viewer.canvas,
    moveHandler: (event) => updateCoordinates(event.position),
    exitHandler: () => updateCoordinates(),
  }).setTracking(true);
}

function webToImage(webPoint) {
  const viewportPoint = state.viewer.viewport.pointFromPixel(webPoint);
  return state.viewer.world.getItemAt(0).viewportToImageCoordinates(viewportPoint);
}

function clientToImage(clientX, clientY) {
  const rect = elements.viewer.getBoundingClientRect();
  return webToImage(new OpenSeadragon.Point(clientX - rect.left, clientY - rect.top));
}

function updateCoordinates(webPoint = null) {
  if (!state.viewer?.world.getItemCount()) return;
  let position = "x — · y —";
  if (webPoint) {
    const point = webToImage(webPoint);
    if (point.x >= 0 && point.y >= 0 && point.x < state.metadata.width && point.y < state.metadata.height) {
      position = `x ${Math.round(point.x).toLocaleString("fr-FR")} · y ${Math.round(point.y).toLocaleString("fr-FR")}`;
    }
  }
  const zoom = state.viewer.viewport.viewportToImageZoom(state.viewer.viewport.getZoom());
  elements.coordinates.textContent = `${position} · zoom ${zoom.toFixed(2)}×`;
}

function addZoneOverlays() {
  const image = state.viewer.world.getItemAt(0);
  for (const zone of state.zones) {
    const overlay = document.createElement("div");
    overlay.className = "work-zone";
    overlay.dataset.zoneId = zone.id;
    overlay.style.setProperty("--zone-color", STATUS[zone.status].color);
    const location = image.imageToViewportRectangle(zone.x, zone.y, zone.width, zone.height);
    state.viewer.addOverlay({ element: overlay, location, checkResize: false });
    state.zoneOverlays.set(zone.id, overlay);
  }
  updateZoneOverlayStyles();
}

function updateZoneOverlayStyles() {
  elements.viewer.classList.toggle("zones-visible", state.zonesVisible);
  elements["toggle-zones"].classList.toggle("active", state.zonesVisible);
  for (const [id, overlay] of state.zoneOverlays.entries()) {
    overlay.classList.toggle("selected", id === state.selectedZoneId);
  }
}

function renderZoneState() {
  const zone = selectedZone();
  elements["current-zone"].textContent = zone ? zoneName(zone) : "Aucune tuile";
  elements["previous-zone"].disabled = !zone;
  elements["next-zone"].disabled = !state.zones.length;
  document.querySelectorAll("[data-zone-status]").forEach((button) => {
    button.disabled = !zone;
    button.classList.toggle("active", zone?.status === button.dataset.zoneStatus);
  });
  updateZoneOverlayStyles();
  renderDetectionControl();
}

function renderAnalysisOverlay() {
  window.dispatchEvent(new Event('crack-zone-changed'));
}

function renderDetectionControl() {
  const button = elements["detect-cracks"];
  if (!button) return;
  const hasWork = state.cracksLoaded && state.cracks.some((crack) => crack.state !== "rejected");
  button.disabled = !state.selectedZoneId || !state.cracksLoaded || state.routing || hasWork;
  button.title = hasWork
    ? "Cette tuile contient déjà un travail : détection bloquée pour éviter les doublons."
    : "Proposer automatiquement les axes de fissures de la tuile (A)";
}

async function selectZone(zoneId, focus = false) {
  const zone = state.zones.find((item) => item.id === zoneId);
  if (!zone) return;
  const changed = state.selectedZoneId !== zoneId;
  if (changed) {
    state.selectedZoneId = zoneId;
    state.selectedCrackId = null;
    state.draftCrackId = null;
    state.pendingStart = null;
    state.cracks = [];
    state.cracksLoaded = false;
    hideCategoryPalette();
  }
  localStorage.setItem("crack.lastZone", String(zoneId));
  const url = new URL(window.location.href);
  url.searchParams.set("zone", zoneId);
  history.replaceState(null, "", url);
  renderZoneState();
  renderCracks();
  renderAllCracksOverlay();
  if (focus && state.viewer?.world.getItemCount()) {
    const image = state.viewer.world.getItemAt(0);
    const bounds = image.imageToViewportRectangle(zone.x, zone.y, zone.width, zone.height);
    state.viewer.viewport.fitBounds(bounds, true);
  }
  renderAnalysisOverlay();
  if (changed) await loadCracks(zoneId);
  loadLengthStatistics();
  warmZone(zoneId);
}

function restoreZone() {
  const fromUrl = Number(new URLSearchParams(window.location.search).get("zone"));
  const remembered = Number(localStorage.getItem("crack.lastZone"));
  const zoneId = fromUrl || remembered;
  if (state.zones.some((zone) => zone.id === zoneId)) selectZone(zoneId, true);
}

async function loadCracks(zoneId = state.selectedZoneId, silent = false) {
  if (!zoneId) return;
  const request = ++state.zoneRequest;
  if (!silent) setStatus("Chargement des fissures…");
  try {
    const cracks = await api(`/api/zones/${zoneId}/cracks?include_rejected=true`);
    if (request !== state.zoneRequest || zoneId !== state.selectedZoneId) return;
    state.cracks = cracks;
    state.cracksLoaded = true;
    if (!cracks.some((crack) => crack.id === state.selectedCrackId)) state.selectedCrackId = null;
    if (!cracks.some((crack) => crack.id === state.draftCrackId)) state.draftCrackId = null;
    renderCracks();
    syncAllCracksFromActiveZone();
    if (!silent) setStatus(`${cracks.filter((crack) => crack.state !== "rejected").length} fissure(s) dans ${zoneName(selectedZone())}`);
  } catch (error) {
    setStatus(error.message, "error");
  }
}

function warmZone(zoneId) {
  if (!zoneId || state.preparedZones.has(zoneId)) return;
  const promise = api(`/api/zones/${zoneId}/prepare`, { method: "POST", body: "{}" }).catch(() => null);
  state.preparedZones.set(zoneId, promise);
}

function visibleCracks() {
  return state.cracks.filter((crack) => crack.state !== "rejected");
}

function renderSelection() {
  const crack = selectedCrack();
  const enabled = Boolean(crack && crack.state !== "rejected");
  document.querySelectorAll("button[data-category]").forEach((button) => {
    button.disabled = !enabled;
    button.classList.toggle("active", crack?.category === button.dataset.category);
  });
  elements["delete-crack"].disabled = !enabled && !state.pendingStart;
  elements["insert-node"].disabled = !enabled || state.routing;
  renderUndoPointControl();
  if (!crack) {
    elements["selection-summary"].textContent = state.pendingStart
      ? "Nouveau tracé · premier point placé"
      : "Aucune fissure sélectionnée";
    return;
  }
  const inProgress = crack.id === state.draftCrackId;
  elements["selection-summary"].textContent = inProgress
    ? `Fissure ${crack.id} · ${crack.anchors.length} points · en cours`
    : `Fissure ${crack.id} · ${CATEGORY[crack.category].label} · ${crack.anchors.length} points`;
}

function renderUndoPointControl() {
  const available = Boolean(state.pendingStart || draftCrack());
  elements["undo-point"].disabled = !available || state.routing;
}

function renderCracks() {
  const active = visibleCracks().length;
  elements["zone-summary"].textContent = state.selectedZoneId ? `Tuile ${state.selectedZoneId} · mesures dans « Vue et mesures »` : "Sélectionner une tuile";
  renderSelection();
  renderCrackOverlay();
  renderDetectionControl();
}

async function detectCracks() {
  const zone = selectedZone();
  if (!zone || !state.cracksLoaded || state.routing) return;
  if (state.cracks.some((crack) => crack.state !== "rejected")) {
    setStatus("Détection bloquée : cette tuile contient déjà des annotations.", "error");
    return;
  }

  state.pendingStart = null;
  state.selectedCrackId = null;
  state.draftCrackId = null;
  hideCategoryPalette();
  setMode("select");
  setBusy(true, "Recherche des fissures…");
  try {
    const result = await api(`/api/zones/${zone.id}/detect`, {
      method: "POST",
      body: JSON.stringify({
        annotator: elements.annotator.value.trim() || null,
      }),
    });
    if (zone.id !== state.selectedZoneId) return;
    state.cracks = result.cracks;
    state.cracksLoaded = true;
    renderCracks();
    syncAllCracksFromActiveZone();
    loadLengthStatistics();
    if (!result.created) {
      setStatus("Travail existant conservé : aucune proposition ajoutée.", "error");
      return;
    }
    const createdIds = result.cracks.map((crack) => crack.id);
    if (createdIds.length) {
      rememberUndo({ type: "auto_batch", zoneId: zone.id, crackIds: createdIds });
      setStatus(
        `${createdIds.length} proposition(s) automatique(s) non classée(s) · clique pour corriger ou catégoriser`,
        "success",
      );
    } else {
      setStatus("Aucune fissure probable détectée dans cette tuile.");
    }
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    setBusy(false);
  }
}

function svgElement(name, attributes = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  return element;
}

function localPoints(points, zone) {
  return points.map(([x, y]) => `${x - zone.x},${y - zone.y}`).join(" ");
}

function renderCrackOverlay() {
  if (state.crackOverlay && state.viewer) {
    state.viewer.removeOverlay(state.crackOverlay);
    state.crackOverlay = null;
  }
  const zone = selectedZone();
  if (!zone || !state.viewer?.world.getItemCount()) return;

  const wrapper = document.createElement("div");
  wrapper.className = "crack-overlay";
  wrapper.classList.toggle("traces-hidden", !state.tracesVisible);
  const svg = svgElement("svg", {
    viewBox: `0 0 ${zone.width} ${zone.height}`,
    preserveAspectRatio: "none",
  });

  for (const crack of visibleCracks()) {
    svg.append(svgElement("polyline", {
      points: localPoints(crack.geometry, zone),
      class: `crack-line category-${crack.category} state-${crack.state}${crack.id === state.selectedCrackId ? " selected" : ""}`,
      "data-crack-id": crack.id,
    }));
  }

  const crack = selectedCrack();
  if (crack && crack.state !== "rejected") {
    crack.anchors.forEach(([x, y], index) => {
      const handle = svgElement("circle", {
        cx: x - zone.x,
        cy: y - zone.y,
        r: 7,
        class: "crack-handle",
      });
      handle.addEventListener("pointerdown", (event) => beginAnchorDrag(event, crack.id, index));
      handle.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        event.stopPropagation();
        removeAnchor(crack.id, index);
      });
      svg.append(handle);
    });
  }

  if (state.pendingStart?.zoneId === zone.id) {
    svg.append(svgElement("circle", {
      cx: state.pendingStart.x - zone.x,
      cy: state.pendingStart.y - zone.y,
      r: 7,
      class: "endpoint-marker",
    }));
  }

  wrapper.append(svg);
  const image = state.viewer.world.getItemAt(0);
  const location = image.imageToViewportRectangle(zone.x, zone.y, zone.width, zone.height);
  state.viewer.addOverlay({ element: wrapper, location, checkResize: false });
  state.crackOverlay = wrapper;
}

function removeAllCracksOverlay() {
  if (state.allCracksOverlay && state.viewer) {
    state.viewer.removeOverlay(state.allCracksOverlay);
  }
  state.allCracksOverlay = null;
}

function renderAllCracksOverlay() {
  removeAllCracksOverlay();
  if (!state.allCracksVisible || !state.allCracksLoaded ||
      !state.viewer?.world.getItemCount() || !state.metadata) return;

  const wrapper = document.createElement("div");
  wrapper.className = "all-cracks-overlay";
  wrapper.style.opacity = String(Number(elements["all-cracks-opacity"].value) / 100);
  const svg = svgElement("svg", {
    viewBox: `0 0 ${state.metadata.width} ${state.metadata.height}`,
    preserveAspectRatio: "none",
  });
  for (const crack of state.allCracks) {
    if (crack.state === "rejected" ||
        (state.tracesVisible && crack.zone_id === state.selectedZoneId)) continue;
    svg.append(svgElement("polyline", {
      points: crack.geometry.map(([x, y]) => `${x},${y}`).join(" "),
      class: `crack-line category-${crack.category} state-${crack.state}`,
    }));
  }
  wrapper.append(svg);
  const image = state.viewer.world.getItemAt(0);
  const location = image.imageToViewportRectangle(
    0, 0, state.metadata.width, state.metadata.height
  );
  state.viewer.addOverlay({ element: wrapper, location, checkResize: false });
  state.allCracksOverlay = wrapper;
}

function syncAllCracksFromActiveZone() {
  if (!state.allCracksLoaded || !state.selectedZoneId || !state.cracksLoaded) return;
  state.allCracks = state.allCracks
    .filter((crack) => crack.zone_id !== state.selectedZoneId)
    .concat(state.cracks.filter((crack) => crack.state !== "rejected"));
  renderAllCracksOverlay();
}

async function loadAllCracks() {
  if (!state.allCracksVisible) return;
  const request = ++state.allCracksRequest;
  elements["toggle-all-cracks"].disabled = true;
  setStatus("Chargement des fissures de toute la mosaïque…");
  try {
    const cracks = await api("/api/cracks");
    if (request !== state.allCracksRequest || !state.allCracksVisible) return;
    state.allCracks = cracks;
    state.allCracksLoaded = true;
    renderAllCracksOverlay();
    setStatus(`${cracks.length} fissure(s) affichée(s) sur la mosaïque`);
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    elements["toggle-all-cracks"].disabled = false;
  }
}

function toggleAllCracks() {
  state.allCracksVisible = !state.allCracksVisible;
  localStorage.setItem("crack.allCracksVisible", String(state.allCracksVisible));
  elements["toggle-all-cracks"].classList.toggle("active", state.allCracksVisible);
  elements["all-cracks-opacity"].disabled = !state.allCracksVisible;
  if (state.allCracksVisible) {
    loadAllCracks();
  } else {
    state.allCracksRequest += 1;
    removeAllCracksOverlay();
    setStatus("Vue globale des fissures masquée");
  }
}

function pointSegmentDistance(point, first, second) {
  const dx = second[0] - first[0];
  const dy = second[1] - first[1];
  const squared = dx * dx + dy * dy;
  if (!squared) return Math.hypot(point[0] - first[0], point[1] - first[1]);
  const position = Math.max(0, Math.min(1,
    ((point[0] - first[0]) * dx + (point[1] - first[1]) * dy) / squared
  ));
  return Math.hypot(
    point[0] - first[0] - position * dx,
    point[1] - first[1] - position * dy,
  );
}

function crackAtPoint(point) {
  if (!state.viewer || !state.tracesVisible) return null;
  const imageZoom = state.viewer.viewport.viewportToImageZoom(state.viewer.viewport.getZoom());
  const tolerance = Math.max(3, 12 / Math.max(imageZoom, 0.001));
  let best = null;
  let bestDistance = tolerance;
  for (const crack of visibleCracks()) {
    for (let index = 1; index < crack.geometry.length; index += 1) {
      const distance = pointSegmentDistance(
        [point.x, point.y], crack.geometry[index - 1], crack.geometry[index]
      );
      if (distance <= bestDistance) {
        best = crack;
        bestDistance = distance;
      }
    }
  }
  return best;
}

function selectCrack(crackId, screenPoint = null, showPalette = false) {
  const crack = state.cracks.find((item) => item.id === crackId);
  if (!crack) return;
  state.pendingStart = null;
  state.selectedCrackId = crackId;
  state.draftCrackId = null;
  renderCracks();
  if (showPalette && screenPoint) {
    showCategoryPalette(crackId, screenPoint.clientX, screenPoint.clientY);
  }
  setStatus(state.draftCrackId
    ? `Fissure ${crackId} en cours · clique pour ajouter un point ou choisis sa catégorie`
    : `Fissure ${crackId} sélectionnée · choisis sa catégorie`);
}

function showCategoryPalette(crackId, clientX, clientY) {
  const crack = state.cracks.find((item) => item.id === crackId);
  if (!crack) return;
  state.paletteCrackId = crackId;
  const palette = elements["image-category-palette"];
  palette.classList.remove("hidden");
  palette.querySelectorAll("[data-palette-category]").forEach((button) => {
    button.classList.toggle("active", button.dataset.paletteCategory === crack.category);
  });
  const shellRect = document.querySelector(".canvas-shell").getBoundingClientRect();
  const maximumLeft = Math.max(8, shellRect.width - palette.offsetWidth - 8);
  const maximumTop = Math.max(8, shellRect.height - palette.offsetHeight - 30);
  palette.style.left = `${Math.min(maximumLeft, Math.max(8, clientX - shellRect.left + 10))}px`;
  palette.style.top = `${Math.min(maximumTop, Math.max(8, clientY - shellRect.top + 10))}px`;
}

function hideCategoryPalette() {
  state.paletteCrackId = null;
  elements["image-category-palette"].classList.add("hidden");
}

async function handleCanvasClick(point, screenPoint) {
  if (["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) {
    document.activeElement.blur();
  }
  const zone = zoneAtPoint(point);
  if (!zone) {
    setStatus("Ce point est hors de la mosaïque.", "error");
    return;
  }

  // Le premier clic dans une autre tuile ne dessine jamais : il ne fait que
  // charger et sélectionner cette tuile.
  if (zone.id !== state.selectedZoneId) {
    await selectZone(zone.id, false);
    setStatus(`${zoneName(zone)} sélectionnée · clique à nouveau pour agir`);
    return;
  }

  if (state.mode === "insert" || (state.mode === "select" && screenPoint.shiftKey && selectedCrack())) {
    await insertAnchor(point);
    return;
  }
  if (state.mode === "select") {
    const hit = crackAtPoint(point);
    if (hit) {
      selectCrack(hit.id, screenPoint, true);
    } else {
      state.selectedCrackId = null;
      hideCategoryPalette();
      renderCracks();
      setStatus("Aucune fissure à cet endroit");
    }
    return;
  }

  // En mode Tracer, même un clic posé sur une autre ligne est un nouveau
  // point. Cela permet de créer volontairement une jonction/ramification.
  await addPoint(point, zone, screenPoint);
}

function finishDraft() {
  if (state.routing) {
    state.finishRequested = true;
    setStatus("Fin du tracé demandée · enregistrement du calcul en cours");
    return;
  }
  const hadDraft = Boolean(draftCrack());
  state.draftCrackId = null;
  state.pendingStart = null;
  hideCategoryPalette();
  setMode("select");
  setStatus(hadDraft ? "Tracé terminé et enregistré sans changer sa catégorie · C pour un nouveau tracé" : "Mode Sélection");
}

function projectOnGeometry(point, geometry) {
  let best = null, length = 0;
  for (let i=1;i<geometry.length;i++) {
    const a=geometry[i-1], b=geometry[i], dx=b[0]-a[0],dy=b[1]-a[1];
    const size=Math.hypot(dx,dy); if(!size) continue;
    const t=Math.max(0,Math.min(1,((point.x-a[0])*dx+(point.y-a[1])*dy)/(size*size)));
    const x=a[0]+t*dx,y=a[1]+t*dy,distance=Math.hypot(x-point.x,y-point.y);
    if(!best || distance<best.distance) best={x,y,distance,along:length+t*size,segmentIndex:i-1};
    length+=size;
  }
  return best;
}

async function insertAnchor(point) {
  const crack=selectedCrack(); if(!crack || state.routing) return;
  const projected=projectOnGeometry(point,crack.geometry);
  const zoom=state.viewer.viewport.viewportToImageZoom(state.viewer.viewport.getZoom());
  // Keep a comfortable, zoom-independent hit area around the selected line.
  // A miss never extends an endpoint: insertion is deliberately one-purpose.
  if(!projected || projected.distance>Math.max(3,16/Math.max(zoom,0.001))) {
    setStatus("Le clic doit être posé sur la fissure sélectionnée.","error"); return;
  }
  const positions=crack.anchors.map(([x,y])=>projectOnGeometry({x,y},crack.geometry).along);
  const index=positions.findIndex(position=>position>projected.along+1e-6);
  if(index<1 || crack.anchors.some(([x,y])=>Math.hypot(x-projected.x,y-projected.y)<3)) {
    setStatus("Choisir un emplacement entre deux nœuds, à plus de 3 px d’un nœud existant.","error"); return;
  }
  const anchors=crack.anchors.map(a=>[...a]); anchors.splice(index,0,[projected.x,projected.y]);
  await patchCrack(crack.id,{anchors,state:crack.state},{successMessage:"Nœud ajouté à l'endroit choisi · clique ailleurs sur la fissure pour continuer"});
}

async function addPoint(point, zone, screenPoint) {
  const draft = draftCrack();
  if (draft) {
    const last = draft.anchors[draft.anchors.length - 1];
    if (Math.hypot(point.x - last[0], point.y - last[1]) < 3) {
      setStatus("Le nouveau point est trop proche du précédent.", "error");
      return;
    }
    const anchors = [...draft.anchors.map((anchor) => [...anchor]), [point.x, point.y]];
    const updated = await patchCrack(draft.id, { anchors, state: "proposed" }, {
      closePalette: false,
      successMessage: `Point ${anchors.length} ajouté · continue ou choisis une catégorie`,
    });
    if (updated) state.draftCrackId = updated.id;
    return;
  }

  if (!state.pendingStart) {
    hideCategoryPalette();
    state.selectedCrackId = null;
    state.pendingStart = { x: point.x, y: point.y, zoneId: zone.id };
    renderCracks();
    warmZone(zone.id);
    setStatus("Premier point placé · clique plus loin sur la même fissure");
    return;
  }

  if (zone.id !== state.pendingStart.zoneId) {
    setStatus("Les points d’une fissure doivent rester dans la même tuile.", "error");
    return;
  }
  if (Math.hypot(point.x - state.pendingStart.x, point.y - state.pendingStart.y) < 3) {
    setStatus("Le second point est trop proche du premier.", "error");
    return;
  }

  setBusy(true, "Calcul de la fissure…");
  try {
    const crack = await api(`/api/zones/${zone.id}/cracks`, {
      method: "POST",
      body: JSON.stringify({
        anchors: [[state.pendingStart.x, state.pendingStart.y], [point.x, point.y]],
        annotator: elements.annotator.value.trim() || null,
      }),
    });
    state.pendingStart = null;
    state.cracks.push(crack);
    state.selectedCrackId = crack.id;
    state.draftCrackId = crack.id;
    rememberUndo({ type: "create", crackId: crack.id, zoneId: zone.id });
    renderCracks();
    syncAllCracksFromActiveZone();
    loadLengthStatistics();
    showCategoryPalette(crack.id, screenPoint.clientX, screenPoint.clientY);
    setStatus(`Fissure ${crack.id} · 2 points · continue à cliquer ou choisis une catégorie`, "success");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    setBusy(false);
  }
}

async function patchCrack(crackId, changes, options = {}) {
  const crack = state.cracks.find((item) => item.id === crackId);
  if (!crack) return null;
  const closePalette = options.closePalette !== false;
  const previous = {
    anchors: crack.anchors.map((anchor) => [...anchor]),
    category: crack.category,
    state: crack.state,
  };
  if (changes.anchors) setBusy(true, "Recalcul de la fissure…");
  try {
    const updated = await api(`/api/cracks/${crackId}`, {
      method: "PATCH",
      body: JSON.stringify({
        expected_revision: crack.revision,
        annotator: elements.annotator.value.trim() || null,
        ...changes,
      }),
    });
    state.cracks[state.cracks.findIndex((item) => item.id === crackId)] = updated;
    if (options.recordUndo !== false) {
      rememberUndo({ type: "crack", crackId, zoneId: crack.zone_id, previous });
    }
    if (updated.state === "rejected") {
      if (state.draftCrackId === crackId) state.draftCrackId = null;
      if (state.selectedCrackId === crackId) state.selectedCrackId = null;
    }
    if (changes.category && changes.category !== "unclassified" && state.draftCrackId === crackId) {
      state.draftCrackId = null;
      state.pendingStart = null;
    }
    if (closePalette) hideCategoryPalette();
    renderCracks();
    syncAllCracksFromActiveZone();
    loadLengthStatistics();
    setStatus(options.successMessage || `Fissure ${updated.id} enregistrée`, "success");
    return updated;
  } catch (error) {
    setStatus(error.message, "error");
    if (error.status === 409) await loadCracks(state.selectedZoneId, true);
    return null;
  } finally {
    if (changes.anchors) setBusy(false);
  }
}

async function categorizeCrack(crackId, category) {
  const crack = state.cracks.find((item) => item.id === crackId);
  if (!crack || crack.state === "rejected") return;
  const wasDraft = crackId === state.draftCrackId;
  const updated = await patchCrack(crackId, { category, state: "validated" }, {
    successMessage: `Fissure ${crackId} classée ${CATEGORY[category].label}`,
  });
  if (updated && wasDraft) {
    state.draftCrackId = null;
    renderCracks();
    setStatus(`Fissure ${crackId} terminée · clique dans l’image pour commencer la suivante`, "success");
  }
}

async function deleteSelectedCrack() {
  if (state.pendingStart && !selectedCrack()) {
    state.pendingStart = null;
    hideCategoryPalette();
    renderCracks();
    setStatus("Premier point supprimé");
    return;
  }
  const crack = selectedCrack();
  if (!crack) return;
  await patchCrack(crack.id, { state: "rejected" }, {
    successMessage: `Fissure ${crack.id} supprimée`,
  });
}

function removeAnchor(crackId, anchorIndex) {
  const crack = state.cracks.find((item) => item.id === crackId);
  if (!crack || crack.anchors.length <= 2) {
    setStatus("Une fissure doit conserver au moins deux points.", "error");
    return;
  }
  const anchors = crack.anchors.map((anchor) => [...anchor]);
  anchors.splice(anchorIndex, 1);
  patchCrack(crackId, { anchors, state: crack.state }, {
    successMessage: `Point supprimé · ${anchors.length} points restants`,
  });
}

async function removeLastDraftAnchor() {
  if (state.pendingStart) {
    state.pendingStart = null;
    renderCracks();
    setStatus("Premier point annulé");
    return;
  }
  const crack = draftCrack();
  if (!crack || state.routing) return;
  if (crack.anchors.length <= 2) {
    const first = crack.anchors[0];
    const zoneId = crack.zone_id;
    const creationIndex = state.undoStack.findLastIndex(
      (action) => action.type === "create" && action.crackId === crack.id
    );
    if (creationIndex >= 0) state.undoStack.splice(creationIndex, 1);
    const removed = await patchCrack(crack.id, { state: "rejected" }, {
      recordUndo: false,
      successMessage: "",
    });
    if (removed) {
      state.pendingStart = { x: first[0], y: first[1], zoneId };
      state.selectedCrackId = null;
      state.draftCrackId = null;
      setMode("draw");
      renderCracks();
      setStatus("Dernier point retiré · premier point conservé", "success");
    }
    return;
  }
  const anchors = crack.anchors.slice(0, -1).map((anchor) => [...anchor]);
  patchCrack(crack.id, { anchors, state: "proposed" }, {
    successMessage: `Dernier point retiré · ${anchors.length} points`,
  });
}

function beginAnchorDrag(event, crackId, anchorIndex) {
  if (event.button !== 0 || state.routing) return;
  event.preventDefault();
  event.stopPropagation();
  hideCategoryPalette();
  const crack = state.cracks.find((item) => item.id === crackId);
  state.dragging = {
    crackId,
    anchorIndex,
    anchors: crack.anchors.map((anchor) => [...anchor]),
    handle: event.currentTarget,
  };
  state.viewer.setMouseNavEnabled(false);
}

function dragAnchor(event) {
  if (!state.dragging) return;
  const zone = selectedZone();
  const point = clientToImage(event.clientX, event.clientY);
  const x = Math.max(zone.x, Math.min(zone.x + zone.width - 1, point.x));
  const y = Math.max(zone.y, Math.min(zone.y + zone.height - 1, point.y));
  state.dragging.anchors[state.dragging.anchorIndex] = [x, y];
  state.dragging.handle.setAttribute("cx", x - zone.x);
  state.dragging.handle.setAttribute("cy", y - zone.y);
}

function finishAnchorDrag() {
  if (!state.dragging) return;
  const { crackId, anchors } = state.dragging;
  const crack = state.cracks.find((item) => item.id === crackId);
  state.dragging = null;
  state.viewer.setMouseNavEnabled(true);
  patchCrack(crackId, { anchors, state: crack.state }, {
    successMessage: "Point déplacé",
  });
}

async function undoLastAction() {
  if (state.pendingStart) {
    state.pendingStart = null;
    renderCracks();
    setStatus("Premier point annulé");
    return;
  }
  const action = state.undoStack.pop();
  if (!action) {
    setStatus("Rien à annuler");
    return;
  }

  if (action.type === "zone") {
    if (action.zoneId !== state.selectedZoneId) await selectZone(action.zoneId, false);
    const zone = selectedZone();
    try {
      const updated = await api(`/api/zones/${zone.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          status: action.previous.status,
          assigned_to: action.previous.assigned_to,
          expected_revision: zone.revision,
        }),
      });
      state.zones[state.zones.findIndex((item) => item.id === zone.id)] = updated;
      renderZoneState();
      setStatus("Modification de la tuile annulée", "success");
    } catch (error) {
      setStatus(error.message, "error");
    }
    return;
  }

  if (action.zoneId !== state.selectedZoneId) await selectZone(action.zoneId, false);
  if (action.type === "auto_batch") {
    setBusy(true, "Annulation de la détection…");
    let removed = 0;
    try {
      for (const crackId of action.crackIds) {
        const crack = state.cracks.find((item) => item.id === crackId);
        if (!crack || crack.state === "rejected") continue;
        const updated = await patchCrack(crack.id, { state: "rejected" }, {
          recordUndo: false,
          closePalette: false,
          successMessage: "",
        });
        if (updated) removed += 1;
      }
      state.selectedCrackId = null;
      state.draftCrackId = null;
      hideCategoryPalette();
      renderCracks();
      setStatus(`Détection annulée · ${removed} proposition(s) retirée(s)`, "success");
    } finally {
      setBusy(false);
    }
    return;
  }
  const crack = state.cracks.find((item) => item.id === action.crackId);
  if (!crack) {
    setStatus("La fissure à restaurer n’est plus disponible.", "error");
    return;
  }
  state.selectedCrackId = crack.id;

  if (action.type === "create") {
    const first = crack.anchors[0];
    const wasDraft = crack.id === state.draftCrackId;
    const removed = await patchCrack(crack.id, { state: "rejected" }, {
      recordUndo: false,
      successMessage: "Création de la fissure annulée",
    });
    if (removed) {
      state.draftCrackId = null;
      if (wasDraft) {
        state.pendingStart = { x: first[0], y: first[1], zoneId: action.zoneId };
        setMode("draw");
        renderCracks();
        setStatus("Dernier point annulé · premier point conservé", "success");
      }
    }
    return;
  }

  const restored = await patchCrack(crack.id, {
    anchors: action.previous.anchors,
    category: action.previous.category,
    state: action.previous.state,
  }, {
    recordUndo: false,
    closePalette: true,
    successMessage: "Dernière modification annulée",
  });
  if (restored) {
    state.selectedCrackId = restored.state === "rejected" ? null : restored.id;
    state.draftCrackId = restored.category === "unclassified" && restored.state === "proposed"
      ? restored.id
      : null;
    renderCracks();
  }
}

async function updateZoneStatus(status) {
  const zone = selectedZone();
  if (!zone) return;
  const previous = { status: zone.status, assigned_to: zone.assigned_to };
  try {
    const updated = await api(`/api/zones/${zone.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        status,
        assigned_to: elements.annotator.value.trim() || null,
        expected_revision: zone.revision,
      }),
    });
    state.zones[state.zones.findIndex((item) => item.id === zone.id)] = updated;
    rememberUndo({ type: "zone", zoneId: zone.id, previous });
    const overlay = state.zoneOverlays.get(zone.id);
    if (overlay) overlay.style.setProperty("--zone-color", STATUS[updated.status].color);
    renderZoneState();
    setStatus(`${zoneName(updated)} · ${STATUS[updated.status].label}`, "success");
  } catch (error) {
    setStatus(error.message, "error");
    if (error.status === 409) {
      state.zones = await api("/api/zones");
      renderZoneState();
    }
  }
}

function navigateZone(offset) {
  const current = state.zones.findIndex((zone) => zone.id === state.selectedZoneId);
  const index = current < 0 ? 0 : Math.max(0, Math.min(state.zones.length - 1, current + offset));
  if (state.zones[index]) selectZone(state.zones[index].id, true);
}

function applyDisplayFilters() {
  const brightness = elements.brightness.value;
  const contrast = elements.contrast.value;
  elements["brightness-value"].textContent = `${brightness} %`;
  elements["contrast-value"].textContent = `${contrast} %`;
  const canvas = state.viewer?.drawer?.canvas;
  if (canvas) canvas.style.filter = `brightness(${brightness}%) contrast(${contrast}%)`;
  localStorage.setItem("crack.brightness", brightness);
  localStorage.setItem("crack.contrast", contrast);
}

function categoryFromKeyboard(event) {
  const byCode = {
    Digit1: "open",
    Numpad1: "open",
    Digit2: "filled",
    Numpad2: "filled",
    Digit3: "uncertain",
    Numpad3: "uncertain",
  };
  if (byCode[event.code]) return byCode[event.code];
  if (event.key === "&") return "open";
  if (event.key === "é") return "filled";
  if (["\"", "'"].includes(event.key)) return "uncertain";
  return null;
}

function bindControls() {
  elements["insert-node"].addEventListener("click", () => setMode("insert"));
  elements.annotator.value = localStorage.getItem("crack.annotator") || "";
  elements.brightness.value = localStorage.getItem("crack.brightness") || "100";
  elements.contrast.value = localStorage.getItem("crack.contrast") || "100";
  state.allCracksVisible = localStorage.getItem("crack.allCracksVisible") === "true";
  elements["all-cracks-opacity"].value = localStorage.getItem("crack.allCracksOpacity") || "45";
  elements["all-cracks-opacity"].disabled = !state.allCracksVisible;
  elements["toggle-all-cracks"].classList.toggle("active", state.allCracksVisible);
  elements.annotator.addEventListener("change", () => {
    localStorage.setItem("crack.annotator", elements.annotator.value.trim());
  });

  elements["mode-select"].addEventListener("click", () => setMode("select"));
  elements["mode-draw"].addEventListener("click", () => setMode("draw"));
  elements["undo-point"].addEventListener("click", removeLastDraftAnchor);
  elements["detect-cracks"].addEventListener("click", detectCracks);
  elements["previous-zone"].addEventListener("click", () => navigateZone(-1));
  elements["next-zone"].addEventListener("click", () => navigateZone(1));
  document.querySelectorAll("[data-zone-status]").forEach((button) => {
    button.addEventListener("click", () => updateZoneStatus(button.dataset.zoneStatus));
  });
  document.querySelectorAll("[data-category]").forEach((button) => {
    button.addEventListener("click", () => {
      const crack = selectedCrack();
      if (crack) categorizeCrack(crack.id, button.dataset.category);
    });
  });
  document.querySelectorAll("[data-palette-category]").forEach((button) => {
    button.addEventListener("pointerdown", (event) => event.stopPropagation());
    button.addEventListener("click", () => {
      const crackId = state.paletteCrackId;
      if (crackId) categorizeCrack(crackId, button.dataset.paletteCategory);
    });
  });
  elements["delete-crack"].addEventListener("click", deleteSelectedCrack);
  elements["palette-delete"].addEventListener("pointerdown", (event) => event.stopPropagation());
  elements["palette-delete"].addEventListener("click", deleteSelectedCrack);

  elements["toggle-zones"].addEventListener("click", () => {
    state.zonesVisible = !state.zonesVisible;
    updateZoneOverlayStyles();
  });
  elements["toggle-traces"].addEventListener("click", () => {
    state.tracesVisible = !state.tracesVisible;
    elements["toggle-traces"].classList.toggle("active", state.tracesVisible);
    state.crackOverlay?.classList.toggle("traces-hidden", !state.tracesVisible);
    renderAllCracksOverlay();
  });
  elements["toggle-all-cracks"].addEventListener("click", toggleAllCracks);
  elements["all-cracks-opacity"].addEventListener("input", () => {
    localStorage.setItem("crack.allCracksOpacity", elements["all-cracks-opacity"].value);
    if (state.allCracksOverlay) {
      state.allCracksOverlay.style.opacity = String(
        Number(elements["all-cracks-opacity"].value) / 100
      );
    }
  });
  elements.home.addEventListener("click", () => state.viewer.viewport.goHome(true));
  elements["zoom-out"].addEventListener("click", () => state.viewer.viewport.zoomBy(1 / 1.5));
  elements["zoom-in"].addEventListener("click", () => state.viewer.viewport.zoomBy(1.5));
  elements.brightness.addEventListener("input", applyDisplayFilters);
  elements.contrast.addEventListener("input", applyDisplayFilters);
  elements["reset-display"].addEventListener("click", () => {
    elements.brightness.value = "100";
    elements.contrast.value = "100";
    applyDisplayFilters();
  });

  window.addEventListener("pointermove", dragAnchor);
  window.addEventListener("pointerup", finishAnchorDrag);
  window.addEventListener("keydown", (event) => {
    const active = document.activeElement;
    const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(active?.tagName);
    const editingText = active?.tagName === "TEXTAREA" ||
      (active?.tagName === "INPUT" && ["text", "search", "email", "number"].includes(active.type));
    const key = String(event.key || "").toLowerCase();
    if (!typing && (key === "z" || ["Escape","KeyC","KeyV","Delete","Backspace","Space"].includes(event.code))) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
    if (event.code === "Escape" && !typing) {
      finishDraft();
      return;
    }
    if (event.code === "Space" && !typing) {
      event.preventDefault();
      state.crackOverlay?.classList.add("peek-image");
    }
    if ((event.ctrlKey || event.metaKey) && key === "z" && !editingText) {
      event.preventDefault();
      if (state.routing) {
        state.undoRequested = true;
        setStatus("Annulation demandée · appliquée dès la fin du calcul");
      } else {
        undoLastAction();
      }
      return;
    }
    if (typing || state.routing) return;
    if (key === "z") {
      if (state.pendingStart || draftCrack()) {
        event.preventDefault();
        removeLastDraftAnchor();
      }
      return;
    }
    if (event.code === "KeyC") {
      event.preventDefault();
      setMode("draw");
      return;
    }
    if (event.code === "KeyV") {
      event.preventDefault();
      setMode("select");
      return;
    }
    if (key === "a") {
      event.preventDefault();
      detectCracks();
      return;
    }

    const category = categoryFromKeyboard(event);
    if (category) {
      const crack = selectedCrack();
      if (crack) {
        event.preventDefault();
        categorizeCrack(crack.id, category);
      }
      return;
    }
    if (event.code === "Delete") {
      event.preventDefault();
      deleteSelectedCrack();
    } else if (event.code === "Backspace") {
      event.preventDefault();
      removeLastDraftAnchor();
    } else if (event.code === "Escape") {
      event.preventDefault();
      hideCategoryPalette();
      setMode("select");
    }
  }, true);
  window.addEventListener("keypress", (event) => {
    if (!["INPUT","TEXTAREA","SELECT"].includes(document.activeElement?.tagName) && String(event.key).toLowerCase() === "z") {
      event.preventDefault(); event.stopImmediatePropagation();
    }
  }, true);
  window.addEventListener("keyup", (event) => {
    if (event.code === "Space") state.crackOverlay?.classList.remove("peek-image");
  });
  window.addEventListener("blur", () => state.crackOverlay?.classList.remove("peek-image"));
}

async function start() {
  bindControls();
  try {
    [state.metadata, state.zones] = await Promise.all([api("/api/image"), api("/api/zones")]);
    elements["image-name"].textContent = `${state.metadata.name} · ${state.metadata.width.toLocaleString("fr-FR")} × ${state.metadata.height.toLocaleString("fr-FR")} px`;
    elements["server-status"].className = "connection";
    elements["server-status"].title = "Serveur connecté";
    renderZoneState();
    renderCracks();
    initializeViewer(state.metadata);
    setMode("select");
  } catch (error) {
    elements["server-status"].className = "connection error";
    elements["viewer-message"].textContent = error.message;
    setStatus(error.message, "error");
  }
}

import { initializeAnalysis } from './analysis.js';
initializeAnalysis(state, api);
start();
