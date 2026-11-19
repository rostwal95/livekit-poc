"""Supplemental isolated P2 PG proof; inert unless explicitly invoked with execute.

Each fixture mode runs in its own closed-environment process group. Failure,
timeout or uncertain ownership withholds all later stages, including DROP.
This local evidence tool is not a maintained runtime or a full P1/RTC gate.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
NODE = Path(
    "/private/tmp/livekit-academy-node-24.22.2-n1rqgu__/node-v24.22.2-darwin-arm64/bin/node"
)
FIXTURE = ROOT / "output/lifecycle-cleanup/pg-native-end.mjs"
BASE = {"PATH": "/usr/bin:/bin", "LANG": "C", "NO_COLOR": "1"}
STAGES = {"install": 45, "run": 90, "verify": 15, "cleanup": 15}
CAP = 32768
STOP_SECONDS = 10
TOTAL_SECONDS = 220
_stopped = False


class Failed(RuntimeError):
    """Finite error only; never reflect configuration, SQL or child text."""


def need(value: bool, code: str) -> None:
    if not value:
        raise Failed(code)


def encoded(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, allow_nan=False, indent=2) + "\n").encode()


def publish(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def private_directory(path: Path) -> None:
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = path.lstat()
    need(
        stat.S_ISDIR(info.st_mode)
        and not stat.S_ISLNK(info.st_mode)
        and stat.S_IMODE(info.st_mode) == 0o700
        and info.st_uid == os.getuid(),
        "private_directory_invalid",
    )


def group_absent(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def signal_group(pid: int, value: int) -> None:
    try:
        os.killpg(pid, value)
    except ProcessLookupError:
        pass


def fixture_report(mode: str, raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise Failed("invalid_child_report") from None
    expected = {"schemaVersion", "mode", "status"} | {
        "install": set(),
        "run": {"scenarios", "externalLogicalAcceptances", "cleanupComplete"},
        "verify": {"reconciledOriginalInputs", "independentExternalReceipts"},
        "cleanup": {"cleanupComplete"},
    }[mode]
    need(type(value) is dict and set(value) == expected, "invalid_child_report")
    need(
        type(value["schemaVersion"]) is int
        and value["schemaVersion"] == 1
        and value["mode"] == mode
        and value["status"] == "passed",
        "invalid_child_report",
    )
    for key, count in {
        "scenarios": 6,
        "externalLogicalAcceptances": 3,
        "reconciledOriginalInputs": 6,
        "independentExternalReceipts": 3,
    }.items():
        if key in value:
            need(type(value[key]) is int and value[key] == count, "invalid_child_report")
    if "cleanupComplete" in value:
        need(value["cleanupComplete"] is True, "invalid_child_report")
    return value


def child(
    mode: str,
    config: Path,
    work: Path,
    deadline: float,
    records: list[dict[str, object]],
) -> None:
    """Bound capture and observation; retain state if actual absence is unproved."""
    need(not _stopped and time.monotonic() < deadline, "stopped_before_stage")
    process = subprocess.Popen(
        [str(NODE), str(FIXTURE), mode],
        cwd=ROOT,
        env={**BASE, "P2_END_CONFIG": str(config)},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    record: dict[str, object] = {"mode": mode, "pid": process.pid, "pgid": process.pid}
    records.append(record)
    captured = {"stdout": bytearray(), "stderr": bytearray()}
    first_failure: str | None = None
    stop_at: float | None = None
    sent_kill = False
    stage_end = min(deadline, time.monotonic() + STAGES[mode])
    assert process.stdout is not None and process.stderr is not None
    try:
        publish(work / (mode + "-owner.json"), encoded(record))
        with selectors.DefaultSelector() as observer:
            for stream, name in ((process.stdout, "stdout"), (process.stderr, "stderr")):
                os.set_blocking(stream.fileno(), False)
                observer.register(stream, selectors.EVENT_READ, name)
            while observer.get_map() or process.poll() is None or not group_absent(process.pid):
                now = time.monotonic()
                if (_stopped or now >= stage_end or first_failure) and stop_at is None:
                    first_failure = first_failure or (
                        "interrupted" if _stopped else "child_timeout"
                    )
                    stop_at = now
                    signal_group(process.pid, signal.SIGTERM)
                if stop_at is not None:
                    if not sent_kill and now - stop_at >= 2:
                        signal_group(process.pid, signal.SIGKILL)
                        sent_kill = True
                    if now - stop_at >= STOP_SECONDS:
                        break
                for key, _ in observer.select(0.025):
                    raw = os.read(key.fd, 8192)
                    if not raw:
                        observer.unregister(key.fileobj)
                    else:
                        output = captured[key.data]
                        if len(output) + len(raw) > CAP:
                            first_failure = first_failure or "capture_exceeded"
                        output.extend(raw[: max(0, CAP - len(output))])
            reaped = process.poll() is not None
            if reaped:
                process.wait(timeout=1)
            record.update(
                returncode=process.returncode,
                reaped=reaped,
                groupAbsent=group_absent(process.pid),
                pipeEof=not bool(observer.get_map()),
                stdoutBytes=len(captured["stdout"]),
                stderrBytes=len(captured["stderr"]),
            )
    except BaseException as error:
        # No later phase may run after this error; keep the exact process identity.
        record["firstFailure"] = str(error) if type(error) is Failed else "child_observer_failed"
        signal_group(process.pid, signal.SIGKILL)
        try:
            process.wait(timeout=STOP_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        record.update(
            returncode=process.poll(),
            reaped=process.poll() is not None,
            groupAbsent=group_absent(process.pid),
        )
        raise
    finally:
        process.stdout.close()
        process.stderr.close()
        try:
            for name, raw in captured.items():
                publish(work / (mode + "." + name + ".bin"), bytes(raw))
            publish(work / (mode + "-final-owner.json"), encoded(record))
        except OSError:
            if "firstFailure" not in record:
                raise Failed(first_failure or "capture_persist_failed") from None
    need(
        record["reaped"] is True and record["groupAbsent"] is True and record["pipeEof"] is True,
        first_failure or "cleanup_incomplete",
    )
    need(first_failure is None, first_failure or "child_failed")
    need(process.returncode == 0 and not captured["stderr"], "child_failed")
    record["report"] = fixture_report(mode, bytes(captured["stdout"]))


def load_setup():
    path = ROOT / "local-setup/scripts/channel_policy_setup.py"
    spec = importlib.util.spec_from_file_location("lifecycle_pg_owner_setup", path)
    need(spec is not None and spec.loader is not None, "setup_unavailable")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def namespace(settings, schema: str) -> dict[str, object] | None:
    with closing(settings.connect(application_name="continuity-migrate")) as connection:
        return connection.execute(
            "SELECT n.nspname, r.rolname AS owner FROM pg_namespace n "
            "JOIN pg_roles r ON r.oid=n.nspowner WHERE n.nspname=%s",
            [schema],
        ).fetchone()


def execute() -> int:
    # The strict maintained loader reads only infrastructure settings. It does
    # not read .env.providers; role passwords are never placed in argv/report.
    started = time.monotonic()
    records: list[dict[str, object]] = []
    run_id = uuid4().hex
    schema = "p2_lifecycle_" + run_id
    need(re.fullmatch(r"p2_lifecycle_[a-f0-9]{32}", schema) is not None, "invalid_schema")
    private_root = ROOT / "output/lifecycle-cleanup/private-runs"
    private_directory(private_root)
    work = private_root / run_id
    work.mkdir(mode=0o700)  # A prior observation is never reused or repaired.
    private_directory(work)
    data = work / "data"
    data.mkdir(mode=0o700)
    report: dict[str, object] = {
        "schemaVersion": 1,
        "schema": schema,
        "privateWork": str(work),
        "status": "failed",
        "stages": records,
        "cleanupComplete": False,
        "limits": "Supplemental real P2 PostgreSQL/HTTP; cooperating file port, not P1/RTC/provider qualification.",
    }
    try:
        need(NODE.is_file() and os.access(NODE, os.X_OK), "node_unavailable")
        report["nodeSha256"] = hashlib.sha256(NODE.read_bytes()).hexdigest()
        fixture_hash = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        report["fixtureSha256"] = fixture_hash
        bindings = {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "projects/channel-continuity/dist").glob("*.js"))
        }
        need(bool(bindings), "build_unavailable")
        report["runtimeBindings"] = bindings
        setup = load_setup()
        database = setup._load_database(ROOT)
        settings = setup._settings(database, schema, owner=True)
        need(namespace(settings, schema) is None, "schema_already_exists")
        publish(
            work / "ownership.json",
            encoded(
                {
                    "schemaVersion": 1,
                    "runId": run_id,
                    "schema": schema,
                    "freshNamespaceObserved": True,
                    "fixtureSha256": fixture_hash,
                    "node": str(NODE),
                    "parentPid": os.getpid(),
                }
            ),
        )
        configs = {}
        for role, user, password in (
            ("owner", "continuity_migrator", database.owner_password),
            ("runtime", "livekit_lab", database.runtime_password),
        ):
            path = work / (role + "-config.json")
            publish(
                path,
                encoded(
                    {
                        "database": {
                            "host": "127.0.0.1",
                            "port": database.port,
                            "database": "livekit_lab",
                            "schema": schema,
                            "user": user,
                            "password": password,
                        },
                        "directory": str(data),
                    }
                ),
            )
            configs[role] = path
        for mode in STAGES:
            need(
                not _stopped and time.monotonic() - started < TOTAL_SECONDS, "stopped_before_stage"
            )
            need(
                hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == fixture_hash, "fixture_changed"
            )
            need(
                all(
                    hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == digest
                    for p, digest in bindings.items()
                ),
                "build_changed",
            )
            if mode == "cleanup":
                # Prior run+verify passed; every earlier child has an independent
                # observed reap/absence before this sole owned-schema DROP.
                need(
                    namespace(settings, schema)
                    == {"nspname": schema, "owner": "continuity_migrator"},
                    "schema_ownership_changed",
                )
                need(
                    all(x.get("reaped") is True and x.get("groupAbsent") is True for x in records),
                    "cleanup_incomplete",
                )
            child(
                mode,
                configs["runtime" if mode == "run" else "owner"],
                work,
                started + TOTAL_SECONDS,
                records,
            )
        need(namespace(settings, schema) is None, "schema_absence_unconfirmed")
        report["schemaAbsenceIndependentlyObserved"] = True
        # Delete only this run's credential copies, after actual owner settlement
        # and proven schema removal; preserve synthetic nonsecret proof files.
        credential_copies = (configs["owner"], configs["runtime"], data / "fixture.json")
        for path in credential_copies:
            info = path.lstat()
            need(
                stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and stat.S_IMODE(info.st_mode) == 0o600,
                "credential_copy_changed",
            )
        for path in credential_copies:
            path.unlink()
        report.update(status="passed", cleanupComplete=True, credentialCopiesRemoved=True)
    except Exception as error:  # noqa: BLE001 - finite evidence boundary, preserve private state
        report["firstFailure"] = (
            str(error)
            if type(error) is Failed
            else "interrupted"
            if isinstance(error, KeyboardInterrupt)
            else "orchestrator_failed"
        )
        report["preservedPrivateWork"] = True
        report["dependentDropWithheldAfterFailure"] = not any(
            x["mode"] == "cleanup" for x in records
        )
    report["elapsedSeconds"] = round(time.monotonic() - started, 3)
    publish(work / "report.json", encoded(report))
    # Only finite status and a private evidence path are printed; never child text.
    print(json.dumps({"status": report["status"], "report": str(work / "report.json")}))
    return 0 if report["status"] == "passed" else 1


def plan() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "status": "prepared_not_executed",
        "node": str(NODE),
        "fixture": str(FIXTURE),
        "modes": STAGES,
        "totalObserverSeconds": TOTAL_SECONDS,
        "stopObservationSeconds": STOP_SECONDS,
        "captureBytesPerStreamPerChild": CAP,
        "schemaPattern": "p2_lifecycle_<fresh_uuid_hex>",
        "roleEnvironment": sorted([*BASE, "P2_END_CONFIG"]),
        "settingsLoader": "channel_policy_setup._load_database",
        "configurationReads": [
            "local-setup/.env",
            "local-setup/.secrets.env",
            "local-setup/images.env",
        ],
        "failurePolicy": "Preserve first failure, work, credentials and schema; no dependent DROP. If group absence is unresolved, record exact PID/group and fail without dependent cleanup.",
        "successPolicy": "Separate role children install/run/verify/cleanup; all actual owners settled before DROP; independently check schema absence; remove only owned credential copies.",
        "limits": "Supplemental P2 PostgreSQL/HTTP only; no providers, SFU, browser or full P1 gate.",
    }


def main() -> int:
    if sys.argv[1:] == ["--plan"]:
        print(json.dumps(plan(), indent=2))
        return 0
    if sys.argv[1:] != ["execute"]:
        print('{"status":"failed","code":"explicit_execute_required"}')
        return 2

    def stopped(_signum, _frame):
        global _stopped
        _stopped = True

    for value in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(value, stopped)
    return execute()


if __name__ == "__main__":
    raise SystemExit(main())
