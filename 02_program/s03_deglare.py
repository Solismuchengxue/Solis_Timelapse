"""03 去眩光:剔除 config.deglare.reject 列出的过曝/眩光帧。产出 work/02_deglared/,坏帧移到 work/_rejected/。"""
from common import *


def process_one(seg):
    cfg = load_config(seg)
    dg = cfg["deglare"]
    name = seg_name(seg)
    if not dg["enable"] or not dg["reject"]:
        return
    in_dir = input_stage_dir(seg, "02_deglared")
    out = new_stage_dir(seg, "02_deglared")
    rej_dir = os.path.join(seg_work(seg), "_rejected")
    os.makedirs(rej_dir, exist_ok=True)
    reject = set(dg["reject"])
    kept = 0
    for f in list_images(in_dir):
        base = os.path.splitext(os.path.basename(f))[0]
        if base in reject:
            shutil.copy2(f, os.path.join(rej_dir, os.path.basename(f)))
        else:
            shutil.copy2(f, os.path.join(out, os.path.basename(f)))
            kept += 1
    sync_result(seg, out)
    update_preview(seg, cfg)
    log(f"[{name}] 去眩光: 剔除 {len(reject)}, 保留 {kept} -> {out}")


def main():
    for seg in iter_segments():
        process_one(seg)


if __name__ == "__main__":
    main()
