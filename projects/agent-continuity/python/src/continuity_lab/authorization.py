"""Trusted local token/scope boundary for the supported synchronous inquiry API.

This is an application composition boundary, not an HTTP adapter or production
IAM system. Provision the directory from trusted configuration. Untrusted callers
receive this service rather than a store accepting arbitrary scope identifiers.
"""

import hashlib
import hmac
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from .execution_models import (
    AttemptRecord,
    ExecutionError,
    ExecutionRecord,
    ExecutionSubmission,
    Operation,
    UnsupportedOperation,
    WorkerExecutionPort,
)
from .models import BookingChange

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
_AUTHENTICATION_MESSAGE = "A valid inquiry credential is required"


class AuthenticationFailed(ExecutionError):
    """Missing, malformed and unknown credentials share one safe failure."""

    code = "authentication_required"


def _identity(value: str) -> None:
    if (
        type(value) is not str
        or not 1 <= len(value) <= 128
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("Actor and scope identities must be bounded nonempty strings")


@dataclass(frozen=True, slots=True)
class AuthenticatedActor:
    """Immutable identity provisioned by trusted application configuration."""

    actor_id: str
    scope_id: str

    def __post_init__(self) -> None:
        _identity(self.actor_id)
        _identity(self.scope_id)


@dataclass(frozen=True, slots=True)
class BearerToken:
    """A bounded opaque credential whose representation never contains its value."""

    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.value) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{32,128}", self.value) is None
        ):
            raise AuthenticationFailed(_AUTHENTICATION_MESSAGE)


@dataclass(frozen=True, slots=True, init=False)
class TokenDirectory:
    """Finite immutable SHA-256 token directory; no plaintext tokens are retained.

    Use high entropy generated tokens. This deliberately has no self-registration,
    token minting, password authentication, expiry or production IAM integration.
    Replacing the directory is a trusted application configuration operation.
    """

    _entries: tuple[tuple[bytes, AuthenticatedActor], ...] = field(repr=False)

    def __init__(self, registrations: Mapping[BearerToken, AuthenticatedActor]) -> None:
        if not isinstance(registrations, Mapping) or not 1 <= len(registrations) <= 256:
            raise ValueError("A token directory requires 1 to 256 trusted registrations")
        entries = []
        for token, actor in registrations.items():
            if type(token) is not BearerToken or type(actor) is not AuthenticatedActor:
                raise ValueError("Token registrations require validated credentials and actors")
            digest = hashlib.sha256(token.value.encode("ascii")).digest()
            entries.append((digest, actor))
        object.__setattr__(self, "_entries", tuple(entries))

    def authenticate(self, token: BearerToken) -> AuthenticatedActor:
        match = None
        if type(token) is BearerToken:
            digest = hashlib.sha256(token.value.encode("ascii")).digest()
            # Traverse the finite inventory; do not stop at a matching entry.
            for expected, actor in self._entries:
                if hmac.compare_digest(expected, digest):
                    match = actor
        if match is None:
            LOGGER.warning(
                "authentication_rejected",
                extra={"event": "authentication_rejected", "code": "authentication_required"},
            )
            raise AuthenticationFailed(_AUTHENTICATION_MESSAGE)
        return match


@dataclass(frozen=True, slots=True)
class ScopedInquiryService:
    """Authenticate every call and bind its scope before touching inquiry state.

    Public methods have no actor/scope override. The validated BookingChange
    value has an exact schema; a caller-supplied mapping cannot smuggle authority.
    Blocking stores must still be offloaded by a bounded conversational adapter.
    Cancellation/signals remain unsupported after an authorized existence check.
    """

    directory: TokenDirectory = field(repr=False)
    store: WorkerExecutionPort = field(repr=False)

    def submit(
        self,
        *,
        token: BearerToken,
        idempotency_key: str,
        request: BookingChange,
        operation: str = Operation.INQUIRE,
    ) -> ExecutionSubmission:
        actor = self.directory.authenticate(token)
        if type(request) is not BookingChange:
            raise ValueError("A validated booking investigation is required")
        return self.store.submit(
            scope_id=actor.scope_id,
            idempotency_key=idempotency_key,
            request=request,
            operation=operation,
        )

    def get(self, *, token: BearerToken, task_id: str) -> ExecutionRecord:
        actor = self.directory.authenticate(token)
        return self.store.get(scope_id=actor.scope_id, task_id=task_id)

    def list(self, *, token: BearerToken, limit: int = 100) -> tuple[ExecutionRecord, ...]:
        actor = self.directory.authenticate(token)
        return self.store.list(scope_id=actor.scope_id, limit=limit)

    def history(self, *, token: BearerToken, task_id: str) -> tuple[AttemptRecord, ...]:
        actor = self.directory.authenticate(token)
        return self.store.attempts(scope_id=actor.scope_id, task_id=task_id)

    def cancel(self, *, token: BearerToken, task_id: str) -> None:
        actor = self.directory.authenticate(token)
        self.store.get(scope_id=actor.scope_id, task_id=task_id)
        raise UnsupportedOperation("Inquiry cancellation is not implemented")

    def signal(self, *, token: BearerToken, task_id: str) -> None:
        actor = self.directory.authenticate(token)
        self.store.get(scope_id=actor.scope_id, task_id=task_id)
        raise UnsupportedOperation("Inquiry signals are not implemented")
