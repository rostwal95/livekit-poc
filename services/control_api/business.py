"""Authenticated P1 controller HTTP boundary; model tools cannot approve quotes."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any, TypeVar

from fastapi import Depends, FastAPI, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import Response

from continuity_lab.authorization import BearerToken
from continuity_lab.case_models import MAX_INTEGER, identity
from continuity_lab.case_projection import parse_confirmation_payload
from continuity_lab.conversation_service import (
    AsyncConversationService,
    ConversationService,
    ManagedReceipt,
)
from continuity_lab.execution_models import ExecutionError
from continuity_lab.models import BookingChange, IdempotencyConflict, IntakeCapacityExceeded
from continuity_lab.tracing import TraceRuntime

from .telemetry import ApiError

T = TypeVar("T")
MAX_RESPONSE_BYTES = 65536


class StrictBusinessModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BusinessInvestigation(StrictBusinessModel):
    booking_reference: str = Field(min_length=1, max_length=64)
    new_check_in: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    confirmed: bool
    idempotency_key: str = Field(min_length=1, max_length=128)

    def domain(self) -> BookingChange:
        identity(self.idempotency_key)
        if self.confirmed is not True:
            raise ValueError("Explicit investigation authorization is required")
        return BookingChange(self.booking_reference, date.fromisoformat(self.new_check_in), True)


class QuoteCommand(StrictBusinessModel):
    expected_revision: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,18})$")
    command_id: str = Field(min_length=1, max_length=128)


class SignalCommand(StrictBusinessModel):
    confirmation_payload: str = Field(min_length=1, max_length=4096)
    explicit: bool
    command_id: str = Field(min_length=1, max_length=128)


class CancelCommand(StrictBusinessModel):
    command_id: str = Field(min_length=1, max_length=128)


def business_error(error: Exception) -> ApiError:
    if isinstance(error, IdempotencyConflict):
        return ApiError(
            409, "Request identity already has different content", code="idempotency_conflict"
        )
    if isinstance(error, IntakeCapacityExceeded):
        return ApiError(503, "Outstanding work limit reached", code="capacity_exhausted")
    if isinstance(error, ExecutionError):
        try:
            code = getattr(error, "code", "internal_error")
        except Exception:  # noqa: BLE001 - diagnostic metadata is untrusted
            code = "internal_error"
        choices = {
            "execution_not_found": 404,
            "session_in_use": 409,
            "authentication_required": 401,
            "capacity_exhausted": 503,
            "storage_unavailable": 503,
            "dependency_unavailable": 503,
            "unsupported_operation": 409,
            "stale_revision": 409,
            "transition_conflict": 409,
            "quote_expired": 409,
            "invalid_confirmation": 409,
            "case_cancelled": 409,
            "intent_committed": 409,
            "invalid_stored_state": 503,
            "schema_version_unsupported": 503,
        }
        if type(code) is str and code in choices:
            return ApiError(
                choices[code],
                "Business operation could not complete; inspect current state",
                code=code,
            )
    if isinstance(error, ValueError):
        return ApiError(422, "Invalid business request", code="validation_error")
    return ApiError(
        503,
        "Business operation unavailable; reconcile the original identity",
        code="dependency_unavailable",
    )


def response(value: dict[str, object]) -> Response:
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ApiError(
            503,
            "Projection exceeds the response budget; request a smaller page",
            code="response_too_large",
        )
    return Response(raw, media_type="application/json", headers={"Cache-Control": "no-store"})


def install_business_routes(
    application: FastAPI, authenticated: Callable[..., Awaitable[Any]]
) -> None:
    protected = [Depends(authenticated)]

    def configured(request: Request) -> tuple[AsyncConversationService, BearerToken]:
        boundary = getattr(request.app.state, "business", None)
        if boundary is None:
            raise ApiError(503, "Business workspace is offline", code="business_unavailable")
        return boundary, request.app.state.operator_token

    async def call(
        request: Request, operation: str, action: Callable[[ConversationService, BearerToken], T]
    ) -> T:
        boundary, token = configured(request)
        tracing: TraceRuntime = request.app.state.business_tracing
        try:
            route_task = request.path_params.get("task_id")
            attributes = {"continuity.task_id": route_task} if type(route_task) is str else {}
            with tracing.span(operation, **attributes) as span:
                result = await boundary.run(lambda service: action(service, token))
                if isinstance(result, ManagedReceipt):
                    span.set_attribute("continuity.task_id", result.task_id)
                return result
        except (ExecutionError, IdempotencyConflict, IntakeCapacityExceeded, ValueError) as error:
            raise business_error(error) from None

    @application.post("/api/business/investigations", dependencies=protected)
    async def submit(payload: BusinessInvestigation, request: Request) -> Response:
        try:
            domain = payload.domain()
        except ValueError:
            raise ApiError(
                422, "Explicit valid investigation input is required", code="validation_error"
            ) from None
        value = await call(
            request,
            "submit",
            lambda service, token: service.submit(
                token=token, idempotency_key=payload.idempotency_key, request=domain
            ),
        )
        return response(value.payload())

    @application.get("/api/business/cases/{task_id}", dependencies=protected)
    async def get(
        task_id: str,
        request: Request,
        cursor: str | None = Query(default=None, max_length=512),
        limit: int = Query(default=10, ge=1, le=50),
    ) -> Response:
        value = await call(
            request,
            "get",
            lambda service, token: service.get(
                token=token, task_id=task_id, cursor=cursor, limit=limit
            ),
        )
        return response(value.payload())

    @application.post("/api/business/cases/{task_id}/quote", dependencies=protected)
    async def quote(task_id: str, payload: QuoteCommand, request: Request) -> Response:
        revision = int(payload.expected_revision)
        if revision > MAX_INTEGER:
            raise ApiError(422, "Case revision is out of range", code="validation_error")
        receipt = await call(
            request,
            "quote",
            lambda service, token: service.prepare_quote(
                token=token,
                task_id=task_id,
                expected_revision=revision,
                command_id=payload.command_id,
            ),
        )
        current = await call(
            request, "get", lambda service, token: service.get(token=token, task_id=task_id)
        )
        return response(
            {
                "projection": current.payload(),
                "receipt": {
                    "command_id": payload.command_id,
                    "created": receipt.created,
                    "quote_id": receipt.quote.quote_id,
                },
            }
        )

    @application.post("/api/business/cases/{task_id}/signal", dependencies=protected)
    async def signal(task_id: str, payload: SignalCommand, request: Request) -> Response:
        try:
            confirmation = parse_confirmation_payload(
                payload.confirmation_payload, explicit=payload.explicit
            )
        except (ValueError, ExecutionError):
            raise ApiError(
                422, "An exact explicit proposal confirmation is required", code="validation_error"
            ) from None
        receipt = await call(
            request,
            "signal",
            lambda service, token: service.signal(
                token=token,
                task_id=task_id,
                confirmation=confirmation,
                command_id=payload.command_id,
            ),
        )
        current = await call(
            request, "get", lambda service, token: service.get(token=token, task_id=task_id)
        )
        return response(
            {
                "projection": current.payload(),
                "receipt": {
                    "command_id": payload.command_id,
                    "created": receipt.created,
                    "signal_id": receipt.signal_id,
                },
            }
        )

    @application.post("/api/business/cases/{task_id}/cancel", dependencies=protected)
    async def cancel(task_id: str, payload: CancelCommand, request: Request) -> Response:
        receipt = await call(
            request,
            "cancel",
            lambda service, token: service.cancel(
                token=token, task_id=task_id, command_id=payload.command_id
            ),
        )
        current = await call(
            request, "get", lambda service, token: service.get(token=token, task_id=task_id)
        )
        return response(
            {
                "projection": current.payload(),
                "receipt": {
                    "command_id": payload.command_id,
                    "created": receipt.created,
                    "cancellation_id": receipt.cancellation_id,
                    "disposition": receipt.disposition.value,
                },
            }
        )
