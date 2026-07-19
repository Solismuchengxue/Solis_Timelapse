"""FFmpeg-backed image sequence export."""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Callable

from PIL import Image

from .task_manager import TaskCancelled


VALID_FPS = {24, 25, 30, 50, 60}
FRAME_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
RESOLUTIONS = {"1080p": (1920, 1080), "4k": (3840, 2160)}
CODECS = {"h264": "libx264", "h265": "libx265", "hevc": "libx265"}
NVENC_CODECS = {"h264": "h264_nvenc", "h265": "hevc_nvenc", "hevc": "hevc_nvenc"}
H264_NVENC_MAX_DIMENSION = 4096
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


@lru_cache(maxsize=8)
def _ffmpeg_encoders(ffmpeg_exe: str) -> str:
    try:
        result = subprocess.run(
            [ffmpeg_exe, "-hide_banner", "-encoders"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    return f"{result.stdout}\n{result.stderr}"


def _nvenc_available(ffmpeg_exe: str, encoder: str) -> bool:
    return encoder in _ffmpeg_encoders(ffmpeg_exe)


def _concat_line(path: Path) -> str:
    normalized = path.resolve().as_posix().replace("'", "'\\''")
    return f"file '{normalized}'\n"


def _image_dimensions(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def validate_export_compatibility(frame: Path, options: dict) -> None:
    codec_name = str(options.get("codec", "h264")).lower()
    resolution = str(options.get("resolution", "4k")).lower()
    if resolution == "source":
        resolution = "original"
    hardware_acceleration = str(options.get("hardware_acceleration", "off")).lower()
    if (
        resolution != "original"
        or codec_name != "h264"
        or hardware_acceleration not in {"auto", "nvenc"}
    ):
        return
    ffmpeg_exe = _ffmpeg_executable(options)
    if not _nvenc_available(ffmpeg_exe, NVENC_CODECS[codec_name]):
        return
    try:
        width, height = _image_dimensions(Path(frame))
    except OSError:
        return
    if max(width, height) > H264_NVENC_MAX_DIMENSION:
        raise ValueError(
            f"原图尺寸 {width}x{height} 超过 H.264 NVENC 的 4096 像素限制；"
            "请选择 H.265 保留原始分辨率，或选择 4K 后使用 H.264"
        )


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def _run_ffmpeg_attempt(
    command: list[str],
    encoder: str,
    frame_count: int,
    output_name: str,
    progress: Callable | None,
    cancelled: Callable[[], bool] | None,
) -> None:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    stop_watcher = threading.Event()

    def watch_cancellation() -> None:
        while not stop_watcher.wait(0.1):
            if cancelled is not None and cancelled():
                _stop_process(process)
                return

    watcher = None
    if cancelled is not None:
        watcher = threading.Thread(
            target=watch_cancellation,
            name="ffmpeg-cancellation",
            daemon=True,
        )
        watcher.start()

    started = time.monotonic()
    values: dict[str, str] = {}
    last_reported = 0
    try:
        if process.stdout is None:
            raise RuntimeError("FFmpeg progress pipe is unavailable")
        for raw_line in process.stdout:
            line = raw_line.strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key] = value
            if key != "progress":
                continue
            try:
                done = min(frame_count, max(0, int(values.get("frame", 0))))
            except (TypeError, ValueError):
                done = last_reported
            if progress is not None and done > last_reported:
                elapsed = max(time.monotonic() - started, 0.001)
                measured_fps = done / elapsed
                eta_seconds = max(0, round((frame_count - done) / measured_fps))
                try:
                    reported_fps = float(values.get("fps", measured_fps))
                except (TypeError, ValueError):
                    reported_fps = measured_fps
                progress(
                    done,
                    frame_count,
                    file=output_name,
                    encoder=encoder,
                    encoded_frames=done,
                    fps=round(reported_fps, 2),
                    speed=values.get("speed", "-"),
                    eta_seconds=eta_seconds,
                )
                last_reported = done
        return_code = process.wait()
        error_text = process.stderr.read() if process.stderr is not None else ""
        if cancelled is not None and cancelled():
            raise TaskCancelled("task cancelled")
        if return_code:
            raise subprocess.CalledProcessError(
                return_code, command, stderr=error_text
            )
        if progress is not None and last_reported < frame_count:
            progress(
                frame_count,
                frame_count,
                file=output_name,
                encoder=encoder,
                encoded_frames=frame_count,
                fps=round(frame_count / max(time.monotonic() - started, 0.001), 2),
                speed=values.get("speed", "-"),
                eta_seconds=0,
            )
    except BaseException:
        _stop_process(process)
        raise
    finally:
        stop_watcher.set()
        if watcher is not None:
            watcher.join(timeout=1)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def export_video(
    frame_dir: Path,
    output: Path,
    options: dict,
    progress: Callable | None = None,
    cancelled: Callable[[], bool] | None = None,
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
    if resolution == "source":
        resolution = "original"
    if resolution not in {*RESOLUTIONS, "original", "preview"}:
        raise ValueError("resolution must be 1080p, 4k, preview or original")
    preview_width = None
    if resolution == "preview":
        preview_width = int(options.get("width", 1920))
        if not 320 <= preview_width <= 3840 or preview_width % 2:
            raise ValueError("preview width must be an even number between 320 and 3840")
    crf = int(options.get("crf", 18))
    if not 0 <= crf <= 51:
        raise ValueError("crf must be between 0 and 51")
    hardware_acceleration = str(options.get("hardware_acceleration", "off")).lower()
    if hardware_acceleration not in {"off", "auto", "nvenc"}:
        raise ValueError("hardware acceleration must be off, auto or nvenc")

    requested = Path(output)
    requested.parent.mkdir(parents=True, exist_ok=True)
    final_output = requested.with_name(sanitize_windows_filename(requested.name))
    ffmpeg_exe = _ffmpeg_executable(options)
    software_encoder = CODECS[codec_name]
    nvenc_encoder = NVENC_CODECS[codec_name]
    nvenc_available = (
        hardware_acceleration in {"auto", "nvenc"}
        and _nvenc_available(ffmpeg_exe, nvenc_encoder)
    )
    validate_export_compatibility(frames[0], options)

    concat_path = final_output.parent / f".frames-{uuid.uuid4().hex}.ffconcat"
    temporary_output = final_output.parent / f".{final_output.stem}-rendering-{uuid.uuid4().hex}.mp4"
    concat_path.write_text("ffconcat version 1.0\n" + "".join(_concat_line(path) for path in frames), encoding="utf-8")

    command = [
        ffmpeg_exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-stats_period",
        "0.5",
        "-progress",
        "pipe:1",
        "-nostats",
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
    if resolution in RESOLUTIONS or resolution == "preview":
        if resolution == "preview":
            width = preview_width
            height = round(width * 9 / 16)
            height -= height % 2
        else:
            width, height = RESOLUTIONS[resolution]
        command.extend(
            [
                "-vf",
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
            ]
        )
    encoders = [software_encoder]
    if nvenc_available:
        encoders.insert(0, nvenc_encoder)

    try:
        selected_encoder = None
        last_error = None
        for encoder in encoders:
            temporary_output.unlink(missing_ok=True)
            codec_options = ["-c:v", encoder]
            if encoder in NVENC_CODECS.values():
                codec_options.extend(
                    [
                        "-preset",
                        "p3",
                        "-tune",
                        "hq",
                        "-multipass",
                        "disabled",
                        "-rc",
                        "vbr",
                        "-cq",
                        str(crf),
                        "-b:v",
                        "0",
                    ]
                )
            else:
                codec_options.extend(["-preset", "faster", "-crf", str(crf)])
            attempt = [
                *command,
                *codec_options,
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(temporary_output),
            ]
            attempt_callback = options.get("_on_encoder_attempt")
            if callable(attempt_callback):
                attempt_callback(encoder)
            try:
                _run_ffmpeg_attempt(
                    attempt,
                    encoder,
                    len(frames),
                    final_output.name,
                    progress,
                    cancelled,
                )
            except subprocess.CalledProcessError as exc:
                last_error = exc
                failed_callback = options.get("_on_encoder_failed")
                if callable(failed_callback):
                    failed_callback(encoder, (exc.stderr or "").strip())
                if encoder == encoders[-1]:
                    raise
                continue
            selected_encoder = encoder
            break
        if selected_encoder is None and last_error is not None:
            raise last_error
        if not temporary_output.is_file():
            raise RuntimeError("FFmpeg completed without creating an output file")
        if cancelled is not None and cancelled():
            raise TaskCancelled("task cancelled")
        encoder_callback = options.get("_on_encoder_selected")
        if callable(encoder_callback):
            encoder_callback(selected_encoder)
        os.replace(temporary_output, final_output)
        return final_output
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or "FFmpeg export failed").strip()
        raise RuntimeError(message) from exc
    finally:
        concat_path.unlink(missing_ok=True)
        temporary_output.unlink(missing_ok=True)
