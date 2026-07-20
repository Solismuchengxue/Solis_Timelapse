# Solis_Timelapse

Solis_Timelapse 是面向 RAW/JPEG 照片序列的延时摄影处理工具。它可以识别连续拍摄段、分析亮度与异常帧、完成去闪和风光调色、导出 MP4 视频，也可以合成包围曝光 HDR 照片。

原始照片始终按只读素材处理。工作文件、成片和归档分别保存，不会移动、改名或覆盖源照片。

## 项目介绍

- 自动扫描照片并按拍摄时间分段。
- 显示代表帧、缩略图和亮度变化曲线。
- 支持坏帧排除、分段拆分、合并和排序。
- 提供自然、通透、色彩强化和霞光增强等处理方案。
- 照片渲染会按设备性能自动并行处理；检测到 NVIDIA NVENC 时，预览和最终 MP4 会自动使用显卡编码。
- 支持 2–9 张照片自动对齐、曝光融合或辐射 HDR，并输出 JPEG 或 16 位 TIFF。
- 导出 4K MP4，并按日期时间归档原始照片与最终成片。
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

在“设置 → 处理 → RAW/JPEG 渲染设备”中可选择“自动（推荐）”“CPU”或“GPU”。自动模式会根据配方选择实测更快的设备：普通调色使用 CPU 并行，启用霞光增强时使用 OpenCV OpenCL GPU；没有兼容 GPU 时回退 CPU。手动选择会强制使用指定设备。RAW 解码仍由 CPU 完成。渲染会自动选择保守的并行数，避免占满内存或显存。预览和导出视频会优先使用 NVIDIA NVENC，并在显卡、驱动或容器运行环境不支持时自动回退到 CPU 编码。实际使用的处理设备、帧处理并行数和视频编码器会显示在任务日志中。

页面右上角可以切换白天、夜间、跟随系统主题，也可以切换中文或 English。选择结果保存在当前浏览器中。

“归档与日志”会显示目录选择、扫描、分段、渲染、导出、归档和清理等操作，启动命令行窗口会同步输出。可直接在日志区域选择 `INFO` 或 `DEBUG`：日常使用建议 `INFO`；排查问题时选择 `DEBUG`，会额外记录逐帧进度、处理参数和异常堆栈。

### HDR 合成

1. 在工作台打开“帧检查”的“多选”，选择同一分段中的 2–9 张照片。
2. 点击“发送到 HDR”，进入独立的 HDR 合成页面。
3. 默认使用“曝光融合”，适合大多数包围曝光照片且不要求快门 EXIF；“辐射 HDR”会按快门时间恢复辐射信息，因此每张照片都必须有有效快门 EXIF。
4. 根据画面调整自动对齐、运动抑制、融合权重或色调映射参数，然后开始合成。
5. 合成结果保存在 `output/hdr/`；JPEG 适合直接查看，16 位 TIFF 更适合继续精修。

HDR 最适合同一机位、短时间内拍摄的包围曝光。直接选择延时序列中时间间隔较大的照片，云层、树叶或人物移动可能产生重影；此时应提高运动抑制，或改用时间更接近的照片。

## 飞牛 fnOS Docker 部署

### 先看镜像说明

项目通过 GitHub Actions 自动构建并发布 AMD64 镜像，飞牛默认直接拉取：

```text
ghcr.io/solismuchengxue/solis_timelapse:latest
```

不要在 Docker Hub 下载同名的第三方镜像。`latest` 对应主分支最新构建，版本发布还会生成 `v1.0.0` 这类固定标签。镜像由公开仓库的 `Dockerfile` 构建，可在 GitHub 的 Actions 和 Packages 页面核对构建记录与来源。

当前官方 Package 已设为 `Public`，飞牛可以匿名拉取，无需配置 GitHub 账号或令牌。自行 Fork 并发布新镜像时，应在对应 GitHub Packages 设置中确认可见性。

### 1. 安装 Docker 并确认路径

1. 在飞牛应用中心安装并打开“Docker”。飞牛 Docker 页面内置 Compose 项目管理，不需要另外下载 `docker-compose` 程序。
2. 在文件管理器中找到照片目录，打开“详细信息”并复制原始路径。不要根据共享文件夹名称猜路径。
3. 本文以以下路径为例：

```text
照片目录：/vol1/1000/照片/延时摄影
应用目录：/vol1/1000/solis_timelapse
```

`/vol1/1000` 只是示例。存储池编号和用户 UID 不同时，必须替换为飞牛显示的真实路径；不要求存在 `/vol1/1000/docker`。

### 2. 准备 Compose 和数据目录

从项目仓库下载源码 ZIP：

```text
https://github.com/Solismuchengxue/Solis_Timelapse
```

默认使用 GHCR 镜像时，只需要把压缩包中的 `compose.yaml` 和 `.env.example` 上传到 `/vol1/1000/solis_timelapse/app`，不需要把完整源码放到飞牛。

推荐目录结构如下：

```text
/vol1/1000/solis_timelapse/
  app/                    # Compose 项目目录
    compose.yaml
    .env.example
  workspace/              # 分析、缩略图、渲染帧和任务状态
  output/                 # 导出的 MP4 和 HDR 照片
  archive/                # 已归档的原片、配方和最终成片
  config/                 # WebUI 保存的本地设置
```

`app` 只保存部署配置；另外四个数据目录不要放进 `app`，更新 Compose 时也不要删除。

### 3. 创建 `.env`

将 `app/.env.example` 复制为 `app/.env`，修改为实际值：

```dotenv
INPUT_PATH=/vol1/1000/照片/延时摄影
APP_ROOT=/vol1/1000/solis_timelapse
PUID=1000
PGID=1000
```

- `INPUT_PATH`：原始照片目录。容器内固定挂载为 `/media/input:ro`，其中 `ro` 表示只读。
- `APP_ROOT`：上一步创建的应用数据根目录，不是 `app` 源码目录。
- `PUID`、`PGID`：用于运行容器的飞牛用户 UID 和 GID，必须对四个数据目录有写权限，并对照片目录有读取权限。

容器使用镜像内的默认配置启动。用户在 WebUI 保存设置后，会在宿主机生成 `${APP_ROOT}/config/config.yaml`；目录初次部署时为空是正常的。Windows 本地开发使用的 `config/local.yaml` 不会用于 Docker。

通过 SSH 执行下面命令可以查询当前用户的 UID 和 GID：

```bash
id
```

输出中的 `uid=数字` 填入 `PUID`，`gid=数字` 填入 `PGID`。示例管理员通常是 `1000:1000`，但应以实际输出为准。

没有使用 SSH 时，可以在电脑上编辑 `.env.example`，另存为文件名 `.env` 后上传到 `app`。注意不能变成 `.env.txt`。

### 4. 设置目录权限

使用文件管理器创建 `workspace`、`output`、`archive`、`config`，并给 `PUID/PGID` 对应用户读写权限。照片目录只需要读取权限。

遇到 `Permission denied` 时，可通过 SSH 按实际 UID/GID 修复：

```bash
sudo chown -R 1000:1000 /vol1/1000/solis_timelapse/workspace
sudo chown -R 1000:1000 /vol1/1000/solis_timelapse/output
sudo chown -R 1000:1000 /vol1/1000/solis_timelapse/archive
sudo chown -R 1000:1000 /vol1/1000/solis_timelapse/config
sudo chmod -R u+rwX /vol1/1000/solis_timelapse/workspace /vol1/1000/solis_timelapse/output /vol1/1000/solis_timelapse/archive /vol1/1000/solis_timelapse/config
```

这里的 `1000:1000` 和路径都必须替换为自己的实际值。不要对照片目录执行递归写权限修改，Solis_Timelapse 不需要写入原片目录。

### 5. Compose 配置说明

仓库自带的 `compose.yaml` 可以直接使用：

```yaml
services:
  solis_timelapse:
    image: ghcr.io/solismuchengxue/solis_timelapse:latest
    pull_policy: always
    container_name: solis_timelapse
    user: "${PUID:?请在 .env 中设置飞牛用户 UID}:${PGID:?请在 .env 中设置飞牛用户 GID}"
    environment:
      SOLIS_CONTAINER: "1"
      PYTHONUNBUFFERED: "1"
    ports:
      - "9501:9501"
    volumes:
      - "${INPUT_PATH:?请在 .env 中设置照片目录}:/media/input:ro"
      - "${APP_ROOT:?请在 .env 中设置应用数据目录}/workspace:/media/workspace"
      - "${APP_ROOT:?请在 .env 中设置应用数据目录}/output:/media/output"
      - "${APP_ROOT:?请在 .env 中设置应用数据目录}/archive:/media/archive"
      - "${APP_ROOT:?请在 .env 中设置应用数据目录}/config:/data/config"
    restart: unless-stopped
```

关键配置含义：

- `image`：从 GitHub Container Registry 拉取项目官方镜像。
- `pull_policy: always`：每次创建或更新容器前检查 `latest` 是否有新版本。
- `user`：使用飞牛真实 UID/GID 运行，不使用 root。
- `9501:9501`：左边是飞牛端口，右边是容器端口。如果飞牛的 9501 已占用，只把左边改成例如 `19501:9501`，访问地址也改为 `http://飞牛IP:19501/`。
- 五条 `volumes`：把照片、工作区、输出、归档和配置放在宿主机。不要修改冒号右侧的容器路径。
- `restart: unless-stopped`：飞牛或 Docker 重启后自动恢复服务，除非用户主动停止容器。

`${变量:?提示}` 表示变量必填。`.env` 缺少任何路径或 UID/GID 时，Compose 会在创建容器前直接报错，避免把数据误写到错误目录。

### 6. 飞牛图形界面部署

不同 fnOS 版本的按钮名称可能略有差异，操作逻辑相同：

1. 打开“Docker” → “Compose”。
2. 点击“新建项目”或“导入项目”。
3. 项目名称填写 `solis_timelapse`。
4. 项目路径选择 `/vol1/1000/solis_timelapse/app`，该目录内必须同时存在 `compose.yaml` 和 `.env`。
5. 如果界面提供 Compose 编辑器，确认显示的是仓库中的 `compose.yaml` 内容；某些版本没有自动识别 `compose.yaml` 时，可新建 Compose 项目并把上面的 YAML 完整粘贴进去。
6. 点击“部署”“创建”或“确定”。第一次会从 GHCR 下载已经构建好的镜像，不会在飞牛上安装 Python 依赖。
7. 在“容器”页面确认 `solis_timelapse` 状态为“运行中”或“健康”。
8. 浏览器访问 `http://飞牛IP:9501/`。

进入 WebUI 后，容器只能浏览 `.env` 中 `INPUT_PATH` 对应的照片目录。页面里看到的是容器路径 `/media/input`，不能浏览飞牛上的其他目录，这是只读边界的正常表现。

### 7. SSH 命令部署

已经启用 SSH 时，可直接执行：

```bash
cd /vol1/1000/solis_timelapse/app

# 检查 .env 是否被正确读取，并展开最终 Compose 配置
docker compose config

# 拉取 GitHub Actions 发布的最新镜像
docker compose pull

# 在后台创建并启动容器
docker compose up -d

# 查看容器状态和健康状态
docker compose ps

# 查看最近日志；Ctrl+C 只退出日志，不会停止容器
docker compose logs --tail=100 -f
```

如果 `docker compose config` 报 `INPUT_PATH`、`APP_ROOT`、`PUID` 或 `PGID` 未设置，说明 `.env` 不存在、文件名错误，或没有放在 `compose.yaml` 同一目录。先修正，不要跳过检查直接启动。

### 8. 日常管理

在 `app` 目录执行：

```bash
# 查看状态
docker compose ps

# 查看日志
docker compose logs --tail=200

# 停止但保留容器
docker compose stop

# 再次启动
docker compose start

# 重启应用
docker compose restart

# 删除容器和项目网络；宿主机绑定的数据目录不会删除
docker compose down
```

本项目使用宿主机目录绑定挂载。`docker compose down` 只会移除容器和项目网络，不会删除 `workspace`、`output`、`archive` 和 `config`；不要在文件管理器中手动删除这四个目录。

### 9. 更新 Solis_Timelapse

GitHub Actions 发布新版镜像后，在飞牛 Compose 页面执行“拉取/重新部署”，或通过 SSH 执行：

```bash
cd /vol1/1000/solis_timelapse/app
docker compose config
docker compose pull
docker compose up -d
docker compose ps
```

仅执行 `docker compose restart` 不会拉取新镜像。必须先执行 `docker compose pull`，再执行 `docker compose up -d`。宿主机上的 `workspace`、`output`、`archive` 和 `config` 不会因更新镜像而丢失。

### 10. 本地构建备用方案

GHCR 暂时无法访问，或需要测试未发布源码时，才使用仓库中的 `compose.build.yaml`。此方式必须把完整源码上传到 `app`，然后执行：

```bash
cd /vol1/1000/solis_timelapse/app
docker compose -f compose.build.yaml config
docker compose -f compose.build.yaml up -d --build
```

本地构建会在飞牛上下载 `python:3.12-slim`、安装 Python 依赖并生成 `solis_timelapse:local`，通常明显慢于直接拉取 GHCR 镜像。

### 11. 常见问题

**拉取镜像时提示 denied 或 unauthorized**

先确认镜像已经由 GitHub Actions 成功发布，并在 GitHub Packages 中设置为 `Public`。公开镜像不需要执行 `docker login`。

**拉取 GHCR 很慢或连接失败**

这是飞牛到 `ghcr.io` 的网络问题，不是照片处理问题。可稍后重试；长期无法访问时使用上一节的本地构建备用方案。不要把来源不明的镜像代理地址写进 Compose。

**容器启动后立即退出**

先运行 `docker compose logs --tail=200`。最常见原因是数据目录不可写、照片目录不可读，或 `.env` 路径不存在。入口程序会在启动前检查这些挂载并输出具体目录。

**打开 `飞牛IP:9501` 没有页面**

运行 `docker compose ps` 检查容器是否运行和端口是否为 `0.0.0.0:9501->9501/tcp`。如果端口冲突，将 Compose 中的 `9501:9501` 改成 `19501:9501` 后重新执行 `docker compose up -d`。

**WebUI 中看不到照片**

检查 `.env` 的 `INPUT_PATH` 是否为真实绝对路径，并确认该用户有读取权限。修改 `.env` 后不能只点“重启”，需要重新创建容器：

```bash
docker compose up -d --force-recreate
```

**没有 NVIDIA GPU 能否运行**

可以。默认 Compose 不要求显卡，照片处理和视频编码会自动使用 CPU。需要在容器中使用 NVENC 时，飞牛宿主机还必须具备 NVIDIA 驱动和 NVIDIA Container Toolkit，并额外把 GPU 暴露给容器；当前默认 Compose 没有开启该配置。

## 输出与归档

当前导出的 MP4 保存在 `output/`，HDR 照片保存在 `output/hdr/`。归档完成后，成果结构如下：

```text
archive/YYYY-MM-DD_HHMMSS/
  manifest.json
  project.json
  Segment 01/
    originals/
      *.ARW / *.JPG
    recipe.json
    analysis.json
  output/
    Segment 01.mp4
```

导出和归档只作用于当前分段。归档会原样复制当前分段的 ARW/JPEG 源照片、最终导出的 MP4、处理配方和分析数据，并校验文件大小与 SHA-256；不会把处理产生的 JPEG 或低码率预览视频作为归档成果。归档不会清理当前项目、输出视频或外部原始照片。

归档记录会显示焦距、拍摄日期、拍摄时间和照片 EXIF 中的 GPS 位置；没有 GPS 标签时显示“位置未知”。单条删除和全部删除都会永久删除对应归档中的原始照片与最终成片，操作前会再次确认。

“清除当前项目”只清除工作区中的当前项目状态、处理结果和 `output/` 中的当前输出，不会自动归档，也不会删除源照片及 `archive/` 中的文件。

## 网络安全

WebUI 的 `9501` 端口目前没有登录认证，只应在可信局域网中使用，**不要直接暴露到公网**。需要远程访问时，请使用 VPN，或在带身份认证的反向代理后访问。
