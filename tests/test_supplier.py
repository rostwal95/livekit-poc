"""The independent supplier persists inquiry identity without mutating bookings."""

import dataclasses
import json
import logging
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from continuity_lab.models import BookingChange
from continuity_lab.supplier import (
    FakeSupplier,
    SupplierRejected,
    SupplierReplayConflict,
    SupplierUnavailable,
    initialize_supplier,
)


class SupplierTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.database = self.root / "supplier.sqlite3"
        self.scope = "traveller-a"
        self.request = BookingChange("DEMO-BK-001", date(2030, 12, 10), confirmed=True)
        initialize_supplier(self.database, scope_id=self.scope)
        self.supplier = FakeSupplier(self.database)
        self.original = self.supplier.booking(scope_id=self.scope, booking_reference="DEMO-BK-001")

    def inquire(self, **overrides):
        arguments = {"scope_id": self.scope, "effect_id": "effect-a", "request": self.request}
        arguments.update(overrides)
        return self.supplier.inquire(**arguments)

    def test_declared_read_only_capabilities_and_ordinary_replay(self):
        self.assertTrue(self.supplier.capabilities.idempotent)
        self.assertTrue(self.supplier.capabilities.lookup)
        self.assertTrue(self.supplier.capabilities.read_only)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.supplier.capabilities.read_only = False
        self.assertIsNone(
            self.supplier.lookup(scope_id=self.scope, effect_id="effect-a", request=self.request)
        )
        first = self.inquire()
        self.assertTrue(first.created)
        self.assertTrue(first.result.available)
        self.assertEqual(first.result.booking_reference, self.request.booking_reference)
        self.assertEqual(first.result.new_check_in, self.request.new_check_in)
        reopened = FakeSupplier(self.database)
        observed = reopened.lookup(scope_id=self.scope, effect_id="effect-a", request=self.request)
        self.assertFalse(observed.created)
        self.assertEqual(observed.result, first.result)
        self.assertEqual(observed.effect_id, first.effect_id)
        self.assertFalse(self.inquire().created)
        self.assertEqual(reopened.count_inquiries(scope_id=self.scope), 1)
        self.assertEqual(
            reopened.booking(scope_id=self.scope, booking_reference="DEMO-BK-001"), self.original
        )

    def test_fixed_unavailable_date_is_an_observed_result_not_a_mutation(self):
        request = BookingChange("DEMO-BK-001", date(2030, 12, 25), confirmed=True)
        result = self.inquire(request=request)
        self.assertFalse(result.result.available)
        self.assertEqual(self.supplier.count_inquiries(scope_id=self.scope), 1)
        self.assertEqual(
            self.supplier.booking(scope_id=self.scope, booking_reference="DEMO-BK-001"),
            self.original,
        )

    def test_concurrent_identical_requests_create_one_persisted_inquiry(self):
        def inquire(_):
            return FakeSupplier(self.database).inquire(
                scope_id=self.scope, effect_id="effect-a", request=self.request
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            observations = list(pool.map(inquire, range(16)))
        self.assertEqual(sum(observed.created for observed in observations), 1)
        self.assertEqual({observed.effect_id for observed in observations}, {"effect-a"})
        self.assertEqual(len({observed.result for observed in observations}), 1)
        self.assertEqual(self.supplier.count_inquiries(scope_id=self.scope), 1)
        self.assertEqual(
            self.supplier.booking(scope_id=self.scope, booking_reference="DEMO-BK-001"),
            self.original,
        )

    def test_process_exit_without_response_preserves_original_effect_for_lookup(self):
        script = """
import os, sys
from datetime import date
from continuity_lab.models import BookingChange
from continuity_lab.supplier import FakeSupplier
FakeSupplier(sys.argv[1]).inquire(scope_id='traveller-a',effect_id='effect-a',request=BookingChange('DEMO-BK-001',date(2030,12,10),confirmed=True))
os._exit(73)
"""
        result = subprocess.run(
            [sys.executable, "-c", script, str(self.database)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertEqual(result.stdout, "")
        recovered = FakeSupplier(self.database).lookup(
            scope_id=self.scope, effect_id="effect-a", request=self.request
        )
        self.assertIsNotNone(recovered)
        self.assertFalse(recovered.created)
        self.assertEqual(recovered.effect_id, "effect-a")
        self.assertFalse(self.inquire().created)
        self.assertEqual(self.supplier.count_inquiries(scope_id=self.scope), 1)
        self.assertEqual(
            self.supplier.booking(scope_id=self.scope, booking_reference="DEMO-BK-001"),
            self.original,
        )

    def test_changed_payload_conflicts_for_inquiry_and_lookup_without_overwrite(self):
        original = self.inquire()
        changed = BookingChange("DEMO-BK-001", date(2030, 12, 11), confirmed=True)
        for operation in (self.supplier.inquire, self.supplier.lookup):
            with (
                self.subTest(operation=operation.__name__),
                self.assertRaises(SupplierReplayConflict),
            ):
                operation(scope_id=self.scope, effect_id="effect-a", request=changed)
        self.assertEqual(self.inquire().result, original.result)
        self.assertEqual(self.supplier.count_inquiries(scope_id=self.scope), 1)

    def test_effect_identity_is_bound_to_scope_and_wrong_scope_lookup_discloses_nothing(self):
        first = self.inquire()
        initialize_supplier(self.database, scope_id="traveller-b")
        self.assertIsNone(
            self.supplier.lookup(scope_id="traveller-b", effect_id="effect-a", request=self.request)
        )
        with self.assertRaises(SupplierReplayConflict):
            self.inquire(scope_id="traveller-b")
        second = self.inquire(scope_id="traveller-b", effect_id="effect-b")
        self.assertTrue(second.created)
        self.assertNotEqual(first.effect_id, second.effect_id)
        self.assertEqual(self.supplier.count_inquiries(scope_id="traveller-b"), 1)

    def test_unknown_booking_is_definitively_rejected_without_accepted_inquiry(self):
        unknown = BookingChange("UNKNOWN-BOOKING", date(2030, 12, 10), confirmed=True)
        with self.assertRaises(SupplierRejected) as failure:
            self.inquire(request=unknown)
        self.assertEqual(failure.exception.code, "inquiry_rejected")
        self.assertIsNone(
            self.supplier.lookup(scope_id=self.scope, effect_id="effect-a", request=unknown)
        )
        with self.assertRaises(SupplierRejected):
            self.supplier.booking(scope_id="traveller-b", booking_reference="DEMO-BK-001")
        self.assertEqual(self.supplier.count_inquiries(scope_id=self.scope), 0)

    def test_seed_replay_is_idempotent_and_changed_seed_never_resets_state(self):
        self.inquire()
        initialize_supplier(self.database, scope_id=self.scope)
        with self.assertRaises(SupplierReplayConflict):
            initialize_supplier(self.database, scope_id=self.scope, check_in=date(2030, 12, 2))
        self.assertEqual(
            self.supplier.booking(scope_id=self.scope, booking_reference="DEMO-BK-001"),
            self.original,
        )
        self.assertEqual(self.supplier.count_inquiries(scope_id=self.scope), 1)
        self.assertEqual(self.database.stat().st_mode & 0o777, 0o600)

    def test_invalid_identity_and_untrusted_request_types_cannot_create_inquiry(self):
        for field in ("scope_id", "effect_id"):
            for invalid in ("", " ", " leading", "a" * 129, True, 3, None):
                with (
                    self.subTest(field=field, invalid=invalid),
                    self.assertRaises(SupplierRejected),
                ):
                    self.inquire(**{field: invalid})
        for invalid in (None, {"confirmed": True}, SimpleNamespace(confirmed=True)):
            with self.subTest(invalid=invalid), self.assertRaises(SupplierRejected):
                self.inquire(request=invalid)
        for field, value in (
            ("confirmed", False),
            ("booking_reference", "demo-bk-001"),
            ("new_check_in", datetime(2030, 12, 10)),
        ):
            malformed = BookingChange("DEMO-BK-001", date(2030, 12, 10), confirmed=True)
            object.__setattr__(malformed, field, value)
            with self.subTest(field=field), self.assertRaises(SupplierRejected):
                self.inquire(request=malformed)
        self.assertEqual(self.supplier.count_inquiries(scope_id=self.scope), 0)

    def test_noncanonical_seed_and_unsupported_date_are_rejected_before_creation(self):
        for value in (" demo-bk-001 ", "demo-bk-001", True, None):
            target = self.root / "not-created.sqlite3"
            with self.subTest(value=value), self.assertRaises(SupplierRejected):
                initialize_supplier(target, scope_id=self.scope, booking_reference=value)
            self.assertFalse(target.exists())
        with self.assertRaises(SupplierRejected):
            initialize_supplier(
                self.root / "bad-date.sqlite3", scope_id=self.scope, check_in=datetime(2030, 12, 1)
            )

    def test_missing_or_symlink_database_is_not_created_or_served(self):
        missing = self.root / "missing.sqlite3"
        with self.assertRaises(SupplierUnavailable):
            FakeSupplier(missing)
        self.assertFalse(missing.exists())
        link = self.root / "link.sqlite3"
        link.symlink_to(self.database)
        for operation in (
            lambda: FakeSupplier(link),
            lambda: initialize_supplier(link, scope_id=self.scope),
        ):
            with self.assertRaises(SupplierUnavailable):
                operation()

    def test_unknown_schema_version_or_objects_fail_closed_without_reset(self):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("PRAGMA user_version=99")
        for operation in (
            lambda: FakeSupplier(self.database),
            lambda: initialize_supplier(self.database, scope_id=self.scope),
        ):
            with self.assertRaises(SupplierUnavailable):
                operation()
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 99)
            self.assertEqual(connection.execute("SELECT count(*) FROM bookings").fetchone()[0], 1)
            connection.execute("PRAGMA user_version=1")
            connection.execute("CREATE TABLE sqliteXforeign (data TEXT)")
        with self.assertRaises(SupplierUnavailable):
            FakeSupplier(self.database)

    def test_persisted_json_and_booking_integrity_are_verified_at_startup(self):
        self.inquire()
        with closing(sqlite3.connect(self.database)) as connection, connection:
            original = connection.execute("SELECT result_json FROM inquiries").fetchone()[0]
            connection.execute("UPDATE inquiries SET result_json='SECRET_SENTINEL malformed'")
        with self.assertRaises(SupplierUnavailable) as failure:
            FakeSupplier(self.database)
        self.assertNotIn("SECRET_SENTINEL", str(failure.exception))
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("UPDATE inquiries SET result_json=?", (original,))
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute("UPDATE bookings SET revision=-1")
        with self.assertRaises(SupplierUnavailable):
            FakeSupplier(self.database)

    def test_actual_runtime_operations_do_not_write_booking_or_create_schema(self):
        original_connect = sqlite3.connect
        forbidden_actions = []

        def connect(*args, **kwargs):
            connection = original_connect(*args, **kwargs)

            def authorize(action, name, _column, _database, _trigger):
                if action in {
                    sqlite3.SQLITE_CREATE_TABLE,
                    sqlite3.SQLITE_DROP_TABLE,
                    sqlite3.SQLITE_ALTER_TABLE,
                } or (
                    action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}
                    and name == "bookings"
                ):
                    forbidden_actions.append((action, name))
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            connection.set_authorizer(authorize)
            return connection

        with patch("continuity_lab.supplier.sqlite3.connect", side_effect=connect):
            runtime = FakeSupplier(self.database)
            self.assertTrue(
                runtime.inquire(
                    scope_id=self.scope, effect_id="effect-a", request=self.request
                ).created
            )
            self.assertIsNotNone(
                runtime.lookup(scope_id=self.scope, effect_id="effect-a", request=self.request)
            )
            self.assertEqual(
                runtime.booking(scope_id=self.scope, booking_reference="DEMO-BK-001"), self.original
            )
        self.assertEqual(forbidden_actions, [])

    def test_storage_failure_is_typed_and_logs_never_render_private_exception(self):
        class PrivateSQLiteFailure(sqlite3.OperationalError):
            def __str__(self):
                raise AssertionError("Do not render private SQLite errors")

            def __repr__(self):
                raise AssertionError("Do not represent private SQLite errors")

        private = PrivateSQLiteFailure("SECRET_SENTINEL")
        with (
            patch("continuity_lab.supplier.sqlite3.connect", side_effect=private),
            self.assertLogs("continuity_lab.supplier", level=logging.INFO) as captured,
            self.assertRaises(SupplierUnavailable) as failure,
        ):
            self.inquire()
        self.assertIs(failure.exception.__cause__, private)
        self.assertEqual(failure.exception.code, "dependency_unavailable")
        self.assertNotIn("SECRET_SENTINEL", str(failure.exception))
        self.assertNotIn("SECRET_SENTINEL", "\n".join(captured.output))
        self.assertEqual(captured.records[0].event, "supplier_unavailable")
        self.assertEqual(captured.records[0].code, "dependency_unavailable")
        self.assertEqual(captured.records[0].levelname, "ERROR")

    def test_inquiry_events_are_fixed_and_replay_conflicts_are_warnings(self):
        with self.assertLogs("continuity_lab.supplier", level=logging.INFO) as captured:
            self.inquire()
            self.inquire()
            with self.assertRaises(SupplierReplayConflict):
                self.inquire(
                    request=BookingChange("DEMO-BK-001", date(2030, 12, 11), confirmed=True)
                )
        self.assertEqual(
            [(record.event, record.code, record.levelname) for record in captured.records],
            [
                ("supplier_inquiry_created", "ok", "INFO"),
                ("supplier_inquiry_replayed", "ok", "INFO"),
                ("supplier_replay_conflict", "inquiry_conflict", "WARNING"),
            ],
        )
        for text in captured.output:
            self.assertNotIn("DEMO-BK-001", text)
            self.assertNotIn("traveller-a", text)
            self.assertNotIn("effect-a", text)

    def test_connections_release_locks_after_success_replay_and_rejection(self):
        self.inquire()
        self.inquire()
        with self.assertRaises(SupplierRejected):
            self.inquire(
                effect_id="other",
                request=BookingChange("UNKNOWN", date(2030, 12, 10), confirmed=True),
            )
        with closing(sqlite3.connect(self.database, timeout=0.05)) as writer:
            writer.execute("BEGIN EXCLUSIVE")
            writer.rollback()

    def test_cli_reports_safe_status_without_reflecting_input_or_path(self):
        target = self.root / "SECRET_SENTINEL.sqlite3"
        command = [
            sys.executable,
            "-m",
            "continuity_lab.supplier",
            "--db",
            str(target),
            "init",
            "--scope",
            "traveller-a",
        ]
        success = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(success.returncode, 0, success.stderr)
        self.assertEqual(json.loads(success.stdout)["status"], "initialized")
        records = [json.loads(line) for line in success.stderr.splitlines()]
        self.assertIn("supplier_initialized", [record["event"] for record in records])
        self.assertTrue(all(record["service"] == "continuity-execution" for record in records))
        self.assertNotIn("SECRET_SENTINEL", success.stdout + success.stderr)
        invalid = subprocess.run(
            command + ["--check-in", "SECRET_SENTINEL"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(invalid.returncode, 2)
        self.assertEqual(json.loads(invalid.stdout)["code"], "invalid_input")
        self.assertNotIn("SECRET_SENTINEL", invalid.stdout + invalid.stderr)

    def test_import_has_no_database_or_logging_configuration_side_effect(self):
        script = """
import logging
from unittest.mock import patch
root=logging.getLogger()
before=(root.level,tuple(root.handlers))
with patch('sqlite3.connect',side_effect=AssertionError('Import must not open databases')):
    from continuity_lab import supplier
assert (root.level,tuple(root.handlers))==before
assert not logging.getLogger(supplier.__name__).handlers
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout + result.stderr, "")

    def test_cli_contains_unexpected_defect_without_rendering_its_private_exception(self):
        script = """
from unittest.mock import patch
from continuity_lab.supplier import main
class PrivateFailure(RuntimeError):
    def __str__(self): raise AssertionError('Do not render private failures')
    def __repr__(self): raise AssertionError('Do not represent private failures')
with patch('continuity_lab.supplier.initialize_supplier',side_effect=PrivateFailure('SECRET_SENTINEL')):
    raise SystemExit(main(['--db','unused.sqlite3','init','--scope','traveller-a']))
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["code"], "unexpected_error")
        self.assertEqual(json.loads(result.stderr)["severity"], "error")
        self.assertNotIn("SECRET_SENTINEL", result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
