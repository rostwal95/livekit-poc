"""Shared row readers reject corrupt scalar/outcome state without rewriting evidence."""

import json
import unittest
from dataclasses import FrozenInstanceError
from datetime import date

from continuity_lab.execution_codec import decode_attempt, decode_execution
from continuity_lab.execution_models import (
    AttemptStatus,
    ExecutionStatus,
    FailureCode,
    InvalidStoredState,
)
from continuity_lab.models import BookingChange

BIGINT = 9223372036854775807
EFFECT = "12345678-1234-4234-8234-abcdef123456"
ATTEMPT = "22345678-1234-4234-8234-abcdef123456"
INSTANT = "2030-12-01T11:00:00.000123+05:30"
FINISHED = "2030-12-01T06:00:00.000456Z"


class PrivateValue:
    def __str__(self):
        raise AssertionError("Private value must not be formatted")

    def __repr__(self):
        raise AssertionError("Private value must not be formatted")


class ExecutionCodecTests(unittest.TestCase):
    def execution(self, **changes):
        request = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)
        return {
            "task_id": "legacy-task-id",
            "scope_id": "account-a",
            "idempotency_key": "one",
            "payload": json.dumps(request.payload(), sort_keys=True, separators=(",", ":")),
            "operation": "booking.inquire",
            "status": "accepted",
            "effect_id": EFFECT,
            "version": 0,
            "created_at": INSTANT,
            "updated_at": INSTANT,
            "result_json": None,
            "error_code": None,
        } | changes

    def attempt(self, **changes):
        return {
            "attempt_id": ATTEMPT,
            "task_id": "legacy-task-id",
            "attempt_no": 1,
            "status": "started",
            "started_at": INSTANT,
            "finished_at": None,
            "error_code": None,
        } | changes

    def result_json(self, **changes):
        body = {"booking_reference": "DEMO-BK-001", "new_check_in": "2030-12-10", "available": True}
        return json.dumps(body | changes, sort_keys=True, separators=(",", ":"))

    def assert_invalid(self, decoder, row):
        with self.assertRaises(InvalidStoredState) as caught:
            decoder(row)
        self.assertEqual(caught.exception.code, "invalid_stored_state")
        expected = "Execution" if decoder is decode_execution else "Attempt"
        self.assertEqual(str(caught.exception), f"{expected} contains invalid stored state")
        self.assertNotIn("SECRET_SENTINEL", str(caught.exception))

    def test_canonical_execution_preserves_identity_request_and_original_offset_bytes(self):
        row = self.execution(version=BIGINT, updated_at=FINISHED)
        original = dict(row)
        record = decode_execution(row)
        self.assertEqual(
            (record.task_id, record.scope_id, record.idempotency_key),
            (row["task_id"], row["scope_id"], row["idempotency_key"]),
        )
        self.assertEqual((record.effect_id, record.version), (EFFECT, BIGINT))
        self.assertEqual((record.created_at, record.updated_at), (INSTANT, FINISHED))
        self.assertEqual(
            json.dumps(record.request.payload(), sort_keys=True, separators=(",", ":")),
            row["payload"],
        )
        self.assertEqual(row, original)
        with self.assertRaises(FrozenInstanceError):
            record.version = 1

    def test_valid_execution_outcomes_roundtrip_without_state_repair(self):
        for status, result, error in (
            ("accepted", None, None),
            ("running", None, None),
            ("succeeded", self.result_json(), None),
            ("failed", None, "inquiry_rejected"),
        ):
            with self.subTest(status=status):
                record = decode_execution(
                    self.execution(status=status, result_json=result, error_code=error)
                )
                self.assertEqual(record.status, ExecutionStatus(status))
                self.assertEqual(record.result is not None, status == "succeeded")
                self.assertEqual(
                    record.error_code, FailureCode(error) if error is not None else None
                )
                if record.result is not None:
                    self.assertEqual(
                        json.dumps(record.result.payload(), sort_keys=True, separators=(",", ":")),
                        result,
                    )

    def test_valid_attempt_outcomes_preserve_times_and_bigint_boundary(self):
        for status, finished, error in (
            ("started", None, None),
            ("succeeded", FINISHED, None),
            ("interrupted", FINISHED, None),
            ("failed", FINISHED, "dependency_unavailable"),
        ):
            with self.subTest(status=status):
                record = decode_attempt(
                    self.attempt(
                        status=status, finished_at=finished, error_code=error, attempt_no=BIGINT
                    )
                )
                self.assertEqual(
                    (record.attempt_id, record.task_id, record.attempt_no),
                    (ATTEMPT, "legacy-task-id", BIGINT),
                )
                self.assertEqual(
                    (record.status, record.started_at, record.finished_at),
                    (AttemptStatus(status), INSTANT, finished),
                )
                self.assertEqual(
                    record.error_code, FailureCode(error) if error is not None else None
                )
                with self.assertRaises(FrozenInstanceError):
                    record.attempt_no = 2

    def test_execution_rejects_invalid_identity_and_uuid_values(self):
        for field in ("task_id", "scope_id", "idempotency_key", "effect_id"):
            for value in (None, "", " SECRET_SENTINEL ", "x" * 129, 1, PrivateValue()):
                with self.subTest(field=field):
                    self.assert_invalid(decode_execution, self.execution(**{field: value}))
        for effect in ("SECRET_SENTINEL", EFFECT.upper(), EFFECT.replace("-", "")):
            self.assert_invalid(decode_execution, self.execution(effect_id=effect))

    def test_attempt_rejects_invalid_identity_and_uuid_values(self):
        for field in ("task_id", "attempt_id"):
            for value in (None, "", " SECRET_SENTINEL ", "x" * 129, 1, PrivateValue()):
                with self.subTest(field=field):
                    self.assert_invalid(decode_attempt, self.attempt(**{field: value}))
        for identity in ("SECRET_SENTINEL", ATTEMPT.upper(), ATTEMPT.replace("-", "")):
            self.assert_invalid(decode_attempt, self.attempt(attempt_id=identity))

    def test_integer_ranges_reject_bool_float_text_and_overflow(self):
        for value in (-1, BIGINT + 1, True, False, 1.0, "SECRET_SENTINEL", None, PrivateValue()):
            self.assert_invalid(decode_execution, self.execution(version=value))
        for value in (-1, 0, BIGINT + 1, True, False, 1.0, "SECRET_SENTINEL", None, PrivateValue()):
            self.assert_invalid(decode_attempt, self.attempt(attempt_no=value))

    def test_timestamps_are_bounded_aware_strings_for_both_readers(self):
        invalid = (
            None,
            "",
            1,
            "SECRET_SENTINEL",
            "2030-12-01T11:00:00",
            " " + INSTANT,
            INSTANT + "\n",
            "x" * 65,
            PrivateValue(),
        )
        for field in ("created_at", "updated_at"):
            for value in invalid:
                with self.subTest(field=field):
                    self.assert_invalid(decode_execution, self.execution(**{field: value}))
        for field in ("started_at", "finished_at"):
            for value in invalid:
                with self.subTest(field=field):
                    row = self.attempt(status="succeeded", finished_at=FINISHED)
                    row[field] = value
                    self.assert_invalid(decode_attempt, row)

    def test_execution_status_result_error_matrix_is_exact(self):
        for status in ("accepted", "running", "succeeded", "failed"):
            for result in (None, self.result_json()):
                for error in (None, "inquiry_rejected"):
                    valid = (status == "succeeded") == (result is not None) and (
                        status == "failed"
                    ) == (error is not None)
                    row = self.execution(status=status, result_json=result, error_code=error)
                    if valid:
                        decode_execution(row)
                    else:
                        self.assert_invalid(decode_execution, row)

    def test_attempt_status_finish_error_matrix_is_exact(self):
        for status in ("started", "succeeded", "interrupted", "failed"):
            for finished in (None, FINISHED):
                for error in (None, "inquiry_rejected"):
                    valid = (status == "started") == (finished is None) and (
                        status == "failed"
                    ) == (error is not None)
                    row = self.attempt(status=status, finished_at=finished, error_code=error)
                    if valid:
                        decode_attempt(row)
                    else:
                        self.assert_invalid(decode_attempt, row)

    def test_empty_unknown_or_private_enums_fail_closed_without_formatting(self):
        for field in ("operation", "status", "error_code"):
            for value in ("", "SECRET_SENTINEL", [], PrivateValue()):
                with self.subTest(field=field):
                    self.assert_invalid(decode_execution, self.execution(**{field: value}))
        for field in ("status", "error_code"):
            for value in ("", "SECRET_SENTINEL", [], PrivateValue()):
                with self.subTest(field=field):
                    self.assert_invalid(decode_attempt, self.attempt(**{field: value}))

    def test_request_and_result_json_must_be_canonical_exact_and_applicable(self):
        row = self.execution()
        for value in (
            None,
            [],
            "null",
            "[]",
            "SECRET_SENTINEL",
            row["payload"] + " ",
            json.dumps({"extra": 1}),
            PrivateValue(),
        ):
            self.assert_invalid(decode_execution, self.execution(payload=value))
        for value in (
            "null",
            "[]",
            "SECRET_SENTINEL",
            self.result_json() + " ",
            self.result_json(new_check_in="2030-12-11"),
            self.result_json(booking_reference="OTHER"),
            self.result_json(available=1),
            PrivateValue(),
        ):
            self.assert_invalid(
                decode_execution, self.execution(status="succeeded", result_json=value)
            )

    def test_missing_columns_fail_with_fixed_record_specific_error(self):
        for decoder, row in (
            (decode_execution, self.execution()),
            (decode_attempt, self.attempt()),
        ):
            for key in tuple(row):
                incomplete = {name: value for name, value in row.items() if name != key}
                self.assert_invalid(decoder, incomplete)


if __name__ == "__main__":
    unittest.main()
