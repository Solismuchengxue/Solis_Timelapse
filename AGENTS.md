# Solis_Timelapse 项目规则

本文件适用于整个仓库。修改前先阅读 `README.md`、`DESIGN.md`、相关 `docs/`、被 Git 忽略的 `TODO.md`、`DEVLOG.md`、`PLAYBOOK.md` 和相关测试，并区分已跟踪源码、长期共享文档、外部素材与本机运行数据。

## 数据与安全边界

- 用户选择的原始照片目录始终视为只读。不得移动、改名、覆盖或删除源照片，也不得让源目录与 `workspace/`、`output/`、`archive/` 相互包含。
- 源码与运行数据保持分离。`.venv/`、`config/local.yaml`、`.env`、`workspace/`、`output/`、`archive/`、日志和缓存不得作为源码提交。
- 不得提交真实照片、视频、归档、本机绝对路径、本机配置、凭据、密钥或 Token。文件系统测试必须使用临时目录和合成数据。
- `TODO.md`、`DEVLOG.md` 与 `PLAYBOOK.md` 继续仅在本机维护并由 Git 忽略；`README.md` 与 `README_EN.md` 只保留用户可见的项目介绍、安装、使用方法和必要限制；`DESIGN.md` 与 `docs/` 保存长期共享的设计、架构、运行和验证事实。

## 修改与迁移纪律

- 使用“快速扫描 → 最小变更 → 立即验证 → 继续或回退”，保留用户现有改动，不做无关清理。
- 迁移期间只处理仓库连续性、文档边界和载荷核对，不得顺手修改产品功能、依赖、测试行为、README 用户内容或部署配置。
- 迁移载荷默认以 Git 跟踪文件为准。本机虚拟环境、实例锁、任务状态、缓存和运行产物应在目标位置重建或重新生成，不随源码迁移。
- 未经用户明确批准，不得暂存、提交、推送、移动、复制、删除、重置或丢弃文件。

## 文档同步

- 用户可见行为、安装或使用方式变化时同步更新 `README.md` 与 `README_EN.md`。
- 架构、组件职责、集成对象、运行模式或数据边界变化时更新 `DESIGN.md` 与 `docs/architecture.md`。
- fnOS 镜像、目录、Compose、认证重置、升级或排障方式变化时更新 `docs/operations/fnos.md`，并检查中英文 README 的快速入口。
- 静态演示不得复制或维护第二套 WebUI 源码；`demo/build_site.py` 只能从 `webui/` 白名单组装站点，`.demo-site/` 必须保持 Git 忽略且不得提交。
- WebUI 结构、核心 API 路由或响应形状变化时，同步更新 `demo/mock_api.js`、静态演示契约与相关架构/验证文档。
- 测试命令、覆盖范围、现场验收或已验证/未验证边界变化时更新 `docs/verification.md`。
- 当前行动、优先级、阻塞项和下一步写入本机 `TODO.md`，完成或失效后及时移除。
- 项目实现事实、故障、验证证据和演进过程写入本机 `DEVLOG.md`。
- 可跨项目复用的方法写入本机 `PLAYBOOK.md`。
- 数据安全边界、协作规则或验证要求变化时更新本文件。

## 验证要求

按改动范围先运行最小相关测试；产品代码变更完成前执行：

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m compileall -q src webui docker demo tests
node --check webui\app.js
node --check webui\ui_prefs.js
node --check demo\mock_api.js
node tests\test_webui_contracts.js
node tests\test_demo_mock.js
git diff --check
```

文档或迁移边界变更至少检查最终 diff、`git diff --check`、中英文入口与相关 Markdown 路径、`git check-ignore -v` 和 `git status`，并确认 `TODO.md`、`DEVLOG.md`、`PLAYBOOK.md`、运行数据、敏感配置与真实媒体均未进入暂存区。
