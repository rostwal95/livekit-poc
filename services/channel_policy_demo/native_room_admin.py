"""Explicit bounded public LiveKit admin/token adapter; no session ownership in Parent.

Construction is inert and reads no environment. API room operations are never
retried. Unknown create/delete acknowledgement is distinct from absence; the
controller reconciles only the original owned name/metadata/SID.
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import re
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from .native_room_state import NativeRoomError, RoomIdentity, _identifier, utc_time
from .native_worker_config import validate_livekit_url

if TYPE_CHECKING:
    import aiohttp
    from livekit import api

_T = TypeVar("_T")
NETWORK_SECONDS = 4.0


@dataclass(frozen=True, slots=True)
class LiveKitAdminSettings:
    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)
    url: str = "http://127.0.0.1:17880"

    def __post_init__(self) -> None:
        try:
            if (
                type(self.api_key) is not str
                or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.api_key, re.ASCII) is None
                or type(self.api_secret) is not str
                or not 1 <= len(self.api_secret.encode("utf-8", "strict")) <= 512
                or "\0" in self.api_secret
            ):
                raise ValueError
            validate_livekit_url(self.url, scheme="http")
        except Exception:  # noqa: BLE001 - finite SDK boundary; independent actual owners remain retained
            raise NativeRoomError("invalid_input") from None

    @property
    def rtc_url(self) -> str:
        # Derive the worker/browser endpoint from exactly the validated admin
        # host port; never fall back to the container's internal listener port.
        return "ws" + validate_livekit_url(self.url, scheme="http")[4:]


@dataclass(frozen=True, slots=True)
class RoomPresence:
    state: Literal["absent", "owned", "foreign"]
    as_of: str
    room: RoomIdentity | None = None

    def __post_init__(self) -> None:
        utc_time(self.as_of)
        if (
            type(self.state) is not str
            or self.state not in {"absent", "owned", "foreign"}
            or (self.state == "owned") != (self.room is not None)
        ):
            raise NativeRoomError("invalid_input")
        if self.room is not None and (type(self.room) is not RoomIdentity or self.room.sid is None):
            raise NativeRoomError("invalid_input")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _copy(identity: RoomIdentity) -> RoomIdentity:
    if type(identity) is not RoomIdentity:
        raise NativeRoomError("invalid_input")
    return RoomIdentity(identity.name, identity.metadata, identity.sid)


def _spawn(operation: Coroutine[Any, Any, _T], *, cleanup: bool = False) -> asyncio.Task[_T]:
    try:
        task = asyncio.create_task(operation, eager_start=False)
    except BaseException as error:
        operation.close()
        if isinstance(error, Exception):
            raise NativeRoomError("cleanup_incomplete" if cleanup else "unavailable") from None
        raise
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return task


class LiveKitRoomAdmin:
    """Own a bounded HTTP session; at most two actual calls survive waiter loss.

    list/create/delete are explicit methods with no automatic business retries.
    The SDK receives explicit credentials and failover=False. Observed SID and
    metadata checks are as-of checks: DeleteRoom accepts a name, not a SID CAS.
    The parent serializes its one lifecycle and never claims a stronger fence.
    """

    def __init__(
        self, settings: LiveKitAdminSettings, *, timeout_s: float = 4, cleanup_timeout_s: float = 1
    ) -> None:
        if type(settings) is not LiveKitAdminSettings:
            raise NativeRoomError("invalid_input")
        self._settings = LiveKitAdminSettings(settings.api_key, settings.api_secret, settings.url)
        for value in (timeout_s, cleanup_timeout_s):
            if (
                type(value) not in (int, float)
                or not 0.02 <= value <= 4
                or not math.isfinite(value)
            ):
                raise NativeRoomError("invalid_input")
        self._timeout, self._cleanup = float(timeout_s), float(cleanup_timeout_s)
        self._api: api.LiveKitAPI | None = None
        self._session: aiohttp.ClientSession | None = None
        self._connector: aiohttp.TCPConnector | None = None
        self._calls: set[asyncio.Task[Any]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._settle_task: asyncio.Task[None] | None = None
        self._closing = False

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise NativeRoomError("invalid_input")
        self._loop = loop
        return loop

    @property
    def pending_count(self) -> int:
        return len(self._calls)

    def _ensure(self) -> api.LiveKitAPI:
        import aiohttp
        from livekit import api

        self._bind()
        if self._closing:
            raise NativeRoomError("closed")
        if self._api is None:
            if self._connector is None:
                self._connector = aiohttp.TCPConnector(limit=2, limit_per_host=2)
            if self._session is None:
                self._session = aiohttp.ClientSession(
                    connector=self._connector, timeout=aiohttp.ClientTimeout(total=4)
                )
            # Session is registered before the next potentially failing factory.
            self._api = api.LiveKitAPI(
                self._settings.url,
                self._settings.api_key,
                self._settings.api_secret,
                session=self._session,
                failover=False,
            )
        return self._api

    async def _actual(self, operation: Coroutine[Any, Any, _T]) -> _T:
        # The pinned SDK passes timeout=None to aiohttp, which overrides the
        # session default. Bound the actual public SDK task independently of a
        # shorter observer; cancellation/timeout still retains it until settled.
        async with asyncio.timeout(NETWORK_SECONDS):
            return await operation

    async def _call(self, operation: Coroutine[Any, Any, _T], *, mutating: bool) -> _T:
        self._bind()
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            operation.close()
            raise asyncio.CancelledError
        if self._closing or len(self._calls) >= 2:
            operation.close()
            raise NativeRoomError("closed" if self._closing else "capacity")
        try:
            task = _spawn(self._actual(operation))
        except BaseException:
            operation.close()
            raise
        self._calls.add(task)
        task.add_done_callback(self._calls.discard)
        try:
            async with asyncio.timeout(self._timeout):
                return await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - finite SDK boundary; independent actual owners remain retained
            raise NativeRoomError("outcome_unknown" if mutating else "unavailable") from None

    async def inspect(self, identity: RoomIdentity) -> RoomPresence:
        original = _copy(identity)

        async def actual() -> RoomPresence:
            from livekit.protocol.room import ListRoomsRequest

            rooms = await self._ensure().room.list_rooms(ListRoomsRequest(names=[original.name]))
            values = tuple(rooms.rooms)
            if not values:
                return RoomPresence("absent", _now())
            if len(values) != 1:
                return RoomPresence("foreign", _now())
            found = values[0]
            if (
                found.name != original.name
                or found.metadata != original.metadata
                or not found.sid
                or original.sid is not None
                and found.sid != original.sid
            ):
                return RoomPresence("foreign", _now())
            return RoomPresence(
                "owned", _now(), RoomIdentity(original.name, original.metadata, found.sid)
            )

        return await self._call(actual(), mutating=False)

    async def create(self, identity: RoomIdentity) -> RoomIdentity:
        original = _copy(identity)
        if original.sid is not None:
            raise NativeRoomError("invalid_input")

        async def actual() -> RoomIdentity:
            from livekit.protocol.room import CreateRoomRequest

            value = await self._ensure().room.create_room(
                CreateRoomRequest(
                    name=original.name,
                    metadata=original.metadata,
                    empty_timeout=180,
                    max_participants=2,
                )
            )
            if value.name != original.name or value.metadata != original.metadata or not value.sid:
                raise NativeRoomError("outcome_unknown")
            return RoomIdentity(original.name, original.metadata, value.sid)

        return await self._call(actual(), mutating=True)

    async def delete(self, identity: RoomIdentity) -> None:
        original = _copy(identity)
        if original.sid is None:
            raise NativeRoomError("invalid_input")

        async def actual() -> None:
            from livekit.protocol.room import DeleteRoomRequest

            # Caller must just have observed exact name/metadata/SID ownership.
            # The public SDK/API offers no expected-SID parameter on deletion.
            await self._ensure().room.delete_room(DeleteRoomRequest(room=original.name))

        await self._call(actual(), mutating=True)

    async def _finish_settle(self, calls: tuple[asyncio.Task[Any], ...]) -> None:
        if calls:
            await asyncio.gather(*calls, return_exceptions=True)

    async def settle(self) -> None:
        """Observe retained actual calls without issuing a new room request.

        This intentionally does not reopen admission or close the SDK/session;
        the controller can make an explicit original-name list afterwards.
        """
        self._bind()
        if self._settle_task is None or self._settle_task.done():
            self._settle_task = _spawn(self._finish_settle(tuple(self._calls)), cleanup=True)
        try:
            async with asyncio.timeout(self._cleanup):
                await asyncio.shield(self._settle_task)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - finite SDK boundary; independent actual owners remain retained
            raise NativeRoomError("cleanup_incomplete") from None

    def mint(
        self, *, room: str, identity: str, role: Literal["browser", "agent"], expires_at: str
    ) -> str:
        from livekit import api

        if self._closing:
            raise NativeRoomError("closed")
        _identifier(room)
        _identifier(identity)
        utc_time(expires_at)
        if type(role) is not str or role not in {"browser", "agent"}:
            raise NativeRoomError("invalid_input")
        deadline = datetime.fromisoformat(expires_at)
        remaining = (deadline - datetime.now(UTC)).total_seconds()
        if not 1 < remaining <= 180:
            raise NativeRoomError("closed")
        try:
            grant = api.VideoGrants(
                room_join=True,
                room=room,
                room_create=False,
                room_list=False,
                room_admin=False,
                room_record=False,
                ingress_admin=False,
                agent=False,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
                can_publish_sources=["microphone"],
                can_update_own_metadata=role == "agent",
                can_manage_agent_session=False,
            )
            token = (
                api.AccessToken(self._settings.api_key, self._settings.api_secret)
                .with_identity(identity)
                .with_kind("agent" if role == "agent" else "standard")
                .with_grants(grant)
                .with_ttl(timedelta(seconds=remaining - 1))
                .to_jwt()
            )
            # Verify the genuine SDK signature/grants first; inspect exp solely
            # to ensure the locally minted JWT never extends original expiry.
            claims = api.TokenVerifier(
                self._settings.api_key, self._settings.api_secret, leeway=timedelta(0)
            ).verify(token)
            encoded = token.split(".")[1]
            payload: object = json.loads(
                base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            )
            if (
                type(payload) is not dict
                or type(payload.get("exp")) is not int
                or payload["exp"] > int(deadline.timestamp())
                or claims.identity != identity
                or claims.video is None
                or claims.video.room != room
                or claims.video.room_join is not True
            ):
                raise ValueError
            return token
        except Exception:  # noqa: BLE001 - finite SDK boundary; independent actual owners remain retained
            raise NativeRoomError("unavailable") from None

    async def _finish_close(self) -> None:
        calls = tuple(self._calls)
        if calls:
            await asyncio.gather(*calls, return_exceptions=True)
        failed = False
        if self._api is not None:
            try:
                await self._api.aclose()
            except Exception:  # noqa: BLE001 - finite SDK boundary; independent actual owners remain retained
                failed = True
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:  # noqa: BLE001 - finite SDK boundary; independent actual owners remain retained
                failed = True
        elif self._connector is not None:
            try:
                await self._connector.close()
            except Exception:  # noqa: BLE001 - finite SDK boundary; independent actual owners remain retained
                failed = True
        if failed:
            raise NativeRoomError("cleanup_incomplete")
        self._api, self._session, self._connector = None, None, None
        self._calls.difference_update(tuple(task for task in self._calls if task.done()))
        if self._calls:
            raise NativeRoomError("cleanup_incomplete")

    async def close(self) -> None:
        self._bind()
        self._closing = True
        if (
            self._close_task is None
            or self._close_task.done()
            and (self._close_task.cancelled() or self._close_task.exception() is not None)
        ):
            self._close_task = _spawn(self._finish_close(), cleanup=True)
        try:
            async with asyncio.timeout(self._cleanup):
                await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - finite SDK boundary; independent actual owners remain retained
            raise NativeRoomError("cleanup_incomplete") from None
