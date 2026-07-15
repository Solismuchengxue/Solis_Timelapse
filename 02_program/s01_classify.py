"""01 分类:把 00_dist 里的素材按拍摄时间间隔切段(间隔 > 阈值分新段),复制到 01_input/segNN/raw/。
   若已在 01_input 手动分好段(每段一个含 raw/ 的文件夹),可直接跳过本步。"""
import datetime
import os
import shutil

from common import DIST_DIR, INPUT_DIR, list_images, log

GAP_SECONDS = 120   # 相邻两帧拍摄间隔超过此值 → 分为新段

try:
    import exifread
except ImportError:
    exifread = None


def shot_dt(path):
    if exifread:
        with open(path, "rb") as f:
            t = exifread.process_file(f, stop_tag="EXIF DateTimeOriginal", details=False)
        s = str(t.get("EXIF DateTimeOriginal", ""))
        try:
            return datetime.datetime.strptime(s, "%Y:%m:%d %H:%M:%S")
        except ValueError:
            pass
    return datetime.datetime.fromtimestamp(os.path.getmtime(path))


def copy_segments(segments, input_dir=INPUT_DIR):
    """复制分类结果。任何目标段已存在时,在写入前整体停止。"""
    targets = [os.path.join(input_dir, f"seg{idx:02d}")
               for idx in range(1, len(segments) + 1)]
    conflicts = [path for path in targets if os.path.exists(path)]
    if conflicts:
        names = ", ".join(os.path.basename(path) for path in conflicts)
        raise RuntimeError(f"目标分段已存在({names}),为防止混入旧帧已停止分类")

    for target, segment in zip(targets, segments):
        raw_dir = os.path.join(target, "raw")
        os.makedirs(raw_dir)
        for source in segment:
            shutil.copy2(source, os.path.join(raw_dir, os.path.basename(source)))
        log(f"  {os.path.basename(target)}: {len(segment)} 帧 -> {raw_dir}")


def main():
    files = list_images(DIST_DIR)
    if not files:
        log("00_dist 为空。若已在 01_input 手动分好段,直接跳过本步即可。")
        return
    dated = sorted(((shot_dt(f), f) for f in files), key=lambda x: x[0])
    segments, cur, prev = [], [], None
    for dt, f in dated:
        if prev is not None and (dt - prev).total_seconds() > GAP_SECONDS:
            segments.append(cur)
            cur = []
        cur.append(f)
        prev = dt
    if cur:
        segments.append(cur)
    log(f"共 {len(files)} 帧,按间隔 >{GAP_SECONDS}s 分成 {len(segments)} 段:")
    copy_segments(segments)
    log("\n分类完成(00_dist 原始保留)。请到各段目录写 config.json 指定处理参数,可参考 README。")


if __name__ == "__main__":
    main()
