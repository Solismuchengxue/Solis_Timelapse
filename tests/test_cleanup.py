import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROGRAM = ROOT / "02_program"
sys.path.insert(0, str(PROGRAM))
SPEC = importlib.util.spec_from_file_location("s08_cleanup", PROGRAM / "s08_cleanup.py")
CLEANUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLEANUP)


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.root = Path(self.temp.name)
        self.input_dir = self.root / "01_input"
        self.preview_dir = self.root / "03_preview"
        self.output_dir = self.root / "04_output"
        self.archive_dir = self.root / "05_archive"
        for path in (self.input_dir, self.preview_dir, self.output_dir, self.archive_dir):
            path.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def make_segment(self, name="seg01", with_config=True, with_preview=True):
        seg = self.input_dir / name
        (seg / "raw").mkdir(parents=True)
        (seg / "result").mkdir()
        (seg / "raw" / "frame.arw").write_bytes(b"raw")
        (seg / "result" / "frame.jpg").write_bytes(b"jpeg")
        if with_config:
            (seg / "config.json").write_text('{"type":"raw"}', encoding="utf-8")
        if with_preview:
            (self.preview_dir / f"{name}.mp4").write_bytes(b"preview")
        return str(seg)

    def run_cleanup(self, segments, **kwargs):
        return CLEANUP.run_cleanup(
            segments=segments,
            archive_dir=str(self.archive_dir),
            preview_dir=str(self.preview_dir),
            output_dir=str(self.output_dir),
            timestamp="2026-07-13_150000",
            **kwargs,
        )

    def test_success_archives_config_manifest_preview_and_output_then_cleans(self):
        segments = [self.make_segment()]
        (self.output_dir / "final.mp4").write_bytes(b"final-video")

        archive_root = Path(self.run_cleanup(segments, confirmed=True))

        self.assertFalse(Path(segments[0]).exists())
        self.assertEqual(list(self.preview_dir.iterdir()), [])
        self.assertTrue((self.output_dir / "final.mp4").exists())
        self.assertEqual((archive_root / "seg01" / "frame.jpg").read_bytes(), b"jpeg")
        self.assertEqual(
            json.loads((archive_root / "seg01" / "config.json").read_text(encoding="utf-8")),
            {"type": "raw"},
        )
        self.assertEqual((archive_root / "seg01.mp4").read_bytes(), b"preview")
        self.assertEqual((archive_root / "output" / "final.mp4").read_bytes(), b"final-video")
        manifest = json.loads((archive_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["segments"][0]["frame_count"], 1)
        self.assertEqual(manifest["output_files"], ["final.mp4"])

    def test_missing_config_aborts_without_deleting_anything(self):
        segments = [self.make_segment(with_config=False)]

        with self.assertRaisesRegex(RuntimeError, "config.json"):
            self.run_cleanup(segments, confirmed=True)

        self.assertTrue(Path(segments[0]).exists())
        self.assertTrue((self.preview_dir / "seg01.mp4").exists())

    def test_dry_run_does_not_archive_or_delete(self):
        segments = [self.make_segment()]

        result = self.run_cleanup(segments, dry_run=True)

        self.assertIsNone(result)
        self.assertTrue(Path(segments[0]).exists())
        self.assertEqual(list(self.archive_dir.iterdir()), [])
        self.assertTrue((self.preview_dir / "seg01.mp4").exists())


if __name__ == "__main__":
    unittest.main()
