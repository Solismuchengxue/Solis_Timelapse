"""Persistent authentication state for container deployments."""
from __future__ import annotations

import json
import hmac
import os
import secrets
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash


_AUTH_WRITE_LOCK = threading.Lock()


@dataclass(frozen=True)
class AuthRecord:
    version: int
    username: str
    password_hash: str
    session_secret: str
    created_at: str


class AuthStateError(RuntimeError):
    """Raised when persisted authentication state cannot be trusted."""


def _record_from_payload(payload: object) -> AuthRecord:
    if not isinstance(payload, dict):
        raise AuthStateError("authentication state is invalid")
    try:
        record = AuthRecord(**payload)
    except (TypeError, ValueError) as exc:
        raise AuthStateError("authentication state is invalid") from exc
    if (
        record.version != 1
        or not isinstance(record.username, str)
        or not record.username
        or not isinstance(record.password_hash, str)
        or not record.password_hash.startswith("scrypt:")
        or not isinstance(record.session_secret, str)
        or len(record.session_secret) < 32
        or not isinstance(record.created_at, str)
        or not record.created_at
    ):
        raise AuthStateError("authentication state is invalid")
    return record


class AuthStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> AuthRecord | None:
        if not self.path.is_file():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return _record_from_payload(payload)
        except (OSError, json.JSONDecodeError, AuthStateError) as exc:
            raise AuthStateError("authentication state is invalid") from exc

    def initialize(self, username: str, password: str) -> AuthRecord:
        if not isinstance(username, str) or not isinstance(password, str):
            raise AuthStateError("invalid authentication setup")
        username = username.strip()
        if not 1 <= len(username) <= 64 or not 8 <= len(password) <= 256:
            raise AuthStateError("invalid authentication setup")
        with _AUTH_WRITE_LOCK:
            if self.path.exists():
                raise AuthStateError("authentication is already initialized")
            record = AuthRecord(
                version=1,
                username=username,
                password_hash=generate_password_hash(password, method="scrypt"),
                session_secret=secrets.token_urlsafe(32),
                created_at=datetime.now(UTC).isoformat(),
            )
            self._write(record)
            return record

    def change_password(self, current_password: str, new_password: str) -> AuthRecord:
        if not isinstance(current_password, str) or not isinstance(new_password, str):
            raise AuthStateError("invalid password change")
        if not 8 <= len(new_password) <= 256:
            raise AuthStateError("invalid password change")
        with _AUTH_WRITE_LOCK:
            record = self.load()
            if record is None or not check_password_hash(record.password_hash, current_password):
                raise AuthStateError("invalid password change")
            changed = AuthRecord(
                version=record.version,
                username=record.username,
                password_hash=generate_password_hash(new_password, method="scrypt"),
                session_secret=secrets.token_urlsafe(32),
                created_at=record.created_at,
            )
            try:
                self._write(changed)
            except OSError as exc:
                raise AuthStateError("authentication state could not be updated") from exc
            return changed

    def _write(self, record: AuthRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(asdict(record), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def verify(self, username: str, password: str) -> bool:
        record = self.load()
        if record is None:
            return False
        username_matches = hmac.compare_digest(record.username, username)
        password_matches = check_password_hash(record.password_hash, password)
        return username_matches and password_matches
