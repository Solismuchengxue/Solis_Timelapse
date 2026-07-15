import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROGRAM = ROOT / "02_program"
sys.path.insert(0, str(PROGRAM))
SPEC = importlib.util.spec_from_file_location("s01_classify", PROGRAM / "s01_classify.py")
CLASSIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLASSIFY)


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.input_dir = self.root / "01_input"
        self.source.mkdir()
        self.input_dir.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def make_source(self, name, content):
        path = self.source / name
        path.write_bytes(content)
        return str(path)

    def test_copy_segments_creates_numbered_raw_directories(self):
        first = self.make_source("a.jpg", b"a")
        second = self.make_source("b.jpg", b"b")

        CLASSIFY.copy_segments([[first], [second]], str(self.input_dir))

        self.assertEqual((self.input_dir / "seg01" / "raw" / "a.jpg").read_bytes(), b"a")
        self.assertEqual((self.input_dir / "seg02" / "raw" / "b.jpg").read_bytes(), b"b")

    def test_existing_segment_aborts_before_copying_any_new_files(self):
        existing = self.input_dir / "seg02" / "raw"
        existing.mkdir(parents=True)
        (existing / "old.jpg").write_bytes(b"old")
        first = self.make_source("a.jpg", b"a")
        second = self.make_source("b.jpg", b"b")

        with self.assertRaisesRegex(RuntimeError, "seg02"):
            CLASSIFY.copy_segments([[first], [second]], str(self.input_dir))

        self.assertFalse((self.input_dir / "seg01").exists())
        self.assertEqual((existing / "old.jpg").read_bytes(), b"old")


if __name__ == "__main__":
    unittest.main()
