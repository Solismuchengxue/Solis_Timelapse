"""FFmpeg-backed image sequence export."""
from __future__ import annotations

import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Callable


VALID_FPS = {24, 25, 30, 50, 60}
FRAME_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
RESOLUTIONS = {"1080p": (1920, 1080), "4k": (3840, 2160)}
CODECS = {"h264": "libx264", "h265": "libx265", "hevc": "libx265"}
INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def sanitize_windows_filename(name: str) -> str:
    source = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    suffix = Path(source).suffix
    stem = source[: -len(suffix)] if suffix else source
    stem = INVALID_WINDOWS_CHARS.sub("_", stem).rstrip(" .")
    suffix = INVALID_WINDOWS_CHARS.sub("_", suffix).rstrip(" .")
    if not stem:
        stem = "video"
    if stem.upper() in RESERVED_WINDOWS_NAMES:
        stem = f"_{stem}"
    return f"{stem}{suffix or '.mp4'}"


def _natural_key(path: Path) -> list[object]:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", path.name)]


def _ffmpeg_executable(options: dict) -> str:
    explicit = options.get("ffmpeg_exe")
    if explicit:
        return str(explicit)
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise RuntimeError("imageio-ffmpeg is not installed") from exc
    return imageio_ffmpeg.get_ffmpeg_exe()


def _concat_line(path: Path) -> str:
    normalized = path.resolve().as_posix().replace("'", "'\\''")
    return f"file '{normalized}'\n"


def export_video(
    frame_dir: Path,
    output: Path,
    options: dict,
    progress: Callable | None = None,
) -> Path:
    frame_dir = Path(frame_dir)
    if not frame_dir.is_dir():
        raise FileNotFoundError(f"frame directory does not exist: {frame_dir}")
    frames = sorted(
        (path for path in frame_dir.iterdir() if path.is_file() and path.suffix.lower() in FRAME_SUFFIXES),
        key=_natural_key,
    )
    if not frames:
        raise ValueError("frame directory contains no supported images")

    fps = int(options.get("fps", 30))
    if fps not in VALID_FPS:
        raise ValueError(f"fps must be one of {sorted(VALID_FPS)}")
    codec_name = str(options.get("codec", "h264")).lower()
    if codec_name not in CODECS:
        raise ValueError("codec must be h264 or h265")
    resolution = str(options.get("resolution", "4k")).lower()
    if resolution not in {*RESOLUTIONS, "original"}:
        raise ValueError("resolution must be 1080p, 4k or original")
    crf = int(options.get("crf", 18))
    if not 0 <= crf <= 51:
        raise ValueError("crf must be between 0 and 51")

    requested = Path(output)
    requested.parent.mkdir(parents=True, exist_ok=True)
    final_output = requested.with_name(sanitize_windows_filename(requested.name))
    concat_path = final_output.parent / f".frames-{uuid.uuid4().hex}.ffconcat"
    temporary_output = final_output.parent / f".{final_output.stem}-rendering-{uuid.uuid4().hex}.mp4"
    concat_path.write_text("ffconcat version 1.0\n" + "".join(_concat_line(path) for path in frames), encoding="utf-8")

    command = [
        _ffmpeg_executable(options),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-r",
        str(fps),
        "-i",
        str(concat_path),
    ]
    if resolution in RESOLUTIONS:
        width, height = RESOLUTIONS[resolution]
        command.extend(
            [
                "-vf",
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
            ]
        )
    command.extend(
        [
            "-c:v",
            CODECS[codec_name],
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(temporary_output),
        ]
    )

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        if not temporary_output.is_file():
            raise RuntimeError("FFmpeg completed without creating an output file")
        os.replace(temporary_output, final_output)
        if progress is not None:
            progress(len(frames), len(frames), file=final_output.name)
        return final_output
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or "FFmpeg export failed").strip()
        raise RuntimeError(message) from exc
    finally:
        concat_path.unlink(missing_ok=True)
        temporary_output.unlink(missing_ok=True)
