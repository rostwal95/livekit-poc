"""Bounded named dispatch that never reuses an active room for another binding."""

import asyncio

import aiohttp
from livekit import api
from livekit.protocol.agent import JobStatus
from livekit.protocol.agent_dispatch import AgentDispatch

from continuity_lab.execution_models import ExecutionError
from continuity_lab.session_grants import ConversationGrant, verify_grant

from .business import BUSINESS_AGENT_NAME
from .business_availability import NativeWorkerAvailability, NativeWorkerAvailabilityPort
from .settings import Settings


class BusinessDispatchConflict(ExecutionError):
    code = "session_in_use"


class BusinessDispatcher:
    def __init__(
        self, settings: Settings, readiness: NativeWorkerAvailabilityPort | None = None
    ) -> None:
        self.settings = settings
        self.readiness = (
            NativeWorkerAvailability(settings.business_worker_url)
            if readiness is None
            else readiness
        )
        self.lock = asyncio.Lock()

    async def dispatch(self, room: str, metadata: str) -> None:
        incoming = verify_grant(
            metadata,
            secret=self.settings.livekit_api_secret,
            room=room,
            expected_scope=self.settings.business_scope,
            expected_actor=self.settings.business_actor,
        )
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
                        departure_timeout=10,
                        max_participants=3,
                    )
                )
                existing = await client.agent_dispatch.list_dispatch(room)
                for item in existing:
                    if item.agent_name != BUSINESS_AGENT_NAME or item.state.deleted_at:
                        continue
                    prior = self._verify_binding(item, item.id, room, incoming)
                    if prior.grant_id == incoming.grant_id:
                        # A lost acknowledgement repeats the same invocation,
                        # never retires a newly admitted healthy consumer.
                        await self._wait_for_assignment(client, room, item, incoming)
                        return
                    await self._wait_for_terminal(client, room, item, incoming)
                    await client.agent_dispatch.delete_dispatch(item.id, room)
                # Observe the composed one-job worker before creating anything.
                # Actual server admission remains mandatory after this hint.
                while not await self.readiness.available():
                    await asyncio.sleep(0.05)
                created = await client.agent_dispatch.create_dispatch(
                    api.CreateAgentDispatchRequest(
                        room=room, agent_name=BUSINESS_AGENT_NAME, metadata=metadata
                    )
                )
                await self._wait_for_assignment(client, room, created, incoming)
        except (TimeoutError, api.TwirpError, aiohttp.ClientError, OSError) as error:
            raise ExecutionError("Conversational dispatch is unavailable") from error

    async def _wait_for_assignment(
        self,
        client: api.LiveKitAPI,
        room: str,
        current: AgentDispatch,
        incoming: ConversationGrant,
    ) -> None:
        """Observe one accepted job within dispatch's existing four-second budget.

        Empty records can represent a launch still in flight or a dropped request.
        Retain that uncertainty; deleting a dispatch is not a pending-launch fence.
        The browser checks actual agent presence after joining the admitted room.
        """
        dispatch_id = current.id
        while True:
            bound = self._verify_binding(current, dispatch_id, room, incoming)
            if bound.grant_id != incoming.grant_id:
                raise BusinessDispatchConflict(
                    "Room is assigned to another conversational invocation"
                )
            jobs = current.state.jobs
            if any(
                job.state.status in {JobStatus.JS_PENDING, JobStatus.JS_RUNNING}
                and job.state.worker_id
                for job in jobs
            ):
                return
            if jobs and all(
                job.state.status
                in {JobStatus.JS_SUCCESS, JobStatus.JS_FAILED, JobStatus.JS_CANCELLED}
                for job in jobs
            ):
                raise ExecutionError("Conversational dispatch ended before admission was observed")
            await asyncio.sleep(0.05)
            observed = await client.agent_dispatch.get_dispatch(dispatch_id, room)
            if observed is None:
                raise ExecutionError("Conversational dispatch admission is unknown")
            current = observed

    def _verify_binding(
        self, current: AgentDispatch, dispatch_id: str, room: str, incoming: ConversationGrant
    ) -> ConversationGrant:
        if (
            current.id != dispatch_id
            or current.room != room
            or current.agent_name != BUSINESS_AGENT_NAME
            or current.state.deleted_at
        ):
            raise ExecutionError("Conversational dispatch admission is unknown")
        try:
            bound = verify_grant(
                current.metadata,
                secret=self.settings.livekit_api_secret,
                room=room,
                expected_scope=self.settings.business_scope,
                expected_actor=self.settings.business_actor,
            )
        except ExecutionError:
            raise BusinessDispatchConflict("Room has an unresolved active binding") from None
        if bound.binding_digest() != incoming.binding_digest():
            raise BusinessDispatchConflict("Room is assigned to another conversation")
        return bound

    async def _wait_for_terminal(
        self, client: api.LiveKitAPI, room: str, current: AgentDispatch, incoming: ConversationGrant
    ) -> None:
        """Retire only a previous invocation whose known jobs have all ended."""
        dispatch_id = current.id
        terminal = {JobStatus.JS_SUCCESS, JobStatus.JS_FAILED, JobStatus.JS_CANCELLED}
        retiring_id = self._verify_binding(current, dispatch_id, room, incoming).grant_id
        while True:
            if self._verify_binding(current, dispatch_id, room, incoming).grant_id != retiring_id:
                raise BusinessDispatchConflict("Previous conversational invocation changed")
            jobs = current.state.jobs
            if not jobs:
                raise ExecutionError("Previous conversational invocation admission is unknown")
            if all(job.state.status in terminal for job in jobs):
                return
            await asyncio.sleep(0.05)
            observed = await client.agent_dispatch.get_dispatch(dispatch_id, room)
            if observed is None:
                raise ExecutionError("Previous conversational invocation completion is unknown")
            current = observed
