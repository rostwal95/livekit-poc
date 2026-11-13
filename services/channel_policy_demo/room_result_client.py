"""Fixed-room read-only loopback transport; import starts no I/O.

One room-view capability is immutable for one Node epoch/generation. Caller input
selects only a delivery UUID. Publisher/native credentials are never accepted as
request fields. The current-result producer owns full source/P3 applicability
joins. This client drains actual TCP I/O, not mode-G global Node SQL ownership.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, cast

from ._loopback_json import LoopbackJSONError, LoopbackJSONTransport, finite_error
from .current_result import CurrentResultIntent, CurrentResultObserved, CurrentResultReceipt
from .discovery import DiscoveryScope
from .wire import channel_identifier, uuid_value

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
NETWORK_SECONDS = 5.0
MAX_CALLS = 2
MAX_RESPONSE_BYTES = 32768
_MAX_COUNTER = 9007199254740991
RoomResultCode = Literal[
    "invalid_input",
    "invalid_state",
    "unauthorized",
    "capacity",
    "closed",
    "unavailable",
    "deadline_exceeded",
    "cleanup_incomplete",
]
_CODES = frozenset(
    {
        "invalid_input",
        "invalid_state",
        "unauthorized",
        "capacity",
        "closed",
        "unavailable",
        "deadline_exceeded",
        "cleanup_incomplete",
    }
)


class RoomResultError(RuntimeError):
    def __init__(self, code: RoomResultCode = "unavailable") -> None:
        self.code: RoomResultCode = code if type(code) is str and code in _CODES else "unavailable"
        super().__init__(self.code)


def _need(value: bool, code: RoomResultCode = "invalid_state") -> None:
    if not value:
        raise RoomResultError(code)


def _budget(value: float) -> float:
    _need(
        type(value) in (float, int) and 0.001 <= value <= 5 and math.isfinite(value),
        "invalid_input",
    )
    return float(value)


@dataclass(frozen=True, slots=True)
class RoomResultEndpoint:
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = 11029

    def __post_init__(self) -> None:
        _need(
            type(self.host) is str
            and self.host == "127.0.0.1"
            and type(self.port) is int
            and 1 <= self.port <= 65535,
            "invalid_input",
        )


@dataclass(frozen=True, slots=True)
class RoomResultBinding:
    node_epoch: str
    generation: str

    def __post_init__(self) -> None:
        try:
            uuid_value(self.node_epoch)
            _need(
                type(self.generation) is str
                and re.fullmatch(r"[1-9][0-9]{0,6}", self.generation, re.ASCII) is not None
                and int(self.generation) <= 1000000,
                "invalid_input",
            )
        except Exception:  # noqa: BLE001 - fixed trusted configuration diagnostics
            raise RoomResultError("invalid_input") from None


@dataclass(frozen=True, slots=True)
class RoomViewCredential:
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        _need(
            type(self.value) is str
            and re.fullmatch(r"[A-Za-z0-9_-]{43}", self.value, re.ASCII) is not None,
            "invalid_input",
        )


def _pairs(values: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in values:
        _need(key not in out)
        out[key] = value
    return out


def _invalid_number(_: str) -> object:
    raise RoomResultError("invalid_state")


def _tree(value: object, depth: int, budget: list[int]) -> None:
    budget[0] -= 1
    _need(depth <= 12 and budget[0] >= 0)
    if type(value) is str:
        value.encode("utf-8", "strict")
    elif value is None or type(value) in (bool, int):
        return
    elif type(value) is list:
        _need(len(cast(list[object], value)) <= 64)
        for item in cast(list[object], value):
            _tree(item, depth + 1, budget)
    elif type(value) is dict:
        _need(len(cast(dict[str, object], value)) <= 64)
        for key, item in cast(dict[str, object], value).items():
            _tree(key, depth + 1, budget)
            _tree(item, depth + 1, budget)
    else:
        raise RoomResultError("invalid_state")


def _decode(raw: bytes, maximum: int) -> object:
    _need(type(raw) is bytes and 0 < len(raw) <= maximum)
    try:
        value: object = json.loads(
            raw.decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_invalid_number
        )
        _tree(value, 0, [4096])
        return value
    except (UnicodeError, ValueError, RecursionError):
        raise RoomResultError("invalid_state") from None


def _fields(value: object, keys: set[str]) -> dict[str, object]:
    _need(type(value) is dict and set(value) == keys)
    return cast(dict[str, object], value)


def _view(raw: bytes, delivery_id: str) -> bytes | None:
    if raw == b"null":
        return None
    try:
        value = _fields(
            _decode(raw, MAX_RESPONSE_BYTES),
            {"schemaVersion", "intent", "receipt", "case", "observed"},
        )
        _need(type(value["schemaVersion"]) is int and value["schemaVersion"] == 1)
        intent = _fields(
            value["intent"],
            {
                "delivery_id",
                "scope",
                "work_id",
                "attempt_id",
                "result_sha256",
                "receiver_id",
                "recipient_id",
                "body",
                "prepared_at_ms",
            },
        )
        scope = _fields(intent["scope"], {"tenant_id", "account_id"})
        copied_intent = CurrentResultIntent(
            cast(str, intent["delivery_id"]),
            DiscoveryScope(cast(str, scope["tenant_id"]), cast(str, scope["account_id"])),
            cast(str, intent["work_id"]),
            cast(str, intent["attempt_id"]),
            cast(str, intent["result_sha256"]),
            cast(str, intent["receiver_id"]),
            cast(str, intent["recipient_id"]),
            cast(str, intent["body"]),
            cast(int, intent["prepared_at_ms"]),
        )
        receipt = _fields(
            value["receipt"],
            {
                "delivery_id",
                "receipt_id",
                "receiver_id",
                "recipient_id",
                "result_sha256",
                "accepted_at_ms",
            },
        )
        copied_receipt = CurrentResultReceipt(
            cast(str, receipt["delivery_id"]),
            cast(str, receipt["receipt_id"]),
            cast(str, receipt["receiver_id"]),
            cast(str, receipt["recipient_id"]),
            cast(str, receipt["result_sha256"]),
            cast(int, receipt["accepted_at_ms"]),
        )
        _need(
            copied_intent.delivery_id == delivery_id
            and (
                copied_intent.delivery_id,
                copied_intent.receiver_id,
                copied_intent.recipient_id,
                copied_intent.result_sha256,
            )
            == (
                copied_receipt.delivery_id,
                copied_receipt.receiver_id,
                copied_receipt.recipient_id,
                copied_receipt.result_sha256,
            )
        )
        case = _fields(
            value["case"],
            {
                "schemaVersion",
                "source",
                "scope",
                "caseId",
                "conversationId",
                "revision",
                "request",
                "workflow",
                "intent",
                "mutation",
                "supplierResult",
                "sourceRevision",
            },
        )
        _need(
            type(case["schemaVersion"]) is int
            and case["schemaVersion"] == 1
            and case["source"] == "p1_public_v4"
        )
        case_scope = _fields(case["scope"], {"tenantId", "accountId"})
        _need(
            case_scope
            == {
                "tenantId": copied_intent.scope.tenant_id,
                "accountId": copied_intent.scope.account_id,
            }
        )
        channel_identifier(case["caseId"])
        channel_identifier(case["conversationId"])
        _need(
            type(case["revision"]) is str
            and re.fullmatch(r"0|[1-9][0-9]{0,18}", case["revision"], re.ASCII) is not None
            and int(case["revision"]) <= 9223372036854775807
        )
        observed = _fields(
            value["observed"], {"p2ObservedAt", "caseObservedAt", "disclosureAdmittedAt", "atomic"}
        )
        CurrentResultObserved(
            cast(str, observed["p2ObservedAt"]),
            cast(str, observed["caseObservedAt"]),
            cast(str, observed["disclosureAdmittedAt"]),
            cast(Literal[False], observed["atomic"]),
        )
        return raw
    except Exception:  # noqa: BLE001 - full authority validation remains producer-owned
        raise RoomResultError("invalid_state") from None


def _error(raw: bytes, status: int) -> RoomResultError:
    try:
        obj = _fields(_decode(raw, 4096), {"schemaVersion", "status", "code"})
        _need(
            type(obj["schemaVersion"]) is int
            and obj["schemaVersion"] == 1
            and obj["status"] == "unavailable"
        )
        allowed = {
            400: {"invalid_input"},
            401: {"unauthorized"},
            409: {"conflict", "recovery_required"},
            429: {"capacity"},
            503: {"closed", "unavailable", "outcome_unknown", "cleanup_incomplete"},
        }
        code = obj["code"]
        _need(type(code) is str and code in allowed[status])
        return RoomResultError(cast(RoomResultCode, code) if code in _CODES else "unavailable")
    except Exception:  # noqa: BLE001 - malformed operational errors never become absence
        return RoomResultError()


def _network_budget() -> float:
    return NETWORK_SECONDS


def _room_event(code: str) -> None:
    LOGGER.info("channel_policy_room_result", extra={"event": "read", "code": code})


class RoomResultHttpClient:
    """Fixed room facade borrowing one private retained exchange owner.

    Domain validation and semantic counters remain inside the actual call, even
    after waiter abandonment. close drains TCP ownership, not global Node SQL.
    """

    def __init__(
        self,
        endpoint: RoomResultEndpoint,
        binding: RoomResultBinding,
        credential: RoomViewCredential,
        *,
        timeout_s: float = 1,
        cleanup_timeout_s: float = 1,
    ) -> None:
        try:
            _need(
                type(endpoint) is RoomResultEndpoint
                and type(binding) is RoomResultBinding
                and type(credential) is RoomViewCredential,
                "invalid_input",
            )
            self._endpoint = RoomResultEndpoint(endpoint.host, endpoint.port)
            self._binding = RoomResultBinding(binding.node_epoch, binding.generation)
            cap = RoomViewCredential(credential.value)
            self._transport = LoopbackJSONTransport(
                port=self._endpoint.port,
                bearer=cap.value,
                purpose="native_result",
                timeout_s=timeout_s,
                cleanup_timeout_s=cleanup_timeout_s,
                observer=_room_event,
                network_budget=_network_budget,
            )
        except Exception:  # noqa: BLE001 - fixed trusted configuration errors
            raise RoomResultError("invalid_input") from None

    @property
    def pending_count(self) -> int:
        return self._transport.pending_count

    def metrics(self) -> MappingProxyType[str, int]:
        return self._transport.metrics()

    async def read(self, *, delivery_id: str) -> bytes | None:
        try:
            delivery = uuid_value(delivery_id)
            body = json.dumps(
                {
                    "schemaVersion": 1,
                    "nodeEpoch": self._binding.node_epoch,
                    "generation": self._binding.generation,
                    "deliveryId": delivery,
                },
                separators=(",", ":"),
            ).encode("ascii")

            def decode(status: int, raw: bytes) -> bytes | None:
                try:
                    if status != 200:
                        raise _error(raw, status)
                    return _view(raw, delivery)
                except RoomResultError as error:
                    raise finite_error(error) from None

            return await self._transport.exchange_decoded(body, decoder=decode)
        except asyncio.CancelledError:
            raise
        except LoopbackJSONError as error:
            safe = finite_error(error)
            raise RoomResultError(safe.code) from None
        except Exception:  # noqa: BLE001 - original input cannot enter diagnostics
            raise RoomResultError("invalid_input") from None

    async def close(self) -> None:
        try:
            await self._transport.close()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - fixed cleanup boundary
            safe = finite_error(error)
            raise RoomResultError(safe.code) from None
