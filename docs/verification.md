# 验证与证据

- 状态：accepted
- 最近核对：2026-08-11
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
.venv\Scripts\python.exe -m compileall -q src webui docker tests
node --check webui\app.js
node --check webui\ui_prefs.js
node tests\test_webui_contracts.js
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

截至 2026-08-11，测试源码包含 243 个 Python `unittest` 测试方法。这个数字描述当前测试清单，不代表任意未来工作区已经运行通过。

| 测试文件 | 主要覆盖 |
| --- | --- |
| `tests/test_archive.py` | 归档集合、Manifest、哈希、路径和失败行为 |
| `tests/test_auth.py` | scrypt 密码记录、初始化、验证、损坏状态和原子写入 |
| `tests/test_config_io.py` | 默认配置、本机覆盖和配置写入 |
| `tests/test_docker_contracts.py` | Compose、固定 GHCR 镜像、AMD64 工作流、挂载、认证文档 |
| `tests/test_end_to_end.py` | 合成 24 帧序列的扫描、处理、导出、归档与源文件哈希不变 |
| `tests/test_hdr_merge.py` | HDR 对齐、融合、辐射模式、输出和参数边界 |
| `tests/test_image_ops.py` | 解码、亮度、调色、去闪、设备选择和数值安全 |
| `tests/test_image_pipeline.py` | 分析、异常候选、渲染、源身份、并行和原子发布 |
| `tests/test_media_catalog.py` | 递归扫描、EXIF、分段、同名文件和时间线操作 |
| `tests/test_project_store.py` | 项目状态与原子持久化 |
| `tests/test_task_manager.py` | 单任务、进度、日志、取消、恢复和状态限制 |
| `tests/test_video_export.py` | H.264/H.265、NVENC、回退、取消、进度和原子输出 |
| `tests/test_webui_api.py` | API、路径边界、认证、任务和媒体访问 |
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
| 容器业务路由需要登录 | 初始化、登录、退出、会话、API 和媒体路由测试 |

## 5. 历史 fnOS 验收边界

2026-08-11 对固定镜像 `sha-887a557` 完成过一次 fnOS 现场验收，范围包括：容器 healthy、镜像 revision、首次初始化、登录/退出/重新登录、匿名业务 API 拒绝、输入只读挂载和关键数据基线未变化。

该记录只证明当时指定 fnOS 环境和镜像的状态。它不证明：

- 当前容器仍在运行；
- 任意 fnOS 版本或设备都兼容；
- ARM64 可以运行；
- 默认 HTTP 服务适合公网；
- GPU/NVENC 已在容器中启用。

新部署按 [fnOS 运行手册](operations/fnos.md) 的最小验收清单重新核对。

## 6. 当前未提供的证据

- ARM64 构建与运行验收；
- TLS、公网部署和外部身份系统集成；
- 可公开复现的性能基准；
- 自动化覆盖率报告；
- 客户采用、用户规模或量化业务收益；
- 持续在线演示或正式 Release 验收；
- 许可证兼容性结论。

在补充对应证据前，README 和作品集材料不得把这些内容表述为现有能力。

## 7. 更新触发条件

测试数量、标准命令、部署镜像、平台架构、运行时验收或安全边界变化时更新本文件。任何“已通过”结论必须同时记录实际命令、时间点和输出摘要。
