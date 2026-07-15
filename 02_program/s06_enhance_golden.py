"""06 色彩强化:日照金山冷暖强化。core 帧区间 full 强度,两端 ramp 帧渐入渐出。产出 work/05_enhanced/。"""
from common import *


def process_one(seg):
    cfg = load_config(seg)
    eg = cfg["enhance_golden"]
    name = seg_name(seg)
    if not eg["enable"]:
        return
    full = GOLDEN_STRENGTH.get(eg["level"], GOLDEN_STRENGTH["strong"])
    core, ramp = eg["core"], eg["ramp"]
    in_dir = input_stage_dir(seg, "05_enhanced")
    out = new_stage_dir(seg, "05_enhanced")
    for f in list_images(in_dir):
        s = golden_ramp_strength(frame_num(f), core, ramp, full)
        save_jpeg(enhance_golden(load_image(f), s), os.path.join(out, os.path.basename(f)))
    sync_result(seg, out)
    update_preview(seg, cfg)
    log(f"[{name}] 金山强化 level={eg['level']} core={core} ramp={ramp} -> {out}")


def main():
    for seg in iter_segments():
        process_one(seg)


if __name__ == "__main__":
    main()
