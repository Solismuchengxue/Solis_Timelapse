# Solis_Timelapse UI, i18n, Docker, and Repository Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the Studio Console WebUI, light/dark/system themes, Chinese/English localization, and a safe fnOS Docker deployment, then move the verified repository to `F:\01_Project\Solis_Timelapse`.

**Architecture:** Keep Flask and the existing processing modules unchanged. Add one dependency-free browser module for theme and translation state, one Python module for local/container runtime policy, and narrowly extend the existing API for capabilities, health, and read-only input-directory browsing. Docker uses explicit bind mounts for all growing data and refuses to start when persistence paths are unavailable.

**Tech Stack:** Python 3.12, Flask 3.1, vanilla HTML/CSS/JavaScript, Python `unittest`, Node.js contract tests, Docker Compose.

## Global Constraints

- Product brand is exactly `Solis_Timelapse`; Compose service, container, and default local image are exactly `solis_timelapse`.
- Preserve all existing scan, segment, processing, export, archive, hash-verification, and source-read-only behavior.
- Do not add frontend or Python production dependencies.
- Supported themes are exactly `light`, `dark`, and `system`; default and invalid-value fallback are `system`.
- Supported languages are exactly `zh-CN` and `en`; missing keys fall back to Chinese.
- Local Windows mode binds `127.0.0.1:9501` and retains the native directory picker.
- Container mode binds `0.0.0.0:9501`; directory browsing is restricted to `/media/input`.
- Container persistence paths are `/media/workspace`, `/media/output`, `/media/archive`, and `/data/config`; source is `/media/input:ro`.
- README remains user-facing; ignored `DEVLOG.md` remains local-only; `.superpowers/` must never be committed.
- Repository relocation is the final operation, after code, tests, Docker, docs, and commits are complete.

---

### Task 1: Add Tested Theme and Translation Primitives

**Files:**
- Create: `webui/ui_prefs.js`
- Modify: `webui/index.html`
- Modify: `tests/test_webui_contracts.js`
- Modify: `tests/test_webui_contracts.py`

**Interfaces:**
- Produces: `window.SolisUI` and CommonJS exports containing `SUPPORTED_THEMES`, `SUPPORTED_LANGUAGES`, `TRANSLATIONS`, `normalizeTheme(value)`, `normalizeLanguage(value, browserLanguage)`, `t(language, key, params)`, `loadPreferences(storage, browserLanguage)`, and `applyPreferences(document, preferences)`.
- Produces: DOM events `solis:themechange` and `solis:languagechange`, each with `event.detail.value`.
- Consumes: browser `localStorage`, `navigator.language`, and `matchMedia('(prefers-color-scheme: dark)')`.

- [ ] **Step 1: Add failing JavaScript contract tests**

Append tests that load `webui/ui_prefs.js` with `require()` and assert the exact behavior:

```javascript
const prefs = require("../webui/ui_prefs.js");

assert.deepStrictEqual(prefs.SUPPORTED_THEMES, ["light", "dark", "system"]);
assert.deepStrictEqual(prefs.SUPPORTED_LANGUAGES, ["zh-CN", "en"]);
assert.strictEqual(prefs.normalizeTheme("broken"), "system");
assert.strictEqual(prefs.normalizeLanguage("broken", "zh-Hans-CN"), "zh-CN");
assert.strictEqual(prefs.normalizeLanguage(null, "en-US"), "en");
assert.strictEqual(prefs.t("en", "nav.workbench"), "Workbench");
assert.strictEqual(prefs.t("en", "missing.key"), "missing.key");
assert.deepStrictEqual(
  Object.keys(prefs.TRANSLATIONS["zh-CN"]).sort(),
  Object.keys(prefs.TRANSLATIONS.en).sort(),
  "Chinese and English translation keys must match",
);
```

Update the Python static contract to require local scripts only and the new script before `app.js`:

```python
self.assertIn('src="/ui_prefs.js"', self.html)
self.assertLess(self.html.index('/ui_prefs.js'), self.html.index('/app.js'))
self.assertNotRegex(self.html, r'https?://')
```

- [ ] **Step 2: Run the focused tests and confirm the expected failure**

Run:

```powershell
node tests\test_webui_contracts.js
.venv\Scripts\python.exe -m unittest tests.test_webui_contracts -v
```

Expected: JavaScript fails because `webui/ui_prefs.js` does not exist; Python fails because `index.html` does not load it.

- [ ] **Step 3: Implement the preference module and early theme bootstrap**

Create a UMD-style module with flat dictionaries and parameter replacement:

```javascript
(function initSolisUI(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.SolisUI = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildSolisUI() {
  const SUPPORTED_THEMES = ["light", "dark", "system"];
  const SUPPORTED_LANGUAGES = ["zh-CN", "en"];
  const TRANSLATIONS = {
    "zh-CN": {
      "app.name": "Solis_Timelapse",
      "nav.workbench": "工作台",
      "nav.history": "历史",
      "nav.settings": "设置",
      "theme.light": "白天",
      "theme.dark": "夜间",
      "theme.system": "跟随系统",
      "language.zh-CN": "中文",
      "language.en": "English"
    },
    en: {
      "app.name": "Solis_Timelapse",
      "nav.workbench": "Workbench",
      "nav.history": "History",
      "nav.settings": "Settings",
      "theme.light": "Light",
      "theme.dark": "Dark",
      "theme.system": "System",
      "language.zh-CN": "中文",
      "language.en": "English"
    }
  };

  function normalizeTheme(value) {
    return SUPPORTED_THEMES.includes(value) ? value : "system";
  }

  function normalizeLanguage(value, browserLanguage = "en") {
    if (SUPPORTED_LANGUAGES.includes(value)) return value;
    return String(browserLanguage).toLowerCase().startsWith("zh") ? "zh-CN" : "en";
  }

  function t(language, key, params = {}) {
    const template = TRANSLATIONS[language]?.[key] ?? TRANSLATIONS["zh-CN"][key];
    if (template === undefined) {
      if (typeof console !== "undefined") console.warn(`Missing translation: ${key}`);
      return key;
    }
    return template.replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? `{${name}}`));
  }

  function loadPreferences(storage, browserLanguage) {
    return {
      theme: normalizeTheme(storage?.getItem("solis.theme")),
      language: normalizeLanguage(storage?.getItem("solis.language"), browserLanguage),
    };
  }

  function applyPreferences(documentRef, preferences) {
    documentRef.documentElement.dataset.theme = normalizeTheme(preferences.theme);
    documentRef.documentElement.lang = normalizeLanguage(preferences.language, preferences.language);
  }

  return { SUPPORTED_THEMES, SUPPORTED_LANGUAGES, TRANSLATIONS, normalizeTheme, normalizeLanguage, t, loadPreferences, applyPreferences };
});
```

Expand both dictionaries during this task to cover every static and dynamic string currently found in `index.html` and `app.js`, using namespaced keys such as `status.running`, `error.invalid_media_path`, `history.loading`, `dialog.archive.title`, and `aria.task_progress`. Load `/ui_prefs.js` synchronously in `<head>` and immediately apply stored preferences before CSS is painted; continue loading `/app.js` with `defer`.

- [ ] **Step 4: Run focused tests and key-parity scan**

Run:

```powershell
node tests\test_webui_contracts.js
.venv\Scripts\python.exe -m unittest tests.test_webui_contracts -v
rg -n "Sony timelapse|sony-timelapse|sony_timelapse" webui tests
```

Expected: both test commands pass; the brand scan returns no matches in `webui` or frontend tests.

- [ ] **Step 5: Commit the preference primitives**

```powershell
git add webui/ui_prefs.js webui/index.html tests/test_webui_contracts.js tests/test_webui_contracts.py
git commit -m "添加主题与中英文界面基础"
```

---

### Task 2: Rebuild the WebUI as the Studio Console

**Files:**
- Modify: `webui/index.html`
- Modify: `webui/styles.css`
- Modify: `webui/app.js`
- Modify: `tests/test_webui_contracts.py`
- Modify: `tests/test_webui_contracts.js`

**Interfaces:**
- Consumes: all existing stable element IDs used by `app.js`; `window.SolisUI.t()` and preference events from Task 1.
- Produces: theme selector `#theme-select`, language selector `#language-select`, and stable `data-i18n`, `data-i18n-title`, `data-i18n-aria-label`, and `data-i18n-placeholder` bindings.
- Preserves: all current API URLs, task polling, recipe autosave, segment editing, frame rejection, export, archive, history, and settings behavior.

- [ ] **Step 1: Strengthen layout and localization contract tests**

Add assertions for the chosen information architecture and responsive contract:

```python
for required_id in ("theme-select", "language-select", "sidebar-nav", "studio-main", "task-bar"):
    self.assertIn(f'id="{required_id}"', self.html)
self.assertIn('data-theme="system"', self.html)
self.assertIn('@media (max-width: 720px)', self.css)
self.assertIn('grid-template-columns', self.css)
self.assertIn('overflow-x: hidden', self.css)
self.assertNotIn('linear-gradient(', self.css)
self.assertNotIn('radial-gradient(', self.css)
```

Add JavaScript assertions that all user-visible runtime messages use `t(` or a translation map and that both preference selectors are wired:

```javascript
for (const token of ["theme-select", "language-select", "solis:themechange", "solis:languagechange"]) {
  assert(js.includes(token), `Missing UI preference wiring: ${token}`);
}
assert(!js.includes("正在读取历史..."), "Dynamic copy must come from i18n");
```

- [ ] **Step 2: Run the contract tests and confirm they fail on the old layout**

Run:

```powershell
node tests\test_webui_contracts.js
.venv\Scripts\python.exe -m unittest tests.test_webui_contracts -v
```

Expected: failures mention missing selectors, Studio Console regions, and untranslated dynamic copy.

- [ ] **Step 3: Restructure HTML without changing behavior IDs**

Use this top-level structure while retaining every existing form/control ID inside its corresponding region:

```html
<div id="app" class="studio-shell">
  <header class="studio-header">...</header>
  <aside id="sidebar-nav" class="studio-sidebar">...</aside>
  <main id="studio-main" class="studio-main">...</main>
  <footer id="task-bar" class="task-bar">...</footer>
</div>
```

Move the three primary navigation buttons to the sidebar; keep segments directly below them. Put source controls, representative image, brightness curve, recipe controls, advanced controls, frame strip, and export controls in the center in that order. Put theme and language `<select>` controls in the header. Mark all fixed text with the relevant `data-i18n*` attribute and retain current ARIA relationships.

- [ ] **Step 4: Replace CSS with theme tokens and responsive Studio Console rules**

Define semantic tokens once and override them by theme:

```css
:root,
:root[data-theme="light"] {
  color-scheme: light;
  --bg: #f3f6f6;
  --surface: #ffffff;
  --surface-subtle: #e9eeee;
  --text: #172322;
  --muted: #5e6d6b;
  --border: #cbd5d3;
  --accent: #087f73;
  --accent-hover: #06695f;
  --warm: #b86612;
  --danger: #b42318;
  --focus: #0b8f82;
}

:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #171b1b;
  --surface: #202626;
  --surface-subtle: #29302f;
  --text: #edf3f2;
  --muted: #a9b7b5;
  --border: #3f4a48;
  --accent: #44b8aa;
  --accent-hover: #67c9bd;
  --warm: #e2a252;
  --danger: #ff8b82;
  --focus: #62d2c4;
}

@media (prefers-color-scheme: dark) {
  :root[data-theme="system"] {
    color-scheme: dark;
    --bg: #171b1b;
    --surface: #202626;
    --surface-subtle: #29302f;
    --text: #edf3f2;
    --muted: #a9b7b5;
    --border: #3f4a48;
    --accent: #44b8aa;
    --accent-hover: #67c9bd;
    --warm: #e2a252;
    --danger: #ff8b82;
    --focus: #62d2c4;
  }
}
```

Use a desktop grid with `220px minmax(0, 1fr)`, a fixed header and bottom task bar, 8px-or-smaller corners, stable control dimensions, and no page-level horizontal scroll. At `1024px`, reduce spacing and preview columns; at `720px`, use one column, make the sidebar an unframed horizontal navigation band, allow command rows to wrap, and add bottom padding equal to the task bar height.

- [ ] **Step 5: Translate static and dynamic UI and redraw theme-sensitive canvas content**

In `app.js`, centralize translation and preference application:

```javascript
const ui = window.SolisUI;
let preferences = ui.loadPreferences(localStorage, navigator.language);

function translateDocument() {
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = ui.t(preferences.language, node.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-title]").forEach((node) => {
    node.title = ui.t(preferences.language, node.dataset.i18nTitle);
  });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((node) => {
    node.setAttribute("aria-label", ui.t(preferences.language, node.dataset.i18nAriaLabel));
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
    node.placeholder = ui.t(preferences.language, node.dataset.i18nPlaceholder);
  });
  document.title = ui.t(preferences.language, "app.title");
}
```

Replace all dynamic Chinese literals with stable keys, including status names, task log labels, errors, history summaries, confirmation text, page counts, frame tooltips, and restart-required notices. Map API `code` values before using backend `error` text. On theme changes, save `solis.theme`, apply the theme, update browser `color-scheme`, and redraw the brightness canvas using computed CSS token colors. On language changes, save `solis.language`, set `<html lang>`, translate the document, and re-render current segment/history/task state.

- [ ] **Step 6: Verify frontend contracts and existing API behavior**

Run:

```powershell
node tests\test_webui_contracts.js
.venv\Scripts\python.exe -m unittest tests.test_webui_contracts tests.test_webui_api -v
```

Expected: all tests pass and no existing API contract changes.

- [ ] **Step 7: Commit the Studio Console UI**

```powershell
git add webui/index.html webui/styles.css webui/app.js tests/test_webui_contracts.py tests/test_webui_contracts.js
git commit -m "重构 Studio Console 双语主题界面"
```

---

### Task 3: Add Local and Container Runtime Policy

**Files:**
- Create: `src/runtime_env.py`
- Create: `tests/test_runtime_env.py`
- Modify: `src/config_io.py`
- Modify: `tests/test_config_io.py`
- Modify: `webui/server.py`
- Modify: `tests/test_webui_api.py`

**Interfaces:**
- Produces: `RuntimeEnvironment(mode, input_root, workspace_dir, output_dir, archive_dir, local_config_path, host, native_picker)` dataclass.
- Produces: `load_runtime_environment(environ, repository_root) -> RuntimeEnvironment`.
- Produces: `validate_runtime_environment(runtime) -> list[str]`, returning exact human-readable path failures.
- Produces API: `GET /api/capabilities`, `GET /api/health`, and `GET /api/directories?path=<relative>`.
- Preserves: `create_app(overrides=None)` testing interface; tests may inject `runtime_environment` in overrides.

- [ ] **Step 1: Write failing runtime and API tests**

Cover local defaults, container constants, required writability, capabilities, health, and directory confinement:

```python
def test_container_environment_uses_only_persistent_mounts(self):
    runtime = load_runtime_environment({"SOLIS_CONTAINER": "1"}, self.root)
    self.assertEqual(runtime.input_root, Path("/media/input"))
    self.assertEqual(runtime.workspace_dir, Path("/media/workspace"))
    self.assertEqual(runtime.output_dir, Path("/media/output"))
    self.assertEqual(runtime.archive_dir, Path("/media/archive"))
    self.assertEqual(runtime.local_config_path, Path("/data/config/local.yaml"))
    self.assertEqual(runtime.host, "0.0.0.0")
    self.assertFalse(runtime.native_picker)
```

```python
def test_directory_browser_rejects_escape_and_windows_paths(self):
    for value in ("../", "/etc", r"C:\\Users"):
        response = self.client.get("/api/directories", query_string={"path": value})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["code"], "invalid_media_path")
```

Create a temporary symlink outside the input root when the platform permits it and assert the same rejection. Assert successful listings contain only `name` and POSIX `path`, not absolute host/container paths.

- [ ] **Step 2: Run focused tests and confirm missing-module/routes failures**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_runtime_env tests.test_config_io tests.test_webui_api -v
```

Expected: import and route failures because runtime policy is not implemented.

- [ ] **Step 3: Implement the runtime dataclass and validation**

Use only the standard library:

```python
@dataclass(frozen=True)
class RuntimeEnvironment:
    mode: str
    input_root: Path | None
    workspace_dir: Path
    output_dir: Path
    archive_dir: Path
    local_config_path: Path
    host: str
    native_picker: bool

def load_runtime_environment(environ: Mapping[str, str], repository_root: Path) -> RuntimeEnvironment:
    if environ.get("SOLIS_CONTAINER") == "1":
        return RuntimeEnvironment(
            mode="container",
            input_root=Path("/media/input"),
            workspace_dir=Path("/media/workspace"),
            output_dir=Path("/media/output"),
            archive_dir=Path("/media/archive"),
            local_config_path=Path("/data/config/local.yaml"),
            host="0.0.0.0",
            native_picker=False,
        )
    return RuntimeEnvironment(
        mode="local",
        input_root=None,
        workspace_dir=repository_root / "workspace",
        output_dir=repository_root / "output",
        archive_dir=repository_root / "archive",
        local_config_path=repository_root / "config" / "local.yaml",
        host="127.0.0.1",
        native_picker=True,
    )
```

Validation must check input readability and directory writability without creating fallback paths. For writable mounts, create and remove a uniquely named zero-byte probe inside each directory; return one error per failing path.

- [ ] **Step 4: Wire runtime roots into config loading and Flask creation**

In `create_app`, load the runtime policy before config, use its `local_config_path`, and use runtime directories as container-mode effective roots. Keep explicit test overrides highest priority. Add capabilities and health responses:

```json
{"mode":"container","native_directory_picker":false,"directory_browser":true}
```

```json
{"status":"ok"}
```

Health returns HTTP 503 and `{"status":"error","code":"runtime_unavailable","issues":[...]}` when validation fails. In local mode, keep `/api/pick-directory`; in container mode return `native_picker_unavailable` with HTTP 409.

- [ ] **Step 5: Implement the confined directory listing route**

Reject empty-root misconfiguration, NUL, drive-letter/UNC paths, absolute paths, and traversal. Resolve `input_root / relative`, require `candidate.relative_to(input_root.resolve())`, reject symlink escape after resolution, require a directory, and return sorted child directories only:

```json
{"path":"trip/day1","parent":"trip","directories":[{"name":"A","path":"trip/day1/A"}]}
```

Use the existing `_error()` envelope with code `invalid_media_path` for every invalid or escaped path.

- [ ] **Step 6: Run focused and adjacent backend tests**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_runtime_env tests.test_config_io tests.test_webui_api tests.test_media_routes -v
```

Expected: all tests pass; existing media whitelist and API tests remain green.

- [ ] **Step 7: Commit runtime policy and APIs**

```powershell
git add src/runtime_env.py src/config_io.py webui/server.py tests/test_runtime_env.py tests/test_config_io.py tests/test_webui_api.py
git commit -m "增加容器运行模式与安全目录浏览"
```

---

### Task 4: Add the Docker Input Directory Browser to the WebUI

**Files:**
- Modify: `webui/index.html`
- Modify: `webui/app.js`
- Modify: `webui/styles.css`
- Modify: `webui/ui_prefs.js`
- Modify: `tests/test_webui_contracts.js`
- Modify: `tests/test_webui_api.py`

**Interfaces:**
- Consumes: `GET /api/capabilities` and `GET /api/directories?path=` from Task 3.
- Produces: modal `#directory-browser-dialog`, breadcrumb `#directory-browser-breadcrumb`, list `#directory-browser-list`, choose action `#directory-browser-choose`, and selected source path `/media/input/<relative>` sent to the unchanged scan API.
- Preserves: native Windows picker and settings-directory pickers in local mode.

- [ ] **Step 1: Add failing browser mode contract tests**

Assert `app.js` fetches capabilities before selecting a picker and HTML contains an accessible dialog:

```javascript
for (const token of ["/api/capabilities", "/api/directories", "directory-browser-dialog"]) {
  assert(js.includes(token) || html.includes(token), `Missing directory browser token: ${token}`);
}
```

Assert container mode never calls `/api/pick-directory` and local mode still does by extracting the decision function into `chooseDirectoryMode(capabilities)` and exporting it under `window.SolisAppTest` in test contexts.

- [ ] **Step 2: Run frontend tests and confirm the browser controls are missing**

Run:

```powershell
node tests\test_webui_contracts.js
.venv\Scripts\python.exe -m unittest tests.test_webui_contracts -v
```

Expected: failures mention missing capabilities fetch and directory dialog.

- [ ] **Step 3: Implement the modal and capability-driven picker**

On bootstrap, fetch capabilities once. The source button behavior is:

```javascript
async function pickSourceDirectory() {
  if (state.capabilities.native_directory_picker) {
    const result = await api("/api/pick-directory", { method: "POST", body: { kind: "source" } });
    if (result.path) setSourcePath(result.path);
    return;
  }
  await openDirectoryBrowser("");
}
```

Render path segments as breadcrumb buttons, directory rows as buttons, an empty-state message for leaf directories, and a confirm button selecting the current directory. Do not render untrusted names with `innerHTML`; use `textContent`. Add all modal copy, errors, tooltips, and ARIA labels to both translation dictionaries.

- [ ] **Step 4: Verify both picker modes and commit**

Run:

```powershell
node tests\test_webui_contracts.js
.venv\Scripts\python.exe -m unittest tests.test_webui_contracts tests.test_webui_api -v
```

Expected: all tests pass.

```powershell
git add webui/index.html webui/app.js webui/styles.css webui/ui_prefs.js tests/test_webui_contracts.js tests/test_webui_api.py
git commit -m "接入 Docker 素材目录浏览器"
```

---

### Task 5: Package the Application for fnOS Docker

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `compose.yaml`
- Create: `.env.example`
- Create: `docker/entrypoint.py`
- Create: `tests/test_docker_contracts.py`
- Modify: `webui/server.py`

**Interfaces:**
- Consumes: `SOLIS_CONTAINER=1` runtime policy and `/api/health` from Task 3.
- Produces: image `solis_timelapse`, service/container `solis_timelapse`, port `9501`, and the five approved mounts.
- Produces: entrypoint exit code `2` when runtime mounts fail validation; otherwise starts Flask without opening a browser.

- [ ] **Step 1: Write failing Docker artifact contract tests**

Parse text and YAML using existing PyYAML and assert exact service/mount/security values:

```python
self.assertEqual(compose["services"]["solis_timelapse"]["container_name"], "solis_timelapse")
self.assertEqual(compose["services"]["solis_timelapse"]["user"], "${PUID}:${PGID}")
self.assertIn("${INPUT_PATH}:/media/input:ro", volumes)
self.assertIn("${APP_ROOT}/workspace:/media/workspace", volumes)
self.assertIn("${APP_ROOT}/output:/media/output", volumes)
self.assertIn("${APP_ROOT}/archive:/media/archive", volumes)
self.assertIn("${APP_ROOT}/config:/data/config", volumes)
self.assertNotIn("privileged", service)
self.assertNotIn("/var/run/docker.sock", "\n".join(volumes))
```

Also assert the Dockerfile starts from `python:3.12-slim`, sets `SOLIS_CONTAINER=1`, exposes 9501, has a Python-based health check, and runs as the Compose-provided UID/GID rather than hard-coding a user.

- [ ] **Step 2: Run Docker contract tests and confirm missing-file failures**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_docker_contracts -v
```

Expected: failure because Docker artifacts do not exist.

- [ ] **Step 3: Implement the minimal image and Compose configuration**

Use this Compose shape exactly:

```yaml
services:
  solis_timelapse:
    image: solis_timelapse
    build: .
    container_name: solis_timelapse
    user: "${PUID}:${PGID}"
    environment:
      SOLIS_CONTAINER: "1"
      PYTHONUNBUFFERED: "1"
    ports:
      - "9501:9501"
    volumes:
      - ${INPUT_PATH}:/media/input:ro
      - ${APP_ROOT}/workspace:/media/workspace
      - ${APP_ROOT}/output:/media/output
      - ${APP_ROOT}/archive:/media/archive
      - ${APP_ROOT}/config:/data/config
    restart: unless-stopped
```

Use `.env.example` values:

```dotenv
INPUT_PATH=/vol1/1000/照片/延时摄影
APP_ROOT=/vol1/1000/solis_timelapse
PUID=1000
PGID=1000
```

The Dockerfile copies only application/runtime files, installs `requirements.txt` with `--no-cache-dir`, uses `docker/entrypoint.py`, and health-checks `http://127.0.0.1:9501/api/health` using `urllib.request` so no curl/wget package is required. `.dockerignore` excludes Git metadata, virtualenvs, tests, docs, `.superpowers`, local config, and all workspace/output/archive contents.

- [ ] **Step 4: Implement fail-fast entrypoint validation**

`docker/entrypoint.py` loads `RuntimeEnvironment`, prints every validation issue to stderr prefixed with `Solis_Timelapse:`, exits 2 when any issue exists, and otherwise calls `webui.server.main(["--host", runtime.host, "--port", "9501", "--no-browser"])`. Adjust `main(argv=None)` so tests can inject arguments without changing `python -m webui.server` behavior.

- [ ] **Step 5: Run static and Docker CLI validation**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_docker_contracts tests.test_runtime_env -v
docker compose --env-file .env.example config
docker build -t solis_timelapse .
```

Expected: tests pass; Compose renders service `solis_timelapse`; image build completes. If Docker Desktop is unavailable, record the exact failed command and leave runtime container verification explicitly unverified rather than weakening tests.

- [ ] **Step 6: Run an isolated container persistence and read-only smoke test**

Create temporary host directories outside real media, copy one fixture JPEG sequence into an input subdirectory, set a temporary `.env`, then run Compose. Verify:

```powershell
$smokeEnv = Join-Path $env:TEMP 'solis-timelapse-smoke.env'
docker compose --env-file $smokeEnv up -d
docker inspect --format '{{.State.Health.Status}}' solis_timelapse
docker exec solis_timelapse python -c "from pathlib import Path; Path('/media/input/write-test').write_text('x')"
docker compose --env-file $smokeEnv restart
```

Expected: health becomes `healthy`; the write command fails with a read-only filesystem error; files created through the application under workspace/output/archive/config remain after restart. Stop the temporary stack without deleting the host directories until their contents are inspected.

- [ ] **Step 7: Commit Docker packaging**

```powershell
git add Dockerfile .dockerignore compose.yaml .env.example docker/entrypoint.py webui/server.py tests/test_docker_contracts.py
git commit -m "封装飞牛 Docker 部署"
```

---

### Task 6: Update User Documentation and Local Maintenance Notes

**Files:**
- Modify: `README.md`
- Modify: `.gitignore`
- Modify locally only: `DEVLOG.md`
- Modify: `tests/test_webui_contracts.py`

**Interfaces:**
- Produces: Windows and fnOS usage instructions matching the implemented paths and names.
- Preserves: `DEVLOG.md` as ignored local-only content.

- [ ] **Step 1: Add failing documentation/brand assertions**

Require README to contain `Solis_Timelapse`, `run.bat`, `docker compose`, `INPUT_PATH`, `APP_ROOT`, `/media/input:ro`, PUID/PGID instructions, and the LAN-only warning. Require `.gitignore` to include `.superpowers/`.

- [ ] **Step 2: Run the documentation contract and confirm failure**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_webui_contracts -v
```

Expected: README and ignore assertions fail before documentation is updated.

- [ ] **Step 3: Rewrite README from the user perspective**

Keep only these user-facing sections: project introduction, feature summary, Windows quick start, interface/theme/language use, fnOS Docker deployment, directory/permission explanation, update procedure, and LAN security warning. State that `/vol1/1000` is an example, `/vol1/1000/docker` is not assumed to exist, and users should copy the original path in fnOS File Manager and run `id your_username` for PUID/PGID.

- [ ] **Step 4: Update local-only engineering notes and ignore policy**

Add `.superpowers/` to `.gitignore`. Update ignored `DEVLOG.md` with translation-key parity, preference storage keys, container path-confinement rules, mount validation, and the pending final path move. Verify both local-only files remain ignored:

```powershell
git check-ignore -v DEVLOG.md .superpowers
```

Expected: both are ignored by repository `.gitignore` rules.

- [ ] **Step 5: Run docs tests and brand/path scan**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_webui_contracts -v
rg -n -i "sony[-_ ]timelapse|F:\\02_Tools\\sony_timelapse|/vol1/1000/docker" --glob '!docs/superpowers/specs/**' --glob '!docs/superpowers/plans/**' --glob '!.git/**' .
```

Expected: tests pass. The scan may find historical design/plan documents only because they intentionally document migration history; no runtime, README, Docker, or active UI file contains old branding/path assumptions.

- [ ] **Step 6: Commit only public documentation changes**

```powershell
git add README.md .gitignore tests/test_webui_contracts.py
git commit -m "完善 Solis_Timelapse 使用与部署说明"
```

Do not stage `DEVLOG.md` or `.superpowers/`.

---

### Task 7: Complete Automated, Visual, and Media Workflow Verification

**Files:**
- Modify only when a verified regression requires it: files owned by Tasks 1-6
- Do not commit: screenshots, fixture outputs, temporary Docker mounts

**Interfaces:**
- Consumes: complete application from Tasks 1-6.
- Produces: test evidence for desktop/mobile UI, both languages, all themes, source immutability, export/archive, Docker health, persistence, and read-only input.

- [ ] **Step 1: Run the complete automated suite**

Run:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests\test_webui_contracts.js
.venv\Scripts\python.exe -m compileall -q src webui docker tests
git diff --check
```

Expected: every unittest and JavaScript contract passes; compile and diff checks exit 0.

- [ ] **Step 2: Run the real fixture workflow and verify source immutability**

Run the existing `tests.test_end_to_end` separately so its output is visible:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_end_to_end.EndToEndTests.test_real_api_workflow_preserves_sources_and_archives_outputs -v
```

Expected: JPEG processing, MP4 export, archive verification, and before/after source SHA256 checks pass.

- [ ] **Step 3: Start the local server for browser QA**

Stop any stale server on port 9501, then run:

```powershell
.venv\Scripts\python.exe -m webui.server --host 127.0.0.1 --port 9501 --no-browser
```

Expected: `http://127.0.0.1:9501/` responds and `/api/health` returns HTTP 200.

- [ ] **Step 4: Inspect the actual UI at required viewports**

Using the in-app browser, capture and inspect 1440x900, 1024x768, and 390x844 for all of:

- `light`, `dark`, and `system` with the OS preference toggled once.
- `zh-CN` and `en`.
- Workbench with actual fixture thumbnails and brightness curve, history, settings, confirmation dialogs, error banner, and running task bar.
- Keyboard tab order, visible focus ring, no horizontal page overflow, no clipped labels, no task-bar content overlap, and no blank canvas/image area.

If a visual defect is found, add the smallest reproducible contract or browser check before fixing it, rerun Step 1, and repeat the affected screenshots.

- [ ] **Step 5: Re-run Docker validation on the final image**

Run:

```powershell
docker compose --env-file .env.example config
docker build -t solis_timelapse .
```

Repeat the isolated temporary-mount smoke test from Task 5 and confirm health, read-only input, and persistence after restart.

- [ ] **Step 6: Review final diff and commit any verified QA fixes**

Run:

```powershell
git status --short
git diff --stat
git diff --check
```

Expected: only intentional tracked changes are present; `.superpowers/`, runtime media, local config, and DEVLOG remain ignored. If QA required tracked fixes, commit them with:

```powershell
git add webui/index.html webui/styles.css webui/app.js webui/ui_prefs.js webui/server.py src/runtime_env.py tests
git commit -m "修正界面与容器验收问题"
```

---

### Task 8: Move the Verified Repository to Its Final Path

**Files:**
- Move working tree: `F:\02_Tools\sony_timelapse` -> `F:\01_Project\Solis_Timelapse`
- No tracked file content should change solely because of the move.

**Interfaces:**
- Consumes: clean, committed, fully verified repository from Task 7.
- Produces: operational checkout at `F:\01_Project\Solis_Timelapse`.

- [ ] **Step 1: Confirm a clean tracked state and stop path users**

Run:

```powershell
git status --short
Get-Process | Where-Object { $_.ProcessName -match 'python|docker|node' } | Select-Object Id, ProcessName, Path
```

Expected: no tracked changes; only explicitly understood ignored runtime files. Stop the WebUI process started in Task 7 and any process whose command line/cwd uses the old checkout. Do not stop unrelated Python, Docker, or Node processes.

- [ ] **Step 2: Validate resolved source and destination before moving**

Run:

```powershell
$source = (Resolve-Path -LiteralPath 'F:\02_Tools\sony_timelapse').Path
$target = 'F:\01_Project\Solis_Timelapse'
if ($source -ne 'F:\02_Tools\sony_timelapse') { throw "Unexpected source: $source" }
if (Test-Path -LiteralPath $target) { throw "Target already exists: $target" }
if (-not (Test-Path -LiteralPath 'F:\01_Project' -PathType Container)) { throw 'Missing target parent' }
```

Expected: checks exit without output or error.

- [ ] **Step 3: Move the complete working tree once**

After obtaining filesystem approval for the destination outside the current writable root, run:

```powershell
Move-Item -LiteralPath 'F:\02_Tools\sony_timelapse' -Destination 'F:\01_Project\Solis_Timelapse'
```

Expected: old path no longer exists; new path contains `.git`, source, tests, Docker files, and ignored local data. Do not copy-and-delete and do not edit Codex history or memory databases.

- [ ] **Step 4: Verify the checkout from the new path**

Run with `F:\01_Project\Solis_Timelapse` as the explicit working directory:

```powershell
git status --short
git rev-parse --show-toplevel
.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests\test_webui_contracts.js
docker compose --env-file .env.example config
```

Expected: Git root is `F:/01_Project/Solis_Timelapse`; all tests pass; Compose renders service `solis_timelapse`.

- [ ] **Step 5: Verify Windows launch and final repository state**

Start `run.bat` from the new directory, confirm `http://127.0.0.1:9501/` loads and reports `Solis_Timelapse`, then stop it. Run:

```powershell
git status --short
git log -8 --oneline
```

Expected: no unexpected tracked changes and all implementation commits are present. Record the completed new path in ignored `DEVLOG.md`, then reopen the folder as a new Codex local project/task because the current task retains the old working-directory reference.

---

## Final Acceptance Checklist

- [ ] All existing processing, export, archive, and source-integrity tests pass.
- [ ] Studio Console is usable at 1440x900, 1024x768, and 390x844 without overlap or horizontal overflow.
- [ ] Light, dark, and system themes persist and system changes redraw the chart.
- [ ] Chinese and English switch without reload and all translation-key sets match.
- [ ] Windows native picker still works; Docker browser cannot escape `/media/input`.
- [ ] Docker image builds, Compose validates, health passes, source is read-only, and all growth paths persist on host mounts.
- [ ] README contains accurate fnOS paths and warns against exposing port 9501 publicly.
- [ ] Runtime, UI, Docker, and documentation use `Solis_Timelapse` / `solis_timelapse` consistently.
- [ ] Repository operates from `F:\01_Project\Solis_Timelapse`; old path is absent; Codex history/memory files were not edited.
