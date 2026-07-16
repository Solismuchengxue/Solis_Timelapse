"use strict";

const API = Object.freeze({
  state: "/api/state",
  capabilities: "/api/capabilities",
  directories: "/api/directories",
  pickDirectory: "/api/pick-directory",
  scan: "/api/project/scan",
  project: "/api/project",
  split: "/api/segments/split",
  merge: "/api/segments/merge",
  segment: (id) => `/api/segments/${encodeURIComponent(id)}`,
  reorder: "/api/segments/reorder",
  thumbnails: (id) => `/api/segments/${encodeURIComponent(id)}/thumbnails`,
  chart: (id) => `/api/segments/${encodeURIComponent(id)}/chart`,
  frameImage: (id, index) => `/api/segments/${encodeURIComponent(id)}/frames/${index}/image`,
  segmentVideo: (id) => `/api/segments/${encodeURIComponent(id)}/video`,
  process: "/api/process",
  retry: "/api/process/retry",
  cancel: "/api/tasks/cancel",
  task: "/api/tasks/current",
  export: "/api/export",
  archive: "/api/archive",
  history: "/api/history",
  historyItem: (timestamp) => `/api/history/${encodeURIComponent(timestamp)}`,
  logs: "/api/logs",
  settings: "/api/settings",
  colorPresets: "/api/color-presets",
  colorPreset: (id) => `/api/color-presets/${encodeURIComponent(id)}`
});

const ACTIVE_TASK_STATES = new Set(["queued", "running", "cancelling"]);
const PAGE_SIZE = 20;
const ui = window.SolisUI;
let preferences = ui.loadPreferences(window.localStorage, window.navigator.language);

const state = {
  project: null,
  task: { status: "idle", progress: 0, logs: [] },
  selectedSegmentId: null,
  selectedSegmentIds: new Set(),
  segmentMultiSelect: false,
  selectedFrames: new Set(),
  frameMultiSelect: false,
  selectionAnchor: null,
  thumbnails: [],
  thumbnailTotal: 0,
  thumbnailPage: 0,
  chart: null,
  pendingSourcePath: "",
  history: [],
  logs: [],
  settings: {},
  colorPresets: [],
  selectedColorPresetId: null,
  histogramOpen: true,
  exportDialogOpen: false,
  pollingTimer: null,
  recipeSaveTimer: null,
  recipeSavePromise: Promise.resolve(),
  pendingRecipe: null,
  capabilities: { mode: "local", native_directory_picker: true, directory_browser: false },
  directoryBrowserPath: ""
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

function syncPreferenceControls() {
  document.querySelectorAll("[data-theme-choice]").forEach((button) => {
    button.setAttribute("aria-checked", String(button.dataset.themeChoice === preferences.theme));
  });
  document.querySelectorAll("[data-language-choice]").forEach((button) => {
    button.setAttribute("aria-checked", String(button.dataset.languageChoice === preferences.language));
  });
}

function applyTheme(theme) {
  preferences.theme = ui.normalizeTheme(theme);
  localStorage.setItem("solis.theme", preferences.theme);
  ui.applyPreferences(document, preferences);
  syncPreferenceControls();
  drawChart();
  window.dispatchEvent(new CustomEvent("solis:themechange", { detail: { value: preferences.theme } }));
}

function applyLanguage(language) {
  preferences.language = ui.normalizeLanguage(language, navigator.language);
  localStorage.setItem("solis.language", preferences.language);
  ui.applyPreferences(document, preferences);
  syncPreferenceControls();
  translateDocument();
  renderAll();
  renderFrameStrip();
  renderHistory();
  populateColorPresetSelects();
  renderColorPresets();
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

function currentSegmentIdsForAction() {
  const current = selectedSegment();
  return current ? [current.id] : [];
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
    state.selectedSegmentIds = new Set(
      [...state.selectedSegmentIds].filter((id) => ids.has(String(id)))
    );
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
  list.classList.toggle("is-merge-mode", state.segmentMultiSelect);
  list.setAttribute("aria-multiselectable", String(state.segmentMultiSelect));
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
    const isCurrent = String(segment.id) === String(state.selectedSegmentId);
    const isSelected = !state.segmentMultiSelect && isCurrent;
    button.classList.toggle("is-selected", isSelected);
    const isMergeSelected = state.selectedSegmentIds.has(String(segment.id));
    button.classList.toggle("is-merge-selected", isMergeSelected);
    button.setAttribute("aria-selected", String(state.segmentMultiSelect ? isMergeSelected : isCurrent));

    const check = document.createElement("span");
    check.className = "segment-check";
    check.textContent = isMergeSelected ? "✓" : "";
    check.setAttribute("aria-hidden", "true");

    const name = document.createElement("strong");
    name.textContent = segment.name || t("segment.unnamed");
    const heading = document.createElement("span");
    heading.className = "segment-item-heading";
    const meta = document.createElement("span");
    meta.className = "segment-item-meta";
    const focal = segment.focal_length ? `${segment.focal_length}mm` : t("segment.focal_unknown");
    const timeRange = segment.time_range || segment.captured_range || t("segment.time_unknown");
    meta.textContent = t("segment.meta", { count: frameCount(segment), focal, time: timeRange });
    const status = document.createElement("span");
    status.className = "segment-item-status";
    status.textContent = statusLabel(segment.status || segment.render_status || "pending");
    heading.append(name, status);
    button.append(check, heading, meta);
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
  const surface = byId("segment-preview");
  surface.replaceChildren();
  const selectedFrameIndex = !state.frameMultiSelect && state.selectedFrames.size === 1
    ? [...state.selectedFrames][0]
    : null;
  const selectedFrame = selectedFrameIndex == null
    ? null
    : state.thumbnails.find((frame) => Number(frame.index) === selectedFrameIndex);
  const representative = segment?.representative_url || segment?.preview_image || state.thumbnails[0]?.url;
  if (segment && selectedFrameIndex != null) {
    const image = document.createElement("img");
    image.className = "source-frame-preview";
    image.src = API.frameImage(segment.id, selectedFrameIndex);
    image.alt = frameTooltip(selectedFrame || {}, selectedFrameIndex);
    image.decoding = "async";
    surface.append(image);
    attachPreviewHistogram(surface, image);
    const dimensions = selectedFrame?.width && selectedFrame?.height
      ? ` · ${selectedFrame.width}×${selectedFrame.height}`
      : "";
    byId("preview-caption").textContent = `${selectedFrame?.name || `#${selectedFrameIndex + 1}`}${dimensions}`;
  } else if (hasSegmentVideo(segment)) {
    const video = document.createElement("video");
    video.className = "exported-video-preview";
    video.src = API.segmentVideo(segment.id);
    video.controls = true;
    video.preload = "metadata";
    surface.append(video);
    byId("preview-caption").textContent = segment?.export_artifact
      ? t("history.output")
      : t("history.preview");
  } else if (representative) {
    const image = document.createElement("img");
    image.src = representative;
    image.alt = t("preview.alt", { name: segment.name || t("segment.current") });
    surface.append(image);
    attachPreviewHistogram(surface, image);
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
      api(`${API.thumbnails(segmentId)}?offset=0&limit=${PAGE_SIZE}`),
      api(API.chart(segmentId))
    ]);
    if (String(segmentId) !== String(state.selectedSegmentId)) return;
    state.thumbnails = thumbnailPayload.thumbnails || thumbnailPayload.frames || [];
    state.thumbnailTotal = Number(thumbnailPayload.total || state.thumbnails.length);
    state.chart = chartPayload.chart || chartPayload;
    state.thumbnailPage = 0;
    state.selectedFrames = state.thumbnailTotal ? new Set([0]) : new Set();
    state.frameMultiSelect = false;
    state.selectionAnchor = state.thumbnailTotal ? 0 : null;
    renderFrameStrip();
    drawChart();
    renderSegmentDetail();
  } catch (error) {
    if (error.status !== 404 && error.status !== 409) showError(error);
    state.thumbnails = [];
    state.thumbnailTotal = 0;
    state.chart = null;
    renderFrameStrip();
    drawChart();
  }
}

function hasSegmentVideo(segment) {
  return Boolean(segment?.export_artifact || segment?.preview_file);
}

function attachPreviewHistogram(surface, image) {
  const panel = document.createElement("details");
  panel.id = "preview-histogram-panel";
  panel.className = "preview-histogram-panel";
  panel.open = state.histogramOpen;
  const summary = document.createElement("summary");
  summary.textContent = t("preview.histogram");
  const canvas = document.createElement("canvas");
  canvas.id = "preview-histogram";
  canvas.className = "preview-histogram";
  canvas.width = 256;
  canvas.height = 96;
  canvas.setAttribute("aria-label", t("preview.histogram_aria"));
  panel.append(summary, canvas);
  panel.addEventListener("toggle", () => { state.histogramOpen = panel.open; });
  surface.append(panel);
  const draw = () => drawPreviewHistogram(image);
  if (image.complete && image.naturalWidth) window.requestAnimationFrame(draw);
  else image.addEventListener("load", draw, { once: true });
}

function drawPreviewHistogram(image) {
  const canvas = byId("preview-histogram");
  if (!canvas || !image?.naturalWidth) return;
  const sample = document.createElement("canvas");
  sample.width = 160;
  sample.height = 100;
  const sampleContext = sample.getContext("2d", { willReadFrequently: true });
  const context = canvas.getContext("2d");
  if (!sampleContext || !context) return;
  try {
    sampleContext.drawImage(image, 0, 0, sample.width, sample.height);
    const pixels = sampleContext.getImageData(0, 0, sample.width, sample.height).data;
    const channels = [new Uint32Array(64), new Uint32Array(64), new Uint32Array(64)];
    for (let index = 0; index < pixels.length; index += 4) {
      channels[0][pixels[index] >> 2] += 1;
      channels[1][pixels[index + 1] >> 2] += 1;
      channels[2][pixels[index + 2] >> 2] += 1;
    }
    const maximum = Math.max(1, ...channels.flatMap((values) => [...values]));
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = "rgba(9, 13, 12, 0.58)";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.strokeStyle = "rgba(255, 255, 255, 0.12)";
    context.lineWidth = 1;
    for (let line = 1; line < 4; line += 1) {
      const y = Math.round(line * canvas.height / 4) + 0.5;
      context.beginPath();
      context.moveTo(0, y);
      context.lineTo(canvas.width, y);
      context.stroke();
    }
    ["rgba(255, 91, 91, 0.9)", "rgba(78, 224, 150, 0.9)", "rgba(88, 150, 255, 0.9)"].forEach((color, channel) => {
      context.strokeStyle = color;
      context.lineWidth = 1.5;
      context.beginPath();
      channels[channel].forEach((value, index) => {
        const x = index / 63 * (canvas.width - 1);
        const y = canvas.height - 4 - value / maximum * (canvas.height - 10);
        if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
      });
      context.stroke();
    });
  } catch (_error) {
    canvas.hidden = true;
  }
}

async function loadThumbnailPage(page) {
  const segmentId = state.selectedSegmentId;
  if (!segmentId) return;
  const targetPage = Math.max(0, page);
  try {
    const payload = await api(
      `${API.thumbnails(segmentId)}?offset=${targetPage * PAGE_SIZE}&limit=${PAGE_SIZE}`
    );
    if (String(segmentId) !== String(state.selectedSegmentId)) return;
    state.thumbnails = payload.thumbnails || payload.frames || [];
    state.thumbnailTotal = Number(payload.total || state.thumbnails.length);
    state.thumbnailPage = targetPage;
    renderFrameStrip();
    renderSegmentDetail();
  } catch (error) { showError(error); }
}

function renderFrameStrip() {
  const strip = byId("frame-strip");
  strip.replaceChildren();
  const totalPages = Math.ceil(state.thumbnailTotal / PAGE_SIZE);
  state.thumbnailPage = clamp(state.thumbnailPage, 0, Math.max(0, totalPages - 1));
  const pageFrames = state.thumbnails;
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
    const indexLabel = document.createElement("span");
    indexLabel.className = "frame-index-badge";
    indexLabel.textContent = `#${absoluteIndex + 1}`;
    const label = document.createElement("span");
    label.className = "frame-name";
    label.textContent = frame.name || `#${absoluteIndex + 1}`;
    button.append(image, indexLabel, label);
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
  byId("frame-multi-select-btn").setAttribute("aria-pressed", String(state.frameMultiSelect));
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

function frameLuminanceChanges(values) {
  return values.map((rawValue, index) => {
    if (index === 0) return 0;
    const current = Number(rawValue);
    const previous = Number(values[index - 1]);
    return Number.isFinite(current) && Number.isFinite(previous) ? current - previous : 0;
  });
}

function buildVideoChartSeries(chart, chartType, colors) {
  const measured = chart.luminance || chart.measured_luminance || [];
  if (chartType === "gain") {
    return {
      baseline: 1,
      series: [{ values: chart.gain || chart.gains || [], color: colors.warning }]
    };
  }
  if (chartType === "change") {
    return {
      baseline: 0,
      series: [{ values: frameLuminanceChanges(measured), color: colors.danger }]
    };
  }
  return {
    baseline: null,
    series: [
      { values: measured, color: colors.muted },
      { values: chart.target_luminance || chart.target || [], color: colors.accent }
    ]
  };
}

function drawChart() {
  const canvas = byId("brightness-chart");
  const context = canvas.getContext("2d");
  const cssWidth = Math.max(320, Math.floor(canvas.clientWidth || 720));
  const cssHeight = Math.max(96, Math.floor(canvas.clientHeight || 220));
  const scale = window.devicePixelRatio || 1;
  canvas.width = cssWidth * scale;
  canvas.height = cssHeight * scale;
  context.scale(scale, scale);
  context.clearRect(0, 0, cssWidth, cssHeight);
  context.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--line-strong");
  context.lineWidth = 1;
  context.beginPath();
  const axisLeft = 18;
  const axisTop = 4;
  const axisBottom = cssHeight - 10;
  const axisRight = cssWidth - 4;
  context.moveTo(axisLeft, axisTop);
  context.lineTo(axisLeft, axisBottom);
  context.lineTo(axisRight, axisBottom);
  context.stroke();

  const chartType = byId("chart-type-select").value || "brightness";
  byId("chart-legend").textContent = t(`chart.legend.${chartType}`);
  canvas.setAttribute("aria-label", `${t("chart.aria")} · ${t(`chart.type.${chartType}`)}`);
  const styles = getComputedStyle(document.documentElement);
  const chart = state.chart || {};
  const chartDefinition = buildVideoChartSeries(chart, chartType, {
    muted: styles.getPropertyValue("--muted"),
    accent: styles.getPropertyValue("--accent"),
    warning: styles.getPropertyValue("--warning"),
    danger: styles.getPropertyValue("--danger")
  });
  const series = chartDefinition.series.filter((item) => item.values.length);
  if (!series.length) {
    context.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--muted");
    context.fillText(t("chart.empty"), axisLeft + 10, cssHeight / 2);
    return;
  }
  const all = series.flatMap((item) => item.values.map(Number).filter(Number.isFinite));
  if (chartDefinition.baseline != null) all.push(chartDefinition.baseline);
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max - min || 1;
  if (chartDefinition.baseline != null) {
    const y = axisTop + (1 - (chartDefinition.baseline - min) / span) * (axisBottom - axisTop);
    context.save();
    context.setLineDash([4, 4]);
    context.strokeStyle = styles.getPropertyValue("--line-strong");
    context.beginPath();
    context.moveTo(axisLeft, y);
    context.lineTo(axisRight, y);
    context.stroke();
    context.restore();
  }
  series.forEach((item) => {
    context.strokeStyle = item.color;
    context.lineWidth = 1.7;
    context.beginPath();
    item.values.forEach((rawValue, index) => {
      const x = axisLeft + (index / Math.max(1, item.values.length - 1)) * (axisRight - axisLeft);
      const y = axisTop + (1 - (Number(rawValue) - min) / span) * (axisBottom - axisTop);
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
  if (state.exportDialogOpen && task.kind === "export") updateExportDialog(task);
}

function renderActionAvailability() {
  const busy = isTaskActive();
  const segment = selectedSegment();
  const renderedSegment = Boolean(segment)
    && ["rendered", "completed"].includes(segment.render_status || segment.status);
  const segmentIndex = segments().findIndex((item) => String(item.id) === String(state.selectedSegmentId));
  byId("pick-source-btn").disabled = busy;
  byId("scan-btn").disabled = busy || !state.pendingSourcePath;
  byId("clear-project-btn").disabled = busy || !state.project;
  byId("move-up-btn").disabled = busy || segmentIndex <= 0;
  byId("move-down-btn").disabled = busy || segmentIndex < 0 || segmentIndex >= segments().length - 1;
  byId("split-btn").disabled = busy || !segment || !byId("split-frame").value;
  byId("segment-multi-select-btn").disabled = busy || segments().length < 2;
  byId("segment-multi-select-btn").setAttribute("aria-pressed", String(state.segmentMultiSelect));
  byId("merge-btn").disabled = busy || state.selectedSegmentIds.size < 2;
  byId("bad-frame-btn").disabled = busy || !state.selectedFrames.size;
  byId("unmark-bad-frame-btn").disabled = busy || !state.selectedFrames.size;
  byId("frame-multi-select-btn").disabled = busy || !segment;
  byId("process-current-btn").disabled = busy || !segment;
  byId("cancel-btn").disabled = !busy || taskStatus() === "cancelling";
  byId("export-btn").disabled = busy || !renderedSegment;
  byId("preview-video-btn").disabled = busy || !hasSegmentVideo(segment);
  byId("archive-btn").disabled = busy || !renderedSegment || !segment?.export_artifact;
  byId("clear-logs-btn").disabled = busy || !state.logs.length;
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
    const completedTask = normaliseTask(await api(API.task));
    state.task = completedTask;
    renderTask();
    renderActionAvailability();
    if (byId("view-history").classList.contains("is-active")) await loadLogs();
    if (ACTIVE_TASK_STATES.has(previous) && !isTaskActive()) {
      await refreshState();
      showTaskCompletion(completedTask);
    }
    updateTaskPolling();
  } catch (error) {
    showError(error);
    updateTaskPolling();
  }
}

function switchView(viewName) {
  byId("app").dataset.activeView = viewName;
  byId("source-band").hidden = viewName !== "workbench";
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
  if (viewName === "history") Promise.all([loadHistory(), loadLogs()]);
  if (viewName === "recipes") loadColorPresets();
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

function chooseDirectoryMode(capabilities) {
  return capabilities?.native_directory_picker ? "native" : "browser";
}

async function loadCapabilities() {
  state.capabilities = await api(API.capabilities);
  document.querySelectorAll("[data-settings-directory]").forEach((button) => {
    button.disabled = !state.capabilities.native_directory_picker;
  });
}

function containerSourcePath(relative) {
  return relative ? `/media/input/${relative}` : "/media/input";
}

function renderDirectoryBrowser(payload) {
  state.directoryBrowserPath = payload.path || "";
  const breadcrumb = byId("directory-browser-breadcrumb");
  breadcrumb.replaceChildren();
  const rootButton = document.createElement("button");
  rootButton.type = "button";
  rootButton.dataset.directoryPath = "";
  rootButton.textContent = t("browser.root");
  breadcrumb.append(rootButton);
  const parts = state.directoryBrowserPath.split("/").filter(Boolean);
  parts.forEach((part, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.directoryPath = parts.slice(0, index + 1).join("/");
    button.textContent = part;
    breadcrumb.append(button);
  });

  const list = byId("directory-browser-list");
  list.replaceChildren();
  if (!payload.directories?.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = t("browser.empty");
    list.append(empty);
    return;
  }
  payload.directories.forEach((directory) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "directory-row";
    button.dataset.directoryPath = directory.path;
    const icon = document.createElement("span");
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = "▸";
    const label = document.createElement("span");
    label.textContent = directory.name;
    button.append(icon, label);
    list.append(button);
  });
}

async function openDirectoryBrowser(relative = "") {
  try {
    clearError();
    const payload = await api(`${API.directories}?${new URLSearchParams({ path: relative })}`);
    renderDirectoryBrowser(payload);
    const dialog = byId("directory-browser-dialog");
    if (!dialog.open) dialog.showModal();
  } catch (error) {
    showError(error);
  }
}

function chooseBrowsedDirectory() {
  state.pendingSourcePath = containerSourcePath(state.directoryBrowserPath);
  byId("directory-browser-dialog").close();
  renderSource();
  renderActionAvailability();
}

async function pickDirectory() {
  try {
    clearError();
    if (chooseDirectoryMode(state.capabilities) === "browser") {
      await openDirectoryBrowser("");
      return;
    }
    const result = await api(API.pickDirectory, { method: "POST" });
    if (!result.path) return;
    state.pendingSourcePath = result.path;
    renderSource();
    renderActionAvailability();
  } catch (error) { showError(error); }
}

async function scanSource() {
  if (!state.pendingSourcePath) return;
  await startOperation(API.scan, { source_dir: state.pendingSourcePath });
}

async function startOperation(path, body = {}, options = {}) {
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
  state.thumbnailTotal = 0;
  state.chart = null;
  renderSegments();
  renderSegmentDetail();
  renderFrameStrip();
  drawChart();
  renderActionAvailability();
  await loadSegmentMedia(segmentId);
}

function openExportDialog() {
  const dialog = byId("export-progress-dialog");
  state.exportDialogOpen = true;
  byId("export-progress-title").textContent = t("dialog.export_progress.title");
  byId("export-progress-message").textContent = t("dialog.export_progress.preparing");
  byId("export-progress").value = 0;
  byId("export-progress").setAttribute("aria-valuenow", "0");
  byId("export-progress-cancel-btn").hidden = false;
  byId("export-progress-cancel-btn").disabled = false;
  byId("export-progress-close-btn").hidden = true;
  byId("export-progress-preview-btn").hidden = true;
  if (!dialog.open) dialog.showModal();
}

function updateExportDialog(task) {
  if (!state.exportDialogOpen) return;
  const status = taskStatus(task);
  const completed = Number(task.completed ?? task.progress?.completed ?? 0);
  const total = Number(task.total ?? task.progress?.total ?? 0);
  const rawPercent = task.percent ?? task.progress_percent ?? (total ? completed / total * 100 : status === "completed" ? 100 : 0);
  const percent = clamp(Math.round(Number(rawPercent) || 0), 0, 100);
  const progress = byId("export-progress");
  const cancelButton = byId("export-progress-cancel-btn");
  const closeButton = byId("export-progress-close-btn");
  const previewButton = byId("export-progress-preview-btn");
  progress.value = percent;
  progress.textContent = `${percent}%`;
  progress.setAttribute("aria-valuenow", String(percent));

  if (ACTIVE_TASK_STATES.has(status)) {
    byId("export-progress-title").textContent = status === "cancelling"
      ? t("dialog.export_progress.cancelling")
      : t("dialog.export_progress.title");
    byId("export-progress-message").textContent = task.current_file
      || task.current_segment
      || task.message
      || t("dialog.export_progress.running", { percent });
    cancelButton.hidden = false;
    cancelButton.disabled = status === "cancelling";
    closeButton.hidden = true;
    previewButton.hidden = true;
    return;
  }

  cancelButton.hidden = true;
  closeButton.hidden = false;
  if (status === "completed") {
    const result = task.result || {};
    byId("export-progress-title").textContent = t("dialog.export_done.title");
    byId("export-progress-message").textContent = t("dialog.export_done.body", {
      path: result.output_dir || "-",
      files: Array.isArray(result.outputs) && result.outputs.length ? result.outputs.join(", ") : "-"
    });
    previewButton.hidden = !selectedSegment()?.export_artifact;
  } else if (status === "cancelled") {
    byId("export-progress-title").textContent = t("dialog.export_progress.cancelled");
    byId("export-progress-message").textContent = t("dialog.export_progress.cancelled_body");
    previewButton.hidden = true;
  } else {
    byId("export-progress-title").textContent = t("dialog.export_progress.failed");
    byId("export-progress-message").textContent = task.error || t("error.unknown");
    previewButton.hidden = true;
  }
}

function closeExportDialog() {
  state.exportDialogOpen = false;
  const dialog = byId("export-progress-dialog");
  if (dialog.open) dialog.close();
}

function previewCurrentVideo() {
  const segment = selectedSegment();
  if (!hasSegmentVideo(segment)) return;
  state.frameMultiSelect = false;
  state.selectedFrames.clear();
  state.selectionAnchor = null;
  renderFrameStrip();
  renderSegmentDetail();
  byId("segment-preview").querySelector("video")?.focus();
}

function showTaskCompletion(completedTask) {
  if (completedTask.kind === "export") {
    updateExportDialog(completedTask);
    return;
  }
  if (taskStatus(completedTask) !== "completed") return;
  const result = completedTask.result || {};
  const dialog = byId("operation-result-dialog");
  const title = byId("operation-result-title");
  const message = byId("operation-result-message");
  const historyButton = byId("result-history-btn");
  historyButton.hidden = true;
  if (completedTask.kind === "archive") {
    title.textContent = t("dialog.archive_done.title");
    message.textContent = t("dialog.archive_done.body", { path: result.archive_dir || "-" });
    historyButton.hidden = false;
  } else {
    return;
  }
  dialog.showModal();
}

async function toggleSegmentSelection(segmentId) {
  const key = String(segmentId);
  if (state.selectedSegmentIds.has(key)) state.selectedSegmentIds.delete(key);
  else state.selectedSegmentIds.add(key);
  const selectedPositions = segments()
    .map((item, index) => state.selectedSegmentIds.has(String(item.id)) ? index : -1)
    .filter((index) => index >= 0);
  if (selectedPositions.length >= 2) {
    const first = Math.min(...selectedPositions);
    const last = Math.max(...selectedPositions);
    state.selectedSegmentIds = new Set(
      segments().slice(first, last + 1).map((item) => String(item.id))
    );
  }
  if (!state.selectedSegmentId) await selectSegment(segmentId);
  renderSegments();
  renderActionAvailability();
}

function toggleSegmentMultiSelect() {
  state.segmentMultiSelect = !state.segmentMultiSelect;
  state.selectedSegmentIds.clear();
  if (state.segmentMultiSelect && state.selectedSegmentId) {
    state.selectedSegmentIds.add(String(state.selectedSegmentId));
  }
  renderSegments();
  renderActionAvailability();
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

async function mergeSelectedSegments() {
  const segmentIds = segments()
    .filter((item) => state.selectedSegmentIds.has(String(item.id)))
    .map((item) => item.id);
  if (segmentIds.length < 2) return;
  const selectedId = segmentIds[0];
  try {
    await api(API.merge, { method: "POST", body: { segment_ids: segmentIds } });
    state.selectedSegmentId = selectedId;
    state.selectedSegmentIds.clear();
    state.segmentMultiSelect = false;
    await refreshState();
  } catch (error) {
    showError(error);
  }
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
  if (!state.frameMultiSelect) {
    state.selectedFrames = new Set([index]);
    state.selectionAnchor = index;
  } else if (extend && state.selectionAnchor != null) {
    const [start, end] = [state.selectionAnchor, index].sort((a, b) => a - b);
    state.selectedFrames = new Set(Array.from({ length: end - start + 1 }, (_, offset) => start + offset));
  } else {
    if (state.selectedFrames.has(index)) state.selectedFrames.delete(index); else state.selectedFrames.add(index);
    state.selectionAnchor = index;
  }
  renderFrameStrip();
  renderSegmentDetail();
}

function toggleFrameMultiSelect() {
  state.frameMultiSelect = !state.frameMultiSelect;
  state.selectedFrames.clear();
  state.selectionAnchor = null;
  renderFrameStrip();
  renderSegmentDetail();
}

async function updateRejected(markRejected) {
  const segment = selectedSegment();
  if (!segment) return;
  const rejected = new Set((segment.rejected_frames || segment.bad_frames || []).map(stableValue).filter(Boolean));
  state.selectedFrames.forEach((index) => {
    const thumbnail = state.thumbnails.find((frame) => Number(frame.index) === index);
    const stableId = frameStableId(thumbnail, index);
    if (!stableId) return;
    if (markRejected) rejected.add(stableId); else rejected.delete(stableId);
  });
  await patchSelectedSegment({ rejected_frames: [...rejected].sort((left, right) => left.localeCompare(right)) });
  renderFrameStrip();
}

async function cancelTask() {
  try {
    const payload = await api(API.cancel, { method: "POST" });
    state.task = normaliseTask(payload.task || payload);
    renderTask();
    renderActionAvailability();
  } catch (error) { showError(error); }
}

async function processCurrentSegment(fromStage, path) {
  try {
    await flushRecipeSave();
    const segmentIds = currentSegmentIdsForAction();
    if (!segmentIds.length) return;
    await startOperation(path, { segment_ids: segmentIds, from_stage: fromStage });
  } catch (error) { showError(error); }
}

async function exportVideo() {
  const segmentIds = currentSegmentIdsForAction();
  if (!segmentIds.length) return;
  openExportDialog();
  try {
    await flushRecipeSave();
    await startOperation(API.export, {
      segment_ids: segmentIds,
      fps: Number(byId("export-fps").value),
      resolution: byId("export-resolution").value,
      codec: byId("export-codec").value,
      crf: Number(byId("export-crf").value)
    }, { showError: false });
  } catch (error) {
    updateExportDialog({ kind: "export", status: "failed", error: error.message });
  }
}

function openArchiveDialog() {
  const segment = selectedSegment();
  if (!segment) return;
  byId("archive-dialog-message").textContent = t("dialog.archive.body", {
    name: segment.name
  });
  byId("archive-dialog").showModal();
}

async function archiveProject() {
  byId("archive-dialog").close();
  try {
    await flushRecipeSave();
    await startOperation(API.archive, {
      confirm_archive: true,
      preserve_source: true,
      segment_ids: currentSegmentIdsForAction()
    });
  } catch (error) { showError(error); }
}

async function clearProject() {
  byId("clear-project-dialog").close();
  try {
    await api(API.project, { method: "DELETE", body: { confirm: true } });
    state.project = null;
    state.selectedSegmentId = null;
    state.pendingSourcePath = "";
    state.thumbnails = [];
    state.thumbnailTotal = 0;
    state.selectedSegmentIds.clear();
    state.segmentMultiSelect = false;
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

async function loadLogs() {
  try {
    const payload = await api(API.logs);
    state.logs = Array.isArray(payload.logs) ? payload.logs : [];
    renderLogs();
    renderActionAvailability();
  } catch (error) { showError(error); }
}

function renderLogs() {
  const output = byId("task-log");
  output.textContent = state.logs.length
    ? state.logs.map((entry) => {
        const timestamp = entry.timestamp ? `[${entry.timestamp}]` : "";
        const level = entry.level ? `[${entry.level}]` : "[INFO]";
        const kind = entry.kind ? `[${entry.kind}]` : "[system]";
        return `${timestamp} ${level} ${kind} ${entry.message || entry}`.trim();
      }).join("\n")
    : t("task.no_logs");
  output.scrollTop = output.scrollHeight;
}

async function clearLogs() {
  try {
    await api(API.logs, { method: "DELETE" });
    state.logs = [];
    renderLogs();
    renderActionAvailability();
  } catch (error) { showError(error); }
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

function colorPresetLabel(preset) {
  const builtinKey = preset?.builtin && ["natural", "clear", "punchy", "custom"].includes(preset.id)
    ? `recipe.${preset.id}`
    : null;
  return builtinKey ? t(builtinKey) : preset?.name || t("presets.unnamed");
}

function populateColorPresetSelects() {
  const segmentValue = recipeOf(selectedSegment()).name || byId("recipe-select")?.value || "natural";
  const settingsValue = state.settings.processing?.default_recipe || byId("settings-default-recipe")?.value || "natural";
  [["recipe-select", segmentValue], ["settings-default-recipe", settingsValue]].forEach(([id, selected]) => {
    const select = byId(id);
    if (!select) return;
    select.replaceChildren();
    state.colorPresets.forEach((preset) => {
      const option = document.createElement("option");
      option.value = preset.id;
      option.textContent = colorPresetLabel(preset);
      select.append(option);
    });
    if ([...select.options].some((option) => option.value === selected)) select.value = selected;
  });
}

async function loadColorPresets(preferredId = state.selectedColorPresetId) {
  const payload = await api(API.colorPresets);
  state.colorPresets = Array.isArray(payload.presets) ? payload.presets : [];
  const available = new Set(state.colorPresets.map((preset) => preset.id));
  state.selectedColorPresetId = available.has(preferredId)
    ? preferredId
    : available.has(payload.default) ? payload.default : state.colorPresets[0]?.id || null;
  populateColorPresetSelects();
  renderColorPresets();
  if (selectedSegment()) renderSegmentDetail();
}

function renderColorPresets() {
  const list = byId("color-preset-list");
  if (!list) return;
  list.replaceChildren();
  state.colorPresets.forEach((preset) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "color-preset-item";
    button.dataset.colorPresetId = preset.id;
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", String(preset.id === state.selectedColorPresetId));
    const heading = document.createElement("span");
    heading.className = "color-preset-item-heading";
    const name = document.createElement("strong");
    name.textContent = colorPresetLabel(preset);
    const kind = document.createElement("span");
    kind.textContent = preset.builtin ? t("presets.builtin") : t("presets.user");
    const values = document.createElement("span");
    values.className = "muted";
    values.textContent = `S ${preset.sat} · C ${preset.con} · P ${preset.pivot}`;
    heading.append(name, kind);
    button.append(heading, values);
    list.append(button);
  });
  fillColorPresetForm(state.colorPresets.find((preset) => preset.id === state.selectedColorPresetId) || null);
}

function fillColorPresetForm(preset) {
  byId("color-preset-id").value = preset?.id || "";
  byId("color-preset-name").value = preset?.name || "";
  byId("color-preset-sat").value = preset?.sat ?? 1;
  byId("color-preset-con").value = preset?.con ?? 1;
  byId("color-preset-pivot").value = preset?.pivot ?? 118;
  byId("color-preset-kind").textContent = preset
    ? preset.builtin ? t("presets.builtin") : t("presets.user")
    : t("presets.new_badge");
  byId("delete-color-preset-btn").disabled = !preset || preset.builtin;
}

function selectColorPreset(presetId) {
  state.selectedColorPresetId = presetId;
  renderColorPresets();
}

function newColorPreset() {
  state.selectedColorPresetId = null;
  renderColorPresets();
  byId("color-preset-name").focus();
}

async function saveColorPreset(event) {
  event.preventDefault();
  const presetId = byId("color-preset-id").value;
  const body = {
    name: byId("color-preset-name").value.trim(),
    sat: Number(byId("color-preset-sat").value),
    con: Number(byId("color-preset-con").value),
    pivot: Number(byId("color-preset-pivot").value)
  };
  try {
    const payload = await api(presetId ? API.colorPreset(presetId) : API.colorPresets, {
      method: presetId ? "PUT" : "POST",
      body
    });
    await loadColorPresets(payload.preset?.id || presetId);
    byId("color-preset-save-status").textContent = t("presets.saved");
  } catch (error) { showError(error); }
}

async function deleteColorPreset() {
  const presetId = byId("color-preset-id").value;
  const preset = state.colorPresets.find((item) => item.id === presetId);
  if (!preset || preset.builtin || !window.confirm(t("presets.delete_confirm", { name: colorPresetLabel(preset) }))) return;
  try {
    await api(API.colorPreset(presetId), { method: "DELETE" });
    await loadColorPresets();
    byId("color-preset-save-status").textContent = t("presets.deleted");
  } catch (error) { showError(error); }
}

async function loadSettings() {
  try {
    const payload = await api(API.settings);
    state.settings = payload.settings || payload.config || payload;
    setSettingsForm(state.settings);
  } catch (error) { showError(error); }
}

function setSettingsForm(settings) {
  populateColorPresetSelects();
  byId("settings-workspace-dir").value = settings.workspace_dir || "";
  byId("settings-output-dir").value = settings.output_dir || "";
  byId("settings-archive-dir").value = settings.archive_dir || "";
  byId("settings-default-recipe").value = settings.processing?.default_recipe || "natural";
  byId("settings-gap-seconds").value = settings.scan?.gap_seconds ?? 120;
  byId("settings-log-level").value = settings.logging?.level || "INFO";
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
    logging: { level: byId("settings-log-level").value },
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
  byId("dismiss-error-btn").addEventListener("click", clearError);
  byId("pick-source-btn").addEventListener("click", pickDirectory);
  byId("scan-btn").addEventListener("click", scanSource);
  byId("clear-project-btn").addEventListener("click", () => byId("clear-project-dialog").showModal());
  byId("clear-confirm-btn").addEventListener("click", clearProject);
  byId("segment-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-segment-id]");
    if (!button) return;
    if (state.segmentMultiSelect) toggleSegmentSelection(button.dataset.segmentId);
    else selectSegment(button.dataset.segmentId);
  });
  byId("segment-name").addEventListener("change", (event) => patchSelectedSegment({ name: event.target.value.trim() }));
  byId("split-frame").addEventListener("input", renderActionAvailability);
  byId("split-btn").addEventListener("click", splitSegment);
  byId("segment-multi-select-btn").addEventListener("click", toggleSegmentMultiSelect);
  byId("merge-btn").addEventListener("click", mergeSelectedSegments);
  byId("move-up-btn").addEventListener("click", () => moveSegment(-1));
  byId("move-down-btn").addEventListener("click", () => moveSegment(1));
  ["recipe-select", "recipe-strength", "golden-strength", "deflicker-enabled", "deflicker-window", "gain-limit", "golden-start", "golden-end"].forEach((id) => byId(id).addEventListener("input", scheduleRecipeSave));
  byId("frame-strip").addEventListener("click", (event) => {
    const button = event.target.closest("[data-frame-index]");
    if (button) selectFrame(Number(button.dataset.frameIndex), event.shiftKey);
  });
  byId("frame-multi-select-btn").addEventListener("click", toggleFrameMultiSelect);
  byId("frame-page-prev").addEventListener("click", () => loadThumbnailPage(state.thumbnailPage - 1));
  byId("frame-page-next").addEventListener("click", () => loadThumbnailPage(state.thumbnailPage + 1));
  byId("chart-type-select").addEventListener("change", drawChart);
  byId("chart-type-select").addEventListener("click", (event) => event.stopPropagation());
  document.querySelector(".frame-summary").addEventListener("click", (event) => {
    if (event.target.closest("button")) {
      event.preventDefault();
      event.stopPropagation();
    }
  });
  byId("bad-frame-btn").addEventListener("click", () => updateRejected(true));
  byId("unmark-bad-frame-btn").addEventListener("click", () => updateRejected(false));
  byId("process-current-btn").addEventListener("click", () => processCurrentSegment("analyze", API.process));
  byId("cancel-btn").addEventListener("click", cancelTask);
  byId("export-btn").addEventListener("click", exportVideo);
  byId("preview-video-btn").addEventListener("click", previewCurrentVideo);
  byId("archive-btn").addEventListener("click", openArchiveDialog);
  byId("archive-confirm-btn").addEventListener("click", archiveProject);
  byId("export-progress-cancel-btn").addEventListener("click", cancelTask);
  byId("export-progress-close-btn").addEventListener("click", closeExportDialog);
  byId("export-progress-preview-btn").addEventListener("click", () => {
    closeExportDialog();
    previewCurrentVideo();
  });
  byId("result-history-btn").addEventListener("click", () => {
    byId("operation-result-dialog").close();
    switchView("history");
  });
  byId("refresh-history-btn").addEventListener("click", loadHistory);
  byId("clear-logs-btn").addEventListener("click", clearLogs);
  byId("color-preset-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-color-preset-id]");
    if (button) selectColorPreset(button.dataset.colorPresetId);
  });
  byId("new-color-preset-btn").addEventListener("click", newColorPreset);
  byId("color-preset-form").addEventListener("submit", saveColorPreset);
  byId("delete-color-preset-btn").addEventListener("click", deleteColorPreset);
  byId("settings-form").addEventListener("submit", saveSettings);
  document.querySelectorAll("[data-settings-directory]").forEach((button) => button.addEventListener("click", () => pickSettingsDirectory(button.dataset.settingsDirectory)));
  document.querySelectorAll("[data-theme-choice]").forEach((button) => button.addEventListener("click", () => applyTheme(button.dataset.themeChoice)));
  document.querySelectorAll("[data-language-choice]").forEach((button) => button.addEventListener("click", () => applyLanguage(button.dataset.languageChoice)));
  byId("directory-browser-breadcrumb").addEventListener("click", (event) => {
    const button = event.target.closest("[data-directory-path]");
    if (button) openDirectoryBrowser(button.dataset.directoryPath);
  });
  byId("directory-browser-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-directory-path]");
    if (button) openDirectoryBrowser(button.dataset.directoryPath);
  });
  byId("directory-browser-choose").addEventListener("click", chooseBrowsedDirectory);
  byId("directory-browser-cancel").addEventListener("click", () => byId("directory-browser-dialog").close());
  byId("directory-browser-close").addEventListener("click", () => byId("directory-browser-dialog").close());
  window.addEventListener("resize", drawChart);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (preferences.theme === "system") drawChart();
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  syncPreferenceControls();
  translateDocument();
  bindEvents();
  try { await Promise.all([loadCapabilities(), loadColorPresets()]); } catch (error) { showError(error); }
  renderFrameStrip();
  drawChart();
  refreshState();
});

window.SolisAppTest = { chooseDirectoryMode, containerSourcePath };
