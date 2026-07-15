"""00 提取信息:遍历各段 raw/(及 00_dist),汇总格式、数量、分辨率、拍摄时间、曝光参数,辅助判断如何配置。"""
import os

from common import iter_segments, seg_raw, seg_name, list_images, is_raw, log, DIST_DIR

try:
    import exifread
except ImportError:
    exifread = None

_TAGS = {"time": "EXIF DateTimeOriginal", "shutter": "EXIF ExposureTime",
         "fnum": "EXIF FNumber", "iso": "EXIF ISOSpeedRatings", "focal": "EXIF FocalLength"}


def read_exif(path):
    if exifread is None:
        return {}
    with open(path, "rb") as f:
        t = exifread.process_file(f, details=False)
    return {k: str(t.get(v, "")) for k, v in _TAGS.items()}


def resolution(path):
    try:
        if is_raw(path):
            import rawpy
            with rawpy.imread(path) as r:
                return r.sizes.width, r.sizes.height
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (0, 0)


def report(files, name):
    exts = sorted(set(os.path.splitext(f)[1].lower() for f in files))
    w, h = resolution(files[0])
    a, b = read_exif(files[0]), read_exif(files[-1])
    log(f"=== {name}: {len(files)} 帧 | 格式 {','.join(exts)} | {w}x{h} ===")
    log(f"  首 {os.path.basename(files[0])}  {a.get('time','')}  {a.get('shutter','')}s f{a.get('fnum','')} ISO{a.get('iso','')} {a.get('focal','')}mm")
    log(f"  末 {os.path.basename(files[-1])}  {b.get('time','')}  {b.get('shutter','')}s f{b.get('fnum','')} ISO{b.get('iso','')} {b.get('focal','')}mm")
    if exifread and len(files) > 2:
        sh, iso, foc = set(), set(), set()
        for f in files:
            e = read_exif(f)
            sh.add(e.get("shutter")); iso.add(e.get("iso")); foc.add(e.get("focal"))
        log(f"  曝光跨度: {len(sh)} 种快门 / {len(iso)} 种 ISO / {len(foc)} 种焦距"
            + ("  ← 焦距有变化(可能中途变焦)" if len(foc) > 1 else ""))


def main():
    segs = iter_segments()
    for seg in segs:
        files = list_images(seg_raw(seg))
        if files:
            report(files, seg_name(seg))
        else:
            log(f"[{seg_name(seg)}] raw/ 为空")
    dist = list_images(DIST_DIR)
    if dist:
        report(dist, "00_dist(未分类)")
    if not segs and not dist:
        log("没有素材。把原始文件放进 00_dist,或 01_input/<段>/raw/。")


if __name__ == "__main__":
    main()
