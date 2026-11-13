"""Actual PostgreSQL exact-consent authority: races, replay and process loss."""

import json
import os
import subprocess
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from psycopg import sql

from continuity_lab.authorization import AuthenticatedActor, BearerToken, TokenDirectory
from continuity_lab.case_models import (
    CaseCancelled,
    CaseCapacityExceeded,
    Confirmation,
    DeadlineExpired,
    IntentAlreadyCommitted,
    InvalidConfirmation,
    QuoteExpired,
    QuoteSnapshot,
    StaleRevision,
    canonical,
)
from continuity_lab.execution_models import (
    ExecutionNotFound,
    InquiryResult,
    InvalidStoredState,
    TransitionConflict,
)
from continuity_lab.models import BookingChange, IdempotencyConflict
from continuity_lab.postgres_case import PostgresCaseAuthority
from continuity_lab.postgres_migrations import install_schema, upgrade_v2
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.postgres_unit_of_work import protected_transaction


class PostgresCaseCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("P1_RUN_POSTGRES_TESTS") != "1":
            raise RuntimeError("Real PostgreSQL setup is required; this lane cannot skip")
        cls.runtime_base = PostgresSettings.from_env()
        cls.migration_base = PostgresSettings.from_env("P1_MIGRATION_")

    def setUp(self):
        self.schema = "p1_case_" + uuid4().hex
        self.runtime = replace(self.runtime_base, schema=self.schema)
        self.migration = replace(self.migration_base, schema=self.schema)
        self.addCleanup(self.drop_schema)
        install_schema(self.migration)
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL(
                    "UPDATE {} SET state='active',migration_id=%s,source_digest=%s WHERE singleton"
                ).format(sql.Identifier(self.schema, "schema_metadata")),
                (str(uuid4()), "0" * 64),
            )
        upgrade_v2(self.migration)
        self.store = PostgresExecutionStore(self.runtime)
        self.now = datetime(2030, 12, 1, tzinfo=UTC)
        self.cases = PostgresCaseAuthority(self.store, clock=lambda: self.now)
        self.actor = AuthenticatedActor("actor-a", "account-a")
        self.request = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)

    def drop_schema(self):
        if not self.schema.startswith("p1_case_") or len(self.schema) != 40:
            raise AssertionError("Only this test's owned schema may be removed")
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema))
            )

    def prepare(self, key="one", actor=None):
        actor = actor or self.actor
        record = self.store.submit(
            scope_id=actor.scope_id, idempotency_key=key, request=self.request
        ).execution
        self.cases.enroll(actor=actor, task_id=record.task_id)
        return record

    def quote(self, record, **changes):
        current = self.cases.get(actor=self.actor, task_id=record.task_id)
        value = QuoteSnapshot(
            str(uuid4()),
            record.task_id,
            current.revision,
            current.request.booking_reference,
            current.request.new_check_in,
            1250,
            "USD",
            (self.now + timedelta(minutes=10)).isoformat(),
        )
        return replace(value, **changes)

    def publish(self, record, **changes):
        quote = self.quote(record, **changes)
        self.cases.publish_quote(actor=self.actor, quote=quote)
        return quote

    def counts(self):
        with closing(self.runtime.connect()) as connection:
            return tuple(
                connection.execute(
                    sql.SQL("SELECT COUNT(*) AS n FROM {}").format(
                        sql.Identifier(self.schema, table)
                    )
                ).fetchone()["n"]
                for table in ("confirmations", "action_intents", "intent_dispatch")
            )

    def insert_control(self, record, *, state="inquiry_complete", deadline=None):
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL(
                    "INSERT INTO {} (task_id,state,policy_json,deadline,next_attempt_at,version,last_failure,error_code,updated_at) VALUES (%s,%s,%s,%s,%s,0,NULL,NULL,%s)"
                ).format(sql.Identifier(self.schema, "execution_controls")),
                (
                    record.task_id,
                    state,
                    json.dumps(
                        {"max_attempts": 3, "initial_delay_seconds": 1, "max_delay_seconds": 4},
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    (deadline or self.now + timedelta(minutes=5)).isoformat(),
                    (self.now + timedelta(seconds=5)).isoformat()
                    if state == "retry_wait"
                    else None,
                    self.now.isoformat(),
                ),
            )

    def test_enrollment_and_revision_preserve_original_request_effect_and_quote_history(self):
        record = self.prepare()
        quote = self.publish(record)
        self.assertEqual(
            self.cases.enroll(actor=self.actor, task_id=record.task_id),
            self.cases.get(actor=self.actor, task_id=record.task_id),
        )
        changed = BookingChange("DEMO-BK-001", date(2030, 12, 11), True)
        revised = self.cases.revise(
            actor=self.actor, task_id=record.task_id, expected_revision=0, request=changed
        )
        self.assertEqual((revised.revision, revised.request, revised.quote), (1, changed, None))
        self.assertEqual(
            self.store.get(scope_id=self.actor.scope_id, task_id=record.task_id), record
        )
        with self.assertRaises(StaleRevision):
            self.cases.commit_intent(
                actor=self.actor, confirmation=Confirmation(quote, True), command_id="stale"
            )
        new_quote = self.publish(record)
        result = self.cases.commit_intent(
            actor=self.actor, confirmation=Confirmation(new_quote, True), command_id="current"
        )
        self.assertEqual(result.quote.new_check_in, date(2030, 12, 11))
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_valid_exact_confirmation_commits_one_immutable_intent_effect_and_dispatch(self):
        record = self.prepare()
        quote = self.publish(record)
        confirmation = Confirmation(quote, True)
        intent = self.cases.commit_intent(
            actor=self.actor, confirmation=confirmation, command_id="confirm-one"
        )
        self.assertEqual(intent.quote, quote)
        self.assertNotEqual(intent.effect_id, record.effect_id)
        [event] = self.cases.dispatches(actor=self.actor, task_id=record.task_id)
        self.assertEqual((event.event_id, event.intent), (intent.dispatch_event_id, intent))
        self.assertEqual(self.cases.get(actor=self.actor, task_id=record.task_id).intent, intent)
        self.assertEqual(self.counts(), (1, 1, 1))
        self.now += timedelta(days=365)
        self.assertEqual(
            self.cases.commit_intent(
                actor=self.actor, confirmation=confirmation, command_id="confirm-one"
            ),
            intent,
        )
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_every_changed_quote_field_rejects_before_any_commit_then_valid_work_progresses(self):
        record = self.prepare()
        quote = self.publish(record)
        changes = (
            {"amount_minor": 1251},
            {"currency": "EUR"},
            {"booking_reference": "DEMO-BK-002"},
            {"new_check_in": date(2030, 12, 11)},
            {"quote_id": str(uuid4())},
            {"expires_at": (self.now + timedelta(minutes=11)).isoformat()},
        )
        for index, change in enumerate(changes):
            with self.subTest(fields=list(change)), self.assertRaises(InvalidConfirmation):
                self.cases.commit_intent(
                    actor=self.actor,
                    confirmation=Confirmation(replace(quote, **change), True),
                    command_id="bad-" + str(index),
                )
            self.assertEqual(self.counts(), (0, 0, 0))
        with self.assertRaises(InvalidConfirmation):
            self.cases.commit_intent(actor=self.actor, confirmation=None, command_id="missing")
        self.cases.commit_intent(
            actor=self.actor, confirmation=Confirmation(quote, True), command_id="valid"
        )
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_expiry_boundary_is_checked_after_lock_admission(self):
        record = self.prepare()
        quote = self.publish(record)
        started = threading.Event()

        def attempt():
            started.set()
            return self.cases.commit_intent(
                actor=self.actor, confirmation=Confirmation(quote, True), command_id="expired"
            )

        with ThreadPoolExecutor(max_workers=1) as pool:
            with protected_transaction(self.store):
                future = pool.submit(attempt)
                self.assertTrue(started.wait(2))
                self.now = datetime.fromisoformat(quote.expires_at)
            with self.assertRaises(QuoteExpired):
                future.result(timeout=10)
        self.assertEqual(self.counts(), (0, 0, 0))
        fresh = self.publish(record)
        self.cases.commit_intent(
            actor=self.actor, confirmation=Confirmation(fresh, True), command_id="fresh"
        )
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_changed_command_replay_conflicts_and_new_command_retains_one_logical_intent(self):
        record = self.prepare()
        quote = self.publish(record)
        confirmation = Confirmation(quote, True)
        first = self.cases.commit_intent(
            actor=self.actor, confirmation=confirmation, command_id="one"
        )
        second = self.cases.commit_intent(
            actor=self.actor, confirmation=confirmation, command_id="two"
        )
        self.assertEqual(first, second)
        with self.assertRaises(IdempotencyConflict):
            self.cases.commit_intent(
                actor=self.actor,
                confirmation=Confirmation(replace(quote, amount_minor=1251), True),
                command_id="one",
            )
        self.assertEqual(self.counts(), (2, 1, 1))

    def test_replayed_old_quote_publication_never_restores_superseded_current_quote(self):
        record = self.prepare()
        first = self.publish(record)
        second = self.publish(record, amount_minor=1500)
        self.assertEqual(self.cases.publish_quote(actor=self.actor, quote=first), first)
        self.assertEqual(self.cases.get(actor=self.actor, task_id=record.task_id).quote, second)
        with self.assertRaises(InvalidConfirmation):
            self.cases.commit_intent(
                actor=self.actor, confirmation=Confirmation(first, True), command_id="old"
            )
        self.cases.commit_intent(
            actor=self.actor, confirmation=Confirmation(second, True), command_id="new"
        )
        with self.assertRaises(IntentAlreadyCommitted):
            self.cases.revise(
                actor=self.actor, task_id=record.task_id, expected_revision=0, request=self.request
            )

    def test_scope_and_owner_are_checked_before_any_detailed_disclosure(self):
        record = self.prepare()
        quote = self.publish(record)
        for actor in (
            AuthenticatedActor("other", "account-a"),
            AuthenticatedActor("actor-a", "account-b"),
        ):
            observed = []
            for task_id in (record.task_id, "unknown"):
                with self.assertRaises(ExecutionNotFound) as caught:
                    self.cases.get(actor=actor, task_id=task_id)
                observed.append((caught.exception.code, str(caught.exception)))
            self.assertEqual(observed[0], observed[1])
            for operation in (
                lambda actor=actor: self.cases.enroll(actor=actor, task_id=record.task_id),
                lambda actor=actor: self.cases.revise(
                    actor=actor, task_id=record.task_id, expected_revision=0, request=self.request
                ),
                lambda actor=actor: self.cases.commit_intent(
                    actor=actor, confirmation=Confirmation(quote, True), command_id="attack"
                ),
                lambda actor=actor: self.cases.dispatches(actor=actor, task_id=record.task_id),
            ):
                with self.assertRaises(ExecutionNotFound):
                    operation()
        self.assertEqual(self.counts(), (0, 0, 0))
        self.cases.commit_intent(
            actor=self.actor, confirmation=Confirmation(quote, True), command_id="own"
        )
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_precommit_failure_rolls_back_all_three_receipts_and_valid_retry_progresses(self):
        record = self.prepare()
        quote = self.publish(record)

        def fail(name):
            if name == "case.after_intent_rows":
                raise RuntimeError("Controlled precommit loss")

        failing = PostgresCaseAuthority(self.store, clock=lambda: self.now, failpoint=fail)
        with self.assertRaises(RuntimeError):
            failing.commit_intent(
                actor=self.actor, confirmation=Confirmation(quote, True), command_id="one"
            )
        self.assertEqual(self.counts(), (0, 0, 0))
        self.cases.commit_intent(
            actor=self.actor, confirmation=Confirmation(quote, True), command_id="one"
        )
        self.assertEqual(self.counts(), (1, 1, 1))

    def child_commit(self, confirmation, point):
        code = """import json,os,sys\nfrom datetime import UTC,datetime\nfrom continuity_lab.authorization import AuthenticatedActor\nfrom continuity_lab.case_models import parse_confirmation\nfrom continuity_lab.postgres_case import PostgresCaseAuthority\nfrom continuity_lab.postgres_settings import PostgresSettings\nfrom continuity_lab.postgres_store import PostgresExecutionStore\ndef fail(name):\n if name==sys.argv[1]:os._exit(73)\ncases=PostgresCaseAuthority(PostgresExecutionStore(PostgresSettings.from_env()),clock=lambda:datetime(2030,12,1,tzinfo=UTC),failpoint=fail)\ncases.commit_intent(actor=AuthenticatedActor("actor-a","account-a"),confirmation=parse_confirmation(json.load(sys.stdin)),command_id="child")\n"""
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("P1_MIGRATION_")
        }
        environment["P1_POSTGRES_SCHEMA"] = self.schema
        return subprocess.run(
            [sys.executable, "-c", code, point],
            check=False,
            input=json.dumps(confirmation.payload()),
            text=True,
            capture_output=True,
            timeout=15,
            env=environment,
        )

    def test_independent_process_exit_before_commit_leaves_no_partial_intent(self):
        record = self.prepare()
        quote = self.publish(record)
        confirmation = Confirmation(quote, True)
        child = self.child_commit(confirmation, "case.after_intent_rows")
        self.assertEqual(child.returncode, 73, child.stderr)
        self.assertEqual(self.counts(), (0, 0, 0))
        self.cases.commit_intent(actor=self.actor, confirmation=confirmation, command_id="child")
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_independent_process_lost_commit_ack_replays_original_intent_and_effect(self):
        record = self.prepare()
        quote = self.publish(record)
        confirmation = Confirmation(quote, True)
        child = self.child_commit(confirmation, "case.after_intent_commit")
        self.assertEqual(child.returncode, 73, child.stderr)
        original = self.cases.get(actor=self.actor, task_id=record.task_id).intent
        self.assertIsNotNone(original)
        self.now += timedelta(days=1)
        self.assertEqual(
            self.cases.commit_intent(
                actor=self.actor, confirmation=confirmation, command_id="child"
            ),
            original,
        )
        self.assertEqual(self.counts(), (1, 1, 1))

    def race(self, winner_point, winner, loser):
        entered, release = threading.Event(), threading.Event()

        def fail(name):
            if name == winner_point:
                entered.set()
                if not release.wait(5):
                    raise AssertionError("Race barrier was not released")

        selected = PostgresCaseAuthority(self.store, clock=lambda: self.now, failpoint=fail)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(winner, selected)
            self.assertTrue(entered.wait(5))
            second = pool.submit(loser)
            release.set()
            result = first.result(timeout=10)
            return result, second.exception(timeout=10)

    def test_revision_wins_race_and_stale_confirmation_cannot_commit(self):
        record = self.prepare()
        quote = self.publish(record)
        changed = BookingChange("DEMO-BK-001", date(2030, 12, 11), True)
        result, error = self.race(
            "case.before_revision_commit",
            lambda cases: cases.revise(
                actor=self.actor, task_id=record.task_id, expected_revision=0, request=changed
            ),
            lambda: self.cases.commit_intent(
                actor=self.actor, confirmation=Confirmation(quote, True), command_id="loser"
            ),
        )
        self.assertEqual(result.revision, 1)
        self.assertIsInstance(error, StaleRevision)
        self.assertEqual(self.counts(), (0, 0, 0))
        fresh = self.publish(record)
        self.cases.commit_intent(
            actor=self.actor, confirmation=Confirmation(fresh, True), command_id="current"
        )
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_commit_wins_race_and_revision_cannot_rewrite_committed_intent(self):
        record = self.prepare()
        quote = self.publish(record)
        changed = BookingChange("DEMO-BK-001", date(2030, 12, 11), True)
        result, error = self.race(
            "case.before_intent_commit",
            lambda cases: cases.commit_intent(
                actor=self.actor, confirmation=Confirmation(quote, True), command_id="winner"
            ),
            lambda: self.cases.revise(
                actor=self.actor, task_id=record.task_id, expected_revision=0, request=changed
            ),
        )
        self.assertIsInstance(error, IntentAlreadyCommitted)
        self.assertEqual(self.cases.get(actor=self.actor, task_id=record.task_id).intent, result)
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_precommit_cancellation_flag_blocks_intent_without_false_mutation(self):
        record = self.prepare()
        quote = self.publish(record)
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL("UPDATE {} SET cancelled=TRUE WHERE task_id=%s").format(
                    sql.Identifier(self.schema, "cases")
                ),
                (record.task_id,),
            )
        with self.assertRaises(CaseCancelled):
            self.cases.commit_intent(
                actor=self.actor, confirmation=Confirmation(quote, True), command_id="cancelled"
            )
        self.assertEqual(self.counts(), (0, 0, 0))
        self.assertEqual(
            self.store.get(scope_id=self.actor.scope_id, task_id=record.task_id), record
        )
        other = self.prepare("other")
        fresh = self.publish(other)
        self.cases.commit_intent(
            actor=self.actor, confirmation=Confirmation(fresh, True), command_id="valid-other"
        )
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_retention_caps_preserve_prior_receipts_and_reject_only_new_rows(self):
        record = self.prepare()
        limited = PostgresCaseAuthority(
            self.store,
            clock=lambda: self.now,
            maximum_cases=1,
            maximum_quotes_per_case=1,
            maximum_confirmations_per_case=1,
        )
        self.assertEqual(
            limited.enroll(actor=self.actor, task_id=record.task_id).task_id, record.task_id
        )
        other = self.store.submit(
            scope_id=self.actor.scope_id, idempotency_key="other", request=self.request
        ).execution
        with self.assertRaises(CaseCapacityExceeded):
            limited.enroll(actor=self.actor, task_id=other.task_id)
        quote = self.quote(record)
        limited.publish_quote(actor=self.actor, quote=quote)
        self.assertEqual(limited.publish_quote(actor=self.actor, quote=quote), quote)
        with self.assertRaises(CaseCapacityExceeded):
            limited.publish_quote(actor=self.actor, quote=self.quote(record))
        first = limited.commit_intent(
            actor=self.actor, confirmation=Confirmation(quote, True), command_id="one"
        )
        with self.assertRaises(CaseCapacityExceeded):
            limited.commit_intent(
                actor=self.actor, confirmation=Confirmation(quote, True), command_id="two"
            )
        self.now += timedelta(days=365)
        self.assertEqual(
            limited.commit_intent(
                actor=self.actor, confirmation=Confirmation(quote, True), command_id="one"
            ),
            first,
        )
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_managed_business_deadline_cannot_be_bypassed_by_direct_confirmation(self):
        record = self.prepare()
        quote = self.publish(record)
        self.insert_control(record, deadline=self.now + timedelta(seconds=1))
        self.now += timedelta(seconds=1)
        with self.assertRaises(DeadlineExpired):
            self.cases.commit_intent(
                actor=self.actor, confirmation=Confirmation(quote, True), command_id="expired"
            )
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_managed_terminal_or_unfinished_inquiry_cannot_accept_direct_confirmation(self):
        for state in ("ready", "running", "retry_wait", "failed", "uncertain"):
            with self.subTest(state=state):
                record = self.prepare(state)
                quote = self.publish(record)
                self.insert_control(record, state=state)
                with self.assertRaises(TransitionConflict):
                    self.cases.commit_intent(
                        actor=self.actor, confirmation=Confirmation(quote, True), command_id=state
                    )
                self.assertEqual(self.counts(), (0, 0, 0))

    def test_direct_confirmation_atomically_updates_managed_state_and_pending_wait(self):
        record = self.prepare()
        quote = self.publish(record)
        self.insert_control(record, state="waiting")
        wait_id = str(uuid4())
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL(
                    "INSERT INTO {} (wait_id,task_id,quote_json,deadline,state,created_at,finished_at) VALUES (%s,%s,%s,%s,'pending',%s,NULL)"
                ).format(sql.Identifier(self.schema, "execution_waits")),
                (
                    wait_id,
                    record.task_id,
                    canonical(quote.payload()),
                    (self.now + timedelta(minutes=2)).isoformat(),
                    self.now.isoformat(),
                ),
            )
        intent = self.cases.commit_intent(
            actor=self.actor, confirmation=Confirmation(quote, True), command_id="direct"
        )
        with closing(self.runtime.connect()) as connection:
            control = connection.execute(
                sql.SQL("SELECT state,version FROM {} WHERE task_id=%s").format(
                    sql.Identifier(self.schema, "execution_controls")
                ),
                (record.task_id,),
            ).fetchone()
            wait = connection.execute(
                sql.SQL("SELECT state,finished_at FROM {} WHERE wait_id=%s").format(
                    sql.Identifier(self.schema, "execution_waits")
                ),
                (wait_id,),
            ).fetchone()
        self.assertEqual((control["state"], control["version"]), ("intent_committed", 1))
        self.assertEqual((wait["state"], wait["finished_at"]), ("consumed", intent.created_at))
        self.now += timedelta(days=1)
        self.assertEqual(
            self.cases.commit_intent(
                actor=self.actor, confirmation=Confirmation(quote, True), command_id="direct"
            ),
            intent,
        )

    def test_public_token_service_binds_scope_and_valid_confirmation_progresses(self):
        from continuity_lab.case_service import ScopedCaseService

        record = self.prepare()
        quote = self.publish(record)
        own, other = BearerToken("a" * 40), BearerToken("b" * 40)
        service = ScopedCaseService(
            TokenDirectory({own: self.actor, other: AuthenticatedActor("actor-b", "account-b")}),
            self.cases,
            object(),
        )
        with self.assertRaises(ExecutionNotFound):
            service.get(token=other, task_id=record.task_id)
        with self.assertRaises(ExecutionNotFound):
            service.confirm(
                token=other, confirmation=Confirmation(quote, True), command_id="attack"
            )
        with self.assertRaises(TypeError):
            service.get(token=own, task_id=record.task_id, scope_id="account-b")
        intent = service.confirm(
            token=own, confirmation=Confirmation(quote, True), command_id="own"
        )
        self.assertEqual(service.get(token=own, task_id=record.task_id).intent, intent)
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_current_quote_cross_case_corruption_fails_closed_and_repair_restores_progress(self):
        record = self.prepare()
        original = self.publish(record)
        other = self.prepare("other")
        other_quote = self.publish(other)
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL("UPDATE {} SET current_quote_id=%s WHERE task_id=%s").format(
                    sql.Identifier(self.schema, "cases")
                ),
                (other_quote.quote_id, record.task_id),
            )
        with self.assertRaises(InvalidStoredState):
            self.cases.get(actor=self.actor, task_id=record.task_id)
        with self.assertRaises(InvalidStoredState):
            self.cases.commit_intent(
                actor=self.actor,
                confirmation=Confirmation(original, True),
                command_id="bad-binding",
            )
        self.assertEqual(self.counts(), (0, 0, 0))
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL("UPDATE {} SET current_quote_id=%s WHERE task_id=%s").format(
                    sql.Identifier(self.schema, "cases")
                ),
                (original.quote_id, record.task_id),
            )
        self.cases.commit_intent(
            actor=self.actor, confirmation=Confirmation(original, True), command_id="valid"
        )
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_runtime_cannot_update_or_delete_immutable_consent_effect_and_dispatch_rows(self):
        import psycopg

        record = self.prepare()
        quote = self.publish(record)
        self.cases.commit_intent(
            actor=self.actor, confirmation=Confirmation(quote, True), command_id="one"
        )
        for table in ("quotes", "confirmations", "action_intents", "intent_dispatch"):
            for statement in (
                "UPDATE {} SET payload_json='{{}}'",
                "DELETE FROM {}",
                "TRUNCATE TABLE {}",
            ):
                with (
                    self.subTest(table=table, operation=statement.split()[0]),
                    closing(self.runtime.connect()) as connection,
                    self.assertRaises(psycopg.errors.InsufficientPrivilege),
                ):
                    connection.execute(
                        sql.SQL(statement).format(sql.Identifier(self.schema, table))
                    )
        self.assertEqual(self.counts(), (1, 1, 1))
        self.assertIsNotNone(self.cases.get(actor=self.actor, task_id=record.task_id).intent)

    def test_direct_confirmation_cannot_bypass_matching_wait_deadline(self):
        record = self.prepare()
        quote = self.publish(record)
        self.insert_control(record, state="waiting")
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL(
                    "INSERT INTO {} (wait_id,task_id,quote_json,deadline,state,created_at,finished_at) VALUES (%s,%s,%s,%s,'pending',%s,NULL)"
                ).format(sql.Identifier(self.schema, "execution_waits")),
                (
                    str(uuid4()),
                    record.task_id,
                    canonical(quote.payload()),
                    (self.now + timedelta(seconds=1)).isoformat(),
                    self.now.isoformat(),
                ),
            )
        self.now += timedelta(seconds=1)
        with self.assertRaises(DeadlineExpired):
            self.cases.commit_intent(
                actor=self.actor, confirmation=Confirmation(quote, True), command_id="too-late"
            )
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_committed_read_requires_original_matching_confirmation_evidence(self):
        record = self.prepare()
        quote = self.publish(record)
        confirmation = Confirmation(quote, True)
        intent = self.cases.commit_intent(
            actor=self.actor, confirmation=confirmation, command_id="one"
        )
        changed = Confirmation(replace(quote, amount_minor=9999), True)
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL("UPDATE {} SET payload_json=%s WHERE confirmation_id=%s").format(
                    sql.Identifier(self.schema, "confirmations")
                ),
                (canonical(changed.payload()), intent.confirmation_id),
            )
        with self.assertRaises(InvalidStoredState):
            self.cases.get(actor=self.actor, task_id=record.task_id)
        with self.assertRaises(InvalidStoredState):
            self.cases.commit_intent(actor=self.actor, confirmation=confirmation, command_id="one")
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL("UPDATE {} SET payload_json=%s WHERE confirmation_id=%s").format(
                    sql.Identifier(self.schema, "confirmations")
                ),
                (canonical(confirmation.payload()), intent.confirmation_id),
            )
        self.assertEqual(self.cases.get(actor=self.actor, task_id=record.task_id).intent, intent)
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_committed_read_requires_mandatory_canonical_dispatch_evidence(self):
        from continuity_lab.case_models import IntentDispatch

        record = self.prepare()
        quote = self.publish(record)
        intent = self.cases.commit_intent(
            actor=self.actor, confirmation=Confirmation(quote, True), command_id="one"
        )
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL("DELETE FROM {} WHERE intent_id=%s").format(
                    sql.Identifier(self.schema, "intent_dispatch")
                ),
                (intent.intent_id,),
            )
        with self.assertRaises(InvalidStoredState):
            self.cases.get(actor=self.actor, task_id=record.task_id)
        with closing(self.runtime.connect()) as connection:
            connection.execute(
                sql.SQL(
                    "INSERT INTO {} (event_id,intent_id,payload_json,created_at) VALUES (%s,%s,%s,%s)"
                ).format(sql.Identifier(self.schema, "intent_dispatch")),
                (intent.dispatch_event_id, intent.intent_id, "{}", intent.created_at),
            )
        with self.assertRaises(InvalidStoredState):
            self.cases.get(actor=self.actor, task_id=record.task_id)
        event = IntentDispatch(intent.dispatch_event_id, intent, intent.created_at)
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL("UPDATE {} SET payload_json=%s WHERE intent_id=%s").format(
                    sql.Identifier(self.schema, "intent_dispatch")
                ),
                (canonical(event.payload()), intent.intent_id),
            )
        self.assertEqual(self.cases.get(actor=self.actor, task_id=record.task_id).intent, intent)
        self.assertEqual(self.cases.dispatches(actor=self.actor, task_id=record.task_id), (event,))

    def completed_wait(self):
        from continuity_lab.postgres_lifecycle import PostgresLifecycle
        from continuity_lab.retry_policy import RetryPolicy

        record = self.prepare()
        started = self.store.start_attempt(
            scope_id=self.actor.scope_id, task_id=record.task_id, expected_version=record.version
        )
        completed = self.store.finish_attempt(
            scope_id=self.actor.scope_id,
            task_id=record.task_id,
            attempt_id=started.attempt.attempt_id,
            expected_version=started.execution.version,
            result=InquiryResult(
                record.request.booking_reference, record.request.new_check_in, True
            ),
        )
        lifecycle = PostgresLifecycle(self.store, cases=self.cases, clock=lambda: self.now)
        policy = RetryPolicy(3, 1, 4)
        lifecycle.manage(
            scope_id=self.actor.scope_id,
            task_id=record.task_id,
            policy=policy,
            deadline=self.now + timedelta(minutes=5),
        )
        quote = self.publish(record)
        wait = lifecycle.arm_wait(
            actor=self.actor,
            task_id=record.task_id,
            wait_id=str(uuid4()),
            quote=quote,
            deadline=self.now + timedelta(minutes=2),
        )
        return completed, lifecycle, quote, wait

    def test_revision_expires_stale_wait_and_new_valid_signal_makes_useful_progress(self):
        completed, lifecycle, old_quote, old_wait = self.completed_wait()
        old_signal = lifecycle.signal(
            actor=self.actor, event_id="old", confirmation=Confirmation(old_quote, True)
        )
        self.cases.revise(
            actor=self.actor,
            task_id=completed.task_id,
            expected_revision=0,
            request=BookingChange("DEMO-BK-001", date(2030, 12, 11), True),
        )
        self.assertEqual(
            lifecycle.get(scope_id=self.actor.scope_id, task_id=completed.task_id).state,
            "inquiry_complete",
        )
        new_quote = self.publish(completed)
        new_wait = lifecycle.arm_wait(
            actor=self.actor,
            task_id=completed.task_id,
            wait_id=str(uuid4()),
            quote=new_quote,
            deadline=self.now + timedelta(minutes=3),
        )
        unchanged = lifecycle.advance(actor=self.actor, task_id=completed.task_id)
        self.assertIsNone(unchanged.intent)
        lifecycle.signal(
            actor=self.actor, event_id="new", confirmation=Confirmation(new_quote, True)
        )
        advanced = lifecycle.advance(actor=self.actor, task_id=completed.task_id)
        self.assertEqual(advanced.intent.quote, new_quote)
        self.assertEqual(advanced.intent.revision, 1)
        waits = {
            value.wait_id: value
            for value in lifecycle.waits(actor=self.actor, task_id=completed.task_id)
        }
        self.assertEqual(
            (waits[old_wait.wait_id].state, waits[new_wait.wait_id].state), ("expired", "consumed")
        )
        replay = lifecycle.signal(
            actor=self.actor, event_id="old", confirmation=Confirmation(old_quote, True)
        )
        self.assertEqual(replay.signal_id, old_signal.signal_id)
        self.assertIsNone(replay.consumed_wait_id)
        self.assertEqual(
            self.store.get(scope_id=self.actor.scope_id, task_id=completed.task_id), completed
        )
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_revision_cannot_renew_an_expired_business_deadline(self):
        completed, lifecycle, _, old_wait = self.completed_wait()
        original = lifecycle.get(scope_id=self.actor.scope_id, task_id=completed.task_id)
        self.now += timedelta(minutes=5)
        self.cases.revise(
            actor=self.actor,
            task_id=completed.task_id,
            expected_revision=0,
            request=BookingChange("DEMO-BK-001", date(2030, 12, 11), True),
        )
        current = lifecycle.get(scope_id=self.actor.scope_id, task_id=completed.task_id)
        self.assertEqual((current.state, current.error_code), ("failed", "deadline_expired"))
        self.assertEqual((current.deadline, current.policy), (original.deadline, original.policy))
        [wait] = lifecycle.waits(actor=self.actor, task_id=completed.task_id)
        self.assertEqual((wait.wait_id, wait.state), (old_wait.wait_id, "expired"))
        fresh = self.publish(completed)
        with self.assertRaises(DeadlineExpired):
            self.cases.commit_intent(
                actor=self.actor, confirmation=Confirmation(fresh, True), command_id="late"
            )
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_business_case_identity_is_distinct_and_stable_across_replay_revision_and_scope_guards(
        self,
    ):
        from dataclasses import FrozenInstanceError
        from uuid import UUID

        record = self.prepare()
        original = self.cases.get(actor=self.actor, task_id=record.task_id)
        self.assertNotEqual(original.case_id, record.task_id)
        self.assertEqual(str(UUID(original.case_id)), original.case_id)
        replay = self.cases.enroll(actor=self.actor, task_id=record.task_id)
        self.assertEqual(replay.case_id, original.case_id)
        revised = self.cases.revise(
            actor=self.actor,
            task_id=record.task_id,
            expected_revision=0,
            request=BookingChange("DEMO-BK-001", date(2030, 12, 11), True),
        )
        self.assertEqual((revised.case_id, revised.task_id), (original.case_id, record.task_id))
        self.assertEqual(
            self.store.get(scope_id=self.actor.scope_id, task_id=record.task_id), record
        )
        with self.assertRaises(FrozenInstanceError):
            revised.case_id = str(uuid4())
        for actor in (
            AuthenticatedActor("other", "account-a"),
            AuthenticatedActor("actor-a", "account-b"),
        ):
            with self.assertRaises(ExecutionNotFound):
                self.cases.get(actor=actor, task_id=record.task_id)
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL("UPDATE {} SET case_id=%s WHERE task_id=%s").format(
                    sql.Identifier(self.schema, "cases")
                ),
                ("malformed", record.task_id),
            )
        with self.assertRaises(InvalidStoredState):
            self.cases.get(actor=self.actor, task_id=record.task_id)
        import psycopg

        with (
            closing(self.migration.connect(application_name="continuity-migrate")) as connection,
            self.assertRaises(psycopg.errors.CheckViolation),
        ):
            connection.execute(
                sql.SQL("UPDATE {} SET case_id=%s WHERE task_id=%s").format(
                    sql.Identifier(self.schema, "cases")
                ),
                (record.task_id, record.task_id),
            )
        with self.assertRaises(ValueError):
            replace(revised, case_id=revised.task_id)
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL("UPDATE {} SET case_id=%s WHERE task_id=%s").format(
                    sql.Identifier(self.schema, "cases")
                ),
                (original.case_id, record.task_id),
            )
        self.assertEqual(
            self.cases.get(actor=self.actor, task_id=record.task_id).case_id, original.case_id
        )
