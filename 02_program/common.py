"""
common.py — 延时摄影流水线公共库

所有 s0x 步骤脚本共用的:路径、配置、解码、去闪、调色、强化、视频、日志。
数据流约定:
  01_input/<段>/raw/       原始 ARW/JPEG
  01_input/<段>/work/NN_*/ 各处理阶段中间产物(按数字前缀排序,最大者为最新)
  01_input/<段>/result/    当前最新成品(每步结束同步,给剪映用)
  01_input/<段>/config.json 该段参数
每个步骤:从 latest_stage_dir 读 → 写 new_stage_dir → sync_result。
"""
import glob
import json
import os
import shutil

import numpy as np
import rawpy
from PIL import Image

try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG = "ffmpeg"

# ---------------- 路径 ----------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(ROOT, "00_dist")
INPUT_DIR = os.path.join(ROOT, "01_input")
PROGRAM_DIR = os.path.join(ROOT, "02_program")
PREVIEW_DIR = os.path.join(ROOT, "03_preview")
OUTPUT_DIR = os.path.join(ROOT, "04_output")
ARCHIVE_DIR = os.path.join(ROOT, "05_archive")

RAW_EXTS = (".arw",)
JPEG_EXTS = (".jpg", ".jpeg")

# ---------------- 预设 ----------------
GRADE_PRESETS = {
    "punchy":  {"sat": 1.25, "con": 1.18, "pivot": 110.0},   # 日出通透
    "natural": {"sat": 1.20, "con": 1.12, "pivot": 118.0},   # 白天自然
    "none":    {"sat": 1.00, "con": 1.00, "pivot": 118.0},
}
GOLDEN_STRENGTH = {"mild": 0.55, "medium": 0.85, "strong": 1.20}

DEFAULT_CONFIG = {
    "type": "raw",                                    # raw | jpeg
    "decode": {"bright": 3.5, "wb": "camera", "gamma": "srgb"},
    "deflicker":      {"enable": True,  "window": 11, "clip": [0.85, 1.2]},
    "deglare":        {"enable": False, "reject": []},         # 剔除的帧名(不含扩展名)
    "lift_dark":      {"enable": False, "window": 15, "clip": [0.7, 1.7]},
    "grade":          {"style": "none"},              # punchy | natural | none (+可选 sat/con/pivot 覆盖)
    "enhance_golden": {"enable": False, "level": "strong", "core": [0, 0], "ramp": 10},
    "preview_fps": 30,
}

# ---------------- 日志 ----------------
def log(msg):
    print(msg, flush=True)


# ---------------- 段 / 配置 ----------------
def iter_segments():
    """返回 01_input 下所有段目录(含 config.json 或 raw/ 的子目录),按名排序。"""
    if not os.path.isdir(INPUT_DIR):
        return []
    segs = []
    for name in sorted(os.listdir(INPUT_DIR)):
        d = os.path.join(INPUT_DIR, name)
        if os.path.isdir(d) and (os.path.exists(os.path.join(d, "config.json")) or os.path.isdir(os.path.join(d, "raw"))):
            segs.append(d)
    return segs


def _deep_merge(base, override):
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(seg_dir):
    cfg_path = os.path.join(seg_dir, "config.json")
    user = {}
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            user = json.load(f)
    cfg = _deep_merge(DEFAULT_CONFIG, user)
    cfg["_name"] = os.path.basename(seg_dir)
    cfg["_dir"] = seg_dir
    return cfg


def seg_name(seg_dir):
    return os.path.basename(seg_dir)


# ---------------- 阶段目录 ----------------
def seg_raw(seg_dir):
    return os.path.join(seg_dir, "raw")


def seg_work(seg_dir):
    return os.path.join(seg_dir, "work")


def seg_result(seg_dir):
    return os.path.join(seg_dir, "result")


def latest_stage_dir(seg_dir):
    """work/ 下数字前缀最大的阶段目录;没有则返回 raw/。"""
    work = seg_work(seg_dir)
    if os.path.isdir(work):
        stages = sorted(d for d in os.listdir(work)
                        if os.path.isdir(os.path.join(work, d)) and d[:2].isdigit())
        if stages:
            return os.path.join(work, stages[-1])
    return seg_raw(seg_dir)


def new_stage_dir(seg_dir, stage_name):
    """新建(或清空重建)本步的阶段目录,保证重跑幂等、不残留旧帧。"""
    d = os.path.join(seg_work(seg_dir), stage_name)
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
    return d


def input_stage_dir(seg_dir, my_stage):
    """本步的输入 = work/ 里阶段号 < my_stage 的最大阶段目录;没有则 raw/。
    (避免把上次中断残留的同名/更高阶段目录误当输入。)"""
    my_n = int(my_stage[:2])
    work = seg_work(seg_dir)
    cands = []
    if os.path.isdir(work):
        for d in os.listdir(work):
            p = os.path.join(work, d)
            if os.path.isdir(p) and d[:2].isdigit() and int(d[:2]) < my_n:
                cands.append(d)
    if cands:
        return os.path.join(work, sorted(cands)[-1])
    return seg_raw(seg_dir)


def sync_result(seg_dir, from_dir):
    """把 from_dir 的图片镜像到 result/(清空重填),作为当前最新成品。
    优先硬链接(同盘秒建、不占额外空间;删 work 后 result 仍保留数据),跨盘回退复制。"""
    res = seg_result(seg_dir)
    if os.path.isdir(res):
        shutil.rmtree(res)
    os.makedirs(res, exist_ok=True)
    for f in list_images(from_dir):
        dst = os.path.join(res, os.path.basename(f))
        try:
            os.link(f, dst)
        except OSError:
            shutil.copy2(f, dst)
    return res


# ---------------- 帧 / 列表 ----------------
def frame_num(name):
    """从 'CZ_01194.ARW' 提取 1194;失败返回 -1。"""
    base = os.path.splitext(os.path.basename(name))[0]
    digits = "".join(ch for ch in base if ch.isdigit())
    return int(digits) if digits else -1


def is_raw(path):
    return os.path.splitext(path)[1].lower() in RAW_EXTS


def list_images(d, exts=RAW_EXTS + JPEG_EXTS):
    if not os.path.isdir(d):
        return []
    files = [os.path.join(d, f) for f in os.listdir(d)
             if os.path.splitext(f)[1].lower() in exts]
    return sorted(files, key=lambda p: (frame_num(p), p))


# ---------------- 解码 / 载入 ----------------
_GAMMA = {"srgb": (2.222, 4.5), "linear": (1.0, 1.0)}


def decode_raw(path, bright=3.5, wb="camera", gamma="srgb", half=False):
    with rawpy.imread(path) as raw:
        return raw.postprocess(
            use_camera_wb=(wb == "camera"), use_auto_wb=(wb == "auto"),
            no_auto_bright=True, bright=bright, output_bps=8,
            gamma=_GAMMA.get(gamma, _GAMMA["srgb"]), half_size=half,
        ).astype(np.float32)


def load_image(path, decode=None, half=False):
    """RAW → 解码;JPEG → 直接读。decode 为 config['decode'] dict。"""
    d = decode or {}
    if is_raw(path):
        return decode_raw(path, d.get("bright", 3.5), d.get("wb", "camera"),
                          d.get("gamma", "srgb"), half=half)
    im = Image.open(path).convert("RGB")
    if half:
        im = im.resize((im.width // 2, im.height // 2), Image.BILINEAR)
    return np.asarray(im).astype(np.float32)


def save_jpeg(arr, path, quality=95):
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(path, quality=quality)


# ---------------- 去闪 / 曝光平滑 ----------------
def smooth_median(arr, window):
    arr = np.asarray(arr, dtype=np.float64)
    n = len(arr)
    half = window // 2
    out = np.empty(n)
    for i in range(n):
        out[i] = np.median(arr[max(0, i - half):min(n, i + half + 1)])
    return out


def exposure_gain(lums, window, clip):
    """从亮度序列算每帧增益(平滑目标 / 实测),clip 限幅。"""
    lums = np.asarray(lums, dtype=np.float64)
    target = smooth_median(lums, window)
    return np.clip(target / np.maximum(lums, 1e-6), clip[0], clip[1])


# ---------------- 调色 ----------------
def grade(rgb, sat, con, pivot):
    gray = rgb.mean(axis=2, keepdims=True)
    out = gray + (rgb - gray) * sat
    out = (out - pivot) * con + pivot
    return np.clip(out, 0, 255)


def grade_by_style(rgb, style, overrides=None):
    p = dict(GRADE_PRESETS.get(style, GRADE_PRESETS["none"]))
    p.update({k: v for k, v in (overrides or {}).items() if k in ("sat", "con", "pivot")})
    return grade(rgb, p["sat"], p["con"], p["pivot"])


# ---------------- HSV / 日照金山强化 ----------------
def rgb2hsv(rgb):
    r, g, b = rgb[..., 0] / 255., rgb[..., 1] / 255., rgb[..., 2] / 255.
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    df = mx - mn
    h = np.zeros_like(mx)
    m = df > 1e-9
    rm = (mx == r) & m
    gm = (mx == g) & m & ~rm
    bm = (mx == b) & m & ~rm & ~gm
    h[rm] = (((g - b)[rm] / df[rm]) % 6)
    h[gm] = ((b - r)[gm] / df[gm]) + 2
    h[bm] = ((r - g)[bm] / df[bm]) + 4
    h /= 6.0
    s = np.where(mx > 0, df / np.maximum(mx, 1e-9), 0)
    return h, s, mx


def hsv2rgb(h, s, v):
    h6 = (h * 6.0) % 6
    i = np.floor(h6).astype(int)
    f = h6 - i
    p = v * (1 - s)
    q = v * (1 - s * f)
    t = v * (1 - s * (1 - f))
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], -1) * 255.


def enhance_golden(rgb, strength):
    """日照金山强化:橙金受光区提亮提纯 + 环境压暗压冷,冷暖分离。strength 0..~1.2。"""
    if strength <= 0:
        return rgb
    h, sat, v = rgb2hsv(rgb)
    hue_gold = np.clip(1 - np.abs(h - 0.09) / 0.11, 0, 1)     # 橙金色相带
    lit = np.clip((v - 0.42) / 0.42, 0, 1)                    # 受光亮区
    gold = hue_gold * lit
    shadow = np.clip((0.38 - v) / 0.38, 0, 1)                 # 暗部环境
    v2 = np.clip(v + gold * 0.18 * strength - shadow * 0.17 * strength, 0, 1)
    sat2 = np.clip(sat + gold * 0.38 * strength, 0, 1)
    h2 = h + gold * (0.075 - h) * 0.35 * strength
    out = hsv2rgb(np.clip(h2, 0, 1), sat2, v2)
    out[..., 2] += shadow * 15 * strength
    out[..., 0] -= shadow * 8 * strength
    return np.clip(out, 0, 255)


def golden_ramp_strength(fnum, core, ramp, full):
    """核心区间 full,两端 ramp 帧线性渐入渐出。"""
    lo, hi = core
    if lo <= fnum <= hi:
        return full
    if lo - ramp <= fnum < lo:
        return full * (fnum - (lo - ramp)) / ramp
    if hi < fnum <= hi + ramp:
        return full * ((hi + ramp) - fnum) / ramp
    return 0.0


# ---------------- 视频 ----------------
def make_video(frame_dir, out_path, fps=30, width=1920):
    """用 concat demuxer 把 frame_dir 里的图片(按帧号排序,支持缺号)合成视频。"""
    import subprocess
    files = list_images(frame_dir, exts=JPEG_EXTS)
    if not files:
        raise RuntimeError(f"no jpeg frames in {frame_dir}")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    list_path = out_path + ".concat.txt"
    dur = 1.0 / fps
    with open(list_path, "w", encoding="utf-8") as f:
        for fp in files:
            f.write(f"file '{fp.replace(os.sep, '/')}'\n")
            f.write(f"duration {dur:.6f}\n")
        f.write(f"file '{files[-1].replace(os.sep, '/')}'\n")
    cmd = [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", list_path,
           "-vf", f"fps={fps},scale={width}:-2", "-c:v", "libx264",
           "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if os.path.exists(list_path):
        os.remove(list_path)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-1000:])
    return out_path, len(files)


def update_preview(seg_dir, cfg):
    """为该段当前 result/ 生成/更新预览视频到 03_preview/<段>.mp4。"""
    out = os.path.join(PREVIEW_DIR, seg_name(seg_dir) + ".mp4")
    try:
        _, n = make_video(seg_result(seg_dir), out, cfg.get("preview_fps", 30))
        log(f"  预览 {os.path.basename(out)} ({n} 帧)")
    except Exception as e:
        log(f"  预览生成跳过: {e}")
