import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "migrate_to_new_path.bat"


class MigrationBatContractTests(unittest.TestCase):
    def test_migration_script_has_safe_fixed_path_contract(self):
        self.assertTrue(SCRIPT.is_file(), "migration BAT must exist")
        content = SCRIPT.read_text(encoding="ascii")

        for token in (
            r'set "SOURCE=F:\02_Tools\sony_timelapse"',
            r'set "TARGET=F:\01_Project\Solis_Timelapse"',
            r'set "TARGET_PARENT=F:\01_Project"',
            r'copy /y "%~f0" "%HELPER%"',
            'if /i "%~1"=="--helper"',
            r'move "%SOURCE%" "%TARGET%"',
            r'git -C "%TARGET%" rev-parse --show-toplevel',
            r'mklink /J "%SOURCE%" "%TARGET%"',
            'set "MAX_ATTEMPTS=180"',
        ):
            with self.subTest(token=token):
                self.assertIn(token, content)

    def test_migration_script_does_not_modify_codex_state_or_delete_trees(self):
        content = SCRIPT.read_text(encoding="ascii").lower()
        for forbidden in (
            r"c:\users\smile\.codex",
            "state_5.sqlite",
            "memories_1.sqlite",
            "remove-item",
            "rmdir /s",
            "rd /s",
            "robocopy",
            "xcopy",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, content)

    @unittest.skipUnless(os.name == "nt", "Windows BAT integration test")
    def test_helper_moves_git_repo_and_creates_compatibility_junction(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "old_repo"
            target_parent = root / "new_parent"
            target = target_parent / "Solis_Timelapse"
            source.mkdir()
            target_parent.mkdir()
            subprocess.run(
                ["git", "init", str(source)],
                check=True,
                capture_output=True,
                text=True,
            )
            (source / "probe.txt").write_text("migration probe", encoding="ascii")

            content = SCRIPT.read_text(encoding="ascii")
            content = content.replace(
                r'set "SOURCE=F:\02_Tools\sony_timelapse"',
                f'set "SOURCE={source}"',
            ).replace(
                r'set "TARGET=F:\01_Project\Solis_Timelapse"',
                f'set "TARGET={target}"',
            ).replace(
                r'set "TARGET_PARENT=F:\01_Project"',
                f'set "TARGET_PARENT={target_parent}"',
            )
            helper = root / "migration-test.bat"
            helper.write_text(content, encoding="ascii", newline="\r\n")

            environment = os.environ.copy()
            environment["SOLIS_MIGRATION_NO_PAUSE"] = "1"
            completed = subprocess.run(
                ["cmd.exe", "/d", "/c", "call", str(helper), "--helper"],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertTrue((target / ".git").is_dir())
            self.assertEqual("migration probe", (target / "probe.txt").read_text(encoding="ascii"))
            self.assertTrue(source.is_dir())
            self.assertTrue(os.path.samefile(source, target))
            git_root = subprocess.run(
                ["git", "-C", str(target), "rev-parse", "--show-toplevel"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(target.resolve(), Path(git_root).resolve())

            os.rmdir(source)


if __name__ == "__main__":
    unittest.main()
