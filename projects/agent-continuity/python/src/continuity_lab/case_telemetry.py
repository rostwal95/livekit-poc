"""Finite per-service case metrics and safe application-boundary observations."""

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

from .execution_cli import _CODES
from .execution_models import ExecutionError, StorageUnavailable
from .migrations import MigrationError

T = TypeVar("T")
OPERATIONS = frozenset(
    {
        "enroll",
        "managed_submit",
        "projection",
        "prepare_quote",
        "get",
        "revise",
        "confirm",
        "arm_wait",
        "signal",
        "advance",
        "waits",
        "lifecycle",
        "cancel",
        "effect",
        "completion",
        "delivery",
    }
)
OUTCOMES = frozenset({"success", "rejected", "failed"})
LOGGER = logging.getLogger("continuity_lab.case_service")
LOGGER.addHandler(logging.NullHandler())


class CaseTelemetry:
    """Observe real public calls; operational counters do not replace the ledger.

    Private registries avoid process-global duplicate collectors. No actor/task/
    quote/token labels or exception strings are recorded. A metrics/logging failure
    is contained here and cannot alter acceptance, original errors or replay.
    """

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.operations = Counter(
            "continuity_case_operations_total",
            "Observed case operations",
            ("operation", "outcome"),
            registry=self.registry,
        )
        self.duration = Histogram(
            "continuity_case_operation_duration_seconds",
            "Case operation duration in seconds",
            ("operation", "outcome"),
            buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
            registry=self.registry,
        )

    def _observe(self, operation: str, outcome: str, code: str, started: float) -> None:
        try:
            self.operations.labels(operation, outcome).inc()
            self.duration.labels(operation, outcome).observe(max(0.0, time.monotonic() - started))
            LOGGER.log(
                logging.INFO
                if outcome == "success"
                else logging.WARNING
                if outcome == "rejected"
                else logging.ERROR,
                "case_operation",
                extra={
                    "event": "case_operation",
                    "code": code,
                    "operation": operation,
                    "outcome": outcome,
                },
            )
        except Exception:  # noqa: BLE001 - explicit telemetry-only containment boundary
            return

    def call(self, operation: str, action: Callable[[], T]) -> T:
        if type(operation) is not str or operation not in OPERATIONS:
            raise ValueError("Unsupported case observation operation")
        started = time.monotonic()
        try:
            value = action()
        except Exception as error:
            code = "unexpected_error"
            if isinstance(error, (ExecutionError, MigrationError, ValueError)):
                try:
                    candidate = getattr(error, "code", "invalid_input")
                    if isinstance(candidate, str) and candidate in _CODES:
                        code = candidate
                except Exception:  # noqa: BLE001 - diagnostic metadata is untrusted
                    code = "unexpected_error"
            outcome = (
                "rejected"
                if isinstance(error, (ExecutionError, ValueError))
                and not isinstance(error, (StorageUnavailable, MigrationError))
                else "failed"
            )
            self._observe(operation, outcome, code, started)
            raise
        self._observe(operation, "success", "ok", started)
        return value

    def render(self) -> bytes:
        """Operator scrape output; no HTTP exporter or durable count is implied."""
        return generate_latest(self.registry)
