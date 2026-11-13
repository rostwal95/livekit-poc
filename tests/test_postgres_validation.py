"""Catalog batching preserves the versioned read-only authorization boundary."""

from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace

from continuity_lab import postgres_migrations as migrations
from continuity_lab.migrations import SchemaVersionError


class CatalogConnection:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, statement, parameters):
        self.calls.append((statement, parameters))
        return SimpleNamespace(fetchall=lambda: copy.deepcopy(self.rows))


class RoleConnection:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def execute(self, statement, parameters):
        self.calls.append((statement, parameters))
        return SimpleNamespace(fetchone=lambda: copy.deepcopy(self.row))


def column_rows(catalog):
    result = []
    for table in sorted(catalog.columns):
        for name in catalog.columns[table]:
            kind, not_null = catalog.column_specs[table][name]
            result.append(
                {
                    "table_name": table,
                    "attname": name,
                    "kind": kind,
                    "attnotnull": not_null,
                    "collname": "C" if kind == "text" else None,
                    "attidentity": "",
                    "attgenerated": "",
                    "atthasdef": False,
                }
            )
    return result


def original_column_decision(catalog, rows):
    """Original per-table predicates, independent of the new grouping function."""
    for table, columns in catalog.columns.items():
        actual = [row for row in rows if row["table_name"] == table]
        if tuple(row["attname"] for row in actual) != columns:
            return "PostgreSQL columns are unsupported"
        for row in actual:
            expected_type, not_null = catalog.column_specs[table][row["attname"]]
            if (
                row["kind"] != expected_type
                or row["attnotnull"] != not_null
                or row["attidentity"]
                or row["attgenerated"]
                or row["atthasdef"]
                or (expected_type == "text" and row["collname"] != "C")
            ):
                return "PostgreSQL column constraints are unsupported"
    return None


class PostgresValidationTests(unittest.TestCase):
    def assert_same_column_decision(self, catalog, rows):
        expected = original_column_decision(catalog, rows)
        connection = CatalogConnection(rows)
        if expected is None:
            migrations._validate_columns(connection, "owned_schema", catalog)
        else:
            with self.assertRaises(SchemaVersionError) as caught:
                migrations._validate_columns(connection, "owned_schema", catalog)
            self.assertEqual(expected, str(caught.exception))
        self.assertEqual(1, len(connection.calls))
        return connection

    def test_one_current_ordered_catalog_read_preserves_each_supported_version(self):
        for version, table_count, columns_count in (
            (1, 4, 27),
            (2, 13, 90),
            (3, 19, 132),
            (4, 21, 144),
        ):
            with self.subTest(version=version):
                catalog = migrations._catalog(version)
                rows = column_rows(catalog)
                before = copy.deepcopy(rows)
                connection = self.assert_same_column_decision(catalog, rows)
                self.assertEqual(rows, before)
                self.assertEqual(table_count, len(catalog.columns))
                self.assertEqual(columns_count, len(rows))
                query, parameters = connection.calls[0]
                self.assertEqual(("owned_schema", list(catalog.columns)), parameters)
                self.assertIn("t.relname=ANY(%s)", query)
                self.assertIn("ORDER BY t.relname,a.attnum", query)
                self.assertIn("a.attnum>0 AND NOT a.attisdropped", query)

    def test_all_versions_reject_missing_extra_reordered_and_duplicate_columns(self):
        for version in range(1, 5):
            catalog = migrations._catalog(version)
            original = column_rows(catalog)
            for table in catalog.columns:
                indices = [
                    index for index, row in enumerate(original) if row["table_name"] == table
                ]
                missing_table = [row for row in original if row["table_name"] != table]
                missing_column = original[: indices[0]] + original[indices[0] + 1 :]
                extra = copy.deepcopy(original)
                extra.insert(indices[-1] + 1, {**original[indices[-1]], "attname": "unexpected"})
                duplicate = copy.deepcopy(original)
                duplicate.insert(indices[0], copy.deepcopy(original[indices[0]]))
                reordered = copy.deepcopy(original)
                reordered[indices[0]], reordered[indices[1]] = (
                    reordered[indices[1]],
                    reordered[indices[0]],
                )
                for kind, rows in (
                    ("missing-table", missing_table),
                    ("missing-column", missing_column),
                    ("extra", extra),
                    ("duplicate", duplicate),
                    ("reordered", reordered),
                ):
                    with self.subTest(version=version, table=table, corruption=kind):
                        self.assertIsNotNone(original_column_decision(catalog, rows))
                        self.assert_same_column_decision(catalog, rows)

    def test_every_column_retains_type_null_default_identity_generated_and_text_collation_checks(
        self,
    ):
        for version in range(1, 5):
            catalog = migrations._catalog(version)
            original = column_rows(catalog)
            for index, row in enumerate(original):
                changes = {
                    "kind": "unsupported type",
                    "attnotnull": not row["attnotnull"],
                    "atthasdef": True,
                    "attidentity": "a",
                    "attgenerated": "s",
                }
                if row["kind"] == "text":
                    changes["collname"] = "default"
                for field, value in changes.items():
                    rows = copy.deepcopy(original)
                    rows[index][field] = value
                    with self.subTest(
                        version=version, table=row["table_name"], column=row["attname"], field=field
                    ):
                        self.assertEqual(
                            "PostgreSQL column constraints are unsupported",
                            original_column_decision(catalog, rows),
                        )
                        self.assert_same_column_decision(catalog, rows)

    def test_repeated_validation_observes_later_catalog_drift_without_caching(self):
        catalog = migrations._catalog(4)
        connection = CatalogConnection(column_rows(catalog))
        migrations._validate_columns(connection, "owned_schema", catalog)
        connection.rows[-1]["atthasdef"] = True
        with self.assertRaises(SchemaVersionError):
            migrations._validate_columns(connection, "owned_schema", catalog)
        connection.rows[-1]["atthasdef"] = False
        migrations._validate_columns(connection, "owned_schema", catalog)
        self.assertEqual(3, len(connection.calls))

    def test_role_flags_and_membership_share_one_fresh_read_with_original_failure_priority(self):
        flags = ("rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls")
        allowed = {**dict.fromkeys(flags, False), "memberships": False}
        scenarios = [(None, "Restricted PostgreSQL roles are required"), (allowed, None)]
        scenarios += [
            ({**allowed, flag: True}, "Restricted PostgreSQL roles are required") for flag in flags
        ]
        scenarios += [
            (
                {**allowed, "memberships": True},
                "Inherited PostgreSQL administration is unsupported",
            ),
            (
                {**allowed, "memberships": True, "rolsuper": True},
                "Restricted PostgreSQL roles are required",
            ),
        ]
        for row, expected in scenarios:
            with self.subTest(flags=row):
                connection = RoleConnection(row)
                if expected is None:
                    migrations._restricted_role(connection, "livekit_lab")
                else:
                    with self.assertRaises(SchemaVersionError) as caught:
                        migrations._restricted_role(connection, "livekit_lab")
                    self.assertEqual(expected, str(caught.exception))
                self.assertEqual(1, len(connection.calls))
                query, parameters = connection.calls[0]
                self.assertEqual(("livekit_lab",), parameters)
                self.assertIn("m.member=r.oid", query)
        connection = RoleConnection(allowed)
        migrations._restricted_role(connection, "livekit_lab")
        connection.row["memberships"] = True
        with self.assertRaisesRegex(SchemaVersionError, "Inherited PostgreSQL"):
            migrations._restricted_role(connection, "livekit_lab")
        self.assertEqual(2, len(connection.calls))


if __name__ == "__main__":
    unittest.main()
