"""Retained startup/cleanup and strict returning-result wire regressions; no live services."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import copy
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

from continuity_lab.delivery_api import DeliveryIntent, DeliveryReceipt
from continuity_lab.work_api import WorkScope
from delegation_reliability import DelegationRunError, FixedPolicyRunner
from delegation_reliability.contracts import EvidenceRef, identifier
from delegation_reliability.security import EvidenceRecord

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "local-setup/scripts/p3_result_return_cases.py"
SPEC = importlib.util.spec_from_file_location("result_return_consumer_tested", SOURCE)
assert SPEC is not None and SPEC.loader is not None
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


class CloseOwner:
    def __init__(self, name: str, events: list[str], *, fail: bool = False) -> None:
        self.name, self.events, self.fail = name, events, fail
        self.closed = False

    async def close(self) -> None:
        self.events.append(self.name)
        if self.fail:
            raise RuntimeError("PRIVATE_CLOSE_SENTINEL")
        self.closed = True


class Facade(CloseOwner):
    def __init__(self, child: CloseOwner, events: list[str]) -> None:
        super().__init__("facade", events)
        self.child = child

    async def close(self) -> None:
        await self.child.close()
        await super().close()


class OwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_startup_retains_ignored_thread_until_late_owner_is_acquired_and_closed(
        self,
    ):
        resources = m.OwnedResources()
        entered, release = threading.Event(), threading.Event()
        events: list[str] = []
        late = CloseOwner("late", events)

        def factory() -> CloseOwner:
            entered.set()
            if not release.wait(2):
                raise TimeoutError("finite_test_factory_wait")
            return late

        waiter = asyncio.create_task(resources.startup(factory, 1))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
            self.assertEqual(resources.observation()["startup_pending"], 1)
            self.assertFalse(late.closed)
            release.set()
            self.assertTrue(await resources.close())
            self.assertTrue(late.closed)
            self.assertEqual(events, ["late"])
            self.assertEqual(resources.observation()["retained_tiers"], [0, 0, 0])
        finally:
            release.set()
            if not waiter.done():
                waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
            await resources.close()

    async def test_partial_factory_failure_closes_prior_public_client(self):
        resources = m.OwnedResources()
        events: list[str] = []
        first = CloseOwner("first_factory_client", events)
        self.assertIs(await resources.startup(lambda: first, 2), first)

        def failing_factory() -> CloseOwner:
            raise ValueError("PRIVATE_FACTORY_SENTINEL")

        with self.assertRaises(ValueError):
            await resources.startup(failing_factory, 2)
        self.assertFalse(first.closed)
        self.assertTrue(await resources.close())
        self.assertTrue(first.closed)
        self.assertEqual(events, ["first_factory_client"])

    async def test_facade_constructor_failure_keeps_raw_client_for_cleanup(self):
        resources = m.OwnedResources()
        events: list[str] = []
        raw = await resources.startup(lambda: CloseOwner("raw", events), 0)

        def construct_facade(child: CloseOwner) -> CloseOwner:
            self.assertIs(child, raw)
            raise ValueError("PRIVATE_CONSTRUCTOR_SENTINEL")

        with self.assertRaises(ValueError):
            resources.transfer(construct_facade(raw), (raw,), 0)
        self.assertFalse(raw.closed)
        self.assertTrue(await resources.close())
        self.assertTrue(raw.closed)
        self.assertEqual(events, ["raw"])

    async def test_failed_delivery_close_withholds_borrowed_runner_and_case_until_explicit_retry(
        self,
    ):
        resources = m.OwnedResources()
        events: list[str] = []
        delivery = resources.add(CloseOwner("delivery", events, fail=True), 0)
        runner = resources.add(CloseOwner("runner", events), 1)
        case = resources.add(CloseOwner("case", events), 2)
        self.assertFalse(await resources.close())
        self.assertEqual(events, ["delivery"])
        self.assertFalse(runner.closed)
        self.assertFalse(case.closed)
        self.assertFalse(resources.observation()["cleanup_complete"])
        delivery.fail = False
        self.assertTrue(await resources.close())
        self.assertEqual(events, ["delivery", "delivery", "runner", "case"])
        self.assertTrue(runner.closed and case.closed)

    async def test_successful_facade_transfer_closes_original_child_once_before_borrowed_reader(
        self,
    ):
        resources = m.OwnedResources()
        events: list[str] = []
        raw = await resources.startup(lambda: CloseOwner("raw", events), 0)
        facade = resources.transfer(Facade(raw, events), (raw,), 0)
        reader = resources.add(CloseOwner("reader", events), 1)
        self.assertTrue(await resources.close())
        self.assertTrue(raw.closed and facade.closed and reader.closed)
        self.assertEqual(events, ["raw", "facade", "reader"])


class RunCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_numeric_owner_uuid_rejects_before_issue_then_namespaced_command_runs_and_replays(
        self,
    ):
        # Reuse public-port fakes, while exercising the actual selected consumer specialist
        # and actual FixedPolicyRunner. No P1/P2 store, service or provider is constructed.
        spec = importlib.util.spec_from_file_location(
            "result_return_public_execution_fakes",
            ROOT / "projects/delegation-reliability/tests/test_runner.py",
        )
        assert spec is not None and spec.loader is not None
        fakes = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fakes)
        source = json.loads((ROOT / "contracts/delegation/fixed-policy-v2.json").read_bytes())
        raw = copy.deepcopy(source["producer_input"])
        raw["deadline_at_ms"] = time.time_ns() // 1_000_000 + 60_000
        request = m.produce_fixed_policy_request(raw)
        records = tuple(
            EvidenceRecord(request.scope, EvidenceRef(**ref), body.encode())
            for ref, body in zip(
                raw["evidence"],
                (source["policy_body_utf8"], source["facts_body_utf8"]),
                strict=True,
            )
        )
        execution = fakes.FakeExecution(request)
        specialist = m.ScriptedPolicy(m.parse_fixed_policy_result(m.canonical(source["result"])))
        owner = "11111111-1111-4111-8111-111111111111"
        runner = FixedPolicyRunner(
            executions=execution,
            scope=request.scope,
            owner_id=owner,
            specialist=specialist,
            case_authority=fakes.FakeCases(request),
            evidence=records,
        )
        try:
            with self.assertRaises(DelegationRunError) as caught:
                await runner.run_once(execution.record.work_id, owner)
            self.assertEqual(caught.exception.code, "invalid_input")
            self.assertEqual(
                (execution.issue_count, execution.complete_count, specialist.invocations),
                (0, 0, 0),
            )
            self.assertEqual(runner.metrics()["started"], 0)
            command = m.run_command("original", owner)
            self.assertEqual(command, "return_original_" + UUID(owner).hex)
            self.assertEqual(command, m.run_command("original", owner))
            self.assertEqual(identifier(command), command)
            first = await runner.run_once(execution.record.work_id, command)
            self.assertTrue(first.invoked)
            self.assertEqual(first.recorded.disposition, "eligible_at_commit")
            self.assertEqual(first.view.applicability, "candidate")
            self.assertEqual(first.view.execution.current_attempt.command_id, command)
            again = await runner.run_once(execution.record.work_id, command)
            self.assertFalse(again.invoked)
            self.assertEqual(again.view.result, first.view.result)
            self.assertEqual(
                (execution.issue_count, execution.complete_count, specialist.invocations),
                (1, 1, 1),
            )
            self.assertEqual(
                len({m.run_command(label, owner) for label in ("original", "stale", "current")}),
                3,
            )
            with self.assertRaises(AssertionError):
                m.run_command("foreign", owner)
        finally:
            await runner.close()


class FailureDiagnosticTests(unittest.TestCase):
    def test_known_runner_error_is_finite_and_foreign_exception_text_stays_private(self):
        for failure, expected in (
            (DelegationRunError("invalid_input"), "invalid_input"),
            (RuntimeError("PRIVATE_DIAGNOSTIC_SENTINEL"), "consumer_failed"),
        ):
            with (
                self.subTest(expected=expected),
                tempfile.TemporaryDirectory(dir="/private/tmp") as folder,
            ):
                output = io.StringIO()
                with (
                    patch.dict(os.environ, {"P3_RESULT_DIRECTORY": folder}),
                    patch.object(m, "configuration", return_value={}),
                    patch.object(m, "exercise", new=AsyncMock(side_effect=failure)),
                    patch.object(m, "STAGE", "run"),
                    patch.object(m, "LABEL", "original"),
                    contextlib.redirect_stdout(output),
                ):
                    self.assertEqual(m.main(), 1)
                raw = (Path(folder) / "p3-return-failure.json").read_bytes()
                diagnostic = json.loads(raw)
                self.assertEqual(
                    diagnostic,
                    {
                        "schema_version": 1,
                        "status": "failed",
                        "stage": "run",
                        "case": "original",
                        "code": expected,
                    },
                )
                self.assertEqual(json.loads(output.getvalue()), diagnostic)
                self.assertNotIn(b"PRIVATE_DIAGNOSTIC_SENTINEL", raw)
                self.assertNotIn("PRIVATE_DIAGNOSTIC_SENTINEL", output.getvalue())


def native_fixture() -> tuple[dict[str, Any], dict[str, Any], DeliveryIntent, DeliveryReceipt]:
    shared = json.loads((ROOT / "contracts/delegation/result-receiver-v1.json").read_bytes())
    wire = json.loads(shared["intent_canonical"])
    intent = DeliveryIntent(
        wire["delivery_id"],
        WorkScope(**wire["scope"]),
        wire["work_id"],
        wire["attempt_id"],
        wire["result_sha256"],
        wire["receiver_id"],
        wire["recipient_id"],
        base64.b64decode(wire["body"], validate=True),
        wire["prepared_at_ms"],
    )
    receipt = DeliveryReceipt(**shared["receipt"])
    config = {
        "scope": wire["scope"],
        "case_id": "case_fixed",
        "conversation_id": "conversation_fixed",
    }
    case = {
        "schemaVersion": 1,
        "source": "p1_public_v4",
        "scope": {"tenantId": wire["scope"]["tenant_id"], "accountId": wire["scope"]["account_id"]},
        "caseId": config["case_id"],
        "conversationId": config["conversation_id"],
        "revision": "2",
        "request": {
            "schemaVersion": 1,
            "kind": "booking_investigation",
            "bookingReference": "DEMO-BK-001",
            "newCheckIn": "2030-12-12",
            "investigationConsent": True,
        },
        "workflow": {
            "taskId": "11111111-1111-4111-8111-111111111111",
            "state": "ready",
            "version": "0",
        },
        "intent": {"state": "not_committed", "intentId": None},
        "mutation": {
            "state": "not_observed",
            "outcome": "not_observed",
            "cancellation": "not_requested",
            "effectId": None,
            "outcomeEventId": None,
        },
        "supplierResult": None,
        "sourceRevision": "a" * 64,
    }
    view = {
        "schemaVersion": 1,
        "intent": wire,
        "receipt": asdict(receipt),
        "case": case,
        "observed": {
            "p2ObservedAt": "2030-01-01T00:00:00.000Z",
            "caseObservedAt": "2030-01-01T00:00:00.001Z",
            "disclosureAdmittedAt": "2030-01-01T00:00:00.002Z",
            "atomic": False,
        },
    }
    return config, {"schemaVersion": 1, "status": "known", "view": view}, intent, receipt


class WireTests(unittest.TestCase):
    def test_original_receipt_and_opaque_result_remain_separate_from_current_case(self):
        config, envelope, intent, receipt = native_fixture()
        view = m.validate_native_view(config, envelope, intent, receipt)
        self.assertEqual(view["intent"], json.loads(intent.canonical()))
        self.assertEqual(view["receipt"], asdict(receipt))
        self.assertEqual(view["case"]["revision"], "2")
        self.assertFalse(view["observed"]["atomic"])
        self.assertNotIn("applicability", view)
        self.assertNotIn("candidate", view)

    def test_wrong_envelopes_receipt_binding_current_scope_and_as_of_claims_fail(self):
        config, original, intent, receipt = native_fixture()
        changes = (
            lambda v: v.update(extra=1),
            lambda v: v.update(schemaVersion=True),
            lambda v: v.update(status="missing"),
            lambda v: v["view"].update(extra=1),
            lambda v: v["view"].update(schemaVersion=True),
            lambda v: v["view"]["intent"].update(body="YQ=="),
            lambda v: v["view"]["receipt"].update(result_sha256="f" * 64),
            lambda v: v["view"]["receipt"].update(
                receipt_id="22222222-2222-4222-8222-222222222222"
            ),
            lambda v: v["view"]["case"].update(source="standalone_reference_v1"),
            lambda v: v["view"]["case"].update(revision="1"),
            lambda v: v["view"]["case"].update(caseId="foreign_case"),
            lambda v: v["view"]["case"].update(conversationId="foreign_conversation"),
            lambda v: v["view"]["case"]["scope"].update(accountId="foreign_account"),
            lambda v: v["view"]["observed"].update(atomic=True),
            lambda v: v["view"]["observed"].update(caseObservedAt="not-a-time"),
        )
        for number, change in enumerate(changes):
            candidate = copy.deepcopy(original)
            change(candidate)
            with self.subTest(control=number), self.assertRaises(AssertionError):
                m.validate_native_view(config, candidate, intent, receipt)

    def test_duplicate_wire_keys_reject_before_dict_equality_can_hide_them(self):
        with self.assertRaises(AssertionError):
            json.loads('{"schemaVersion":1,"schemaVersion":1}', object_pairs_hook=m._json_pairs)

    def test_isolated_import_loads_fixed_compatibility_helper_and_canonical_receiver_without_io(
        self,
    ):
        code = "\n".join(
            [
                "import importlib.util, pathlib, sys",
                "def denied(event, args):",
                "    if event in {'socket.connect','socket.bind','subprocess.Popen'}: raise AssertionError('unexpected_import_io')",
                "sys.addaudithook(denied)",
                f"source = pathlib.Path({str(SOURCE)!r})",
                "spec = importlib.util.spec_from_file_location('isolated_return_consumer', source)",
                "module = importlib.util.module_from_spec(spec)",
                "sys.modules[spec.name] = module",
                "spec.loader.exec_module(module)",
                "from services.channel_policy_demo.result_receiver import ChannelResultReceiver as canonical",
                "helper = sys.modules['p3_result_return_receiver_helper']",
                "assert pathlib.Path(helper.__file__).resolve() == source.with_name('p3_channel_receiver.py').resolve()",
                "assert module.ChannelResultReceiver is helper.ChannelResultReceiver is canonical",
                "assert canonical.__module__ == 'services.channel_policy_demo.result_receiver'",
                "assert not module.OwnedResources().startups",
                "print('isolated_import_ok')",
            ]
        )
        result = subprocess.run(
            [sys.executable, "-I", "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "isolated_import_ok")


if __name__ == "__main__":
    unittest.main()
