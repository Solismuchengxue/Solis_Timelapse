"""Analysis and one-pass rendering for a timelapse segment."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from .image_ops import (
    GOLDEN_STRENGTH,
    apply_gain,
    enhance_golden,
    exposure_gain,
    frame_num,
    golden_ramp_strength,
    grade_by_style,
    load_image,
    measure_luminance,
    save_jpeg,
    smooth_median,
)
from .task_manager import TaskCancelled


@dataclass(frozen=True)
class RenderResult:
    frame_count: int
    result_dir: str
    rejected_count: int


def _frame_paths(segment: dict) -> list[Path]:
    values = segment.get("frames", segment.get("source_files", []))
    paths = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("path")
        elif hasattr(value, "path"):
            value = value.path
        if not value:
            raise ValueError("segment contains a frame without a path")
        paths.append(Path(value).resolve())
    if not paths:
        raise ValueError("segment contains no frames")
    return paths


def _check_cancelled(cancelled: Callable[[], bool]) -> None:
    if cancelled():
        raise TaskCancelled("task cancelled")


def _source_identity(path: Path) -> dict:
    stat = path.stat()
    return {
        "path": str(path),
        "name": path.name,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _path_key(path: str | Path) -> str:
    return os.path.normpath(str(Path(path).resolve())).casefold()


def _same_identity(expected: dict, actual: dict) -> bool:
    try:
        return (
            _path_key(expected["path"]) == _path_key(actual["path"])
            and int(expected["size"]) == int(actual["size"])
            and int(expected["mtime_ns"]) == int(actual["mtime_ns"])
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _thumbnail(rgb: np.ndarray, width: int = 320, height: int = 180) -> np.ndarray:
    pixels = np.clip(rgb, 0, 255).astype(np.uint8)
    image = Image.fromarray(pixels)
    image.thumbnail((width, height), Image.Resampling.LANCZOS)
    return np.asarray(image, dtype=np.float32)


def _fsync_file(path: Path) -> None:
    with path.open("r+b") as source:
        os.fsync(source.fileno())


def _fsync_directory(path: Path) -> None:
    """Best-effort directory fsync; Windows may not allow directory handles."""
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        try:
            os.fsync(descriptor)
        except OSError:
            pass
    finally:
        os.close(descriptor)


def _anomaly_candidates(
    paths: list[Path], luminance: np.ndarray, gains: np.ndarray, threshold: float = 0.05
) -> list[dict]:
    candidates = []
    for index, (path, measured, gain) in enumerate(zip(paths, luminance, gains)):
        if abs(float(gain) - 1.0) >= threshold:
            candidates.append(
                {
                    "index": index,
                    "path": str(path),
                    "name": path.name,
                    "measured_luminance": float(measured),
                    "gain": float(gain),
                    "reason": "exposure_gain",
                }
            )
    return candidates


def _gains(luminance: np.ndarray, recipe: dict) -> tuple[np.ndarray, np.ndarray]:
    combined = np.ones(len(luminance), dtype=np.float64)
    target = luminance.copy()
    deflicker = recipe.get("deflicker", {})
    if deflicker.get("enable", True):
        window = deflicker.get("window", 11)
        target = smooth_median(luminance, window)
        combined *= exposure_gain(
            luminance,
            window,
            deflicker.get("clip", (0.85, 1.2)),
        )

    lift_dark = recipe.get("lift_dark", {})
    if lift_dark.get("enable", False):
        corrected = luminance * combined
        window = lift_dark.get("window", 15)
        target = smooth_median(corrected, window)
        combined *= exposure_gain(
            corrected,
            window,
            lift_dark.get("clip", (0.7, 1.7)),
        )
    return combined, target


def analyze_segment(
    segment: dict,
    recipe: dict,
    work_dir: Path,
    progress: Callable,
    cancelled: Callable,
) -> dict:
    """Measure sources and transactionally publish analysis UI assets."""
    paths = _frame_paths(segment)
    decode = recipe.get("decode", {})
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    version_id = uuid.uuid4().hex
    version_relative = f".analysis_versions/{version_id}"
    versions_dir = work_dir / ".analysis_versions"
    version_dir = versions_dir / version_id
    thumbnail_dir = version_dir / "thumbnails"
    luminance = []
    sources = []
    thumbnails = []
    histogram_counts = np.zeros(32, dtype=np.int64)
    histogram_edges = np.linspace(0.0, 256.0, 33)
    committed = False
    try:
        thumbnail_dir.mkdir(parents=True)
        for index, path in enumerate(paths):
            _check_cancelled(cancelled)
            identity = _source_identity(path)
            rgb = load_image(path, decode, half=True)
            measured_value = measure_luminance(rgb)
            if not _same_identity(identity, _source_identity(path)):
                raise ValueError(f"source identity changed during analysis: {path.name}")
            luminance.append(measured_value)
            sources.append(identity)
            gray = rgb.mean(axis=2)
            counts, _ = np.histogram(gray, bins=histogram_edges)
            histogram_counts += counts
            relative = f"{version_relative}/thumbnails/{index:06d}.jpg"
            thumbnail_path = work_dir / relative
            save_jpeg(_thumbnail(rgb), thumbnail_path, quality=82)
            _fsync_file(thumbnail_path)
            thumbnails.append(
                {"index": index, "source": str(path), "name": path.name, "path": relative}
            )
            progress(index + 1, len(paths), frame=str(path))

        measured = np.asarray(luminance, dtype=np.float64)
        gain, target = _gains(measured, recipe)
        representative_index = int(np.argmin(np.abs(measured - np.median(measured))))
        representative_thumbnail = thumbnails[representative_index]["path"]
        representative_relative = f"{version_relative}/representative.jpg"
        representative_path = work_dir / representative_relative
        shutil.copy2(work_dir / representative_thumbnail, representative_path)
        _fsync_file(representative_path)
        _fsync_directory(thumbnail_dir)
        _fsync_directory(version_dir)
        _fsync_directory(versions_dir)
        analysis = {
            "schema_version": 1,
            "segment_id": segment.get("id"),
            "frame_count": len(paths),
            "sources": sources,
            "measured_luminance": measured.tolist(),
            "target_luminance": target.tolist(),
            "gain": gain.tolist(),
            "anomaly_candidates": _anomaly_candidates(paths, measured, gain),
            "histogram_summary": {
                "bins": histogram_edges.tolist(),
                "counts": histogram_counts.tolist(),
                "sample_count": int(histogram_counts.sum()),
            },
            "asset_version": version_relative,
            "thumbnails": thumbnails,
            "representative_frame": {
                "index": representative_index,
                "source": str(paths[representative_index]),
                "name": paths[representative_index].name,
                "thumbnail": representative_thumbnail,
                "image": representative_relative,
            },
        }

        _check_cancelled(cancelled)
        temporary = work_dir / f".analysis-{version_id}.json.tmp"
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            json.dump(analysis, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        _check_cancelled(cancelled)
        os.replace(temporary, work_dir / "analysis.json")
        committed = True
        _fsync_directory(work_dir)
    except BaseException:
        temporary = work_dir / f".analysis-{version_id}.json.tmp"
        temporary.unlink(missing_ok=True)
        if not committed and version_dir.exists():
            shutil.rmtree(version_dir)
        raise
    return analysis


def _rejection_rules(segment: dict, recipe: dict) -> tuple[set[str], set[str]]:
    rejected_paths = set()
    rejected_names = set()
    for value in (
        segment.get("rejected_frames", []),
        segment.get("bad_frames", []),
        segment.get("reject", []),
        recipe.get("deglare", {}).get("reject", []),
    ):
        for item in value:
            text = str(item)
            path = Path(text)
            if path.is_absolute() or "/" in text or "\\" in text:
                rejected_paths.add(_path_key(path))
            else:
                rejected_names.add(path.name.casefold())
                rejected_names.add(path.stem.casefold())
    return rejected_paths, rejected_names


def _is_rejected(path: Path, rules: tuple[set[str], set[str]]) -> bool:
    rejected_paths, rejected_names = rules
    return (
        _path_key(path) in rejected_paths
        or path.name.casefold() in rejected_names
        or path.stem.casefold() in rejected_names
    )


def _render_output_names(
    paths: list[Path], rules: tuple[set[str], set[str]]
) -> dict[int, str]:
    """Assign deterministic names while preserving non-conflicting frame stems."""
    kept = [(index, path) for index, path in enumerate(paths) if not _is_rejected(path, rules)]
    groups: dict[str, list[tuple[int, Path]]] = {}
    for index, path in kept:
        groups.setdefault(f"{path.stem}.jpg".casefold(), []).append((index, path))

    if all(len(group) == 1 for group in groups.values()):
        return {index: f"{path.stem}.jpg" for index, path in kept}

    return {
        index: f"{ordinal:06d}__{path.stem}.jpg"
        for ordinal, (index, path) in enumerate(kept, start=1)
    }


def _analysis_gain_by_path(paths: list[Path], analysis: dict) -> list[float]:
    gains = analysis.get("gain", [])
    sources = analysis.get("sources", [])
    if analysis.get("frame_count") != len(paths):
        raise ValueError("analysis frame count does not match segment")
    if len(gains) != len(paths):
        raise ValueError("analysis frame count does not match segment")
    if len(sources) != len(paths):
        raise ValueError("analysis source count does not match segment")
    validated_gains = []
    for path, source, gain in zip(paths, sources, gains):
        current = _source_identity(path)
        if not _same_identity(source, current):
            raise ValueError(f"source identity does not match analysis: {path.name}")
        try:
            gain = float(gain)
        except (TypeError, ValueError) as error:
            raise ValueError("analysis gain must be a finite number") from error
        if not np.isfinite(gain) or gain < 0 or gain > 16:
            raise ValueError("analysis gain must be finite and between 0 and 16")
        validated_gains.append(gain)
    return validated_gains


def _golden_strength(recipe: dict, path: Path) -> float:
    settings = recipe.get("enhance_golden", {})
    if not settings.get("enable", False):
        return 0.0
    full = float(
        settings.get(
            "strength",
            GOLDEN_STRENGTH.get(settings.get("level", "strong"), GOLDEN_STRENGTH["strong"]),
        )
    )
    core = settings.get("core")
    if not core:
        return full
    return golden_ramp_strength(
        frame_num(path), core, settings.get("ramp", 10), full
    )


def _publish_render(temporary: Path, result: Path) -> None:
    backup = result.parent / f".result-backup-{uuid.uuid4().hex}"
    had_result = result.exists()
    if had_result:
        os.replace(result, backup)
    try:
        os.replace(temporary, result)
    except BaseException:
        if had_result and backup.exists() and not result.exists():
            os.replace(backup, result)
        raise
    if backup.exists():
        try:
            shutil.rmtree(backup)
        except OSError:
            # Publication already succeeded; a stale backup is safer than
            # reporting failure after replacing the official result.
            pass


def render_segment(
    segment: dict,
    recipe: dict,
    analysis: dict,
    target_dir: Path,
    progress: Callable,
    cancelled: Callable,
) -> RenderResult:
    """Render every kept frame from its source and publish the result directory."""
    paths = _frame_paths(segment)
    gains = _analysis_gain_by_path(paths, analysis)
    rejection_rules = _rejection_rules(segment, recipe)
    output_names = _render_output_names(paths, rejection_rules)
    decode = recipe.get("decode", {})
    configured_grade = recipe.get("grade", {})
    if isinstance(configured_grade, str):
        grade_settings = {"style": configured_grade}
    elif isinstance(configured_grade, dict):
        grade_settings = configured_grade
    else:
        raise ValueError("grade settings must be a mapping or style name")
    style = grade_settings.get("style", recipe.get("style", "none"))
    quality = recipe.get("jpeg_quality", recipe.get("quality", 95))
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    temporary = target_dir / f".rendering-{uuid.uuid4().hex}"
    temporary.mkdir()
    result_dir = target_dir / "result"
    saved = 0
    rejected_count = 0

    try:
        for index, (path, gain) in enumerate(zip(paths, gains), start=1):
            _check_cancelled(cancelled)
            if _is_rejected(path, rejection_rules):
                rejected_count += 1
                progress(index, len(paths), frame=str(path), rejected=True)
                continue

            output_name = output_names[index - 1]

            rgb = load_image(path, decode, half=False)
            rgb = apply_gain(rgb, gain)
            rgb = grade_by_style(rgb, style, grade_settings)
            rgb = enhance_golden(rgb, _golden_strength(recipe, path))
            save_jpeg(rgb, temporary / output_name, quality=quality)
            saved += 1
            progress(index, len(paths), frame=str(path), rejected=False)

        _check_cancelled(cancelled)
        _publish_render(temporary, result_dir)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise

    return RenderResult(saved, str(result_dir), rejected_count)
