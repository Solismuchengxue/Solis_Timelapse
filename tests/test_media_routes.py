import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from webui.server import create_app


class MediaRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.archive = self.root / "archive"
        self.output = self.root / "output"
        preview = self.workspace / "current" / "previews"
        preview.mkdir(parents=True)
        self.archive.mkdir()
        self.output.mkdir()
        (preview / "frame.jpg").write_bytes(b"safe-image")
        (self.workspace / "current" / "project.json").write_text("{}", encoding="utf-8")
        (self.workspace / "current" / "segments").mkdir()
        (self.workspace / "current" / "segments" / "source.jpg").write_bytes(b"source-image")
        (self.archive / "2026-07-15_120000").mkdir()
        (self.archive / "2026-07-15_120000" / "preview.mp4").write_bytes(b"safe-video")
        (self.archive / "2026-07-15_120000" / "representative.jpg").write_bytes(b"representative")
        archived_segment = self.archive / "2026-07-15_120000" / "Segment 01"
        archived_segment.mkdir()
        (archived_segment / "frame_000001.jpg").write_bytes(b"full-result-frame")
        (archived_segment / "preview-disguise.jpg").write_bytes(b"full-result-frame")
        (self.archive / "2026-07-15_120000" / "undeclared_preview.jpg").write_bytes(b"not-declared")
        manifest = {
            "segments": [{"archive_name": "Segment 01"}],
            "media": {
                "previews": ["preview.mp4"],
                "outputs": [],
                "representatives": ["representative.jpg"],
            },
        }
        (self.archive / "2026-07-15_120000" / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (self.root / "secret.txt").write_bytes(b"secret")
        self.app = create_app({
            "TESTING": True,
            "workspace_dir": str(self.workspace),
            "output_dir": str(self.output),
            "archive_dir": str(self.archive),
            "local_config_path": str(self.root / "local.yaml"),
        })
        self.client = self.app.test_client()

    def tearDown(self):
        self.app.extensions["timelapse_tasks"].shutdown()
        self.temp.cleanup()

    def test_valid_current_media_is_served(self):
        with self.client.get("/media/current/previews/frame.jpg") as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"safe-image")

    def test_parent_traversal_is_rejected(self):
        for path in (
            "/media/current/../../secret.txt",
            "/media/current/" + quote("../../secret.txt", safe=""),
            "/media/current/C:/Windows/win.ini",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_only_media_files_under_allowed_roots_are_served(self):
        for path, expected in (
            ("/media/archive/2026-07-15_120000/preview.mp4", 200),
            ("/media/archive/2026-07-15_120000/representative.jpg", 200),
            ("/media/archive/2026-07-15_120000/Segment%2001/frame_000001.jpg", 404),
            ("/media/archive/2026-07-15_120000/Segment%2001/preview-disguise.jpg", 404),
            ("/media/archive/2026-07-15_120000/undeclared_preview.jpg", 404),
            ("/media/current/project.json", 404),
            ("/media/current/segments/source.jpg", 404),
            ("/media/archive/2026-07-15_120000/manifest.json", 404),
        ):
            with self.subTest(path=path), self.client.get(path) as response:
                self.assertEqual(response.status_code, expected)


if __name__ == "__main__":
    unittest.main()
