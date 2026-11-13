"""Public P1 guarded case-intent client; independent exact human confirmation is mandatory."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from time import monotonic
from types import MappingProxyType
from typing import TypeVar

from .action_models import ActionError, ActionPort, ActionReceipt
from .action_store import ActionStore, translated
from .authorization import AuthenticatedActor, BearerToken, TokenDirectory
from .bounded_io import BoundedAsyncIO
from .case_models import ActionIntent, Confirmation, parse_confirmation
from .execution_models import ExecutionCapacityExceeded, ExecutionPortClosed
from .postgres_settings import PostgresSettings
from .work_models import WorkDirectory, WorkScope
from .work_store import WorkStore

__all__ = [
    "ActionClient",
    "ActionError",
    "ActionIntent",
    "ActionPort",
    "ActionReceipt",
    "AuthenticatedActor",
    "BearerToken",
    "Confirmation",
    "PostgresSettings",
    "WorkDirectory",
    "WorkScope",
    "open_action_client",
]
T = TypeVar("T")


class ActionClient:
    """Four actual I/O slots; cancellation preserves committed truth and thread ownership."""

    def __init__(
        self,
        store: ActionStore,
        directory: WorkDirectory,
        token: BearerToken,
        case_directory: TokenDirectory,
        case_token: BearerToken,
    ) -> None:
        self._store, self._directory, self._token = store, directory, token
        self._cases, self._case_token = case_directory, case_token
        self._io = BoundedAsyncIO(maximum=4, admission_timeout=0.05, shutdown_timeout=5)

    @property
    def scope(self) -> WorkScope:
        return self._directory.authenticate(self._token).scope

    @property
    def case_actor_id(self) -> str:
        return self._cases.authenticate(self._case_token).actor_id

    @property
    def case_scope_id(self) -> str:
        return self._cases.authenticate(self._case_token).scope_id

    @property
    def case_schema(self) -> str:
        self._cases.authenticate(self._case_token)
        return self._store.case_settings.schema

    @property
    def pending_count(self) -> int:
        return self._io.pending_count

    def metrics(self) -> Mapping[str, int]:
        return MappingProxyType(
            {"pending": self.pending_count, "telemetry_failures": self._store.telemetry_failures}
        )

    async def _run(self, call: Callable[[WorkScope, AuthenticatedActor], T]) -> T:
        try:
            scope = self.scope
            actor = self._cases.authenticate(self._case_token)
            return await self._io._run(lambda: call(scope, actor))
        except ActionError:
            raise
        except ExecutionCapacityExceeded:
            raise ActionError("capacity") from None
        except ExecutionPortClosed:
            raise ActionError("closed") from None
        except Exception as error:  # noqa: BLE001 - public containment
            raise translated(error) from None

    async def authorize(
        self,
        *,
        work_id: str,
        attempt_id: str,
        result_sha256: str,
        expected_revision: int,
        confirmation: Confirmation,
        command_id: str,
    ) -> ActionReceipt:
        if (
            type(confirmation) is not Confirmation
            or type(expected_revision) is not int
            or expected_revision < 0
        ):
            raise ActionError("invalid_confirmation")
        try:
            snapshot = parse_confirmation(confirmation.payload())
        except Exception:  # noqa: BLE001 - schema boundary
            raise ActionError("invalid_confirmation") from None
        if snapshot.quote.schema_version != 2 or snapshot.quote.revision != expected_revision:
            raise ActionError("invalid_confirmation")
        return await self._run(
            lambda scope, actor: self._store.authorize(
                scope,
                actor,
                work_id=work_id,
                attempt_id=attempt_id,
                result_sha256=result_sha256,
                expected_revision=expected_revision,
                confirmation=snapshot,
                command_id=command_id,
            )
        )

    async def find_action(self, *, command_id: str) -> ActionReceipt | None:
        return await self._run(
            lambda scope, actor: self._store.read(scope, actor, command_id=command_id)
        )

    async def action(self, *, work_id: str) -> ActionReceipt | None:
        return await self._run(lambda scope, actor: self._store.read(scope, actor, work_id=work_id))

    async def close(self) -> None:
        deadline = monotonic() + 5
        try:
            await self._io.close()
            if monotonic() >= deadline:
                raise ActionError("cleanup_incomplete")
        except TimeoutError:
            raise ActionError("cleanup_incomplete") from None


def open_action_client(
    *,
    settings: PostgresSettings,
    directory: WorkDirectory,
    token: BearerToken,
    case_settings: PostgresSettings,
    case_actor: AuthenticatedActor,
    case_token: BearerToken,
    harness_failpoint: Callable[[str], None] | None = None,
) -> ActionClient:
    """Synchronous trusted startup. Same SQL target; explicit distinct existing schemas."""
    try:
        if (
            type(settings) is not PostgresSettings
            or type(case_settings) is not PostgresSettings
            or type(directory) is not WorkDirectory
            or type(case_actor) is not AuthenticatedActor
            or type(case_token) is not BearerToken
        ):
            raise ActionError("invalid_input")
        directory.authenticate(token)
        if (
            tuple(getattr(settings, k) for k in ("host", "port", "dbname", "user", "password"))
            != tuple(
                getattr(case_settings, k) for k in ("host", "port", "dbname", "user", "password")
            )
            or settings.schema == case_settings.schema
        ):
            raise ActionError("invalid_input")
        if harness_failpoint is not None and not callable(harness_failpoint):
            raise ActionError("invalid_input")
        cases = TokenDirectory({case_token: case_actor})
        cases.authenticate(case_token)
        return ActionClient(
            ActionStore(WorkStore(settings), case_settings, harness_failpoint),
            directory,
            token,
            cases,
            case_token,
        )
    except ActionError:
        raise
    except Exception as error:  # noqa: BLE001 - startup diagnostics are fixed
        raise translated(error) from None
