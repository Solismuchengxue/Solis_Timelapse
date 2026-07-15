"""Single-worker background task state machine."""
from __future__ import annotations

import json
import os
import threading
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


ACTIVE_STATES = {"queued", "running", "cancelling"}


class TaskBusy(RuntimeError):
    """Raised when a second task is submitted while one is active."""


class TaskCancelled(RuntimeError):
    """Raised at a cooperative cancellation boundary."""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class TaskContext:
    def __init__(
        self,
        cancel_event: threading.Event,
        progress_callback: Callable[..., None],
        log_callback: Callable[[str], None],
    ) -> None:
        self._cancel_event = cancel_event
        self._progress_callback = progress_callback
        self._log_callback = log_callback

    def progress(self, completed: int, total: int, **detail: Any) -> None:
        self.raise_if_cancelled()
        self._progress_callback(completed, total, **detail)

    def log(self, message: str) -> None:
        self.raise_if_cancelled()
        self._log_callback(str(message))

    def raise_if_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise TaskCancelled("task cancelled")

    def cancelled(self) -> bool:
        return self._cancel_event.is_set()


class TaskManager:
    def __init__(self, state_path: Path | None = None, max_logs: int = 200) -> None:
        if max_logs < 1:
            raise ValueError("max_logs must be positive")
        self._state_path = Path(state_path) if state_path is not None else None
        self._max_logs = max_logs
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="timelapse-task")
        self._cancel_event = threading.Event()
        self._state = self._load_state()
        if self._state["status"] in ACTIVE_STATES:
            self._state["status"] = "interrupted"
            self._state["finished_at"] = _now()
            self._state["error"] = "任务因服务重启而中断"
            self._persist_locked()

    @staticmethod
    def _empty_state() -> dict:
        return {
            "job_id": None,
            "kind": None,
            "status": "idle",
            "completed": 0,
            "total": 0,
            "detail": {},
            "logs": [],
            "result": None,
            "error": None,
            "created_at": None,
            "started_at": None,
            "finished_at": None,
        }

    def _load_state(self) -> dict:
        state = self._empty_state()
        if self._state_path is None or not self._state_path.is_file():
            return state
        try:
            loaded = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return state
        if isinstance(loaded, dict):
            state.update(loaded)
        state["logs"] = list(state.get("logs") or [])[-self._max_logs :]
        state["detail"] = dict(state.get("detail") or {})
        return state

    def _persist_locked(self) -> None:
        if self._state_path is None:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        os.replace(temporary, self._state_path)

    def submit(self, kind: str, fn: Callable[[TaskContext], Any]) -> dict:
        if not kind or not callable(fn):
            raise ValueError("kind and callable fn are required")
        with self._lock:
            if self._state["status"] in ACTIVE_STATES:
                raise TaskBusy("another task is already active")
            job_id = uuid.uuid4().hex
            self._cancel_event = threading.Event()
            self._state = {
                **self._empty_state(),
                "job_id": job_id,
                "kind": kind,
                "status": "queued",
                "created_at": _now(),
            }
            self._persist_locked()
            self._executor.submit(self._run, job_id, fn, self._cancel_event)
            return deepcopy(self._state)

    def _run(
        self,
        job_id: str,
        fn: Callable[[TaskContext], Any],
        cancel_event: threading.Event,
    ) -> None:
        with self._lock:
            if self._state.get("job_id") != job_id:
                return
            self._state["status"] = "running"
            self._state["started_at"] = _now()
            self._persist_locked()

        context = TaskContext(
            cancel_event,
            lambda completed, total, **detail: self._progress(job_id, completed, total, detail),
            lambda message: self._log(job_id, message),
        )
        try:
            context.raise_if_cancelled()
            result = fn(context)
            context.raise_if_cancelled()
        except TaskCancelled:
            self._finish(job_id, "cancelled")
        except Exception as exc:  # Task failures are represented in state for the API.
            self._finish(job_id, "failed", error=str(exc) or exc.__class__.__name__)
        else:
            self._finish(job_id, "completed", result=result)

    def _progress(self, job_id: str, completed: int, total: int, detail: dict) -> None:
        if completed < 0 or total < 0 or completed > total:
            raise ValueError("invalid task progress")
        with self._lock:
            if self._state.get("job_id") != job_id:
                return
            self._state["completed"] = completed
            self._state["total"] = total
            self._state["detail"] = deepcopy(detail)
            self._persist_locked()

    def _log(self, job_id: str, message: str) -> None:
        with self._lock:
            if self._state.get("job_id") != job_id:
                return
            logs = deque(self._state.get("logs") or [], maxlen=self._max_logs)
            logs.append(message)
            self._state["logs"] = list(logs)
            self._persist_locked()

    def _finish(
        self,
        job_id: str,
        status: str,
        *,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            if self._state.get("job_id") != job_id:
                return
            self._state["status"] = status
            self._state["result"] = deepcopy(result)
            self._state["error"] = error
            self._state["finished_at"] = _now()
            self._persist_locked()

    def cancel(self) -> dict:
        with self._lock:
            if self._state["status"] in {"queued", "running"}:
                self._cancel_event.set()
                self._state["status"] = "cancelling"
                self._persist_locked()
            return deepcopy(self._state)

    def snapshot(self) -> dict:
        with self._lock:
            return deepcopy(self._state)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)
