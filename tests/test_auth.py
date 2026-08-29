import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.auth import AuthStateError, AuthStore


class AuthStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.path = Path(self.temp.name) / "auth.json"

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_auth_file_is_uninitialized(self):
        self.assertIsNone(AuthStore(self.path).load())

    def test_initialize_persists_hash_without_plaintext_password(self):
        record = AuthStore(self.path).initialize("admin", "correct horse battery")

        raw = self.path.read_text(encoding="utf-8")
        payload = json.loads(raw)
        self.assertEqual(record.username, "admin")
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["username"], "admin")
        self.assertIn("password_hash", payload)
        self.assertIn("session_secret", payload)
        self.assertNotIn("correct horse battery", raw)
        self.assertNotIn("password", payload)

    def test_saved_credentials_verify_after_reload(self):
        AuthStore(self.path).initialize("owner", "long enough password")
        reloaded = AuthStore(self.path)

        self.assertEqual(reloaded.load().username, "owner")
        self.assertTrue(reloaded.verify("owner", "long enough password"))
        self.assertFalse(reloaded.verify("owner", "wrong password"))
        self.assertFalse(reloaded.verify("someone-else", "long enough password"))

    def test_wrong_username_still_performs_password_hash_check(self):
        AuthStore(self.path).initialize("owner", "long enough password")

        with patch("src.auth.check_password_hash", return_value=False) as check:
            self.assertFalse(AuthStore(self.path).verify("someone-else", "long enough password"))

        check.assert_called_once()

    def test_invalid_auth_file_fails_closed(self):
        invalid_values = (
            "not-json",
            json.dumps({"version": 2, "username": "owner", "password_hash": "x", "session_secret": "y", "created_at": "z"}),
            json.dumps({"version": 1, "username": "owner"}),
            json.dumps({
                "version": 1,
                "username": "owner",
                "password_hash": "not-a-password-hash",
                "session_secret": "x" * 32,
                "created_at": "2026-08-11T00:00:00+00:00",
            }),
        )
        for value in invalid_values:
            with self.subTest(value=value):
                self.path.write_text(value, encoding="utf-8")
                with self.assertRaises(AuthStateError):
                    AuthStore(self.path).load()

    def test_reinitialization_is_rejected_without_changing_credentials(self):
        store = AuthStore(self.path)
        store.initialize("owner", "original password")

        with self.assertRaises(AuthStateError):
            store.initialize("attacker", "replacement password")

        self.assertTrue(store.verify("owner", "original password"))
        self.assertFalse(store.verify("attacker", "replacement password"))

    def test_initialize_rejects_invalid_username_and_password_lengths(self):
        invalid_values = (
            ("", "long enough password"),
            ("   ", "long enough password"),
            ("x" * 65, "long enough password"),
            ("owner", "short"),
            ("owner", "x" * 257),
        )
        for index, (username, password) in enumerate(invalid_values):
            with self.subTest(username=username, password_length=len(password)):
                candidate = self.path.with_name(f"auth-{index}.json")
                with self.assertRaises(AuthStateError):
                    AuthStore(candidate).initialize(username, password)
                self.assertFalse(candidate.exists())

    def test_change_password_replaces_hash_and_rotates_all_sessions(self):
        store = AuthStore(self.path)
        original = store.initialize("owner", "original password")

        changed = store.change_password("original password", "replacement password")

        self.assertEqual(changed.username, original.username)
        self.assertEqual(changed.created_at, original.created_at)
        self.assertNotEqual(changed.password_hash, original.password_hash)
        self.assertNotEqual(changed.session_secret, original.session_secret)
        self.assertFalse(store.verify("owner", "original password"))
        self.assertTrue(store.verify("owner", "replacement password"))
        self.assertNotIn("replacement password", self.path.read_text(encoding="utf-8"))

    def test_change_password_rejects_invalid_credentials_without_mutating_record(self):
        store = AuthStore(self.path)
        store.initialize("owner", "original password")
        original = self.path.read_bytes()

        for current_password, new_password in (
            ("wrong password", "replacement password"),
            ("original password", "short"),
            ("original password", "x" * 257),
        ):
            with self.subTest(current_password=current_password, new_length=len(new_password)):
                with self.assertRaises(AuthStateError):
                    store.change_password(current_password, new_password)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertTrue(store.verify("owner", "original password"))

    def test_change_password_write_failure_preserves_original_record(self):
        store = AuthStore(self.path)
        store.initialize("owner", "original password")
        original = self.path.read_bytes()

        with patch("src.auth.os.replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(AuthStateError):
                store.change_password("original password", "replacement password")

        self.assertEqual(self.path.read_bytes(), original)
        self.assertTrue(store.verify("owner", "original password"))


if __name__ == "__main__":
    unittest.main()
