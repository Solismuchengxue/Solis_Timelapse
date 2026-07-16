import tempfile
import unittest
from pathlib import Path

from src.instance_guard import InstanceAlreadyRunning, InstanceGuard


class InstanceGuardTests(unittest.TestCase):
    def test_second_guard_for_same_workspace_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            guard_path = Path(root) / ".solis-instance"

            with InstanceGuard(guard_path):
                with self.assertRaises(InstanceAlreadyRunning):
                    with InstanceGuard(guard_path):
                        self.fail("second guard must not be acquired")

    def test_guard_can_be_reacquired_after_release(self):
        with tempfile.TemporaryDirectory() as root:
            guard_path = Path(root) / ".solis-instance"

            with InstanceGuard(guard_path):
                pass
            with InstanceGuard(guard_path):
                pass


if __name__ == "__main__":
    unittest.main()
