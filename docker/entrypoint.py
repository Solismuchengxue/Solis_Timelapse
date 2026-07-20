"""Validate persistent mounts before starting Solis_Timelapse."""
from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.runtime_env import RuntimeEnvironment, load_runtime_environment, validate_runtime_environment
from webui import server


def migrate_legacy_container_config(runtime: RuntimeEnvironment) -> bool:
    if runtime.mode != "container":
        return False
    destination = Path(runtime.local_config_path)
    legacy = destination.with_name("local.yaml")
    if destination.exists() or not legacy.is_file():
        return False
    legacy.replace(destination)
    return True


def main() -> int:
    runtime = load_runtime_environment(os.environ, ROOT)
    issues = validate_runtime_environment(runtime)
    if issues:
        for issue in issues:
            print(f"Solis_Timelapse: {issue}", file=sys.stderr, flush=True)
        return 2
    if migrate_legacy_container_config(runtime):
        print("Solis_Timelapse: migrated /data/config/local.yaml to config.yaml", flush=True)
    server.main(["--host", runtime.host, "--port", "9501", "--no-browser"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
