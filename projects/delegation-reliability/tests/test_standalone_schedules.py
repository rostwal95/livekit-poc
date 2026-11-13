"""Meaningful public-example ownership checks; durable behavior has a lab gate."""

import asyncio
import base64
import contextlib
import csv
import hashlib
import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from continuity_lab.case_control_api import CaseControlIdentity
from delegation_reliability import ActionBinding, CompletionError
from delegation_reliability.contracts import Scope

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


load("policy_completion", EXAMPLES / "policy_completion.py")
EXAMPLE = load("p3_standalone_example", EXAMPLES / "standalone_policy.py")


class Owner:
    def __init__(self, *, release=None, failure=None):
        self.release = release
        self.failure = failure
        self.entered = asyncio.Event()
        self.settled = asyncio.Event()
        self.calls = 0

    @property
    def pending_count(self):
        return int(self.entered.is_set() and not self.settled.is_set())

    async def close(self):
        self.calls += 1
        self.entered.set()
        self.settled.clear()
        try:
            if self.release is not None:
                await self.release.wait()
            if self.failure is not None:
                error, self.failure = self.failure, None
                raise error
        finally:
            self.settled.set()


def application(owners):
    return EXAMPLE.StandaloneApplication(
        (owners[0], owners[1]), owners[4], owners[3], owners[2], owners[5]
    )


class StandaloneOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_independent_dependents_close_concurrently_before_shared_readers(self):
        release = asyncio.Event()
        owners = [Owner(release=release) for _ in range(4)] + [Owner(), Owner()]
        app = application(owners)
        closing = asyncio.create_task(app.close())
        try:
            for owner in owners[:4]:
                await asyncio.wait_for(owner.entered.wait(), 1)
            self.assertFalse(owners[4].entered.is_set())
            self.assertFalse(owners[5].entered.is_set())
            self.assertEqual(app.pending_count, 4)
            self.assertFalse(app.cleanup_complete)
        finally:
            release.set()
            await closing
        self.assertTrue(app.cleanup_complete)
        self.assertEqual(app.pending_count, 0)
        self.assertEqual([o.calls for o in owners], [1] * 6)

    async def test_cancelled_close_waiter_retains_actual_cleanup_and_rejects_new_work(self):
        release = asyncio.Event()
        owners = [Owner(release=release)] + [Owner() for _ in range(5)]
        app = application(owners)
        waiter = asyncio.create_task(app.close())
        try:
            await asyncio.wait_for(owners[0].entered.wait(), 1)
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
            self.assertFalse(app.cleanup_complete)
            self.assertEqual(app.pending_count, 1)
            with self.assertRaises(EXAMPLE.StandaloneClosedError):
                await app.inspect(str(uuid4()))
            with self.assertRaises(EXAMPLE.StandaloneClosedError):
                await app.complete(
                    None,
                    confirmation=None,
                    execution_command_id="issue",
                    confirmation_command_id="confirmation",
                )
        finally:
            release.set()
            await app.close()
        self.assertEqual([o.calls for o in owners], [1] * 6)
        self.assertTrue(app.cleanup_complete)

    async def test_timeout_does_not_claim_close_or_release_held_owner(self):
        release = asyncio.Event()
        owners = [Owner(release=release)] + [Owner() for _ in range(5)]
        app = application(owners)
        try:
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(app.close(), 0.02)
            self.assertEqual(app.pending_count, 1)
            self.assertFalse(app.cleanup_complete)
        finally:
            release.set()
            await app.close()
        self.assertEqual(app.pending_count, 0)
        self.assertEqual([o.calls for o in owners], [1] * 6)

    async def test_first_close_failure_preserves_independent_attempts_and_later_retry(self):
        original = RuntimeError("original_safe_failure")
        owners = [Owner(failure=original), Owner(), Owner(failure=ValueError("later"))]
        owners += [Owner(), Owner(), Owner()]
        app = application(owners)
        with self.assertRaises(RuntimeError) as raised:
            await app.close()
        self.assertIs(raised.exception, original)
        self.assertEqual([o.calls for o in owners], [1, 1, 1, 1, 0, 0])
        self.assertFalse(app.cleanup_complete)
        self.assertEqual(app.pending_count, 0)
        await app.close()
        self.assertTrue(app.cleanup_complete)
        self.assertEqual([o.calls for o in owners], [2, 2, 2, 2, 1, 1])
        await app.close()
        self.assertEqual([o.calls for o in owners], [2, 2, 2, 2, 1, 1])

    async def test_shared_work_client_is_rejected_before_any_port_operation(self):
        same = object()
        with self.assertRaises(EXAMPLE.StandaloneConfigurationError):
            EXAMPLE.configure_standalone(
                scope=Scope("tenant_unit", "account_unit"),
                owner_id=str(uuid4()),
                work_clients=(same, same),
                execution=object(),
                specialist=object(),
                case_client=object(),
                deliveries=object(),
                receiver=object(),
                actions=object(),
                evidence=(),
                action_bindings=(),
                delivery_bindings=(),
            )

    async def test_counted_specialist_uses_public_observed_port_and_owns_close(self):
        fixture = load(
            "p3_standalone_observed_adapter_units",
            Path(__file__).with_name("pg_standalone_cases.py"),
        )
        observation, request = object(), object()
        actual = SimpleNamespace(
            invoke_observed=AsyncMock(return_value=observation),
            invoke=AsyncMock(side_effect=AssertionError("unobserved_method_used")),
            close=AsyncMock(),
        )
        entries = []
        adapter = fixture.CountedSpecialist(actual, SimpleNamespace(add=entries.append))
        self.assertIs(await adapter.invoke_observed(request), observation)
        actual.invoke_observed.assert_awaited_once_with(request)
        actual.invoke.assert_not_called()
        self.assertEqual(entries, ["invoke"])
        await adapter.close()
        actual.close.assert_awaited_once()

    async def test_real_exact_case_adapter_rejects_wrong_actor_before_submission(self):
        binding = ActionBinding("case_unit", str(uuid4()), str(uuid4()), "actor", "scope", "case")
        client = SimpleNamespace(identity=CaseControlIdentity("foreign_actor", "scope", "case"))
        with self.assertRaisesRegex(CompletionError, "^unauthorized$"):
            EXAMPLE.configure_standalone(
                scope=Scope("tenant_unit", "account_unit"),
                owner_id=str(uuid4()),
                work_clients=(object(), object()),
                execution=object(),
                specialist=object(),
                case_client=client,
                deliveries=object(),
                receiver=object(),
                actions=object(),
                evidence=(),
                action_bindings=(binding,),
                delivery_bindings=(),
            )


class ReaderOwner(Owner):
    def __init__(self):
        super().__init__()
        self.closed = False
        self.reads = 0

    def late_read(self):
        if self.closed:
            raise AssertionError("shared_reader_closed_before_actual_settlement")
        self.reads += 1

    async def close(self):
        await super().close()
        self.closed = True


class RetainedOwner:
    """A real held asyncio task outlives its finite close observation."""

    def __init__(self, reader):
        self.release = asyncio.Event()
        self.calls = 0
        self.reader = reader
        self.actual = asyncio.create_task(self.run())

    async def run(self):
        await self.release.wait()
        self.reader.late_read()

    @property
    def pending_count(self):
        return int(not self.actual.done())

    async def close(self):
        self.calls += 1
        try:
            async with asyncio.timeout(0.02):
                await asyncio.shield(self.actual)
        except TimeoutError:
            raise CompletionError("cleanup_incomplete") from None


class RetainedDependencyTests(unittest.IsolatedAsyncioTestCase):
    async def exercise_retained_tier(self, index):
        reader = ReaderOwner()
        retained = RetainedOwner(reader)
        owners = [Owner() for _ in range(6)]
        owners[index] = retained
        owners[4 if index == 0 else 5] = reader
        app = application(owners)
        try:
            for _ in range(2):
                with self.assertRaisesRegex(CompletionError, "^cleanup_incomplete$"):
                    await app.close()
                self.assertEqual(app.pending_count, 1)
                self.assertFalse(app.cleanup_complete)
                self.assertFalse(reader.closed)
                self.assertFalse(retained.actual.cancelled())
                self.assertEqual(owners[5].calls, 0)
                if index == 0:
                    self.assertEqual(owners[4].calls, 0)
            self.assertEqual(retained.calls, 2)
            retained.release.set()
            await retained.actual
            self.assertEqual(reader.reads, 1)
            await app.close()
            self.assertTrue(app.cleanup_complete)
            self.assertTrue(reader.closed)
            self.assertEqual(retained.calls, 3)
            self.assertEqual(app.pending_count, 0)
        finally:
            retained.release.set()
            await asyncio.gather(retained.actual, return_exceptions=True)
            await app.close()

    async def test_incomplete_dependent_retains_shared_readers_until_late_work_and_retry(self):
        await self.exercise_retained_tier(0)

    async def test_incomplete_runner_retains_case_reader_until_actual_settlement(self):
        await self.exercise_retained_tier(4)


class ArtifactBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = load(
            "p3_standalone_gate_units",
            Path(__file__).resolve().parents[3] / "local-setup/scripts/p3_package_check.py",
        )

    def wheel(self, folder, *, changed=False, missing_dependency=False):
        member = folder / "member"
        member.mkdir()
        (member / "README.md").write_bytes(b"Exact public guide.\n")
        (member / "pyproject.toml").write_text(
            '[project]\nname="demo-pkg"\nversion="0.1.0"\ndependencies=["h11==0.16.0"]\n'
        )
        prefix = "demo_pkg-0.1.0.dist-info/"
        body = {"demo_pkg/__init__.py": b"x=1\n", "demo_pkg/py.typed": b""}
        files = {
            **body,
            prefix
            + "METADATA": b"Metadata-Version: 2.4\nName: demo-pkg\nVersion: 0.1.0\nRequires-Python: >=3.14,<3.15\n"
            + (b"" if missing_dependency else b"Requires-Dist: h11==0.16.0\n")
            + b"\nExact public guide.\n",
            prefix + "WHEEL": b"Wheel-Version: 1.0\n",
            prefix + "top_level.txt": b"demo_pkg\n",
        }
        record = io.StringIO()
        writer = csv.writer(record, lineterminator="\n")
        for name, data in files.items():
            writer.writerow(
                (
                    name,
                    "sha256="
                    + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode(),
                    len(data),
                )
            )
        writer.writerow((prefix + "RECORD", "", ""))
        files[prefix + "RECORD"] = record.getvalue().encode()
        if changed:
            files["demo_pkg/__init__.py"] = b"x=2\n"
        path = folder / "demo.whl"
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        return path, member, body

    def test_exact_wheel_record_readme_and_declared_dependency(self):
        with tempfile.TemporaryDirectory() as temp:
            path, member, expected = self.wheel(Path(temp))
            self.gate._wheel(path, member, "demo_pkg", expected)

    def test_changed_wheel_payload_rejects_even_with_same_size(self):
        with tempfile.TemporaryDirectory() as temp:
            path, member, expected = self.wheel(Path(temp), changed=True)
            with self.assertRaises(self.gate.GateError):
                self.gate._wheel(path, member, "demo_pkg", expected)

    def test_undeclared_missing_wheel_requirement_rejects(self):
        with tempfile.TemporaryDirectory() as temp:
            path, member, expected = self.wheel(Path(temp), missing_dependency=True)
            with self.assertRaises(self.gate.GateError):
                self.gate._wheel(path, member, "demo_pkg", expected)

    def test_archive_traversal_duplicate_and_finite_unpacked_bounds(self):
        for entries in [
            [("../outside", 1)],
            [("/outside", 1)],
            [("a\\b", 1)],
            [("a", 1), ("a", 1)],
            [("a", 524289)],
            [(str(i), 524288) for i in range(17)],
            [(str(i), 0) for i in range(513)],
        ]:
            with self.subTest(entries=entries[:1]), self.assertRaises(self.gate.GateError):
                self.gate._archive_entries(entries)
        self.gate._archive_entries([("package/one.py", 524288), ("package/py.typed", 0)])

    def test_retained_index_binds_nested_summary_and_empty_capture(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp:
            directory = Path(temp)
            directory.chmod(0o700)
            self.gate._write(directory / "package/summary.json", b'{"status":"passed"}\n')
            self.gate._write(directory / "commands/stdout.bin", b"")
            files = {
                str(p.relative_to(directory)): {
                    "bytes": p.stat().st_size,
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                }
                for p in directory.rglob("*")
                if p.is_file()
            }
            raw = json.dumps({"schema_version": 1, "files": files}).encode()
            self.gate._write(directory / "retained-index.json", raw)
            self.gate.validate_retained_index(directory, hashlib.sha256(raw).hexdigest())
            (directory / "package/summary.json").write_bytes(b'{"status":"failed"}\n')
            with self.assertRaises(self.gate.GateError):
                self.gate.validate_retained_index(directory, hashlib.sha256(raw).hexdigest())

    def test_inventory_framing_and_caps(self):
        self.assertNotEqual(
            self.gate.inventory_digest([{"a": "bc"}]),
            self.gate.inventory_digest([{"a": "b"}, {"c": ""}]),
        )
        for records in ([], [{}] * 65, [{"value": "x" * 4096}], [{"v": "x" * 4000}] * 17):
            with self.assertRaises(self.gate.GateError):
                self.gate.inventory_digest(records)

    def test_build_uses_exact_host_interpreter_with_closed_child_path(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temp:
            gate = object.__new__(self.gate.PackageRun)
            gate.root, gate.work = Path("/synthetic-root"), Path(temp)
            observed = []

            def command(argv, *, stage):
                observed.append(argv)
                (gate.work / "output" / "one.whl").write_bytes(b"synthetic-only")

            with patch.object(gate, "command", side_effect=command):
                gate.build(Path("/member"), "output", "--wheel", stage="build_p1")
            self.assertEqual(len(observed), 1)
            index = observed[0].index("--python")
            self.assertEqual(observed[0][index + 1], sys.executable)
            self.assertIn("--offline", observed[0])
            self.assertIn("--no-sources", observed[0])

    def test_shipped_example_telemetry_precedes_one_exact_terminal_verdict(self):
        telemetry = [
            {
                "component": "delegation_specialist",
                "event": "attempt_started",
                "operation": "invoke",
                "code": "ok",
            },
            {
                "component": "delegation_specialist",
                "event": "attempt_finished",
                "operation": "invoke",
                "code": "ok",
            },
            {
                "component": "delegation_specialist",
                "event": "closed",
                "operation": "http",
                "code": "ok",
            },
        ]
        final = {
            "status": "passed",
            "mode": "local_scripted_http",
            "capability": "booking.evaluate_policy",
            "result": "candidate",
            "eligible": True,
            "business_action": "not_authorized",
            "durable_acceptance": False,
            "cleanup_complete": True,
        }

        def encoded(values):
            return ("\n".join(json.dumps(value) for value in values) + "\n").encode()

        self.assertEqual(self.gate.validate_node_example(encoded([*telemetry, final])), final)
        for rows in (
            [final],
            [*telemetry, final, final],
            [*reversed(telemetry), final],
            [*telemetry, {**final, "eligible": "true"}],
            [{**telemetry[0], "private_headers": "synthetic-denied"}, *telemetry[1:], final],
            [*telemetry, {**final, "cleanup_complete": False}],
        ):
            with self.subTest(rows=rows), self.assertRaises(self.gate.GateError):
                self.gate.validate_node_example(encoded(rows))

    def service_proof(self):
        return {
            "schema_version": 1,
            "status": "closed",
            "node_version": "24.22.2",
            "invoked": 1,
            "strict_completed": 1,
            "active": 0,
            "requests": 0,
            "sockets": 0,
            "request_sha256": "a" * 64,
            "wire_attempt_id": "attempt_" + "1" * 32,
            "scope": {"tenant_id": "tenant_standalone", "account_id": "account_standalone"},
        }

    def test_service_wire_requires_canonical_file_plus_one_stdout_newline(self):
        proof = self.service_proof()
        raw = json.dumps(proof, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        self.assertEqual(self.gate.validate_service_observation(raw + b"\n", raw), proof)
        for stdout, stored in (
            (raw, raw),
            (raw + b"\n\n", raw),
            (raw + b"\n{}\n", raw),
            (raw + b"\n", json.dumps(proof, indent=2).encode()),
            (raw + b"\n", raw.replace(b'"active":0', b'"active":1')),
        ):
            with self.subTest(stdout=stdout[-10:]), self.assertRaises(self.gate.GateError):
                self.gate.validate_service_observation(stdout, stored)

    def test_real_parent_service_finish_uses_shared_wire_guard_and_retains_failure(self):
        raw = json.dumps(
            self.service_proof(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            folder = Path(temporary)
            folder.chmod(0o700)
            self.gate._write(folder / "standalone-service.json", raw)
            run = object.__new__(self.gate.PackageRun)
            run.lab_folder = folder
            run.remaining = lambda: 10
            peer = SimpleNamespace(
                wait=lambda **kw: SimpleNamespace(returncode=0),
                close=lambda: None,
                cleanup_failed=False,
            )
            run.capture = lambda child: (raw + b"\n", b"")
            failures = []
            run.failure_context = lambda mode, child: failures.append((mode, child))
            with patch.object(
                self.gate,
                "validate_service_observation",
                wraps=self.gate.validate_service_observation,
            ) as validator:
                run.finish_service(peer)
                validator.assert_called_once_with(raw + b"\n", raw)
            self.assertEqual(run.stage, "lab_server")
            self.assertEqual(failures, [])
            run.capture = lambda child: (raw, b"")
            with self.assertRaises(self.gate.GateError):
                run.finish_service(peer)
            self.assertEqual(failures, [("node", peer)])

    def test_owner_source_query_derives_exact_scoped_cancellation_without_fake_column(self):
        fixture = load(
            "p3_standalone_source_query_units", Path(__file__).with_name("pg_standalone_cases.py")
        )
        with contextlib.closing(sqlite3.connect(":memory:")) as database, database:
            database.row_factory = sqlite3.Row
            database.executescript(
                "CREATE TABLE accepted_work(work_id TEXT,tenant_id TEXT,account_id TEXT); CREATE TABLE attempt_results(work_id TEXT,tenant_id TEXT,account_id TEXT,attempt_id TEXT,body BLOB,sha256 TEXT,recorded_at_ms INTEGER,disposition TEXT); CREATE TABLE issued_attempts(work_id TEXT,tenant_id TEXT,account_id TEXT,attempt_id TEXT,command_id TEXT,owner_id TEXT,number INTEGER,epoch INTEGER); CREATE TABLE result_feed_events(work_id TEXT,tenant_id TEXT,account_id TEXT,attempt_id TEXT,event_id TEXT,sequence INTEGER); CREATE TABLE cancellation_commands(work_id TEXT,tenant_id TEXT,account_id TEXT);"
            )
            key = ("work", "tenant", "account")
            database.execute("INSERT INTO accepted_work VALUES(?,?,?)", key)
            database.execute(
                "INSERT INTO attempt_results VALUES(?,?,?,?,?,?,?,?)",
                (*key, "attempt", b"result", "hash", 1, "eligible_at_commit"),
            )
            database.execute(
                "INSERT INTO issued_attempts VALUES(?,?,?,?,?,?,?,?)",
                (*key, "attempt", "command", "owner", 1, 1),
            )
            database.execute(
                "INSERT INTO result_feed_events VALUES(?,?,?,?,?,?)", (*key, "attempt", "event", 1)
            )
            query = fixture.source_query("main").as_string()
            self.assertEqual(database.execute(query).fetchone()["cancel_requested"], 0)
            for wrong in (
                ("other", "tenant", "account"),
                ("work", "foreign", "account"),
                ("work", "tenant", "foreign"),
            ):
                database.execute("INSERT INTO cancellation_commands VALUES(?,?,?)", wrong)
                self.assertEqual(database.execute(query).fetchone()["cancel_requested"], 0)
            database.execute("INSERT INTO cancellation_commands VALUES(?,?,?)", key)
            self.assertEqual(database.execute(query).fetchone()["cancel_requested"], 1)
            self.assertNotIn(
                "cancel_requested",
                [row[1] for row in database.execute("PRAGMA table_info(accepted_work)")],
            )

    def test_owner_helper_cannot_load_in_any_public_consumer_mode(self):
        fixture = load(
            "p3_standalone_fixture_units", Path(__file__).with_name("pg_standalone_cases.py")
        )
        for mode in ("complete", "metadata", "negative", "replay", "cancel"):
            fixture.MODE = mode
            with self.assertRaisesRegex(ValueError, "owner_helper_forbidden"):
                fixture.helper()


class PendingChild:
    def __init__(self, pid, *, pending):
        self.pid = pid
        self.returncode = None if pending else 0
        self.cleanup_failed = False
        self.close_calls = 0

    def close(self):
        self.close_calls += 1
        if self.returncode is None:
            raise RuntimeError("synthetic_close_not_settled")


class ParentCleanupTests(unittest.TestCase):
    def setUp(self):
        self.gate = ArtifactBoundaryTests.gate
        self.temp = tempfile.TemporaryDirectory(
            prefix="phase38-parent-cleanup-", dir="/private/tmp"
        )
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.folder.chmod(0o700)
        self.work_temp = tempfile.TemporaryDirectory(
            prefix="p3-standalone-package-", dir="/private/tmp"
        )
        self.addCleanup(self.work_temp.cleanup)
        self.work = Path(self.work_temp.name)
        self.work.chmod(0o700)
        self.gate._write(self.work / "owned-marker", b"p3-standalone-package-v1\n")

    def configured(self, pending=True):
        run = object.__new__(self.gate.PackageRun)
        run.children = [PendingChild(101, pending=pending), PendingChild(102, pending=False)]
        run.work = self.work
        run.retained = self.folder / "evidence"
        run.retained.mkdir(mode=0o700)
        run.capture = lambda child: (b"", b"")
        run.lab_started = True
        run.lab_cleaned = False
        events = []

        def cleanup_lab():
            events.append("DDL")
            run.lab_cleaned = True

        run.cleanup_lab = cleanup_lab
        return run, events

    def test_actual_main_withholds_DDL_and_work_removal_preserves_primary_then_reap_allows_cleanup(
        self,
    ):
        run, events = self.configured()
        original = self.gate.GateError("consumer_failed")

        def offline():
            raise original

        run.offline = offline
        run.stage = "lab_complete"
        run.started = time.monotonic()
        run.passed = set()
        report = Path(".local/validation/p3-package/pending.json")
        with (
            patch.object(self.gate, "PackageRun", return_value=run),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            status = self.gate.main(["--lab", "--report", str(report)], root=self.folder)
        value = json.loads((self.folder / report).read_bytes())
        self.assertEqual(status, 1)
        self.assertEqual(value["code"], "consumer_failed")
        self.assertFalse(value["cleanup_complete"])
        self.assertEqual(events, [])
        self.assertEqual([child.close_calls for child in run.children], [1, 1])
        self.assertTrue((self.work / "owned-marker").is_file())
        observation = json.loads((run.retained / "unresolved-work.json").read_bytes())
        self.assertEqual(observation["work_directory"], str(self.work))
        self.assertIsNone(observation["children"][0]["returncode"])
        run.children[0].returncode = -9
        run.cleanup_resources()
        self.assertEqual(events, ["DDL"])
        self.assertFalse(self.work.exists())
        # The first report remains an immutable failed observation.
        self.assertFalse(json.loads((self.folder / report).read_bytes())["cleanup_complete"])

    def test_cleanup_failed_flag_with_exit_code_does_not_claim_settlement(self):
        run, events = self.configured(pending=False)
        run.children[0].cleanup_failed = True
        with self.assertRaises(self.gate.GateError):
            run.cleanup_resources()
        self.assertEqual(events, [])
        self.assertTrue(self.work.exists())
        self.assertFalse(run.children_settled())

    def test_failed_owner_cleanup_preserves_work_marker_for_explicit_reconciliation(self):
        run, _events = self.configured(pending=False)
        original = RuntimeError("synthetic_owner_cleanup_failed")

        def cleanup():
            raise original

        run.cleanup_lab = cleanup
        with self.assertRaises(RuntimeError) as caught:
            run.cleanup_resources()
        self.assertIs(caught.exception, original)
        self.assertTrue((self.work / "owned-marker").is_file())
        self.assertTrue((run.retained / "unresolved-work.json").is_file())


if __name__ == "__main__":
    unittest.main()
