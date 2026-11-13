"""Trusted quote reads share provider authority without mutating its fixture."""

import hashlib
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

from continuity_lab.mutation_supplier import (
    MutationRejected,
    MutationSupplier,
    MutationUnavailable,
    initialize_mutation_supplier,
)
from continuity_lab.quote_reader import ReadOnlyQuoteSupplier


class ReadOnlyQuoteSupplierTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "supplier ?unicode-é#.sqlite3"
        initialize_mutation_supplier(self.path, scope_id="tenant-unit", revision=9007199254740993)

    def digest(self):
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def test_reads_same_provider_and_exact_bigint_revision_without_writing(self):
        source = MutationSupplier(self.path)
        before = self.digest()
        reader = ReadOnlyQuoteSupplier(self.path)
        self.assertEqual(reader.provider_id, source.provider_id)
        actual = reader.booking(scope_id="tenant-unit", booking_reference=" demo-bk-001 ")
        self.assertEqual(
            actual, source.booking(scope_id="tenant-unit", booking_reference="DEMO-BK-001")
        )
        self.assertEqual(actual.revision, 9007199254740993)
        self.assertEqual(actual.check_in, date(2030, 12, 1))
        self.assertEqual(self.digest(), before)
        self.assertFalse(Path(str(self.path) + "-wal").exists())
        self.assertFalse(Path(str(self.path) + "-journal").exists())
        self.assertFalse(hasattr(reader, "apply"))
        self.assertFalse(hasattr(reader, "lookup"))

    def test_connection_is_readonly_and_queryonly_even_if_queryonly_is_disabled(self):
        reader = ReadOnlyQuoteSupplier(self.path)
        before = self.digest()
        with reader._connection() as connection:
            self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("UPDATE bookings SET revision=revision+1")
            connection.execute("PRAGMA query_only=OFF")
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("UPDATE bookings SET revision=revision+1")
        self.assertEqual(self.digest(), before)

    def test_fixture_can_be_on_readonly_filesystem_paths_and_mode_is_preserved(self):
        self.path.chmod(0o400)
        self.root.chmod(0o500)
        self.addCleanup(self.root.chmod, 0o700)
        before = self.digest()
        reader = ReadOnlyQuoteSupplier(self.path)
        self.assertEqual(
            reader.booking(scope_id="tenant-unit", booking_reference="DEMO-BK-001").revision,
            9007199254740993,
        )
        self.assertEqual(self.digest(), before)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o400)

    def test_missing_cross_scope_and_wrong_reference_never_return_another_booking(self):
        reader = ReadOnlyQuoteSupplier(self.path)
        for scope, reference in (
            ("other-tenant", "DEMO-BK-001"),
            ("tenant-unit", "MISSING"),
            ("tenant-unit' OR 1=1 --", "DEMO-BK-001"),
        ):
            with self.subTest(scope=scope), self.assertRaises(MutationRejected):
                reader.booking(scope_id=scope, booking_reference=reference)

    def test_missing_symlink_directory_and_unknown_schema_fail_without_initialization(self):
        missing = self.root / "missing.sqlite3"
        symlink = self.root / "alias.sqlite3"
        symlink.symlink_to(self.path)
        empty = self.root / "empty.sqlite3"
        empty.touch(mode=0o600)
        for path in (missing, symlink, self.root, empty):
            with self.subTest(path=path.name), self.assertRaises(MutationUnavailable):
                ReadOnlyQuoteSupplier(path)
        self.assertFalse(missing.exists())
        self.assertEqual(empty.stat().st_size, 0)

    def test_replacement_provider_is_rejected_by_existing_reader(self):
        reader = ReadOnlyQuoteSupplier(self.path)
        replacement = self.root / "replacement.sqlite3"
        initialize_mutation_supplier(replacement, scope_id="tenant-unit")
        self.assertNotEqual(ReadOnlyQuoteSupplier(replacement).provider_id, reader.provider_id)
        os.replace(replacement, self.path)
        with self.assertRaises(MutationUnavailable):
            reader.booking(scope_id="tenant-unit", booking_reference="DEMO-BK-001")

    def test_changed_cooperation_mode_is_rejected_by_existing_reader(self):
        reader = ReadOnlyQuoteSupplier(self.path)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE supplier_metadata SET cooperating=0")
        with self.assertRaises(MutationUnavailable):
            reader.booking(scope_id="tenant-unit", booking_reference="DEMO-BK-001")
        fresh = ReadOnlyQuoteSupplier(self.path)
        self.assertEqual(fresh.provider_id, reader.provider_id)
        self.assertEqual(
            fresh.booking(scope_id="tenant-unit", booking_reference="DEMO-BK-001").revision,
            9007199254740993,
        )
