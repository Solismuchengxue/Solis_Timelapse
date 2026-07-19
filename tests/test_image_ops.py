import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from src import image_ops


class ImageOpsTests(unittest.TestCase):
    def test_render_device_resolves_auto_cpu_and_gpu(self):
        with mock.patch("src.image_ops.gpu_render_available", return_value=True):
            self.assertEqual(image_ops.resolve_render_device("auto"), "gpu")
            self.assertEqual(image_ops.resolve_render_device("gpu"), "gpu")
            self.assertEqual(image_ops.resolve_render_device("cpu"), "cpu")

        with mock.patch("src.image_ops.gpu_render_available", return_value=False):
            self.assertEqual(image_ops.resolve_render_device("auto"), "cpu")
            with self.assertRaises(RuntimeError):
                image_ops.resolve_render_device("gpu")

        with self.assertRaises(ValueError):
            image_ops.resolve_render_device("quantum")

    def test_cpu_render_adjustments_match_established_pipeline(self):
        rgb = np.array([[[30.0, 90.0, 180.0], [220.0, 150.0, 45.0]]])
        expected = image_ops.enhance_golden(
            image_ops.grade_by_style(image_ops.apply_gain(rgb, 1.05), "natural"),
            1.2,
        )

        actual = image_ops.render_adjustments(rgb, 1.05, "natural", None, 1.2, "cpu")

        np.testing.assert_array_equal(actual, expected)

    def test_linear_cpu_render_is_equivalent_to_established_pipeline(self):
        rgb = np.random.default_rng(7).uniform(0, 255, (48, 64, 3)).astype(np.float32)
        overrides = {"sat": 1.2, "con": 1.12, "pivot": 118.0}
        expected = image_ops.grade_by_style(
            image_ops.apply_gain(rgb, 1.05), "none", overrides
        )

        actual = image_ops.render_adjustments(
            rgb, 1.05, "none", overrides, 0.0, "cpu"
        )

        np.testing.assert_allclose(actual, expected, rtol=0, atol=0.001)

    @unittest.skipUnless(image_ops.gpu_render_available(), "OpenCL GPU is unavailable")
    def test_gpu_render_adjustments_are_visually_equivalent_to_cpu(self):
        rgb = np.random.default_rng(42).uniform(0, 255, (48, 64, 3)).astype(np.float32)
        overrides = {"sat": 1.2, "con": 1.12, "pivot": 118.0}

        cpu = image_ops.render_adjustments(rgb, 1.05, "none", overrides, 1.2, "cpu")
        gpu = image_ops.render_adjustments(rgb, 1.05, "none", overrides, 1.2, "gpu")

        np.testing.assert_allclose(gpu, cpu, rtol=0, atol=0.1)

    @unittest.skipUnless(image_ops.gpu_render_available(), "OpenCL GPU is unavailable")
    def test_gpu_render_can_return_compact_uint8_pixels(self):
        rgb = np.random.default_rng(8).integers(0, 256, (48, 64, 3), dtype=np.uint8)
        overrides = {"sat": 1.2, "con": 1.12, "pivot": 118.0}

        full = image_ops.render_adjustments(
            rgb, 1.05, "none", overrides, 1.2, "gpu"
        )
        compact = image_ops.render_adjustments(
            rgb, 1.05, "none", overrides, 1.2, "gpu", output_uint8=True
        )

        self.assertEqual(compact.dtype, np.uint8)
        np.testing.assert_allclose(compact, full, rtol=0, atol=1.0)

    def test_median_smoothing_and_gain_clipping(self):
        luminance = np.array([10.0, 10.0, 100.0, 10.0, 10.0])

        target = image_ops.smooth_median(luminance, 3)
        gain = image_ops.exposure_gain(luminance, 3, (0.85, 1.2))

        np.testing.assert_allclose(target, [10.0, 10.0, 10.0, 10.0, 10.0])
        np.testing.assert_allclose(gain, [1.0, 1.0, 0.85, 1.0, 1.0])

    def test_zero_luminance_produces_finite_clipped_gain(self):
        gain = image_ops.exposure_gain([0.0, 0.0, 0.0], 3, (0.85, 1.2))

        np.testing.assert_allclose(gain, [0.85, 0.85, 0.85])
        self.assertTrue(np.isfinite(gain).all())

    def test_non_finite_luminance_and_invalid_clip_are_rejected(self):
        for values in ([1.0, np.nan], [1.0, np.inf]):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    image_ops.exposure_gain(values, 3, (0.85, 1.2))

        for clip in ((1.2, 0.85), (0.0, 1.2), (0.85, np.inf), (0.85,), (0.85, 20.0)):
            with self.subTest(clip=clip):
                with self.assertRaises(ValueError):
                    image_ops.exposure_gain([10.0, 10.0], 3, clip)

    def test_grade_presets_and_no_op(self):
        rgb = np.array([[[40.0, 100.0, 180.0], [120.0, 120.0, 120.0]]])

        none = image_ops.grade_by_style(rgb, "none")
        natural = image_ops.grade_by_style(rgb, "natural")
        punchy = image_ops.grade_by_style(rgb, "punchy")

        np.testing.assert_allclose(none, rgb)
        self.assertGreater(np.ptp(natural[0, 0]), np.ptp(none[0, 0]))
        self.assertGreater(np.ptp(punchy[0, 0]), np.ptp(natural[0, 0]))

    def test_unknown_grade_style_is_no_op(self):
        rgb = np.array([[[32.0, 96.0, 160.0]]])
        np.testing.assert_allclose(image_ops.grade_by_style(rgb, "unknown"), rgb)

    def test_non_finite_gain_grade_and_golden_inputs_are_rejected(self):
        rgb = np.full((1, 1, 3), 100.0)
        for gain in (np.nan, np.inf, -1.0):
            with self.subTest(gain=gain):
                with self.assertRaises(ValueError):
                    image_ops.apply_gain(rgb, gain)
        for overrides in ({"sat": np.nan}, {"con": np.inf}, {"pivot": -1.0}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    image_ops.grade_by_style(rgb, "natural", overrides)
        for strength in (np.nan, np.inf, -0.1, 5.0):
            with self.subTest(strength=strength):
                with self.assertRaises(ValueError):
                    image_ops.enhance_golden(rgb, strength)

    def test_save_jpeg_rejects_non_finite_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.jpg"
            with self.assertRaises(ValueError):
                image_ops.save_jpeg(np.array([[[np.nan, 0.0, 0.0]]]), path)
            self.assertFalse(path.exists())

    def test_save_jpeg_uses_uint8_pixels_without_float_validation_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fast.jpg"
            pixels = np.full((8, 12, 3), 127, dtype=np.uint8)

            with mock.patch(
                "src.image_ops._finite_rgb",
                side_effect=AssertionError("uint8 fast path should not make a float copy"),
            ):
                image_ops.save_jpeg(pixels, path)

            self.assertTrue(path.exists())

    def test_golden_ramp_strength_at_boundaries(self):
        core = (100, 110)

        self.assertEqual(image_ops.golden_ramp_strength(90, core, 10, 1.2), 0.0)
        self.assertAlmostEqual(image_ops.golden_ramp_strength(95, core, 10, 1.2), 0.6)
        self.assertEqual(image_ops.golden_ramp_strength(100, core, 10, 1.2), 1.2)
        self.assertEqual(image_ops.golden_ramp_strength(110, core, 10, 1.2), 1.2)
        self.assertAlmostEqual(image_ops.golden_ramp_strength(115, core, 10, 1.2), 0.6)
        self.assertEqual(image_ops.golden_ramp_strength(120, core, 10, 1.2), 0.0)

    def test_golden_enhancement_changes_warm_highlights_more_than_neutral_shadows(self):
        rgb = np.array([[[230.0, 150.0, 55.0], [45.0, 45.0, 45.0]]])

        enhanced = image_ops.enhance_golden(rgb, 1.2)
        warm_change = np.linalg.norm(enhanced[0, 0] - rgb[0, 0])
        shadow_change = np.linalg.norm(enhanced[0, 1] - rgb[0, 1])

        self.assertGreater(warm_change, shadow_change)

    def test_frame_number_extraction(self):
        self.assertEqual(image_ops.frame_num("C:/photos/CZ_01194.ARW"), 1194)
        self.assertEqual(image_ops.frame_num("frame-without-number.jpg"), -1)


if __name__ == "__main__":
    unittest.main()
