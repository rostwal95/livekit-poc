"""The independent synthetic supplier proves exact effects and declared limits."""

import json
import logging
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from continuity_lab.case_models import ActionIntent, QuoteSnapshot, canonical
from continuity_lab.execution_models import ExecutionCapacityExceeded
from continuity_lab.models import BookingChange
from continuity_lab.mutation_supplier import (
    MutationCapabilities,
    MutationConflict,
    MutationLookupUnsupported,
    MutationRejected,
    MutationSupplier,
    MutationUnavailable,
    NonCooperatingMutationSupplier,
    initialize_mutation_supplier,
)
from continuity_lab.supplier import FakeSupplier, SupplierReplayConflict, initialize_supplier

SCOPE = "account-a"
BOOKING = "DEMO-BK-001"
NOW = datetime(2030, 12, 1, tzinfo=UTC)


def intent_for(supplier, **changes):
    quote = QuoteSnapshot(
        str(uuid4()),
        str(uuid4()),
        0,
        BOOKING,
        date(2030, 12, 10),
        12500,
        "USD",
        (NOW + timedelta(hours=1)).isoformat(),
        case_id=str(uuid4()),
        expected_supplier_revision=0,
        supplier_id=supplier.provider_id,
    )
    intent = ActionIntent(
        str(uuid4()),
        quote.task_id,
        SCOPE,
        "actor-a",
        0,
        quote,
        str(uuid4()),
        str(uuid4()),
        str(uuid4()),
        NOW.isoformat(),
    )
    return replace(intent, **changes)


class MutationSupplierTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.database = self.folder / "supplier.sqlite3"
        initialize_mutation_supplier(self.database, scope_id=SCOPE)
        self.supplier = MutationSupplier(self.database, clock=lambda: NOW)
        self.intent = intent_for(self.supplier)
        self.before = self.supplier.booking(scope_id=SCOPE, booking_reference=BOOKING)

    def test_explicit_private_initialization_preserves_seed_and_provider_on_replay(self):
        self.assertEqual(self.database.stat().st_mode & 0o777, 0o600)
        provider = self.supplier.provider_id
        initialize_mutation_supplier(self.database, scope_id=SCOPE)
        self.assertEqual(MutationSupplier(self.database).provider_id, provider)
        self.assertEqual(
            self.supplier.booking(scope_id=SCOPE, booking_reference=BOOKING), self.before
        )
        with self.assertRaises(MutationUnavailable):
            MutationSupplier(self.folder / "missing.sqlite3")
        self.assertFalse((self.folder / "missing.sqlite3").exists())

    def test_exact_apply_records_confirmed_revision_date_amount_and_currency(self):
        observation = self.supplier.apply(self.intent)
        result = observation.result
        self.assertTrue(observation.created)
        self.assertEqual(
            (
                result.effect_id,
                result.intent_id,
                result.task_id,
                result.case_id,
                result.supplier_id,
            ),
            (
                self.intent.effect_id,
                self.intent.intent_id,
                self.intent.task_id,
                self.intent.quote.case_id,
                self.supplier.provider_id,
            ),
        )
        self.assertEqual(
            (
                result.previous_check_in,
                result.new_check_in,
                result.previous_revision,
                result.revision,
                result.amount_minor,
                result.currency,
            ),
            (self.before.check_in, self.intent.quote.new_check_in, 0, 1, 12500, "USD"),
        )
        after = self.supplier.booking(scope_id=SCOPE, booking_reference=BOOKING)
        self.assertEqual((after.check_in, after.revision), (self.intent.quote.new_check_in, 1))
        self.assertEqual(
            (
                self.supplier.count_calls(scope_id=SCOPE),
                self.supplier.count_mutations(scope_id=SCOPE),
            ),
            (1, 1),
        )

    def test_new_supplier_object_replays_original_effect_before_revision_check(self):
        first = self.supplier.apply(self.intent)
        reopened = MutationSupplier(self.database, clock=lambda: NOW + timedelta(days=1))
        replay = reopened.apply(self.intent)
        self.assertFalse(replay.created)
        self.assertEqual(replay.result, first.result)
        self.assertEqual(reopened.lookup(self.intent).result, first.result)
        self.assertEqual(
            (reopened.count_calls(scope_id=SCOPE), reopened.count_mutations(scope_id=SCOPE)), (2, 1)
        )

    def test_concurrent_equal_apply_calls_change_one_booking_revision(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = list(
                pool.map(
                    lambda _: MutationSupplier(self.database, clock=lambda: NOW).apply(self.intent),
                    range(8),
                )
            )
        self.assertEqual(sum(value.created for value in values), 1)
        self.assertEqual(len({value.result for value in values}), 1)
        self.assertEqual(self.supplier.count_mutations(scope_id=SCOPE), 1)
        self.assertEqual(
            self.supplier.booking(scope_id=SCOPE, booking_reference=BOOKING).revision, 1
        )

    def test_changed_effect_semantics_never_rewrite_original_receipt_or_booking(self):
        original = self.supplier.apply(self.intent)
        for modified in (
            replace(self.intent, intent_id=str(uuid4())),
            replace(self.intent, scope_id="account-b"),
            replace(self.intent, quote=replace(self.intent.quote, new_check_in=date(2030, 12, 11))),
            replace(self.intent, quote=replace(self.intent.quote, amount_minor=12501)),
            replace(self.intent, quote=replace(self.intent.quote, currency="EUR")),
        ):
            with self.subTest(kind=modified):
                with self.assertRaises(MutationConflict):
                    self.supplier.apply(modified)
                with self.assertRaises(MutationConflict):
                    self.supplier.lookup(modified)
        self.assertEqual(self.supplier.lookup(self.intent).result, original.result)
        self.assertEqual(self.supplier.count_mutations(scope_id=SCOPE), 1)

    def test_stale_supplier_revision_is_definitive_rejection_without_mutation(self):
        stale = replace(self.intent, quote=replace(self.intent.quote, expected_supplier_revision=1))
        with self.assertRaises(MutationRejected):
            self.supplier.apply(stale)
        self.assertEqual(
            self.supplier.booking(scope_id=SCOPE, booking_reference=BOOKING), self.before
        )
        self.assertIsNone(self.supplier.lookup(stale))
        self.assertEqual(self.supplier.count_mutations(scope_id=SCOPE), 0)
        self.assertTrue(self.supplier.apply(self.intent).created)

    def test_wrong_provider_target_never_looks_up_or_applies_another_authority(self):
        wrong = replace(self.intent, quote=replace(self.intent.quote, supplier_id=str(uuid4())))
        with self.assertRaises(MutationConflict):
            self.supplier.lookup(wrong)
        with self.assertRaises(MutationConflict):
            self.supplier.apply(wrong)
        self.assertEqual(self.supplier.count_calls(scope_id=SCOPE), 0)
        self.assertEqual(
            self.supplier.booking(scope_id=SCOPE, booking_reference=BOOKING), self.before
        )

    def test_legacy_quote_is_not_filled_from_mutable_current_booking(self):
        legacy = replace(
            self.intent,
            quote=replace(
                self.intent.quote, case_id=None, expected_supplier_revision=None, supplier_id=None
            ),
        )
        with self.assertRaises(MutationRejected):
            self.supplier.apply(legacy)
        self.assertEqual(self.supplier.count_calls(scope_id=SCOPE), 0)
        self.assertTrue(self.supplier.apply(self.intent).created)

    def test_noncooperating_mode_does_not_secretly_deduplicate_or_expose_lookup(self):
        database = self.folder / "noncooperating.sqlite3"
        initialize_mutation_supplier(database, scope_id=SCOPE, cooperating=False)
        supplier = NonCooperatingMutationSupplier(database, clock=lambda: NOW)
        intent = intent_for(supplier)
        self.assertEqual(supplier.capabilities, MutationCapabilities(False, False))
        self.assertTrue(supplier.apply(intent).created)
        with self.assertRaises(MutationLookupUnsupported):
            supplier.lookup(intent)
        with self.assertRaises(MutationRejected):
            supplier.apply(intent)
        self.assertEqual(
            (supplier.count_calls(scope_id=SCOPE), supplier.count_mutations(scope_id=SCOPE)), (2, 1)
        )
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM mutation_receipts").fetchone()[0], 0
            )

    def test_mode_is_immutable_and_opposite_adapter_cannot_reopen_same_authority(self):
        with self.assertRaises(MutationUnavailable):
            NonCooperatingMutationSupplier(self.database)
        with self.assertRaises(MutationConflict):
            initialize_mutation_supplier(self.database, scope_id=SCOPE, cooperating=False)
        self.assertEqual(
            self.supplier.booking(scope_id=SCOPE, booking_reference=BOOKING), self.before
        )

    def test_runtime_detects_provider_identity_drift_without_claiming_reliable_absence(self):
        original = self.supplier.provider_id
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("UPDATE supplier_metadata SET provider_id=?", (str(uuid4()),))
        with self.assertRaises(MutationUnavailable):
            self.supplier.lookup(self.intent)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("UPDATE supplier_metadata SET provider_id=?", (original,))
        self.assertIsNone(self.supplier.lookup(self.intent))
        self.assertTrue(self.supplier.apply(self.intent).created)

    def test_precommit_failure_rolls_back_booking_call_and_effect_then_retry_progresses(self):
        def fail(point):
            if point == "supplier.before_mutation_commit":
                raise RuntimeError("Controlled interruption")

        supplier = MutationSupplier(self.database, clock=lambda: NOW, failpoint=fail)
        with self.assertRaises(RuntimeError):
            supplier.apply(self.intent)
        self.assertEqual(
            self.supplier.booking(scope_id=SCOPE, booking_reference=BOOKING), self.before
        )
        self.assertEqual(self.supplier.count_calls(scope_id=SCOPE), 0)
        self.assertIsNone(self.supplier.lookup(self.intent))
        self.assertTrue(self.supplier.apply(self.intent).created)

    def test_aftercommit_lost_response_reopens_original_mutation_evidence(self):
        def fail(point):
            if point == "supplier.after_mutation_commit":
                raise MutationUnavailable("SECRET_SENTINEL")

        supplier = MutationSupplier(self.database, clock=lambda: NOW, failpoint=fail)
        with self.assertRaises(MutationUnavailable):
            supplier.apply(self.intent)
        result = MutationSupplier(self.database).lookup(self.intent)
        self.assertIsNotNone(result)
        self.assertEqual(result.result.revision, 1)
        self.assertEqual(self.supplier.count_mutations(scope_id=SCOPE), 1)

    def test_inquiry_view_has_no_apply_and_reads_same_mutable_booking_authority(self):
        view = self.supplier.inquiry_view()
        self.assertFalse(hasattr(view, "apply"))
        self.assertEqual(view.provider_id, self.supplier.provider_id)
        request = BookingChange(BOOKING, date(2030, 12, 10), True)
        effect = str(uuid4())
        initial = view.inquire(scope_id=SCOPE, effect_id=effect, request=request)
        self.assertEqual(view.booking(scope_id=SCOPE, booking_reference=BOOKING), self.before)
        self.supplier.apply(self.intent)
        self.assertEqual(view.booking(scope_id=SCOPE, booking_reference=BOOKING).revision, 1)
        replay = view.inquire(scope_id=SCOPE, effect_id=effect, request=request)
        self.assertFalse(replay.created)
        self.assertEqual(replay.result, initial.result)
        self.assertEqual(self.supplier.count_inquiries(scope_id=SCOPE), 1)
        with self.assertRaises(SupplierReplayConflict):
            view.inquire(
                scope_id=SCOPE,
                effect_id=effect,
                request=BookingChange(BOOKING, date(2030, 12, 11), True),
            )

    def test_old_readonly_supplier_fixture_remains_compatible_and_cannot_be_reused_as_new_schema(
        self,
    ):
        database = self.folder / "legacy.sqlite3"
        initialize_supplier(database, scope_id=SCOPE)
        original = FakeSupplier(database).booking(scope_id=SCOPE, booking_reference=BOOKING)
        with self.assertRaises(MutationUnavailable):
            MutationSupplier(database)
        with self.assertRaises(MutationUnavailable):
            initialize_mutation_supplier(database, scope_id=SCOPE)
        self.assertEqual(
            FakeSupplier(database).booking(scope_id=SCOPE, booking_reference=BOOKING), original
        )

    def test_capacities_preserve_original_receipt_replay_and_prevent_new_effect(self):
        supplier = MutationSupplier(
            self.database, clock=lambda: NOW, maximum_mutations=1, maximum_calls=1
        )
        first = supplier.apply(self.intent)
        self.assertEqual(supplier.apply(self.intent).result, first.result)
        next_intent = intent_for(supplier)
        next_intent = replace(
            next_intent, quote=replace(next_intent.quote, expected_supplier_revision=1)
        )
        with self.assertRaises(ExecutionCapacityExceeded):
            supplier.apply(next_intent)
        self.assertEqual(supplier.count_mutations(scope_id=SCOPE), 1)
        self.assertEqual(supplier.booking(scope_id=SCOPE, booking_reference=BOOKING).revision, 1)

    def test_corrupt_receipt_is_unavailable_not_success_or_missing_and_repair_restores_progress(
        self,
    ):
        expected = self.supplier.apply(self.intent)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            original = connection.execute("SELECT result_json FROM mutation_receipts").fetchone()[0]
            altered = json.loads(original)
            altered["amount_minor"] += 1
            connection.execute("UPDATE mutation_receipts SET result_json=?", (canonical(altered),))
        with self.assertRaises(MutationUnavailable):
            self.supplier.lookup(self.intent)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("UPDATE mutation_receipts SET result_json=?", (original,))
        self.assertEqual(self.supplier.lookup(self.intent).result, expected.result)

    def test_logging_outage_cannot_turn_a_known_supplier_success_into_ambiguity(self):
        class Broken(logging.Handler):
            def emit(self, record):
                raise RuntimeError("SECRET_SENTINEL")

        logger = logging.getLogger("continuity_lab.mutation_supplier")
        handler = Broken()
        logger.addHandler(handler)
        level = logger.level
        logger.setLevel(logging.INFO)
        try:
            self.assertTrue(self.supplier.apply(self.intent).created)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(level)
        self.assertEqual(self.supplier.count_mutations(scope_id=SCOPE), 1)

    def test_invalid_capability_flags_are_not_truthy_model_values(self):
        for flags in [("yes", True), (True, 1), (None, False)]:
            with self.assertRaises(ValueError):
                MutationCapabilities(*flags)

    def test_initialization_cannot_reset_a_changed_booking(self):
        self.supplier.apply(self.intent)
        with self.assertRaises(MutationConflict):
            initialize_mutation_supplier(self.database, scope_id=SCOPE)
        self.assertEqual(
            self.supplier.booking(scope_id=SCOPE, booking_reference=BOOKING).revision, 1
        )
