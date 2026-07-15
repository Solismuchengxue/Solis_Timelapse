# 延时摄影 WebUI 整体重构设计

## 目标

把当前由 `00_` 到 `08_` BAT 驱动的本地延时摄影流水线重构为单一 WebUI 应用。用户只需要双击 `run.bat`，在浏览器中完成素材分析、分段审核、配方设置、渲染、预览、视频导出和历史归档。

重构采用直接迁移：新流程验证通过后删除旧编号 BAT 和 `02_program/`，不提供兼容入口。现有图像算法按职责迁移到 `src/`，但处理数据流改为从原始照片一次渲染，避免多个步骤反复编码 JPEG。

## 核心约束

- 平台为 Windows，启动入口仅保留根目录 `run.bat`。
- 后端使用 Flask，前端使用原生 HTML、CSS、JavaScript，不引入 Node 构建链。
- 服务只监听 `127.0.0.1`，默认端口 `9501`。
- 第一版同时只处理一个素材批次，批次内允许多个分段，后台任务严格串行。
- 原始 ARW/JPEG 只读引用外部目录；工具不得移动、改名或删除源文件。
- 默认提供一键完整处理，高级设置允许修改参数后从分析或渲染阶段重跑。
- 运行状态、工作文件、个人配置和历史归档均为本机数据，不进入 Git。

## 非目标

- 第一版不支持多批次并发或任务队列。
- 不做云端服务、远程访问、用户系统或权限系统。
- 不内置类似剪映的多轨时间线、音乐、字幕或复杂转场。
- 不实现完整 RAW 调色软件；只提供本项目已验证的延时摄影参数和配方。
- 不自动删除源照片，也不提供源照片清理按钮。

## 目标目录结构

```text
sony_timelapse/
├─ run.bat
├─ src/
│  ├─ config_io.py
│  ├─ media_catalog.py
│  ├─ project_store.py
│  ├─ image_ops.py
│  ├─ image_pipeline.py
│  ├─ task_manager.py
│  ├─ video_export.py
│  └─ archive.py
├─ webui/
│  ├─ server.py
│  ├─ index.html
│  ├─ styles.css
│  └─ app.js
├─ config/
│  ├─ config.yaml
│  └─ local.yaml
├─ workspace/
│  └─ current/
├─ output/
├─ archive/
├─ tests/
├─ docs/
├─ requirements.txt
├─ README.md
└─ DEVLOG.md
```

`config/config.yaml`、源码、测试、README 和设计文档受 Git 管理。`config/local.yaml`、`workspace/`、`output/`、`archive/`、`.venv/`、DEVLOG 和 Agent 本地目录被 `.gitignore` 排除。

## 模块职责

### `src/config_io.py`

维护配置分层：

1. 代码内最小默认值。
2. 受 Git 管理的 `config/config.yaml`。
3. 本机 `config/local.yaml`。

后加载的层覆盖前面的同名字段，嵌套字典做深合并。WebUI 保存设置时只写 `local.yaml`，不修改受跟踪默认配置。

### `src/media_catalog.py`

只读扫描用户选择的素材目录：

- 支持 `.arw`、`.jpg`、`.jpeg`。
- 读取拍摄时间、快门、光圈、ISO、曝光补偿、测光模式、焦距、白平衡和尺寸。
- 计算相邻拍摄间隔和 EXIF 参数变化点。
- 生成自动分段建议和低分辨率缩略图。

自动分段综合以下信号：

- 相邻拍摄时间超过配置阈值。
- 焦距变化。
- 曝光模式或测光模式变化。
- 连续曝光参数出现明显台阶。

自动结果只是建议，必须允许用户在 WebUI 中合并、拆分、排序和重命名。

### `src/project_store.py`

管理 `workspace/current/project.json`。写入采用临时文件加 `os.replace()`，避免服务中断产生半个 JSON。

项目状态至少包含：

```json
{
  "schema_version": 1,
  "source_dir": "D:/photos/timelapse",
  "created_at": "2026-07-15T10:00:00+08:00",
  "updated_at": "2026-07-15T10:05:00+08:00",
  "status": "analyzed",
  "segments": [],
  "active_job_id": null
}
```

每个分段包含稳定 ID、名称、源文件绝对路径列表、帧范围、处理配方、坏帧集合、分析结果、渲染状态和输出文件。分段编辑后保留源文件顺序，不复制照片。

### `src/image_ops.py`

承载无状态图像函数：RAW 解码、亮度测量、中值平滑、曝光增益、自然/通透调色、HSV 转换、日照金山强化和 JPEG 保存。函数只接收数据和参数，不读取项目状态。

### `src/image_pipeline.py`

每个分段分为两个阶段：

#### 分析

- 半分辨率读取源照片。
- 计算亮度曲线、曝光增益、异常帧候选和直方图摘要。
- 保存为 `workspace/current/segments/<id>/analysis.json`。
- 生成用于 UI 的代表帧和缩略图，不产生全分辨率阶段 JPEG。

#### 渲染

逐帧从源照片读取一次，并按固定顺序执行：

1. RAW 解码或 JPEG 载入。
2. 应用分析阶段得到的曝光增益。
3. 跳过用户标记的坏帧。
4. 应用自然、通透或自定义基础调色。
5. 按帧号和渐变范围应用日照金山强化。
6. 写入一次最终 JPEG。

结果位于 `workspace/current/segments/<id>/result/`。修改颜色参数只需要重新渲染；修改去闪、暗帧或分段范围时重新分析后渲染。

### `src/task_manager.py`

维护单个后台任务：

- 状态：`idle`、`queued`、`running`、`cancelling`、`cancelled`、`failed`、`completed`。
- 任务类型：`scan`、`analyze`、`render`、`preview`、`export`、`archive`。
- 在帧边界检查取消事件。
- 记录总帧数、已完成帧数、当前分段、当前文件、开始时间、错误和滚动日志。
- 同时已有任务时拒绝新任务并返回 HTTP 409。
- 服务重启时把遗留的 `running` 状态标记为 `interrupted`，不自动继续写文件。

第一版前端每秒轮询任务状态，不引入 WebSocket 或 SSE。

### `src/video_export.py`

使用 `imageio-ffmpeg` 自带 FFmpeg：

- 快速预览：默认宽 1920、H.264、CRF 20。
- 最终导出：支持 1080p、4K、原图宽度约束；H.264/H.265；24/25/30/50/60 fps；CRF 可配置。
- 允许逐段导出，不做多轨编辑。
- 输出到 `output/`，文件名以分段名为基础并处理非法 Windows 字符。

### `src/archive.py`

归档到 `archive/YYYY-MM-DD_HHMMSS/`：

```text
archive/<时间>/
  manifest.json
  project.json
  <segment-name>/
    recipe.json
    analysis.json
    *.jpg
  <segment-name>_preview.mp4
  output/
    *.mp4
```

归档先复制、逐文件校验大小和数量，再原子写 manifest。成功后仅清理 `workspace/current/`，不清理源目录和 `output/`。归档失败时保留完整 workspace。

## Web API

所有 API 使用 JSON；错误统一返回 `{ "error": "用户可读说明", "code": "稳定错误码" }`。

### 项目与目录

- `GET /api/state`：返回当前项目、任务和服务能力。
- `POST /api/pick-directory`：打开 Windows 原生目录选择器。
- `POST /api/project/scan`：提交源目录并启动扫描任务。
- `DELETE /api/project`：只清理 workspace 当前项目，必须二次确认，不触碰源目录。

### 分段

- `POST /api/segments/split`：在指定帧前拆分。
- `POST /api/segments/merge`：合并相邻分段。
- `PATCH /api/segments/<id>`：修改名称、配方、参数和坏帧集合。
- `POST /api/segments/reorder`：调整分段顺序。
- `GET /api/segments/<id>/thumbnails`：返回缩略图与帧元数据。
- `GET /api/segments/<id>/chart`：返回亮度、目标亮度和增益曲线。

### 处理与输出

- `POST /api/process`：按选择的分段执行分析和渲染。
- `POST /api/process/retry`：从 `analyze` 或 `render` 重跑。
- `POST /api/tasks/cancel`：请求取消当前任务。
- `GET /api/tasks/current`：返回进度和日志。
- `POST /api/export`：导出最终 MP4。
- `POST /api/archive`：归档当前成果。

### 历史与媒体

- `GET /api/history`：列出归档时间、分段和输出摘要。
- `GET /api/history/<timestamp>`：读取 manifest。
- `GET /media/current/...`：只提供 workspace 内预览和缩略图。
- `GET /media/archive/...`：只提供 archive 内 MP4 和代表图。

媒体路由必须先解析真实路径，再验证其位于允许根目录中，拒绝 `..` 和越界绝对路径。

## WebUI 信息架构

### 工作台

页面默认进入工作台，不显示营销或欢迎页。

- 顶部应用栏：产品名、当前素材目录、任务状态、设置按钮。
- 素材操作带：选择目录、扫描、当前帧数和拍摄时长摘要。
- 主区左栏：紧凑分段列表，显示名称、帧数、焦距、时间范围和状态；提供拆分、合并、排序操作。
- 主区右侧：当前分段大预览、亮度曲线和配方设置。
- 下方帧带：固定尺寸缩略图，可多选标记坏帧，并设置强化起止帧。
- 底部任务栏：开始处理、取消、进度、当前帧和可展开日志。

普通用户只看到配方、强度和输出设置；去闪窗口、增益限制、解码亮度、色彩参数放在高级折叠区。

### 历史

按时间倒序显示归档批次。每批展示源目录只读记录、分段数量、JPEG 数量、配方、预览和最终 MP4。历史页只读，不提供恢复源素材或删除归档功能。

### 设置

维护工作目录、默认配方、预览帧率、最终分辨率、编码器和 CRF。保存到 `config/local.yaml`。

## 视觉方向

界面定位为安静、紧凑、工作导向的影像处理控制台：

- 浅色默认，支持跟随系统深色模式。
- 使用中性灰、青绿色操作色、琥珀色警告和红色错误，不采用单一蓝紫色主题。
- 页面段落使用全宽工作区，不把每层都包装成卡片。
- 分段、帧带、进度和参数控件尺寸固定，动态状态不得推动布局跳动。
- 图标按钮使用 Lucide 图标并带 tooltip；命令按钮使用图标加文字。
- 桌面优先，同时保证 768 像素宽可用；手机只要求查看状态和预览，不承诺高效编辑大量帧。

## 错误处理

- 源目录不存在、无支持文件、EXIF 不完整时返回明确错误或降级说明。
- 单帧解码失败时停止当前分段并记录文件名，不静默跳过。
- 磁盘空间不足时在渲染前估算并阻止开始。
- FFmpeg 不可用或导出失败时保留 JPEG 结果。
- 浏览器关闭不取消后台任务；服务进程关闭才中断。
- 取消任务后保留分析数据，删除本次未完成的临时输出，已完成的正式结果不被覆盖。
- 所有覆盖操作先写临时目录，完整成功后用目录替换发布。

## 配置默认值

```yaml
server:
  host: 127.0.0.1
  port: 9501
  open_browser: true
workspace_dir: workspace
output_dir: output
archive_dir: archive
scan:
  gap_seconds: 120
preview:
  fps: 30
  width: 1920
export:
  fps: 30
  resolution: 4k
  codec: h264
  crf: 18
processing:
  jpeg_quality: 95
  default_recipe: natural
```

本机设置允许覆盖这些字段，但不保存源目录；当前源目录属于 `project.json`。

## 迁移策略

迁移分三个可验收阶段：

1. 建立 `src/` 业务模块、配置分层、项目状态和测试；旧代码仍存在。
2. 建立 Flask API 与 WebUI，完成扫描、分段、处理、导出和归档的端到端验证。
3. 验证新流程后删除 `00_` 到 `08_` BAT、`02_program/`、旧编号数据目录和旧配置示例，只保留 `run.bat`。

现有 `05_archive` 历史目录迁移到 `archive/legacy/`，不重写旧文件。当前旧格式 archive 可在历史页显示为“旧版归档”，缺少 manifest 时只展示文件统计。

## 测试与验收

### 单元测试

- 配置三层深合并和本机保存。
- EXIF 扫描、排序、时间间隔和参数变化分段。
- 分段拆分、相邻合并、重命名和顺序稳定性。
- 去闪增益、坏帧剔除、配方强度和一次 JPEG 写入。
- 任务互斥、进度、取消、失败和重启中断状态。
- 路径越界防护、归档校验和源目录不变性。

### API 测试

- 空项目状态。
- 扫描到分段编辑再处理的完整契约。
- 运行中重复提交返回 409。
- 取消任务后状态与临时文件正确。
- 导出和归档成功、失败时均不修改源照片。

### 端到端与视觉测试

- 使用测试生成的小型 JPEG 序列跑通扫描、处理、预览、导出和归档。
- 启动服务并用 Playwright 检查 1440×900、1024×768 和 390×844。
- 检查帧带、任务栏、参数面板不重叠，长文件名不撑破容器。
- 检查预览图和视频像素非空，任务进度实际变化。
- 检查深色和浅色模式的文本、状态色和焦点可见性。

### 完成标准

- 双击 `run.bat` 可自动创建 `.venv`、安装依赖、启动服务并打开浏览器。
- 用户不接触命令行即可完成一个多分段批次的全部流程。
- 源目录在扫描、处理、归档和清理后文件清单及内容保持不变。
- 每张最终 JPEG 在流水线中只编码一次。
- 最终视频与预览视频在 UI 和归档中明确区分。
- 所有自动化测试、Python 编译、API 测试和视觉检查通过。
- Git 中不存在本机路径、照片、视频、workspace、output、archive、local.yaml 或 DEVLOG。
