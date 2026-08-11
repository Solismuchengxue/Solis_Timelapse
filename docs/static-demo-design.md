# WebUI 复用型静态演示与 Docker 中性化设计

状态：accepted

日期：2026-08-11

实施状态：尚未开始

## 1. 目标

为 Solis_Timelapse 增加一个可公开访问的静态演示入口。演示直接复用现有 WebUI 的 HTML、CSS、主题、国际化和应用交互代码，只用合成数据适配层替代 Flask API，不重新设计或维护第二套界面。

同时调整中英文 README，使其只展示通用 Docker 部署方式，不把特定 NAS 平台作为项目身份或主要使用前提。

静态演示用于说明真实产品界面和端到端流程，不替代后端处理，也不作为算法能力、运行性能或现场部署的验证证据。

## 2. 已确认决策

- 视觉目标采用用户选定的方案 2：现有 WebUI 布局、控件密度和白天主题，填入合成任务数据并增加轻量演示提示。
- 不创建独立的 `demo/index.html`、`demo/styles.css` 或另一套 UI 实现。
- GitHub Pages 构建时直接复制 `webui/index.html`、`webui/styles.css`、`webui/ui_prefs.js` 和 `webui/app.js`。
- Pages 产物在 `app.js` 之前注入 `demo/mock_api.js`；该文件只在静态产物中加载，不进入真实 Flask 运行路径。
- 演示只使用合成数据和合成媒体，不读取、上传、处理或保存真实照片与视频。
- 演示公开发布到 GitHub Pages，预期入口为 `https://solismuchengxue.github.io/Solis_Timelapse/`。
- Pages artifact 由明确白名单组装，不发布整个仓库。
- README 与 README_EN 只突出通用 Docker 部署；平台专属运维文档继续作为独立事实记录存在，但不作为 README 的主要入口。
- 不增加“个人职责”“本人贡献”或类似自述章节。
- 后续提交说明不使用“作品集”字样；不重写既有 Git 历史。

## 3. 方案对比与选择理由

### 方案 A：复用 WebUI 并注入 Mock API（采用）

优点是静态演示与真实产品共享 UI 源码，外观、主题、国际化和大部分交互不会形成长期分叉。主要成本是需要覆盖现有 `/api/` 请求，并处理少量由媒体元素直接访问的 `/media/` 或帧图像地址。

### 方案 B：复制 WebUI 后单独维护静态版本（不采用）

初期简单，但 HTML、CSS 和应用逻辑会在真实产品与演示之间逐渐漂移，无法保证在线演示仍代表当前产品。

### 方案 C：重新设计独立展示页（不采用）

视觉自由度最高，但会造成“演示比产品更像另一套系统”的误导，也增加重复开发和维护成本。

## 4. 文件与职责

计划新增：

```text
demo/
├── build_site.py       # 用标准库按白名单组装静态站点
├── mock_api.js         # 合成状态、API 响应和确定性任务状态机
└── assets/             # 仅包含生成的合成 JPEG/WebP 演示媒体
.github/workflows/pages.yml
tests/test_demo_contracts.py
```

计划修改：

- `webui/app.js`：只增加媒体 URL 的兼容回退，使 Mock 数据可以提供静态图片 URL；真实 API 未提供该字段时保持现有行为。
- `README.md`、`README_EN.md`：增加在线演示入口并改为平台无关的 Docker 部署说明。
- `DESIGN.md`、`docs/architecture.md`、`docs/verification.md`：记录 WebUI 复用边界、Pages 组装链路和证据状态。
- `AGENTS.md`：增加演示与真实 WebUI 不得分叉、生成站点不得提交的维护规则。
- `.gitignore`：忽略本地生成的 `.demo-site/`。
- `TODO.md`、`DEVLOG.md`：按项目规则更新本地行动和验证事实，继续保持 Git 忽略。

不修改照片扫描、图像处理、视频编码、归档、认证或 Flask API 实现。

## 5. 静态站点组装

`demo/build_site.py` 使用 Python 标准库完成以下确定性步骤：

1. 创建或清空指定输出目录；默认本地输出为 `.demo-site/`。
2. 从 `webui/` 白名单复制 `index.html`、`styles.css`、`ui_prefs.js` 和 `app.js`。
3. 将生成产物 `index.html` 中的根路径静态资源引用改为相对路径。
4. 在生成产物的 `app.js` 引用之前插入 `mock_api.js`。
5. 复制 `demo/mock_api.js` 和 `demo/assets/`。
6. 拒绝输出目录指向仓库根目录、`webui/`、`demo/`、真实媒体目录或它们的父目录。

组装脚本只修改输出目录，不改写 `webui/` 源文件。产物中的 `styles.css`、`ui_prefs.js` 和 `app.js` 必须与源文件逐字节一致；只有生成后的 `index.html` 允许发生资源路径与 Mock 脚本注入两类变化。

## 6. Mock API 与数据流

`mock_api.js` 在真实 `app.js` 加载前安装演示运行时，并接管 `window.fetch`。它只处理当前 WebUI 已存在的同源 API 请求：

```text
真实 WebUI 控件
    ↓
webui/app.js
    ↓ fetch("/api/...")
demo/mock_api.js
    ↓
合成项目状态 + 确定性任务状态机
```

未列入演示契约的请求必须返回明确的本地错误，不得继续访问互联网或当前主机的真实 API。页面不得使用 `XMLHttpRequest`、`WebSocket`、统计、追踪或第三方脚本。

演示启动后默认显示一个已扫描的合成项目：

- 3 个分段。
- 按真实 `app.js` 的现有行为默认选择第 1 个分段；用户可切换到另外两个分段。
- 12 张合成缩略图。
- 1 条亮度曲线。
- 2 个异常候选，其中 1 个可通过现有“标记坏帧/取消坏帧”交互改变状态。
- 1 张合成代表帧预览。
- 合成配方、设备能力和导出参数。

现有按钮继续驱动真实 `app.js` 逻辑；Mock 层只提供相同形状的响应：

- 重新扫描：进入短时扫描任务，然后恢复 3 个分段。
- 选择分段：加载该分段的合成缩略图与曲线。
- 调整配方和坏帧：只更新内存中的演示状态。
- 渲染：进入短时处理任务并显示进度、日志和完成状态。
- 导出与归档：显示模拟任务进度和结果说明，但不生成、下载或删除文件。
- 清除与重置：只重置当前页面内存；刷新页面恢复初始合成项目。
- HDR、历史、色彩配方和设置页面继续复用现有导航；不属于核心流程的操作可保持只读或返回明确的“静态演示不执行此操作”。

所有模拟动作都必须在可见文案中标明，不伪装成真实后端处理。

## 7. 媒体适配

现有 `app.js` 的普通 API 请求可由 `fetch` 适配器接管，但 `<img>`、`<video>` 等媒体元素不会经过该适配器。因此：

- Mock 缩略图响应直接返回 `demo/assets/` 下的相对 URL。
- Mock 分段直接返回静态 `representative_url`。
- `webui/app.js` 在选中单帧时优先使用 Mock 可选字段 `image_url`，字段不存在时继续调用现有 `API.frameImage(...)`。
- 演示不提供真实视频文件；导出完成只显示模拟结果，不启用视频播放或下载。
- 非核心 HDR 缩略图媒体路径不在本轮扩展；HDR 页面在静态演示中保持只读说明。

合成媒体必须是由 ImageGen 生成的独立图片，不得包含真实照片、人物身份信息、GPS、设备地址、用户名、凭据、水印或外部素材版权声明。

## 8. 视觉与可用性

- 不改变现有 WebUI 的页面结构、字号、控件密度、配色系统或导航。
- 默认呈现用户选定的白天主题；现有白天、夜间和跟随系统切换继续工作。
- 中英文切换继续使用 `webui/ui_prefs.js`；演示新增文案必须具有中英文版本。
- 顶栏增加小型“静态演示 · 合成数据 · 不处理真实文件”提示和 Docker 入口，不增加 Hero、营销模块或大按钮。
- 主要交互保持键盘可操作、焦点可见、状态由现有 `aria-live` 与进度语义呈现。
- 现有响应式布局继续作为移动端基础，不新增与真实产品不同的移动导航。
- 遵循 `prefers-reduced-motion`；Mock 任务在减少动画模式下直接进入完成状态或缩短等待。

## 9. 数据、安全与真实性

- 所有任务名、时间、帧数、路径、日志和结果均为合成示例。
- 合成路径使用明显虚构的展示值，不包含 Windows 盘符、NAS 路径、真实用户名或设备 IP。
- 页面不提供文件输入、上传、真实下载或持久化写入。
- Mock 层对未知 API 路径关闭失败，不回退到真实网络。
- Pages artifact 只允许包含组装后的 WebUI 文件、Mock 脚本和合成媒体。
- 不加载外部字体、图标库、脚本、媒体、分析或广告；唯一外部导航是用户主动点击的 GitHub 仓库 Docker 文档链接。
- 静态站点无法证明 Flask 后端、图像处理、FFmpeg、Docker 或归档链路已经运行。

## 10. README 调整原则

README 与 README_EN 将：

- 在首屏附近增加在线静态演示入口，并准确说明它复用真实 WebUI、使用合成数据且不运行后端处理。
- 使用通用 Docker 主机目录、端口和访问地址示例。
- 保留 GHCR 固定镜像、只读源目录挂载、运行数据目录、用户映射、登录与密码重置等真实部署要点。
- 删除对特定 NAS 品牌、平台名称、专属路径和专属访问地址的强调。
- 将静态演示、本地自动化测试、Docker 部署与历史现场验收明确分开。
- 不增加个人职责、自我评价或无法由仓库验证的成果描述。

平台专属运维文档继续保留，不从历史验证记录中删除真实平台事实。

## 11. GitHub Pages 发布设计

使用 GitHub 官方推荐的 Actions Pages 部署结构：

- 触发条件：推送到 `main` 且演示、WebUI 或 Pages 工作流发生变化；同时允许手动触发。
- 最小权限：`contents: read`、`pages: write`、`id-token: write`；按当前官方动作要求补充 `actions: read`。
- 构建 Job 运行 `python demo/build_site.py --output .demo-site` 和演示契约测试。
- 上传路径固定为 `.demo-site/`。
- 部署 Job 使用 `github-pages` environment，并将动作输出写入 environment URL。
- 动作版本在实施时依据 GitHub 官方文档再次核对，计划使用 `actions/checkout@v6`、`actions/configure-pages@v5`、`actions/upload-pages-artifact@v4` 和 `actions/deploy-pages@v4`。

创建工作流不等于站点已上线。提交、推送、仓库 Pages 来源配置、Actions 成功结果和最终 URL HTTP 验收需要分别保留证据。用户已确认公开 GitHub Pages 方案，但提交与推送仍需单独明确授权。

## 12. 验证与验收标准

### 12.1 自动验证

- 先为组装边界、Mock API 和媒体回退编写失败测试，再实现最小代码。
- `tests/test_demo_contracts.py` 验证静态产物只来自允许白名单。
- 验证产物 `styles.css`、`ui_prefs.js` 和 `app.js` 与 `webui/` 源文件 SHA-256 一致。
- 验证生成的 `index.html` 只发生相对路径改写和 `mock_api.js` 注入。
- 验证 Mock 覆盖核心 API、未知请求关闭失败、无外部 URL、无真实路径模式、无文件上传或网络回退。
- 验证 `webui/app.js` 的媒体回退在 Mock 字段缺失时保持现有真实 API 行为。
- `node --check demo/mock_api.js`、`node --check webui/app.js` 和现有 WebUI 契约通过。
- 现有 Python 全量测试、Python 编译检查和 `git diff --check` 通过。
- 检查中英文 README 的演示链接、Docker 示例和去平台化约束。

### 12.2 浏览器验收

- 在 1440×900 下分别捕获真实 WebUI 与静态演示的相同工作台状态，确认布局、字号、控件和颜色系统一致。
- 在移动宽度下确认沿用现有响应式布局且无横向溢出。
- 完成分段选择、坏帧切换、配方调整、渲染、导出模拟和重置流程。
- 确认明暗主题、中英文切换、键盘焦点和减少动画模式可用。
- 确认控制台无错误，除当前静态站点资源外没有网络请求。
- 设计 QA 必须以“真实 WebUI 截图 + 静态演示截图”同视口对比通过；报告保存在项目根目录 `design-qa.md`，通过后按用户要求删除或保留，不默认提交。

### 12.3 发布验收

- GitHub Actions Pages 工作流成功。
- Pages artifact 只包含 `.demo-site/` 白名单产物。
- 公开 URL 返回成功状态并可完成主要模拟流程。
- README 中演示链接与实际 URL 一致。

完成发布验收前，只能报告“静态演示已实现并通过本地验证”，不能报告“在线演示已上线”。

## 13. 风险与控制

| 风险 | 控制方式 |
| --- | --- |
| 静态演示与真实 UI 漂移 | Pages 每次直接复制 `webui/` 源文件，并用哈希契约禁止复制后再修改 |
| 模拟结果被误认为真实处理 | 顶栏持续显示合成数据说明，任务结果与 README 同步标明模拟 |
| Mock 请求泄漏到真实网络 | 未识别请求关闭失败；浏览器验收检查网络请求 |
| 媒体元素绕过 `fetch` | API 数据返回本地静态 URL，并增加最小媒体 URL 回退 |
| Pages 意外公开仓库内容 | 构建脚本与工作流使用明确白名单，测试检查 artifact 清单 |
| README 去平台化后丢失真实运维知识 | 保留独立平台运维文档与历史验证事实，不把它作为 README 主入口 |

## 14. 完成定义

以下条件全部满足后，本项工作才算完成：

1. Pages 产物直接复用真实 WebUI 文件，没有第二套 HTML、CSS 或主应用逻辑。
2. Mock API、合成媒体和核心模拟流程通过自动与浏览器验收。
3. 真实 Flask WebUI 的现有行为和测试保持不变。
4. README 与 README_EN 已完成 Docker 中性化并正确说明静态演示边界。
5. 共享设计、架构和验证文档准确区分演示、自动测试与真实运行证据。
6. GitHub Pages 工作流只发布白名单组装产物。
7. 已获得提交与推送授权并成功发布。
8. Actions 与公开 URL 均有实际成功证据。
9. 最终 diff 不含真实媒体、敏感配置、本机路径、生成站点或无关变更。

当前没有未决产品决策；按配套实施计划测试先行修改并逐项验收。
