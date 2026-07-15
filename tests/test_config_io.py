import tempfile
import unittest
from pathlib import Path

import yaml

from src import config_io


class ConfigIoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.root = Path(self.temp.name)
        self.default_path = self.root / "config.yaml"
        self.local_path = self.root / "local.yaml"
        self.default_path.write_text(
            yaml.safe_dump({"server": {"port": 9501}, "preview": {"width": 1920, "fps": 30}}),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_local_yaml_deep_overrides_defaults(self):
        self.local_path.write_text(yaml.safe_dump({"preview": {"width": 1280}}), encoding="utf-8")

        config = config_io.load_config(self.default_path, self.local_path)

        self.assertEqual(config["preview"]["width"], 1280)
        self.assertEqual(config["preview"]["fps"], 30)
        self.assertEqual(config["server"]["port"], 9501)

    def test_save_only_writes_local_yaml(self):
        original_default = self.default_path.read_text(encoding="utf-8")

        saved = config_io.save_local_config({"server": {"port": 9600}}, self.local_path)

        self.assertEqual(saved["server"]["port"], 9600)
        self.assertEqual(yaml.safe_load(self.local_path.read_text(encoding="utf-8"))["server"]["port"], 9600)
        self.assertEqual(self.default_path.read_text(encoding="utf-8"), original_default)
        self.assertFalse(self.local_path.with_suffix(".yaml.tmp").exists())

    def test_invalid_local_yaml_uses_tracked_defaults(self):
        self.local_path.write_text("preview: [", encoding="utf-8")

        config = config_io.load_config(self.default_path, self.local_path)

        self.assertEqual(config["preview"]["width"], 1920)

    def test_project_path_is_under_repository_root(self):
        path = config_io.project_path("workspace", "current")

        self.assertEqual(path, config_io.ROOT / "workspace" / "current")


if __name__ == "__main__":
    unittest.main()
