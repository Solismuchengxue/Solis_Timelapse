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


if __name__ == "__main__":
    unittest.main()
