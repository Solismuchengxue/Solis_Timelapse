# Solis_Timelapse

Solis_Timelapse 是面向 RAW/JPEG 照片序列的延时摄影处理工具。它可以识别连续拍摄段、分析亮度与异常帧、完成去闪和风光调色，并导出 MP4 视频。

原始照片始终按只读素材处理。工作文件、成片和归档分别保存，不会移动、改名或覆盖源照片。

## 项目介绍

- 自动扫描照片并按拍摄时间分段。
- 显示代表帧、缩略图和亮度变化曲线。
- 支持坏帧排除、分段拆分、合并和排序。
- 提供自然、通透、日照金山等处理方案。
- 导出 4K MP4，并按日期时间归档 JPEG 序列与成片。
- 提供白天、夜间、跟随系统三种主题。
- 支持中文和 English 界面即时切换。
- 支持 Windows 本地运行和飞牛 fnOS Docker 部署。

## Windows 使用方法

1. 安装 Python 3.12，并在安装时勾选 `Add Python to PATH`。
2. 双击项目根目录的 `run.bat`。
3. 首次启动会创建 `.venv` 并安装依赖。
4. 浏览器打开 `http://127.0.0.1:9501/` 后即可使用。

以后再次双击 `run.bat` 即可启动。关闭启动窗口会停止 WebUI。

## WebUI 使用方法

在工作台中依次完成以下操作：

1. 选择照片目录并扫描素材。
2. 检查自动识别的分段及异常帧。
3. 为每一段选择处理方案和强度。
4. 开始处理并检查预览。
5. 选择一个分段，设置帧率、分辨率和编码格式后导出视频。
6. 确认结果完整后归档当前分段。

“选择要合并分段”只用于合并连续分段；开启时会先勾选当前分段，再选择两个或以上连续分段并点击“合并”。渲染、导出、预览和归档始终只作用于当前分段。

右下角“最终导出”可以展开或折叠。展开后可设置输出参数并渲染、导出、预览或归档当前分段；折叠后只保留任务状态和进度。

页面右上角可以切换白天、夜间、跟随系统主题，也可以切换中文或 English。选择结果保存在当前浏览器中。

“处理历史与日志”会显示目录选择、扫描、分段、渲染、导出、归档和清理等操作，启动命令行窗口会同步输出。可在“设置 → 处理 → 日志级别”选择 `INFO` 或 `DEBUG`：日常使用建议 `INFO`；排查问题时选择 `DEBUG`，会额外记录逐帧进度、处理参数和异常堆栈。

## 飞牛 fnOS Docker 部署

部署前需要安装 Docker Compose，并准备照片目录和应用数据目录。下面的 `/vol1/1000` 只是示例，请在飞牛文件管理器中打开目录的“详细信息”，使用“复制原始路径”取得实际路径。无需预设名为 `docker` 的中间目录。

### 1. 配置路径和权限

将 `.env.example` 复制为 `.env`，按实际环境修改：

```dotenv
INPUT_PATH=/vol1/1000/照片/延时摄影
APP_ROOT=/vol1/1000/solis_timelapse
PUID=1000
PGID=1000
```

- `INPUT_PATH`：照片素材目录，只读挂载到容器的 `/media/input:ro`。
- `APP_ROOT`：应用数据根目录，其下保存工作区、成片、归档和配置。
- `PUID`、`PGID`：容器运行用户。通过 SSH 执行 `id your_username` 查询实际 UID 和 GID。

在 `APP_ROOT` 下创建以下目录，并确保 `PUID`、`PGID` 对应的用户具有读写权限：

```text
/vol1/1000/solis_timelapse/
  workspace/
  output/
  archive/
  config/
```

所有持续增长的数据都挂载在宿主机：

```text
${INPUT_PATH}             -> /media/input:ro
${APP_ROOT}/workspace     -> /media/workspace
${APP_ROOT}/output        -> /media/output
${APP_ROOT}/archive       -> /media/archive
${APP_ROOT}/config        -> /data/config
```

### 2. 启动

在项目目录执行：

```bash
docker compose up -d --build
```

启动后访问 `http://飞牛IP:9501/`。容器模式只能浏览 `INPUT_PATH` 内的目录，不能访问其外部路径。

### 3. 更新

更新项目文件后，在项目目录重新执行：

```bash
docker compose up -d --build
```

`workspace`、`output`、`archive` 和 `config` 均位于宿主机，因此重新构建或重启容器不会清空这些数据。

## 输出与归档

当前导出的 MP4 保存在 `output/`。归档完成后，成果结构如下：

```text
archive/YYYY-MM-DD_HHMMSS/
  manifest.json
  01_段名/
    *.jpg
  output/
    01_段名.mp4
```

导出和归档只作用于当前分段。归档会复制当前分段的 JPEG 序列和 MP4，不会清理当前项目、输出视频或外部原始照片。

“清除当前项目”只清除工作区中的当前项目状态和处理结果，不会自动归档，也不会删除输出目录和归档目录中的文件。

## 网络安全

WebUI 的 `9501` 端口目前没有登录认证，只应在可信局域网中使用，**不要直接暴露到公网**。需要远程访问时，请使用 VPN，或在带身份认证的反向代理后访问。
