"""Verified, source-safe project archival."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .video_export import sanitize_windows_filename


ORIGINAL_SUFFIXES = {".arw", ".jpg", ".jpeg"}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_component(value: Any, fallback: str) -> str:
    sanitized = sanitize_windows_filename(str(value or fallback))
    if sanitized.lower().endswith(".mp4"):
        sanitized = sanitized[:-4]
    return sanitized or fallback


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _overlaps(left: Path, right: Path) -> bool:
    return _is_within(left, right) or _is_within(right, left)


def _validate_roots(
    project: dict,
    workspace: Path,
    output_dir: Path,
    archive_dir: Path,
) -> None:
    managed_roots = {
        "workspace": workspace,
        "output": output_dir,
        "archive": archive_dir,
    }
    names = list(managed_roots)
    for index, left_name in enumerate(names):
        for right_name in names[index + 1 :]:
            if _overlaps(managed_roots[left_name], managed_roots[right_name]):
                raise ValueError(f"{left_name} and {right_name} directories must not overlap")

    source_value = project.get("source_dir")
    if not source_value:
        raise ValueError("project source_dir is required")
    source_dir = Path(source_value).resolve()
    for name, managed_root in managed_roots.items():
        if _overlaps(source_dir, managed_root):
            raise ValueError(f"source and {name} directories must not overlap")


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _copy(source: Path, destination: Path, verification: list[tuple[Path, Path]]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    verification.append((source, destination))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path.cwd(),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _segment_source_files(segment: dict, source_root: Path) -> list[tuple[Path, Path]]:
    frames = segment.get("frames")
    if not isinstance(frames, list) or not frames:
        frames = segment.get("source_files", segment.get("frame_paths", []))
    if not isinstance(frames, list):
        raise ValueError("segment source files must be a list")

    resolved: list[tuple[Path, Path]] = []
    seen: set[Path] = set()
    for frame in frames:
        value = frame.get("path") if isinstance(frame, dict) else frame
        if not isinstance(value, str):
            raise ValueError("segment source file path is invalid")
        source = Path(value).resolve()
        try:
            relative = source.relative_to(source_root)
        except ValueError as exc:
            raise ValueError(f"source file is outside project source_dir: {source}") from exc
        if source in seen:
            continue
        if not source.is_file() or source.suffix.casefold() not in ORIGINAL_SUFFIXES:
            raise FileNotFoundError(f"source file does not exist or is unsupported: {source}")
        seen.add(source)
        resolved.append((source, relative))
    return resolved


def archive_project(
    project: dict,
    workspace: Path,
    output_dir: Path,
    archive_dir: Path,
    timestamp: str | None = None,
    segment_ids: list[str] | None = None,
    clear_workspace: bool = True,
    check_cancelled: Callable[[], None] | None = None,
) -> Path:
    workspace = Path(workspace).resolve()
    output_dir = Path(output_dir).resolve()
    archive_dir = Path(archive_dir).resolve()
    _validate_roots(project, workspace, output_dir, archive_dir)
    if not workspace.is_dir():
        raise FileNotFoundError(f"workspace does not exist: {workspace}")

    archive_name = timestamp or datetime.now().astimezone().strftime("%Y-%m-%d_%H%M%S")
    if Path(archive_name).name != archive_name or archive_name in {".", ".."}:
        raise ValueError("invalid archive timestamp")
    archive_dir.mkdir(parents=True, exist_ok=True)
    destination = archive_dir / archive_name
    if timestamp is None:
        base_name = archive_name
        sequence = 2
        while destination.exists():
            archive_name = f"{base_name}_{sequence:02d}"
            destination = archive_dir / archive_name
            sequence += 1
    elif destination.exists():
        raise FileExistsError(f"archive already exists: {destination}")
    temporary = archive_dir / f".archiving-{archive_name}-{uuid.uuid4().hex}"
    verification: list[tuple[Path, Path]] = []
    segment_manifest = []
    output_paths: list[str] = []
    source_root = Path(project["source_dir"]).resolve()

    def ensure_not_cancelled() -> None:
        if check_cancelled is not None:
            check_cancelled()

    all_segments = project.get("segments", [])
    if segment_ids is None:
        selected_segments = all_segments
    else:
        requested = list(dict.fromkeys(segment_ids))
        known = {str(segment.get("id")): segment for segment in all_segments}
        if not requested or any(segment_id not in known for segment_id in requested):
            raise ValueError("segment_ids must reference existing segments")
        requested_set = set(requested)
        selected_segments = [
            segment for segment in all_segments
            if str(segment.get("id")) in requested_set
        ]
    try:
        ensure_not_cancelled()
        temporary.mkdir(parents=True)

        used_names: set[str] = set()
        for index, segment in enumerate(selected_segments, start=1):
            ensure_not_cancelled()
            segment_id = _safe_component(segment.get("id"), f"segment-{index}")
            base_name = _safe_component(segment.get("name"), f"segment-{index}")
            segment_name = base_name
            suffix = 2
            while segment_name.casefold() in used_names:
                segment_name = f"{base_name}_{suffix}"
                suffix += 1
            used_names.add(segment_name.casefold())

            source_segment = workspace / "segments" / segment_id
            archived_segment = temporary / segment_name
            archived_segment.mkdir(parents=True)
            recipe_file = source_segment / "recipe.json"
            analysis_file = source_segment / "analysis.json"
            if recipe_file.is_file():
                _copy(recipe_file, archived_segment / "recipe.json", verification)
            else:
                _write_json(archived_segment / "recipe.json", segment.get("recipe", {}))
            if analysis_file.is_file():
                _copy(analysis_file, archived_segment / "analysis.json", verification)
            elif isinstance(segment.get("analysis"), dict):
                _write_json(archived_segment / "analysis.json", segment["analysis"])

            originals: list[str] = []
            source_names: list[str] = []
            for source_file, relative in _segment_source_files(segment, source_root):
                ensure_not_cancelled()
                original_destination = archived_segment / "originals" / relative
                _copy(source_file, original_destination, verification)
                originals.append(original_destination.relative_to(temporary).as_posix())
                source_names.append(source_file.name)

            segment_manifest.append(
                {
                    "id": segment.get("id"),
                    "name": segment.get("name", segment_name),
                    "archive_name": segment_name,
                    "source_file_count": len(originals),
                    "first_file": source_names[0] if source_names else None,
                    "last_file": source_names[-1] if source_names else None,
                    "originals": originals,
                    "recipe": segment.get("recipe", {}),
                    "focal_length": segment.get("focal_length"),
                    "captured_start": segment.get("captured_start"),
                    "captured_end": segment.get("captured_end"),
                    "capture_date": segment.get("capture_date"),
                    "capture_time": segment.get("capture_time"),
                    "time_range": segment.get("time_range"),
                    "latitude": segment.get("latitude"),
                    "longitude": segment.get("longitude"),
                    "location": segment.get("location"),
                }
            )

        if segment_ids is None and output_dir.is_dir():
            for output_file in sorted(path for path in output_dir.rglob("*") if path.is_file()):
                relative = output_file.relative_to(output_dir)
                target = temporary / "output" / relative
                _copy(output_file, target, verification)
                output_paths.append((Path("output") / relative).as_posix())
        elif segment_ids is not None:
            seen_outputs: set[Path] = set()
            for segment in selected_segments:
                artifact = segment.get("export_artifact")
                artifact_value = artifact.get("path") if isinstance(artifact, dict) else None
                if not isinstance(artifact_value, str):
                    continue
                output_file = Path(artifact_value).resolve()
                if (
                    output_file in seen_outputs
                    or not output_file.is_file()
                    or not _is_within(output_file, output_dir)
                ):
                    continue
                seen_outputs.add(output_file)
                relative = output_file.relative_to(output_dir)
                target = temporary / "output" / relative
                _copy(output_file, target, verification)
                output_paths.append((Path("output") / relative).as_posix())

        for source, copied in verification:
            ensure_not_cancelled()
            if source.stat().st_size != copied.stat().st_size or _digest(source) != _digest(copied):
                raise OSError(f"archive verification failed: {source.name}")

        ensure_not_cancelled()
        manifest = {
            "schema_version": 2,
            "archived_at": _now(),
            "source_dir": project.get("source_dir"),
            "source_file_count": sum(item["source_file_count"] for item in segment_manifest),
            "segment_count": len(segment_manifest),
            "segments": segment_manifest,
            "recipes": [item["recipe"] for item in segment_manifest],
            "media": {
                "outputs": output_paths,
            },
            "git_commit": _git_commit(),
        }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(temporary, destination)

        if clear_workspace:
            for child in list(workspace.iterdir()):
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        return destination
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        raise
