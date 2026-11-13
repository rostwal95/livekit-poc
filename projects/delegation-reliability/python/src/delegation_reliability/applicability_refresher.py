"""One explicitly requested refresh over immutable results; no execution permission."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Literal, cast
from uuid import UUID

from continuity_lab.execution_api import (
    AttemptResult,
    ExecutionObservation,
    ExecutionPort,
    IssuedAttempt,
)
from continuity_lab.result_feed_api import (
    ResultFeedCursor,
    ResultFeedEvent,
    ResultFeedPage,
    ResultFeedPort,
)
from continuity_lab.work_api import WorkError, WorkScope

from .applicability_api import ApplicabilityClient
from .applicability_models import ApplicabilityRefresh, _RefreshDraft, parse_refresh, snapshot_view
from .completion import CompletionError, _evidence
from .contracts import (
    CAPABILITY,
    Attempt,
    ContractError,
    DelegationRequest,
    DelegationResult,
    Scope,
    encode_request,
    encode_result,
    identifier,
    parse_request,
    parse_result,
)
from .coordinator import CaseAuthorityPort, CaseSnapshot
from .projection_api import _Call, _ProjectionOwner
from .projection_models import (
    ApplicabilityObservation,
    Appraisal,
    ProjectedResult,
    ProjectionBinding,
    ProjectionError,
    event_digest,
    integer,
    timestamp,
    uuid,
)
from .projector import _issued, _recorded, _work
from .security import EvidenceRecord, verify_policy_facts


class ApplicabilityRefresher(_ProjectionOwner):
    """Own feed/execution/metadata clients; the application owns its shared case port.

    Command replay is historical fact. Fresh reads are non-atomic observations,
    and revision CAS orders only this metadata. No automatic loop or effect runs.
    """

    def __init__(
        self,
        *,
        events: ResultFeedPort,
        executions: ExecutionPort,
        applicability: ApplicabilityClient,
        scope: Scope,
        evidence: tuple[EvidenceRecord, ...],
        case_authority: CaseAuthorityPort,
        max_active: int = 2,
        timeout_ms: int = 10000,
        cleanup_ms: int = 1000,
    ) -> None:
        super().__init__(
            (events, executions, applicability),
            max_active=max_active,
            timeout_ms=timeout_ms,
            cleanup_ms=cleanup_ms,
        )
        try:
            if type(scope) is not Scope:
                raise ProjectionError("invalid_input")
            self._scope = Scope(identifier(scope.tenant_id), identifier(scope.account_id))
            self._evidence = _evidence(self._scope, evidence)
            self._events, self._executions, self._metadata, self._cases = (
                events,
                executions,
                applicability,
                case_authority,
            )
            self._binding = ProjectionBinding(
                applicability.source_id, WorkScope(scope.tenant_id, scope.account_id)
            )
            self._policy = applicability.policy
            self._counts.update(
                {
                    "refreshes_observed": 0,
                    "command_replays": 0,
                    "write_reconciliations": 0,
                    "reconciliation_failed": 0,
                }
            )
            self._require_local()
            self._require_source()
        except (CompletionError, ContractError, WorkError, AttributeError, TypeError, ValueError):
            raise ProjectionError("invalid_input") from None

    def _require_local(self) -> None:
        try:
            if self._metadata.scope != self._binding.scope:
                raise ProjectionError("unauthorized")
            if self._metadata.source_id != self._binding.source_id:
                raise ProjectionError("source_mismatch")
            if self._metadata.policy.sha256 != self._policy.sha256:
                raise ProjectionError("identity_conflict")
        except ProjectionError:
            raise
        except Exception:  # noqa: BLE001 - fixed credential/configuration boundary
            raise ProjectionError("unauthorized") from None

    def _require_source(self) -> None:
        self._require_local()
        try:
            for value in (self._events.scope, self._executions.scope):
                if (
                    type(value) is not WorkScope
                    or WorkScope(value.tenant_id, value.account_id) != self._binding.scope
                ):
                    raise ProjectionError("unauthorized")
            if self._events.source_id != self._binding.source_id:
                raise ProjectionError("source_mismatch")
        except ProjectionError:
            raise
        except Exception:  # noqa: BLE001 - no authority details escape
            raise ProjectionError("unauthorized") from None

    def _receipt(
        self, value: ApplicabilityRefresh, work_id: str, attempt_id: str, expected_revision: int
    ) -> ApplicabilityRefresh:
        if type(value) is not ApplicabilityRefresh:
            raise ProjectionError("invalid_source_state")
        copied = parse_refresh(value.canonical())
        if (
            copied.event.scope != self._binding.scope
            or copied.event.source_id != self._binding.source_id
            or copied.policy_sha256 != self._policy.sha256
        ):
            raise ProjectionError("invalid_source_state")
        if (copied.event.work_id, copied.event.attempt_id, copied.expected_revision) != (
            work_id,
            attempt_id,
            expected_revision,
        ):
            raise ProjectionError("identity_conflict")
        return copied

    async def refresh(
        self, *, work_id: str, attempt_id: str, command_id: str, expected_revision: int
    ) -> ApplicabilityRefresh:
        work_id, attempt_id, command_id = uuid(work_id), uuid(attempt_id), uuid(command_id)
        integer(expected_revision, 8)
        self._require_local()
        return await self._run(
            "applicability_refresh",
            lambda call: self._refresh(call, work_id, attempt_id, command_id, expected_revision),
        )

    async def _refresh(
        self, call: _Call, work_id: str, attempt_id: str, command_id: str, expected_revision: int
    ) -> ApplicabilityRefresh:
        value = await self._metadata.command(command_id=command_id)
        if value is not None:
            result = self._receipt(value, work_id, attempt_id, expected_revision)
            if result.command_id != command_id:
                raise ProjectionError("invalid_source_state")
            self._counts["command_replays"] += 1
            return result
        self._check(call)
        view = snapshot_view(await self._metadata.inspect(work_id=work_id, attempt_id=attempt_id))
        row = view.projection
        if (row.event.work_id, row.event.attempt_id, row.event.source_id, row.event.scope) != (
            work_id,
            attempt_id,
            self._binding.source_id,
            self._binding.scope,
        ):
            raise ProjectionError("invalid_source_state")
        if view.revision != expected_revision:
            raise ProjectionError("checkpoint_conflict")
        if view.revision >= self._policy.max_per_result:
            raise ProjectionError("capacity")
        self._check(call)
        self._require_source()
        await self._source_event(row)
        self._check(call)
        draft = await self._read(row)
        self._check(call)
        self._require_source()
        call.writing = True
        try:
            result = await self._metadata._commit(
                command_id=command_id, expected_revision=expected_revision, draft=draft
            )
        except ProjectionError as error:
            if error.code not in {"acknowledgement_unknown", "checkpoint_conflict"}:
                raise
            try:
                value = await self._metadata.command(command_id=command_id)
                if value is not None:
                    original = self._receipt(value, work_id, attempt_id, expected_revision)
                    if original.command_id == command_id:
                        self._counts["write_reconciliations"] += 1
                        return original
            except Exception:  # noqa: BLE001 - one failed exact lookup never changes uncertainty/conflict
                self._counts["reconciliation_failed"] += 1
            raise
        copied = self._receipt(result, work_id, attempt_id, expected_revision)
        if copied.command_id != command_id:
            raise ProjectionError("invalid_source_state")
        self._counts["refreshes_observed"] += 1
        return copied

    async def _source_event(self, row: ProjectedResult) -> None:
        self._require_source()
        original = row.event
        try:
            value = await self._events.read(
                after=ResultFeedCursor(
                    self._binding.source_id, self._binding.scope, original.sequence - 1
                ),
                limit=1,
            )
            if (
                type(value) is not ResultFeedPage
                or type(value.events) is not tuple
                or len(value.events) != 1
                or type(value.scope) is not WorkScope
            ):
                raise ProjectionError("invalid_source_state")
            e = value.events[0]
            if type(e) is not ResultFeedEvent or type(e.scope) is not WorkScope:
                raise ProjectionError("invalid_source_state")
            event = ResultFeedEvent(
                e.event_id,
                e.source_id,
                WorkScope(e.scope.tenant_id, e.scope.account_id),
                e.sequence,
                e.work_id,
                e.attempt_id,
                e.issue_command_id,
                e.result_sha256,
                e.recorded_at_ms,
                e.disposition,
                e.origin,
                e.kind,
            )

            def cursor(c: ResultFeedCursor) -> ResultFeedCursor:
                if type(c) is not ResultFeedCursor or type(c.scope) is not WorkScope:
                    raise ProjectionError("invalid_source_state")
                return ResultFeedCursor(
                    c.source_id, WorkScope(c.scope.tenant_id, c.scope.account_id), c.sequence
                )

            page = ResultFeedPage(
                value.source_id,
                WorkScope(value.scope.tenant_id, value.scope.account_id),
                cursor(value.after),
                (event,),
                cursor(value.next_cursor),
                cursor(value.high_watermark),
                value.has_more,
            )
            if (
                page.source_id != self._binding.source_id
                or page.scope != self._binding.scope
                or page.after.sequence != original.sequence - 1
                or page.next_cursor.sequence != original.sequence
                or event_digest(event) != event_digest(original)
            ):
                raise ProjectionError("invalid_source_state")
        except WorkError as error:
            raise ProjectionError(
                "storage_unavailable"
                if error.code
                in {"storage_unavailable", "acknowledgement_unknown", "deadline_exceeded"}
                else "unauthorized"
                if error.code == "unauthorized"
                else "invalid_source_state"
            ) from None
        except (ValueError, TypeError, AttributeError):
            raise ProjectionError("invalid_source_state") from None

    async def _historical(self, row: ProjectedResult) -> tuple[IssuedAttempt, AttemptResult]:
        self._require_source()
        value = await self._executions.find_issue(command_id=row.event.issue_command_id)
        if value is None:
            raise ProjectionError("invalid_source_state")
        grant = _issued(value, self._binding.scope, row.event.work_id)
        if (grant.command_id, grant.attempt_id, grant.record.payload.sha256) != (
            row.event.issue_command_id,
            row.event.attempt_id,
            row.request_sha256,
        ):
            raise ProjectionError("invalid_source_state")
        self._require_source()
        value_result = await self._executions.result(
            work_id=row.event.work_id, attempt_id=row.event.attempt_id
        )
        if value_result is None:
            raise ProjectionError("invalid_source_state")
        result = _recorded(value_result)
        if (
            result.work_id,
            result.attempt_id,
            result.sha256,
            result.recorded_at_ms,
            result.disposition,
        ) != (
            row.event.work_id,
            row.event.attempt_id,
            row.event.result_sha256,
            row.event.recorded_at_ms,
            row.event.disposition,
        ):
            raise ProjectionError("invalid_source_state")
        return grant, result

    async def _read(self, row: ProjectedResult) -> _RefreshDraft:
        try:
            grant, recorded = await self._historical(row)
            if row.validation == "rejected":
                return _RefreshDraft(row, grant.number, grant.number, None)
            request = parse_request(grant.record.payload.body)
            if (
                request.scope != self._scope
                or encode_request(request) != grant.record.payload.body
                or request.delegation_id != grant.record.idempotency_key
                or grant.record.payload.operation != CAPABILITY
                or request.deadline_at_ms != grant.record.payload.deadline_at_ms
                or (
                    request.delegation_id,
                    request.case_id,
                    request.request_revision,
                    request.input_fingerprint,
                )
                != (row.delegation_id, row.case_id, row.request_revision, row.input_fingerprint)
            ):
                raise ProjectionError("invalid_source_state")
            transport = parse_request(
                encode_request(
                    replace(
                        request,
                        attempt=Attempt("attempt_" + UUID(grant.attempt_id).hex, grant.number),
                    )
                )
            )
            parsed = parse_result(recorded.body)
            if encode_result(parsed) != recorded.body:
                raise ProjectionError("invalid_source_state")
            verify_policy_facts(
                transport, parsed, self._evidence, observed_at_ms=recorded.recorded_at_ms
            )
            observed, number = await self._observe(row, grant, request, transport, parsed)
            return _RefreshDraft(row, grant.number, number, observed)
        except WorkError as error:
            raise ProjectionError(
                "storage_unavailable"
                if error.code
                in {"storage_unavailable", "acknowledgement_unknown", "deadline_exceeded"}
                else "unauthorized"
                if error.code == "unauthorized"
                else "invalid_source_state"
            ) from None
        except (ContractError, AttributeError, TypeError, ValueError):
            raise ProjectionError("invalid_source_state") from None

    async def _observe(
        self,
        row: ProjectedResult,
        original: IssuedAttempt,
        request: DelegationRequest,
        transport: DelegationRequest,
        result: DelegationResult,
    ) -> tuple[ApplicabilityObservation, int]:
        self._require_source()
        value = await self._executions.observe(work_id=row.event.work_id)
        if type(value) is not ExecutionObservation:
            raise ProjectionError("invalid_source_state")
        record = _work(value.record, self._binding.scope, row.event.work_id)
        if replace(record, cancel_requested=False) != original.record:
            raise ProjectionError("invalid_source_state")
        current = (
            None
            if value.current_attempt is None
            else _issued(value.current_attempt, self._binding.scope, row.event.work_id)
        )
        latest = None if value.result is None else _recorded(value.result)
        observed = ExecutionObservation(
            record, current, latest, value.attempts_issued, value.status
        )
        if (
            current is None
            or current.number < original.number
            or (current.number == original.number and current.attempt_id != original.attempt_id)
        ):
            raise ProjectionError("invalid_source_state")
        if current.attempt_id == original.attempt_id and (
            latest is None
            or (
                latest.work_id,
                latest.attempt_id,
                latest.sha256,
                latest.recorded_at_ms,
                latest.disposition,
            )
            != (
                row.event.work_id,
                row.event.attempt_id,
                row.event.result_sha256,
                row.event.recorded_at_ms,
                row.event.disposition,
            )
        ):
            raise ProjectionError("invalid_source_state")
        execution_at = timestamp(time.time_ns() // 1_000_000)
        facts = verify_policy_facts(transport, result, self._evidence, observed_at_ms=execution_at)
        appraisal: Appraisal
        case_state: Literal["observed", "unavailable", "not_read"] = "not_read"
        revision = None
        cancelled = None
        case_at = None
        if (
            record.cancel_requested
            or observed.status == "cancelled"
            or row.event.disposition != "eligible_at_commit"
            or current.attempt_id != original.attempt_id
        ):
            appraisal = "execution_ineligible"
        elif facts == "expired" or observed.status == "expired":
            appraisal = "expired"
        else:
            try:
                case = await self._cases.snapshot(case_id=request.case_id)
                case_at = timestamp(time.time_ns() // 1_000_000)
                if (
                    type(case) is not CaseSnapshot
                    or type(case.scope) is not Scope
                    or Scope(identifier(case.scope.tenant_id), identifier(case.scope.account_id))
                    != self._scope
                    or identifier(case.case_id) != request.case_id
                    or type(case.cancelled) is not bool
                    or type(case.request_revision) is not int
                    or not 1 <= case.request_revision <= 9007199254740991
                ):
                    raise ProjectionError("invalid_source_state")
                revision, cancelled, case_state = case.request_revision, case.cancelled, "observed"
                appraisal = (
                    "case_cancelled"
                    if cancelled
                    else "outdated"
                    if revision != request.request_revision
                    else cast(Appraisal, facts)
                )
            except Exception:  # noqa: BLE001 - foreign/unavailable case fields are discarded entirely
                case_at = timestamp(time.time_ns() // 1_000_000)
                revision, cancelled, case_state, appraisal = (
                    None,
                    None,
                    "unavailable",
                    "unavailable",
                )
        return ApplicabilityObservation(
            appraisal,
            observed.status,
            record.cancel_requested,
            current.attempt_id,
            execution_at,
            case_state,
            revision,
            cancelled,
            case_at,
            timestamp(time.time_ns() // 1_000_000),
        ), current.number
