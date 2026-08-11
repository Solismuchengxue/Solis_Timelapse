# fnOS Docker 运行手册

- 状态：accepted
- 最近核对：2026-08-11
- 适用范围：使用 GitHub Actions 发布的 AMD64 GHCR 镜像部署到飞牛 fnOS

> 本手册包含部署、更新、登录重置和排障步骤。默认服务使用局域网明文 HTTP，不要直接暴露到公网。

## 1. 镜像与部署方式

项目只通过 GitHub Actions 构建并发布 AMD64 镜像。fnOS 只拉取已发布的 GHCR 镜像，不在 NAS 上本地构建：

```text
ghcr.io/solismuchengxue/solis_timelapse:sha-887a557
```

不要从 Docker Hub 下载同名第三方镜像。Compose 固定到 `sha-887a557`，不会自动漂移到后续构建。镜像由公开仓库的 `Dockerfile` 构建，可以在 GitHub Actions 和 Packages 页面核对来源。

当前 Package 为 Public，可以匿名拉取。自行 Fork 并发布新镜像时，需要在对应 GitHub Packages 设置中确认可见性。

## 2. 安装 Docker 并确认路径

1. 在飞牛应用中心安装并打开 Docker。fnOS Docker 页面内置 Compose 项目管理，不需要另行安装 `docker-compose`。
2. 在文件管理器中找到照片目录，打开详细信息并复制原始路径，不要根据共享文件夹名称猜测。
3. 以下路径只是示例：

```text
照片目录：/vol1/1000/照片/延时摄影
应用目录：/vol1/1000/Solis_Timelapse
```

存储池编号和用户 UID 不同时，必须替换为设备上的真实值。

## 3. 准备 Compose 和数据目录

从仓库下载 `compose.yaml` 和 `.env.example`，上传到 `/vol1/1000/Solis_Timelapse`。使用默认 GHCR 镜像时不需要上传完整源码。

```text
/vol1/1000/Solis_Timelapse/
  compose.yaml
  .env.example
  workspace/
  output/
  archive/
  config/
```

四个数据目录与 Compose 位于应用根目录。更新 Compose 时不要删除 `workspace`、`output`、`archive` 或 `config`。

## 4. 创建 `.env`

把 `.env.example` 复制为 `.env`，并修改为真实值：

```dotenv
INPUT_PATH=/vol1/1000/照片/延时摄影
APP_ROOT=/vol1/1000/Solis_Timelapse
PUID=1000
PGID=1000
```

- `INPUT_PATH`：原始照片目录，容器内固定挂载为 `/media/input:ro`。
- `APP_ROOT`：Compose 和四个应用数据目录所在的根目录。
- `PUID`、`PGID`：容器运行用户，必须能读取照片并写入四个数据目录。

通过 SSH 执行 `id` 可以查询当前用户的 UID 和 GID。示例值 `1000:1000` 不能替代实际查询。

用户在 WebUI 保存设置后会生成 `${APP_ROOT}/config/config.yaml`。首次初始化管理员后会生成 `${APP_ROOT}/config/auth.json`。Windows 本地使用的 `config/local.yaml` 不用于 Docker。

## 5. 设置目录权限

通过文件管理器创建 `workspace`、`output`、`archive` 和 `config`，并授予 PUID/PGID 对应用户读写权限。照片目录只需要读取权限。

遇到 `Permission denied` 时，可以通过 SSH 按实际 UID/GID 修复应用数据目录：

```bash
sudo chown -R 1000:1000 /vol1/1000/Solis_Timelapse/workspace
sudo chown -R 1000:1000 /vol1/1000/Solis_Timelapse/output
sudo chown -R 1000:1000 /vol1/1000/Solis_Timelapse/archive
sudo chown -R 1000:1000 /vol1/1000/Solis_Timelapse/config
sudo chmod -R u+rwX /vol1/1000/Solis_Timelapse/workspace /vol1/1000/Solis_Timelapse/output /vol1/1000/Solis_Timelapse/archive /vol1/1000/Solis_Timelapse/config
```

替换示例 UID/GID 和路径。不要对照片目录递归授予写权限。

## 6. Compose 配置说明

仓库的 `compose.yaml` 使用以下关键配置：

```yaml
name: solis_timelapse

services:
  solis_timelapse:
    image: ghcr.io/solismuchengxue/solis_timelapse:sha-887a557
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

- `name` 固定 Compose 项目名为 `solis_timelapse`。
- `pull_policy: always` 会在创建或更新容器前检查固定标签。
- `user` 使用实际 UID/GID，而不是 root。
- `9501:9501` 的左侧是 fnOS 端口；冲突时只修改左侧。
- 输入挂载保持只读，四个应用目录显式持久化。
- `${变量:?提示}` 让缺少变量的配置在创建容器前失败。

## 7. 飞牛图形界面部署

不同 fnOS 版本的按钮名称可能略有差异，操作逻辑一致：

1. 打开“Docker” → “Compose”。
2. 新建或导入项目，项目名称填写 `solis_timelapse`。
3. 项目路径选择 `/vol1/1000/Solis_Timelapse`，确认同目录存在 `compose.yaml` 和 `.env`。
4. 如果界面没有自动识别文件，把仓库中的 Compose YAML 完整粘贴到编辑器。
5. 点击部署。第一次会从 GHCR 拉取已构建镜像，不会在 fnOS 安装 Python 依赖。
6. 在容器页面确认 `solis_timelapse` 为运行中或健康。
7. 浏览器访问 `http://飞牛IP:9501/`。首次访问会显示“初始化管理员”；后续访问显示登录页。

容器中的照片路径是 `/media/input`，不能浏览 fnOS 上的其他目录，这是预期的只读边界。

## 8. SSH 命令部署

已启用 SSH 时，在应用根目录执行：

```bash
cd /vol1/1000/Solis_Timelapse
docker compose config
docker compose pull
docker compose up -d
docker compose ps
docker compose logs --tail=100 -f
```

`docker compose config` 如果报告 `INPUT_PATH`、`APP_ROOT`、`PUID` 或 `PGID` 未设置，先修正 `.env`，不要跳过检查直接启动。

## 9. 日常管理

```bash
cd /vol1/1000/Solis_Timelapse

docker compose ps
docker compose logs --tail=200
docker compose stop
docker compose start
docker compose restart
docker compose down
```

`docker compose down` 移除容器和项目网络，但不会删除宿主机绑定的 `workspace`、`output`、`archive` 和 `config`。不要把“容器删除”误解为“数据目录可以删除”。

## 10. 更新 Solis_Timelapse

GitHub Actions 发布新镜像后，先把 `compose.yaml` 的 `image` 明确改为新版本的 `sha-<短提交>` 标签，然后执行：

```bash
cd /vol1/1000/Solis_Timelapse
docker compose config
docker compose pull
docker compose up -d
docker compose ps
```

仅执行 `docker compose restart` 不会拉取新镜像。宿主机上的四个数据目录不会因为更新镜像而丢失，但更新前仍应保留自己的备份和回退信息。

## 11. 管理员登录与密码重置

登录保护只在 fnOS/Docker 容器模式启用；Windows 双击 `run.bat` 的本地模式保持原有的免登录行为。

管理员密码不会以明文保存。`config/auth.json` 保存加盐哈希和会话密钥，无法从文件中读回原密码。

忘记密码时，在可信 fnOS 管理环境执行：

```bash
cd /vol1/1000/Solis_Timelapse
mv config/auth.json config/auth.json.bak
docker compose restart
```

重新打开页面并创建管理员。确认新账号可以登录后，再自行决定是否删除备份。重置认证不会删除 `workspace`、`output`、`archive` 或 `config/config.yaml`。由于没有一次性初始化码，重置后的首次管理员创建必须在可信局域网中进行。

## 12. 常见问题

### 拉取镜像提示 denied 或 unauthorized

确认镜像已经由 GitHub Actions 发布，并在 GitHub Packages 中设为 Public。公开镜像不需要 `docker login`。

### 拉取 GHCR 很慢或连接失败

这是 fnOS 到 `ghcr.io` 的网络问题。保留当前正常容器，检查 Packages 状态和设备网络后再重试。不要改用来源不明的镜像代理。

### 容器启动后立即退出

执行 `docker compose logs --tail=200`。常见原因是数据目录不可写、照片目录不可读或 `.env` 路径不存在。入口程序会在启动前检查挂载。

### 打开 `飞牛IP:9501` 没有页面

执行 `docker compose ps`，确认容器运行且端口为 `0.0.0.0:9501->9501/tcp`。端口冲突时改为 `19501:9501` 并重新执行 `docker compose up -d`。

### WebUI 中看不到照片

确认 `INPUT_PATH` 是真实绝对路径且运行用户有读取权限。修改 `.env` 后使用：

```bash
docker compose up -d --force-recreate
```

### 没有 NVIDIA GPU 能否运行

可以。默认 Compose 不要求 GPU，照片处理和视频编码可以使用 CPU。容器 NVENC 还需要宿主机 NVIDIA 驱动、NVIDIA Container Toolkit 和额外 GPU 暴露配置；默认 Compose 不包含这些配置。

## 13. 网络安全

fnOS 的 `9501` 仍是明文 HTTP，只适合可信局域网。不要直接暴露到公网，也不要仅依赖应用内登录代替 TLS、网络访问控制、系统权限和备份。

需要远程访问时，应在项目外使用可信反向代理、HTTPS 和额外访问控制。本项目当前不提供这些基础设施配置。

## 14. 最小验收清单

- `docker compose config` 能正确展开路径、UID/GID 和固定镜像。
- 容器状态为 healthy。
- 匿名访问健康接口成功，未登录业务 API 被拒绝。
- 首次初始化、登录、退出和重新登录均正常。
- `/media/input` 保持只读挂载。
- `workspace`、`output`、`archive` 和 `config` 重建容器后仍然存在。
- 更新或重置认证前后的源照片数量和哈希不发生变化。

历史环境验收不能替代新设备验收。每次迁移、镜像变更或目录调整后都应重新执行适用检查。
