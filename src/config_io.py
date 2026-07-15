"""Tracked defaults and local configuration overrides."""
from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "config" / "config.yaml"
LOCAL_PATH = ROOT / "config" / "local.yaml"

DEFAULTS = {
    "server": {"host": "127.0.0.1", "port": 9501, "open_browser": True},
    "workspace_dir": "workspace",
    "output_dir": "output",
    "archive_dir": "archive",
    "scan": {"gap_seconds": 120},
    "preview": {"fps": 30, "width": 1920},
    "export": {"fps": 30, "resolution": "4k", "codec": "h264", "crf": 18},
    "processing": {"jpeg_quality": 95, "default_recipe": "natural"},
}


def deep_merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _read_yaml(path: Path, *, tolerate_invalid: bool) -> dict:
    if not path.is_file():
        return {}
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        if tolerate_invalid:
            return {}
        raise
    return value if isinstance(value, dict) else {}


def load_config(default_path: Path = DEFAULT_PATH, local_path: Path = LOCAL_PATH) -> dict:
    config = deep_merge(DEFAULTS, _read_yaml(Path(default_path), tolerate_invalid=False))
    return deep_merge(config, _read_yaml(Path(local_path), tolerate_invalid=True))


def save_local_config(values: dict, local_path: Path = LOCAL_PATH) -> dict:
    path = Path(local_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        yaml.safe_dump(values, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return deepcopy(values)


def project_path(*parts: str) -> Path:
    return ROOT.joinpath(*parts)
