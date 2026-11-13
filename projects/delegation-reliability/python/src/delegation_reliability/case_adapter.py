"""Read-only adapter over P1's declared managed-case projection API."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from continuity_lab.postgres_api import CaseProjection

from .contracts import Scope, identifier
from .coordinator import CaseSnapshot, CoordinatorError


class ManagedCaseReadPort(Protocol):
    """The credential-bound read subset of P1 ManagedCaseClient."""

    async def get(
        self, *, task_id: str, cursor: str | None = None, limit: int = 10
    ) -> CaseProjection: ...


@dataclass(frozen=True, slots=True)
class CaseBinding:
    """Trusted startup mapping from a P3 logical ID to exact P1 task and case IDs."""

    case_id: str
    task_id: str
    authority_case_id: str


def _uuid(value: str) -> str:
    if type(value) is not str or len(value) != 36:
        raise CoordinatorError("invalid_input")
    try:
        parsed = UUID(value)
    except ValueError:
        raise CoordinatorError("invalid_input") from None
    if str(parsed) != value or parsed.version != 4:
        raise CoordinatorError("invalid_input")
    return value


class ManagedCaseAuthority:
    """Finite immutable bindings; the injected P1 client authenticates every read.

    Application composition supplies the trusted P3 scope and mapping because
    P1 booking IDs and scope are a different public vocabulary. Caller JSON cannot
    select another P1 task. This adapter does not own/close the injected client.
    The projection is only a read observation, not current-at-commit authority.
    Committed cases fail closed because their public projection cannot distinguish
    subsequent cancellation; a future exact public read is required for that use.
    """

    def __init__(
        self, client: ManagedCaseReadPort, *, scope: Scope, bindings: tuple[CaseBinding, ...]
    ) -> None:
        if type(scope) is not Scope or type(bindings) is not tuple or not 1 <= len(bindings) <= 128:
            raise CoordinatorError("invalid_input")
        self._scope = Scope(identifier(scope.tenant_id), identifier(scope.account_id))
        copied = []
        for binding in bindings:
            if type(binding) is not CaseBinding:
                raise CoordinatorError("invalid_input")
            copied.append(
                CaseBinding(
                    identifier(binding.case_id),
                    _uuid(binding.task_id),
                    _uuid(binding.authority_case_id),
                )
            )
        if len({binding.case_id for binding in copied}) != len(copied):
            raise CoordinatorError("invalid_input")
        self._bindings, self._client = tuple(copied), client

    async def snapshot(self, *, case_id: str) -> CaseSnapshot:
        identifier(case_id)
        binding = next((item for item in self._bindings if item.case_id == case_id), None)
        if binding is None:
            raise CoordinatorError("not_found")
        projection = await self._client.get(task_id=binding.task_id, limit=1)
        if type(projection) is not CaseProjection:
            raise CoordinatorError("invalid_stored_state")
        try:
            data = projection.payload()
            revision = data.get("case_revision")
            confirmation = data.get("confirmation")
            if (
                type(data.get("schema_version")) is not int
                or data["schema_version"] != 1
                or data.get("task_id") != binding.task_id
                or data.get("case_id") != binding.authority_case_id
                or type(revision) is not str
                or re.fullmatch(r"[1-9][0-9]{0,15}", revision) is None
                or int(revision) > 9_007_199_254_740_991
                or type(confirmation) is not dict
                or confirmation.get("state")
                not in {"not_requested", "required", "committed", "cancelled"}
            ):
                raise CoordinatorError("invalid_stored_state")
            if confirmation["state"] == "committed":
                # P1's public projection intentionally does not expose whether a
                # committed case was subsequently cancelled. Never infer false.
                raise CoordinatorError("case_state_unavailable")
            return CaseSnapshot(
                self._scope, binding.case_id, int(revision), confirmation["state"] == "cancelled"
            )
        except (ValueError, TypeError, AttributeError):
            raise CoordinatorError("invalid_stored_state") from None
