"""Authenticated effect views and cancellation retain safe finite observations."""

import json
import unittest
from dataclasses import replace
from datetime import date
from unittest.mock import create_autospec, patch

from prometheus_client.parser import text_string_to_metric_families

from continuity_lab.authorization import (
    AuthenticatedActor,
    AuthenticationFailed,
    BearerToken,
    TokenDirectory,
)
from continuity_lab.case_models import ActionIntent, CaseAuthorityPort, CaseSnapshot, QuoteSnapshot
from continuity_lab.case_service import LifecyclePort, ScopedCaseService
from continuity_lab.case_telemetry import OPERATIONS, OUTCOMES
from continuity_lab.effect_models import (
    BusinessOutcome,
    CancellationDisposition,
    CancellationReceipt,
    CancelReason,
    CompletionEvent,
    DeliverySnapshot,
    DeliveryState,
    EffectSnapshot,
    EffectState,
    EffectViewPort,
)
from continuity_lab.execution_cli import _SafeFormatter
from continuity_lab.execution_models import (
    ExecutionNotFound,
    StorageUnavailable,
    UnsupportedOperation,
)
from continuity_lab.models import BookingChange


class PrivateEffectFailure(RuntimeError):
    def __str__(self):
        raise AssertionError("Private exception text must never be formatted")

    def __repr__(self):
        raise AssertionError("Private exception representation must never be formatted")


class EffectServiceTests(unittest.TestCase):
    def setUp(self):
        self.actor = AuthenticatedActor("PRIVATE_ACTOR", "PRIVATE_SCOPE")
        self.peer = AuthenticatedActor("PRIVATE_OTHER_ACTOR", self.actor.scope_id)
        self.foreign = AuthenticatedActor(self.actor.actor_id, "PRIVATE_OTHER_SCOPE")
        self.token, self.peer_token, self.foreign_token = (
            BearerToken(character * 40) for character in ("a", "b", "c")
        )
        self.unknown = BearerToken("d" * 40)
        self.directory = TokenDirectory(
            {self.token: self.actor, self.peer_token: self.peer, self.foreign_token: self.foreign}
        )
        self.task_id, self.command_id = "PRIVATE_TASK", "PRIVATE_COMMAND"
        self.created = "2030-12-01T00:00:00+00:00"
        self.quote = QuoteSnapshot(
            "10000000-0000-0000-0000-000000000001",
            self.task_id,
            0,
            "DEMO-BK-001",
            date(2030, 12, 10),
            1250,
            "USD",
            "2030-12-01T00:10:00+00:00",
            "20000000-0000-0000-0000-000000000002",
            4,
            "30000000-0000-0000-0000-000000000003",
        )
        self.intent = ActionIntent(
            "40000000-0000-0000-0000-000000000004",
            self.task_id,
            self.actor.scope_id,
            self.actor.actor_id,
            0,
            self.quote,
            "50000000-0000-0000-0000-000000000005",
            "60000000-0000-0000-0000-000000000006",
            "70000000-0000-0000-0000-000000000007",
            self.created,
        )
        self.case = CaseSnapshot(
            self.task_id,
            self.actor.scope_id,
            self.actor.actor_id,
            0,
            BookingChange(self.quote.booking_reference, self.quote.new_check_in, True),
            self.quote,
            True,
            self.intent,
            self.created,
            self.created,
            self.quote.case_id,
        )
        self.effect = EffectSnapshot(
            self.intent, EffectState.CANCELLED, 1, 0, 0, None, None, self.created
        )
        self.receipt = CancellationReceipt(
            "80000000-0000-0000-0000-000000000008",
            self.task_id,
            self.quote.case_id,
            self.command_id,
            CancelReason.USER_REQUESTED,
            CancellationDisposition.BEFORE_DISPATCH,
            self.created,
            True,
        )
        outcome = BusinessOutcome(
            self.task_id,
            self.quote.case_id,
            self.actor.scope_id,
            self.intent.intent_id,
            self.intent.effect_id,
            EffectState.CANCELLED,
            None,
            None,
            CancellationDisposition.BEFORE_DISPATCH,
            self.created,
        )
        self.completion = CompletionEvent(
            "90000000-0000-0000-0000-000000000009", outcome, self.created
        )
        self.delivery = DeliverySnapshot(
            self.completion, None, DeliveryState.PENDING, 0, 0, self.created, None, self.created
        )
        self.cases = create_autospec(CaseAuthorityPort, instance=True, spec_set=True)
        self.lifecycle = create_autospec(LifecyclePort, instance=True, spec_set=True)
        self.effects = create_autospec(EffectViewPort, instance=True, spec_set=True)
        self.cases.get.return_value = self.case
        self.effects.cancel.return_value = self.receipt
        self.effects.get.return_value = self.effect
        self.effects.completion.return_value = self.completion
        self.effects.delivery.return_value = self.delivery
        self.service = ScopedCaseService(
            self.directory, self.cases, self.lifecycle, effects=self.effects
        )

    def operations(self, service=None, token=None):
        service = self.service if service is None else service
        token = self.token if token is None else token
        base = {"token": token, "task_id": self.task_id}
        return {
            "cancel": (
                service.cancel,
                base | {"command_id": self.command_id},
                self.effects.cancel,
                self.receipt,
            ),
            "effect": (service.get_effect, base, self.effects.get, self.effect),
            "completion": (service.get_completion, base, self.effects.completion, self.completion),
            "delivery": (service.get_delivery, base, self.effects.delivery, self.delivery),
        }

    def samples(self, service=None):
        service = self.service if service is None else service
        return [
            sample
            for family in text_string_to_metric_families(service.telemetry.render().decode())
            for sample in family.samples
        ]

    def counter(self, operation, outcome, service=None):
        return sum(
            sample.value
            for sample in self.samples(service)
            if sample.name == "continuity_case_operations_total"
            and sample.labels == {"operation": operation, "outcome": outcome}
        )

    def reset_backends(self):
        self.cases.reset_mock()
        self.lifecycle.reset_mock()
        self.effects.reset_mock()

    def test_every_operation_authenticates_before_accessing_any_backend(self):
        for invalid in (self.unknown, "a" * 40, False):
            for operation, (method, arguments, _, _) in self.operations().items():
                arguments = arguments | {"token": invalid}
                with (
                    self.subTest(operation=operation, token_kind=type(invalid).__name__),
                    self.assertLogs("continuity_lab.authorization", level="WARNING"),
                    self.assertRaises(AuthenticationFailed),
                ):
                    method(**arguments)
                self.assertEqual(self.cases.mock_calls, [])
                self.assertEqual(self.effects.mock_calls, [])
                self.assertEqual(self.lifecycle.mock_calls, [])
        for operation in self.operations():
            self.assertEqual(self.counter(operation, "rejected"), 3)
            self.assertEqual(self.counter(operation, "success"), 0)

    def test_each_operation_derives_its_actor_or_scope_from_trusted_credentials(self):
        for operation, (method, arguments, backend, expected) in self.operations().items():
            self.reset_backends()
            with self.subTest(operation=operation):
                self.assertIs(method(**arguments), expected)
                if operation == "effect":
                    self.cases.get.assert_called_once_with(actor=self.actor, task_id=self.task_id)
                    backend.assert_called_once_with(
                        scope_id=self.actor.scope_id, task_id=self.task_id
                    )
                elif operation == "cancel":
                    backend.assert_called_once_with(
                        actor=self.actor,
                        task_id=self.task_id,
                        command_id=self.command_id,
                        reason=CancelReason.USER_REQUESTED,
                    )
                else:
                    backend.assert_called_once_with(actor=self.actor, task_id=self.task_id)
                self.assertEqual(self.lifecycle.mock_calls, [])
                self.assertEqual(self.counter(operation, "success"), 1)

    def test_public_methods_reject_actor_scope_and_authority_overrides(self):
        for operation, (method, arguments, _, _) in self.operations().items():
            for name, value in (
                ("actor", self.foreign),
                ("scope_id", self.foreign.scope_id),
                ("supplier_id", self.quote.supplier_id),
                ("force", True),
            ):
                with self.subTest(operation=operation, field=name), self.assertRaises(TypeError):
                    method(**arguments, **{name: value})
        self.assertEqual(self.cases.mock_calls, [])
        self.assertEqual(self.effects.mock_calls, [])
        self.assertEqual(self.lifecycle.mock_calls, [])

    def test_same_scope_other_actor_and_other_scope_remain_rejected_by_owner_authority(self):
        def owned_case(*, actor, task_id):
            if actor != self.actor or task_id != self.task_id:
                raise ExecutionNotFound("Execution is unavailable")
            return self.case

        def owned_effect(*, actor, task_id, **_):
            owned_case(actor=actor, task_id=task_id)
            return self.receipt

        self.cases.get.side_effect = owned_case
        for name in ("cancel", "completion", "delivery"):
            getattr(self.effects, name).side_effect = owned_effect
        for token, actor in ((self.peer_token, self.peer), (self.foreign_token, self.foreign)):
            for operation, (method, arguments, backend, _) in self.operations(token=token).items():
                self.reset_backends()
                with (
                    self.subTest(
                        operation=operation, same_scope=actor.scope_id == self.actor.scope_id
                    ),
                    self.assertRaises(ExecutionNotFound),
                ):
                    method(**arguments)
                if operation == "effect":
                    self.cases.get.assert_called_once_with(actor=actor, task_id=self.task_id)
                    self.effects.get.assert_not_called()
                else:
                    self.assertIs(backend.call_args.kwargs["actor"], actor)
        self.cases.get.side_effect = None
        for name in ("cancel", "completion", "delivery"):
            getattr(self.effects, name).side_effect = None
        for operation, (method, arguments, _, expected) in self.operations().items():
            with self.subTest(valid_progress=operation):
                self.assertIs(method(**arguments), expected)

    def test_effect_inspection_checks_case_actor_before_scope_only_backend_read(self):
        original = ExecutionNotFound("SECRET_SENTINEL")
        self.cases.get.side_effect = original
        with self.assertRaises(ExecutionNotFound) as caught:
            self.service.get_effect(token=self.token, task_id=self.task_id)
        self.assertIs(caught.exception, original)
        self.effects.get.assert_not_called()
        self.assertEqual(self.counter("effect", "rejected"), 1)

    def test_missing_effect_configuration_is_explicitly_unsupported_after_authentication(self):
        service = replace(self.service, effects=None)
        for operation, (method, arguments, _, _) in self.operations(service=service).items():
            with self.subTest(operation=operation), self.assertRaises(UnsupportedOperation):
                method(**arguments)
            self.assertEqual(self.counter(operation, "rejected", service), 1)
            with (
                self.assertLogs("continuity_lab.authorization", level="WARNING"),
                self.assertRaises(AuthenticationFailed),
            ):
                method(**(arguments | {"token": self.unknown}))
            self.assertEqual(self.counter(operation, "rejected", service), 2)
        self.assertEqual(self.effects.mock_calls, [])
        self.assertEqual(self.lifecycle.mock_calls, [])

    def test_absent_effect_completion_and_delivery_are_successful_reads(self):
        for operation, (method, arguments, backend, _) in self.operations().items():
            if operation == "cancel":
                continue
            backend.return_value = None
            with self.subTest(operation=operation):
                self.assertIsNone(method(**arguments))
                self.assertEqual(self.counter(operation, "success"), 1)

    def test_cancellation_replay_and_explicit_reason_are_forwarded_without_new_authority(self):
        first = self.service.cancel(
            token=self.token,
            task_id=self.task_id,
            command_id=self.command_id,
            reason=CancelReason.USER_REQUESTED,
        )
        replay = replace(self.receipt, created=False)
        self.effects.cancel.return_value = replay
        second = self.service.cancel(
            token=self.token, task_id=self.task_id, command_id=self.command_id
        )
        self.assertIs(first, self.receipt)
        self.assertIs(second, replay)
        self.assertEqual(self.effects.cancel.call_count, 2)
        self.assertEqual(
            self.effects.cancel.call_args.kwargs,
            {
                "actor": self.actor,
                "task_id": self.task_id,
                "command_id": self.command_id,
                "reason": CancelReason.USER_REQUESTED,
            },
        )
        self.assertEqual(self.counter("cancel", "success"), 2)

    def test_new_operations_preserve_original_failures_and_emit_only_finite_safe_labels(self):
        rendered = []
        for operation, (method, arguments, backend, expected) in self.operations().items():
            with (
                self.subTest(operation=operation),
                self.assertLogs("continuity_lab.case_service", level="INFO") as logs,
            ):
                self.assertIs(method(**arguments), expected)
                for original, expected_outcome, expected_code in (
                    (ExecutionNotFound("SECRET_SENTINEL"), "rejected", "execution_not_found"),
                    (StorageUnavailable("SECRET_SENTINEL"), "failed", "storage_unavailable"),
                    (PrivateEffectFailure(), "failed", "unexpected_error"),
                ):
                    backend.side_effect = original
                    with self.assertRaises(type(original)) as caught:
                        method(**arguments)
                    self.assertIs(caught.exception, original)
                    self.assertEqual(logs.records[-1].outcome, expected_outcome)
                    self.assertEqual(logs.records[-1].code, expected_code)
                backend.side_effect = None
            rendered.extend(_SafeFormatter().format(record) for record in logs.records)
            self.assertEqual(self.counter(operation, "success"), 1)
            self.assertEqual(self.counter(operation, "rejected"), 1)
            self.assertEqual(self.counter(operation, "failed"), 2)
        for text in rendered:
            record = json.loads(text)
            self.assertEqual(
                set(record),
                {"service", "timestamp", "severity", "event", "code", "operation", "outcome"},
            )
            self.assertIn(record["operation"], {"cancel", "effect", "completion", "delivery"})
        for sample in self.samples():
            self.assertLessEqual(set(sample.labels), {"operation", "outcome", "le"})
            self.assertIn(sample.labels["operation"], OPERATIONS)
            self.assertIn(sample.labels["outcome"], OUTCOMES)
        diagnostics = (
            "".join(rendered) + self.service.telemetry.render().decode() + repr(self.service)
        )
        for private in (
            self.token.value,
            self.task_id,
            self.command_id,
            self.actor.actor_id,
            self.actor.scope_id,
            self.quote.quote_id,
            self.quote.case_id,
            self.quote.supplier_id,
            self.intent.effect_id,
            "SECRET_SENTINEL",
            "Traceback",
        ):
            self.assertNotIn(private, diagnostics)

    def test_logging_outage_cannot_replace_return_values_or_original_domain_failures(self):
        for operation, (method, arguments, backend, expected) in self.operations().items():
            with (
                self.subTest(operation=operation),
                patch(
                    "continuity_lab.case_telemetry.LOGGER.log", side_effect=PrivateEffectFailure()
                ),
            ):
                self.assertIs(method(**arguments), expected)
                original = ExecutionNotFound("SECRET_SENTINEL")
                backend.side_effect = original
                with self.assertRaises(ExecutionNotFound) as caught:
                    method(**arguments)
                self.assertIs(caught.exception, original)
                backend.side_effect = None
