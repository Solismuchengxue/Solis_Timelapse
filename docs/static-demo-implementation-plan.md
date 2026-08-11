# WebUI 复用型静态演示实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 当前任务不得使用子 Agent，除非用户随后明确要求。

**Goal:** 直接复用现有 WebUI 构建一个由 Mock API 和合成媒体驱动的 GitHub Pages 静态演示，同时把中英文 README 收敛为通用 Docker 入口。

**Architecture:** `demo/build_site.py` 从 `webui/` 白名单组装 `.demo-site/`，只转换生成产物的资源路径并在 `app.js` 前注入 `mock_api.js`。真实 WebUI 的 CSS、国际化与主应用脚本逐字节复用；Mock 层以与 Flask API 相同的响应形状维护内存状态，未知请求关闭失败。

**Tech Stack:** Python 3.12 标准库、原生 HTML/CSS/JavaScript、现有 `unittest` 与 Node 静态契约、GitHub Actions Pages、GitHub Pages。

## Global Constraints

- 不创建或维护第二套 `index.html`、`styles.css`、`ui_prefs.js` 或主应用逻辑。
- 不修改照片扫描、图像处理、视频编码、归档、认证或 Flask API 实现。
- 不安装依赖，不新增前端框架、打包器、图标库、外部字体、分析服务或第三方运行脚本。
- 只使用合成数据和 ImageGen 生成的合成媒体；不得读取或提交真实照片、视频、路径、GPS、用户名、设备地址、凭据或 Token。
- 页面不执行上传、真实下载、文件写入、视频生成或归档删除。
- README 与 README_EN 不出现 `fnOS`、`飞牛`、`/vol1/` 或平台专属入口；历史运维文档与验证事实保留。
- 本地生成站点固定为 `.demo-site/` 并由 Git 忽略，不得进入提交。
- `TODO.md`、`DEVLOG.md` 与 `PLAYBOOK.md` 继续本机维护并保持 Git 忽略。
- 未经用户另行明确批准，不执行 `git add`、`git commit`、`git push`、Pages 仓库设置修改或旧历史重写。
- 后续提交说明不使用“作品集”字样。

---

### Task 1: 建立本地行动记录与静态组装契约

**Files:**
- Modify: `TODO.md`
- Create: `tests/test_demo_contracts.py`
- Create: `demo/build_site.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `webui/index.html`、`webui/styles.css`、`webui/ui_prefs.js`、`webui/app.js`。
- Produces: `build_site(repo_root: Path, output_dir: Path) -> tuple[Path, ...]`，返回生成文件的相对路径；命令行 `python demo/build_site.py --output .demo-site`。

- [ ] **Step 1: 把当前任务写入本地 TODO**

将“当前行动”替换为：

```markdown
## 当前行动

- [ ] 复用现有 WebUI 组装 GitHub Pages 静态演示，不维护第二套 UI。
- [ ] 使用合成媒体和 Mock API 完成扫描、分段、检查、渲染、导出与重置模拟。
- [ ] 将中英文 README 收敛为通用 Docker 入口并完成自动、浏览器和发布验证。
```

- [ ] **Step 2: 先编写失败的组装测试**

在 `tests/test_demo_contracts.py` 创建 `DemoBuildContractTests`，测试代码必须包含：

```python
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_builder():
    path = ROOT / "demo" / "build_site.py"
    spec = importlib.util.spec_from_file_location("demo_build_site", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DemoBuildContractTests(unittest.TestCase):
    def test_build_reuses_webui_sources_and_injects_only_mock_runtime(self):
        builder = load_builder()
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "site"
            files = builder.build_site(ROOT, output)
            names = {path.as_posix() for path in files}
            self.assertTrue(
                {"app.js", "index.html", "mock_api.js", "styles.css", "ui_prefs.js"}.issubset(names)
            )
            for name in ("app.js", "styles.css", "ui_prefs.js"):
                self.assertEqual(
                    sha256((output / name).read_bytes()).digest(),
                    sha256((ROOT / "webui" / name).read_bytes()).digest(),
                )
            html = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn('src="./mock_api.js"', html)
            self.assertLess(html.index("./mock_api.js"), html.index("./ui_prefs.js"))
            self.assertLess(html.index("./mock_api.js"), html.index("./app.js"))
            self.assertNotIn('src="/app.js"', html)

    def test_build_rejects_protected_output_paths(self):
        builder = load_builder()
        for path in (ROOT, ROOT / "webui", ROOT / "demo", ROOT / "workspace"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    builder.build_site(ROOT, path)
```

- [ ] **Step 3: 运行测试并确认 RED**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_demo_contracts.DemoBuildContractTests -v
```

Expected: FAIL，因为 `demo/build_site.py` 尚不存在。

- [ ] **Step 4: 实现最小组装脚本**

`demo/build_site.py` 使用以下接口和常量：

```python
from argparse import ArgumentParser
from pathlib import Path
from shutil import copy2, copytree, rmtree

WEBUI_FILES = ("index.html", "styles.css", "ui_prefs.js", "app.js")
MOCK_SCRIPT = '  <script src="./mock_api.js"></script>\n'


def validate_output_dir(repo_root: Path, output_dir: Path) -> Path:
    root = repo_root.resolve()
    output = output_dir.resolve()
    if output == root or output in root.parents:
        raise ValueError("output cannot be the repository root or its parent")
    for protected_name in ("webui", "demo", "workspace", "output", "archive"):
        protected = (root / protected_name).resolve()
        if output == protected or protected in output.parents or output in protected.parents:
            raise ValueError(f"output overlaps protected path: {protected_name}")
    return output


def transform_index(html: str) -> str:
    replacements = {
        'src="/ui_prefs.js"': 'src="./ui_prefs.js"',
        'href="/styles.css"': 'href="./styles.css"',
        'src="/app.js"': 'src="./app.js"',
    }
    for old, new in replacements.items():
        if html.count(old) != 1:
            raise ValueError(f"expected one index token: {old}")
        html = html.replace(old, new)
    marker = '  <script src="./ui_prefs.js"></script>\n'
    if html.count(marker) != 1:
        raise ValueError("preference script marker changed")
    return html.replace(marker, MOCK_SCRIPT + marker)


def build_site(repo_root: Path, output_dir: Path) -> tuple[Path, ...]:
    root = repo_root.resolve()
    output = validate_output_dir(root, output_dir)
    if output.exists():
        rmtree(output)
    output.mkdir(parents=True)
    for name in WEBUI_FILES:
        copy2(root / "webui" / name, output / name)
    (output / "index.html").write_text(
        transform_index((root / "webui" / "index.html").read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    copy2(root / "demo" / "mock_api.js", output / "mock_api.js")
    assets = root / "demo" / "assets"
    if assets.is_dir():
        copytree(assets, output / "assets")
    return tuple(sorted(path.relative_to(output) for path in output.rglob("*") if path.is_file()))
```

命令行只解析 `--output`，并以脚本父目录的父目录作为仓库根目录。

- [ ] **Step 5: 添加最小 Mock 占位文件并让组装测试进入下一失败点**

先创建可被复制但尚不实现 API 的 `demo/mock_api.js`：

```javascript
"use strict";

globalThis.SolisDemoMock = Object.freeze({ installed: false });
```

重新运行 Task 1 测试。Expected: 组装测试 PASS。

- [ ] **Step 6: 忽略本地生成站点并验证**

在 `.gitignore` 的运行文件区域增加：

```gitignore
.demo-site/
design-qa.md
```

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_demo_contracts.DemoBuildContractTests -v
git check-ignore -v .demo-site design-qa.md
```

Expected: 测试 PASS；两个本地验证产物均命中仓库 `.gitignore`。

---

### Task 2: 为真实 WebUI 增加静态媒体 URL 回退

**Files:**
- Modify: `tests/test_webui_contracts.py`
- Modify: `webui/app.js`

**Interfaces:**
- Consumes: Mock 缩略图对象可选字段 `image_url: string`。
- Produces: `framePreviewUrl(segmentId, frame, index) -> string`；字段缺失时返回现有 `API.frameImage(...)`。

- [ ] **Step 1: 先修改契约测试表达兼容行为**

在 `tests/test_webui_contracts.py` 增加：

```python
def test_frame_preview_accepts_static_demo_media_without_changing_api_fallback(self):
    self.assertIn("function framePreviewUrl(segmentId, frame, index)", self.js)
    self.assertIn("frame?.image_url || API.frameImage(segmentId, index)", self.js)
    self.assertIn(
        "image.src = framePreviewUrl(segment.id, selectedFrame, selectedFrameIndex)",
        self.js,
    )
```

把旧的精确断言 `API.frameImage(segment.id, selectedFrameIndex)` 更新为新 helper 调用，不削弱其它媒体白名单断言。

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_webui_contracts.WebUiStaticContractTests.test_frame_preview_accepts_static_demo_media_without_changing_api_fallback -v
```

Expected: FAIL，因为 helper 尚不存在。

- [ ] **Step 3: 实现最小兼容 helper**

在 `renderSegmentDetail()` 前增加：

```javascript
function framePreviewUrl(segmentId, frame, index) {
  return frame?.image_url || API.frameImage(segmentId, index);
}
```

并将选中帧分支改为：

```javascript
image.src = framePreviewUrl(segment.id, selectedFrame, selectedFrameIndex);
```

不修改 HDR、视频或真实 API 路由。

- [ ] **Step 4: 运行最小与邻近测试并确认 GREEN**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_webui_contracts -v
node --check webui\app.js
node tests\test_webui_contracts.js
```

Expected: 全部 PASS。

---

### Task 3: 实现可测试的 Mock API 状态机

**Files:**
- Create: `tests/test_demo_mock.js`
- Modify: `demo/mock_api.js`
- Modify: `tests/test_demo_contracts.py`

**Interfaces:**
- Produces: `SolisDemoMock.createRuntime(options)`、`runtime.handle(path, init)`、`runtime.reset()`、`SolisDemoMock.install(window)`。
- State values: `idle`、`running`、`completed`；扫描、渲染、导出和归档均使用确定性进度序列 `0 → 35 → 72 → 100`。

- [ ] **Step 1: 先编写 Node 行为测试**

`tests/test_demo_mock.js` 必须直接调用真实 Mock 代码：

```javascript
"use strict";

const assert = require("assert/strict");
const mock = require("../demo/mock_api.js");

async function main() {
  const runtime = mock.createRuntime({ instant: true });
  const initial = await runtime.handle("/api/state", { method: "GET" });
  assert.equal(initial.status, 200);
  assert.equal(initial.body.project.segments.length, 3);

  const media = await runtime.handle("/api/segments/demo-02/thumbnails", { method: "GET" });
  assert.equal(media.body.thumbnails.length, 12);
  assert.ok(media.body.thumbnails.every((frame) => frame.image_url.startsWith("./assets/")));

  await runtime.handle("/api/process", {
    method: "POST",
    body: JSON.stringify({ segment_ids: ["demo-02"] }),
  });
  const completed = await runtime.handle("/api/tasks/current", { method: "GET" });
  assert.equal(completed.body.task.status, "completed");
  assert.equal(completed.body.task.progress, 100);

  const unknown = await runtime.handle("/api/not-allowed", { method: "GET" });
  assert.equal(unknown.status, 404);
  assert.match(unknown.body.error, /静态演示/);

  runtime.reset();
  const reset = await runtime.handle("/api/state", { method: "GET" });
  assert.equal(reset.body.project.segments[1].name, "日出过渡");
}

main().then(() => console.log("Demo mock contracts passed"));
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```powershell
node tests\test_demo_mock.js
```

Expected: FAIL，因为 `createRuntime` 尚不存在。

- [ ] **Step 3: 实现状态与路由表**

`demo/mock_api.js` 使用 CommonJS/浏览器双环境包装，并定义：

```javascript
const SEGMENT_IDS = ["demo-01", "demo-02", "demo-03"];
const TASK_STEPS = [0, 35, 72, 100];

function createRuntime({ instant = false, schedule = setTimeout } = {}) {
  let state = createInitialState();
  let task = idleTask();

  async function handle(path, init = {}) {
    const method = String(init.method || "GET").toUpperCase();
    if (method === "GET" && path === "/api/state") return ok({ project: state.project, task });
    if (method === "GET" && path === "/api/capabilities") return ok(state.capabilities);
    if (method === "GET" && path === "/api/tasks/current") return ok({ task });
    if (method === "GET" && /^\/api\/segments\/[^/]+\/thumbnails$/.test(path)) return thumbnailsResponse(path);
    if (method === "GET" && /^\/api\/segments\/[^/]+\/chart$/.test(path)) return chartResponse(path);
    if (method === "POST" && ["/api/project/scan", "/api/process", "/api/export", "/api/archive"].includes(path)) {
      return startTask(path, { instant, schedule });
    }
    return notFound("静态演示未提供此操作");
  }

  return { handle, reset: () => { state = createInitialState(); task = idleTask(); } };
}
```

`createInitialState()` 必须提供与现有 UI 使用字段一致的 3 个分段、12 帧媒体、曲线、配方、能力、设置和空历史；不包含真实绝对路径、IP、GPS、凭据或视频 URL。

基础响应 helper 必须使用以下实现，不引入自定义 Response 类：

```javascript
function ok(body, status = 200) {
  return { status, body };
}

function rejected(message, status = 409) {
  return ok({ error: message }, status);
}

function idleTask() {
  return { kind: "demo", status: "idle", progress: 0, completed: 0, total: 0, logs: [] };
}

function routeSegmentId(path) {
  return decodeURIComponent(path.split("/")[3] || "");
}
```

`createRuntime()` 内部的 `thumbnailsResponse` 与 `chartResponse` 从 `state.media[segmentId]` 返回数据；分段不存在时返回 404。`startTask` 使用以下确定性状态更新，不得使用随机数：

```javascript
function startTask(kind, { instant, schedule }) {
  task = {
    kind,
    status: "running",
    progress: 0,
    completed: 0,
    total: 100,
    logs: [`[静态演示] ${kind} 已开始`],
  };
  if (instant) {
    task = { ...task, status: "completed", progress: 100, completed: 100, logs: [...task.logs, `[静态演示] ${kind} 已完成`] };
  } else {
    TASK_STEPS.slice(1).forEach((progress, index) => schedule(() => {
      const completed = progress === 100;
      task = {
        ...task,
        status: completed ? "completed" : "running",
        progress,
        completed: progress,
        logs: completed ? [...task.logs, `[静态演示] ${kind} 已完成`] : task.logs,
      };
    }, 350 * (index + 1)));
  }
  return ok({ task });
}
```

Mock 路由表必须精确覆盖：

```text
GET    /api/auth/status                         -> {enabled: false}
GET    /api/capabilities                        -> 本地演示能力
GET    /api/state                               -> {project, task}
GET    /api/tasks/current                       -> {task}
GET    /api/settings                            -> {settings}
PUT    /api/settings                            -> 更新内存设置
GET    /api/color-presets                       -> {presets, default}
POST   /api/pick-directory                      -> {path: "合成素材 / Synthetic sequence"}
GET    /api/segments/:id/thumbnails             -> 12 帧或对应分段帧
GET    /api/segments/:id/chart                  -> 合成亮度曲线
GET    /api/segments/:id/frames/:index/exif     -> 明确标记的合成 EXIF
PATCH  /api/segments/:id                        -> 名称、配方与坏帧内存更新
POST   /api/project/scan                        -> 扫描模拟任务
POST   /api/process                             -> 渲染模拟任务
POST   /api/export                              -> 导出模拟任务，不返回视频 URL
POST   /api/archive                             -> 归档模拟任务，不写文件
POST   /api/tasks/cancel                        -> 取消当前模拟任务
DELETE /api/project                             -> 重置内存状态
GET    /api/history                             -> {history: []}
GET    /api/logs                                -> 当前合成任务日志
DELETE /api/logs                                -> 清空合成日志
```

分段拆分、合并、重排、HDR、历史删除和色彩预设写入不属于核心演示流程，统一返回状态 409 与“静态演示不执行此操作”，不得让请求落到真实网络。

- [ ] **Step 4: 安装浏览器 fetch 适配器**

实现：

```javascript
function install(target) {
  const runtime = createRuntime();
  const originalFetch = target.fetch.bind(target);
  target.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url, target.location.href);
    if (url.origin !== target.location.origin) {
      return new Response(JSON.stringify({ error: "静态演示禁止外部请求" }), {
        status: 403,
        headers: { "Content-Type": "application/json" },
      });
    }
    const result = await runtime.handle(url.pathname, { ...init, body: init.body });
    return new Response(JSON.stringify(result.body), {
      status: result.status,
      headers: { "Content-Type": "application/json" },
    });
  };
  return { runtime, restore: () => { target.fetch = originalFetch; } };
}
```

浏览器环境自动调用 `install(window)`；CommonJS 环境只导出，不自动安装。

浏览器自动安装前，如果 `solis.theme` 尚无用户值，则写入 `light`，让演示首次打开呈现用户选定的白天主题；已有主题偏好不得覆盖。

同时实现 `installDemoChrome(target)`：在现有 `.header-tools` 内插入一个复用 `status-pill` 样式的演示声明和一个普通链接，不新增布局或样式表：

```javascript
const DOCKER_DOCS_URL = "https://github.com/Solismuchengxue/Solis_Timelapse#docker-部署";

function installDemoChrome(target) {
  const tools = target.document.querySelector(".header-tools");
  const notice = target.document.createElement("span");
  notice.className = "status-pill demo-notice";
  notice.textContent = "静态演示 · 合成数据 · 不处理真实文件";
  const link = target.document.createElement("a");
  link.className = "demo-docker-link";
  link.href = DOCKER_DOCS_URL;
  link.textContent = "使用 Docker 运行真实项目";
  tools.prepend(link);
  tools.prepend(notice);
}
```

新增文案以 `solis:languagechange` 监听器切换为对应英文，不修改 `ui_prefs.js` 的翻译表；浏览器契约验证中英文内容。

- [ ] **Step 5: 增加静态安全契约并确认 GREEN**

在 `tests/test_demo_contracts.py` 增加断言：

```python
def test_mock_is_local_only_and_contains_no_sensitive_path_patterns(self):
    source = (ROOT / "demo" / "mock_api.js").read_text(encoding="utf-8")
    for forbidden in ("XMLHttpRequest", "WebSocket", "http://", "/vol1/", "F:\\\\"):
        with self.subTest(forbidden=forbidden):
            self.assertNotIn(forbidden, source)
    self.assertEqual(source.count("https://"), 1)
    self.assertIn("https://github.com/Solismuchengxue/Solis_Timelapse#docker-部署", source)
    self.assertIn("静态演示禁止外部请求", source)
    self.assertIn("/api/not-allowed", (ROOT / "tests" / "test_demo_mock.js").read_text(encoding="utf-8"))
```

Run:

```powershell
node --check demo\mock_api.js
node tests\test_demo_mock.js
.venv\Scripts\python.exe -m unittest tests.test_demo_contracts -v
```

Expected: 全部 PASS。

---

### Task 4: 生成并接入 12 张合成延时媒体

**Files:**
- Create: `demo/assets/frame-01.png` through `demo/assets/frame-12.png`
- Modify: `demo/mock_api.js`
- Modify: `tests/test_demo_contracts.py`

**Interfaces:**
- Consumes: `mock_api.js` 的 12 帧数组。
- Produces: 每帧 `url` 与 `image_url` 均为 `./assets/frame-NN.png`；第 8 帧同时作为第 2 分段 `representative_url`。

- [ ] **Step 1: 先编写资产完整性失败测试**

```python
def test_demo_contains_exactly_twelve_generated_frames(self):
    assets = sorted((ROOT / "demo" / "assets").glob("frame-*.png"))
    self.assertEqual([path.name for path in assets], [f"frame-{index:02d}.png" for index in range(1, 13)])
    for path in assets:
        self.assertGreater(path.stat().st_size, 20_000)
```

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_demo_contracts.DemoBuildContractTests.test_demo_contains_exactly_twelve_generated_frames -v
```

Expected: FAIL，因为资产目录尚不存在。

- [ ] **Step 2: 使用 ImageGen 分别生成 12 帧**

每张图独立生成，统一要求：16:9、无人物、无文字、无水印、固定湖面与山脉机位、写实摄影、从蓝调时刻到日出后暖光。精确序列：

```text
frame-01 05:40 深蓝黎明，地平线微光
frame-02 05:45 蓝调增强，薄云可见
frame-03 05:50 地平线橙光出现
frame-04 05:55 云层边缘变暖
frame-05 06:00 日出前金色带
frame-06 06:05 太阳刚露出山脊
frame-07 06:10 太阳半露，湖面反光
frame-08 06:15 完整日出，主代表帧
frame-09 06:20 暖光扩大，薄云掠过
frame-10 06:25 湖面高光增强
frame-11 06:30 天空转浅蓝
frame-12 06:35 日出后稳定暖光
```

每次生成后用 `view_image` 检查机位、时间连续性、无人物和无文字，再保存到对应路径；不得用 CSS、SVG、渐变或同一图片重复伪造帧序列。

- [ ] **Step 3: 接入精确媒体路径**

Mock 帧对象使用：

```javascript
{
  index: 0,
  name: "合成帧 01 · 05:40",
  stable_id: "synthetic-frame-01",
  url: "./assets/frame-01.png",
  image_url: "./assets/frame-01.png",
  timestamp: "2026-08-09T05:40:00",
  luminance: 0.18,
}
```

12 帧时间每 5 分钟递增；亮度值为：

```javascript
[0.18, 0.22, 0.28, 0.36, 0.48, 0.60, 0.72, 0.84, 0.80, 0.88, 0.92, 0.95]
```

异常候选固定为 `synthetic-frame-04` 与 `synthetic-frame-09`。

- [ ] **Step 4: 运行资产、Mock 和组装测试**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_demo_contracts -v
node tests\test_demo_mock.js
.venv\Scripts\python.exe demo\build_site.py --output .demo-site
```

Expected: PASS；`.demo-site/assets/` 精确包含 12 张图片。

---

### Task 5: 增加 GitHub Pages 白名单工作流

**Files:**
- Create: `.github/workflows/pages.yml`
- Modify: `tests/test_demo_contracts.py`

**Interfaces:**
- Consumes: `demo/build_site.py --output .demo-site`。
- Produces: Pages artifact `.demo-site/` 与 `steps.deployment.outputs.page_url`。

- [ ] **Step 1: 先编写工作流失败测试**

```python
def test_pages_workflow_builds_and_uploads_only_demo_site(self):
    workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    for token in (
        "contents: read", "pages: write", "id-token: write", "actions: read",
        "python demo/build_site.py --output .demo-site",
        "python -m unittest tests.test_demo_contracts",
        "path: .demo-site", "environment:", "name: github-pages",
        "actions/checkout@v6", "actions/configure-pages@v5",
        "actions/upload-pages-artifact@v4", "actions/deploy-pages@v4",
    ):
        self.assertIn(token, workflow)
    self.assertNotIn("path: .\n", workflow)
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_demo_contracts.DemoBuildContractTests.test_pages_workflow_builds_and_uploads_only_demo_site -v
```

Expected: ERROR/FAIL，因为工作流尚不存在。

- [ ] **Step 3: 实现官方 Pages 两 Job 工作流**

工作流必须包含 `build` 与 `deploy`，触发路径只覆盖：

```yaml
paths:
  - ".github/workflows/pages.yml"
  - "demo/**"
  - "webui/index.html"
  - "webui/styles.css"
  - "webui/ui_prefs.js"
  - "webui/app.js"
  - "tests/test_demo_contracts.py"
  - "tests/test_demo_mock.js"
```

完整结构：

```yaml
name: Deploy static demo to Pages

on:
  push:
    branches: [main]
    paths:
      - ".github/workflows/pages.yml"
      - "demo/**"
      - "webui/index.html"
      - "webui/styles.css"
      - "webui/ui_prefs.js"
      - "webui/app.js"
      - "tests/test_demo_contracts.py"
      - "tests/test_demo_mock.js"
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write
  actions: read

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v6
      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - name: Test static demo contracts
        run: python -m unittest tests.test_demo_contracts
      - name: Build static demo
        run: python demo/build_site.py --output .demo-site
      - name: Configure Pages
        uses: actions/configure-pages@v5
      - name: Upload Pages artifact
        uses: actions/upload-pages-artifact@v4
        with:
          path: .demo-site

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - name: Deploy Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 4: 运行工作流契约并确认 GREEN**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_demo_contracts -v
```

Expected: PASS。

---

### Task 6: README Docker 中性化与共享文档同步

**Files:**
- Modify: `tests/test_webui_contracts.py`
- Modify: `tests/test_docker_contracts.py`
- Modify: `README.md`
- Modify: `README_EN.md`
- Modify: `DESIGN.md`
- Modify: `docs/architecture.md`
- Modify: `docs/verification.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Public demo URL: `https://solismuchengxue.github.io/Solis_Timelapse/`。
- Generic Docker example: `INPUT_PATH=/srv/timelapse/input`、`APP_ROOT=/srv/solis_timelapse`、`http://DOCKER-HOST:9501/`。

- [ ] **Step 1: 先把文档契约改成期望状态**

将 `test_user_documentation_covers_windows_and_fnos_deployment` 重命名为 `test_user_documentation_covers_windows_docker_and_static_demo`，并断言中英文 README 包含：

```text
https://solismuchengxue.github.io/Solis_Timelapse/
静态演示
合成数据
docker compose
INPUT_PATH
APP_ROOT
/media/input:ro
PUID
PGID
/srv/solis_timelapse
DOCKER-HOST
ghcr.io/solismuchengxue/solis_timelapse:sha-887a557
docs/architecture.md
docs/verification.md
```

同时断言 README 与 README_EN 不包含：

```text
fnOS
飞牛
/vol1/
docs/operations/fnos.md
作品集
个人职责
```

`test_fnos_authentication_and_reset_are_documented` 改为验证通用 README 包含初始化、登录、可信 Docker 主机上的认证文件重置；平台专属命令与 HTTP 边界继续只在 `docs/operations/fnos.md` 断言。

测试主体使用：

```python
def test_user_documentation_covers_windows_docker_and_static_demo(self):
    readme = README_PATH.read_text(encoding="utf-8")
    english = (ROOT / "README_EN.md").read_text(encoding="utf-8")
    for token in (
        "https://solismuchengxue.github.io/Solis_Timelapse/",
        "docker compose", "INPUT_PATH", "APP_ROOT", "/media/input:ro",
        "PUID", "PGID", "/srv/solis_timelapse", "DOCKER-HOST",
        "ghcr.io/solismuchengxue/solis_timelapse:sha-887a557",
        "docs/architecture.md", "docs/verification.md",
    ):
        self.assertIn(token, readme)
    for token in ("Live Static Demo", "synthetic data", "docker compose", "/srv/solis_timelapse", "DOCKER-HOST"):
        self.assertIn(token, english)
    for document in (readme, english):
        for forbidden in ("fnOS", "飞牛", "/vol1/", "docs/operations/fnos.md", "作品集", "个人职责"):
            self.assertNotIn(forbidden, document)
```

Docker 契约使用：

```python
def test_container_authentication_and_platform_runbook_are_documented(self):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "docs" / "operations" / "fnos.md").read_text(encoding="utf-8")
    self.assertIn("首次访问会显示“初始化管理员”", readme)
    self.assertIn("/srv/solis_timelapse/config/auth.json", readme)
    self.assertIn("Windows 双击 `run.bat` 的本地模式保持原有的免登录行为", readme)
    self.assertIn("mv config/auth.json config/auth.json.bak", runbook)
    self.assertIn("`9501` 仍是明文 HTTP", runbook)
```

- [ ] **Step 2: 运行两个文档契约并确认 RED**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_webui_contracts.WebUiStaticContractTests.test_user_documentation_covers_windows_docker_and_static_demo tests.test_docker_contracts.DockerContractTests.test_container_authentication_and_platform_runbook_are_documented -v
```

Expected: FAIL，因为 README 尚未去平台化和增加演示入口。

- [ ] **Step 3: 修改中英文 README**

执行以下精确内容调整：

- 首屏导航加入“在线静态演示 / Live Static Demo”，说明复用真实 WebUI 但不运行后端。
- 架构 Mermaid 把 `fnOS Docker Compose` 改成 `Docker Host / Docker Compose`。
- “飞牛 fnOS Docker 部署”改为“Docker 部署”，示例路径使用 `/srv/timelapse/input` 与 `/srv/solis_timelapse`。
- 访问地址改为 `http://DOCKER-HOST:9501/`。
- 密码重置使用通用宿主机目录 `/srv/solis_timelapse/config/auth.json`。
- 删除 README 对 `docs/operations/fnos.md` 的入口，但不删除该文件。
- 当前限制删除“没有在线演示”，改为“静态演示不执行真实媒体处理”。
- 不增加个人职责或不可验证成果。

- [ ] **Step 4: 同步长期文档与规则**

- `DESIGN.md` 增加“静态演示模式”：Pages 构建复用 WebUI，Mock 不属于生产运行时。
- `docs/architecture.md` 增加 `webui → build_site → Mock API → Pages` 链路和与 Flask API 的隔离边界。
- `docs/verification.md` 增加静态演示本地自动证据、浏览器证据与线上发布证据三层，并保留历史 fnOS 验收章节。
- `AGENTS.md` 增加：演示不得复制 UI 源码；`.demo-site/` 不得提交；WebUI 结构/API 变化时同步 Mock 契约。

- [ ] **Step 5: 运行文档契约并确认 GREEN**

Run:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_webui_contracts tests.test_docker_contracts tests.test_demo_contracts -v
rg -n "fnOS|飞牛|/vol1/|docs/operations/fnos.md" README.md README_EN.md
```

Expected: 测试 PASS；`rg` 返回退出码 1（`NO_MATCH`）。

---

### Task 7: 全量自动验证与浏览器设计 QA

**Files:**
- Create locally: `design-qa.md`（Git 忽略，不暂存）
- Modify locally: `DEVLOG.md`
- Modify locally: `TODO.md`

**Interfaces:**
- Local static URL: `http://127.0.0.1:9510/`，仅用于本机验收。
- Visual reference: 当前真实 WebUI 1440×900 白天主题；目标为同布局、合成数据填充状态。

- [ ] **Step 1: 执行全量自动验证**

Run:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m compileall -q src webui docker demo tests
node --check webui\app.js
node --check webui\ui_prefs.js
node --check demo\mock_api.js
node tests\test_webui_contracts.js
node tests\test_demo_mock.js
.venv\Scripts\python.exe demo\build_site.py --output .demo-site
git diff --check
```

Expected: 全部退出码 0；不得仅以构建成功代替浏览器验收。

- [ ] **Step 2: 启动本地静态服务器并打开应用内浏览器**

使用 `.venv\Scripts\python.exe -m http.server 9510 --bind 127.0.0.1 --directory .demo-site` 隐藏启动。浏览器使用 Codex 应用内 Browser，不使用 Chrome 或外部 Playwright。

- [ ] **Step 3: 验收桌面核心流程**

在 1440×900 下验证：

1. 默认白天主题显示 3 个分段、第 2 段、12 帧、曲线与代表帧。
2. 顶栏显示“静态演示 · 合成数据 · 不处理真实文件”。
3. 分段切换更新缩略图、曲线和代表帧。
4. 标记/取消坏帧、配方强度、语言与主题切换有效。
5. 渲染、导出、归档模拟显示确定性进度和明确模拟结果。
6. 重置后恢复初始合成项目。
7. 控制台无 error；页面网络请求仅访问本地 HTML、JS、CSS 和 12 张资产。

- [ ] **Step 4: 验收移动端与无障碍边界**

在 390×844 下验证 `scrollWidth <= innerWidth`，主要操作可达、焦点可见、中英文不截断；启用减少动画后任务不产生长等待。

- [ ] **Step 5: 执行阻断式设计 QA**

读取 `product-design:design-qa` 技能。分别捕获真实 WebUI 与静态演示的 1440×900 白天主题截图，在同一视觉比较输入中检查布局、字号、间距、颜色、边框、圆角与控件位置。

`design-qa.md` 必须记录：

```markdown
# Solis_Timelapse Static Demo Design QA

- reference: production WebUI, 1440x900, light theme
- candidate: generated static demo, 1440x900, light theme
- P0/P1/P2 findings: none
- P3 follow-ups: none or explicit minor differences
- final result: passed
```

发现 P0/P1/P2 时先修复并重新捕获，直到 `final result: passed`；不得用截图存在代替比较结论。

- [ ] **Step 6: 记录本地证据并收敛 TODO**

在 `DEVLOG.md` 记录实际测试数量、命令结果、浏览器视口、网络边界和仍未执行的 Pages 发布验证。完成的 TODO 条目从 `TODO.md` 移除；未发布前保留“提交、推送、Actions 和公开 URL 验收”。

- [ ] **Step 7: 检查最终边界**

Run:

```powershell
git status --short
git diff --stat
git diff --check
git check-ignore -v TODO.md DEVLOG.md PLAYBOOK.md .demo-site design-qa.md
git ls-files .demo-site design-qa.md TODO.md DEVLOG.md PLAYBOOK.md
```

Expected: 生成站点、QA 报告和本地维护文件均被忽略且未跟踪；没有真实媒体、敏感配置或无关变更。

---

### Task 8: 提交、推送与线上发布验收门

**Files:**
- No new implementation files.

**Interfaces:**
- Consumes: Task 1–7 的全部本地证据。
- Produces: 只有在用户明确批准后才产生 Git commit、远端分支更新和 Pages 线上证据。

- [ ] **Step 1: 向用户报告待提交文件和验证证据**

报告必须区分：本地实现通过、Git 提交、Git 推送、Actions Pages 成功和公开 URL 可用五种状态。

- [ ] **Step 2: 等待明确提交与推送授权**

未获得授权时停止，不暂存、不提交、不推送、不修改 GitHub Pages 仓库设置。

- [ ] **Step 3: 获得授权后使用中性提交说明**

建议提交说明：

```text
复用 WebUI 增加静态演示并完善 Docker 文档
```

提交前再次运行 `git diff --cached --check` 并确认暂存区不含 `.demo-site/`、`design-qa.md`、本地维护文件或真实媒体。

- [ ] **Step 4: 推送后验收 Pages**

检查 Pages Actions run、artifact 范围、公开 URL HTTP 状态、桌面核心流程和 README 链接。只有全部成功后才报告“在线演示已上线”；否则准确报告失败阶段和未验证边界。
