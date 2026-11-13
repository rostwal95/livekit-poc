"""Independent receiver retains logical uniqueness across projection pruning."""

import logging
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from continuity_lab.completion_sink import (
    CompletionSink,
    CompletionSinkConflict,
    CompletionSinkUnavailable,
    initialize_completion_sink,
)
from continuity_lab.execution_models import ExecutionCapacityExceeded
from tests.test_effect_models import NOW, example_event


class CompletionSinkTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "receiver.sqlite3"
        self.receiver_id = initialize_completion_sink(self.path)
        self.sink = CompletionSink(self.path, clock=lambda: NOW)
        self.event = example_event()

    def test_explicit_initialization_and_restart_preserve_private_receiver_identity(
        self,
    ):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(initialize_completion_sink(self.path), self.receiver_id)
        self.assertEqual(CompletionSink(self.path).receiver_id, self.receiver_id)
        with self.assertRaises(CompletionSinkConflict):
            initialize_completion_sink(self.path, receiver_id=str(uuid4()))
        missing = self.path.with_name("missing.sqlite3")
        with self.assertRaises(CompletionSinkUnavailable):
            CompletionSink(missing)
        self.assertFalse(missing.exists())

    def test_same_event_replay_returns_original_receipt_at_full_capacity(self):
        sink = CompletionSink(self.path, clock=lambda: NOW, maximum_records=1)
        first = sink.accept(self.event)
        reopened = CompletionSink(
            self.path, clock=lambda: NOW + timedelta(days=1), maximum_records=1
        )
        replay = reopened.accept(self.event)
        self.assertTrue(first.created)
        self.assertFalse(replay.created)
        self.assertEqual(first.received_at, replay.received_at)
        self.assertEqual(reopened.count(), 1)
        self.assertEqual(reopened.get(event_id=self.event.event_id), self.event)
        with self.assertRaises(ExecutionCapacityExceeded):
            reopened.accept(example_event())

    def test_changed_payload_same_event_conflicts_without_replacing_evidence(self):
        self.sink.accept(self.event)
        # A valid but different immutable result remains a conflicting event.
        changed_result = replace(
            self.event.outcome.result,
            previous_check_in=self.event.outcome.result.previous_check_in + timedelta(days=1),
        )
        changed = replace(self.event, outcome=replace(self.event.outcome, result=changed_result))
        with self.assertRaises(CompletionSinkConflict):
            self.sink.accept(changed)
        self.assertEqual(self.sink.get(event_id=self.event.event_id), self.event)
        self.assertEqual(self.sink.count(), 1)

    def test_parallel_receivers_accept_one_logical_completion(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            receipts = list(
                pool.map(
                    lambda _: CompletionSink(self.path, clock=lambda: NOW).accept(self.event),
                    range(8),
                )
            )
        self.assertEqual(sum(receipt.created for receipt in receipts), 1)
        self.assertEqual(self.sink.count(), 1)

    def test_diagnostic_pruning_never_erases_core_late_replay_deduplication(self):
        sink = CompletionSink(self.path, clock=lambda: NOW, diagnostic_limit=2)
        original = sink.accept(self.event)
        for _ in range(5):
            sink.accept(example_event())
        self.assertEqual((sink.count(), sink.diagnostic_count()), (6, 2))
        self.assertEqual(sink.prune_diagnostics(keep=0), 2)
        self.assertEqual(sink.diagnostic_count(), 0)
        reopened = CompletionSink(self.path, clock=lambda: NOW + timedelta(days=365))
        replay = reopened.accept(self.event)
        self.assertFalse(replay.created)
        self.assertEqual(replay.received_at, original.received_at)
        self.assertEqual((reopened.count(), reopened.diagnostic_count()), (6, 1))

    def test_receiver_target_identity_is_immutable_for_existing_instance(self):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE sink_metadata SET receiver_id=?", (str(uuid4()),))
        with self.assertRaises(CompletionSinkConflict):
            self.sink.accept(self.event)

    def test_corrupt_receipt_clock_is_rejected_without_false_acknowledgement(self):
        self.sink.accept(self.event)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE completion_receipts SET received_at='bad-clock'")
        with self.assertRaises(CompletionSinkUnavailable):
            self.sink.accept(self.event)

    def test_unknown_schema_and_public_permissions_fail_closed(self):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("CREATE TABLE unexpected (value TEXT)")
        with self.assertRaises(CompletionSinkUnavailable):
            CompletionSink(self.path)
        self.path.chmod(0o644)
        with self.assertRaises(CompletionSinkUnavailable):
            CompletionSink(self.path)

    def test_telemetry_failure_does_not_change_accepted_completion(self):
        class BrokenHandler(logging.Handler):
            def emit(self, record):
                raise RuntimeError("SECRET_SENTINEL")

        logger = logging.getLogger("continuity_lab.completion_sink")
        handler = BrokenHandler()
        logger.addHandler(handler)
        old = logger.level
        logger.setLevel(logging.INFO)
        self.addCleanup(logger.removeHandler, handler)
        self.addCleanup(logger.setLevel, old)
        self.assertTrue(self.sink.accept(self.event).created)
        self.assertEqual(self.sink.count(), 1)
