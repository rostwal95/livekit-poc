"""Offline public values and credential boundary; never connects to PostgreSQL."""

import dataclasses
import unittest
from unittest.mock import patch

from continuity_lab.work_api import (
    BearerToken,
    PostgresSettings,
    WorkDirectory,
    WorkError,
    WorkLimits,
    WorkPayload,
    WorkPrincipal,
    WorkScope,
    open_work_client,
)


class HostileEquality:
    def __eq__(self, other):
        raise AssertionError("No caller equality hook may run")


class ReadOnlyWorkValues(unittest.TestCase):
    def test_immutable_bounded_bytes_have_original_digest_and_safe_representation(self):
        payload = WorkPayload("booking.evaluate_policy", b"{}", 2000000000000)
        self.assertEqual(
            payload.sha256, "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            payload.body = b"different"
        private = WorkPayload("booking.evaluate_policy", b"PRIVATE_BODY_SENTINEL", 2000000000000)
        self.assertNotIn("PRIVATE_BODY_SENTINEL", repr(private))
        self.assertEqual(private.body, b"PRIVATE_BODY_SENTINEL")

    def test_bad_values_reject_before_caller_hooks_and_valid_input_progresses(self):
        for operation, body, deadline in (
            (HostileEquality(), b"{}", 1),
            ("booking.change", b"{}", 1),
            ("booking.evaluate_policy", bytearray(b"{}"), 1),
            ("booking.evaluate_policy", b"", 1),
            ("booking.evaluate_policy", b"x" * 16385, 1),
            ("booking.evaluate_policy", b"{}", True),
            ("booking.evaluate_policy", b"{}", -1),
            ("booking.evaluate_policy", b"{}", 4102444800001),
        ):
            with self.subTest(kind=type(body).__name__), self.assertRaises(WorkError):
                WorkPayload(operation, body, deadline)
        self.assertEqual(
            WorkPayload("booking.evaluate_policy", b"x" * 16384, 4102444800000).body, b"x" * 16384
        )
        self.assertEqual(str(WorkError([])), "invalid_input")

    def test_typed_scope_and_caps_reject_ambiguous_or_unbounded_values(self):
        for scope in (
            ("tenant\n", "account"),
            ("tenant/part", "account"),
            ("x" * 129, "account"),
            (True, "account"),
        ):
            with self.assertRaises(WorkError):
                WorkScope(*scope)
        self.assertNotEqual(WorkScope("tenant-a", "account-b"), WorkScope("tenant", "a-account-b"))
        for value in (0, 10001, True, 1.5):
            with self.assertRaises(WorkError):
                WorkLimits(value, 1)
        self.assertEqual(WorkLimits(1, 1).max_records, 1)

    def test_directory_snapshots_configuration_and_never_retains_token_text(self):
        token = BearerToken("synthetic-work-token-" + "x" * 32)
        principal = WorkPrincipal("operator", WorkScope("tenant", "account"))
        registrations = {token: principal}
        directory = WorkDirectory(registrations)
        registrations.clear()
        self.assertEqual(directory.authenticate(token), principal)
        self.assertNotIn(token.value, repr(directory))
        with self.assertRaises(WorkError) as caught:
            directory.authenticate(BearerToken("y" * 43))
        self.assertEqual(caught.exception.code, "unauthorized")
        with self.assertRaises(WorkError):
            WorkDirectory({})

    def test_duplicate_credential_inventory_cannot_silently_replace_scope(self):
        token = BearerToken("x" * 43)
        first = WorkPrincipal("first", WorkScope("tenant", "first"))
        second = WorkPrincipal("second", WorkScope("tenant", "second"))

        class Duplicate(dict):
            def items(self):
                return ((token, first), (token, second))

        with self.assertRaises(WorkError):
            WorkDirectory(Duplicate({token: first}))
        self.assertEqual(WorkDirectory({token: first}).authenticate(token), first)

    def test_mapping_items_cannot_exceed_the_credential_inventory_limit(self):
        principal = WorkPrincipal("operator", WorkScope("tenant", "account"))

        class ReportedOne(dict):
            def __init__(self, count):
                super().__init__({BearerToken("x" * 43): principal})
                self.count = count
                self.yielded = 0

            def items(self):
                for position in range(self.count):
                    self.yielded += 1
                    yield BearerToken(f"{position:043d}"), principal

        empty = ReportedOne(0)
        with self.assertRaises(WorkError) as empty_error:
            WorkDirectory(empty)
        self.assertEqual(empty_error.exception.code, "invalid_input")
        self.assertEqual(empty.yielded, 0)
        overflow = ReportedOne(1000)
        with self.assertRaises(WorkError) as caught:
            WorkDirectory(overflow)
        self.assertEqual(caught.exception.code, "invalid_input")
        self.assertEqual(overflow.yielded, 65)
        bounded = ReportedOne(64)
        directory = WorkDirectory(bounded)
        self.assertEqual(directory.authenticate(BearerToken(f"{63:043d}")), principal)
        self.assertEqual(bounded.yielded, 64)

    def test_factory_authenticates_before_opening_store_and_never_installs(self):
        token = BearerToken("x" * 43)
        directory = WorkDirectory(
            {token: WorkPrincipal("operator", WorkScope("tenant", "account"))}
        )
        settings = PostgresSettings(password="synthetic-only-password", schema="p1_work_fixture")
        with (
            patch("continuity_lab.work_api.WorkStore") as store,
            self.assertRaises(WorkError) as caught,
        ):
            open_work_client(settings=settings, directory=directory, token=BearerToken("y" * 43))
        self.assertEqual(caught.exception.code, "unauthorized")
        store.assert_not_called()
