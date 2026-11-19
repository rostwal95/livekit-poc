"""Closed role contracts and owned harmless Node children; no product startup."""

from __future__ import annotations

import asyncio
import dataclasses
import http.client
import importlib.util
import json
import os
import shutil
import signal
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

DRAFT = Path(__file__).resolve().parents[1]
SOURCE = DRAFT / "local-setup/scripts/channel_policy_launch_child.py"
SPEC = importlib.util.spec_from_file_location("_channel_policy_launch_child", SOURCE)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)
NODE = shutil.which("node")
if NODE is None:
    raise RuntimeError("required_node_unavailable")
BASE = {"PATH": "/usr/bin:/bin", "LANG": "C"}
PORTS = {"native": 11024, "sms": 11025, "read": 11026, "receiver": 11027, "specialist": 11028}


def spec(directory, role="specialist"):
    extras = (
        {"P3_DEMO_SPECIALIST_BEARER": "s" * 43}
        if role == "specialist"
        else {key: "x" * 43 for key in m.GATEWAY}
        if role == "gateway"
        else {}
    )
    if role == "gateway":
        extras["P2_DEMO_CASE_AUTHORIZATION"] = "Bearer " + "c" * 43
        extras["P2_DEMO_POSTGRES_PASSWORD"] = "ordinary_bounded_password_" * 2
    return m.ChildSpec(
        role,
        directory,
        Path(NODE),
        str(uuid4()),
        PORTS,
        BASE | extras,
        directory / "config.json" if role != "ui" else None,
        directory / "room.json" if role == "gateway" else None,
        directory / "bridge.json" if role == "gateway" else None,
    )


def ready(value, pid=123):
    if value.role == "specialist":
        return {
            "schemaVersion": 1,
            "status": "ready",
            "label": "scripted",
            "mode": "scripted_fixed_policy",
            "pid": pid,
            "endpoint": {"host": "127.0.0.1", "port": 11028},
        }
    if value.role == "ui":
        return {
            "schemaVersion": 1,
            "status": "ready",
            "mode": "scripted_ui_preview",
            "pid": pid,
            "endpoint": {"host": "127.0.0.1", "port": 5179},
        }
    return {
        "schemaVersion": 1,
        "status": "ready",
        "mode": "scripted_readonly_policy",
        "pid": pid,
        "profileId": value.profile_id,
        "endpoints": {
            key: {"host": "127.0.0.1", "port": PORTS[key]}
            for key in ("native", "sms", "read", "receiver")
        },
        "roomControl": {
            "nodeEpoch": str(uuid4()),
            "generation": "0",
            "recoveryRequired": False,
            "endpoint": {"host": "127.0.0.1", "port": 11029},
        },
        "nativeBridge": {
            "prepareEndpoint": {"host": "127.0.0.1", "port": 11030},
            "rehydrationEndpoint": {"host": "127.0.0.1", "port": 11032},
        },
    }


class Contracts(unittest.TestCase):
    def setUp(self):
        self.directory = Path("/trusted/repository")

    def test_fixed_role_argv_and_immutable_environment(self):
        for role in ("specialist", "gateway", "ui"):
            with self.subTest(role=role):
                value = spec(self.directory, role)
                argv = value.argv()
                self.assertEqual(argv[0], NODE)
                self.assertNotIn(".env", " ".join(argv))
                self.assertNotIn("P3_DEMO_SPECIALIST_BEARER", " ".join(argv))
                self.assertNotIn("shell", " ".join(argv))
                with self.assertRaises(TypeError):
                    value.environment["EVIL"] = "x"
                if role == "ui":
                    self.assertIn("import {preview} from 'vite'", argv[3])
                    self.assertIn("strictPort:true", argv[3])
                    self.assertEqual(set(value.environment), set(BASE))
                elif role == "gateway":
                    self.assertEqual(
                        argv[-4:],
                        (
                            "--room-control",
                            str(value.room_control),
                            "--native-bridge",
                            str(value.native_bridge),
                        ),
                    )
                else:
                    self.assertEqual(
                        set(value.environment), set(BASE) | {"P3_DEMO_SPECIALIST_BEARER"}
                    )

    def test_role_environment_rejects_unrelated_or_missing_secrets(self):
        for role in ("specialist", "gateway", "ui"):
            value = spec(self.directory, role)
            for key in ("OPENAI_API_KEY", "NODE_OPTIONS", "PGPORT", "HTTP_PROXY", "PYTHONPATH"):
                with self.subTest(role=role, key=key), self.assertRaises(m.ChildError):
                    m.role_environment(role, dict(value.environment) | {key: "PRIVATE"})
        with self.assertRaises(m.ChildError):
            m.role_environment("specialist", BASE)
        with self.assertRaises(m.ChildError):
            m.role_environment("ui", BASE | {"P3_DEMO_SPECIALIST_BEARER": "s" * 43})

    def test_ready_frames_bind_actual_pid_profile_and_all_endpoints(self):
        for role in ("specialist", "gateway", "ui"):
            value = spec(self.directory, role)
            original = ready(value)
            self.assertEqual(m.ready_frame(json.dumps(original).encode(), value, 123), original)
            for changed in (
                {**original, "pid": 124},
                {**original, "private": "PRIVATE"},
                {**original, "schemaVersion": True},
            ):
                with self.subTest(role=role, changed=changed), self.assertRaises(m.ChildError):
                    m.ready_frame(json.dumps(changed).encode(), value, 123)
        value = spec(self.directory, "gateway")
        for field, replacement in (
            ("profileId", str(uuid4())),
            ("roomControl", {**ready(value)["roomControl"], "generation": "00"}),
            (
                "nativeBridge",
                {
                    "prepareEndpoint": {"host": "localhost", "port": 11030},
                    "rehydrationEndpoint": {"host": "127.0.0.1", "port": 11032},
                },
            ),
        ):
            with self.subTest(field=field), self.assertRaises(m.ChildError):
                m.ready_frame(json.dumps(ready(value) | {field: replacement}).encode(), value, 123)

    def test_closed_frames_are_not_resource_reap_proof_and_are_closed(self):
        value = spec(self.directory)
        closed = {
            "schemaVersion": 1,
            "status": "closed",
            "label": "scripted",
            "cleanupComplete": True,
            "metrics": {"calls": 0, "closed": True},
        }
        self.assertTrue(m.terminal_frame(closed, value, 1))
        for changed in (
            closed | {"extra": "PRIVATE"},
            closed | {"metrics": {"code": "PRIVATE"}},
            closed | {"cleanupComplete": False},
        ):
            with self.assertRaises(m.ChildError):
                m.terminal_frame(changed, value, 1)

    def test_quiescence_ack_requires_requested_ready_pid_profile_and_original_node_incarnation(
        self,
    ):
        value = spec(self.directory, "gateway")
        original = ready(value)
        ack = {
            "schemaVersion": 1,
            "status": "dispatch_quiesced",
            "mode": "scripted_readonly_policy",
            "pid": 123,
            "profileId": value.profile_id,
            "nodeEpoch": original["roomControl"]["nodeEpoch"],
        }
        m.dispatch_quiesced_frame(ack, value, 123, original, True)
        for changed, observed, requested in (
            (ack, None, True),
            (ack, original, False),
            (ack | {"pid": 124}, original, True),
            (ack | {"profileId": str(uuid4())}, original, True),
            (ack | {"nodeEpoch": str(uuid4())}, original, True),
            (ack | {"schemaVersion": True}, original, True),
            (ack | {"log": "uncontrolled"}, original, True),
        ):
            with self.subTest(ack=changed, requested=requested), self.assertRaises(m.ChildError):
                m.dispatch_quiesced_frame(changed, value, 123, observed, requested)

    def test_invalid_specs_fail_before_process_allocation(self):
        value = spec(self.directory)
        for values in (
            {"role": "shell"},
            {"ports": PORTS | {"native": True}},
            {"node": Path("relative")},
            {"profile_id": str(uuid4()).upper()},
            {"room_control": self.directory / "unexpected"},
        ):
            with self.subTest(values=values), self.assertRaises(m.ChildError):
                dataclasses.replace(value, **values)


class ActualChildren(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name).resolve()
        self.owners = []
        self.executions = []
        self.real_spawn = asyncio.create_subprocess_exec

    async def asyncTearDown(self):
        async with asyncio.timeout(4):
            for owner in self.owners:
                await owner.close()
        self.temporary.cleanup()

    def owner(self, role="specialist"):
        result = m.RoleChild(spec(self.directory, role))
        self.owners.append(result)
        return result

    def harmless(self, owner, extra="", before=None):
        async def spawn(*argv, **kwargs):
            self.assertEqual(argv, owner.spec.argv())
            self.assertEqual(kwargs["env"], dict(owner.spec.environment))
            self.assertEqual(kwargs["cwd"], owner.spec.cwd())
            self.assertTrue(kwargs["start_new_session"])
            self.assertNotIn("shell", kwargs)
            self.executions.append(owner.spec.role)
            if before is not None:
                await before.wait()
            row = ready(owner.spec)
            source = (
                "const ready="
                + json.dumps(row)
                + ";ready.pid=process.pid;"
                + extra
                + ";process.stdout.write(JSON.stringify(ready)+'\\n');process.once('SIGTERM',()=>{process.stdout.write(JSON.stringify({schemaVersion:1,status:'closed',label:'scripted',cleanupComplete:true,metrics:{}})+'\\n');process.exitCode=0;clearInterval(timer);});const timer=setInterval(()=>{},1000);"
            )
            # Only the test substitution is arbitrary. Production argv and exact
            # role environment were asserted before this harmless program runs.
            kwargs["cwd"] = self.directory
            return await self.real_spawn(NODE, "-e", source, **kwargs)

        return patch.object(m.asyncio, "create_subprocess_exec", spawn)

    def gateway_control(self, owner, *, before=None):
        async def spawn(*argv, **kwargs):
            self.assertEqual(argv, owner.spec.argv())
            self.assertEqual(kwargs["env"], dict(owner.spec.environment))
            self.executions.append(owner.spec.role)
            if before is not None:
                await before.wait()
            row = ready(owner.spec)
            source = (
                "const ready=" + json.dumps(row) + ";ready.pid=process.pid;let sent=false;"
                "process.on('SIGUSR1',()=>{if(sent)return;sent=true;setTimeout(()=>"
                "process.stdout.write(JSON.stringify({schemaVersion:1,status:'dispatch_quiesced',"
                "mode:ready.mode,pid:process.pid,profileId:ready.profileId,"
                "nodeEpoch:ready.roomControl.nodeEpoch})+'\\n'),100);});"
                "process.once('SIGTERM',()=>{process.stdout.write(JSON.stringify({schemaVersion:1,"
                "status:'closed',cleanupComplete:true,metrics:{}})+'\\n');clearInterval(timer);});"
                "const timer=setInterval(()=>{},1000);process.stdout.write(JSON.stringify(ready)+'\\n');"
            )
            kwargs["cwd"] = self.directory
            return await self.real_spawn(NODE, "-e", source, **kwargs)

        return patch.object(m.asyncio, "create_subprocess_exec", spawn)

    async def test_actual_gateway_quiesce_survives_cancelled_waiter_and_keeps_control_process_live(
        self,
    ):
        owner = self.owner("gateway")
        with self.gateway_control(owner):
            await owner.start()
            await owner.wait_ready(asyncio.get_running_loop().time() + 2)
            waiting = asyncio.create_task(owner.quiesce_dispatch())
            async with asyncio.timeout(1):
                while not owner._quiesce_requested:
                    await asyncio.sleep(0)
            waiting.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiting
            self.assertFalse(owner._quiesce.done())
            await owner.quiesce_dispatch()
            self.assertTrue(owner._quiesced.is_set())
            self.assertFalse(owner._wait.done())
            self.assertFalse(owner.facts()["reaped"])
            await owner.close()
        self.assertTrue(owner.facts()["gracefulClosed"])

    async def test_quiesce_waits_for_late_spawn_then_proves_absence_if_no_ready_was_adopted(self):
        owner, release = self.owner("gateway"), asyncio.Event()
        with self.gateway_control(owner, before=release):
            starting = asyncio.create_task(owner.start())
            async with asyncio.timeout(1):
                while not self.executions:
                    await asyncio.sleep(0)
            quiescing = asyncio.create_task(owner.quiesce_dispatch())
            await asyncio.sleep(0)
            self.assertFalse(owner._quiesce_requested)
            self.assertFalse(quiescing.done())
            release.set()
            await starting
            await quiescing
            self.assertFalse(owner._quiesce_requested)
            self.assertTrue(owner.facts()["reaped"])
            self.assertTrue(owner.facts()["groupAbsent"])
            await owner.close()

    async def test_alive_gateway_without_ready_is_reaped_before_app_dependency_can_close(self):
        owner = self.owner("gateway")
        actual_spawn = self.real_spawn

        async def quiet_gateway(*argv, **kwargs):
            self.assertEqual(argv, owner.spec.argv())
            kwargs["cwd"] = self.directory
            return await actual_spawn(
                NODE,
                "-e",
                "process.on('SIGTERM',()=>{clearInterval(timer)});"
                "const timer=setInterval(()=>{},1000);",
                **kwargs,
            )

        with patch.object(m.asyncio, "create_subprocess_exec", quiet_gateway):
            await owner.start()
            with self.assertRaises(m.ChildError):
                await owner.wait_ready(asyncio.get_running_loop().time() + 0.1)
            self.assertIsNone(owner._frame)
            self.assertIsNone(owner._process.returncode)
            # The launcher awaits this barrier before Parent.close/App cleanup.
            async with asyncio.timeout(1):
                await owner.quiesce_dispatch()
            self.assertTrue(owner.facts()["reaped"])
            self.assertTrue(owner.facts()["groupAbsent"])
            self.assertFalse(owner._quiesce_requested)
            self.assertFalse(owner._quiesced.is_set())
            with self.assertRaises(ProcessLookupError):
                os.killpg(owner.pid, 0)

    async def test_gateway_quiesce_before_start_fences_later_spawn_without_an_ack(self):
        owner = self.owner("gateway")
        await owner.quiesce_dispatch()
        self.assertIsNone(owner._process)
        self.assertFalse(owner._quiesced.is_set())
        with self.assertRaises(m.ChildError):
            await owner.start()
        self.assertIsNone(owner._spawn)

    async def test_reaped_gateway_needs_no_quiesce_ack_to_prove_no_dispatch_owner(self):
        owner = self.owner("gateway")
        with self.gateway_control(owner):
            await owner.start()
            await owner.wait_ready(asyncio.get_running_loop().time() + 2)
            await owner.close()
            await owner.quiesce_dispatch()
        self.assertFalse(owner._quiesce_requested)
        self.assertTrue(owner.facts()["reaped"])
        self.assertTrue(owner.facts()["groupAbsent"])

    async def test_real_node_ready_then_sigterm_reap_and_group_absence(self):
        owner = self.owner()
        with self.harmless(owner):
            await owner.start()
            row = await owner.wait_ready(asyncio.get_running_loop().time() + 2)
            self.assertEqual(row["pid"], owner.pid)
            self.assertFalse(owner.facts()["reaped"])
            await owner.close()
        facts = owner.facts()
        self.assertEqual(
            (facts["returncode"], facts["reaped"], facts["groupAbsent"]), (0, True, True)
        )
        self.assertFalse(facts["failed"])
        with self.assertRaises(ProcessLookupError):
            os.killpg(owner.pid, 0)

    async def test_cancelled_spawn_waiter_retains_actual_late_child(self):
        owner, release = self.owner(), asyncio.Event()
        with self.harmless(owner, before=release):
            waiter = asyncio.create_task(owner.start())
            async with asyncio.timeout(1):
                while not self.executions:
                    await asyncio.sleep(0)
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
            closer = asyncio.create_task(owner.close())
            await asyncio.sleep(0)
            self.assertFalse(closer.done())
            release.set()
            await closer
        self.assertTrue(owner.facts()["reaped"])
        self.assertTrue(owner.facts()["groupAbsent"])

    async def test_overlong_stdout_is_discarded_and_never_ready(self):
        owner = self.owner()
        with self.harmless(owner, "process.stdout.write('x'.repeat(9000)+'\\n')"):
            await owner.start()
            await asyncio.wait_for(owner.wait_terminal(), 2)
            with self.assertRaises(m.ChildError):
                await owner.wait_ready(asyncio.get_running_loop().time() + 1)
            await owner.close()
        self.assertTrue(owner.facts()["failed"])
        self.assertIsNone(owner._frame)

    async def test_stderr_is_discarded_with_a_saturated_counter(self):
        owner = self.owner()
        with self.harmless(owner, "process.stderr.write('PRIVATE'.repeat(160000))"):
            await owner.start()
            await asyncio.wait_for(owner.wait_terminal(), 2)
            with self.assertRaises(m.ChildError):
                await owner.wait_ready(asyncio.get_running_loop().time() + 1)
            await owner.close()
        self.assertEqual(owner.facts()["stderrBytesCapped"], m.STDERR_CAP + 1)
        self.assertNotIn("PRIVATE", repr(owner.facts()))

    async def test_allocation_failure_keeps_created_child_for_close_retry(self):
        owner = self.owner()
        original = m._task
        failures = 1

        def allocation(action, **kwargs):
            nonlocal failures
            if getattr(action, "cr_code", None).co_name == "_actual_wait" and failures:
                failures -= 1
                action.close()
                raise m.ChildError("cleanup_incomplete")
            return original(action, **kwargs)

        with self.harmless(owner), patch.object(m, "_task", allocation):
            with self.assertRaises(m.ChildError):
                await owner.start()
            self.assertIsNotNone(owner.pid)
            await owner.close()
        self.assertTrue(owner.facts()["groupAbsent"])

    def preview_fixture(self):
        # Actual pinned public Vite.preview serves only this private tiny HTML;
        # no application gateway, database, admin credential or proxy is used.
        import services

        repository = Path(services.__file__).resolve().parents[1]
        ui = self.directory / "apps/local-console"
        ui.mkdir(parents=True)
        (ui / "node_modules").symlink_to(
            repository / "apps/local-console/node_modules", target_is_directory=True
        )
        (ui / "vite.channel-policy.config.ts").write_text(
            "export default {root:"
            + json.dumps(str(ui))
            + ",appType:'mpa',build:{outDir:'dist-channel-policy'},server:{proxy:{}},preview:{host:'127.0.0.1',port:5179,strictPort:true}};"
        )
        (ui / "dist-channel-policy").mkdir()
        (ui / "dist-channel-policy/channel-policy.html").write_text(
            "<!doctype html><title>private_preview_ok</title>"
        )
        return self.owner("ui")

    async def test_actual_public_preview_fixed_command_closes_gracefully(self):
        owner = self.preview_fixture()
        await owner.start()
        await owner.wait_ready(asyncio.get_running_loop().time() + 5)
        self.assertIsNotNone(owner._process.stdin)

        def get():
            with closing(http.client.HTTPConnection("127.0.0.1", 5179, timeout=2)) as connection:
                connection.request("GET", "/channel-policy.html")
                response = connection.getresponse()
                return response.status, response.read(4096)

        code, body = await asyncio.to_thread(get)
        self.assertEqual(code, 200)
        self.assertIn(b"private_preview_ok", body)
        await owner.close()
        facts = owner.facts()
        self.assertEqual(facts["returncode"], 0)
        self.assertTrue(facts["closedFrameObserved"])
        self.assertTrue(facts["gracefulClosed"])
        self.assertTrue(facts["groupAbsent"])
        self.assertFalse(facts["failed"])
        self.assertTrue(owner._process.stdin.is_closing())

    async def test_actual_public_preview_external_sigterm_is_physical_not_graceful(self):
        owner = self.preview_fixture()
        await owner.start()
        await owner.wait_ready(asyncio.get_running_loop().time() + 5)
        owner._process.send_signal(signal.SIGTERM)
        await asyncio.shield(owner._wait)
        await owner.close()
        facts = owner.facts()
        self.assertEqual(facts["returncode"], 143)
        self.assertFalse(facts["closedFrameObserved"])
        self.assertFalse(facts["gracefulClosed"])
        self.assertTrue(facts["failed"])
        self.assertTrue(facts["groupAbsent"])

    async def test_cancelled_or_failed_owned_reader_cannot_claim_drained(self):
        for failure in ("cancelled", "failed"):
            with self.subTest(failure=failure):
                owner = self.owner()
                with self.harmless(owner):
                    await owner.start()
                    await owner.wait_ready(asyncio.get_running_loop().time() + 2)
                    original = owner._readers["stdout"]
                    original.cancel()
                    await asyncio.gather(original, return_exceptions=True)
                    if failure == "failed":

                        async def broken():
                            raise RuntimeError("PRIVATE_READER")

                        owner._readers["stdout"] = asyncio.create_task(broken())
                        await asyncio.gather(owner._readers["stdout"], return_exceptions=True)
                    with self.assertRaises(m.ChildError) as caught:
                        await owner.close()
                    self.assertEqual(caught.exception.code, "cleanup_incomplete")
                    self.assertTrue(owner.facts()["reaped"])
                    self.assertFalse(owner.facts()["groupAbsent"])
                    self.assertNotIn("stdout", owner._drained)

                    # Test-only deliberate backfill observes the real remaining
                    # pipe to EOF; no failed task is relabelled successful.
                    async def drain(value=owner):
                        while await value._process.stdout.read(4096):
                            pass
                        value._drained.add("stdout")

                    owner._readers["stdout"] = asyncio.create_task(drain())
                    await owner.close()
                    self.assertTrue(owner.facts()["groupAbsent"])

    async def test_queued_cancel_does_not_spawn_new_process(self):
        owner = self.owner()

        async def call():
            asyncio.current_task().cancel()
            await owner.start()

        with self.harmless(owner), self.assertRaises(asyncio.CancelledError):
            await asyncio.create_task(call())
        self.assertFalse(self.executions)
        await owner.close()
