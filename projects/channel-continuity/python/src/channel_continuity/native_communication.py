"""Immutable source-qualified communication values and an explicit bounded HTTP port."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, TypeVar, cast

from .codec import AccountScope, ProviderScope
from .native_http import NativeCleanupIncomplete
from .native_models import (
    CODES,
    NativeBinding,
    NativeCredential,
    NativeEndpoint,
    NativeError,
    decode,
    fields,
    identifier,
    text,
    uuid,
)

__all__ = [
    "BrowserObservation",
    "NativeCommunicationHttpClient",
    "NativeCommunicationPort",
    "ObservationReceipt",
    "ResponseAnchor",
    "ResponseReceipt",
    "ResponseView",
    "SdkObservation",
]

_T = TypeVar("_T")
SdkState = Literal["unknown", "completed", "interrupted", "conflicted"]
BrowserState = Literal[
    "unknown", "started", "partial", "interrupted", "completed_reported", "conflicted"
]


def _payload_digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    ).hexdigest()


def _revision(value: object) -> str:
    if (
        type(value) is not str
        or not re.fullmatch(r"[1-9][0-9]{0,18}", value, re.ASCII)
        or int(value) > 9223372036854775807
    ):
        raise NativeError()
    return value


def _digest(value: object) -> str:
    if type(value) is not str or not re.fullmatch("[0-9a-f]{64}", value, re.ASCII):
        raise NativeError()
    return value


def _iso(value: object) -> str:
    if type(value) is not str or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value, re.ASCII
    ):
        raise NativeError()
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z") != value:
            raise ValueError()
    except ValueError:
        raise NativeError() from None
    return value


@dataclass(frozen=True, slots=True)
class ResponseAnchor:
    response_id: str
    generation_id: str
    sdk_speech_id: str
    binding_id: str
    input_id: str
    receipt_id: str
    operation_key: str
    case_revision: str

    def __post_init__(self) -> None:
        for v in (
            self.response_id,
            self.generation_id,
            self.binding_id,
            self.input_id,
            self.receipt_id,
            self.operation_key,
        ):
            uuid(v)
        identifier(self.sdk_speech_id)
        _revision(self.case_revision)

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "responseId": self.response_id,
            "generationId": self.generation_id,
            "sdkSpeechId": self.sdk_speech_id,
            "bindingId": self.binding_id,
            "inputId": self.input_id,
            "receiptId": self.receipt_id,
            "operationKey": self.operation_key,
            "caseRevision": self.case_revision,
        }


@dataclass(frozen=True, slots=True)
class ResponseReceipt:
    response_id: str
    receipt_id: str
    anchor_digest: str
    response_sequence: str
    accepted_at: str

    def __post_init__(self) -> None:
        uuid(self.response_id)
        uuid(self.receipt_id)
        _digest(self.anchor_digest)
        _revision(self.response_sequence)
        _iso(self.accepted_at)

    def payload(self) -> dict[str, object]:
        return {
            "responseId": self.response_id,
            "receiptId": self.receipt_id,
            "anchorDigest": self.anchor_digest,
            "responseSequence": self.response_sequence,
            "acceptedAt": self.accepted_at,
        }


@dataclass(frozen=True, slots=True)
class ObservationReceipt:
    response_id: str
    event_id: str
    receipt_id: str
    payload_digest: str
    observation_sequence: str
    accepted_at: str

    def __post_init__(self) -> None:
        uuid(self.response_id)
        uuid(self.event_id)
        uuid(self.receipt_id)
        _digest(self.payload_digest)
        _revision(self.observation_sequence)
        _iso(self.accepted_at)

    def payload(self) -> dict[str, object]:
        return {
            "responseId": self.response_id,
            "eventId": self.event_id,
            "receiptId": self.receipt_id,
            "payloadDigest": self.payload_digest,
            "observationSequence": self.observation_sequence,
            "acceptedAt": self.accepted_at,
        }


@dataclass(frozen=True, slots=True)
class SdkObservation:
    event_id: str
    response_id: str
    generation_id: str
    sdk_speech_id: str
    kind: Literal["generated_complete", "speech_settled"]
    text: str | None = None
    state: Literal["completed", "interrupted", "unknown"] | None = None
    sdk_text: str | None = None

    def __post_init__(self) -> None:
        uuid(self.event_id)
        uuid(self.response_id)
        uuid(self.generation_id)
        identifier(self.sdk_speech_id)
        if type(self.kind) is not str:
            raise NativeError()
        if self.kind == "generated_complete":
            text(self.text, 4096)
            if self.state is not None or self.sdk_text is not None:
                raise NativeError()
        elif self.kind == "speech_settled":
            if (
                self.text is not None
                or type(self.state) is not str
                or self.state not in ("completed", "interrupted", "unknown")
            ):
                raise NativeError()
            if self.sdk_text is not None:
                text(self.sdk_text, 4096)
        else:
            raise NativeError()

    def payload(self) -> dict[str, object]:
        fact: dict[str, object] = (
            {"type": "generated_complete", "text": self.text}
            if self.kind == "generated_complete"
            else {"type": "speech_settled", "state": self.state, "sdkText": self.sdk_text}
        )
        return {
            "schemaVersion": 1,
            "eventId": self.event_id,
            "responseId": self.response_id,
            "generationId": self.generation_id,
            "sdkSpeechId": self.sdk_speech_id,
            "fact": fact,
        }


@dataclass(frozen=True, slots=True)
class BrowserObservation:
    event_id: str
    response_id: str
    state: Literal["started", "partial", "interrupted", "completed"]
    observed_audio_ms: int

    def __post_init__(self) -> None:
        uuid(self.event_id)
        uuid(self.response_id)
        if (
            type(self.state) is not str
            or self.state not in ("started", "partial", "interrupted", "completed")
            or type(self.observed_audio_ms) is not int
            or not 0 <= self.observed_audio_ms <= 180000
        ):
            raise NativeError()

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "eventId": self.event_id,
            "responseId": self.response_id,
            "state": self.state,
            "observedAudioMs": self.observed_audio_ms,
        }


@dataclass(frozen=True, slots=True)
class ResponseView:
    anchor: ResponseAnchor
    binding: NativeBinding
    receipt: ResponseReceipt
    observation_count: int
    generated_text: str | None
    sdk_state: SdkState
    sdk_text: str | None
    browser_state: BrowserState
    conflicted: bool

    def __post_init__(self) -> None:
        if (
            type(self.anchor) is not ResponseAnchor
            or type(self.binding) is not NativeBinding
            or type(self.receipt) is not ResponseReceipt
            or self.anchor.binding_id != self.binding.binding_id
            or self.anchor.response_id != self.receipt.response_id
            or type(self.observation_count) is not int
            or not 0 <= self.observation_count <= 64
            or type(self.sdk_state) is not str
            or self.sdk_state not in ("unknown", "completed", "interrupted", "conflicted")
            or type(self.browser_state) is not str
            or self.browser_state
            not in (
                "unknown",
                "started",
                "partial",
                "interrupted",
                "completed_reported",
                "conflicted",
            )
            or type(self.conflicted) is not bool
        ):
            raise NativeError()
        if self.generated_text is not None:
            text(self.generated_text, 4096)
        if self.sdk_text is not None:
            text(self.sdk_text, 4096)

    def payload(self) -> dict[str, object]:
        b = self.binding
        return {
            "anchor": {
                **self.anchor.payload(),
                "scope": {
                    "tenantId": b.account_scope.tenant_id,
                    "accountId": b.account_scope.account_id,
                },
                "providerScope": {
                    "tenantId": b.provider_scope.tenant_id,
                    "provider": b.provider_scope.provider,
                    "providerAccountId": b.provider_scope.provider_account_id,
                },
                "caseId": b.case_id,
                "conversationId": b.conversation_id,
                "roomId": b.room_id,
                "participantId": b.participant_id,
            },
            "receipt": self.receipt.payload(),
            "observationCount": self.observation_count,
            "generatedText": self.generated_text,
            "sdkState": self.sdk_state,
            "sdkText": self.sdk_text,
            "browserState": self.browser_state,
            "conflicted": self.conflicted,
        }


class NativeCommunicationPort(Protocol):
    async def begin_response(self, anchor: ResponseAnchor) -> ResponseReceipt: ...
    async def observe_sdk(self, observation: SdkObservation) -> ObservationReceipt: ...
    async def observe_browser(self, observation: BrowserObservation) -> ObservationReceipt: ...
    async def inspect_response(self, response_id: str) -> ResponseView: ...
    async def aclose(self) -> None: ...


def response_receipt(value: object) -> ResponseReceipt:
    v = fields(value, {"responseId", "receiptId", "anchorDigest", "responseSequence", "acceptedAt"})
    return ResponseReceipt(
        cast(str, v["responseId"]),
        cast(str, v["receiptId"]),
        cast(str, v["anchorDigest"]),
        cast(str, v["responseSequence"]),
        cast(str, v["acceptedAt"]),
    )


def observation_receipt(value: object) -> ObservationReceipt:
    v = fields(
        value,
        {
            "responseId",
            "eventId",
            "receiptId",
            "payloadDigest",
            "observationSequence",
            "acceptedAt",
        },
    )
    return ObservationReceipt(
        cast(str, v["responseId"]),
        cast(str, v["eventId"]),
        cast(str, v["receiptId"]),
        cast(str, v["payloadDigest"]),
        cast(str, v["observationSequence"]),
        cast(str, v["acceptedAt"]),
    )


def response_view(value: object, binding: NativeBinding) -> ResponseView:
    v = fields(
        value,
        {
            "anchor",
            "receipt",
            "observationCount",
            "generatedText",
            "sdkState",
            "sdkText",
            "browserState",
            "conflicted",
        },
    )
    a = fields(
        v["anchor"],
        {
            "schemaVersion",
            "responseId",
            "generationId",
            "sdkSpeechId",
            "bindingId",
            "inputId",
            "receiptId",
            "operationKey",
            "caseRevision",
            "scope",
            "providerScope",
            "caseId",
            "conversationId",
            "roomId",
            "participantId",
        },
    )
    if (
        type(a["schemaVersion"]) is not int
        or a["schemaVersion"] != 1
        or a["scope"]
        != {
            "tenantId": binding.account_scope.tenant_id,
            "accountId": binding.account_scope.account_id,
        }
        or a["providerScope"]
        != {
            "tenantId": binding.provider_scope.tenant_id,
            "provider": binding.provider_scope.provider,
            "providerAccountId": binding.provider_scope.provider_account_id,
        }
        or any(
            a[key] != getattr(binding, attr)
            for key, attr in (
                ("bindingId", "binding_id"),
                ("caseId", "case_id"),
                ("conversationId", "conversation_id"),
                ("roomId", "room_id"),
                ("participantId", "participant_id"),
            )
        )
    ):
        raise NativeError("forbidden")
    anchor = ResponseAnchor(
        *(
            cast(str, a[k])
            for k in (
                "responseId",
                "generationId",
                "sdkSpeechId",
                "bindingId",
                "inputId",
                "receiptId",
                "operationKey",
                "caseRevision",
            )
        )
    )
    result = ResponseView(
        anchor,
        binding,
        response_receipt(v["receipt"]),
        cast(int, v["observationCount"]),
        cast(str | None, v["generatedText"]),
        cast(SdkState, v["sdkState"]),
        cast(str | None, v["sdkText"]),
        cast(BrowserState, v["browserState"]),
        cast(bool, v["conflicted"]),
    )
    if result.receipt.anchor_digest != _payload_digest(
        cast(dict[str, object], result.payload()["anchor"])
    ):
        raise NativeError()
    return result


def _copy_binding(binding: NativeBinding) -> NativeBinding:
    return NativeBinding(
        binding.binding_id,
        ProviderScope(
            binding.provider_scope.tenant_id,
            binding.provider_scope.provider,
            binding.provider_scope.provider_account_id,
        ),
        AccountScope(binding.account_scope.tenant_id, binding.account_scope.account_id),
        binding.case_id,
        binding.conversation_id,
        binding.room_id,
        binding.participant_id,
        binding.agent_id,
    )


class NativeCommunicationHttpClient:
    def __init__(
        self,
        endpoint: NativeEndpoint,
        publisher: NativeCredential,
        sdk: NativeCredential,
        browser: NativeCredential,
        account: NativeCredential,
        binding: NativeBinding,
        *,
        timeout: float = 3.0,
        cleanup: float = 5.0,
    ) -> None:
        if (
            type(endpoint) is not NativeEndpoint
            or type(binding) is not NativeBinding
            or any(type(x) is not NativeCredential for x in (publisher, sdk, browser, account))
            or len({x.value for x in (publisher, sdk, browser, account)}) != 4
            or type(timeout) not in (int, float)
            or not 0.02 <= timeout <= 5
            or type(cleanup) not in (int, float)
            or not 0.02 <= cleanup <= 5
        ):
            raise NativeError()
        self._endpoint, self._binding = (
            NativeEndpoint(endpoint.host, endpoint.port),
            _copy_binding(binding),
        )
        self._publisher, self._sdk, self._browser, self._account = (
            NativeCredential(x.value) for x in (publisher, sdk, browser, account)
        )
        self._timeout, self._cleanup = float(timeout), float(cleanup)
        self._tasks: set[asyncio.Task[object]] = set()
        self._closed = False
        self._counts = {"started": 0, "known": 0, "rejected": 0, "unknown": 0}

    def metrics(self) -> dict[str, int]:
        return {**self._counts, "active": len(self._tasks)}

    async def _call(
        self,
        path: str,
        credential: NativeCredential,
        payload: dict[str, object],
        parser: Callable[[object], _T],
        *,
        read: bool = False,
    ) -> _T:
        if self._closed:
            raise NativeError("closed")
        if len(self._tasks) >= 2:
            raise NativeError("capacity_exhausted")
        raw = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        if len(raw) > 32768:
            raise NativeError()
        task: asyncio.Task[object] = asyncio.create_task(
            self._exchange(path, credential, raw, parser, read), name="communication-http"
        )
        self._tasks.add(task)
        self._counts["started"] += 1

        def settled(done: asyncio.Task[object]) -> None:
            self._tasks.discard(done)
            if not done.cancelled():
                done.exception()

        task.add_done_callback(settled)
        return cast(_T, await asyncio.shield(task))

    async def _exchange(
        self,
        path: str,
        credential: NativeCredential,
        raw: bytes,
        parser: Callable[[object], object],
        read: bool,
    ) -> object:
        writer: asyncio.StreamWriter | None = None
        deadline = time.monotonic() + self._timeout
        validated: NativeError | None = None
        try:
            async with asyncio.timeout(self._timeout):
                reader, writer = await asyncio.open_connection(
                    self._endpoint.host, self._endpoint.port, limit=4096
                )
                head = f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{self._endpoint.port}\r\nAuthorization: Bearer {credential.value}\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\nConnection: close\r\n\r\n".encode(
                    "ascii"
                )
                writer.write(head + raw)
                await writer.drain()
                rawhead = await reader.readuntil(b"\r\n\r\n")
                if len(rawhead) > 4096:
                    raise NativeError()
                lines = rawhead.decode("ascii").split("\r\n")
                parts = lines[0].split(" ")
                if (
                    len(parts) < 3
                    or parts[0] != "HTTP/1.1"
                    or parts[1] not in ("200", "400", "401", "403", "409", "413", "429", "503")
                ):
                    raise NativeError()
                headers: dict[str, str] = {}
                for line in lines[1:-2]:
                    name, header_value = line.split(":", 1)
                    name = name.lower()
                    if name in headers or name not in (
                        "content-type",
                        "content-length",
                        "connection",
                        "date",
                        "server",
                        "cache-control",
                    ):
                        raise NativeError()
                    headers[name] = header_value.strip()
                size = headers.get("content-length", "")
                maximum = 65536 if read else 2048
                if (
                    headers.get("connection") != "close"
                    or headers.get("content-type") != "application/json"
                    or not size.isascii()
                    or not size.isdecimal()
                    or size.startswith("0")
                    or not 1 <= int(size) <= maximum
                ):
                    raise NativeError()
                response = decode(await reader.readexactly(int(size)), maximum)
                if await reader.read(1) != b"" or time.monotonic() >= deadline:
                    raise NativeError()
                if parts[1] == "200":
                    value = fields(response, {"schemaVersion", "status", "result"})
                    if (
                        type(value["schemaVersion"]) is not int
                        or value["schemaVersion"] != 1
                        or value["status"] != "known"
                    ):
                        raise NativeError()
                    parsed = parser(value["result"])
                    self._counts["known"] += 1
                    return parsed
                value = fields(response, {"schemaVersion", "status", "code"})
                if (
                    type(value["schemaVersion"]) is not int
                    or value["schemaVersion"] != 1
                    or type(value["code"]) is not str
                    or value["code"] not in CODES
                ):
                    raise NativeError()
                if value["status"] == "rejected" and value["code"] != "acknowledgement_unknown":
                    validated = NativeError(
                        cast(
                            Literal[
                                "invalid_input",
                                "forbidden",
                                "idempotency_conflict",
                                "capacity_exhausted",
                                "dependency_unavailable",
                                "closed",
                            ],
                            value["code"],
                        )
                    )
                    self._counts["rejected"] += 1
                    raise validated
                if value["status"] != "unknown" or value["code"] != "acknowledgement_unknown":
                    raise NativeError()
                raise NativeError("acknowledgement_unknown")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - Invalid or lost network response stays fixed uncertainty.
            if validated is not None:
                raise validated from None
            self._counts["unknown"] += 1
            raise NativeError(
                "dependency_unavailable" if read else "acknowledgement_unknown"
            ) from None
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass

    async def begin_response(self, anchor: ResponseAnchor) -> ResponseReceipt:
        if type(anchor) is not ResponseAnchor:
            raise NativeError()
        anchor = ResponseAnchor(
            anchor.response_id,
            anchor.generation_id,
            anchor.sdk_speech_id,
            anchor.binding_id,
            anchor.input_id,
            anchor.receipt_id,
            anchor.operation_key,
            anchor.case_revision,
        )
        if type(anchor) is not ResponseAnchor or anchor.binding_id != self._binding.binding_id:
            raise NativeError("forbidden")

        bound = self._binding
        canonical = {
            **anchor.payload(),
            "scope": {
                "tenantId": bound.account_scope.tenant_id,
                "accountId": bound.account_scope.account_id,
            },
            "providerScope": {
                "tenantId": bound.provider_scope.tenant_id,
                "provider": bound.provider_scope.provider,
                "providerAccountId": bound.provider_scope.provider_account_id,
            },
            "caseId": bound.case_id,
            "conversationId": bound.conversation_id,
            "roomId": bound.room_id,
            "participantId": bound.participant_id,
        }
        expected = _payload_digest(canonical)

        def parse(value: object) -> ResponseReceipt:
            r = response_receipt(value)
            if r.response_id != anchor.response_id or r.anchor_digest != expected:
                raise NativeError()
            return r

        return await self._call("/v1/native/responses", self._publisher, anchor.payload(), parse)

    async def observe_sdk(self, observation: SdkObservation) -> ObservationReceipt:
        if type(observation) is not SdkObservation:
            raise NativeError()
        observation = SdkObservation(
            observation.event_id,
            observation.response_id,
            observation.generation_id,
            observation.sdk_speech_id,
            observation.kind,
            observation.text,
            observation.state,
            observation.sdk_text,
        )

        def parse(value: object) -> ObservationReceipt:
            r = observation_receipt(value)
            if (r.response_id, r.event_id) != (
                observation.response_id,
                observation.event_id,
            ) or r.payload_digest != _payload_digest(observation.payload()):
                raise NativeError()
            return r

        return await self._call(
            "/v1/native/sdk-observations", self._sdk, observation.payload(), parse
        )

    async def observe_browser(self, observation: BrowserObservation) -> ObservationReceipt:
        if type(observation) is not BrowserObservation:
            raise NativeError()
        observation = BrowserObservation(
            observation.event_id,
            observation.response_id,
            observation.state,
            observation.observed_audio_ms,
        )

        def parse(value: object) -> ObservationReceipt:
            r = observation_receipt(value)
            if (r.response_id, r.event_id) != (
                observation.response_id,
                observation.event_id,
            ) or r.payload_digest != _payload_digest(observation.payload()):
                raise NativeError()
            return r

        return await self._call(
            "/v1/native/browser-observations", self._browser, observation.payload(), parse
        )

    async def inspect_response(self, response_id: str) -> ResponseView:
        uuid(response_id)

        def parse(value: object) -> ResponseView:
            r = response_view(value, _copy_binding(self._binding))
            if r.anchor.response_id != response_id:
                raise NativeError()
            return r

        return await self._call(
            "/v1/native/response-inspect",
            self._account,
            {"schemaVersion": 1, "responseId": response_id},
            parse,
            read=True,
        )

    async def aclose(self) -> None:
        self._closed = True
        try:
            async with asyncio.timeout(self._cleanup):
                if self._tasks:
                    await asyncio.shield(
                        asyncio.gather(*tuple(self._tasks), return_exceptions=True)
                    )
        except TimeoutError:
            raise NativeCleanupIncomplete() from None
        self._tasks = {task for task in self._tasks if not task.done()}
        if self._tasks:
            raise NativeCleanupIncomplete()
