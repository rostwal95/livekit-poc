"""Explicit real-PostgreSQL contract lane; missing setup is a failure, never a skip.

The fixture owner activates an empty isolated schema solely to exercise the
runtime adapter. Source cutover/verification is covered by its own lane, not
inferred from this fixture administration step.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql

import continuity_lab
from continuity_lab.authorization import (
    AuthenticatedActor,
    BearerToken,
    ScopedInquiryService,
    TokenDirectory,
)
from continuity_lab.execution import ExecutionStore
from continuity_lab.execution_models import (
    AttemptStatus,
    ExecutionCapacityExceeded,
    ExecutionNotFound,
    ExecutionStatus,
    FailureCode,
    InquiryResult,
    StorageUnavailable,
    TransitionConflict,
    UnsupportedOperation,
)
from continuity_lab.inquiry_worker import InquiryWorker
from continuity_lab.migrations import migrate
from continuity_lab.models import BookingChange, IdempotencyConflict, IntakeCapacityExceeded
from continuity_lab.postgres_migrations import install_schema
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.supplier import FakeSupplier, initialize_supplier


class PostgresStoreCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("P1_RUN_POSTGRES_TESTS") != "1":
            raise RuntimeError(
                "Real PostgreSQL lane requires explicit P1_RUN_POSTGRES_TESTS=1 and local role credentials"
            )
        cls.runtime_base = PostgresSettings.from_env()
        cls.migration_base = PostgresSettings.from_env("P1_MIGRATION_")

    def setUp(self):
        self.schema = "p1_store_" + uuid4().hex
        self.runtime = replace(self.runtime_base, schema=self.schema)
        self.migration = replace(self.migration_base, schema=self.schema)
        self.addCleanup(self.drop_schema)
        install_schema(self.migration, runtime_role="livekit_lab")
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL(
                    "UPDATE {} SET state='active',migration_id=%s,source_digest=%s WHERE singleton"
                ).format(sql.Identifier(self.schema, "schema_metadata")),
                (str(uuid4()), "0" * 64),
            )
        self.store = PostgresExecutionStore(self.runtime)
        self.request = BookingChange("DEMO-BK-001", date(2030, 12, 10), confirmed=True)

    def drop_schema(self):
        if not self.schema.startswith("p1_store_") or len(self.schema) != 41:
            raise AssertionError("Only owned isolated test schemas may be removed")
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema))
            )

    def submit(self, **overrides):
        values = {"scope_id": "account-a", "idempotency_key": "one", "request": self.request}
        values.update(overrides)
        return self.store.submit(**values)

    def result(self):
        return InquiryResult("DEMO-BK-001", date(2030, 12, 10), True)

    def test_committed_identity_replays_after_new_connection_and_lost_ack(self):
        def fail(name):
            if name == "execution.after_accept_commit":
                raise RuntimeError("SECRET_SENTINEL lost acknowledgement")

        store = PostgresExecutionStore(self.runtime, failpoint=fail)
        with self.assertRaises(RuntimeError):
            store.submit(scope_id="account-a", idempotency_key="one", request=self.request)
        [original] = self.store.list(scope_id="account-a")
        replay = self.submit()
        self.assertEqual(replay.execution, original)
        self.assertEqual((replay.created, replay.enrolled), (False, False))

    def test_concurrent_equal_requests_serialize_to_one_identity_and_effect(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.submit(), range(12)))
        self.assertEqual(sum(row.created for row in results), 1)
        self.assertEqual(sum(row.enrolled for row in results), 1)
        self.assertEqual(len({row.execution.effect_id for row in results}), 1)
        self.assertEqual(len(self.store.list(scope_id="account-a")), 1)

    def test_scoped_conflict_preserves_original_and_other_scope_is_independent(self):
        first = self.submit().execution
        with self.assertRaises(IdempotencyConflict):
            self.submit(request=BookingChange("DEMO-BK-001", date(2030, 12, 11), True))
        other = self.submit(scope_id="account-b").execution
        self.assertNotEqual(other.task_id, first.task_id)
        errors = []
        for scope, identity in (("account-b", first.task_id), ("account-a", "unknown")):
            with self.assertRaises(ExecutionNotFound) as caught:
                self.store.get(scope_id=scope, task_id=identity)
            errors.append((caught.exception.code, str(caught.exception)))
        self.assertEqual(errors[0], errors[1])

    def test_authenticated_scope_blocks_forged_overrides_and_cross_scope_history_or_cancel(self):
        token_a, token_b = BearerToken("a" * 32), BearerToken("b" * 32)
        service = ScopedInquiryService(
            TokenDirectory(
                {
                    token_a: AuthenticatedActor("actor-a", "account-a"),
                    token_b: AuthenticatedActor("actor-b", "account-b"),
                }
            ),
            self.store,
        )
        own = service.submit(
            token=token_a, idempotency_key="shared-key", request=self.request
        ).execution
        other = service.submit(
            token=token_b, idempotency_key="shared-key", request=self.request
        ).execution
        self.assertNotEqual(own.task_id, other.task_id)
        with self.assertRaises(TypeError):
            service.submit(
                token=token_b, idempotency_key="forged", request=self.request, scope_id="account-a"
            )
        with self.assertRaises(ValueError):
            service.submit(
                token=token_b,
                idempotency_key="forged",
                request=self.request.payload() | {"scope_id": "account-a"},
            )
        for method in (service.get, service.history, service.cancel, service.signal):
            errors = []
            for task_id in (own.task_id, "unknown"):
                with self.assertRaises(ExecutionNotFound) as caught:
                    method(token=token_b, task_id=task_id)
                errors.append((caught.exception.code, str(caught.exception)))
            self.assertEqual(errors[0], errors[1])
        self.assertEqual(service.list(token=token_b), (other,))
        self.assertEqual(service.history(token=token_a, task_id=own.task_id), ())
        self.assertEqual(self.store.get(scope_id="account-a", task_id=own.task_id), own)
        with TemporaryDirectory() as directory:
            supplier_database = Path(directory) / "supplier.sqlite3"
            initialize_supplier(supplier_database, scope_id="account-a")
            result = InquiryWorker(self.store, FakeSupplier(supplier_database)).run_one(
                scope_id="account-a", task_id=own.task_id
            )
        self.assertEqual(result.status, ExecutionStatus.SUCCEEDED)
        self.assertEqual(service.get(token=token_a, task_id=own.task_id), result)
        self.assertEqual(service.get(token=token_b, task_id=other.task_id), other)

    def test_sqlite_and_postgres_share_identical_core_snapshots_and_fixed_events(self):
        instant = datetime(2030, 12, 1, 11, 0, 0, 123, tzinfo=UTC)
        identities = [uuid4() for _ in range(4)]

        def trace(store):
            accepted = store.submit(
                scope_id="account-a", idempotency_key="same", request=self.request
            )
            replay = store.submit(
                scope_id="account-a", idempotency_key="same", request=self.request
            )
            started = store.start_attempt(
                scope_id="account-a", task_id=accepted.execution.task_id, expected_version=0
            )
            recovered = store.recover_attempt(
                scope_id="account-a", task_id=accepted.execution.task_id, expected_version=1
            )
            completed = store.finish_attempt(
                scope_id="account-a",
                task_id=accepted.execution.task_id,
                attempt_id=recovered.attempt.attempt_id,
                expected_version=2,
                result=self.result(),
            )
            return (
                accepted,
                replay,
                started,
                recovered,
                completed,
                store.attempts(scope_id="account-a", task_id=accepted.execution.task_id),
            )

        with TemporaryDirectory() as directory:
            database = Path(directory) / "sqlite-parity.sqlite3"
            migrate(database, Path(directory) / "before.sqlite3")
            sqlite = ExecutionStore(database, clock=lambda: instant)
            postgres = PostgresExecutionStore(self.runtime, clock=lambda: instant)
            with (
                patch("continuity_lab.execution.uuid4", side_effect=identities),
                self.assertLogs("continuity_lab.execution", level="INFO") as sqlite_logs,
            ):
                sqlite_trace = trace(sqlite)
            with (
                patch("continuity_lab.postgres_store.uuid4", side_effect=identities),
                self.assertLogs("continuity_lab.postgres_store", level="INFO") as postgres_logs,
            ):
                postgres_trace = trace(postgres)
        self.assertEqual(postgres_trace, sqlite_trace)
        sqlite_events = [(record.event, record.code) for record in sqlite_logs.records]
        postgres_events = [(record.event, record.code) for record in postgres_logs.records]
        self.assertEqual(postgres_events, sqlite_events)
        self.assertEqual(
            postgres_events,
            [
                ("execution_accepted", "ok"),
                ("execution_replayed", "ok"),
                ("attempt_started", "ok"),
                ("attempt_recovered", "ok"),
                ("attempt_finished", "succeeded"),
            ],
        )

    def test_precommit_failure_rolls_back_and_valid_retry_progresses(self):
        def fail(name):
            if name == "execution.before_accept_commit":
                raise RuntimeError("Controlled precommit interruption")

        with self.assertRaises(RuntimeError):
            PostgresExecutionStore(self.runtime, failpoint=fail).submit(
                scope_id="account-a", idempotency_key="one", request=self.request
            )
        self.assertEqual(self.store.list(scope_id="account-a"), ())
        self.assertTrue(self.submit().created)

    def test_current_attempt_completes_with_matching_result(self):
        row = self.submit().execution
        started = self.store.start_attempt(
            scope_id=row.scope_id, task_id=row.task_id, expected_version=0
        )
        with self.assertRaises(ValueError):
            self.store.finish_attempt(
                scope_id=row.scope_id,
                task_id=row.task_id,
                attempt_id=started.attempt.attempt_id,
                expected_version=1,
                result=InquiryResult("DEMO-BK-001", date(2030, 12, 11), True),
            )
        completed = self.store.finish_attempt(
            scope_id=row.scope_id,
            task_id=row.task_id,
            attempt_id=started.attempt.attempt_id,
            expected_version=1,
            result=self.result(),
        )
        self.assertEqual(
            (completed.status, completed.version, completed.effect_id),
            (ExecutionStatus.SUCCEEDED, 2, row.effect_id),
        )
        [attempt] = self.store.attempts(scope_id=row.scope_id, task_id=row.task_id)
        self.assertEqual(attempt.status, AttemptStatus.SUCCEEDED)
        with self.assertRaises(TransitionConflict):
            self.store.finish_attempt(
                scope_id=row.scope_id,
                task_id=row.task_id,
                attempt_id=started.attempt.attempt_id,
                expected_version=1,
                result=self.result(),
            )

    def test_recovery_preserves_effect_and_rejects_old_attempt_even_with_new_version(self):
        row = self.submit().execution
        first = self.store.start_attempt(
            scope_id=row.scope_id, task_id=row.task_id, expected_version=0
        )
        second = self.store.recover_attempt(
            scope_id=row.scope_id, task_id=row.task_id, expected_version=1
        )
        self.assertEqual(second.execution.effect_id, row.effect_id)
        self.assertEqual(second.attempt.attempt_no, 2)
        with self.assertRaises(TransitionConflict):
            self.store.finish_attempt(
                scope_id=row.scope_id,
                task_id=row.task_id,
                attempt_id=first.attempt.attempt_id,
                expected_version=2,
                result=self.result(),
            )
        completed = self.store.finish_attempt(
            scope_id=row.scope_id,
            task_id=row.task_id,
            attempt_id=second.attempt.attempt_id,
            expected_version=2,
            result=self.result(),
        )
        self.assertEqual(completed.status, ExecutionStatus.SUCCEEDED)
        self.assertEqual(
            [row.status for row in self.store.attempts(scope_id=row.scope_id, task_id=row.task_id)],
            [AttemptStatus.INTERRUPTED, AttemptStatus.SUCCEEDED],
        )

    def test_finite_attempt_limit_and_safe_failure_code_preserve_inspection(self):
        self.store = PostgresExecutionStore(self.runtime, maximum_attempts=1)
        row = self.submit().execution
        first = self.store.start_attempt(
            scope_id=row.scope_id, task_id=row.task_id, expected_version=0
        )
        with self.assertRaises(TransitionConflict):
            self.store.recover_attempt(
                scope_id=row.scope_id, task_id=row.task_id, expected_version=1
            )
        with self.assertRaises(ValueError):
            self.store.finish_attempt(
                scope_id=row.scope_id,
                task_id=row.task_id,
                attempt_id=first.attempt.attempt_id,
                expected_version=1,
                error_code="SECRET_SENTINEL",
            )
        finished = self.store.finish_attempt(
            scope_id=row.scope_id,
            task_id=row.task_id,
            attempt_id=first.attempt.attempt_id,
            expected_version=1,
            error_code=FailureCode.INQUIRY_REJECTED,
        )
        self.assertEqual(
            (finished.status, finished.error_code),
            (ExecutionStatus.FAILED, FailureCode.INQUIRY_REJECTED),
        )

    def test_pending_and_retained_capacity_leave_replay_reads_and_useful_progress(self):
        self.store = PostgresExecutionStore(self.runtime, maximum_pending=1, maximum_records=1)
        row = self.submit().execution
        with self.assertRaises(IntakeCapacityExceeded):
            self.submit(idempotency_key="another")
        first = self.store.start_attempt(
            scope_id=row.scope_id, task_id=row.task_id, expected_version=0
        )
        finished = self.store.finish_attempt(
            scope_id=row.scope_id,
            task_id=row.task_id,
            attempt_id=first.attempt.attempt_id,
            expected_version=1,
            result=self.result(),
        )
        with self.assertRaises(IntakeCapacityExceeded):
            self.submit(idempotency_key="another")
        self.assertEqual(self.submit().execution, finished)
        self.assertEqual(self.store.list(scope_id=row.scope_id), (finished,))

    def test_worker_slot_is_nonblocking_and_holds_no_database_transaction(self):
        other = PostgresExecutionStore(self.runtime)
        with self.store.worker_slot():
            with self.assertRaises(ExecutionCapacityExceeded), other.worker_slot():
                self.fail("A second cooperating worker cannot enter")
            self.assertTrue(
                other.submit(
                    scope_id="account-b", idempotency_key="other", request=self.request
                ).created
            )
        with other.worker_slot():
            pass

    def test_worker_slot_preserves_original_failure_and_releases_session(self):
        original = RuntimeError("SECRET_SENTINEL")
        with self.assertRaises(RuntimeError) as caught, self.store.worker_slot():
            raise original
        self.assertIs(caught.exception, original)
        with PostgresExecutionStore(self.runtime).worker_slot():
            pass

    def test_postgres_worker_completes_and_terminal_replay_preserves_supplier_booking(self):
        with TemporaryDirectory() as directory:
            supplier_database = Path(directory) / "supplier.sqlite3"
            initialize_supplier(supplier_database, scope_id="account-a")
            supplier = FakeSupplier(supplier_database)
            original = supplier.booking(scope_id="account-a", booking_reference="DEMO-BK-001")
            accepted = self.submit().execution
            worker = InquiryWorker(self.store, supplier)
            completed = worker.run_one(scope_id="account-a", task_id=accepted.task_id)
            self.assertEqual(completed.status, ExecutionStatus.SUCCEEDED)
            self.assertEqual(completed.effect_id, accepted.effect_id)
            self.assertTrue(completed.result.available)
            self.assertEqual(
                worker.run_one(scope_id="account-a", task_id=accepted.task_id), completed
            )
            self.assertEqual(supplier.count_inquiries(scope_id="account-a"), 1)
            self.assertEqual(
                supplier.booking(scope_id="account-a", booking_reference="DEMO-BK-001"),
                original,
            )

    def test_postgres_worker_reconciles_supplier_success_after_lost_local_acknowledgement(self):
        def fail(name):
            if name == "worker.after_supplier_success":
                raise RuntimeError("Controlled stopped worker")

        with TemporaryDirectory() as directory:
            supplier_database = Path(directory) / "supplier.sqlite3"
            initialize_supplier(supplier_database, scope_id="account-a")
            supplier = FakeSupplier(supplier_database)
            accepted = self.submit().execution
            with self.assertRaises(RuntimeError):
                InquiryWorker(self.store, supplier, failpoint=fail).run_one(
                    scope_id="account-a", task_id=accepted.task_id
                )
            self.assertEqual(
                self.store.get(scope_id="account-a", task_id=accepted.task_id).status,
                ExecutionStatus.RUNNING,
            )
            completed = InquiryWorker(PostgresExecutionStore(self.runtime), supplier).run_one(
                scope_id="account-a", task_id=accepted.task_id
            )
            self.assertEqual(completed.status, ExecutionStatus.SUCCEEDED)
            self.assertEqual(completed.effect_id, accepted.effect_id)
            self.assertEqual(supplier.count_inquiries(scope_id="account-a"), 1)
            self.assertEqual(
                [
                    row.status
                    for row in self.store.attempts(scope_id="account-a", task_id=accepted.task_id)
                ],
                [AttemptStatus.INTERRUPTED, AttemptStatus.SUCCEEDED],
            )

    def test_postgres_worker_process_death_releases_slot_and_reconciles_one_supplier_effect(self):
        with TemporaryDirectory() as directory:
            supplier_database = Path(directory) / "supplier.sqlite3"
            initialize_supplier(supplier_database, scope_id="account-a")
            supplier = FakeSupplier(supplier_database)
            booking = supplier.booking(scope_id="account-a", booking_reference="DEMO-BK-001")
            accepted = self.submit().execution
            environment = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith(("P1_POSTGRES_", "P1_MIGRATION_"))
                and key not in {"PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"}
            }
            environment.update(
                {
                    "P1_POSTGRES_HOST": self.runtime.host,
                    "P1_POSTGRES_PORT": str(self.runtime.port),
                    "P1_POSTGRES_DB": self.runtime.dbname,
                    "P1_POSTGRES_USER": self.runtime.user,
                    "P1_POSTGRES_PASSWORD": self.runtime.password,
                    "P1_POSTGRES_SCHEMA": self.runtime.schema,
                    "P1_TEST_SUPPLIER_DB": str(supplier_database),
                    "P1_TEST_TASK_ID": accepted.task_id,
                }
            )
            child = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    """
import os
from pathlib import Path
from continuity_lab.inquiry_worker import InquiryWorker
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.supplier import FakeSupplier

def stop(name):
    if name == "worker.after_supplier_success":
        os._exit(71)

worker = InquiryWorker(
    PostgresExecutionStore(PostgresSettings.from_env()),
    FakeSupplier(Path(os.environ["P1_TEST_SUPPLIER_DB"])),
    failpoint=stop,
)
worker.run_one(scope_id="account-a", task_id=os.environ["P1_TEST_TASK_ID"])
raise SystemExit(72)
""",
                ],
                cwd=Path(continuity_lab.__file__).resolve().parents[1],
                env=environment,
                capture_output=True,
                timeout=15,
                check=False,
            )
            self.assertEqual(
                child.returncode, 71, "Child must stop at the committed supplier boundary"
            )
            retained = self.store.get(scope_id="account-a", task_id=accepted.task_id)
            self.assertEqual(
                (retained.status, retained.version, retained.effect_id),
                (ExecutionStatus.RUNNING, 1, accepted.effect_id),
            )
            self.assertEqual(supplier.count_inquiries(scope_id="account-a"), 1)
            recovered = InquiryWorker(PostgresExecutionStore(self.runtime), supplier).run_one(
                scope_id="account-a", task_id=accepted.task_id
            )
            self.assertEqual(
                (recovered.status, recovered.effect_id),
                (ExecutionStatus.SUCCEEDED, accepted.effect_id),
            )
            self.assertEqual(supplier.count_inquiries(scope_id="account-a"), 1)
            self.assertEqual(
                [
                    row.status
                    for row in self.store.attempts(scope_id="account-a", task_id=accepted.task_id)
                ],
                [AttemptStatus.INTERRUPTED, AttemptStatus.SUCCEEDED],
            )
            self.assertEqual(
                supplier.booking(scope_id="account-a", booking_reference="DEMO-BK-001"), booking
            )

    def test_existing_store_fails_closed_if_metadata_becomes_staging(self):
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL("UPDATE {} SET state='staging' WHERE singleton").format(
                    sql.Identifier(self.schema, "schema_metadata")
                )
            )
        with self.assertRaises(ValueError):
            self.submit()
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            count = connection.execute(
                sql.SQL("SELECT COUNT(*) AS count FROM {}").format(
                    sql.Identifier(self.schema, "tasks")
                )
            ).fetchone()
            self.assertEqual(count["count"], 0)

    def test_migrator_cannot_be_used_as_runtime_and_runtime_cannot_administer(self):
        with self.assertRaises(StorageUnavailable):
            PostgresExecutionStore(self.migration)
        statements = (
            sql.SQL("CREATE TABLE {} (id INTEGER)").format(
                sql.Identifier(self.schema, "forbidden")
            ),
            sql.SQL("CREATE TEMP TABLE forbidden (id INTEGER)"),
            sql.SQL("UPDATE {} SET state='active'").format(
                sql.Identifier(self.schema, "schema_metadata")
            ),
            sql.SQL("DELETE FROM {}").format(sql.Identifier(self.schema, "tasks")),
        )
        with closing(self.runtime.connect()) as connection:
            for statement in statements:
                with (
                    self.subTest(statement=statement),
                    self.assertRaises(psycopg.errors.InsufficientPrivilege),
                ):
                    connection.execute(statement)
        self.assertTrue(self.submit().created)

    def test_extra_metadata_write_grant_is_rejected_before_work(self):
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL("GRANT UPDATE ON {} TO {}").format(
                    sql.Identifier(self.schema, "schema_metadata"), sql.Identifier("livekit_lab")
                )
            )
        with self.assertRaises(StorageUnavailable):
            self.submit()

    def test_unsupported_operation_and_cancel_never_change_state(self):
        with self.assertRaises(UnsupportedOperation):
            self.submit(operation="booking.apply")
        row = self.submit().execution
        with self.assertRaises(UnsupportedOperation):
            self.store.cancel(scope_id=row.scope_id, task_id=row.task_id)
        self.assertEqual(self.store.get(scope_id=row.scope_id, task_id=row.task_id), row)

    def test_real_events_are_fixed_and_exclude_request_values(self):
        with self.assertLogs("continuity_lab.postgres_store", level="INFO") as logs:
            self.submit()
            self.submit()
        self.assertEqual(
            [record.event for record in logs.records], ["execution_accepted", "execution_replayed"]
        )
        self.assertNotIn(
            "DEMO-BK-001", json.dumps([record.__dict__ for record in logs.records], default=str)
        )


if __name__ == "__main__":
    unittest.main()
