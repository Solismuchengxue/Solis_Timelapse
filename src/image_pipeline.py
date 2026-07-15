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


def _gains(luminance: np.ndarray, recipe: dict) -> tuple[np.ndarray, np.ndarray]:
    combined = np.ones(len(luminance), dtype=np.float64)
    target = luminance.copy()
    deflicker = recipe.get("deflicker", {})
    if deflicker.get("enable", True):
        window = int(deflicker.get("window", 11))
        target = smooth_median(luminance, window)
        combined *= exposure_gain(
            luminance,
            window,
            deflicker.get("clip", (0.85, 1.2)),
        )

    lift_dark = recipe.get("lift_dark", {})
    if lift_dark.get("enable", False):
        corrected = luminance * combined
        window = int(lift_dark.get("window", 15))
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
    """Measure source frames at half resolution and atomically publish analysis."""
    paths = _frame_paths(segment)
    decode = recipe.get("decode", {})
    luminance = []
    sources = []
    for index, path in enumerate(paths, start=1):
        _check_cancelled(cancelled)
        rgb = load_image(path, decode, half=True)
        luminance.append(measure_luminance(rgb))
        sources.append(_source_identity(path))
        progress(index, len(paths), frame=str(path))

    measured = np.asarray(luminance, dtype=np.float64)
    gain, target = _gains(measured, recipe)
    analysis = {
        "schema_version": 1,
        "segment_id": segment.get("id"),
        "frame_count": len(paths),
        "sources": sources,
        "measured_luminance": measured.tolist(),
        "target_luminance": target.tolist(),
        "gain": gain.tolist(),
    }

    _check_cancelled(cancelled)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    destination = work_dir / "analysis.json"
    temporary = work_dir / "analysis.json.tmp"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            json.dump(analysis, output, ensure_ascii=False, indent=2)
            output.write("\n")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return analysis


def _rejected_names(segment: dict, recipe: dict) -> set[str]:
    rejected = set()
    for value in (
        segment.get("rejected_frames", []),
        segment.get("bad_frames", []),
        segment.get("reject", []),
        recipe.get("deglare", {}).get("reject", []),
    ):
        for item in value:
            path = Path(str(item))
            rejected.add(path.name.casefold())
            rejected.add(path.stem.casefold())
    return rejected


def _analysis_gain_by_path(paths: list[Path], analysis: dict) -> list[float]:
    gains = analysis.get("gain", [])
    sources = analysis.get("sources", [])
    if len(gains) != len(paths):
        raise ValueError("analysis frame count does not match segment")
    if not sources:
        return [float(value) for value in gains]
    if len(sources) != len(paths):
        raise ValueError("analysis source count does not match segment")

    expected = [str(path.resolve()).casefold() for path in paths]
    actual = [str(Path(item["path"]).resolve()).casefold() for item in sources]
    if actual != expected:
        raise ValueError("analysis sources do not match segment frame order")
    return [float(value) for value in gains]


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
        frame_num(path), core, int(settings.get("ramp", 10)), full
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
    rejected = _rejected_names(segment, recipe)
    decode = recipe.get("decode", {})
    configured_grade = recipe.get("grade", {})
    if isinstance(configured_grade, str):
        grade_settings = {"style": configured_grade}
    else:
        grade_settings = configured_grade
    style = grade_settings.get("style", recipe.get("style", "none"))
    quality = int(recipe.get("jpeg_quality", recipe.get("quality", 95)))
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    temporary = target_dir / f".rendering-{uuid.uuid4().hex}"
    temporary.mkdir()
    result_dir = target_dir / "result"
    saved = 0
    rejected_count = 0
    output_names = set()

    try:
        for index, (path, gain) in enumerate(zip(paths, gains), start=1):
            _check_cancelled(cancelled)
            if path.name.casefold() in rejected or path.stem.casefold() in rejected:
                rejected_count += 1
                progress(index, len(paths), frame=str(path), rejected=True)
                continue

            output_name = f"{path.stem}.jpg"
            folded_name = output_name.casefold()
            if folded_name in output_names:
                raise ValueError(f"duplicate output frame name: {output_name}")
            output_names.add(folded_name)

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
