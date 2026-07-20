import tempfile
import unittest
from pathlib import Path

from docker.entrypoint import migrate_legacy_container_config
from src.runtime_env import (
    RuntimeEnvironment,
    load_runtime_environment,
    validate_runtime_environment,
)


class RuntimeEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_local_environment_uses_repository_paths_and_native_picker(self):
        runtime = load_runtime_environment({}, self.root)

        self.assertEqual(runtime.mode, "local")
        self.assertIsNone(runtime.input_root)
        self.assertEqual(runtime.workspace_dir, self.root / "workspace")
        self.assertEqual(runtime.output_dir, self.root / "output")
        self.assertEqual(runtime.archive_dir, self.root / "archive")
        self.assertEqual(runtime.local_config_path, self.root / "config" / "local.yaml")
        self.assertEqual(runtime.host, "127.0.0.1")
        self.assertTrue(runtime.native_picker)

    def test_container_environment_uses_only_persistent_mounts(self):
        runtime = load_runtime_environment({"SOLIS_CONTAINER": "1"}, self.root)

        self.assertEqual(runtime.mode, "container")
        self.assertEqual(runtime.input_root, Path("/media/input"))
        self.assertEqual(runtime.workspace_dir, Path("/media/workspace"))
        self.assertEqual(runtime.output_dir, Path("/media/output"))
        self.assertEqual(runtime.archive_dir, Path("/media/archive"))
        self.assertEqual(runtime.local_config_path, Path("/data/config/config.yaml"))
        self.assertEqual(runtime.host, "0.0.0.0")
        self.assertFalse(runtime.native_picker)

    def test_validation_reports_missing_mounts_without_creating_them(self):
        runtime = RuntimeEnvironment(
            mode="container",
            input_root=self.root / "input",
            workspace_dir=self.root / "workspace",
            output_dir=self.root / "output",
            archive_dir=self.root / "archive",
            local_config_path=self.root / "config" / "local.yaml",
            host="0.0.0.0",
            native_picker=False,
        )

        issues = validate_runtime_environment(runtime)

        self.assertEqual(len(issues), 5)
        self.assertFalse((self.root / "workspace").exists())
        self.assertFalse((self.root / "config").exists())

    def test_validation_accepts_readable_input_and_writable_persistence(self):
        for name in ("input", "workspace", "output", "archive", "config"):
            (self.root / name).mkdir()
        runtime = RuntimeEnvironment(
            mode="container",
            input_root=self.root / "input",
            workspace_dir=self.root / "workspace",
            output_dir=self.root / "output",
            archive_dir=self.root / "archive",
            local_config_path=self.root / "config" / "local.yaml",
            host="0.0.0.0",
            native_picker=False,
        )

        self.assertEqual(validate_runtime_environment(runtime), [])
        self.assertEqual(list((self.root / "workspace").iterdir()), [])

    def test_container_migrates_legacy_local_yaml_without_overwriting_config(self):
        config_dir = self.root / "config"
        config_dir.mkdir()
        legacy = config_dir / "local.yaml"
        destination = config_dir / "config.yaml"
        legacy.write_text("logging:\n  level: DEBUG\n", encoding="utf-8")
        runtime = RuntimeEnvironment(
            mode="container",
            input_root=self.root / "input",
            workspace_dir=self.root / "workspace",
            output_dir=self.root / "output",
            archive_dir=self.root / "archive",
            local_config_path=destination,
            host="0.0.0.0",
            native_picker=False,
        )

        self.assertTrue(migrate_legacy_container_config(runtime))
        self.assertFalse(legacy.exists())
        self.assertIn("DEBUG", destination.read_text(encoding="utf-8"))

        legacy.write_text("logging:\n  level: INFO\n", encoding="utf-8")
        self.assertFalse(migrate_legacy_container_config(runtime))
        self.assertTrue(legacy.exists())
        self.assertIn("DEBUG", destination.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
