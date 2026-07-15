# Sony 延时摄影处理流水线

面向 Sony ZV-E10 RAW/JPEG 照片序列的 Windows 批处理工具。流水线可完成素材分类、去闪、坏帧剔除、暗帧提亮、自然/通透调色、日照金山色彩强化、预览生成与成果归档。

## 环境准备

1. 安装 Python 3.12。
2. 安装依赖：

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. 如果 Python 不在 `D:\Python3_12\python.exe`，修改根目录各 BAT 中的 Python 路径。

## 目录

```text
00_dist/       待分类的原始照片，可选
01_input/      当前正在处理的分段任务
02_program/    Python 处理程序
03_preview/    自动生成的快速预览
04_output/     剪映等软件导出的最终视频
05_archive/    按处理时间保存的历史成果
```

每个分段使用以下结构：

```text
01_input/<段名>/
  raw/          原始 ARW/JPEG
  work/         处理中间文件
  result/       当前 JPEG 成品序列
  config.json   本段处理参数
```

配置可从 [config.example.json](config.example.json) 复制后修改。

## 使用方法

### 1. 准备素材

任选一种方式：

- 把可能混有多段的素材放入 `00_dist/`，运行 `01_分类.bat`。
- 手动创建 `01_input/<段名>/raw/`，直接放入一段连续素材。

为每段复制一份 `config.example.json` 到分段目录，并改名为 `config.json`。

自动分类不会覆盖已有的 `01_input/segNN/`。如果目标分段已经存在，脚本会停止，避免新旧帧混在一起。

### 2. 检查素材

运行 `00_提取信息.bat`，查看照片数量、分辨率、拍摄时间、曝光和焦距变化。

### 3. 按顺序处理

依次运行需要的步骤。脚本会遍历所有分段，只处理其 `config.json` 中已启用的功能。

| 顺序 | 文件 | 用途 |
|---|---|---|
| 00 | `00_提取信息.bat` | 检查素材与 EXIF |
| 01 | `01_分类.bat` | 按拍摄时间间隔分类 |
| 02 | `02_去闪.bat` | RAW 解码并平滑亮度 |
| 03 | `03_去眩光.bat` | 剔除配置中指定的坏帧 |
| 04 | `04_暗帧提亮.bat` | 修正明显偏暗的跳变帧 |
| 05 | `05_通透调色.bat` | 日出、风光通透调色 |
| 06 | `06_色彩强化.bat` | 日照金山冷暖强化 |
| 07 | `07_自然调色.bat` | 白天自然调色 |
| 08 | `08_清理.bat` | 归档成果并清空当前任务 |

每个图像步骤完成后，JPEG 序列位于 `result/`，快速预览位于 `03_preview/<段名>.mp4`。

### 4. 制作最终视频

将 `result/` 中的 JPEG 序列导入剪映或其他剪辑软件，设置帧率、转场、变速和运镜。最终导出的视频放入 `04_output/`。

### 5. 清理与归档

运行 `08_清理.bat` 前务必确认不再需要 `01_input/` 中的原始照片。脚本会先显示清理计划，并要求输入 `DELETE` 才会继续。

脚本会先把成果归档到：

```text
05_archive/YYYY-MM-DD_HHMMSS/
  manifest.json
  <段名>/
    config.json
    *.jpg
  <段名>.mp4
  output/
```

全部归档校验成功后，脚本才会删除 `01_input/` 下的分段目录并清空 `03_preview/`。`04_output/` 中的最终视频会被归档，但原文件保留。

## 常用配置

- `deflicker.window`：去闪平滑窗口，通常为 11；越大越平滑。
- `deflicker.clip`：限制单帧曝光增益，防止过度修正。
- `deglare.reject`：要剔除的帧名，不含扩展名。
- `grade.style`：`punchy`、`natural` 或 `none`。
- `enhance_golden.level`：`mild`、`medium` 或 `strong`。
- `enhance_golden.core`：色彩强化的起止帧号。
- `preview_fps`：预览视频帧率。

`03_preview` 中的视频默认缩放到 1920 像素宽，仅用于检查，不等同于最终 4K 成片。
