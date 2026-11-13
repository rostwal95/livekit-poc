"""Offline recovery scheduling/lifetime checks; real authority uses its explicit PG gate."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from continuity_lab.action_api import ActionIntent, ActionReceipt
from continuity_lab.case_control_api import CaseControlIdentity
from continuity_lab.postgres_api import Confirmation, QuoteSnapshot, parse_confirmation_payload
from continuity_lab.work_api import (
    BearerToken,
    PostgresSettings,
    WorkDirectory,
    WorkError,
    WorkPrincipal,
    WorkScope,
)
from delegation_reliability.contracts import encode_request, parse_request
from delegation_reliability.projection_api import open_projection_client
from delegation_reliability.projection_models import ProjectionError

ROOT = Path(__file__).resolve().parents[3]


def fixture() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "recovery_schedule_tests",
        ROOT / "projects/delegation-reliability/tests/pg_recovery_cases.py",
    )
    assert spec is not None and spec.loader is not None
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


F = fixture()


def context(directory: Path, *, owner: bool = False) -> dict[str, str]:
    env = {
        "P3_RECOVERY_PG_PORT": "15432",
        "P3_RECOVERY_WORK_SCHEMA": "p1_work_recovery_" + uuid4().hex,
        "P3_RECOVERY_CASE_SCHEMA": "p3_completion_" + uuid4().hex,
        "P3_RECOVERY_PROJECTION_SCHEMA": "p3_projection_recovery_" + uuid4().hex,
        "P3_RECOVERY_DIRECTORY": str(directory),
        "P3_RECOVERY_OWNER_PASSWORD" if owner else "P3_RECOVERY_RUNTIME_PASSWORD": "synthetic",
    }
    if not owner:
        env.update(
            P3_RECOVERY_EXECUTION_TOKEN="E" * 43,
            P3_RECOVERY_COMPLETION_TOKEN="C" * 43,
            P3_RECOVERY_NODE_TOKEN="N" * 43,
            P3_RECOVERY_ENDPOINT_FILE=str(directory / "endpoint-a.json"),
        )
    return env


class RecoveryScheduleTests(unittest.TestCase):
    def test_closed_runtime_environment_and_distinct_owner_role(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            env = context(directory)
            with patch.object(F, "MODE", "issued-replay"), patch.dict(os.environ, env, clear=True):
                F.environment()
            for key in (
                "P3_RECOVERY_OWNER_PASSWORD",
                "PYTHONPATH",
                "NODE_OPTIONS",
                "OPENAI_API_KEY",
                "PGPASSWORD",
            ):
                with (
                    self.subTest(key=key),
                    patch.object(F, "MODE", "issued-replay"),
                    patch.dict(os.environ, {**env, key: "inert"}, clear=True),
                    self.assertRaises(AssertionError),
                ):
                    F.environment()
            owner_env = context(directory, owner=True)
            with patch.object(F, "MODE", "install"), patch.dict(os.environ, owner_env, clear=True):
                F.environment()
            with (
                patch.object(F, "MODE", "install"),
                patch.dict(
                    os.environ, {**owner_env, "P3_RECOVERY_COMPLETION_TOKEN": "C" * 43}, clear=True
                ),
                self.assertRaises(AssertionError),
            ):
                F.environment()

    def test_real_public_exact_case_constructor_uses_actor_then_scope(self) -> None:
        schema = "p3_completion_" + uuid4().hex
        identity = CaseControlIdentity(F.HELPER.ACTOR.actor_id, F.HELPER.ACTOR.scope_id, schema)
        client = SimpleNamespace(identity=identity, case=AsyncMock())
        with (
            patch.object(
                F, "load", return_value={"task_id": str(uuid4()), "case_id": str(uuid4())}
            ),
            patch.object(F, "settings", return_value=SimpleNamespace(schema=schema)),
        ):
            bound = F.binding()
        self.assertEqual(bound.authority_actor_id, F.HELPER.ACTOR.actor_id)
        self.assertEqual(bound.authority_scope_id, F.HELPER.ACTOR.scope_id)
        F.ExactManagedCaseAuthority(client, scope=F.COMPLETION, bindings=(bound,))
        swapped = replace(
            bound,
            authority_actor_id=bound.authority_scope_id,
            authority_scope_id=bound.authority_actor_id,
        )
        with self.assertRaises(F.CompletionError) as caught:
            F.ExactManagedCaseAuthority(client, scope=F.COMPLETION, bindings=(swapped,))
        self.assertEqual(caught.exception.code, "unauthorized")
        client.case.assert_not_called()

    def test_child_success_cannot_hide_secondary_cleanup_failure(self) -> None:
        output = io.StringIO()
        diagnostics = {
            "queryVisibility": "unobserved",
            "owned_backend_ids": [],
            "waiters": [],
            "cleanup_failure": True,
        }
        with (
            patch.object(F, "MODE", ""),
            patch.object(F, "DIAGNOSTICS", diagnostics),
            patch.object(F, "environment"),
            patch.object(F, "dispatch", new=AsyncMock(return_value=F.RESPONSES["issued-replay"])),
            patch.object(sys, "argv", ["fixture", "issued-replay"]),
            redirect_stdout(output),
        ):
            self.assertEqual(F.main(), 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "failed")
        self.assertIs(result["diagnostics"]["cleanup_failure"], True)

    def test_all_emitted_public_error_codes_are_vetted_without_value_reflection(self) -> None:
        expected = {
            "acknowledgement_unknown",
            "capacity",
            "case_cancelled",
            "case_changed",
            "checkpoint_conflict",
            "cleanup_incomplete",
            "closed",
            "deadline_exceeded",
            "deadline_expired",
            "expired",
            "fixture_failed",
            "identity_conflict",
            "intent_committed",
            "internal_error",
            "invalid_confirmation",
            "invalid_input",
            "invalid_result",
            "invalid_source_state",
            "invalid_stored_state",
            "not_eligible",
            "not_found",
            "quote_expired",
            "request_aborted",
            "schema_mismatch",
            "source_mismatch",
            "stale_revision",
            "storage_unavailable",
            "transport_unknown",
            "unauthorized",
        }
        self.assertEqual(F.DIAGNOSTIC_CODES, expected)
        for code in expected - {"fixture_failed"}:
            accepted = []
            for cls in (F.WorkError, F.DelegationRunError, F.CompletionError, F.ProjectionError):
                error = cls(code)
                if error.code == code:
                    accepted.append(F.failure_identity(error)[1])
            self.assertTrue(accepted, code)
            self.assertEqual(set(accepted), {code})

    def test_action_snapshot_preserves_public_versioned_confirmation_and_intent_wire(self) -> None:
        task_id, case_id = str(uuid4()), str(uuid4())
        quote = QuoteSnapshot(
            str(uuid4()),
            task_id,
            2,
            "DEMO-BK-001",
            date(2030, 12, 10),
            500,
            "USD",
            "2030-01-01T00:00:00+00:00",
            case_id,
            0,
            str(uuid4()),
        )
        consent = Confirmation(quote, True)
        intent = ActionIntent(
            str(uuid4()),
            task_id,
            "case_scope",
            "case_actor",
            2,
            quote,
            str(uuid4()),
            str(uuid4()),
            str(uuid4()),
            "2026-11-11T00:00:00+00:00",
        )
        receipt = ActionReceipt(
            str(uuid4()),
            WorkScope("tenant_recovery", "completion"),
            str(uuid4()),
            str(uuid4()),
            "a" * 64,
            "p3_completion_" + uuid4().hex,
            "case_scope",
            "case_actor",
            task_id,
            case_id,
            2,
            "recovery_action",
            consent,
            intent,
            1800000000000,
        )
        saved = F.action_payload(receipt)
        self.assertEqual(saved["confirmation"], consent.payload())
        self.assertEqual(saved["intent"], intent.payload())
        self.assertEqual(set(saved["confirmation"]), {"schema_version", "quote", "explicit"})
        self.assertEqual(saved["confirmation"]["schema_version"], 2)
        decoded = parse_confirmation_payload(
            F.canonical(saved["confirmation"]["quote"]).decode(),
            explicit=saved["confirmation"]["explicit"],
        )
        self.assertEqual(decoded.payload(), saved["confirmation"])
        self.assertEqual(decoded.quote, quote)
        self.assertEqual(F.action_payload(receipt), saved)

    def test_public_projection_factory_accepts_exact_recovery_prefix(self) -> None:
        token = BearerToken("C" * 43)
        scope = WorkScope("tenant_recovery", "completion")
        directory = WorkDirectory({token: WorkPrincipal("recovery", scope)})
        settings = PostgresSettings(
            schema="p3_projection_recovery_" + uuid4().hex, password="synthetic"
        )
        with (
            patch.object(PostgresSettings, "connect", side_effect=OSError("inert")) as connection,
            self.assertRaises(ProjectionError) as caught,
        ):
            open_projection_client(
                settings=settings, directory=directory, token=token, source_id=str(uuid4())
            )
        self.assertEqual(caught.exception.code, "storage_unavailable")
        self.assertEqual(connection.call_count, 1)
        with (
            patch.object(PostgresSettings, "connect") as connection,
            self.assertRaises(ProjectionError) as caught,
        ):
            open_projection_client(
                settings=PostgresSettings(
                    schema="p3_recovery_" + uuid4().hex, password="synthetic"
                ),
                directory=directory,
                token=token,
                source_id=str(uuid4()),
            )
        self.assertEqual(caught.exception.code, "invalid_input")
        connection.assert_not_called()

    def test_request_is_fresh_codec_valid_and_scope_not_collapsed(self) -> None:
        with patch.object(F.time, "time_ns", return_value=1800000000000000000):
            early = F.make_request("i")
            completion = F.make_request("m")
        with patch.object(F.time, "time_ns", return_value=1800000000100000000):
            later = F.make_request("i")
        self.assertEqual(early.deadline_at_ms, 1800000060000)
        self.assertEqual(later.deadline_at_ms, 1800000060100)
        self.assertEqual(parse_request(encode_request(early)), early)
        self.assertNotEqual(early.scope, completion.scope)
        self.assertEqual(early.scope.account_id, "execution")
        self.assertEqual(completion.scope.account_id, "completion")
        self.assertNotEqual(early.case_id, completion.case_id)
        self.assertEqual(F.evidence(early.scope)[0].reference, early.evidence[0])

    def test_immutable_save_preserves_equal_bytes_and_rejects_changed_payload(self) -> None:
        with (
            tempfile.TemporaryDirectory() as name,
            patch.dict(os.environ, {"P3_RECOVERY_DIRECTORY": name}, clear=True),
        ):
            F.save("receipt.json", {"identity": "original"})
            path = Path(name) / "receipt.json"
            before = path.read_bytes()
            stamp = path.stat().st_mtime_ns
            F.save("receipt.json", {"identity": "original"})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(path.stat().st_mtime_ns, stamp)
            with self.assertRaises(AssertionError):
                F.save("receipt.json", {"identity": "changed"})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_load_rejects_oversize_links_and_directory_permissions(self) -> None:
        with (
            tempfile.TemporaryDirectory() as name,
            patch.dict(os.environ, {"P3_RECOVERY_DIRECTORY": name}, clear=True),
        ):
            path = Path(name) / "oversize.json"
            path.write_bytes(b"x" * 32769)
            path.chmod(0o600)
            with self.assertRaises(AssertionError):
                F.load("oversize.json")
            F.save("original.json", {"ok": True})
            (Path(name) / "linked.json").symlink_to(Path(name) / "original.json")
            with self.assertRaises(AssertionError):
                F.load("linked.json")
            Path(name).chmod(0o755)
            try:
                with self.assertRaises(AssertionError):
                    F.folder()
            finally:
                Path(name).chmod(0o700)

    def test_pid_marker_is_private_exclusive(self) -> None:
        with (
            tempfile.TemporaryDirectory() as name,
            patch.dict(os.environ, {"P3_RECOVERY_DIRECTORY": name}, clear=True),
        ):
            F.marker("ready")
            p = Path(name) / "ready.reached"
            self.assertEqual(p.read_text(), str(os.getpid()) + "\n")
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                F.marker("ready")

    def test_diagnostics_never_reflect_unknown_exception_properties_or_messages(self) -> None:
        class UntrustedError(Exception):
            @property
            def code(self) -> str:
                raise AssertionError("unknown exception property executed")

        self.assertEqual(
            F.failure_identity(UntrustedError("private payload")),
            ("DependencyError", "fixture_failed"),
        )
        self.assertEqual(
            F.failure_identity(AssertionError("private payload")),
            ("AssertionError", "fixture_failed"),
        )
        self.assertEqual(
            F.failure_identity(WorkError("storage_unavailable")),
            ("WorkError", "storage_unavailable"),
        )
        changed = WorkError("storage_unavailable")
        changed.code = "lowercase_private_value"
        self.assertEqual(F.failure_identity(changed), ("WorkError", "fixture_failed"))

    def test_inventory_digest_has_framing_and_finite_caps(self) -> None:
        self.assertEqual(F.inventory_digest([{"a": 1}]), F.inventory_digest([{"a": 1}]))
        self.assertNotEqual(
            F.inventory_digest([{"a": 1}, {"b": 2}]), F.inventory_digest([{"a": 1, "b": 2}])
        )
        self.assertNotEqual(F.inventory_digest([{"a": 1}]), F.inventory_digest([{"a": 2}]))
        for records in ([], [{}] * 65, [{"body": "x" * 4096}], [{"body": "x" * 4000}] * 17):
            with self.subTest(size=len(records)), self.assertRaises(AssertionError):
                F.inventory_digest(records)


class RecoveryAsyncScheduleTests(unittest.IsolatedAsyncioTestCase):
    async def test_coordinator_marker_observes_before_real_invoke_without_waiting(self) -> None:
        order = []

        async def invoke(request: object) -> str:
            order.append("invoke")
            return "observed"

        actual = SimpleNamespace(invoke_observed=invoke, close=AsyncMock())
        with (
            patch.object(F, "MODE", "coordinator-crash"),
            patch.object(F, "marker", side_effect=lambda _: order.append("marker")),
            patch.object(F, "held", side_effect=AssertionError("must not hold before HTTP")),
        ):
            self.assertEqual(await F.InvocationTap(actual).invoke_observed(object()), "observed")
        self.assertEqual(order, ["marker", "invoke"])

    async def test_race_issue_waits_until_parent_release_before_authority_call(self) -> None:
        entered, released = threading.Event(), threading.Event()
        calls = []

        def held(name: str) -> None:
            entered.set()
            self.assertTrue(released.wait(2))

        async def issue(**values: object) -> str:
            calls.append(values)
            return "issued"

        actual = SimpleNamespace(issue=issue)
        with patch.object(F, "MODE", "race-a"), patch.object(F, "held", side_effect=held):
            task = asyncio.create_task(
                F.CapturedExecution(actual, "i").issue(
                    work_id="work", owner_id="owner", command_id="command"
                )
            )
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                self.assertEqual(calls, [])
                self.assertFalse(task.done())
            finally:
                released.set()
            self.assertEqual(await task, "issued")
        self.assertEqual(calls, [{"work_id": "work", "owner_id": "owner", "command_id": "command"}])

    async def test_public_connection_instrumentation_records_exact_owned_backend(self) -> None:
        order = []
        connection = SimpleNamespace(info=SimpleNamespace(backend_pid=456), close=MagicMock())

        def connect(value: PostgresSettings, *, application_name: str = "continuity-runtime"):
            order.append("connected")
            return connection

        async def issue(**values: object) -> str:
            actual = F.settings().connect()
            order.append("authority")
            actual.close()
            return "issued"

        with tempfile.TemporaryDirectory() as name:
            env = context(Path(name))
            env["P3_RECOVERY_BARRIER"] = str(Path(name) / "race_a_ready.reached")
            with (
                patch.dict(os.environ, env, clear=True),
                patch.object(F, "MODE", "race-a"),
                patch.object(F, "held", side_effect=lambda _: order.append("released")),
                patch.object(PostgresSettings, "connect", connect),
            ):
                self.assertEqual(
                    await F.CapturedExecution(SimpleNamespace(issue=issue), "i").issue(
                        work_id="work", owner_id="owner", command_id="command"
                    ),
                    "issued",
                )
                self.assertEqual(
                    F.load("race_a_backend.json"),
                    {"role": "race-a", "process_pid": os.getpid(), "backend_pid": 456},
                )
        self.assertEqual(order, ["released", "connected", "authority"])
        connection.close.assert_called_once()

    async def test_bundle_attempts_all_independent_closes_then_preserves_first_error(self) -> None:
        first = RuntimeError("first")
        order = []

        def owner(name: str, failure: BaseException | None = None) -> SimpleNamespace:
            async def close() -> None:
                order.append(name)
                if failure is not None:
                    raise failure

            return SimpleNamespace(close=close)

        b = F.Bundle.__new__(F.Bundle)
        b.processor = owner("processor", first)
        b.delivery = owner("shared_delivery")
        b.authorizer = owner("authorizer", ValueError("second"))
        b.runner = owner("runner")
        b.coordinator = owner("coordinator")
        b.control = owner("control")
        with self.assertRaises(RuntimeError) as caught:
            await b.close()
        self.assertIs(caught.exception, first)
        self.assertEqual(order, ["processor", "authorizer", "runner", "coordinator", "control"])

    async def test_secondary_cleanup_failure_never_masks_active_primary(self) -> None:
        primary = ValueError("primary")
        order = []

        async def first_close() -> None:
            order.append("first")
            raise RuntimeError("secondary")

        async def second_close() -> None:
            order.append("second")

        diagnostics = {"cleanup_failure": False}
        with patch.object(F, "DIAGNOSTICS", diagnostics), self.assertRaises(ValueError) as caught:
            try:
                raise primary
            finally:
                await F.close_preserving(
                    SimpleNamespace(close=first_close), SimpleNamespace(close=second_close)
                )
        self.assertIs(caught.exception, primary)
        self.assertEqual(order, ["first", "second"])
        self.assertIs(diagnostics["cleanup_failure"], True)

    async def test_cleanup_without_primary_raises_first_after_all_owners(self) -> None:
        first = RuntimeError("first")
        later = AsyncMock()

        async def close() -> None:
            raise first

        with (
            patch.object(F, "DIAGNOSTICS", {"cleanup_failure": False}),
            self.assertRaises(RuntimeError) as caught,
        ):
            await F.close_preserving(SimpleNamespace(close=close), SimpleNamespace(close=later))
        self.assertIs(caught.exception, first)
        later.assert_awaited_once()

    async def test_synthetic_reader_rejects_completion_case(self) -> None:
        self.assertEqual(
            (await F.SyntheticCases().snapshot(case_id="case_execution")).scope.account_id,
            "execution",
        )
        with self.assertRaises(AssertionError):
            await F.SyntheticCases().snapshot(case_id="case_completion")

    async def test_duplicate_receiver_entry_is_durable_and_never_reaches_receiver(self) -> None:
        actual = SimpleNamespace(accept=AsyncMock(return_value="receipt"))
        intent = SimpleNamespace(
            delivery_id=str(uuid4()),
            work_id=str(uuid4()),
            attempt_id=str(uuid4()),
            result_sha256="a" * 64,
        )
        with (
            tempfile.TemporaryDirectory() as name,
            patch.dict(os.environ, {"P3_RECOVERY_DIRECTORY": name}, clear=True),
            patch.object(F, "MODE", "receiver-resume"),
        ):
            adapter = F.ReturnedReceiver(actual)
            self.assertEqual(await adapter.accept(intent), "receipt")
            first = (Path(name) / "receiver_call.json").read_bytes()
            for _ in range(2):
                with self.assertRaises(AssertionError):
                    await adapter.accept(intent)
            self.assertEqual((Path(name) / "receiver_call.json").read_bytes(), first)
            self.assertEqual(F.load("receiver_call_duplicate.json"), F.load("receiver_call.json"))
            self.assertEqual(len(tuple(Path(name).glob("receiver_call_duplicate.json"))), 1)
        actual.accept.assert_awaited_once()

    async def test_returned_receiver_preserves_commit_before_owned_crash_cut(self) -> None:
        order = []

        async def accept(intent: object) -> str:
            order.append("committed")
            return "receipt"

        actual = SimpleNamespace(accept=accept)
        with (
            patch.object(F, "MODE", "receiver-crash"),
            patch.object(F, "record_receiver_call", side_effect=lambda *args: order.append("call")),
            patch.object(F, "held", side_effect=lambda _: order.append("crash_cut")),
        ):
            intent = SimpleNamespace(
                delivery_id="delivery", work_id="work", attempt_id="attempt", result_sha256="digest"
            )
            self.assertEqual(await F.ReturnedReceiver(actual).accept(intent), "receipt")
        self.assertEqual(order, ["call", "committed", "crash_cut"])


def wrapper() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "recovery_parent_tests", ROOT / "local-setup/scripts/p3_recovery_check.py"
    )
    assert spec is not None and spec.loader is not None
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


W = wrapper()


class RecoveryParentDiagnosticTests(unittest.TestCase):
    def test_real_child_exit_before_arrival_retains_fixed_original_failure(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            work = Path(name).resolve()
            owner = W.Children(work, time.monotonic() + 3)
            barrier = W.FileBarrier(work, "issue_commit")
            fixed = {
                "schema_version": 1,
                "status": "failed",
                "mode": "issued-crash",
                "stage": "issued-crash",
                "error_type": "AssertionError",
                "code": "fixture_failed",
                "diagnostics": {
                    "queryVisibility": "unobserved",
                    "cleanup_failure": False,
                    "owned_backend_ids": [],
                    "waiters": [],
                },
            }
            child = owner.start(
                "issued-crash",
                [
                    sys.executable,
                    "-I",
                    "-c",
                    "import sys;sys.stdout.write("
                    + repr(json.dumps(fixed))
                    + ");sys.stdout.flush();sys.exit(1)",
                ],
                {},
                cwd=work,
            )
            try:
                with self.assertRaises(W.ProcessControlError):
                    owner.wait(child, barrier, "issue_commit")
                self.assertEqual(owner.first_failure, fixed)
                self.assertEqual(
                    owner.first_observation,
                    {
                        "child": "issued-crash",
                        "operation": "wait",
                        "barrier": "issue_commit",
                        "kind": "exited",
                        "process_pid": child.pid,
                        "returncode": 1,
                    },
                )
                encoded = json.dumps(
                    {
                        "schema_version": 1,
                        "status": "failed",
                        "diagnostic_only": True,
                        "parent_observation": owner.first_observation,
                        "child_failure": owner.first_failure,
                    }
                ).encode()
                self.assertEqual(W.validated_parent_failure(encoded)["child_failure"], fixed)
            finally:
                owner.close()
            self.assertIsNotNone(child.returncode)

    def test_live_wait_timeout_is_unobserved_and_owned_child_is_reaped(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            work = Path(name).resolve()
            owner = W.Children(work, time.monotonic() + 0.04)
            barrier = W.FileBarrier(work, "issue_commit")
            child = owner.start(
                "issued-crash",
                [sys.executable, "-I", "-c", "import time;time.sleep(2)"],
                {},
                cwd=work,
            )
            try:
                with self.assertRaises(W.ProcessControlError):
                    owner.wait(child, barrier, "issue_commit")
                self.assertIsNone(owner.first_failure)
                self.assertEqual(owner.first_observation["kind"], "timeout")
                self.assertIsNone(owner.first_observation["returncode"])
            finally:
                owner.close()
            self.assertIsNotNone(child.returncode)

    def test_kill_and_finish_errors_keep_finite_context_and_actual_ownership(self) -> None:
        for operation in ("kill", "finish"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as name:
                work = Path(name).resolve()
                owner = W.Children(work, time.monotonic() + 3)
                child = owner.start(
                    "issued-crash",
                    [sys.executable, "-I", "-c", "import time;time.sleep(2)"],
                    {},
                    cwd=work,
                )
                try:
                    with (
                        patch.object(
                            child,
                            "kill" if operation == "kill" else "wait",
                            side_effect=W.ProcessControlError("private exception text"),
                        ),
                        self.assertRaises(W.ProcessControlError),
                    ):
                        getattr(owner, operation)(child)
                    self.assertEqual(owner.first_observation["operation"], operation)
                    self.assertEqual(owner.first_observation["kind"], "control_error")
                    self.assertIsNone(owner.first_failure)
                    self.assertNotIn("private", json.dumps(owner.first_observation))
                finally:
                    owner.close()
                self.assertIsNotNone(child.returncode)

    def test_failed_normal_context_is_retained_and_sink_fault_preserves_primary(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            work = Path(name).resolve()
            owner = W.Children(work, time.monotonic() + 1)
            observed = {
                "child": "issued-crash",
                "operation": "wait",
                "barrier": "issue_commit",
                "kind": "timeout",
                "process_pid": 123,
                "returncode": None,
            }
            owner.first_observation = observed.copy()
            target = work / "normal_failed.json"
            self.assertTrue(W.retain_parent_context(target, owner))
            value = json.loads((work / "normal_failed-diagnostic.json").read_bytes())
            self.assertIs(value["diagnostic_only"], True)
            self.assertEqual(value["parent_observation"], observed)
            for fault in (OSError("private sink"), RuntimeError("private sink")):
                with patch.object(W, "write_json", side_effect=fault):
                    self.assertFalse(W.retain_parent_context(work / "other_failed.json", owner))
                self.assertEqual(owner.first_observation, observed)
                self.assertIsNone(owner.first_failure)

    def test_parent_envelope_rejects_success_unknown_stage_pid_bool_and_extra_data(self) -> None:
        base = {
            "schema_version": 1,
            "status": "failed",
            "diagnostic_only": True,
            "parent_observation": {
                "child": "issued-crash",
                "operation": "wait",
                "barrier": "issue_commit",
                "kind": "timeout",
                "process_pid": 123,
                "returncode": None,
            },
            "child_failure": None,
        }
        self.assertEqual(W.validated_parent_failure(json.dumps(base).encode()), base)
        for changed in (
            {**base, "status": "passed"},
            {**base, "diagnostic_only": False},
            {**base, "body": "inert"},
            {**base, "parent_observation": {**base["parent_observation"], "child": "foreign"}},
            {**base, "parent_observation": {**base["parent_observation"], "process_pid": True}},
            {**base, "parent_observation": {**base["parent_observation"], "returncode": False}},
            {**base, "parent_observation": {**base["parent_observation"], "operation": "send"}},
            {**base, "parent_observation": {**base["parent_observation"], "barrier": "different"}},
        ):
            with self.assertRaises(W.GateError):
                W.validated_parent_failure(json.dumps(changed).encode())


if __name__ == "__main__":
    unittest.main()
