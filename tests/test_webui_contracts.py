from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "webui" / "index.html"
JS_PATH = ROOT / "webui" / "app.js"
CSS_PATH = ROOT / "webui" / "styles.css"
PREFS_PATH = ROOT / "webui" / "ui_prefs.js"
SERVER_PATH = ROOT / "webui" / "server.py"
RUN_PATH = ROOT / "run.bat"
README_PATH = ROOT / "README.md"
GITIGNORE_PATH = ROOT / ".gitignore"


class WebUiStaticContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML_PATH.read_text(encoding="utf-8")
        cls.js = JS_PATH.read_text(encoding="utf-8")
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        cls.server = SERVER_PATH.read_text(encoding="utf-8")
        cls.run_bat = RUN_PATH.read_text(encoding="utf-8")

    def test_theme_i18n_assets_and_studio_regions_exist(self):
        self.assertTrue(PREFS_PATH.is_file())
        for required_id in (
            "theme-choice", "language-choice", "sidebar-nav",
            "studio-main", "task-panel", "directory-browser-dialog",
            "directory-browser-breadcrumb", "directory-browser-list",
            "directory-browser-choose",
        ):
            self.assertIn(f'id="{required_id}"', self.html)
        self.assertIn('data-theme="system"', self.html)
        self.assertIn('src="/ui_prefs.js"', self.html)
        self.assertLess(self.html.index('/ui_prefs.js'), self.html.index('/app.js'))
        self.assertNotIn('id="open-settings-btn"', self.html)
        self.assertNotIn('id="theme-select"', self.html)
        self.assertNotIn('id="language-select"', self.html)
        self.assertEqual(3, self.html.count('data-theme-choice='))
        self.assertEqual(2, self.html.count('data-language-choice='))
        self.assertIn('role="radiogroup"', self.html)

    def test_required_workbench_controls_have_stable_ids(self):
        required_ids = {
            "source-path", "pick-source-btn", "scan-btn", "segment-list",
            "segment-preview", "brightness-chart", "recipe-select",
            "recipe-strength", "advanced-settings", "bad-frame-btn",
            "frame-strip", "frame-multi-select-btn", "split-btn", "merge-btn",
            "segment-multi-select-btn", "move-up-btn", "move-down-btn",
            "process-current-btn", "cancel-btn", "output-flyout",
            "task-progress", "task-log", "export-btn", "archive-btn",
            "history-list", "clear-logs-btn", "settings-form", "save-settings-btn",
            "color-preset-list", "color-preset-form", "new-color-preset-btn",
            "save-color-preset-btn", "delete-color-preset-btn", "preview-histogram",
            "settings-save-status", "operation-result-dialog",
            "operation-result-title", "operation-result-message", "result-history-btn",
            "preview-video-btn", "export-progress-dialog", "export-progress",
            "export-progress-cancel-btn", "export-progress-close-btn",
        }
        present = set(re.findall(r'\bid="([^"]+)"', self.html))
        self.assertEqual(set(), required_ids - present)

    def test_four_named_views_and_accessible_controls_exist(self):
        for label in ("工作台", "处理历史与日志", "色彩配方", "设置"):
            self.assertIn(f">{label}</button>", self.html)
        self.assertNotIn('data-view="logs"', self.html)
        self.assertIn('aria-label="分段列表"', self.html)
        self.assertIn('aria-label="分段缩略图带"', self.html)
        self.assertIn('aria-label="当前分段任务"', self.html)
        self.assertIn("外部源照片始终保留", self.html)

    def test_tabs_and_progress_expose_complete_aria_state(self):
        self.assertIn('role="tablist"', self.html)
        self.assertEqual(4, len(re.findall(r'role="tab"', self.html)))
        self.assertEqual(4, len(re.findall(r'role="tabpanel"', self.html)))
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
            "/api/logs", "/api/export", "/api/archive", "/api/history", "/api/settings",
            "/frames/", "/video",
        )
        for route in routes:
            with self.subTest(route=route):
                self.assertIn(route, self.js)

    def test_frontend_polls_tasks_and_pages_thumbnails(self):
        self.assertRegex(self.js, r"setInterval\(pollTask,\s*1000\)")
        self.assertIn("const PAGE_SIZE = 20", self.js)
        self.assertIn("thumbnailPage", self.js)
        self.assertIn("API.historyItem(timestamp)", self.js)
        self.assertIn("showModal()", self.js)

    def test_current_segment_and_original_media_drive_workbench_actions(self):
        self.assertIn("function currentSegmentIdsForAction()", self.js)
        self.assertIn("function hasSegmentVideo(segment)", self.js)
        self.assertIn("state.selectedSegmentIds", self.js)
        self.assertIn('API.frameImage(segment.id, selectedFrameIndex)', self.js)
        self.assertIn('API.segmentVideo(segment.id)', self.js)
        self.assertIn('className = "source-frame-preview"', self.js)
        self.assertIn('state.selectedFrames = state.thumbnailTotal ? new Set([0]) : new Set()', self.js)
        self.assertIn('className = "exported-video-preview"', self.js)
        self.assertIn("hasSegmentVideo(segment)", self.js)
        self.assertIn("showTaskCompletion(completedTask)", self.js)
        self.assertIn("segment_ids: segmentIds", self.js)
        export_body = re.search(r"async function exportVideo\(\) \{(.*?)\n\}", self.js, re.DOTALL).group(1)
        archive_body = re.search(r"async function archiveProject\(\) \{(.*?)\n\}", self.js, re.DOTALL).group(1)
        self.assertIn("currentSegmentIdsForAction()", export_body)
        self.assertIn("currentSegmentIdsForAction()", archive_body)
        self.assertNotIn("selectedSegmentIds", export_body + archive_body)

    def test_segment_multi_select_is_only_a_merge_mode(self):
        self.assertIn('data-i18n="segment.merge_select">选择要合并分段</button>', self.html)
        self.assertIn('class="merge-actions"', self.html)
        merge_controls = re.search(r'<div class="merge-actions">(.*?)</div>', self.html, re.DOTALL).group(1)
        self.assertLess(merge_controls.index('id="segment-multi-select-btn"'), merge_controls.index('id="merge-btn"'))
        self.assertNotIn('id="process-btn"', self.html)
        self.assertNotIn('id="process-selected-btn"', self.html)
        self.assertNotIn('id="retry-btn"', self.html)
        self.assertNotIn('id="retry-stage"', self.html)
        self.assertIn("state.selectedSegmentIds.size < 2", self.js)
        self.assertIn("segments().slice(first, last + 1)", self.js)
        self.assertIn("!state.segmentMultiSelect && isCurrent", self.js)
        self.assertIn("state.selectedSegmentIds.add(String(state.selectedSegmentId))", self.js)

    def test_non_workbench_views_hide_segment_workspace(self):
        self.assertIn('data-active-view="workbench"', self.html)
        self.assertIn('byId("app").dataset.activeView = viewName', self.js)
        self.assertIn('.studio-shell:not([data-active-view="workbench"]) .segments-pane', self.css)

    def test_export_progress_dialog_supports_cancel_and_preview(self):
        self.assertIn('id="export-progress-dialog"', self.html)
        self.assertIn('id="export-progress-cancel-btn"', self.html)
        self.assertIn('id="preview-video-btn"', self.html)
        self.assertIn("updateExportDialog", self.js)
        self.assertIn("cancelTask", self.js)
        self.assertIn("previewCurrentVideo", self.js)

    def test_mobile_source_commands_precede_segments_and_recipe_follows_frames(self):
        self.assertLess(self.html.index('id="source-band"'), self.html.index('id="sidebar-nav"'))
        self.assertLess(self.html.index('class="frame-band"'), self.html.index('class="recipe-panel"'))
        chart = self.html.index('class="chart-panel"')
        preview = self.html.index('class="preview-stage"')
        self.assertLess(chart, preview)
        self.assertIn('<details class="chart-panel"', self.html)

    def test_desktop_inspector_recipe_and_export_preserve_preview_height(self):
        inspector = re.search(r'<div class="workbench-left-rail">(.*?)</div>\s*<figure class="preview-stage">', self.html, re.DOTALL)
        self.assertIsNotNone(inspector)
        inspector_html = inspector.group(1)
        self.assertLess(inspector_html.index('class="chart-panel"'), inspector_html.index('class="frame-band"'))
        self.assertLess(inspector_html.index('class="frame-band"'), inspector_html.index('class="recipe-panel"'))
        self.assertLess(self.html.index('class="preview-stage"'), self.html.index('id="output-flyout"'))
        self.assertIn('<details id="output-flyout" class="output-flyout"', self.html)
        self.assertIn('<summary class="output-summary">', self.html)
        self.assertIn('data-i18n="task.start_current">渲染</button>', self.html)
        self.assertIn('.output-flyout { position: absolute;', self.css)
        self.assertIn('left: 0; right: 0; bottom: 0; width: 100%', self.css)
        self.assertIn('.output-summary::before { content: "\\25B8"', self.css)
        self.assertIn('.output-flyout[open] .output-summary::before { content: "\\25BE"', self.css)
        self.assertIn('.chart-panel[open] > summary', self.css)
        self.assertIn('border-bottom: 1px solid var(--line)', self.css)
        self.assertIn('.chart-panel:not([open]) #brightness-chart { display: none; }', self.css)
        self.assertIn('<details class="frame-band"', self.html)
        self.assertIn('<details class="recipe-panel"', self.html)
        self.assertIn('.frame-band:not([open]) .frame-panel-content', self.css)
        self.assertIn('.recipe-panel:not([open]) .recipe-panel-content', self.css)
        self.assertIn('grid-template-columns: repeat(5, minmax(72px, 1fr))', self.css)
        self.assertIn('.segment-item:hover:not(:disabled)', self.css)

    def test_sidebar_split_and_export_controls_use_compact_order(self):
        self.assertIn('grid-template-columns: 250px minmax(0, 1fr)', self.css)
        split = re.search(r'<div class="split-actions">(.*?)</div>', self.html, re.DOTALL)
        self.assertIsNotNone(split)
        self.assertNotIn('<label', split.group(1))
        self.assertLess(split.group(1).index('id="split-frame"'), split.group(1).index('id="split-btn"'))
        workflow = re.search(r'<div class="workflow-action-row">(.*?)</div>', self.html, re.DOTALL).group(1)
        self.assertLess(workflow.index('id="export-crf"'), workflow.index('id="process-current-btn"'))
        self.assertLess(workflow.index('id="process-current-btn"'), workflow.index('id="export-btn"'))
        self.assertIn('const axisLeft = 18', self.js)
        self.assertIn('const axisBottom = cssHeight - 10', self.js)

    def test_segment_status_and_frame_panel_use_requested_compact_layout(self):
        self.assertIn('className = "segment-item-heading"', self.js)
        self.assertIn('className = "segment-item-status"', self.js)
        self.assertIn('.segment-item-heading { display: flex;', self.css)
        self.assertIn('.frame-band[open] { display: flex; flex: 1 1 230px;', self.css)
        self.assertIn('.recipe-panel[open] { flex: 0 0 auto;', self.css)
        self.assertIn('grid-template-rows: repeat(4, minmax(48px, 1fr))', self.css)
        self.assertIn('#frame-multi-select-btn:hover:not(:disabled)', self.css)

    def test_history_logs_are_combined_and_color_presets_are_editable(self):
        history = re.search(r'<section id="view-history"(.*?)</section>\s*<section id="view-recipes"', self.html, re.DOTALL)
        self.assertIsNotNone(history)
        self.assertIn('id="history-list"', history.group(1))
        self.assertIn('id="task-log"', history.group(1))
        self.assertIn('id="clear-logs-btn"', history.group(1))
        self.assertIn('id="color-preset-form"', self.html)
        for field in ("color-preset-name", "color-preset-sat", "color-preset-con", "color-preset-pivot"):
            self.assertIn(f'id="{field}"', self.html)
        self.assertIn('colorPresets: "/api/color-presets"', self.js)
        self.assertIn("async function saveColorPreset", self.js)
        self.assertIn("async function deleteColorPreset", self.js)
        self.assertNotIn('id="recipe-mode"', self.html)
        self.assertNotIn('data-recipe=', self.html)

    def test_preview_has_real_histogram_overlay(self):
        self.assertIn('id="preview-histogram-panel"', self.html)
        self.assertIn('<summary data-i18n="preview.histogram">直方图</summary>', self.html)
        self.assertIn('id="preview-histogram"', self.html)
        self.assertIn("function drawPreviewHistogram(image)", self.js)
        self.assertIn("getImageData", self.js)
        self.assertIn("histogramOpen: true", self.js)
        self.assertIn(".preview-histogram-panel { position: absolute;", self.css)
        self.assertIn(".preview-histogram-panel:not([open])", self.css)

    def test_video_chart_supports_multiple_metric_views(self):
        self.assertIn('data-i18n="chart.title">视频图表</span>', self.html)
        self.assertIn('id="chart-type-select"', self.html)
        for chart_type in ("brightness", "gain", "change"):
            self.assertIn(f'<option value="{chart_type}"', self.html)
        self.assertIn("function buildVideoChartSeries", self.js)
        self.assertIn("function frameLuminanceChanges", self.js)
        self.assertIn('byId("chart-type-select").addEventListener("change", drawChart)', self.js)
        self.assertIn('t(`chart.legend.${chartType}`)', self.js)

    def test_desktop_frame_thumbnails_are_wider_and_show_full_names(self):
        self.assertIn('grid-template-columns: minmax(400px, 480px)', self.css)
        self.assertIn('max-width: calc(100% - 6px)', self.css)
        self.assertIn('font-size: 10px', self.css)
        self.assertIn('top: 50%', self.css)

    def test_frame_toolbar_groups_selection_actions_beside_heading(self):
        self.assertIn('class="rail-panel-summary frame-summary"', self.html)
        self.assertIn('class="frame-selection-actions"', self.html)
        self.assertIn('class="frame-pagination"', self.html)
        self.assertIn("background: var(--surface)", self.css)

    def test_recipe_is_flushed_before_processing_and_export(self):
        self.assertIn("async function flushRecipeSave()", self.js)
        for function_name in ("processCurrentSegment", "exportVideo"):
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
        self.assertIn('recipes.textContent = t("history.recipe"', self.js)

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
        self.assertIn('t("settings.saved_restart")', self.js)

    def test_settings_include_runtime_log_level(self):
        self.assertIn('id="settings-log-level"', self.html)
        self.assertIn('name="logging.level"', self.html)
        self.assertIn('data-i18n="settings.logging"', self.html)
        self.assertIn('data-i18n="settings.log_level"', self.html)
        self.assertIn('byId("settings-log-level")', self.js)

    def test_layout_contract_is_desktop_first_and_responsive(self):
        self.assertIn("grid-template-columns: 250px minmax(0, 1fr)", self.css)
        self.assertIn("height: 100vh", self.css)
        self.assertIn("overflow: hidden", self.css)
        self.assertIn("@media (max-width: 720px)", self.css)
        self.assertNotIn("linear-gradient(", self.css)
        self.assertNotIn("radial-gradient(", self.css)
        self.assertNotIn('class="task-bar"', self.html)
        self.assertIn('class="workflow-action-row"', self.html)

    def test_embedded_workflow_actions_fit_without_mobile_horizontal_scrolling(self):
        self.assertIn(".workflow-action-row", self.css)
        self.assertIn(".workflow-action-row { display: grid;", self.css)
        self.assertIn("prefers-color-scheme: dark", self.css)
        self.assertIn("overflow-wrap: anywhere", self.css)
        self.assertRegex(self.css, r"body \{[^}]*overflow-x: hidden")

    def test_console_startup_banner_is_branded_and_explains_log_window(self):
        self.assertIn("Solis_Timelapse —— 正在启动...", self.run_bat)
        for token in (
            "Solis_Timelapse · WebUI 已启动",
            "本机访问",
            "局域网",
            "绑定",
            "这个窗口是服务日志",
            "停止：Ctrl+C",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.server)
        self.assertNotIn("Sony 延时摄影", self.run_bat + self.server)

    def test_user_documentation_covers_windows_and_fnos_deployment(self):
        readme = README_PATH.read_text(encoding="utf-8")
        for token in (
            "Solis_Timelapse", "run.bat", "docker compose", "INPUT_PATH",
            "APP_ROOT", "/media/input:ro", "PUID", "PGID",
            "/vol1/1000/solis_timelapse", "9501", "不要直接暴露到公网",
        ):
            with self.subTest(token=token):
                self.assertIn(token, readme)
        for internal_token in (
            "F:\\01_Project", "migrate_to_new_path.bat", "DEVLOG.md",
            "PLAYBOOK.md", ".codex", "junction",
        ):
            with self.subTest(internal_token=internal_token):
                self.assertNotIn(internal_token, readme)

    def test_local_agent_notes_are_ignored(self):
        gitignore = GITIGNORE_PATH.read_text(encoding="utf-8")
        for token in ("DEVLOG.md", "PLAYBOOK.md"):
            with self.subTest(token=token):
                self.assertIn(token, gitignore)


if __name__ == "__main__":
    unittest.main()
