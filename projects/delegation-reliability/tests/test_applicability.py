"""Refresh identity, monotonic evidence and owned I/O; durability has its own gate."""

import asyncio
import hashlib
import threading
import time
import unittest
from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4

import test_projection as fixtures
from test_runner import POLICY

from continuity_lab.work_api import BearerToken, WorkDirectory, WorkError, WorkPrincipal, WorkScope
from delegation_reliability import ApplicabilityRefresher
from delegation_reliability.applicability_api import ApplicabilityClient
from delegation_reliability.applicability_models import (
    ApplicabilityView,
    DisplayTombstone,
    RefreshPolicy,
    _RefreshDraft,
    parse_refresh,
    parse_refresh_policy,
    parse_tombstone,
    refreshed,
)
from delegation_reliability.contracts import Scope
from delegation_reliability.coordinator import CaseSnapshot
from delegation_reliability.projection_models import (
    ProjectionBinding,
    ProjectionError,
    parse_projected,
)
from delegation_reliability.security import EvidenceRecord


class Metadata:
    def __init__(self, row):
        self.row = parse_projected(row.canonical())
        self.scope, self.source_id = row.event.scope, row.event.source_id
        self.policy = RefreshPolicy(30, 8)
        self.commands = {}
        self.latest = self.tombstone = None
        self.revision = self.commits = self.command_reads = self.closed = 0
        self.failure = None
        self.persist = True
        self.lookup_failure = False
        self.alter = lambda value: value

    async def command(self, *, command_id):
        self.command_reads += 1
        if self.commits and self.lookup_failure:
            raise RuntimeError("PRIVATE_LOOKUP")
        return self.commands.get(command_id)

    async def inspect(self, *, work_id, attempt_id):
        if (work_id, attempt_id) != (self.row.event.work_id, self.row.event.attempt_id):
            raise ProjectionError("not_found")
        return ApplicabilityView(self.row, self.revision, self.latest, self.tombstone)

    async def _commit(self, *, command_id, expected_revision, draft):
        self.commits += 1
        if self.persist:
            receipt = refreshed(
                command_id=command_id,
                expected_revision=expected_revision,
                policy=self.policy,
                draft=draft,
                previous=self.latest,
                observed_at_ms=time.time_ns() // 1_000_000,
            )
            self.commands[command_id] = self.latest = receipt
            self.revision = receipt.revision
        if self.failure:
            raise ProjectionError(self.failure)
        return self.alter(self.latest)

    async def close(self):
        self.closed += 1


class ApplicabilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.owner = fixtures.ProjectorTests(
            "test_useful_result_projects_refs_and_asof_only_then_empty"
        )
        await self.owner.asyncSetUp()
        self.row = (await self.owner.client().project_once()).rows[0]
        self.metadata = Metadata(self.row)
        self.clients = []

    def client(self, **kw):
        client = ApplicabilityRefresher(
            events=self.owner.feed,
            executions=self.owner.execution,
            applicability=self.metadata,
            scope=self.owner.value.scope,
            evidence=(
                EvidenceRecord(self.owner.value.scope, self.owner.value.evidence[0], POLICY),
            ),
            case_authority=self.owner.cases,
            **kw,
        )
        self.clients.append(client)
        return client

    async def refresh(self, client=None, *, command_id=None, expected_revision=None):
        return await (client or self.client()).refresh(
            work_id=self.row.event.work_id,
            attempt_id=self.row.event.attempt_id,
            command_id=command_id or str(uuid4()),
            expected_revision=self.metadata.revision
            if expected_revision is None
            else expected_revision,
        )

    async def asyncTearDown(self):
        if self.owner.feed.release is not None:
            self.owner.feed.release.set()
        for client in self.clients:
            await client.close()
        await self.owner.asyncTearDown()

    async def test_normal_refresh_is_separate_from_original_projection_and_execution(self):
        original = self.row.canonical()
        result = await self.refresh()
        self.assertEqual(
            (result.revision, result.classification, result.reason), (1, "current", "candidate")
        )
        self.assertEqual(parse_refresh(result.canonical()), result)
        self.assertEqual(self.metadata.row.canonical(), original)
        self.assertEqual(
            (self.owner.execution.issue_count, self.owner.execution.complete_count), (0, 0)
        )
        self.assertEqual(result.observation.kind, "as_of_non_atomic")

    async def test_case_advanced_cannot_revive_after_stale_or_unavailable_reads(self):
        self.owner.cases.current = replace(self.owner.cases.current, request_revision=4)
        first = await self.refresh()
        self.assertEqual((first.classification, first.reason), ("outdated", "revision_advanced"))
        self.owner.cases.current = replace(self.owner.cases.current, request_revision=1)
        self.assertEqual((await self.refresh()).classification, "outdated")
        self.owner.cases.failure = RuntimeError("PRIVATE_CASE")
        result = await self.refresh()
        self.assertEqual(result.classification, "outdated")
        self.assertEqual(result.observation.case_status, "unavailable")
        self.assertEqual(result.retained.highest_case_revision, 4)

    async def test_later_work_cancel_uses_current_flag_despite_result_recorded_status(self):
        await self.refresh()
        self.owner.execution.record = replace(self.owner.execution.record, cancel_requested=True)
        result = await self.refresh()
        self.assertEqual(result.observation.execution_status, "result_recorded")
        self.assertEqual((result.classification, result.reason), ("invalidated", "work_cancelled"))
        self.owner.execution.record = replace(self.owner.execution.record, cancel_requested=False)
        self.assertEqual((await self.refresh()).reason, "work_cancelled")

    async def test_case_cancel_latches_and_unavailable_does_not_clear_it(self):
        self.owner.cases.current = replace(self.owner.cases.current, cancelled=True)
        self.assertEqual((await self.refresh()).reason, "case_cancelled")
        self.owner.cases.current = replace(self.owner.cases.current, cancelled=False)
        self.assertEqual((await self.refresh()).classification, "invalidated")
        self.owner.cases.failure = RuntimeError("PRIVATE_CASE")
        result = await self.refresh()
        self.assertTrue(result.retained.case_cancelled)
        self.assertEqual(result.observation.case_status, "unavailable")

    async def test_local_deadline_observation_latches_without_claiming_database_time(self):
        deadline = self.owner.value.deadline_at_ms
        with patch(
            "delegation_reliability.applicability_refresher.time.time_ns",
            return_value=(deadline + 1) * 1_000_000,
        ):
            result = await self.refresh()
        self.assertEqual(result.reason, "deadline_expired_local_as_of")
        self.assertEqual((await self.refresh()).reason, result.reason)
        self.assertIn(b"local_as_of", result.canonical())

    async def test_eligible_result_does_not_expire_with_its_old_grant_lease(self):
        original = self.owner.execution.current
        grant = replace(
            original,
            issued_at_ms=original.issued_at_ms - 11000,
            lease_until_ms=original.issued_at_ms - 1000,
        )
        self.owner.execution.current = grant
        self.owner.execution.issues[grant.command_id] = grant
        self.assertEqual((await self.refresh()).classification, "current")

    async def test_original_different_attempt_witness_never_revives_on_first_refresh(self):
        old = self.row.observation
        observation = replace(
            old,
            applicability="execution_ineligible",
            current_attempt_id=str(uuid4()),
            case_status="not_read",
            case_revision=None,
            case_cancelled=None,
            case_observed_at_ms=None,
        )
        self.metadata.row = replace(self.metadata.row, observation=observation)
        result = await self.refresh()
        self.assertEqual(
            (result.classification, result.reason), ("invalidated", "attempt_advanced")
        )
        self.assertTrue(result.retained.attempt_changed_seen)
        # Independent current B still progresses rather than rejecting every observation.
        self.metadata = Metadata(self.row)
        self.assertEqual((await self.refresh()).classification, "current")

    async def test_original_cancel_witness_and_current_stale_read_remain_invalid(self):
        self.metadata.row = replace(
            self.metadata.row,
            observation=replace(
                self.row.observation, cancel_requested=True, applicability="execution_ineligible"
            ),
        )
        result = await self.refresh()
        self.assertEqual(result.reason, "work_cancelled")

    async def test_unavailable_only_recovers_with_later_verified_read(self):
        self.owner.cases.failure = RuntimeError("PRIVATE_CASE")
        first = await self.refresh()
        self.assertEqual(first.classification, "unavailable")
        self.owner.cases.failure = None
        self.assertEqual((await self.refresh()).classification, "current")
        self.assertEqual(first.classification, "unavailable")

    async def test_foreign_case_data_is_discarded_then_valid_work_progresses(self):
        original = self.owner.cases.current
        self.owner.cases.current = CaseSnapshot(
            Scope("PRIVATE_TENANT", "other"), "PRIVATE_CASE", 999, False
        )
        result = await self.refresh()
        self.assertEqual(result.classification, "unavailable")
        self.assertIsNone(result.observation.case_revision)
        self.assertNotIn(b"PRIVATE", result.canonical())
        self.owner.cases.current = original
        self.assertEqual((await self.refresh()).classification, "current")

    async def test_transient_feed_failure_is_safe_storage_error_and_zero_refresh(self):
        self.owner.feed.failure = WorkError("storage_unavailable")
        with self.assertRaisesRegex(ProjectionError, "^storage_unavailable$"):
            await self.refresh()
        self.assertEqual(self.metadata.commits, 0)
        self.owner.feed.failure = None
        self.assertEqual((await self.refresh()).classification, "current")

    async def test_missing_or_changed_historical_result_never_commits(self):
        grant = self.owner.execution.current
        original = self.owner.execution.results.pop(grant.attempt_id)
        with self.assertRaisesRegex(ProjectionError, "^invalid_source_state$"):
            await self.refresh()
        self.owner.execution.results[grant.attempt_id] = replace(
            original, body=b"PRIVATE_BAD_RESULT"
        )
        with self.assertRaisesRegex(ProjectionError, "^invalid_source_state$"):
            await self.refresh()
        self.assertEqual(self.metadata.commits, 0)
        self.owner.execution.results[grant.attempt_id] = original
        self.assertEqual((await self.refresh()).classification, "current")

    async def test_contradictory_current_result_snapshot_never_refreshes(self):
        original = self.owner.execution.observe

        async def contradictory(*, work_id):
            value = await original(work_id=work_id)
            return replace(value, result=replace(value.result, body=b"PRIVATE_OTHER_RESULT"))

        self.owner.execution.observe = contradictory
        with self.assertRaisesRegex(ProjectionError, "^invalid_source_state$"):
            await self.refresh()
        self.assertEqual(self.metadata.commits, 0)
        self.owner.execution.observe = original
        self.assertEqual((await self.refresh()).classification, "current")

    async def test_wrong_source_or_foreign_feed_scope_never_writes(self):
        client = self.client()
        self.owner.feed.source_id = str(uuid4())
        with self.assertRaisesRegex(ProjectionError, "^source_mismatch$"):
            await self.refresh(client)
        self.owner.feed.source_id = self.metadata.source_id
        self.owner.feed.scope = WorkScope("PRIVATE_FOREIGN", "account")
        with self.assertRaisesRegex(ProjectionError, "^unauthorized$"):
            await self.refresh(client)
        self.assertEqual(self.metadata.commits, 0)

    async def test_known_command_replays_before_new_source_case_reads_or_caps(self):
        command = str(uuid4())
        client = self.client()
        first = await self.refresh(client, command_id=command)
        reads = self.owner.feed.reads
        self.owner.feed.failure = WorkError("storage_unavailable")
        self.owner.feed.source_id = str(uuid4())
        self.owner.cases.failure = RuntimeError("PRIVATE_CASE")
        self.metadata.revision = 8
        replay = await self.refresh(client, command_id=command, expected_revision=0)
        self.assertEqual(replay.canonical(), first.canonical())
        self.assertEqual(self.owner.feed.reads, reads)
        self.assertEqual(self.metadata.commits, 1)

    async def test_changed_expected_revision_under_known_command_conflicts(self):
        command = str(uuid4())
        client = self.client()
        await self.refresh(client, command_id=command)
        with self.assertRaisesRegex(ProjectionError, "^identity_conflict$"):
            await self.refresh(client, command_id=command, expected_revision=1)
        self.assertEqual(self.metadata.commits, 1)

    async def test_stale_expected_revision_fails_without_write_or_source_read(self):
        client = self.client()
        await self.refresh(client)
        reads = self.owner.feed.reads
        with self.assertRaisesRegex(ProjectionError, "^checkpoint_conflict$"):
            await self.refresh(client, expected_revision=0)
        self.assertEqual((self.metadata.commits, self.owner.feed.reads), (1, reads))

    async def test_unknown_commit_reconciles_exact_command_once_without_second_write(self):
        self.metadata.failure = "acknowledgement_unknown"
        result = await self.refresh()
        self.assertEqual(result.revision, 1)
        self.assertEqual((self.metadata.commits, self.metadata.command_reads), (1, 2))

    async def test_conflicting_commit_reconciles_exact_command_once_without_second_write(self):
        self.metadata.failure = "checkpoint_conflict"
        result = await self.refresh()
        self.assertEqual(result.revision, 1)
        self.assertEqual((self.metadata.commits, self.metadata.command_reads), (1, 2))

    async def test_unknown_or_conflict_absence_keeps_original_code(self):
        for code in ("acknowledgement_unknown", "checkpoint_conflict"):
            self.metadata = Metadata(self.row)
            self.metadata.failure, self.metadata.persist = code, False
            with self.subTest(code=code), self.assertRaisesRegex(ProjectionError, "^" + code + "$"):
                await self.refresh()
            self.assertEqual((self.metadata.commits, self.metadata.command_reads), (1, 2))

    async def test_failed_reconciliation_does_not_replace_original_unknown(self):
        self.metadata.failure, self.metadata.lookup_failure = "acknowledgement_unknown", True
        with self.assertRaisesRegex(ProjectionError, "^acknowledgement_unknown$"):
            await self.refresh()
        self.assertEqual(self.metadata.commits, 1)

    async def test_public_head_eight_is_capacity_not_malformed_input(self):
        await self.refresh()
        self.metadata.revision = 8
        self.metadata.latest = replace(self.metadata.latest, expected_revision=7, revision=8)
        with self.assertRaisesRegex(ProjectionError, "^capacity$"):
            await self.refresh(expected_revision=8)
        self.assertEqual(self.metadata.commits, 1)

    async def test_raw_ineligible_or_nonresult_state_cannot_become_current(self):
        for changes in (
            {"applicability": "execution_ineligible"},
            {"execution_status": "running"},
            {"applicability": "outdated"},
        ):
            raw = replace(self.row.observation, **changes)
            draft = _RefreshDraft(self.row, 1, 1, raw)
            receipt = refreshed(
                command_id=str(uuid4()),
                expected_revision=0,
                policy=self.metadata.policy,
                draft=draft,
                previous=None,
                observed_at_ms=time.time_ns() // 1_000_000,
            )
            self.assertNotEqual(receipt.classification, "current")

    async def test_current_receipt_rejects_contradictory_public_values(self):
        result = await self.refresh()
        for changes in (
            {"applicability": "execution_ineligible"},
            {"current_attempt_id": str(uuid4())},
            {"case_revision": 2},
            {"case_cancelled": True},
            {"cancel_requested": True},
        ):
            with self.subTest(changes=changes), self.assertRaises(ProjectionError):
                replace(result, observation=replace(result.observation, **changes))
        with self.assertRaises(ProjectionError):
            replace(result, current_attempt_number=2)

    async def test_public_reason_requires_its_exact_retained_or_historical_witness(self):
        result = await self.refresh()
        for reason in (
            "work_cancelled",
            "case_cancelled",
            "deadline_expired_local_as_of",
            "attempt_advanced",
            "historical_cancelled",
            "historical_expired",
            "historical_superseded",
            "historical_lease_expired",
        ):
            with self.subTest(reason=reason), self.assertRaises(ProjectionError):
                replace(result, classification="invalidated", reason=reason)
        with self.assertRaises(ProjectionError):
            replace(result, classification="outdated", reason="revision_advanced")
        with self.assertRaises(ProjectionError):
            replace(result, reason="clarification")
        with self.assertRaises(ProjectionError):
            replace(result.retained, attempt_changed_seen=[])

    async def test_strict_codecs_and_primitive_bounds(self):
        result = await self.refresh()
        self.assertEqual(
            parse_refresh_policy(self.metadata.policy.canonical()), self.metadata.policy
        )
        for raw in (b"{}", b"[]", result.canonical() + b" ", b'{"command_id":1,"command_id":2}'):
            with self.assertRaises(ProjectionError):
                parse_refresh(raw)
        for changes in (
            {"classification": []},
            {"reason": {}},
            {"revision": True},
            {"schema_version": True},
        ):
            with self.subTest(changes=changes), self.assertRaises(ProjectionError):
                replace(result, **changes)
        for value in (True, 0, 30001):
            with self.assertRaises(ProjectionError):
                RefreshPolicy(max_commands=value)

    async def test_returned_command_is_copied_before_another_caller_mutates_it(self):
        command = str(uuid4())
        first = await self.refresh(command_id=command)
        replay = await self.refresh(command_id=command, expected_revision=0)
        object.__setattr__(first.event.scope, "tenant_id", "PRIVATE_MUTATED")
        self.assertNotIn(b"PRIVATE", replay.canonical())

    async def test_read_abandonment_holds_capacity_and_prevents_late_refresh(self):
        self.owner.feed.release = asyncio.Event()
        self.owner.feed.entered.clear()
        client = self.client(max_active=1, timeout_ms=20, cleanup_ms=20)
        task = asyncio.create_task(self.refresh(client))
        await asyncio.wait_for(self.owner.feed.entered.wait(), 1)
        with self.assertRaisesRegex(ProjectionError, "^deadline_exceeded$"):
            await task
        self.assertEqual(client.pending_count, 1)
        with self.assertRaisesRegex(ProjectionError, "^capacity$"):
            await self.refresh(client)
        with self.assertRaisesRegex(ProjectionError, "^cleanup_incomplete$"):
            await client.close()
        self.owner.feed.release.set()
        await asyncio.sleep(0.02)
        await client.close()
        self.assertEqual(self.metadata.commits, 0)

    async def test_read_cancellation_retains_owned_task_until_settled(self):
        self.owner.feed.release = asyncio.Event()
        self.owner.feed.entered.clear()
        client = self.client()
        task = asyncio.create_task(self.refresh(client))
        await asyncio.wait_for(self.owner.feed.entered.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(client.pending_count, 1)
        self.owner.feed.release.set()
        await asyncio.sleep(0.01)
        self.assertEqual(self.metadata.commits, 0)

    async def test_safe_operation_logs_never_include_case_failure_or_submitted_values(self):
        self.owner.cases.failure = RuntimeError("PRIVATE_CASE_PAYLOAD")
        client = self.client()
        with patch("delegation_reliability.projection_api.LOGGER.info") as log:
            result = await self.refresh(client)
        self.assertEqual(result.classification, "unavailable")
        log.assert_called_once_with(
            "result_projection",
            extra={"operation": "applicability_refresh", "code": "ok", "outcome": "succeeded"},
        )
        self.assertNotIn("PRIVATE", str(log.call_args))
        self.assertNotIn(self.row.event.work_id, str(log.call_args))

    async def test_original_higher_revision_witness_survives_first_stale_refresh(self):
        self.metadata.row = replace(
            self.metadata.row,
            observation=replace(self.row.observation, applicability="outdated", case_revision=4),
        )
        result = await self.refresh()
        self.assertEqual(
            (result.classification, result.retained.highest_case_revision), ("outdated", 4)
        )
        self.assertEqual(result.observation.case_revision, 1)

    async def test_telemetry_outage_preserves_refresh_fact_and_safe_counters(self):
        client = self.client()
        with patch(
            "delegation_reliability.projection_api.LOGGER.info",
            side_effect=RuntimeError("PRIVATE_LOG"),
        ):
            result = await self.refresh(client)
        self.assertEqual(result.classification, "current")
        self.assertEqual(client.metrics()["telemetry_failed"], 1)
        self.assertEqual(client.metrics()["refreshes_observed"], 1)
        self.assertNotIn("PRIVATE", str(dict(client.metrics())))


class ApplicabilityClientLifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def setup_values(self):
        owner = fixtures.ProjectorTests("test_useful_result_projects_refs_and_asof_only_then_empty")
        await owner.asyncSetUp()
        row = (await owner.client().project_once()).rows[0]
        principal = WorkPrincipal("refresh_user", row.event.scope)
        token = BearerToken("a" * 32)
        directory = WorkDirectory({token: principal})
        return owner, row, directory, token

    async def held_write(self, *, cancel):
        owner, row, directory, token = await self.setup_values()
        entered, release = threading.Event(), threading.Event()
        captured = []
        policy = RefreshPolicy()
        draft = _RefreshDraft(row, 1, 1, row.observation)
        command = str(uuid4())

        class Store:
            binding = ProjectionBinding(row.event.source_id, row.event.scope)

            def commit(self, command_id, expected_revision, copied):
                entered.set()
                if not release.wait(2):
                    raise RuntimeError("PRIVATE_HOLD")
                captured.append(copied)
                return refreshed(
                    command_id=command_id,
                    expected_revision=expected_revision,
                    policy=policy,
                    draft=copied,
                    previous=None,
                    observed_at_ms=time.time_ns() // 1_000_000,
                )

        store = Store()
        store.policy = policy
        client = ApplicabilityClient(
            store, directory, token, max_active=1, timeout_ms=20, cleanup_ms=20
        )
        original = row.canonical()
        task = asyncio.create_task(
            client._commit(command_id=command, expected_revision=0, draft=draft)
        )
        await asyncio.to_thread(entered.wait, 1)
        object.__setattr__(row.event.scope, "tenant_id", "PRIVATE_MUTATED")
        object.__setattr__(row.observation, "case_revision", 99)
        if cancel:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        else:
            with self.assertRaisesRegex(ProjectionError, "^acknowledgement_unknown$"):
                await task
        self.assertEqual(client.pending_count, 1)
        with self.assertRaisesRegex(ProjectionError, "^cleanup_incomplete$"):
            await client.close()
        release.set()
        await asyncio.sleep(0.03)
        await client.close()
        self.assertEqual(captured[0].projection.canonical(), original)
        self.assertEqual(captured[0].observation.case_revision, 1)
        await owner.asyncTearDown()

    async def test_write_timeout_retains_thread_and_deep_snapshot_until_settled(self):
        await self.held_write(cancel=False)

    async def test_write_cancellation_retains_thread_and_deep_snapshot_until_settled(self):
        await self.held_write(cancel=True)

    async def test_ambiguous_hide_looks_up_once_and_never_resubmits(self):
        owner, row, directory, token = await self.setup_values()
        policy = RefreshPolicy()
        tombstone = DisplayTombstone(
            row.event,
            hashlib.sha256(row.canonical()).hexdigest(),
            row.request_sha256,
            policy.sha256,
            time.time_ns() // 1_000_000,
        )

        class Store:
            binding = ProjectionBinding(row.event.source_id, row.event.scope)
            hides = reads = 0

            def hide(self, work, attempt):
                self.hides += 1
                raise ProjectionError("acknowledgement_unknown")

            def inspect(self, work, attempt):
                self.reads += 1
                return ApplicabilityView(row, 0, None, tombstone)

        store = Store()
        store.policy = policy
        client = ApplicabilityClient(store, directory, token)
        observed = await client.hide_display(
            work_id=row.event.work_id, attempt_id=row.event.attempt_id
        )
        self.assertEqual(observed, tombstone)
        self.assertEqual((store.hides, store.reads), (1, 1))
        await client.close()
        await owner.asyncTearDown()

    async def test_display_hide_replays_tombstone_without_changing_original_reads(self):
        owner, row, directory, token = await self.setup_values()
        policy = RefreshPolicy()
        receipt = refreshed(
            command_id=str(uuid4()),
            expected_revision=0,
            policy=policy,
            draft=_RefreshDraft(row, 1, 1, row.observation),
            previous=None,
            observed_at_ms=time.time_ns() // 1_000_000,
        )

        class Store:
            binding = ProjectionBinding(row.event.source_id, row.event.scope)
            tombstone = None

            def inspect(self, work, attempt):
                return ApplicabilityView(row, 1, receipt, self.tombstone)

            def hide(self, work, attempt):
                if self.tombstone is None:
                    self.tombstone = DisplayTombstone(
                        row.event,
                        hashlib.sha256(row.canonical()).hexdigest(),
                        row.request_sha256,
                        policy.sha256,
                        time.time_ns() // 1_000_000,
                    )
                return self.tombstone

        store = Store()
        store.policy = policy
        client = ApplicabilityClient(store, directory, token)
        original = await client.inspect(work_id=row.event.work_id, attempt_id=row.event.attempt_id)
        tomb = await client.hide_display(work_id=row.event.work_id, attempt_id=row.event.attempt_id)
        self.assertEqual(parse_tombstone(tomb.canonical()), tomb)
        self.assertEqual(
            await client.hide_display(work_id=row.event.work_id, attempt_id=row.event.attempt_id),
            tomb,
        )
        self.assertEqual(
            await client.display(work_id=row.event.work_id, attempt_id=row.event.attempt_id), tomb
        )
        after = await client.inspect(work_id=row.event.work_id, attempt_id=row.event.attempt_id)
        self.assertEqual(after.projection.canonical(), original.projection.canonical())
        self.assertEqual(after.latest.canonical(), original.latest.canonical())
        await client.close()
        await owner.asyncTearDown()
