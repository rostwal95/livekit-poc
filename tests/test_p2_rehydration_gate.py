"""Independent malformed-boundary and evidence-integrity checks; no PG or providers."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "local-setup/scripts"
sys.path.insert(0, str(SCRIPTS))
import p2_rehydration_check as gate


class RehydrationGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name).resolve()
        self.common = {
            "P2_REHYDRATION_DIRECTORY": str(self.directory),
            "P2_REHYDRATION_SCHEMA": "p2_rehydration_" + "a" * 32,
            "P2_REHYDRATION_PG_PORT": "15432",
        }
        self.values = {
            "POSTGRES_PASSWORD": "runtime-only-synthetic",
            "POSTGRES_MIGRATION_PASSWORD": "owner-only-synthetic",
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_owner_and_runtime_never_forward_other_role_or_provider(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sentinel",
                "HTTPS_PROXY": "sentinel",
                "NODE_OPTIONS": "sentinel",
                "P2_REHYDRATION_OWNER_PASSWORD": "ambient",
            },
        ):
            for mode in (
                "install",
                "verify",
                "cleanup",
                "seed",
                "expiry",
                "revocation",
                "replay",
                "media-serve",
                "media-sms",
            ):
                env = gate.child_environment(self.values, self.common, mode)
                self.assertNotIn("OPENAI_API_KEY", env)
                self.assertNotIn("HTTPS_PROXY", env)
                self.assertNotIn("NODE_OPTIONS", env)
                self.assertNotIn(
                    "P2_REHYDRATION_RUNTIME_PASSWORD"
                    if mode in gate.OWNER_MODES
                    else "P2_REHYDRATION_OWNER_PASSWORD",
                    env,
                )

    def test_integrated_credential_only_to_selected_exercise(self) -> None:
        extra = {
            "P2_REHYDRATION_CURRENT_CASE_PORT": "12345",
            "P2_REHYDRATION_CURRENT_CASE_TOKEN": "x" * 43,
        }
        self.assertIn(
            "P2_REHYDRATION_CURRENT_CASE_TOKEN",
            gate.child_environment(self.values, self.common, "exercise", extra),
        )
        self.assertNotIn(
            "P2_REHYDRATION_CURRENT_CASE_TOKEN",
            gate.child_environment(self.values, self.common, "seed", extra),
        )
        with self.assertRaises(gate.GateError):
            gate.child_environment(self.values, self.common, "exercise")

    def test_unknown_mode_cannot_choose_runtime_role(self) -> None:
        with self.assertRaises(gate.GateError):
            gate.child_environment(self.values, self.common, "forged")

    def test_role_smuggling_and_arbitrary_selectors_rejected(self) -> None:
        env = gate.child_environment(self.values, self.common, "seed")
        for name in (
            "P2_REHYDRATION_OWNER_PASSWORD",
            "P2_REHYDRATION_CURRENT_CASE_TOKEN",
            "PYTHONPATH",
            "P2_CASE_ID",
            "OPENAI_API_KEY",
        ):
            with self.subTest(name=name), self.assertRaises(gate.GateError):
                gate.validate_child_environment({**env, name: "synthetic"}, "seed")

    def test_bad_schema_port_and_relative_paths_rejected(self) -> None:
        env = gate.child_environment(self.values, self.common, "seed")
        for name, value in (
            ("P2_REHYDRATION_SCHEMA", "p2_rehydration_" + "a" * 32 + "\n"),
            ("P2_REHYDRATION_SCHEMA", "continuity"),
            ("P2_REHYDRATION_PG_PORT", "0"),
            ("P2_REHYDRATION_PG_PORT", "65536"),
            ("P2_REHYDRATION_PG_PORT", "015432"),
            ("P2_REHYDRATION_DIRECTORY", "relative"),
        ):
            with self.subTest(name=name, value=value), self.assertRaises(gate.GateError):
                gate.validate_child_environment({**env, name: value}, "seed")

    def test_clean_stage_requires_exact_named_assertions(self) -> None:
        v = {
            "schemaVersion": 1,
            "status": "passed",
            "mode": "exercise",
            "nodeVersion": "24.22.2",
            "storageVersion": 7,
            **gate.STAGE_EXTRA["exercise"],
        }
        self.assertEqual(gate.validated_stage(json.dumps(v).encode(), "exercise"), v)
        for mutate in (
            lambda x: x.update(extra=True),
            lambda x: x.update(status="skipped"),
            lambda x: x.update(storageVersion=True),
            lambda x: x.update(nodeVersion="24.22.3"),
            lambda x: x.update(completedGroups=list(reversed(x["completedGroups"]))),
            lambda x: x.update(completedGroups=x["completedGroups"][:-1]),
        ):
            changed = json.loads(json.dumps(v))
            mutate(changed)
            with self.assertRaises(gate.GateError):
                gate.validated_stage(json.dumps(changed).encode(), "exercise")

    def test_duplicate_json_keys_nonfinite_and_oversized_fail_closed(self) -> None:
        for raw in (
            b'{"status":"failed","status":"passed"}',
            b'{"duration":NaN}',
            b" " * 32769,
            b"[]",
            b"null",
            b"\xff",
        ):
            with self.subTest(raw=raw[:32]), self.assertRaises(gate.GateError):
                gate.validated_report(raw)

    def test_stage_bound_to_exact_mode(self) -> None:
        v = {
            "schemaVersion": 1,
            "status": "passed",
            "mode": "seed",
            "nodeVersion": "24.22.2",
            "storageVersion": 7,
            **gate.STAGE_EXTRA["seed"],
        }
        for mode in ("install", "crash", "media-serve", "forged"):
            with self.subTest(mode=mode), self.assertRaises(gate.GateError):
                gate.validated_stage(json.dumps(v).encode(), mode)

    def test_fixture_authorities_distinct_and_fresh_room_same_case(self) -> None:
        f = gate.fixture("a" * 32)
        tokens = (
            [f[k] for k in ("accountToken", "publisherToken", "prepareToken")]
            + list(f["communication"].values())
            + [f["bindings"][k]["bindingToken"] for k in ("A", "B")]
        )
        self.assertEqual(len(tokens), len(set(tokens)))
        self.assertEqual(f["providerScope"]["provider"], "livekit")
        self.assertEqual(f["sms"]["providerScope"]["provider"], "fake_sms")
        self.assertNotEqual(f["bindings"]["A"]["roomId"], f["bindings"]["B"]["roomId"])
        self.assertTrue(f["referenceRequest"]["investigationConsent"])
        self.assertEqual(set(f["ids"]), {"voice", "text", "sms", "newText"})

    def test_manifest_binds_nested_summary_and_exact_private_files(self) -> None:
        nested = self.directory / "package"
        nested.mkdir()
        (nested / "summary.json").write_text('{"status":"passed"}')
        (self.directory / "source.json").write_text("{}")
        index = gate.retained_index(self.directory)
        self.assertEqual(set(index["files"]), {"package/summary.json", "source.json"})
        self.assertEqual((nested / "summary.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(nested.stat().st_mode & 0o777, 0o700)
        with self.assertRaises(gate.GateError):
            gate.retained_index(self.directory)

    def test_symlink_cannot_be_evidence(self) -> None:
        target = self.directory / "real"
        target.write_text("safe")
        (self.directory / "link").symlink_to(target)
        with self.assertRaises(gate.GateError):
            gate.retained_index(self.directory)

    def test_hardlink_cannot_be_evidence(self) -> None:
        target = self.directory / "real"
        target.write_text("safe")
        os.link(target, self.directory / "link")
        with self.assertRaises(gate.GateError):
            gate.retained_index(self.directory)

    def test_import_has_no_listener_settings_or_child_side_effect(self) -> None:
        import asyncio
        import socket
        import subprocess

        spec = importlib.util.spec_from_file_location(
            "rehydration_gate_fresh", SCRIPTS / "p2_rehydration_check.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        with (
            patch.object(socket.socket, "bind", side_effect=AssertionError("import listener")),
            patch.object(subprocess, "Popen", side_effect=AssertionError("import child")),
            patch.object(gate.core, "load_setup", side_effect=AssertionError("import settings")),
            patch.object(asyncio, "run", side_effect=AssertionError("import run")),
        ):
            spec.loader.exec_module(module)
        self.assertEqual(module.MODE, gate.MODE)


class RetainedP1OwnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_retains_actual_operation_and_close_waits(self) -> None:
        import asyncio
        import time

        from p2_rehydration_p1 import P1ReadFixture

        with tempfile.TemporaryDirectory() as temporary:
            owner = P1ReadFixture(
                {
                    "POSTGRES_PORT": "15432",
                    "POSTGRES_PASSWORD": "runtime-synthetic",
                    "POSTGRES_MIGRATION_PASSWORD": "owner-synthetic",
                },
                Path(temporary),
                {},
            )
            entered = asyncio.Event()
            release = asyncio.Event()

            async def held() -> int:
                entered.set()
                await release.wait()
                return 7

            waiting = asyncio.create_task(owner.bounded(held(), time.monotonic() + 0.02))
            await entered.wait()
            with self.assertRaises(TimeoutError):
                await waiting
            self.assertEqual(len(owner._operations), 1)
            self.assertFalse(next(iter(owner._operations)).done())
            closing = asyncio.create_task(owner.close(deadline=time.monotonic() + 1))
            await asyncio.sleep(0)
            self.assertFalse(closing.done())
            release.set()
            await closing
            self.assertEqual(next(iter(owner._operations)).result(), 7)

    async def test_caller_cancel_does_not_cancel_retained_operation(self) -> None:
        import asyncio
        import time

        from p2_rehydration_p1 import P1ReadFixture

        with tempfile.TemporaryDirectory() as temporary:
            owner = P1ReadFixture(
                {
                    "POSTGRES_PORT": "15432",
                    "POSTGRES_PASSWORD": "runtime-synthetic",
                    "POSTGRES_MIGRATION_PASSWORD": "owner-synthetic",
                },
                Path(temporary),
                {},
            )
            entered = asyncio.Event()
            release = asyncio.Event()

            async def held() -> None:
                entered.set()
                await release.wait()

            waiting = asyncio.create_task(owner.bounded(held(), time.monotonic() + 1))
            await entered.wait()
            waiting.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiting
            self.assertFalse(next(iter(owner._operations)).cancelled())
            release.set()
            await owner.close(deadline=time.monotonic() + 1)


class EvidenceJoinTests(unittest.TestCase):
    def test_index_detects_added_or_modified_nested_artifacts(self) -> None:
        import hashlib

        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            (folder / "nested").mkdir()
            source = folder / "nested/summary.json"
            source.write_text("{}")
            gate.retained_index(folder)
            sha = hashlib.sha256((folder / "retained-index.json").read_bytes()).hexdigest()
            self.assertIn("nested/summary.json", gate.validate_retained_index(folder, sha)["files"])
            source.write_text('{"changed":true}')
            with self.assertRaises(gate.GateError):
                gate.validate_retained_index(folder, sha)
            source.write_text("{}")
            (folder / "unindexed.json").write_text("{}")
            with self.assertRaises(gate.GateError):
                gate.validate_retained_index(folder, sha)

    def test_report_family_and_existing_results_are_protected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            requested = Path(".local/validation/p2-rehydration/normal-01.json")
            target = gate.target_path(root, requested)
            target.write_text("{}")
            with self.assertRaises(gate.GateError):
                gate.target_path(root, requested)
            for path in (
                Path("/private/tmp/owned.json"),
                Path(".local/validation/p2-playback/x.json"),
                Path(".local/validation/p2-rehydration/../x.json"),
                Path(".local/validation/p2-rehydration/x.json\n"),
            ):
                with self.subTest(path=path), self.assertRaises(gate.GateError):
                    gate.target_path(root, path)


class P1DeadlineGuardTests(unittest.IsolatedAsyncioTestCase):
    def owner(self, directory: str):
        from p2_rehydration_p1 import P1ReadFixture

        return P1ReadFixture(
            {
                "POSTGRES_PORT": "15432",
                "POSTGRES_PASSWORD": "runtime-synthetic",
                "POSTGRES_MIGRATION_PASSWORD": "owner-synthetic",
            },
            Path(directory),
            {},
        )

    async def test_expired_admission_never_starts_operation(self) -> None:
        import time

        with tempfile.TemporaryDirectory() as temporary:
            owner = self.owner(temporary)
            started = []

            async def operation() -> None:
                started.append(True)

            pending = operation()
            with self.assertRaises(TimeoutError):
                await owner.bounded(pending, time.monotonic() - 1)
            self.assertEqual(started, [])
            self.assertIsNone(pending.cr_frame)
            self.assertEqual(owner._operations, set())

    async def test_cancelled_waiter_is_not_worker_drain_proof(self) -> None:
        import asyncio
        import time

        import p2_rehydration_p1 as parent

        with tempfile.TemporaryDirectory() as temporary:
            owner = self.owner(temporary)
            owner.installed = True
            task = asyncio.create_task(asyncio.sleep(10))
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            owner._operations.add(task)
            with patch.object(
                parent.fixture, "cleanup", side_effect=AssertionError("premature DDL")
            ) as ddl:
                with self.assertRaises(TimeoutError):
                    await owner.close(deadline=time.monotonic() + 1)
                ddl.assert_not_called()

    async def test_held_client_close_retains_owner_and_blocks_schema_until_settled(self) -> None:
        import asyncio
        import time
        from types import SimpleNamespace

        import p2_rehydration_p1 as parent

        with tempfile.TemporaryDirectory() as temporary:
            owner = self.owner(temporary)
            owner.installed = True
            entered = asyncio.Event()
            release = asyncio.Event()
            reader_closed = []

            async def close_bridge() -> None:
                entered.set()
                await release.wait()

            async def close_reader() -> None:
                reader_closed.append(True)

            owner.bridge = SimpleNamespace(close=close_bridge)
            owner.reader = SimpleNamespace(close=close_reader)
            with patch.object(parent.fixture, "cleanup", return_value={"status": "passed"}) as ddl:
                with self.assertRaises(TimeoutError):
                    await owner.close(deadline=time.monotonic() + 0.02)
                await asyncio.sleep(0)
                self.assertTrue(entered.is_set())
                self.assertEqual(reader_closed, [])
                ddl.assert_not_called()
                self.assertFalse(owner._resource_closers["bridge"].done())
                release.set()
                await owner.close(deadline=time.monotonic() + 1)
                self.assertEqual(reader_closed, [True])
                ddl.assert_called_once()

    async def test_failed_bridge_close_withholds_dependent_reader(self) -> None:
        import time
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as temporary:
            owner = self.owner(temporary)
            closed = []

            async def broken() -> None:
                raise RuntimeError("synthetic close failure")

            async def healthy() -> None:
                closed.append(True)

            owner.bridge = SimpleNamespace(close=broken)
            owner.reader = SimpleNamespace(close=healthy)
            with self.assertRaisesRegex(RuntimeError, "synthetic close failure"):
                await owner.close(deadline=time.monotonic() + 1)
            self.assertEqual(closed, [])

    async def test_public_bridge_internal_timeout_reobserves_before_reader_and_schema(self) -> None:
        import asyncio
        import time
        from types import SimpleNamespace

        import p2_rehydration_p1 as parent

        with tempfile.TemporaryDirectory() as temporary:
            owner = self.owner(temporary)
            owner.installed = True
            release = asyncio.Event()
            actual = asyncio.create_task(release.wait())
            calls = []

            async def public_bridge_close():
                calls.append("bridge")
                async with asyncio.timeout(0.01):
                    await asyncio.shield(actual)

            async def reader_close():
                calls.append("reader")

            owner.bridge = SimpleNamespace(close=public_bridge_close)
            owner.reader = SimpleNamespace(close=reader_close)
            try:
                with patch.object(parent.fixture, "cleanup", return_value={}) as ddl:
                    with self.assertRaises(TimeoutError):
                        await owner.close(deadline=time.monotonic() + 1)
                    self.assertFalse(actual.done())
                    self.assertTrue(owner._resource_closers["bridge"].done())
                    self.assertEqual(calls, ["bridge"])
                    ddl.assert_not_called()
                    release.set()
                    await owner.close(deadline=time.monotonic() + 1)
                    self.assertEqual(calls, ["bridge", "bridge", "reader"])
                    ddl.assert_called_once()
                    await owner.close(deadline=time.monotonic() + 1)
                    self.assertEqual(calls.count("reader"), 1)
                    ddl.assert_called_once()
            finally:
                release.set()
                await actual

    async def test_one_active_operation_and_close_reject_unstarted_coroutine(self) -> None:
        import asyncio
        import time

        with tempfile.TemporaryDirectory() as temporary:
            owner = self.owner(temporary)
            entered, release = asyncio.Event(), asyncio.Event()

            async def held():
                entered.set()
                await release.wait()
                return 7

            calls = []

            async def forbidden():
                calls.append(True)

            first = asyncio.create_task(owner.bounded(held(), time.monotonic() + 1))
            await entered.wait()
            second = forbidden()
            with self.assertRaises(RuntimeError):
                await owner.bounded(second, time.monotonic() + 1)
            self.assertIsNone(second.cr_frame)
            self.assertEqual(calls, [])
            release.set()
            self.assertEqual(await first, 7)
            await owner.close(deadline=time.monotonic() + 1)
            third = forbidden()
            with self.assertRaises(RuntimeError):
                await owner.bounded(third, time.monotonic() + 1)
            self.assertIsNone(third.cr_frame)
            self.assertEqual(calls, [])

    async def test_late_install_thread_stops_before_constructing_boundary_or_listener(self) -> None:
        import asyncio
        import threading
        import time

        import p2_rehydration_p1 as parent

        with tempfile.TemporaryDirectory() as temporary:
            owner = self.owner(temporary)
            entered, release = threading.Event(), threading.Event()

            def installation(*args):
                entered.set()
                if not release.wait(2):
                    raise TimeoutError()

            with (
                patch.object(parent.fixture, "install", side_effect=installation),
                patch.object(
                    parent,
                    "build_conversation_service",
                    side_effect=AssertionError("late boundary"),
                ) as boundary,
                patch.object(
                    parent, "start_current_case_bridge", side_effect=AssertionError("late listener")
                ) as bridge,
                patch.object(parent.fixture, "cleanup", return_value={}) as ddl,
            ):
                waiter = asyncio.create_task(owner.bounded(owner.start(), time.monotonic() + 0.02))
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait, 0.5))
                    with self.assertRaises(TimeoutError):
                        await waiter
                    with self.assertRaises(TimeoutError):
                        await owner.close(deadline=time.monotonic() + 0.01)
                    self.assertFalse(next(iter(owner._operations)).done())
                    ddl.assert_not_called()
                finally:
                    release.set()
                    await asyncio.gather(*owner._operations, return_exceptions=True)
                await owner.close(deadline=time.monotonic() + 1)
                boundary.assert_not_called()
                bridge.assert_not_called()
                ddl.assert_called_once()

    async def test_close_during_submit_drains_it_then_reader_without_late_bridge(self) -> None:
        import asyncio
        import time
        from types import SimpleNamespace

        import p2_rehydration_p1 as parent

        with tempfile.TemporaryDirectory() as temporary:
            owner = self.owner(temporary)
            entered, release = asyncio.Event(), asyncio.Event()
            closed = []

            async def submit(**kwargs):
                entered.set()
                await release.wait()
                return SimpleNamespace(task_id="trusted-task", case_id="trusted-case")

            async def reader_close():
                closed.append("reader")

            with (
                patch.object(parent.fixture, "install", return_value={}),
                patch.object(parent, "build_conversation_service", return_value=object()),
                patch.object(
                    parent,
                    "PublicCurrentCaseReader",
                    return_value=SimpleNamespace(close=reader_close),
                ),
                patch.object(
                    parent, "ManagedCaseClient", return_value=SimpleNamespace(submit=submit)
                ),
                patch.object(parent, "CaseControlClient", return_value=object()),
                patch.object(
                    parent, "start_current_case_bridge", side_effect=AssertionError("late bind")
                ) as bridge,
                patch.object(parent.fixture, "cleanup", return_value={}) as ddl,
            ):
                operation = asyncio.create_task(owner.bounded(owner.start(), time.monotonic() + 1))
                await entered.wait()
                closing = asyncio.create_task(owner.close(deadline=time.monotonic() + 1))
                await asyncio.sleep(0)
                self.assertTrue(owner.closing_requested)
                self.assertFalse(closed)
                release.set()
                with self.assertRaises(TimeoutError):
                    await operation
                await closing
                self.assertEqual(closed, ["reader"])
                bridge.assert_not_called()
                ddl.assert_called_once()

    async def test_advance_abandoned_quote_and_confirmation_never_admit_next_stage(self) -> None:
        import asyncio
        import time
        from types import SimpleNamespace

        import p2_rehydration_p1 as parent

        for stage in ("quote", "confirmation", "cancelled_quote"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                owner = self.owner(temporary)
                entered, release = asyncio.Event(), asyncio.Event()
                calls = []

                async def quote(
                    *, calls=calls, stage=stage, entered=entered, release=release, **kwargs
                ):
                    calls.append("quote")
                    if stage in ("quote", "cancelled_quote"):
                        entered.set()
                        await release.wait()
                    return SimpleNamespace(quote=object())

                async def confirmation(*, calls=calls, entered=entered, release=release, **kwargs):
                    calls.append("confirmation")
                    entered.set()
                    await release.wait()
                    return SimpleNamespace(effect_id="effect")

                owner.managed = SimpleNamespace(prepare_quote=quote)
                owner.control = SimpleNamespace(commit_confirmation=confirmation)
                with (
                    patch.object(parent.fixture, "inquire", return_value={}),
                    patch.object(parent, "Confirmation", return_value=object()),
                    patch.object(
                        parent.fixture, "mutate", side_effect=AssertionError("late mutation")
                    ) as mutation,
                ):
                    waiter = asyncio.create_task(
                        owner.bounded(owner.advance(), time.monotonic() + 0.02)
                    )
                    await entered.wait()
                    if stage == "cancelled_quote":
                        waiter.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await waiter
                    else:
                        with self.assertRaises(TimeoutError):
                            await waiter
                    self.assertFalse(next(iter(owner._operations)).done())
                    release.set()
                    await asyncio.gather(*owner._operations, return_exceptions=True)
                    self.assertEqual(
                        calls, ["quote"] if stage != "confirmation" else ["quote", "confirmation"]
                    )
                    mutation.assert_not_called()
                    self.assertFalse(owner.advanced)
                    self.assertIsInstance(next(iter(owner._operations)).exception(), TimeoutError)


if __name__ == "__main__":
    unittest.main()
