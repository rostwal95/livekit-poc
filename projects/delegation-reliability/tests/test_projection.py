"""Projection contracts and owned-I/O behavior; actual durability is a separate gate."""

import asyncio
import hashlib
import time
import unittest
from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4

from test_coordinator import request
from test_runner import POLICY, FakeCases, FakeExecution, result_for

from continuity_lab.execution_api import AttemptResult, IssuedAttempt
from continuity_lab.result_feed_api import ResultFeedCursor, ResultFeedEvent, ResultFeedPage
from continuity_lab.work_api import WorkError, WorkScope
from delegation_reliability.contracts import Attempt, Scope, encode_result
from delegation_reliability.coordinator import CaseSnapshot
from delegation_reliability.projection_models import (
    ApplicabilityObservation,
    ProjectedResult,
    ProjectionBatch,
    ProjectionBinding,
    ProjectionCheckpoint,
    ProjectionError,
    ProjectionLimits,
    event_digest,
    parse_projected,
)
from delegation_reliability.projector import ProjectionProjector
from delegation_reliability.security import EvidenceRecord


class Feed:
    def __init__(self, scope, events):
        self.scope = scope
        self.source_id = str(uuid4())
        self.events = [replace(e, source_id=self.source_id) for e in events]
        self.closed = self.reads = 0
        self.failure = None
        self.alter = lambda page: page
        self.entered = asyncio.Event()
        self.release = None

    async def read(self, *, after=None, limit=25):
        self.reads += 1
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.failure:
            raise self.failure
        after = after or ResultFeedCursor(self.source_id, self.scope, 0)
        events = tuple(e for e in self.events if e.sequence > after.sequence)[:limit]
        point = events[-1].sequence if events else after.sequence
        high = self.events[-1].sequence if self.events else 0
        return self.alter(
            ResultFeedPage(
                self.source_id,
                self.scope,
                after,
                events,
                ResultFeedCursor(self.source_id, self.scope, point),
                ResultFeedCursor(self.source_id, self.scope, high),
                point < high,
            )
        )

    async def close(self):
        self.closed += 1


class Projection:
    def __init__(self, feed):
        self.scope, self.source_id = feed.scope, feed.source_id
        self.point = ProjectionCheckpoint(ProjectionBinding(feed.source_id, feed.scope), 0, 0)
        self.rows = []
        self.writes = self.lookups = self.closed = 0
        self.failure = None
        self.lookup_failure = False
        self.persist_unknown = True

    async def checkpoint(self):
        return self.point

    async def _apply(self, point, rows):
        self.writes += 1
        if self.failure is None or self.persist_unknown:
            before = self.point
            self.rows.extend(rows)
            self.point = ProjectionCheckpoint(
                point.binding, rows[-1].event.sequence, len(self.rows)
            )
        if self.failure:
            raise self.failure
        return ProjectionBatch(before, self.point, rows, False)

    async def _reconcile(self, point, rows):
        self.lookups += 1
        if self.lookup_failure:
            raise RuntimeError("PRIVATE_LOOKUP")
        if self.point.sequence < rows[-1].event.sequence:
            return None
        return ProjectionBatch(self.point, self.point, tuple(self.rows), True)

    async def close(self):
        self.closed += 1


class ProjectorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.value = request()
        self.execution = FakeExecution(self.value)
        now = time.time_ns() // 1_000_000
        grant = IssuedAttempt(
            self.execution.record,
            str(uuid4()),
            "project_first",
            1,
            str(uuid4()),
            1,
            now,
            now + 10000,
        )
        self.execution.current = grant
        self.execution.issues[grant.command_id] = grant
        transport = replace(
            self.value, attempt=Attempt("attempt_" + grant.attempt_id.replace("-", ""), 1)
        )
        result = AttemptResult(
            grant.record.work_id,
            grant.attempt_id,
            encode_result(result_for(transport)),
            now,
            "eligible_at_commit",
        )
        self.execution.results[grant.attempt_id] = result
        event = ResultFeedEvent(
            str(uuid4()),
            str(uuid4()),
            self.execution.scope,
            1,
            result.work_id,
            result.attempt_id,
            grant.command_id,
            result.sha256,
            now,
            result.disposition,
            "live",
        )
        self.feed = Feed(self.execution.scope, [event])
        self.projection = Projection(self.feed)
        self.cases = FakeCases(self.value)
        self.clients = []

    def client(self, **kw):
        result = ProjectionProjector(
            events=self.feed,
            executions=self.execution,
            projections=self.projection,
            scope=self.value.scope,
            evidence=(EvidenceRecord(self.value.scope, self.value.evidence[0], POLICY),),
            case_authority=self.cases,
            **kw,
        )
        self.clients.append(result)
        return result

    async def asyncTearDown(self):
        if self.feed.release is not None:
            self.feed.release.set()
        for client in self.clients:
            await client.close()

    async def test_useful_result_projects_refs_and_asof_only_then_empty(self):
        client = self.client()
        result = await client.project_once()
        self.assertEqual((result.before.sequence, result.after.sequence), (0, 1))
        row = result.rows[0]
        self.assertEqual(row.validation, "validated")
        self.assertEqual(row.observation.applicability, "candidate")
        self.assertEqual(row.observation.kind, "as_of_non_atomic")
        self.assertNotIn(b"policy_version", row.canonical())
        self.assertEqual(parse_projected(row.canonical()), row)
        empty = await client.project_once()
        self.assertEqual(empty.rows, ())
        self.assertEqual(self.projection.writes, 1)
        self.assertEqual((self.execution.issue_count, self.execution.complete_count), (0, 0))

    async def test_case_only_change_does_not_rewrite_original_observation(self):
        client = self.client()
        first = (await client.project_once()).rows[0].canonical()
        self.cases.current = replace(self.cases.current, request_revision=99)
        self.assertEqual((await client.project_once()).rows, ())
        self.assertEqual(self.projection.rows[0].canonical(), first)
        self.assertEqual(self.projection.rows[0].observation.case_revision, 1)

    async def test_outdated_case_is_an_explicit_asof_observation(self):
        self.cases.current = replace(self.cases.current, request_revision=2)
        row = (await self.client().project_once()).rows[0]
        self.assertEqual(
            (row.observation.applicability, row.observation.case_revision), ("outdated", 2)
        )

    async def test_cancelled_case_is_an_explicit_asof_observation(self):
        self.cases.current = replace(self.cases.current, cancelled=True)
        self.assertEqual(
            (await self.client().project_once()).rows[0].observation.applicability, "case_cancelled"
        )

    async def test_foreign_case_is_discarded_without_disclosure(self):
        self.cases.current = CaseSnapshot(
            Scope("PRIVATE_FOREIGN", "account"), "PRIVATE_CASE", 33, False
        )
        row = (await self.client().project_once()).rows[0]
        self.assertEqual(row.observation.applicability, "unavailable")
        self.assertIsNone(row.observation.case_revision)
        self.assertNotIn(b"PRIVATE", row.canonical())

    async def test_case_failure_is_unavailable_and_can_advance(self):
        self.cases.failure = RuntimeError("PRIVATE_CASE")
        row = (await self.client().project_once()).rows[0]
        self.assertEqual(row.observation.case_status, "unavailable")
        self.assertEqual(self.projection.point.sequence, 1)

    async def test_definite_bad_result_is_quarantined(self):
        old = next(iter(self.execution.results.values()))
        bad = replace(old, body=b"{}")
        self.execution.results[bad.attempt_id] = bad
        self.feed.events[0] = replace(self.feed.events[0], result_sha256=bad.sha256)
        row = (await self.client().project_once()).rows[0]
        self.assertEqual(row.validation, "rejected")
        self.assertIsNone(row.observation)
        self.assertEqual(self.projection.point.sequence, 1)

    async def test_invalid_original_contract_has_no_invented_logical_binding(self):
        from continuity_lab.work_api import WorkPayload

        old = self.execution.current
        record = replace(
            old.record,
            payload=WorkPayload(
                "booking.evaluate_policy", b"{}", old.record.payload.deadline_at_ms
            ),
        )
        self.execution.current = replace(old, record=record)
        self.execution.issues[old.command_id] = self.execution.current
        row = (await self.client().project_once()).rows[0]
        self.assertEqual(row.validation, "rejected")
        self.assertIsNone(row.case_id)
        self.assertIsNone(row.delegation_id)

    async def test_misbound_original_request_discards_all_logical_metadata(self):
        from continuity_lab.work_api import WorkPayload
        from delegation_reliability.contracts import encode_request

        for foreign in (False, True):
            old = self.execution.current
            value = (
                request(scope={"tenant_id": "foreign", "account_id": "account"})
                if foreign
                else self.value
            )
            record = replace(
                old.record,
                idempotency_key="wrong_binding" if not foreign else value.delegation_id,
                payload=WorkPayload(
                    "booking.evaluate_policy", encode_request(value), value.deadline_at_ms
                ),
            )
            self.execution.issues[old.command_id] = replace(old, record=record)
            self.projection.point = ProjectionCheckpoint(self.projection.point.binding, 0, 0)
            self.projection.rows = []
            row = (await self.client().project_once()).rows[0]
            self.assertEqual(row.validation, "rejected")
            self.assertIsNone(row.case_id)
            self.assertIsNone(row.delegation_id)
            self.assertNotIn(b"foreign", row.canonical())

    async def test_invalid_evidence_constructor_has_projection_error_boundary(self):
        with self.assertRaisesRegex(ProjectionError, "^invalid_input$"):
            ProjectionProjector(
                events=self.feed,
                executions=self.execution,
                projections=self.projection,
                scope=self.value.scope,
                evidence=(),
                case_authority=self.cases,
            )

    async def test_missing_historical_grant_stops_without_advance(self):
        self.execution.issues.clear()
        with self.assertRaisesRegex(ProjectionError, "^invalid_source_state$"):
            await self.client().project_once()
        self.assertEqual(self.projection.writes, 0)

    async def test_source_result_digest_mismatch_stops_without_quarantine(self):
        self.feed.events[0] = replace(self.feed.events[0], result_sha256="0" * 64)
        with self.assertRaisesRegex(ProjectionError, "^invalid_source_state$"):
            await self.client().project_once()
        self.assertEqual(self.projection.writes, 0)

    async def test_unavailable_feed_does_not_advance(self):
        self.feed.failure = WorkError("storage_unavailable")
        with self.assertRaisesRegex(ProjectionError, "^storage_unavailable$"):
            await self.client().project_once()
        self.assertEqual(self.projection.writes, 0)

    async def test_unavailable_execution_does_not_advance(self):
        self.execution.lookup_failure = True
        with self.assertRaisesRegex(ProjectionError, "^storage_unavailable$"):
            await self.client().project_once()
        self.assertEqual(self.projection.writes, 0)

    async def test_changed_source_or_scope_rejected_before_read(self):
        client = self.client()
        self.feed.source_id = str(uuid4())
        with self.assertRaisesRegex(ProjectionError, "^source_mismatch$"):
            await client.project_once()
        self.assertEqual(self.feed.reads, 0)

    async def test_changed_scope_rejected_before_read(self):
        client = self.client()
        self.execution.scope = WorkScope("foreign", "account")
        with self.assertRaisesRegex(ProjectionError, "^unauthorized$"):
            await client.project_once()
        self.assertEqual(self.feed.reads, 0)

    async def test_corrupt_page_gap_cannot_skip_event(self):
        def corrupt(page):
            object.__setattr__(page.events[0], "sequence", 2)
            return page

        self.feed.alter = corrupt
        with self.assertRaisesRegex(ProjectionError, "^invalid_source_state$"):
            await self.client().project_once()
        self.assertEqual(self.projection.writes, 0)

    async def test_unknown_ack_reads_exact_original_once_without_second_write(self):
        self.projection.failure = ProjectionError("acknowledgement_unknown")
        result = await self.client().project_once()
        self.assertTrue(result.reconciled)
        self.assertEqual((result.before.sequence, result.after.sequence), (1, 1))
        self.assertEqual((self.projection.writes, self.projection.lookups), (1, 1))

    async def test_unknown_ack_absence_stays_unknown_without_second_write(self):
        self.projection.failure = ProjectionError("acknowledgement_unknown")
        self.projection.persist_unknown = False
        with self.assertRaisesRegex(ProjectionError, "^acknowledgement_unknown$"):
            await self.client().project_once()
        self.assertEqual((self.projection.writes, self.projection.lookups), (1, 1))

    async def test_unknown_ack_lookup_failure_stays_unknown(self):
        self.projection.failure = ProjectionError("acknowledgement_unknown")
        self.projection.lookup_failure = True
        with self.assertRaisesRegex(ProjectionError, "^acknowledgement_unknown$"):
            await self.client().project_once()
        self.assertEqual((self.projection.writes, self.projection.lookups), (1, 1))

    async def test_page_event_and_execution_are_copied_before_case_await(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def held(*, case_id):
            entered.set()
            await release.wait()
            return self.cases.current

        self.cases.snapshot = held
        task = asyncio.create_task(self.client().project_once())
        await asyncio.wait_for(entered.wait(), 1)
        object.__setattr__(self.feed.events[0], "result_sha256", "f" * 64)
        object.__setattr__(self.execution.record, "cancel_requested", True)
        release.set()
        row = (await task).rows[0]
        self.assertNotEqual(row.event.result_sha256, "f" * 64)
        self.assertFalse(row.observation.cancel_requested)

    async def test_abandoned_feed_keeps_capacity_and_never_writes_later(self):
        self.feed.release = asyncio.Event()
        client = self.client(max_active=1, timeout_ms=20, cleanup_ms=20)
        task = asyncio.create_task(client.project_once())
        await asyncio.wait_for(self.feed.entered.wait(), 1)
        with self.assertRaisesRegex(ProjectionError, "^deadline_exceeded$"):
            await task
        self.assertEqual(client.pending_count, 1)
        with self.assertRaisesRegex(ProjectionError, "^capacity$"):
            await client.project_once()
        with self.assertRaisesRegex(ProjectionError, "^cleanup_incomplete$"):
            await client.close()
        self.feed.release.set()
        await asyncio.sleep(0.01)
        await client.close()
        self.assertEqual(self.projection.writes, 0)
        self.assertEqual(
            (self.feed.closed, self.execution.closed, self.projection.closed), (1, 1, 1)
        )

    async def test_cancelled_waiter_retains_actual_task_until_settlement(self):
        self.feed.release = asyncio.Event()
        client = self.client(max_active=1)
        task = asyncio.create_task(client.project_once())
        await asyncio.wait_for(self.feed.entered.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(client.pending_count, 1)
        self.feed.release.set()
        await asyncio.sleep(0.01)
        self.assertEqual(self.projection.writes, 0)

    async def test_bad_limits_and_closed_owner_reject(self):
        client = self.client()
        for limit in (0, 9, True):
            with self.assertRaisesRegex(ProjectionError, "^invalid_input$"):
                await client.project_once(limit=limit)
        await client.close()
        with self.assertRaisesRegex(ProjectionError, "^closed$"):
            await client.project_once()

    async def test_logging_failure_cannot_change_projection(self):
        with patch(
            "delegation_reliability.projection_api.LOGGER.info",
            side_effect=RuntimeError("PRIVATE_LOG"),
        ):
            client = self.client()
            self.assertEqual((await client.project_once()).after.sequence, 1)
        self.assertEqual(client.metrics()["telemetry_failed"], 1)


class ProjectionModelTests(unittest.TestCase):
    def test_safe_error_code_and_bounded_limits(self):
        self.assertEqual(str(ProjectionError([])), "invalid_input")
        for n in (0, 30001, True):
            with self.assertRaises(ProjectionError):
                ProjectionLimits(n)

    def test_int64_source_cursor_is_separate_from_retention(self):
        binding = ProjectionBinding(str(uuid4()), WorkScope("tenant", "account"))
        with self.assertRaises(ProjectionError):
            ProjectionCheckpoint(binding, 30001, 30001)
        self.assertEqual(ProjectionLimits(30000).max_records, 30000)

    def test_strict_persisted_codec_rejects_unknown_duplicate_or_noncanonical(self):
        for raw in (b"{}", b'{"event":1,"event":2}', b"[]", b" " * 8193):
            with self.assertRaisesRegex(ProjectionError, "^invalid_input$"):
                parse_projected(raw)

    def test_unavailable_observation_cannot_contain_foreign_case_metadata(self):
        now = time.time_ns() // 1_000_000
        with self.assertRaises(ProjectionError):
            ApplicabilityObservation(
                "unavailable",
                "result_recorded",
                False,
                None,
                now,
                "unavailable",
                99,
                False,
                now,
                now,
            )


class ProjectionStorageBoundaryTests(unittest.TestCase):
    def row(self, *, scope=None, source=None, sequence=1):
        scope = scope or WorkScope("tenant", "account")
        event = ResultFeedEvent(
            str(uuid4()),
            source or str(uuid4()),
            scope,
            sequence,
            str(uuid4()),
            str(uuid4()),
            "issue_test",
            "a" * 64,
            2000000000000,
            "eligible_at_commit",
            "live",
        )
        return ProjectedResult(
            event,
            "b" * 64,
            None,
            None,
            None,
            None,
            "rejected",
            "invalid_contract",
            None,
            2000000000000,
        )

    def test_valid_source_event_int64_does_not_narrow_to_retention_cap(self):
        row = self.row(sequence=30001)
        self.assertEqual(parse_projected(row.canonical()).event.sequence, 30001)
        self.assertEqual(row.schema_version, 1)
        self.assertEqual(row.kind, "result_projection")

    def test_foreign_corrupted_stored_body_cannot_escape_authenticated_read(self):
        from delegation_reliability.projection_store import ProjectionStore

        store = object.__new__(ProjectionStore)
        store.binding = ProjectionBinding(str(uuid4()), WorkScope("tenant", "account"))
        for row in (
            self.row(),
            self.row(source=store.binding.source_id, scope=WorkScope("foreign", "account")),
        ):
            body = row.canonical()
            stored = {
                "body_json": body.decode(),
                "body_sha256": hashlib.sha256(body).hexdigest(),
                "event_sequence": row.event.sequence,
                "event_id": row.event.event_id,
                "work_id": row.event.work_id,
                "attempt_id": row.event.attempt_id,
                "result_sha256": row.event.result_sha256,
                "event_sha256": event_digest(row.event),
            }
            with self.assertRaisesRegex(ProjectionError, "^schema_mismatch$"):
                store._decode(stored)

    def test_strict_observation_and_schema_enum_types(self):
        now = 2000000000000
        base = ApplicabilityObservation(
            "candidate", "result_recorded", False, str(uuid4()), now, "observed", 1, False, now, now
        )
        for change in (
            {"applicability": []},
            {"kind": []},
            {"case_status": []},
            {"cancel_requested": 1},
        ):
            with self.assertRaisesRegex(ProjectionError, "^invalid_input$"):
                replace(base, **change)
        row = self.row()
        for change in ({"schema_version": True}, {"kind": []}, {"schema_version": 2}):
            with self.assertRaisesRegex(ProjectionError, "^invalid_input$"):
                replace(row, **change)


class ProjectionClientLifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_blocking_read_retains_slot_through_waiter_abandonment(self):
        import threading

        from continuity_lab.work_api import BearerToken, WorkDirectory, WorkPrincipal
        from delegation_reliability.projection_api import ProjectionClient

        class Store:
            def __init__(self):
                self.binding = ProjectionBinding(str(uuid4()), WorkScope("tenant", "account"))
                self.entered = threading.Event()
                self.release = threading.Event()

            def checkpoint(self):
                self.entered.set()
                assert self.release.wait(2)
                return ProjectionCheckpoint(self.binding, 0, 0)

        store = Store()
        token = BearerToken("synthetic-projection-" + "x" * 40)
        client = ProjectionClient(
            store,
            WorkDirectory({token: WorkPrincipal("actor", store.binding.scope)}),
            token,
            max_active=1,
            timeout_ms=20,
            cleanup_ms=20,
        )
        task = asyncio.create_task(client.checkpoint())
        try:
            await asyncio.to_thread(store.entered.wait, 1)
            with self.assertRaisesRegex(ProjectionError, "^deadline_exceeded$"):
                await task
            self.assertEqual(client.pending_count, 1)
            with self.assertRaisesRegex(ProjectionError, "^capacity$"):
                await client.checkpoint()
            with self.assertRaisesRegex(ProjectionError, "^cleanup_incomplete$"):
                await client.close()
        finally:
            store.release.set()
            await asyncio.sleep(0.01)
            await client.close()
        self.assertEqual(client.pending_count, 0)

    async def test_client_authenticates_before_storage_or_identifier_validation(self):
        from continuity_lab.work_api import BearerToken, WorkDirectory, WorkPrincipal
        from delegation_reliability.projection_api import open_projection_client

        token = BearerToken("synthetic-projection-" + "x" * 40)
        directory = WorkDirectory({token: WorkPrincipal("actor", WorkScope("tenant", "account"))})
        with patch("delegation_reliability.projection_api.ProjectionStore") as store:
            with self.assertRaisesRegex(ProjectionError, "^unauthorized$"):
                open_projection_client(
                    settings=object(),
                    directory=directory,
                    token=BearerToken("invalid-" + "x" * 40),
                    source_id="invalid",
                )
            store.assert_not_called()
