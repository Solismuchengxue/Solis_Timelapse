import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from src import hdr_merge


class HdrMergeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.root = Path(self.temp.name)
        self.frames = []
        for index, value in enumerate((28, 92, 210)):
            pixels = np.full((24, 32, 3), value, dtype=np.uint8)
            pixels[:, 8:24, 0] = min(255, value + 30)
            path = self.root / f"frame_{index}.jpg"
            Image.fromarray(pixels).save(path)
            self.frames.append(path)

    def tearDown(self):
        self.temp.cleanup()

    def test_fusion_writes_preview_and_jpeg_without_exposure_times(self):
        output = self.root / "output.jpg"
        preview = self.root / "preview.jpg"

        result = hdr_merge.merge_exposures(
            self.frames,
            output,
            preview,
            {"mode": "fusion", "align": False, "output_format": "jpeg"},
        )

        self.assertTrue(output.is_file())
        self.assertTrue(preview.is_file())
        self.assertEqual(result["mode"], "fusion")
        self.assertEqual(result["frame_count"], 3)
        with Image.open(output) as image:
            self.assertEqual(image.size, (32, 24))

    def test_radiance_requires_one_positive_exposure_time_per_frame(self):
        with self.assertRaisesRegex(ValueError, "exposure"):
            hdr_merge.merge_exposures(
                self.frames,
                self.root / "output.jpg",
                self.root / "preview.jpg",
                {"mode": "radiance", "align": False},
                exposure_times=[0.01, None, 1.0],
            )

    def test_radiance_merge_accepts_valid_exposure_times(self):
        output = self.root / "radiance.jpg"

        result = hdr_merge.merge_exposures(
            self.frames,
            output,
            self.root / "radiance-preview.jpg",
            {"mode": "radiance", "align": False},
            exposure_times=[1 / 30, 1 / 125, 1 / 500],
        )

        self.assertTrue(output.is_file())
        self.assertEqual(result["mode"], "radiance")

    def test_frame_count_is_limited_to_two_through_nine(self):
        with self.assertRaisesRegex(ValueError, "2 to 9"):
            hdr_merge.merge_exposures(
                self.frames[:1],
                self.root / "output.jpg",
                self.root / "preview.jpg",
                {"mode": "fusion"},
            )

        with self.assertRaisesRegex(ValueError, "2 to 9"):
            hdr_merge.merge_exposures(
                self.frames * 4,
                self.root / "output.jpg",
                self.root / "preview.jpg",
                {"mode": "fusion"},
            )

    def test_tiff_output_is_16_bit(self):
        output = self.root / "output.tiff"

        hdr_merge.merge_exposures(
            self.frames,
            output,
            self.root / "preview.jpg",
            {"mode": "fusion", "align": False, "output_format": "tiff"},
        )

        import cv2

        decoded = cv2.imread(str(output), cv2.IMREAD_UNCHANGED)
        self.assertEqual(decoded.dtype, np.uint16)


if __name__ == "__main__":
    unittest.main()
