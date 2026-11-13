"""Local operator API; no production authentication or business execution claims."""

import asyncio
import secrets
import sqlite3
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date, timedelta
from typing import Annotated, Protocol
from urllib.parse import urlsplit, urlunsplit

import aiohttp
import httpx
import psycopg
from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from livekit import api
from livekit.protocol.agent import JobStatus
from livekit.protocol.agent_dispatch import AgentDispatch
from prometheus_client import CONTENT_TYPE_LATEST
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from continuity_lab.authorization import AuthenticatedActor, BearerToken
from continuity_lab.conversation_composition import build_conversation_service
from continuity_lab.conversation_service import AsyncConversationService
from continuity_lab.models import (
    BookingChange,
    IdempotencyConflict,
    IntakeCapacityExceeded,
)
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.sqlite_admission import SourceAdmissionClosed
from continuity_lab.store import TaskStore
from continuity_lab.tracing import TraceRuntime, TraceSettings

from .business import BusinessDispatchPort, install_business_routes
from .business_dispatch import BusinessDispatcher
from .settings import AGENT_NAME, SCOPE_ID, Settings
from .telemetry import (
    ApiError,
    HttpTelemetry,
    TelemetryMiddleware,
    error_response,
    http_error_handler,
    validation_error_handler,
)

TOKEN_TTL_SECONDS = 300
MAX_BODY_BYTES = 16_384
MAX_DATABASE_BYTES = 8 * 1024 * 1024
TERMINAL_JOB_STATUSES = frozenset(
    {JobStatus.JS_SUCCESS, JobStatus.JS_FAILED, JobStatus.JS_CANCELLED}
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionRequest(StrictModel):
    room: str = Field(pattern=r"^lab-[a-z0-9][a-z0-9-]{0,47}$")
    identity: str = Field(pattern=r"^(?:browser|smoke)-[a-z0-9][a-z0-9-]{0,47}$")
    dispatch_agent: bool = Field(default=True, strict=True)


class SessionResponse(StrictModel):
    url: str
    token: str
    room: str
    identity: str
    expires_in: int
    agent_name: str
    agent_dispatched: bool


class InvestigationRequest(StrictModel):
    booking_reference: str = Field(min_length=1, max_length=64)
    new_check_in: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    confirmed: bool = Field(strict=True)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("confirmed")
    @classmethod
    def investigation_confirmation(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Explicit investigation confirmation is required")
        return value

    @field_validator("new_check_in")
    @classmethod
    def valid_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value


class BodyLimitMiddleware:
    """Bound request accumulation before JSON parsing, including chunked input."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
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

        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


class BoundedIO:
    """Hold capacity until a thread finishes, even if its HTTP caller disconnects."""

    def __init__(self, limit: int = 4):
        self.slots = asyncio.Semaphore(limit)
        self.pending: set[asyncio.Task] = set()

    async def run(self, function: Callable, *args, **kwargs):
        try:
            await asyncio.wait_for(self.slots.acquire(), timeout=0.05)
        except TimeoutError as error:
            raise ApiError(
                503,
                "Local I/O capacity exhausted",
                code="capacity_exhausted",
                headers={"Retry-After": "1"},
            ) from error
        task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        self.pending.add(task)

        def complete(finished):
            self.pending.discard(finished)
            self.slots.release()
            if not finished.cancelled():
                finished.exception()  # retrieve orphaned failures without logging data

        task.add_done_callback(complete)
        return await asyncio.shield(task)

    async def close(self):
        if self.pending:
            await asyncio.wait_for(asyncio.gather(*self.pending, return_exceptions=True), 10)


class SessionLimiter:
    def __init__(self, clock=time.monotonic, maximum=12):
        self.clock, self.maximum = clock, maximum
        self.started, self.count = clock(), 0

    def accept(self):
        now = self.clock()
        if now - self.started >= 60:
            self.started, self.count = now, 0
        if self.count >= self.maximum:
            raise ApiError(
                429,
                "Local session rate limit",
                code="rate_limited",
                headers={"Retry-After": "60"},
            )
        self.count += 1


class DispatchUnavailable(RuntimeError):
    """The configured transport agent could not be dispatched."""


class Backend(Protocol):
    async def dispatch(self, room: str) -> None: ...


class LiveKitBackend:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.lock = asyncio.Lock()

    @staticmethod
    def _reusable(dispatch: AgentDispatch) -> bool:
        if dispatch.state.deleted_at:
            return False
        jobs = dispatch.state.jobs
        # Missing jobs/state represent a dispatch awaiting assignment. Unknown
        # future job states are conservatively treated as nonterminal as well.
        return not jobs or any(job.state.status not in TERMINAL_JOB_STATUSES for job in jobs)

    async def dispatch(self, room: str) -> None:
        # The single local control process serializes list/create to avoid routine
        # repeated browser requests dispatching duplicate diagnostic agents.
        try:
            async with (
                asyncio.timeout(4),
                self.lock,
                api.LiveKitAPI(
                    url=self.settings.livekit_url,
                    api_key=self.settings.livekit_api_key,
                    api_secret=self.settings.livekit_api_secret,
                ) as client,
            ):
                await client.room.create_room(
                    api.CreateRoomRequest(
                        name=room,
                        empty_timeout=60,
                        departure_timeout=20,
                        max_participants=6,
                    )
                )
                existing = await client.agent_dispatch.list_dispatch(room)
                matching = [item for item in existing if item.agent_name == AGENT_NAME]
                if any(self._reusable(item) for item in matching):
                    return
                for item in matching:
                    if not item.state.deleted_at:
                        # Every job is terminal. Retire only this defunct named
                        # dispatch before replacing it; native failure-restart
                        # scheduling must not later duplicate the new job.
                        await client.agent_dispatch.delete_dispatch(item.id, room)
                await client.agent_dispatch.create_dispatch(
                    api.CreateAgentDispatchRequest(room=room, agent_name=AGENT_NAME)
                )
        except (TimeoutError, api.TwirpError, aiohttp.ClientError, OSError) as error:
            raise DispatchUnavailable("Diagnostic dispatch failed") from error


async def default_readiness(settings: Settings) -> dict[str, bool]:
    async def postgres_ready():
        try:
            async with asyncio.timeout(3):
                connection = await psycopg.AsyncConnection.connect(
                    host=settings.postgres_host,
                    port=settings.postgres_port,
                    dbname=settings.postgres_db,
                    user=settings.postgres_user,
                    password=settings.postgres_password,
                    connect_timeout=2,
                )
                async with connection:
                    cursor = await connection.execute("SELECT 1")
                    return (await cursor.fetchone()) == (1,)
        except (psycopg.Error, TimeoutError, OSError):
            return False

    async def livekit_ready():
        parsed = urlsplit(settings.livekit_url)
        url = urlunsplit(
            ("https" if parsed.scheme == "wss" else "http", parsed.netloc, "/", "", "")
        )
        try:
            async with httpx.AsyncClient(timeout=2, follow_redirects=False) as client:
                result = await client.get(url)
                return result.status_code == 200
        except (httpx.HTTPError, TimeoutError, OSError):
            return False

    postgres, livekit = await asyncio.gather(postgres_ready(), livekit_ready())
    return {"postgres": postgres, "livekit": livekit}


def create_app(
    settings: Settings | None = None,
    *,
    backend: Backend | None = None,
    readiness=default_readiness,
    business: AsyncConversationService | None = None,
    business_backend: BusinessDispatchPort | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        config = settings or Settings.from_env()
        app.state.settings = config
        app.state.backend = backend or LiveKitBackend(config)
        app.state.io = BoundedIO()
        config.intake_database.parent.mkdir(parents=True, exist_ok=True)
        app.state.store = await app.state.io.run(TaskStore, config.intake_database)
        app.state.limiter = SessionLimiter()
        app.state.session_slots = asyncio.Semaphore(4)
        app.state.business = business
        app.state.business_backend = business_backend or BusinessDispatcher(config)
        app.state.business_tracing = TraceRuntime(
            TraceSettings(
                "business-api",
                config.trace_endpoint if config.business_enabled else None,
                mode=config.conversation_inference_mode,
            )
        )
        try:
            if business is None and config.business_enabled:
                app.state.business = await app.state.io.run(
                    build_conversation_service,
                    actor=AuthenticatedActor(config.business_actor, config.business_scope),
                    token=BearerToken(config.local_access_token),
                    settings=PostgresSettings.from_env(),
                    quote_database=config.business_supplier,
                )
            yield
        finally:
            try:
                if app.state.business is not None:
                    await app.state.business.close()
            finally:
                try:
                    await asyncio.wait_for(asyncio.to_thread(app.state.business_tracing.close), 3)
                finally:
                    await app.state.io.close()

    application = FastAPI(
        title="Local ecosystem control",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.telemetry = HttpTelemetry()
    application.add_middleware(BodyLimitMiddleware)
    application.add_middleware(TelemetryMiddleware, telemetry=application.state.telemetry)
    application.add_exception_handler(StarletteHTTPException, http_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    bearer = HTTPBearer(auto_error=False)

    async def authenticated(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ):
        expected = request.app.state.settings.local_access_token
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or not secrets.compare_digest(
                credentials.credentials.encode("utf-8"), expected.encode("utf-8")
            )
        ):
            raise ApiError(
                401,
                "Local operator token required",
                code="authentication_required",
                headers={"WWW-Authenticate": "Bearer"},
            )

    protected = [Depends(authenticated)]
    install_business_routes(application, authenticated)

    @application.get("/healthz")
    async def health():
        return {"status": "ok", "service": "local-control"}

    @application.get("/readyz")
    async def ready(request: Request):
        status = await readiness(request.app.state.settings)
        if not all(status.values()):
            raise ApiError(
                503,
                {"status": "not_ready", "dependencies": status},
                code="dependency_unavailable",
            )
        return {"status": "ready", "dependencies": status}

    @application.get("/api/metrics", dependencies=protected)
    async def metrics(request: Request):
        return Response(
            content=request.app.state.telemetry.render()
            + (
                request.app.state.business.service.telemetry.render()
                if request.app.state.business is not None
                else b""
            ),
            media_type=CONTENT_TYPE_LATEST,
        )

    @application.get("/api/config")
    async def config(request: Request):
        return {
            "livekit_url": request.app.state.settings.livekit_public_url,
            "agent_name": AGENT_NAME,
            "scope_id": SCOPE_ID,
            "capabilities": ["m1-investigation-intake", "deterministic-rtc-transport"],
            "inference_enabled": False,
        }

    @application.post("/api/session", response_model=SessionResponse, dependencies=protected)
    async def session(payload: SessionRequest, request: Request):
        state = request.app.state
        state.limiter.accept()
        try:
            await asyncio.wait_for(state.session_slots.acquire(), timeout=0.05)
        except TimeoutError as error:
            raise ApiError(
                503,
                "Local session capacity exhausted",
                code="capacity_exhausted",
                headers={"Retry-After": "1"},
            ) from error
        try:
            if payload.dispatch_agent:
                try:
                    await state.backend.dispatch(payload.room)
                except DispatchUnavailable:
                    raise ApiError(
                        503,
                        "Diagnostic agent dispatch unavailable",
                        code="dispatch_unavailable",
                    ) from None
            token = (
                api.AccessToken(state.settings.livekit_api_key, state.settings.livekit_api_secret)
                .with_identity(payload.identity)
                .with_ttl(timedelta(seconds=TOKEN_TTL_SECONDS))
                .with_grants(
                    api.VideoGrants(
                        room_join=True,
                        room=payload.room,
                        can_publish=True,
                        can_subscribe=True,
                        can_publish_data=True,
                    )
                )
                .to_jwt()
            )
            return SessionResponse(
                url=state.settings.livekit_public_url,
                token=token,
                room=payload.room,
                identity=payload.identity,
                expires_in=TOKEN_TTL_SECONDS,
                agent_name=AGENT_NAME,
                agent_dispatched=payload.dispatch_agent,
            )
        finally:
            state.session_slots.release()

    @application.post("/api/investigations", dependencies=protected)
    async def submit(payload: InvestigationRequest, request: Request):
        state = request.app.state
        try:
            investigation = BookingChange(
                payload.booking_reference,
                date.fromisoformat(payload.new_check_in),
                confirmed=payload.confirmed,
            )

            def persist():
                return state.store.submit(
                    scope_id=SCOPE_ID,
                    idempotency_key=payload.idempotency_key,
                    request=investigation,
                    max_database_bytes=MAX_DATABASE_BYTES,
                )

            result = await state.io.run(persist)
            return asdict(result)
        except SourceAdmissionClosed:
            raise ApiError(
                503, "SQLite source is closed after cutover", code="source_quiesced"
            ) from None
        except IntakeCapacityExceeded:
            raise ApiError(
                503, "Local intake storage limit reached", code="storage_limit_reached"
            ) from None
        except IdempotencyConflict:
            raise ApiError(
                409,
                "Idempotency key already belongs to another request",
                code="idempotency_conflict",
            ) from None
        except ValueError:
            raise ApiError(422, "Invalid investigation request", code="validation_error") from None
        except (sqlite3.Error, OSError):
            raise ApiError(
                503, "Local intake storage unavailable", code="storage_unavailable"
            ) from None

    @application.get("/api/investigations", dependencies=protected)
    async def listing(request: Request, limit: int = Query(default=50, ge=1, le=100)):
        state = request.app.state
        try:

            def read():
                return state.store.list_tasks(scope_id=SCOPE_ID, limit=limit + 1)

            tasks = await state.io.run(read)
            return {
                "scope_id": SCOPE_ID,
                "items": [asdict(item) for item in tasks[:limit]],
                "truncated": len(tasks) > limit,
            }
        except (sqlite3.Error, OSError):
            raise ApiError(
                503, "Local intake storage unavailable", code="storage_unavailable"
            ) from None

    return application


app = create_app()
