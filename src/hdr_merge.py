"""HDR exposure fusion and radiance-map merging for selected source frames."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

import cv2
import numpy as np
from PIL import Image

from . import image_ops
from .task_manager import TaskCancelled


Progress = Callable[..., None]
Cancelled = Callable[[], bool]
VALID_MODES = {"fusion", "radiance"}
VALID_OUTPUT_FORMATS = {"jpeg", "tiff"}


def _number(options: dict, key: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(options.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc
    if not np.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return value


def _check_cancelled(cancelled: Cancelled | None) -> None:
    if cancelled is not None and cancelled():
        raise TaskCancelled("task cancelled")


def _notify(progress: Progress | None, done: int, total: int, stage: str) -> None:
    if progress is not None:
        progress(done, total, stage=stage)


def _validated_options(options: dict | None) -> dict:
    values = dict(options or {})
    mode = str(values.get("mode", "fusion")).casefold()
    output_format = str(values.get("output_format", "jpeg")).casefold()
    if mode not in VALID_MODES:
        raise ValueError("mode must be fusion or radiance")
    if output_format not in VALID_OUTPUT_FORMATS:
        raise ValueError("output_format must be jpeg or tiff")
    return {
        "mode": mode,
        "output_format": output_format,
        "align": bool(values.get("align", True)),
        "crop_edges": bool(values.get("crop_edges", True)),
        "deghost_strength": _number(values, "deghost_strength", 0.25, 0.0, 1.0),
        "contrast_weight": _number(values, "contrast_weight", 1.0, 0.0, 5.0),
        "saturation_weight": _number(values, "saturation_weight", 1.0, 0.0, 5.0),
        "exposure_weight": _number(values, "exposure_weight", 0.2, 0.0, 5.0),
        "gamma": _number(values, "gamma", 2.2, 0.1, 5.0),
        "intensity": _number(values, "intensity", 0.0, -8.0, 8.0),
        "light_adapt": _number(values, "light_adapt", 1.0, 0.0, 1.0),
        "color_adapt": _number(values, "color_adapt", 0.0, 0.0, 1.0),
        "post_contrast": _number(values, "post_contrast", 1.0, 0.25, 3.0),
        "post_saturation": _number(values, "post_saturation", 1.0, 0.0, 3.0),
    }


def _load_frames(paths: list[Path], progress: Progress | None, cancelled: Cancelled | None) -> list[np.ndarray]:
    frames: list[np.ndarray] = []
    expected_shape = None
    total = len(paths) + 4
    for index, path in enumerate(paths, start=1):
        _check_cancelled(cancelled)
        pixels = np.clip(image_ops.load_image(path), 0, 255).astype(np.uint8)
        if pixels.ndim != 3 or pixels.shape[2] != 3:
            raise ValueError("HDR source frames must be RGB images")
        if expected_shape is None:
            expected_shape = pixels.shape
        elif pixels.shape != expected_shape:
            raise ValueError("HDR source frames must have matching dimensions")
        frames.append(np.ascontiguousarray(pixels))
        _notify(progress, index, total, f"decode:{path.name}")
    return frames


def _align_frames(frames: list[np.ndarray], crop_edges: bool) -> list[np.ndarray]:
    aligned = [frame.copy() for frame in frames]
    cv2.createAlignMTB(max_bits=6, exclude_range=4, cut=crop_edges).process(frames, aligned)
    return aligned


def _radiance_merge(frames: list[np.ndarray], exposure_times: Iterable[float | None] | None, options: dict) -> np.ndarray:
    values = list(exposure_times or [])
    if len(values) != len(frames):
        raise ValueError("radiance HDR needs one exposure time per frame")
    try:
        times = np.asarray([float(value) for value in values], dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise ValueError("radiance HDR exposure times must be positive numbers") from exc
    if not np.isfinite(times).all() or np.any(times <= 0):
        raise ValueError("radiance HDR exposure times must be positive numbers")
    response = cv2.createCalibrateDebevec(samples=70, lambda_=10.0, random=False).process(frames, times)
    radiance = cv2.createMergeDebevec().process(frames, times=times.copy(), response=response)
    mapper = cv2.createTonemapReinhard(
        gamma=options["gamma"],
        intensity=options["intensity"],
        light_adapt=options["light_adapt"],
        color_adapt=options["color_adapt"],
    )
    return mapper.process(radiance.copy())


def _fusion_merge(frames: list[np.ndarray], options: dict) -> np.ndarray:
    merger = cv2.createMergeMertens(
        contrast_weight=options["contrast_weight"],
        saturation_weight=options["saturation_weight"],
        exposure_weight=options["exposure_weight"],
    )
    return merger.process(frames)


def _deghost(result: np.ndarray, frames: list[np.ndarray], strength: float) -> np.ndarray:
    if strength <= 0:
        return result
    stack = np.stack(frames).astype(np.float32) / 255.0
    luminance = stack @ np.asarray([0.2126, 0.7152, 0.0722], dtype=np.float32)
    levels = np.median(luminance, axis=(1, 2))
    normalized = luminance / np.maximum(levels[:, None, None], 1e-4)
    motion = np.std(normalized, axis=0)
    mask = np.clip((motion - 0.08) / 0.24, 0.0, 1.0) * strength
    base_index = int(np.argsort(levels)[len(levels) // 2])
    base = stack[base_index]
    return result * (1.0 - mask[..., None]) + base * mask[..., None]


def _post_grade(result: np.ndarray, contrast: float, saturation: float) -> np.ndarray:
    safe = np.nan_to_num(result, nan=0.0, posinf=1.0, neginf=0.0)
    safe = np.clip(safe, 0.0, 1.0)
    gray = safe @ np.asarray([0.2126, 0.7152, 0.0722], dtype=np.float32)
    graded = gray[..., None] + (safe - gray[..., None]) * saturation
    return np.clip((graded - 0.5) * contrast + 0.5, 0.0, 1.0)


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _save_result(result: np.ndarray, output: Path, output_format: str) -> None:
    if output_format == "tiff":
        bgr = cv2.cvtColor(np.round(result * 65535).astype(np.uint16), cv2.COLOR_RGB2BGR)
        ok, encoded = cv2.imencode(".tiff", bgr)
        if not ok:
            raise RuntimeError("OpenCV could not encode the TIFF result")
        _atomic_bytes(output, encoded.tobytes())
        return
    image = Image.fromarray(np.round(result * 255).astype(np.uint8), mode="RGB")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    image.save(temporary, format="JPEG", quality=96, subsampling=0)
    temporary.replace(output)


def _save_preview(result: np.ndarray, preview: Path) -> None:
    image = Image.fromarray(np.round(result * 255).astype(np.uint8), mode="RGB")
    image.thumbnail((1920, 1280), Image.Resampling.LANCZOS)
    preview.parent.mkdir(parents=True, exist_ok=True)
    temporary = preview.with_name(f".{preview.name}.tmp")
    image.save(temporary, format="JPEG", quality=90)
    temporary.replace(preview)


def merge_exposures(
    paths: Iterable[str | Path],
    output: str | Path,
    preview: str | Path,
    options: dict | None = None,
    *,
    exposure_times: Iterable[float | None] | None = None,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> dict:
    """Merge two to nine registered source photos and publish an HDR result."""
    source_paths = [Path(path) for path in paths]
    if not 2 <= len(source_paths) <= 9:
        raise ValueError("HDR merge requires 2 to 9 source frames")
    if any(not path.is_file() for path in source_paths):
        raise ValueError("HDR source frame does not exist")
    settings = _validated_options(options)
    frames = _load_frames(source_paths, progress, cancelled)
    total = len(frames) + 4
    _check_cancelled(cancelled)
    if settings["align"]:
        frames = _align_frames(frames, settings["crop_edges"])
    _notify(progress, len(frames) + 1, total, "align")
    _check_cancelled(cancelled)
    if settings["mode"] == "radiance":
        merged = _radiance_merge(frames, exposure_times, settings)
    else:
        merged = _fusion_merge(frames, settings)
    _notify(progress, len(frames) + 2, total, "merge")
    _check_cancelled(cancelled)
    merged = _deghost(merged, frames, settings["deghost_strength"])
    merged = _post_grade(merged, settings["post_contrast"], settings["post_saturation"])
    _notify(progress, len(frames) + 3, total, "grade")
    _check_cancelled(cancelled)
    output_path = Path(output)
    preview_path = Path(preview)
    _save_result(merged, output_path, settings["output_format"])
    _save_preview(merged, preview_path)
    _notify(progress, total, total, "save")
    return {
        "mode": settings["mode"],
        "output_format": settings["output_format"],
        "frame_count": len(frames),
        "width": int(merged.shape[1]),
        "height": int(merged.shape[0]),
    }
