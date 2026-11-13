"""Typed conversation boundaries preserve auth, exact integers and owned I/O."""

import asyncio
import base64
import threading
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from continuity_lab.authorization import (
    AuthenticatedActor,
    AuthenticationFailed,
    BearerToken,
    TokenDirectory,
)
from continuity_lab.case_models import CaseSnapshot, Confirmation, QuoteSnapshot, canonical
from continuity_lab.case_projection import (
    CaseProjection,
    _cursor,
    _decode_cursor,
    parse_confirmation_payload,
    quote_payload,
    strict_json,
    wire_value,
)
from continuity_lab.case_service import ScopedCaseService
from continuity_lab.conversation_service import AsyncConversationService, ConversationService
from continuity_lab.execution_models import (
    ExecutionCapacityExceeded,
    ExecutionNotFound,
    InvalidStoredState,
)
from continuity_lab.models import BookingChange
from continuity_lab.quote_producer import QuoteReceipt, quote_command_ids

ACTOR = AuthenticatedActor("actor-a", "scope-a")
TOKEN = BearerToken("a" * 40)
UNKNOWN = BearerToken("b" * 40)
TASK = "11111111-1111-4111-8111-111111111111"
CASE = "22222222-2222-4222-8222-222222222222"
QUOTE = "33333333-3333-4333-8333-333333333333"
SUPPLIER = "44444444-4444-4444-8444-444444444444"
STAMP = "2030-12-01T00:00:00+00:00"
REQUEST = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)


def proposal(revision=0):
    return QuoteSnapshot(
        QUOTE,
        TASK,
        revision,
        REQUEST.booking_reference,
        REQUEST.new_check_in,
        2500,
        "USD",
        "2030-12-01T00:02:00+00:00",
        CASE,
        9223372036854775806,
        SUPPLIER,
    )


class ConversationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = TokenDirectory({TOKEN: ACTOR})
        self.cases = Mock()
        self.lifecycle = Mock()
        self.effects = Mock()
        self.case_service = ScopedCaseService(
            self.directory, self.cases, self.lifecycle, effects=self.effects
        )
        self.admission = Mock()
        self.projection = Mock()
        self.producer = Mock()
        self.service = ConversationService(
            self.directory, self.admission, self.projection, self.case_service, self.producer
        )
        self.case = CaseSnapshot(
            TASK, ACTOR.scope_id, ACTOR.actor_id, 0, REQUEST, None, False, None, STAMP, STAMP, CASE
        )
        self.document = CaseProjection.create(
            {"task_id": TASK, "case_id": CASE, "request_key": "key"}
        )
        self.admission.accept.return_value = SimpleNamespace(created=True, case=self.case)
        self.projection.get.return_value = self.document

    def test_every_operation_authenticates_before_backend_or_payload_validation(self):
        operations = [
            lambda: self.service.submit(token=UNKNOWN, idempotency_key=None, request=None),
            lambda: self.service.get(token=UNKNOWN, task_id=None, cursor="not-base64"),
            lambda: self.service.prepare_quote(
                token=UNKNOWN, task_id=None, expected_revision=True, command_id=None
            ),
            lambda: self.service.signal(
                token=UNKNOWN, task_id=None, confirmation=None, command_id=None
            ),
            lambda: self.service.cancel(token=UNKNOWN, task_id=None, command_id=None),
        ]
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaises(AuthenticationFailed):
                operation()
        self.admission.accept.assert_not_called()
        self.projection.get.assert_not_called()
        self.producer.prepare.assert_not_called()
        self.lifecycle.signal.assert_not_called()
        self.effects.cancel.assert_not_called()

    def test_submit_returns_original_ids_and_current_projection_with_trusted_actor(self):
        result = self.service.submit(token=TOKEN, idempotency_key="key", request=REQUEST)
        self.admission.accept.assert_called_once_with(
            actor=ACTOR, idempotency_key="key", request=REQUEST
        )
        self.projection.get.assert_called_once_with(actor=ACTOR, task_id=TASK)
        self.assertEqual(
            result.payload(),
            {
                "created": True,
                "task_id": TASK,
                "case_id": CASE,
                "projection": self.document.payload(),
            },
        )
        self.assertNotIn(TOKEN.value, repr(self.service))

    def test_signal_route_binding_rejects_before_any_signal_write(self):
        confirmation = Confirmation(proposal(), True)
        with self.assertRaises(ValueError):
            self.service.signal(
                token=TOKEN, task_id="different-task", confirmation=confirmation, command_id="same"
            )
        self.lifecycle.signal.assert_not_called()
        self.service.signal(
            token=TOKEN, task_id=TASK, confirmation=confirmation, command_id="signal-1"
        )
        self.lifecycle.signal.assert_called_once_with(
            actor=ACTOR, event_id="signal-1", confirmation=confirmation
        )

    def test_no_producer_is_unsupported_only_after_auth_and_cancel_remains_available(self):
        service = ConversationService(
            self.directory, self.admission, self.projection, self.case_service
        )
        from continuity_lab.execution_models import UnsupportedOperation

        with self.assertRaises(AuthenticationFailed):
            service.prepare_quote(token=UNKNOWN, task_id=TASK, expected_revision=0, command_id="q")
        with self.assertRaises(UnsupportedOperation):
            service.prepare_quote(token=TOKEN, task_id=TASK, expected_revision=0, command_id="q")
        service.cancel(token=TOKEN, task_id=TASK, command_id="cancel-1")
        self.effects.cancel.assert_called_once()
        self.assertEqual(self.effects.cancel.call_args.kwargs["actor"], ACTOR)

    def test_projection_never_accepts_scope_or_actor_overrides(self):
        with self.assertRaises(TypeError):
            self.service.get(token=TOKEN, task_id=TASK, scope_id="other")
        with self.assertRaises(TypeError):
            self.service.submit(token=TOKEN, idempotency_key="x", request=REQUEST, actor=ACTOR)
        self.projection.get.side_effect = ExecutionNotFound("private-unavailable")
        with self.assertRaises(ExecutionNotFound):
            self.service.get(token=TOKEN, task_id=TASK, cursor="bad")
        self.projection.get.assert_called_once_with(
            actor=ACTOR, task_id=TASK, cursor="bad", limit=10
        )

    def test_controller_and_conversation_directory_cannot_disagree(self):
        another = TokenDirectory({TOKEN: AuthenticatedActor("other", "other")})
        with self.assertRaises(ValueError):
            ConversationService(another, self.admission, self.projection, self.case_service)

    def test_telemetry_failure_does_not_replace_original_private_error(self):
        class Private(ExecutionNotFound):
            def __str__(self):
                raise AssertionError("Exception text must never be read")

        error = Private("SECRET_SENTINEL")
        self.projection.get.side_effect = error
        with (
            patch(
                "continuity_lab.case_telemetry.LOGGER.log",
                side_effect=RuntimeError("logger outage"),
            ),
            self.assertRaises(Private) as caught,
        ):
            self.service.get(token=TOKEN, task_id=TASK)
        self.assertIs(caught.exception, error)
        metrics = self.service.telemetry.render().decode()
        self.assertNotIn("SECRET_SENTINEL", metrics)
        self.assertNotIn(TOKEN.value, metrics)

    def test_prepare_quote_returns_created_receipt_without_caller_price_fields(self):
        receipt = QuoteReceipt(proposal(), False, "55555555-5555-4555-8555-555555555555")
        self.producer.prepare.return_value = receipt
        self.assertEqual(
            self.service.prepare_quote(
                token=TOKEN, task_id=TASK, expected_revision=0, command_id="q"
            ),
            receipt,
        )
        self.producer.prepare.assert_called_once_with(
            actor=ACTOR, task_id=TASK, expected_revision=0, command_id="q"
        )
        with self.assertRaises(TypeError):
            self.service.prepare_quote(
                token=TOKEN, task_id=TASK, expected_revision=0, command_id="q", amount_minor=0
            )


class ProjectionContractTests(unittest.TestCase):
    def test_bigint_presentation_and_opaque_confirmation_roundtrip_exactly(self):
        quote = proposal(9007199254740993)
        wire = quote_payload(quote)
        self.assertEqual(wire["revision"], "9007199254740993")
        self.assertEqual(wire["expected_supplier_revision"], "9223372036854775806")
        confirmation = parse_confirmation_payload(wire["confirmation_payload"], explicit=True)
        self.assertEqual(confirmation.quote, quote)
        self.assertIs(type(confirmation.quote.revision), int)
        self.assertEqual(
            wire_value({"revision": 9223372036854775807, "amount_minor": 2500}),
            {"revision": "9223372036854775807", "amount_minor": 2500},
        )

    def test_wire_bigints_reject_bool_float_and_nonfinite_projection_values(self):
        for value in (True, 1.0, "1", -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                wire_value({"revision": value})
        with self.assertRaises(ValueError):
            CaseProjection.create({"x": float("nan")})

    def test_confirmation_rejects_noncanonical_duplicate_float_and_nonfinite_payloads(self):
        raw = canonical(proposal().payload())
        invalid = [
            " " + raw,
            raw.replace('"revision":0', '"revision":0.0'),
            raw.replace('"revision":0', '"revision":NaN'),
            raw.replace('"revision":0', '"revision":0,"revision":0'),
            raw.replace('"amount_minor":2500', '"amount_minor":2501'),
        ]
        for value in invalid[:-1]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_confirmation_payload(value, explicit=True)
        # Changed canonical content remains a different typed confirmation; authority must reject it.
        self.assertNotEqual(
            parse_confirmation_payload(invalid[-1], explicit=True).quote, proposal()
        )
        for explicit in (False, 1, "true", None):
            with self.subTest(explicit=explicit), self.assertRaises(ValueError):
                parse_confirmation_payload(raw, explicit=explicit)
        with self.assertRaises(ValueError):
            strict_json('{"x":1,"x":2}')
        with self.assertRaises(ValueError):
            strict_json('{"x":Infinity}')

    def test_cursor_is_bounded_canonical_and_never_carries_authority(self):
        cursor = _cursor("a" * 64, 1)
        self.assertEqual(_decode_cursor(cursor), ("a" * 64, 1))
        self.assertIsNone(_decode_cursor(None))
        for bad in ("a" * 513, "=bad", "not_base64", "", _cursor("b" * 64, 1001)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                _decode_cursor(bad)
        raw = (
            base64.urlsafe_b64encode(b'{"v":1,"revision":"' + b"a" * 64 + b'","offset":true}')
            .decode()
            .rstrip("=")
        )
        with self.assertRaises(ValueError):
            _decode_cursor(raw)

    def test_projection_snapshots_are_copied_and_response_bytes_are_bounded(self):
        value = {"task_id": TASK, "nested": {"state": "waiting"}}
        result = CaseProjection.create(value)
        value["nested"]["state"] = "succeeded"
        self.assertEqual(result.payload()["nested"]["state"], "waiting")
        first = result.payload()
        first["nested"]["state"] = "cancelled"
        self.assertEqual(result.payload()["nested"]["state"], "waiting")
        with self.assertRaises(InvalidStoredState):
            CaseProjection.create({"x": "a" * 65536})

    def test_quote_command_identity_binds_owner_scope_task_and_command(self):
        original = quote_command_ids(ACTOR, TASK, "one")
        self.assertNotEqual(original[0], original[1])
        self.assertEqual(original, quote_command_ids(ACTOR, TASK, "one"))
        for actor, task, command in [
            (AuthenticatedActor("other", ACTOR.scope_id), TASK, "one"),
            (AuthenticatedActor(ACTOR.actor_id, "other"), TASK, "one"),
            (ACTOR, "other", "one"),
            (ACTOR, TASK, "two"),
        ]:
            self.assertNotEqual(original, quote_command_ids(actor, task, command))


class AsyncConversationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_media_waiter_does_not_cancel_running_acceptance_or_release_capacity_early(
        self,
    ):
        entered = threading.Event()
        release = threading.Event()
        completed = threading.Event()

        def accept(_service):
            entered.set()
            release.wait(3)
            completed.set()
            return "original-task"

        service = SimpleNamespace()
        io = AsyncConversationService(
            service, maximum=1, admission_timeout=0.02, shutdown_timeout=3
        )
        caller = asyncio.create_task(io.run(accept))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            caller.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await caller
            self.assertEqual(io.pending_count, 1)
            # Event-loop work can still progress while the storage thread is held.
            self.assertEqual(
                await asyncio.wait_for(asyncio.sleep(0.01, result="responsive"), 0.2), "responsive"
            )
            with self.assertRaises(ExecutionCapacityExceeded):
                await io.run(lambda _: "second")
            release.set()
            await io.close()
            self.assertTrue(completed.is_set())
            self.assertEqual(io.pending_count, 0)
        finally:
            release.set()
            await io.close()
