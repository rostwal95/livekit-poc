"""Explicit bounded delivery-only processing; neither source ACK nor a work queue."""

from __future__ import annotations

import hashlib
import time
from typing import Literal, Protocol, cast

from continuity_lab.delivery_api import DeliveryIntent, DeliveryReceipt, DeliverySnapshot
from continuity_lab.result_feed_api import (
    ResultFeedCursor,
    ResultFeedEvent,
    ResultFeedPage,
    ResultFeedPort,
)
from continuity_lab.work_api import WorkError, WorkScope

from .completion import CompletionError, DelegationResultReadPort, _evidence, _result
from .contracts import ContractError, Scope, identifier
from .delivery_contract import DelegationDelivery, DeliveryBinding, ResultDeliveryPort
from .processing_api import ProcessingClient
from .processing_models import (
    CompletionPolicy,
    ProcessingAcknowledgement,
    ProcessingCheckpoint,
    ProcessingOutcome,
    ProcessingPage,
    ProcessingStep,
    parse_ack,
    snapshot_policy,
)
from .projection_api import _Call, _ProjectionOwner
from .projection_models import (
    ProjectedResult,
    ProjectionCode,
    ProjectionError,
    event_digest,
    parse_projected,
)
from .runner import DelegationRunError
from .security import EvidenceRecord

_UNAVAILABLE = frozenset(
    {
        "storage_unavailable",
        "acknowledgement_unknown",
        "deadline_exceeded",
        "capacity",
        "closed",
        "cleanup_incomplete",
        "request_aborted",
    }
)


def _dependency_code(code: str) -> ProjectionCode:
    """Dependency availability is never evidence about the source or result bytes."""
    if code in _UNAVAILABLE:
        return "storage_unavailable"
    return "unauthorized" if code == "unauthorized" else "invalid_source_state"


class ProcessingDeliveryPort(ResultDeliveryPort, Protocol):
    @property
    def scope(self) -> WorkScope: ...
    @property
    def receiver_id(self) -> str: ...
    @property
    def bindings(self) -> tuple[DeliveryBinding, ...]: ...


class CompletionProcessor(_ProjectionOwner):
    """Own processing/feed/delivery clients; application owns shared result/case reads."""

    def __init__(
        self,
        *,
        processing: ProcessingClient,
        source: ResultFeedPort,
        delivery: ProcessingDeliveryPort,
        results: DelegationResultReadPort,
        scope: Scope,
        evidence: tuple[EvidenceRecord, ...],
        max_active: int = 2,
        timeout_ms: int = 10000,
        cleanup_ms: int = 1000,
    ) -> None:
        super().__init__(
            (processing, source, delivery),
            max_active=max_active,
            timeout_ms=timeout_ms,
            cleanup_ms=cleanup_ms,
        )
        try:
            if type(scope) is not Scope:
                raise ProjectionError("invalid_input")
            self._scope = Scope(identifier(scope.tenant_id), identifier(scope.account_id))
            self._evidence = _evidence(self._scope, evidence)
            self._processing, self._source, self._delivery, self._results = (
                processing,
                source,
                delivery,
                results,
            )
            self._policy = snapshot_policy(processing.policy)
            self._counts.update(
                {
                    "examined": 0,
                    "acknowledged": 0,
                    "unknown": 0,
                    "unavailable": 0,
                    "unroutable": 0,
                    "ack_reconciliations": 0,
                }
            )
            self._source_id = processing.source_id
            self._require()
        except (ContractError, WorkError, CompletionError, AttributeError, TypeError, ValueError):
            raise ProjectionError("invalid_input") from None

    def _require(self) -> None:
        try:
            expected = WorkScope(self._scope.tenant_id, self._scope.account_id)
            for scope in (self._processing.scope, self._source.scope, self._delivery.scope):
                if (
                    type(scope) is not WorkScope
                    or WorkScope(scope.tenant_id, scope.account_id) != expected
                ):
                    raise ProjectionError("unauthorized")
            if (
                self._processing.source_id != self._source_id
                or self._source.source_id != self._source_id
            ):
                raise ProjectionError("source_mismatch")
            actual = CompletionPolicy(
                self._delivery.receiver_id,
                tuple(
                    DeliveryBinding(b.case_id, b.conversation_id, b.recipient_id)
                    for b in self._delivery.bindings
                ),
            )
            if (
                actual.sha256 != self._policy.sha256
                or self._processing.policy.sha256 != self._policy.sha256
            ):
                raise ProjectionError("identity_conflict")
        except ProjectionError:
            raise
        except Exception:  # noqa: BLE001 - authority configuration cannot expose dependency values
            raise ProjectionError("unauthorized") from None

    def _page(self, value: ProcessingPage, limit: int) -> ProcessingPage:
        if (
            type(value) is not ProcessingPage
            or type(value.checkpoint) is not ProcessingCheckpoint
            or type(value.rows) is not tuple
            or len(value.rows) > limit
        ):
            raise ProjectionError("invalid_source_state")
        p = value.checkpoint
        from .projection_models import ProjectionBinding

        point = ProcessingCheckpoint(
            ProjectionBinding(
                p.binding.source_id,
                WorkScope(p.binding.scope.tenant_id, p.binding.scope.account_id),
            ),
            p.policy_sha256,
            p.revision,
            p.terminal_watermark,
            p.scan_after,
            p.terminal_count,
            p.projected_through,
        )
        if (
            point.binding.source_id != self._source_id
            or point.binding.scope != WorkScope(self._scope.tenant_id, self._scope.account_id)
            or point.policy_sha256 != self._policy.sha256
        ):
            raise ProjectionError("source_mismatch")
        rows = tuple(parse_projected(row.canonical()) for row in value.rows)
        seen = set()
        wrapped = False
        last = point.scan_after
        for row in rows:
            seq = row.event.sequence
            if (
                seq in seen
                or not point.terminal_watermark < seq <= point.projected_through
                or row.event.scope != point.binding.scope
                or row.event.source_id != self._source_id
            ):
                raise ProjectionError("invalid_source_state")
            if seq <= last:
                if wrapped or seq > point.scan_after:
                    raise ProjectionError("invalid_source_state")
                wrapped = True
            if wrapped and seq > point.scan_after:
                raise ProjectionError("invalid_source_state")
            seen.add(seq)
            last = seq
        return ProcessingPage(point, rows)

    async def process_once(self, *, limit: int = 4) -> ProcessingStep:
        if type(limit) is not int or not 1 <= limit <= 8:
            raise ProjectionError("invalid_input")
        self._require()
        return await self._run("completion_processing", lambda call: self._step(call, limit))

    async def _source_event(self, row: ProjectedResult) -> None:
        self._require()
        original = row.event
        try:
            value = await self._source.read(
                after=ResultFeedCursor(
                    self._source_id,
                    WorkScope(self._scope.tenant_id, self._scope.account_id),
                    original.sequence - 1,
                ),
                limit=1,
            )
            if (
                type(value) is not ResultFeedPage
                or type(value.events) is not tuple
                or len(value.events) != 1
                or value.after.sequence != original.sequence - 1
                or value.next_cursor.sequence != original.sequence
            ):
                raise ProjectionError("invalid_source_state")
            event = value.events[0]
            if type(event) is not ResultFeedEvent or type(event.scope) is not WorkScope:
                raise ProjectionError("invalid_source_state")
            copied = ResultFeedEvent(
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

            def cursor(c: ResultFeedCursor) -> ResultFeedCursor:
                if type(c) is not ResultFeedCursor or type(c.scope) is not WorkScope:
                    raise ProjectionError("invalid_source_state")
                return ResultFeedCursor(
                    c.source_id, WorkScope(c.scope.tenant_id, c.scope.account_id), c.sequence
                )

            if type(value.scope) is not WorkScope:
                raise ProjectionError("invalid_source_state")
            page = ResultFeedPage(
                value.source_id,
                WorkScope(value.scope.tenant_id, value.scope.account_id),
                cursor(value.after),
                (copied,),
                cursor(value.next_cursor),
                cursor(value.high_watermark),
                value.has_more,
            )
            if page.source_id != self._source_id or page.scope != WorkScope(
                self._scope.tenant_id, self._scope.account_id
            ):
                raise ProjectionError("invalid_source_state")
            if event_digest(copied) != event_digest(original):
                raise ProjectionError("invalid_source_state")
        except WorkError as error:
            raise ProjectionError(_dependency_code(error.code)) from None
        except (AttributeError, ValueError, TypeError):
            raise ProjectionError("invalid_source_state") from None

    def _snapshot_delivery(
        self, value: DelegationDelivery, row: ProjectedResult
    ) -> DelegationDelivery:
        try:
            if (
                type(value) is not DelegationDelivery
                or type(value.snapshot) is not DeliverySnapshot
                or type(value.receiver_invoked) is not bool
            ):
                raise ProjectionError("invalid_source_state")
            s = value.snapshot
            i = s.intent
            intent = (
                None
                if i is None
                else DeliveryIntent(
                    i.delivery_id,
                    WorkScope(i.scope.tenant_id, i.scope.account_id),
                    i.work_id,
                    i.attempt_id,
                    i.result_sha256,
                    i.receiver_id,
                    i.recipient_id,
                    i.body,
                    i.prepared_at_ms,
                )
            )
            r = s.receipt
            receipt = (
                None
                if r is None
                else DeliveryReceipt(
                    r.delivery_id,
                    r.receipt_id,
                    r.receiver_id,
                    r.recipient_id,
                    r.result_sha256,
                    r.accepted_at_ms,
                )
            )
            snapshot = DeliverySnapshot(intent, s.possible, receipt)
            state = (
                "accepted"
                if receipt is not None
                else "unknown"
                if snapshot.possible
                else "prepared"
                if intent is not None
                else "missing"
            )
            if value.state != state:
                raise ProjectionError("invalid_source_state")
            if intent is not None and (
                intent.scope != WorkScope(self._scope.tenant_id, self._scope.account_id)
                or intent.work_id != row.event.work_id
                or intent.attempt_id != row.event.attempt_id
                or intent.result_sha256 != row.event.result_sha256
                or intent.receiver_id != self._policy.receiver_id
            ):
                raise ProjectionError("identity_conflict")
            return DelegationDelivery(
                snapshot,
                state,
                value.receiver_invoked,
            )
        except (WorkError, AttributeError, TypeError, ValueError):
            raise ProjectionError("invalid_source_state") from None

    def _ack(
        self,
        row: ProjectedResult,
        decision: str,
        reason: str,
        receipt: DeliveryReceipt | None = None,
    ) -> ProcessingAcknowledgement:
        return ProcessingAcknowledgement(
            row.event,
            hashlib.sha256(row.canonical()).hexdigest(),
            row.request_sha256,
            self._policy.sha256,
            cast('Literal["receiver_accepted","rejected_content","not_required_as_of"]', decision),
            reason,
            time.time_ns() // 1_000_000,
            receipt,
        )

    async def _evaluate(
        self, call: _Call, row: ProjectedResult
    ) -> tuple[ProcessingAcknowledgement | None, str]:
        try:
            await self._source_event(row)
        except ProjectionError as error:
            if error.code != "storage_unavailable":
                raise
            return None, "unavailable"
        self._check(call)
        if row.validation == "rejected":
            return self._ack(row, "rejected_content", "rejected_content"), "acknowledged"
        if row.event.disposition != "eligible_at_commit":
            return self._ack(row, "not_required_as_of", row.event.disposition), "acknowledged"
        self._require()
        try:
            snapshot = self._snapshot_delivery(await self._delivery.inspect(row.event.work_id), row)
            view = _result(
                await self._results.inspect(row.event.work_id),
                self._scope,
                row.event.work_id,
                self._evidence,
            )
            if (
                view.issued.attempt_id != row.event.attempt_id
                or view.recorded.sha256 != row.event.result_sha256
                or view.view.execution.record.payload.sha256 != row.request_sha256
                or (
                    view.request.delegation_id,
                    view.request.case_id,
                    view.request.request_revision,
                    view.request.input_fingerprint,
                )
                != (row.delegation_id, row.case_id, row.request_revision, row.input_fingerprint)
            ):
                raise ProjectionError("identity_conflict")
            route = next(
                (
                    b
                    for b in self._policy.bindings
                    if b.case_id == view.request.case_id
                    and b.conversation_id == view.request.conversation_id
                ),
                None,
            )
            if route is None:
                # Bindings are frozen at the policy upgrade, so an unroutable result
                # stays unACKed forever; it must not block later results.
                self._counts["unroutable"] += 1
                return None, "unavailable"
            if (
                snapshot.snapshot.intent is not None
                and snapshot.snapshot.intent.recipient_id != route.recipient_id
            ):
                raise ProjectionError("identity_conflict")
            # Original receipt is a fact before applying any fresh applicability policy.
            if snapshot.snapshot.receipt is not None:
                return self._ack(
                    row, "receiver_accepted", "known_receipt", snapshot.snapshot.receipt
                ), "acknowledged"
            applicability = view.view.applicability
            if not snapshot.snapshot.possible:
                if applicability == "unavailable":
                    return None, "unavailable"
                if applicability in {
                    "outdated",
                    "case_cancelled",
                    "expired",
                    "execution_ineligible",
                }:
                    return self._ack(row, "not_required_as_of", applicability), "acknowledged"
                if applicability not in {"candidate", "clarification"}:
                    raise ProjectionError("invalid_source_state")
            self._proceed(call)
            self._require()
            call.writing = True
            delivered = self._snapshot_delivery(
                await self._delivery.deliver_once(row.event.work_id), row
            )
            if (
                delivered.snapshot.intent is not None
                and delivered.snapshot.intent.recipient_id != route.recipient_id
            ):
                raise ProjectionError("identity_conflict")
            if delivered.snapshot.receipt is not None:
                return self._ack(
                    row, "receiver_accepted", "known_receipt", delivered.snapshot.receipt
                ), "acknowledged"
            return None, "unknown"
        except (CompletionError, DelegationRunError) as error:
            if error.code == "acknowledgement_unknown":
                return None, "unknown"
            code = _dependency_code(error.code)
            if code == "storage_unavailable" or error.code in {
                "not_eligible",
                "expired",
                "case_changed",
                "case_cancelled",
            }:
                return None, "unavailable"
            raise ProjectionError(code) from None

    def _committed(
        self,
        value: tuple[ProcessingCheckpoint, ProcessingAcknowledgement | None],
        expected: ProcessingCheckpoint,
        row: ProjectedResult,
    ) -> tuple[ProcessingCheckpoint, ProcessingAcknowledgement | None]:
        if (
            type(value) is not tuple
            or len(value) != 2
            or type(value[0]) is not ProcessingCheckpoint
        ):
            raise ProjectionError("invalid_source_state")
        p = value[0]
        from .projection_models import ProjectionBinding

        copied = ProcessingCheckpoint(
            ProjectionBinding(
                p.binding.source_id,
                WorkScope(p.binding.scope.tenant_id, p.binding.scope.account_id),
            ),
            p.policy_sha256,
            p.revision,
            p.terminal_watermark,
            p.scan_after,
            p.terminal_count,
            p.projected_through,
        )
        if (
            copied.binding != expected.binding
            or copied.policy_sha256 != expected.policy_sha256
            or copied.revision < expected.revision
            or copied.terminal_watermark < expected.terminal_watermark
            or copied.terminal_count < expected.terminal_count
            or copied.projected_through < expected.projected_through
        ):
            raise ProjectionError("invalid_source_state")
        ack = None if value[1] is None else parse_ack(value[1].canonical())
        if ack is not None and (
            event_digest(ack.event) != event_digest(row.event)
            or ack.projected_sha256 != hashlib.sha256(row.canonical()).hexdigest()
            or ack.request_sha256 != row.request_sha256
            or ack.policy_sha256 != self._policy.sha256
        ):
            raise ProjectionError("identity_conflict")
        return copied, ack

    def _proceed(self, call: _Call) -> None:
        # close() spares a call mid-write; that call still starts no later row or send.
        if self._closed:
            call.abandoned = True
        self._check(call)

    async def _step(self, call: _Call, limit: int) -> ProcessingStep:
        page = self._page(await self._processing._page(limit), limit)
        point = page.checkpoint
        outcomes = []
        for row in page.rows:
            self._proceed(call)
            self._counts["examined"] += 1
            self._require()
            ack, state = await self._evaluate(call, row)
            self._check(call)
            self._require()
            call.writing = True
            try:
                point, known = self._committed(
                    await self._processing._commit(point, row, ack), point, row
                )
            except ProjectionError as error:
                if error.code not in {"acknowledgement_unknown", "checkpoint_conflict"}:
                    raise
                original_code = error.code
                try:
                    found = await self._processing._reconcile(row)
                except Exception:  # noqa: BLE001 - uncertain write remains uncertain after failed lookup
                    raise ProjectionError(original_code) from None
                if found is None:
                    raise ProjectionError(original_code)
                point, known = self._committed(found, point, row)
                self._counts["ack_reconciliations"] += 1
            call.writing = False
            self._counts["acknowledged" if known is not None else state] += 1
            outcomes.append(
                ProcessingOutcome(
                    row.event.sequence,
                    "acknowledged"
                    if known is not None
                    else cast('Literal["unknown","unavailable"]', state),
                    known,
                )
            )
        return ProcessingStep(page.checkpoint, point, tuple(outcomes))
