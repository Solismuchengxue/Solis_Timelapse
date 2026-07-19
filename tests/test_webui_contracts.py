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
        cls.prefs = PREFS_PATH.read_text(encoding="utf-8")
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
            "history-list", "delete-all-history-btn", "clear-logs-btn", "settings-form", "save-settings-btn",
            "color-preset-list", "color-preset-form", "new-color-preset-btn",
            "save-color-preset-btn", "delete-color-preset-btn", "preview-histogram",
            "settings-save-status", "archive-progress-dialog", "archive-spinner",
            "archive-progress-cancel-btn", "archive-progress-close-btn", "archive-progress-history-btn",
            "preview-video-btn", "export-progress-dialog", "export-progress",
            "export-progress-percent", "export-progress-stats",
            "export-progress-cancel-btn", "export-progress-close-btn",
            "scan-progress-dialog", "scan-progress", "scan-progress-percent",
            "scan-progress-cancel-btn", "scan-progress-close-btn",
            "preview-caption", "exif-dialog", "exif-table-body", "exif-dialog-close",
            "hdr-send-btn", "hdr-form", "hdr-frame-list", "hdr-preview",
            "hdr-start-btn", "hdr-cancel-btn", "hdr-download-btn",
            "settings-render-device",
        }
        present = set(re.findall(r'\bid="([^"]+)"', self.html))
        self.assertEqual(set(), required_ids - present)

    def test_five_named_views_and_accessible_controls_exist(self):
        for label in ("工作台", "HDR 合成", "归档与日志", "色彩配方", "设置"):
            self.assertIn(f">{label}</button>", self.html)
        self.assertNotIn('data-view="logs"', self.html)
        self.assertIn('aria-label="分段列表"', self.html)
        self.assertIn('aria-label="分段缩略图带"', self.html)
        self.assertIn('aria-label="当前分段任务"', self.html)
        self.assertIn("外部源照片始终保留", self.html)

    def test_tabs_and_progress_expose_complete_aria_state(self):
        self.assertIn('role="tablist"', self.html)
        self.assertEqual(5, len(re.findall(r'role="tab"', self.html)))
        self.assertEqual(5, len(re.findall(r'role="tabpanel"', self.html)))
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
            "/api/hdr",
            "/frames/", "/video",
        )
        for route in routes:
            with self.subTest(route=route):
                self.assertIn(route, self.js)

    def test_frontend_polls_tasks_and_loads_all_thumbnails_once(self):
        self.assertRegex(self.js, r"setInterval\(pollTask,\s*1000\)")
        self.assertIn("api(API.thumbnails(segmentId))", self.js)
        self.assertNotIn("loadMoreThumbnails", self.js)
        self.assertNotIn('byId("frame-strip").addEventListener("scroll"', self.js)
        self.assertNotIn('class="frame-pagination"', self.html)
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

    def test_workflow_buttons_follow_render_cancel_preview_export_archive_order(self):
        row = re.search(r'<div class="workflow-action-row">(.*?)</div>', self.html, re.DOTALL)
        self.assertIsNotNone(row)
        body = row.group(1)
        ordered = ["process-current-btn", "cancel-btn", "preview-video-btn", "export-btn", "archive-btn"]
        positions = [body.index(f'id="{item}"') for item in ordered]
        self.assertEqual(positions, sorted(positions))

    def test_archive_has_dedicated_cancellable_waiting_dialog(self):
        for required_id in (
            "archive-progress-dialog",
            "archive-spinner",
            "archive-progress-cancel-btn",
            "archive-progress-close-btn",
            "archive-progress-history-btn",
        ):
            self.assertIn(f'id="{required_id}"', self.html)
        self.assertIn("state.archiveDialogOpen", self.js)
        self.assertIn("updateArchiveProgressDialog", self.js)
        self.assertIn('byId("archive-progress-cancel-btn").addEventListener("click", cancelTask)', self.js)
        self.assertIn('["analyze", "render"].includes(state.task?.kind)', self.js)

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

    def test_export_dialog_uses_real_progress_and_supports_cancel(self):
        self.assertIn('id="export-progress-dialog"', self.html)
        self.assertIn('id="export-progress"', self.html)
        self.assertIn('id="export-progress-percent"', self.html)
        self.assertIn('id="export-progress-stats"', self.html)
        self.assertIn('id="export-progress-cancel-btn"', self.html)
        self.assertIn('id="preview-video-btn"', self.html)
        self.assertNotIn('id="export-spinner"', self.html)
        self.assertNotIn('id="export-progress-preview-btn"', self.html)
        self.assertIn("updateExportDialog", self.js)
        self.assertIn("cancelTask", self.js)

    def test_directory_selection_auto_scans_with_dedicated_real_progress(self):
        self.assertIn('data-i18n="source.rescan">重新扫描</button>', self.html)
        for required_id in (
            "scan-progress-dialog",
            "scan-progress",
            "scan-progress-percent",
            "scan-progress-cancel-btn",
            "scan-progress-close-btn",
        ):
            self.assertIn(f'id="{required_id}"', self.html)
        self.assertIn('state.scanDialogOpen', self.js)
        self.assertIn('await scanSource()', self.js)
        self.assertIn('busy || !state.pendingSourcePath', self.js)
        self.assertIn('const workflowTask = task.kind === "scan"', self.js)
        self.assertIn('updateScanDialog', self.js)
        self.assertIn('progress.value = percent', self.js)
        self.assertIn('progress.setAttribute("aria-valuenow", String(percent))', self.js)

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
        self.assertIn('<details id="output-flyout" class="output-flyout" aria-labelledby="output-heading" open>', self.html)
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
        self.assertIn('<section id="advanced-settings" class="advanced-settings"', self.html)
        self.assertNotIn('<details id="advanced-settings"', self.html)
        self.assertIn('.frame-band:not([open]) .frame-panel-content', self.css)
        self.assertIn('.recipe-panel:not([open]) .recipe-panel-content', self.css)
        self.assertIn('grid-template-columns: repeat(4, minmax(72px, 1fr))', self.css)
        self.assertIn('grid-auto-rows: max-content', self.css)
        self.assertIn('.frame-thumb { position: relative; aspect-ratio: 4 / 3;', self.css)
        self.assertIn('.frame-thumb img { width: 100%; height: 100%; object-fit: contain;', self.css)
        self.assertIn('.segment-item:hover:not(:disabled)', self.css)

    def test_recipe_selector_and_deflicker_toggle_share_compact_top_alignment(self):
        self.assertIn('class="recipe-select-field"', self.html)
        self.assertIn('aria-label="配方预设" data-i18n-aria-label="recipe.mode"', self.html)
        self.assertNotIn('<span data-i18n="recipe.mode">配方预设</span>', self.html)
        self.assertIn('.recipe-select-field { align-self: start; }', self.css)
        self.assertIn('.deflicker-toggle { align-self: start; min-height: 32px;', self.css)

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
        self.assertIn('.frame-band[open] { position: relative; display: flex; flex: 1 1 230px;', self.css)
        self.assertIn('.recipe-panel[open] { flex: 0 0 auto;', self.css)
        self.assertNotIn('grid-auto-rows: calc((100% - 15px) / 4)', self.css)
        self.assertNotIn('.frame-thumb { height: 88px; min-height: 88px; }', self.css)
        self.assertNotIn('.frame-thumb { min-height: 35px; }', self.css)
        self.assertIn('overflow-y: auto', self.css)
        self.assertIn('#frame-multi-select-btn:hover:not(:disabled)', self.css)

    def test_segment_status_tracks_export_and_archive_lifecycle(self):
        self.assertIn("function segmentWorkflowStatus(segment)", self.js)
        self.assertIn("segment?.archive_artifact", self.js)
        self.assertIn("segment?.export_artifact", self.js)
        self.assertIn('"status.exported"', self.prefs)
        self.assertIn('"status.archived"', self.prefs)
        self.assertIn("!segment?.export_artifact", self.js)
        self.assertIn("Boolean(segment?.archive_artifact)", self.js)

    def test_segment_cards_show_capture_metadata_in_requested_order(self):
        render_body = re.search(r"function renderSegments\(\) \{(.*?)\n\}", self.js, re.DOTALL)
        self.assertIsNotNone(render_body)
        ordered_keys = [
            "segment.meta_frame_focal",
            "segment.meta_date_time",
            "segment.meta_exposure",
            "segment.meta_location",
        ]
        positions = [render_body.group(1).index(key) for key in ordered_keys]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn('"segment.meta_time": "拍摄时间：', self.prefs)
        self.assertNotIn('"segment.meta_location": "拍摄位置：', self.prefs)
        self.assertIn('height: auto; min-height: 0; overflow: visible;', self.css)

    def test_history_logs_are_combined_and_color_presets_are_editable(self):
        history = re.search(r'<section id="view-history"(.*?)</section>\s*<section id="view-recipes"', self.html, re.DOTALL)
        self.assertIsNotNone(history)
        self.assertIn('id="history-list"', history.group(1))
        self.assertIn('id="task-log"', history.group(1))
        self.assertIn('id="clear-logs-btn"', history.group(1))
        self.assertIn('id="delete-all-history-btn"', history.group(1))
        self.assertIn('id="settings-log-level"', history.group(1))
        self.assertIn('id="color-preset-form"', self.html)
        for field in ("color-preset-name", "color-preset-sat", "color-preset-con", "color-preset-pivot"):
            self.assertIn(f'id="{field}"', self.html)
        self.assertIn('colorPresets: "/api/color-presets"', self.js)
        self.assertIn("async function saveColorPreset", self.js)
        self.assertIn("async function deleteColorPreset", self.js)
        self.assertNotIn('id="recipe-mode"', self.html)
        self.assertNotIn('data-recipe=', self.html)
        self.assertIn('class="color-preset-sidebar"', self.html)

    def test_preview_has_real_histogram_overlay(self):
        self.assertIn('id="preview-histogram-panel"', self.html)
        self.assertIn('<summary data-i18n="preview.histogram">直方图</summary>', self.html)
        self.assertIn('id="preview-histogram"', self.html)
        self.assertIn("function drawPreviewHistogram(image)", self.js)
        self.assertIn("getImageData", self.js)
        self.assertIn("histogramOpen: true", self.js)
        self.assertIn(".preview-histogram-panel { position: absolute;", self.css)
        self.assertIn(".preview-histogram-panel:not([open])", self.css)

    def test_frame_preview_shows_capture_metadata_and_full_exif_dialog(self):
        for key in (
            "preview.focal",
            "preview.aperture",
            "preview.shutter",
            "preview.location",
            "preview.exposure_bias",
        ):
            self.assertIn(f't("{key}"', self.js)
        self.assertIn("API.frameExif(segment.id, frameIndex)", self.js)
        self.assertIn('button.id = "preview-exif-btn"', self.js)
        self.assertIn('class="confirm-dialog exif-dialog"', self.html)
        self.assertIn(".exif-table th { position: sticky;", self.css)

    def test_video_chart_supports_multiple_metric_views(self):
        self.assertIn('data-i18n="chart.title">视频图表</span>', self.html)
        self.assertIn('id="chart-type-select"', self.html)
        for chart_type in ("brightness", "gain", "change"):
            self.assertIn(f'<option value="{chart_type}"', self.html)
        self.assertIn("function buildVideoChartSeries", self.js)
        self.assertIn("function frameLuminanceChanges", self.js)
        self.assertIn('byId("chart-type-select").addEventListener("change", drawChart)', self.js)
        self.assertIn('t(`chart.legend.${chartType}`)', self.js)

    def test_original_resolution_controls_use_backend_canonical_value(self):
        self.assertEqual(2, self.html.count('value="original" data-i18n="export.source_width"'))
        self.assertNotIn('value="source" data-i18n="export.source_width"', self.html)

    def test_export_dialog_has_real_progress_controls(self):
        self.assertIn('id="export-progress"', self.html)
        self.assertIn('id="export-progress-percent"', self.html)
        self.assertIn('id="export-progress-stats"', self.html)
        self.assertNotIn('id="export-spinner"', self.html)
        self.assertIn('dialog.export_progress.h264_oversize', self.js)

    def test_desktop_frame_thumbnails_are_wider_and_show_full_names(self):
        self.assertIn('grid-template-columns: minmax(420px, 520px)', self.css)
        self.assertIn('max-width: calc(100% - 6px)', self.css)
        self.assertIn('font-size: 10px', self.css)
        self.assertIn('top: 50%', self.css)

    def test_frame_toolbar_groups_selection_actions_beside_heading(self):
        self.assertIn('class="rail-panel-summary frame-summary"', self.html)
        self.assertIn('class="frame-selection-actions"', self.html)
        self.assertNotIn('class="frame-pagination"', self.html)
        self.assertIn("overflow-y: auto", self.css)
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

    def test_operation_error_routing_is_owned_by_start_operation(self):
        start_match = re.search(
            r"async function startOperation\([^)]*\) \{(.*?)\n\}",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(start_match)
        self.assertIn("options.showError === false", start_match.group(1))

        process_match = re.search(
            r"async function processCurrentSegment\([^)]*\) \{(.*?)\n\}",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(process_match)
        self.assertNotIn("options.showError", process_match.group(1))

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
        self.assertIn("function historyCaptureSummary(entry)", self.js)
        self.assertIn('className = "history-delete-button"', self.js)
        self.assertIn('className = "history-media-link"', self.js)
        self.assertIn("async function deleteHistoryEntry", self.js)
        self.assertIn("async function deleteAllHistory", self.js)
        self.assertIn("function potPlayerUrl", self.js)
        self.assertIn("link.href = potPlayerUrl", self.js)
        for function_name in ("deleteHistoryEntry", "deleteAllHistory"):
            start = self.js.index(f"async function {function_name}")
            body = self.js[start:self.js.index("\n}", start)]
            self.assertIn("refreshState()", body)
        self.assertIn('.history-media-link::before { content: "\\25B6"', self.css)

    def test_history_detail_preserves_only_final_video_urls(self):
        self.assertIn("async function loadHistoryDetail(summary)", self.js)
        self.assertIn("function normaliseHistoryMedia(summary, manifest)", self.js)
        self.assertIn("summary.outputs || summary.final_videos", self.js)
        self.assertIn("manifest.outputs || manifest.final_videos", self.js)
        self.assertNotIn('appendMediaLinks(media, t("history.preview")', self.js)
        self.assertIn("mergeMediaItems", self.js)

    def test_workbench_video_caption_prefers_render_preview(self):
        self.assertIn(
            'segment?.preview_file ? t("history.preview") : t("history.output")',
            self.js,
        )

    def test_history_original_count_prefers_segment_manifest_counts(self):
        match = re.search(
            r"function historyOriginalCount\(entry\) \{(.*?)\n\}",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        body = match.group(1)
        self.assertIn("segment.source_file_count", body)
        self.assertIn("segmentCounts.reduce", body)
        self.assertIn("entry.source_file_count", body)
        self.assertIn("historyOriginalCount(entry)", self.js)

    def test_history_shows_first_and_last_source_filenames(self):
        self.assertIn("function historyFileRanges(entry)", self.js)
        self.assertIn("segment.first_file", self.js)
        self.assertIn("segment.last_file", self.js)
        self.assertIn("segment.originals", self.js)
        self.assertIn('t("history.file_range"', self.js)
        self.assertIn('"history.file_range"', self.prefs)

    def test_archive_history_has_an_independent_scroll_container(self):
        self.assertIn(
            '#view-history.is-active { display: grid; grid-template-rows: auto minmax(0, 1fr); overflow: hidden; }',
            self.css,
        )
        self.assertIn('scrollbar-gutter: stable', self.css)
        self.assertIn('overscroll-behavior: contain', self.css)
        self.assertIn('.history-list, .log-console { max-height: min(55vh, 520px); overflow-y: auto; }', self.css)

    def test_archive_history_and_task_logs_are_independently_collapsible(self):
        for heading_id, toggle_id, content_id in (
            ("archive-history-bar", "archive-history-toggle", "history-list"),
            ("task-log-bar", "task-log-toggle", "task-log-content"),
        ):
            self.assertIn(f'id="{heading_id}"', self.html)
            self.assertIn(f'id="{toggle_id}"', self.html)
            self.assertIn(f'aria-controls="{content_id}"', self.html)
            self.assertIn('aria-expanded="true"', self.html)
        self.assertIn('id="task-log-content"', self.html)
        self.assertIn('function toggleHistoryRegion(toggleId, contentId)', self.js)
        self.assertIn('function bindHistoryRegionToggle(headingId, toggleId, contentId)', self.js)
        self.assertIn('.region-heading.is-collapsible', self.css)
        self.assertIn('.task-log-content[hidden]', self.css)
        self.assertLess(
            self.html.index('class="log-level-help"'),
            self.html.index('id="task-log-content"'),
        )
        self.assertIn('column-gap: 1px', self.css)
        self.assertIn('background: var(--line)', self.css)
        self.assertIn('.history-region.is-collapsed, .logs-region.is-collapsed', self.css)
        self.assertIn('.region-collapse-toggle[aria-expanded="false"] .disclosure-icon', self.css)

    def test_settings_paths_are_read_only_picker_controls(self):
        for purpose in ("workspace", "output", "archive"):
            self.assertRegex(
                self.html,
                rf'id="settings-{purpose}-dir"[^>]*readonly',
            )
            self.assertIn(f'data-settings-directory="{purpose}"', self.html)

    def test_settings_expose_render_device_selection(self):
        self.assertIn('id="settings-render-device"', self.html)
        for value in ("auto", "cpu", "gpu"):
            self.assertIn(f'<option value="{value}"', self.html)
        self.assertIn('settings.processing?.render_device || "auto"', self.js)
        self.assertIn('render_device: byId("settings-render-device").value', self.js)

    def test_restart_required_settings_response_has_explicit_notice(self):
        self.assertIn('id="settings-save-status"', self.html)
        self.assertIn('role="status"', self.html)
        self.assertIn("payload.restart_required", self.js)
        self.assertIn('t("settings.saved_restart")', self.js)

    def test_history_page_contains_runtime_log_level(self):
        history = re.search(r'<section id="view-history"(.*?)</section>\s*<section id="view-recipes"', self.html, re.DOTALL)
        settings = re.search(r'<section id="view-settings"(.*?)</section>', self.html, re.DOTALL)
        self.assertIn('id="settings-log-level"', history.group(1))
        self.assertNotIn('id="settings-log-level"', settings.group(1))
        self.assertIn('data-i18n="settings.logging"', self.html)
        self.assertIn('data-i18n="settings.log_level"', self.html)
        self.assertIn("async function saveLogLevel", self.js)
        self.assertIn('byId("settings-log-level").addEventListener("change", saveLogLevel)', self.js)

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

    def test_clear_project_dialog_emphasizes_deleted_directories(self):
        for required_id in (
            "clear-workspace-path",
            "clear-output-path",
            "clear-archive-path",
        ):
            self.assertIn(f'id="{required_id}"', self.html)
        self.assertGreaterEqual(self.html.count('class="clear-danger-path"'), 2)
        self.assertIn(".clear-danger-path", self.css)
        self.assertIn("font-weight: 700", self.css)
        self.assertIn("color: var(--danger)", self.css)
        self.assertIn("function openClearProjectDialog()", self.js)
        self.assertIn('payload.cleanup_targets', self.js)
        self.assertIn('state.task = { status: "idle", completed: 0, total: 0', self.js)

    def test_user_documentation_covers_windows_and_fnos_deployment(self):
        readme = README_PATH.read_text(encoding="utf-8")
        for token in (
            "Solis_Timelapse", "run.bat", "docker compose", "INPUT_PATH",
            "APP_ROOT", "/media/input:ro", "PUID", "PGID",
            "/vol1/1000/solis_timelapse", "9501", "不要直接暴露到公网",
            "python:3.12-slim", "没有发布可直接拉取的应用镜像",
            "飞牛图形界面部署", "SSH 命令部署", "docker compose config",
            "docker compose logs", "docker compose ps", "9501:9501",
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
