import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.task_manager import TaskCancelled
from src.video_export import export_video, sanitize_windows_filename


class VideoExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.frames = self.root / "frames"
        self.frames.mkdir()
        for name in ["frame_10.jpg", "frame_2.jpg", "frame_1.jpg"]:
            (self.frames / name).write_bytes(b"jpeg")

    def tearDown(self):
        self.temporary.cleanup()

    def run_export(self, output_name="movie.mp4", **options):
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            concat = Path(command[command.index("-i") + 1])
            captured["concat_text"] = concat.read_text(encoding="utf-8")
            Path(command[-1]).write_bytes(b"mp4")
            return subprocess.CompletedProcess(command, 0, "", "")

        values = {"ffmpeg_exe": "ffmpeg-test", "fps": 30, **options}
        with patch("src.video_export.subprocess.run", side_effect=fake_run):
            result = export_video(self.frames, self.root / output_name, values)
        captured["result"] = result
        return captured

    def test_h264_1080p_command_and_natural_frame_order(self):
        captured = self.run_export(codec="h264", resolution="1080p", crf=20)
        command = captured["command"]
        self.assertIn("libx264", command)
        self.assertIn("scale=1920:1080:force_original_aspect_ratio=decrease", " ".join(command))
        self.assertLess(captured["concat_text"].index("frame_1.jpg"), captured["concat_text"].index("frame_2.jpg"))
        self.assertLess(captured["concat_text"].index("frame_2.jpg"), captured["concat_text"].index("frame_10.jpg"))

    def test_h265_4k_command(self):
        command = self.run_export(codec="h265", resolution="4k", fps=60)["command"]
        self.assertIn("libx265", command)
        self.assertIn("scale=3840:2160:force_original_aspect_ratio=decrease", " ".join(command))
        self.assertEqual(command[command.index("-r") + 1], "60")

    def test_preview_width_builds_16_by_9_scale_filter(self):
        command = self.run_export(
            codec="h264",
            resolution="preview",
            width=1280,
            crf=24,
        )["command"]
        self.assertIn("scale=1280:720:force_original_aspect_ratio=decrease", " ".join(command))

    def test_invalid_preview_width_is_rejected(self):
        with self.assertRaises(ValueError):
            export_video(
                self.frames,
                self.root / "preview.mp4",
                {"fps": 30, "resolution": "preview", "width": 1279},
            )

    def test_invalid_fps_is_rejected(self):
        with self.assertRaises(ValueError):
            export_video(self.frames, self.root / "movie.mp4", {"fps": 29})

    def test_windows_filename_is_sanitized(self):
        captured = self.run_export("A*金山?.mp4")
        self.assertEqual(captured["result"].name, "A_金山_.mp4")
        self.assertNotIn("*", captured["command"][-1])

    def test_concat_file_is_removed_and_ffmpeg_failure_preserves_frames(self):
        before = {path.name: path.read_bytes() for path in self.frames.iterdir()}
        with patch(
            "src.video_export.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, ["ffmpeg"], stderr="encode failed"),
        ):
            with self.assertRaises(RuntimeError):
                export_video(
                    self.frames,
                    self.root / "failed.mp4",
                    {"ffmpeg_exe": "ffmpeg-test", "fps": 30},
                )
        after = {path.name: path.read_bytes() for path in self.frames.iterdir()}
        self.assertEqual(before, after)
        self.assertEqual(list(self.root.glob(".frames-*.ffconcat")), [])

    def test_sanitize_reserved_and_trailing_characters(self):
        self.assertEqual(sanitize_windows_filename("A:B.mp4"), "A_B.mp4")
        self.assertEqual(sanitize_windows_filename("CON.mp4"), "_CON.mp4")
        self.assertEqual(sanitize_windows_filename("clip. .mp4"), "clip.mp4")

    def test_cancel_after_ffmpeg_keeps_existing_published_video(self):
        output = self.root / "movie.mp4"
        output.write_bytes(b"previous-video")

        def fake_run(command, **kwargs):
            Path(command[-1]).write_bytes(b"new-video")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch("src.video_export.subprocess.run", side_effect=fake_run):
            with self.assertRaises(TaskCancelled):
                export_video(
                    self.frames,
                    output,
                    {"ffmpeg_exe": "ffmpeg-test", "fps": 30},
                    cancelled=lambda: True,
                )

        self.assertEqual(output.read_bytes(), b"previous-video")
        self.assertEqual(list(self.root.glob(".frames-*.ffconcat")), [])
        self.assertEqual(list(self.root.glob(".*-rendering-*.mp4")), [])

    def test_cancel_after_ffmpeg_does_not_publish_new_video(self):
        output = self.root / "cancelled.mp4"

        def fake_run(command, **kwargs):
            Path(command[-1]).write_bytes(b"encoded-video")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch("src.video_export.subprocess.run", side_effect=fake_run):
            with self.assertRaises(TaskCancelled):
                export_video(
                    self.frames,
                    output,
                    {"ffmpeg_exe": "ffmpeg-test", "fps": 30},
                    cancelled=lambda: True,
                )

        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob(".frames-*.ffconcat")), [])
        self.assertEqual(list(self.root.glob(".*-rendering-*.mp4")), [])


if __name__ == "__main__":
    unittest.main()
