import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image

from tests.fixtures.make_sequence import create_sequence
from webui.server import create_app


class EndToEndWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.output = self.root / "output"
        self.archive = self.root / "archive"
        self.sequence = create_sequence(self.root / "source")
        self.source_hashes = self._hashes(self.sequence.frames)
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

    def _hashes(self, paths):
        return {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths
        }

    def _assert_sources_unchanged(self):
        self.assertEqual(self._hashes(self.sequence.frames), self.source_hashes)

    def _wait_for_task(self, timeout=45):
        deadline = time.monotonic() + timeout
        task = None
        while time.monotonic() < deadline:
            task = self.client.get("/api/tasks/current").get_json()["task"]
            if task["status"] not in {"pending", "queued", "running", "cancelling"}:
                if task["status"] == "completed":
                    return task
                self.fail(f"background task failed: {task}")
            time.sleep(0.02)
        self.fail(f"background task timed out: {task}")

    def _post_task(self, path, payload):
        response = self.client.post(path, json=payload)
        self.assertEqual(response.status_code, 202, response.get_data(as_text=True))
        return self._wait_for_task()

    def test_fixture_sequence_is_stable_and_scan_segmentable(self):
        self.assertEqual(len(self.sequence.frames), 24)
        self.assertEqual(
            [path.name for path in self.sequence.frames],
            [f"frame_{index:03d}.jpg" for index in range(24)],
        )
        self.assertEqual([len(group) for group in self.sequence.groups], [12, 12])
        self.assertGreater(
            self.sequence.groups[1][0].stat().st_mtime - self.sequence.groups[0][-1].stat().st_mtime,
            120,
        )
        self.assertLess(
            self.sequence.brightness[self.sequence.dark_frame.name],
            self.sequence.brightness[self.sequence.frames[0].name],
        )
        self.assertNotEqual(self.sequence.dark_frame, self.sequence.reject_candidate)
        for frame in self.sequence.frames:
            with Image.open(frame) as image:
                self.assertEqual(image.size, (320, 180))
                self.assertEqual(dict(image.getexif()), {})

    def test_real_api_workflow_preserves_sources_and_archives_outputs(self):
        self._post_task("/api/project/scan", {"source_dir": str(self.sequence.source_dir)})
        self._assert_sources_unchanged()

        project = self.client.get("/api/state").get_json()["project"]
        self.assertEqual([len(segment["frames"]) for segment in project["segments"]], [12, 12])

        expected_results = {}
        segment_ids = []
        for index, segment in enumerate(project["segments"], start=1):
            payload = {
                "name": f"E2E Segment {index}",
                "recipe": {"name": "natural", "deflicker": {"enabled": True, "window": 3}},
            }
            if index == 1:
                payload["rejected_frames"] = [str(self.sequence.reject_candidate)]
                expected_results[segment["id"]] = 11
            else:
                expected_results[segment["id"]] = 12
            response = self.client.patch(f"/api/segments/{segment['id']}", json=payload)
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            segment_ids.append(segment["id"])
        self._assert_sources_unchanged()

        self._post_task("/api/process", {"segment_ids": segment_ids, "from_stage": "analyze"})
        self._assert_sources_unchanged()

        project = self.client.get("/api/state").get_json()["project"]
        for segment in project["segments"]:
            self.assertEqual(segment["render_status"], "completed")
            result_dir = self.workspace / "current" / "segments" / segment["id"] / "result"
            self.assertEqual(len(list(result_dir.glob("*.jpg"))), expected_results[segment["id"]])

        self._post_task("/api/export", {
            "segment_ids": segment_ids,
            "fps": 24,
            "resolution": "original",
            "codec": "h264",
            "crf": 28,
        })
        self._assert_sources_unchanged()

        outputs = sorted(self.output.glob("*.mp4"))
        self.assertEqual(len(outputs), 2)
        self.assertTrue(all(path.stat().st_size > 0 for path in outputs))

        archive_task = self._post_task("/api/archive", {
            "confirm_workspace_clear": True,
            "preserve_source": True,
        })
        self._assert_sources_unchanged()

        timestamp = archive_task["result"]["timestamp"]
        archive_root = self.archive / timestamp
        manifest = json.loads((archive_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_file_count"], 24)
        self.assertEqual(manifest["segment_count"], 2)
        self.assertEqual(sum(item["jpeg_count"] for item in manifest["segments"]), 23)
        self.assertEqual(len(manifest["media"]["outputs"]), 2)
        self.assertTrue(all((archive_root / path).is_file() for path in manifest["media"]["outputs"]))
        self.assertTrue(all((archive_root / path).stat().st_size > 0 for path in manifest["media"]["outputs"]))
        self.assertEqual(len(list(archive_root.rglob("*.jpg"))), 23)
        current = self.workspace / "current"
        self.assertTrue(not current.exists() or not any(current.iterdir()))

        history = self.client.get("/api/history").get_json()["history"]
        self.assertEqual([entry["timestamp"] for entry in history], [timestamp])
        self.assertEqual(
            self.client.get(f"/api/history/{timestamp}").get_json()["manifest"]["segment_count"],
            2,
        )
        self._assert_sources_unchanged()
