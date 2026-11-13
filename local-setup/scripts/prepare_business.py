"""Explicit host-only empty business bootstrap; serving M1 is never an input."""

from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
import re
import signal
import stat
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, Protocol, cast
from uuid import UUID, uuid4

try:
    from psycopg import sql

    from continuity_lab.cutover import CutoverReport, cutover
    from continuity_lab.migrations import migrate
    from continuity_lab.postgres_migrations import (
        read_import_state,
        upgrade_v2,
        upgrade_v3,
        upgrade_v4,
        validate_schema,
    )
    from continuity_lab.postgres_settings import PostgresSettings
    from continuity_lab.source_transfer import prepare_source, read_source_state
except Exception:
    if __name__ == "__main__":
        print(
            '{"status":"failed","code":"setup_required","stage":"preflight","partial_artifacts_retained":false,"cleanup_incomplete":false}'
        )
        raise SystemExit(2) from None
    raise

ROOT = Path(__file__).resolve().parents[2]
STAGES = frozenset(
    {"preflight", "source", "cutover", "upgrade_v2", "upgrade_v3", "upgrade_v4", "verify"}
)


class BootstrapError(ValueError):
    """No values, credentials, SQL or dependency exceptions cross the CLI boundary."""

    def __init__(self, code: str) -> None:
        if code not in {
            "setup_required",
            "target_refused",
            "bootstrap_state_invalid",
            "bootstrap_busy",
            "bootstrap_timeout",
            "bootstrap_cancelled",
            "bootstrap_failed",
        }:
            raise ValueError("Unsupported bootstrap category")
        self.code = code
        self.cleanup_incomplete = False
        super().__init__(
            "Business preparation did not complete; retain private bootstrap artifacts"
        )


def require(condition: bool, code: str = "bootstrap_state_invalid") -> None:
    if not condition:
        raise BootstrapError(code)


def binding(owner: PostgresSettings, runtime: PostgresSettings) -> str:
    require(type(owner) is PostgresSettings and type(runtime) is PostgresSettings, "setup_required")
    require(owner.user == "continuity_migrator" and runtime.user == "livekit_lab", "setup_required")
    require(
        owner.host == runtime.host == "127.0.0.1"
        and owner.dbname == runtime.dbname == "livekit_lab",
        "setup_required",
    )
    require(
        owner.port == runtime.port
        and owner.schema == runtime.schema
        and owner.password != runtime.password,
        "setup_required",
    )
    require(
        owner.schema not in {"public", "information_schema"} and not owner.schema.startswith("pg_"),
        "setup_required",
    )
    return hashlib.sha256(
        json.dumps(
            {
                "host": owner.host,
                "port": owner.port,
                "database": owner.dbname,
                "schema": owner.schema,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class Target:
    version: int
    state: str
    migration_id: str | None = None
    source_digest: str | None = None
    counts: tuple[int, int, int] | None = None

    def __post_init__(self) -> None:
        require(type(self.version) is int and 0 <= self.version <= 4)
        require(self.state in ({"absent"} if self.version == 0 else {"staging", "active"}))
        require((self.migration_id is None) == (self.source_digest is None))
        if self.migration_id is not None:
            require(
                str(UUID(self.migration_id)) == self.migration_id
                and type(self.source_digest) is str
                and re.fullmatch(r"[a-f0-9]{64}", self.source_digest) is not None
            )
        if self.counts is not None:
            require(
                type(self.counts) is tuple
                and len(self.counts) == 3
                and all(type(value) is int and value >= 0 for value in self.counts)
            )


class BootstrapPort(Protocol):
    def inspect(self) -> Target: ...
    def activate(self, source: Path, backup: Path) -> CutoverReport: ...
    def upgrade(self, version: int) -> None: ...
    def ready(self) -> None: ...


class PostgresBootstrap:
    def __init__(self, owner: PostgresSettings, runtime: PostgresSettings) -> None:
        binding(owner, runtime)
        self.owner, self.runtime = owner, runtime

    def inspect(self) -> Target:
        with closing(self.owner.connect(application_name="continuity-migrate")) as connection:
            row = connection.execute(
                "SELECT pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname=%s",
                (self.owner.schema,),
            ).fetchone()
            if row is None:
                return Target(0, "absent")
            require(row["owner"] == "continuity_migrator", "target_refused")
        current = read_import_state(self.owner)
        if current.version == 4 and current.state == "active":
            return Target(
                current.version, current.state, current.migration_id, current.source_digest
            )
        counts: list[int] = []
        with closing(self.owner.connect(application_name="continuity-migrate")) as connection:
            for table in ("tasks", "executions", "execution_attempts"):
                row = connection.execute(
                    sql.SQL("SELECT COUNT(*) AS count FROM {}").format(
                        sql.Identifier(self.owner.schema, table)
                    )
                ).fetchone()
                require(row is not None)
                assert row is not None
                value = row["count"]
                require(type(value) is int and value >= 0)
                counts.append(value)
        return Target(
            current.version,
            current.state,
            current.migration_id,
            current.source_digest,
            (counts[0], counts[1], counts[2]),
        )

    def activate(self, source: Path, backup: Path) -> CutoverReport:
        return cutover(source, backup, self.owner)

    def upgrade(self, version: int) -> None:
        if version == 2:
            upgrade_v2(self.owner)
        elif version == 3:
            upgrade_v3(self.owner)
        elif version == 4:
            upgrade_v4(self.owner)
        else:
            raise BootstrapError("bootstrap_state_invalid")

    def ready(self) -> None:
        with closing(self.runtime.connect()) as connection, connection.transaction():
            connection.execute("SET TRANSACTION READ ONLY")
            validate_schema(connection, self.runtime.schema, minimum_version=4)


def private_directory(path: Path, *, create: bool = False) -> None:
    require(not path.is_symlink())
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    require(
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o700
    )


def private_file(path: Path) -> None:
    info = path.lstat()
    require(
        not path.is_symlink()
        and stat.S_ISREG(info.st_mode)
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1
    )


@contextmanager
def owned_lock(base: Path) -> Iterator[None]:
    private_directory(base, create=True)
    path = base / ".prepare.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    original: BaseException | None = None
    try:
        private_file(path)
        observed = os.fstat(descriptor)
        require(observed.st_ino == path.stat().st_ino and observed.st_dev == path.stat().st_dev)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BootstrapError("bootstrap_busy") from None
        yield
    except BaseException as error:
        if isinstance(error, Exception) and not isinstance(error, BootstrapError):
            translated = BootstrapError("bootstrap_failed")
            original = translated
            raise translated from error
        original = error
        raise
    finally:
        try:
            os.close(descriptor)
        except OSError:
            if isinstance(original, BootstrapError):
                original.cleanup_incomplete = True
            elif original is not None:
                original.add_note("Bootstrap resource cleanup incomplete")
            else:
                cleanup_failure = BootstrapError("bootstrap_failed")
                cleanup_failure.cleanup_incomplete = True
                raise cleanup_failure from None
        # Never unlink the shared lock inode, including after a failed contender.


def save(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(path.name + "-" + uuid4().hex + ".pending")
    with os.fdopen(
        os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "w"
    ) as stream:
        json.dump(dict(value), stream, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    if path.exists() or path.is_symlink():
        private_file(path)
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def receipt(path: Path, fingerprint: str) -> dict[str, Any] | None:
    if not path.exists() and not path.is_symlink():
        return None
    private_file(path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        raw = stream.read(4097)
    require(len(raw) <= 4096)

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result)
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=unique)
    require(
        type(value) is dict
        and set(value)
        == {"schema_version", "target_fingerprint", "run_id", "migration_id", "source_digest"}
    )
    require(
        type(value["schema_version"]) is int
        and value["schema_version"] == 1
        and value["target_fingerprint"] == fingerprint
    )
    require(
        type(value["run_id"]) is str and re.fullmatch(r"[a-f0-9]{32}", value["run_id"]) is not None
    )
    require(
        type(value["migration_id"]) is str
        and str(UUID(value["migration_id"])) == value["migration_id"]
    )
    require(
        type(value["source_digest"]) is str
        and re.fullmatch(r"[a-f0-9]{64}", value["source_digest"]) is not None
    )
    return cast(dict[str, Any], value)


def prepare(
    owner: PostgresSettings,
    runtime: PostgresSettings,
    base: Path,
    *,
    operations: BootstrapPort | None = None,
    progress: Callable[[str], None] = lambda _: None,
) -> dict[str, Any]:
    fingerprint = binding(owner, runtime)
    require(base.name == "business-bootstrap" and base.is_absolute() and ".." not in base.parts)
    require(not any(path.is_symlink() for path in (base, *base.parents)))
    require(base.parent.is_dir())
    port = operations if operations is not None else PostgresBootstrap(owner, runtime)
    with owned_lock(base):
        progress("preflight")
        target = port.inspect()
        if target.version == 4 and target.state == "active":
            port.ready()
            return {
                "status": "business_ready",
                "schema_version": 4,
                "changed": False,
                "bootstrap_run_id": None,
                "fixture_initialization": False,
                "serving_m1_unchanged": True,
            }
        require(
            target.version in {0, 1, 2, 3} and target.state in {"absent", "staging", "active"},
            "target_refused",
        )
        require(target.version == 0 or target.counts == (0, 0, 0), "target_refused")
        entry = base / ("target-" + fingerprint + ".json")
        previous = receipt(entry, fingerprint)
        fresh = (
            target.version == 0
            and target.state == "absent"
            or target.version == 1
            and target.state == "staging"
            and target.migration_id is None
            and target.source_digest is None
        )
        require(fresh or previous is not None, "target_refused")
        if target.migration_id is not None:
            require(
                previous is not None
                and (target.migration_id, target.source_digest)
                == (previous["migration_id"], previous["source_digest"]),
                "target_refused",
            )
        run_id = previous["run_id"] if previous is not None else uuid4().hex
        directory = base / run_id
        if previous is None:
            directory.mkdir(mode=0o700)
        private_directory(directory)
        source, backup, old = (
            directory / "source.sqlite3",
            directory / "before-cutover.sqlite3",
            directory / "before-inquiry-schema.sqlite3",
        )
        progress("source")
        if previous is None:
            require(not source.exists() and not backup.exists() and not old.exists())
            migrate(source, old)
        else:
            for path in (source, backup, old):
                private_file(path)
        snapshot = prepare_source(source, backup)
        require(
            not snapshot.tasks and not snapshot.executions and not snapshot.attempts,
            "target_refused",
        )
        source_state = read_source_state(source)
        require(source_state is not None and source_state.target_identity in {None, fingerprint})
        if previous is not None:
            require(
                (snapshot.migration_id, snapshot.source_digest)
                == (previous["migration_id"], previous["source_digest"])
            )
        current = {
            "schema_version": 1,
            "target_fingerprint": fingerprint,
            "run_id": run_id,
            "migration_id": snapshot.migration_id,
            "source_digest": snapshot.source_digest,
        }
        if previous is None:
            save(entry, current)

        def stage(name: str) -> None:
            require(name in STAGES)
            save(
                directory / "stage.json", {"schema_version": 1, "stage": name, "status": "running"}
            )
            progress(name)

        stage("cutover")
        activated = port.activate(source, backup)
        require(
            (activated.migration_id, activated.source_digest)
            == (snapshot.migration_id, snapshot.source_digest)
            and (activated.tasks, activated.executions, activated.attempts) == (0, 0, 0)
            and activated.state == "active"
        )
        for version in (2, 3, 4):
            stage("upgrade_v" + str(version))
            port.upgrade(version)
        stage("verify")
        port.ready()
        save(directory / "stage.json", {"schema_version": 1, "stage": "verify", "status": "passed"})
        return {
            "status": "business_ready",
            "schema_version": 4,
            "changed": True,
            "bootstrap_run_id": run_id,
            "fixture_initialization": False,
            "serving_m1_unchanged": True,
        }


def settings(values: Mapping[str, str]) -> tuple[PostgresSettings, PostgresSettings]:
    schema = values.get("P1_WORKER_SCHEMA", "continuity")
    port = int(values["POSTGRES_PORT"])
    return (
        PostgresSettings(
            host="127.0.0.1",
            port=port,
            dbname="livekit_lab",
            schema=schema,
            user="continuity_migrator",
            password=values["POSTGRES_MIGRATION_PASSWORD"],
        ),
        PostgresSettings(
            host="127.0.0.1",
            port=port,
            dbname="livekit_lab",
            schema=schema,
            user="livekit_lab",
            password=values["POSTGRES_PASSWORD"],
        ),
    )


def main() -> int:
    stage = "preflight"

    def progress(current: str) -> None:
        nonlocal stage
        require(current in STAGES)
        stage = current
        print(
            json.dumps({"event": "business_preparation", "stage": stage, "status": "running"}),
            flush=True,
        )

    def timed_out(_signal: int, _frame: object) -> NoReturn:
        raise BootstrapError("bootstrap_timeout")

    def cancelled(_signal: int, _frame: object) -> NoReturn:
        raise BootstrapError("bootstrap_cancelled")

    previous = signal.signal(signal.SIGALRM, timed_out)
    previous_term = signal.signal(signal.SIGTERM, cancelled)
    previous_int = signal.signal(signal.SIGINT, cancelled)
    signal.setitimer(signal.ITIMER_REAL, 90)
    try:
        require(len(sys.argv) == 1, "setup_required")
        for name in tuple(os.environ):
            if name.startswith(("PG", "P1_")):
                os.environ.pop(name)
        spec = importlib.util.spec_from_file_location(
            "business_prepare_settings", ROOT / "local-setup/stack.py"
        )
        require(spec is not None and spec.loader is not None, "setup_required")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        owner, runtime = settings(module.load_settings(ROOT / "local-setup"))
        local = ROOT / ".local"
        require(not local.is_symlink())
        local.mkdir(mode=0o700, exist_ok=True)
        info = local.lstat()
        require(
            stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o022
        )
        result = prepare(owner, runtime, local / "business-bootstrap", progress=progress)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    except Exception as error:  # noqa: BLE001 - fixed host CLI diagnostics only
        payload = {
            "status": "failed",
            "code": error.code if isinstance(error, BootstrapError) else "bootstrap_failed",
            "stage": stage,
            "partial_artifacts_retained": True,
            "cleanup_incomplete": isinstance(error, BootstrapError) and error.cleanup_incomplete,
        }
        print(json.dumps(payload), flush=True)
        return 2
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)


if __name__ == "__main__":
    raise SystemExit(main())
