"""Versioned mutation evidence preserves exact authority and observed truth."""

import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from continuity_lab.case_models import ActionIntent, QuoteSnapshot
from continuity_lab.effect_models import (
    BusinessOutcome,
    CancellationDisposition,
    CompletionEvent,
    DeliveryPolicy,
    EffectFailure,
    EffectState,
    MutationResult,
    parse_completion_event,
    parse_delivery_policy,
    parse_mutation_result,
    require_result_binding,
)
from continuity_lab.execution_models import InvalidStoredState, UnsupportedOperation

NOW = datetime(2030, 12, 1, tzinfo=UTC)


def example_intent():
    task = str(uuid4())
    quote = QuoteSnapshot(
        str(uuid4()),
        task,
        0,
        "DEMO-BK-001",
        date(2030, 12, 10),
        1250,
        "USD",
        (NOW + timedelta(minutes=10)).isoformat(),
        str(uuid4()),
        0,
        str(uuid4()),
    )
    return ActionIntent(
        str(uuid4()),
        task,
        "account-a",
        "actor-a",
        0,
        quote,
        str(uuid4()),
        str(uuid4()),
        str(uuid4()),
        NOW.isoformat(),
    )


def example_result(intent):
    return MutationResult(
        intent.effect_id,
        intent.intent_id,
        intent.task_id,
        intent.quote.case_id,
        intent.quote.supplier_id,
        intent.scope_id,
        intent.quote.booking_reference,
        date(2030, 12, 5),
        intent.quote.new_check_in,
        0,
        1,
        intent.quote.amount_minor,
        intent.quote.currency,
        NOW.isoformat(),
    )


def example_event():
    intent = example_intent()
    outcome = BusinessOutcome(
        intent.task_id,
        intent.quote.case_id,
        intent.scope_id,
        intent.intent_id,
        intent.effect_id,
        EffectState.SUCCEEDED,
        example_result(intent),
        None,
        CancellationDisposition.NOT_REQUESTED,
        NOW.isoformat(),
    )
    return CompletionEvent(str(uuid4()), outcome, NOW.isoformat())


class EffectModelTests(unittest.TestCase):
    def test_exact_result_and_completion_round_trip_preserve_all_authority(self):
        intent = example_intent()
        result = example_result(intent)
        self.assertEqual(parse_mutation_result(result.payload()), result)
        require_result_binding(result, intent)
        event = example_event()
        self.assertEqual(parse_completion_event(event.payload()), event)
        self.assertEqual(event.canonical(), parse_completion_event(event.payload()).canonical())

    def test_each_authority_binding_rejects_changed_external_result(self):
        intent = example_intent()
        result = example_result(intent)
        changes = (
            {"effect_id": str(uuid4())},
            {"intent_id": str(uuid4())},
            {"task_id": str(uuid4())},
            {"case_id": str(uuid4())},
            {"supplier_id": str(uuid4())},
            {"scope_id": "account-b"},
            {"booking_reference": "DEMO-BK-002"},
            {"new_check_in": date(2030, 12, 11)},
            {"previous_revision": 1, "revision": 2},
            {"amount_minor": 1251},
            {"currency": "EUR"},
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(InvalidStoredState):
                require_result_binding(replace(result, **change), intent)

    def test_legacy_intent_cannot_acquire_mutation_authority_from_result(self):
        intent = example_intent()
        legacy = replace(
            intent,
            quote=replace(
                intent.quote,
                case_id=None,
                expected_supplier_revision=None,
                supplier_id=None,
            ),
        )
        with self.assertRaises(UnsupportedOperation):
            require_result_binding(example_result(intent), legacy)

    def test_result_rejects_noncanonical_identity_revision_type_date_and_currency(self):
        result = example_result(example_intent())
        for change in (
            {"effect_id": "not-a-uuid"},
            {"previous_revision": True},
            {"revision": 2},
            {"amount_minor": -1},
            {"currency": []},
            {"created_at": "2030-12-01"},
            {"previous_check_in": "2030-12-05"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(result, **change)

    def test_unknown_fields_versions_and_boolean_versions_fail_closed(self):
        for parser, payload in (
            (parse_mutation_result, example_result(example_intent()).payload()),
            (parse_completion_event, example_event().payload()),
        ):
            for change in (
                {"future": "unsupported"},
                {"schema_version": 2},
                {"schema_version": True},
            ):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    parser(payload | change)

    def test_business_outcome_requires_truthful_terminal_classification(self):
        outcome = example_event().outcome
        for change in (
            {"state": EffectState.CLAIMED},
            {"result": None},
            {"error_code": EffectFailure.AMBIGUOUS_OUTCOME},
            {"cancellation": "not_requested"},
            {"task_id": "different-task"},
            {"intent_id": None},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(outcome, **change)
        with self.assertRaises(ValueError):
            replace(outcome, state=EffectState.CANCELLED, result=None)
        cancelled = replace(
            outcome,
            state=EffectState.CANCELLED,
            result=None,
            cancellation=CancellationDisposition.BEFORE_DISPATCH,
        )
        self.assertEqual(
            parse_completion_event(replace(example_event(), outcome=cancelled).payload()).outcome,
            cancelled,
        )
        uncertain = replace(
            outcome,
            state=EffectState.UNCERTAIN,
            result=None,
            error_code=EffectFailure.AMBIGUOUS_OUTCOME,
        )
        self.assertEqual(uncertain.state, EffectState.UNCERTAIN)

    def test_completion_timestamp_and_retry_policy_are_bounded(self):
        event = example_event()
        with self.assertRaises(ValueError):
            replace(event, created_at=(NOW + timedelta(seconds=1)).isoformat())
        policy = DeliveryPolicy(8, 1, 30)
        self.assertEqual(parse_delivery_policy(policy.payload()), policy)
        for args in (
            (True, 1, 30),
            (0, 1, 30),
            (101, 1, 30),
            (8, 0, 30),
            (8, 30, 1),
            (8, 1, 3601),
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                DeliveryPolicy(*args)
