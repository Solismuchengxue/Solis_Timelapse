# 验证与证据

- 状态：accepted
- 最近核对：2026-08-29
- 设计入口：[DESIGN.md](../DESIGN.md)

## 1. 证据层级

项目将证据分为四类，避免从一类检查推导另一类结论：

| 层级 | 能证明什么 | 不能自动证明什么 |
| --- | --- | --- |
| 源码与配置检查 | 组件、默认值、挂载、工作流和实现路径存在 | 实际设备运行成功 |
| 自动化测试 | 测试覆盖的输入、失败分支和不变量符合预期 | 所有真实照片、驱动或 NAS 环境兼容 |
| 本地构建与语法检查 | 当前环境能导入、编译或解析相关文件 | fnOS/GPU/网络部署状态 |
| 现场验收 | 指定设备、镜像和时间点的实际状态 | 其他设备、未来版本或公网安全性 |

## 2. 标准验证命令

在项目根目录使用已有 `.venv`：

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

这些命令不安装依赖。若 `.venv` 不存在或依赖不可用，应如实报告未执行项，不自动安装。

文档或治理变更还需要：

```powershell
git status --short
git check-ignore -v TODO.md DEVLOG.md PLAYBOOK.md config/local.yaml config/auth.json .env
```

并人工检查 Markdown 相对链接、Mermaid 语法、固定镜像标签和中英文限制是否一致。

## 3. 当前自动化覆盖

截至 2026-08-29，测试源码包含 258 个 Python `unittest` 测试方法。这个数字描述当前测试清单，不代表任意未来工作区已经运行通过。

| 测试文件 | 主要覆盖 |
| --- | --- |
| `tests/test_archive.py` | 归档集合、Manifest、哈希、路径和失败行为 |
| `tests/test_auth.py` | scrypt 密码记录、初始化、验证、密码轮换、损坏状态和原子写入 |
| `tests/test_config_io.py` | 默认配置、本机覆盖和配置写入 |
| `tests/test_docker_contracts.py` | Compose、固定 GHCR 镜像、AMD64 工作流、挂载、认证文档 |
| `tests/test_demo_contracts.py` / `test_demo_mock.js` | WebUI 白名单组装、共享浏览器标签图标、12 张合成媒体、Mock 路由与状态、外部请求拒绝、Pages artifact 边界 |
| `tests/test_end_to_end.py` | 合成 24 帧序列的扫描、处理、导出、归档与源文件哈希不变 |
| `tests/test_hdr_merge.py` | HDR 对齐、融合、辐射模式、输出和参数边界 |
| `tests/test_image_ops.py` | 解码、亮度、调色、去闪、设备选择和数值安全 |
| `tests/test_image_pipeline.py` | 分析、异常候选、渲染、源身份、并行和原子发布 |
| `tests/test_media_catalog.py` | 递归扫描、EXIF、分段、同名文件和时间线操作 |
| `tests/test_project_store.py` | 项目状态与原子持久化 |
| `tests/test_task_manager.py` | 单任务、进度、日志、取消、恢复和状态限制 |
| `tests/test_video_export.py` | H.264/H.265、NVENC、回退、取消、进度和原子输出 |
| `tests/test_webui_api.py` | API、路径边界、认证、修改密码、跨会话失效、任务和媒体访问 |
| `tests/test_webui_contracts.py` / `.js` | 用户界面、国际化、工作流、文档和部署静态契约 |

文件系统和端到端测试使用临时目录与合成数据，不读取用户真实照片库。

## 4. 关键不变量与证据

| 不变量 | 主要证据 |
| --- | --- |
| 源照片在工作流中不被修改 | 端到端逐阶段 SHA-256 对比、只读挂载契约、路径校验测试 |
| 输入与应用数据目录不重叠 | Flask 运行根校验、归档根校验及对应测试 |
| 半成品不替换当前结果 | 项目、分析、渲染、视频和归档的临时发布测试 |
| 路径不能逃逸允许根目录 | 当前媒体、归档媒体和容器目录 API 测试 |
| 无 GPU 时仍可运行 | OpenCL/NVENC 能力检测和 CPU 回退测试 |
| 部署镜像可追溯 | Compose 固定 `sha-*`、GitHub Actions 标签和合约测试 |
| 容器业务路由需要登录且密码轮换收回旧会话 | 初始化、登录、退出、修改密码、跨会话失效、API 和媒体路由测试 |
| 静态演示不访问真实后端或外部网络 | Mock 路由测试、敏感路径扫描、未知路由和跨源请求失败关闭 |

## 5. 静态演示证据边界

静态演示的证据分三层，不能互相替代：

1. **本地自动证据**：`tests/test_demo_contracts.py`、`tests/test_demo_mock.js`、语法检查和 `build_site.py` 证明组装白名单、响应形状、12 张合成媒体、确定性状态和 Pages artifact 边界。
2. **本地浏览器证据**：在本机 HTTP 服务中，以桌面和移动视口验证实际页面渲染、分段切换、坏帧、主题/语言、模拟任务、控制台和网络请求。
3. **线上发布证据**：只有工作流在 GitHub 上成功且公开 URL 可访问，才能声称在线静态演示已发布。仓库内工作流文件和本地构建成功本身不构成线上可用证据。

静态演示只证明 WebUI 的展示与核心交互契约，不证明 Flask、图像管线、FFmpeg、Docker 容器或真实文件处理正在运行。

## 6. 2026-08-29 fnOS 部署验收

固定镜像 `sha-6f4a766` 已部署到指定 fnOS Compose 项目。现场证据包括：

- 容器状态为 `healthy`、重启计数为 0；Compose 标签、OCI revision `6f4a7666951a6a0d678682c6ddc99238ed26d7af` 和 GHCR digest `sha256:e4f10d54d95c6661ebae76621f60f5891ea7b767940a6801339cc28ed23eef88` 相互一致。
- `/api/health` 返回 `200`，匿名业务 API 返回 `401`，匿名访问 `/auth/password` 跳转登录页。
- `/favicon.png` 返回 `200 image/png`，现场 SHA-256 `c1be3ef7b7466c9031812a9a4040baca48c70bed37cb571919fd0d83134155ad` 与仓库源图标一致；实际浏览器登录页解析到同一路径。
- 输入挂载保持只读；`workspace`、`output`、`archive`、`config` 的文件数与字节数均与部署前一致，`auth.json` 与 `config.yaml` 的 SHA-256 未变化，认证文件仍为 `0600` 和 `1000:1000`。

真实管理员账号没有为验收而执行一次实际密码变更，避免无必要地使用户现有会话失效，也不要求用户向自动化提供当前密码。密码校验、原子替换、写失败保留旧记录、新密码登录和跨会话失效由 `tests/test_auth.py` 与 `tests/test_webui_api.py` 覆盖；真实账号改密仍属于用户主动操作。

## 7. 历史 fnOS 验收边界

2026-08-11 对固定镜像 `sha-887a557` 完成过一次 fnOS 现场验收，范围包括：容器 healthy、镜像 revision、首次初始化、登录/退出/重新登录、匿名业务 API 拒绝、输入只读挂载和关键数据基线未变化。

该记录只证明当时指定 fnOS 环境和镜像的状态。它不证明：

- 当前容器仍在运行；
- 任意 fnOS 版本或设备都兼容；
- ARM64 可以运行；
- 默认 HTTP 服务适合公网；
- GPU/NVENC 已在容器中启用。

新部署按 [fnOS 运行手册](operations/fnos.md) 的最小验收清单重新核对。

## 8. 当前未提供的证据

- ARM64 构建与运行验收；
- TLS、公网部署和外部身份系统集成；
- 可公开复现的性能基准；
- 自动化覆盖率报告；
- 客户采用、用户规模或量化业务收益；
- GitHub Pages 线上工作流与公开 URL 验收（在实际推送并核对前）；
- 许可证兼容性结论。

在补充对应证据前，README 和其他项目介绍不得把这些内容表述为现有能力。

## 2026-10-31 fnOS GPU 接入验收

- 范围：只重建 `solis_timelapse`，使用 `docker compose up -d --no-deps --no-build --pull never solis_timelapse`，未拉取或升级镜像。镜像 ID 始终为 `sha256:97f121bd561ee4ba7a0953cc486cba920c52daad115e67c42d97c6cd02e64593`，OCI revision 为 `6f4a7666951a6a0d678682c6ddc99238ed26d7af`。
- 变更前任务状态为 `completed`；实际容器 User 为空、PID1 为 root、输入 RW、restart 为 `always`、GPU 请求为空。NAS 与本机 Compose 却要求 `1000:1000`、输入 RO、`unless-stopped`。只能确认配置与运行态漂移；现有标签不足以确认责任操作或时间。
- 配置层：本机与 NAS Compose 新增一张 NVIDIA GPU 的标准设备请求和 `compute,utility,video`；目标 Compose 解析通过。没有改主机驱动或其他容器。
- 容器层：`Config.User=1000:1000`，`/proc/1/status` UID/GID 均为 1000，输入 Mounts.RW=false，restart=`unless-stopped`；DeviceRequests 为 nvidia/count=1/capabilities=[[gpu]]；P4 与驱动 580.142 可见，NVIDIA 设备节点及编码驱动库可用。
- 健康与访问控制：容器 healthy，`/api/health` 为 200，匿名 `/api/project` 为 401。
- 持久化：重建前后 workspace/output/archive/config 的文件数和字节数分别保持 `282/2269455`、`0/0`、`0/0`、`2/1089`；认证和配置内容的 SHA-256 相等，仅比较摘要，未输出凭据正文；挂载来源与目标均相同。未遍历真实照片或对原片写入。
- 硬件编码层：应用选择的 FFmpeg 为 imageio-ffmpeg `ffmpeg-linux-x86_64-v7.0.2`，编码器列表无 NVENC。分别用 `testsrc2` 640×360、24 帧请求 `h264_nvenc`/`hevc_nvenc`，均以退出码 8 和 `Unknown encoder` 失败；容器内无系统 FFmpeg。
- 应用路径：在容器临时目录生成 24 张 640×360 合成 JPEG，直接调用镜像内 `src.video_export.export_video`，请求 NVENC。H.264 实际选 `libx264`，产物 8005 字节；H.265 实际选 `libx265`，产物 11055 字节。CPU 回退通过，应用 GPU 编码未通过；没有通过 WebUI 发起真实业务任务，也没有修改保存的导出设置。
- 飞牛 UI 开关未直接核验；DeviceRequests 及编码证据不替代 UI 状态。OpenCL 照片处理未验证。临时样本由测试上下文正常回收，未写入业务输出目录。
- 后续：需授权在镜像中提供带 NVENC 的 FFmpeg 并发布、部署后重验。设备接入成功不应表述成硬件编码已可用。

## 2026-11-01 NVENC 修复与收尾

- 发布源码 `190e62890d93cf8b13143e1676878b16a0f54343`，固定镜像 `sha-190e628`；现场 image ID `sha256:4d62c76574142065fff64049ab1084258d6f4410739d2a5490356ef88d43cabd`，RepoDigest `sha256:c74dcb3c4c5b282289e1c553179ceab2df53f7f47e3de091e1223269874c029e`。Docker CI `41221500534`、Pages CI `41221500506` 成功。
- Dockerfile 安装系统 FFmpeg，通过 `IMAGEIO_FFMPEG_EXE=/usr/bin/ffmpeg` 使用版本 7.1.5-0+deb13u1；构建检查两个 NVENC 编码器。未改宿主驱动或 Toolkit，没有业务 Schema 变更。
- 空闲后仅更新目标服务；PID/用户 `1000:1000`，输入 RO，restart unless-stopped，nvidia/count=1/gpu，healthy。认证、配置摘要与四个持久目录计数/字节均与更新前相同。原镜像及 `compose.rollback-20261101.yaml` 保留；未实际执行回滚，恢复仍需核对数据及功能。
- 容器内应用真实 `export_video` 调用，24 张 640×360 合成 JPEG：H.264 NVENC 选 `h264_nvenc`、6297 字节，H.265 NVENC 选 `hevc_nvenc`、4394 字节；显式 CPU 分别选 libx264/libx265、5880/9941 字节，四个产物均经 FFmpeg 解码成功。另用临时包装器模拟 NVENC 子进程失败，应用从 h264_nvenc 自动回退 libx264 成功，5880 字节。
- 新镜像内运行仓库的 2 项端到端测试：临时合成照片经过扫描、分析、渲染、视频导出、归档，逐阶段原片摘要不变，通过；仅测试进程使用隔离临时目录和本地模式，不改变生产服务配置或任务。全部临时产物正常回收。
- 本地 258 项 Python 测试、compileall、3 项 JS 语法、2 项 Node 契约通过；另认证/API/文档相关 141 项通过。无真实密码读取或变更，部署后健康 200、匿名业务 API 401、改密页跳登录，页面入口源码与合成认证页面测试通过。用户实际改密是可选操作，不作为软件阻塞。
- OpenCL 实测 `(False, OpenCL unavailable)`。它是独立的条件照片 GPU 渲染能力，原有自动 CPU 回退和显式 GPU 不可用报错保持；视频 NVENC 不依赖它，不适用为本次视频接入准入条件。未增加宿主 OpenCL 组件，也不宣称 OpenCL 渲染已通过。
- 旧 Pages `33241296392` 注释确认 Node20 告警存在；已使用官方 configure-pages v6、upload-pages-artifact v5、deploy-pages v5。新版运行检查注释只有 runner 镜像迁移提示，没有 Node20 弃用告警。
- 飞牛复选框仍为 NOT_VERIFIED：Computer Use 在观察浏览器时因无法可靠识别当前 URL 而停止本轮界面操作，未重试或绕过。实际 DeviceRequests 与容器硬件编码均已通过；此项仅剩人工查看界面，不能据 SSH 结果宣称 UI 勾选实测。

后续用户于 2026-11-01 提供 solis_timelapse 详情设置页截图，并明确确认“已经开启了”。截图中“启用显卡支持”已勾选；UI 展示核验据此关闭，证据类型为用户确认及截图，而非 Agent 自动点击或直接操作。

## 8. 更新触发条件

测试数量、标准命令、部署镜像、平台架构、运行时验收或安全边界变化时更新本文件。任何“已通过”结论必须同时记录实际命令、时间点和输出摘要。
