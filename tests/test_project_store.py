from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.project_store import ProjectStore


class ProjectStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name) / "workspace"
        self.source_dir = Path(self.temp_dir.name) / "source"
        self.source_dir.mkdir()
        self.store = ProjectStore(self.workspace)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_load_update_and_clear(self):
        created = self.store.create(self.source_dir)

        self.assertEqual(created["schema_version"], 1)
        self.assertEqual(created["source_dir"], str(self.source_dir.resolve()))
        self.assertEqual(created["status"], "created")
        self.assertEqual(created["segments"], [])
        self.assertIsNone(created["active_job_id"])
        self.assertIn("T", created["created_at"])
        self.assertEqual(self.store.load(), created)

        updated = self.store.update(
            lambda state: {**state, "status": "analyzed"}
        )
        self.assertEqual(updated["status"], "analyzed")
        self.assertEqual(updated["created_at"], created["created_at"])
        self.assertNotEqual(updated["updated_at"], "")

        self.store.clear()
        self.assertIsNone(self.store.load())
        self.assertFalse(self.store.current_dir.exists())

    def test_save_publishes_with_os_replace(self):
        state = self.store.create(self.source_dir)

        with mock.patch("src.project_store.os.replace", wraps=os.replace) as replace:
            self.store.save({**state, "status": "scanned"})

        replace.assert_called_once_with(self.store.temporary_path, self.store.project_path)
        self.assertEqual(self.store.load()["status"], "scanned")

    def test_leftover_temporary_file_does_not_replace_valid_project(self):
        valid = self.store.create(self.source_dir)
        self.store.temporary_path.write_text(
            json.dumps({**valid, "status": "corrupt"}), encoding="utf-8"
        )

        self.assertEqual(self.store.load()["status"], "created")

    def test_update_requires_existing_project(self):
        with self.assertRaisesRegex(RuntimeError, "No active project"):
            self.store.update(lambda state: state)


if __name__ == "__main__":
    unittest.main()
