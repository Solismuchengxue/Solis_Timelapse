from argparse import ArgumentParser
from pathlib import Path
from shutil import copy2, copytree, rmtree


WEBUI_FILES = ("index.html", "styles.css", "ui_prefs.js", "app.js")
MOCK_SCRIPT = '  <script src="./mock_api.js"></script>\n'


def validate_output_dir(repo_root: Path, output_dir: Path) -> Path:
    root = repo_root.resolve()
    output = output_dir.resolve()
    if output == root or output in root.parents:
        raise ValueError("output cannot be the repository root or its parent")
    for protected_name in ("webui", "demo", "workspace", "output", "archive"):
        protected = (root / protected_name).resolve()
        if output == protected or protected in output.parents or output in protected.parents:
            raise ValueError(f"output overlaps protected path: {protected_name}")
    return output


def transform_index(html: str) -> str:
    replacements = {
        'src="/ui_prefs.js"': 'src="./ui_prefs.js"',
        'href="/styles.css"': 'href="./styles.css"',
        'src="/app.js"': 'src="./app.js"',
    }
    for old, new in replacements.items():
        if html.count(old) != 1:
            raise ValueError(f"expected one index token: {old}")
        html = html.replace(old, new)
    marker = '  <script src="./ui_prefs.js"></script>\n'
    if html.count(marker) != 1:
        raise ValueError("preference script marker changed")
    return html.replace(marker, MOCK_SCRIPT + marker)


def build_site(repo_root: Path, output_dir: Path) -> tuple[Path, ...]:
    root = repo_root.resolve()
    output = validate_output_dir(root, output_dir)
    if output.exists():
        rmtree(output)
    output.mkdir(parents=True)
    for name in WEBUI_FILES:
        copy2(root / "webui" / name, output / name)
    (output / "index.html").write_text(
        transform_index((root / "webui" / "index.html").read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    copy2(root / "demo" / "mock_api.js", output / "mock_api.js")
    assets = root / "demo" / "assets"
    if assets.is_dir():
        copytree(assets, output / "assets")
    return tuple(sorted(path.relative_to(output) for path in output.rglob("*") if path.is_file()))


def main() -> None:
    parser = ArgumentParser(description="Build the static Solis Timelapse demo site.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    build_site(repo_root, args.output)


if __name__ == "__main__":
    main()
