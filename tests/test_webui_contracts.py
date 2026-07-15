from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "webui" / "index.html"
JS_PATH = ROOT / "webui" / "app.js"
CSS_PATH = ROOT / "webui" / "styles.css"


class WebUiStaticContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML_PATH.read_text(encoding="utf-8")
        cls.js = JS_PATH.read_text(encoding="utf-8")
        cls.css = CSS_PATH.read_text(encoding="utf-8")

    def test_required_workbench_controls_have_stable_ids(self):
        required_ids = {
            "source-path", "pick-source-btn", "scan-btn", "segment-list",
            "segment-preview", "brightness-chart", "recipe-select",
            "recipe-strength", "advanced-settings", "bad-frame-btn",
            "frame-strip", "split-btn", "merge-btn", "move-up-btn",
            "move-down-btn", "process-btn", "retry-btn", "cancel-btn",
            "task-progress", "task-log", "export-btn", "archive-btn",
            "history-list", "settings-form", "save-settings-btn",
            "settings-save-status",
        }
        present = set(re.findall(r'\bid="([^"]+)"', self.html))
        self.assertEqual(set(), required_ids - present)

    def test_three_named_views_and_accessible_controls_exist(self):
        for label in ("工作台", "历史", "设置"):
            self.assertIn(f">{label}</button>", self.html)
        self.assertIn('aria-label="分段列表"', self.html)
        self.assertIn('aria-label="分段缩略图带"', self.html)
        self.assertIn('aria-label="任务状态栏"', self.html)
        self.assertIn("外部源照片始终保留", self.html)

    def test_tabs_and_progress_expose_complete_aria_state(self):
        self.assertIn('role="tablist"', self.html)
        self.assertEqual(3, len(re.findall(r'role="tab"', self.html)))
        self.assertEqual(3, len(re.findall(r'role="tabpanel"', self.html)))
        self.assertIn('tabindex="-1"', self.html)
        for attribute in ('role="progressbar"', 'aria-valuemin="0"',
                          'aria-valuemax="100"', 'aria-valuenow="0"'):
            self.assertIn(attribute, self.html)
        self.assertIn('button.tabIndex = active ? 0 : -1', self.js)
        self.assertIn('handleTabKeydown', self.js)

    def test_no_inline_event_handlers_or_external_build_assets(self):
        self.assertIsNone(re.search(r"\son[a-z]+\s*=", self.html, re.IGNORECASE))
        self.assertNotIn("node_modules", self.html)
        self.assertNotIn("https://", self.html)
        self.assertIn('src="/app.js"', self.html)
        self.assertIn('href="/styles.css"', self.html)

    def test_javascript_references_every_api_contract(self):
        routes = (
            "/api/state", "/api/pick-directory", "/api/project/scan",
            "/api/project", "/api/segments/split", "/api/segments/merge",
            "/api/segments/", "/api/segments/reorder", "/api/process",
            "/api/process/retry", "/api/tasks/cancel", "/api/tasks/current",
            "/api/export", "/api/archive", "/api/history", "/api/settings",
        )
        for route in routes:
            with self.subTest(route=route):
                self.assertIn(route, self.js)

    def test_frontend_polls_tasks_and_pages_thumbnails(self):
        self.assertRegex(self.js, r"setInterval\(pollTask,\s*1000\)")
        self.assertIn("PAGE_SIZE", self.js)
        self.assertIn("thumbnailPage", self.js)
        self.assertIn("API.historyItem(timestamp)", self.js)
        self.assertIn("showModal()", self.js)

    def test_recipe_is_flushed_before_processing_and_export(self):
        self.assertIn("async function flushRecipeSave()", self.js)
        for function_name in ("processSegments", "exportVideo"):
            match = re.search(
                rf"async function {function_name}\([^)]*\) \{{(.*?)\n\}}",
                self.js,
                re.DOTALL,
            )
            self.assertIsNotNone(match)
            body = match.group(1)
            self.assertLess(body.index("await flushRecipeSave()"),
                            body.index("await startOperation("))

    def test_rejected_frames_use_stable_source_identifiers(self):
        self.assertIn("function frameStableId(frame, index)", self.js)
        self.assertIn("segment?.source_files?.[index]", self.js)
        self.assertIn("rejected.add(stableId)", self.js)
        self.assertIn("{ rejected_frames: [...rejected]", self.js)
        self.assertNotIn("rejected.add(index)", self.js)
        self.assertNotIn(".map(Number));\n  state.selectedFrames", self.js)

    def test_history_has_client_sort_and_recipe_summary(self):
        self.assertIn("historySortValue(right) - historySortValue(left)", self.js)
        self.assertIn("entry.timestamp || entry.created_at || entry.archived_at", self.js)
        self.assertIn("function recipeSummary(entry)", self.js)
        self.assertIn('recipes.textContent = `配方：${recipeSummary(entry)}`', self.js)

    def test_history_detail_preserves_summary_media_urls(self):
        self.assertIn("async function loadHistoryDetail(summary)", self.js)
        self.assertIn("function normaliseHistoryMedia(summary, manifest)", self.js)
        self.assertIn("summary.previews || summary.preview_videos", self.js)
        self.assertIn("manifest.previews || manifest.preview_videos", self.js)
        self.assertIn("summary.outputs || summary.final_videos", self.js)
        self.assertIn("manifest.outputs || manifest.final_videos", self.js)
        self.assertIn("mergeMediaItems", self.js)

    def test_history_jpeg_count_prefers_segment_manifest_counts(self):
        match = re.search(
            r"function historyJpegCount\(entry\) \{(.*?)\n\}",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        body = match.group(1)
        self.assertIn("segment.jpeg_count", body)
        self.assertIn("segmentCounts.reduce", body)
        self.assertIn("entry.jpeg_count ?? entry.frame_count ?? 0", body)
        self.assertIn("historyJpegCount(entry)", self.js)

    def test_settings_paths_are_read_only_picker_controls(self):
        for purpose in ("workspace", "output", "archive"):
            self.assertRegex(
                self.html,
                rf'id="settings-{purpose}-dir"[^>]*readonly',
            )
            self.assertIn(f'data-settings-directory="{purpose}"', self.html)

    def test_restart_required_settings_response_has_explicit_notice(self):
        self.assertIn('id="settings-save-status"', self.html)
        self.assertIn('role="status"', self.html)
        self.assertIn("payload.restart_required", self.js)
        self.assertIn('"已保存，重启程序后生效"', self.js)

    def test_layout_contract_is_desktop_first_and_responsive(self):
        self.assertIn("grid-template-columns: minmax(270px, 330px)", self.css)
        self.assertIn("position: fixed", self.css)
        self.assertIn("@media (max-width: 767px)", self.css)
        self.assertIn("prefers-color-scheme: dark", self.css)
        self.assertIn("overflow-wrap: anywhere", self.css)
        self.assertRegex(self.css, r"body \{[^}]*overflow-x: hidden")


if __name__ == "__main__":
    unittest.main()
