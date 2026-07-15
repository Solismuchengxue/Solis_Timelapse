"""02 去闪:解码(RAW)/载入(JPEG)建立基准图像,按亮度曲线做曝光平滑去闪。产出 work/01_decoded/。"""
from common import *


def process_one(seg):
    cfg = load_config(seg)
    files = list_images(seg_raw(seg))
    name = seg_name(seg)
    if not files:
        log(f"[{name}] raw/ 为空,跳过")
        return
    dec, df = cfg["decode"], cfg["deflicker"]
    if df["enable"]:
        log(f"[{name}] 测光 {len(files)} 帧 ...")
        lums = [float(load_image(f, dec, half=True).mean()) for f in files]
        gain = exposure_gain(lums, df["window"], df["clip"])
        log(f"[{name}] 去闪 gain {gain.min():.3f}..{gain.max():.3f}")
    else:
        gain = np.ones(len(files))
    out = new_stage_dir(seg, "01_decoded")
    for i, f in enumerate(files):
        g = float(gain[i])
        if is_raw(f):
            rgb = decode_raw(f, dec["bright"] * g, dec["wb"], dec["gamma"])
        else:
            rgb = load_image(f, dec)
            if g != 1.0:
                rgb = np.clip(rgb * g, 0, 255)
        save_jpeg(rgb, os.path.join(out, os.path.splitext(os.path.basename(f))[0] + ".jpg"))
        if (i + 1) % 50 == 0:
            log(f"  {i+1}/{len(files)}")
    sync_result(seg, out)
    update_preview(seg, cfg)
    log(f"[{name}] -> {out}")


def main():
    for seg in iter_segments():
        process_one(seg)


if __name__ == "__main__":
    main()
