"""Expiring server-signed bindings for the local native conversational consumer.

This is a local composition credential, not user/model-provided business consent.
It binds a frozen investigation request to one room/participant and configured
principal. Exact mutation confirmation remains outside the conversational tools.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import uuid4

from .authorization import AuthenticatedActor, AuthenticationFailed
from .case_models import canonical, identity, uuid_identity
from .models import BookingChange

DOMAIN = b"livekit-ecosystem.conversation-grant.v1\x00"
MAX_GRANT_BYTES = 8192
PAYLOAD_FIELDS = frozenset(
    {
        "schema_version",
        "grant_id",
        "issued_at",
        "expires_at",
        "room",
        "participant",
        "scope_id",
        "actor_id",
        "request",
        "request_key",
        "task_id",
    }
)


def _reject() -> AuthenticationFailed:
    return AuthenticationFailed("A valid local conversation binding is required")


def _key(secret: str) -> bytes:
    if type(secret) is not str or not 32 <= len(secret) <= 512:
        raise ValueError("A bounded server signing credential is required")
    return secret.encode("utf-8")


def _signature(payload: dict[str, object], secret: str) -> str:
    digest = hmac.new(_key(secret), DOMAIN + canonical(payload).encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass(frozen=True, slots=True)
class ConversationGrant:
    grant_id: str
    issued_at: int
    expires_at: int
    room: str
    participant: str
    scope_id: str
    actor_id: str
    request: BookingChange
    request_key: str
    task_id: str | None = None

    def __post_init__(self) -> None:
        uuid_identity(self.grant_id)
        if (
            type(self.issued_at) is not int
            or type(self.expires_at) is not int
            or not 0 <= self.issued_at < self.expires_at <= 9007199254740991
            or not 1 <= self.expires_at - self.issued_at <= 300
        ):
            raise ValueError("Conversation lifetime must be bounded")
        if (
            type(self.room) is not str
            or re.fullmatch(r"business-[a-z0-9][a-z0-9-]{0,39}", self.room) is None
        ):
            raise ValueError("A local business room is required")
        if (
            type(self.participant) is not str
            or re.fullmatch(r"(?:browser|smoke)-[a-z0-9][a-z0-9-]{0,47}", self.participant) is None
        ):
            raise ValueError("A bounded expected participant is required")
        AuthenticatedActor(self.actor_id, self.scope_id)
        identity(self.request_key)
        if type(self.request) is not BookingChange or self.request.confirmed is not True:
            raise ValueError("Only explicitly authorized investigation may be bound")
        if self.task_id is not None:
            uuid_identity(self.task_id)

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "grant_id": self.grant_id,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "room": self.room,
            "participant": self.participant,
            "scope_id": self.scope_id,
            "actor_id": self.actor_id,
            "request": self.request.payload(),
            "request_key": self.request_key,
            "task_id": self.task_id,
        }

    def binding_digest(self) -> str:
        value = self.payload()
        for key in ("grant_id", "issued_at", "expires_at"):
            value.pop(key)
        return hashlib.sha256(canonical(value).encode()).hexdigest()


def sign_grant(
    *,
    secret: str,
    actor: AuthenticatedActor,
    room: str,
    participant: str,
    request: BookingChange,
    request_key: str,
    task_id: str | None = None,
    grant_id: str | None = None,
    now: int | None = None,
) -> str:
    stamp = int(time.time()) if now is None else now
    grant = ConversationGrant(
        str(uuid4()) if grant_id is None else uuid_identity(grant_id),
        stamp,
        stamp + 300,
        room,
        participant,
        actor.scope_id,
        actor.actor_id,
        request,
        request_key,
        task_id,
    )
    result = canonical(
        {"payload": grant.payload(), "signature": _signature(grant.payload(), secret)}
    )
    if len(result.encode("utf-8")) > MAX_GRANT_BYTES:
        raise ValueError("Conversation binding exceeds its byte budget")
    return result


def verify_grant(
    raw: str,
    *,
    secret: str,
    room: str,
    expected_scope: str,
    expected_actor: str,
    now: int | None = None,
) -> ConversationGrant:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate binding field")
            result[key] = value
        return result

    def nonfinite(_value: str) -> None:
        raise ValueError("Nonfinite binding field")

    try:
        if type(raw) is not str or not 1 <= len(raw.encode("utf-8")) <= MAX_GRANT_BYTES:
            raise ValueError("Invalid binding bytes")
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
        if type(value) is not dict or set(value) != {"payload", "signature"}:
            raise ValueError("Invalid binding envelope")
        payload, signature = value["payload"], value["signature"]
        if (
            type(payload) is not dict
            or set(payload) != PAYLOAD_FIELDS
            or payload["schema_version"] != 1
            or type(payload["schema_version"]) is not int
        ):
            raise ValueError("Invalid binding fields")
        if (
            type(signature) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{43}", signature) is None
            or not hmac.compare_digest(signature, _signature(payload, secret))
        ):
            raise ValueError("Invalid binding signature")
        request = payload["request"]
        if (
            type(request) is not dict
            or set(request) != {"booking_reference", "new_check_in", "confirmed"}
            or request["confirmed"] is not True
        ):
            raise ValueError("Invalid frozen investigation")
        grant = ConversationGrant(
            payload["grant_id"],
            payload["issued_at"],
            payload["expires_at"],
            payload["room"],
            payload["participant"],
            payload["scope_id"],
            payload["actor_id"],
            BookingChange(
                request["booking_reference"], date.fromisoformat(request["new_check_in"]), True
            ),
            payload["request_key"],
            payload["task_id"],
        )
        stamp = int(time.time()) if now is None else now
        if (
            type(stamp) is not int
            or not grant.issued_at <= stamp < grant.expires_at
            or grant.room != room
            or grant.scope_id != expected_scope
            or grant.actor_id != expected_actor
            or canonical(payload) != canonical(grant.payload())
        ):
            raise ValueError("Binding is expired or mismatched")
        return grant
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError, UnicodeError) as error:
        raise _reject() from error
