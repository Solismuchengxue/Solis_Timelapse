import json
import os
import tempfile
import subprocess
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from PIL import Image

from webui.server import _recipe_for_pipeline, create_app
from src.runtime_env import RuntimeEnvironment


class WebUiApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.root = Path(self.temp.name)
        self.app = create_app({
            "TESTING": True,
            "workspace_dir": str(self.root / "workspace"),
            "output_dir": str(self.root / "output"),
            "archive_dir": str(self.root / "archive"),
            "local_config_path": str(self.root / "local.yaml"),
        })
        self.client = self.app.test_client()

    def tearDown(self):
        self.app.extensions["timelapse_tasks"].shutdown()
        self.temp.cleanup()

    def _wait_for_task(self, status, timeout=10):
        deadline = time.monotonic() + timeout
        task = None
        while time.monotonic() < deadline:
            task = self.client.get("/api/tasks/current").get_json()["task"]
            if task["status"] == status:
                return task
            time.sleep(0.01)
        self.fail(f"task did not reach {status}: {task}")

    def _scan_source(self, count=3):
        source = self.root / "source"
        source.mkdir()
        for index in range(count):
            Image.new("RGB", (12, 8), (20 * index, 80, 120)).save(source / f"frame_{index:03d}.jpg")
        response = self.client.post("/api/project/scan", json={"source_dir": str(source)})
        self.assertEqual(response.status_code, 202)
        self._wait_for_task("completed")
        return self.client.get("/api/state").get_json()["project"]

    def _mark_archive_ready(self, project):
        for segment in project["segments"]:
            result_dir = self.root / "workspace" / "current" / "segments" / segment["id"] / "result"
            result_dir.mkdir(parents=True, exist_ok=True)
            (result_dir / "frame.jpg").write_bytes(b"jpeg")
        self.app.extensions["timelapse_store"].update(
            lambda state: {
                **state,
                "segments": [{**segment, "render_status": "completed"} for segment in state["segments"]],
            }
        )

        def fake_export(_frames, output, _options, _progress, cancelled=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"mp4")
            return output

        with patch("webui.server.video_export.export_video", side_effect=fake_export):
            response = self.client.post(
                "/api/export",
                json={"segment_ids": [segment["id"] for segment in project["segments"]]},
            )
            self.assertEqual(response.status_code, 202)
            self._wait_for_task("completed")
        return self.client.get("/api/state").get_json()["project"]

    @staticmethod
    def _archive_body(segment_ids):
        return {
            "confirm_archive": True,
            "preserve_source": True,
            "segment_ids": list(segment_ids),
        }

    def test_empty_state_has_no_project_and_idle_task(self):
        response = self.client.get("/api/state")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertIsNone(body["project"])
        self.assertEqual(body["task"]["status"], "idle")
        self.assertEqual(
            self.app.extensions["timelapse_tasks"]._state_path,
            self.root / "workspace" / "task.json",
        )

    def test_local_ui_preference_module_is_served(self):
        response = self.client.get("/ui_prefs.js")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"SolisUI", response.data)
        response.close()

    def test_frame_exif_route_reads_registered_source_without_exposing_path(self):
        project = self._scan_source(1)
        segment = project["segments"][0]
        source = Path(segment["frames"][0]["path"])
        entries = [{"group": "Image", "tag": "Model", "value": "ZV-E10"}]

        with patch("webui.server.media_catalog.read_exif_details", return_value=entries) as reader:
            response = self.client.get(f"/api/segments/{segment['id']}/frames/0/exif")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["entries"], entries)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["frame"], {"index": 0, "name": source.name})
        self.assertNotIn("path", json.dumps(body).casefold())
        reader.assert_called_once_with(source.resolve())

    def test_hdr_merge_uses_registered_frames_and_records_result(self):
        project = self._scan_source(3)
        segment = project["segments"][0]

        def fake_merge(paths, output, preview, options, exposure_times=None, **_kwargs):
            self.assertEqual(paths, [Path(segment["frames"][0]["path"]), Path(segment["frames"][2]["path"])])
            self.assertEqual(options["mode"], "fusion")
            self.assertEqual(len(exposure_times), 2)
            output.parent.mkdir(parents=True, exist_ok=True)
            preview.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"hdr-jpeg")
            preview.write_bytes(b"preview-jpeg")
            return {"mode": "fusion", "frame_count": 2, "width": 12, "height": 8}

        with patch("webui.server.hdr_merge.merge_exposures", side_effect=fake_merge):
            response = self.client.post("/api/hdr", json={
                "segment_id": segment["id"],
                "frame_indices": [0, 2],
                "mode": "fusion",
                "output_format": "jpeg",
            })
            self.assertEqual(response.status_code, 202)
            task = self._wait_for_task("completed")

        self.assertEqual(task["kind"], "hdr")
        result = task["result"]
        self.assertEqual(result["frame_indices"], [0, 2])
        self.assertTrue(result["output_name"].endswith(".jpg"))
        self.assertNotIn(".mp4", result["output_name"])
        self.assertTrue(result["preview_url"].startswith("/media/current/hdr/"))
        saved = self.client.get("/api/state").get_json()["project"]
        self.assertEqual(saved["hdr_results"][-1]["id"], result["id"])

    def test_hdr_merge_rejects_invalid_frame_selection(self):
        project = self._scan_source(3)
        segment = project["segments"][0]

        too_few = self.client.post("/api/hdr", json={
            "segment_id": segment["id"], "frame_indices": [0]
        })
        outside = self.client.post("/api/hdr", json={
            "segment_id": segment["id"], "frame_indices": [0, 99]
        })

        self.assertEqual(too_few.status_code, 400)
        self.assertEqual(too_few.get_json()["code"], "invalid_hdr")
        self.assertEqual(outside.status_code, 400)
        self.assertEqual(outside.get_json()["code"], "invalid_hdr")

    def test_local_capabilities_keep_native_picker(self):
        response = self.client.get("/api/capabilities")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "mode": "local",
            "native_directory_picker": True,
            "directory_browser": False,
        })

    def test_container_health_capabilities_and_directory_browser_are_confined(self):
        input_root = self.root / "media-input"
        (input_root / "trip" / "day1").mkdir(parents=True)
        (input_root / "trip" / "frame.jpg").write_bytes(b"jpeg")
        outside_link_target = self.root / "outside-link-target"
        outside_link_target.mkdir()
        symlink_created = False
        try:
            (input_root / "escape").symlink_to(outside_link_target, target_is_directory=True)
            symlink_created = True
        except OSError:
            pass
        for name in ("container-workspace", "container-output", "container-archive", "container-config"):
            (self.root / name).mkdir()
        runtime = RuntimeEnvironment(
            mode="container",
            input_root=input_root,
            workspace_dir=self.root / "container-workspace",
            output_dir=self.root / "container-output",
            archive_dir=self.root / "container-archive",
            local_config_path=self.root / "container-config" / "local.yaml",
            host="0.0.0.0",
            native_picker=False,
        )
        app = create_app({"TESTING": True, "runtime_environment": runtime})
        client = app.test_client()
        try:
            self.assertEqual(client.get("/api/health").get_json(), {"status": "ok"})
            self.assertEqual(client.get("/api/capabilities").get_json(), {
                "mode": "container",
                "native_directory_picker": False,
                "directory_browser": True,
            })
            listing = client.get("/api/directories", query_string={"path": "trip"})
            self.assertEqual(listing.status_code, 200)
            self.assertEqual(listing.get_json(), {
                "path": "trip",
                "parent": "",
                "directories": [{"name": "day1", "path": "trip/day1"}],
            })
            picker = client.post("/api/pick-directory")
            self.assertEqual(picker.status_code, 409)
            self.assertEqual(picker.get_json()["code"], "native_picker_unavailable")
            for value in ("../", "/etc", r"C:\Users", r"\\server\share"):
                response = client.get("/api/directories", query_string={"path": value})
                self.assertEqual(response.status_code, 400, value)
                self.assertEqual(response.get_json()["code"], "invalid_media_path")
            if symlink_created:
                response = client.get("/api/directories", query_string={"path": "escape"})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["code"], "invalid_media_path")
        finally:
            app.extensions["timelapse_tasks"].shutdown()

    def test_container_scan_rejects_source_outside_input_mount(self):
        input_root = self.root / "media-input-restricted"
        input_root.mkdir()
        outside = self.root / "outside-input"
        outside.mkdir()
        for name in ("restricted-workspace", "restricted-output", "restricted-archive", "restricted-config"):
            (self.root / name).mkdir()
        runtime = RuntimeEnvironment(
            mode="container",
            input_root=input_root,
            workspace_dir=self.root / "restricted-workspace",
            output_dir=self.root / "restricted-output",
            archive_dir=self.root / "restricted-archive",
            local_config_path=self.root / "restricted-config" / "local.yaml",
            host="0.0.0.0",
            native_picker=False,
        )
        app = create_app({"TESTING": True, "runtime_environment": runtime})
        try:
            response = app.test_client().post("/api/project/scan", json={"source_dir": str(outside)})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()["code"], "invalid_media_path")
        finally:
            app.extensions["timelapse_tasks"].shutdown()

    def test_configured_runtime_roots_must_not_overlap(self):
        with self.assertRaisesRegex(ValueError, "overlap"):
            create_app({
                "TESTING": True,
                "workspace_dir": str(self.root / "shared"),
                "output_dir": str(self.root / "shared" / "output"),
                "archive_dir": str(self.root / "archive-2"),
                "local_config_path": str(self.root / "unsafe-local.yaml"),
            })

    def test_config_round_trip_only_uses_local_override(self):
        response = self.client.post("/api/config", json={"preview": {"width": 1280}})

        self.assertEqual(response.status_code, 200)
        saved = self.client.get("/api/config").get_json()
        self.assertEqual(saved["preview"]["width"], 1280)
        self.assertTrue((self.root / "local.yaml").exists())

    def test_settings_round_trip_uses_frontend_route(self):
        response = self.client.put(
            "/api/settings",
            json={"preview": {"width": 1280}, "logging": {"level": "DEBUG"}},
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["settings"]["preview"]["width"], 1280)
        self.assertEqual(body["settings"]["logging"]["level"], "DEBUG")
        self.assertFalse(body["restart_required"])
        self.assertEqual(body["effective_roots"]["workspace_dir"], str(self.root / "workspace"))
        self.assertEqual(self.client.get("/api/settings").get_json()["settings"]["preview"]["width"], 1280)

    def test_settings_reject_invalid_log_level(self):
        response = self.client.put(
            "/api/settings", json={"logging": {"level": "VERBOSE"}}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "invalid_log_level")

    def test_color_preset_crud_persists_and_builtin_presets_cannot_be_deleted(self):
        initial = self.client.get("/api/color-presets")
        self.assertEqual(initial.status_code, 200)
        presets = initial.get_json()["presets"]
        self.assertEqual({"natural", "clear", "punchy", "custom"}, {item["id"] for item in presets})
        self.assertTrue(all(item["builtin"] for item in presets))

        created = self.client.post("/api/color-presets", json={
            "name": "雪山冷调", "sat": 1.08, "con": 1.22, "pivot": 116,
        })
        self.assertEqual(created.status_code, 201)
        preset = created.get_json()["preset"]
        self.assertFalse(preset["builtin"])

        updated = self.client.put(f"/api/color-presets/{preset['id']}", json={
            "name": "雪山通透", "sat": 1.12, "con": 1.24, "pivot": 114,
        })
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["preset"]["name"], "雪山通透")

        reloaded = self.client.get("/api/color-presets").get_json()["presets"]
        self.assertIn("雪山通透", {item["name"] for item in reloaded})
        self.assertEqual(self.client.delete(f"/api/color-presets/{preset['id']}").status_code, 200)
        self.assertNotIn(preset["id"], {
            item["id"] for item in self.client.get("/api/color-presets").get_json()["presets"]
        })

        rejected = self.client.delete("/api/color-presets/natural")
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.get_json()["code"], "preset_builtin")

    def test_pipeline_recipe_resolves_saved_color_parameters_and_strength(self):
        settings = self.client.get("/api/settings").get_json()["settings"]
        settings["processing"]["color_presets"]["test"] = {
            "name": "Test", "sat": 1.4, "con": 1.2, "pivot": 120,
        }

        recipe = _recipe_for_pipeline({"name": "test", "strength": 50}, settings)

        self.assertEqual(recipe["grade"]["style"], "none")
        self.assertAlmostEqual(recipe["grade"]["sat"], 1.2)
        self.assertAlmostEqual(recipe["grade"]["con"], 1.1)
        self.assertEqual(recipe["grade"]["pivot"], 120)
        self.assertEqual(recipe["render_workers"], 0)
        self.assertEqual(recipe["render_device"], "auto")

    def test_settings_reject_unknown_render_device(self):
        response = self.client.put(
            "/api/settings", json={"processing": {"render_device": "quantum"}}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "invalid_render_device")

    def test_settings_save_new_safe_roots_for_restart_without_changing_effective_roots(self):
        replacement = self.root / "workspace-next"
        response = self.client.put("/api/settings", json={"workspace_dir": str(replacement)})

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["restart_required"])
        self.assertEqual(body["settings"]["workspace_dir"], str(replacement))
        self.assertEqual(body["effective_roots"]["workspace_dir"], str(self.root / "workspace"))
        current = self.client.get("/api/settings").get_json()
        self.assertEqual(current["effective_roots"]["workspace_dir"], str(self.root / "workspace"))

    def test_settings_reject_overlapping_runtime_roots_without_leaking_paths(self):
        response = self.client.put("/api/settings", json={
            "workspace_dir": str(self.root / "unsafe"),
            "output_dir": str(self.root / "unsafe" / "output"),
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "invalid_runtime_roots")
        self.assertNotIn(str(self.root), response.get_data(as_text=True))

    def test_scan_rejects_source_inside_runtime_root_without_modifying_source(self):
        source = self.root / "workspace" / "source"
        source.mkdir(parents=True)
        photo = source / "frame.jpg"
        Image.new("RGB", (8, 6), "red").save(photo)
        before = photo.read_bytes()

        response = self.client.post("/api/project/scan", json={"source_dir": str(source)})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "unsafe_source_dir")
        self.assertEqual(photo.read_bytes(), before)

    def test_scan_rejects_source_containing_runtime_roots(self):
        photo = self.root / "frame.jpg"
        Image.new("RGB", (8, 6), "red").save(photo)

        response = self.client.post("/api/project/scan", json={"source_dir": str(self.root)})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "unsafe_source_dir")
        self.assertTrue(photo.is_file())

    def test_scan_segment_edits_media_and_process_use_project_modules(self):
        project = self._scan_source()
        segment_id = project["segments"][0]["id"]

        response = self.client.post("/api/segments/split", json={"segment_id": segment_id, "frame_index": 1})
        self.assertEqual(response.status_code, 200)
        project = response.get_json()["project"]
        self.assertEqual(len(project["segments"]), 2)

        reversed_ids = [project["segments"][1]["id"], project["segments"][0]["id"]]
        response = self.client.post("/api/segments/reorder", json={"ordered_ids": reversed_ids})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.get_json()["project"]["segments"]], reversed_ids)
        project = self.client.post("/api/segments/reorder", json={"ordered_ids": list(reversed(reversed_ids))}).get_json()["project"]

        response = self.client.post("/api/segments/merge", json={
            "left_id": project["segments"][0]["id"],
            "right_id": project["segments"][1]["id"],
        })
        self.assertEqual(response.status_code, 200)
        segment = response.get_json()["project"]["segments"][0]

        response = self.client.patch(f"/api/segments/{segment['id']}", json={
            "name": "Edited",
            "rejected_frames": [segment["frames"][1]["path"]],
            "recipe": {"name": "natural", "deflicker": {"enabled": True, "window": 3}},
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["segment"]["name"], "Edited")
        self.assertEqual(response.get_json()["segment"]["rejected_frames"], [segment["frames"][1]["path"]])
        response = self.client.patch(f"/api/segments/{segment['id']}", json={"rejected_frames": [segment["frames"][2]["name"]]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["segment"]["rejected_frames"], [segment["frames"][2]["name"]])

        thumbnails = self.client.get(f"/api/segments/{segment['id']}/thumbnails").get_json()
        self.assertEqual(len(thumbnails["thumbnails"]), 3)
        self.assertTrue(thumbnails["thumbnails"][0]["url"].startswith("/media/current/"))

        response = self.client.post("/api/process", json={"segment_ids": [segment["id"]], "from_stage": "analyze"})
        self.assertEqual(response.status_code, 202)
        self._wait_for_task("completed")
        persisted = json.loads(
            (self.root / "workspace" / "current" / "project.json").read_text(encoding="utf-8")
        )
        self.assertIsNone(persisted["segments"][0]["analysis"])
        response = self.client.post("/api/process/retry", json={"segment_ids": [segment["id"]], "from_stage": "render"})
        self.assertEqual(response.status_code, 202)
        self._wait_for_task("completed")
        chart = self.client.get(f"/api/segments/{segment['id']}/chart").get_json()["chart"]
        self.assertEqual(len(chart["measured_luminance"]), 3)

    def test_process_progress_weights_analysis_render_and_preview(self):
        project = self._scan_source(4)
        segment_id = project["segments"][0]["id"]

        response = self.client.post(
            "/api/process",
            json={"segment_ids": [segment_id], "from_stage": "analyze"},
        )
        self.assertEqual(response.status_code, 202)
        task = self._wait_for_task("completed")

        self.assertEqual(task["completed"], 40)
        self.assertEqual(task["total"], 40)

    def test_invalid_input_and_busy_task_use_stable_statuses(self):
        self.assertEqual(self.client.post("/api/project/scan", json={}).status_code, 400)
        source = self.root / "source"
        source.mkdir()
        release = threading.Event()
        tasks = self.app.extensions["timelapse_tasks"]
        tasks.submit("scan", lambda context: release.wait(1))

        response = self.client.post("/api/project/scan", json={"source_dir": str(source)})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "task_busy")
        self.assertEqual(self.client.post("/api/tasks/cancel").status_code, 200)
        release.set()
        self._wait_for_task("cancelled")

    def test_original_frame_and_exported_video_routes_are_segment_scoped(self):
        project = self._scan_source(1)
        segment = project["segments"][0]
        source_frame = Path(segment["frames"][0]["path"])

        response = self.client.get(
            f"/api/segments/{segment['id']}/frames/0/image"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, source_frame.read_bytes())
        response.close()
        self.assertEqual(
            self.client.get(f"/api/segments/{segment['id']}/frames/1/image").status_code,
            404,
        )

        self._mark_archive_ready(project)
        completed = self.client.get("/api/tasks/current").get_json()["task"]
        self.assertEqual(completed["result"]["output_dir"], str(self.root / "output"))
        response = self.client.get(f"/api/segments/{segment['id']}/video")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"mp4")
        response.close()

    def test_render_preview_video_route_does_not_require_export(self):
        project = self._scan_source(1)
        segment = project["segments"][0]
        work_dir = self.root / "workspace" / "current" / "segments" / segment["id"]
        preview = work_dir / "preview.mp4"
        preview.parent.mkdir(parents=True, exist_ok=True)
        preview.write_bytes(b"preview-mp4")
        self.app.extensions["timelapse_store"].update(
            lambda state: {
                **state,
                "segments": [{
                    **state["segments"][0],
                    "render_status": "completed",
                    "preview_file": str(preview),
                    "export_artifact": None,
                }],
            }
        )

        response = self.client.get(f"/api/segments/{segment['id']}/video")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"preview-mp4")
        response.close()

    def test_segment_video_prefers_browser_compatible_preview_over_export(self):
        project = self._scan_source(1)
        segment = project["segments"][0]
        work_dir = self.root / "workspace" / "current" / "segments" / segment["id"]
        preview = work_dir / "preview.mp4"
        preview.parent.mkdir(parents=True, exist_ok=True)
        preview.write_bytes(b"browser-preview")
        exported = self.root / "output" / "final.mp4"
        exported.parent.mkdir(parents=True, exist_ok=True)
        exported.write_bytes(b"large-or-hevc-export")
        self.app.extensions["timelapse_store"].update(
            lambda state: {
                **state,
                "segments": [{
                    **state["segments"][0],
                    "render_status": "completed",
                    "preview_file": str(preview),
                    "export_artifact": {"path": str(exported)},
                }],
            }
        )

        response = self.client.get(f"/api/segments/{segment['id']}/video")
        content = response.data
        response.close()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(content, b"browser-preview")

    def test_export_archive_and_history_are_async_and_do_not_leak_paths(self):
        project = self._scan_source(1)
        segment = project["segments"][0]
        result_dir = self.root / "workspace" / "current" / "segments" / segment["id"] / "result"
        result_dir.mkdir(parents=True)
        (result_dir / "frame.jpg").write_bytes(b"jpeg")
        self.app.extensions["timelapse_store"].update(
            lambda state: {**state, "segments": [{**state["segments"][0], "render_status": "completed"}]}
        )

        def fake_export(_frames, output, _options, _progress, cancelled=None):
            output.write_bytes(b"mp4")
            return output

        with patch("webui.server.video_export.export_video", side_effect=fake_export):
            response = self.client.post("/api/export", json={"segment_ids": [segment["id"]]})
            self.assertEqual(response.status_code, 202)
            self._wait_for_task("completed")

        with patch("webui.server.archive.archive_project", side_effect=RuntimeError(str(self.root / "secret"))):
            response = self.client.post("/api/archive", json=self._archive_body([segment["id"]]))
            self.assertEqual(response.status_code, 202)
            failed = self._wait_for_task("failed")
            self.assertNotIn(str(self.root), failed["error"])

        response = self.client.post("/api/archive", json=self._archive_body([segment["id"]]))
        self.assertEqual(response.status_code, 202)
        completed = self._wait_for_task("completed")
        self.assertEqual(
            completed["result"]["archive_dir"],
            str(self.root / "archive" / completed["result"]["timestamp"]),
        )
        self.assertTrue((self.root / "workspace" / "task.json").is_file())
        self.assertTrue((self.root / "workspace" / "current" / "project.json").is_file())
        self.assertTrue(result_dir.is_dir())
        history = self.client.get("/api/history").get_json()["history"]
        self.assertEqual(len(history), 1)
        self.assertTrue(self.client.get(f"/api/history/{history[0]['timestamp']}").get_json()["manifest"])

    def test_export_normalizes_legacy_source_resolution(self):
        project = self._scan_source(1)
        segment = project["segments"][0]
        result_dir = self.root / "workspace" / "current" / "segments" / segment["id"] / "result"
        result_dir.mkdir(parents=True)
        (result_dir / "frame.jpg").write_bytes(b"jpeg")
        self.app.extensions["timelapse_store"].update(
            lambda state: {**state, "segments": [{**state["segments"][0], "render_status": "completed"}]}
        )
        captured = {}

        def fake_export(_frames, output, options, _progress, cancelled=None):
            captured.update(options)
            output.write_bytes(b"mp4")
            return output

        with patch("webui.server.video_export.export_video", side_effect=fake_export):
            response = self.client.post(
                "/api/export",
                json={"segment_ids": [segment["id"]], "resolution": "source"},
            )
            self.assertEqual(response.status_code, 202)
            self._wait_for_task("completed")

        self.assertEqual(captured["resolution"], "original")

    def test_export_rejects_oversize_original_h264_before_starting_task(self):
        project = self._scan_source(1)
        segment = project["segments"][0]
        result_dir = self.root / "workspace" / "current" / "segments" / segment["id"] / "result"
        result_dir.mkdir(parents=True)
        Image.new("RGB", (12, 8), "navy").save(result_dir / "frame.jpg")
        self.app.extensions["timelapse_store"].update(
            lambda state: {
                **state,
                "segments": [{**state["segments"][0], "render_status": "completed"}],
            }
        )

        with (
            patch("webui.server.video_export._nvenc_available", return_value=True),
            patch("webui.server.video_export._image_dimensions", return_value=(6024, 4024)),
        ):
            response = self.client.post(
                "/api/export",
                json={
                    "segment_ids": [segment["id"]],
                    "resolution": "original",
                    "codec": "h264",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "h264_nvenc_dimension_limit")
        self.assertIn("6024x4024", response.get_json()["error"])
        self.assertNotEqual(
            self.client.get("/api/tasks/current").get_json()["task"]["kind"],
            "export",
        )

    def test_export_task_reports_actual_encoded_frame_progress(self):
        project = self._scan_source(3)
        segment = project["segments"][0]
        result_dir = self.root / "workspace" / "current" / "segments" / segment["id"] / "result"
        result_dir.mkdir(parents=True)
        for index in range(3):
            (result_dir / f"frame-{index}.jpg").write_bytes(f"jpeg-{index}".encode())
        self.app.extensions["timelapse_store"].update(
            lambda state: {
                **state,
                "segments": [{**state["segments"][0], "render_status": "completed"}],
            }
        )

        def fake_export(_frames, output, _options, progress, cancelled=None):
            progress(
                1,
                3,
                file=output.name,
                encoder="h264_nvenc",
                fps=12.5,
                speed="0.5x",
                eta_seconds=2,
            )
            progress(
                3,
                3,
                file=output.name,
                encoder="h264_nvenc",
                fps=18.0,
                speed="0.75x",
                eta_seconds=0,
            )
            output.write_bytes(b"mp4")
            return output

        with patch("webui.server.video_export.export_video", side_effect=fake_export):
            response = self.client.post(
                "/api/export", json={"segment_ids": [segment["id"]]}
            )
            self.assertEqual(response.status_code, 202)
            completed = self._wait_for_task("completed")

        self.assertEqual(completed["completed"], 3)
        self.assertEqual(completed["total"], 3)
        self.assertEqual(completed["detail"]["encoder"], "h264_nvenc")
        self.assertEqual(completed["detail"]["encoded_frames"], 3)
        self.assertEqual(completed["detail"]["eta_seconds"], 0)

    def test_segment_lifecycle_blocks_repeat_export_and_archive_until_rerender(self):
        project = self._scan_source(1)
        segment_id = project["segments"][0]["id"]

        def fake_video_export(_frames, output, _options, progress=None, cancelled=None):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(f"mp4-{output.name}".encode())
            if progress is not None:
                progress(1, 1, file=output.name, encoder="test")
            return output

        with patch("webui.server.video_export.export_video", side_effect=fake_video_export):
            rendered = self.client.post(
                "/api/process",
                json={"segment_ids": [segment_id], "from_stage": "analyze"},
            )
            self.assertEqual(rendered.status_code, 202)
            self._wait_for_task("completed")

            first_export = self.client.post(
                "/api/export", json={"segment_ids": [segment_id]}
            )
            self.assertEqual(first_export.status_code, 202)
            self._wait_for_task("completed")
            repeated_export = self.client.post(
                "/api/export", json={"segment_ids": [segment_id]}
            )
            self.assertEqual(repeated_export.status_code, 409)
            self.assertEqual(repeated_export.get_json()["code"], "already_exported")

            first_archive = self.client.post(
                "/api/archive", json=self._archive_body([segment_id])
            )
            self.assertEqual(first_archive.status_code, 202)
            first_archive_task = self._wait_for_task("completed")
            first_archive_dir = Path(first_archive_task["result"]["archive_dir"])
            repeated_archive = self.client.post(
                "/api/archive", json=self._archive_body([segment_id])
            )
            self.assertEqual(repeated_archive.status_code, 409)
            self.assertEqual(repeated_archive.get_json()["code"], "already_archived")

            rerendered = self.client.post(
                "/api/process",
                json={"segment_ids": [segment_id], "from_stage": "analyze"},
            )
            self.assertEqual(rerendered.status_code, 202)
            self._wait_for_task("completed")
            segment = self.client.get("/api/state").get_json()["project"]["segments"][0]
            self.assertIsNone(segment.get("export_artifact"))
            self.assertIsNone(segment.get("archive_artifact"))

            second_export = self.client.post(
                "/api/export", json={"segment_ids": [segment_id]}
            )
            self.assertEqual(second_export.status_code, 202)
            self._wait_for_task("completed")
            second_archive = self.client.post(
                "/api/archive", json=self._archive_body([segment_id])
            )
            self.assertEqual(second_archive.status_code, 202)
            second_archive_task = self._wait_for_task("completed")

        second_archive_dir = Path(second_archive_task["result"]["archive_dir"])
        self.assertNotEqual(first_archive_dir, second_archive_dir)
        self.assertTrue(first_archive_dir.is_dir())
        self.assertTrue(second_archive_dir.is_dir())
        segment = self.client.get("/api/state").get_json()["project"]["segments"][0]
        self.assertEqual(segment["archive_artifact"]["timestamp"], second_archive_dir.name)

    def test_archive_history_delete_requires_confirmation_and_supports_delete_all(self):
        archive_root = self.root / "archive"
        for timestamp in ("2026-07-15_120000", "2026-07-15_130000"):
            item = archive_root / timestamp
            item.mkdir(parents=True)
            (item / "manifest.json").write_text(
                json.dumps({"archived_at": timestamp, "segments": []}),
                encoding="utf-8",
            )
        unmanaged = archive_root / "unmanaged"
        unmanaged.mkdir()
        (unmanaged / "keep.txt").write_text("keep", encoding="utf-8")

        denied = self.client.delete("/api/history/2026-07-15_120000", json={})
        self.assertEqual(denied.status_code, 400)
        self.assertTrue((archive_root / "2026-07-15_120000").is_dir())

        deleted = self.client.delete(
            "/api/history/2026-07-15_120000",
            json={"confirm_delete": True},
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse((archive_root / "2026-07-15_120000").exists())
        self.assertTrue((archive_root / "2026-07-15_130000").is_dir())

        deleted_all = self.client.delete("/api/history", json={"confirm_delete": True})
        self.assertEqual(deleted_all.status_code, 200)
        self.assertEqual(deleted_all.get_json()["deleted_count"], 1)
        self.assertEqual(self.client.get("/api/history").get_json()["history"], [])
        self.assertTrue((unmanaged / "keep.txt").is_file())

    def test_deleting_archive_history_unlocks_segment_for_rearchive(self):
        project = self._mark_archive_ready(self._scan_source(1))
        segment_id = project["segments"][0]["id"]

        first = self.client.post(
            "/api/archive", json=self._archive_body([segment_id])
        )
        self.assertEqual(first.status_code, 202)
        first_task = self._wait_for_task("completed")
        first_timestamp = first_task["result"]["timestamp"]

        deleted = self.client.delete(
            f"/api/history/{first_timestamp}",
            json={"confirm_delete": True},
        )

        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.get_json()["unlocked_segment_count"], 1)
        segment = self.client.get("/api/state").get_json()["project"]["segments"][0]
        self.assertIsNone(segment.get("archive_artifact"))
        self.assertIsInstance(segment.get("export_artifact"), dict)
        preview = self.client.get(f"/api/segments/{segment_id}/video")
        self.assertEqual(preview.status_code, 200)
        preview.close()

        second = self.client.post(
            "/api/archive", json=self._archive_body([segment_id])
        )
        self.assertEqual(second.status_code, 202)
        second_task = self._wait_for_task("completed")
        second_timestamp = second_task["result"]["timestamp"]
        self.assertTrue((self.root / "archive" / second_timestamp).is_dir())
        segment = self.client.get("/api/state").get_json()["project"]["segments"][0]
        self.assertEqual(segment["archive_artifact"]["timestamp"], second_timestamp)

    def test_archive_rejects_incomplete_project_without_clearing_workspace(self):
        project = self._scan_source(1)
        project_file = self.root / "workspace" / "current" / "project.json"

        response = self.client.post(
            "/api/archive",
            json=self._archive_body([project["segments"][0]["id"]]),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "archive_incomplete")
        self.assertTrue(project_file.is_file())
        self.assertEqual(self.client.get("/api/state").get_json()["project"]["source_dir"], project["source_dir"])

    def test_running_archive_can_be_cancelled(self):
        project = self._mark_archive_ready(self._scan_source(1))
        started = threading.Event()
        release = threading.Event()

        def blocking_archive(_project, _workspace, _output, archive_dir, **options):
            started.set()
            while not release.wait(0.01):
                options["check_cancelled"]()
            return archive_dir / "2026-07-15_130000"

        with patch("webui.server.archive.archive_project", side_effect=blocking_archive):
            response = self.client.post(
                "/api/archive",
                json=self._archive_body([project["segments"][0]["id"]]),
            )
            self.assertEqual(response.status_code, 202)
            self.assertTrue(started.wait(1))
            cancel = self.client.post("/api/tasks/cancel")
            self.assertEqual(cancel.status_code, 200)
            self.assertEqual(cancel.get_json()["task"]["status"], "cancelling")
            release.set()
            self._wait_for_task("cancelled")
        self.assertEqual(project["segments"][0]["render_status"], "completed")

    def test_server_uses_only_public_task_manager_cancellation_api(self):
        server_source = (Path(__file__).resolve().parents[1] / "webui" / "server.py").read_text(encoding="utf-8")

        self.assertNotIn("._lock", server_source)
        self.assertIn("TaskNotCancellable", server_source)
        self.assertNotIn('submit("archive", work, cancellable_while_running=False)', server_source)
        self.assertIn("check_cancelled=context.raise_if_cancelled", server_source)
        self.assertIn("cancelled=context.cancelled", server_source)

    def test_archive_rejects_partial_result_even_after_export(self):
        project = self._scan_source(3)
        segment = project["segments"][0]
        result_dir = self.root / "workspace" / "current" / "segments" / segment["id"] / "result"
        result_dir.mkdir(parents=True)
        (result_dir / "only-one.jpg").write_bytes(b"jpeg")
        self.app.extensions["timelapse_store"].update(
            lambda state: {**state, "segments": [{**state["segments"][0], "render_status": "completed"}]}
        )

        def fake_export(_frames, output, _options, _progress, cancelled=None):
            output.write_bytes(b"mp4")
            return output

        with patch("webui.server.video_export.export_video", side_effect=fake_export):
            self.assertEqual(self.client.post("/api/export", json={"segment_ids": [segment["id"]]}).status_code, 202)
            self._wait_for_task("completed")

        response = self.client.post("/api/archive", json=self._archive_body([segment["id"]]))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "archive_incomplete")
        self.assertTrue((self.root / "workspace" / "current" / "project.json").is_file())

    def test_archive_rejects_export_created_for_older_result_identity(self):
        project = self._scan_source(1)
        segment = project["segments"][0]
        result_dir = self.root / "workspace" / "current" / "segments" / segment["id"] / "result"
        result_dir.mkdir(parents=True)
        frame = result_dir / "frame.jpg"
        frame.write_bytes(b"first-version")
        self.app.extensions["timelapse_store"].update(
            lambda state: {**state, "segments": [{**state["segments"][0], "render_status": "completed"}]}
        )

        def fake_export(_frames, output, _options, _progress, cancelled=None):
            output.write_bytes(b"mp4")
            return output

        with patch("webui.server.video_export.export_video", side_effect=fake_export):
            self.client.post("/api/export", json={"segment_ids": [segment["id"]]})
            self._wait_for_task("completed")
        frame.write_bytes(b"new-render-version")

        response = self.client.post("/api/archive", json=self._archive_body([segment["id"]]))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "archive_incomplete")

    def test_archive_rejects_changed_jpeg_with_preserved_size_and_mtime(self):
        project = self._mark_archive_ready(self._scan_source(1))
        segment = project["segments"][0]
        frame = self.root / "workspace" / "current" / "segments" / segment["id"] / "result" / "frame.jpg"
        original_stat = frame.stat()

        frame.write_bytes(b"JPE2")
        os.utime(frame, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

        response = self.client.post("/api/archive", json=self._archive_body([segment["id"]]))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "archive_incomplete")

    def test_archive_rejects_replaced_mp4_content(self):
        project = self._mark_archive_ready(self._scan_source(1))
        artifact = Path(project["segments"][0]["export_artifact"]["path"])
        artifact.write_bytes(b"bad")

        response = self.client.post(
            "/api/archive",
            json=self._archive_body([project["segments"][0]["id"]]),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "archive_incomplete")

    def test_export_and_archive_require_explicit_segment_ids(self):
        self._scan_source(1)

        export = self.client.post("/api/export", json={})
        archive_response = self.client.post(
            "/api/archive",
            json={"confirm_archive": True, "preserve_source": True},
        )

        self.assertEqual(export.status_code, 400)
        self.assertEqual(export.get_json()["code"], "invalid_export")
        self.assertEqual(archive_response.status_code, 400)
        self.assertEqual(archive_response.get_json()["code"], "invalid_segment")

    def test_clear_project_removes_current_workspace_and_output_but_preserves_source_and_archive(self):
        project = self._scan_source(1)
        source_frame = Path(project["segments"][0]["frames"][0]["path"])
        output = self.root / "output" / "delete.mp4"
        nested_output = self.root / "output" / "nested" / "delete.jpg"
        archive_file = self.root / "archive" / "keep" / "manifest.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        nested_output.parent.mkdir(parents=True, exist_ok=True)
        archive_file.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"output")
        nested_output.write_bytes(b"preview")
        archive_file.write_text("{}", encoding="utf-8")

        response = self.client.delete("/api/project", json={"confirm": True})

        self.assertEqual(response.status_code, 200)
        cleared_state = self.client.get("/api/state").get_json()
        self.assertIsNone(cleared_state["project"])
        self.assertEqual(cleared_state["task"]["status"], "idle")
        self.assertEqual(cleared_state["task"]["completed"], 0)
        self.assertEqual(cleared_state["task"]["total"], 0)
        self.assertEqual(cleared_state["task"]["detail"], {})
        self.assertTrue(source_frame.is_file())
        self.assertFalse((self.root / "workspace" / "current").exists())
        self.assertFalse(output.exists())
        self.assertFalse(nested_output.exists())
        self.assertTrue((self.root / "output").is_dir())
        self.assertEqual(archive_file.read_text(encoding="utf-8"), "{}")
        self.assertEqual(response.get_json()["cleared"]["output_dir"], str(self.root / "output"))

    def test_same_name_segments_export_to_distinct_artifacts(self):
        project = self._scan_source(2)
        original_id = project["segments"][0]["id"]
        project = self.client.post(
            "/api/segments/split",
            json={"segment_id": original_id, "frame_index": 1},
        ).get_json()["project"]
        for segment in project["segments"]:
            response = self.client.patch(f"/api/segments/{segment['id']}", json={"name": "Same Name"})
            self.assertEqual(response.status_code, 200)
            result_dir = self.root / "workspace" / "current" / "segments" / segment["id"] / "result"
            result_dir.mkdir(parents=True)
            (result_dir / "frame.jpg").write_bytes(segment["id"].encode("ascii"))
        self.app.extensions["timelapse_store"].update(
            lambda state: {
                **state,
                "segments": [{**segment, "render_status": "completed"} for segment in state["segments"]],
            }
        )

        def fake_export(_frames, output, _options, _progress, cancelled=None):
            output.write_bytes(b"mp4")
            return output

        ids = [segment["id"] for segment in project["segments"]]
        with patch("webui.server.video_export.export_video", side_effect=fake_export):
            self.assertEqual(self.client.post("/api/export", json={"segment_ids": ids}).status_code, 202)
            self._wait_for_task("completed")

        saved = self.client.get("/api/state").get_json()["project"]["segments"]
        artifacts = [segment["export_artifact"] for segment in saved]
        self.assertEqual(len({artifact["path"].casefold() for artifact in artifacts}), 2)
        self.assertTrue(all(Path(artifact["path"]).is_file() for artifact in artifacts))
        self.assertTrue(all(artifact["frame_count"] == 1 for artifact in artifacts))
        self.assertTrue(all(artifact["result_signature"] for artifact in artifacts))

    def test_split_segments_generate_their_own_thumbnail_pages(self):
        project = self._scan_source(4)
        original_id = project["segments"][0]["id"]

        response = self.client.post(
            "/api/segments/split",
            json={"segment_id": original_id, "frame_index": 2},
        )

        self.assertEqual(response.status_code, 200)
        segments = response.get_json()["project"]["segments"]
        self.assertEqual(len(segments), 2)
        for segment in segments:
            payload = self.client.get(
                f"/api/segments/{segment['id']}/thumbnails?offset=0&limit=24"
            ).get_json()
            self.assertEqual(payload["total"], 2)
            self.assertTrue(all(frame["url"] for frame in payload["thumbnails"]))

    def test_thumbnail_route_returns_entire_segment_without_paging(self):
        project = self._scan_source(1)
        segment = project["segments"][0]
        frame = segment["frames"][0]
        frame_count = 205
        self.app.extensions["timelapse_store"].update(
            lambda state: {
                **state,
                "segments": [
                    {
                        **state["segments"][0],
                        "frames": [dict(frame) for _ in range(frame_count)],
                        "source_files": [frame["path"] for _ in range(frame_count)],
                    }
                ],
            }
        )

        with patch("webui.server.image_pipeline.write_thumbnail"):
            response = self.client.get(f"/api/segments/{segment['id']}/thumbnails")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["total"], frame_count)
        self.assertEqual(len(payload["thumbnails"]), frame_count)

    def test_history_rejects_windows_and_parent_path_forms(self):
        for timestamp in (
            "..",
            "C:relative",
            r"C:\absolute",
            r"\\server\share",
        ):
            with self.subTest(timestamp=timestamp):
                response = self.client.get("/api/history/" + quote(timestamp, safe=""))
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(str(self.root), response.get_data(as_text=True))

    def test_history_rejects_archive_symlink_escape(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "manifest.json").write_text('{"segment_count": 99}', encoding="utf-8")
        archive_root = self.root / "archive"
        archive_root.mkdir(exist_ok=True)
        link = archive_root / "escape"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            junction = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                capture_output=True,
                text=True,
            )
            if junction.returncode != 0:
                self.fail("test setup could not create a directory symlink or junction")

        response = self.client.get("/api/history/escape")

        self.assertEqual(response.status_code, 404)

    def test_unknown_api_returns_stable_error_envelope(self):
        response = self.client.get("/api/not-a-route")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["code"], "not_found")
        self.assertIn("error", response.get_json())

    def test_task_log_history_can_be_read_and_cleared(self):
        project = self._scan_source(1)
        self.assertTrue(project["segments"])

        response = self.client.get("/api/logs")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["logs"])

        response = self.client.delete("/api/logs")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/logs").get_json()["logs"], [])

    def test_debug_logs_include_scan_progress_and_summary(self):
        self.client.put("/api/settings", json={"logging": {"level": "DEBUG"}})
        self._scan_source(2)

        logs = self.client.get("/api/logs").get_json()["logs"]
        messages = [entry["message"] for entry in logs]
        self.assertTrue(any(message.startswith("扫描开始：目录=") for message in messages))
        self.assertIn("素材读取完成：共 2 帧 · 拍摄时长 0.0 秒", messages)
        self.assertTrue(any(message.startswith("自动分段完成：") for message in messages))
        self.assertTrue(any(entry["level"] == "DEBUG" and entry["message"].startswith("进度 ") for entry in logs))

    def test_clear_project_records_deleted_output_and_preserved_archive(self):
        self._scan_source(1)
        output = self.root / "output" / "delete.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"output")

        response = self.client.delete("/api/project", json={"confirm": True})

        self.assertEqual(response.status_code, 200)
        messages = [
            entry["message"]
            for entry in self.client.get("/api/logs").get_json()["logs"]
        ]
        self.assertTrue(any("已清除当前项目" in message for message in messages))
        self.assertTrue(any("输出目录已清空" in message for message in messages))
        self.assertTrue(any("源照片和归档目录未删除" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
