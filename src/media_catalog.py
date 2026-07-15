"""Read-only source scanning and pure segment editing helpers."""
from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import exifread
from PIL import Image, UnidentifiedImageError


SUPPORTED_EXTENSIONS = {".arw", ".jpg", ".jpeg"}


@dataclass(frozen=True)
class FrameInfo:
    path: str
    name: str
    captured_at: str | None
    width: int
    height: int
    shutter: float | None
    aperture: float | None
    iso: int | None
    exposure_bias: float | None
    exposure_mode: str | None
    metering_mode: str | None
    focal_length: float | None
    white_balance: str | None


def _tag(tags: dict[str, Any], *names: str) -> Any | None:
    for name in names:
        if name in tags:
            return tags[name]
    return None


def _first_value(value: Any) -> Any:
    values = getattr(value, "values", value)
    if isinstance(values, (list, tuple)):
        return values[0] if values else None
    return values


def _number(value: Any) -> float | None:
    value = _first_value(value)
    if value is None:
        return None
    numerator = getattr(value, "num", None)
    denominator = getattr(value, "den", None)
    if numerator is not None and denominator:
        return float(numerator) / float(denominator)
    try:
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _captured_at(value: Any, path: Path) -> str:
    text = _text(value)
    if text:
        for pattern in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(text, pattern).isoformat()
            except ValueError:
                continue
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()


def _dimensions(path: Path, tags: dict[str, Any]) -> tuple[int, int]:
    if path.suffix.casefold() in {".jpg", ".jpeg"}:
        try:
            with Image.open(path) as image:
                return image.size
        except UnidentifiedImageError:
            pass
    width = _integer(_tag(tags, "EXIF ExifImageWidth", "Image ImageWidth")) or 0
    height = _integer(_tag(tags, "EXIF ExifImageLength", "Image ImageLength")) or 0
    return width, height


def _jpeg_capture_tag(path: Path) -> Any | None:
    if path.suffix.casefold() not in {".jpg", ".jpeg"}:
        return None
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            return exif.get(36867) or exif.get(36868) or exif.get(306)
    except UnidentifiedImageError:
        return None


def _read_frame(path: Path) -> FrameInfo:
    with path.open("rb") as handle:
        tags = exifread.process_file(handle, details=False, strict=False)
    width, height = _dimensions(path, tags)
    capture_tag = _tag(
        tags, "EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "Image DateTime"
    ) or _jpeg_capture_tag(path)
    return FrameInfo(
        path=str(path.resolve()),
        name=path.name,
        captured_at=_captured_at(capture_tag, path),
        width=width,
        height=height,
        shutter=_number(_tag(tags, "EXIF ExposureTime")),
        aperture=_number(_tag(tags, "EXIF FNumber")),
        iso=_integer(_tag(tags, "EXIF ISOSpeedRatings", "EXIF PhotographicSensitivity")),
        exposure_bias=_number(_tag(tags, "EXIF ExposureBiasValue")),
        exposure_mode=_text(_tag(tags, "EXIF ExposureMode", "Image ExposureProgram")),
        metering_mode=_text(_tag(tags, "EXIF MeteringMode")),
        focal_length=_number(_tag(tags, "EXIF FocalLength")),
        white_balance=_text(_tag(tags, "EXIF WhiteBalance")),
    )


def scan_source(source_dir: Path) -> list[FrameInfo]:
    source = Path(source_dir).resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Source directory does not exist: {source}")
    paths = [
        path
        for path in source.rglob("*")
        if path.is_file() and path.suffix.casefold() in SUPPORTED_EXTENSIONS
    ]
    frames = [_read_frame(path) for path in paths]
    return sorted(
        frames,
        key=lambda item: (
            item.captured_at is None,
            item.captured_at or "",
            item.name.casefold(),
            item.name,
            item.path.casefold(),
        ),
    )


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _exposure_value(frame: FrameInfo) -> float | None:
    if not frame.shutter or not frame.aperture or not frame.iso:
        return frame.exposure_bias
    if frame.shutter <= 0 or frame.aperture <= 0 or frame.iso <= 0:
        return frame.exposure_bias
    value = math.log2((frame.aperture * frame.aperture) / frame.shutter)
    value -= math.log2(frame.iso / 100.0)
    if frame.exposure_bias is not None:
        value -= frame.exposure_bias
    return value


def _changed(left: str | None, right: str | None) -> bool:
    return left is not None and right is not None and left != right


def _should_split(left: FrameInfo, right: FrameInfo, settings: dict) -> bool:
    gap_limit = float(settings.get("gap_seconds", 120))
    left_time = _parse_time(left.captured_at)
    right_time = _parse_time(right.captured_at)
    if left_time is not None and right_time is not None:
        try:
            if (right_time - left_time).total_seconds() > gap_limit:
                return True
        except TypeError:
            pass

    focal_tolerance = float(settings.get("focal_length_tolerance", 0.5))
    if left.focal_length is not None and right.focal_length is not None:
        if abs(left.focal_length - right.focal_length) > focal_tolerance:
            return True

    if _changed(left.exposure_mode, right.exposure_mode):
        return True
    if _changed(left.metering_mode, right.metering_mode):
        return True

    left_ev = _exposure_value(left)
    right_ev = _exposure_value(right)
    ev_limit = float(settings.get("exposure_ev_jump", 1.0))
    return (
        left_ev is not None
        and right_ev is not None
        and abs(left_ev - right_ev) > ev_limit
    )


def _new_segment(frames: list[FrameInfo], number: int, start_index: int) -> dict:
    return {
        "id": str(uuid4()),
        "name": f"Segment {number:02d}",
        "source_files": [frame.path for frame in frames],
        "frames": [asdict(frame) for frame in frames],
        "frame_range": {
            "start": start_index,
            "end": start_index + len(frames) - 1,
        },
        "recipe": "natural",
        "rejected_frames": [],
        "analysis": None,
        "render_status": "pending",
        "output_files": [],
    }


def suggest_segments(frames: list[FrameInfo], settings: dict) -> list[dict]:
    if not frames:
        return []
    groups: list[tuple[int, list[FrameInfo]]] = []
    start = 0
    current = [frames[0]]
    for index, item in enumerate(frames[1:], start=1):
        if _should_split(frames[index - 1], item, settings):
            groups.append((start, current))
            start = index
            current = []
        current.append(item)
    groups.append((start, current))
    return [
        _new_segment(group, number, start_index)
        for number, (start_index, group) in enumerate(groups, start=1)
    ]


def _reset_processing(segment: dict) -> None:
    segment["analysis"] = None
    segment["render_status"] = "pending"
    segment["output_files"] = []


def split_segment(segments: list[dict], segment_id: str, frame_index: int) -> list[dict]:
    result = deepcopy(segments)
    position = next((i for i, item in enumerate(result) if item.get("id") == segment_id), None)
    if position is None:
        raise KeyError(f"Unknown segment: {segment_id}")
    original = result[position]
    source_files = original.get("source_files", [])
    if frame_index <= 0 or frame_index >= len(source_files):
        raise ValueError("Split index must be inside the segment")

    left = deepcopy(original)
    right = deepcopy(original)
    right["id"] = str(uuid4())
    right["name"] = f"{original.get('name', 'Segment')} 2"
    left["source_files"] = source_files[:frame_index]
    right["source_files"] = source_files[frame_index:]
    if "frames" in original:
        left["frames"] = original["frames"][:frame_index]
        right["frames"] = original["frames"][frame_index:]
    start = int(original.get("frame_range", {}).get("start", 0))
    left["frame_range"] = {"start": start, "end": start + frame_index - 1}
    right["frame_range"] = {
        "start": start + frame_index,
        "end": start + len(source_files) - 1,
    }
    rejected = set(original.get("rejected_frames", []))
    left["rejected_frames"] = [path for path in left["source_files"] if path in rejected]
    right["rejected_frames"] = [path for path in right["source_files"] if path in rejected]
    _reset_processing(left)
    _reset_processing(right)
    return result[:position] + [left, right] + result[position + 1 :]


def merge_segments(segments: list[dict], left_id: str, right_id: str) -> list[dict]:
    result = deepcopy(segments)
    left_position = next((i for i, item in enumerate(result) if item.get("id") == left_id), None)
    right_position = next((i for i, item in enumerate(result) if item.get("id") == right_id), None)
    if left_position is None or right_position is None:
        raise KeyError("Unknown segment ID")
    if right_position != left_position + 1:
        raise ValueError("Only adjacent left-to-right segments may be merged")

    left = result[left_position]
    right = result[right_position]
    left["source_files"] = left.get("source_files", []) + right.get("source_files", [])
    if "frames" in left or "frames" in right:
        left["frames"] = left.get("frames", []) + right.get("frames", [])
    left["frame_range"] = {
        "start": int(left.get("frame_range", {}).get("start", 0)),
        "end": int(right.get("frame_range", {}).get("end", len(left["source_files"]) - 1)),
    }
    rejected = set(left.get("rejected_frames", [])) | set(right.get("rejected_frames", []))
    left["rejected_frames"] = [path for path in left["source_files"] if path in rejected]
    _reset_processing(left)
    return result[:left_position] + [left] + result[right_position + 1 :]


def reorder_segments(segments: list[dict], ordered_ids: list[str]) -> list[dict]:
    current_ids = [item.get("id") for item in segments]
    if len(ordered_ids) != len(current_ids) or set(ordered_ids) != set(current_ids):
        raise ValueError("Ordered IDs must contain every segment exactly once")
    if len(set(ordered_ids)) != len(ordered_ids):
        raise ValueError("Ordered IDs must not contain duplicates")
    by_id = {item["id"]: deepcopy(item) for item in segments}
    return [by_id[segment_id] for segment_id in ordered_ids]
