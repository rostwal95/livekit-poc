"""Offline fault-schedule boundaries; actual authority has a separate PostgreSQL gate."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from delegation_reliability.contracts import ContractError, encode_request, parse_request

ROOT = Path(__file__).resolve().parents[3]


def load_fixture() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "deadline_schedule_tests",
        ROOT / "projects/delegation-reliability/tests/pg_deadline_cases.py",
    )
    assert spec is not None and spec.loader is not None
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


FIXTURE = load_fixture()


def context(owner: bool = False) -> dict[str, str]:
    result = {
        "P3_DEADLINE_WORK_SCHEMA": "p1_work_deadline_" + uuid4().hex,
        "P3_DEADLINE_CASE_SCHEMA": "p3_completion_" + uuid4().hex,
        "P3_DEADLINE_SCHEMA": "p3_projection_deadline_" + uuid4().hex,
        "P3_DEADLINE_DIRECTORY": "/private/tmp",
        "P3_DEADLINE_PG_PORT": "15432",
        "P3_DEADLINE_OWNER_PASSWORD" if owner else "P3_DEADLINE_RUNTIME_PASSWORD": "synthetic",
    }
    if not owner:
        result.update(P3_DEADLINE_TOKEN="T" * 43, P3_DEADLINE_PORT="15433")
    return result


class DeadlineScheduleTests(unittest.TestCase):
    def test_failure_diagnostics_are_exact_finite_and_never_reflect_unknown_errors(self) -> None:
        touched = []

        class UnknownError(Exception):
            @property
            def code(self):
                touched.append("code")
                raise AssertionError("SECRET_SENTINEL")

            def __str__(self):
                touched.append("message")
                raise AssertionError("SECRET_SENTINEL")

        class RunSubclass(FIXTURE.DelegationRunError):
            @property
            def code(self):
                touched.append("subclass")
                raise AssertionError("SECRET_SENTINEL")

        for error in (UnknownError("SECRET_SENTINEL"), RunSubclass.__new__(RunSubclass)):
            value = FIXTURE.diagnostic_failure(
                error, mode="invoke-lease", stage="invoke_lease_await_run"
            )
            self.assertEqual(
                value,
                {
                    "status": "failed",
                    "mode": "invoke-lease",
                    "stage": "invoke_lease_await_run",
                    "code": "fixture_failed",
                    "type": "unexpected",
                },
            )
            self.assertNotIn("SECRET_SENTINEL", json.dumps(value))
        self.assertEqual(touched, [])
        for known, kind, allowed in FIXTURE.DIAGNOSTIC_ERRORS:
            for code in allowed:
                error = known(code)
                value = FIXTURE.diagnostic_failure(
                    error, mode="invoke-lease", stage="denied_lease_action"
                )
                self.assertEqual((value["code"], value["type"]), (code, kind))
            error = known(next(iter(allowed)))
            for code in ("secret_sentinel", [], True):
                error.code = code
                value = FIXTURE.diagnostic_failure(
                    error, mode="invoke-lease", stage="denied_lease_action"
                )
                self.assertEqual(value["code"], "fixture_failed")
        self.assertEqual(
            FIXTURE.diagnostic_failure(
                AssertionError("SECRET_SENTINEL"),
                mode="invoke-lease",
                stage="invoke_lease_view_assert",
            )["code"],
            "assertion_failed",
        )

    def test_failure_stage_and_mode_are_closed_without_echoing_rejected_values(self) -> None:
        previous = FIXTURE.STAGE
        try:
            for stage in FIXTURE.DIAGNOSTIC_STAGES:
                FIXTURE.diagnostic_stage(stage)
                self.assertEqual(FIXTURE.STAGE, stage)
            for value in ("SECRET_SENTINEL", [], True):
                with self.assertRaises(AssertionError):
                    FIXTURE.diagnostic_stage(value)
                reply = FIXTURE.diagnostic_failure(
                    RuntimeError("SECRET_SENTINEL"), mode=value, stage=value
                )
                self.assertEqual(reply["mode"], "unknown")
                self.assertEqual(reply["stage"], "unknown")
                self.assertNotIn("SECRET_SENTINEL", json.dumps(reply))
        finally:
            FIXTURE.STAGE = previous

    def test_peer_release_reader_accepts_only_actual_private_publication_and_pid(self) -> None:
        peer = (
            ROOT / "projects/delegation-reliability/specialist-ts/tests/fixtures/deadline-peer.mjs"
        )
        source = peer.read_text()
        # Execute the exact maintained helper with real files; no SDK/server/build import.
        helper = source[
            source.index("async function readReleasedPid(") : source.index(
                "function configuration("
            )
        ]
        program = (
            r"""
import * as fs from 'node:fs';
import {join} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import assert from 'node:assert/strict';
const {constants,openSync,fstatSync,closeSync,readFileSync,readSync}=fs;
let race=null;
const lstatSync=(path)=>{if(race && path===race.pending){const current=race;race=null;fs.unlinkSync(path);if(current.replace){fs.unlinkSync(current.path);fs.writeFileSync(current.path,String(process.pid)+'\n',{mode:0o600,flag:'wx'});}const error=new Error('absent');error.code='ENOENT';throw error;}return fs.lstatSync(path);};
function fail(){throw new Error('fixture_failed');}
"""
            + helper
            + r"""
const root=process.cwd();let count=0;
function release(name,kind='single',body=String(process.pid)+'\n'){
 const path=join(root,name+'.released'),pending=path+'.'+process.pid+'.pending';
 fs.writeFileSync(pending,body,{flag:'wx',mode:0o600});fs.linkSync(pending,path);if(kind==='single')fs.unlinkSync(pending);return {path,pending};
}
const end=()=>performance.now()+1000;
const single=release('single');assert.equal(await readReleasedPid(single.path,process.pid,end()),process.pid);count++;
const transitioning=release('transitioning','two');const pending=readReleasedPid(transitioning.path,process.pid,end());setTimeout(()=>fs.unlinkSync(transitioning.pending),10);assert.equal(await pending,process.pid);count++;
const settled=release('settled','two');race=settled;assert.equal(await readReleasedPid(settled.path,process.pid,end()),process.pid);count++;
const replaced=release('replaced','two');const held=fs.openSync(replaced.path,'r');try{race={...replaced,replace:true};await assert.rejects(readReleasedPid(replaced.path,process.pid,end()));count++;}finally{fs.closeSync(held);}
const foreign=release('foreign','single',String(process.pid+1)+'\n');await assert.rejects(readReleasedPid(foreign.path,process.pid,end()));count++;
const target=release('target');fs.symlinkSync(target.path,join(root,'symlink.released'));await assert.rejects(readReleasedPid(join(root,'symlink.released'),process.pid,end()));count++;
const wrong=release('wrong');fs.linkSync(wrong.path,join(root,'unrelated-link'));await assert.rejects(readReleasedPid(wrong.path,process.pid,end()));count++;
const heldPending=release('held','two');await assert.rejects(readReleasedPid(heldPending.path,process.pid,performance.now()+20));count++;
console.log(JSON.stringify({status:'passed',controls:count}));
"""
        )
        node = shutil.which("node")
        self.assertIsNotNone(node)
        with tempfile.TemporaryDirectory(
            prefix="deadline-release-control-", dir="/private/tmp"
        ) as directory:
            folder = Path(directory)
            script = folder / "control.mjs"
            script.write_text(program)
            script.chmod(0o600)
            result = subprocess.run(
                [node, str(script)],
                cwd=folder,
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            self.assertEqual(json.loads(result.stdout), {"status": "passed", "controls": 8})

    def test_runtime_environment_rejects_owner_provider_and_interpreter_injection(self) -> None:
        valid = context()
        with patch.object(FIXTURE, "MODE", "seed"), patch.dict(os.environ, valid, clear=True):
            FIXTURE.environment()
        for key in (
            "P3_DEADLINE_OWNER_PASSWORD",
            "OPENAI_API_KEY",
            "PYTHONPATH",
            "NODE_OPTIONS",
            "PGPASSWORD",
            "DATABASE_URL",
        ):
            with (
                self.subTest(key=key),
                patch.object(FIXTURE, "MODE", "seed"),
                patch.dict(os.environ, {**valid, key: "inert"}, clear=True),
                self.assertRaises(AssertionError),
            ):
                FIXTURE.environment()

    def test_owner_receives_no_runtime_token_or_remote_port(self) -> None:
        valid = context(owner=True)
        with patch.object(FIXTURE, "MODE", "install"), patch.dict(os.environ, valid, clear=True):
            FIXTURE.environment()
        for key in ("P3_DEADLINE_RUNTIME_PASSWORD", "P3_DEADLINE_TOKEN", "P3_DEADLINE_PORT"):
            with (
                patch.object(FIXTURE, "MODE", "install"),
                patch.dict(os.environ, {**valid, key: "inert"}, clear=True),
                self.assertRaises(AssertionError),
            ):
                FIXTURE.environment()

    def test_each_stage_request_has_fresh_bounded_horizon_and_recomputed_fingerprint(self) -> None:
        with patch.object(FIXTURE, "now", return_value=1800000000000):
            first = FIXTURE.request("expiry", 1800)
            ordinary = FIXTURE.request("useful")
        with patch.object(FIXTURE, "now", return_value=1800000000100):
            second = FIXTURE.request("expiry", 1800)
        self.assertEqual(first.deadline_at_ms, 1800000001800)
        self.assertEqual(second.deadline_at_ms, 1800000001900)
        self.assertEqual(ordinary.deadline_at_ms, 1800000060000)
        self.assertNotEqual(first.input_fingerprint, second.input_fingerprint)
        self.assertEqual(parse_request(encode_request(first)), first)
        altered = json.loads(encode_request(first))
        altered["deadline_at_ms"] += 1
        with self.assertRaises(ContractError):
            parse_request(json.dumps(altered).encode())

    def test_short_request_production_uses_public_codec_without_expanding_authority_horizon(
        self,
    ) -> None:
        with patch.object(FIXTURE, "now", return_value=1800000000000):
            request = FIXTURE.request("lock_wait", 700)
        self.assertEqual(request.deadline_at_ms, 1800000000700)
        self.assertEqual(request.scope, FIXTURE.SCOPE)
        self.assertEqual(request.request_revision, 2)
        self.assertEqual(request.delegation_id, "delegation_lock_wait")
        self.assertEqual(request.evidence[0].sha256, hashlib.sha256(FIXTURE.POLICY).hexdigest())

    def test_immutable_local_identity_file_refuses_overwrite_symlink_and_oversize(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(os.environ, {"P3_DEADLINE_DIRECTORY": temporary}),
        ):
            FIXTURE.save("identity.json", {"request_sha256": "a" * 64})
            path = Path(temporary) / "identity.json"
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                FIXTURE.save("identity.json", {"request_sha256": "b" * 64})
            (Path(temporary) / "redirect.json").symlink_to(path)
            with self.assertRaises(FileExistsError):
                FIXTURE.save("redirect.json", {"changed": True})
            with self.assertRaises(AssertionError):
                FIXTURE.save("oversize.json", {"value": "x" * 32768})
            self.assertFalse((Path(temporary) / "oversize.json").exists())
            self.assertEqual(json.loads(path.read_text())["request_sha256"], "a" * 64)

    def test_pid_marker_is_atomic_private_and_exclusive(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(os.environ, {"P3_DEADLINE_DIRECTORY": temporary}),
        ):
            FIXTURE.marker("temporal_hold")
            path = Path(temporary) / "temporal_hold.reached"
            self.assertEqual(path.read_text(), str(os.getpid()) + "\n")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.stat().st_nlink, 1)
            self.assertFalse(list(Path(temporary).glob("*.pending")))
            with self.assertRaises(FileExistsError):
                FIXTURE.marker("temporal_hold")

    def test_barrier_rejects_other_process_release_instead_of_continuing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "temporal_hold.released").write_text(str(os.getpid() + 1) + "\n")
            with (
                patch.dict(
                    os.environ,
                    {
                        "P3_DEADLINE_DIRECTORY": temporary,
                        "P3_DEADLINE_BARRIER": str(root / "temporal_hold.reached"),
                    },
                ),
                self.assertRaisesRegex(AssertionError, "wrong_barrier_release"),
            ):
                FIXTURE.barrier("temporal_hold")

    def test_expiry_wait_uses_authority_observation_and_never_host_clock(self) -> None:
        calls = []

        def authority_now() -> int:
            calls.append(True)
            return 1800000000000 + len(calls)

        with patch.object(FIXTURE, "now", side_effect=authority_now):
            observed = asyncio.run(FIXTURE.after(1800000000002))
        self.assertGreaterEqual(observed, 1800000000002)
        self.assertEqual(len(calls), 2)

    def test_owner_cleanup_attempts_all_profiles_after_case_cleanup_failure(self) -> None:
        attempted = []
        failure = RuntimeError("safe-owner-failure")

        def settings(kind="work"):
            attempted.append(kind)
            connection = MagicMock()
            connection.execute.return_value.fetchone.return_value = None
            return SimpleNamespace(schema=kind, connect=lambda **_: connection)

        with (
            patch.object(FIXTURE, "settings", side_effect=settings),
            patch.object(FIXTURE.HELPER, "cleanup", side_effect=failure),
            patch.object(
                FIXTURE, "load", return_value={"projection": "projection", "work": "work"}
            ),
            self.assertRaises(RuntimeError) as raised,
        ):
            FIXTURE.cleanup()
        self.assertIs(raised.exception, failure)
        self.assertEqual(attempted, ["case", "projection", "work"])


class HeldExecutionScheduleTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_projection_prefix_reaches_public_storage_validation_with_io_blocked(
        self,
    ) -> None:
        from continuity_lab.work_api import (
            BearerToken,
            PostgresSettings,
            WorkDirectory,
            WorkPrincipal,
            WorkScope,
        )
        from delegation_reliability.projection_api import ProjectionError, open_projection_client

        token = BearerToken("T" * 43)
        scope = WorkScope("tenant_deadline", "account_deadline")
        directory = WorkDirectory({token: WorkPrincipal("deadline_actor", scope)})
        for prefix, accepted in (("p3_projection_deadline_", True), ("p3_deadline_", False)):
            settings = PostgresSettings(
                schema=prefix + uuid4().hex, user="livekit_lab", password="synthetic"
            )
            with (
                patch.object(
                    PostgresSettings, "connect", side_effect=OSError("blocked-test-only-io")
                ) as connection,
                self.assertRaises(ProjectionError) as raised,
            ):
                open_projection_client(
                    settings=settings, directory=directory, token=token, source_id=str(uuid4())
                )
            self.assertEqual(
                raised.exception.code, "storage_unavailable" if accepted else "invalid_input"
            )
            self.assertEqual(connection.call_count, 1 if accepted else 0)

    async def test_issue_hold_retains_original_public_result_and_pending_ownership(self) -> None:
        entered = asyncio.Event()
        grant = object()
        arguments = {}

        async def issue(**values):
            arguments.update(values)
            entered.set()
            return grant

        actual = SimpleNamespace(scope="scope", pending_count=2, issue=issue)
        port = FIXTURE.HeldExecution(actual)
        task = asyncio.create_task(
            port.issue(work_id="work", owner_id="owner", command_id="command")
        )
        await asyncio.wait_for(port.entered.wait(), 1)
        self.assertTrue(entered.is_set())
        self.assertFalse(task.done())
        self.assertEqual(port.pending_count, 2)
        self.assertEqual(
            arguments, {"work_id": "work", "owner_id": "owner", "command_id": "command"}
        )
        port.release.set()
        self.assertIs(await task, grant)

    async def test_bundle_closes_all_owners_and_preserves_first_cancellation(self) -> None:
        seen = []
        failure = asyncio.CancelledError()

        class Owner:
            def __init__(self, name):
                self.name = name

            async def close(self):
                seen.append(self.name)
                if self.name == "authorizer":
                    raise failure

        bundle = FIXTURE.Bundle.__new__(FIXTURE.Bundle)
        bundle.proxy = None
        for name in ("authorizer", "runner", "coordinator", "control"):
            setattr(bundle, name, Owner(name))
        with self.assertRaises(asyncio.CancelledError) as raised:
            await bundle.close()
        self.assertIs(raised.exception, failure)
        self.assertEqual(seen, ["authorizer", "runner", "coordinator", "control"])

    async def test_held_public_error_never_becomes_a_fabricated_grant(self) -> None:
        from continuity_lab.work_api import WorkError

        async def issue(**values):
            raise WorkError("expired")

        port = FIXTURE.HeldExecution(SimpleNamespace(scope="scope", pending_count=0, issue=issue))
        with self.assertRaises(WorkError) as raised:
            await port.issue(work_id="work", owner_id="owner", command_id="command")
        self.assertEqual(raised.exception.code, "expired")
        self.assertFalse(port.entered.is_set())
        self.assertEqual(port.pending_count, 0)


if __name__ == "__main__":
    unittest.main()
