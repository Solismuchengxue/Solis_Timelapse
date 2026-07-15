"""Atomic storage for the active WebUI project."""
from __future__ import annotations

import json
import os
import shutil
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config_io import project_path


SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="microseconds")


class ProjectStore:
    def __init__(self, workspace: Path):
        workspace_path = Path(workspace)
        if not workspace_path.is_absolute():
            workspace_path = project_path(str(workspace_path))
        self.workspace = workspace_path
        self.current_dir = self.workspace / "current"
        self.project_path = self.current_dir / "project.json"
        self.temporary_path = self.current_dir / "project.json.tmp"

    def create(self, source_dir: Path) -> dict:
        source = Path(source_dir).resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"Source directory does not exist: {source}")
        timestamp = _now()
        state = {
            "schema_version": SCHEMA_VERSION,
            "source_dir": str(source),
            "created_at": timestamp,
            "updated_at": timestamp,
            "status": "created",
            "segments": [],
            "active_job_id": None,
        }
        return self.save(state)

    def load(self) -> dict | None:
        if not self.project_path.is_file():
            return None
        with self.project_path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
        if not isinstance(state, dict):
            raise ValueError("project.json must contain a JSON object")
        return state

    def save(self, state: dict) -> dict:
        if not isinstance(state, dict):
            raise TypeError("Project state must be a dictionary")
        published = deepcopy(state)
        self.current_dir.mkdir(parents=True, exist_ok=True)
        with self.temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(published, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(self.temporary_path, self.project_path)
        return deepcopy(published)

    def update(self, updater: Callable[[dict], dict]) -> dict:
        current = self.load()
        if current is None:
            raise RuntimeError("No active project")
        updated = updater(deepcopy(current))
        if not isinstance(updated, dict):
            raise TypeError("Project updater must return a dictionary")
        updated = deepcopy(updated)
        updated["updated_at"] = _now()
        return self.save(updated)

    def clear(self) -> None:
        if self.current_dir.exists():
            shutil.rmtree(self.current_dir)
