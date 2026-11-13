"""Authenticated operator composition over borrowed public application ports.

HTTP owns bounded actual exchange tasks. End changes only the room lifecycle;
the separately authorized synthetic SMS and read ports remain available.
"""

from __future__ import annotations

from inspect import getattr_static
from typing import Protocol, cast

from .current_result import CurrentResultObservation
from .native_room_state import (
    BrowserRoomGrant,
    EndCommand,
    NativeRoomStatus,
    StartCommand,
    parse_end_command,
    parse_start_command,
)
from .operator_contract import (
    OPERATOR_CODES,
    REQUEST_BYTES,
    CaseObservation,
    OperatorCode,
    OperatorError,
    ProgressObservation,
    SmsCommand,
    SmsObservation,
    decode,
    encode,
    fields,
    parse_empty,
    parse_sms_command,
    require,
)
from .worker_current_result import current_result_fact

OPERATIONS = frozenset({"status", "start", "end", "current", "case", "progress", "sms"})


class RoomOperatorPort(Protocol):
    def status(self) -> NativeRoomStatus: ...
    def is_current(self, command: EndCommand) -> bool: ...
    async def start(self, command: StartCommand) -> BrowserRoomGrant: ...
    async def end(self, command: EndCommand) -> NativeRoomStatus: ...
    async def read_current(self, command: EndCommand) -> CurrentResultObservation: ...


class ApplicationObservationPort(Protocol):
    async def observe_case(self) -> CaseObservation: ...
    async def observe_progress(self) -> ProgressObservation: ...


class SmsOperatorPort(Protocol):
    async def send(self, command: SmsCommand) -> SmsObservation: ...


def operator_error(error: BaseException) -> OperatorError:
    try:
        value = getattr_static(error, "code", None)
    except Exception:  # noqa: BLE001 - no dependency property or message is serialized
        value = None
    return OperatorError(
        cast(OperatorCode, value)
        if type(value) is str and value in OPERATOR_CODES
        else "unavailable"
    )


class ChannelPolicyOperator:
    """Seven closed operations; no client-selected principal, work or route.

    This facade owns no dependency and has no close authority. The Parent closes
    its HTTP host before the SMS/room owners and shared background application.
    """

    def __init__(
        self, rooms: RoomOperatorPort, app: ApplicationObservationPort, sms: SmsOperatorPort
    ) -> None:
        self._rooms, self._app, self._sms = rooms, app, sms

    def response_is_current(self, raw: bytes) -> bool:
        """Synchronous last-write fence for a grant or current-result response."""
        value = decode(raw, 16384)
        require(type(value) is dict, "unavailable")
        data = cast(dict[str, object], value)
        if "rtc" not in data and "fact" not in data:
            return True
        command = parse_end_command(
            encode(
                {
                    "schemaVersion": 1,
                    "ownerEpoch": data.get("ownerEpoch"),
                    "generation": data.get("generation"),
                    "originalStartCommandId": data.get("originalStartCommandId"),
                }
            )
        )
        current = self._rooms.is_current(command)
        require(type(current) is bool, "unavailable")
        return current

    async def exchange(self, raw: bytes) -> bytes:
        # The loopback server supplies this small internal route envelope. The
        # nested request still goes through its exact public decoder.
        try:
            value = fields(decode(raw, REQUEST_BYTES + 128), {"operation", "request"})
            operation = value["operation"]
            require(type(operation) is str and operation in OPERATIONS)
            request = encode(value["request"], REQUEST_BYTES)
            if operation == "start":
                grant = await self._rooms.start(parse_start_command(request))
                require(type(grant) is BrowserRoomGrant, "unavailable")
                response = encode(grant.payload())
            elif operation == "end":
                status = await self._rooms.end(parse_end_command(request))
                require(type(status) is NativeRoomStatus, "unavailable")
                response = encode(status.payload())
            elif operation == "current":
                command = parse_end_command(request)
                observed = await self._rooms.read_current(command)
                fact = current_result_fact(observed)
                response = encode(
                    {
                        "schemaVersion": 1,
                        "ownerEpoch": command.owner_epoch,
                        "generation": command.generation,
                        "originalStartCommandId": command.original_start_command_id,
                        "fact": decode(fact.summary().encode()),
                    }
                )
            elif operation == "sms":
                command_sms = parse_sms_command(request)
                receipt = await self._sms.send(command_sms)
                require(
                    type(receipt) is SmsObservation
                    and receipt.command_id == command_sms.command_id,
                    "unavailable",
                )
                response = encode(receipt.payload())
            else:
                parse_empty(request)
                if operation == "status":
                    status = self._rooms.status()
                    require(type(status) is NativeRoomStatus, "unavailable")
                    response = encode(status.payload())
                elif operation == "case":
                    case = await self._app.observe_case()
                    require(type(case) is CaseObservation, "unavailable")
                    response = encode(case.payload())
                else:
                    progress = await self._app.observe_progress()
                    require(type(progress) is ProgressObservation, "unavailable")
                    response = encode(progress.payload())
            require(self.response_is_current(response), "closed")
            return response
        except OperatorError:
            raise
        except Exception as error:  # noqa: BLE001 - one finite outer public-command boundary
            raise operator_error(error) from None
