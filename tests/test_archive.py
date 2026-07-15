import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.archive import archive_project


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.workspace = self.root / "workspace" / "current"
        self.output = self.root / "output"
        self.archive = self.root / "archive"
        for directory in [self.source, self.workspace, self.output, self.archive]:
            directory.mkdir(parents=True)

        self.source_files = [self.source / "a.jpg", self.source / "b.arw"]
        self.source_files[0].write_bytes(b"source-jpeg")
        self.source_files[1].write_bytes(b"source-raw")

        segment_dir = self.workspace / "segments" / "seg-1"
        (segment_dir / "result").mkdir(parents=True)
        (segment_dir / "result" / "000001.jpg").write_bytes(b"result-1")
        (segment_dir / "result" / "000002.jpg").write_bytes(b"result-2")
        (segment_dir / "analysis.json").write_text('{"gain": [1, 1]}', encoding="utf-8")
        (segment_dir / "recipe.json").write_text('{"grade": "natural"}', encoding="utf-8")
        (segment_dir / "preview.mp4").write_bytes(b"preview")
        self.project = {
            "schema_version": 1,
            "source_dir": str(self.source),
            "segments": [
                {
                    "id": "seg-1",
                    "name": "日照:金山",
                    "frames": [str(path) for path in self.source_files],
                    "recipe": {"grade": "natural"},
                }
            ],
        }
        (self.workspace / "project.json").write_text(
            json.dumps(self.project, ensure_ascii=False), encoding="utf-8"
        )
        self.final_video = self.output / "日照金山.mp4"
        self.final_video.write_bytes(b"final")

    def tearDown(self):
        self.temporary.cleanup()

    def test_archive_contains_contract_and_keeps_source_and_output(self):
        source_hashes = {path.name: digest(path) for path in self.source_files}
        output_hash = digest(self.final_video)

        destination = archive_project(
            self.project,
            self.workspace,
            self.output,
            self.archive,
            timestamp="2026-07-15_120000",
        )

        self.assertEqual(destination.name, "2026-07-15_120000")
        self.assertTrue((destination / "project.json").is_file())
        segment = destination / "日照_金山"
        self.assertTrue((segment / "recipe.json").is_file())
        self.assertTrue((segment / "analysis.json").is_file())
        self.assertEqual(len(list(segment.glob("*.jpg"))), 2)
        self.assertTrue((destination / "日照_金山_preview.mp4").is_file())
        self.assertTrue((destination / "output" / self.final_video.name).is_file())
        manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["source_file_count"], 2)
        self.assertEqual(manifest["segments"][0]["jpeg_count"], 2)
        self.assertEqual(manifest["media"]["previews"], ["日照_金山_preview.mp4"])
        self.assertEqual(manifest["media"]["outputs"], ["output/日照金山.mp4"])

        self.assertEqual(list(self.workspace.iterdir()), [])
        self.assertEqual({path.name: digest(path) for path in self.source_files}, source_hashes)
        self.assertEqual(digest(self.final_video), output_hash)

    def test_copy_failure_preserves_workspace_and_does_not_publish_archive(self):
        before = sorted(str(path.relative_to(self.workspace)) for path in self.workspace.rglob("*"))
        with patch("src.archive.shutil.copy2", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                archive_project(
                    self.project,
                    self.workspace,
                    self.output,
                    self.archive,
                    timestamp="2026-07-15_120001",
                )
        after = sorted(str(path.relative_to(self.workspace)) for path in self.workspace.rglob("*"))
        self.assertEqual(before, after)
        self.assertFalse((self.archive / "2026-07-15_120001").exists())

    def test_workspace_cannot_contain_output_or_archive(self):
        with self.assertRaises(ValueError):
            archive_project(
                self.project,
                self.workspace,
                self.workspace / "output",
                self.archive,
                timestamp="2026-07-15_120002",
            )

    def test_workspace_output_archive_roots_must_be_pairwise_disjoint(self):
        cases = [
            ("same workspace output", "workspace", "workspace", "archive"),
            ("output inside workspace", "workspace", "workspace/output", "archive"),
            ("workspace inside output", "output/workspace", "output", "archive"),
            ("archive inside workspace", "workspace", "output", "workspace/archive"),
            ("workspace inside archive", "archive/workspace", "output", "archive"),
            ("archive inside output", "workspace", "output", "output/archive"),
            ("output inside archive", "workspace", "archive/output", "archive"),
        ]
        for index, (label, workspace, output, archive) in enumerate(cases):
            with self.subTest(label=label):
                case_root = self.root / f"roots-{index}"
                paths = [case_root / workspace, case_root / output, case_root / archive]
                for path in paths:
                    path.mkdir(parents=True, exist_ok=True)
                marker = paths[0] / "keep.txt"
                marker.write_bytes(b"workspace")
                project = {"source_dir": str(case_root / "source"), "segments": []}

                with self.assertRaises(ValueError):
                    archive_project(project, *paths, timestamp="2026-07-15_130000")

                self.assertEqual(marker.read_bytes(), b"workspace")
                self.assertEqual(list(case_root.rglob(".archiving-*")), [])

    def test_source_must_not_overlap_any_managed_root_in_either_direction(self):
        cases = [
            ("source equals workspace", "workspace", "workspace", "output", "archive"),
            ("source in workspace", "workspace/source", "workspace", "output", "archive"),
            ("workspace in source", "source", "source/workspace", "output", "archive"),
            ("source in output", "output/source", "workspace", "output", "archive"),
            ("output in source", "source", "workspace", "source/output", "archive"),
            ("source in archive", "archive/source", "workspace", "output", "archive"),
            ("archive in source", "source", "workspace", "output", "source/archive"),
        ]
        for index, (label, source, workspace, output, archive) in enumerate(cases):
            with self.subTest(label=label):
                case_root = self.root / f"source-roots-{index}"
                source_path = case_root / source
                paths = [case_root / workspace, case_root / output, case_root / archive]
                source_path.mkdir(parents=True, exist_ok=True)
                for path in paths:
                    path.mkdir(parents=True, exist_ok=True)
                marker = paths[0] / "keep.txt"
                marker.write_bytes(b"workspace")
                project = {"source_dir": str(source_path), "segments": []}

                with self.assertRaises(ValueError):
                    archive_project(project, *paths, timestamp="2026-07-15_140000")

                self.assertEqual(marker.read_bytes(), b"workspace")
                self.assertEqual(list(case_root.rglob(".archiving-*")), [])


if __name__ == "__main__":
    unittest.main()
