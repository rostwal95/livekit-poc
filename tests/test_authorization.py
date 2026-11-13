"""Real inquiry-store contracts for the trusted local actor/scope boundary."""

import hashlib
import inspect
import unittest
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from continuity_lab.authorization import (
    AuthenticatedActor,
    AuthenticationFailed,
    BearerToken,
    ScopedInquiryService,
    TokenDirectory,
)
from continuity_lab.execution import ExecutionStore
from continuity_lab.execution_models import ExecutionNotFound, InquiryResult, UnsupportedOperation
from continuity_lab.migrations import migrate
from continuity_lab.models import BookingChange, IdempotencyConflict


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        directory = Path(self.temporary.name)
        self.database = directory / "inquiry.sqlite3"
        migrate(self.database, directory / "before.sqlite3")
        self.store = ExecutionStore(self.database)
        self.actor_a = AuthenticatedActor("actor-a", "account-a")
        self.actor_b = AuthenticatedActor("actor-b", "account-b")
        self.token_a = BearerToken("SYNTHETIC_A_" + "a" * 40)
        self.token_b = BearerToken("SYNTHETIC_B_" + "b" * 40)
        self.unknown = BearerToken("SYNTHETIC_UNKNOWN_" + "u" * 40)
        self.registrations = {self.token_a: self.actor_a, self.token_b: self.actor_b}
        self.directory = TokenDirectory(self.registrations)
        self.service = ScopedInquiryService(self.directory, self.store)
        self.request = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)

    def submit(self, token=None, **overrides):
        return self.service.submit(
            token=self.token_a if token is None else token,
            idempotency_key="inquiry-1",
            request=overrides.pop("request", self.request),
            **overrides,
        )

    def test_submit_get_list_and_history_bind_scope_from_the_current_credential(self):
        a = self.submit().execution
        b = self.submit(self.token_b).execution
        self.assertNotEqual(a.task_id, b.task_id)
        self.assertNotEqual(a.effect_id, b.effect_id)
        self.assertEqual(a.scope_id, self.actor_a.scope_id)
        self.assertEqual(b.scope_id, self.actor_b.scope_id)
        self.assertEqual(self.service.get(token=self.token_a, task_id=a.task_id), a)
        self.assertEqual(self.service.get(token=self.token_b, task_id=b.task_id), b)
        self.assertEqual(self.service.list(token=self.token_a), (a,))
        self.assertEqual(self.service.list(token=self.token_b), (b,))
        self.assertEqual(self.service.history(token=self.token_a, task_id=a.task_id), ())
        with self.assertRaises(ExecutionNotFound):
            self.service.get(token=self.token_b, task_id=a.task_id)

    def test_idempotent_replay_and_conflict_preserve_original_scope_and_effect(self):
        a = self.submit().execution
        self.assertEqual(self.submit().execution, a)
        changed = BookingChange("DEMO-BK-001", date(2030, 12, 11), True)
        with self.assertRaises(IdempotencyConflict):
            self.submit(request=changed)
        b = self.submit(self.token_b, request=changed).execution
        self.assertNotEqual(b.task_id, a.task_id)
        self.assertEqual(self.service.get(token=self.token_a, task_id=a.task_id), a)

    def test_cross_scope_and_unknown_get_history_cancel_signal_are_indistinguishable(self):
        a = self.submit().execution
        for operation in ("get", "history", "cancel", "signal"):
            failures = []
            for token, task_id in ((self.token_b, a.task_id), (self.token_a, "missing")):
                with self.subTest(operation=operation, same_scope=token == self.token_a):
                    with self.assertRaises(ExecutionNotFound) as caught:
                        getattr(self.service, operation)(token=token, task_id=task_id)
                    failures.append(
                        (type(caught.exception), caught.exception.code, str(caught.exception))
                    )
            self.assertEqual(failures[0], failures[1])
        self.assertEqual(self.service.get(token=self.token_a, task_id=a.task_id), a)

    def test_same_scope_controls_explicitly_remain_unsupported_without_state_changes(self):
        a = self.submit().execution
        for operation in ("cancel", "signal"):
            with (
                self.subTest(operation=operation),
                self.assertRaises(UnsupportedOperation) as caught,
            ):
                getattr(self.service, operation)(token=self.token_a, task_id=a.task_id)
            self.assertEqual(caught.exception.code, "unsupported_operation")
        self.assertEqual(self.service.get(token=self.token_a, task_id=a.task_id), a)
        self.assertEqual(self.service.history(token=self.token_a, task_id=a.task_id), ())

    def test_each_method_authenticates_before_any_store_access_or_request_validation(self):
        methods = {
            "submit": {"idempotency_key": "inquiry-1", "request": {"scope_id": "account-a"}},
            "get": {"task_id": "missing"},
            "list": {"limit": 0},
            "history": {"task_id": "missing"},
            "cancel": {"task_id": "missing"},
            "signal": {"task_id": "missing"},
        }
        for operation, arguments in methods.items():
            for token in (self.unknown, None, "unwrapped_token", object()):
                with self.subTest(operation=operation, token_type=type(token).__name__):
                    with (
                        patch.object(self.store, "get") as get,
                        patch.object(self.store, "submit") as submit,
                        patch.object(self.store, "list") as listing,
                        patch.object(self.store, "attempts") as attempts,
                        self.assertRaises(AuthenticationFailed) as caught,
                    ):
                        getattr(self.service, operation)(token=token, **arguments)
                    self.assertEqual(caught.exception.code, "authentication_required")
                    get.assert_not_called()
                    submit.assert_not_called()
                    listing.assert_not_called()
                    attempts.assert_not_called()

    def test_successful_authentication_is_not_cached_for_a_later_request(self):
        row = self.submit().execution
        self.assertEqual(self.service.get(token=self.token_a, task_id=row.task_id), row)
        with self.assertRaises(AuthenticationFailed):
            self.service.get(token=self.unknown, task_id=row.task_id)
        with self.assertRaises(ExecutionNotFound):
            self.service.get(token=self.token_b, task_id=row.task_id)
        self.assertEqual(self.service.get(token=self.token_a, task_id=row.task_id), row)

    def test_scope_actor_tenant_and_account_override_parameters_are_rejected(self):
        row = self.submit().execution
        methods = {
            "submit": {"idempotency_key": "another-key", "request": self.request},
            "get": {"task_id": row.task_id},
            "list": {},
            "history": {"task_id": row.task_id},
            "cancel": {"task_id": row.task_id},
            "signal": {"task_id": row.task_id},
        }
        for operation, arguments in methods.items():
            signature = inspect.signature(getattr(self.service, operation))
            self.assertNotIn("scope_id", signature.parameters)
            self.assertFalse(
                any(
                    parameter.kind == inspect.Parameter.VAR_KEYWORD
                    for parameter in signature.parameters.values()
                )
            )
            for field in ("scope_id", "actor_id", "tenant_id", "account_id"):
                with self.subTest(operation=operation, field=field), self.assertRaises(TypeError):
                    getattr(self.service, operation)(
                        token=self.token_a, **arguments, **{field: "account-b"}
                    )
        self.assertEqual(self.service.list(token=self.token_a), (row,))
        self.assertEqual(self.service.list(token=self.token_b), ())

    def test_untrusted_request_mapping_cannot_supply_scope_or_mutation_authority(self):
        for body in (
            {**self.request.payload(), "scope_id": "account-b"},
            {**self.request.payload(), "actor_id": "actor-b"},
            {**self.request.payload(), "operation": "booking.apply"},
        ):
            with self.subTest(fields=set(body)), self.assertRaisesRegex(ValueError, "validated"):
                self.submit(request=body)
        with self.assertRaises(UnsupportedOperation):
            self.submit(operation="booking.apply")
        self.assertEqual(self.service.list(token=self.token_a), ())
        self.assertEqual(self.service.list(token=self.token_b), ())

    def test_real_attempt_history_retains_scope_and_investigation_only_consent(self):
        row = self.submit().execution
        started = self.store.start_attempt(
            scope_id=row.scope_id, task_id=row.task_id, expected_version=0
        )
        result = InquiryResult(self.request.booking_reference, self.request.new_check_in, True)
        completed = self.store.finish_attempt(
            scope_id=row.scope_id,
            task_id=row.task_id,
            attempt_id=started.attempt.attempt_id,
            expected_version=1,
            result=result,
        )
        history = self.service.history(token=self.token_a, task_id=row.task_id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].attempt_id, started.attempt.attempt_id)
        self.assertEqual(history[0].status, "succeeded")
        self.assertEqual(self.service.get(token=self.token_a, task_id=row.task_id), completed)
        with self.assertRaises(ExecutionNotFound):
            self.service.history(token=self.token_b, task_id=row.task_id)
        self.assertEqual(completed.operation, "booking.inquire")
        self.assertEqual(completed.request.payload(), self.request.payload())

    def test_directory_keeps_only_hashes_and_is_independent_of_original_registrations(self):
        self.assertEqual(
            self.directory._entries,
            (
                (hashlib.sha256(self.token_a.value.encode()).digest(), self.actor_a),
                (hashlib.sha256(self.token_b.value.encode()).digest(), self.actor_b),
            ),
        )
        self.registrations.clear()
        self.registrations[self.unknown] = self.actor_a
        self.assertEqual(self.directory.authenticate(self.token_a), self.actor_a)
        with self.assertRaises(AuthenticationFailed):
            self.directory.authenticate(self.unknown)
        for value in (self.token_a, self.token_b, self.directory, self.service):
            self.assertNotIn(self.token_a.value, repr(value))
            self.assertNotIn(self.token_b.value, repr(value))
            self.assertNotIn(self.token_a.value, str(value))

    def test_actor_token_directory_and_service_bindings_are_immutable(self):
        fields = [
            (self.actor_a, "scope_id", "account-b"),
            (self.token_a, "value", self.token_b.value),
            (self.directory, "_entries", ()),
            (self.service, "directory", TokenDirectory({self.unknown: self.actor_b})),
        ]
        for target, name, value in fields:
            with self.subTest(target=type(target).__name__), self.assertRaises(FrozenInstanceError):
                setattr(target, name, value)
        self.assertEqual(self.directory.authenticate(self.token_a).scope_id, "account-a")

    def test_multiple_trusted_actors_can_share_the_same_account_scope(self):
        second = BearerToken("SYNTHETIC_TEAMMATE_" + "t" * 40)
        service = ScopedInquiryService(
            TokenDirectory(
                {self.token_a: self.actor_a, second: AuthenticatedActor("teammate", "account-a")}
            ),
            self.store,
        )
        row = service.submit(
            token=self.token_a, idempotency_key="one", request=self.request
        ).execution
        self.assertEqual(service.get(token=second, task_id=row.task_id), row)
        self.assertEqual(service.list(token=second), (row,))

    def test_list_limit_stays_bounded_by_the_actual_store(self):
        self.submit()
        for limit in (0, 1001, True, "1"):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.service.list(token=self.token_a, limit=limit)
        self.assertEqual(len(self.service.list(token=self.token_a, limit=1)), 1)

    def test_token_validation_has_one_safe_code_and_never_echoes_bad_values(self):
        failures = []
        for value in (
            "short",
            "x" * 129,
            "TOKEN_SENTINEL_" + "x" * 32 + "\n",
            "x" * 40 + "$()",
            None,
        ):
            with self.subTest(kind=type(value).__name__):
                with self.assertRaises(AuthenticationFailed) as caught:
                    BearerToken(value)
                failures.append((caught.exception.code, str(caught.exception)))
                if isinstance(value, str):
                    self.assertNotIn(value, str(caught.exception))
        with self.assertRaises(AuthenticationFailed) as caught:
            self.directory.authenticate(self.unknown)
        failures.append((caught.exception.code, str(caught.exception)))
        self.assertEqual(len(set(failures)), 1)

    def test_invalid_trusted_config_fails_without_echoing_identities_or_credentials(self):
        for actor, scope in (
            ("", "scope"),
            ("actor", ""),
            (" actor", "scope"),
            ("actor", "scope\nother"),
            ("a" * 129, "scope"),
        ):
            with self.subTest(actor_length=len(actor)), self.assertRaises(ValueError) as caught:
                AuthenticatedActor(actor, scope)
            self.assertNotIn("scope\nother", str(caught.exception))
        for registrations in ({}, {self.token_a.value: self.actor_a}, {self.token_a: "actor"}):
            with self.subTest(size=len(registrations)), self.assertRaises(ValueError) as caught:
                TokenDirectory(registrations)
            self.assertNotIn(self.token_a.value, str(caught.exception))
        oversized = {
            BearerToken(f"TOKEN_{index:04d}_" + "x" * 32): self.actor_a for index in range(257)
        }
        with self.assertRaisesRegex(ValueError, "1 to 256"):
            TokenDirectory(oversized)

    def test_failed_authentication_log_has_fixed_fields_and_no_token_or_principal(self):
        with (
            self.assertLogs("continuity_lab.authorization", level="WARNING") as logs,
            self.assertRaises(AuthenticationFailed),
        ):
            self.directory.authenticate(self.unknown)
        [record] = logs.records
        self.assertEqual(record.getMessage(), "authentication_rejected")
        self.assertEqual(record.event, "authentication_rejected")
        self.assertEqual(record.code, "authentication_required")
        text = repr(record.__dict__)
        for value in (
            self.token_a.value,
            self.token_b.value,
            self.unknown.value,
            self.actor_a.actor_id,
            self.actor_a.scope_id,
        ):
            self.assertNotIn(value, text)


if __name__ == "__main__":
    unittest.main()
