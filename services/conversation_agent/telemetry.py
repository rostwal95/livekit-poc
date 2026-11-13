"""Finite conversation logs; SDK message bodies and exception chains stay private."""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TextIO

LOGGER = logging.getLogger("services.conversation_agent")
EVENTS = frozenset(
    {
        "conversation_event",
        "startup_progress",
        "input_rejected",
        "job_rejected",
        "session_started",
        "session_finished",
        "session_failed",
        "cleanup_failed",
        "hint_failed",
        "sdk_warning",
        "sdk_error",
    }
)
# Pinned SDK locations classify failures without reading log message, stack,
# exception text or arbitrary metadata. Unknown locations keep sdk_error.
SDK_FAILURE_PHASES = {
    ("worker", "_job_request_task"): "assignment",
    ("proc_pool", "_acquire_proc"): "process_acquire",
    ("proc_pool", "launch_job"): "process_launch",
    ("proc_pool", "_proc_spawn_task"): "process_initialize",
    ("job_proc_lazy_main", "_on_entry_done"): "job_entry",
    ("job_proc_lazy_main", "_shutdown_job"): "job_shutdown",
    ("job", "_on_session_end"): "session_report",
    ("supervised_proc", "initialize"): "process_initialize",
    ("supervised_proc", "aclose"): "process_shutdown",
    ("supervised_proc", "_supervise_task"): "process_exit",
    ("supervised_proc", "_memory_monitor_task"): "process_memory",
    ("supervised_proc", "_pong_timeout_co"): "process_unresponsive",
    ("log", "async_fn_logs"): "callback",
    ("log", "fn_logs"): "callback",
}
SDK_FAILURE_TYPES = (
    (TimeoutError, "timeout"),
    (AttributeError, "attribute"),
    (RuntimeError, "runtime"),
    (TypeError, "type"),
    (ValueError, "value"),
    (AssertionError, "assertion"),
)
SESSION_FAILURE_PHASES = frozenset(
    {
        "setup",
        "rtc_connect",
        "media_ready",
        "session",
        "cleanup_runtime",
        "cleanup_controls",
        "cleanup_observer",
        "cleanup_port",
    }
)
SESSION_FAILURE_KINDS = frozenset({"timeout", "configuration", "dependency", "cancelled"})
SESSION_FAILURE_CODES = frozenset(
    "session_" + phase + "_" + kind
    for phase in SESSION_FAILURE_PHASES
    for kind in SESSION_FAILURE_KINDS
)


def session_failure_code(phase: str, error: BaseException) -> str:
    """Classify only trusted stage and exact builtin type, never error content."""
    if type(phase) is not str or phase not in SESSION_FAILURE_PHASES:
        raise ValueError("A fixed native failure phase is required")
    category = (
        "timeout"
        if type(error) is TimeoutError
        else "cancelled"
        if type(error) is asyncio.CancelledError
        else "configuration"
        if type(error) in {ValueError, TypeError, AttributeError, AssertionError}
        else "dependency"
    )
    return "session_" + phase + "_" + category


SDK_FAILURE_CODES = frozenset(
    "sdk_" + phase + "_" + kind
    for phase in SDK_FAILURE_PHASES.values()
    for kind in ("other", "none", *(name for _, name in SDK_FAILURE_TYPES))
)


# These frozen SDK warnings place the caught exception in one positional
# argument rather than exc_info. Read only its exact builtin type; no body,
# repr, chained exception, arbitrary class name or metadata is consulted.
SDK_TRANSCRIPTION_WARNING_PHASES = {
    ("_output", "capture_text"): "transcription_capture",
    ("_output", "_flush_task"): "transcription_flush",
    ("_output", "_publish_transcription"): "transcription_publish",
}
# Exact origins verified against the installed 1.8.11 source. These identify
# the operation that emitted a warning, not its message, resource value or cause.
# In particular memory warning and memory-limit error retain distinct severities.
SDK_STARTUP_WARNING_PHASES = {
    ("proc_pool", "start"): "process_idle_initialize",
    ("proc_pool", "_acquire_proc"): "process_acquire",
    ("proc_pool", "launch_job"): "process_launch",
    ("supervised_proc", "_memory_monitor_task"): "process_memory",
    ("supervised_proc", "_read_ipc_task"): "process_responsiveness",
    ("supervised_proc", "_supervise_task"): "process_exit",
    ("worker", "_connection_task"): "worker_connection",
    ("worker", "_on_accept"): "assignment",
    ("worker", "_job_request_task"): "assignment_answer",
    ("worker", "_handle_assignment"): "assignment_lookup",
    ("job_proc_lazy_main", "_warn_not_connected_task"): "job_entry_connection",
    ("job_proc_lazy_main", "_on_entry_done"): "job_entry",
    ("job_proc_lazy_main", "_shutdown_job"): "job_shutdown",
}
SDK_WARNING_CODES = frozenset(
    "sdk_" + phase + "_" + kind
    for phase in (
        *SDK_TRANSCRIPTION_WARNING_PHASES.values(),
        *SDK_STARTUP_WARNING_PHASES.values(),
    )
    for kind in ("other", "none", *(name for _, name in SDK_FAILURE_TYPES))
)


def _sdk_warning_code(record: logging.LogRecord) -> str:
    module, function = getattr(record, "module", None), getattr(record, "funcName", None)
    if type(module) is not str or type(function) is not str:
        return "sdk_warning"
    transcription_phase = SDK_TRANSCRIPTION_WARNING_PHASES.get((module, function))
    phase = transcription_phase or SDK_STARTUP_WARNING_PHASES.get((module, function))
    if phase is None:
        return "sdk_warning"
    info = record.exc_info
    args = record.args
    if (
        transcription_phase is None
        and type(info) is tuple
        and len(info) == 3
        and info[0] is not None
    ):
        kind = next((name for expected, name in SDK_FAILURE_TYPES if info[0] is expected), "other")
    elif type(args) is tuple and len(args) == 1:
        argument_type = type(args[0])
        kind = next(
            (name for expected, name in SDK_FAILURE_TYPES if argument_type is expected),
            "other",
        )
    else:
        kind = "none"
    return "sdk_" + phase + "_" + kind


def _sdk_failure_code(record: logging.LogRecord) -> str:
    module, function = getattr(record, "module", None), getattr(record, "funcName", None)
    if type(module) is not str or type(function) is not str:
        return "sdk_error"
    phase = SDK_FAILURE_PHASES.get((module, function))
    if phase is None:
        return "sdk_error"
    info = record.exc_info
    if type(info) is tuple and len(info) == 3 and info[0] is not None:
        kind = next((name for expected, name in SDK_FAILURE_TYPES if info[0] is expected), "other")
    else:
        kind = "none"
    return "sdk_" + phase + "_" + kind


# Constructor/connection progress is diagnostic only; RoomIO readiness and
# session_started remain the product barriers. No identity or payload is logged.
STARTUP_PROGRESS_CODES = frozenset(
    {
        "startup_entry",
        "startup_port_ready",
        "startup_runtime_constructing",
        "startup_runtime_ready",
        "startup_rtc_connecting",
        "startup_rtc_connected",
    }
)

CODES = (
    frozenset(
        {
            "ok",
            "accepted",
            "invalid_room",
            "invalid_input",
            "job_capacity",
            "disconnected",
            "duration_limit",
            "cancelled",
            "unexpected_error",
            "shutdown_incomplete",
            "notification_unavailable",
            "sdk_warning",
            "sdk_error",
        }
    )
    | SDK_FAILURE_CODES
    | SDK_WARNING_CODES
    | SESSION_FAILURE_CODES
    | STARTUP_PROGRESS_CODES
)


class _SafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        native = record.name in {"livekit", "opentelemetry"} or record.name.startswith(
            ("livekit.", "opentelemetry.")
        )
        event = (
            "sdk_error"
            if native and record.levelno >= logging.ERROR
            else "sdk_warning"
            if native
            else getattr(record, "event", "conversation_event")
        )
        code = (
            _sdk_failure_code(record)
            if native and record.levelno >= logging.ERROR
            else _sdk_warning_code(record)
            if native
            else getattr(record, "code", "unexpected_error")
        )
        severity = {
            logging.DEBUG: "debug",
            logging.INFO: "info",
            logging.WARNING: "warning",
            logging.ERROR: "error",
            logging.CRITICAL: "critical",
        }.get(record.levelno, "error")
        return json.dumps(
            {
                "service": "conversation-agent",
                "timestamp": datetime.now(UTC).isoformat(),
                "severity": severity,
                "event": event if type(event) is str and event in EVENTS else "conversation_event",
                "code": code if type(code) is str and code in CODES else "unexpected_error",
            }
        )


if TYPE_CHECKING:
    _HandlerBase = logging.StreamHandler[TextIO]
else:
    _HandlerBase = logging.StreamHandler


class _ConversationHandler(_HandlerBase):
    pass


def configure_logging() -> None:
    for name in (
        "services.conversation_agent",
        "livekit",
        "livekit.agents",
        "opentelemetry",
        "openai",
        "httpx",
        "httpx2",
        "httpcore",
        "httpcore2",
        "aiohttp",
        "websockets",
        "deepgram",
        "elevenlabs",
    ):
        logger = logging.getLogger(name)
        if not any(isinstance(handler, _ConversationHandler) for handler in logger.handlers):
            # This application owns the dedicated process's console boundary.
            # Do not serialize existing SDK log bodies, PII extras or chains.
            logger.handlers.clear()
            handler = _ConversationHandler()
            handler.setFormatter(_SafeFormatter())
            logger.addHandler(handler)
        logger.setLevel(logging.INFO if name == "services.conversation_agent" else logging.WARNING)
        logger.propagate = False


def emit(event: str, code: str = "ok") -> None:
    try:
        LOGGER.log(
            logging.ERROR
            if code in SESSION_FAILURE_CODES or code in {"unexpected_error", "shutdown_incomplete"}
            else logging.INFO,
            event,
            extra={"event": event, "code": code},
        )
    except Exception:  # noqa: BLE001 - logging cannot change accepted work or cleanup
        return
