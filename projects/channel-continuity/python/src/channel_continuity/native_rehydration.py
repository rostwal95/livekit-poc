"""Bounded read-only current-case context. Importing this module does not import the SDK."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast
from uuid import UUID

from .codec import AccountScope, ProviderScope, TrustedPrincipal, parse_event_json
from .native_http import NativeCleanupIncomplete
from .native_models import (
    NativeBinding,
    NativeCredential,
    NativeEndpoint,
    NativeError,
    decode,
    fields,
    identifier,
    uuid,
)

__all__ = [
    "NativeContextHttpClient",
    "NativeRehydrationPort",
    "NativeRehydrationProfile",
    "RehydrationContext",
    "RehydrationQuery",
    "context_from",
]

_CODES = frozenset(
    ("access_denied", "invalid_query", "context_unavailable", "overloaded", "closed")
)
_WORK_CODES = frozenset(
    (
        "none",
        "association_required",
        "adapter_invalid",
        "adapter_unavailable",
        "operation_conflict",
        "claim_lost",
        "accepted",
        "lookup_absent",
    )
)


def _json(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise NativeError() from None


def _enum(value: object, allowed: tuple[str, ...] | frozenset[str]) -> str:
    if type(value) is not str or value not in allowed:
        raise NativeError()
    return value


def _integer(value: object, maximum: int) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise NativeError()
    return value


def _revision(value: object, *, positive: bool = False) -> str:
    if (
        type(value) is not str
        or not re.fullmatch(r"0|[1-9][0-9]{0,18}", value, re.ASCII)
        or int(value) > 9223372036854775807
        or (positive and value == "0")
    ):
        raise NativeError()
    return value


def _digest(value: object) -> str:
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value, re.ASCII):
        raise NativeError()
    return value


def _canonical_uuid(value: object) -> str:
    if type(value) is not str:
        raise NativeError()
    try:
        if str(UUID(value)) != value:
            raise ValueError()
    except ValueError:
        raise NativeError() from None
    return value


def _iso(value: object) -> str:
    if type(value) is not str or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z", value, re.ASCII
    ):
        raise NativeError()
    try:
        if (
            datetime.fromisoformat(value).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            != value
        ):
            raise ValueError()
    except ValueError:
        raise NativeError() from None
    return value


def _list(value: object, maximum: int) -> list[object]:
    if type(value) is not list or len(value) > maximum:
        raise NativeError()
    return value.copy()


def _bool(value: object) -> bool:
    if type(value) is not bool:
        raise NativeError()
    return value


def _cursor(value: object, kind: str, expected_digest: str | None = None) -> None:
    if value is None:
        return
    v = fields(
        value,
        {"kind", "scopeDigest", "beforeAcceptedAt", "beforeOutboundId"}
        if kind == "replies"
        else {"kind", "scopeDigest", "beforeSequence"},
    )
    if v["kind"] != kind or (expected_digest is not None and v["scopeDigest"] != expected_digest):
        raise NativeError()
    _digest(v["scopeDigest"])
    if kind == "replies":
        _iso(v["beforeAcceptedAt"])
        uuid(v["beforeOutboundId"])
    else:
        _revision(v["beforeSequence"], positive=True)


@dataclass(frozen=True, slots=True)
class RehydrationQuery:
    """Canonical copied paging hint, never an authorization token."""

    _canonical: bytes = b'{"historyCursor":null,"workCursor":null,"responseCursor":null,"replyCursor":null,"limits":{"history":8,"work":8,"responses":4,"replies":4}}'

    def __post_init__(self) -> None:
        v = decode(self._canonical, 4096)
        fields(v, {"historyCursor", "workCursor", "responseCursor", "replyCursor", "limits"})
        for key, kind in (
            ("historyCursor", "history"),
            ("workCursor", "work"),
            ("responseCursor", "responses"),
            ("replyCursor", "replies"),
        ):
            _cursor(v[key], kind)
        limits = fields(v["limits"], {"history", "work", "responses", "replies"})
        for key, maximum in (("history", 8), ("work", 8), ("responses", 4), ("replies", 4)):
            if _integer(limits[key], maximum) == 0:
                raise NativeError()
        object.__setattr__(self, "_canonical", _json(v))

    @classmethod
    def from_payload(cls, value: object) -> RehydrationQuery:
        return cls(_json(value))

    def payload(self) -> dict[str, object]:
        return decode(self._canonical, 4096)


def _tree(value: object, depth: int = 0, budget: list[int] | None = None) -> None:
    if budget is None:
        budget = [4096]
    budget[0] -= 1
    if budget[0] < 0 or depth > 12:
        raise NativeError()
    if type(value) is str:
        if len(value) > 65536:
            raise NativeError()
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise NativeError() from None
    elif value is None or type(value) in (int, bool):
        return
    elif type(value) is dict:
        if len(value) > 64 or any(type(k) is not str for k in value):
            raise NativeError()
        for key, item in value.items():
            _tree(key, depth + 1, budget)
            _tree(item, depth + 1, budget)
    elif type(value) is list:
        if len(value) > 64:
            raise NativeError()
        for item in value:
            _tree(item, depth + 1, budget)
    else:
        raise NativeError()


def _task_text(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 128
        or len(value.encode("utf-8")) > 512
        or value.strip() != value
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise NativeError()
    return value


def _fact_text(value: object, maximum: int) -> str:
    if (
        type(value) is not str
        or not value
        or len(value.encode("utf-8")) > maximum
        or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value)
    ):
        raise NativeError()
    return value


def _request(value: object) -> None:
    v = fields(
        value, {"schemaVersion", "kind", "bookingReference", "newCheckIn", "investigationConsent"}
    )
    reference = _fact_text(v["bookingReference"], 64)
    if (
        type(v["schemaVersion"]) is not int
        or v["schemaVersion"] != 1
        or v["kind"] != "booking_investigation"
        or v["investigationConsent"] is not True
        or reference.strip().upper() != reference
    ):
        raise NativeError()
    if type(v["newCheckIn"]) is not str or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}", v["newCheckIn"], re.ASCII
    ):
        raise NativeError()
    try:
        if datetime.fromisoformat(v["newCheckIn"]).date().isoformat() != v["newCheckIn"]:
            raise ValueError()
    except ValueError:
        raise NativeError() from None


def _case(value: object, binding: NativeBinding | None) -> tuple[dict[str, object], str]:
    v = fields(
        value,
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
    scope = fields(v["scope"], {"tenantId", "accountId"})
    for item in (*scope.values(), v["caseId"], v["conversationId"]):
        identifier(item)
    if binding is not None and (
        scope
        != {
            "tenantId": binding.account_scope.tenant_id,
            "accountId": binding.account_scope.account_id,
        }
        or v["caseId"] != binding.case_id
        or v["conversationId"] != binding.conversation_id
    ):
        raise NativeError("forbidden")
    if type(v["schemaVersion"]) is not int or v["schemaVersion"] != 1:
        raise NativeError()
    _enum(v["source"], ("standalone_reference_v1", "p1_public_v4"))
    _revision(v["revision"])
    _digest(v["sourceRevision"])
    _request(v["request"])
    workflow = v["workflow"]
    if workflow is not None:
        w = fields(workflow, {"taskId", "state", "version"})
        _task_text(w["taskId"])
        _revision(w["version"])
        _enum(
            w["state"],
            (
                "ready",
                "running",
                "retry_wait",
                "inquiry_complete",
                "waiting",
                "intent_committed",
                "failed",
                "uncertain",
                "completed",
                "cancelled",
            ),
        )
    intent = fields(v["intent"], {"state", "intentId"})
    _enum(intent["state"], ("not_committed", "committed"))
    if (intent["state"] == "committed") != (intent["intentId"] is not None):
        raise NativeError()
    if intent["intentId"] is not None:
        _canonical_uuid(intent["intentId"])
    mutation = fields(
        v["mutation"], {"state", "outcome", "cancellation", "effectId", "outcomeEventId"}
    )
    _enum(
        mutation["state"],
        (
            "not_observed",
            "pending",
            "claimed",
            "dispatched",
            "succeeded",
            "failed",
            "uncertain",
            "cancelled",
        ),
    )
    _enum(mutation["outcome"], ("not_observed", "succeeded", "failed", "uncertain", "cancelled"))
    _enum(
        mutation["cancellation"],
        (
            "not_observed",
            "not_requested",
            "cancelled_before_commit",
            "cancelled_before_dispatch",
            "requested_best_effort",
            "already_terminal",
        ),
    )
    for key in ("effectId", "outcomeEventId"):
        if mutation[key] is not None:
            _canonical_uuid(mutation[key])
    supplier = v["supplierResult"]
    if supplier is not None:
        s = fields(supplier, {"supplierId", "revision", "bookingReference", "newCheckIn"})
        _canonical_uuid(s["supplierId"])
        _revision(s["revision"])
        _request(
            {
                "schemaVersion": 1,
                "kind": "booking_investigation",
                "bookingReference": s["bookingReference"],
                "newCheckIn": s["newCheckIn"],
                "investigationConsent": True,
            }
        )
        if mutation["state"] != "succeeded" and mutation["outcome"] != "succeeded":
            raise NativeError()
    if (
        mutation["state"] != "not_observed"
        or mutation["effectId"] is not None
        or mutation["outcome"] in ("succeeded", "failed", "uncertain")
    ) and intent["state"] != "committed":
        raise NativeError()
    if (mutation["state"] == "succeeded" or mutation["outcome"] == "succeeded") and (
        supplier is None or mutation["effectId"] is None
    ):
        raise NativeError()
    if v["source"] == "p1_public_v4" and workflow is None:
        raise NativeError()
    if v["source"] == "standalone_reference_v1" and (
        workflow is not None
        or supplier is not None
        or mutation
        != {
            "state": "not_observed",
            "outcome": "not_observed",
            "cancellation": "not_observed",
            "effectId": None,
            "outcomeEventId": None,
        }
    ):
        raise NativeError()
    ref = {"scope": scope, "caseId": v["caseId"], "conversationId": v["conversationId"]}
    return v, hashlib.sha256(_json(ref)).hexdigest()


def _message(value: object, case: dict[str, object]) -> None:
    v = fields(value, {"receipt", "event", "operationKey", "processingState", "associationVersion"})
    r = fields(
        v["receipt"], {"receiptId", "eventId", "messageId", "acceptanceSequence", "acceptedAt"}
    )
    uuid(r["receiptId"])
    identifier(r["eventId"])
    identifier(r["messageId"])
    _revision(r["acceptanceSequence"], positive=True)
    _iso(r["acceptedAt"])
    uuid(v["operationKey"])
    _revision(v["associationVersion"], positive=True)
    _enum(
        v["processingState"],
        ("pending", "running", "dispatched", "blocked", "exhausted", "uncertain"),
    )
    e = v["event"]
    if type(e) is not dict:
        raise NativeError()
    provider = fields(e.get("providerScope"), {"tenantId", "provider", "providerAccountId"})
    account = fields(case["scope"], {"tenantId", "accountId"})
    principal = TrustedPrincipal(
        ProviderScope(
            cast(str, provider["tenantId"]),
            cast(str, provider["provider"]),
            cast(str, provider["providerAccountId"]),
        ),
        AccountScope(cast(str, account["tenantId"]), cast(str, account["accountId"])),
    )
    parse_event_json(_json(e).decode(), principal)
    if (
        e.get("caseId") != case["caseId"]
        or e.get("conversationId") != case["conversationId"]
        or e.get("type") != "text.received"
        or e.get("eventId") != r["eventId"]
        or e.get("messageId") != r["messageId"]
    ):
        raise NativeError()


def _response(value: object, case: dict[str, object]) -> None:
    v = fields(
        value,
        {
            "historical",
            "anchor",
            "receipt",
            "observationCount",
            "generated",
            "sdk",
            "browserState",
            "conflicted",
        },
    )
    if v["historical"] is not True:
        raise NativeError()
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
    for key in ("responseId", "generationId", "bindingId", "inputId", "receiptId", "operationKey"):
        uuid(a[key])
    for key in ("sdkSpeechId", "roomId", "participantId"):
        identifier(a[key])
    if (
        type(a["schemaVersion"]) is not int
        or a["schemaVersion"] != 1
        or a["scope"] != case["scope"]
        or a["caseId"] != case["caseId"]
        or a["conversationId"] != case["conversationId"]
    ):
        raise NativeError()
    p = fields(a["providerScope"], {"tenantId", "provider", "providerAccountId"})
    if (
        p["tenantId"] != cast(dict[str, object], case["scope"])["tenantId"]
        or p["provider"] != "livekit"
    ):
        raise NativeError()
    identifier(p["providerAccountId"])
    _revision(a["caseRevision"], positive=True)
    r = fields(
        v["receipt"], {"responseId", "receiptId", "anchorDigest", "responseSequence", "acceptedAt"}
    )
    uuid(r["receiptId"])
    _revision(r["responseSequence"], positive=True)
    _iso(r["acceptedAt"])
    canonical = {
        key: a[key]
        for key in (
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
        )
    }
    if (
        r["responseId"] != a["responseId"]
        or r["anchorDigest"] != hashlib.sha256(_json(canonical)).hexdigest()
    ):
        raise NativeError()
    _integer(v["observationCount"], 64)
    for key, states in (
        ("generated", ("not_observed", "complete", "conflicted")),
        ("sdk", ("unknown", "completed", "interrupted", "conflicted")),
    ):
        s = fields(v[key], {"state", "textDigest", "textBytes"})
        _enum(s["state"], states)
        if (s["textDigest"] is None) != (s["textBytes"] is None):
            raise NativeError()
        if s["textDigest"] is not None:
            _digest(s["textDigest"])
            _integer(s["textBytes"], 4096)
    _enum(
        v["browserState"],
        ("unknown", "started", "partial", "interrupted", "completed_reported", "conflicted"),
    )
    _bool(v["conflicted"])


def _reply(value: object) -> None:
    v = fields(
        value,
        {
            "outboundId",
            "responseId",
            "receiptId",
            "acceptedAt",
            "bodyDigest",
            "attemptCount",
            "lastAttempt",
            "callbackObservations",
            "callbacksTruncated",
        },
    )
    uuid(v["outboundId"])
    identifier(v["responseId"])
    uuid(v["receiptId"])
    _iso(v["acceptedAt"])
    _digest(v["bodyDigest"])
    count = _integer(v["attemptCount"], 5)
    if (v["lastAttempt"] is None) != (count == 0):
        raise NativeError()
    if v["lastAttempt"] is not None:
        a = fields(
            v["lastAttempt"],
            {"attemptId", "providerOperationKey", "requestDigest", "result", "providerMessageId"},
        )
        uuid(a["attemptId"])
        uuid(a["providerOperationKey"])
        _digest(a["requestDigest"])
        _enum(a["result"], ("unknown", "accepted_by_provider", "definitive_not_accepted"))
        if (a["result"] == "accepted_by_provider") != (a["providerMessageId"] is not None):
            raise NativeError()
        if a["providerMessageId"] is not None:
            identifier(a["providerMessageId"])
    for item in _list(v["callbackObservations"], 4):
        c = fields(item, {"attemptId", "eventId", "receiptId", "state"})
        uuid(c["attemptId"])
        identifier(c["eventId"])
        uuid(c["receiptId"])
        _enum(
            c["state"], ("accepted_by_provider", "delivered", "failed", "unknown", "read_reported")
        )
    _bool(v["callbacksTruncated"])


@dataclass(frozen=True, slots=True)
class RehydrationContext:
    """Validated immutable bytes; payload() returns a detached copy, not a live principal."""

    _canonical: bytes

    def payload(self) -> dict[str, object]:
        return decode(self._canonical, 65536)

    @property
    def case_revision(self) -> str:
        return cast(str, cast(dict[str, object], self.payload()["case"])["revision"])

    @property
    def context_id(self) -> str:
        return cast(str, self.payload()["contextId"])


def context_from(value: object, binding: NativeBinding | None = None) -> RehydrationContext:
    _tree(value)
    v = fields(
        value,
        {
            "schemaVersion",
            "contextId",
            "access",
            "case",
            "history",
            "work",
            "responses",
            "replies",
            "observed",
        },
    )
    if type(v["schemaVersion"]) is not int or v["schemaVersion"] != 1:
        raise NativeError()
    uuid(v["contextId"])
    case, digest = _case(v["case"], binding)
    access = v["access"]
    if type(access) is not dict:
        raise NativeError()
    if access.get("kind") == "native":
        a = fields(access, {"kind", "bindingId", "roomId", "participantId"})
        uuid(a["bindingId"])
        identifier(a["roomId"])
        identifier(a["participantId"])
        if binding is not None and (
            a["bindingId"] != binding.binding_id
            or a["roomId"] != binding.room_id
            or a["participantId"] != binding.participant_id
        ):
            raise NativeError("forbidden")
    else:
        a = fields(access, {"kind", "receiptId", "eventId", "senderId", "associationVersion"})
        if a["kind"] != "sms" or binding is not None:
            raise NativeError("forbidden")
        uuid(a["receiptId"])
        identifier(a["eventId"])
        identifier(a["senderId"])
        _revision(a["associationVersion"], positive=True)
    for section, array, kind, maximum in (
        ("history", "messages", "history", 8),
        ("work", "items", "work", 8),
        ("responses", "items", "responses", 4),
        ("replies", "items", "replies", 4),
    ):
        page = fields(v[section], {array, "nextCursor", "hasMore"})
        values = _list(page[array], maximum)
        _cursor(page["nextCursor"], kind, digest)
        if _bool(page["hasMore"]) != (page["nextCursor"] is not None):
            raise NativeError()
        for item in values:
            if section == "history":
                _message(item, case)
            elif section == "responses":
                _response(item, case)
            elif section == "replies":
                _reply(item)
            else:
                w = fields(
                    item,
                    {
                        "receiptId",
                        "operationKey",
                        "acceptanceSequence",
                        "state",
                        "possibleExternal",
                        "externalReceiptId",
                        "attempts",
                        "nextAttemptAt",
                        "lastCode",
                    },
                )
                uuid(w["receiptId"])
                uuid(w["operationKey"])
                _revision(w["acceptanceSequence"], positive=True)
                _enum(w["state"], ("pending", "running", "uncertain", "blocked", "exhausted"))
                _bool(w["possibleExternal"])
                if w["externalReceiptId"] is not None:
                    raise NativeError()
                _integer(w["attempts"], 5)
                if w["nextAttemptAt"] is not None:
                    _iso(w["nextAttemptAt"])
                _enum(w["lastCode"], _WORK_CODES)
    observed = fields(
        v["observed"], {"p2ObservedAt", "caseObservedAt", "disclosureAdmittedAt", "atomic"}
    )
    if observed["atomic"] is not False:
        raise NativeError()
    for name in ("p2ObservedAt", "caseObservedAt", "disclosureAdmittedAt"):
        _iso(observed[name])
    for name, budget in (
        ("case", 4096),
        ("history", 28672),
        ("work", 4096),
        ("responses", 12288),
        ("replies", 8192),
    ):
        if len(_json(v[name])) > budget:
            raise NativeError()
    if len(_json({"schemaVersion": 1, "status": "known", "context": v})) > 65536:
        raise NativeError()
    return RehydrationContext(_json(v))


class NativeRehydrationPort(Protocol):
    async def load(self, query: RehydrationQuery | None = None) -> RehydrationContext: ...
    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class NativeRehydrationProfile:
    port: NativeRehydrationPort


class NativeContextHttpClient:
    def __init__(
        self,
        endpoint: NativeEndpoint,
        credential: NativeCredential,
        binding: NativeBinding,
        *,
        timeout_ms: int = 3000,
    ) -> None:
        if (
            type(endpoint) is not NativeEndpoint
            or type(credential) is not NativeCredential
            or type(binding) is not NativeBinding
            or type(timeout_ms) is not int
            or not 20 <= timeout_ms <= 5000
        ):
            raise NativeError()
        self._endpoint = NativeEndpoint("127.0.0.1", endpoint.port)
        self._credential = NativeCredential(credential.value)
        self._binding = NativeBinding(
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
        self._timeout = timeout_ms / 1000
        self._closing = False
        self._tasks: set[asyncio.Task[RehydrationContext]] = set()
        self._counts = {"started": 0, "known": 0, "unavailable": 0}

    def metrics(self) -> dict[str, int]:
        return {**self._counts, "active": len(self._tasks)}

    async def load(self, query: RehydrationQuery | None = None) -> RehydrationContext:
        if query is not None and type(query) is not RehydrationQuery:
            raise NativeError()
        selected = RehydrationQuery() if query is None else RehydrationQuery(query._canonical)
        if self._closing:
            raise NativeError("closed")
        if len(self._tasks) >= 2:
            raise NativeError("capacity_exhausted")
        task = asyncio.create_task(self._exchange(selected), name="native-context-http")
        self._tasks.add(task)
        self._counts["started"] += 1

        def settled(done: asyncio.Task[RehydrationContext]) -> None:
            self._tasks.discard(done)
            if not done.cancelled():
                done.exception()

        task.add_done_callback(settled)
        return await asyncio.shield(task)

    async def _exchange(self, query: RehydrationQuery) -> RehydrationContext:
        deadline = time.monotonic() + self._timeout
        writer: asyncio.StreamWriter | None = None
        try:
            async with asyncio.timeout(self._timeout):
                reader, writer = await asyncio.open_connection(
                    "127.0.0.1", self._endpoint.port, limit=4096
                )
                raw = _json({"schemaVersion": 1, "query": query.payload()})
                if len(raw) > 4096:
                    raise NativeError()
                writer.write(
                    (
                        f"POST /v1/rehydration/native HTTP/1.1\r\nHost: 127.0.0.1:{self._endpoint.port}\r\nAuthorization: Bearer {self._credential.value}\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\nConnection: close\r\n\r\n"
                    ).encode("ascii")
                    + raw
                )
                await writer.drain()
                rawhead = await reader.readuntil(b"\r\n\r\n")
                if len(rawhead) > 4096:
                    raise NativeError()
                lines = rawhead.decode("ascii").split("\r\n")
                if lines[0] != "HTTP/1.1 200 OK":
                    raise NativeError()
                headers: dict[str, str] = {}
                for line in lines[1:-2]:
                    name, header = line.split(":", 1)
                    name = name.lower()
                    if name in headers or name not in (
                        "content-length",
                        "content-type",
                        "connection",
                        "date",
                        "server",
                    ):
                        raise NativeError()
                    headers[name] = header.strip()
                length = headers.get("content-length", "")
                if (
                    headers.get("connection") != "close"
                    or headers.get("content-type") != "application/json"
                    or not re.fullmatch(r"[1-9][0-9]{0,4}", length, re.ASCII)
                    or int(length) > 65536
                ):
                    raise NativeError()
                body = decode(await reader.readexactly(int(length)), 65536)
                if await reader.read(1) != b"" or time.monotonic() >= deadline:
                    raise NativeError()
                if body.get("status") == "known":
                    v = fields(body, {"schemaVersion", "status", "context"})
                    if type(v["schemaVersion"]) is not int or v["schemaVersion"] != 1:
                        raise NativeError()
                    result = context_from(v["context"], self._binding)
                    self._counts["known"] += 1
                    return result
                v = fields(body, {"schemaVersion", "status", "code"})
                if (
                    type(v["schemaVersion"]) is not int
                    or v["schemaVersion"] != 1
                    or v["status"] != "unavailable"
                    or type(v["code"]) is not str
                    or v["code"] not in _CODES
                ):
                    raise NativeError()
                raise NativeError(
                    "forbidden"
                    if v["code"] == "access_denied"
                    else "capacity_exhausted"
                    if v["code"] == "overloaded"
                    else "closed"
                    if v["code"] == "closed"
                    else "dependency_unavailable"
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._counts["unavailable"] += 1
            if type(error) is NativeError and error.code in (
                "forbidden",
                "capacity_exhausted",
                "closed",
            ):
                raise
            raise NativeError("dependency_unavailable") from None
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass

    async def aclose(self) -> None:
        self._closing = True
        try:
            async with asyncio.timeout(5):
                await asyncio.shield(asyncio.gather(*tuple(self._tasks), return_exceptions=True))
        except TimeoutError:
            raise NativeCleanupIncomplete() from None
        if self._tasks:
            raise NativeCleanupIncomplete()
