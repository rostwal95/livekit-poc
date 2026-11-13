"""Six separate installed-public-P1 adapter controls; reviewed 12 November 2026.

This is test-only application composition. It imports no P1 implementation at
module load. Public CLI/API calls initialize and operate the isolated authority;
owner SQL is observation/cleanup only. No default M1 service is used or changed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Never, Protocol, TypeVar
from unittest.mock import patch

if TYPE_CHECKING:
    from continuity_lab.case_control_api import CaseControlIdentity
    from continuity_lab.postgres_api import CaseProjection, ManagedCaseClient, PostgresSettings

GROUPS = (
    "installed_public_case_identity_scope_read",
    "public_revision_CAS_conflict_unknown_ACK",
    "exact_quote_confirmation_stale_rejection",
    "currentCase_allowlist_excludes_quote_control",
    "revision_zero_read_only_no_dispatch_claim",
    "public_supplier_effect_sources_no_extra_acceptance",
)
STEP_ROLES = frozenset({"stale-inquiry", "exact-inquiry", "exact-mutation"})
STEP_CHILD_ENV = frozenset(
    {
        "PATH",
        "LANG",
        "PYTHONUNBUFFERED",
        "PYTHONDONTWRITEBYTECODE",
        "P1_POSTGRES_HOST",
        "P1_POSTGRES_PORT",
        "P1_POSTGRES_DB",
        "P1_POSTGRES_USER",
        "P1_POSTGRES_PASSWORD",
        "P1_POSTGRES_SCHEMA",
        "P1_WORKER_SCOPE",
        "P1_WORKER_SUPPLIER_DB",
        "P1_WORKER_SINK_DB",
        "P1_WORKER_SUPPLIER_MODE",
        "P1_WORKER_CLAIM",
    }
)
MAX_FILE_BYTES = 65536


class FixtureError(RuntimeError):
    """Fixed, body-free failure; original exception text is never serialized."""


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise FixtureError("invalid_arguments")


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )


def private_directory(path: Path) -> None:
    info = path.lstat()
    if (
        not path.is_absolute()
        or path != path.resolve()
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o700
        or info.st_uid != os.getuid()
    ):
        raise FixtureError("unsafe_path")


def publish(path: Path, raw: bytes) -> None:
    """Complete, exclusive marker publication; no partial observed PID bytes."""
    private_directory(path.parent)
    if len(raw) > MAX_FILE_BYTES or path.name in {".", ".."}:
        raise FixtureError("invalid_proof")
    pending = path.with_name(path.name + f".{os.getpid()}.pending")
    owned = False
    try:
        fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        owned = True
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, path, follow_symlinks=False)
    finally:
        if owned:
            pending.unlink(missing_ok=True)


def installed_module(path: Path, installation: Path) -> None:
    """Require a regular public module physically below the declared fresh venv."""
    module, root = path.absolute(), installation.absolute()
    if (
        root != root.resolve()
        or module != module.resolve()
        or not module.is_relative_to(root)
        or not stat.S_ISREG(module.lstat().st_mode)
    ):
        raise FixtureError("not_installed")


@dataclass(slots=True)
class CapturedStep:
    role: str
    process_id: int
    argv_sha256: str
    handle: subprocess.Popen[bytes] = field(repr=False)
    group_absent: bool = False

    def payload(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "processId": self.process_id,
            "groupId": self.process_id,
            "argvSha256": self.argv_sha256,
            "returnCode": self.handle.returncode,
            "groupAbsent": self.group_absent,
        }


class CapturedSteps:
    """Observe only the one public worker step, preserving actual Popen ownership.

    The public worker owns its nested session normally. This test observer records
    its public handle before publication so the host can also retain/check the
    exact separately owned group if its outer worker fails. No discovery is used.
    """

    def __init__(
        self,
        directory: Path,
        owner: str,
        role: str,
        executable: Path,
        *,
        spawn: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        publish_record: Callable[[Path, bytes], None] = publish,
        signal_group: Callable[[int, int], None] = os.killpg,
    ) -> None:
        private_directory(directory)
        if (
            re.fullmatch(r"[a-f0-9]{32}", owner) is None
            or role not in STEP_ROLES
            or not executable.is_absolute()
            or ".." in executable.parts
            or not executable.is_file()
        ):
            raise FixtureError("invalid_worker")
        self.directory, self.owner, self.role = directory, owner, role
        self.argv = (str(executable), "-m", "continuity_lab.worker_cli", "step")
        self.argv_sha256 = hashlib.sha256(canonical(list(self.argv))).hexdigest()
        self.spawn, self.publish_record, self.signal_group = spawn, publish_record, signal_group
        self.steps: list[CapturedStep] = []

    def observed_spawn(
        self, argv: Sequence[str], *args: Any, **kwargs: Any
    ) -> subprocess.Popen[bytes]:
        if (
            type(argv) not in (list, tuple)
            or tuple(argv) != self.argv
            or args
            or self.steps
            or set(kwargs) != {"env", "cwd", "stdin", "stdout", "stderr", "start_new_session"}
            or kwargs["start_new_session"] is not True
            or kwargs["stdin"] != subprocess.DEVNULL
            or kwargs["stdout"] != subprocess.PIPE
            or kwargs["stderr"] != subprocess.PIPE
            or type(kwargs["env"]) is not dict
            or set(kwargs["env"]) != STEP_CHILD_ENV
            or kwargs["env"]["P1_POSTGRES_HOST"] != "127.0.0.1"
            or kwargs["env"]["P1_POSTGRES_DB"] != "livekit_lab"
            or kwargs["env"]["P1_POSTGRES_USER"] != "livekit_lab"
            or kwargs["env"]["P1_WORKER_SUPPLIER_MODE"] != "cooperating"
            or Path(kwargs["cwd"]) != Path(tempfile.gettempdir())
        ):
            raise FixtureError("unexpected_child")
        child = self.spawn(list(argv), **kwargs)
        # This is deliberately the first action after spawn, before publication
        # or any injected observer. No fallible post-spawn work may hide an owner.
        step = CapturedStep(self.role, child.pid, self.argv_sha256, child)
        self.steps.append(step)
        if child.pid <= 1 or child.pid == os.getpid() or child.pid == os.getpgrp():
            raise FixtureError("unexpected_child")
        self.publish_record(
            self.directory / (self.role + "-started.json"),
            canonical(
                {
                    "schemaVersion": 1,
                    "owner": self.owner,
                    "workerProcessId": os.getpid(),
                    "role": self.role,
                    "processId": child.pid,
                    "groupId": child.pid,
                    "argvSha256": step.argv_sha256,
                }
            ),
        )
        return child

    def _absent(self, step: CapturedStep) -> bool:
        try:
            self.signal_group(step.process_id, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return False

    def close(self, deadline: float) -> bool:
        complete = True
        for step in reversed(self.steps):
            child = step.handle
            try:
                if child.pid <= 1 or child.pid in {os.getpid(), os.getpgrp()}:
                    complete = False
                    continue
                # A live unreaped public handle retains the identity. Once the
                # public worker has reaped its leader, an ambiguous group probe
                # cannot authorize a signal to a potentially reused PID/group.
                if child.poll() is None:
                    try:
                        self.signal_group(step.process_id, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        child.wait(timeout=max(0, min(0.5, deadline - time.monotonic())))
                    except subprocess.TimeoutExpired:
                        try:
                            self.signal_group(step.process_id, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                child.wait(timeout=max(0, deadline - time.monotonic()))
                while not self._absent(step) and time.monotonic() < deadline:
                    time.sleep(min(0.01, max(0, deadline - time.monotonic())))
                step.group_absent = self._absent(step)
                complete &= child.returncode is not None and step.group_absent
                for stream in (child.stdout, child.stderr):
                    if stream is not None:
                        stream.close()
            except BaseException:  # noqa: BLE001 - Observe every independent captured owner.
                complete = False
        return complete

    def payload(self, cleanup_complete: bool) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "owner": self.owner,
            "workerProcessId": os.getpid(),
            "steps": [s.payload() for s in self.steps],
            "cleanupComplete": cleanup_complete,
        }


def public_worker_once(
    observer: CapturedSteps,
    *,
    cleanup_seconds: float = 5,
    invoke: Callable[[], int] | None = None,
) -> dict[str, Any]:
    """The unchanged supported CLI owns execution; observation adds no authority."""
    if invoke is None:
        from continuity_lab import worker_cli

        invoke = lambda: worker_cli.main(["once"])

    primary: BaseException | None = None
    code: int | None = None
    try:
        # Restored on every path. The observer calls its retained original spawn,
        # not this temporary global test seam; environment bytes are not retained.
        with patch("subprocess.Popen", side_effect=observer.observed_spawn):
            code = invoke()
    except BaseException as error:  # noqa: BLE001 - Cleanup must preserve the original failure.
        primary = error
    finally:
        try:
            complete = observer.close(time.monotonic() + cleanup_seconds)
        except BaseException as error:  # noqa: BLE001 - Preserve the original worker failure.
            complete = False
            if primary is None:
                primary = error
    proof = observer.payload(complete)
    try:
        observer.publish_record(
            observer.directory / (observer.role + "-settled.json"), canonical(proof)
        )
    except BaseException as error:  # noqa: BLE001 - Diagnostic failure must not replace primary.
        if primary is None:
            primary = error
    if primary is not None:
        raise primary
    if (
        code != 0
        or len(observer.steps) != 1
        or not complete
        or observer.steps[0].handle.returncode != 0
    ):
        raise FixtureError("worker_incomplete")
    return proof


@dataclass(frozen=True, slots=True)
class PublicProfile:
    directory: Path
    installation: Path
    owner: str
    port: int
    password: str = field(repr=False)
    credentials: dict[str, Any] = field(repr=False)

    @property
    def schema(self) -> str:
        return "p1_starter_" + self.owner

    def scope(self, slot: str) -> str:
        if slot not in {"revision", "stale", "exact"}:
            raise FixtureError("invalid_slot")
        return "p1_starter_" + slot

    def actor(self) -> str:
        return "starter_actor_" + self.owner

    def supplier(self, slot: str) -> Path | None:
        self.scope(slot)
        return None if slot == "revision" else self.directory / (slot + "-supplier.sqlite3")

    def settings(self) -> PostgresSettings:
        from continuity_lab.postgres_api import PostgresSettings

        return PostgresSettings(
            host="127.0.0.1",
            port=self.port,
            dbname="livekit_lab",
            user="livekit_lab",
            password=self.password,
            schema=self.schema,
        )

    def p2_reference(self, slot: str) -> dict[str, Any]:
        self.scope(slot)
        return {
            "scope": {"tenantId": "tenant_starter_p1", "accountId": "account_starter_" + slot},
            "caseId": "case_starter_" + self.owner + "_" + slot,
            "conversationId": "conversation_starter_" + self.owner + "_" + slot,
        }


def _pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for name, value in values:
        if name in body:
            raise FixtureError("invalid_json")
        body[name] = value
    return body


def read_data(path: Path) -> dict[str, Any]:
    private_directory(path.parent)
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != 0o600
        or not 0 < info.st_size <= MAX_FILE_BYTES
    ):
        raise FixtureError("unsafe_path")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(MAX_FILE_BYTES + 1)
        after = os.fstat(stream.fileno())
    if (
        (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino)
        or (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_nlink,
            after.st_mode,
            after.st_uid,
            after.st_mtime_ns,
        )
        != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_nlink,
            opened.st_mode,
            opened.st_uid,
            opened.st_mtime_ns,
        )
        or len(raw) != info.st_size
    ):
        raise FixtureError("unsafe_path")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(FixtureError("invalid_json")),
        )
        if type(value) is not dict:
            raise FixtureError("invalid_json")
        canonical(value)  # Reject invalid Unicode/nonfinite values without normalization.
        return value
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise FixtureError("invalid_json") from None


def _fields(value: Any, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise FixtureError("invalid_config")
    return value


def _credential(value: Any) -> str:
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9_-]{43}", value) is None:
        raise FixtureError("invalid_config")
    return value


def profile(environment: dict[str, str], *, mode: str) -> PublicProfile:
    base = {
        "PATH",
        "HOME",
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "SYSTEMROOT",
        "__CF_USER_TEXT_ENCODING",
        "NO_COLOR",
        "CI",
    }
    required = {
        "P1_STARTER_DIRECTORY",
        "P1_STARTER_INSTALLATION",
        "P1_STARTER_OWNER",
        "P1_STARTER_CREDENTIALS",
        "P1_POSTGRES_HOST",
        "P1_POSTGRES_PORT",
        "P1_POSTGRES_DB",
        "P1_POSTGRES_USER",
        "P1_POSTGRES_PASSWORD",
        "P1_POSTGRES_SCHEMA",
    }
    worker = {
        "P1_WORKER_SCOPE",
        "P1_WORKER_SUPPLIER_DB",
        "P1_WORKER_SINK_DB",
        "P1_WORKER_STATE_FILE",
        "P1_WORKER_SUPPLIER_MODE",
        "P1_WORKER_POLL_SECONDS",
        "P1_WORKER_STEP_SECONDS",
        "P1_WORKER_DRAIN_SECONDS",
        "P1_WORKER_OUTPUT_BYTES",
        "P1_WORKER_FAILURE_LIMIT",
    }
    if mode not in {
        "seed",
        "verify",
        "serve",
        "prepare-stale-quote",
        "prepare-exact-quote",
        *STEP_ROLES,
    }:
        raise FixtureError("invalid_mode")
    if mode in STEP_ROLES:
        required = (required - {"P1_STARTER_CREDENTIALS"}) | worker
    if (
        not required <= environment.keys()
        or environment.keys() - required - base
        or any(
            type(k) is not str or type(v) is not str or not v or "\0" in v
            for k, v in environment.items()
        )
    ):
        raise FixtureError("invalid_config")
    directory = Path(environment["P1_STARTER_DIRECTORY"])
    private_directory(directory)
    installation = Path(environment["P1_STARTER_INSTALLATION"])
    private_directory(installation)
    owner, port = environment["P1_STARTER_OWNER"], environment["P1_POSTGRES_PORT"]
    password = environment["P1_POSTGRES_PASSWORD"]
    if (
        re.fullmatch(r"[0-9a-f]{32}", owner) is None
        or re.fullmatch(r"[1-9][0-9]{0,4}", port) is None
        or int(port) > 65535
        or environment["P1_POSTGRES_HOST"] != "127.0.0.1"
        or environment["P1_POSTGRES_DB"] != "livekit_lab"
        or environment["P1_POSTGRES_USER"] != "livekit_lab"
        or environment["P1_POSTGRES_SCHEMA"] != "p1_starter_" + owner
        or not 1 <= len(password) <= 128
        or any(c in password for c in "\r\n")
    ):
        raise FixtureError("invalid_config")
    if mode in STEP_ROLES:
        slot = "stale" if mode == "stale-inquiry" else "exact"
        expected = {
            "P1_WORKER_SCOPE": "p1_starter_" + slot,
            "P1_WORKER_SUPPLIER_DB": str(directory / (slot + "-supplier.sqlite3")),
            "P1_WORKER_SINK_DB": str(directory / (slot + "-completion.sqlite3")),
            "P1_WORKER_STATE_FILE": str(directory / (mode + "-health.json")),
            "P1_WORKER_SUPPLIER_MODE": "cooperating",
            "P1_WORKER_POLL_SECONDS": "1",
            "P1_WORKER_STEP_SECONDS": "15",
            "P1_WORKER_DRAIN_SECONDS": "5",
            "P1_WORKER_OUTPUT_BYTES": "8192",
            "P1_WORKER_FAILURE_LIMIT": "1",
        }
        if any(environment[k] != value for k, value in expected.items()):
            raise FixtureError("invalid_config")
        return PublicProfile(directory, installation, owner, int(port), password, {})
    credentials_path = Path(environment["P1_STARTER_CREDENTIALS"])
    if credentials_path != directory / "p1-credentials.json":
        raise FixtureError("invalid_config")
    credentials = _fields(
        read_data(credentials_path), {"schemaVersion", "owner", "p1Tokens", "bridgeTokens"}
    )
    if (
        type(credentials["schemaVersion"]) is not int
        or credentials["schemaVersion"] != 1
        or credentials["owner"] != owner
    ):
        raise FixtureError("invalid_config")
    tokens = _fields(credentials["p1Tokens"], {"revision", "stale", "exact"})
    bridge = _fields(credentials["bridgeTokens"], {"case", "confirmation", "currentCase"})
    if len({_credential(v) for v in [*tokens.values(), *bridge.values()]}) != 6:
        raise FixtureError("invalid_config")
    return PublicProfile(directory, installation, owner, int(port), password, credentials)


def _public_modules(current: PublicProfile) -> None:
    from continuity_lab import api, case_control_api, conversation_composition, postgres_api

    for module in (api, case_control_api, conversation_composition, postgres_api):
        if module.__file__ is None:
            raise FixtureError("not_installed")
        installed_module(Path(module.__file__), current.installation)


class PublicClient(Protocol):
    @property
    def pending_count(self) -> int: ...
    async def close(self) -> None: ...


Client = TypeVar("Client", bound=PublicClient)


class PublicFactoryOwners:
    """Register late public factories inside the thread, before waiter delivery."""

    def __init__(self) -> None:
        self.pending: set[asyncio.Task[Any]] = set()
        self.clients: list[PublicClient] = []
        self.closed_clients: set[int] = set()
        self.close_tasks: dict[int, asyncio.Task[None]] = {}
        self.closing = False
        self.admitted = 0

    async def open(self, factory: Callable[[], Client]) -> Client:
        if self.closing or self.admitted >= 9:
            raise FixtureError("closed")
        self.admitted += 1

        def create() -> Client:
            if self.closing:
                raise FixtureError("closed")
            client = factory()
            self.clients.append(client)
            return client

        actual = asyncio.create_task(asyncio.to_thread(create))
        self.pending.add(actual)

        def settled(task: asyncio.Task[Any]) -> None:
            self.pending.discard(task)
            if not task.cancelled():
                task.exception()

        actual.add_done_callback(settled)
        return await asyncio.shield(actual)

    async def close(self, deadline: float) -> bool:
        self.closing = True
        if self.pending:
            _, pending = await asyncio.wait(
                tuple(self.pending), timeout=max(0, deadline - time.monotonic())
            )
            if pending or self.pending:
                return False
        for client in reversed(self.clients):
            key = id(client)
            if key in self.closed_clients or key in self.close_tasks:
                continue
            if time.monotonic() >= deadline:
                continue
            task = asyncio.create_task(client.close())
            self.close_tasks[key] = task

            def observed(done: asyncio.Task[None]) -> None:
                if not done.cancelled():
                    done.exception()

            task.add_done_callback(observed)
        pending_close = tuple(task for task in self.close_tasks.values() if not task.done())
        if pending_close:
            await asyncio.wait(pending_close, timeout=max(0, deadline - time.monotonic()))
        for client in self.clients:
            key = id(client)
            close_task = self.close_tasks.get(key)
            if close_task is None or not close_task.done():
                continue
            if (
                not close_task.cancelled()
                and close_task.exception() is None
                and client.pending_count == 0
            ):
                self.closed_clients.add(key)
            else:
                # A later explicit retry reobserves the same public owner; a
                # failed observer is never interpreted as actual I/O closure.
                self.close_tasks.pop(key)
        return len(self.closed_clients) == len(self.clients)


async def public_phase(current: PublicProfile, mode: str) -> dict[str, Any]:
    """Only public typed business APIs; no SQL business seeding or hidden worker."""
    if mode not in {"seed", "verify", "prepare-stale-quote", "prepare-exact-quote"}:
        raise FixtureError("invalid_mode")
    _public_modules(current)
    from datetime import date

    from continuity_lab.api import BookingChange
    from continuity_lab.postgres_api import AuthenticatedActor, BearerToken, open_postgres_client

    owners = PublicFactoryOwners()
    primary: BaseException | None = None
    output: dict[str, Any] = {}
    try:
        slots = (
            ("revision", "stale", "exact")
            if mode in {"seed", "verify"}
            else ("stale" if mode == "prepare-stale-quote" else "exact",)
        )
        originals = None if mode == "seed" else read_data(current.directory / "p1-originals.json")
        if originals is not None:
            _fields(originals, {"schemaVersion", "owner", "slots"})
            if (
                type(originals["schemaVersion"]) is not int
                or originals["schemaVersion"] != 1
                or originals["owner"] != current.owner
            ):
                raise FixtureError("invalid_originals")
            _fields(originals["slots"], {"revision", "stale", "exact"})
        for slot in slots:
            # The blocking public factory's existing preflight completes before
            # the returned client is admitted to any business operation.
            def create_client(slot: str = slot) -> ManagedCaseClient:
                return open_postgres_client(
                    actor=AuthenticatedActor(current.actor(), current.scope(slot)),
                    token=BearerToken(current.credentials["p1Tokens"][slot]),
                    settings=current.settings(),
                    quote_database=current.supplier(slot),
                )

            client = await owners.open(create_client)
            if mode == "seed":
                day = {"revision": 2, "stale": 3, "exact": 4}[slot]
                receipt = await client.submit(
                    idempotency_key="starter-" + current.owner + "-" + slot,
                    request=BookingChange("DEMO-BK-001", date(2030, 12, day), True),
                )
                if not receipt.created:
                    raise FixtureError("unexpected_replay")
                output[slot] = receipt.payload()
            else:
                assert originals is not None
                original = originals["slots"][slot]
                if type(original) is not dict or type(original.get("task_id")) is not str:
                    raise FixtureError("invalid_originals")
                task_id = original["task_id"]
                if mode == "verify":
                    projection = await client.get(task_id=task_id, limit=50, cursor=None)
                    payload = projection.payload()
                    if (
                        payload.get("has_more") is not False
                        or payload.get("history_truncated") is not False
                    ):
                        raise FixtureError("incomplete_projection")
                    output[slot] = payload
                else:
                    receipt_quote = await client.prepare_quote(
                        task_id=task_id,
                        expected_revision=0,
                        command_id="quote-" + current.owner + "-" + slot,
                    )
                    raw = json.dumps(
                        receipt_quote.quote.payload(),
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                        allow_nan=False,
                    )
                    output = {
                        "schemaVersion": 1,
                        "owner": current.owner,
                        "slot": slot,
                        "taskId": task_id,
                        "authorityCaseId": original["case_id"],
                        "quoteId": receipt_quote.quote.quote_id,
                        "quoteDigest": hashlib.sha256(raw.encode()).hexdigest(),
                        "quoteJson": raw,
                        "created": receipt_quote.created,
                    }
    except BaseException as error:  # noqa: BLE001 - Preserve primary while closing public owners.
        primary = error
    finally:
        complete = await owners.close(time.monotonic() + 20)
    if primary is not None:
        raise primary
    if not complete:
        raise FixtureError("cleanup_incomplete")
    if mode == "seed":
        output = {"schemaVersion": 1, "owner": current.owner, "slots": output}
        destination = "p1-originals.json"
    elif mode == "verify":
        output = {"schemaVersion": 1, "owner": current.owner, "projections": output}
        destination = "p1-public-projections.json"
    else:
        destination = (
            "p1-" + ("stale" if mode == "prepare-stale-quote" else "exact") + "-quote.json"
        )
    publish(current.directory / destination, canonical(output))
    return {
        "schemaVersion": 1,
        "status": "passed",
        "mode": mode,
        "owner": current.owner,
        "proofSha256": hashlib.sha256(canonical(output)).hexdigest(),
        "cleanupComplete": complete,
    }


class PublicReadClient:
    """Own read facade over the same public boundary/token and public identity."""

    def __init__(self, current: PublicProfile, slot: str) -> None:
        from continuity_lab.case_control_api import CaseControlClient
        from continuity_lab.conversation_composition import build_conversation_service
        from continuity_lab.postgres_api import AuthenticatedActor, BearerToken, ManagedCaseClient

        token = BearerToken(current.credentials["p1Tokens"][slot])
        boundary = build_conversation_service(
            actor=AuthenticatedActor(current.actor(), current.scope(slot)),
            token=token,
            settings=current.settings(),
            quote_database=current.supplier(slot),
        )
        self.managed = ManagedCaseClient(boundary, token)
        self.controller = CaseControlClient(boundary, token, current.schema)

    @property
    def identity(self) -> CaseControlIdentity:
        return self.controller.identity

    @property
    def pending_count(self) -> int:
        return self.managed.pending_count

    async def get(
        self, *, task_id: str, cursor: str | None = None, limit: int = 1
    ) -> CaseProjection:
        return await self.managed.get(task_id=task_id, cursor=cursor, limit=limit)

    async def close(self) -> None:
        await self.managed.close()


def _pid_marker(path: Path, expected: int) -> bool:
    """Barrier-only reader: complete publication may still have its pending link.

    Like the existing public FileBarrier, a complete owned PID is admissible
    before the publisher removes its second link. Final retained files must have
    nlink1; this is not the general private JSON/proof reader.
    """
    private_directory(path.parent)
    try:
        before = path.lstat()
    except FileNotFoundError:
        return False
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.getuid()
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_nlink not in {1, 2}
    ):
        raise FixtureError("unsafe_marker")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise FixtureError("unsafe_marker")
        raw = stream.read(34)
    if raw != (str(expected) + "\n").encode("ascii"):
        raise FixtureError("invalid_marker")
    return True


async def _wait_release(path: Path, stop: asyncio.Event, deadline: float) -> None:
    while not _pid_marker(path, os.getpid()):
        if stop.is_set():
            raise FixtureError("closed")
        if time.monotonic() >= deadline:
            raise FixtureError("deadline_exceeded")
        await asyncio.sleep(min(0.01, max(0, deadline - time.monotonic())))


def _bridge_modules() -> tuple[Any, Any]:
    """Only adjacent exact copied host tooling, never a product source path."""
    import sys

    directory = Path(__file__).resolve().parent
    private_directory(directory)
    for filename in ("p2_case_bridge.py", "p2_current_case_bridge.py"):
        path = directory / filename
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise FixtureError("unsafe_tooling")
    sys.path.insert(0, str(directory))
    import p2_case_bridge
    import p2_current_case_bridge

    for module, filename in (
        (p2_case_bridge, "p2_case_bridge.py"),
        (p2_current_case_bridge, "p2_current_case_bridge.py"),
    ):
        if module.__file__ is None or Path(module.__file__).resolve() != directory / filename:
            raise FixtureError("foreign_tooling")
    return p2_case_bridge, p2_current_case_bridge


async def close_bridge_tier(bridges: list[Any], deadline: float) -> bool:
    """At most three public close observations per owner, no cancelled actual work."""
    closed: set[int] = set()
    pending: dict[int, asyncio.Task[None]] = {}

    def observed(done: asyncio.Task[None]) -> None:
        if not done.cancelled():
            done.exception()

    for _ in range(3):
        if time.monotonic() >= deadline:
            break
        for bridge in bridges:
            key = id(bridge)
            if key not in closed and key not in pending:
                task = asyncio.create_task(bridge.close())
                pending[key] = task
                task.add_done_callback(observed)
        actual = tuple(task for task in pending.values() if not task.done())
        if actual:
            await asyncio.wait(actual, timeout=max(0, deadline - time.monotonic()))
        for bridge in bridges:
            key = id(bridge)
            close_task = pending.get(key)
            if close_task is not None and close_task.done():
                if not close_task.cancelled() and close_task.exception() is None:
                    closed.add(key)
                pending.pop(key)
        if len(closed) == len(bridges):
            return True
    return len(closed) == len(bridges)


async def public_serve(current: PublicProfile) -> dict[str, Any]:
    """Three bounded readonly/controller capabilities, no implicit worker or quote."""
    _public_modules(current)
    from continuity_lab.case_control_api import (
        AuthenticatedActor,
        BearerToken,
        CaseControlClient,
        open_case_control_client,
    )

    case_module, current_module = _bridge_modules()
    originals = _fields(
        read_data(current.directory / "p1-originals.json"), {"schemaVersion", "owner", "slots"}
    )
    if (
        type(originals["schemaVersion"]) is not int
        or originals["schemaVersion"] != 1
        or originals["owner"] != current.owner
    ):
        raise FixtureError("invalid_originals")
    original_slots = _fields(originals["slots"], {"revision", "stale", "exact"})
    factories = PublicFactoryOwners()
    bridges: list[Any] = []
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    primary: BaseException | None = None
    complete = False
    endpoint: dict[str, Any] = {}
    try:
        cases: list[Any] = []
        confirmations: list[Any] = []
        reads: list[Any] = []
        for slot in ("revision", "stale", "exact"):
            original = original_slots[slot]
            if (
                type(original) is not dict
                or type(original.get("task_id")) is not str
                or type(original.get("case_id")) is not str
            ):
                raise FixtureError("invalid_originals")
            ref = current.p2_reference(slot)
            for target, allowed, key in (
                (cases, False, "case"),
                (confirmations, True, "confirmation"),
            ):
                if stop.is_set():
                    raise FixtureError("closed")

                def create_control(slot: str = slot) -> CaseControlClient:
                    return open_case_control_client(
                        actor=AuthenticatedActor(current.actor(), current.scope(slot)),
                        token=BearerToken(current.credentials["p1Tokens"][slot]),
                        settings=current.settings(),
                        quote_database=current.supplier(slot),
                    )

                control = await factories.open(create_control)
                target.append(
                    case_module.CaseBinding(
                        tenant_id=ref["scope"]["tenantId"],
                        account_id=ref["scope"]["accountId"],
                        case_id=ref["caseId"],
                        task_id=original["task_id"],
                        authority_case_id=original["case_id"],
                        token=current.credentials["bridgeTokens"][key],
                        client=control,
                        allow_confirmation=allowed,
                    )
                )
            if stop.is_set():
                raise FixtureError("closed")

            def create_reader(slot: str = slot) -> PublicReadClient:
                return PublicReadClient(current, slot)

            reader = await factories.open(create_reader)
            reads.append(
                current_module.CurrentCaseBinding(
                    tenant_id=ref["scope"]["tenantId"],
                    account_id=ref["scope"]["accountId"],
                    case_id=ref["caseId"],
                    conversation_id=ref["conversationId"],
                    task_id=original["task_id"],
                    authority_case_id=original["case_id"],
                    token=current.credentials["bridgeTokens"]["currentCase"],
                    reader=reader,
                )
            )
        revision_calls = 0

        async def after_revision() -> None:
            nonlocal revision_calls
            revision_calls += 1
            if revision_calls == 2:
                publish(
                    current.directory / "p1_revision_committed.reached",
                    (str(os.getpid()) + "\n").encode(),
                )
                await _wait_release(
                    current.directory / "p1_revision_committed.released", stop, time.monotonic() + 5
                )

        bridges.append(
            case_module.CaseBridge(
                tuple(cases),
                request_timeout_ms=2000,
                close_timeout_ms=2000,
                harness_after_revision=after_revision,
            )
        )
        bridges.append(
            case_module.CaseBridge(
                tuple(confirmations), request_timeout_ms=2000, close_timeout_ms=2000
            )
        )
        bridges.append(
            current_module.CurrentCaseBridge(
                tuple(reads), request_timeout_ms=1000, close_timeout_ms=2000
            )
        )
        for bridge in bridges:
            if stop.is_set():
                raise FixtureError("closed")
            await bridge.start(port=0)
            if stop.is_set():
                raise FixtureError("closed")
        endpoint = {
            "schemaVersion": 1,
            "owner": current.owner,
            "pid": os.getpid(),
            "endpoints": {
                key: {"host": "127.0.0.1", "port": bridge.port}
                for key, bridge in zip(
                    ("case", "confirmation", "currentCase"), bridges, strict=True
                )
            },
        }
        publish(current.directory / "p1-endpoints.json", canonical(endpoint))
        publish(current.directory / "p1_ready.reached", (str(os.getpid()) + "\n").encode())
        publish(current.directory / "p1_stop.reached", (str(os.getpid()) + "\n").encode())
        try:
            await _wait_release(
                current.directory / "p1_stop.released", stop, time.monotonic() + 300
            )
        except FixtureError:
            if not stop.is_set():
                raise
    except BaseException as error:  # noqa: BLE001 - Close every actual startup/server owner.
        primary = error
    finally:
        stop.set()
        deadline = time.monotonic() + 20
        try:
            servers_closed = await close_bridge_tier(bridges, deadline)
            # Readers/boundaries stay alive until every listener/get/controller
            # owner has actually closed. An observer timeout never releases them.
            if servers_closed:
                complete = await factories.close(deadline)
        except BaseException as error:  # noqa: BLE001 - Primary remains authoritative.
            if primary is None:
                primary = error
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(signum)
        proof = {
            "schemaVersion": 1,
            "owner": current.owner,
            "pid": os.getpid(),
            "endpoints": endpoint.get("endpoints"),
            "bridgeMetrics": [dict(bridge.metrics()) for bridge in bridges],
            "factoryPending": len(factories.pending),
            "clients": len(factories.clients),
            "clientsClosed": len(factories.closed_clients),
            "cleanupComplete": complete,
        }
        try:
            publish(current.directory / "p1-bridge-closed.json", canonical(proof))
        except BaseException as error:  # noqa: BLE001 - Diagnostic failure cannot replace primary.
            if primary is None:
                primary = error
    if primary is not None:
        raise primary
    if not complete:
        raise FixtureError("cleanup_incomplete")
    return {
        "schemaVersion": 1,
        "status": "passed",
        "mode": "serve",
        "owner": current.owner,
        "cleanupComplete": complete,
    }


def plan() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "status": "not_started",
        "groups": list(GROUPS),
        "measurementStarted": False,
        "protocolFrozen": False,
        "scope": "separate_installed_public_P1_adapter_controls",
        "stepRoles": sorted(STEP_ROLES),
        "standaloneGroups": 0,
        "revisionAcknowledgement": "application_reply_hold_not_command_receipt",
    }


class BoundedOutput(io.StringIO):
    def write(self, value: str) -> int:
        if len((self.getvalue() + value).encode("utf-8")) > 8192:
            raise FixtureError("capture_limit")
        return super().write(value)


def initial_source(environment: dict[str, str]) -> dict[str, Any]:
    base = {
        "PATH",
        "HOME",
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "SYSTEMROOT",
        "__CF_USER_TEXT_ENCODING",
        "NO_COLOR",
        "CI",
    }
    required = {"P1_STARTER_DIRECTORY", "P1_STARTER_INSTALLATION", "P1_STARTER_OWNER"}
    if (
        not required <= environment.keys()
        or environment.keys() - required - base
        or any(
            type(value) is not str or not value or "\0" in value for value in environment.values()
        )
    ):
        raise FixtureError("invalid_config")
    directory, installation = (
        Path(environment["P1_STARTER_DIRECTORY"]),
        Path(environment["P1_STARTER_INSTALLATION"]),
    )
    private_directory(directory)
    private_directory(installation)
    owner = environment["P1_STARTER_OWNER"]
    if re.fullmatch(r"[a-f0-9]{32}", owner) is None:
        raise FixtureError("invalid_config")
    from continuity_lab import api

    if api.__file__ is None:
        raise FixtureError("not_installed")
    installed_module(Path(api.__file__), installation)
    source = directory / "source.sqlite3"
    descriptor = os.open(source, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(descriptor)
    api.migrate(source, directory / "source-v0-backup.sqlite3")
    return {
        "schemaVersion": 1,
        "status": "passed",
        "mode": "init-source",
        "owner": owner,
        "cleanupComplete": True,
    }


def main(argv: list[str] | None = None) -> int:
    mode = "invalid"
    try:
        parser = SafeParser(description=__doc__)
        parser.add_argument("--plan", action="store_true")
        parser.add_argument(
            "--mode",
            choices=(
                "init-source",
                "seed",
                "prepare-stale-quote",
                "prepare-exact-quote",
                "verify",
                "serve",
                *sorted(STEP_ROLES),
            ),
        )
        args = parser.parse_args(argv)
        if args.plan:
            if args.mode is not None:
                raise FixtureError("invalid_arguments")
            print(canonical(plan()).decode("utf-8"))
            return 0
        if args.mode is None:
            raise FixtureError("invalid_arguments")
        mode = args.mode
        environment = dict(os.environ)
        if mode == "init-source":
            result = initial_source(environment)
        else:
            current = profile(environment, mode=mode)
            if mode in STEP_ROLES:
                from continuity_lab import worker_cli

                if worker_cli.__file__ is None:
                    raise FixtureError("not_installed")
                installed_module(Path(worker_cli.__file__), current.installation)
                observer = CapturedSteps(
                    current.directory, current.owner, mode, Path(sys.executable)
                )
                output = BoundedOutput()
                with redirect_stdout(output):
                    proof = public_worker_once(observer)
                publish(
                    current.directory / (mode + "-worker-stdout.bin"),
                    output.getvalue().encode("utf-8"),
                )
                result = {
                    "schemaVersion": 1,
                    "status": "passed",
                    "mode": mode,
                    "owner": current.owner,
                    "steps": len(proof["steps"]),
                    "cleanupComplete": proof["cleanupComplete"],
                }
            elif mode == "serve":
                result = asyncio.run(public_serve(current))
            else:
                result = asyncio.run(public_phase(current, mode))
        print(canonical(result).decode("utf-8"))
        return 0
    except BaseException:  # noqa: BLE001 - Raw public errors/messages/control bytes never cross stdout.
        print(
            canonical(
                {
                    "schemaVersion": 1,
                    "status": "failed",
                    "mode": mode,
                    "code": "fixture_failed",
                    "cleanupComplete": False,
                }
            ).decode("utf-8")
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
