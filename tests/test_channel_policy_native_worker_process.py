"""Owned harmless children exercise exact fixed-command/process lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import signal
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from services.channel_policy_demo import native_worker_process as worker_module
from services.channel_policy_demo.native_room_state import NativeRoomError


def child_program(
    *, stages: tuple[str, ...] = ("prepare_ready",), invalid: bool = False, stderr_bytes: int = 0
) -> str:
    frames = [
        json.dumps(
            {
                "schemaVersion": 1,
                "component": "channel_policy_native_worker",
                "mode": "scripted",
                "state": stage,
                **({"reason": "participant_disconnected"} if stage == "session_closed" else {}),
            },
            separators=(",", ":"),
        )
        for stage in stages
    ]
    return "\n".join(
        (
            "import json,signal,sys,time",
            "stopped=False",
            "def stop(*args):\n global stopped\n stopped=True",
            "signal.signal(signal.SIGTERM,stop)",
            f"frames={frames!r}",
            "for frame in frames: print(frame,flush=True)",
            "print('PRIVATE_BAD_FRAME',flush=True)" if invalid else "pass",
            f"sys.stderr.write('x'*{stderr_bytes});sys.stderr.flush()",
            "while not stopped: time.sleep(0.005)",
            "print(json.dumps({'schemaVersion':1,'component':'channel_policy_native_worker','mode':'scripted','state':'closed'},separators=(',',':')),flush=True)",
        )
    )


CHILD_GROUP_TESTS = frozenset(
    {
        "test_original_venv_path_fixed_role_environment_and_real_reap",
        "test_sdk_close_observation_is_terminal_for_admission_before_actual_reap",
        "test_late_spawn_after_cancel_remains_owned_and_stop_reaps_it",
        "test_partial_observer_allocation_retains_real_child_and_stop_backfills_pipe",
        "test_wrong_order_ready_never_becomes_sdk_ready_or_prepare_ready",
        "test_malformed_stdout_is_private_and_still_drains_and_reaps",
        "test_stderr_excess_is_not_retained_and_graceful_stop_still_reaps",
        "test_start_timeout_cannot_drop_held_actual_spawn",
        "test_early_exit_wakes_readiness_without_fabricating_prepare_fact",
        "test_held_signal_cleanup_retains_owner_until_actual_exit",
    }
)


class ChildGroupRecords:
    """Test-only per-child handshake; serving code has no registry hook or key."""

    def __init__(self, directory: Path, nonce: str) -> None:
        assert re.fullmatch(r"[a-f0-9]{32}", nonce)
        self.directory = directory
        self.nonce = nonce
        if not directory.exists():
            directory.mkdir(mode=0o700)
        meta = directory.lstat()
        assert directory.resolve() == directory and stat.S_ISDIR(meta.st_mode)
        assert stat.S_IMODE(meta.st_mode) == 0o700 and meta.st_uid == os.geteuid()
        self.slots: list[Path] = []

    @staticmethod
    def write(directory: Path, name: str, value: dict[str, object]) -> None:
        raw = json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
        assert len(raw) <= 512
        pending = directory / (name + ".pending")
        fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(raw)
        os.link(pending, directory / name, follow_symlinks=False)
        pending.unlink()

    @staticmethod
    def read(directory: Path, name: str) -> dict[str, object] | None:
        try:
            fd = os.open(directory / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, "rb") as source:
            before = os.fstat(source.fileno())
            assert stat.S_ISREG(before.st_mode) and stat.S_IMODE(before.st_mode) == 0o600
            assert before.st_uid == os.geteuid() and before.st_nlink in (1, 2)
            assert 0 < before.st_size <= 512
            if before.st_nlink == 2:
                try:
                    pending = (directory / (name + ".pending")).lstat()
                except FileNotFoundError:
                    assert os.fstat(source.fileno()).st_nlink == 1
                    return None
                assert (pending.st_dev, pending.st_ino) == (before.st_dev, before.st_ino)
                return None
            raw = source.read(513)
            after = os.fstat(source.fileno())
            assert (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        value = json.loads(raw)
        assert type(value) is dict
        return value

    def allocate(self, test_id: str, program: str) -> Path:
        assert test_id.rsplit(".", 1)[-1] in CHILD_GROUP_TESTS
        assert len(self.slots) < 10
        slot = self.directory / ("child-" + str(len(self.slots) + 1).zfill(2))
        slot.mkdir(mode=0o700)
        self.slots.append(slot)
        self.write(
            slot,
            "descriptor.json",
            {
                "schemaVersion": 1,
                "nonce": self.nonce,
                "slot": slot.name,
                "parentPid": os.getpid(),
                "testId": test_id,
                "programSha256": hashlib.sha256(program.encode()).hexdigest(),
                "lifetimeDeadlineNs": time.monotonic_ns() + 5_000_000_000,
            },
        )
        return slot

    async def admit(self, process: asyncio.subprocess.Process, slot: Path) -> None:
        async with asyncio.timeout(1):
            while (started := self.read(slot, "started.json")) is None:
                assert process.returncode is None
                await asyncio.sleep(0.001)
        assert type(started.get("schemaVersion")) is int
        assert started == {
            "schemaVersion": 1,
            "nonce": self.nonce,
            "slot": slot.name,
            "parentPid": os.getpid(),
            "pid": process.pid,
            "pgid": process.pid,
        }
        self.write(
            slot,
            "go.json",
            {
                "schemaVersion": 1,
                "nonce": self.nonce,
                "slot": slot.name,
                "pid": process.pid,
                "pgid": process.pid,
            },
        )

    async def settled(
        self,
        process: asyncio.subprocess.Process,
        slot: Path,
        owner: worker_module.NativeWorkerProcess,
    ) -> None:
        result = await process.wait()
        assert owner.status().reaped and not owner.status().running and owner.pending_count == 0
        descriptor = self.read(slot, "descriptor.json")
        assert descriptor is not None
        name = str(descriptor["testId"]).rsplit(".", 1)[-1]
        allowed = (
            {2}
            if name == "test_early_exit_wakes_readiness_without_fabricating_prepare_fact"
            else {0, -signal.SIGTERM}
            if name
            in {
                "test_late_spawn_after_cancel_remains_owned_and_stop_reaps_it",
                "test_start_timeout_cannot_drop_held_actual_spawn",
            }
            else {0}
        )
        assert result in allowed
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError("owned_child_group_not_absent")
        self.write(
            slot,
            "settled.json",
            {
                "schemaVersion": 1,
                "nonce": self.nonce,
                "slot": slot.name,
                "pid": process.pid,
                "pgid": process.pid,
                "returncode": result,
                "directReaped": True,
                "pipesDrained": True,
                "groupAbsent": True,
            },
        )

    def proof(self) -> dict[str, object]:
        assert len(self.slots) == 10
        groups = []
        for slot in self.slots:
            descriptor = self.read(slot, "descriptor.json")
            started = self.read(slot, "started.json")
            go = self.read(slot, "go.json")
            settled = self.read(slot, "settled.json")
            assert (
                descriptor is not None
                and started is not None
                and go is not None
                and settled is not None
            )
            assert (
                settled["directReaped"] is True
                and settled["pipesDrained"] is True
                and settled["groupAbsent"] is True
            )
            groups.append(
                {
                    "test_id": descriptor["testId"],
                    "slot": slot.name,
                    "parent_pid": descriptor["parentPid"],
                    "pid": started["pid"],
                    "pgid": started["pgid"],
                    "returncode": settled["returncode"],
                    "direct_reaped": True,
                    "pipes_drained": True,
                    "group_absent": True,
                }
            )
        assert {str(g["test_id"]).rsplit(".", 1)[-1] for g in groups} == CHILD_GROUP_TESTS
        return {"schema_version": 1, "nonce": self.nonce, "groups": groups}


_external_child_records: ChildGroupRecords | None = None


def configure_child_records(directory: Path, nonce: str) -> None:
    """Explicit installed-consumer seam; ordinary source tests use the same protocol."""
    global _external_child_records
    assert _external_child_records is None
    _external_child_records = ChildGroupRecords(directory, nonce)


def child_group_proof() -> dict[str, object]:
    assert _external_child_records is not None
    return _external_child_records.proof()


def child_bootstrap(program: str, slot: Path, nonce: str, parent: int) -> str:
    """A harmless child records its own session before GO; no parent PID signal."""
    descriptor = ChildGroupRecords.read(slot, "descriptor.json")
    assert descriptor is not None
    value = {
        "slot": str(slot),
        "nonce": nonce,
        "parent": parent,
        "program": program,
        "deadline": descriptor["lifetimeDeadlineNs"],
    }
    return r"""import json,os,signal,stat,threading,time
from pathlib import Path
value=BOOTSTRAP_VALUE
slot=Path(value['slot']);nonce=value['nonce'];parent=value['parent'];born=time.monotonic()
meta=slot.lstat()
assert slot.resolve()==slot and stat.S_ISDIR(meta.st_mode) and stat.S_IMODE(meta.st_mode)==0o700 and meta.st_uid==os.geteuid()
def publish(name,body):
 raw=json.dumps(body,separators=(',',':')).encode();assert len(raw)<=512
 pending=slot/(name+'.pending')
 fd=os.open(pending,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb')as out:out.write(raw)
 os.link(pending,slot/name,follow_symlinks=False);pending.unlink()
assert not(slot/'go.json').exists()and not(slot/'go.json').is_symlink()
publish('started.json',{'schemaVersion':1,'nonce':nonce,'slot':slot.name,'parentPid':os.getppid(),'pid':os.getpid(),'pgid':os.getpgrp()})
if time.monotonic_ns()>=value['deadline']:raise SystemExit(3)
deadline=min(time.monotonic()+1,value['deadline']/1_000_000_000)
while True:
 if os.getppid()!=parent:raise SystemExit(3)
 try:fd=os.open(slot/'go.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 except FileNotFoundError:
  if time.monotonic()>=deadline:raise SystemExit(3)
  time.sleep(0.001);continue
 with os.fdopen(fd,'rb')as source:
  meta=os.fstat(source.fileno())
  assert stat.S_ISREG(meta.st_mode)and stat.S_IMODE(meta.st_mode)==0o600 and meta.st_uid==os.geteuid()and meta.st_nlink in (1,2) and 0<meta.st_size<=512
  if meta.st_nlink==2:
   try:pending=(slot/'go.json.pending').lstat()
   except FileNotFoundError:assert os.fstat(source.fileno()).st_nlink==1
   else:assert(pending.st_dev,pending.st_ino)==(meta.st_dev,meta.st_ino)
   if time.monotonic()>=deadline:raise SystemExit(3)
   time.sleep(0.001);continue
  go=json.loads(source.read(513))
 assert type(go.get('schemaVersion'))is int
 assert go=={'schemaVersion':1,'nonce':nonce,'slot':slot.name,'pid':os.getpid(),'pgid':os.getpgrp()}
 break
if time.monotonic_ns()>=value['deadline']:raise SystemExit(3)
finished=threading.Event();hard=value['deadline']/1_000_000_000-0.6
def watchdog():
 while not finished.wait(0.01):
  if os.getppid()!=parent or time.monotonic()>=hard:
   os.kill(os.getpid(),signal.SIGTERM)
   if not finished.wait(0.5):os._exit(143)
   return
threading.Thread(target=watchdog,daemon=True).start()
try:exec(compile(value['program'],'<harmless-worker>','exec'),globals())
finally:finished.set()
""".replace("BOOTSTRAP_VALUE", repr(value))


class WorkerProcessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(delete=False)
        self.directory = Path(self.temporary.name).resolve()
        self.config = self.directory / "worker.json"
        self.config.write_bytes(b"{}")
        self.config.chmod(0o600)
        self.python = Path(sys.executable)
        self.environment = {"PATH": "/usr/bin:/bin", "LANG": "C", "NO_COLOR": "1"}
        self.children: list[worker_module.NativeWorkerProcess] = []
        self.actual_spawn = asyncio.create_subprocess_exec
        self.records = _external_child_records or ChildGroupRecords(
            self.directory / "child-records", uuid4().hex
        )
        self.raw_children: list[
            tuple[asyncio.subprocess.Process, Path, worker_module.NativeWorkerProcess]
        ] = []

    async def asyncTearDown(self) -> None:
        for child in self.children:
            async with asyncio.timeout(2):
                for _ in range(3):
                    try:
                        await child.stop()
                        break
                    except NativeRoomError as error:
                        if error.code != "cleanup_incomplete":
                            raise
        for process, slot, owner in self.raw_children:
            async with asyncio.timeout(2):
                await self.records.settled(process, slot, owner)
        self.temporary.cleanup()

    def owner(self, **keywords: float) -> worker_module.NativeWorkerProcess:
        result = worker_module.NativeWorkerProcess(
            self.python, self.config, self.environment, **keywords
        )
        self.children.append(result)
        return result

    def launch(self, program: str):
        actual = self.actual_spawn
        expected = (
            str(self.python),
            "-I",
            "-B",
            "-m",
            "services.channel_policy_demo.native_worker",
            "--config",
            str(self.config),
        )

        async def spawn(*arguments: str, **keywords: object) -> asyncio.subprocess.Process:
            self.assertEqual(arguments, expected)
            self.assertEqual(keywords["env"], self.environment)
            self.assertEqual(keywords["cwd"], str(self.directory))
            self.assertIs(keywords["start_new_session"], True)
            # Exercise a real owned process, substituting only its fixed worker
            # program with a harmless finite stdout/signal implementation.
            slot = self.records.allocate(self.id(), program)
            process = await actual(
                str(self.python),
                "-I",
                "-B",
                "-c",
                child_bootstrap(program, slot, self.records.nonce, os.getpid()),
                **keywords,
            )
            self.raw_children.append((process, slot, self.children[-1]))
            await self.records.admit(process, slot)
            return process

        return patch.object(worker_module.asyncio, "create_subprocess_exec", side_effect=spawn)

    async def test_original_venv_path_fixed_role_environment_and_real_reap(self) -> None:
        owner = self.owner()
        with self.launch(
            child_program(
                stages=("prepare_ready", "room_connected", "waiting_participant", "ready")
            )
        ):
            await owner.start()
            await owner.wait_prepare()
            async with asyncio.timeout(1):
                while not owner.status().sdk_ready:
                    await asyncio.sleep(0)
            before = owner.status()
            self.assertTrue(before.running)
            self.assertFalse(before.reaped)
            await owner.stop()
        after = owner.status()
        self.assertFalse(after.running)
        self.assertTrue(after.reaped)
        self.assertEqual(after.returncode, 0)
        self.assertEqual(owner.pending_count, 0)
        self.assertEqual(owner._python, self.python)

    async def test_sdk_close_observation_is_terminal_for_admission_before_actual_reap(self) -> None:
        owner = self.owner()
        with self.launch(
            child_program(
                stages=(
                    "prepare_ready",
                    "room_connected",
                    "waiting_participant",
                    "ready",
                    "session_closed",
                )
            )
        ):
            await owner.start()
            await owner.wait_terminal()
            observed = owner.status()
            self.assertEqual(observed.stage, "session_closed")
            self.assertFalse(observed.sdk_ready)
            self.assertTrue(observed.running)
            self.assertFalse(observed.reaped)
            await owner.stop()
        self.assertEqual(owner.pending_count, 0)

    async def test_late_spawn_after_cancel_remains_owned_and_stop_reaps_it(self) -> None:
        owner = self.owner()
        entered, release = asyncio.Event(), asyncio.Event()
        with self.launch(child_program()) as launched:
            ordinary = launched.side_effect

            async def held(*arguments: str, **keywords: object) -> asyncio.subprocess.Process:
                entered.set()
                await release.wait()
                return await ordinary(*arguments, **keywords)

            launched.side_effect = held
            caller = asyncio.create_task(owner.start())
            await entered.wait()
            caller.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await caller
            self.assertEqual(owner.pending_count, 1)
            stopping = asyncio.create_task(owner.stop())
            release.set()
            await stopping
        self.assertEqual(owner.pending_count, 0)
        self.assertTrue(owner.status().reaped)

    async def test_partial_observer_allocation_retains_real_child_and_stop_backfills_pipe(
        self,
    ) -> None:
        owner = self.owner()
        actual = asyncio.create_task
        failed = False

        def allocate(operation, *arguments, **keywords):
            nonlocal failed
            if operation.cr_code.co_name == "_read_stderr" and not failed:
                failed = True
                raise RuntimeError("PRIVATE_PIPE_TASK")
            return actual(operation, *arguments, **keywords)

        with self.launch(child_program(stderr_bytes=worker_module.STDERR_BYTES + 4096)):
            with (
                patch.object(worker_module.asyncio, "create_task", side_effect=allocate),
                self.assertRaises(NativeRoomError) as caught,
            ):
                await owner.start()
            self.assertEqual(str(caught.exception), "unavailable")
            self.assertTrue(owner.status().spawned)
            self.assertEqual(owner.pending_count, 1)
            await owner.wait_prepare()
            await owner.stop()
        self.assertTrue(failed)
        self.assertTrue(owner.status().reaped)
        self.assertEqual(owner.pending_count, 0)

    async def test_queued_cancel_does_not_spawn_but_cleanup_remains_available(self) -> None:
        owner = self.owner()

        async def cancelled() -> None:
            task = asyncio.current_task()
            assert task is not None
            task.cancel()
            await owner.start()

        with patch.object(worker_module.asyncio, "create_subprocess_exec") as spawn:
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.create_task(cancelled())
            spawn.assert_not_called()
        await owner.stop()
        self.assertEqual(owner.pending_count, 0)

    async def test_wrong_order_ready_never_becomes_sdk_ready_or_prepare_ready(self) -> None:
        owner = self.owner(prepare_timeout_s=0.1)
        with self.launch(child_program(stages=("ready",))):
            await owner.start()
            with self.assertRaises(NativeRoomError):
                await owner.wait_prepare()
            self.assertTrue(owner.status().protocol_failed)
            self.assertFalse(owner.status().sdk_ready)
            self.assertFalse(owner.status().prepare_ready)
            await owner.stop()
        self.assertEqual(owner.pending_count, 0)

    async def test_malformed_stdout_is_private_and_still_drains_and_reaps(self) -> None:
        owner = self.owner()
        with self.launch(child_program(invalid=True)):
            await owner.start()
            async with asyncio.timeout(1):
                while not owner.status().protocol_failed:
                    await asyncio.sleep(0)
            with self.assertRaises(NativeRoomError) as caught:
                await owner.wait_prepare()
            self.assertEqual(str(caught.exception), "unavailable")
            await owner.stop()
        self.assertEqual(owner.pending_count, 0)

    async def test_stderr_excess_is_not_retained_and_graceful_stop_still_reaps(self) -> None:
        owner = self.owner()
        with self.launch(child_program(stderr_bytes=worker_module.STDERR_BYTES + 4096)):
            await owner.start()
            async with asyncio.timeout(1):
                while not owner.status().protocol_failed:
                    await asyncio.sleep(0)
            await owner.stop()
        self.assertEqual(owner.pending_count, 0)
        self.assertGreater(owner._stderr_bytes, worker_module.STDERR_BYTES)
        self.assertNotIn("xxxx", repr(vars(owner)))

    async def test_start_timeout_cannot_drop_held_actual_spawn(self) -> None:
        owner = self.owner(prepare_timeout_s=0.02)
        entered, release = asyncio.Event(), asyncio.Event()
        with self.launch(child_program()) as launched:
            ordinary = launched.side_effect

            async def held(*arguments: str, **keywords: object) -> asyncio.subprocess.Process:
                entered.set()
                await release.wait()
                return await ordinary(*arguments, **keywords)

            launched.side_effect = held
            caller = asyncio.create_task(owner.start())
            await entered.wait()
            with self.assertRaises(NativeRoomError):
                await caller
            self.assertEqual(owner.pending_count, 1)
            release.set()
            await owner.stop()
        self.assertTrue(owner.status().reaped)

    async def test_early_exit_wakes_readiness_without_fabricating_prepare_fact(self) -> None:
        owner = self.owner()
        with self.launch("raise SystemExit(2)"):
            await owner.start()
            with self.assertRaises(NativeRoomError):
                await owner.wait_prepare()
            await owner.stop()
        self.assertTrue(owner.status().reaped)
        self.assertFalse(owner.status().prepare_ready)
        self.assertEqual(owner.status().returncode, 2)

    async def test_held_signal_cleanup_retains_owner_until_actual_exit(self) -> None:
        owner = self.owner(cleanup_timeout_s=0.02)
        program = child_program().replace(
            "while not stopped: time.sleep(0.005)",
            "while not stopped: time.sleep(0.005)\ntime.sleep(0.1)",
        )
        with self.launch(program):
            await owner.start()
            await owner.wait_prepare()
            with self.assertRaises(NativeRoomError) as caught:
                await owner.stop()
            self.assertEqual(caught.exception.code, "cleanup_incomplete")
            self.assertEqual(owner.pending_count, 1)
            await owner.wait_exit()
            async with asyncio.timeout(1):
                while owner.pending_count:
                    try:
                        await owner.stop()
                    except NativeRoomError as error:
                        self.assertEqual(error.code, "cleanup_incomplete")
        self.assertTrue(owner.status().reaped)

    async def test_closed_environment_rejects_provider_pg_and_python_injection(self) -> None:
        for name in ("OPENAI_API_KEY", "PGPASSWORD", "PYTHONPATH", "NODE_OPTIONS"):
            with self.subTest(name=name):
                with self.assertRaises(NativeRoomError) as caught:
                    worker_module.NativeWorkerProcess(
                        self.python, self.config, {**self.environment, name: "PRIVATE_SENTINEL"}
                    )
                self.assertEqual(str(caught.exception), "invalid_input")
        with self.assertRaises(NativeRoomError):
            worker_module.NativeWorkerProcess(Path("python"), self.config, self.environment)

    async def test_wait_exit_is_observation_only_and_never_starts_worker(self) -> None:
        owner = self.owner()
        with patch.object(worker_module.asyncio, "create_subprocess_exec") as spawn:
            with self.assertRaises(NativeRoomError):
                await owner.wait_exit()
            spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
