"""Parent-only fixed-purpose native room controls with retained actual ownership.

A waiter timeout/cancellation never means publication or revocation rolled back.
Only the parent explicitly reconciles the original epoch/generation/open request.
Two actual command/cleanup owners span all five HTTP purposes; no retry or ledger.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Literal, TypeVar, cast

from ._loopback_json import LoopbackJSONTransport, Purpose, finite_error
from .room_control import (
    RoomAttach,
    RoomAttachmentObservation,
    RoomBinding,
    RoomCommand,
    RoomControlError,
    RoomObservation,
    RoomOpen,
    RoomPublisherCredential,
    RoomRecover,
    RoomRecoveryObservation,
    encode_room_attach,
    encode_room_control,
    parse_room_attachment,
    parse_room_control_error,
    parse_room_observation,
    parse_room_recovery,
)

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
MAX_CONTROL_CALLS = 2
_MAX_COUNTER = 9007199254740991
ControlPurpose = Literal["room_open", "room_observe", "room_close", "room_recover", "room_attach"]
ControlObservation = RoomObservation | RoomRecoveryObservation | RoomAttachmentObservation
T = TypeVar("T")


def _budget(value: float) -> float:
    if type(value) not in (float, int) or not 0.001 <= value <= 5 or not math.isfinite(value):
        raise RoomControlError("invalid_input")
    return float(value)


def _spawn(action: Coroutine[object, object, T]) -> asyncio.Task[T]:
    try:
        task = asyncio.create_task(action)
    except BaseException:
        action.close()
        raise
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return task


@dataclass(eq=False, slots=True)
class _ControlCall:
    published: asyncio.Future[None]
    transport: LoopbackJSONTransport = field(repr=False)
    purpose: ControlPurpose
    task: asyncio.Task[ControlObservation] | None = field(default=None, repr=False)
    closed: bool = False
    known: ControlObservation | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class _ControlOutcome:
    value: ControlObservation | None = None
    error: RoomControlError | None = None


class RoomControlHttpClient:
    """One fixed publisher role; reads/controls never choose an arbitrary endpoint.

    The caller owns the returned client's lifetime. A validated ACK may return
    while cleanup remains owned; pending_count/close preserve that distinction.
    A fresh actual call uses the same original request bytes supplied by the
    parent. The client performs no replay, recovery or identity renewal itself.
    """

    def __init__(
        self,
        credential: RoomPublisherCredential,
        *,
        port: int = 11029,
        timeout_s: float = 1,
        cleanup_timeout_s: float = 1,
    ) -> None:
        try:
            if (
                type(credential) is not RoomPublisherCredential
                or type(port) is not int
                or not 1 <= port <= 65535
            ):
                raise RoomControlError("invalid_input")
            self._credential = RoomPublisherCredential(credential.value)
        except Exception:  # noqa: BLE001 - incomplete credential values stay private
            raise RoomControlError("invalid_input") from None
        self._port = port
        self._timeout, self._cleanup = _budget(timeout_s), _budget(cleanup_timeout_s)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._calls: set[_ControlCall] = set()
        self._closing = False
        self._close_task: asyncio.Task[None] | None = None
        self._counts = {
            "started": 0,
            "known": 0,
            "rejected": 0,
            "unknown": 0,
            "cancelled_waiters": 0,
            "timed_out_waiters": 0,
            "telemetry_failed": 0,
        }

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RoomControlError("invalid_input")
        return loop

    @property
    def pending_count(self) -> int:
        return len(self._calls)

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType(
            {
                **self._counts,
                "active": self.pending_count,
                "closing": int(self._closing),
                "cleanup_owned": sum(
                    not call.closed and call.task is not None and call.task.done()
                    for call in self._calls
                ),
            }
        )

    def _count(self, key: str) -> None:
        self._counts[key] = min(_MAX_COUNTER, self._counts[key] + 1)

    def _log(self, purpose: ControlPurpose, code: str) -> None:
        try:
            LOGGER.info("channel_policy_room_control", extra={"operation": purpose, "code": code})
        except Exception:  # noqa: BLE001 - diagnostics never grant lifecycle success
            self._count("telemetry_failed")

    async def _perform(
        self, call: _ControlCall, body: bytes, decoder: Callable[[int, bytes], ControlObservation]
    ) -> ControlObservation:
        def decode(status: int, raw: bytes) -> _ControlOutcome:
            if status != 200:
                error = parse_room_control_error(raw, status)
                self._count(
                    "rejected"
                    if error.code
                    in {
                        "invalid_input",
                        "unauthorized",
                        "conflict",
                        "capacity",
                        "recovery_required",
                    }
                    else "unknown"
                )
                return _ControlOutcome(error=error)
            try:
                value = decoder(status, raw)
            except Exception:  # noqa: BLE001 - malformed ACK remains a possible command
                self._count("unknown")
                return _ControlOutcome(error=RoomControlError("outcome_unknown"))
            call.known = value
            self._count("known")
            return _ControlOutcome(value=value)

        try:
            outcome = await call.transport.exchange_decoded(body, decoder=decode)
            if outcome.error is not None:
                raise RoomControlError(outcome.error.code)
            if outcome.value is None:
                raise RoomControlError("outcome_unknown")
            result = outcome.value
        except asyncio.CancelledError:
            raise
        except RoomControlError as error:
            self._log(call.purpose, error.code)
            raise
        except Exception as error:  # noqa: BLE001 - no raw transport/dependency diagnostics
            code = finite_error(error).code
            if code in {"capacity", "closed", "invalid_input"}:
                raise RoomControlError(code) from None
            self._count("unknown")
            self._log(call.purpose, "outcome_unknown")
            raise RoomControlError("outcome_unknown") from None
        finally:
            try:
                await call.transport.close()
                call.closed = True
            except Exception:  # noqa: BLE001 - preserve known ACK/primary and retained cleanup
                self._log(call.purpose, "cleanup_incomplete")
        self._log(call.purpose, "ok")
        return result

    async def _call(
        self,
        purpose: ControlPurpose,
        body: bytes,
        decoder: Callable[[int, bytes], ControlObservation],
    ) -> ControlObservation:
        loop = self._bind()
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise asyncio.CancelledError
        if self._closing:
            raise RoomControlError("closed")
        if len(self._calls) >= MAX_CONTROL_CALLS:
            raise RoomControlError("capacity")
        try:
            publication: asyncio.Future[None] = loop.create_future()
            transport = LoopbackJSONTransport(
                port=self._port,
                bearer=self._credential.value,
                purpose=cast(Purpose, purpose),
                timeout_s=5,
                cleanup_timeout_s=self._cleanup,
            )
        except Exception:  # noqa: BLE001 - no command has been admitted
            raise RoomControlError("unavailable") from None
        call = _ControlCall(publication, transport, purpose)
        self._calls.add(call)
        try:
            call.task = _spawn(self._perform(call, body, decoder))
        except BaseException as error:
            # The fixed transport constructor is inert; no actual exchange began.
            self._calls.discard(call)
            if isinstance(error, Exception):
                raise RoomControlError("unavailable") from None
            raise
        finally:
            publication.set_result(None)
        call.task.add_done_callback(lambda _: self._calls.discard(call) if call.closed else None)
        self._count("started")
        try:
            async with asyncio.timeout(self._timeout):
                return await asyncio.shield(call.task)
        except TimeoutError:
            self._count("timed_out_waiters")
            raise RoomControlError("outcome_unknown") from None
        except asyncio.CancelledError:
            self._count("cancelled_waiters")
            raise

    async def open(self, request: RoomOpen) -> RoomObservation:
        try:
            if type(request) is not RoomOpen or type(request.binding) is not RoomBinding:
                raise RoomControlError("invalid_input")
            snapshot = replace(request, binding=replace(request.binding))
            body = encode_room_control(snapshot)
        except Exception:  # noqa: BLE001 - malformed caller records have no diagnostics authority
            raise RoomControlError("invalid_input") from None
        command = snapshot.command()

        def decode(_status: int, raw: bytes) -> RoomObservation:
            return parse_room_observation(raw, command=command, binding=snapshot.binding)

        return cast(RoomObservation, await self._call("room_open", body, decode))

    async def attach(self, request: RoomAttach) -> RoomAttachmentObservation:
        try:
            if type(request) is not RoomAttach:
                raise RoomControlError("invalid_input")
            snapshot = replace(request)
            if snapshot.prepare_bearer == self._credential.value:
                raise RoomControlError("invalid_input")
            body = encode_room_attach(snapshot)
        except Exception:  # noqa: BLE001 - no caller record or capability escapes
            raise RoomControlError("invalid_input") from None

        def decode(_status: int, raw: bytes) -> RoomAttachmentObservation:
            return parse_room_attachment(raw, request=snapshot)

        return cast(RoomAttachmentObservation, await self._call("room_attach", body, decode))

    async def observe(self, command: RoomCommand, *, binding: RoomBinding) -> RoomObservation:
        return await self._command("room_observe", command, binding)

    async def close_room(self, command: RoomCommand, *, binding: RoomBinding) -> RoomObservation:
        return await self._command("room_close", command, binding)

    async def _command(
        self,
        purpose: Literal["room_observe", "room_close"],
        command: RoomCommand,
        binding: RoomBinding,
    ) -> RoomObservation:
        try:
            if type(command) is not RoomCommand or type(binding) is not RoomBinding:
                raise RoomControlError("invalid_input")
            snapshot, frozen_binding = replace(command), replace(binding)
            body = encode_room_control(snapshot)
        except Exception:  # noqa: BLE001 - no caller-selected body bypasses validation
            raise RoomControlError("invalid_input") from None

        def decode(_status: int, raw: bytes) -> RoomObservation:
            return parse_room_observation(raw, command=snapshot, binding=frozen_binding)

        return cast(RoomObservation, await self._call(purpose, body, decode))

    async def recover(self, request: RoomRecover) -> RoomRecoveryObservation:
        try:
            if type(request) is not RoomRecover:
                raise RoomControlError("invalid_input")
            snapshot = replace(request)
            body = encode_room_control(snapshot)
        except Exception:  # noqa: BLE001 - incomplete recovery input is not sent
            raise RoomControlError("invalid_input") from None

        def decode(_status: int, raw: bytes) -> RoomRecoveryObservation:
            return parse_room_recovery(raw, request=snapshot)

        return cast(RoomRecoveryObservation, await self._call("room_recover", body, decode))

    async def _drain(self, call: _ControlCall) -> None:
        await asyncio.shield(call.published)
        if call.task is not None:
            await asyncio.gather(asyncio.shield(call.task), return_exceptions=True)
        if not call.closed:
            await call.transport.close()
            call.closed = True
        self._calls.discard(call)

    async def _finish_close(self) -> None:
        results = await asyncio.gather(
            *(self._drain(call) for call in tuple(self._calls)), return_exceptions=True
        )
        if any(isinstance(result, BaseException) for result in results) or self._calls:
            raise RoomControlError("cleanup_incomplete")

    async def close(self) -> None:
        self._bind()
        self._closing = True
        if (
            self._close_task is not None
            and self._close_task.done()
            and (self._close_task.cancelled() or self._close_task.exception() is not None)
        ):
            self._close_task = None
        if self._close_task is None:
            try:
                self._close_task = _spawn(self._finish_close())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - actual command owners remain retained
                raise RoomControlError("cleanup_incomplete") from None
        try:
            async with asyncio.timeout(self._cleanup):
                await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - retry observes the same actual owners
            raise RoomControlError("cleanup_incomplete") from None
        if self._calls:
            raise RoomControlError("cleanup_incomplete")
