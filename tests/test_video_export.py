import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src.task_manager import TaskCancelled
from src.video_export import export_video, sanitize_windows_filename


class FakeProcess:
    def __init__(self, command, *, progress="", stderr="", returncode=0):
        self.command = command
        self.stdout = io.StringIO(progress)
        self.stderr = io.StringIO(stderr)
        self.returncode = returncode
        self.terminated = False

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.terminated = True
        self.returncode = -9


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

        def fake_popen(command, **kwargs):
            captured["command"] = command
            concat = Path(command[command.index("-i") + 1])
            captured["concat_text"] = concat.read_text(encoding="utf-8")
            Path(command[-1]).write_bytes(b"mp4")
            return FakeProcess(command, progress="frame=3\nprogress=end\n")

        values = {"ffmpeg_exe": "ffmpeg-test", "fps": 30, **options}
        with patch("src.video_export.subprocess.Popen", side_effect=fake_popen):
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

    def test_source_resolution_alias_preserves_original_dimensions(self):
        command = self.run_export(codec="h264", resolution="source")["command"]

        self.assertNotIn("-vf", command)

    def test_auto_hardware_acceleration_uses_nvenc_quality_controls(self):
        with patch("src.video_export._nvenc_available", return_value=True):
            command = self.run_export(
                codec="h264",
                resolution="4k",
                crf=18,
                hardware_acceleration="auto",
            )["command"]

        self.assertIn("h264_nvenc", command)
        self.assertIn("-cq", command)
        self.assertEqual(command[command.index("-preset") + 1], "p3")
        self.assertIn("-multipass", command)
        self.assertNotIn("-crf", command)

    def test_auto_hardware_acceleration_falls_back_to_software(self):
        commands = []
        selected = []

        def fake_popen(command, **kwargs):
            commands.append(command)
            if "h264_nvenc" in command:
                return FakeProcess(command, stderr="NVENC unavailable", returncode=1)
            Path(command[-1]).write_bytes(b"software-video")
            return FakeProcess(command, progress="frame=3\nprogress=end\n")

        with (
            patch("src.video_export._nvenc_available", return_value=True),
            patch("src.video_export.subprocess.Popen", side_effect=fake_popen),
        ):
            result = export_video(
                self.frames,
                self.root / "fallback.mp4",
                {
                    "ffmpeg_exe": "ffmpeg-test",
                    "fps": 30,
                    "codec": "h264",
                    "hardware_acceleration": "auto",
                    "_on_encoder_selected": selected.append,
                },
            )

        self.assertEqual(len(commands), 2)
        self.assertIn("h264_nvenc", commands[0])
        self.assertIn("libx264", commands[1])
        self.assertEqual(commands[1][commands[1].index("-preset") + 1], "faster")
        self.assertEqual(selected, ["libx264"])
        self.assertEqual(result.read_bytes(), b"software-video")

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
            "src.video_export.subprocess.Popen",
            return_value=FakeProcess(["ffmpeg"], stderr="encode failed", returncode=1),
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

        def fake_popen(command, **kwargs):
            Path(command[-1]).write_bytes(b"new-video")
            return FakeProcess(command, progress="frame=3\nprogress=end\n")

        with patch("src.video_export.subprocess.Popen", side_effect=fake_popen):
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

        def fake_popen(command, **kwargs):
            Path(command[-1]).write_bytes(b"encoded-video")
            return FakeProcess(command, progress="frame=3\nprogress=end\n")

        with patch("src.video_export.subprocess.Popen", side_effect=fake_popen):
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

    def test_reports_real_ffmpeg_frame_progress_and_eta(self):
        updates = []

        def fake_popen(command, **kwargs):
            Path(command[-1]).write_bytes(b"video")
            return FakeProcess(
                command,
                progress=(
                    "frame=1\nfps=2.0\nspeed=0.5x\nprogress=continue\n"
                    "frame=3\nfps=4.0\nspeed=1.0x\nprogress=end\n"
                ),
            )

        with patch("src.video_export.subprocess.Popen", side_effect=fake_popen):
            export_video(
                self.frames,
                self.root / "progress.mp4",
                {"ffmpeg_exe": "ffmpeg-test", "fps": 30},
                progress=lambda done, total, **detail: updates.append(
                    (done, total, detail)
                ),
            )

        self.assertEqual([update[0] for update in updates], [1, 3])
        self.assertTrue(all(update[1] == 3 for update in updates))
        self.assertEqual(updates[-1][2]["encoder"], "libx264")
        self.assertIn("eta_seconds", updates[0][2])

    def test_original_oversize_h264_does_not_silently_fall_back_to_cpu(self):
        frame = self.frames / "frame_1.jpg"
        Image.new("RGB", (5000, 100), "black").save(frame)

        with (
            patch("src.video_export._nvenc_available", return_value=True),
            patch("src.video_export.subprocess.Popen") as popen,
            self.assertRaisesRegex(ValueError, "H.265|4K"),
        ):
            export_video(
                self.frames,
                self.root / "oversize.mp4",
                {
                    "ffmpeg_exe": "ffmpeg-test",
                    "fps": 30,
                    "codec": "h264",
                    "resolution": "original",
                    "hardware_acceleration": "auto",
                },
            )

        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
