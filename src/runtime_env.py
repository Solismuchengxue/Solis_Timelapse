"""Runtime policy for local Windows and container deployments."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from uuid import uuid4


@dataclass(frozen=True)
class RuntimeEnvironment:
    mode: str
    input_root: Path | None
    workspace_dir: Path
    output_dir: Path
    archive_dir: Path
    local_config_path: Path
    host: str
    native_picker: bool


def load_runtime_environment(
    environ: Mapping[str, str],
    repository_root: Path,
) -> RuntimeEnvironment:
    if environ.get("SOLIS_CONTAINER") == "1":
        return RuntimeEnvironment(
            mode="container",
            input_root=Path("/media/input"),
            workspace_dir=Path("/media/workspace"),
            output_dir=Path("/media/output"),
            archive_dir=Path("/media/archive"),
            local_config_path=Path("/data/config/config.yaml"),
            host="0.0.0.0",
            native_picker=False,
        )
    root = Path(repository_root)
    return RuntimeEnvironment(
        mode="local",
        input_root=None,
        workspace_dir=root / "workspace",
        output_dir=root / "output",
        archive_dir=root / "archive",
        local_config_path=root / "config" / "local.yaml",
        host="127.0.0.1",
        native_picker=True,
    )


def _writable_directory_issue(path: Path) -> str | None:
    if not path.is_dir():
        return f"required writable directory is missing: {path}"
    probe = path / f".solis-write-test-{uuid4().hex}"
    try:
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
        return f"required directory is not writable: {path} ({exc})"
    return None


def validate_runtime_environment(runtime: RuntimeEnvironment) -> list[str]:
    issues: list[str] = []
    if runtime.input_root is not None:
        input_root = Path(runtime.input_root)
        if not input_root.is_dir() or not os.access(input_root, os.R_OK):
            issues.append(f"required input directory is not readable: {input_root}")

    for path in (runtime.workspace_dir, runtime.output_dir, runtime.archive_dir):
        issue = _writable_directory_issue(Path(path))
        if issue:
            issues.append(issue)

    config_issue = _writable_directory_issue(Path(runtime.local_config_path).parent)
    if config_issue:
        issues.append(config_issue)
    return issues
