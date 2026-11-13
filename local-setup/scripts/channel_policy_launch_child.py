"""Closed specialist/gateway/prebuilt-UI child ownership; import starts no I/O."""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import stat
from collections.abc import Coroutine, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PosixPath
from types import MappingProxyType
from typing import Any, Literal, TypeVar, cast

Role = Literal["specialist", "gateway", "ui"]
BASE = frozenset({"PATH", "LANG", "CI", "NO_COLOR", "__CF_USER_TEXT_ENCODING"})
GATEWAY = frozenset(
    {
        "P2_DEMO_POSTGRES_PASSWORD",
        "P2_DEMO_ACCOUNT_TOKEN",
        "P2_DEMO_NATIVE_PUBLISHER_TOKEN",
        "P2_DEMO_RESULT_PUBLISHER_TOKEN",
        "P2_DEMO_WORKER_BEARER",
        "P2_DEMO_NATIVE_ORIGIN_BEARER",
        "P2_DEMO_SMS_ORIGIN_BEARER",
        "P2_DEMO_CASE_AUTHORIZATION",
    }
)
SPECIALIST = frozenset({"P3_DEMO_SPECIALIST_BEARER"})
STDOUT_CAP, STDERR_CAP, FRAME_CAP, FRAME_COUNT = 262144, 1048576, 8192, 16
T = TypeVar("T")


class ChildError(RuntimeError):
    def __init__(self, code: str = "unavailable") -> None:
        self.code = (
            code
            if type(code) is str
            and code in {"invalid_configuration", "unavailable", "closed", "cleanup_incomplete"}
            else "unavailable"
        )
        super().__init__(self.code)


def need(value: bool, code: str = "invalid_configuration") -> None:
    if not value:
        raise ChildError(code)


def _task(action: Coroutine[Any, Any, T], *, cleanup: bool = False) -> asyncio.Task[T]:
    try:
        result = asyncio.create_task(action, eager_start=False)
    except BaseException as error:
        action.close()
        if isinstance(error, Exception):
            raise ChildError("cleanup_incomplete" if cleanup else "unavailable") from None
        raise
    result.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return result


def role_environment(role: Role, values: Mapping[str, str]) -> dict[str, str]:
    try:
        extras = (
            GATEWAY if role == "gateway" else SPECIALIST if role == "specialist" else frozenset()
        )
        need(role in {"gateway", "specialist", "ui"} and isinstance(values, Mapping))
        need(not set(values) - BASE - extras and {"PATH", "LANG"} | extras <= set(values))
        result: dict[str, str] = {}
        for key, value in values.items():
            need(
                type(key) is str
                and type(value) is str
                and 0 < len(value.encode("utf-8", "strict")) <= 4096
                and "\0" not in value
            )
            if key in extras:
                if key == "P2_DEMO_POSTGRES_PASSWORD":
                    need(32 <= len(value) and len(value.encode("utf-16-le")) <= 256)
                elif key == "P2_DEMO_CASE_AUTHORIZATION":
                    need(re.fullmatch(r"Bearer [A-Za-z0-9_-]{43}", value, re.ASCII) is not None)
                else:
                    need(re.fullmatch(r"[A-Za-z0-9_-]{43}", value, re.ASCII) is not None)
            result[key] = value
        return result
    except Exception:  # noqa: BLE001 - closed secret-role configuration boundary
        raise ChildError("invalid_configuration") from None


# Public pinned Vite.preview owns exactly this prebuilt UI, with no HMR or
# credentials. A late preview startup remains observed after SIGTERM; no forced
# exit can strand its real listener. Python owns the whole process through reap.
UI_CLOSE_COMMAND = b'{"schemaVersion":1,"command":"close"}\n'
UI_PREVIEW = r"""
import {preview} from 'vite';
let server, stopRequested=false, release, failed=false, commandReceived=false;
const stopped=new Promise(r=>release=r);
const expected=Buffer.from('{"schemaVersion":1,"command":"close"}\n');
let input=Buffer.alloc(0);
const emit=(status,extra={})=>process.stdout.write(JSON.stringify({schemaVersion:1,status,mode:'scripted_ui_preview',pid:process.pid,...extra})+'\n');
const stop=()=>{stopRequested=true;release();};
const onData=chunk=>{
 if(commandReceived||input.length+chunk.length>expected.length){failed=true;stop();return;}
 input=Buffer.concat([input,chunk]);
 if(!input.equals(expected.subarray(0,input.length))){failed=true;stop();return;}
 if(input.length===expected.length){commandReceived=true;stop();}
};
const onEnd=()=>{if(!commandReceived)failed=true;stop();};
process.stdin.on('data',onData);process.stdin.on('end',onEnd);
process.once('SIGTERM',stop);process.once('SIGINT',stop);
try{
 if(process.argv.length!==2)throw Error();
 const actual=preview({configFile:process.argv[1],logLevel:'silent',preview:{host:'127.0.0.1',port:5179,strictPort:true}});
 actual.then(value=>{server=value;},()=>{});
 await Promise.race([actual,stopped]);
 if(!stopRequested){
  server=await actual;
  const endpoint=server.httpServer.address();
  if(!endpoint||typeof endpoint==='string'||endpoint.address!=='127.0.0.1'||endpoint.port!==5179)throw Error();
  emit('ready',{endpoint:{host:'127.0.0.1',port:5179}});
  await stopped;
 }
 await actual.catch(()=>{});
}catch{failed=true;emit('unavailable',{code:'unavailable'});}
finally{
 try{if(server)await server.close();emit('closed',{cleanupComplete:true});}
 catch{failed=true;emit('unavailable',{code:'cleanup_incomplete'});}
 // Public preview.close removes Vite's own stdin-end/SIGTERM exit callbacks.
 // Keep this pipe open until that teardown; only now destroy our input owner.
 process.stdin.off('data',onData);process.stdin.off('end',onEnd);
 process.stdin.destroy();
 process.off('SIGTERM',stop);process.off('SIGINT',stop);
}
process.exitCode=failed?1:0;
"""


@dataclass(frozen=True, slots=True)
class ChildSpec:
    role: Role
    repository: Path
    node: Path
    profile_id: str
    ports: Mapping[str, int]
    environment: Mapping[str, str] = field(repr=False)
    configuration: Path | None = field(default=None, repr=False)
    room_control: Path | None = field(default=None, repr=False)
    native_bridge: Path | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        need(type(self.role) is str and self.role in {"specialist", "gateway", "ui"})
        for path in (self.repository, self.node):
            need(type(path) is PosixPath and path.is_absolute())
        need(
            type(self.profile_id) is str
            and re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                self.profile_id,
                re.ASCII,
            )
            is not None
        )
        need(set(self.ports) == {"native", "sms", "read", "receiver", "specialist"})
        copied = {
            key: self.ports[key] for key in ("native", "sms", "read", "receiver", "specialist")
        }
        need(
            all(type(value) is int and 1 <= value <= 65535 for value in copied.values())
            and len(set(copied.values())) == 5
        )
        for configured_path in (self.configuration, self.room_control, self.native_bridge):
            need(
                configured_path is None
                or type(configured_path) is PosixPath
                and configured_path.is_absolute()
            )
        need((self.configuration is not None) == (self.role != "ui"))
        need(
            (self.room_control is not None and self.native_bridge is not None)
            if self.role == "gateway"
            else self.room_control is None and self.native_bridge is None
        )
        object.__setattr__(self, "ports", MappingProxyType(copied))
        object.__setattr__(
            self, "environment", MappingProxyType(role_environment(self.role, self.environment))
        )

    def argv(self) -> tuple[str, ...]:
        if self.role == "ui":
            return (
                str(self.node),
                "--input-type=module",
                "-e",
                UI_PREVIEW,
                str(self.repository / "apps/local-console/vite.channel-policy.config.ts"),
            )
        entry = "serve.js" if self.role == "gateway" else "specialist-serve.js"
        base = (
            str(self.node),
            str(self.repository / "services/channel-policy-gateway/dist" / entry),
            "--config",
            str(self.configuration),
        )
        return base + (
            ("--room-control", str(self.room_control), "--native-bridge", str(self.native_bridge))
            if self.role == "gateway"
            else ()
        )

    def cwd(self) -> Path:
        return self.repository / (
            "apps/local-console" if self.role == "ui" else "services/channel-policy-gateway"
        )


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        need(key not in result, "unavailable")
        result[key] = value
    return result


def _invalid(_: str) -> object:
    raise ChildError()


def _fields(value: object, names: set[str]) -> dict[str, object]:
    need(type(value) is dict and set(value) == names, "unavailable")
    return cast(dict[str, object], value)


def _endpoint(value: object, port: int) -> None:
    data = _fields(value, {"host", "port"})
    need(
        type(data["host"]) is str
        and data["host"] == "127.0.0.1"
        and type(data["port"]) is int
        and data["port"] == port,
        "unavailable",
    )


def ready_frame(raw: bytes, spec: ChildSpec, pid: int) -> dict[str, object]:
    need(type(raw) is bytes and 0 < len(raw) <= FRAME_CAP, "unavailable")
    try:
        value: object = json.loads(
            raw.decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_invalid
        )
        data = cast(dict[str, object], value)
        common = {"schemaVersion", "status", "mode", "pid"}
        expected = common | (
            {"label", "endpoint"}
            if spec.role == "specialist"
            else {"endpoint"}
            if spec.role == "ui"
            else {"profileId", "endpoints", "roomControl", "nativeBridge"}
        )
        data = _fields(data, expected)
        need(
            type(data["schemaVersion"]) is int
            and data["schemaVersion"] == 1
            and data["status"] == "ready"
            and type(data["pid"]) is int
            and data["pid"] == pid,
            "unavailable",
        )
        if spec.role == "specialist":
            need(
                data["mode"] == "scripted_fixed_policy" and data["label"] == "scripted",
                "unavailable",
            )
            _endpoint(data["endpoint"], spec.ports["specialist"])
        elif spec.role == "ui":
            need(data["mode"] == "scripted_ui_preview", "unavailable")
            _endpoint(data["endpoint"], 5179)
        else:
            need(
                data["mode"] == "scripted_readonly_policy" and data["profileId"] == spec.profile_id,
                "unavailable",
            )
            endpoints = _fields(data["endpoints"], {"native", "sms", "read", "receiver"})
            for key, endpoint in endpoints.items():
                _endpoint(endpoint, spec.ports[key])
            cursor = _fields(
                data["roomControl"], {"nodeEpoch", "endpoint", "generation", "recoveryRequired"}
            )
            from services.channel_policy_demo.native_room_state import NodeRoomCursor

            _endpoint(cursor["endpoint"], 11029)
            NodeRoomCursor(
                cast(str, cursor["nodeEpoch"]),
                cast(str, cursor["generation"]),
                cast(bool, cursor["recoveryRequired"]),
                11029,
            )
            bridge = _fields(data["nativeBridge"], {"prepareEndpoint", "rehydrationEndpoint"})
            _endpoint(bridge["prepareEndpoint"], 11030)
            _endpoint(bridge["rehydrationEndpoint"], 11032)
        return data
    except Exception:  # noqa: BLE001 - received frames never become diagnostics
        raise ChildError() from None


def terminal_frame(value: object, spec: ChildSpec, pid: int) -> bool:
    """Closed terminal DTOs contain only finite counters, never arbitrary text."""
    data = _fields(
        value,
        {"schemaVersion", "status"}
        | (
            {"label"}
            if spec.role == "specialist"
            else {"mode", "pid"}
            if spec.role == "ui"
            else set()
        )
        | (
            {"code"}
            if type(value) is dict and value.get("status") == "unavailable"
            else {"cleanupComplete", "metrics"}
            if spec.role != "ui"
            else {"cleanupComplete"}
        ),
    )
    need(
        type(data["schemaVersion"]) is int
        and data["schemaVersion"] == 1
        and type(data["status"]) is str
        and data["status"] in {"closed", "unavailable"},
        "unavailable",
    )
    if spec.role == "specialist":
        need(data["label"] == "scripted", "unavailable")
    if spec.role == "ui":
        need(
            data["mode"] == "scripted_ui_preview"
            and type(data["pid"]) is int
            and data["pid"] == pid,
            "unavailable",
        )
    if data["status"] == "unavailable":
        need(
            type(data["code"]) is str
            and data["code"]
            in {"invalid_configuration", "unavailable", "closed", "cleanup_incomplete"},
            "unavailable",
        )
        return False
    need(data["cleanupComplete"] is True, "unavailable")
    if spec.role != "ui":
        metrics = data["metrics"]
        need(
            type(metrics) is dict
            and len(metrics) <= 64
            and all(
                type(key) is str
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", key, re.ASCII) is not None
                and (type(number) is bool or type(number) is int and 0 <= number <= 1_000_000_000)
                for key, number in metrics.items()
            ),
            "unavailable",
        )
    return True


class RoleChild:
    """One retained spawn, bounded discarded stdio, one actual wait/stop/reap."""

    def __init__(self, spec: ChildSpec) -> None:
        need(type(spec) is ChildSpec)
        self.spec = spec
        self._spawn: asyncio.Task[asyncio.subprocess.Process] | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._readers: dict[str, asyncio.Task[None]] = {}
        self._drained: set[str] = set()
        self._wait: asyncio.Task[int] | None = None
        self._stop: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._terminal = asyncio.Event()
        self._frame: dict[str, object] | None = None
        self._closed_frame = False
        self._closing = self._failed = self._reaped = self._group_absent = self._signalled = False
        self._stdout = self._stderr = self._frames = 0

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    def facts(self) -> dict[str, object]:
        code = self._process.returncode if self._process is not None else None
        settled = self._reaped and self._drained == {"stdout", "stderr"}
        failed = self._failed or settled and (code != 0 or not self._closed_frame)
        return {
            "role": self.spec.role,
            "pid": self.pid,
            "returncode": code,
            "reaped": self._reaped,
            "groupAbsent": self._group_absent,
            "closedFrameObserved": self._closed_frame,
            "gracefulClosed": settled
            and self._group_absent
            and not failed
            and code == 0
            and self._closed_frame,
            "failed": failed,
            "stdoutBytesCapped": self._stdout,
            "stderrBytesCapped": self._stderr,
        }

    async def _actual_spawn(self) -> asyncio.subprocess.Process:
        def check() -> None:
            info = self.spec.node.stat()
            need(stat.S_ISREG(info.st_mode) and bool(info.st_mode & 0o111))
            need(self.spec.repository.resolve(strict=True) == self.spec.repository)

        await asyncio.to_thread(check)
        need(not self._closing, "closed")
        process = await asyncio.create_subprocess_exec(
            *self.spec.argv(),
            cwd=self.spec.cwd(),
            env=dict(self.spec.environment),
            stdin=asyncio.subprocess.PIPE if self.spec.role == "ui" else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            limit=FRAME_CAP + 1,
        )
        self._process = process
        self._observe(process)
        return process

    def _observe(self, process: asyncio.subprocess.Process) -> None:
        failed = False
        if self._wait is None:
            try:
                self._wait = _task(self._actual_wait(process))
            except Exception:  # noqa: BLE001 - retain child while missing observers retry
                failed = True
        for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
            if name not in self._readers and pipe is not None:
                try:
                    self._readers[name] = _task(
                        self._stdout_read(pipe) if name == "stdout" else self._stderr_read(pipe)
                    )
                except Exception:  # noqa: BLE001 - independently attempt both pipe owners
                    failed = True
        need(
            not failed and process.stdout is not None and process.stderr is not None,
            "cleanup_incomplete",
        )

    async def start(self) -> None:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise asyncio.CancelledError
        need(not self._closing, "closed")
        if self._spawn is None:
            self._spawn = _task(self._actual_spawn())
        try:
            await asyncio.shield(self._spawn)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - finite process boundary
            raise ChildError() from None

    async def wait_ready(self, deadline: float) -> dict[str, object]:
        need(self._spawn is not None, "unavailable")
        try:
            async with asyncio.timeout_at(min(deadline, asyncio.get_running_loop().time() + 15)):
                await self._ready.wait()
            need(
                not self._closing
                and not self._failed
                and self._frame is not None
                and self._process is not None
                and self._process.returncode is None,
                "unavailable",
            )
            assert self._frame is not None
            return dict(self._frame)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - no stderr/body disclosure
            raise ChildError() from None

    async def wait_terminal(self) -> None:
        await self._terminal.wait()

    async def _actual_wait(self, process: asyncio.subprocess.Process) -> int:
        code = await process.wait()
        self._reaped = True
        self._ready.set()
        self._terminal.set()
        return code

    async def _stdout_read(self, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    self._drained.add("stdout")
                    return
                self._stdout = min(STDOUT_CAP + 1, self._stdout + len(raw))
                self._frames = min(FRAME_COUNT + 1, self._frames + 1)
                need(
                    len(raw) <= FRAME_CAP
                    and raw.endswith(b"\n")
                    and self._stdout <= STDOUT_CAP
                    and self._frames <= FRAME_COUNT,
                    "unavailable",
                )
                value = json.loads(
                    raw.decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_invalid
                )
                need(type(value) is dict, "unavailable")
                if value.get("status") == "ready":
                    need(self._frame is None and self._process is not None, "unavailable")
                    assert self._process is not None
                    self._frame = ready_frame(raw, self.spec, self._process.pid)
                    self._ready.set()
                elif value.get("status") in {"closed", "unavailable"}:
                    need(self._process is not None, "unavailable")
                    assert self._process is not None
                    closed = terminal_frame(value, self.spec, self._process.pid)
                    self._closed_frame = self._closed_frame or closed
                    self._terminal.set()
                    self._failed = self._failed or not closed
                else:
                    raise ChildError()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - malformed output fences ready but pipe remains drained
            self._failed = True
            self._ready.set()
            self._terminal.set()
            while await reader.read(4096):
                pass
            self._drained.add("stdout")

    async def _stderr_read(self, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                raw = await reader.read(4096)
                if not raw:
                    self._drained.add("stderr")
                    return
                self._stderr = min(STDERR_CAP + 1, self._stderr + len(raw))
                if self._stderr > STDERR_CAP:
                    self._failed = True
                    self._terminal.set()
                    self._ready.set()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - pipe failure fences readiness without diagnostics
            self._failed = True
            self._terminal.set()
            self._ready.set()

    async def _actual_stop(self) -> None:
        if self._spawn is not None:
            await asyncio.gather(asyncio.shield(self._spawn), return_exceptions=True)
        process = self._process
        if process is None:
            self._group_absent = True
            return
        self._observe(process)
        if process.returncode is None and not self._signalled:
            self._signalled = True
            if self.spec.role == "ui":
                need(process.stdin is not None, "cleanup_incomplete")
                assert process.stdin is not None
                try:
                    process.stdin.write(UI_CLOSE_COMMAND)
                    await process.stdin.drain()
                except Exception:  # noqa: BLE001 - possible control write; retain actual wait/drain
                    self._failed = True
            else:
                try:
                    process.send_signal(signal.SIGTERM)
                except ProcessLookupError:
                    pass
        assert self._wait is not None
        await asyncio.shield(self._wait)
        await asyncio.gather(*self._readers.values(), return_exceptions=True)
        if process.stdin is not None:
            process.stdin.close()
            try:
                await process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                # The public pipe reports its already-closed peer; actual wait
                # and every read EOF below remain separate cleanup evidence.
                self._failed = True
        need(
            set(self._readers) == {"stdout", "stderr"}
            and self._drained == {"stdout", "stderr"}
            and all(
                not value.cancelled() and value.exception() is None
                for value in self._readers.values()
            ),
            "cleanup_incomplete",
        )
        need(self._reaped and process.returncode is not None, "cleanup_incomplete")
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            self._group_absent = True
            return
        except PermissionError:
            raise ChildError("cleanup_incomplete") from None
        raise ChildError("cleanup_incomplete")

    async def close(self) -> None:
        self._closing = True
        if (
            self._stop is None
            or self._stop.done()
            and (self._stop.cancelled() or self._stop.exception() is not None)
        ):
            self._stop = _task(self._actual_stop(), cleanup=True)
        try:
            async with asyncio.timeout(15):
                await asyncio.shield(self._stop)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - actual owner retained
            raise ChildError("cleanup_incomplete") from None
