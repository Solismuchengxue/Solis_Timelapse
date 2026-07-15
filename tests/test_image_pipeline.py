import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from src import image_ops, image_pipeline


def _write_frame(path: Path, value: int) -> None:
    pixels = np.full((8, 10, 3), value, dtype=np.uint8)
    Image.fromarray(pixels).save(path, quality=100, subsampling=0)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ImagePipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.frames = []
        for index, value in enumerate((20, 30, 40, 50, 60, 70, 80, 90), start=1):
            path = self.source / f"CZ_{index:05d}.JPG"
            _write_frame(path, value)
            self.frames.append(path)
        self.segment = {
            "id": "segment-a",
            "name": "sunrise-a",
            "frames": [str(path) for path in self.frames],
        }
        self.recipe = {
            "decode": {"bright": 3.5, "wb": "camera", "gamma": "srgb"},
            "deflicker": {"enable": True, "window": 3, "clip": [0.85, 1.2]},
            "lift_dark": {"enable": False, "window": 15, "clip": [0.7, 1.7]},
            "grade": {"style": "none"},
            "enhance_golden": {"enable": False},
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_analyze_segment_writes_atomic_analysis_and_preserves_sources(self):
        before = {path: _digest(path) for path in self.frames}
        work_dir = self.root / "segment-work"
        progress_calls = []

        with mock.patch("src.image_pipeline.os.replace", wraps=os.replace) as replace:
            result = image_pipeline.analyze_segment(
                self.segment,
                self.recipe,
                work_dir,
                lambda completed, total, **detail: progress_calls.append((completed, total, detail)),
                lambda: False,
            )

        analysis_path = work_dir / "analysis.json"
        self.assertTrue(analysis_path.is_file())
        replace.assert_called_once_with(work_dir / "analysis.json.tmp", analysis_path)
        self.assertFalse((work_dir / "analysis.json.tmp").exists())
        self.assertEqual(json.loads(analysis_path.read_text(encoding="utf-8")), result)
        self.assertEqual(result["frame_count"], 8)
        self.assertEqual(len(result["measured_luminance"]), 8)
        self.assertEqual(len(result["target_luminance"]), 8)
        self.assertEqual(len(result["gain"]), 8)
        expected_target = image_ops.smooth_median(result["measured_luminance"], 3)
        np.testing.assert_allclose(result["target_luminance"], expected_target)
        self.assertEqual(result["sources"][0]["path"], str(self.frames[0].resolve()))
        self.assertEqual(result["sources"][0]["name"], self.frames[0].name)
        self.assertIn("size", result["sources"][0])
        self.assertIn("mtime_ns", result["sources"][0])
        self.assertEqual(progress_calls[-1][0:2], (8, 8))
        self.assertEqual(before, {path: _digest(path) for path in self.frames})

    def test_analyze_cancellation_does_not_replace_previous_analysis(self):
        work_dir = self.root / "segment-work"
        work_dir.mkdir()
        analysis_path = work_dir / "analysis.json"
        analysis_path.write_text('{"old": true}', encoding="utf-8")
        checks = iter((False, False, True))

        with self.assertRaises(image_pipeline.TaskCancelled):
            image_pipeline.analyze_segment(
                self.segment,
                self.recipe,
                work_dir,
                lambda *args, **kwargs: None,
                lambda: next(checks, True),
            )

        self.assertEqual(analysis_path.read_text(encoding="utf-8"), '{"old": true}')

    def test_render_saves_once_per_kept_frame_and_excludes_rejected(self):
        before = {path: _digest(path) for path in self.frames}
        analysis = image_pipeline.analyze_segment(
            self.segment, self.recipe, self.root / "analysis", lambda *a, **k: None, lambda: False
        )
        recipe = dict(self.recipe)
        recipe["deglare"] = {"enable": True, "reject": [self.frames[2].stem]}
        recipe["grade"] = {"style": "natural"}
        recipe["enhance_golden"] = {
            "enable": True,
            "level": "strong",
            "core": [1, 8],
            "ramp": 2,
        }
        target = self.root / "render-target"

        with mock.patch("src.image_pipeline.save_jpeg", wraps=image_ops.save_jpeg) as save:
            result = image_pipeline.render_segment(
                self.segment,
                recipe,
                analysis,
                target,
                lambda *args, **kwargs: None,
                lambda: False,
            )

        self.assertEqual(save.call_count, 7)
        self.assertEqual(result.frame_count, 7)
        self.assertEqual(result.rejected_count, 1)
        output_names = sorted(path.name for path in (target / "result").glob("*.jpg"))
        self.assertNotIn(self.frames[2].with_suffix(".jpg").name, output_names)
        self.assertEqual(len(output_names), 7)
        self.assertEqual(before, {path: _digest(path) for path in self.frames})

    def test_render_applies_combined_gain_then_grade_then_golden(self):
        one_frame = {**self.segment, "frames": [str(self.frames[0])]}
        analysis = {"frame_count": 1, "gain": [1.1], "sources": [{"path": str(self.frames[0].resolve())}]}
        recipe = {
            "grade": {"style": "natural"},
            "enhance_golden": {"enable": True, "strength": 0.8, "core": [1, 1], "ramp": 0},
        }
        target = self.root / "order-target"
        calls = []

        def gain(rgb, value):
            calls.append(("gain", value))
            return rgb

        def grade(rgb, style, overrides=None):
            calls.append(("grade", style))
            return rgb

        def golden(rgb, strength):
            calls.append(("golden", strength))
            return rgb

        with (
            mock.patch("src.image_pipeline.apply_gain", side_effect=gain),
            mock.patch("src.image_pipeline.grade_by_style", side_effect=grade),
            mock.patch("src.image_pipeline.enhance_golden", side_effect=golden),
        ):
            image_pipeline.render_segment(
                one_frame, recipe, analysis, target, lambda *a, **k: None, lambda: False
            )

        self.assertEqual([call[0] for call in calls], ["gain", "grade", "golden"])
        self.assertAlmostEqual(calls[0][1], 1.1)
        self.assertAlmostEqual(calls[2][1], 0.8)

    def test_failed_render_keeps_previous_published_result(self):
        target = self.root / "render-target"
        result_dir = target / "result"
        result_dir.mkdir(parents=True)
        old = result_dir / "old.jpg"
        old.write_bytes(b"previous-result")
        analysis = {"frame_count": 8, "gain": [1.0] * 8,
                    "sources": [{"path": str(path.resolve())} for path in self.frames]}
        real_load = image_ops.load_image
        calls = 0

        def fail_on_second(path, decode=None, half=False):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("decode failed")
            return real_load(path, decode, half)

        with mock.patch("src.image_pipeline.load_image", side_effect=fail_on_second):
            with self.assertRaisesRegex(RuntimeError, "decode failed"):
                image_pipeline.render_segment(
                    self.segment, self.recipe, analysis, target, lambda *a, **k: None, lambda: False
                )

        self.assertEqual(old.read_bytes(), b"previous-result")
        self.assertEqual(list(target.glob(".rendering-*")), [])

    def test_publish_failure_restores_previous_result(self):
        target = self.root / "render-target"
        result_dir = target / "result"
        result_dir.mkdir(parents=True)
        old = result_dir / "old.jpg"
        old.write_bytes(b"previous-result")
        analysis = {"frame_count": 8, "gain": [1.0] * 8,
                    "sources": [{"path": str(path.resolve())} for path in self.frames]}
        real_replace = os.replace
        publication_attempted = False

        def fail_publication(source, destination):
            nonlocal publication_attempted
            if Path(source).name.startswith(".rendering-"):
                publication_attempted = True
                raise OSError("publication failed")
            return real_replace(source, destination)

        with mock.patch("src.image_pipeline.os.replace", side_effect=fail_publication):
            with self.assertRaisesRegex(OSError, "publication failed"):
                image_pipeline.render_segment(
                    self.segment, self.recipe, analysis, target, lambda *a, **k: None, lambda: False
                )

        self.assertTrue(publication_attempted)
        self.assertEqual(old.read_bytes(), b"previous-result")
        self.assertEqual(list(target.glob(".rendering-*")), [])
        self.assertEqual(list(target.glob(".result-backup-*")), [])

    def test_render_cancels_at_frame_boundary_without_replacing_result(self):
        target = self.root / "render-target"
        result_dir = target / "result"
        result_dir.mkdir(parents=True)
        old = result_dir / "old.jpg"
        old.write_bytes(b"previous-result")
        analysis = {"frame_count": 8, "gain": [1.0] * 8,
                    "sources": [{"path": str(path.resolve())} for path in self.frames]}
        checks = iter((False, True))

        with self.assertRaises(image_pipeline.TaskCancelled):
            image_pipeline.render_segment(
                self.segment,
                self.recipe,
                analysis,
                target,
                lambda *args, **kwargs: None,
                lambda: next(checks, True),
            )

        self.assertEqual(old.read_bytes(), b"previous-result")
        self.assertEqual(list(target.glob(".rendering-*")), [])


if __name__ == "__main__":
    unittest.main()
