"""Server-verified native tool composition; no model-supplied business authority."""

from __future__ import annotations

import asyncio
import os
import secrets
from collections.abc import Awaitable, Callable
from uuid import NAMESPACE_URL, uuid5

from livekit.agents import AgentSession, JobContext

from continuity_lab.postgres_api import (
    AuthenticatedActor,
    BearerToken,
    ManagedCaseClient,
    PostgresSettings,
    open_postgres_client,
)
from continuity_lab.session_grants import ConversationGrant, verify_grant
from continuity_lab.tracing import TraceRuntime, TraceSettings

from .observations import SessionObserver
from .session import BusinessPort, ConversationBinding, Receipt

OPERATION_TIMEOUT_SECONDS = 7


class SessionBusinessPort:
    """Freeze identity, consent and replay key before entering a native tool."""

    def __init__(self, client: ManagedCaseClient, grant: ConversationGrant) -> None:
        self._client, self._grant = client, grant
        self._task_id = grant.task_id
        self._submit_issued = False
        self._closed = False
        self._lock = asyncio.Lock()
        self._tracing: TraceRuntime | None = None
        self._cancel_command = str(
            uuid5(NAMESPACE_URL, "continuity:conversation-cancel:" + grant.grant_id)
        )

    def attach_tracing(self, tracing: TraceRuntime) -> None:
        self._tracing = tracing

    async def _run(self, operation: str, action: Callable[[], Awaitable[Receipt]]) -> Receipt:
        if self._closed:
            raise RuntimeError("The conversation port has closed")
        async with asyncio.timeout(OPERATION_TIMEOUT_SECONDS):
            async with self._lock:
                if self._tracing is None:
                    return await action()
                with self._tracing.span(operation) as span:
                    result = await action()
                    task = result.get("task_id")
                    if type(task) is str:
                        span.set_attribute("continuity.task_id", task)
                    return result

    @staticmethod
    def _summary(value: dict[str, object]) -> Receipt:
        inquiry, lifecycle = value["inquiry"], value["lifecycle"]
        assert isinstance(inquiry, dict) and isinstance(lifecycle, dict)
        return {
            "schema_version": 1,
            "task_id": value["task_id"],
            "case_revision": value["case_revision"],
            "inquiry_state": inquiry["state"],
            "lifecycle_state": lifecycle["state"],
            "has_proposal": value["quote"] is not None,
            "has_outcome": value["outcome"] is not None,
            "approval_channel": "authenticated_workflow_panel",
        }

    async def _submit(self) -> Receipt:
        self._submit_issued = True
        accepted = await self._client.submit(
            idempotency_key=self._grant.request_key,
            request=self._grant.request,
        )
        result = self._summary(accepted.projection.payload())
        self._task_id = str(result["task_id"])
        return result

    async def _owned_task(self) -> str:
        # A submit whose acknowledgement was lost may still have committed; only
        # the idempotent frozen replay can identify its original task.
        return self._task_id or str((await self._submit())["task_id"])

    async def submit_investigation(self) -> Receipt:
        return await self._run("submit", self._submit)

    async def get_case(self) -> Receipt:
        if self._task_id is None and not self._submit_issued:
            return {"schema_version": 1, "status": "not_accepted"}

        async def get() -> Receipt:
            task = await self._owned_task()
            return self._summary((await self._client.get(task_id=task)).payload())

        return await self._run("get", get)

    async def cancel_case(self) -> Receipt:
        if self._task_id is None and not self._submit_issued:
            return {"schema_version": 1, "status": "not_accepted"}

        async def cancel() -> Receipt:
            task = await self._owned_task()
            receipt = await self._client.cancel(task_id=task, command_id=self._cancel_command)
            return {"schema_version": 1, "task_id": task, "disposition": receipt.disposition.value}

        return await self._run("cancel", cancel)

    async def aclose(self) -> None:
        self._closed = True
        await self._client.close()


async def create_port(
    raw_metadata: str, room_name: str
) -> tuple[BusinessPort, ConversationBinding]:
    grant = verify_grant(
        raw_metadata,
        secret=os.environ["LIVEKIT_API_SECRET"],
        room=room_name,
        expected_scope=os.environ.get("P1_WORKER_SCOPE", "demo-traveller"),
        expected_actor="local-operator",
    )
    actor = AuthenticatedActor(grant.actor_id, grant.scope_id)
    token = BearerToken(secrets.token_urlsafe(32))
    # Startup is off the media loop. Postgres connection and statement deadlines
    # apply even if the caller stops waiting; no process-memory business queue.
    client = await asyncio.to_thread(
        open_postgres_client, actor=actor, token=token, settings=PostgresSettings.from_env()
    )
    return SessionBusinessPort(client, grant), ConversationBinding(grant.participant)


def observe_session(
    session: AgentSession[None], ctx: JobContext, mode: str = "scripted"
) -> SessionObserver:
    observer = SessionObserver(
        session,
        TraceRuntime(
            TraceSettings(
                "conversation-agent",
                os.environ.get("P1_TRACE_ENDPOINT"),
                shutdown_timeout=0.75,
                mode=mode,
            )
        ),
    )
    # Tools are typed and bound in composition. The hook uses the SDK provider
    # and session report; no request/participant metadata is serialized.
    return observer
