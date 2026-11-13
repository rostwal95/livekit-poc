"""Trusted case boundary, real observations and retained async I/O ownership."""

import asyncio
import json
import threading
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import create_autospec, patch

from prometheus_client.parser import text_string_to_metric_families

from continuity_lab.authorization import (
    AuthenticatedActor,
    AuthenticationFailed,
    BearerToken,
    TokenDirectory,
)
from continuity_lab.case_models import (
    ActionIntent,
    CaseAuthorityPort,
    CaseSnapshot,
    Confirmation,
    InvalidConfirmation,
    QuoteSnapshot,
    parse_confirmation,
)
from continuity_lab.case_service import AsyncCaseService, LifecyclePort, ScopedCaseService
from continuity_lab.case_telemetry import OPERATIONS, OUTCOMES, CaseTelemetry
from continuity_lab.execution_cli import _SafeFormatter
from continuity_lab.execution_models import (
    ExecutionCapacityExceeded,
    ExecutionError,
    ExecutionNotFound,
    ExecutionPortClosed,
    StorageUnavailable,
)
from continuity_lab.lifecycle_models import (
    LifecycleSnapshot,
    LifecycleState,
    SignalReceipt,
    WaitAdvance,
    WaitSnapshot,
    WaitState,
)
from continuity_lab.models import BookingChange
from continuity_lab.retry_policy import RetryPolicy


class PrivateFailure(RuntimeError):
    def __str__(self):
        raise AssertionError("Private exception text must never be formatted")

    def __repr__(self):
        raise AssertionError("Private exception representation must never be formatted")


def fixture():
    actor = AuthenticatedActor("PRIVATE_ACTOR", "PRIVATE_SCOPE")
    token, unknown = BearerToken("a" * 40), BearerToken("b" * 40)
    task_id = "PRIVATE_TASK"
    created = "2030-12-01T12:00:00+00:00"
    request = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)
    quote = QuoteSnapshot(
        "11111111-1111-4111-8111-111111111111",
        task_id,
        0,
        request.booking_reference,
        request.new_check_in,
        2500,
        "USD",
        "2030-12-01T13:00:00+00:00",
    )
    confirmation = Confirmation(quote, True)
    intent = ActionIntent(
        "22222222-2222-4222-8222-222222222222",
        task_id,
        actor.scope_id,
        actor.actor_id,
        0,
        quote,
        "33333333-3333-4333-8333-333333333333",
        "44444444-4444-4444-8444-444444444444",
        "55555555-5555-4555-8555-555555555555",
        created,
    )
    case = CaseSnapshot(
        task_id,
        actor.scope_id,
        actor.actor_id,
        0,
        request,
        quote,
        False,
        None,
        created,
        created,
        "4d96daa1-601c-48a3-8e23-5fb344af892f",
    )
    lifecycle = LifecycleSnapshot(
        task_id,
        LifecycleState.WAITING,
        RetryPolicy(),
        quote.expires_at,
        None,
        0,
        None,
        None,
        created,
    )
    wait = WaitSnapshot(
        "private-wait", task_id, quote, quote.expires_at, WaitState.PENDING, created, None
    )
    return SimpleNamespace(
        actor=actor,
        token=token,
        unknown=unknown,
        task_id=task_id,
        created=created,
        request=request,
        quote=quote,
        confirmation=confirmation,
        intent=intent,
        case=case,
        lifecycle=lifecycle,
        wait=wait,
        directory=TokenDirectory({token: actor}),
    )


def samples(telemetry):
    return [
        sample
        for family in text_string_to_metric_families(telemetry.render().decode())
        for sample in family.samples
    ]


def counter(telemetry, operation, outcome):
    return sum(
        sample.value
        for sample in samples(telemetry)
        if sample.name == "continuity_case_operations_total"
        and sample.labels == {"operation": operation, "outcome": outcome}
    )


class CaseServiceTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture()
        self.cases = create_autospec(CaseAuthorityPort, instance=True, spec_set=True)
        self.lifecycle = create_autospec(LifecyclePort, instance=True, spec_set=True)
        for name in ("enroll", "get", "revise"):
            getattr(self.cases, name).return_value = self.f.case
        self.cases.commit_intent.return_value = self.f.intent
        self.lifecycle.get.return_value = self.f.lifecycle
        self.lifecycle.arm_wait.return_value = self.f.wait
        self.lifecycle.signal.return_value = SignalReceipt(
            "private-signal", self.f.task_id, "private-event", True, None
        )
        self.lifecycle.advance.return_value = WaitAdvance(self.f.lifecycle, self.f.intent)
        self.lifecycle.waits.return_value = (self.f.wait,)
        self.service = ScopedCaseService(self.f.directory, self.cases, self.lifecycle)

    def calls(self, token):
        return {
            "enroll": (self.service.enroll, {"token": token, "task_id": self.f.task_id}),
            "get": (self.service.get, {"token": token, "task_id": self.f.task_id}),
            "revise": (
                self.service.revise,
                {
                    "token": token,
                    "task_id": self.f.task_id,
                    "expected_revision": 0,
                    "request": self.f.request,
                },
            ),
            "confirm": (
                self.service.confirm,
                {
                    "token": token,
                    "confirmation": self.f.confirmation,
                    "command_id": "private-command",
                },
            ),
            "arm_wait": (
                self.service.arm_wait,
                {
                    "token": token,
                    "task_id": self.f.task_id,
                    "wait_id": "private-wait",
                    "quote": self.f.quote,
                    "deadline": datetime(2030, 12, 1, 13, tzinfo=UTC),
                },
            ),
            "signal": (
                self.service.signal,
                {"token": token, "event_id": "private-event", "confirmation": self.f.confirmation},
            ),
            "advance": (self.service.advance, {"token": token, "task_id": self.f.task_id}),
            "waits": (self.service.waits, {"token": token, "task_id": self.f.task_id}),
            "lifecycle": (self.service.get_lifecycle, {"token": token, "task_id": self.f.task_id}),
        }

    def test_all_operations_authenticate_before_any_port_access(self):
        for operation, (method, arguments) in self.calls(self.f.unknown).items():
            with self.subTest(operation=operation), self.assertRaises(AuthenticationFailed):
                method(**arguments)
            self.assertEqual(self.cases.mock_calls, [])
            self.assertEqual(self.lifecycle.mock_calls, [])
            self.assertEqual(counter(self.service.telemetry, operation, "rejected"), 1)

    def test_all_operations_derive_actor_and_scope_from_trusted_directory(self):
        for operation, (method, arguments) in self.calls(self.f.token).items():
            self.cases.reset_mock()
            self.lifecycle.reset_mock()
            with self.subTest(operation=operation):
                self.assertIsNotNone(method(**arguments))
                for call in self.cases.mock_calls + self.lifecycle.mock_calls:
                    if call[0] == "get" and "scope_id" in call.kwargs:
                        self.assertEqual(call.kwargs["scope_id"], self.f.actor.scope_id)
                        self.assertNotIn("actor", call.kwargs)
                    else:
                        self.assertIs(call.kwargs["actor"], self.f.actor)
                self.assertEqual(counter(self.service.telemetry, operation, "success"), 1)

    def test_public_methods_do_not_accept_actor_or_scope_override(self):
        for operation, (method, arguments) in self.calls(self.f.token).items():
            for field, value in (("scope_id", "forged-account"), ("actor", self.f.actor)):
                with self.subTest(operation=operation, field=field), self.assertRaises(TypeError):
                    method(**arguments, **{field: value})
        self.assertEqual(self.cases.mock_calls, [])
        self.assertEqual(self.lifecycle.mock_calls, [])

    def test_lifecycle_inspection_checks_case_actor_before_scope_only_read(self):
        original = ExecutionNotFound("Execution is unavailable")
        self.cases.get.side_effect = original
        with self.assertRaises(ExecutionNotFound) as caught:
            self.service.get_lifecycle(token=self.f.token, task_id=self.f.task_id)
        self.assertIs(caught.exception, original)
        self.cases.get.assert_called_once_with(actor=self.f.actor, task_id=self.f.task_id)
        self.lifecycle.get.assert_not_called()

    def test_model_summary_or_extra_scope_cannot_become_confirmation(self):
        for payload in (
            {"summary": "The user agreed"},
            {**self.f.confirmation.payload(), "scope_id": "forged-account"},
            {**self.f.confirmation.payload(), "explicit": False},
        ):
            with (
                self.subTest(payload_fields=sorted(payload)),
                self.assertRaises(InvalidConfirmation),
            ):
                parse_confirmation(payload)

        def commit(*, actor, confirmation, command_id):
            if type(confirmation) is not Confirmation:
                raise InvalidConfirmation("An exact explicit confirmation is required")
            return self.f.intent

        self.cases.commit_intent.side_effect = commit
        with self.assertRaises(InvalidConfirmation):
            self.service.confirm(
                token=self.f.token,
                confirmation={"summary": "The user agreed"},
                command_id="private-command",
            )
        self.cases.commit_intent.assert_called_once_with(
            actor=self.f.actor,
            confirmation={"summary": "The user agreed"},
            command_id="private-command",
        )
        result = self.service.confirm(
            token=self.f.token, confirmation=self.f.confirmation, command_id="valid-command"
        )
        self.assertIs(result, self.f.intent)


class CaseTelemetryTests(unittest.TestCase):
    def test_real_counter_and_histogram_observe_result_duration_and_failure_classes(self):
        telemetry = CaseTelemetry()
        result = object()
        with patch("continuity_lab.case_telemetry.time.monotonic", side_effect=[10.0, 10.25]):
            self.assertIs(telemetry.call("get", lambda value=result: value), result)
        for error in (
            InvalidConfirmation("SECRET_SENTINEL"),
            StorageUnavailable("SECRET_SENTINEL"),
        ):
            with self.assertRaises(type(error)):
                telemetry.call("confirm", lambda error=error: (_ for _ in ()).throw(error))
        self.assertEqual(counter(telemetry, "get", "success"), 1)
        self.assertEqual(counter(telemetry, "confirm", "rejected"), 1)
        self.assertEqual(counter(telemetry, "confirm", "failed"), 1)
        observed = [
            sample
            for sample in samples(telemetry)
            if sample.name == "continuity_case_operation_duration_seconds_sum"
            and sample.labels == {"operation": "get", "outcome": "success"}
        ]
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0].value, 0.25)

    def test_registries_are_isolated_and_labels_remain_finite(self):
        first, second = CaseTelemetry(), CaseTelemetry()
        self.assertIsNot(first.registry, second.registry)
        for operation in OPERATIONS:
            first.call(operation, lambda: "useful result")
        self.assertEqual(counter(second, "get", "success"), 0)
        pairs = set()
        for sample in samples(first):
            self.assertLessEqual(set(sample.labels), {"operation", "outcome", "le"})
            self.assertIn(sample.labels["operation"], OPERATIONS)
            self.assertIn(sample.labels["outcome"], OUTCOMES)
            pairs.add((sample.labels["operation"], sample.labels["outcome"]))
        self.assertEqual(pairs, {(operation, "success") for operation in OPERATIONS})

    def test_safe_formatter_excludes_tokens_id_values_and_private_exception_text(self):
        f = fixture()
        telemetry = CaseTelemetry()
        failure = PrivateFailure()
        with self.assertLogs("continuity_lab.case_service", level="INFO") as logs:
            telemetry.call("get", lambda: f.case)
            with self.assertRaises(PrivateFailure) as caught:
                telemetry.call("confirm", lambda: (_ for _ in ()).throw(failure))
        self.assertIs(caught.exception, failure)
        rendered = [_SafeFormatter().format(record) for record in logs.records]
        for raw in rendered:
            value = json.loads(raw)
            self.assertEqual(
                set(value),
                {"service", "timestamp", "severity", "event", "code", "operation", "outcome"},
            )
            self.assertEqual(value["event"], "case_operation")
        self.assertEqual(json.loads(rendered[0])["code"], "ok")
        self.assertEqual(json.loads(rendered[1])["code"], "unexpected_error")
        for private in (
            f.token.value,
            f.task_id,
            f.actor.actor_id,
            f.actor.scope_id,
            f.quote.quote_id,
            "Traceback",
            "SECRET_SENTINEL",
        ):
            self.assertNotIn(private, "".join(rendered) + telemetry.render().decode())

    def test_unhashable_exception_code_keeps_original_error_and_safe_observation(self):
        class MalformedCode(ExecutionError):
            def __init__(self):
                super().__init__("SECRET_SENTINEL")
                self.code = []

        error = MalformedCode()
        telemetry = CaseTelemetry()
        with (
            self.assertLogs("continuity_lab.case_service", level="WARNING") as logs,
            self.assertRaises(MalformedCode) as caught,
        ):
            telemetry.call("confirm", lambda: (_ for _ in ()).throw(error))
        self.assertIs(caught.exception, error)
        rendered = _SafeFormatter().format(logs.records[0])
        self.assertEqual(json.loads(rendered)["code"], "unexpected_error")
        self.assertNotIn("SECRET_SENTINEL", rendered)

    def test_counter_histogram_and_logging_outages_preserve_result_and_original_error(self):
        for boundary in ("counter", "histogram", "logger"):
            telemetry = CaseTelemetry()
            result = object()
            original = InvalidConfirmation("SECRET_SENTINEL")
            target = telemetry.operations if boundary == "counter" else telemetry.duration
            outage = (
                patch("continuity_lab.case_telemetry.LOGGER.log", side_effect=PrivateFailure())
                if boundary == "logger"
                else patch.object(target, "labels", side_effect=PrivateFailure())
            )
            with self.subTest(boundary=boundary), outage:
                self.assertIs(telemetry.call("get", lambda value=result: value), result)
                with self.assertRaises(InvalidConfirmation) as caught:
                    telemetry.call("confirm", lambda error=original: (_ for _ in ()).throw(error))
                self.assertIs(caught.exception, original)

    def test_unknown_observation_name_rejects_before_action(self):
        for operation in ("SECRET_SENTINEL", [], None):
            action = create_autospec(lambda: None)
            with self.subTest(kind=type(operation).__name__), self.assertRaises(ValueError):
                CaseTelemetry().call(operation, action)
            action.assert_not_called()


class BlockingCasePort:
    """A test-owned synchronous commit boundary; no network or database simulation claim."""

    def __init__(self, f, loop):
        self.f, self.loop = f, loop
        self.current = f.case
        self.started, self.finished = asyncio.Event(), asyncio.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.commit_calls, self.get_calls, self.active, self.maximum_active = 0, 0, 0, 0

    def enroll(self, *, actor, task_id):
        return self.get(actor=actor, task_id=task_id)

    def get(self, *, actor, task_id):
        if actor != self.f.actor or task_id != self.f.task_id:
            raise ExecutionNotFound("Execution is unavailable")
        with self.lock:
            self.get_calls += 1
            return self.current

    def revise(self, *, actor, task_id, expected_revision, request):
        return self.get(actor=actor, task_id=task_id)

    def commit_intent(self, *, actor, confirmation, command_id):
        if actor != self.f.actor:
            raise ExecutionNotFound("Execution is unavailable")
        with self.lock:
            self.commit_calls += 1
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
        self.loop.call_soon_threadsafe(self.started.set)
        try:
            if not self.release.wait(timeout=2):
                raise TimeoutError("The owned test commit barrier was not released")
            with self.lock:
                self.current = replace(self.current, intent=self.f.intent)
            return self.f.intent
        finally:
            with self.lock:
                self.active -= 1
            self.loop.call_soon_threadsafe(self.finished.set)


class AsyncCaseServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = fixture()
        self.port = BlockingCasePort(self.f, asyncio.get_running_loop())
        self.service = ScopedCaseService(
            self.f.directory,
            self.port,
            create_autospec(LifecyclePort, instance=True, spec_set=True),
        )
        self.wrapper = AsyncCaseService(
            self.service, maximum=1, admission_timeout=0.03, shutdown_timeout=1
        )
        self.callers = []

    async def asyncTearDown(self):
        self.port.release.set()
        await self.wrapper.close()
        await asyncio.gather(*self.callers, return_exceptions=True)

    async def test_cancelled_confirmation_keeps_capacity_until_real_commit_and_read_progresses(
        self,
    ):
        caller = asyncio.create_task(
            self.wrapper.run(
                lambda service: service.confirm(
                    token=self.f.token,
                    confirmation=self.f.confirmation,
                    command_id="private-command",
                )
            )
        )
        self.callers.append(caller)
        await asyncio.wait_for(self.port.started.wait(), timeout=1)
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertEqual(self.wrapper.pending_count, 1)
        self.assertIsNone(self.port.current.intent)
        with self.assertRaises(ExecutionCapacityExceeded):
            await self.wrapper.run(
                lambda service: service.get(token=self.f.token, task_id=self.f.task_id)
            )
        self.assertEqual(self.port.get_calls, 0)
        self.assertEqual(self.port.active, 1)
        self.port.release.set()
        await asyncio.wait_for(self.port.finished.wait(), timeout=1)
        observed = await self.wrapper.run(
            lambda service: service.get(token=self.f.token, task_id=self.f.task_id)
        )
        self.assertEqual(observed.intent, self.f.intent)
        self.assertEqual(self.port.commit_calls, 1)
        self.assertEqual(self.port.get_calls, 1)
        self.assertEqual(self.port.maximum_active, 1)
        self.assertEqual(self.wrapper.pending_count, 0)

    async def test_close_rejects_new_operations_after_drain(self):
        await self.wrapper.close()
        with self.assertRaises(ExecutionPortClosed):
            await self.wrapper.run(
                lambda service: service.get(token=self.f.token, task_id=self.f.task_id)
            )
        self.assertEqual(self.port.get_calls, 0)
