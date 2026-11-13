"""One explicitly requested metadata projection step over P1's durable result feed.

The checkpoint tracks consumed references, never execution, delivery or action
ownership. Applicability is an immutable pair of non-atomic as-of observations.
"""

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
from continuity_lab.work_api import WorkError, WorkPayload, WorkRecord, WorkScope

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
from .projection_api import ProjectionClient, _Call, _ProjectionOwner
from .projection_models import (
    ApplicabilityObservation,
    Appraisal,
    ProjectedResult,
    ProjectionBatch,
    ProjectionBinding,
    ProjectionCheckpoint,
    ProjectionCode,
    ProjectionError,
    event_payload,
    timestamp,
    uuid,
)
from .security import EvidenceRecord, verify_policy_facts


def _work(value: WorkRecord, scope: WorkScope, work_id: str) -> WorkRecord:
    if (
        type(value) is not WorkRecord
        or type(value.scope) is not WorkScope
        or type(value.payload) is not WorkPayload
    ):
        raise ProjectionError("invalid_source_state")
    copied = WorkRecord(
        value.work_id,
        WorkScope(value.scope.tenant_id, value.scope.account_id),
        value.idempotency_key,
        WorkPayload(value.payload.operation, value.payload.body, value.payload.deadline_at_ms),
        value.accepted_at_ms,
        value.cancel_requested,
        value.status,
    )
    if (
        copied.work_id != work_id
        or copied.scope != scope
        or copied.payload.sha256 != value.payload.sha256
    ):
        raise ProjectionError("invalid_source_state")
    return copied


def _issued(value: IssuedAttempt, scope: WorkScope, work_id: str) -> IssuedAttempt:
    if type(value) is not IssuedAttempt:
        raise ProjectionError("invalid_source_state")
    return IssuedAttempt(
        _work(value.record, scope, work_id),
        value.attempt_id,
        value.command_id,
        value.number,
        value.owner_id,
        value.epoch,
        value.issued_at_ms,
        value.lease_until_ms,
    )


def _recorded(value: AttemptResult) -> AttemptResult:
    if type(value) is not AttemptResult:
        raise ProjectionError("invalid_source_state")
    copied = AttemptResult(
        value.work_id, value.attempt_id, value.body, value.recorded_at_ms, value.disposition
    )
    if copied.sha256 != value.sha256:
        raise ProjectionError("invalid_source_state")
    return copied


class ProjectionProjector(_ProjectionOwner):
    """Own the three configured clients; the application owns the shared case port.

    No loop, provider, DDL or delivery is started. A caller explicitly schedules
    each bounded step. Unknown writes are looked up once, never resubmitted.
    """

    def __init__(
        self,
        *,
        events: ResultFeedPort,
        executions: ExecutionPort,
        projections: ProjectionClient,
        scope: Scope,
        evidence: tuple[EvidenceRecord, ...],
        case_authority: CaseAuthorityPort,
        max_active: int = 2,
        timeout_ms: int = 5000,
        cleanup_ms: int = 1000,
    ) -> None:
        super().__init__(
            (events, executions, projections),
            max_active=max_active,
            timeout_ms=timeout_ms,
            cleanup_ms=cleanup_ms,
        )
        try:
            if type(scope) is not Scope:
                raise ProjectionError("invalid_input")
            self._scope = Scope(identifier(scope.tenant_id), identifier(scope.account_id))
            self._evidence = _evidence(self._scope, evidence)
            self._events, self._executions, self._projections, self._cases = (
                events,
                executions,
                projections,
                case_authority,
            )
            self._binding = ProjectionBinding(
                uuid(events.source_id), WorkScope(scope.tenant_id, scope.account_id)
            )
            self._require_binding()
        except CompletionError as error:
            raise ProjectionError(
                "unauthorized" if error.code == "unauthorized" else "invalid_input"
            ) from None
        except (ContractError, WorkError, ValueError, AttributeError):
            raise ProjectionError("invalid_input") from None

    def _require_binding(self) -> None:
        try:
            for value in (self._events.scope, self._executions.scope, self._projections.scope):
                if (
                    type(value) is not WorkScope
                    or WorkScope(value.tenant_id, value.account_id) != self._binding.scope
                ):
                    raise ProjectionError("unauthorized")
            if (
                self._events.source_id != self._binding.source_id
                or self._projections.source_id != self._binding.source_id
            ):
                raise ProjectionError("source_mismatch")
        except ProjectionError:
            raise
        except Exception:  # noqa: BLE001 - credential checks cannot expose dependency data
            raise ProjectionError("unauthorized") from None

    def _page(
        self, value: ResultFeedPage, point: ProjectionCheckpoint, limit: int
    ) -> tuple[ResultFeedEvent, ...]:
        try:
            if (
                type(value) is not ResultFeedPage
                or type(value.scope) is not WorkScope
                or type(value.events) is not tuple
                or len(value.events) > limit
            ):
                raise ProjectionError("invalid_source_state")

            def cursor(c: ResultFeedCursor) -> ResultFeedCursor:
                if type(c) is not ResultFeedCursor or type(c.scope) is not WorkScope:
                    raise ProjectionError("invalid_source_state")
                return ResultFeedCursor(
                    c.source_id, WorkScope(c.scope.tenant_id, c.scope.account_id), c.sequence
                )

            rows = []
            for event in value.events:
                event_payload(event)
                rows.append(
                    ResultFeedEvent(
                        event.event_id,
                        event.source_id,
                        WorkScope(event.scope.tenant_id, event.scope.account_id),
                        event.sequence,
                        event.work_id,
                        event.attempt_id,
                        event.issue_command_id,
                        event.result_sha256,
                        event.recorded_at_ms,
                        event.disposition,
                        event.origin,
                        event.kind,
                    )
                )
            page = ResultFeedPage(
                value.source_id,
                WorkScope(value.scope.tenant_id, value.scope.account_id),
                cursor(value.after),
                tuple(rows),
                cursor(value.next_cursor),
                cursor(value.high_watermark),
                value.has_more,
            )
            if (
                page.source_id != self._binding.source_id
                or page.scope != self._binding.scope
                or page.after.sequence != point.sequence
                or (page.has_more and not page.events)
            ):
                raise ProjectionError("invalid_source_state")
            return page.events
        except (WorkError, ProjectionError, AttributeError, TypeError, ValueError):
            raise ProjectionError("invalid_source_state") from None

    async def project_once(self, *, limit: int = 4) -> ProjectionBatch:
        if type(limit) is not int or not 1 <= limit <= 8:
            raise ProjectionError("invalid_input")
        self._require_binding()
        return await self._run("project_once", lambda call: self._step(call, limit))

    async def _step(self, call: _Call, limit: int) -> ProjectionBatch:
        self._require_binding()
        point = await self._projections.checkpoint()
        if type(point) is not ProjectionCheckpoint:
            raise ProjectionError("invalid_source_state")
        # Copy even frozen nested values before the source read can yield.
        point = ProjectionCheckpoint(
            ProjectionBinding(
                point.binding.source_id,
                WorkScope(point.binding.scope.tenant_id, point.binding.scope.account_id),
            ),
            point.sequence,
            point.record_count,
        )
        if point.binding != self._binding:
            raise ProjectionError("source_mismatch")
        self._check(call)
        self._require_binding()
        try:
            page = await self._events.read(
                after=ResultFeedCursor(
                    self._binding.source_id,
                    WorkScope(self._binding.scope.tenant_id, self._binding.scope.account_id),
                    point.sequence,
                ),
                limit=limit,
            )
            events = self._page(page, point, limit)
            if not events:
                return ProjectionBatch(point, point, (), False)
            rows = []
            for event in events:
                self._check(call)
                rows.append(await self._project(event))
            self._check(call)
            self._require_binding()
            call.writing = True
            try:
                return await self._projections._apply(point, tuple(rows))
            except ProjectionError as error:
                if error.code != "acknowledgement_unknown":
                    raise
                # Exactly one read; never another apply, even if it is absent.
                try:
                    known = await self._projections._reconcile(point, tuple(rows))
                except Exception:  # noqa: BLE001 - lookup failure cannot erase possible commit
                    raise ProjectionError("acknowledgement_unknown") from None
                if known is None:
                    raise ProjectionError("acknowledgement_unknown")
                return known
        except WorkError as error:
            code = (
                "storage_unavailable"
                if error.code in {"storage_unavailable", "acknowledgement_unknown"}
                else "invalid_source_state"
            )
            raise ProjectionError(cast(ProjectionCode, code)) from None

    async def _project(self, event: ResultFeedEvent) -> ProjectedResult:
        self._require_binding()
        try:
            issued = await self._executions.find_issue(command_id=event.issue_command_id)
            if issued is None:
                raise ProjectionError("invalid_source_state")
            grant = _issued(issued, self._binding.scope, event.work_id)
            if (grant.command_id, grant.attempt_id) != (event.issue_command_id, event.attempt_id):
                raise ProjectionError("invalid_source_state")
            self._require_binding()
            value = await self._executions.result(
                work_id=event.work_id, attempt_id=event.attempt_id
            )
            if value is None:
                raise ProjectionError("invalid_source_state")
            result = _recorded(value)
            if (
                result.work_id,
                result.attempt_id,
                result.sha256,
                result.recorded_at_ms,
                result.disposition,
            ) != (
                event.work_id,
                event.attempt_id,
                event.result_sha256,
                event.recorded_at_ms,
                event.disposition,
            ):
                raise ProjectionError("invalid_source_state")
        except WorkError:
            raise
        except (AttributeError, TypeError, ValueError):
            raise ProjectionError("invalid_source_state") from None
        request = None
        request_bound = False
        try:
            request = parse_request(grant.record.payload.body)
            if (
                request.scope != self._scope
                or encode_request(request) != grant.record.payload.body
                or request.delegation_id != grant.record.idempotency_key
                or grant.record.payload.operation != CAPABILITY
                or grant.record.payload.deadline_at_ms != request.deadline_at_ms
            ):
                raise ContractError("identity_conflict")
            request_bound = True
            transport = replace(
                request, attempt=Attempt("attempt_" + UUID(grant.attempt_id).hex, grant.number)
            )
            transport = parse_request(encode_request(transport))
            parsed = parse_result(result.body)
            if encode_result(parsed) != result.body:
                raise ContractError("invalid_contract")
            verify_policy_facts(
                transport, parsed, self._evidence, observed_at_ms=result.recorded_at_ms
            )
        except ContractError as error:
            # Only definitely invalid P3 bytes/facts are quarantined; source errors above do not advance.
            if not request_bound:
                request = None
            return self._row(event, grant.record, request, "rejected", error.code, None)
        observation = await self._observe(event, grant.record, request, transport, parsed)
        return self._row(event, grant.record, request, "validated", None, observation)

    @staticmethod
    def _row(
        event: ResultFeedEvent,
        record: WorkRecord,
        request: DelegationRequest | None,
        validation: str,
        rejection: str | None,
        observation: ApplicabilityObservation | None,
    ) -> ProjectedResult:
        return ProjectedResult(
            event,
            record.payload.sha256,
            None if request is None else request.delegation_id,
            None if request is None else request.case_id,
            None if request is None else request.request_revision,
            None if request is None else request.input_fingerprint,
            cast('Literal["validated", "rejected"]', validation),
            rejection,
            observation,
            time.time_ns() // 1_000_000,
        )

    async def _observe(
        self,
        event: ResultFeedEvent,
        original: WorkRecord,
        request: DelegationRequest,
        transport: DelegationRequest,
        parsed: DelegationResult,
    ) -> ApplicabilityObservation:
        self._require_binding()
        value = await self._executions.observe(work_id=event.work_id)
        try:
            if type(value) is not ExecutionObservation:
                raise ProjectionError("invalid_source_state")
            record = _work(value.record, self._binding.scope, event.work_id)
            if replace(record, cancel_requested=False) != replace(original, cancel_requested=False):
                raise ProjectionError("invalid_source_state")
            current = (
                None
                if value.current_attempt is None
                else _issued(value.current_attempt, self._binding.scope, event.work_id)
            )
            latest = None if value.result is None else _recorded(value.result)
            observed = ExecutionObservation(
                record, current, latest, value.attempts_issued, value.status
            )
            execution_at = timestamp(time.time_ns() // 1_000_000)
        except (WorkError, AttributeError, TypeError, ValueError):
            raise ProjectionError("invalid_source_state") from None
        facts = verify_policy_facts(transport, parsed, self._evidence, observed_at_ms=execution_at)
        appraisal: Appraisal
        case_state = "not_read"
        revision = None
        cancelled = None
        case_at = None
        if (
            record.cancel_requested
            or observed.status == "cancelled"
            or event.disposition != "eligible_at_commit"
            or current is None
            or current.attempt_id != event.attempt_id
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
            except Exception:  # noqa: BLE001 - foreign/unavailable case data is discarded completely
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
            None if current is None else current.attempt_id,
            execution_at,
            cast('Literal["observed", "unavailable", "not_read"]', case_state),
            revision,
            cancelled,
            case_at,
            timestamp(time.time_ns() // 1_000_000),
        )
