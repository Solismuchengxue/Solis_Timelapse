"""07 自然调色:对 grade.style==natural 的段做自然调色(白天用)。产出 work/04_graded/。"""
from common import *


def process_one(seg):
    cfg = load_config(seg)
    gr = cfg["grade"]
    name = seg_name(seg)
    if gr.get("style") != "natural":
        return
    in_dir = input_stage_dir(seg, "04_graded")
    out = new_stage_dir(seg, "04_graded")
    for f in list_images(in_dir):
        save_jpeg(grade_by_style(load_image(f), "natural", gr), os.path.join(out, os.path.basename(f)))
    sync_result(seg, out)
    update_preview(seg, cfg)
    log(f"[{name}] 自然调色 -> {out}")


def main():
    for seg in iter_segments():
        process_one(seg)


if __name__ == "__main__":
    main()
