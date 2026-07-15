# 延时摄影 WebUI 整体重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把编号 BAT 延时摄影流水线重构为只读引用源照片、单任务串行、一次 JPEG 渲染、支持预览/导出/归档的本地 WebUI。

**Architecture:** Flask 提供本地 API 和静态文件，原生 HTML/CSS/JS 提供工作台。`src/` 业务模块通过 `workspace/current/project.json` 共享稳定状态，后台任务由单例任务管理器串行执行；分析只保存指标，渲染从源照片一次完成全部图像操作。

**Tech Stack:** Python 3.12、Flask、PyYAML、rawpy、NumPy、Pillow、ExifRead、imageio-ffmpeg、原生 HTML/CSS/JavaScript、unittest、Playwright。

## Global Constraints

- Windows 本地应用，只监听 `127.0.0.1:9501`。
- 仅保留一个根目录 `run.bat`，首次启动自动建立 `.venv` 并安装依赖。
- 原始 ARW/JPEG 只读引用，任何处理、归档、清理不得改动源目录。
- 同时只运行一个任务，任务在帧边界可取消。
- 最终 JPEG 每帧只编码一次。
- `config/local.yaml`、workspace、output、archive、DEVLOG 和媒体文件不进入 Git。
- 旧 BAT 和 `02_program/` 仅在新流程完整验收通过后删除。

---

### Task 1: 新项目骨架、配置分层与启动入口

**Files:**
- Create: `src/__init__.py`
- Create: `src/config_io.py`
- Create: `config/config.yaml`
- Create: `webui/__init__.py`
- Create: `run.bat`
- Modify: `requirements.txt`
- Modify: `.gitignore`
- Test: `tests/test_config_io.py`

**Interfaces:**
- Produces: `load_config() -> dict`, `save_local_config(values: dict) -> dict`, `project_path(*parts) -> Path`.
- Consumes: no project modules; this is the base layer for all later tasks.

- [ ] **Step 1: Write failing configuration tests**

```python
class ConfigIoTests(unittest.TestCase):
    def test_local_yaml_deep_overrides_defaults(self):
        config = config_io.load_config(default_path, local_path)
        self.assertEqual(config["preview"]["width"], 1280)
        self.assertEqual(config["preview"]["fps"], 30)

    def test_save_only_writes_local_yaml(self):
        config_io.save_local_config({"server": {"port": 9600}}, local_path)
        self.assertEqual(yaml.safe_load(local_path.read_text())["server"]["port"], 9600)
        self.assertEqual(default_path.read_text(), original_default)
```

- [ ] **Step 2: Verify tests fail**

Run: `D:\Python3_12\python.exe -m unittest tests.test_config_io -v`

Expected: import failure because `src/config_io.py` does not exist.

- [ ] **Step 3: Implement minimal configuration layer**

Implement these exact public functions:

```python
def deep_merge(base: dict, override: dict) -> dict: ...
def load_config(default_path: Path = DEFAULT_PATH, local_path: Path = LOCAL_PATH) -> dict: ...
def save_local_config(values: dict, local_path: Path = LOCAL_PATH) -> dict: ...
def project_path(*parts: str) -> Path: ...
```

`save_local_config` must write `<name>.tmp` then `os.replace`. Invalid or missing local YAML falls back to defaults and does not rewrite files.

- [ ] **Step 4: Add tracked defaults and startup**

`config/config.yaml` must contain the values from the approved spec. `run.bat` must:

1. use CRLF;
2. create `.venv` with `python -m venv .venv` when missing;
3. install `requirements.txt`;
4. run `.venv\Scripts\python.exe webui\server.py`;
5. display an actionable Python-not-found error.

Add `flask` and `PyYAML` to `requirements.txt`. Ignore `.venv/`, `config/local.yaml`, `workspace/`, `output/`, and `archive/`, while tracking `.gitkeep` files for the three data roots.

- [ ] **Step 5: Verify Task 1**

Run:

```powershell
D:\Python3_12\python.exe -m unittest tests.test_config_io -v
D:\Python3_12\python.exe -m py_compile src\config_io.py
git diff --check
git check-ignore config\local.yaml workspace\x output\x archive\x
```

Expected: tests pass; compile succeeds; all four local paths are ignored.

- [ ] **Step 6: Commit Task 1**

```powershell
git add src config webui run.bat requirements.txt .gitignore tests/test_config_io.py workspace/.gitkeep output/.gitkeep archive/.gitkeep
git commit -m "搭建 WebUI 配置与启动骨架"
```

---

### Task 2: 项目状态、素材扫描与自动分段

**Files:**
- Create: `src/project_store.py`
- Create: `src/media_catalog.py`
- Test: `tests/test_project_store.py`
- Test: `tests/test_media_catalog.py`

**Interfaces:**
- Consumes: `config_io.project_path`.
- Produces: `ProjectStore`, `scan_source(Path) -> list[FrameInfo]`, `suggest_segments(frames, settings) -> list[dict]`.

- [ ] **Step 1: Write failing project store tests**

Cover:

```python
store.create(source_dir)
store.load()["source_dir"] == str(source_dir.resolve())
store.update(lambda state: {**state, "status": "analyzed"})
store.clear()
```

Patch `os.replace` to assert atomic publication. Test that a leftover `.tmp` does not replace the last valid `project.json`.

- [ ] **Step 2: Implement `ProjectStore`**

Public API:

```python
class ProjectStore:
    def __init__(self, workspace: Path): ...
    def create(self, source_dir: Path) -> dict: ...
    def load(self) -> dict | None: ...
    def save(self, state: dict) -> dict: ...
    def update(self, updater: Callable[[dict], dict]) -> dict: ...
    def clear(self) -> None: ...
```

State must include schema version, ISO timestamps, source directory, status, segments, and active job ID.

- [ ] **Step 3: Write failing catalog and segmentation tests**

Use synthetic frame metadata instead of camera files for segmentation tests. Cover splits caused by:

- time gap over 120 seconds;
- focal length change;
- metering/exposure mode change;
- exposure value jump;
- stable sequence remaining one segment.

Also test deterministic ordering when EXIF timestamps match.

- [ ] **Step 4: Implement scan and segmentation**

Public dataclass and functions:

```python
@dataclass(frozen=True)
class FrameInfo:
    path: str
    name: str
    captured_at: str | None
    width: int
    height: int
    shutter: float | None
    aperture: float | None
    iso: int | None
    exposure_bias: float | None
    exposure_mode: str | None
    metering_mode: str | None
    focal_length: float | None
    white_balance: str | None

def scan_source(source_dir: Path) -> list[FrameInfo]: ...
def suggest_segments(frames: list[FrameInfo], settings: dict) -> list[dict]: ...
```

Source scanning must not create, modify, or delete any file under `source_dir`.

- [ ] **Step 5: Add pure segment editing helpers**

Implement and test:

```python
def split_segment(segments: list[dict], segment_id: str, frame_index: int) -> list[dict]: ...
def merge_segments(segments: list[dict], left_id: str, right_id: str) -> list[dict]: ...
def reorder_segments(segments: list[dict], ordered_ids: list[str]) -> list[dict]: ...
```

Only adjacent segments may merge. Stable IDs use UUID4; frame order and membership must be preserved exactly.

- [ ] **Step 6: Verify and commit Task 2**

Run: `D:\Python3_12\python.exe -m unittest tests.test_project_store tests.test_media_catalog -v`

Expected: all state, scan, split, merge, reorder and read-only-source tests pass.

Commit: `git commit -m "实现素材扫描分段与项目状态"`.

---

### Task 3: 无状态图像操作与一次渲染流水线

**Files:**
- Create: `src/image_ops.py`
- Create: `src/image_pipeline.py`
- Test: `tests/test_image_ops.py`
- Test: `tests/test_image_pipeline.py`

**Interfaces:**
- Consumes: frame paths and recipe dictionaries from Task 2.
- Produces: `analyze_segment(...) -> dict`, `render_segment(...) -> RenderResult`.

- [ ] **Step 1: Port image operation tests before code**

Create deterministic NumPy fixtures and test:

- median smoothing and gain clipping;
- natural/punchy/no-op grading;
- golden ramp strength at both boundaries;
- golden enhancement changes warm highlights more than neutral shadows;
- frame number extraction.

Expected initial failure: `src.image_ops` missing.

- [ ] **Step 2: Port stateless operations**

Move only pure functions from `02_program/common.py`: RAW/JPEG loading, luminance measurement, smoothing, gain, grading, HSV conversion, golden enhancement and final JPEG save. Preserve current validated numeric defaults.

Do not port stage directory or `sync_result` behavior.

- [ ] **Step 3: Write analysis tests**

Use 8 small generated JPEG frames with known brightness. Assert `analyze_segment` writes `analysis.json` containing measured luminance, target luminance, gain, frame count and source file identity. Assert source bytes are unchanged.

- [ ] **Step 4: Implement analysis**

```python
def analyze_segment(segment: dict, recipe: dict, work_dir: Path,
                    progress: Callable, cancelled: Callable) -> dict: ...
```

Use half-size decoding, save JSON atomically, and stop with `TaskCancelled` when requested.

- [ ] **Step 5: Write one-pass rendering tests**

Patch `save_jpeg` and assert it is called exactly once per kept source frame. Verify rejected frames are absent; combined exposure gain, grade and golden enhancement are applied in order; a failed render leaves the previous published result untouched.

- [ ] **Step 6: Implement atomic rendering**

```python
@dataclass(frozen=True)
class RenderResult:
    frame_count: int
    result_dir: str
    rejected_count: int

def render_segment(segment: dict, recipe: dict, analysis: dict,
                   target_dir: Path, progress: Callable,
                   cancelled: Callable) -> RenderResult: ...
```

Render into `<segment>/.rendering-<uuid>/`; after all frames succeed, replace the published `result/`. Never read a generated JPEG as the input to another processing operation.

- [ ] **Step 7: Verify and commit Task 3**

Run:

```powershell
D:\Python3_12\python.exe -m unittest tests.test_image_ops tests.test_image_pipeline -v
D:\Python3_12\python.exe -m py_compile src\image_ops.py src\image_pipeline.py
```

Expected: all operations and one-write invariant pass.

Commit: `git commit -m "实现一次渲染图像流水线"`.

---

### Task 4: 串行任务、视频导出与安全归档

**Files:**
- Create: `src/task_manager.py`
- Create: `src/video_export.py`
- Create: `src/archive.py`
- Test: `tests/test_task_manager.py`
- Test: `tests/test_video_export.py`
- Test: `tests/test_archive.py`

**Interfaces:**
- Consumes: Task 2 project state and Task 3 pipeline callables.
- Produces: `TaskManager`, `export_video`, `archive_project`.

- [ ] **Step 1: Test task state machine**

Cover idle → running → completed, duplicate submit raising `TaskBusy`, cancellation at callback boundary, exception → failed, bounded rolling logs, and startup conversion of persisted running state to interrupted.

- [ ] **Step 2: Implement `TaskManager`**

```python
class TaskManager:
    def submit(self, kind: str, fn: Callable[[TaskContext], Any]) -> dict: ...
    def cancel(self) -> dict: ...
    def snapshot(self) -> dict: ...

class TaskContext:
    def progress(self, completed: int, total: int, **detail) -> None: ...
    def log(self, message: str) -> None: ...
    def raise_if_cancelled(self) -> None: ...
```

Use one `ThreadPoolExecutor(max_workers=1)` and one lock around state transitions.

- [ ] **Step 3: Test and implement video export**

```python
def export_video(frame_dir: Path, output: Path, options: dict,
                 progress: Callable | None = None) -> Path: ...
```

Tests inspect generated command arguments rather than requiring a full 4K encode. Cover H.264/H.265, valid fps, 1080p/4K scaling, concat cleanup, Windows filename sanitization and FFmpeg failure preserving frames.

- [ ] **Step 4: Test archive contract**

Create a temporary source directory and record hashes before archive. Assert archive includes project, recipes, analysis, JPEG, previews, output and manifest; workspace is cleared only after verification; source hashes and output files remain unchanged; copy failure preserves workspace.

- [ ] **Step 5: Implement archive**

```python
def archive_project(project: dict, workspace: Path, output_dir: Path,
                    archive_dir: Path, timestamp: str | None = None) -> Path: ...
```

Manifest records schema version, archive time, source path, source file count, segment counts, recipes, preview/final output distinction and Git commit when available.

- [ ] **Step 6: Verify and commit Task 4**

Run: `D:\Python3_12\python.exe -m unittest tests.test_task_manager tests.test_video_export tests.test_archive -v`

Commit: `git commit -m "实现任务导出与安全归档"`.

---

### Task 5: Flask API 与本地路径安全

**Files:**
- Create: `webui/server.py`
- Test: `tests/test_webui_api.py`
- Test: `tests/test_media_routes.py`

**Interfaces:**
- Consumes: all Task 1–4 public interfaces.
- Produces: Flask `app`, REST endpoints and static/media serving.

- [ ] **Step 1: Create Flask test fixture and failing state tests**

Build `create_app(config_overrides=None)` so tests can inject temporary workspace/output/archive roots. Test `GET /api/state` on an empty workspace and stable error envelope.

- [ ] **Step 2: Implement application factory and core APIs**

Implement the approved endpoints for state, scan, split, merge, reorder, patch segment, process, retry, task cancel/current, export, archive, settings and history.

Long-running endpoints return HTTP 202 with task ID. Busy operations return HTTP 409 and code `task_busy`. Invalid user input returns HTTP 400; internal failures return HTTP 500 without Python filesystem details in the response.

- [ ] **Step 3: Implement Windows directory picker**

`POST /api/pick-directory` opens `tkinter.filedialog.askdirectory` on the server machine. Empty selection returns `{ "path": null }`, not an error.

- [ ] **Step 4: Test media path traversal before implementation**

Verify `/media/current/../../README.md`, encoded traversal and absolute paths return 404. Valid media under injected roots must return 200.

- [ ] **Step 5: Implement safe media serving**

Resolve candidate and allowed root with `Path.resolve()`, require `candidate.is_relative_to(root)`, and use `send_file` only after validation. Do not expose original source photos through HTTP.

- [ ] **Step 6: Verify API and commit Task 5**

Run:

```powershell
D:\Python3_12\python.exe -m unittest tests.test_webui_api tests.test_media_routes -v
D:\Python3_12\python.exe webui\server.py --help
```

Commit: `git commit -m "提供延时摄影 WebUI API"`.

---

### Task 6: 工作台、分段编辑、进度与历史前端

**Files:**
- Create: `webui/index.html`
- Create: `webui/styles.css`
- Create: `webui/app.js`
- Test: `tests/test_webui_contracts.py`
- Test: `tests/test_webui_contracts.js`

**Interfaces:**
- Consumes: Task 5 JSON endpoints.
- Produces: browser workbench, history and settings views.

- [ ] **Step 1: Add static contract tests**

Assert HTML contains accessible names and stable IDs for source picker, scan, segment list, preview, recipe controls, bad-frame action, process, cancel, progress, log, export, archive, history and settings. Assert JS references every required API route and does not use inline `onclick` handlers.

- [ ] **Step 2: Implement semantic page skeleton**

Use three tabs: 工作台、历史、设置. Build full-width work bands, a desktop two-column segment/detail area, fixed thumbnail dimensions and a sticky task bar. Include only actual tool controls; no feature-description cards or landing content.

- [ ] **Step 3: Implement state and API client**

Create a single in-memory `state` object. Implement `api(path, options)`, `refreshState()`, one-second task polling while active, error banner, button disable rules and log rendering.

- [ ] **Step 4: Implement segmentation interactions**

Support selecting, renaming, splitting at selected frame, merging adjacent segments, moving up/down and changing recipe. Advanced settings use native inputs, sliders, selects, toggles and segmented controls.

- [ ] **Step 5: Implement frame strip and preview**

Render virtualized or paged thumbnails so 700 frames do not create 700 simultaneous full images. Allow range selection, mark/unmark reject, choose golden start/end and show frame metadata tooltip.

- [ ] **Step 6: Implement processing, export and archive flows**

Process and cancel buttons reflect task state. Export shows fps/resolution/codec/CRF controls. Archive requires a modal confirmation that states workspace will be cleared and source files retained.

- [ ] **Step 7: Implement history and settings**

History fetches manifests and renders preview/final video separately. Settings save to local config and never display or edit arbitrary server paths outside directory picker controls.

- [ ] **Step 8: Verify static contracts and commit Task 6**

Run:

```powershell
D:\Python3_12\python.exe -m unittest tests.test_webui_contracts -v
node tests\test_webui_contracts.js
```

Commit: `git commit -m "实现延时摄影 WebUI 工作台"`.

---

### Task 7: 端到端验证、视觉 QA 与旧结构删除

**Files:**
- Create: `tests/fixtures/make_sequence.py`
- Create: `tests/test_end_to_end.py`
- Modify: `README.md`
- Modify: `DEVLOG.md` (local only)
- Delete after verification: `00_提取信息.bat` through `08_清理.bat`
- Delete after verification: `02_program/`
- Delete after verification: old numbered data roots and `config.example.json`
- Move local legacy archive: `05_archive/` to `archive/legacy/`

**Interfaces:**
- Consumes: complete application.
- Produces: final user-facing project and migration record.

- [ ] **Step 1: Generate a deterministic fixture sequence**

Create 24 small JPEG frames with known brightness ramp, one artificial dark frame, one reject marker candidate and two EXIF-free groups separated by filesystem timestamps. Fixture generation occurs in a temporary directory during tests; generated media is not committed.

- [ ] **Step 2: Add end-to-end API test**

Through Flask test client: scan → edit segments → process → verify one-write result count → generate preview → export MP4 command → archive. Assert fixture source hashes are unchanged after every stage.

- [ ] **Step 3: Run full automated verification before deletion**

Run:

```powershell
D:\Python3_12\python.exe -m unittest discover -s tests -v
D:\Python3_12\python.exe -m py_compile (Get-ChildItem src,webui,tests -Recurse -Filter *.py | Select-Object -ExpandProperty FullName)
git diff --check
```

Expected: all tests pass and no compile/diff errors.

- [ ] **Step 4: Start application and perform browser QA**

Run: `.venv\Scripts\python.exe webui\server.py --no-browser --port 9501`

Use Playwright at 1440×900, 1024×768 and 390×844. Capture screenshots and verify:

- page and media previews are nonblank;
- segment list, detail pane, frame strip and task bar do not overlap;
- long file names wrap or truncate without resizing controls;
- processing progress changes while fixture task runs;
- light and dark modes maintain readable contrast;
- mobile view can inspect status and preview without horizontal page overflow.

- [ ] **Step 5: Delete old structure only after Steps 3–4 pass**

Remove numbered BAT files and `02_program/`. Migrate existing local `05_archive` to `archive/legacy` without changing its contents. Remove old numbered empty roots and `config.example.json`. Do not delete Git history or the external source directory.

- [ ] **Step 6: Rewrite README for WebUI-only usage**

README must contain only project introduction, `run.bat` quick start, WebUI workflow, source safety, directory structure, export/archive behavior and troubleshooting. It must not mention running old numbered scripts.

- [ ] **Step 7: Final repository checks**

Run:

```powershell
rg "02_program|00_提取信息|01_分类|02_去闪|08_清理" --glob "!DEVLOG.md" --glob "!docs/superpowers/**"
git status --short
git check-ignore config/local.yaml workspace/x output/x archive/x DEVLOG.md
```

Expected: no active old-path references; only intended migration changes are present; all local data is ignored.

- [ ] **Step 8: Commit final migration**

```powershell
git add -A
git diff --cached --check
git commit -m "完成延时摄影 WebUI 整体迁移"
```

---

## Plan Self-Review

- Every approved requirement maps to a task: configuration and startup (1), read-only source and segmentation (2), one-pass image pipeline (3), serial tasks/export/archive (4), API/security (5), WebUI (6), migration and visual QA (7).
- Old code deletion is gated behind automated and browser verification.
- Preview and final video have separate modules, UI labels and archive entries.
- Source safety is tested in Tasks 2, 4 and 7.
- No task requires Node as a build dependency; Node is used only for an optional static JavaScript contract test already consistent with the reference project.
