"""Authenticated loopback operator API for the durable booking demo."""

import asyncio
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from continuity_lab.authorization import AuthenticatedActor, BearerToken
from continuity_lab.conversation_composition import build_conversation_service
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.tracing import TraceRuntime, TraceSettings

from .business import install_business_routes
from .telemetry import (
    ApiError,
    HttpTelemetry,
    TelemetryMiddleware,
    error_response,
    http_error_handler,
    validation_error_handler,
)

MAX_BODY_BYTES = 16_384


class BodyLimitMiddleware:
    """Bound request accumulation before JSON parsing, including chunked input."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return
        body = bytearray()
        try:
            async with asyncio.timeout(5):
                while True:
                    event = await receive()
                    if event["type"] == "http.disconnect":
                        return
                    chunk = event.get("body", b"")
                    if len(body) + len(chunk) > MAX_BODY_BYTES:
                        await error_response(
                            scope, 413, "Request body too large", "request_too_large"
                        )(scope, receive, send)
                        return
                    body.extend(chunk)
                    if not event.get("more_body", False):
                        break
        except TimeoutError:
            await error_response(scope, 408, "Request body timeout", "request_timeout")(
                scope, receive, send
            )
            return
        consumed = False

        async def replay() -> Message:
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    token = BearerToken(os.environ["LOCAL_ACCESS_TOKEN"])
    actor = AuthenticatedActor(
        "local-operator", os.environ.get("P1_WORKER_SCOPE", "demo-traveller")
    )
    supplier = Path(os.environ.get("P1_BUSINESS_SUPPLIER_DB", "/business/supplier.sqlite3"))
    tracing = TraceRuntime(TraceSettings("business-api", None, mode="scripted"))
    try:
        business = await asyncio.to_thread(
            build_conversation_service,
            actor=actor,
            token=token,
            settings=PostgresSettings.from_env(),
            quote_database=supplier,
        )
        application.state.operator_token = token
        application.state.business = business
        application.state.business_tracing = tracing
        try:
            yield
        finally:
            await business.close()
    finally:
        await asyncio.to_thread(tracing.close)


app = FastAPI(
    title="Continuity demo operator",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(BodyLimitMiddleware)
app.add_middleware(TelemetryMiddleware, telemetry=HttpTelemetry())
app.add_exception_handler(StarletteHTTPException, http_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
bearer = HTTPBearer(auto_error=False)


async def authenticated(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    token: BearerToken = request.app.state.operator_token
    if credentials is not None and secrets.compare_digest(
        credentials.credentials.encode("utf-8"), token.value.encode("utf-8")
    ):
        return
    raise ApiError(
        401,
        "Local operator key required",
        code="authentication_required",
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "ok"}


install_business_routes(app, authenticated)
