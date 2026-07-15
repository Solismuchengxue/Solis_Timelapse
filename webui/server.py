"""Local Flask server for the Sony timelapse WebUI."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import threading
import webbrowser
from copy import deepcopy
from pathlib import Path, PureWindowsPath
from typing import Any, Callable

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import archive, config_io, image_pipeline, media_catalog, video_export
from src.project_store import ProjectStore
from src.runtime_env import (
    RuntimeEnvironment,
    load_runtime_environment,
    validate_runtime_environment,
)
from src.task_manager import (
    ACTIVE_STATES,
    TaskBusy,
    TaskContext,
    TaskManager,
    TaskNotCancellable,
)


WEBUI_DIR = Path(__file__).resolve().parent
CURRENT_MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".mp4"}
ARCHIVE_MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".mp4"}
RUNTIME_ROOT_KEYS = ("workspace_dir", "output_dir", "archive_dir")


class ApiError(RuntimeError):
    def __init__(self, message: str, code: str = "invalid_request", status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def _error(message: str, code: str, status: int):
    return jsonify({"error": message, "code": code}), status


def _safe_media_path(root: Path, relative: str, suffixes: set[str], allowed: Callable[[Path], bool]) -> Path | None:
    try:
        base = Path(root).resolve()
        candidate = (base / relative).resolve()
        candidate.relative_to(base)
    except (OSError, ValueError):
        return None
    if not candidate.is_file() or candidate.suffix.casefold() not in suffixes or not allowed(candidate):
        return None
    return candidate


def _safe_input_directory(root: Path, relative: str) -> tuple[Path, str] | None:
    if not isinstance(relative, str) or "\x00" in relative or "\\" in relative:
        return None
    windows_path = PureWindowsPath(relative)
    native_path = Path(relative)
    if windows_path.drive or windows_path.root or native_path.is_absolute():
        return None
    if any(part in {".", ".."} for part in native_path.parts):
        return None
    try:
        base = Path(root).resolve(strict=True)
        candidate = (base / native_path).resolve(strict=True)
        resolved_relative = candidate.relative_to(base)
    except (OSError, ValueError):
        return None
    if not candidate.is_dir():
        return None
    value = "" if resolved_relative == Path(".") else resolved_relative.as_posix()
    return candidate, value


def _paths_overlap(left: Path, right: Path) -> bool:
    left = Path(left).resolve()
    right = Path(right).resolve()
    return left.is_relative_to(right) or right.is_relative_to(left)


def _validate_runtime_roots(roots: dict[str, Path]) -> None:
    values = list(roots.values())
    for index, left in enumerate(values):
        for right in values[index + 1 :]:
            if _paths_overlap(left, right):
                raise ValueError("runtime roots overlap")


def _configured_root(value: Any) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = config_io.ROOT / path
    return path.resolve()


def _configured_roots(settings: dict) -> dict[str, Path]:
    return {key: _configured_root(settings[key]) for key in RUNTIME_ROOT_KEYS}


def _safe_archive_timestamp_dir(root: Path, timestamp: str) -> Path | None:
    if not isinstance(timestamp, str) or not timestamp or timestamp in {".", ".."}:
        return None
    windows_path = PureWindowsPath(timestamp)
    native_path = Path(timestamp)
    if windows_path.drive or windows_path.root or native_path.is_absolute():
        return None
    try:
        base = Path(root).resolve()
        candidate = (base / native_path).resolve()
    except OSError:
        return None
    if not candidate.is_relative_to(base) or candidate.parent != base:
        return None
    return candidate


def _current_media_allowed(current_root: Path, candidate: Path) -> bool:
    try:
        relative = candidate.relative_to(current_root.resolve())
    except ValueError:
        return False
    parts = relative.parts
    return (
        len(parts) >= 2 and parts[0] == "previews"
    ) or (
        len(parts) >= 4 and parts[0] == "segments" and parts[2] in {"thumbnails", "result"}
    )


def _manifest_media_paths(timestamp_root: Path, manifest: dict, kind: str) -> list[Path]:
    media = manifest.get("media", {}) if isinstance(manifest.get("media"), dict) else {}
    values = media.get(kind, [])
    if not isinstance(values, list):
        return []
    allowed_suffixes = {".mp4"} if kind == "outputs" else ARCHIVE_MEDIA_SUFFIXES
    result = []
    for value in values:
        if not isinstance(value, str):
            continue
        windows_path = PureWindowsPath(value)
        if windows_path.drive or windows_path.root or Path(value).is_absolute():
            continue
        try:
            candidate = (timestamp_root / value).resolve()
        except OSError:
            continue
        if candidate.is_relative_to(timestamp_root) and candidate.suffix.casefold() in allowed_suffixes:
            result.append(candidate)
    return result


def _archive_media_allowed(archive_root: Path, candidate: Path) -> bool:
    try:
        base = archive_root.resolve()
        relative = candidate.relative_to(base)
    except (OSError, ValueError):
        return False
    if len(relative.parts) < 2:
        return False
    timestamp_root = _safe_archive_timestamp_dir(base, relative.parts[0])
    if timestamp_root is None or not candidate.is_relative_to(timestamp_root):
        return False
    manifest_path = timestamp_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(manifest, dict):
        return False
    if candidate.suffix.casefold() in {".jpg", ".jpeg", ".png", ".webp"}:
        for segment in manifest.get("segments", []):
            archive_name = segment.get("archive_name") if isinstance(segment, dict) else None
            if isinstance(archive_name, str):
                segment_root = (timestamp_root / archive_name).resolve()
                if candidate.is_relative_to(segment_root):
                    return False
    declared = {
        path
        for kind in ("previews", "outputs", "representatives")
        for path in _manifest_media_paths(timestamp_root, manifest, kind)
    }
    return candidate in declared


def _natural_key(path: Path) -> list[object]:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", path.name)]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _result_identity(result_dir: Path) -> dict:
    root = Path(result_dir)
    frames = sorted(
        (
            path
            for path in root.iterdir()
            if path.is_file() and path.suffix.casefold() in {".jpg", ".jpeg"}
        ),
        key=_natural_key,
    ) if root.is_dir() else []
    digest = hashlib.sha256()
    for frame in frames:
        relative_name = frame.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative_name).to_bytes(8, "big"))
        digest.update(relative_name)
        digest.update(frame.stat().st_size.to_bytes(8, "big"))
        with frame.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    return {"frame_count": len(frames), "result_signature": digest.hexdigest()}


def _expected_result_count(segment: dict) -> int:
    frames = segment.get("frames", segment.get("source_files", []))
    rejected = {
        value.casefold()
        for value in segment.get("rejected_frames", [])
        if isinstance(value, str)
    }
    rejected_count = 0
    for frame in frames:
        value = frame.get("path") if isinstance(frame, dict) else frame
        if not isinstance(value, str):
            continue
        path = Path(value)
        if value.casefold() in rejected or path.name.casefold() in rejected:
            rejected_count += 1
    return len(frames) - rejected_count


def _export_filename(segment: dict) -> str:
    segment_id = str(segment.get("id", "segment"))
    short_id = hashlib.sha256(segment_id.encode("utf-8")).hexdigest()[:8]
    return video_export.sanitize_windows_filename(
        f"{segment.get('name', segment_id)}-{short_id}.mp4"
    )


def _task_response(task: dict) -> dict:
    """Return task data without task exception text or source paths."""
    safe = deepcopy(task)
    if safe.get("error"):
        safe["error"] = "任务失败，请查看任务日志。"
    detail = safe.get("detail")
    if isinstance(detail, dict):
        safe["detail"] = {
            key: Path(value).name if key in {"file", "frame", "current_file"} and isinstance(value, str) else value
            for key, value in detail.items()
        }
    safe["logs"] = [str(entry) for entry in safe.get("logs", [])]
    return safe


def _body() -> dict:
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ApiError("请求内容必须是 JSON 对象", "invalid_json")
    return value


def _path_value(body: dict, key: str) -> Path:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(f"{key} 必须是非空路径", "invalid_path")
    path = Path(value).expanduser()
    if not path.is_dir():
        raise ApiError("目录不存在或无法访问", "invalid_path")
    return path.resolve()


def _recipe_for_pipeline(recipe: Any, settings: dict) -> dict:
    """Translate the compact UI recipe into image_pipeline's established shape."""
    source = recipe if isinstance(recipe, dict) else {"name": recipe or settings["processing"]["default_recipe"]}
    deflicker = source.get("deflicker", {}) if isinstance(source.get("deflicker", {}), dict) else {}
    golden = source.get("golden", {}) if isinstance(source.get("golden", {}), dict) else {}
    name = str(source.get("name", source.get("style", settings["processing"]["default_recipe"])))
    gain_limit = deflicker.get("gain_limit")
    pipeline_recipe = {
        "jpeg_quality": int(settings["processing"].get("jpeg_quality", 95)),
        "deflicker": {
            "enable": bool(deflicker.get("enabled", deflicker.get("enable", True))),
            "window": int(deflicker.get("window", 11)),
            "clip": deflicker.get("clip", (0.85, 1.2)),
        },
        "grade": {"style": name},
        "enhance_golden": {
            "enable": bool(golden),
            "strength": float(golden.get("strength", 0)) / 100 if golden else 0,
            "core": [golden["start"], golden["end"]] if golden.get("start") is not None and golden.get("end") is not None else None,
        },
    }
    if gain_limit is not None and "clip" not in deflicker:
        limit = abs(float(gain_limit))
        pipeline_recipe["deflicker"]["clip"] = (max(0.01, 1 - limit), 1 + limit)
    return pipeline_recipe


def _segment_by_id(project: dict, segment_id: str) -> dict:
    for segment in project.get("segments", []):
        if segment.get("id") == segment_id:
            return segment
    raise ApiError("分段不存在", "segment_not_found", 404)


def _frame_rejections(segment: dict, values: Any) -> list[str]:
    if not isinstance(values, list):
        raise ApiError("rejected_frames 必须是数组", "invalid_segment")
    frames = segment.get("source_files", [])
    resolved = []
    for value in values:
        if isinstance(value, int):
            if value < 0 or value >= len(frames):
                raise ApiError("坏帧索引超出范围", "invalid_segment")
            resolved.append(frames[value])
        elif isinstance(value, str):
            resolved.append(value)
        else:
            raise ApiError("坏帧必须是索引或路径", "invalid_segment")
    return resolved


def create_app(overrides: dict | None = None) -> Flask:
    runtime = dict(overrides or {})
    runtime_environment = runtime.get("runtime_environment")
    if runtime_environment is None:
        runtime_environment = load_runtime_environment(os.environ, config_io.ROOT)
    if not isinstance(runtime_environment, RuntimeEnvironment):
        raise TypeError("runtime_environment must be a RuntimeEnvironment")
    local_config_path = Path(runtime.get("local_config_path", runtime_environment.local_config_path)).resolve()
    settings = config_io.load_config(local_path=local_config_path)
    startup_configured_roots = _configured_roots(settings)
    environment_roots = {
        "workspace_dir": runtime_environment.workspace_dir,
        "output_dir": runtime_environment.output_dir,
        "archive_dir": runtime_environment.archive_dir,
    } if runtime_environment.mode == "container" else settings
    effective_roots = {
        "workspace_dir": _configured_root(runtime.get("workspace_dir", environment_roots["workspace_dir"])),
        "output_dir": _configured_root(runtime.get("output_dir", environment_roots["output_dir"])),
        "archive_dir": _configured_root(runtime.get("archive_dir", environment_roots["archive_dir"])),
    }
    _validate_runtime_roots(effective_roots)
    workspace = effective_roots["workspace_dir"]
    output = effective_roots["output_dir"]
    archive_dir = effective_roots["archive_dir"]
    store = ProjectStore(workspace)
    tasks = TaskManager(workspace / "task.json")

    app = Flask(__name__, static_folder=None)
    app.config.update(TESTING=bool(runtime.get("TESTING", False)))
    app.extensions["timelapse_paths"] = {
        "workspace": workspace,
        "output": output,
        "archive": archive_dir,
        "local_config": local_config_path,
    }
    app.extensions["timelapse_store"] = store
    app.extensions["timelapse_tasks"] = tasks
    app.extensions["solis_runtime"] = runtime_environment

    def active_task() -> bool:
        return tasks.snapshot().get("status") in ACTIVE_STATES

    def require_idle() -> None:
        if active_task():
            raise TaskBusy("another task is already active")

    def validate_source_dir(source: Path, roots: dict[str, Path] = effective_roots) -> None:
        if runtime_environment.input_root is not None:
            try:
                source.resolve().relative_to(runtime_environment.input_root.resolve(strict=True))
            except (OSError, ValueError):
                raise ApiError("素材目录超出容器输入目录", "invalid_media_path") from None
        if any(_paths_overlap(source, root) for root in roots.values()):
            raise ApiError("素材目录不能与工作目录重叠", "unsafe_source_dir")

    def project_or_error() -> dict:
        try:
            project = store.load()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ApiError("项目状态不可读取", "project_unavailable", 500) from exc
        if project is None:
            raise ApiError("当前没有项目", "project_missing", 400)
        return project

    def submit(
        kind: str,
        work: Callable[[TaskContext], Any],
        *,
        cancellable_while_running: bool = True,
    ):
        try:
            task = tasks.submit(
                kind,
                work,
                cancellable_while_running=cancellable_while_running,
            )
        except TaskBusy as exc:
            raise ApiError("已有任务正在运行", "task_busy", 409) from exc
        return jsonify({"task": _task_response(task)}), 202

    def save_project_segment(segment_id: str, values: dict) -> dict:
        def update(project: dict) -> dict:
            segments = []
            found = False
            for segment in project.get("segments", []):
                if segment.get("id") == segment_id:
                    segments.append({**segment, **deepcopy(values)})
                    found = True
                else:
                    segments.append(segment)
            if not found:
                raise ApiError("分段不存在", "segment_not_found", 404)
            return {**project, "segments": segments}

        return store.update(update)

    def validate_archive_complete(project: dict) -> None:
        segments = project.get("segments", [])
        if not segments:
            raise ApiError("当前项目尚未完成处理和导出", "archive_incomplete")
        artifact_paths: set[str] = set()
        for segment in segments:
            if segment.get("render_status") != "completed":
                raise ApiError("当前项目尚未完成处理和导出", "archive_incomplete")
            segment_id = segment.get("id")
            if not isinstance(segment_id, str):
                raise ApiError("当前项目尚未完成处理和导出", "archive_incomplete")
            result_dir = (workspace / "current" / "segments" / segment_id / "result").resolve()
            expected_parent = (workspace / "current" / "segments").resolve()
            if not result_dir.is_relative_to(expected_parent):
                raise ApiError("当前项目尚未完成处理和导出", "archive_incomplete")
            identity = _result_identity(result_dir)
            if identity["frame_count"] != _expected_result_count(segment):
                raise ApiError("当前项目尚未完成处理和导出", "archive_incomplete")
            artifact = segment.get("export_artifact")
            if not isinstance(artifact, dict):
                raise ApiError("当前项目尚未完成处理和导出", "archive_incomplete")
            artifact_value = artifact.get("path")
            if not isinstance(artifact_value, str) or not Path(artifact_value).is_absolute():
                raise ApiError("当前项目尚未完成处理和导出", "archive_incomplete")
            artifact_path = Path(artifact_value).resolve()
            if (
                not artifact_path.is_relative_to(output.resolve())
                or artifact_path.suffix.casefold() != ".mp4"
                or not artifact_path.is_file()
            ):
                raise ApiError("当前项目尚未完成处理和导出", "archive_incomplete")
            try:
                mp4_sha256 = _sha256_file(artifact_path)
            except OSError:
                raise ApiError("当前项目尚未完成处理和导出", "archive_incomplete") from None
            if (
                artifact.get("frame_count") != identity["frame_count"]
                or artifact.get("result_signature") != identity["result_signature"]
                or artifact.get("mp4_sha256") != mp4_sha256
            ):
                raise ApiError("当前项目尚未完成处理和导出", "archive_incomplete")
            artifact_key = str(artifact_path).casefold()
            if artifact_key in artifact_paths:
                raise ApiError("当前项目尚未完成处理和导出", "archive_incomplete")
            artifact_paths.add(artifact_key)

    @app.get("/")
    def index():
        return send_from_directory(WEBUI_DIR, "index.html")

    @app.get("/<path:filename>")
    def static_asset(filename):
        if filename not in {"styles.css", "app.js", "ui_prefs.js"}:
            return _error("资源不存在", "not_found", 404)
        return send_from_directory(WEBUI_DIR, filename)

    @app.get("/api/state")
    def api_state():
        return jsonify({
            "project": store.load(),
            "task": _task_response(tasks.snapshot()),
            "capabilities": {"raw": True, "export": ["h264", "h265"]},
        })

    @app.get("/api/capabilities")
    def api_capabilities():
        return jsonify({
            "mode": runtime_environment.mode,
            "native_directory_picker": runtime_environment.native_picker,
            "directory_browser": runtime_environment.input_root is not None,
        })

    @app.get("/api/health")
    def api_health():
        issues = validate_runtime_environment(runtime_environment)
        if issues:
            return jsonify({
                "status": "error",
                "code": "runtime_unavailable",
                "issues": issues,
            }), 503
        return jsonify({"status": "ok"})

    @app.get("/api/directories")
    def api_directories():
        if runtime_environment.input_root is None:
            return _error("当前模式不提供素材目录浏览", "invalid_media_path", 400)
        safe = _safe_input_directory(runtime_environment.input_root, request.args.get("path", ""))
        if safe is None:
            return _error("素材目录无效", "invalid_media_path", 400)
        directory, relative = safe
        directories = []
        try:
            children = sorted(
                (child for child in directory.iterdir() if child.is_dir()),
                key=lambda child: child.name.casefold(),
            )
        except OSError:
            return _error("素材目录无法访问", "invalid_media_path", 400)
        for child in children:
            child_safe = _safe_input_directory(runtime_environment.input_root, f"{relative}/{child.name}".strip("/"))
            if child_safe is None:
                continue
            child_relative = child_safe[1]
            directories.append({"name": child.name, "path": child_relative})
        parent = Path(relative).parent.as_posix() if relative else ""
        if parent == ".":
            parent = ""
        return jsonify({"path": relative, "parent": parent, "directories": directories})

    @app.post("/api/pick-directory")
    def api_pick_directory():
        if not runtime_environment.native_picker:
            return _error("当前模式不支持本机目录选择器", "native_picker_unavailable", 409)
        picker = runtime.get("directory_picker")
        if picker is not None:
            selected = picker()
        else:
            try:
                import tkinter as tk
                from tkinter import filedialog

                root = tk.Tk()
                root.withdraw()
                try:
                    selected = filedialog.askdirectory(parent=root)
                finally:
                    root.destroy()
            except Exception as exc:
                raise ApiError("无法打开目录选择器", "picker_unavailable", 500) from exc
        return jsonify({"path": str(Path(selected).resolve()) if selected else None})

    @app.post("/api/project/scan")
    def api_scan_project():
        require_idle()
        source = _path_value(_body(), "source_dir")
        validate_source_dir(source)
        scan_settings = config_io.load_config(local_path=local_config_path)

        def work(context: TaskContext):
            context.log("正在扫描素材")
            frames = media_catalog.scan_source(source)
            context.raise_if_cancelled()
            if not frames:
                raise ValueError("素材目录中没有支持的照片")
            project = store.create(source)
            segments = media_catalog.suggest_segments(frames, scan_settings["scan"])
            for segment in segments:
                context.raise_if_cancelled()
                segment["recipe"] = {"name": scan_settings["processing"]["default_recipe"]}
                thumbnail_dir = workspace / "current" / "segments" / segment["id"] / "thumbnails"
                for index, frame in enumerate(segment.get("frames", [])):
                    context.raise_if_cancelled()
                    source_path = Path(frame["path"])
                    try:
                        from PIL import Image

                        thumbnail_dir.mkdir(parents=True, exist_ok=True)
                        with Image.open(source_path) as image:
                            image.thumbnail((320, 180))
                            image.convert("RGB").save(thumbnail_dir / f"{index:06d}.jpg", quality=82)
                    except (OSError, ValueError):
                        # RAW support is provided by the processing pipeline; a missing UI thumbnail is non-fatal.
                        continue
            context.raise_if_cancelled()
            saved = store.save({**project, "status": "scanned", "segments": segments, "active_job_id": None})
            return {"segments": len(saved["segments"])}

        return submit("scan", work)

    @app.delete("/api/project")
    def api_delete_project():
        require_idle()
        if _body().get("confirm") is not True:
            raise ApiError("必须确认清理当前工作区", "confirmation_required")
        store.clear()
        return jsonify({"ok": True})

    @app.post("/api/segments/split")
    def api_split_segment():
        require_idle()
        body = _body()
        segment_id = body.get("segment_id")
        frame_index = body.get("frame_index")
        if not isinstance(segment_id, str) or not isinstance(frame_index, int):
            raise ApiError("segment_id 和 frame_index 必须有效", "invalid_segment")
        project = store.update(lambda state: {
            **state,
            "segments": media_catalog.split_segment(state.get("segments", []), segment_id, frame_index),
            "status": "edited",
        })
        return jsonify({"project": project})

    @app.post("/api/segments/merge")
    def api_merge_segments():
        require_idle()
        body = _body()
        left_id, right_id = body.get("left_id"), body.get("right_id")
        if not isinstance(left_id, str) or not isinstance(right_id, str):
            raise ApiError("left_id 和 right_id 必须有效", "invalid_segment")
        project = store.update(lambda state: {
            **state,
            "segments": media_catalog.merge_segments(state.get("segments", []), left_id, right_id),
            "status": "edited",
        })
        return jsonify({"project": project})

    @app.post("/api/segments/reorder")
    def api_reorder_segments():
        require_idle()
        ordered_ids = _body().get("ordered_ids")
        if not isinstance(ordered_ids, list) or not all(isinstance(item, str) for item in ordered_ids):
            raise ApiError("ordered_ids 必须是分段 ID 数组", "invalid_segment")
        project = store.update(lambda state: {
            **state,
            "segments": media_catalog.reorder_segments(state.get("segments", []), ordered_ids),
            "status": "edited",
        })
        return jsonify({"project": project})

    @app.patch("/api/segments/<segment_id>")
    def api_patch_segment(segment_id: str):
        require_idle()
        body = _body()
        allowed = {"name", "recipe", "rejected_frames", "bad_frames"}
        if not body or set(body) - allowed:
            raise ApiError("包含不支持的分段字段", "invalid_segment")
        project = project_or_error()
        segment = _segment_by_id(project, segment_id)
        values: dict[str, Any] = {}
        if "name" in body:
            if not isinstance(body["name"], str) or not body["name"].strip():
                raise ApiError("分段名称不能为空", "invalid_segment")
            values["name"] = body["name"].strip()
        if "recipe" in body:
            if not isinstance(body["recipe"], (dict, str)):
                raise ApiError("recipe 必须是对象或名称", "invalid_segment")
            values["recipe"] = deepcopy(body["recipe"])
        rejection_values = body.get("rejected_frames", body.get("bad_frames"))
        if rejection_values is not None:
            values["rejected_frames"] = _frame_rejections(segment, rejection_values)
        updated = save_project_segment(segment_id, values)
        return jsonify({"project": updated, "segment": _segment_by_id(updated, segment_id)})

    @app.get("/api/segments/<segment_id>/thumbnails")
    def api_thumbnails(segment_id: str):
        project = project_or_error()
        segment = _segment_by_id(project, segment_id)
        try:
            offset = int(request.args.get("offset", "0"))
            limit = int(request.args.get("limit", "200"))
        except ValueError as exc:
            raise ApiError("offset 和 limit 必须是整数", "invalid_paging") from exc
        if offset < 0 or limit < 1:
            raise ApiError("offset 和 limit 超出范围", "invalid_paging")
        thumbnails = []
        for index, frame in enumerate(segment.get("frames", [])):
            if index < offset or len(thumbnails) >= limit:
                continue
            metadata = {key: value for key, value in frame.items() if key != "path"}
            thumbnail = workspace / "current" / "segments" / segment_id / "thumbnails" / f"{index:06d}.jpg"
            metadata.update({
                "index": index,
                "url": f"/media/current/segments/{segment_id}/thumbnails/{index:06d}.jpg" if thumbnail.is_file() else "",
            })
            thumbnails.append(metadata)
        return jsonify({"thumbnails": thumbnails, "total": len(segment.get("frames", []))})

    @app.get("/api/segments/<segment_id>/chart")
    def api_chart(segment_id: str):
        project = project_or_error()
        segment = _segment_by_id(project, segment_id)
        analysis = segment.get("analysis")
        if not isinstance(analysis, dict):
            path = workspace / "current" / "segments" / segment_id / "analysis.json"
            if path.is_file():
                try:
                    analysis = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    analysis = None
        if not isinstance(analysis, dict):
            return jsonify({"chart": {"measured_luminance": [], "target_luminance": [], "gain": []}})
        return jsonify({"chart": {
            "measured_luminance": list(analysis.get("measured_luminance", [])),
            "target_luminance": list(analysis.get("target_luminance", [])),
            "gain": list(analysis.get("gain", [])),
        }})

    def run_process(project: dict, segment_ids: list[str], from_stage: str, context: TaskContext) -> dict:
        selected = [_segment_by_id(project, segment_id) for segment_id in segment_ids]
        settings_for_task = config_io.load_config(local_path=local_config_path)
        multiplier = 2 if from_stage == "analyze" else 1
        total = sum(len(segment.get("source_files", [])) * multiplier for segment in selected)
        completed = 0
        for segment in selected:
            context.raise_if_cancelled()
            segment_id = segment["id"]
            work_dir = workspace / "current" / "segments" / segment_id
            recipe = _recipe_for_pipeline(segment.get("recipe"), settings_for_task)

            def progress(done: int, _segment_total: int, **detail: Any) -> None:
                frame = detail.get("frame") or detail.get("file")
                context.progress(
                    completed + done,
                    total,
                    current_segment=segment.get("name", segment_id),
                    current_file=Path(frame).name if frame else None,
                )

            if from_stage == "analyze":
                context.log(f"正在分析 {segment.get('name', segment_id)}")
                analysis = image_pipeline.analyze_segment(segment, recipe, work_dir, progress, context.cancelled)
                save_project_segment(segment_id, {"analysis": analysis, "render_status": "analyzed"})
                completed += len(segment.get("source_files", []))
            else:
                analysis = segment.get("analysis")
                if not isinstance(analysis, dict):
                    analysis_path = work_dir / "analysis.json"
                    if not analysis_path.is_file():
                        raise ValueError("该分段没有可用于渲染的分析结果")
                    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))

            context.raise_if_cancelled()
            context.log(f"正在渲染 {segment.get('name', segment_id)}")
            result = image_pipeline.render_segment(segment, recipe, analysis, work_dir, progress, context.cancelled)
            save_project_segment(segment_id, {
                "analysis": analysis,
                "render_status": "completed",
                "output_files": [path.name for path in (work_dir / "result").glob("*.jpg")],
                "representative_url": f"/media/current/segments/{segment_id}/thumbnails/000000.jpg",
                "export_artifact": None,
            })
            completed += len(segment.get("source_files", []))
        store.update(lambda state: {**state, "status": "processed", "active_job_id": None})
        return {"segments": len(selected)}

    def start_process(from_stage: str):
        require_idle()
        body = _body()
        project = project_or_error()
        ids = body.get("segment_ids") or [segment.get("id") for segment in project.get("segments", [])]
        if from_stage not in {"analyze", "render"} or not isinstance(ids, list) or not ids or not all(isinstance(item, str) for item in ids):
            raise ApiError("处理参数无效", "invalid_process")
        for segment_id in ids:
            _segment_by_id(project, segment_id)
        return submit("render" if from_stage == "render" else "analyze", lambda context: run_process(project, ids, from_stage, context))

    @app.post("/api/process")
    def api_process():
        return start_process(_body().get("from_stage", "analyze"))

    @app.post("/api/process/retry")
    def api_retry_process():
        return start_process(_body().get("from_stage", "analyze"))

    @app.post("/api/tasks/cancel")
    def api_cancel_task():
        try:
            cancelled = tasks.cancel()
        except TaskNotCancellable as exc:
            raise ApiError("归档开始后不能取消", "non_cancellable", 409) from exc
        return jsonify({"task": _task_response(cancelled)})

    @app.get("/api/tasks/current")
    def api_current_task():
        return jsonify({"task": _task_response(tasks.snapshot())})

    @app.post("/api/export")
    def api_export():
        require_idle()
        body = _body()
        project = project_or_error()
        ids = body.get("segment_ids") or [segment.get("id") for segment in project.get("segments", [])]
        if not isinstance(ids, list) or not ids or not all(isinstance(item, str) for item in ids):
            raise ApiError("segment_ids 必须是非空数组", "invalid_export")
        selected = [_segment_by_id(project, segment_id) for segment_id in ids]
        options = config_io.deep_merge(config_io.load_config(local_path=local_config_path)["export"], {
            key: body[key] for key in {"fps", "resolution", "codec", "crf"} if key in body
        })
        try:
            if int(options["fps"]) not in video_export.VALID_FPS or str(options["codec"]).lower() not in video_export.CODECS:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ApiError("导出参数无效", "invalid_export") from exc

        def work(context: TaskContext):
            outputs = []
            for index, segment in enumerate(selected, start=1):
                context.raise_if_cancelled()
                result_dir = workspace / "current" / "segments" / segment["id"] / "result"
                identity = _result_identity(result_dir)
                output.mkdir(parents=True, exist_ok=True)
                target = output / _export_filename(segment)
                context.log(f"正在导出 {segment.get('name', segment['id'])}")
                result = video_export.export_video(
                    result_dir,
                    target,
                    options,
                    lambda done, total, **detail: context.progress(index - 1 + done / max(total, 1), len(selected), current_file=detail.get("file")),
                    cancelled=context.cancelled,
                )
                context.raise_if_cancelled()
                artifact_path = Path(result).resolve()
                if not artifact_path.is_relative_to(output.resolve()) or not artifact_path.is_file():
                    raise RuntimeError("export did not produce a valid output artifact")
                save_project_segment(segment["id"], {
                    "export_artifact": {
                        "path": str(artifact_path),
                        "frame_count": identity["frame_count"],
                        "result_signature": identity["result_signature"],
                        "mp4_sha256": _sha256_file(artifact_path),
                    }
                })
                outputs.append(artifact_path.name)
            return {"outputs": outputs}

        return submit("export", work)

    @app.post("/api/archive")
    def api_archive():
        require_idle()
        body = _body()
        if body.get("confirm_workspace_clear") is not True or body.get("preserve_source") is not True:
            raise ApiError("必须确认清理工作区且保留源照片", "confirmation_required")
        project = project_or_error()
        validate_archive_complete(project)

        def work(context: TaskContext):
            context.log("正在验证并归档项目")
            context.raise_if_cancelled()
            destination = archive.archive_project(project, workspace / "current", output, archive_dir)
            return {"timestamp": destination.name}

        return submit("archive", work, cancellable_while_running=False)

    def archive_summary(timestamp: str, manifest: dict) -> dict:
        timestamp_root = _safe_archive_timestamp_dir(archive_dir, timestamp)
        paths = {
            kind: _manifest_media_paths(timestamp_root, manifest, kind) if timestamp_root else []
            for kind in ("previews", "outputs", "representatives")
        }

        def urls(kind: str) -> list[str]:
            return [f"/media/archive/{path.relative_to(archive_dir.resolve()).as_posix()}" for path in paths[kind]]

        return {
            "timestamp": timestamp,
            "archived_at": manifest.get("archived_at"),
            "source_dir": manifest.get("source_dir"),
            "segment_count": manifest.get("segment_count", 0),
            "previews": urls("previews"),
            "outputs": urls("outputs"),
            "representatives": urls("representatives"),
        }

    @app.get("/api/history")
    def api_history():
        history = []
        if archive_dir.is_dir():
            for child in sorted(archive_dir.iterdir(), key=lambda path: path.name, reverse=True):
                safe_child = _safe_archive_timestamp_dir(archive_dir, child.name)
                if safe_child is None or not safe_child.is_dir():
                    continue
                manifest_path = safe_child / "manifest.json"
                if not manifest_path.is_file():
                    continue
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(manifest, dict):
                    history.append(archive_summary(child.name, manifest))
        return jsonify({"history": history})

    @app.get("/api/history/<timestamp>")
    def api_history_item(timestamp: str):
        archive_path = _safe_archive_timestamp_dir(archive_dir, timestamp)
        if archive_path is None:
            raise ApiError("归档不存在", "not_found", 404)
        manifest_path = archive_path / "manifest.json"
        if not manifest_path.is_file():
            raise ApiError("归档不存在", "not_found", 404)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ApiError("归档记录不可读取", "archive_unavailable", 500) from exc
        return jsonify({"manifest": manifest, **archive_summary(timestamp, manifest)})

    def settings_payload() -> dict:
        return config_io.load_config(local_path=local_config_path)

    def settings_response(current_settings: dict | None = None) -> dict:
        values = current_settings or settings_payload()
        configured = _configured_roots(values)
        return {
            "settings": values,
            "effective_roots": {key: str(value) for key, value in effective_roots.items()},
            "restart_required": configured != startup_configured_roots,
        }

    def save_settings(values: dict) -> dict:
        candidate = config_io.deep_merge(settings_payload(), values)
        try:
            candidate_roots = _configured_roots(candidate)
            _validate_runtime_roots(candidate_roots)
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError("工作、输出和归档目录配置不安全", "invalid_runtime_roots") from exc
        project = store.load()
        if project and project.get("source_dir"):
            try:
                validate_source_dir(Path(project["source_dir"]).resolve(), candidate_roots)
            except (OSError, ApiError) as exc:
                raise ApiError("工作、输出和归档目录配置不安全", "invalid_runtime_roots") from exc
        config_io.save_local_config(candidate, local_config_path)
        return candidate

    @app.get("/api/settings")
    def api_get_settings():
        return jsonify(settings_response())

    @app.put("/api/settings")
    @app.post("/api/settings")
    def api_save_settings():
        saved = save_settings(_body())
        return jsonify(settings_response(saved))

    @app.get("/api/config")
    def api_get_config():
        return jsonify(settings_payload())

    @app.post("/api/config")
    def api_save_config():
        save_settings(_body())
        return jsonify({"ok": True})

    @app.get("/media/current/<path:relative>")
    def media_current(relative):
        current_root = workspace / "current"
        path = _safe_media_path(
            current_root,
            relative,
            CURRENT_MEDIA_SUFFIXES,
            lambda candidate: _current_media_allowed(current_root, candidate),
        )
        return send_file(path) if path else ("", 404)

    @app.get("/media/archive/<path:relative>")
    def media_archive(relative):
        path = _safe_media_path(archive_dir, relative, ARCHIVE_MEDIA_SUFFIXES, lambda candidate: _archive_media_allowed(archive_dir, candidate))
        return send_file(path) if path else ("", 404)

    @app.errorhandler(ApiError)
    def api_error(error: ApiError):
        return _error(str(error), error.code, error.status)

    @app.errorhandler(TaskBusy)
    def task_busy(_exception: TaskBusy):
        return _error("已有任务正在运行", "task_busy", 409)

    @app.errorhandler(Exception)
    def unexpected_error(error: Exception):
        if isinstance(error, HTTPException):
            if request.path.startswith("/api/"):
                return _error("接口不存在", "not_found", error.code or 404)
            return "", error.code or 404
        if request.path.startswith("/api/"):
            logging.getLogger(__name__).exception("Unhandled WebUI API error", exc_info=error)
            return _error("服务器处理请求时失败", "internal_error", 500)
        raise error

    return app


def _print_banner(host: str, port: int) -> None:
    print(
        f"\nSony Timelapse WebUI is running\n"
        f"Local URL: http://127.0.0.1:{port}/\n"
        f"Binding: {host}:{port}\n"
        "Close this window or press Ctrl+C to stop the server.\n",
        flush=True,
    )


def main() -> None:
    defaults = config_io.load_config()["server"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=defaults["host"])
    parser.add_argument("--port", type=int, default=int(defaults["port"]))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    _print_banner(args.host, args.port)
    if defaults.get("open_browser", True) and not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}/")).start()
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    create_app().run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
