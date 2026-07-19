"""Read-only source scanning and pure segment editing helpers."""
from __future__ import annotations

import math
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import exifread
from PIL import Image, UnidentifiedImageError


SUPPORTED_EXTENSIONS = {".arw", ".jpg", ".jpeg"}
EXIF_BINARY_FIELDS = {"JPEGThumbnail", "TIFFThumbnail", "Filename"}


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
    latitude: float | None = None
    longitude: float | None = None


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


def _gps_decimal(value: Any, reference: Any) -> float | None:
    values = getattr(value, "values", value)
    if not isinstance(values, (list, tuple)) or len(values) < 3:
        return None
    parts = [_number(item) for item in values[:3]]
    if any(item is None for item in parts):
        return None
    coordinate = float(parts[0]) + float(parts[1]) / 60 + float(parts[2]) / 3600
    ref = str(_first_value(reference) or "").strip().upper()
    return -coordinate if ref in {"S", "W"} else coordinate


def _gps_coordinates(
    latitude: Any,
    latitude_ref: Any,
    longitude: Any,
    longitude_ref: Any,
) -> tuple[float | None, float | None]:
    return (
        _gps_decimal(latitude, latitude_ref),
        _gps_decimal(longitude, longitude_ref),
    )


def _jpeg_gps(exif: Any) -> tuple[float | None, float | None]:
    try:
        gps = exif.get_ifd(34853)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None, None
    if not isinstance(gps, dict):
        return None, None
    return _gps_coordinates(gps.get(2), gps.get(1), gps.get(4), gps.get(3))


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


def _jpeg_exif_value(exif: Any, tag_id: int) -> Any | None:
    value = exif.get(tag_id)
    if value is not None:
        return value
    try:
        return exif.get_ifd(34665).get(tag_id)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def _read_jpeg_frame(path: Path) -> FrameInfo:
    with Image.open(path) as image:
        width, height = image.size
        exif = image.getexif()
        capture_tag = (
            _jpeg_exif_value(exif, 36867)
            or _jpeg_exif_value(exif, 36868)
            or _jpeg_exif_value(exif, 306)
        )
        latitude, longitude = _jpeg_gps(exif)
        return FrameInfo(
            path=str(path.resolve()),
            name=path.name,
            captured_at=_captured_at(capture_tag, path),
            width=width,
            height=height,
            shutter=_number(_jpeg_exif_value(exif, 33434)),
            aperture=_number(_jpeg_exif_value(exif, 33437)),
            iso=_integer(_jpeg_exif_value(exif, 34855)),
            exposure_bias=_number(_jpeg_exif_value(exif, 37380)),
            exposure_mode=_text(
                _jpeg_exif_value(exif, 41986) or _jpeg_exif_value(exif, 34850)
            ),
            metering_mode=_text(_jpeg_exif_value(exif, 37383)),
            focal_length=_number(_jpeg_exif_value(exif, 37386)),
            white_balance=_text(_jpeg_exif_value(exif, 41987)),
            latitude=latitude,
            longitude=longitude,
        )
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            return exif.get(36867) or exif.get(36868) or exif.get(306)
    except UnidentifiedImageError:
        return None


def _read_frame(path: Path) -> FrameInfo:
    if path.suffix.casefold() in {".jpg", ".jpeg"}:
        return _read_jpeg_frame(path)
    with path.open("rb") as handle:
        tags = exifread.process_file(handle, details=False, strict=False)
    width, height = _dimensions(path, tags)
    capture_tag = _tag(
        tags, "EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "Image DateTime"
    ) or _jpeg_capture_tag(path)
    latitude, longitude = _gps_coordinates(
        _tag(tags, "GPS GPSLatitude"),
        _tag(tags, "GPS GPSLatitudeRef"),
        _tag(tags, "GPS GPSLongitude"),
        _tag(tags, "GPS GPSLongitudeRef"),
    )
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
        latitude=latitude,
        longitude=longitude,
    )


def read_exif_details(path: Path) -> list[dict[str, str]]:
    source = Path(path)
    with source.open("rb") as handle:
        tags = exifread.process_file(handle, details=True, strict=False)
    entries = []
    for name in sorted(tags, key=str.casefold):
        if name in EXIF_BINARY_FIELDS:
            continue
        value = str(tags[name]).strip()
        if not value:
            continue
        group, _, tag_name = name.partition(" ")
        entries.append({
            "group": group if tag_name else "EXIF",
            "tag": tag_name or name,
            "value": value[:4096] + ("…" if len(value) > 4096 else ""),
        })
    return entries


def scan_source(
    source_dir: Path,
    *,
    max_workers: int | None = None,
    progress: Callable[[int, int, Path], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> list[FrameInfo]:
    source = Path(source_dir).resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Source directory does not exist: {source}")
    paths = sorted(
        [
        path
        for path in source.rglob("*")
        if path.is_file() and path.suffix.casefold() in SUPPORTED_EXTENSIONS
        ],
        key=lambda path: (path.name.casefold(), path.name, str(path).casefold()),
    )
    if not paths:
        return []
    workers = max_workers or min(8, max(2, (os.cpu_count() or 2)))
    workers = max(1, min(int(workers), len(paths), 16))
    frames = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="media-scan") as executor:
        for index, frame in enumerate(executor.map(_read_frame, paths), start=1):
            if cancelled and cancelled():
                executor.shutdown(wait=False, cancel_futures=True)
                raise RuntimeError("scan cancelled")
            frames.append(frame)
            if progress:
                progress(index, len(paths), Path(frame.path))
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


def capture_duration_seconds(frames: list[FrameInfo]) -> float | None:
    times = [_parse_time(frame.captured_at) for frame in frames]
    valid = [value for value in times if value is not None]
    if len(valid) < 2:
        return 0.0 if valid else None
    try:
        return max(0.0, (valid[-1] - valid[0]).total_seconds())
    except TypeError:
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


def _format_time_range(start: str | None, end: str | None) -> str | None:
    left = _parse_time(start)
    right = _parse_time(end)
    if left is None or right is None:
        return None
    if left.date() == right.date():
        return f"{left:%Y-%m-%d %H:%M:%S}–{right:%H:%M:%S}"
    return f"{left:%Y-%m-%d %H:%M:%S}–{right:%Y-%m-%d %H:%M:%S}"


def _format_capture_parts(start: str | None, end: str | None) -> tuple[str | None, str | None]:
    left = _parse_time(start)
    right = _parse_time(end)
    if left is None or right is None:
        return None, None
    capture_date = (
        f"{left:%Y-%m-%d}"
        if left.date() == right.date()
        else f"{left:%Y-%m-%d}–{right:%Y-%m-%d}"
    )
    return capture_date, f"{left:%H:%M:%S}–{right:%H:%M:%S}"


def _format_location(latitude: float, longitude: float) -> str:
    latitude_ref = "N" if latitude >= 0 else "S"
    longitude_ref = "E" if longitude >= 0 else "W"
    return f"{abs(latitude):.6f}°{latitude_ref}, {abs(longitude):.6f}°{longitude_ref}"


def _refresh_segment_metadata(segment: dict) -> None:
    frames = segment.get("frames", [])
    focals = [float(item["focal_length"]) for item in frames if item.get("focal_length") is not None]
    if focals:
        low, high = min(focals), max(focals)
        segment["focal_length"] = round(sum(focals) / len(focals), 2) if high - low <= 0.5 else f"{low:g}–{high:g}"
    else:
        segment["focal_length"] = None
    captured = [item.get("captured_at") for item in frames if item.get("captured_at")]
    segment["captured_start"] = captured[0] if captured else None
    segment["captured_end"] = captured[-1] if captured else None
    segment["time_range"] = _format_time_range(
        segment["captured_start"], segment["captured_end"]
    )
    segment["capture_date"], segment["capture_time"] = _format_capture_parts(
        segment["captured_start"], segment["captured_end"]
    )
    coordinates = [
        (float(item["latitude"]), float(item["longitude"]))
        for item in frames
        if item.get("latitude") is not None and item.get("longitude") is not None
    ]
    if coordinates:
        segment["latitude"] = sum(item[0] for item in coordinates) / len(coordinates)
        segment["longitude"] = sum(item[1] for item in coordinates) / len(coordinates)
        segment["location"] = _format_location(segment["latitude"], segment["longitude"])
    else:
        segment["latitude"] = None
        segment["longitude"] = None
        segment["location"] = None


def _new_segment(frames: list[FrameInfo], number: int, start_index: int) -> dict:
    segment = {
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
    _refresh_segment_metadata(segment)
    return segment


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
    segment.pop("representative_url", None)
    segment.pop("representative_name", None)
    segment.pop("export_artifact", None)


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
    _refresh_segment_metadata(left)
    _refresh_segment_metadata(right)
    return result[:position] + [left, right] + result[position + 1 :]


def merge_segments(
    segments: list[dict], segment_ids: list[str] | str, right_id: str | None = None
) -> list[dict]:
    result = deepcopy(segments)
    requested = [segment_ids, right_id] if isinstance(segment_ids, str) else list(segment_ids)
    if len(requested) < 2 or any(not isinstance(item, str) for item in requested):
        raise ValueError("At least two segment IDs are required")
    if len(set(requested)) != len(requested):
        raise ValueError("Segment IDs must not contain duplicates")
    requested_set = set(requested)
    positions = [index for index, item in enumerate(result) if item.get("id") in requested_set]
    if len(positions) != len(requested):
        raise KeyError("Unknown segment ID")
    if positions != list(range(positions[0], positions[-1] + 1)):
        raise ValueError("Only contiguous segments may be merged")

    selected = [result[index] for index in positions]
    left = selected[0]
    left["source_files"] = [path for segment in selected for path in segment.get("source_files", [])]
    if any("frames" in segment for segment in selected):
        left["frames"] = [frame for segment in selected for frame in segment.get("frames", [])]
    left["frame_range"] = {
        "start": int(left.get("frame_range", {}).get("start", 0)),
        "end": int(selected[-1].get("frame_range", {}).get("end", len(left["source_files"]) - 1)),
    }
    rejected = set().union(*(set(segment.get("rejected_frames", [])) for segment in selected))
    left["rejected_frames"] = [path for path in left["source_files"] if path in rejected]
    _reset_processing(left)
    _refresh_segment_metadata(left)
    return result[:positions[0]] + [left] + result[positions[-1] + 1 :]


def reorder_segments(segments: list[dict], ordered_ids: list[str]) -> list[dict]:
    current_ids = [item.get("id") for item in segments]
    if len(ordered_ids) != len(current_ids) or set(ordered_ids) != set(current_ids):
        raise ValueError("Ordered IDs must contain every segment exactly once")
    if len(set(ordered_ids)) != len(ordered_ids):
        raise ValueError("Ordered IDs must not contain duplicates")
    by_id = {item["id"]: deepcopy(item) for item in segments}
    return [by_id[segment_id] for segment_id in ordered_ids]
