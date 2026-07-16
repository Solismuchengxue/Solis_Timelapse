"""Single-worker background task state machine."""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


ACTIVE_STATES = {"pending", "queued", "running", "cancelling"}
CONFIGURED_LOG_LEVELS = {"INFO", "DEBUG"}
EVENT_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


class TaskBusy(RuntimeError):
    """Raised when a second task is submitted while one is active."""


class TaskCancelled(RuntimeError):
    """Raised at a cooperative cancellation boundary."""


class TaskNotCancellable(RuntimeError):
    """Raised when cancellation is forbidden after a task starts running."""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class TaskContext:
    def __init__(
        self,
        cancel_event: threading.Event,
        progress_callback: Callable[..., None],
        log_callback: Callable[[str, str], None],
    ) -> None:
        self._cancel_event = cancel_event
        self._progress_callback = progress_callback
        self._log_callback = log_callback

    def progress(self, completed: int, total: int, **detail: Any) -> None:
        self.raise_if_cancelled()
        self._progress_callback(completed, total, **detail)

    def log(self, message: str, level: str = "INFO") -> None:
        self.raise_if_cancelled()
        self._log_callback(str(message), level)

    def debug(self, message: str) -> None:
        self.log(message, "DEBUG")

    def raise_if_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise TaskCancelled("task cancelled")

    def cancelled(self) -> bool:
        return self._cancel_event.is_set()


class TaskManager:
    def __init__(
        self,
        state_path: Path | None = None,
        max_logs: int = 200,
        max_history_logs: int = 2000,
        log_level: str = "INFO",
    ) -> None:
        if max_logs < 1:
            raise ValueError("max_logs must be positive")
        if max_history_logs < 1:
            raise ValueError("max_history_logs must be positive")
        self._state_path = Path(state_path) if state_path is not None else None
        self._max_logs = max_logs
        self._max_history_logs = max_history_logs
        self._log_level = self._normalise_configured_level(log_level)
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="timelapse-task")
        self._cancel_event = threading.Event()
        self._state = self._load_state()
        if self._state["status"] in ACTIVE_STATES:
            self._state["status"] = "interrupted"
            self._state["cancellable"] = False
            self._state["finished_at"] = _now()
            self._state["error"] = "任务因服务重启而中断"
            self._append_history_locked("任务因服务重启而中断")
            self._persist_locked()

    @staticmethod
    def _empty_state() -> dict:
        return {
            "job_id": None,
            "kind": None,
            "status": "idle",
            "cancellable": False,
            "cancellable_while_running": True,
            "completed": 0,
            "total": 0,
            "detail": {},
            "logs": [],
            "history_logs": [],
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
            if "cancellable_while_running" not in loaded:
                state["cancellable_while_running"] = bool(loaded.get("cancellable", True))
        state["logs"] = list(state.get("logs") or [])[-self._max_logs :]
        history_logs = []
        for entry in list(state.get("history_logs") or [])[-self._max_history_logs :]:
            if isinstance(entry, dict):
                entry = {**entry, "level": str(entry.get("level", "INFO")).upper()}
            history_logs.append(entry)
        state["history_logs"] = history_logs
        state["detail"] = dict(state.get("detail") or {})
        return state

    @staticmethod
    def _normalise_configured_level(level: str) -> str:
        value = str(level).upper()
        if value not in CONFIGURED_LOG_LEVELS:
            raise ValueError("log level must be INFO or DEBUG")
        return value

    @staticmethod
    def _normalise_event_level(level: str) -> str:
        value = str(level).upper()
        if value not in EVENT_LOG_LEVELS:
            raise ValueError("invalid event log level")
        return value

    def _should_log(self, level: str) -> bool:
        return self._log_level == "DEBUG" or level != "DEBUG"

    def _append_history_locked(
        self,
        message: str,
        level: str = "INFO",
        *,
        inherit_task: bool = True,
        kind: str | None = None,
    ) -> bool:
        level = self._normalise_event_level(level)
        if not self._should_log(level):
            return False
        entry = {
            "timestamp": _now(),
            "job_id": self._state.get("job_id") if inherit_task else None,
            "kind": self._state.get("kind") if inherit_task else kind,
            "level": level,
            "message": str(message),
        }
        history = deque(
            self._state.get("history_logs") or [], maxlen=self._max_history_logs
        )
        history.append(entry)
        self._state["history_logs"] = list(history)
        kind_label = entry["kind"] or "system"
        print(
            f"[{entry['timestamp']}] [{entry['level']:<7}] [{kind_label}] {entry['message']}",
            flush=True,
        )
        return True

    def _persist_locked(self) -> None:
        if self._state_path is None:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        for attempt in range(5):
            try:
                os.replace(temporary, self._state_path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02 * (attempt + 1))

    def submit(
        self,
        kind: str,
        fn: Callable[[TaskContext], Any],
        *,
        cancellable_while_running: bool = True,
    ) -> dict:
        if not kind or not callable(fn):
            raise ValueError("kind and callable fn are required")
        with self._lock:
            if self._state["status"] in ACTIVE_STATES:
                raise TaskBusy("another task is already active")
            job_id = uuid.uuid4().hex
            history_logs = list(self._state.get("history_logs") or [])
            self._cancel_event = threading.Event()
            self._state = {
                **self._empty_state(),
                "history_logs": history_logs,
                "job_id": job_id,
                "kind": kind,
                "status": "queued",
                "cancellable": True,
                "cancellable_while_running": bool(cancellable_while_running),
                "created_at": _now(),
            }
            self._append_history_locked(f"任务已提交：{kind}")
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
            if cancel_event.is_set():
                self._state["status"] = "cancelled"
                self._state["cancellable"] = False
                self._state["finished_at"] = _now()
                self._persist_locked()
                return
            self._state["status"] = "running"
            self._state["cancellable"] = bool(
                self._state.get("cancellable_while_running", True)
            )
            self._state["started_at"] = _now()
            self._append_history_locked(f"任务开始：{self._state.get('kind')}")
            self._persist_locked()

        context = TaskContext(
            cancel_event,
            lambda completed, total, **detail: self._progress(job_id, completed, total, detail),
            lambda message, level: self._log(job_id, message, level),
        )
        try:
            context.raise_if_cancelled()
            result = fn(context)
            context.raise_if_cancelled()
        except TaskCancelled:
            self._finish(job_id, "cancelled")
        except Exception as exc:  # Task failures are represented in state for the API.
            self._finish(
                job_id,
                "failed",
                error=str(exc) or exc.__class__.__name__,
                traceback_text=traceback.format_exc(),
            )
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
            values = []
            for key, value in detail.items():
                if key in {"file", "frame", "current_file"} and isinstance(value, str):
                    value = Path(value).name
                values.append(f"{key}={value}")
            suffix = f" · {' · '.join(values)}" if values else ""
            self._append_history_locked(
                f"进度 {completed}/{total}{suffix}", "DEBUG"
            )
            self._persist_locked()

    def _log(self, job_id: str, message: str, level: str = "INFO") -> None:
        level = self._normalise_event_level(level)
        with self._lock:
            if self._state.get("job_id") != job_id:
                return
            if not self._should_log(level):
                return
            logs = deque(self._state.get("logs") or [], maxlen=self._max_logs)
            logs.append(message)
            self._state["logs"] = list(logs)
            self._append_history_locked(message, level)
            self._persist_locked()

    def _finish(
        self,
        job_id: str,
        status: str,
        *,
        result: Any = None,
        error: str | None = None,
        traceback_text: str | None = None,
    ) -> None:
        with self._lock:
            if self._state.get("job_id") != job_id:
                return
            self._state["status"] = status
            self._state["cancellable"] = False
            self._state["result"] = deepcopy(result)
            self._state["error"] = error
            self._state["finished_at"] = _now()
            labels = {
                "completed": "任务完成",
                "failed": "任务失败",
                "cancelled": "任务已取消",
            }
            message = labels.get(status, f"任务状态：{status}")
            if status == "failed" and error:
                detail = " ".join(str(error).splitlines()).strip()
                if detail:
                    message = f"任务失败：{detail}"
            level = "ERROR" if status == "failed" else "INFO"
            self._append_history_locked(message, level)
            if traceback_text:
                self._append_history_locked(traceback_text.rstrip(), "DEBUG")
            self._persist_locked()

    def cancel(self) -> dict:
        with self._lock:
            status = self._state["status"]
            if status in {"pending", "queued"}:
                self._cancel_event.set()
                self._state["status"] = "cancelling"
                self._state["cancellable"] = False
                self._append_history_locked("正在取消任务")
                self._persist_locked()
            elif status == "running":
                if not self._state.get("cancellable_while_running", True):
                    raise TaskNotCancellable("running task cannot be cancelled")
                self._cancel_event.set()
                self._state["status"] = "cancelling"
                self._state["cancellable"] = False
                self._append_history_locked("正在取消任务")
                self._persist_locked()
            return deepcopy(self._state)

    def history(self) -> list[dict]:
        with self._lock:
            return deepcopy(self._state.get("history_logs") or [])

    def set_log_level(self, level: str) -> None:
        value = self._normalise_configured_level(level)
        with self._lock:
            self._log_level = value
            self._append_history_locked(
                f"日志级别已切换为 {value}", "INFO", inherit_task=False, kind="settings"
            )
            self._persist_locked()

    def record(self, message: str, *, level: str = "INFO", kind: str = "system") -> None:
        with self._lock:
            if self._append_history_locked(
                message, level, inherit_task=False, kind=kind
            ):
                self._persist_locked()

    def clear_logs(self) -> None:
        with self._lock:
            self._state["logs"] = []
            self._state["history_logs"] = []
            self._persist_locked()

    def snapshot(self) -> dict:
        with self._lock:
            return deepcopy(self._state)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)
