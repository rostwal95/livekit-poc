"""Explicitly configured, payload-free application logs for the diagnostic worker.

Native LiveKit SDK logs retain their own configuration. This module neither
modifies the root logger nor attaches handlers during import. Event/code pairs
and optional numeric counts have a finite vocabulary; exception text, identity,
room, track, credentials and input content are never serialized.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import UTC, datetime
from typing import TextIO

LOGGER_NAME = "services.rtc_agent.application"
MAX_REPORTED_COUNT = 1024
_CONFIGURATION_LOCK = threading.Lock()
_logger: logging.Logger | None = None

_EVENT_LEVELS = {
    ("session_started", "accepted"): logging.INFO,
    ("session_finished", "disconnected"): logging.INFO,
    ("session_finished", "duration_limit"): logging.INFO,
    ("session_finished", "cancelled"): logging.INFO,
    ("session_finished", "failed"): logging.INFO,
    ("session_failed", "timeout"): logging.ERROR,
    ("session_failed", "invalid_input"): logging.ERROR,
    ("session_failed", "transport_error"): logging.ERROR,
    ("session_failed", "unexpected_error"): logging.ERROR,
    ("job_rejected", "invalid_room"): logging.WARNING,
    ("job_rejected", "job_capacity"): logging.WARNING,
    ("stream_rejected", "invalid_source"): logging.WARNING,
    ("stream_rejected", "task_capacity"): logging.WARNING,
    ("stream_rejected", "audio_capacity"): logging.WARNING,
    ("task_completed", "completed"): logging.INFO,
    ("task_cancelled", "cancelled"): logging.INFO,
    ("task_failed", "invalid_input"): logging.WARNING,
    ("task_failed", "timeout"): logging.WARNING,
    ("task_failed", "transport_error"): logging.ERROR,
    ("task_failed", "unexpected_error"): logging.ERROR,
}


class _ApplicationHandler(logging.StreamHandler):
    """Identify the one handler owned by this application logger."""


def configure_logging(*, stream: TextIO | None = None) -> None:
    """Configure once at an actual worker entry point; the first stream wins.

    Repeated admission/session callbacks reuse the existing application-owned
    handler. This leaves the root and native SDK logger configuration untouched.
    """
    global _logger
    with _CONFIGURATION_LOCK:
        logger = logging.getLogger(LOGGER_NAME)
        if not any(isinstance(handler, _ApplicationHandler) for handler in logger.handlers):
            handler = _ApplicationHandler(stream)
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        _logger = logger


def emit_event(
    event: str,
    *,
    code: str,
    active_tasks: int | None = None,
    active_audio_tracks: int | None = None,
) -> None:
    """Emit only an allowlisted event and small numeric observations.

    Pure consumers may instantiate diagnostic helpers without starting a worker.
    Before explicit entry-point configuration this is a no-op, never a fallback
    to root logging. Invalid instrumentation inputs still fail deterministically.
    """
    if type(event) is not str or type(code) is not str:
        raise ValueError("Invalid worker application event")
    level = _EVENT_LEVELS.get((event, code))
    if level is None:
        raise ValueError("Unknown worker application event or code")
    counts = {
        "active_tasks": active_tasks,
        "active_audio_tracks": active_audio_tracks,
    }
    for value in counts.values():
        if value is not None and (type(value) is not int or not 0 <= value <= MAX_REPORTED_COUNT):
            raise ValueError("Invalid worker application count")
    if _logger is None:
        return
    record: dict[str, str | int] = {
        "service": "rtc-agent",
        "severity": logging.getLevelName(level).lower(),
        "timestamp": datetime.now(UTC).isoformat(),
        "event": event,
        "code": code,
    }
    record.update({name: value for name, value in counts.items() if value is not None})
    _logger.log(level, json.dumps(record, separators=(",", ":")))


def classify_error(error: BaseException) -> str:
    """Classify by trusted Python type without reading exception data or chains."""
    if isinstance(error, asyncio.CancelledError):
        return "cancelled"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ValueError):
        return "invalid_input"
    if isinstance(error, OSError):
        return "transport_error"
    return "unexpected_error"


def log_task_completion(task: asyncio.Future[object], *, active_tasks: int) -> None:
    """Observe a finished task once, preserving distinct cancellation semantics."""
    if task.cancelled():
        emit_event("task_cancelled", code="cancelled", active_tasks=active_tasks)
        return
    error = task.exception()
    if error is None:
        emit_event("task_completed", code="completed", active_tasks=active_tasks)
    else:
        emit_event("task_failed", code=classify_error(error), active_tasks=active_tasks)
