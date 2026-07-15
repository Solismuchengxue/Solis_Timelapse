# Solis_Timelapse UI、国际化、Docker 与仓库迁移设计

## 1. 目标

在不改变现有延时摄影处理、导出和归档契约的前提下，完成以下升级：

1. 将产品品牌统一改为 `Solis_Timelapse`。
2. 将现有 WebUI 重构为已选定的 Studio Console 视觉方向。
3. 增加明亮、暗色、跟随系统三种主题。
4. 增加中文和英文界面切换。
5. 提供适用于飞牛 fnOS 的 Dockerfile 与 Docker Compose 部署方式。
6. 全部实现和验证完成后，将仓库从 `F:\02_Tools\sony_timelapse` 移动到 `F:\01_Project\Solis_Timelapse`。

## 2. 不在范围内

- 不改变现有照片分析、去闪、调色、视频导出和归档算法。
- 不增加用户系统、登录页或公网身份认证。
- 不迁移到 Vue、React 或其他前端框架。
- 不增加上传大型 RAW 文件的浏览器上传流程。
- 不支持从 Docker 容器浏览 `/media/input` 以外的素材目录。
- 不自动修改 Codex 全局配置、历史会话文件或记忆文件。

## 3. 已确认决策

### 3.1 品牌与命名

- 产品品牌：`Solis_Timelapse`
- Docker Compose 服务名：`solis_timelapse`
- Docker 容器名：`solis_timelapse`
- Docker 镜像本地默认名：`solis_timelapse`
- 飞牛默认应用目录示例：`/vol1/1000/solis_timelapse`
- 最终本地仓库路径：`F:\01_Project\Solis_Timelapse`

品牌文字、页面标题、启动提示、日志前缀、README、Docker 文件和示例路径必须同步更新。Python 包名和现有 API URL 不因品牌重命名而变更。

### 3.2 技术路线

保留 Flask 和原生 HTML/CSS/JavaScript。主题使用 CSS 自定义属性与根元素 `data-theme`；国际化使用仓库内的中英文 JavaScript 字典。该方案不新增生产依赖，也不引入前端构建步骤。

未采用的方案：

- Vue + vue-i18n：状态管理更规范，但需要整体迁移和 Node 构建链，对当前单页工具成本过高。
- Flask-Babel：适合服务端模板，但当前动态界面仍需独立 JavaScript 翻译，且切换语言通常需要刷新。

## 4. Studio Console 界面

### 4.1 视觉系统

采用用户选择的 Studio Console 方向：安静、专业、工作导向，避免营销页和装饰性元素。

- 主色：克制的青绿色，用于主操作、活动状态和进度。
- 中性色：浅色主题使用冷灰白；暗色主题使用石墨灰而不是深蓝。
- 暖色：仅用于日照金山范围、警告和需要注意的状态。
- 卡片圆角不超过 8px，不使用渐变、装饰光斑或嵌套卡片。
- 实际照片、缩略图和亮度曲线始终是主视觉，不用插画替代素材内容。
- 图标按钮优先使用现有可用的图标方案；不为少量图标新增大型依赖。

### 4.2 信息架构

- 顶部：品牌、当前素材路径、任务状态、语言菜单、主题菜单。
- 左侧：工作台、历史、设置主导航，以及当前分段列表。
- 中部：当前代表帧、亮度曲线、处理配方和高级参数。
- 下部：帧检查时间线和坏帧操作。
- 底部：固定任务栏，包含开始、重跑、取消、当前文件、进度、导出和归档。

现有功能不减少。桌面保持高信息密度；窄屏改为单列，但页面本身不得水平溢出。固定格式控件使用稳定宽度，语言切换不得造成跳动或重叠。

## 5. 主题

支持以下值：

- `light`：强制明亮主题。
- `dark`：强制暗色主题。
- `system`：跟随 `prefers-color-scheme`。

实现约定：

- 根元素使用 `data-theme="light|dark|system"`。
- 首次打开默认为 `system`。
- 用户选择保存在 `localStorage`。
- `system` 模式下监听系统主题变化并即时更新图表、浏览器 `color-scheme` 和主题图标。
- 非法或旧版本值回退到 `system`。
- 三种主题必须满足文本、按钮、焦点环、禁用态、危险态和图表曲线的对比度要求。

## 6. 国际化

支持：

- `zh-CN`
- `en`

实现约定：

- 使用本地翻译字典，不新增 i18n 依赖。
- 静态 DOM 使用稳定翻译键；动态内容通过统一 `t(key, params)` 函数生成。
- 中英文翻译键集合必须完全一致，由自动测试校验。
- 首次打开时，浏览器语言以 `zh` 开头则使用 `zh-CN`，否则使用 `en`。
- 用户选择保存在 `localStorage`，刷新后保持。
- 缺少翻译时回退到中文，并在开发控制台报告缺失键。
- 页面标题、状态、任务日志、错误提示、空状态、历史摘要、表单标签、按钮、Tooltip、ARIA 和确认对话框全部纳入翻译。
- 文件名、用户自定义段名、路径、EXIF 值和归档内容不翻译。

后端继续返回稳定错误代码。前端优先按错误代码翻译，后端错误文本仅作为未知错误的兜底。

## 7. Docker 与飞牛 fnOS

### 7.1 镜像

- 基础镜像使用官方 `python:3.12-slim`。
- 只安装当前 Python 依赖运行所需的最少系统库。
- 不使用特权模式，不挂载 Docker Socket。
- 容器内服务监听 `0.0.0.0:9501`；Windows 本地运行继续监听 `127.0.0.1:9501`。
- 增加不依赖额外命令行工具的 HTTP 健康检查。

### 7.2 Compose

```yaml
services:
  solis_timelapse:
    container_name: solis_timelapse
    user: "${PUID}:${PGID}"
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

飞牛 `.env` 示例：

```env
INPUT_PATH=/vol1/1000/照片/延时摄影
APP_ROOT=/vol1/1000/solis_timelapse
PUID=1000
PGID=1000
```

`/vol1/1000` 仅是常见首位管理员示例，不写死到程序。`/vol1/1000/docker` 也不是飞牛预置目录，本设计不依赖它。用户应在飞牛文件管理器中通过“详细信息 → 复制原始路径”取得真实路径，或通过 SSH 使用 `id 用户名` 确认 PUID/PGID。

### 7.3 容器目录

- `/media/input`：原始照片，只读。
- `/media/workspace`：当前任务和 JPEG 结果。
- `/media/output`：当前 MP4。
- `/media/archive`：归档历史。
- `/data/config/local.yaml`：容器本地持久化设置。

Docker 启动时必须验证 `/media/input` 可读，并验证 `/media/workspace`、`/media/output`、`/media/archive` 和 `/data/config` 可写。失败时启动日志给出明确原因，不能回退写入容器临时层。

### 7.4 目录选择

- Windows 本地模式保留原生文件夹选择窗口。
- Docker 模式使用 WebUI 目录浏览器。
- Docker 目录浏览 API 只允许列出 `/media/input` 及其子目录。
- 所有路径必须经过 `resolve` 和 `relative_to` 校验，拒绝 `..`、绝对路径注入、Windows 路径形式和符号链接逃逸。
- 浏览器只返回目录名和相对路径，不向前端泄露容器其他文件系统信息。

### 7.5 网络边界

首版不增加登录系统，只用于可信家庭局域网。README 必须明确说明不要把 9501 端口直接转发到公网；需要远程访问时，应使用受控 VPN 或反向代理认证，不在本次实现中配置这些基础设施。

## 8. 数据与安全契约

现有安全契约保持不变：

1. 原始照片目录始终只读，不移动、不改名、不覆盖、不删除。
2. 源目录不得与工作、输出、归档目录互相包含。
3. 分析、渲染和视频继续使用临时路径与原子发布。
4. 归档完成哈希与数量校验后才清理工作区。
5. Docker 的 `/media/input:ro` 在操作系统层进一步限制误写。

## 9. 错误处理

- 无效主题或语言设置自动回退，不阻止页面启动。
- 翻译缺失使用中文兜底，并保留可诊断日志。
- Docker 未挂载 `/media/input`、持久化目录不可写或权限不匹配时，健康检查失败并输出具体路径和权限问题。
- Docker 目录浏览越界统一返回稳定的 `invalid_media_path` 错误码。
- 容器模式下不可调用本地图形目录选择器；前端根据服务端能力自动切换控件。
- 现有任务失败、取消和原子发布行为不变。

## 10. 验证

### 10.1 自动测试

- 中英文翻译键一致。
- 主题与语言非法值回退。
- 静态文字、动态状态和错误代码均通过翻译入口。
- Docker 目录浏览正常列出与路径穿越、符号链接逃逸拒绝。
- 容器模式运行目录与本地模式互不影响。
- 现有 Python、API、媒体白名单、任务、导出、归档和端到端测试全部通过。
- 真实 JPEG → 处理 → MP4 → 归档流程继续验证源文件 SHA256 不变。

### 10.2 UI 验证

在 1440×900、1024×768 和 390×844 视口检查：

- 明亮、暗色、跟随系统。
- 中文和英文。
- 无页面级横向溢出、文本遮挡或固定任务栏覆盖内容。
- 键盘导航、焦点环、ARIA 状态和颜色对比度。
- 实际素材缩略图、亮度曲线和任务进度可见。

### 10.3 Docker 验证

- `docker build` 成功。
- `docker compose config` 成功。
- 容器健康检查通过。
- `/media/input` 内测试素材可扫描但不可写。
- `/media/workspace`、`/media/output`、`/media/archive` 和 `/data/config` 中的数据在容器重启后仍存在。
- 真实测试序列能够完成处理、导出和归档。

## 11. 仓库路径迁移

路径迁移只在代码、测试、Docker 和文档全部完成并提交后执行：

1. 搜索仓库及本地维护文件中的 `sony_timelapse` 和旧绝对路径引用。
2. 停止本地 WebUI、视觉方案服务和其他占用旧目录的进程。
3. 核对目标 `F:\01_Project\Solis_Timelapse` 不存在，源和目标都位于预期父目录。
4. 将整个 Git 工作树移动到新路径。
5. 从新路径验证 Git 状态、完整测试、`run.bat`、WebUI 和 Docker Compose。
6. 在 Codex 桌面端从新目录重新打开本地项目。

Codex 历史任务和本地记忆保存在 Codex 用户目录，不会随仓库移动而删除。但当前任务记录了旧工作目录，移动后不保证能继续获得文件权限；因此迁移完成后的后续工作应从新路径打开项目并创建新任务。不得直接编辑 Codex 历史会话或记忆数据库来强行改路径。

## 12. 文档

- README 保持纯用户视角，包含 Windows 启动、主题语言、Docker 与飞牛部署、卷挂载、权限、升级和局域网安全说明。
- `DEVLOG.md` 保持本地忽略，记录 i18n 键约束、主题状态、Docker 路径安全和仓库迁移结果。
- `.superpowers/` 视觉讨论产物属于本地临时资料，不提交 Git。
