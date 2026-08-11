from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.util
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_builder():
    path = ROOT / "demo" / "build_site.py"
    spec = importlib.util.spec_from_file_location("demo_build_site", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DemoBuildContractTests(unittest.TestCase):
    def test_build_reuses_webui_sources_and_injects_only_mock_runtime(self):
        builder = load_builder()
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "site"
            files = builder.build_site(ROOT, output)
            names = {path.as_posix() for path in files}
            self.assertTrue(
                {"app.js", "index.html", "mock_api.js", "styles.css", "ui_prefs.js"}.issubset(names)
            )
            for name in ("app.js", "styles.css", "ui_prefs.js"):
                self.assertEqual(
                    sha256((output / name).read_bytes()).digest(),
                    sha256((ROOT / "webui" / name).read_bytes()).digest(),
                )
            html = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn('src="./mock_api.js"', html)
            self.assertLess(html.index("./mock_api.js"), html.index("./ui_prefs.js"))
            self.assertLess(html.index("./mock_api.js"), html.index("./app.js"))
            self.assertNotIn('src="/app.js"', html)

    def test_build_rejects_protected_output_paths(self):
        builder = load_builder()
        for path in (ROOT, ROOT / "webui", ROOT / "demo", ROOT / "workspace"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    builder.build_site(ROOT, path)

    def test_mock_is_local_only_and_contains_no_sensitive_path_patterns(self):
        source = (ROOT / "demo" / "mock_api.js").read_text(encoding="utf-8")
        for forbidden in ("XMLHttpRequest", "WebSocket", "http://", "/vol1/", "F:\\"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertEqual(source.count("https://"), 1)
        self.assertIn("https://github.com/Solismuchengxue/Solis_Timelapse#docker-部署", source)
        self.assertIn("静态演示禁止外部请求", source)
        self.assertIn("/api/not-allowed", (ROOT / "tests" / "test_demo_mock.js").read_text(encoding="utf-8"))

    def test_demo_chrome_uses_the_webui_language_value(self):
        source = (ROOT / "demo" / "mock_api.js").read_text(encoding="utf-8")
        self.assertIn('getItem("solis.language")?.startsWith("en")', source)

    def test_demo_chrome_wraps_without_overlapping_on_mobile(self):
        source = (ROOT / "demo" / "mock_api.js").read_text(encoding="utf-8")
        self.assertIn("@media (max-width: 720px)", source)
        self.assertIn(".studio-header.static-demo-header", source)
        self.assertIn("flex-wrap: wrap", source)
        self.assertIn("display: inline-flex", source)

    def test_demo_contains_exactly_twelve_generated_frames(self):
        assets = sorted((ROOT / "demo" / "assets").glob("frame-*.png"))
        self.assertEqual(
            [path.name for path in assets],
            [f"frame-{index:02d}.png" for index in range(1, 13)],
        )
        for path in assets:
            self.assertGreater(path.stat().st_size, 20_000)

    def test_pages_workflow_builds_and_uploads_only_demo_site(self):
        workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        for token in (
            "contents: read", "pages: write", "id-token: write", "actions: read",
            "python demo/build_site.py --output .demo-site",
            "python -m unittest tests.test_demo_contracts",
            "path: .demo-site", "environment:", "name: github-pages",
            "actions/checkout@v6", "actions/configure-pages@v5",
            "actions/upload-pages-artifact@v4", "actions/deploy-pages@v4",
        ):
            self.assertIn(token, workflow)
        self.assertNotIn("path: .\n", workflow)
