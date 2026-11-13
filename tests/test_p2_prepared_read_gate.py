"""Pure parent lifecycle/proof controls; no subprocess, PG, compiler or provider runs."""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "prepared_read_gate_tested", ROOT / "local-setup/scripts/p2_prepared_read_check.py"
)
assert SPEC is not None and SPEC.loader is not None
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


class FakeChild:
    next_pid = 10000

    def __init__(self, argv, *, cwd, env, output_directory, max_output_bytes, final_deadline):
        self.pid = FakeChild.next_pid
        FakeChild.next_pid += 1
        self.argv, self.env, self.max_output_bytes = argv, env, max_output_bytes
        self.returncode, self.group_settled, self.cleanup_failed = None, False, False
        self.output_directory = output_directory
        output_directory.mkdir(mode=0o700)
        for name, raw in (
            ("stdout.bin", b""),
            ("stderr.bin", b""),
            ("process-group.pid", str(self.pid).encode()),
        ):
            (output_directory / name).write_bytes(raw)
            (output_directory / name).chmod(0o600)

    def wait(self, timeout):
        self.returncode = 0
        return SimpleNamespace(returncode=0)

    def close(self):
        self.returncode, self.group_settled = 0, True


class GuardTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name).resolve()
        self.directory.chmod(0o700)

    def test_plan_is_inert_and_preserves_exact_declared_schedule(self):
        output = io.StringIO()
        with (
            patch.object(m, "run", side_effect=AssertionError("NO_RUN")),
            patch.object(m.core, "load_setup", side_effect=AssertionError("NO_SETTINGS")),
            patch.object(m, "private_report", side_effect=AssertionError("NO_FILES")),
            patch.object(m, "private_group_owner", side_effect=AssertionError("NO_GROUP")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(m.main(["--plan"]), 0)
        value = json.loads(output.getvalue())
        self.assertEqual(value["commands"], list(m.ROLES))
        self.assertEqual(
            (
                len(value["assertions"]),
                value["expected_process_groups"],
                value["max_process_groups"],
            ),
            (8, 5, 8),
        )
        self.assertEqual(
            (value["deadline_seconds"], value["business_seconds"], value["cleanup_seconds"]),
            (180, 160, 20),
        )
        self.assertEqual(
            (value["stream_bytes"], value["aggregate_capture_bytes"]), (65536, 1048576)
        )
        self.assertEqual(
            (
                value["schemas"],
                value["scheduled_owned_sigkills"],
                value["rtc_rooms"],
                value["p1_calls"],
            ),
            (1, 0, 0, 0),
        )
        self.assertFalse(value["provider_calls"])
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_unknown_cli_and_hostile_exception_getters_never_expose_private_text(self):
        class Hostile(RuntimeError):
            @property
            def code(self):
                raise AssertionError("PRIVATE_GETTER")

        self.assertEqual(m.finite_code(Hostile("PRIVATE_BODY")), "component_failed")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(m.main(["--PRIVATE_SECRET"]), 1)
        self.assertNotIn("PRIVATE", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["code"], "invalid_input")

    def test_finite_codes_contain_non_strings_and_overwritten_error_state(self):
        for code in ([], {}, None, 1, True):
            error = m.PreparedGateError(code)
            self.assertEqual((str(error), m.finite_code(error)), ("invalid_proof", "invalid_proof"))
            error.code = code
            self.assertEqual(m.finite_code(error), "component_failed")
        self.assertEqual(m.finite_code(m.PreparedGateError("source_changed")), "source_changed")

    def test_sql_holder_closed_requires_connection_and_transaction_release(self):
        holder = m.SqlHolder(SimpleNamespace())
        self.assertTrue(holder.closed)

        class Connection:
            fail = True

            def close(self):
                if self.fail:
                    raise RuntimeError("PRIVATE_CONNECTION_CLOSE")

        class Transaction:
            def __exit__(self, *_args):
                raise RuntimeError("PRIVATE_TRANSACTION_CLOSE")

        connection = Connection()
        holder.connection, holder.transaction = connection, Transaction()
        with self.assertRaises(RuntimeError):
            holder.close()
        self.assertFalse(holder.closed)
        self.assertIs(holder.connection, connection)
        self.assertIsNotNone(holder.transaction)
        connection.fail = False
        with self.assertRaises(RuntimeError):
            holder.close()
        self.assertTrue(holder.closed)
        holder.transaction = Transaction()
        self.assertFalse(holder.closed)

    def test_child_base_environment_never_reads_or_forwards_unrelated_selectors(self):
        env = {
            "PATH": "/pinned/bin",
            "LANG": "en_US.UTF-8",
            "OPENAI_API_KEY": "PRIVATE_KEY",
            "PGSERVICE": "PRIVATE_DB",
            "HTTPS_PROXY": "PRIVATE_PROXY",
            "HOME": "PRIVATE_HOME",
        }
        with patch.dict(m.os.environ, env, clear=True):
            value = m.base_environment()
        self.assertEqual(
            value, {"PATH": "/pinned/bin", "LANG": "en_US.UTF-8", "CI": "1", "NO_COLOR": "1"}
        )

    def test_private_owner_limits_do_not_mutate_canonical_helper_and_share_both_registries(self):
        before = (m.starter.MAX_CHILDREN, m.starter.MAX_STREAM_BYTES, m.starter.MAX_CAPTURE_BYTES)
        groups = m.Groups(self.directory, time.monotonic() + 1, time.monotonic() + 2)
        self.assertEqual(
            (
                groups.module.MAX_CHILDREN,
                groups.module.MAX_STREAM_BYTES,
                groups.module.MAX_CAPTURE_BYTES,
            ),
            (8, 65536, 1048576),
        )
        self.assertIs(type(groups.business), groups.module.Children)
        self.assertIs(type(groups.cleanup), groups.module.Children)
        self.assertEqual(
            (m.starter.MAX_CHILDREN, m.starter.MAX_STREAM_BYTES, m.starter.MAX_CAPTURE_BYTES),
            before,
        )
        self.assertIsNot(groups.module, m.starter)

    def test_business_deadline_is_not_renewed_for_cleanup_role_and_caps_remain_combined(self):
        groups = m.Groups(self.directory, time.monotonic() - 1, time.monotonic() + 5)
        with (
            patch.object(groups.module, "GroupedOwnedProcess", FakeChild),
            self.assertRaises(groups.module.GateError),
        ):
            groups.start("setup", ["/fake/node"], {}, self.directory)
        # Private and canonical helper error identities intentionally differ.

    def test_cleanup_registry_can_start_after_business_deadline_with_unchanged_final(self):
        now = time.monotonic()
        groups = m.Groups(self.directory, now - 1, now + 5)
        with patch.object(groups.module, "GroupedOwnedProcess", FakeChild):
            child = groups.start("cleanup", ["/fake/node"], {}, self.directory)
            self.assertEqual(child.max_output_bytes, 65536)
            groups.finish("cleanup")
        self.assertEqual(groups.business.deadline, now - 1)
        self.assertEqual(groups.cleanup.deadline, now + 5)
        self.assertTrue(groups.settled())
        groups.business.captured = 1048577
        with self.assertRaises(m.PreparedGateError):
            groups.capture_budget()

    def test_only_exact_owned_work_can_be_removed_and_aliases_remain(self):
        scratch = self.directory / "scratch"
        scratch.mkdir(mode=0o700)
        work = scratch / "run-owned"
        work.mkdir(mode=0o700)
        marker = {"schema_version": 1, "schema": "p2_prepared_" + "a" * 32, "work_id": "x"}
        m.publish(work / "prepared-owned-work.json", marker)
        with self.assertRaises(m.PreparedGateError):
            m.remove_owned_work(work, scratch, marker, authorized=False)
        foreign = self.directory / "foreign"
        foreign.write_bytes(b"original")
        foreign.chmod(0o600)
        (work / "alias").symlink_to(foreign)
        with self.assertRaises(m.starter.GateError):
            m.remove_owned_work(work, scratch, marker, authorized=True)
        self.assertEqual(foreign.read_bytes(), b"original")
        (work / "alias").unlink()
        m.remove_owned_work(work, scratch, marker, authorized=True)
        self.assertFalse(work.exists())
        self.assertTrue(foreign.exists())

    def test_saved_bundle_validator_consumes_exact_persisted_bytes(self):
        path = self.directory / "bundle.json"
        original = {"schema_version": 1, "value": 1}
        m.publish(path, original)
        original["value"] = 2
        observed = []

        def oracle(value):
            observed.append(value)
            return {case: {"status": "passed", "code": "ok"} for case in m.CASES}

        with patch.object(m, "validate_bundle", side_effect=oracle):
            self.assertEqual(len(m.validate_saved_bundle(path)), 8)
        self.assertEqual(observed, [{"schema_version": 1, "value": 1}])

    def test_pg_graph_retains_roles_from_both_actual_query_results_without_hardcoding(self):
        schema = "p2_prepared_" + "a" * 32
        holder_pid, waiter_pid = 6001, 6002

        class Result:
            def __init__(self, value):
                self.value = value

            def fetchall(self):
                return self.value

        class Connection:
            def __init__(self, owner=False):
                self.owner = owner

            def close(self):
                pass

            def execute(self, query, parameters):
                if self.owner:
                    return Result(
                        [
                            {
                                "pid": holder_pid,
                                "usename": "measured_owner",
                                "query": 'LOCK TABLE "'
                                + schema
                                + '"."dispatch_plans" IN ACCESS EXCLUSIVE MODE',
                                "state": "idle in transaction",
                                "application_name": "continuity-test",
                            }
                        ]
                    )
                if "SELECT pid,usename" in query:
                    return Result(
                        [
                            {
                                "pid": waiter_pid,
                                "usename": "measured_runtime",
                                "blockers": [holder_pid],
                                "query": "SELECT payload_json FROM " + schema + ".dispatch_plans",
                                "wait_event_type": "Lock",
                            }
                        ]
                    )
                return Result(
                    [
                        {
                            "pid": pid,
                            "relation_oid": 5001,
                            "schema_name": schema,
                            "table_name": "dispatch_plans",
                            "locktype": "relation",
                            "mode": mode,
                            "granted": granted,
                        }
                        for pid, mode, granted in (
                            (holder_pid, "AccessExclusiveLock", True),
                            (waiter_pid, "AccessShareLock", False),
                        )
                    ]
                )

        observer = SimpleNamespace(schema=schema, connect=lambda **_kwargs: Connection())
        holder = SimpleNamespace(
            pid=holder_pid,
            settings=SimpleNamespace(connect=lambda **_kwargs: Connection(owner=True)),
        )
        graph = m.wait_graph(observer, holder)
        self.assertEqual(graph["holder_usename"], "measured_owner")
        self.assertEqual(graph["waiters"][0]["usename"], "measured_runtime")
        from p2_prepared_read_evidence import PreparedReadEvidenceError
        from p2_prepared_read_evidence import graph as validate_graph

        with self.assertRaises(PreparedReadEvidenceError):
            validate_graph(graph, schema)

    def test_source_bindings_cover_all_program_profiles_and_change_with_config_or_example(self):
        baseline = m.source_snapshot(ROOT)
        configs = [
            "tsconfig.json",
            "tsconfig.examples.json",
            "tsconfig.starter.json",
            "tsconfig.pg.json",
            "tsconfig.test.json",
        ]
        for name in configs:
            self.assertIn("projects/channel-continuity/" + name, baseline)
        p1 = ROOT / "projects/agent-continuity/python"
        expected_p1 = (
            {path.relative_to(ROOT).as_posix() for path in (p1 / "src").rglob("*.py")}
            | {path.relative_to(ROOT).as_posix() for path in (p1 / "src").rglob("py.typed")}
            | {"projects/agent-continuity/python/pyproject.toml"}
        )
        self.assertTrue(expected_p1 <= set(baseline))
        self.assertIn(
            "projects/agent-continuity/python/src/continuity_lab/postgres_settings.py",
            baseline,
        )
        target_names = [
            "projects/agent-continuity/python/src/continuity_lab/postgres_settings.py",
            "projects/agent-continuity/python/pyproject.toml",
            "projects/channel-continuity/tsconfig.examples.json",
            "projects/channel-continuity/examples/standalone/external-http.ts",
        ]
        actual = Path.read_bytes
        for name in target_names:
            path = ROOT / name

            def changed(p, target=path):
                raw = actual(p)
                return raw + b"\n" if p == target else raw

            with patch.object(Path, "read_bytes", changed):
                after = m.source_snapshot(ROOT)
            self.assertNotEqual(after[name], baseline[name])
            self.assertEqual({k for k in after if after[k] != baseline[k]}, {name})


class AsyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name).resolve()
        self.directory.chmod(0o700)

    async def test_cancelled_offload_waiter_retains_actual_task_until_settlement(self):
        entered, release = threading.Event(), threading.Event()
        actions = m.Actions(time.monotonic() + 5, time.monotonic() + 6)

        def actual():
            entered.set()
            release.wait(2)
            return 7

        waiter = asyncio.create_task(actions.run(actual))
        try:
            await asyncio.to_thread(entered.wait, 1)
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
            self.assertEqual(len(actions.tasks), 1)
            self.assertFalse(next(iter(actions.tasks)).done())
            release.set()
            self.assertTrue(await actions.drain())
            self.assertEqual(next(iter(actions.tasks)).result(), 7)
        finally:
            release.set()

    async def test_task_registration_failure_closes_unscheduled_coroutine(self):
        actions = m.Actions(time.monotonic() + 1, time.monotonic() + 2)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", RuntimeWarning)
            with (
                patch.object(
                    m.asyncio, "create_task", side_effect=RuntimeError("PRIVATE_SCHEDULE")
                ),
                self.assertRaises(RuntimeError),
            ):
                await actions.run(lambda: 1)
        self.assertFalse(actions.tasks)
        self.assertFalse(any("never awaited" in str(item.message) for item in caught))

    async def test_expired_business_denies_callback_but_cleanup_uses_original_final(self):
        actions = m.Actions(time.monotonic() - 1, time.monotonic() + 2)
        called = []
        with self.assertRaises(m.PreparedGateError):
            await actions.run(lambda: called.append("business"))
        await actions.run(lambda: called.append("cleanup"), cleaning=True)
        self.assertEqual(called, ["cleanup"])

    async def test_atomic_two_link_marker_waits_only_until_owned_pending_removed(self):
        path = self.directory / "marker.json"
        pending = self.directory / "pending.json"
        m.publish(pending, {"schema_version": 1, "complete": True})
        os.link(pending, path)
        groups = SimpleNamespace(owners={"read": SimpleNamespace(returncode=None)})
        waiter = asyncio.create_task(m.wait_marker(groups, path, time.monotonic() + 1))
        await asyncio.sleep(0.01)
        self.assertFalse(waiter.done())
        pending.unlink()
        self.assertEqual(await waiter, {"schema_version": 1, "complete": True})

    async def test_malformed_or_unsafe_marker_fails_without_sleeping_or_retrying(self):
        path = self.directory / "marker.json"
        groups = SimpleNamespace(owners={"read": SimpleNamespace(returncode=None)})
        path.write_text('{"same":1,"same":2}')
        path.chmod(0o600)
        with (
            patch.object(m.asyncio, "sleep", side_effect=AssertionError("NO_RETRY")),
            self.assertRaises(m.PreparedGateError),
        ):
            await m.wait_marker(groups, path, time.monotonic() + 1)
        path.chmod(0o644)
        with self.assertRaises(m.PreparedGateError):
            await m.wait_marker(groups, path, time.monotonic() + 1)

    async def test_wrong_typed_caller_marker_releases_holder_without_observing_sql(self):
        trace = []
        holder = SimpleNamespace(
            acquire=lambda: trace.append("acquire"), close=lambda: trace.append("release")
        )

        async def marker(*_args):
            return {"schema_version": 1, "callerCount": True}

        async def no_graph(*_args):
            raise AssertionError("NO_GRAPH_AFTER_BAD_MARKER")

        with (
            patch.object(m, "wait_marker", side_effect=marker),
            patch.object(m, "observed_wait", side_effect=no_graph),
            self.assertRaises(m.PreparedGateError),
        ):
            await m.exercise_hold(
                m.Actions(time.monotonic() + 2, time.monotonic() + 3),
                SimpleNamespace(),
                holder,
                SimpleNamespace(),
                self.directory,
                time.monotonic() + 2,
                1001,
            )
        self.assertEqual(trace, ["acquire", "release"])
        self.assertTrue((self.directory / "prepared-hold-ready.json").exists())
        self.assertFalse((self.directory / "prepared-close-read.json").exists())

    async def test_graph_failure_remains_primary_when_holder_release_also_fails(self):
        original = m.PreparedGateError("invalid_proof")
        trace = []

        def release():
            trace.append("release")
            raise RuntimeError("PRIVATE_CLOSE")

        holder = SimpleNamespace(acquire=lambda: trace.append("acquire"), close=release)

        async def marker(*_args):
            return {"schema_version": 1, "callerCount": 1}

        async def bad_graph(*_args):
            raise original

        with (
            patch.object(m, "wait_marker", side_effect=marker),
            patch.object(m, "observed_wait", side_effect=bad_graph),
            self.assertRaises(m.PreparedGateError) as caught,
        ):
            await m.exercise_hold(
                m.Actions(time.monotonic() + 2, time.monotonic() + 3),
                SimpleNamespace(),
                holder,
                SimpleNamespace(),
                self.directory,
                time.monotonic() + 2,
                1001,
            )
        self.assertIs(caught.exception, original)
        self.assertEqual(trace, ["acquire", "release"])

    async def test_cleanup_attempts_independent_owners_and_metadata_failure_does_not_skip_schema_guard(
        self,
    ):
        trace = []

        def step(name, fail=False):
            def call():
                trace.append(name)
                if fail:
                    raise RuntimeError("PRIVATE_CLEANUP")

            return call

        holder = SimpleNamespace(close=step("holder", True), closed=True)
        groups = SimpleNamespace(
            close_business=step("business", True),
            close_cleanup=step("cleanup"),
            settled=lambda: True,
        )
        errors = await m.cleanup_owners(
            m.Actions(time.monotonic() + 1, time.monotonic() + 2),
            groups,
            holder,
            step("schema-guard"),
        )
        self.assertEqual(trace, ["holder", "business", "cleanup", "schema-guard", "cleanup"])
        self.assertEqual(errors, ["sql_holder", "business_groups"])

    async def test_retained_sql_holder_prevents_ddl_but_attempts_independent_group_cleanup(self):
        trace = []

        def fail_close():
            trace.append("holder")
            raise RuntimeError("PRIVATE_RETAINED_CONNECTION")

        holder = SimpleNamespace(close=fail_close, closed=False)
        groups = SimpleNamespace(
            close_business=lambda: trace.append("business"),
            close_cleanup=lambda: trace.append("cleanup"),
            settled=lambda: True,
        )
        errors = await m.cleanup_owners(
            m.Actions(time.monotonic() + 1, time.monotonic() + 2),
            groups,
            holder,
            lambda: trace.append("DDL"),
        )
        self.assertEqual(trace, ["holder", "business", "cleanup"])
        self.assertEqual(errors, ["sql_holder", "unresolved_owner_no_ddl"])

    async def test_closed_sql_holder_allows_schema_guard_and_final_cleanup_progress(self):
        trace = []
        holder = SimpleNamespace(close=lambda: trace.append("holder"), closed=True)
        groups = SimpleNamespace(
            close_business=lambda: trace.append("business"),
            close_cleanup=lambda: trace.append("cleanup"),
            settled=lambda: True,
        )
        errors = await m.cleanup_owners(
            m.Actions(time.monotonic() + 1, time.monotonic() + 2),
            groups,
            holder,
            lambda: trace.append("DDL"),
        )
        self.assertEqual(trace, ["holder", "business", "cleanup", "DDL", "cleanup"])
        self.assertEqual(errors, [])

    async def test_unsettled_group_prevents_schema_ddl_even_after_other_cleanup_attempts(self):
        trace = []
        groups = SimpleNamespace(
            close_business=lambda: trace.append("business"),
            close_cleanup=lambda: trace.append("cleanup"),
            settled=lambda: False,
        )
        errors = await m.cleanup_owners(
            m.Actions(time.monotonic() + 1, time.monotonic() + 2),
            groups,
            SimpleNamespace(close=lambda: trace.append("holder"), closed=True),
            lambda: trace.append("DDL"),
        )
        self.assertEqual(trace, ["holder", "business", "cleanup"])
        self.assertIn("unresolved_owner_no_ddl", errors)

    async def test_actual_parent_preserves_first_failure_and_private_work_when_cleanup_and_capture_fail(
        self,
    ):
        root = self.directory / "root"
        project = root / "projects/channel-continuity"
        compiler = project / "node_modules/typescript/bin/tsc"
        compiler.parent.mkdir(parents=True)
        compiler.write_bytes(b"inert")
        root.chmod(0o700)
        target = root / "report.json"
        trace = []

        class FakeGroups:
            def __init__(self, directory, deadline, final):
                self.directory, self.owners, self.sentinels = directory, {}, ()

            def start(self, role, argv, environment, cwd):
                self.owners[role] = FakeChild(
                    argv,
                    cwd=cwd,
                    env=environment,
                    output_directory=self.directory / role,
                    max_output_bytes=65536,
                    final_deadline=time.monotonic() + 10,
                )
                self.owners[role].returncode = 1
                self.owners[role].group_settled = True
                return self.owners[role]

            def finish(self, role):
                raise m.PreparedGateError("source_changed")

            def close_business(self):
                trace.append("business-close")
                raise RuntimeError("PRIVATE_CLEANUP")

            def close_cleanup(self):
                trace.append("cleanup-close")

            def settled(self):
                return True

            def capture_all(self):
                raise RuntimeError("PRIVATE_CAPTURE")

            def observation(self):
                return {
                    "schema_version": 1,
                    "groups": [
                        {
                            "role": role,
                            "pid": child.pid,
                            "returncode": child.returncode,
                            "group_settled": True,
                            "cleanup_failed": False,
                        }
                        for role, child in self.owners.items()
                    ],
                    "capture_bytes": 0,
                }

        values = {
            "POSTGRES_PORT": "15432",
            "POSTGRES_PASSWORD": "synthetic-runtime-" * 3,
            "POSTGRES_MIGRATION_PASSWORD": "synthetic-owner-" * 3,
        }
        with (
            patch.object(m, "Groups", FakeGroups),
            patch.object(
                m.core, "load_setup", return_value=SimpleNamespace(load_settings=lambda: values)
            ),
            patch.object(m.starter, "tool", return_value=Path("/fake/node")),
            patch.object(m.starter, "build_configurations", return_value=()),
            patch.object(m, "namespace", return_value=[]),
            patch.object(
                m, "relation_locks", side_effect=lambda _owner: trace.append("quiet") or 0
            ),
            patch.object(m, "source_snapshot", return_value={"source": "a" * 64}),
            patch.object(m, "remove_owned_work") as remove,
        ):
            result = await m.run(root, target)
        self.assertEqual(
            (result["status"], result["code"], result["failure_stage"]),
            ("failed", "source_changed", "compile-public"),
        )
        self.assertIn("business_groups", result["cleanup_errors"])
        self.assertIn("capture", result["cleanup_errors"])
        self.assertIn("quiet", trace)
        self.assertFalse(remove.called)
        self.assertTrue(result["work_directory_retained"])
        self.assertTrue(Path(result["work_directory"]).is_dir())
        self.assertEqual(m.read(target)["code"], "source_changed")
        self.assertNotIn("PRIVATE", target.read_text())


if __name__ == "__main__":
    unittest.main()
