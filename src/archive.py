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
from typing import Any

from .video_export import sanitize_windows_filename


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


def _source_file_count(project: dict) -> int:
    frame_paths = {
        str(frame)
        for segment in project.get("segments", [])
        for frame in segment.get("frames", segment.get("frame_paths", []))
    }
    if frame_paths:
        return len(frame_paths)
    source_dir = Path(project.get("source_dir", ""))
    if not source_dir.is_dir():
        return 0
    return sum(
        1
        for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".arw", ".jpg", ".jpeg"}
    )


def archive_project(
    project: dict,
    workspace: Path,
    output_dir: Path,
    archive_dir: Path,
    timestamp: str | None = None,
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
    if destination.exists():
        raise FileExistsError(f"archive already exists: {destination}")
    temporary = archive_dir / f".archiving-{archive_name}-{uuid.uuid4().hex}"
    verification: list[tuple[Path, Path]] = []
    segment_manifest = []
    preview_paths: list[str] = []
    output_paths: list[str] = []

    try:
        temporary.mkdir(parents=True)
        project_file = workspace / "project.json"
        if project_file.is_file():
            _copy(project_file, temporary / "project.json", verification)
        else:
            _write_json(temporary / "project.json", project)

        used_names: set[str] = set()
        for index, segment in enumerate(project.get("segments", []), start=1):
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
            elif "analysis" in segment:
                _write_json(archived_segment / "analysis.json", segment["analysis"])

            result_dir = source_segment / "result"
            jpeg_count = 0
            if result_dir.is_dir():
                for frame in sorted(result_dir.iterdir(), key=lambda path: path.name.casefold()):
                    if frame.is_file() and frame.suffix.lower() in {".jpg", ".jpeg"}:
                        _copy(frame, archived_segment / frame.name, verification)
                        jpeg_count += 1

            preview_candidates = [source_segment / "preview.mp4"]
            configured_preview = segment.get("preview_file") or segment.get("preview")
            if configured_preview:
                preview_candidates.append(Path(configured_preview))
            preview_destination = None
            for candidate in preview_candidates:
                if candidate.is_file():
                    preview_destination = temporary / f"{segment_name}_preview.mp4"
                    _copy(candidate, preview_destination, verification)
                    preview_paths.append(preview_destination.name)
                    break

            segment_manifest.append(
                {
                    "id": segment.get("id"),
                    "name": segment.get("name", segment_name),
                    "archive_name": segment_name,
                    "source_frame_count": len(segment.get("frames", segment.get("frame_paths", []))),
                    "jpeg_count": jpeg_count,
                    "recipe": segment.get("recipe", {}),
                    "preview": preview_destination.name if preview_destination else None,
                }
            )

        previews_dir = workspace / "previews"
        if previews_dir.is_dir():
            for preview in sorted(previews_dir.rglob("*.mp4")):
                name = sanitize_windows_filename(preview.name)
                target = temporary / name
                counter = 2
                while target.exists():
                    target = temporary / f"{Path(name).stem}_{counter}.mp4"
                    counter += 1
                _copy(preview, target, verification)
                preview_paths.append(target.name)

        if output_dir.is_dir():
            for output_file in sorted(path for path in output_dir.rglob("*") if path.is_file()):
                relative = output_file.relative_to(output_dir)
                target = temporary / "output" / relative
                _copy(output_file, target, verification)
                output_paths.append((Path("output") / relative).as_posix())

        for source, copied in verification:
            if source.stat().st_size != copied.stat().st_size or _digest(source) != _digest(copied):
                raise OSError(f"archive verification failed: {source.name}")

        manifest = {
            "schema_version": 1,
            "archived_at": _now(),
            "source_dir": project.get("source_dir"),
            "source_file_count": _source_file_count(project),
            "segment_count": len(segment_manifest),
            "segments": segment_manifest,
            "recipes": [item["recipe"] for item in segment_manifest],
            "media": {
                "previews": preview_paths,
                "outputs": output_paths,
            },
            "git_commit": _git_commit(),
        }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(temporary, destination)

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
