import hashlib
import json
import tempfile
import unittest
from datetime import datetime
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
                    "focal_length": 70.0,
                    "captured_start": "2026-05-07T06:10:00",
                    "captured_end": "2026-05-07T06:55:03",
                    "capture_date": "2026-05-07",
                    "capture_time": "06:10:00–06:55:03",
                    "location": "27.102345°N, 100.175678°E",
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

    def test_archive_contains_original_files_and_final_video_without_processed_jpegs_or_preview(self):
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
        self.assertFalse((destination / "project.json").exists())
        segment = destination / "日照_金山"
        self.assertTrue((segment / "recipe.json").is_file())
        self.assertTrue((segment / "analysis.json").is_file())
        self.assertEqual((segment / "originals" / "a.jpg").read_bytes(), b"source-jpeg")
        self.assertEqual((segment / "originals" / "b.arw").read_bytes(), b"source-raw")
        self.assertFalse((segment / "000001.jpg").exists())
        self.assertFalse((destination / "日照_金山_preview.mp4").exists())
        self.assertTrue((destination / "output" / self.final_video.name).is_file())
        manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(manifest["source_file_count"], 2)
        self.assertEqual(manifest["segments"][0]["source_file_count"], 2)
        self.assertEqual(manifest["segments"][0]["first_file"], "a.jpg")
        self.assertEqual(manifest["segments"][0]["last_file"], "b.arw")
        self.assertEqual(manifest["segments"][0]["focal_length"], 70.0)
        self.assertEqual(manifest["segments"][0]["capture_date"], "2026-05-07")
        self.assertEqual(manifest["segments"][0]["capture_time"], "06:10:00–06:55:03")
        self.assertEqual(manifest["segments"][0]["location"], "27.102345°N, 100.175678°E")
        self.assertEqual(
            manifest["segments"][0]["originals"],
            ["日照_金山/originals/a.jpg", "日照_金山/originals/b.arw"],
        )
        self.assertNotIn("previews", manifest["media"])
        self.assertEqual(manifest["media"]["outputs"], ["output/日照金山.mp4"])

        archived_hashes = {
            path.name: digest(path)
            for path in (segment / "originals").iterdir()
        }
        self.assertEqual(archived_hashes, source_hashes)

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

    def test_selected_segment_archive_keeps_workspace_and_copies_only_selected_output(self):
        second_dir = self.workspace / "segments" / "seg-2" / "result"
        second_dir.mkdir(parents=True)
        (second_dir / "000001.jpg").write_bytes(b"other-result")
        selected_video = self.output / "selected.mp4"
        selected_video.write_bytes(b"selected-video")
        other_video = self.output / "other.mp4"
        other_video.write_bytes(b"other-video")
        self.project["segments"][0]["export_artifact"] = {"path": str(selected_video)}
        self.project["segments"].append({
            "id": "seg-2",
            "name": "Other",
            "frames": [str(self.source_files[0])],
            "recipe": {"grade": "clear"},
            "export_artifact": {"path": str(other_video)},
        })

        destination = archive_project(
            self.project,
            self.workspace,
            self.output,
            self.archive,
            timestamp="2026-07-15_120010",
            segment_ids=["seg-1"],
            clear_workspace=False,
        )

        manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["segment_count"], 1)
        self.assertEqual([item["id"] for item in manifest["segments"]], ["seg-1"])
        self.assertEqual(manifest["media"]["outputs"], ["output/selected.mp4"])
        self.assertTrue((destination / "output" / "selected.mp4").is_file())
        self.assertFalse((destination / "output" / "other.mp4").exists())
        self.assertTrue((self.workspace / "project.json").is_file())
        self.assertTrue((self.workspace / "segments" / "seg-2" / "result" / "000001.jpg").is_file())

    def test_cancelled_archive_removes_temporary_copy_and_keeps_workspace(self):
        class CancelledForTest(RuntimeError):
            pass

        checks = 0

        def check_cancelled():
            nonlocal checks
            checks += 1
            if checks >= 3:
                raise CancelledForTest("cancelled")

        with self.assertRaises(CancelledForTest):
            archive_project(
                self.project,
                self.workspace,
                self.output,
                self.archive,
                timestamp="2026-07-15_120011",
                check_cancelled=check_cancelled,
            )

        self.assertFalse((self.archive / "2026-07-15_120011").exists())
        self.assertFalse(any(path.name.startswith(".archiving-") for path in self.archive.iterdir()))
        self.assertTrue((self.workspace / "project.json").is_file())

    def test_automatic_archive_name_never_overwrites_same_second_archive(self):
        fixed = datetime(2026, 7, 19, 10, 30, 45).astimezone()
        with patch("src.archive.datetime") as clock:
            clock.now.return_value = fixed
            first = archive_project(
                self.project,
                self.workspace,
                self.output,
                self.archive,
                clear_workspace=False,
            )
            second = archive_project(
                self.project,
                self.workspace,
                self.output,
                self.archive,
                clear_workspace=False,
            )

        self.assertEqual(first.name, "2026-07-19_103045")
        self.assertEqual(second.name, "2026-07-19_103045_02")
        self.assertTrue(first.is_dir())
        self.assertTrue(second.is_dir())

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
