"""Actual work/case shared-transaction guards; explicit local PostgreSQL only."""

import asyncio
import importlib.util
import logging
import os
import tempfile
import threading
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from psycopg import sql

from continuity_lab.action_api import ActionError, open_action_client
from continuity_lab.authorization import AuthenticatedActor
from continuity_lab.case_control_api import open_case_control_client
from continuity_lab.case_models import Confirmation
from continuity_lab.execution_api import open_execution_client
from continuity_lab.postgres_api import open_postgres_client
from continuity_lab.result_feed_api import open_result_feed_client
from continuity_lab.work_admin import (
    install_work_schema,
    upgrade_work_schema_v2,
    upgrade_work_schema_v3,
    upgrade_work_schema_v4,
)
from continuity_lab.work_api import (
    BearerToken,
    PostgresSettings,
    WorkDirectory,
    WorkPayload,
    WorkPrincipal,
    WorkScope,
    open_work_client,
)

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "guard_case_fixture", ROOT / "local-setup/scripts/p3_case_fixture.py"
)
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)


class GuardedActionPostgresCases(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if os.environ.get("P1_RUN_POSTGRES_TESTS") != "1":
            raise RuntimeError("Explicit actual PostgreSQL setup required")
        self.work_runtime = replace(PostgresSettings.from_env(), schema="p1_work_" + uuid4().hex)
        self.work_owner = replace(
            PostgresSettings.from_env("P1_MIGRATION_"), schema=self.work_runtime.schema
        )
        self.case_runtime = replace(self.work_runtime, schema="p3_completion_" + uuid4().hex)
        self.case_owner = replace(self.work_owner, schema=self.case_runtime.schema)
        self.temp = tempfile.TemporaryDirectory(prefix="p1-action-")
        self.folder = Path(self.temp.name).resolve()
        self.supplier = self.folder / "supplier.sqlite3"
        self.clients = []
        self.installed_case = False
        self.token = BearerToken("w" * 43)
        self.case_token = BearerToken("c" * 43)
        self.scope = WorkScope("tenant_guard", "account_guard")
        self.directory = WorkDirectory({self.token: WorkPrincipal("guard_user", self.scope)})
        self.addAsyncCleanup(self.cleanup)
        await asyncio.to_thread(install_work_schema, self.work_owner)
        await asyncio.to_thread(upgrade_work_schema_v2, self.work_owner)
        await asyncio.to_thread(upgrade_work_schema_v3, self.work_owner)
        await asyncio.to_thread(fixture.install, self.case_owner, self.supplier)
        self.installed_case = True
        self.work = self.own(
            open_work_client(settings=self.work_runtime, directory=self.directory, token=self.token)
        )
        self.execution = self.own(
            open_execution_client(
                settings=self.work_runtime, directory=self.directory, token=self.token
            )
        )
        self.book = self.own(
            open_postgres_client(
                actor=fixture.ACTOR,
                token=self.case_token,
                settings=self.case_runtime,
                quote_database=self.supplier,
            )
        )
        self.control = self.own(
            open_case_control_client(
                actor=fixture.ACTOR, token=self.case_token, settings=self.case_runtime
            )
        )
        self.actions = self.client()

    def own(self, client):
        self.clients.append(client)
        return client

    def client(self, hook=None, actor=None):
        return self.own(
            open_action_client(
                settings=self.work_runtime,
                directory=self.directory,
                token=self.token,
                case_settings=self.case_runtime,
                case_actor=fixture.ACTOR if actor is None else actor,
                case_token=self.case_token,
                harness_failpoint=hook,
            )
        )

    async def cleanup(self):
        for client in reversed(self.clients):
            await client.close()
        if self.installed_case:
            await asyncio.to_thread(fixture.cleanup, self.case_owner)
        with closing(self.work_owner.connect(application_name="continuity-test")) as connection:
            row = connection.execute(
                "SELECT obj_description(oid,'pg_namespace') AS marker,pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname=%s",
                [self.work_owner.schema],
            ).fetchone()
            if row is not None:
                self.assertEqual(row["owner"], "continuity_migrator")
                self.assertIn(
                    row["marker"],
                    {
                        "continuity-readonly-work-v1",
                        "continuity-readonly-work-v2",
                        "continuity-readonly-work-v3",
                        "continuity-readonly-work-v4",
                    },
                )
                connection.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.work_owner.schema))
                )
        self.temp.cleanup()

    async def known_work(self, key="work", deadline_ms=None):
        if deadline_ms is None:
            with closing(self.work_runtime.connect()) as connection:
                deadline_ms = connection.execute(
                    "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint+60000 AS value"
                ).fetchone()["value"]
        accepted = await self.work.submit(
            idempotency_key=key, payload=WorkPayload("booking.evaluate_policy", b"{}", deadline_ms)
        )
        issued = await self.execution.issue(
            work_id=accepted.record.work_id, owner_id=str(uuid4()), command_id="issue-" + key
        )
        result = await self.execution.complete(
            attempt=issued.attempt, body=b"known read-only result"
        )
        return accepted.record, issued.attempt, result

    async def prepare(self):
        accepted = await self.book.submit(idempotency_key="booking", request=fixture.REQUEST)
        await asyncio.to_thread(fixture.inquire, self.case_runtime, self.supplier, accepted.task_id)
        current = await self.control.case(task_id=accepted.task_id)
        receipt = await self.book.prepare_quote(
            task_id=current.task_id, expected_revision=current.revision, command_id="quote-original"
        )
        quote = receipt.quote
        work, grant, result = await self.known_work()
        return current, quote, work, grant, result

    async def authorize(self, values, client=None, command="approve", **changes):
        _, quote, work, grant, result = values
        arguments = {
            "work_id": work.work_id,
            "attempt_id": grant.attempt_id,
            "result_sha256": result.sha256,
            "expected_revision": quote.revision,
            "confirmation": Confirmation(quote, True),
            "command_id": command,
        }
        arguments.update(changes)
        return await (self.actions if client is None else client).authorize(**arguments)

    async def absent(self, values):
        case, _, work, _, _ = values
        self.assertIsNone(await self.actions.action(work_id=work.work_id))
        self.assertIsNone((await self.control.case(task_id=case.task_id)).intent)

    async def test_current_guard_commit_replay_and_independent_single_fake_effect(self):
        await self.assert_guard_and_effect()

    async def test_work_v4_guarded_action_startup_result_feed_and_single_fake_effect(self):
        await asyncio.to_thread(upgrade_work_schema_v4, self.work_owner)
        self.actions = self.client()
        await self.assert_guard_and_effect()
        feed = self.own(
            open_result_feed_client(
                settings=self.work_runtime, directory=self.directory, token=self.token
            )
        )
        page = await feed.read()
        self.assertEqual(len(page.events), 1)
        self.assertEqual(page.events[0].origin, "live")
        self.assertEqual(page.events[0].disposition, "eligible_at_commit")

    async def assert_guard_and_effect(self):
        values = await self.prepare()
        receipt = await self.authorize(values)
        self.assertEqual(await self.authorize(values), receipt)
        self.assertEqual(await self.actions.find_action(command_id="approve"), receipt)
        self.assertEqual(
            receipt.intent, (await self.control.case(task_id=receipt.case_task_id)).intent
        )
        result = await asyncio.to_thread(
            fixture.mutate, self.case_runtime, self.supplier, receipt.case_task_id
        )
        self.assertEqual(result["effect_id"], receipt.intent.effect_id)
        truth = await asyncio.to_thread(fixture.supplier_truth, self.supplier)
        self.assertEqual(truth["applied_calls"], 1)
        self.assertEqual(len(truth["mutation_receipts"]), 1)
        self.assertEqual(await self.authorize(values), receipt)
        with self.assertRaises(ActionError) as changed:
            await self.authorize(values, command="different-command")
        self.assertEqual(changed.exception.code, "identity_conflict")

    async def test_stale_case_confirmation_blocks_then_current_independent_result_progresses(self):
        values = await self.prepare()
        case, _quote, *_ = values
        revised = await self.control.revise(
            task_id=case.task_id, expected_revision=case.revision, request=fixture.ALTERNATE
        )
        with self.assertRaises(ActionError) as stale:
            await self.authorize(values)
        self.assertEqual(stale.exception.code, "stale_revision")
        await self.absent(values)
        current = await self.control.revise(
            task_id=case.task_id, expected_revision=revised.revision, request=fixture.REQUEST
        )
        newquote = (
            await self.book.prepare_quote(
                task_id=case.task_id, expected_revision=current.revision, command_id="quote-current"
            )
        ).quote
        newwork, newgrant, newresult = await self.known_work("current")
        receipt = await self.authorize(
            (current, newquote, newwork, newgrant, newresult), command="approve-current"
        )
        self.assertEqual(receipt.expected_revision, current.revision)

    async def test_cancel_before_guard_rejects_without_intent(self):
        values = await self.prepare()
        await self.work.cancel(work_id=values[2].work_id, command_id="cancel")
        with self.assertRaises(ActionError) as rejected:
            await self.authorize(values)
        self.assertEqual(rejected.exception.code, "expired")
        await self.absent(values)

    async def test_authority_clock_after_deadline_blocks_new_intent(self):
        values = await self.prepare()
        with closing(self.work_runtime.connect()) as connection:
            deadline = connection.execute(
                "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint+1000 AS value"
            ).fetchone()["value"]
        work, grant, result = await self.known_work("short", deadline)
        current = (*values[:2], work, grant, result)
        for _ in range(100):
            with closing(self.work_runtime.connect()) as connection:
                expired = connection.execute(
                    "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint>=%s AS expired",
                    [deadline],
                ).fetchone()["expired"]
            if expired:
                break
            await asyncio.sleep(0.02)
        self.assertTrue(expired)
        with self.assertRaises(ActionError) as rejected:
            await self.authorize(current)
        self.assertEqual(rejected.exception.code, "expired")
        await self.absent(current)

    async def test_forged_result_or_unissued_attempt_does_not_authorize(self):
        values = await self.prepare()
        for changed in ({"result_sha256": "0" * 64}, {"attempt_id": str(uuid4())}):
            with self.assertRaises(ActionError) as rejected:
                await self.authorize(values, **changed)
            self.assertEqual(rejected.exception.code, "invalid_result")
        await self.absent(values)

    async def test_concurrent_equal_command_has_one_immutable_receipt(self):
        values = await self.prepare()
        other = self.client()
        first, second = await asyncio.gather(self.authorize(values), self.authorize(values, other))
        self.assertEqual(first, second)

    async def test_before_commit_rollback_preserves_both_owners_then_progresses(self):
        values = await self.prepare()

        def hook(stage):
            if stage == "authorize.before_commit":
                raise OSError("PRIVATE_BEFORE_COMMIT")

        with self.assertRaises(ActionError) as failed:
            await self.authorize(values, self.client(hook))
        self.assertEqual(failed.exception.code, "storage_unavailable")
        await self.absent(values)
        self.assertEqual((await self.authorize(values)).work_id, values[2].work_id)

    async def test_after_commit_ack_unknown_reconciles_original_intent(self):
        values = await self.prepare()

        def hook(stage):
            if stage == "authorize.after_commit":
                raise OSError("PRIVATE_AFTER_COMMIT")

        with self.assertRaises(ActionError) as failed:
            await self.authorize(values, self.client(hook))
        self.assertEqual(failed.exception.code, "acknowledgement_unknown")
        original = await self.actions.find_action(command_id="approve")
        self.assertIsNotNone(original)
        self.assertEqual(await self.authorize(values), original)

    async def test_cancel_wins_before_shared_locks_then_other_work_progresses(self):
        values = await self.prepare()
        entered = threading.Event()
        release = threading.Event()

        def hook(stage):
            if stage == "authorize.before_locks":
                entered.set()
                if not release.wait(3):
                    raise AssertionError("release_timeout")

        pending = asyncio.create_task(self.authorize(values, self.client(hook)))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            await self.work.cancel(work_id=values[2].work_id, command_id="cancel-before-lock")
        finally:
            release.set()
        with self.assertRaises(ActionError) as denied:
            await pending
        self.assertEqual(denied.exception.code, "expired")
        await self.absent(values)
        work, grant, result = await self.known_work("after-cancel")
        self.assertEqual(
            (
                await self.authorize((*values[:2], work, grant, result), command="new-current")
            ).work_id,
            work.work_id,
        )

    async def test_commit_wins_under_both_locks_later_cancel_preserves_receipt(self):
        values = await self.prepare()
        entered = threading.Event()
        release = threading.Event()

        def hook(stage):
            if stage == "authorize.after_locks":
                entered.set()
                if not release.wait(3):
                    raise AssertionError("release_timeout")

        pending = asyncio.create_task(self.authorize(values, self.client(hook)))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            cancel = asyncio.create_task(
                self.work.cancel(work_id=values[2].work_id, command_id="cancel-after-lock")
            )
            await asyncio.sleep(0.03)
            self.assertFalse(cancel.done())
        finally:
            release.set()
        receipt = await pending
        await cancel
        self.assertTrue((await self.work.get(work_id=receipt.work_id)).cancel_requested)
        self.assertEqual(await self.authorize(values), receipt)

    async def test_case_actor_rebinding_cannot_read_or_replace_receipt(self):
        values = await self.prepare()
        await self.authorize(values)
        foreign = self.client(actor=AuthenticatedActor("foreign_actor", fixture.ACTOR.scope_id))
        self.assertIsNone(await foreign.find_action(command_id="approve"))
        self.assertIsNone(await foreign.action(work_id=values[2].work_id))
        with self.assertRaises(ActionError) as rejected:
            await self.authorize(values, foreign)
        self.assertEqual(rejected.exception.code, "identity_conflict")

    async def test_logging_failure_preserves_committed_receipt_and_progress(self):
        values = await self.prepare()

        class Failing(logging.Handler):
            def emit(self, record):
                raise OSError("PRIVATE_LOG_SINK")

        logger = logging.getLogger("continuity_lab.action_store")
        old = logger.level
        handler = Failing()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            receipt = await self.authorize(values)
            self.assertEqual(await self.authorize(values), receipt)
            self.assertEqual(await self.actions.action(work_id=receipt.work_id), receipt)
            self.assertGreaterEqual(self.actions.metrics()["telemetry_failures"], 3)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old)

    async def test_guard_rejects_counters_above_persisted_caps_even_when_counts_match(self):
        values = await self.prepare()
        await self.known_work("second")
        with closing(self.work_owner.connect(application_name="continuity-test")) as connection:
            connection.execute(
                sql.SQL("UPDATE {}.schema_metadata SET max_records=1 WHERE singleton").format(
                    sql.Identifier(self.work_owner.schema)
                )
            )
        try:
            with self.assertRaises(ActionError) as rejected:
                await self.authorize(values)
            self.assertEqual(rejected.exception.code, "schema_mismatch")
        finally:
            with closing(self.work_owner.connect(application_name="continuity-test")) as connection:
                connection.execute(
                    sql.SQL(
                        "UPDATE {}.schema_metadata SET max_records=1000 WHERE singleton"
                    ).format(sql.Identifier(self.work_owner.schema))
                )
        await self.absent(values)

    async def test_unrelated_prior_case_intent_cannot_be_retroactively_bound_to_result(self):
        values = await self.prepare()
        case, quote, work, _, _ = values
        original = await self.control.commit_confirmation(
            task_id=case.task_id,
            confirmation=Confirmation(quote, True),
            command_id="independent-controller",
        )
        with self.assertRaises(ActionError) as rejected:
            await self.authorize(values)
        self.assertEqual(rejected.exception.code, "intent_committed")
        self.assertIsNone(await self.actions.action(work_id=work.work_id))
        self.assertEqual((await self.control.case(task_id=case.task_id)).intent, original)
