"""Immutable result delivery bindings; receipt acceptance is not human acknowledgement."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Protocol

from .work_models import WorkError, WorkScope, work_identifier, work_milliseconds, work_uuid


def result_digest(value: str) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise WorkError("invalid_input")
    return value


@dataclass(frozen=True, slots=True)
class DeliveryIntent:
    delivery_id: str
    scope: WorkScope
    work_id: str
    attempt_id: str
    result_sha256: str
    receiver_id: str
    recipient_id: str
    body: bytes = field(repr=False)
    prepared_at_ms: int

    def __post_init__(self) -> None:
        for value in (self.delivery_id, self.work_id, self.attempt_id, self.receiver_id):
            work_uuid(value)
        if type(self.scope) is not WorkScope:
            raise WorkError("invalid_input")
        work_identifier(self.recipient_id)
        result_digest(self.result_sha256)
        if type(self.body) is not bytes or not 1 <= len(self.body) <= 8192:
            raise WorkError("invalid_input")
        if hashlib.sha256(self.body).hexdigest() != self.result_sha256:
            raise WorkError("invalid_input")
        work_milliseconds(self.prepared_at_ms)

    def canonical(self) -> bytes:
        return json.dumps(
            {
                "delivery_id": self.delivery_id,
                "scope": {"tenant_id": self.scope.tenant_id, "account_id": self.scope.account_id},
                "work_id": self.work_id,
                "attempt_id": self.attempt_id,
                "result_sha256": self.result_sha256,
                "receiver_id": self.receiver_id,
                "recipient_id": self.recipient_id,
                "body": base64.b64encode(self.body).decode("ascii"),
                "prepared_at_ms": self.prepared_at_ms,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")


def snapshot_intent(value: DeliveryIntent) -> DeliveryIntent:
    if type(value) is not DeliveryIntent or type(value.scope) is not WorkScope:
        raise WorkError("invalid_input")
    return DeliveryIntent(
        value.delivery_id,
        WorkScope(value.scope.tenant_id, value.scope.account_id),
        value.work_id,
        value.attempt_id,
        value.result_sha256,
        value.receiver_id,
        value.recipient_id,
        value.body,
        value.prepared_at_ms,
    )


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    delivery_id: str
    receipt_id: str
    receiver_id: str
    recipient_id: str
    result_sha256: str
    accepted_at_ms: int

    def __post_init__(self) -> None:
        for value in (self.delivery_id, self.receipt_id, self.receiver_id):
            work_uuid(value)
        work_identifier(self.recipient_id)
        result_digest(self.result_sha256)
        work_milliseconds(self.accepted_at_ms)


def snapshot_receipt(value: DeliveryReceipt) -> DeliveryReceipt:
    if type(value) is not DeliveryReceipt:
        raise WorkError("invalid_input")
    return DeliveryReceipt(
        value.delivery_id,
        value.receipt_id,
        value.receiver_id,
        value.recipient_id,
        value.result_sha256,
        value.accepted_at_ms,
    )


def match_receipt(intent: DeliveryIntent, receipt: DeliveryReceipt) -> None:
    if (intent.delivery_id, intent.receiver_id, intent.recipient_id, intent.result_sha256) != (
        receipt.delivery_id,
        receipt.receiver_id,
        receipt.recipient_id,
        receipt.result_sha256,
    ):
        raise WorkError("identity_conflict")


@dataclass(frozen=True, slots=True)
class DeliveryStart:
    intent: DeliveryIntent
    created: bool

    def __post_init__(self) -> None:
        if type(self.intent) is not DeliveryIntent or type(self.created) is not bool:
            raise WorkError("invalid_input")


@dataclass(frozen=True, slots=True)
class DeliverySnapshot:
    intent: DeliveryIntent | None
    possible: bool
    receipt: DeliveryReceipt | None

    def __post_init__(self) -> None:
        if type(self.possible) is not bool:
            raise WorkError("invalid_input")
        if self.intent is None:
            if self.possible or self.receipt is not None:
                raise WorkError("invalid_input")
        elif type(self.intent) is not DeliveryIntent:
            raise WorkError("invalid_input")
        if self.receipt is not None:
            if (
                type(self.receipt) is not DeliveryReceipt
                or self.intent is None
                or not self.possible
            ):
                raise WorkError("invalid_input")
            match_receipt(self.intent, self.receipt)


class DeliveryPort(Protocol):
    @property
    def scope(self) -> WorkScope: ...
    @property
    def pending_count(self) -> int: ...
    async def prepare(
        self,
        *,
        work_id: str,
        attempt_id: str,
        result_sha256: str,
        receiver_id: str,
        recipient_id: str,
    ) -> DeliveryIntent: ...
    async def begin(self, *, intent: DeliveryIntent) -> DeliveryStart: ...
    async def record_receipt(
        self, *, intent: DeliveryIntent, receipt: DeliveryReceipt
    ) -> DeliveryReceipt: ...
    async def inspect(self, *, work_id: str) -> DeliverySnapshot: ...
    async def close(self) -> None: ...
