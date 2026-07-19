from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from src.media_catalog import (
    FrameInfo,
    merge_segments,
    read_exif_details,
    reorder_segments,
    scan_source,
    split_segment,
    suggest_segments,
)


BASE_TIME = datetime(2026, 5, 7, 6, 10, tzinfo=timezone(timedelta(hours=8)))


def frame(index: int, **changes) -> FrameInfo:
    value = FrameInfo(
        path=f"C:/photos/CZ_{index:05d}.ARW",
        name=f"CZ_{index:05d}.ARW",
        captured_at=(BASE_TIME + timedelta(seconds=index * 5)).isoformat(),
        width=5328,
        height=4000,
        shutter=1 / 100,
        aperture=4.0,
        iso=100,
        exposure_bias=0.0,
        exposure_mode="Manual",
        metering_mode="Multi-segment",
        focal_length=70.0,
        white_balance="Manual",
    )
    return replace(value, **changes)


class SegmentationTests(unittest.TestCase):
    def assert_split_at_second_frame(self, frames, settings=None):
        segments = suggest_segments(frames, settings or {})
        self.assertEqual([len(item["source_files"]) for item in segments], [1, 1])
        self.assertEqual(segments[0]["source_files"], [frames[0].path])
        self.assertEqual(segments[1]["source_files"], [frames[1].path])

    def test_time_gap_over_threshold_splits(self):
        self.assert_split_at_second_frame(
            [frame(0), frame(1, captured_at=(BASE_TIME + timedelta(seconds=121)).isoformat())],
            {"gap_seconds": 120},
        )

    def test_focal_length_change_splits(self):
        self.assert_split_at_second_frame([frame(0), frame(1, focal_length=100.0)])

    def test_exposure_or_metering_mode_change_splits(self):
        self.assert_split_at_second_frame([frame(0), frame(1, exposure_mode="Aperture priority")])
        self.assert_split_at_second_frame([frame(0), frame(1, metering_mode="Spot")])

    def test_exposure_value_jump_splits(self):
        self.assert_split_at_second_frame(
            [frame(0), frame(1, shutter=1 / 25)], {"exposure_ev_jump": 1.5}
        )

    def test_stable_sequence_remains_one_segment(self):
        frames = [frame(index, latitude=27.102345, longitude=100.175678) for index in range(5)]
        segments = suggest_segments(frames, {})
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["source_files"], [item.path for item in frames])
        self.assertEqual(segments[0]["focal_length"], 70.0)
        self.assertIn("2026-05-07", segments[0]["time_range"])
        self.assertIn("06:10:00", segments[0]["time_range"])
        self.assertEqual(segments[0]["capture_date"], "2026-05-07")
        self.assertEqual(segments[0]["capture_time"], "06:10:00–06:10:20")
        self.assertEqual(segments[0]["location"], "27.102345°N, 100.175678°E")

    def test_empty_sequence_has_no_segments(self):
        self.assertEqual(suggest_segments([], {}), [])


class SegmentEditingTests(unittest.TestCase):
    def setUp(self):
        self.segments = suggest_segments([frame(index) for index in range(4)], {})
        self.original_id = self.segments[0]["id"]

    def test_split_preserves_membership_order_and_assigns_stable_ids(self):
        result = split_segment(self.segments, self.original_id, 2)
        self.assertEqual([segment["source_files"] for segment in result], [
            [frame(0).path, frame(1).path],
            [frame(2).path, frame(3).path],
        ])
        self.assertEqual(len({segment["id"] for segment in result}), 2)
        self.assertNotEqual(result[0]["id"], result[1]["id"])

    def test_split_rejects_boundaries(self):
        with self.assertRaises(ValueError):
            split_segment(self.segments, self.original_id, 0)
        with self.assertRaises(ValueError):
            split_segment(self.segments, self.original_id, 4)

    def test_merge_requires_adjacent_segments_and_preserves_order(self):
        split = split_segment(self.segments, self.original_id, 1)
        merged = merge_segments(split, split[0]["id"], split[1]["id"])
        self.assertEqual(merged[0]["source_files"], [frame(index).path for index in range(4)])
        self.assertEqual(merged[0]["id"], split[0]["id"])

        three = split_segment(split, split[1]["id"], 1)
        with self.assertRaises(ValueError):
            merge_segments(three, three[0]["id"], three[2]["id"])

    def test_merge_accepts_multiple_contiguous_segments(self):
        two = split_segment(self.segments, self.original_id, 1)
        three = split_segment(two, two[1]["id"], 1)

        merged = merge_segments(three, [segment["id"] for segment in three])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["source_files"], [frame(index).path for index in range(4)])
        self.assertEqual(merged[0]["focal_length"], 70.0)

    def test_reorder_requires_exact_ids_and_preserves_segments(self):
        split = split_segment(self.segments, self.original_id, 2)
        reordered = reorder_segments(split, [split[1]["id"], split[0]["id"]])
        self.assertEqual(reordered, [split[1], split[0]])
        with self.assertRaises(ValueError):
            reorder_segments(split, [split[0]["id"]])


class SourceScanTests(unittest.TestCase):
    def test_scan_is_deterministic_and_does_not_modify_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            exif = Image.Exif()
            exif[36867] = "2026:05:07 06:10:00"
            for name, color in (("B.JPG", "red"), ("a.jpg", "blue")):
                Image.new("RGB", (8, 6), color).save(source / name, exif=exif)
            (source / "ignored.txt").write_text("unchanged", encoding="utf-8")
            timestamp = BASE_TIME.timestamp()
            for path in source.iterdir():
                os.utime(path, (timestamp, timestamp))

            before = self._snapshot(source)
            scanned = scan_source(source)
            after = self._snapshot(source)

            self.assertEqual([item.name for item in scanned], ["a.jpg", "B.JPG"])
            self.assertTrue(all((item.width, item.height) == (8, 6) for item in scanned))
            self.assertEqual(
                {item.captured_at for item in scanned}, {"2026-05-07T06:10:00"}
            )
            self.assertEqual(before, after)

    def test_scan_reads_jpeg_capture_time_and_focal_length(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            exif = Image.Exif()
            exif[36867] = "2026:05:07 06:10:00"
            exif[37386] = (70, 1)
            Image.new("RGB", (8, 6), "red").save(source / "frame.jpg", exif=exif)

            scanned = scan_source(source)

            self.assertEqual(scanned[0].captured_at, "2026-05-07T06:10:00")
            self.assertEqual(scanned[0].focal_length, 70.0)

    def test_read_exif_details_returns_human_readable_tags_without_binary_thumbnail(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "frame.jpg"
            exif = Image.Exif()
            exif[271] = "SONY"
            exif[272] = "ZV-E10"
            Image.new("RGB", (8, 6), "red").save(source, exif=exif)

            entries = read_exif_details(source)
            tags = {(item["group"], item["tag"]): item["value"] for item in entries}

            self.assertEqual(tags[("Image", "Make")], "SONY")
            self.assertEqual(tags[("Image", "Model")], "ZV-E10")
            self.assertNotIn("JPEGThumbnail", {item["tag"] for item in entries})

    def test_scan_rejects_missing_directory(self):
        with self.assertRaises(FileNotFoundError):
            scan_source(Path("definitely-missing-source"))

    @staticmethod
    def _snapshot(source: Path):
        return {
            path.name: (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
            for path in source.iterdir()
        }


if __name__ == "__main__":
    unittest.main()
