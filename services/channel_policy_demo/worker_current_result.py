"""One worker's fixed current-result callback and bounded model fact projection.

Only a fresh per-room callback capability is held here. No P1, publisher,
worker-discovery or Node room-view credential is accepted. Parent owns current
applicability; this consumer validates its route and result metadata, not evidence
or perpetual permission. Imports start no I/O and do not load the native SDK.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Literal, Protocol, cast
from uuid import UUID

from delegation_reliability import (
    channel_policy_key,
    encode_channel_policy_result,
    parse_channel_policy_result,
)

from ._loopback_json import LoopbackCode, LoopbackJSONError, LoopbackJSONTransport, finite_error
from .current_result import (
    CurrentResultObservation,
    encode_current_result_observation,
    parse_current_result_observation,
)
from .worker_client import WorkerBinding

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
FACT_BYTES = 1024
WorkerCurrentCode = LoopbackCode


class WorkerCurrentResultError(RuntimeError):
    def __init__(self, code: WorkerCurrentCode = "unavailable") -> None:
        self.code = finite_error(LoopbackJSONError(code)).code
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class WorkerCurrentEndpoint:
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = 11031

    def __post_init__(self) -> None:
        if (
            type(self.host) is not str
            or self.host != "127.0.0.1"
            or type(self.port) is not int
            or not 1 <= self.port <= 65535
        ):
            raise WorkerCurrentResultError("invalid_input")


@dataclass(frozen=True, slots=True)
class CurrentResultCredential:
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.value) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{43}", self.value, re.ASCII) is None
        ):
            raise WorkerCurrentResultError("invalid_input")


class WorkerCurrentResultReadPort(Protocol):
    async def read(self) -> CurrentResultObservation: ...


@dataclass(frozen=True, slots=True)
class CurrentResultFact:
    state: Literal["current", "no_delivery", "not_applicable", "unavailable"]
    eligible: bool | None
    uncertainty: Literal["none", "missing", "conflicting"] | None
    revision: str | None
    as_of: str | None

    def __post_init__(self) -> None:
        _valid_fact(self)

    def summary(self) -> str:
        """Only finite result facts; no body/source IDs/credentials/tools."""
        _valid_fact(self)
        text = json.dumps(
            {
                "state": self.state,
                "eligible": self.eligible,
                "uncertainty": self.uncertainty,
                "revision": self.revision,
                "asOf": self.as_of,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(text.encode("utf-8")) > FACT_BYTES:
            raise WorkerCurrentResultError("invalid_state")
        return text


def _valid_fact(value: CurrentResultFact) -> None:
    if (
        type(value) is not CurrentResultFact
        or type(value.state) is not str
        or value.state not in {"current", "no_delivery", "not_applicable", "unavailable"}
    ):
        raise WorkerCurrentResultError("invalid_state")
    if value.state != "current":
        if (
            value.eligible is not None
            or value.uncertainty is not None
            or value.revision is not None
        ):
            raise WorkerCurrentResultError("invalid_state")
    else:
        if value.eligible is not None and type(value.eligible) is not bool:
            raise WorkerCurrentResultError("invalid_state")
        if type(value.uncertainty) is not str or value.uncertainty not in {
            "none",
            "missing",
            "conflicting",
        }:
            raise WorkerCurrentResultError("invalid_state")
        if (
            type(value.revision) is not str
            or re.fullmatch(r"[1-9][0-9]{0,18}", value.revision, re.ASCII) is None
            or int(value.revision) > 9223372036854775807
        ):
            raise WorkerCurrentResultError("invalid_state")
        if (value.uncertainty == "none") != (value.eligible is not None):
            raise WorkerCurrentResultError("invalid_state")
    if value.state == "unavailable":
        if value.as_of is not None:
            raise WorkerCurrentResultError("invalid_state")
    else:
        # Public codec supplies strict UTC millisecond observation timestamps.
        if (
            type(value.as_of) is not str
            or re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z",
                value.as_of,
                re.ASCII,
            )
            is None
        ):
            raise WorkerCurrentResultError("invalid_state")
        try:
            if (
                datetime.fromisoformat(value.as_of)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
                != value.as_of
            ):
                raise ValueError
        except ValueError:
            raise WorkerCurrentResultError("invalid_state") from None


def unavailable_fact() -> CurrentResultFact:
    return CurrentResultFact("unavailable", None, None, None, None)


def current_result_fact(value: CurrentResultObservation) -> CurrentResultFact:
    """Validate public result metadata joins before selecting five bounded facts.

    Evidence/deadline/current-grant checks stay with the trusted Parent producer.
    This projection carries its as-of observation and grants no action permission.
    """
    try:
        copied = parse_current_result_observation(encode_current_result_observation(value))
        if copied.state != "current":
            return CurrentResultFact(
                copied.state,
                None,
                None,
                None,
                copied.read_completed_at,
            )
        projection = copied.result
        if projection is None:
            raise WorkerCurrentResultError("invalid_state")
        body = base64.b64decode(projection.intent.body, validate=True)
        result = parse_channel_policy_result(body)
        inner = result.result
        if encode_channel_policy_result(result) != body or (
            inner.scope.tenant_id,
            inner.scope.account_id,
            inner.case_id,
            inner.request_revision,
            inner.delegation_id,
            inner.attempt_id,
        ) != (
            copied.scope.tenant_id,
            copied.scope.account_id,
            copied.case_id,
            int(projection.case.revision),
            channel_policy_key(projection.operation_key),
            "attempt_" + UUID(projection.intent.attempt_id).hex,
        ):
            raise WorkerCurrentResultError("invalid_state")
        fact = CurrentResultFact(
            "current",
            inner.eligible,
            inner.uncertainty,
            projection.case.revision,
            copied.read_completed_at,
        )
        _valid_fact(fact)
        return fact
    except Exception:  # noqa: BLE001 - untrusted DTO/body fields never enter model diagnostics
        raise WorkerCurrentResultError("invalid_state") from None


def _parent_error(status: int, raw: bytes) -> LoopbackJSONError:
    try:

        def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in values:
                if key in result:
                    raise ValueError
                result[key] = value
            return result

        obj: object = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=pairs)
        if type(obj) is not dict:
            raise ValueError
        data = cast(dict[str, object], obj)
        if (
            set(data) != {"schemaVersion", "status", "code"}
            or type(data["schemaVersion"]) is not int
            or data["schemaVersion"] != 1
            or data["status"] != "unavailable"
        ):
            raise ValueError
        allowed = {
            400: {"invalid_input"},
            401: {"unauthorized"},
            429: {"capacity"},
            503: {"closed", "unavailable", "cleanup_incomplete"},
        }
        code = data["code"]
        if type(code) is not str or code not in allowed.get(status, set()):
            raise ValueError
        return LoopbackJSONError(cast(LoopbackCode, code))
    except Exception:  # noqa: BLE001 - operational failures cannot become missing data
        return LoopbackJSONError()


def _event(code: str) -> None:
    LOGGER.info("channel_policy_worker_current", extra={"event": "read", "code": code})


class WorkerCurrentResultClient:
    """Two retained callback exchanges, with no caller-selected route or work."""

    def __init__(
        self,
        endpoint: WorkerCurrentEndpoint,
        binding: WorkerBinding,
        credential: CurrentResultCredential,
        *,
        timeout_s: float = 4,
        cleanup_timeout_s: float = 1,
    ) -> None:
        try:
            if (
                type(endpoint) is not WorkerCurrentEndpoint
                or type(binding) is not WorkerBinding
                or type(credential) is not CurrentResultCredential
            ):
                raise ValueError
            self._endpoint = WorkerCurrentEndpoint(endpoint.host, endpoint.port)
            self._binding = WorkerBinding(
                binding.profile_id, binding.scope, binding.case_id, binding.conversation_id
            )
            cap = CurrentResultCredential(credential.value)
            fixed = self._binding

            def decode(status: int, raw: bytes) -> CurrentResultObservation:
                if status != 200:
                    raise _parent_error(status, raw)
                try:
                    value = parse_current_result_observation(raw)
                    if (value.profile_id, value.scope, value.case_id, value.conversation_id) != (
                        fixed.profile_id,
                        fixed.scope,
                        fixed.case_id,
                        fixed.conversation_id,
                    ):
                        raise LoopbackJSONError("unauthorized")
                    current_result_fact(value)
                    return value
                except LoopbackJSONError:
                    raise
                except Exception:  # noqa: BLE001 - no Parent response fields in diagnostics
                    raise LoopbackJSONError("invalid_state") from None

            self._decode = decode
            self._transport = LoopbackJSONTransport(
                port=self._endpoint.port,
                bearer=cap.value,
                purpose="worker_current_result",
                timeout_s=timeout_s,
                cleanup_timeout_s=cleanup_timeout_s,
                observer=_event,
            )
        except Exception:  # noqa: BLE001 - fixed private configuration has finite diagnostics
            raise WorkerCurrentResultError("invalid_input") from None

    @property
    def pending_count(self) -> int:
        return self._transport.pending_count

    def metrics(self) -> MappingProxyType[str, int]:
        return self._transport.metrics()

    async def read(self) -> CurrentResultObservation:
        try:
            return await self._transport.exchange_decoded(
                b'{"schemaVersion":1}', decoder=self._decode
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - static finite errors only
            raise WorkerCurrentResultError(finite_error(error).code) from None

    async def close(self) -> None:
        try:
            await self._transport.close()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - retain actual ownership on incomplete close
            raise WorkerCurrentResultError(finite_error(error).code) from None
