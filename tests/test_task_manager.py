import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.task_manager import TaskBusy, TaskManager, TaskNotCancellable


class ControlledExecutor:
    def __init__(self, *args, **kwargs):
        self.pending = None

    def submit(self, fn, *args, **kwargs):
        self.pending = (fn, args, kwargs)

    def run_pending(self):
        fn, args, kwargs = self.pending
        fn(*args, **kwargs)

    def shutdown(self, wait=True, cancel_futures=False):
        pass


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

    def test_queued_task_can_be_cancelled_even_when_running_would_not_be(self):
        self.manager.shutdown()
        executor = ControlledExecutor()
        with patch("src.task_manager.ThreadPoolExecutor", return_value=executor):
            self.manager = TaskManager(self.state_path)
        submitted = self.manager.submit(
            "archive",
            lambda context: self.fail("cancelled queued task must not run"),
            cancellable_while_running=False,
        )
        self.assertEqual(submitted["status"], "queued")
        self.assertTrue(submitted["cancellable"])
        self.assertFalse(submitted["cancellable_while_running"])

        cancelling = self.manager.cancel()
        self.assertEqual(cancelling["status"], "cancelling")
        executor.run_pending()
        self.assertEqual(self.manager.snapshot()["status"], "cancelled")

    def test_running_non_cancellable_task_rejects_cancel_without_setting_event(self):
        ready = threading.Event()
        release = threading.Event()
        cancellation_seen = []

        def archive(context):
            ready.set()
            release.wait(1)
            cancellation_seen.append(context.cancelled())

        submitted = self.manager.submit(
            "archive", archive, cancellable_while_running=False
        )
        self.assertTrue(submitted["cancellable"])
        self.assertTrue(ready.wait(1))
        running = self.wait_for("running")
        self.assertFalse(running["cancellable"])
        with self.assertRaises(TaskNotCancellable):
            self.manager.cancel()
        self.assertEqual(self.manager.snapshot()["status"], "running")
        release.set()
        self.wait_for("completed")
        self.assertEqual(cancellation_seen, [False])

    def test_normal_running_task_remains_cancellable(self):
        ready = threading.Event()
        release = threading.Event()

        def work(context):
            ready.set()
            release.wait(1)
            context.raise_if_cancelled()

        submitted = self.manager.submit("render", work)
        self.assertTrue(submitted["cancellable"])
        self.assertTrue(ready.wait(1))
        running = self.wait_for("running")
        self.assertTrue(running["cancellable"])
        self.assertEqual(self.manager.cancel()["status"], "cancelling")
        release.set()
        self.wait_for("cancelled")

    def test_exception_marks_task_failed(self):
        def fail(context):
            raise ValueError("broken frame")

        self.manager.submit("render", fail)
        failed = self.wait_for("failed")
        self.assertEqual(failed["error"], "broken frame")
        self.assertIn(
            "任务失败：broken frame",
            [entry["message"] for entry in self.manager.history()],
        )

    def test_info_level_omits_debug_progress_details(self):
        self.manager.submit(
            "scan",
            lambda context: context.progress(1, 2, current_file="frame-1.jpg"),
        )
        self.wait_for("completed")

        self.assertNotIn(
            "进度 1/2 · current_file=frame-1.jpg",
            [entry["message"] for entry in self.manager.history()],
        )

    def test_debug_level_records_progress_and_traceback(self):
        self.manager.set_log_level("DEBUG")

        def fail(context):
            context.progress(1, 2, current_file="frame-1.jpg")
            raise ValueError("broken frame")

        self.manager.submit("render", fail)
        self.wait_for("failed")
        history = self.manager.history()

        self.assertIn(
            "进度 1/2 · current_file=frame-1.jpg",
            [entry["message"] for entry in history],
        )
        self.assertTrue(any(entry["level"] == "DEBUG" for entry in history))
        self.assertTrue(
            any("Traceback (most recent call last)" in entry["message"] for entry in history)
        )

    def test_record_adds_detailed_non_task_event(self):
        self.manager.record("已选择素材目录：photos", kind="project")

        event = self.manager.history()[-1]
        self.assertEqual(event["level"], "INFO")
        self.assertEqual(event["kind"], "project")
        self.assertIsNone(event["job_id"])
        self.assertEqual(event["message"], "已选择素材目录：photos")

    def test_logs_are_bounded(self):
        def work(context):
            for index in range(5):
                context.log(f"line {index}")

        self.manager.submit("scan", work)
        completed = self.wait_for("completed")
        self.assertEqual(completed["logs"], ["line 2", "line 3", "line 4"])

    def test_history_logs_survive_next_task_and_can_be_cleared(self):
        self.manager.submit("first", lambda context: context.log("first message"))
        self.wait_for("completed")
        self.manager.submit("second", lambda context: context.log("second message"))
        self.wait_for("completed")

        messages = [entry["message"] for entry in self.manager.history()]
        self.assertIn("first message", messages)
        self.assertIn("second message", messages)

        self.manager.clear_logs()

        self.assertEqual(self.manager.history(), [])
        self.assertEqual(self.manager.snapshot()["logs"], [])

    def test_reset_current_returns_to_idle_without_deleting_history(self):
        self.manager.submit("render", lambda context: context.log("render complete"))
        completed = self.wait_for("completed")
        history = self.manager.history()

        reset = self.manager.reset_current()

        self.assertEqual(reset["status"], "idle")
        self.assertIsNone(reset["job_id"])
        self.assertEqual(reset["completed"], 0)
        self.assertEqual(reset["total"], 0)
        self.assertEqual(reset["detail"], {})
        self.assertEqual(reset["history_logs"], history)
        self.assertNotEqual(completed["status"], reset["status"])

    def test_transient_permission_error_during_persist_is_retried(self):
        real_replace = __import__("os").replace
        attempts = []

        def flaky_replace(source, target):
            attempts.append((source, target))
            if len(attempts) == 1:
                raise PermissionError(5, "file is temporarily locked")
            return real_replace(source, target)

        with (
            patch("src.task_manager.os.replace", side_effect=flaky_replace),
            patch("src.task_manager.time.sleep") as sleep,
        ):
            self.manager.clear_logs()

        self.assertEqual(len(attempts), 2)
        sleep.assert_called_once()
        self.assertTrue(self.state_path.is_file())

    def test_persisted_running_task_becomes_interrupted_on_startup(self):
        self.manager.shutdown()
        self.state_path.write_text(
            json.dumps({"status": "running", "job_id": "old", "kind": "render"}),
            encoding="utf-8",
        )
        self.manager = TaskManager(self.state_path)
        snapshot = self.manager.snapshot()
        self.assertEqual(snapshot["status"], "interrupted")
        self.assertFalse(snapshot["cancellable"])
        self.assertTrue(snapshot["cancellable_while_running"])
        self.assertIsNotNone(snapshot["finished_at"])
        persisted = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["status"], "interrupted")


if __name__ == "__main__":
    unittest.main()
