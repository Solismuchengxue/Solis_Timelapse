"""04 暗帧提亮:对开头/中途的暗跳变帧,用更宽平滑窗口 + 增益提亮对齐。产出 work/03_lifted/。"""
from common import *


def process_one(seg):
    cfg = load_config(seg)
    ld = cfg["lift_dark"]
    name = seg_name(seg)
    if not ld["enable"]:
        return
    in_dir = input_stage_dir(seg, "03_lifted")
    files = list_images(in_dir)
    if not files:
        return
    lums = [float(load_image(f, half=True).mean()) for f in files]
    gain = exposure_gain(lums, ld["window"], ld["clip"])
    out = new_stage_dir(seg, "03_lifted")
    for i, f in enumerate(files):
        rgb = load_image(f)
        g = float(gain[i])
        if g != 1.0:
            rgb = np.clip(rgb * g, 0, 255)
        save_jpeg(rgb, os.path.join(out, os.path.basename(f)))
    sync_result(seg, out)
    update_preview(seg, cfg)
    log(f"[{name}] 暗帧提亮 gain {gain.min():.3f}..{gain.max():.3f} -> {out}")


def main():
    for seg in iter_segments():
        process_one(seg)


if __name__ == "__main__":
    main()
