import hashlib
import json
import os
import tempfile
import threading
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

    def _analysis_for(self, frames=None, gains=None):
        frames = frames or self.frames
        gains = gains or [1.0] * len(frames)
        return {
            "frame_count": len(frames),
            "gain": gains,
            "sources": [image_pipeline._source_identity(path.resolve()) for path in frames],
        }

    def _install_old_analysis(self, work_dir):
        version = work_dir / ".analysis_versions" / "old-version"
        thumbnails = version / "thumbnails"
        thumbnails.mkdir(parents=True)
        thumbnail = thumbnails / "000000.jpg"
        thumbnail.write_bytes(b"old-thumbnail")
        representative = version / "representative.jpg"
        representative.write_bytes(b"old-representative")
        old = {
            "old": True,
            "thumbnails": [{"path": ".analysis_versions/old-version/thumbnails/000000.jpg"}],
            "representative_frame": {
                "thumbnail": ".analysis_versions/old-version/thumbnails/000000.jpg",
                "image": ".analysis_versions/old-version/representative.jpg",
            },
        }
        analysis_path = work_dir / "analysis.json"
        analysis_path.write_text(json.dumps(old), encoding="utf-8")
        return old, thumbnail, representative

    def test_analyze_segment_writes_atomic_analysis_and_preserves_sources(self):
        before = {path: _digest(path) for path in self.frames}
        source_names = {path.name for path in self.source.iterdir()}
        work_dir = self.root / "segment-work"
        work_dir.mkdir()
        old_analysis, old_thumbnail, old_representative = self._install_old_analysis(work_dir)
        progress_calls = []
        commit_observed = []
        real_replace = os.replace

        def commit(source, destination):
            self.assertEqual(Path(destination), work_dir / "analysis.json")
            self.assertEqual(
                json.loads((work_dir / "analysis.json").read_text(encoding="utf-8")),
                old_analysis,
            )
            candidate = json.loads(Path(source).read_text(encoding="utf-8"))
            for thumbnail in candidate["thumbnails"]:
                self.assertTrue((work_dir / thumbnail["path"]).is_file())
            self.assertTrue((work_dir / candidate["representative_frame"]["image"]).is_file())
            self.assertFalse((work_dir / "thumbnails").exists())
            self.assertFalse((work_dir / "representative.jpg").exists())
            real_replace(source, destination)
            self.assertEqual(
                json.loads((work_dir / "analysis.json").read_text(encoding="utf-8")),
                candidate,
            )
            commit_observed.append(True)

        with mock.patch("src.image_pipeline.os.replace", side_effect=commit) as replace:
            result = image_pipeline.analyze_segment(
                self.segment,
                self.recipe,
                work_dir,
                lambda completed, total, **detail: progress_calls.append((completed, total, detail)),
                lambda: False,
            )

        analysis_path = work_dir / "analysis.json"
        self.assertTrue(analysis_path.is_file())
        self.assertEqual(replace.call_count, 1)
        self.assertEqual(commit_observed, [True])
        self.assertTrue(old_thumbnail.is_file())
        self.assertTrue(old_representative.is_file())
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
        self.assertIn("anomaly_candidates", result)
        self.assertEqual(sum(result["histogram_summary"]["counts"]), 8 * 8 * 10)
        self.assertEqual(len(result["thumbnails"]), 8)
        self.assertTrue((work_dir / result["representative_frame"]["thumbnail"]).is_file())
        self.assertTrue((work_dir / result["representative_frame"]["image"]).is_file())
        for thumbnail in result["thumbnails"]:
            self.assertTrue((work_dir / thumbnail["path"]).is_file())
        self.assertEqual(progress_calls[-1][0:2], (8, 8))
        self.assertEqual(before, {path: _digest(path) for path in self.frames})
        self.assertEqual(source_names, {path.name for path in self.source.iterdir()})

    def test_analyze_cancellation_does_not_replace_previous_analysis(self):
        work_dir = self.root / "segment-work"
        work_dir.mkdir()
        analysis_path = work_dir / "analysis.json"
        old_analysis, old_thumbnail, representative = self._install_old_analysis(work_dir)
        checks = iter((False, False, True))

        with self.assertRaises(image_pipeline.TaskCancelled):
            image_pipeline.analyze_segment(
                self.segment,
                self.recipe,
                work_dir,
                lambda *args, **kwargs: None,
                lambda: next(checks, True),
            )

        self.assertEqual(json.loads(analysis_path.read_text(encoding="utf-8")), old_analysis)
        self.assertEqual(old_thumbnail.read_bytes(), b"old-thumbnail")
        self.assertEqual(representative.read_bytes(), b"old-representative")

    def test_analysis_publish_failure_restores_old_analysis_and_thumbnails(self):
        work_dir = self.root / "segment-work"
        work_dir.mkdir()
        analysis_path = work_dir / "analysis.json"
        old_analysis, old_thumbnail, representative = self._install_old_analysis(work_dir)
        old_versions = set((work_dir / ".analysis_versions").iterdir())

        def fail_new_analysis(source, destination):
            candidate = json.loads(Path(source).read_text(encoding="utf-8"))
            for thumbnail in candidate["thumbnails"]:
                self.assertTrue((work_dir / thumbnail["path"]).is_file())
            self.assertEqual(
                json.loads(analysis_path.read_text(encoding="utf-8")), old_analysis
            )
            raise OSError("analysis publication failed")

        with mock.patch("src.image_pipeline.os.replace", side_effect=fail_new_analysis) as replace:
            with self.assertRaisesRegex(OSError, "analysis publication failed"):
                image_pipeline.analyze_segment(
                    self.segment, self.recipe, work_dir, lambda *a, **k: None, lambda: False
                )

        self.assertEqual(replace.call_count, 1)
        self.assertEqual(json.loads(analysis_path.read_text(encoding="utf-8")), old_analysis)
        self.assertEqual(old_thumbnail.read_bytes(), b"old-thumbnail")
        self.assertEqual(representative.read_bytes(), b"old-representative")
        self.assertEqual(set((work_dir / ".analysis_versions").iterdir()), old_versions)
        self.assertFalse((work_dir / "thumbnails").exists())
        self.assertFalse((work_dir / "representative.jpg").exists())

    def test_post_commit_fsync_failure_keeps_committed_version_available(self):
        work_dir = self.root / "segment-work"
        work_dir.mkdir()

        def fail_after_commit(path):
            if Path(path) == work_dir:
                raise OSError("post-commit fsync failed")

        with mock.patch("src.image_pipeline._fsync_directory", side_effect=fail_after_commit):
            with self.assertRaisesRegex(OSError, "post-commit fsync failed"):
                image_pipeline.analyze_segment(
                    self.segment, self.recipe, work_dir, lambda *a, **k: None, lambda: False
                )

        committed = json.loads((work_dir / "analysis.json").read_text(encoding="utf-8"))
        self.assertEqual(committed["frame_count"], 8)
        for thumbnail in committed["thumbnails"]:
            self.assertTrue((work_dir / thumbnail["path"]).is_file())
        representative = committed["representative_frame"]
        self.assertTrue((work_dir / representative["thumbnail"]).is_file())
        self.assertTrue((work_dir / representative["image"]).is_file())

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

    def test_render_workers_process_frames_concurrently_without_losing_outputs(self):
        analysis = self._analysis_for()
        recipe = {**self.recipe, "render_workers": 4}
        target = self.root / "parallel-render-target"
        barrier = threading.Barrier(4)
        thread_ids = set()
        lock = threading.Lock()
        real_load = image_ops.load_image

        def concurrent_load(path, decode=None, half=False):
            with lock:
                thread_ids.add(threading.get_ident())
            barrier.wait(timeout=2)
            return real_load(path, decode, half)

        with mock.patch("src.image_pipeline.load_image", side_effect=concurrent_load):
            result = image_pipeline.render_segment(
                self.segment,
                recipe,
                analysis,
                target,
                lambda *args, **kwargs: None,
                lambda: False,
            )

        self.assertGreaterEqual(len(thread_ids), 4)
        self.assertEqual(result.frame_count, len(self.frames))
        self.assertEqual(len(list((target / "result").glob("*.jpg"))), len(self.frames))

    def test_auto_render_device_uses_gpu_only_for_golden_processing(self):
        with mock.patch("src.image_pipeline.resolve_render_device", return_value="gpu") as resolve:
            self.assertEqual(
                image_pipeline.render_device({"render_device": "auto"}), "cpu"
            )
            self.assertEqual(
                image_pipeline.render_device(
                    {
                        "render_device": "auto",
                        "enhance_golden": {"enable": True, "strength": 1.2},
                    }
                ),
                "gpu",
            )

        resolve.assert_called_once_with("auto")

    def test_auto_cpu_workers_scale_to_eight_on_twenty_threads(self):
        with mock.patch("src.image_pipeline.os.cpu_count", return_value=20):
            workers = image_pipeline.render_worker_count(
                {"render_workers": 0, "render_device": "cpu"}, 100
            )

        self.assertEqual(workers, 8)

    def test_duplicate_names_from_different_directories_render_once_in_stable_order(self):
        first_dir = self.source / "first"
        second_dir = self.source / "second"
        first_dir.mkdir()
        second_dir.mkdir()
        first = first_dir / "frame_000.jpg"
        second = second_dir / "frame_000.jpg"
        _write_frame(first, 25)
        _write_frame(second, 200)
        segment = {**self.segment, "frames": [str(first), str(second)]}
        analysis = self._analysis_for([first, second])
        before = {path: _digest(path) for path in (first, second)}

        with (
            mock.patch("src.image_pipeline.load_image", wraps=image_ops.load_image) as decode,
            mock.patch("src.image_pipeline.save_jpeg", wraps=image_ops.save_jpeg) as save,
        ):
            image_pipeline.render_segment(
                segment,
                self.recipe,
                analysis,
                self.root / "duplicate-target",
                lambda *a, **k: None,
                lambda: False,
            )

        outputs = sorted((self.root / "duplicate-target" / "result").glob("*.jpg"))
        self.assertEqual(len(outputs), 2)
        self.assertNotEqual(outputs[0].name.casefold(), outputs[1].name.casefold())
        self.assertEqual(decode.call_count, 2)
        self.assertEqual(save.call_count, 2)
        self.assertLess(np.asarray(Image.open(outputs[0])).mean(), np.asarray(Image.open(outputs[1])).mean())

        image_pipeline.render_segment(
            segment,
            self.recipe,
            analysis,
            self.root / "duplicate-target-2",
            lambda *a, **k: None,
            lambda: False,
        )
        second_names = sorted(
            path.name for path in (self.root / "duplicate-target-2" / "result").glob("*.jpg")
        )
        self.assertEqual([path.name for path in outputs], second_names)
        self.assertEqual(before, {path: _digest(path) for path in (first, second)})

    def test_duplicate_sequences_keep_source_timeline_when_outputs_are_sorted(self):
        first_dir = self.source / "first"
        second_dir = self.source / "second"
        first_dir.mkdir()
        second_dir.mkdir()
        paths = [
            first_dir / "frame_000.jpg",
            first_dir / "frame_001.jpg",
            second_dir / "frame_000.jpg",
            second_dir / "frame_001.jpg",
        ]
        for path, value in zip(paths, (20, 70, 140, 220)):
            _write_frame(path, value)
        segment = {**self.segment, "frames": [str(path) for path in paths]}

        image_pipeline.render_segment(
            segment,
            self.recipe,
            self._analysis_for(paths),
            self.root / "duplicate-sequence-target",
            lambda *a, **k: None,
            lambda: False,
        )

        outputs = sorted((self.root / "duplicate-sequence-target" / "result").glob("*.jpg"))
        means = [float(np.asarray(Image.open(path)).mean()) for path in outputs]
        self.assertEqual(len(outputs), 4)
        self.assertEqual(means, sorted(means))

    def test_rejecting_duplicate_by_source_path_keeps_other_original_name(self):
        first_dir = self.source / "first"
        second_dir = self.source / "second"
        first_dir.mkdir()
        second_dir.mkdir()
        first = first_dir / "frame_000.jpg"
        second = second_dir / "frame_000.jpg"
        _write_frame(first, 25)
        _write_frame(second, 200)
        segment = {**self.segment, "frames": [str(first), str(second)]}
        analysis = self._analysis_for([first, second])
        recipe = dict(self.recipe)
        recipe["deglare"] = {"enable": True, "reject": [str(second.resolve())]}

        with mock.patch("src.image_pipeline.load_image", wraps=image_ops.load_image) as decode:
            result = image_pipeline.render_segment(
                segment,
                recipe,
                analysis,
                self.root / "reject-target",
                lambda *a, **k: None,
                lambda: False,
            )

        self.assertEqual(result.frame_count, 1)
        self.assertEqual(result.rejected_count, 1)
        self.assertEqual(decode.call_count, 1)
        self.assertEqual(
            [path.name for path in (self.root / "reject-target" / "result").glob("*.jpg")],
            ["frame_000.jpg"],
        )

    def test_render_applies_combined_gain_then_grade_then_golden(self):
        one_frame = {**self.segment, "frames": [str(self.frames[0])]}
        analysis = self._analysis_for([self.frames[0]], [1.1])
        recipe = {
            "grade": {"style": "natural"},
            "enhance_golden": {"enable": True, "strength": 0.8, "core": [1, 1], "ramp": 0},
        }
        target = self.root / "order-target"
        calls = []

        def adjustments(
            rgb, gain, style, overrides, golden, device, output_uint8=False
        ):
            calls.append((gain, style, golden, device, output_uint8))
            return rgb

        with mock.patch(
            "src.image_pipeline.render_adjustments", side_effect=adjustments
        ):
            image_pipeline.render_segment(
                one_frame, recipe, analysis, target, lambda *a, **k: None, lambda: False
            )

        self.assertEqual(len(calls), 1)
        self.assertAlmostEqual(calls[0][0], 1.1)
        self.assertEqual(calls[0][1], "natural")
        self.assertAlmostEqual(calls[0][2], 0.8)
        self.assertEqual(calls[0][3], "cpu")
        self.assertFalse(calls[0][4])

    def test_gpu_render_uses_decode_grade_encode_pipeline(self):
        analysis = self._analysis_for()
        recipe = {
            **self.recipe,
            "render_device": "gpu",
            "render_workers": 2,
            "enhance_golden": {"enable": True, "strength": 0.8},
        }
        target = self.root / "gpu-pipeline-target"
        decode_threads = set()
        grade_threads = set()
        save_threads = set()

        def load(path, decode=None, half=False):
            decode_threads.add(threading.get_ident())
            return np.full((8, 12, 3), 80, dtype=np.float32)

        def adjust(
            rgb, gain, style, overrides, golden, device, output_uint8=False
        ):
            grade_threads.add(threading.get_ident())
            self.assertEqual(device, "gpu")
            self.assertTrue(output_uint8)
            return rgb.astype(np.uint8)

        def save(rgb, path, quality=95):
            save_threads.add(threading.get_ident())
            image_ops.save_jpeg(rgb, path, quality)

        with (
            mock.patch("src.image_pipeline.resolve_render_device", return_value="gpu"),
            mock.patch("src.image_pipeline.load_image", side_effect=load),
            mock.patch("src.image_pipeline.render_adjustments", side_effect=adjust),
            mock.patch("src.image_pipeline.save_jpeg", side_effect=save),
        ):
            result = image_pipeline.render_segment(
                self.segment,
                recipe,
                analysis,
                target,
                lambda *a, **k: None,
                lambda: False,
            )

        self.assertEqual(result.frame_count, len(self.frames))
        self.assertGreaterEqual(len(decode_threads), 1)
        self.assertEqual(grade_threads, {threading.get_ident()})
        self.assertTrue(save_threads)
        self.assertTrue(grade_threads.isdisjoint(save_threads))

    def test_failed_render_keeps_previous_published_result(self):
        target = self.root / "render-target"
        result_dir = target / "result"
        result_dir.mkdir(parents=True)
        old = result_dir / "old.jpg"
        old.write_bytes(b"previous-result")
        analysis = self._analysis_for()
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
        analysis = self._analysis_for()
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
        analysis = self._analysis_for()
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

    def test_render_rejects_changed_source_identity_and_keeps_result(self):
        target = self.root / "render-target"
        result_dir = target / "result"
        result_dir.mkdir(parents=True)
        old = result_dir / "old.jpg"
        old.write_bytes(b"previous-result")
        analysis = self._analysis_for()
        _write_frame(self.frames[0], 200)

        with self.assertRaisesRegex(ValueError, "source identity"):
            image_pipeline.render_segment(
                self.segment, self.recipe, analysis, target, lambda *a, **k: None, lambda: False
            )

        self.assertEqual(old.read_bytes(), b"previous-result")
        self.assertEqual(list(target.glob(".rendering-*")), [])

    def test_source_identity_path_comparison_is_case_insensitive_on_windows(self):
        analysis = self._analysis_for()
        for source in analysis["sources"]:
            source["path"] = source["path"].swapcase()

        result = image_pipeline.render_segment(
            self.segment,
            self.recipe,
            analysis,
            self.root / "render-target",
            lambda *a, **k: None,
            lambda: False,
        )

        self.assertEqual(result.frame_count, 8)

    def test_each_kept_frame_decodes_once_and_rejected_frame_is_not_decoded(self):
        analysis = self._analysis_for()
        recipe = dict(self.recipe)
        recipe["deglare"] = {"enable": True, "reject": [self.frames[3].stem]}
        target = self.root / "render-target"

        with mock.patch("src.image_pipeline.load_image", wraps=image_ops.load_image) as decode:
            image_pipeline.render_segment(
                self.segment, recipe, analysis, target, lambda *a, **k: None, lambda: False
            )

        decoded = [Path(call.args[0]).name for call in decode.call_args_list]
        self.assertEqual(len(decoded), 7)
        self.assertNotIn(self.frames[3].name, decoded)
        self.assertEqual(len(decoded), len(set(decoded)))

    def test_non_finite_analysis_gain_is_rejected_before_render(self):
        target = self.root / "render-target"
        with self.assertRaises(ValueError):
            image_pipeline.render_segment(
                self.segment,
                self.recipe,
                self._analysis_for(gains=[1.0] * 7 + [np.nan]),
                target,
                lambda *a, **k: None,
                lambda: False,
            )
        self.assertFalse((target / "result").exists())


if __name__ == "__main__":
    unittest.main()
