import unittest

import numpy as np

from src import image_ops


class ImageOpsTests(unittest.TestCase):
    def test_median_smoothing_and_gain_clipping(self):
        luminance = np.array([10.0, 10.0, 100.0, 10.0, 10.0])

        target = image_ops.smooth_median(luminance, 3)
        gain = image_ops.exposure_gain(luminance, 3, (0.85, 1.2))

        np.testing.assert_allclose(target, [10.0, 10.0, 10.0, 10.0, 10.0])
        np.testing.assert_allclose(gain, [1.0, 1.0, 0.85, 1.0, 1.0])

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
