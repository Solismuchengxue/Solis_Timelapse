"use strict";

const API = Object.freeze({
  state: "/api/state",
  pickDirectory: "/api/pick-directory",
  scan: "/api/project/scan",
  project: "/api/project",
  split: "/api/segments/split",
  merge: "/api/segments/merge",
  segment: (id) => `/api/segments/${encodeURIComponent(id)}`,
  reorder: "/api/segments/reorder",
  thumbnails: (id) => `/api/segments/${encodeURIComponent(id)}/thumbnails`,
  chart: (id) => `/api/segments/${encodeURIComponent(id)}/chart`,
  process: "/api/process",
  retry: "/api/process/retry",
  cancel: "/api/tasks/cancel",
  task: "/api/tasks/current",
  export: "/api/export",
  archive: "/api/archive",
  history: "/api/history",
  historyItem: (timestamp) => `/api/history/${encodeURIComponent(timestamp)}`,
  settings: "/api/settings"
});

const ACTIVE_TASK_STATES = new Set(["queued", "running", "cancelling"]);
const PAGE_SIZE = 24;
const ui = window.SolisUI;
let preferences = ui.loadPreferences(window.localStorage, window.navigator.language);

const state = {
  project: null,
  task: { status: "idle", progress: 0, logs: [] },
  selectedSegmentId: null,
  selectedFrames: new Set(),
  selectionAnchor: null,
  thumbnails: [],
  thumbnailPage: 0,
  chart: null,
  pendingSourcePath: "",
  history: [],
  settings: {},
  pollingTimer: null,
  recipeSaveTimer: null,
  recipeSavePromise: Promise.resolve(),
  pendingRecipe: null
};

const byId = (id) => document.getElementById(id);
const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
const t = (key, params = {}) => ui.t(preferences.language, key, params);

function translateDocument() {
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-title]").forEach((node) => {
    node.title = t(node.dataset.i18nTitle);
  });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((node) => {
    node.setAttribute("aria-label", t(node.dataset.i18nAriaLabel));
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
    node.placeholder = t(node.dataset.i18nPlaceholder);
  });
  document.title = t("app.title");
}

function applyTheme(theme) {
  preferences.theme = ui.normalizeTheme(theme);
  localStorage.setItem("solis.theme", preferences.theme);
  ui.applyPreferences(document, preferences);
  byId("theme-select").value = preferences.theme;
  drawChart();
  window.dispatchEvent(new CustomEvent("solis:themechange", { detail: { value: preferences.theme } }));
}

function applyLanguage(language) {
  preferences.language = ui.normalizeLanguage(language, navigator.language);
  localStorage.setItem("solis.language", preferences.language);
  ui.applyPreferences(document, preferences);
  byId("language-select").value = preferences.language;
  translateDocument();
  renderAll();
  renderFrameStrip();
  renderHistory();
  drawChart();
  window.dispatchEvent(new CustomEvent("solis:languagechange", { detail: { value: preferences.language } }));
}

async function api(path, options = {}) {
  const request = { ...options, headers: { Accept: "application/json", ...(options.headers || {}) } };
  if (request.body && typeof request.body !== "string") {
    request.headers["Content-Type"] = "application/json";
    request.body = JSON.stringify(request.body);
  }
  const response = await fetch(path, request);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) {
    const code = payload?.code || "request_failed";
    const translated = ui.TRANSLATIONS[preferences.language]?.[`error.${code}`]
      || ui.TRANSLATIONS["zh-CN"]?.[`error.${code}`];
    const error = new Error(translated || payload?.error || `${t("error.unknown")} (HTTP ${response.status})`);
    error.code = code;
    error.status = response.status;
    throw error;
  }
  return payload || {};
}

function showError(error) {
  const translated = error?.code ? ui.TRANSLATIONS[preferences.language]?.[`error.${error.code}`] : null;
  byId("error-message").textContent = translated || error?.message || String(error) || t("error.unknown");
  byId("error-banner").hidden = false;
}

function clearError() {
  byId("error-banner").hidden = true;
  byId("error-message").textContent = "";
}

function segments() {
  return Array.isArray(state.project?.segments) ? state.project.segments : [];
}

function selectedSegment() {
  return segments().find((segment) => String(segment.id) === String(state.selectedSegmentId)) || null;
}

function taskStatus(task = state.task) {
  return task?.status || task?.state || "idle";
}

function isTaskActive() {
  return ACTIVE_TASK_STATES.has(taskStatus());
}

function frameCount(segment) {
  if (!segment) return 0;
  if (Array.isArray(segment.frames)) return segment.frames.length;
  if (Array.isArray(segment.source_files)) return segment.source_files.length;
  return Number(segment.frame_count || segment.count || 0);
}

function normaliseTask(payload) {
  return payload?.task || payload?.current_task || payload || { status: "idle", progress: 0, logs: [] };
}

async function refreshState() {
  try {
    const payload = await api(API.state);
    state.project = payload.project || payload.current_project || null;
    state.task = normaliseTask(payload.task || payload.current_task || { status: "idle" });
    if (state.project?.source_dir) state.pendingSourcePath = state.project.source_dir;
    const ids = new Set(segments().map((segment) => String(segment.id)));
    if (!state.selectedSegmentId || !ids.has(String(state.selectedSegmentId))) {
      state.selectedSegmentId = segments()[0]?.id || null;
      state.selectedFrames.clear();
    }
    renderAll();
    updateTaskPolling();
    if (state.selectedSegmentId) await loadSegmentMedia(state.selectedSegmentId);
  } catch (error) {
    showError(error);
    renderAll();
  }
}

function renderAll() {
  renderSource();
  renderSegments();
  renderSegmentDetail();
  renderTask();
  renderActionAvailability();
}

function renderSource() {
  const source = state.project?.source_dir || state.pendingSourcePath || "";
  const pathLabel = byId("source-path");
  pathLabel.textContent = source || t("source.none");
  pathLabel.title = source || t("source.none");
  const total = segments().reduce((sum, segment) => sum + frameCount(segment), 0);
  const duration = state.project?.duration_seconds;
  const durationText = Number.isFinite(duration) ? formatDuration(duration) : "";
  byId("source-summary").textContent = total
    ? t("source.summary", { frames: total, segments: segments().length, duration: durationText })
    : t("source.help");
}

function formatDuration(seconds) {
  const minutes = Math.floor(seconds / 60);
  const remaining = Math.round(seconds % 60);
  return t("source.duration", { minutes, seconds: remaining });
}

function renderSegments() {
  const list = byId("segment-list");
  list.replaceChildren();
  byId("segment-count").textContent = t("segment.count", { count: segments().length });
  if (!segments().length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = t("segment.empty");
    list.append(empty);
    return;
  }

  segments().forEach((segment) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "segment-item";
    button.dataset.segmentId = segment.id;
    button.setAttribute("role", "option");
    const isSelected = String(segment.id) === String(state.selectedSegmentId);
    button.classList.toggle("is-selected", isSelected);
    button.setAttribute("aria-selected", String(isSelected));

    const name = document.createElement("strong");
    name.textContent = segment.name || t("segment.unnamed");
    const meta = document.createElement("span");
    meta.className = "segment-item-meta";
    const focal = segment.focal_length ? `${segment.focal_length}mm` : t("segment.focal_unknown");
    const timeRange = segment.time_range || segment.captured_range || t("segment.time_unknown");
    meta.textContent = t("segment.meta", { count: frameCount(segment), focal, time: timeRange });
    const status = document.createElement("span");
    status.className = "segment-item-meta";
    status.textContent = statusLabel(segment.status || segment.render_status || "pending");
    button.append(name, meta, status);
    list.append(button);
  });
}

function statusLabel(value) {
  const key = `status.${value || "unknown"}`;
  return ui.TRANSLATIONS[preferences.language]?.[key] || ui.TRANSLATIONS["zh-CN"]?.[key] || value || t("status.unknown");
}

function recipeOf(segment) {
  const recipe = segment?.recipe || {};
  if (typeof recipe === "string") return { name: recipe };
  return recipe;
}

function renderSegmentDetail() {
  const segment = selectedSegment();
  const recipe = recipeOf(segment);
  byId("segment-name").value = segment?.name || "";
  byId("segment-name").disabled = !segment || isTaskActive();
  const segmentStatus = byId("segment-status");
  const value = segment?.status || segment?.render_status || "idle";
  segmentStatus.dataset.status = value;
  segmentStatus.textContent = segment ? statusLabel(value) : t("segment.none");

  const recipeName = recipe.name || recipe.mode || "natural";
  byId("recipe-select").value = recipeName;
  byId("recipe-strength").value = recipe.strength ?? 100;
  byId("recipe-strength-value").textContent = `${byId("recipe-strength").value}%`;
  byId("golden-strength").value = recipe.golden_strength ?? recipe.golden?.strength ?? 0;
  byId("golden-strength-value").textContent = `${byId("golden-strength").value}%`;
  byId("deflicker-enabled").checked = recipe.deflicker?.enabled ?? recipe.deflicker_enabled ?? true;
  byId("deflicker-window").value = recipe.deflicker?.window ?? recipe.deflicker_window ?? 15;
  byId("gain-limit").value = recipe.deflicker?.gain_limit ?? recipe.gain_limit ?? 2;
  byId("golden-start").value = recipe.golden?.start ?? recipe.golden_start ?? "";
  byId("golden-end").value = recipe.golden?.end ?? recipe.golden_end ?? "";
  document.querySelectorAll("[data-recipe]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.recipe === recipeName)));

  const representative = segment?.representative_url || segment?.preview_image || state.thumbnails[0]?.url;
  const surface = byId("segment-preview");
  surface.replaceChildren();
  if (representative) {
    const image = document.createElement("img");
    image.src = representative;
    image.alt = t("preview.alt", { name: segment.name || t("segment.current") });
    surface.append(image);
    byId("preview-caption").textContent = segment?.representative_name || segment?.name || t("preview.representative");
  } else {
    const placeholder = document.createElement("span");
    placeholder.textContent = segment ? t("preview.waiting") : t("preview.none");
    surface.append(placeholder);
    byId("preview-caption").textContent = segment ? t("segment.frames_only", { count: frameCount(segment) }) : t("preview.select");
  }
}

async function loadSegmentMedia(segmentId) {
  try {
    const [thumbnailPayload, chartPayload] = await Promise.all([
      api(`${API.thumbnails(segmentId)}?offset=0&limit=2000`),
      api(API.chart(segmentId))
    ]);
    if (String(segmentId) !== String(state.selectedSegmentId)) return;
    state.thumbnails = thumbnailPayload.thumbnails || thumbnailPayload.frames || [];
    state.chart = chartPayload.chart || chartPayload;
    state.thumbnailPage = 0;
    state.selectedFrames.clear();
    renderFrameStrip();
    drawChart();
    renderSegmentDetail();
  } catch (error) {
    if (error.status !== 404 && error.status !== 409) showError(error);
    state.thumbnails = [];
    state.chart = null;
    renderFrameStrip();
    drawChart();
  }
}

function renderFrameStrip() {
  const strip = byId("frame-strip");
  strip.replaceChildren();
  const totalPages = Math.ceil(state.thumbnails.length / PAGE_SIZE);
  state.thumbnailPage = clamp(state.thumbnailPage, 0, Math.max(0, totalPages - 1));
  const pageFrames = state.thumbnails.slice(state.thumbnailPage * PAGE_SIZE, (state.thumbnailPage + 1) * PAGE_SIZE);
  const rejected = new Set((selectedSegment()?.rejected_frames || selectedSegment()?.bad_frames || []).map(stableValue).filter(Boolean));

  if (!pageFrames.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = selectedSegment() ? t("frames.empty") : t("frames.select_segment");
    strip.append(empty);
  }

  pageFrames.forEach((frame, pageIndex) => {
    const absoluteIndex = Number(frame.index ?? state.thumbnailPage * PAGE_SIZE + pageIndex);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "frame-thumb";
    button.dataset.frameIndex = absoluteIndex;
    button.classList.toggle("is-selected", state.selectedFrames.has(absoluteIndex));
    button.classList.toggle("is-rejected", rejected.has(frameStableId(frame, absoluteIndex)));
    button.title = frameTooltip(frame, absoluteIndex);
    button.setAttribute("aria-label", frameTooltip(frame, absoluteIndex));
    const image = document.createElement("img");
    image.src = frame.url || frame.thumbnail_url || frame.media_url || "";
    image.alt = "";
    image.loading = "lazy";
    const label = document.createElement("span");
    label.textContent = frame.name || `#${absoluteIndex + 1}`;
    button.append(image, label);
    strip.append(button);
  });

  byId("frame-page-label").textContent = t("frames.page", { current: totalPages ? state.thumbnailPage + 1 : 0, total: totalPages });
  byId("frame-page-prev").disabled = state.thumbnailPage <= 0;
  byId("frame-page-next").disabled = state.thumbnailPage >= totalPages - 1;
  const selected = [...state.selectedFrames].sort((a, b) => a - b);
  byId("frame-selection-summary").textContent = selected.length
    ? t("frames.selected_range", { count: selected.length, start: selected[0] + 1, end: selected.at(-1) + 1 })
    : t("frames.none_selected");
  byId("split-frame").value = selected.length === 1 ? selected[0] : byId("split-frame").value;
  renderActionAvailability();
}

function frameTooltip(frame, index) {
  const parts = [frame.name || t("frames.index", { index: index + 1 })];
  if (frame.captured_at) parts.push(frame.captured_at);
  if (frame.shutter) parts.push(t("frames.shutter", { value: frame.shutter }));
  if (frame.aperture) parts.push(`f/${frame.aperture}`);
  if (frame.iso) parts.push(`ISO ${frame.iso}`);
  if (frame.luminance != null) parts.push(t("frames.luminance", { value: Number(frame.luminance).toFixed(3) }));
  return parts.join(" · ");
}

function stableValue(value) {
  if (typeof value === "string") return value;
  return value?.path || value?.source_path || value?.name || null;
}

function frameStableId(frame, index) {
  const segment = selectedSegment();
  const sourceFrame = segment?.source_files?.[index] ?? segment?.frames?.[index];
  return stableValue(sourceFrame) || stableValue(frame);
}

function drawChart() {
  const canvas = byId("brightness-chart");
  const context = canvas.getContext("2d");
  const cssWidth = Math.max(320, Math.floor(canvas.clientWidth || 720));
  const cssHeight = Math.max(140, Math.floor(canvas.clientHeight || 220));
  const scale = window.devicePixelRatio || 1;
  canvas.width = cssWidth * scale;
  canvas.height = cssHeight * scale;
  context.scale(scale, scale);
  context.clearRect(0, 0, cssWidth, cssHeight);
  context.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--line-strong");
  context.lineWidth = 1;
  context.beginPath();
  context.moveTo(32, 10);
  context.lineTo(32, cssHeight - 24);
  context.lineTo(cssWidth - 8, cssHeight - 24);
  context.stroke();

  const chart = state.chart || {};
  const series = [
    { values: chart.luminance || chart.measured_luminance || [], color: getComputedStyle(document.documentElement).getPropertyValue("--muted") },
    { values: chart.target_luminance || chart.target || [], color: getComputedStyle(document.documentElement).getPropertyValue("--accent") },
    { values: chart.gain || chart.gains || [], color: getComputedStyle(document.documentElement).getPropertyValue("--warning") }
  ].filter((item) => item.values.length);
  if (!series.length) {
    context.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--muted");
    context.fillText(t("chart.empty"), 44, cssHeight / 2);
    return;
  }
  const all = series.flatMap((item) => item.values.map(Number).filter(Number.isFinite));
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max - min || 1;
  series.forEach((item) => {
    context.strokeStyle = item.color;
    context.lineWidth = 1.7;
    context.beginPath();
    item.values.forEach((rawValue, index) => {
      const x = 32 + (index / Math.max(1, item.values.length - 1)) * (cssWidth - 40);
      const y = 10 + (1 - (Number(rawValue) - min) / span) * (cssHeight - 34);
      if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
    });
    context.stroke();
  });
}

function renderTask() {
  const task = state.task || {};
  const status = taskStatus(task);
  const completed = Number(task.completed ?? task.progress?.completed ?? 0);
  const total = Number(task.total ?? task.progress?.total ?? 0);
  const rawPercent = task.percent ?? task.progress_percent ?? (total ? completed / total * 100 : status === "completed" ? 100 : 0);
  const percent = clamp(Math.round(Number(rawPercent) || 0), 0, 100);
  const statusText = statusLabel(status);
  byId("task-status").textContent = statusText;
  byId("header-task-status").textContent = statusText;
  byId("header-task-status").dataset.status = status;
  byId("task-current").textContent = task.current_file || task.current_segment || task.detail?.current_file || task.message || t("task.waiting");
  byId("task-percent").textContent = `${percent}%`;
  byId("task-progress").value = percent;
  byId("task-progress").textContent = `${percent}%`;
  byId("task-progress").setAttribute("aria-valuenow", String(percent));
  const logs = task.logs || task.log || [];
  byId("task-log").textContent = Array.isArray(logs) && logs.length ? logs.map((line) => typeof line === "string" ? line : line.message).join("\n") : t("task.no_logs");
}

function renderActionAvailability() {
  const busy = isTaskActive();
  const segment = selectedSegment();
  const segmentIndex = segments().findIndex((item) => String(item.id) === String(state.selectedSegmentId));
  byId("pick-source-btn").disabled = busy;
  byId("scan-btn").disabled = busy || !state.pendingSourcePath;
  byId("clear-project-btn").disabled = busy || !state.project;
  byId("move-up-btn").disabled = busy || segmentIndex <= 0;
  byId("move-down-btn").disabled = busy || segmentIndex < 0 || segmentIndex >= segments().length - 1;
  byId("split-btn").disabled = busy || !segment || !byId("split-frame").value;
  byId("merge-btn").disabled = busy || segmentIndex < 0 || segmentIndex >= segments().length - 1;
  byId("bad-frame-btn").disabled = busy || !state.selectedFrames.size;
  byId("unmark-bad-frame-btn").disabled = busy || !state.selectedFrames.size;
  byId("set-golden-start-btn").disabled = busy || !state.selectedFrames.size;
  byId("set-golden-end-btn").disabled = busy || !state.selectedFrames.size;
  byId("process-btn").disabled = busy || !segments().length;
  byId("retry-btn").disabled = busy || !segment;
  byId("cancel-btn").disabled = !busy || taskStatus() === "cancelling";
  byId("export-btn").disabled = busy || !segments().some((item) => ["rendered", "completed"].includes(item.status || item.render_status));
  byId("archive-btn").disabled = busy || !state.project;
  document.querySelectorAll(".recipe-panel input, .recipe-panel select, .recipe-panel button").forEach((control) => { control.disabled = busy || !segment; });
}

function updateTaskPolling() {
  if (isTaskActive() && !state.pollingTimer) {
    state.pollingTimer = window.setInterval(pollTask, 1000);
  } else if (!isTaskActive() && state.pollingTimer) {
    window.clearInterval(state.pollingTimer);
    state.pollingTimer = null;
  }
}

async function pollTask() {
  try {
    const previous = taskStatus();
    state.task = normaliseTask(await api(API.task));
    renderTask();
    renderActionAvailability();
    if (ACTIVE_TASK_STATES.has(previous) && !isTaskActive()) await refreshState();
    updateTaskPolling();
  } catch (error) {
    showError(error);
    updateTaskPolling();
  }
}

function switchView(viewName) {
  document.querySelectorAll("[data-view-panel]").forEach((panel) => {
    const active = panel.dataset.viewPanel === viewName;
    panel.classList.toggle("is-active", active);
    panel.hidden = !active;
  });
  document.querySelectorAll("[data-view]").forEach((button) => {
    const active = button.dataset.view === viewName;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  if (viewName === "history") loadHistory();
  if (viewName === "settings") loadSettings();
}

function handleTabKeydown(event) {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  const currentIndex = tabs.indexOf(event.target);
  if (currentIndex < 0) return;
  let nextIndex = null;
  if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % tabs.length;
  if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
  if (event.key === "Home") nextIndex = 0;
  if (event.key === "End") nextIndex = tabs.length - 1;
  if (nextIndex == null) return;
  event.preventDefault();
  tabs[nextIndex].focus();
  switchView(tabs[nextIndex].dataset.view);
}

async function pickDirectory() {
  try {
    clearError();
    const result = await api(API.pickDirectory, { method: "POST" });
    if (result.path) {
      state.pendingSourcePath = result.path;
      renderSource();
      renderActionAvailability();
    }
  } catch (error) { showError(error); }
}

async function scanSource() {
  if (!state.pendingSourcePath) return;
  await startOperation(API.scan, { source_dir: state.pendingSourcePath });
}

async function startOperation(path, body = {}) {
  try {
    clearError();
    const payload = await api(path, { method: "POST", body });
    state.task = normaliseTask(payload.task || payload);
    renderTask();
    renderActionAvailability();
    updateTaskPolling();
  } catch (error) { showError(error); }
}

async function selectSegment(segmentId) {
  if (String(segmentId) === String(state.selectedSegmentId)) return;
  state.selectedSegmentId = segmentId;
  state.selectedFrames.clear();
  state.selectionAnchor = null;
  state.thumbnails = [];
  state.chart = null;
  renderSegments();
  renderSegmentDetail();
  renderFrameStrip();
  drawChart();
  renderActionAvailability();
  await loadSegmentMedia(segmentId);
}

async function patchSelectedSegment(values, { refresh = true, throwOnError = false } = {}) {
  const segment = selectedSegment();
  if (!segment) return;
  return patchSegmentById(segment.id, values, { refresh, throwOnError });
}

async function patchSegmentById(segmentId, values, { refresh = true, throwOnError = false } = {}) {
  try {
    const payload = await api(API.segment(segmentId), { method: "PATCH", body: values });
    if (payload.project) state.project = payload.project;
    else {
      const segment = segments().find((item) => String(item.id) === String(segmentId));
      if (segment && payload.segment) Object.assign(segment, payload.segment);
      else if (segment) Object.assign(segment, values);
    }
    if (refresh) renderAll();
  } catch (error) {
    showError(error);
    if (throwOnError) throw error;
  }
}

function recipePayload() {
  return {
    name: byId("recipe-select").value,
    strength: Number(byId("recipe-strength").value),
    deflicker: {
      enabled: byId("deflicker-enabled").checked,
      window: Number(byId("deflicker-window").value),
      gain_limit: Number(byId("gain-limit").value)
    },
    golden: {
      strength: Number(byId("golden-strength").value),
      start: valueOrNull(byId("golden-start").value),
      end: valueOrNull(byId("golden-end").value)
    }
  };
}

function valueOrNull(value) {
  return value === "" ? null : Number(value);
}

function scheduleRecipeSave() {
  byId("recipe-strength-value").textContent = `${byId("recipe-strength").value}%`;
  byId("golden-strength-value").textContent = `${byId("golden-strength").value}%`;
  document.querySelectorAll("[data-recipe]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.recipe === byId("recipe-select").value)));
  const segment = selectedSegment();
  if (!segment) return;
  state.pendingRecipe = { segmentId: segment.id, recipe: recipePayload() };
  window.clearTimeout(state.recipeSaveTimer);
  state.recipeSaveTimer = window.setTimeout(persistPendingRecipe, 300);
}

function persistPendingRecipe() {
  if (!state.pendingRecipe) return state.recipeSavePromise;
  const { segmentId, recipe } = state.pendingRecipe;
  state.pendingRecipe = null;
  state.recipeSaveTimer = null;
  state.recipeSavePromise = state.recipeSavePromise
    .catch(() => undefined)
    .then(() => patchSegmentById(segmentId, { recipe }, { refresh: false, throwOnError: true }));
  state.recipeSavePromise.catch(showError);
  return state.recipeSavePromise;
}

async function flushRecipeSave() {
  window.clearTimeout(state.recipeSaveTimer);
  state.recipeSaveTimer = null;
  if (state.pendingRecipe) persistPendingRecipe();
  await state.recipeSavePromise;
}

async function splitSegment() {
  const segment = selectedSegment();
  if (!segment) return;
  try {
    await api(API.split, { method: "POST", body: { segment_id: segment.id, frame_index: Number(byId("split-frame").value) } });
    await refreshState();
  } catch (error) { showError(error); }
}

async function mergeNextSegment() {
  const index = segments().findIndex((item) => String(item.id) === String(state.selectedSegmentId));
  if (index < 0 || index >= segments().length - 1) return;
  try {
    await api(API.merge, { method: "POST", body: { left_id: segments()[index].id, right_id: segments()[index + 1].id } });
    await refreshState();
  } catch (error) { showError(error); }
}

async function moveSegment(direction) {
  const orderedIds = segments().map((item) => item.id);
  const index = orderedIds.findIndex((id) => String(id) === String(state.selectedSegmentId));
  const target = index + direction;
  if (index < 0 || target < 0 || target >= orderedIds.length) return;
  [orderedIds[index], orderedIds[target]] = [orderedIds[target], orderedIds[index]];
  try {
    await api(API.reorder, { method: "POST", body: { ordered_ids: orderedIds } });
    await refreshState();
  } catch (error) { showError(error); }
}

function selectFrame(index, extend) {
  if (extend && state.selectionAnchor != null) {
    const [start, end] = [state.selectionAnchor, index].sort((a, b) => a - b);
    state.selectedFrames = new Set(Array.from({ length: end - start + 1 }, (_, offset) => start + offset));
  } else {
    if (state.selectedFrames.has(index)) state.selectedFrames.delete(index); else state.selectedFrames.add(index);
    state.selectionAnchor = index;
  }
  renderFrameStrip();
}

async function updateRejected(markRejected) {
  const segment = selectedSegment();
  if (!segment) return;
  const rejected = new Set((segment.rejected_frames || segment.bad_frames || []).map(stableValue).filter(Boolean));
  state.selectedFrames.forEach((index) => {
    const thumbnail = state.thumbnails[index];
    const stableId = frameStableId(thumbnail, index);
    if (!stableId) return;
    if (markRejected) rejected.add(stableId); else rejected.delete(stableId);
  });
  await patchSelectedSegment({ rejected_frames: [...rejected].sort((left, right) => left.localeCompare(right)) });
  renderFrameStrip();
}

async function setGoldenBoundary(which) {
  if (!state.selectedFrames.size) return;
  const index = which === "start" ? Math.min(...state.selectedFrames) : Math.max(...state.selectedFrames);
  byId(`golden-${which}`).value = index;
  scheduleRecipeSave();
  try { await flushRecipeSave(); } catch (error) { showError(error); }
}

async function cancelTask() {
  try {
    const payload = await api(API.cancel, { method: "POST" });
    state.task = normaliseTask(payload.task || payload);
    renderTask();
    renderActionAvailability();
  } catch (error) { showError(error); }
}

async function processSegments(fromStage, path) {
  try {
    await flushRecipeSave();
    const segmentIds = path === API.retry && state.selectedSegmentId
      ? [state.selectedSegmentId]
      : segments().map((segment) => segment.id);
    await startOperation(path, { segment_ids: segmentIds, from_stage: fromStage });
  } catch (error) { showError(error); }
}

async function exportVideo() {
  try {
    await flushRecipeSave();
    await startOperation(API.export, {
      segment_ids: state.selectedSegmentId ? [state.selectedSegmentId] : segments().map((segment) => segment.id),
      fps: Number(byId("export-fps").value),
      resolution: byId("export-resolution").value,
      codec: byId("export-codec").value,
      crf: Number(byId("export-crf").value)
    });
  } catch (error) { showError(error); }
}

async function archiveProject() {
  byId("archive-dialog").close();
  try {
    await flushRecipeSave();
    await startOperation(API.archive, { confirm_workspace_clear: true, preserve_source: true });
  } catch (error) { showError(error); }
}

async function clearProject() {
  byId("clear-project-dialog").close();
  try {
    await api(API.project, { method: "DELETE", body: { confirm: true } });
    state.project = null;
    state.selectedSegmentId = null;
    state.thumbnails = [];
    renderAll();
    renderFrameStrip();
    drawChart();
  } catch (error) { showError(error); }
}

async function loadHistory() {
  const list = byId("history-list");
  const loading = document.createElement("div");
  loading.className = "empty-state";
  loading.textContent = t("history.loading");
  list.replaceChildren(loading);
  try {
    const payload = await api(API.history);
    const summaries = payload.history || payload.archives || payload.items || [];
    state.history = await Promise.all(summaries.map(loadHistoryDetail));
    state.history.sort((left, right) => historySortValue(right) - historySortValue(left));
    renderHistory();
  } catch (error) {
    list.innerHTML = "";
    showError(error);
  }
}

async function loadHistoryDetail(summary) {
  const timestamp = summary.timestamp || summary.archive_id || summary.id;
  if (!timestamp) return normaliseHistoryMedia(summary, {});
  try {
    const detail = await api(API.historyItem(timestamp));
    const manifest = detail.manifest || detail.archive || detail;
    return normaliseHistoryMedia(summary, manifest);
  } catch (error) {
    return normaliseHistoryMedia(summary, {});
  }
}

function normaliseHistoryMedia(summary, manifest) {
  return {
    ...summary,
    ...manifest,
    previews: mergeMediaItems(summary.previews || summary.preview_videos, manifest.previews || manifest.preview_videos),
    outputs: mergeMediaItems(summary.outputs || summary.final_videos, manifest.outputs || manifest.final_videos)
  };
}

function mergeMediaItems(...groups) {
  const items = groups.flatMap((group) => Array.isArray(group) ? group : [group].filter(Boolean));
  const seen = new Set();
  return items.filter((item) => {
    const key = typeof item === "string" ? item : item?.url || item?.path;
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function renderHistory() {
  const list = byId("history-list");
  list.replaceChildren();
  if (!state.history.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = t("history.empty");
    list.append(empty);
    return;
  }
  state.history.forEach((entry) => {
    const article = document.createElement("article");
    article.className = "history-entry";
    const identity = document.createElement("div");
    const title = document.createElement("h2");
    title.textContent = entry.timestamp || entry.created_at || entry.archived_at || t("history.legacy");
    const source = document.createElement("span");
    source.className = "muted";
    source.textContent = entry.source_dir || t("history.source_unavailable");
    source.title = source.textContent;
    identity.append(title, source);
    const summary = document.createElement("div");
    const counts = document.createElement("div");
    counts.textContent = t("history.counts", { segments: entry.segment_count ?? entry.segments?.length ?? 0, jpegs: historyJpegCount(entry) });
    const recipes = document.createElement("div");
    recipes.className = "recipe-summary";
    recipes.textContent = t("history.recipe", { value: recipeSummary(entry) });
    summary.append(counts, recipes);
    const media = document.createElement("div");
    media.className = "media-links";
    appendMediaLinks(media, t("history.preview"), entry.previews || entry.preview_videos || []);
    appendMediaLinks(media, t("history.output"), entry.outputs || entry.final_videos || []);
    article.append(identity, summary, media);
    list.append(article);
  });
}

function historySortValue(entry) {
  const raw = String(entry.timestamp || entry.created_at || entry.archived_at || "");
  const parsed = Date.parse(raw.replace(/^(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})(\d{2})$/, "$1T$2:$3:$4"));
  if (Number.isFinite(parsed)) return parsed;
  return Number(raw.replace(/\D/g, "").slice(0, 14)) || 0;
}

function historyJpegCount(entry) {
  const segmentCounts = (entry.segments || [])
    .map((segment) => Number(segment.jpeg_count))
    .filter(Number.isFinite);
  if (segmentCounts.length) return segmentCounts.reduce((total, count) => total + count, 0);
  return Number(entry.jpeg_count ?? entry.frame_count ?? 0) || 0;
}

function recipeSummary(entry) {
  const values = [];
  if (Array.isArray(entry.recipes)) values.push(...entry.recipes);
  else if (entry.recipes && typeof entry.recipes === "object") values.push(...Object.values(entry.recipes));
  (entry.segments || []).forEach((segment) => values.push(segment.recipe));
  const labels = values.filter(Boolean).map((recipe) => {
    if (typeof recipe === "string") return recipe;
    const name = recipe.name || recipe.mode || recipe.preset || t("recipe.custom");
    return recipe.strength == null ? name : `${name} ${recipe.strength}%`;
  });
  return [...new Set(labels)].join(preferences.language === "zh-CN" ? "、" : ", ") || t("history.record_unavailable");
}

function appendMediaLinks(container, label, items) {
  const values = Array.isArray(items) ? items : [items].filter(Boolean);
  if (!values.length) {
    const missing = document.createElement("span");
    missing.className = "muted";
    missing.textContent = t("history.missing", { label });
    container.append(missing);
    return;
  }
  values.forEach((item, index) => {
    const link = document.createElement("a");
    link.href = typeof item === "string" ? item : item.url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = `${label}${values.length > 1 ? ` ${index + 1}` : ""}`;
    container.append(link);
  });
}

async function loadSettings() {
  try {
    const payload = await api(API.settings);
    state.settings = payload.settings || payload.config || payload;
    setSettingsForm(state.settings);
  } catch (error) { showError(error); }
}

function setSettingsForm(settings) {
  byId("settings-workspace-dir").value = settings.workspace_dir || "";
  byId("settings-output-dir").value = settings.output_dir || "";
  byId("settings-archive-dir").value = settings.archive_dir || "";
  byId("settings-default-recipe").value = settings.processing?.default_recipe || "natural";
  byId("settings-gap-seconds").value = settings.scan?.gap_seconds ?? 120;
  byId("settings-preview-fps").value = settings.preview?.fps ?? 30;
  byId("settings-preview-width").value = settings.preview?.width ?? 1920;
  byId("settings-export-resolution").value = settings.export?.resolution || "4k";
  byId("settings-export-codec").value = settings.export?.codec || "h264";
  byId("settings-export-crf").value = settings.export?.crf ?? 18;
}

async function saveSettings(event) {
  event.preventDefault();
  byId("settings-save-status").textContent = "";
  const values = {
    workspace_dir: byId("settings-workspace-dir").value,
    output_dir: byId("settings-output-dir").value,
    archive_dir: byId("settings-archive-dir").value,
    processing: { default_recipe: byId("settings-default-recipe").value },
    scan: { gap_seconds: Number(byId("settings-gap-seconds").value) },
    preview: { fps: Number(byId("settings-preview-fps").value), width: Number(byId("settings-preview-width").value) },
    export: { resolution: byId("settings-export-resolution").value, codec: byId("settings-export-codec").value, crf: Number(byId("settings-export-crf").value) }
  };
  try {
    const payload = await api(API.settings, { method: "PUT", body: values });
    state.settings = payload.settings || payload.config || values;
    setSettingsForm(state.settings);
    byId("settings-save-status").textContent = payload.restart_required
      ? t("settings.saved_restart")
      : t("settings.saved");
  } catch (error) { showError(error); }
}

async function pickSettingsDirectory(purpose) {
  try {
    const result = await api(API.pickDirectory, { method: "POST", body: { purpose } });
    if (result.path) byId(`settings-${purpose}-dir`).value = result.path;
  } catch (error) { showError(error); }
}

function bindEvents() {
  document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
  byId("app").querySelector('[role="tablist"]').addEventListener("keydown", handleTabKeydown);
  byId("open-settings-btn").addEventListener("click", () => switchView("settings"));
  byId("dismiss-error-btn").addEventListener("click", clearError);
  byId("pick-source-btn").addEventListener("click", pickDirectory);
  byId("scan-btn").addEventListener("click", scanSource);
  byId("clear-project-btn").addEventListener("click", () => byId("clear-project-dialog").showModal());
  byId("clear-confirm-btn").addEventListener("click", clearProject);
  byId("segment-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-segment-id]");
    if (button) selectSegment(button.dataset.segmentId);
  });
  byId("segment-name").addEventListener("change", (event) => patchSelectedSegment({ name: event.target.value.trim() }));
  byId("split-frame").addEventListener("input", renderActionAvailability);
  byId("split-btn").addEventListener("click", splitSegment);
  byId("merge-btn").addEventListener("click", mergeNextSegment);
  byId("move-up-btn").addEventListener("click", () => moveSegment(-1));
  byId("move-down-btn").addEventListener("click", () => moveSegment(1));
  document.querySelectorAll("[data-recipe]").forEach((button) => button.addEventListener("click", () => { byId("recipe-select").value = button.dataset.recipe; scheduleRecipeSave(); }));
  ["recipe-select", "recipe-strength", "golden-strength", "deflicker-enabled", "deflicker-window", "gain-limit", "golden-start", "golden-end"].forEach((id) => byId(id).addEventListener("input", scheduleRecipeSave));
  byId("frame-strip").addEventListener("click", (event) => {
    const button = event.target.closest("[data-frame-index]");
    if (button) selectFrame(Number(button.dataset.frameIndex), event.shiftKey);
  });
  byId("frame-page-prev").addEventListener("click", () => { state.thumbnailPage -= 1; renderFrameStrip(); });
  byId("frame-page-next").addEventListener("click", () => { state.thumbnailPage += 1; renderFrameStrip(); });
  byId("bad-frame-btn").addEventListener("click", () => updateRejected(true));
  byId("unmark-bad-frame-btn").addEventListener("click", () => updateRejected(false));
  byId("set-golden-start-btn").addEventListener("click", () => setGoldenBoundary("start"));
  byId("set-golden-end-btn").addEventListener("click", () => setGoldenBoundary("end"));
  byId("process-btn").addEventListener("click", () => processSegments("analyze", API.process));
  byId("retry-btn").addEventListener("click", () => processSegments(byId("retry-stage").value, API.retry));
  byId("cancel-btn").addEventListener("click", cancelTask);
  byId("export-btn").addEventListener("click", exportVideo);
  byId("archive-btn").addEventListener("click", () => byId("archive-dialog").showModal());
  byId("archive-confirm-btn").addEventListener("click", archiveProject);
  byId("refresh-history-btn").addEventListener("click", loadHistory);
  byId("settings-form").addEventListener("submit", saveSettings);
  document.querySelectorAll("[data-settings-directory]").forEach((button) => button.addEventListener("click", () => pickSettingsDirectory(button.dataset.settingsDirectory)));
  byId("theme-select").addEventListener("change", (event) => applyTheme(event.target.value));
  byId("language-select").addEventListener("change", (event) => applyLanguage(event.target.value));
  window.addEventListener("resize", drawChart);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (preferences.theme === "system") drawChart();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  byId("theme-select").value = preferences.theme;
  byId("language-select").value = preferences.language;
  translateDocument();
  bindEvents();
  renderFrameStrip();
  drawChart();
  refreshState();
});
