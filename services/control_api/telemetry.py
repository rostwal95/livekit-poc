"""Bounded local HTTP telemetry and sanitized error responses.

Metrics use a private per-app registry. Request identifiers are diagnostic only;
caller identifiers, headers, payloads and exception text never become telemetry.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

LOGGER = logging.getLogger("services.control_api.telemetry")
LOGGER.setLevel(logging.INFO)
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(handler)
LOGGER.propagate = False

OPERATIONS = {
    "/healthz": "health",
    "/readyz": "readiness",
    "/api/config": "config",
    "/api/session": "session",
    "/api/investigations": "investigations",
    "/api/metrics": "metrics",
}
METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"})
EXCLUDED_OPERATIONS = frozenset({"health", "readiness", "metrics"})
SAFE_LOCATIONS = frozenset(
    {
        "body",
        "query",
        "path",
        "header",
        "cookie",
        "room",
        "identity",
        "dispatch_agent",
        "booking_reference",
        "new_check_in",
        "confirmed",
        "idempotency_key",
        "limit",
    }
)
ERRORS = {
    "business_unavailable": (True, "start_local_business_profile"),
    "response_too_large": (False, "request_smaller_page"),
    "execution_not_found": (False, "check_case_access"),
    "unsupported_operation": (False, "inspect_current_state"),
    "stale_revision": (False, "refresh_case"),
    "transition_conflict": (False, "refresh_case"),
    "quote_expired": (False, "request_fresh_quote"),
    "invalid_confirmation": (False, "inspect_exact_quote"),
    "case_cancelled": (False, "inspect_current_state"),
    "intent_committed": (False, "inspect_current_state"),
    "invalid_stored_state": (False, "inspect_local_storage"),
    "schema_version_unsupported": (False, "prepare_supported_schema"),
    "session_in_use": (False, "use_another_room"),
    "source_quiesced": (False, "use_active_execution_backend"),
    "authentication_required": (False, "provide_operator_token"),
    "forbidden": (False, "check_permissions"),
    "route_not_found": (False, "check_endpoint"),
    "method_not_allowed": (False, "check_method"),
    "request_timeout": (True, "retry_later"),
    "idempotency_conflict": (False, "reuse_original_payload_or_new_key"),
    "request_too_large": (False, "reduce_request_size"),
    "validation_error": (False, "correct_request"),
    "rate_limited": (True, "honor_retry_after"),
    "capacity_exhausted": (True, "retry_later"),
    "dependency_unavailable": (True, "check_dependencies_then_retry"),
    "dispatch_unavailable": (True, "retry_later"),
    "storage_limit_reached": (False, "inspect_local_storage"),
    "storage_unavailable": (True, "check_storage_then_retry"),
    "service_unavailable": (True, "retry_later"),
    "http_error": (False, "check_request"),
    "internal_error": (False, "inspect_request_id_before_retry"),
}
DEFAULT_ERRORS: dict[int, tuple[str, str]] = {
    401: ("authentication_required", "Local operator token required"),
    403: ("forbidden", "Request forbidden"),
    404: ("route_not_found", "Not Found"),
    405: ("method_not_allowed", "Method Not Allowed"),
    408: ("request_timeout", "Request body timeout"),
    409: ("idempotency_conflict", "Conflicting request"),
    413: ("request_too_large", "Request body too large"),
    422: ("validation_error", "Invalid request"),
    429: ("rate_limited", "Local session rate limit"),
    503: ("service_unavailable", "Local service unavailable"),
}


def operation_for_path(path: str) -> str:
    if path == "/api/business/investigations":
        return "business_submit"
    if path == "/api/business/session":
        return "business_session"
    match = re.fullmatch(
        r"/api/business/cases/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?:/(quote|signal|cancel))?",
        path,
    )
    if match:
        return "business_" + (match[1] or "get")
    return OPERATIONS.get(path, "unknown")


class ApiError(HTTPException):
    """An expected error with a fixed code and an application-owned safe detail."""

    def __init__(
        self,
        status_code: int,
        detail: Any,
        *,
        code: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        if code not in ERRORS:
            raise ValueError("Unknown local API error code")
        self.code = code
        super().__init__(status_code=status_code, detail=detail, headers=headers)


def request_id(scope: Scope) -> str:
    """Return only an internally generated, validated identifier."""
    value = scope.get("state", {}).get("request_id")
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{32}", value) is None:
        raise RuntimeError("Local request identifier is unavailable")
    return value


def error_response(
    scope: Scope,
    status: int,
    detail: Any,
    code: str,
    *,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    retryable, retry_hint = ERRORS[code]
    scope.setdefault("state", {})["error_code"] = code
    return JSONResponse(
        status_code=status,
        content={
            "detail": detail,
            "code": code,
            "retryable": retryable,
            "retry_hint": retry_hint,
            "request_id": request_id(scope),
        },
        headers=dict(headers or {}),
    )


async def http_error_handler(request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, StarletteHTTPException):
        return error_response(request.scope, 500, "Internal server error", "internal_error")
    if isinstance(error, ApiError):
        code = error.code
        detail = error.detail if isinstance(error.detail, (dict, list)) else str(error.detail)
    else:
        code, detail = DEFAULT_ERRORS.get(error.status_code, ("http_error", "HTTP request failed"))
    # Preserve only known HTTP response semantics, not arbitrary provider headers.
    headers = {}
    for key, value in (error.headers or {}).items():
        name = key.lower()
        if (
            name == "www-authenticate"
            and value == "Bearer"
            or name == "retry-after"
            and re.fullmatch(r"[0-9]{1,5}", value)
            or name == "allow"
            and all(part.strip() in METHODS for part in value.split(","))
        ):
            headers[key] = value
    return error_response(request.scope, error.status_code, detail, code, headers=headers)


async def validation_error_handler(request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, RequestValidationError):
        return error_response(request.scope, 500, "Internal server error", "internal_error")
    # FastAPI's default error includes input/context values. Retain its detail-list
    # shape and safe field locations without reflecting submitted values or names.
    details = [
        {
            "loc": [part if part in SAFE_LOCATIONS else "field" for part in item["loc"]],
            "msg": "Invalid request field",
            "type": "request_validation",
        }
        for item in error.errors()[:16]
    ]
    return error_response(request.scope, 422, details, "validation_error")


class HttpTelemetry:
    """In-process metrics with a finite vocabulary and no default collectors."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        labels = ("operation", "method", "status_class")
        self.requests = Counter(
            "livekit_control_http_requests_total",
            "Completed local API requests",
            labels,
            registry=self.registry,
        )
        self.errors = Counter(
            "livekit_control_http_errors_total",
            "Local API requests ending in 4xx or 5xx",
            labels,
            registry=self.registry,
        )
        self.duration = Histogram(
            "livekit_control_http_request_duration_seconds",
            "Local API request duration",
            ("operation", "method"),
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
            registry=self.registry,
        )
        self.inflight = Gauge(
            "livekit_control_http_requests_in_flight",
            "Active local API requests",
            ("operation", "method"),
            registry=self.registry,
        )

    def render(self) -> bytes:
        return generate_latest(self.registry)


class TelemetryMiddleware:
    """Measure complete ASGI requests and contain unexpected pre-response failures."""

    def __init__(self, app: ASGIApp, telemetry: HttpTelemetry) -> None:
        self.app, self.telemetry = app, telemetry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        scope.setdefault("state", {})["request_id"] = secrets.token_hex(16)
        identifier = request_id(scope)
        operation = operation_for_path(scope.get("path", ""))
        raw_method = scope.get("method", "")
        method = raw_method if raw_method in METHODS else "OTHER"
        measured = operation not in EXCLUDED_OPERATIONS
        started = time.perf_counter()
        status, response_started = 500, False
        client_disconnected, returned_normally = False, False
        if measured:
            self.telemetry.inflight.labels(operation, method).inc()

        async def observe_receive() -> Message:
            nonlocal client_disconnected
            message = await receive()
            if message["type"] == "http.disconnect":
                client_disconnected = True
            return message

        async def observe(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status, response_started = message["status"], True
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", identifier.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, observe_receive, observe)
            returned_normally = True
        except asyncio.CancelledError:
            status = 499
            scope["state"]["error_code"] = "request_cancelled"
            raise
        except Exception:  # noqa: BLE001 - sanitize the outer HTTP failure boundary
            status = 500
            scope["state"]["error_code"] = "internal_error"
            if response_started:
                # A started response cannot be replaced. Let the server abort it
                # using a sanitized exception rather than private provider text.
                raise RuntimeError("Local API response failed after response start") from None
            await error_response(scope, 500, "Internal server error", "internal_error")(
                scope, receive, observe
            )
        finally:
            if returned_normally and client_disconnected and not response_started:
                # An interrupted request body never became an HTTP response. It
                # is a client disconnect, not a fabricated application 500.
                status = 499
                scope["state"]["error_code"] = "client_disconnected"
            elapsed = max(0.0, time.perf_counter() - started)
            if measured:
                self.telemetry.inflight.labels(operation, method).dec()
                status_class = f"{status // 100}xx" if 100 <= status < 600 else "other"
                self.telemetry.requests.labels(operation, method, status_class).inc()
                self.telemetry.duration.labels(operation, method).observe(elapsed)
                if status >= 400:
                    self.telemetry.errors.labels(operation, method, status_class).inc()
            if measured or status >= 400:
                severity = "error" if status >= 500 else "warning" if status >= 400 else "info"
                record = {
                    "severity": severity,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "event": "http_request_error" if status >= 400 else "http_request_completed",
                    "operation": operation,
                    "method": method,
                    "status": status,
                    "duration_seconds": round(elapsed, 6),
                    "request_id": identifier,
                }
                if code := scope["state"].get("error_code"):
                    record["code"] = code
                LOGGER.log(
                    logging.ERROR
                    if status >= 500
                    else logging.WARNING
                    if status >= 400
                    else logging.INFO,
                    json.dumps(record),
                )
