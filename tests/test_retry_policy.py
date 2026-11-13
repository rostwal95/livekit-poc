"""Pure controlled-clock retry policy, without remote providers or real sleeps."""

import unittest
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

from continuity_lab.retry_policy import (
    FailureClass,
    RetryDisposition,
    RetryError,
    RetryPolicy,
    decide_retry,
    parse_policy,
)

NOW = datetime(2030, 1, 1, tzinfo=UTC)


class RetryPolicyTests(unittest.TestCase):
    def decision(self, failure=FailureClass.TRANSIENT, attempt_no=1, policy=None, **overrides):
        values = {"now": NOW, "deadline": NOW + timedelta(minutes=5)}
        values.update(overrides)
        return decide_retry(
            failure,
            attempt_no=attempt_no,
            policy=RetryPolicy() if policy is None else policy,
            **values,
        )

    def test_exponential_backoff_is_capped_and_never_sleeps(self):
        policy = RetryPolicy(6, 2, 5)
        for number, seconds in ((1, 2), (2, 4), (3, 5), (4, 5), (5, 5)):
            value = self.decision(attempt_no=number, policy=policy)
            self.assertEqual(value.disposition, RetryDisposition.RETRY_WAIT)
            self.assertEqual(value.next_attempt_at, NOW + timedelta(seconds=seconds))
        exhausted = self.decision(attempt_no=6, policy=policy)
        self.assertEqual(
            (exhausted.disposition, exhausted.error_code),
            (RetryDisposition.FAILED, RetryError.RETRY_EXHAUSTED),
        )
        self.assertIsNone(exhausted.next_attempt_at)

    def test_permanent_failure_never_retries(self):
        value = self.decision(FailureClass.PERMANENT)
        self.assertEqual(
            (value.disposition, value.error_code, value.next_attempt_at),
            (RetryDisposition.FAILED, RetryError.PERMANENT_FAILURE, None),
        )

    def test_ambiguity_remains_uncertain_even_after_deadline_or_budget(self):
        value = self.decision(
            FailureClass.AMBIGUOUS, attempt_no=100, deadline=NOW - timedelta(days=1)
        )
        self.assertEqual(
            (value.disposition, value.error_code, value.next_attempt_at),
            (RetryDisposition.UNCERTAIN, RetryError.AMBIGUOUS_OUTCOME, None),
        )

    def test_deadline_and_exact_next_eligibility_boundary_prevent_retry(self):
        for delta in (-1, 0, 1):
            value = self.decision(deadline=NOW + timedelta(seconds=delta))
            self.assertEqual(value.error_code, RetryError.DEADLINE_EXPIRED)
            self.assertEqual(value.disposition, RetryDisposition.FAILED)
            self.assertIsNone(value.next_attempt_at)
        self.assertEqual(
            self.decision(deadline=NOW + timedelta(seconds=2)).disposition,
            RetryDisposition.RETRY_WAIT,
        )

    def test_aware_offset_clock_is_compared_as_absolute_utc(self):
        shifted = NOW.astimezone(timezone(timedelta(hours=5, minutes=30)))
        self.assertEqual(self.decision(now=shifted), self.decision())

    def test_policy_is_immutable_and_strict_canonical_roundtrip(self):
        policy = RetryPolicy(4, 2, 9)
        self.assertEqual(parse_policy(policy.canonical()), policy)
        with self.assertRaises(FrozenInstanceError):
            policy.max_attempts = 10
        for value in (
            "{}",
            '{"max_attempts":3}',
            policy.canonical() + " ",
            "[]",
            '{"max_attempts":true,"initial_delay_seconds":1,"max_delay_seconds":30}',
        ):
            with self.assertRaises(ValueError):
                parse_policy(value)

    def test_invalid_attempts_delays_and_untyped_categories_are_rejected(self):
        for value in (True, 0, 101, 1.5, "3"):
            with self.assertRaises(ValueError):
                RetryPolicy(max_attempts=value)
            with self.assertRaises(ValueError):
                self.decision(attempt_no=value)
        for initial, maximum in ((0, 1), (2, 1), (1, 3601), (True, 3), (1, 3.5)):
            with self.assertRaises(ValueError):
                RetryPolicy(initial_delay_seconds=initial, max_delay_seconds=maximum)
        with self.assertRaises(ValueError):
            self.decision("transient")
        with self.assertRaises(ValueError):
            self.decision(now=datetime(2030, 1, 1))

    def test_near_datetime_limit_rejects_unreachable_retry_without_overflow(self):
        deadline = datetime.max.replace(tzinfo=UTC)
        now = deadline - timedelta(microseconds=1)
        value = self.decision(now=now, deadline=deadline)
        self.assertEqual(value.disposition, RetryDisposition.FAILED)
        self.assertEqual(value.error_code, RetryError.DEADLINE_EXPIRED)
