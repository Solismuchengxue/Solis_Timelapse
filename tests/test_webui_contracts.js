"use strict";

const fs = require("fs");
const path = require("path");
const nodeAssert = require("assert/strict");

const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "webui", "index.html"), "utf8");
const js = fs.readFileSync(path.join(root, "webui", "app.js"), "utf8");
const prefs = require(path.join(root, "webui", "ui_prefs.js"));

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
assert(ids.length === new Set(ids).size, "HTML contains duplicate IDs");
assert(!/\son[a-z]+\s*=/i.test(html), "Inline event handlers are not allowed");

nodeAssert.deepStrictEqual(prefs.SUPPORTED_THEMES, ["light", "dark", "system"]);
nodeAssert.deepStrictEqual(prefs.SUPPORTED_LANGUAGES, ["zh-CN", "en"]);
nodeAssert.strictEqual(prefs.normalizeTheme("broken"), "system");
nodeAssert.strictEqual(prefs.normalizeLanguage("broken", "zh-Hans-CN"), "zh-CN");
nodeAssert.strictEqual(prefs.normalizeLanguage(null, "en-US"), "en");
nodeAssert.strictEqual(prefs.t("en", "nav.workbench"), "Workbench");
let missingWarning = "";
const originalWarn = console.warn;
console.warn = (message) => { missingWarning = message; };
nodeAssert.strictEqual(prefs.t("en", "missing.key"), "missing.key");
console.warn = originalWarn;
nodeAssert.strictEqual(missingWarning, "Missing translation: missing.key");
nodeAssert.deepStrictEqual(
  Object.keys(prefs.TRANSLATIONS["zh-CN"]).sort(),
  Object.keys(prefs.TRANSLATIONS.en).sort(),
  "Chinese and English translation keys must match",
);

for (const id of [
  "pick-source-btn", "scan-btn", "segment-list", "segment-preview",
  "recipe-select", "frame-strip", "process-btn", "cancel-btn",
  "task-progress", "task-log", "export-btn", "archive-dialog",
  "history-list", "settings-form"
]) {
  assert(ids.includes(id), `Missing required element #${id}`);
  assert(js.includes(`byId("${id}")`) || js.includes(`#${id}`), `JavaScript does not bind #${id}`);
}

for (const route of [
  "/api/state", "/api/capabilities", "/api/directories", "/api/pick-directory", "/api/project/scan",
  "/api/segments/split", "/api/segments/merge", "/api/segments/reorder",
  "/api/process", "/api/process/retry", "/api/tasks/cancel",
  "/api/tasks/current", "/api/export", "/api/archive", "/api/history",
  "/api/settings"
]) {
  assert(js.includes(route), `Missing API route ${route}`);
}

assert(js.includes("addEventListener"), "Events must use addEventListener");
assert(js.includes("setInterval(pollTask, 1000)"), "Active task polling must run every second");
assert(js.includes("preserve_source: true"), "Archive request must explicitly preserve source files");
assert(html.includes('role="tablist"'), "Tab list semantics are required");
assert((html.match(/role="tab"/g) || []).length === 3, "All three tabs need tab roles");
assert(html.includes('aria-valuenow="0"'), "Progress needs an ARIA current value");
assert(js.includes('setAttribute("aria-valuenow", String(percent))'), "Progress ARIA value must update");

for (const functionName of ["processSegments", "exportVideo"]) {
  const start = js.indexOf(`async function ${functionName}`);
  const end = js.indexOf("\n}", start);
  const body = js.slice(start, end);
  assert(body.indexOf("await flushRecipeSave()") >= 0, `${functionName} must flush the recipe`);
  assert(body.indexOf("await flushRecipeSave()") < body.indexOf("await startOperation("), `${functionName} flush must precede operation start`);
}

assert(js.includes("segment?.source_files?.[index]"), "Rejected frames must use source file identifiers");
assert(js.includes("rejected.add(stableId)"), "Rejected frame payload must use stable IDs");
assert(!js.includes("rejected.add(index)"), "Rejected frame payload cannot use array indices");
assert(js.includes("historySortValue(right) - historySortValue(left)"), "History needs descending client sort");
assert(js.includes("recipeSummary(entry)"), "History needs recipe summaries");
assert(js.includes("async function loadHistoryDetail(summary)"), "History details need a dedicated merge path");
assert(js.includes("summary.previews || summary.preview_videos"), "History merge must retain summary preview URLs");
assert(js.includes("summary.outputs || summary.final_videos"), "History merge must retain summary output URLs");
assert(js.includes("manifest.previews || manifest.preview_videos"), "History merge must include manifest preview URLs");
assert(js.includes("manifest.outputs || manifest.final_videos"), "History merge must include manifest output URLs");
assert(js.includes("segmentCounts.reduce((total, count) => total + count, 0)"), "JPEG count must sum segment manifest counts");
assert(js.includes("entry.jpeg_count ?? entry.frame_count ?? 0"), "JPEG count needs legacy top-level fallback");
assert(html.includes('id="settings-save-status"'), "Settings need a live save status");
assert(js.includes("payload.restart_required"), "Settings must inspect restart_required");
assert(js.includes('t("settings.saved_restart")'), "Restart-required save notice must be translated");
assert(html.includes('id="settings-workspace-dir" name="workspace_dir" type="text" readonly'), "Workspace setting must be picker-only");
for (const token of ["theme-select", "language-select", "solis:themechange", "solis:languagechange"]) {
  assert(html.includes(token) || js.includes(token), `Missing UI preference wiring: ${token}`);
}
for (const id of ["directory-browser-dialog", "directory-browser-breadcrumb", "directory-browser-list", "directory-browser-choose"]) {
  assert(ids.includes(id), `Missing Docker directory browser #${id}`);
}
assert(js.includes("function chooseDirectoryMode(capabilities)"), "Picker mode must be capability driven");
assert(js.includes("state.capabilities.native_directory_picker"), "Native picker capability must be checked");
assert(!js.includes("正在读取历史..."), "Dynamic copy must come from i18n");
console.log("WebUI static contracts passed");
