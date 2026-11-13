"""Authenticated explicit refresh/display metadata; imports perform no I/O."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import asdict

from continuity_lab.work_api import (
    BearerToken,
    PostgresSettings,
    WorkDirectory,
    WorkError,
    WorkScope,
)

from .applicability_models import (
    ApplicabilityRefresh,
    ApplicabilityView,
    DisplayTombstone,
    RefreshPolicy,
    _RefreshDraft,
    parse_refresh,
    parse_refresh_policy,
    parse_tombstone,
    snapshot_view,
)
from .applicability_store import ApplicabilityStore
from .projection_api import _Call, _ProjectionOwner
from .projection_models import (
    ApplicabilityObservation,
    ProjectionBinding,
    ProjectionError,
    integer,
    parse_projected,
    uuid,
)

_DEFAULT_REFRESH_POLICY = RefreshPolicy()


class ApplicabilityClient(_ProjectionOwner):
    """Own only its bounded metadata I/O; original fact reads survive display hiding."""

    def __init__(
        self,
        store: ApplicabilityStore,
        directory: WorkDirectory,
        token: BearerToken,
        *,
        max_active: int = 2,
        timeout_ms: int = 5000,
        cleanup_ms: int = 1000,
    ) -> None:
        super().__init__(max_active=max_active, timeout_ms=timeout_ms, cleanup_ms=cleanup_ms)
        self._store, self._directory, self._token = store, directory, token
        self._counts.update(
            {"display_hides_observed": 0, "write_reconciliations": 0, "reconciliation_failed": 0}
        )
        self._authorize()

    def _authorize(self) -> None:
        try:
            if self._directory.authenticate(self._token).scope != self._store.binding.scope:
                raise ProjectionError("unauthorized")
        except WorkError:
            raise ProjectionError("unauthorized") from None

    @property
    def scope(self) -> WorkScope:
        self._authorize()
        return WorkScope(self._store.binding.scope.tenant_id, self._store.binding.scope.account_id)

    @property
    def source_id(self) -> str:
        self._authorize()
        return self._store.binding.source_id

    @property
    def policy(self) -> RefreshPolicy:
        self._authorize()
        return parse_refresh_policy(self._store.policy.canonical())

    async def command(self, *, command_id: str) -> ApplicabilityRefresh | None:
        self._authorize()
        command_id = uuid(command_id)
        value = await self._run(
            "applicability_command_read",
            lambda _call: asyncio.to_thread(self._store.command, command_id),
        )
        return None if value is None else parse_refresh(value.canonical())

    async def inspect(self, *, work_id: str, attempt_id: str) -> ApplicabilityView:
        self._authorize()
        work_id, attempt_id = uuid(work_id), uuid(attempt_id)
        value = await self._run(
            "applicability_inspect",
            lambda _call: asyncio.to_thread(self._store.inspect, work_id, attempt_id),
        )
        return snapshot_view(value)

    async def display(
        self, *, work_id: str, attempt_id: str
    ) -> ApplicabilityView | DisplayTombstone:
        """Read the visible head or its stable tombstone; no identity is expired."""
        view = await self.inspect(work_id=work_id, attempt_id=attempt_id)
        return view if view.tombstone is None else parse_tombstone(view.tombstone.canonical())

    async def hide_display(self, *, work_id: str, attempt_id: str) -> DisplayTombstone:
        """Explicit permanent display hide, independent of refresh revision/capacity."""
        self._authorize()
        work_id, attempt_id = uuid(work_id), uuid(attempt_id)

        async def hide(call: _Call) -> DisplayTombstone:
            self._check(call)
            call.writing = True
            try:
                value = await asyncio.to_thread(self._store.hide, work_id, attempt_id)
            except ProjectionError as error:
                if error.code not in {"acknowledgement_unknown", "checkpoint_conflict"}:
                    raise
                try:
                    original = await asyncio.to_thread(self._store.inspect, work_id, attempt_id)
                    view = snapshot_view(original)
                    if view.tombstone is not None:
                        self._counts["write_reconciliations"] += 1
                        return parse_tombstone(view.tombstone.canonical())
                except Exception:  # noqa: BLE001 - failed lookup preserves original uncertainty/conflict
                    self._counts["reconciliation_failed"] += 1
                raise
            self._counts["display_hides_observed"] += 1
            return parse_tombstone(value.canonical())

        return await self._run("applicability_display_hide", hide)

    async def _commit(
        self, *, command_id: str, expected_revision: int, draft: _RefreshDraft
    ) -> ApplicabilityRefresh:
        self._authorize()
        command_id = uuid(command_id)
        integer(expected_revision, 8)
        if type(draft) is not _RefreshDraft:
            raise ProjectionError("invalid_input")
        copied = _RefreshDraft(
            parse_projected(draft.projection.canonical()),
            integer(draft.original_attempt_number, 3),
            integer(draft.current_attempt_number, 3),
            None
            if draft.observation is None
            else ApplicabilityObservation(**asdict(draft.observation)),
        )
        if copied.original_attempt_number == 0 or (copied.projection.validation == "validated") != (
            copied.observation is not None
        ):
            raise ProjectionError("invalid_input")

        async def commit(call: _Call) -> ApplicabilityRefresh:
            self._check(call)
            call.writing = True
            value = await asyncio.to_thread(
                self._store.commit, command_id, expected_revision, copied
            )
            return parse_refresh(value.canonical())

        return await self._run("applicability_refresh_commit", commit)


def open_applicability_client(
    *,
    settings: PostgresSettings,
    directory: WorkDirectory,
    token: BearerToken,
    source_id: str,
    policy: RefreshPolicy = _DEFAULT_REFRESH_POLICY,
    harness_failpoint: Callable[[str], None] | None = None,
    max_active: int = 2,
    timeout_ms: int = 5000,
    cleanup_ms: int = 1000,
) -> ApplicabilityClient:
    """Trusted synchronous startup against existing v3; no DDL or environment read."""
    if type(directory) is not WorkDirectory or type(policy) is not RefreshPolicy:
        raise ProjectionError("invalid_input")
    try:
        scope = directory.authenticate(token).scope
    except WorkError:
        raise ProjectionError("unauthorized") from None
    if harness_failpoint is not None and not callable(harness_failpoint):
        raise ProjectionError("invalid_input")
    binding = ProjectionBinding(uuid(source_id), WorkScope(scope.tenant_id, scope.account_id))
    return ApplicabilityClient(
        ApplicabilityStore(
            settings, binding, parse_refresh_policy(policy.canonical()), harness_failpoint
        ),
        directory,
        token,
        max_active=max_active,
        timeout_ms=timeout_ms,
        cleanup_ms=cleanup_ms,
    )
