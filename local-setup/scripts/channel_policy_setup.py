"""Explicit fresh owner bootstrap; imports and --plan perform no configuration I/O.

Serving never imports this tool. Partial or uncertain DDL is retained for manual
inspection, with no reset/drop/repair or automatic new-identity retry.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import re
import secrets
import selectors
import signal
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Coroutine, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date
from inspect import getattr_static
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, TypeVar, cast
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from continuity_lab.case_control_api import CaseSnapshot
    from continuity_lab.postgres_api import ManagedReceipt, PostgresSettings
    from services.channel_policy_demo.owner_config import OwnerProfile, ProfilePolicy

T = TypeVar("T")
Code = Literal["invalid_arguments", "invalid_setup", "already_exists", "unavailable", "aborted"]
_NODE_SECONDS = 60.0
_REAP_SECONDS = 5.0
_STREAM_BYTES = 32768
_SCHEMA = re.compile(r"(?:cp45_case_|p1_work_cp45_|cp45_channel_)[0-9a-f]{32}")


class SetupError(ValueError):
    def __init__(self, code: Code = "unavailable") -> None:
        self.code: Code = (
            code
            if type(code) is str
            and code
            in {"invalid_arguments", "invalid_setup", "already_exists", "unavailable", "aborted"}
            else "unavailable"
        )
        super().__init__(self.code)


def _need(condition: bool) -> None:
    if not condition:
        raise SetupError("invalid_setup")


def _password(value: object) -> str:
    _need(type(value) is str)
    try:
        text = cast(str, value)
        text.encode("utf-8", "strict")
        _need(32 <= len(text) and len(text.encode("utf-16-le")) // 2 <= 128)
        _need(not any(ord(c) < 33 or ord(c) == 127 for c in text))
        return text
    except UnicodeError:
        raise SetupError("invalid_setup") from None


@dataclass(frozen=True, slots=True)
class SetupDatabase:
    port: int
    runtime_password: str = field(repr=False)
    owner_password: str = field(repr=False)

    def __post_init__(self) -> None:
        _need(type(self.port) is int and 1 <= self.port <= 65535)
        _password(self.runtime_password)
        _password(self.owner_password)
        _need(self.runtime_password != self.owner_password)


class NodeMigrationPort(Protocol):
    """On cancellation, stop/reap actual child before propagating cancellation."""

    async def upgrade(
        self, *, node: Path, cwd: Path, port: int, schema: str, owner_password: str
    ) -> str: ...


def _json(value: object) -> bytes:
    try:
        return (json.dumps(value, separators=(",", ":"), allow_nan=False) + "\n").encode()
    except (ValueError, TypeError, UnicodeError):
        raise SetupError("invalid_setup") from None


def _publish(path: Path, raw: bytes) -> None:
    """Complete private bytes before final visibility; never overwrite any final."""
    pending = path.with_name(".pending-" + uuid4().hex)
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        created = True
        remaining = memoryview(raw)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError
            remaining = remaining[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.link(pending, path, follow_symlinks=False)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        # Only this call's exclusively created pending path is removable.
        if created:
            pending.unlink()


def _task(action: Coroutine[object, object, T]) -> asyncio.Task[T]:
    try:
        task = asyncio.create_task(action)
    except BaseException:
        action.close()
        raise
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return task


def _admit_business() -> None:
    current = asyncio.current_task()
    if current is not None and current.cancelling():
        raise asyncio.CancelledError


async def _retained(
    action: Coroutine[object, object, T],
    *,
    adopt: Callable[[T], None] | None = None,
    cleanup: bool = False,
) -> T:
    if not cleanup:
        try:
            _admit_business()
        except BaseException:
            action.close()
            raise
    task = _task(action)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:  # noqa: BLE001 - observe retained task; caller normalizes failure
            break
    value = task.result()
    if adopt is not None:
        adopt(value)
    if cancelled:
        raise asyncio.CancelledError
    return value


def _uuid(value: object) -> str:
    _need(type(value) is str)
    try:
        parsed = UUID(cast(str, value))
        _need(str(parsed) == value and parsed.version == 4)
    except (ValueError, AttributeError):
        raise SetupError("invalid_setup") from None
    return cast(str, value)


def _repository() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_database(repository: Path) -> SetupDatabase:
    # The exact maintained loader reads only .env/.secrets.env/images.env.
    path = repository / "local-setup/stack.py"
    spec = importlib.util.spec_from_file_location("channel_policy_setup_stack", path)
    _need(spec is not None and spec.loader is not None)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        values: object = module.load_settings(repository / "local-setup")
        _need(type(values) is dict)
        data = cast(dict[str, str], values)
        return SetupDatabase(
            int(data["POSTGRES_PORT"]),
            data["POSTGRES_PASSWORD"],
            data["POSTGRES_MIGRATION_PASSWORD"],
        )
    finally:
        sys.modules.pop(spec.name, None)


def _settings(database: SetupDatabase, schema: str, *, owner: bool) -> PostgresSettings:
    from continuity_lab.postgres_api import PostgresSettings

    return PostgresSettings(
        port=database.port,
        user="continuity_migrator" if owner else "livekit_lab",
        password=database.owner_password if owner else database.runtime_password,
        schema=schema,
    )


def _fresh_namespaces(settings: PostgresSettings, schemas: tuple[str, str, str]) -> None:
    with closing(settings.connect(application_name="continuity-migrate")) as connection:
        for schema in schemas:
            _need(
                connection.execute(
                    "SELECT 1 FROM pg_namespace WHERE nspname=%s", [schema]
                ).fetchone()
                is None
            )


async def _install_case(settings: PostgresSettings) -> None:
    from continuity_lab.postgres_migrations import (
        activate_import,
        install_schema,
        stage_import,
        upgrade_v2,
        upgrade_v3,
        upgrade_v4,
    )
    from continuity_lab.transfer import make_snapshot

    await _retained(asyncio.to_thread(install_schema, settings))
    snapshot = make_snapshot([], [], [], migration_id=str(uuid4()))
    await _retained(asyncio.to_thread(stage_import, settings, snapshot))
    await _retained(
        asyncio.to_thread(activate_import, settings, snapshot.migration_id, snapshot.source_digest)
    )
    await _retained(asyncio.to_thread(upgrade_v2, settings))
    await _retained(asyncio.to_thread(upgrade_v3, settings))
    await _retained(asyncio.to_thread(upgrade_v4, settings))


async def _install_work(settings: PostgresSettings) -> None:
    from continuity_lab.work_admin import (
        ExecutionLimits,
        WorkLimits,
        install_work_schema,
        upgrade_work_schema_v2,
        upgrade_work_schema_v3,
        upgrade_work_schema_v4,
    )

    await _retained(asyncio.to_thread(install_work_schema, settings, WorkLimits(16, 16)))
    await _retained(
        asyncio.to_thread(upgrade_work_schema_v2, settings, ExecutionLimits(4, 2, 10000))
    )
    await _retained(asyncio.to_thread(upgrade_work_schema_v3, settings))
    await _retained(asyncio.to_thread(upgrade_work_schema_v4, settings))


class _CaseOwner(Protocol):
    @property
    def pending_count(self) -> int: ...
    async def close(self) -> None: ...


async def _close_clients(clients: list[_CaseOwner], journal: Callable[[str], None]) -> None:
    async def close(client: _CaseOwner) -> None:
        await client.close()
        _need(type(client.pending_count) is int and client.pending_count == 0)

    pending: dict[int, asyncio.Task[None]] = {}
    cancelled = incomplete = False
    while clients:
        for client in tuple(clients):
            task = pending.get(id(client))
            if task is None or task.done() and (task.cancelled() or task.exception() is not None):
                try:
                    pending[id(client)] = _task(close(client))
                except asyncio.CancelledError:
                    cancelled = True
                except Exception:  # noqa: BLE001, S110 - retain owner for explicit retry
                    pass  # Retain the same client; later explicit observation retries setup.
        tasks = tuple(pending.values())
        if tasks:

            async def observe(observed: tuple[asyncio.Task[None], ...] = tasks) -> None:
                await asyncio.gather(
                    *(asyncio.shield(task) for task in observed), return_exceptions=True
                )

            try:
                await _retained(observe(), cleanup=True)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:  # noqa: BLE001, S110 - actual client close tasks remain owned
                pass  # Retry observation; never return while adopted close tasks are held.
        for client in tuple(clients):
            task = pending.get(id(client))
            if (
                task is not None
                and task.done()
                and not task.cancelled()
                and task.exception() is None
            ):
                clients.remove(client)
                pending.pop(id(client))
        if clients:
            if not incomplete:
                try:
                    journal("cleanup_incomplete")
                except Exception:  # noqa: BLE001, S110 - diagnostics cannot prevent drainage
                    pass  # Failed diagnostics cannot prevent owner drainage.
                incomplete = True
            try:
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                cancelled = True
    if cancelled:
        raise asyncio.CancelledError


_NODE_PROGRAM = r"""
import { installChannelSchema, upgradeChannelSchemaV2, upgradeChannelSchemaV3,
 upgradeChannelSchemaV4, upgradeChannelSchemaV5, upgradeChannelSchemaV6,
 upgradeChannelSchemaV7, upgradeChannelSchemaV8, upgradeChannelSchemaV9 } from '@livekit-ecosystem/channel-continuity/migrations';
let stopped=false;process.on('SIGTERM',()=>{stopped=true;});process.on('SIGINT',()=>{stopped=true;});
try {
 const chunks=[];let size=0;for await(const chunk of process.stdin){size+=chunk.length;if(size>2048)throw Error();chunks.push(chunk);}
 const p=JSON.parse(Buffer.concat(chunks).toString('utf8'));
 if(Object.keys(p).sort().join(',')!=='port,schema,schema_version'||p.schema_version!==1||!Number.isSafeInteger(p.port)||p.port<1||p.port>65535||typeof p.schema!=='string'||!/^cp45_channel_[0-9a-f]{32}$/.test(p.schema))throw Error();
 const allowed=['PATH','LANG','CI','NO_COLOR','__CF_USER_TEXT_ENCODING','CHANNEL_POLICY_SETUP_OWNER_PASSWORD'];
 if(Object.keys(process.env).some(k=>!allowed.includes(k)))throw Error();
 const password=process.env.CHANNEL_POLICY_SETUP_OWNER_PASSWORD;
 if(typeof password!=='string'||password.length<32||password.length>128)throw Error();
 const settings={host:'127.0.0.1',port:p.port,database:'livekit_lab',user:'continuity_migrator',password,schema:p.schema};
 const steps=[()=>installChannelSchema(settings,{maxInbox:16,maxChallenges:16,maxAssociations:16,maxSenders:16}),
 ()=>upgradeChannelSchemaV2(settings,{maxActive:2,maxAttempts:2,leaseMs:5000,retryDelayMs:100}),
 ()=>upgradeChannelSchemaV3(settings,{maxReplies:16,maxRoutes:16,maxAttempts:2}),
 ()=>upgradeChannelSchemaV4(settings,{maxGlobal:64,maxPerAttempt:8}),
 ()=>upgradeChannelSchemaV5(settings,{maxRecoveryCommands:16,maxPerOperation:2}),
 ()=>upgradeChannelSchemaV6(settings,{maxBindings:16}),
 ()=>upgradeChannelSchemaV7(settings,{maxResponses:16,maxObservations:64,maxObservationsPerResponse:8}),
 ()=>upgradeChannelSchemaV8(settings),
 ()=>upgradeChannelSchemaV9(settings)];
 let receiver;for(const [index,step] of steps.entries()){if(stopped)throw Error();const value=await step();if(index===7)receiver=value;}
 if(stopped||typeof receiver!=='string'||!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(receiver))throw Error();
 process.stdout.write(JSON.stringify({schema_version:1,receiver_id:receiver})+'\n');
} catch { process.stderr.write('{"schema_version":1,"code":"unavailable"}\n');process.exitCode=1; }
"""


def _group_alive(process: subprocess.Popen[bytes]) -> bool:
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return False
    return True


def _reap(process: subprocess.Popen[bytes]) -> None:
    if _group_alive(process):
        os.killpg(process.pid, signal.SIGTERM)
    deadline = time.monotonic() + _REAP_SECONDS
    killed = False
    while True:
        process.poll()
        if process.returncode is not None and not _group_alive(process):
            process.wait()
            return
        if not killed and time.monotonic() >= deadline - _REAP_SECONDS / 2:
            if _group_alive(process):
                os.killpg(process.pid, signal.SIGKILL)
            killed = True
        # A still-owned uninterruptible group cannot be represented as reaped.
        # Keep this exact owner alive after the bounded unsuccessful observation.
        time.sleep(0.02)


def _node_child(
    node: Path,
    cwd: Path,
    program: str,
    private_environment: Mapping[str, str],
    request: Mapping[str, object],
    abort: threading.Event,
    started: Callable[[int], None] | None = None,
) -> bytes:
    """Run one closed-environment Node program; return stdout only after a clean reap."""
    process = subprocess.Popen(
        [str(node), "--input-type=module", "--eval", program],
        cwd=cwd,
        env={
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "CI": "1",
            "NO_COLOR": "1",
            **private_environment,
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        if started is not None:
            started(process.pid)
        assert (
            process.stdin is not None and process.stdout is not None and process.stderr is not None
        )
        process.stdin.write(_json(dict(request)))
        process.stdin.close()
        captured = {"stdout": bytearray(), "stderr": bytearray()}
        deadline = time.monotonic() + _NODE_SECONDS
        with selectors.DefaultSelector() as observer:
            for stream, name in ((process.stdout, "stdout"), (process.stderr, "stderr")):
                os.set_blocking(stream.fileno(), False)
                observer.register(stream, selectors.EVENT_READ, name)
            while observer.get_map() or process.poll() is None:
                if abort.is_set() or time.monotonic() >= deadline:
                    raise SetupError()
                for key, _ in observer.select(min(0.05, max(0.0, deadline - time.monotonic()))):
                    raw = os.read(key.fd, 8192)
                    if not raw:
                        observer.unregister(key.fileobj)
                    else:
                        output = captured[cast(str, key.data)]
                        _need(len(output) + len(raw) <= _STREAM_BYTES)
                        output.extend(raw)
        _need(process.wait(timeout=1) == 0 and not _group_alive(process) and not captured["stderr"])
        return bytes(captured["stdout"])
    finally:
        _reap(process)
        for owned_stream in (process.stdin, process.stdout, process.stderr):
            if owned_stream is not None:
                owned_stream.close()


def _single_line_result(raw: bytes, field: str) -> object:
    value: object = json.loads(raw)
    _need(type(value) is dict and set(value) == {"schema_version", field})
    data = cast(dict[str, object], value)
    _need(type(data["schema_version"]) is int and data["schema_version"] == 1)
    _need(_json(data) == raw)
    return data[field]


def _run_node(
    node: Path,
    cwd: Path,
    port: int,
    schema: str,
    password: str,
    abort: threading.Event,
    started: Callable[[int], None] | None = None,
) -> str:
    raw = _node_child(
        node,
        cwd,
        _NODE_PROGRAM,
        {"CHANNEL_POLICY_SETUP_OWNER_PASSWORD": password},
        {"schema_version": 1, "port": port, "schema": schema},
        abort,
        started,
    )
    return _uuid(_single_line_result(raw, "receiver_id"))


class NodeMigrations:
    def __init__(self, *, started: Callable[[int], None] | None = None) -> None:
        self._started = started

    async def upgrade(
        self, *, node: Path, cwd: Path, port: int, schema: str, owner_password: str
    ) -> str:
        _admit_business()
        abort = threading.Event()
        try:
            task = _task(
                asyncio.to_thread(
                    _run_node, node, cwd, port, schema, owner_password, abort, self._started
                )
            )
        except Exception:  # noqa: BLE001 - no child is admitted after task setup failure
            raise SetupError() from None
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
                abort.set()
            except Exception:  # noqa: BLE001 - retained result is normalized below
                break
        if cancelled:
            # Observe/consume failure before propagating waiter cancellation.
            if not task.cancelled():
                task.exception()
            raise asyncio.CancelledError
        try:
            return task.result()
        except Exception:  # noqa: BLE001 - finite child boundary never reflects diagnostics
            raise SetupError() from None


# Owner-only LINK association for the configured synthetic SMS sender. It uses
# the public P2 challenge API and the joined gateway's declared public
# synthetic_v1 signing material; no carrier key or provider credential exists.
_ASSOCIATE_PROGRAM = r"""
import { ChannelInbox, SeededAccounts } from '@livekit-ecosystem/channel-continuity/postgres';
import { createFakeSmsIntegration, signFakeSms } from '@livekit-ecosystem/channel-continuity/security';
let inbox;
try {
 const chunks=[];let size=0;for await(const chunk of process.stdin){size+=chunk.length;if(size>2048)throw Error();chunks.push(chunk);}
 const p=JSON.parse(Buffer.concat(chunks).toString('utf8'));
 const keys='accountId,caseId,conversationId,port,providerAccountId,schema,schema_version,senderId,tenantId';
 if(Object.keys(p).sort().join(',')!==keys||p.schema_version!==1||!Number.isSafeInteger(p.port)||p.port<1||p.port>65535||typeof p.schema!=='string'||!/^cp45_channel_[0-9a-f]{32}$/.test(p.schema))throw Error();
 for(const k of ['tenantId','accountId','caseId','conversationId','providerAccountId','senderId'])if(typeof p[k]!=='string'||!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(p[k]))throw Error();
 const allowed=['PATH','LANG','CI','NO_COLOR','__CF_USER_TEXT_ENCODING','CHANNEL_POLICY_SETUP_RUNTIME_PASSWORD','CHANNEL_POLICY_SETUP_ACCOUNT_TOKEN'];
 if(Object.keys(process.env).some(k=>!allowed.includes(k)))throw Error();
 const password=process.env.CHANNEL_POLICY_SETUP_RUNTIME_PASSWORD,token=process.env.CHANNEL_POLICY_SETUP_ACCOUNT_TOKEN;
 if(typeof password!=='string'||password.length<32||password.length>128||typeof token!=='string'||!/^[A-Za-z0-9_-]{43}$/.test(token))throw Error();
 const key=Buffer.alloc(32,0x4f);
 const scope={tenantId:p.tenantId,provider:'fake_sms',providerAccountId:p.providerAccountId};
 inbox=new ChannelInbox({host:'127.0.0.1',port:p.port,database:'livekit_lab',user:'livekit_lab',password,schema:p.schema},createFakeSmsIntegration(scope,key),new SeededAccounts([{token,tenantId:p.tenantId,accountId:p.accountId,caseId:p.caseId,conversationId:p.conversationId}]),{},()=>{});
 const challenge=await inbox.createChallenge(token,p.senderId);
 const eventId='cp_link_'+challenge.challengeId.replaceAll('-','');
 const signed=signFakeSms({schemaVersion:1,eventId,messageId:eventId,senderId:p.senderId,body:'LINK '+challenge.challengeId+' '+challenge.secret,occurredAt:new Date().toISOString()},key,Math.floor(Date.now()/1000),scope);
 const linked=await inbox.completeAssociation(signed.raw,signed.headers);
 if(typeof linked.associationVersion!=='string'||!/^[1-9][0-9]{0,18}$/.test(linked.associationVersion))throw Error();
 process.stdout.write(JSON.stringify({schema_version:1,association_version:linked.associationVersion})+'\n');
} catch { process.stderr.write('{"schema_version":1,"code":"unavailable"}\n');process.exitCode=1; }
finally { if(inbox)await inbox.close().catch(()=>{process.exitCode=1;}); }
"""


def _run_association(
    node: Path,
    cwd: Path,
    request: Mapping[str, object],
    password: str,
    token: str,
    abort: threading.Event,
) -> str:
    raw = _node_child(
        node,
        cwd,
        _ASSOCIATE_PROGRAM,
        {
            "CHANNEL_POLICY_SETUP_RUNTIME_PASSWORD": password,
            "CHANNEL_POLICY_SETUP_ACCOUNT_TOKEN": token,
        },
        request,
        abort,
    )
    version = _single_line_result(raw, "association_version")
    _need(type(version) is str and re.fullmatch(r"[1-9][0-9]{0,18}", version) is not None)
    return cast(str, version)


async def associate_sms(directory: Path, node: Path, *, repository: Path | None = None) -> str:
    """Associate the profile's fixed synthetic SMS sender with its case account.

    Each call issues a fresh LINK challenge and activates the next association
    epoch. Earlier accepted messages keep their original epoch as history.
    """
    from services.channel_policy_demo.operator_sms import SmsRoute
    from services.channel_policy_demo.owner_config import read_owner_profile

    repository = (_repository() if repository is None else repository).resolve(strict=True)
    _need(directory.is_absolute() and node.is_absolute())
    _need(directory.resolve(strict=True) == directory)
    _need(directory.is_relative_to(repository / ".local"))
    executable = node.resolve(strict=True)
    _need(executable.is_file() and os.access(executable, os.X_OK))
    cwd = repository / "services/channel-policy-gateway"
    _need(cwd.is_dir())
    profile = await _retained(
        asyncio.to_thread(read_owner_profile, directory / "owner-profile.json")
    )
    route = profile.route
    sender = SmsRoute(route.scope.tenant_id, profile.sms_provider_account_id).sender_id
    request = {
        "schema_version": 1,
        "port": profile.database.port,
        "schema": profile.database.channel_schema,
        "tenantId": route.scope.tenant_id,
        "accountId": route.scope.account_id,
        "caseId": route.case_id,
        "conversationId": route.conversation_id,
        "providerAccountId": profile.sms_provider_account_id,
        "senderId": sender,
    }
    _admit_business()
    abort = threading.Event()
    task = _task(
        asyncio.to_thread(
            _run_association,
            executable,
            cwd,
            request,
            profile.credentials.postgres_password,
            profile.credentials.account_token,
            abort,
        )
    )
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
            abort.set()
        except Exception:  # noqa: BLE001 - retained result is normalized below
            break
    if cancelled:
        if not task.cancelled():
            task.exception()
        raise asyncio.CancelledError
    try:
        return task.result()
    except Exception:  # noqa: BLE001 - finite child boundary never reflects diagnostics
        raise SetupError() from None


def _leaf(directory: Path, repository: Path) -> None:
    _need(directory.is_absolute() and directory.resolve(strict=False) == directory)
    _need(directory.is_relative_to(repository / ".local") and directory != repository / ".local")
    parent = directory.parent.stat()
    _need(directory.parent.resolve(strict=True) == directory.parent)
    _need(
        stat.S_ISDIR(parent.st_mode)
        and parent.st_uid == os.getuid()
        and parent.st_mode & 0o022 == 0
    )
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        raise SetupError("already_exists") from None
    actual = directory.stat()
    _need(stat.S_IMODE(actual.st_mode) == 0o700 and actual.st_uid == os.getuid())


def _policies() -> tuple[ProfilePolicy, ...]:
    from delegation_reliability.fixed_policy_contracts import produce_fixed_policy_request
    from services.channel_policy_demo.owner_config import ProfilePolicy

    policy = _json(
        {
            "schema_version": 1,
            "kind": "booking.notice_policy",
            "policy_version": "notice_v1",
            "rule_id": "notice_minimum_days",
            "minimum_notice_days": 7,
            "note": "Synthetic policy; no action permission.",
        }
    )
    result = []
    for revision, days in ((1, 10), (2, 4)):
        facts = _json(
            {
                "schema_version": 1,
                "kind": "booking.notice_facts",
                "observations": [{"fact_id": "notice_primary", "days_before_arrival": days}],
                "note": "Synthetic fixed facts.",
            }
        )
        refs = [
            {
                "source_id": source,
                "version": version,
                "sha256": hashlib.sha256(body).hexdigest(),
                "media_type": "application/json",
                "byte_length": len(body),
                "width": None,
                "height": None,
            }
            for source, version, body in (
                ("policy_notice", "policy_source_v1", policy),
                (f"facts_notice_r{revision}", f"facts_revision_{revision}", facts),
            )
        ]
        template = produce_fixed_policy_request(
            {
                "schema_version": 1,
                "kind": "delegation.request",
                "capability": "booking.evaluate_policy",
                "input_schema_version": 2,
                "scope": {"tenant_id": "tenant_demo", "account_id": "account_demo"},
                "delegation_id": f"setup_template_{revision}",
                "case_id": "case_demo",
                "request_revision": revision,
                "context_snapshot": {
                    "policy_version": "notice_v1",
                    "policy_source_id": "policy_notice",
                    "facts_source_id": f"facts_notice_r{revision}",
                },
                "evidence": refs,
                "deadline_at_ms": 1900000060000,
                "result_route": {"conversation_id": "conversation_demo"},
                "attempt": {"attempt_id": f"setup_template_{revision}", "number": 1},
            }
        )
        result.append(ProfilePolicy(template, (policy, facts)))
    return tuple(result)


async def _prepare(
    directory: Path,
    node: Path,
    *,
    database: SetupDatabase | None = None,
    repository: Path | None = None,
    migrations: NodeMigrationPort | None = None,
) -> OwnerProfile:
    from continuity_lab.api import BookingChange
    from continuity_lab.case_control_api import open_case_control_client
    from continuity_lab.postgres_api import AuthenticatedActor, BearerToken, open_postgres_client
    from delegation_reliability.contracts import Scope
    from services.channel_policy_demo.owner_config import (
        OwnerProfile,
        ProfileCase,
        ProfileCredentials,
        ProfileDatabase,
        ProfilePorts,
        ProfileRoute,
        encode_owner_profile,
        read_owner_profile,
    )

    repository = (_repository() if repository is None else repository).resolve(strict=True)
    _need(type(directory) is type(repository) and node.is_absolute())
    executable = node.resolve(strict=True)
    _need(executable.is_file() and os.access(executable, os.X_OK))
    cwd = repository / "services/channel-policy-gateway"
    _need(cwd.is_dir())
    _leaf(directory, repository)
    identity = {
        "profile_id": str(uuid4()),
        "app_owner_id": str(uuid4()),
        "case_schema": "cp45_case_" + uuid4().hex,
        "work_schema": "p1_work_cp45_" + uuid4().hex,
        "channel_schema": "cp45_channel_" + uuid4().hex,
    }
    sequence = 0

    def journal(stage: str) -> None:
        nonlocal sequence
        _publish(
            directory / f"setup-{sequence:02}.json",
            _json(
                {
                    "schema_version": 1,
                    "stage": stage,
                    "ddl_outcome": "unverified"
                    if stage in {"failed_partial", "aborted_unknown"}
                    else "stage_observation",
                    "identity": dict(identity),
                }
            ),
        )
        sequence += 1

    clients: list[_CaseOwner] = []
    try:
        journal("planned")
        db = _load_database(repository) if database is None else database
        _need(type(db) is SetupDatabase)
        db = SetupDatabase(db.port, db.runtime_password, db.owner_password)
        schemas = (identity["case_schema"], identity["work_schema"], identity["channel_schema"])
        for schema in schemas:
            _need(_SCHEMA.fullmatch(schema) is not None)
        await _retained(
            asyncio.to_thread(_fresh_namespaces, _settings(db, schemas[0], owner=True), schemas)
        )
        journal("case_install_started")
        await _install_case(_settings(db, schemas[0], owner=True))
        journal("case_installed")
        journal("work_install_started")
        await _install_work(_settings(db, schemas[1], owner=True))
        journal("work_installed")
        credentials = ProfileCredentials(
            db.runtime_password, *(secrets.token_urlsafe(32) for _ in range(10))
        )
        actor = AuthenticatedActor("channel_policy_actor", "channel_policy_scope")
        token = BearerToken(credentials.p1_case_token)
        runtime = _settings(db, schemas[0], owner=False)
        journal("case_seed_started")
        managed = await _retained(
            asyncio.to_thread(open_postgres_client, actor=actor, token=token, settings=runtime),
            adopt=clients.append,
        )
        controller = await _retained(
            asyncio.to_thread(open_case_control_client, actor=actor, token=token, settings=runtime),
            adopt=clients.append,
        )
        original = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)

        def receipt(value: ManagedReceipt) -> None:
            _need(value.created is True)
            identity["task_id"] = _uuid(value.task_id)
            identity["authority_case_id"] = _uuid(value.case_id)
            _need(value.task_id != value.case_id)

        accepted = await _retained(
            managed.submit(
                idempotency_key="cp45_setup_" + UUID(identity["profile_id"]).hex, request=original
            ),
            adopt=receipt,
        )
        initial = await _retained(controller.case(task_id=accepted.task_id))
        _case_check(initial, identity, actor.actor_id, actor.scope_id, 0, original)
        changed = BookingChange("DEMO-BK-001", date(2030, 12, 11), True)
        revised = await _retained(
            controller.revise(task_id=accepted.task_id, expected_revision=0, request=changed)
        )
        _case_check(revised, identity, actor.actor_id, actor.scope_id, 1, changed)
        journal("case_seeded_revision_one")
        await _close_clients(clients, journal)
        journal("node_upgrade_started")

        def node_started(pid: int) -> None:
            _need(type(pid) is int and pid > 1)
            identity["node_pid"] = str(pid)
            journal("node_child_started")

        migration_port = NodeMigrations(started=node_started) if migrations is None else migrations
        _admit_business()
        receiver = await migration_port.upgrade(
            node=executable,
            cwd=cwd,
            port=db.port,
            schema=schemas[2],
            owner_password=db.owner_password,
        )
        identity["receiver_id"] = _uuid(receiver)
        journal("node_upgraded")
        profile = OwnerProfile(
            ProfileRoute(
                identity["profile_id"],
                receiver,
                Scope("tenant_demo", "account_demo"),
                "case_demo",
                "conversation_demo",
                "recipient_demo",
            ),
            ProfilePorts(),
            ProfileDatabase(db.port, *schemas),
            ProfileCase(
                actor.actor_id, actor.scope_id, identity["task_id"], identity["authority_case_id"]
            ),
            credentials,
            identity["app_owner_id"],
            "joined_rtc",
            "joined_sms",
            _policies(),
        )
        _publish(directory / "owner-profile.json", encode_owner_profile(profile))
        journal("profile_published")
        _publish(directory / "node-config.json", _json(profile.node_configuration()))
        _publish(directory / "specialist-config.json", _json(profile.specialist_configuration()))
        journal("prepared")
        return read_owner_profile(directory / "owner-profile.json")
    except BaseException as error:
        try:
            journal(
                "aborted_unknown" if isinstance(error, asyncio.CancelledError) else "failed_partial"
            )
        except Exception:  # noqa: BLE001, S110 - preserve primary and owned cleanup
            pass  # Preserve primary failure and the original partial files.
        if not isinstance(error, Exception):
            raise
        if type(error) is SetupError:
            raise
        raise SetupError() from None
    finally:
        await _close_clients(clients, journal)


async def prepare(
    directory: Path,
    node: Path,
    *,
    database: SetupDatabase | None = None,
    repository: Path | None = None,
    migrations: NodeMigrationPort | None = None,
) -> OwnerProfile:
    """Finite owner boundary; actual resources drain inside the implementation."""
    try:
        _admit_business()
        return await _prepare(
            directory, node, database=database, repository=repository, migrations=migrations
        )
    except Exception as error:  # noqa: BLE001 - path/dependency details never escape this boundary
        raise SetupError(_safe_code(error)) from None


def _case_check(
    value: CaseSnapshot,
    identity: Mapping[str, str],
    actor: str,
    scope: str,
    revision: int,
    request: object,
) -> None:
    _need(
        value.task_id == identity["task_id"]
        and value.case_id == identity["authority_case_id"]
        and value.actor_id == actor
        and value.scope_id == scope
        and type(value.revision) is int
        and value.revision == revision
        and value.request == request
        and value.quote is None
        and value.intent is None
        and value.cancelled is False
    )


Command = Literal["prepare", "associate-sms"]


def _arguments(argv: Sequence[str]) -> tuple[Command, Path, Path] | None:
    if list(argv) == ["--plan"]:
        return None
    if len(argv) != 5 or argv[0] not in {"prepare", "associate-sms"}:
        raise SetupError("invalid_arguments")
    options = {}
    for n in (1, 3):
        key, value = argv[n], argv[n + 1]
        if key not in {"--directory", "--node"} or key in options or type(value) is not str:
            raise SetupError("invalid_arguments")
        options[key] = Path(value)
    if set(options) != {"--directory", "--node"} or not all(
        p.is_absolute() for p in options.values()
    ):
        raise SetupError("invalid_arguments")
    return cast(Command, argv[0]), options["--directory"], options["--node"]


async def _command(action: Coroutine[object, object, T]) -> T:
    loop = asyncio.get_running_loop()
    task = _task(action)
    installed = []
    cancelled = False
    try:
        for selected in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(selected, task.cancel)
            installed.append(selected)
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
                if not task.done():
                    task.cancel()
            except Exception:  # noqa: BLE001 - retained result is normalized below
                break
        if cancelled:
            if not task.cancelled():
                task.exception()
            raise asyncio.CancelledError
        return task.result()
    finally:
        for selected in installed:
            loop.remove_signal_handler(selected)


def _safe_code(error: Exception) -> Code:
    if type(error) is SetupError:
        code: object = getattr_static(error, "code", None)
        if type(code) is str and code in {
            "invalid_arguments",
            "invalid_setup",
            "already_exists",
            "unavailable",
            "aborted",
        }:
            return cast(Code, code)
    return "unavailable"


def main(argv: Sequence[str] | None = None) -> int:
    try:
        selected = _arguments(sys.argv[1:] if argv is None else argv)
        if selected is None:
            print(
                json.dumps(
                    {
                        "schema_version": 1,
                        "event": "plan",
                        "schemas": {"booking": 4, "work": 4, "channel": 8},
                        "node_deadline_ms": 60000,
                        "node_reap_ms": 5000,
                        "stream_bytes": 32768,
                        "destructive_reset": False,
                        "provider_access": False,
                    },
                    separators=(",", ":"),
                )
            )
            return 0
        command, directory, node = selected
        if command == "associate-sms":
            version = asyncio.run(_command(associate_sms(directory, node)))
            print(
                json.dumps(
                    {
                        "schema_version": 1,
                        "event": "associated",
                        "code": "ok",
                        "association_version": version,
                    },
                    separators=(",", ":"),
                )
            )
            return 0
        asyncio.run(_command(prepare(directory, node)))
        print('{"schema_version":1,"event":"prepared","code":"ok"}')
        return 0
    except (KeyboardInterrupt, asyncio.CancelledError):
        code: Code = "aborted"
    except Exception as error:  # noqa: BLE001 - fixed secret-safe CLI boundary
        code = _safe_code(error)
    print(json.dumps({"schema_version": 1, "event": "failed", "code": code}, separators=(",", ":")))
    return 2 if code in {"invalid_arguments", "invalid_setup", "already_exists"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
