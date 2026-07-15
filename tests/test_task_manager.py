import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from src.task_manager import TaskBusy, TaskCancelled, TaskManager


class TaskManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temporary.name) / "task.json"
        self.manager = TaskManager(self.state_path, max_logs=3)

    def tearDown(self):
        self.manager.shutdown()
        self.temporary.cleanup()

    def wait_for(self, status, timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            snapshot = self.manager.snapshot()
            if snapshot["status"] == status:
                return snapshot
            time.sleep(0.01)
        self.fail(f"task did not reach {status}: {self.manager.snapshot()}")

    def test_idle_running_completed_state_and_progress(self):
        started = threading.Event()
        release = threading.Event()

        def work(context):
            started.set()
            context.progress(1, 2, segment="A")
            release.wait(1)
            context.progress(2, 2)
            return {"frames": 2}

        submitted = self.manager.submit("render", work)
        self.assertEqual(submitted["kind"], "render")
        self.assertTrue(started.wait(1))
        running = self.wait_for("running")
        self.assertEqual(running["completed"], 1)
        self.assertEqual(running["detail"], {"segment": "A"})
        release.set()
        completed = self.wait_for("completed")
        self.assertEqual(completed["result"], {"frames": 2})
        self.assertIsNotNone(completed["finished_at"])

    def test_duplicate_submit_raises_task_busy(self):
        release = threading.Event()
        self.manager.submit("scan", lambda context: release.wait(1))
        self.wait_for("running")
        with self.assertRaises(TaskBusy):
            self.manager.submit("render", lambda context: None)
        release.set()

    def test_cancel_is_observed_at_context_callback_boundary(self):
        ready = threading.Event()
        continue_work = threading.Event()

        def work(context):
            ready.set()
            continue_work.wait(1)
            context.progress(1, 1)

        self.manager.submit("analyze", work)
        self.assertTrue(ready.wait(1))
        cancelling = self.manager.cancel()
        self.assertEqual(cancelling["status"], "cancelling")
        continue_work.set()
        cancelled = self.wait_for("cancelled")
        self.assertIsNone(cancelled["error"])

    def test_exception_marks_task_failed(self):
        def fail(context):
            raise ValueError("broken frame")

        self.manager.submit("render", fail)
        failed = self.wait_for("failed")
        self.assertEqual(failed["error"], "broken frame")

    def test_logs_are_bounded(self):
        def work(context):
            for index in range(5):
                context.log(f"line {index}")

        self.manager.submit("scan", work)
        completed = self.wait_for("completed")
        self.assertEqual(completed["logs"], ["line 2", "line 3", "line 4"])

    def test_persisted_running_task_becomes_interrupted_on_startup(self):
        self.manager.shutdown()
        self.state_path.write_text(
            json.dumps({"status": "running", "job_id": "old", "kind": "render"}),
            encoding="utf-8",
        )
        self.manager = TaskManager(self.state_path)
        snapshot = self.manager.snapshot()
        self.assertEqual(snapshot["status"], "interrupted")
        self.assertIsNotNone(snapshot["finished_at"])
        persisted = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["status"], "interrupted")


if __name__ == "__main__":
    unittest.main()
