"""Selected native fixed-policy qualification; --plan is pure and starts no resources.

The parent owns only isolated fixtures. P1 owns durable work and case authority;
SDK text, browser display, verified results and business permission stay separate.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import importlib.util
import json
import math
import os
import re
import stat
import sys
import time
from collections.abc import Awaitable, Callable
from contextlib import closing
from datetime import timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Literal, NoReturn, TypeVar, cast
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import p3_document_evidence as common
import p3_durable_fixed_policy_check as durable
import p3_fixed_policy_check as policy
from p3_document_package import GroupedOwnedProcess

from harness.process_control import FileBarrier, OwnedProcess

GateError = common.GateError
read_private, write_private, private_directory = (
    common.read_private,
    common.write_private,
    common.private_directory,
)
canonical, digest, exact = common.canonical, common.digest, common.exact
MAX_CHILDREN, MAX_CAPTURE, MAX_STREAM, MAX_PROOF = 32, 2097152, 65536, 65536
MAX_RETAINED_BYTES, MAX_RETAINED_FILES = 16777216, 2048
SOURCE_CHILDREN, INSTALLED_CHILDREN = 11, 32
PROJECT = durable.PROJECT
NODE_FIXTURE = PROJECT + "/tests/fixtures/native-policy-server.mjs"
PYTHON_FIXTURE = "projects/delegation-reliability/tests/pg_native_policy_cases.py"
CONSOLE = "apps/local-console"
LABELS = ("native_known", "native_retained", "native_stale", "native_useful")
CASES = (
    "trusted_positive_revision_and_exact_sources",
    "one_sdk_session_per_application",
    "acknowledgement_before_pending_update",
    "held_original_without_result",
    "useful_followup_and_concurrent_authoritative_read",
    "original_verified_result",
    "same_identity_zero_write_replay",
    "stale_original_result_and_outdated_applicability",
    "foreign_and_malformed_input_denial",
    "retained_waiter_and_internal_timeout_ownership",
    "sdk_cancellation_is_not_business_cancellation",
    "actual_close_and_later_useful_progress",
)
BROWSER_GROUPS = (
    "native_text_held_followup",
    "original_result_outdated_applicability",
    "read_failure_retry_and_forget",
)
STAGES = durable.STAGES | {"native-consumer", "ui-build", "browser", "room", "owner-advance"}
BUILD_ROLES = frozenset(
    {
        "compile",
        "public-types",
        "fresh-package",
        "python-venv",
        "python-install",
        "npm-install",
        "installed-imports",
        "ui-build",
        "build",
    }
)
SAFE_CODES = durable.SAFE_CODES
MARKERS = (
    "native_node_ready",
    "native_followup",
    "native_retained_ready",
    "native_ui_ready",
    "native_browser_finished",
    "native_case_done",
)
BROWSER_MARKERS = (
    "parent-peer-held.json",
    "parent-case-advanced.json",
    "parent-result-released.json",
)
SCREENSHOTS = (
    "p3-native-outdated-desktop.png",
    "p3-native-outdated-mobile.png",
    "p3-native-forgotten-mobile.png",
)
T = TypeVar("T")


def fail() -> NoReturn:
    raise GateError("invalid_proof")


def keys(value: object, names: set[str]) -> dict[str, Any]:
    return policy.keys(value, names)


def same(value: object, expected: object) -> None:
    if not exact(value, expected):
        fail()


def uuid(value: object) -> str:
    if type(value) is not str:
        fail()
    try:
        parsed = UUID(value)
    except ValueError:
        fail()
    if parsed.version != 4 or str(parsed) != value:
        fail()
    return value


def bounded(value: object, maximum: int = MAX_PROOF) -> bytes:
    raw = canonical(value)
    if not 0 < len(raw) <= maximum:
        fail()
    return raw


def natural(value: object, maximum: int = 4102444800000, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        fail()
    return value


def proof_boundary(function: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    @wraps(function)
    def checked(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return function(*args, **kwargs)
        except GateError:
            raise
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            UnicodeError,
            RecursionError,
            IndexError,
        ):
            raise GateError("invalid_proof") from None

    return checked


def plan(*, installed: bool = False) -> dict[str, Any]:
    if type(installed) is not bool:
        raise GateError("invalid_input")
    return {
        "schema_version": 1,
        "status": "planned",
        "tests": 12,
        "cases": list(CASES),
        "browser_groups": 3,
        "package_assertions": 8 if installed else 0,
        "child_commands": INSTALLED_CHILDREN if installed else SOURCE_CHILDREN,
        "max_owned_process_groups": 32,
        "deadline_seconds": 360 if installed else 180,
        "cleanup_seconds": 20,
        "stream_bytes": MAX_STREAM,
        "aggregate_capture_bytes": MAX_CAPTURE,
        "applications": list(LABELS),
        "services": "isolated PG + one local SFU RTC TEXT room; scripted, no providers/audio",
    }


def validate_environment(value: dict[str, str], role: str) -> None:
    if role == "node-server":
        required = {"P3_NATIVE_DIRECTORY", "P3_NATIVE_TOKEN"}
        allowed = required | durable.BASE_KEYS
    elif role == "browser":
        required = {
            "P3_NATIVE_BROWSER_ORIGIN",
            "P3_NATIVE_BROWSER_OUTPUT",
            "P3_NATIVE_BROWSER_ACCESS",
        }
        allowed = required | durable.BASE_KEYS | {"PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"}
    elif role == "native-consumer":
        durable.validate_environment(value, "exercise")
        return
    elif role in {"install", "cleanup"}:
        durable.validate_environment(value, role)
        return
    elif role in BUILD_ROLES:
        durable.validate_environment(value, "build")
        return
    else:
        raise GateError("invalid_environment")
    if type(value) is not dict or not required <= value.keys() or value.keys() - allowed:
        raise GateError("invalid_environment")
    if any(
        type(k) is not str or type(v) is not str or not v or "\0" in v for k, v in value.items()
    ):
        raise GateError("invalid_environment")
    for name in required:
        if (
            name.endswith(("TOKEN", "ACCESS"))
            and re.fullmatch(r"[A-Za-z0-9_-]{43}", value[name]) is None
        ):
            raise GateError("invalid_environment")
    for name in ("P3_NATIVE_DIRECTORY", "P3_NATIVE_BROWSER_OUTPUT"):
        if name in value and (
            not Path(value[name]).is_absolute()
            or ".." in Path(value[name]).parts
            or "." in Path(value[name]).parts
        ):
            raise GateError("invalid_environment")
    if role == "browser":
        match = re.fullmatch(
            r"http://127[.]0[.]0[.]1:([1-9][0-9]{0,4})", value["P3_NATIVE_BROWSER_ORIGIN"]
        )
        if match is None or int(match.group(1)) > 65535:
            raise GateError("invalid_environment")


def publish_browser_marker(path: Path, raw: bytes) -> None:
    if path.name not in BROWSER_MARKERS or type(raw) is not bytes or not 0 < len(raw) <= 4096:
        raise GateError("unsafe_path")
    private_directory(path.parent)
    pending = path.with_name(path.name + ".publishing")
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


def target_path(root: Path, requested: Path) -> Path:
    if (
        requested.is_absolute()
        or requested.parts[:3] != (".local", "validation", "p3-native-policy")
        or len(requested.parts) != 4
        or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,99}[.]json", requested.name) is None
    ):
        raise GateError("unsafe_path")
    target = root / requested
    if (
        any(p.is_symlink() for p in (target, *target.parents))
        or target.exists()
        or target.with_name(target.stem + "-artifacts").exists()
        or target.with_name(target.stem + "-artifacts").is_symlink()
    ):
        raise GateError("unsafe_path")
    return target


@proof_boundary
def validated_report(raw: bytes) -> dict[str, Any]:
    v = keys(
        common.decode(raw),
        {
            "schema_version",
            "status",
            "mode",
            "tests",
            "passed",
            "failures",
            "errors",
            "skipped",
            "duration_seconds",
            "child_commands",
            "browser_groups",
            "package_assertions",
            "cleanup_complete",
            "code",
            "stage",
            "retained_index_sha256",
            "case_results",
        },
    )
    installed = v["mode"] == "local_native_policy_installed"
    if (
        v["mode"] not in {"local_native_policy_source", "local_native_policy_installed"}
        or not exact(v["schema_version"], 1)
        or not exact(v["tests"], 12)
        or type(v["duration_seconds"]) not in (int, float)
        or not math.isfinite(v["duration_seconds"])
        or not 0 < v["duration_seconds"] <= (360 if installed else 180)
        or not common.natural(v["passed"], 0, 12)
        or not common.natural(v["child_commands"], 0, 32)
        or not common.natural(v["browser_groups"], 0, 3)
        or type(v["package_assertions"]) is not int
        or v["package_assertions"] not in ({0, 8} if installed else {0})
        or type(v["cleanup_complete"]) is not bool
        or v["code"] not in SAFE_CODES
        or v["stage"] not in STAGES
        or not exact(v["errors"], 0)
        or not exact(v["skipped"], 0)
        or (
            v["retained_index_sha256"] is not None
            and not common.is_hash(v["retained_index_sha256"])
        )
    ):
        raise GateError("invalid_report")
    if not exact(
        v["case_results"], [{"name": n, "status": "passed"} for n in CASES[: v["passed"]]]
    ):
        raise GateError("invalid_report")
    if v["status"] == "passed":
        expected = {
            "passed": 12,
            "failures": 0,
            "child_commands": 32 if installed else 11,
            "browser_groups": 3,
            "package_assertions": 8 if installed else 0,
            "cleanup_complete": True,
            "code": "ok",
            "stage": "complete",
        }
        if any(not exact(v[k], x) for k, x in expected.items()) or not common.is_hash(
            v["retained_index_sha256"]
        ):
            raise GateError("invalid_report")
    elif v["status"] != "failed" or not exact(v["failures"], 1) or v["code"] == "ok":
        raise GateError("invalid_report")
    return v


@proof_boundary
def validate_peer(value: object, input_value: dict[str, Any], *, owner_id: str) -> dict[str, Any]:
    p = keys(
        value,
        {
            "schema_version",
            "kind",
            "status",
            "owner_id",
            "scope",
            "input_sha256",
            "template_sha256",
            "invoked",
            "returned",
            "duplicate_entries",
            "hold_reached",
            "hold_released",
            "record",
            "server_metrics",
            "policy_metrics",
            "events",
            "cleanup_complete",
        },
    )
    bounded(p)
    for k, x in {
        "schema_version": 1,
        "kind": "native-policy.peer",
        "status": "passed",
        "owner_id": owner_id,
        "invoked": 1,
        "returned": 1,
        "duplicate_entries": 0,
        "hold_reached": True,
        "hold_released": True,
        "cleanup_complete": True,
    }.items():
        same(p[k], x)
    template = common.decode(input_value["request_utf8"].encode(), 16384)
    same(p["scope"], template["scope"])
    same(p["template_sha256"], digest(input_value["request_utf8"].encode()))
    same(p["input_sha256"], digest(canonical(input_value) + b"\n"))
    r = keys(
        p["record"],
        {
            "request",
            "request_sha256",
            "result",
            "result_sha256",
            "started_at_ms",
            "returned_at_ms",
            "code",
        },
    )
    same(r["code"], "ok")
    same(digest(bounded(r["request"], 16384)), r["request_sha256"])
    same(digest(bounded(r["result"], 8192)), r["result_sha256"])
    for name in template:
        if name != "attempt":
            same(r["request"][name], template[name])
    _request, _result, verdict = policy.policy_wire(
        {
            "request_utf8": canonical(r["request"]).decode(),
            "result_utf8": canonical(r["result"]).decode(),
        },
        input_value["evidence"],
    )
    same(verdict, "candidate")
    if natural(r["returned_at_ms"]) < natural(r["started_at_ms"]):
        fail()
    same(
        p["events"],
        [
            {"event": "attempt_started", "operation": "invoke", "code": "ok"},
            {"event": "attempt_finished", "operation": "invoke", "code": "ok"},
            {"event": "closed", "operation": "http", "code": "ok"},
        ],
    )
    metrics = p["server_metrics"]
    if type(metrics) is not dict or any(type(x) is not int or x < 0 for x in metrics.values()):
        fail()
    for name in (
        "active",
        "requests",
        "sockets",
        "observerPending",
        "rejected",
        "cancellations",
        "expirations",
        "disconnects",
        "observerFailures",
        "observerDropped",
    ):
        same(metrics.get(name), 0)
    for name in ("invoked", "completed"):
        same(metrics.get(name), 1)
    same(p["policy_metrics"], {"evaluated": 1, "clarified": 0})
    return p


@proof_boundary
def validate_case(
    value: object,
    peer: dict[str, Any],
    input_value: dict[str, Any],
    *,
    label: str,
    owner_id: str,
    command_id: str,
) -> dict[str, Any]:
    if label not in LABELS:
        fail()
    p = keys(
        value,
        {
            "schema_version",
            "kind",
            "name",
            "scope",
            "request",
            "case_before",
            "case_after",
            "observation",
            "accepted",
            "issued",
            "stored_result",
            "sdk",
            "counters",
            "replay",
            "ownership",
            "cleanup_complete",
        },
    )
    bounded(p)
    for k, x in {
        "schema_version": 1,
        "kind": "native-policy.case",
        "name": label,
        "cleanup_complete": True,
    }.items():
        same(p[k], x)
    q = common.decode(input_value["request_utf8"].encode(), 16384)
    same(p["request"], q)
    same(p["scope"], q["scope"])
    same(q["delegation_id"], label)
    same(q["case_id"], "case_fixed")
    same(q["request_revision"], 2 if label == "native_useful" else 1)
    a = keys(
        p["accepted"],
        {
            "work_id",
            "scope",
            "idempotency_key",
            "payload",
            "accepted_at_ms",
            "cancel_requested",
            "status",
        },
    )
    uuid(a["work_id"])
    same(a["scope"], q["scope"])
    same(a["idempotency_key"], label)
    same(a["cancel_requested"], False)
    same(a["status"], "accepted")
    same(
        a["payload"],
        {
            "operation": "booking.evaluate_policy",
            "body": canonical(q).decode(),
            "deadline_at_ms": q["deadline_at_ms"],
            "sha256": digest(canonical(q)),
        },
    )
    natural(a["accepted_at_ms"])
    g = keys(
        p["issued"],
        {
            "record",
            "attempt_id",
            "command_id",
            "number",
            "owner_id",
            "epoch",
            "issued_at_ms",
            "lease_until_ms",
        },
    )
    same(g["record"], a)
    uuid(g["attempt_id"])
    same(g["command_id"], command_id)
    same(g["owner_id"], owner_id)
    same(g["number"], 1)
    same(g["epoch"], 1)
    if not natural(g["issued_at_ms"]) < natural(g["lease_until_ms"]):
        fail()
    r = keys(
        p["stored_result"],
        {"work_id", "attempt_id", "body", "recorded_at_ms", "disposition", "sha256"},
    )
    same(r["work_id"], a["work_id"])
    same(r["attempt_id"], g["attempt_id"])
    same(r["disposition"], "eligible_at_commit")
    same(r["body"], peer["record"]["result"])
    same(r["sha256"], peer["record"]["result_sha256"])
    natural(r["recorded_at_ms"])
    same(
        peer["record"]["request"]["attempt"],
        {"attempt_id": "attempt_" + g["attempt_id"].replace("-", ""), "number": 1},
    )
    o = keys(
        p["observation"],
        {
            "schema_version",
            "kind",
            "binding",
            "state",
            "tool_waiter",
            "owned_run",
            "work",
            "attempt",
            "result",
            "applicability",
            "app_read_completed_at_ms",
            "error",
            "consistency",
        },
    )
    same(o["schema_version"], 1)
    same(o["kind"], "native-policy.observation")
    same(o["error"], None)
    same(o["consistency"], "as_of_non_atomic")
    same(o["owned_run"], False)
    same(o["state"], "outdated" if label == "native_stale" else "result")
    same(o["applicability"], "outdated" if label == "native_stale" else "candidate")
    same(
        o["binding"],
        {
            "scope": q["scope"],
            "delegation_id": label,
            "case_id": "case_fixed",
            "request_revision": q["request_revision"],
            "input_fingerprint": q["input_fingerprint"],
            "sources": [
                {k: ref[k] for k in ("source_id", "version", "sha256", "byte_length")}
                | {"role": role}
                for ref, role in zip(q["evidence"], ("policy", "facts"), strict=True)
            ],
        },
    )
    same(
        o["work"],
        {
            "work_id": a["work_id"],
            "request_sha256": a["payload"]["sha256"],
            "accepted_at_ms": a["accepted_at_ms"],
            "status": "result_recorded",
            "cancel_requested": False,
        },
    )
    same(o["attempt"], {"attempt_id": g["attempt_id"], "number": 1})
    body = r["body"]
    same(
        o["result"],
        {
            "attempt_id": g["attempt_id"],
            "wire_attempt_id": body["attempt_id"],
            "sha256": r["sha256"],
            "recorded_at_ms": r["recorded_at_ms"],
            "disposition": r["disposition"],
            "eligible": True,
            "uncertainty": "none",
            "rule_refs": body["rule_refs"],
            "fact_refs": body["fact_refs"],
        },
    )
    natural(o["app_read_completed_at_ms"])
    if type(o["tool_waiter"]) is not str or o["tool_waiter"] not in {
        "idle",
        "waiting",
        "returned",
        "stopped_waiting",
    }:
        fail()
    for name, rev in (
        ("case_before", q["request_revision"]),
        ("case_after", 2 if label in {"native_stale", "native_useful"} else 1),
    ):
        c = p[name]
        if type(c) is not dict:
            fail()
        same(c.get("case_revision"), str(rev))
        if (
            not common.is_hash(c.get("projection_revision"))
            or c.get("case_id") is None
            or c.get("task_id") is None
        ):
            fail()
    same(p["case_before"]["case_id"], p["case_after"]["case_id"])
    same(p["case_before"]["task_id"], p["case_after"]["task_id"])
    replay = keys(p["replay"], {"before", "after", "observation"})
    same(replay["before"], replay["after"])
    same(replay["observation"]["result"], o["result"])
    counters = p["counters"]
    for source, names in [
        ("work", ("submit", "find", "get", "cancel", "close")),
        ("execution", ("issue", "find_issue", "complete", "result", "observe", "close")),
    ]:
        v = keys(counters[source], set(names))
        for x in v.values():
            natural(x, 1000)
    for k in ("submit", "cancel"):
        same(counters["work"][k], 1 if k == "submit" else 0)
    for k in ("issue", "complete"):
        same(counters["execution"][k], 1)
    same(counters["specialist"]["invocations"], 1)
    sdk = keys(p["sdk"], {"events", "useful_replies", "completed_replies"})
    if type(sdk["events"]) is not list or not 3 <= len(sdk["events"]) <= 24:
        fail()
    natural(sdk["useful_replies"], 4, 1)
    natural(sdk["completed_replies"], 4)
    active = set()
    ended = []
    for event in sdk["events"]:
        kind = event.get("type")
        fields = (
            {"type", "call_id", "name"}
            if kind == "started"
            else {"type", "call_id", "message", "silent"}
            if kind == "updated"
            else {"type", "call_id", "status"}
            if kind == "ended"
            else set()
        )
        if not fields:
            fail()
        event = keys(event, fields)
        call_id = event["call_id"]
        if type(call_id) is not str or not 1 <= len(call_id.encode()) <= 128:
            fail()
        if kind == "started":
            same(event["name"], "evaluate_policy")
            if call_id in active:
                fail()
            active.add(call_id)
        elif call_id not in active:
            fail()
        if kind == "updated":
            same(event["silent"], True)
            same(
                event["message"],
                str({"schema_version": 1, "status": "pending", "work_id": a["work_id"]}),
            )
        if kind == "ended":
            if event["status"] not in {"done", "cancelled", "error"}:
                fail()
            ended.append(event["status"])
            active.remove(call_id)
    if active:
        fail()
    if label == "native_retained":
        same(ended, ["cancelled"])
    elif not ended or any(
        status not in ({"done", "cancelled"} if label == "native_stale" else {"done"})
        for status in ended
    ):
        fail()
    starts = [
        e
        for e in sdk["events"]
        if e.get("type") == "started" and e.get("name") == "evaluate_policy"
    ]
    updates = [e for e in sdk["events"] if e.get("type") == "updated"]
    if not starts or not updates:
        fail()
    update = updates[0]
    same(update.get("silent"), True)
    same(
        update["message"],
        str({"schema_version": 1, "status": "pending", "work_id": a["work_id"]}),
    )
    same(update["call_id"], starts[0]["call_id"])
    own = p["ownership"]
    if label == "native_known":
        denial = keys(own.get("pre_entry_denials"), {"cases", "before", "after"})
        same(
            denial["cases"],
            [
                {"name": "zero_revision_request", "code": "invalid_input"},
                {"name": "foreign_evidence_scope", "code": "invalid_input"},
                {"name": "malformed_observation", "code": "invalid_observation"},
            ],
        )
        zero = {"submit": 0, "cancel": 0, "issue": 0, "complete": 0, "invoke": 0}
        same(denial["before"], zero)
        same(denial["after"], zero)
    for name in ("session_closed", "app_closed", "model_closed", "shared_case_closed"):
        same(own.get(name), True)
    for name in ("coordinator_pending", "runner_pending"):
        same(own.get(name), 0)
    if label == "native_retained":
        for k, x in {
            "wrapper_done_while_pending": True,
            "runner_pending_held": 1,
            "new_call_code": "capacity",
            "close_code": "cleanup_incomplete",
            "shared_reader_open": True,
        }.items():
            same(own.get(k), x)
        same(
            own.get("fresh_inspector_writes"),
            {"submit": 0, "cancel": 0, "issue": 0, "complete": 0, "invoke": 0},
        )
        held = keys(own["read_while_held"], set(o))
        same(held["state"], "work")
        same(held["tool_waiter"], "stopped_waiting")
        same(held["result"], None)
        same(held["owned_run"], True)
        same(held["binding"], o["binding"])
        same(held["attempt"], o["attempt"])
        same(held["work"], {**o["work"], "status": "running"})
        same(held["applicability"], "missing")
        same(held["error"], None)
        same(held["schema_version"], 1)
        same(held["kind"], "native-policy.observation")
        same(held["consistency"], "as_of_non_atomic")
        natural(held["app_read_completed_at_ms"])
    if label == "native_stale":
        room = keys(
            own.get("room_io"),
            {"participant_identity", "audio_input", "audio_output", "text_output", "session_host"},
        )
        if not policy.ident(room["participant_identity"]):
            fail()
        for k, x in {
            "audio_input": False,
            "audio_output": False,
            "text_output": True,
            "session_host": False,
        }.items():
            same(room[k], x)
    return p


@proof_boundary
def validate_browser(value: object, case: dict[str, Any], *, session_id: str) -> dict[str, Any]:
    p = keys(
        value,
        {
            "schema_version",
            "status",
            "mode",
            "groups",
            "session_id",
            "work_id",
            "request_revision",
            "input_fingerprint",
            "useful_reply_sha256",
            "final_reply_observed",
            "states",
            "counters",
            "screenshots",
        },
    )
    bounded(p, 4096)
    for k, x in {
        "schema_version": 1,
        "status": "passed",
        "mode": "local_scripted_p3_native_text",
        "session_id": session_id,
        "work_id": case["accepted"]["work_id"],
        "request_revision": 1,
        "input_fingerprint": case["request"]["input_fingerprint"],
        "groups": [{"name": n, "status": "passed"} for n in BROWSER_GROUPS],
        "useful_reply_sha256": "3be46c35bdf54d5f5a95618f8351476610050e5adcd5af9b3a8feac1c96e62a7",
        "screenshots": list(SCREENSHOTS),
    }.items():
        same(p[k], x)
    if type(p["final_reply_observed"]) is not bool:
        fail()
    states = keys(p["states"], {"held", "outdated", "failed", "recovered", "forgotten"})
    same(states["held"], {"state": "work", "owned_run": True, "result_observed": False})
    o = case["observation"]
    r = o["result"]
    same(
        states["outdated"],
        {
            "state": "outdated",
            "result_sha256": r["sha256"],
            "attempt_id": r["attempt_id"],
            "disposition": r["disposition"],
            "applicability": "outdated",
        },
    )
    same(
        states["failed"],
        {"code": "unavailable", "historical": True, "original_facts_retained": True},
    )
    same(
        states["recovered"],
        {"state": "outdated", "result_sha256": r["sha256"], "historical": False},
    )
    same(
        states["forgotten"],
        {
            "owned_client": 0,
            "actual_requests": 0,
            "actual_sends": 0,
            "cleanup_complete": True,
            "private_facts_cleared": True,
            "password_empty": True,
            "composer_empty": True,
        },
    )
    counters = keys(
        p["counters"],
        {"browser_read_requests", "fixture_read_interceptions", "page_errors", "external_requests"},
    )
    natural(counters["browser_read_requests"], 16, 4)
    same(counters["fixture_read_interceptions"], 1)
    same(counters["page_errors"], 0)
    same(counters["external_requests"], 0)
    return p


@proof_boundary
def validate_inventory(
    value: object, cases: dict[str, dict[str, Any]], context: dict[str, Any], scope: dict[str, str]
) -> dict[str, Any]:
    v = keys(value, {"work", "case"})
    w = v["work"]
    c = v["case"]
    if type(w) is not dict or type(c) is not dict or set(cases) != set(LABELS):
        fail()
    required = set(durable.OWNER_TABLES) | {"result_feed_heads", "admission", "execution_limits"}
    if set(w) != required:
        fail()
    for rows in (*w.values(), *c.values()):
        if type(rows) is not list or len(rows) > 128 or any(type(r) is not dict for r in rows):
            fail()
    for name in ("accepted_work", "issued_attempts", "attempt_results", "result_feed_events"):
        same(len(w[name]), 4)
    for name in (
        "cancellation_commands",
        "result_actions",
        "result_delivery_intents",
        "result_delivery_possible",
        "result_delivery_receipts",
    ):
        same(w[name], [])
    same(len(w["result_feed_source"]), 1)
    same(len(w["result_feed_heads"]), 1)
    same(len(w["schema_metadata"]), 1)
    same(w["schema_metadata"][0]["version"], 4)
    uuid(w["result_feed_source"][0]["source_id"])
    same(w["result_feed_source"][0]["singleton"], True)
    natural(w["result_feed_source"][0]["adopted_at_ms"])
    head = keys(
        w["result_feed_heads"][0], {"tenant_id", "account_id", "anchor_work_id", "last_sequence"}
    )
    same(head["tenant_id"], scope["tenant_id"])
    same(head["account_id"], scope["account_id"])
    same(head["last_sequence"], 4)
    if head["anchor_work_id"] not in {p["accepted"]["work_id"] for p in cases.values()}:
        fail()
    same(w["schema_metadata"][0]["max_records"], 16)
    same(w["schema_metadata"][0]["max_cancel_commands"], 16)
    same(w["admission"], [{"singleton": True, "record_count": 4, "cancel_count": 0}])
    same(
        w["execution_limits"],
        [{"singleton": True, "max_active": 4, "max_attempts": 3, "lease_ms": 10000}],
    )
    same(len(c.get("cases", [])), 2)
    same(len(c.get("tasks", [])), 2)
    fixed = [
        r for r in c["cases"] if r["case_id"] == cases["native_stale"]["case_after"]["case_id"]
    ]
    if len(fixed) != 1:
        fail()
    same(fixed[0]["revision"], 2)
    same(fixed[0]["cancelled"], False)
    cancelled = [r for r in c["cases"] if r["case_id"] != fixed[0]["case_id"]]
    if len(cancelled) != 1:
        fail()
    same(cancelled[0]["revision"], 1)
    same(cancelled[0]["cancelled"], True)

    def one(name: str, field: str, expected: object) -> dict[str, Any]:
        found = [r for r in w[name] if r.get(field) == expected]
        if len(found) != 1:
            fail()
        return cast(dict[str, Any], found[0])

    def body(v: object) -> bytes:
        if type(v) is not str or not v.startswith("\\x"):
            fail()
        try:
            return bytes.fromhex(v[2:])
        except ValueError:
            fail()

    records = []
    for label in LABELS:
        p = cases[label]
        a = p["accepted"]
        g = p["issued"]
        r = p["stored_result"]
        row = one("accepted_work", "work_id", a["work_id"])
        grant = one("issued_attempts", "attempt_id", g["attempt_id"])
        result = one("attempt_results", "attempt_id", g["attempt_id"])
        event = one("result_feed_events", "attempt_id", g["attempt_id"])
        for item in (row, grant, result, event):
            same(item["tenant_id"], scope["tenant_id"])
            same(item["account_id"], scope["account_id"])
            same(item["work_id"], a["work_id"])
        for k, x in {
            "idempotency_key": label,
            "operation": "booking.evaluate_policy",
            "sha256": a["payload"]["sha256"],
            "deadline_at_ms": p["request"]["deadline_at_ms"],
            "accepted_at_ms": a["accepted_at_ms"],
        }.items():
            same(row[k], x)
        same(body(row["body"]), canonical(p["request"]))
        for k in (
            "attempt_id",
            "command_id",
            "number",
            "owner_id",
            "epoch",
            "issued_at_ms",
            "lease_until_ms",
        ):
            same(grant[k], g[k])
        same(grant["command_id"], context["cases"][label]["command_id"])
        same(grant["owner_id"], context["cases"][label]["owner_id"])
        same(body(result["body"]), canonical(r["body"]))
        for k in ("work_id", "attempt_id", "recorded_at_ms", "disposition", "sha256"):
            same(result[k], r[k])
        same(event["origin"], "live")
        uuid(event["event_id"])
        natural(event["sequence"], 4, 1)
        records.append(
            {
                "name": label,
                "work_id": a["work_id"],
                "attempt_id": g["attempt_id"],
                "request_sha256": row["sha256"],
                "result_sha256": result["sha256"],
                "feed_event_id": event["event_id"],
                "feed_sequence": event["sequence"],
                "source_id": w["result_feed_source"][0]["source_id"],
            }
        )
    for field in ("work_id", "attempt_id", "feed_event_id", "feed_sequence"):
        same(len({r[field] for r in records}), 4)
    return {
        "schema_version": 1,
        "kind": "native-policy.owner-joins",
        "records": records,
        "counts": {
            "work": 4,
            "attempts": 4,
            "results": 4,
            "feed": 4,
            "actions": 0,
            "delivery": 0,
            "work_cancellations": 0,
            "case_preparation_tasks": 2,
        },
        "table_names": {k: sorted(v[k]) for k in ("work", "case")},
    }


class NativePolicyRun(durable.DurableWorkRun):
    def __init__(self, root: Path, report: Path, *, installed: bool) -> None:
        super().__init__(root, report, installed=installed)
        self.case_directories = {name: self.directory / "cases" / name for name in LABELS}
        self.case_barriers: dict[tuple[str, str], FileBarrier] = {}
        for name, directory in self.case_directories.items():
            private_directory(directory)
            for marker in MARKERS:
                self.case_barriers[name, marker] = FileBarrier(directory, marker)
            for marker in ("native_policy_server_ready", "native_policy_held"):
                self.case_barriers[name, marker] = FileBarrier(directory, marker)
        self.native_node_fixture = root / NODE_FIXTURE
        self.native_python_fixture = root / PYTHON_FIXTURE
        self.browser_directory = self.work / "browser"
        private_directory(self.browser_directory)
        self.browser_groups = 0
        self.cases: dict[str, dict[str, Any]] = {}
        self.peers: dict[str, dict[str, Any]] = {}
        self.inputs_native: dict[str, dict[str, Any]] = {}
        self.native_context: dict[str, Any] = {}
        self.held: dict[str, dict[str, Any]] = {}
        self.browser: OwnedProcess | None = None
        self.async_runner = asyncio.Runner()
        self.async_tasks: set[asyncio.Task[Any]] = set()
        self.api_client: Any = None
        self.parent_ports: list[Any] = []
        self.room_name = "p3_native_" + uuid4().hex
        self.room_metadata = {"profile": "p3_native_policy_text_v1", "owner": uuid4().hex}
        self.room_attempted = self.room_cleaned = False
        self.cancelled_before: dict[str, Any] | None = None
        self.room_proof: dict[str, Any] = {}

    def start(
        self,
        argv: list[str | Path],
        *,
        stage: str,
        cwd: Path | None = None,
        environment: dict[str, str] | None = None,
        cleanup: bool = False,
    ) -> OwnedProcess:
        nested, captured, reserved = self.nested_usage()
        if stage not in STAGES or self.commands + nested >= MAX_CHILDREN:
            raise GateError("child_budget")
        self.remaining(cleanup=cleanup)
        env = environment or self.base
        validate_environment(env, stage)
        available = (
            MAX_CAPTURE - self.captured - captured - reserved - sum(self.reservations.values())
        )
        limit = min(MAX_STREAM, available // 2)
        if limit < 1 or not Path(argv[0]).is_absolute():
            raise GateError("child_budget")
        self.commands += 1
        self.stage = stage
        output = self.work / "raw-commands" / f"{self.commands:02d}-{stage}"
        private_directory(output.parent)
        child = GroupedOwnedProcess(
            [str(v) for v in argv],
            cwd=cwd or self.work,
            env=env,
            output_directory=output,
            max_output_bytes=limit,
            final_deadline=self.final_deadline,
        )
        self.children.append(child)
        self.outputs[child.pid] = output
        self.child_roles[child.pid] = stage
        self.reservations[child.pid] = 2 * limit
        return child

    def capture(self, child: OwnedProcess) -> tuple[bytes, bytes]:
        if self.child_roles[child.pid] != "browser":
            return super().capture(child)
        raw = tuple(
            read_private(self.outputs[child.pid] / n, MAX_STREAM, empty=True)
            for n in ("stdout.bin", "stderr.bin")
        )
        if any(token.encode() in stream for token in self.tokens for stream in raw):
            raise GateError("unsafe_capture")
        if type(child.returncode) is int and not child.cleanup_failed:
            key = digest(raw[0] + b"\0" + raw[1])
            versions = self.capture_versions.setdefault(child.pid, [])
            if key not in versions:
                if len(versions) >= 3:
                    raise GateError("retention_failed")
                target = (
                    self.retained
                    / "commands"
                    / (
                        self.outputs[child.pid].name
                        + ("" if not versions else "-cleanup-" + str(len(versions)))
                    )
                )
                write_private(
                    target / "capture-metadata.json",
                    common.json_bytes(
                        {
                            "schema_version": 1,
                            "retained_raw": False,
                            "streams": [{"bytes": len(x), "sha256": digest(x)} for x in raw],
                        }
                    ),
                )
                versions.append(key)
                self.captured += sum(map(len, raw))
            self.reservations.pop(child.pid, None)
            self.accounted.add(child.pid)
        if self.captured + self.nested_usage()[1] > MAX_CAPTURE:
            raise GateError("child_budget")
        return b"", b""

    def source_index(self) -> dict[str, str]:
        result = super().source_index()
        names = {
            NODE_FIXTURE,
            PYTHON_FIXTURE,
            "local-setup/scripts/p3_native_policy_check.py",
            "local-setup/scripts/p3_native_policy_http.py",
            "tests/test_p3_native_policy_gate.py",
            "tests/test_p3_native_policy_http.py",
            "projects/delegation-reliability/tests/test_native_policy.py",
            "projects/delegation-reliability/tests/test_native_policy_sdk.py",
            "tests/test_p3_native_policy_evidence.py",
            "tests/fixtures/p3-native-policy-proof-positive.json",
            "harness/process_control.py",
            CONSOLE + "/p3-background.html",
            CONSOLE + "/vite.p3-background.config.ts",
            CONSOLE + "/playwright.p3-background.config.ts",
            CONSOLE + "/e2e/p3-background.media.ts",
            CONSOLE + "/src/style.css",
            CONSOLE + "/tsconfig.json",
            CONSOLE + "/tsconfig.e2e.json",
        }
        names.update(
            p.relative_to(self.root).as_posix()
            for p in (self.root / CONSOLE / "src").glob("p3-background*")
            if p.is_file()
        )
        names.update(
            p.relative_to(self.root).as_posix()
            for p in (self.root / CONSOLE / "public/vendor/livekit").rglob("*")
            if p.is_file()
        )
        for name in names:
            path = self.root / name
            if not path.is_file() or path.is_symlink() or path.stat().st_size > 2097152:
                raise GateError("invalid_artifact")
            result[name] = digest(path.read_bytes())
        return dict(sorted(result.items()))

    def public_types(self) -> None:
        super().public_types()
        names = {
            NODE_FIXTURE,
            PYTHON_FIXTURE,
            "harness/process_control.py",
            "local-setup/scripts/p3_native_policy_http.py",
            "projects/delegation-reliability/examples/native_fixed_policy.py",
        }
        application = self.work / "application"
        for name in names:
            destination = application / name
            raw = (self.root / name).read_bytes()
            if destination.exists():
                same(read_private(destination, 2097152), raw)
            else:
                write_private(destination, raw)
        write_private(
            self.retained / "native-unadapted-copies.json",
            common.json_bytes({n: digest((self.root / n).read_bytes()) for n in sorted(names)}),
        )
        self.native_node_fixture, self.native_python_fixture = (
            application / NODE_FIXTURE,
            application / PYTHON_FIXTURE,
        )

    def prepare(self) -> None:
        super().prepare()
        assert self.node is not None
        assets = self.work / "built-ui"
        self.finish(
            self.start(
                [
                    self.node,
                    self.root / CONSOLE / "node_modules/vite/bin/vite.js",
                    "build",
                    "--config",
                    self.root / CONSOLE / "vite.p3-background.config.ts",
                    "--outDir",
                    assets,
                ],
                stage="ui-build",
                cwd=self.root / CONSOLE,
            )
        )
        if not assets.is_dir() or assets.is_symlink():
            raise GateError("invalid_artifact")
        assets.chmod(0o700)
        built: dict[str, dict[str, Any]] = {}
        for path in assets.rglob("*"):
            if path.is_symlink():
                raise GateError("invalid_artifact")
            if path.is_dir():
                path.chmod(0o700)
            elif path.is_file():
                path.chmod(0o600)
                raw = read_private(path, 2097152, empty=True)
                built[path.relative_to(assets).as_posix()] = {
                    "bytes": len(raw),
                    "sha256": digest(raw),
                }
            else:
                raise GateError("invalid_artifact")
        if (
            "p3-background.html" not in built
            or len(built) > 128
            or sum(v["bytes"] for v in built.values()) > 8388608
        ):
            raise GateError("invalid_artifact")
        write_private(self.retained / "built-ui.json", common.json_bytes(built))
        spec = importlib.util.spec_from_file_location(
            "native_parent_ordinary_settings", self.root / "local-setup/stack.py"
        )
        if spec is None or spec.loader is None:
            raise GateError("missing_setup")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
            settings = module.load_settings()
        finally:
            sys.modules.pop(spec.name, None)
        self.rtc_settings = {
            k: settings[k] for k in ("LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "LIVEKIT_HTTP_PORT")
        }
        self.tokens = (
            *self.tokens,
            self.rtc_settings["LIVEKIT_API_KEY"],
            self.rtc_settings["LIVEKIT_API_SECRET"],
        )
        rtc = self.setup_room()
        self.native_context = {
            "schema_version": 1,
            "installed": self.installed,
            "cases": {
                n: {"owner_id": str(uuid4()), "command_id": "native_command_" + n} for n in LABELS
            },
            "node_token": self.tokens[1],
            "operator_token": self.tokens[2],
            "rtc": rtc,
            "assets": str(assets),
        }
        write_private(
            self.directory / "native-policy-runtime.json", canonical(self.native_context) + b"\n"
        )
        write_private(
            self.retained / "native-allocation.json",
            common.json_bytes(
                {
                    "schema_version": 1,
                    "cases": self.native_context["cases"],
                    "room": self.room_name,
                    "room_metadata": self.room_metadata,
                    "session_id": rtc["session_id"],
                    "participant_identity": rtc["participant_identity"],
                    "agent_identity": rtc["agent_identity"],
                }
            ),
        )

    def async_call(self, invoke: Callable[[], Awaitable[T]], *, cleanup: bool = False) -> T:
        async def observe() -> T:
            async def owned() -> T:
                return await invoke()

            task: asyncio.Task[T] = asyncio.create_task(owned())
            self.async_tasks.add(task)
            task.add_done_callback(lambda value: None if value.cancelled() else value.exception())
            done, _ = await asyncio.wait({task}, timeout=min(5, self.remaining(cleanup=cleanup)))
            if not done:
                raise GateError("cleanup_incomplete" if cleanup else "deadline_exceeded")
            self.async_tasks.discard(task)
            return await task

        return self.async_runner.run(observe())

    def setup_room(self) -> dict[str, Any]:
        import aiohttp
        from livekit import api

        async def setup() -> None:
            self.api_client = api.LiveKitAPI(
                url="http://127.0.0.1:" + self.rtc_settings["LIVEKIT_HTTP_PORT"],
                api_key=self.rtc_settings["LIVEKIT_API_KEY"],
                api_secret=self.rtc_settings["LIVEKIT_API_SECRET"],
                timeout=aiohttp.ClientTimeout(total=3),
                failover=False,
            )
            before = await self.api_client.room.list_rooms(
                api.ListRoomsRequest(names=[self.room_name])
            )
            if before.rooms:
                raise GateError("invalid_proof")
            self.room_attempted = True
            room = await self.api_client.room.create_room(
                api.CreateRoomRequest(
                    name=self.room_name,
                    empty_timeout=180,
                    departure_timeout=10,
                    max_participants=2,
                    metadata=json.dumps(self.room_metadata, sort_keys=True, separators=(",", ":")),
                )
            )
            if room.name != self.room_name or json.loads(room.metadata) != self.room_metadata:
                raise GateError("invalid_proof")
            self.room_proof = {
                "schema_version": 1,
                "name": room.name,
                "sid": room.sid,
                "metadata": self.room_metadata,
                "absent_before_create": True,
            }

        self.stage = "room"
        self.async_call(setup)
        ttl = 180 if not self.installed else 360
        result = {
            "schema_version": 1,
            "kind": "native-policy.session",
            "session_id": str(uuid4()),
            "server_url": "ws://127.0.0.1:" + self.rtc_settings["LIVEKIT_HTTP_PORT"],
            "room_name": self.room_name,
            "participant_identity": "p3_viewer_" + uuid4().hex,
            "agent_identity": "p3_agent_" + uuid4().hex,
            "profile": "p3_native_policy_text_v1",
            "inference_mode": "scripted",
            "expires_at_ms": time.time_ns() // 1000000 + ttl * 1000,
        }
        for name, identity, kind in [
            ("rtc_token", result["participant_identity"], "standard"),
            ("agent_token", result["agent_identity"], "agent"),
        ]:
            token = (
                api.AccessToken(
                    self.rtc_settings["LIVEKIT_API_KEY"], self.rtc_settings["LIVEKIT_API_SECRET"]
                )
                .with_identity(identity)
                .with_kind(cast(Literal["standard", "agent"], kind))
                .with_ttl(timedelta(seconds=ttl))
                .with_grants(
                    api.VideoGrants(
                        room_join=True,
                        room=self.room_name,
                        can_publish=False,
                        can_subscribe=True,
                        can_publish_data=True,
                        can_update_own_metadata=kind == "agent",
                        can_manage_agent_session=False,
                    )
                )
                .to_jwt()
            )
            result[name] = token
            self.tokens = (*self.tokens, token)
        result["expires_at_ms"] = (
            json.loads(base64.urlsafe_b64decode(result["rtc_token"].split(".")[1] + "=="))["exp"]
            * 1000
        )
        write_private(self.retained / "room-owner.json", common.json_bytes(self.room_proof))
        return result

    def native_environment(self, role: str, *, label: str = "") -> dict[str, str]:
        env = {k: v for k, v in self.base.items() if k in durable.BASE_KEYS}
        if role == "node-server":
            env.update(
                P3_NATIVE_DIRECTORY=str(self.case_directories[label]),
                P3_NATIVE_TOKEN=self.tokens[1],
            )
        elif role == "native-consumer":
            return self.fixture_environment("exercise")
        else:
            raise GateError("invalid_environment")
        validate_environment(env, role)
        return env

    def barrier(self, child: OwnedProcess, label: str, name: str, *, release: bool = False) -> None:
        marker = self.case_barriers[label, name]
        try:
            if release:
                child.release_barrier(marker)
            else:
                child.wait_for_barrier(marker, timeout=min(20, self.remaining()))
        except BaseException:
            self.parent_context = {
                "operation": "release" if release else "wait",
                "stage": self.child_roles[child.pid],
                "barrier": name,
                "case": label,
                "pid": child.pid,
                "returncode": child.returncode,
            }
            raise

    def wait_file(self, child: OwnedProcess, path: Path, maximum: int) -> bytes:
        end = time.monotonic() + min(15, self.remaining())
        while True:
            self.remaining()
            if path.exists():
                info = path.lstat()
                if info.st_nlink == 1:
                    return read_private(path, maximum)
                if (
                    info.st_nlink != 2
                    or not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600
                ):
                    raise GateError("unsafe_path")
            if child.returncode is not None or time.monotonic() >= end:
                raise GateError("component_failed")
            time.sleep(0.002)

    def held_state(self, label: str) -> dict[str, Any]:
        from psycopg import sql

        with closing(
            self.owner_settings().connect(application_name="continuity-test")
        ) as connection:
            rows = connection.execute(
                sql.SQL(
                    "SELECT w.work_id,w.sha256,w.body,a.attempt_id,a.owner_id,a.command_id FROM {}.accepted_work w JOIN {}.issued_attempts a USING(tenant_id,account_id,work_id) WHERE w.idempotency_key=%s AND w.tenant_id=%s AND w.account_id=%s"
                ).format(
                    sql.Identifier(self.schemas["work"]), sql.Identifier(self.schemas["work"])
                ),
                (label, self.scope["tenant_id"], self.scope["account_id"]),
            ).fetchall()
            if len(rows) != 1:
                fail()
            row = rows[0]
            absent = connection.execute(
                sql.SQL("SELECT attempt_id FROM {}.attempt_results WHERE work_id=%s").format(
                    sql.Identifier(self.schemas["work"])
                ),
                (row["work_id"],),
            ).fetchall()
            if absent:
                fail()
            same(row["owner_id"].__str__(), self.native_context["cases"][label]["owner_id"])
            same(row["command_id"], self.native_context["cases"][label]["command_id"])
            return {
                "work_id": str(row["work_id"]),
                "attempt_id": str(row["attempt_id"]),
                "request_sha256": row["sha256"],
                "request": json.loads(bytes(row["body"])),
                "no_result": True,
            }

    def cancelled_case(self) -> dict[str, Any]:
        from psycopg import sql

        state = common.decode(read_private(self.directory / "fixed-work-cases.json"))
        with closing(
            self.owner_settings("case").connect(application_name="continuity-test")
        ) as connection:
            rows = connection.execute(
                sql.SQL("SELECT to_jsonb(t)::text AS body FROM {}.cases t WHERE case_id=%s").format(
                    sql.Identifier(self.schemas["case"])
                ),
                (state["case_cancelled"]["case_id"],),
            ).fetchall()
            if len(rows) != 1:
                fail()
            return cast(dict[str, Any], json.loads(rows[0]["body"]))

    def public_case(self, *, advance: bool = False) -> dict[str, Any]:
        from datetime import date

        from continuity_lab.case_control_api import BookingChange, open_case_control_client
        from continuity_lab.postgres_api import AuthenticatedActor, open_postgres_client
        from continuity_lab.work_api import BearerToken, PostgresSettings

        state = common.decode(read_private(self.directory / "fixed-work-cases.json"))

        async def read() -> dict[str, Any]:
            settings = PostgresSettings(
                port=int(self.lab_settings["POSTGRES_PORT"]),
                user="livekit_lab",
                password=self.lab_settings["POSTGRES_PASSWORD"],
                schema=self.schemas["case"],
            )
            args: dict[str, Any] = {
                "actor": AuthenticatedActor("p3_completion_user", "p3_completion_scope"),
                "token": BearerToken(self.tokens[0]),
                "settings": settings,
                "quote_database": self.directory / "supplier.sqlite3",
            }
            reader = await asyncio.to_thread(open_postgres_client, **args)
            self.parent_ports.append(reader)
            control = None
            primary: BaseException | None = None
            try:
                before = (
                    await reader.get(task_id=state["case_fixed"]["task_id"], limit=10)
                ).payload()
                if not advance:
                    return before
                same(before["case_revision"], "1")
                control = await asyncio.to_thread(open_case_control_client, **args)
                self.parent_ports.append(control)
                changed = await control.revise(
                    task_id=state["case_fixed"]["task_id"],
                    expected_revision=1,
                    request=BookingChange("DEMO-BK-001", date(2030, 12, 12), True),
                )
                same(changed.revision, 2)
                after = (
                    await reader.get(task_id=state["case_fixed"]["task_id"], limit=10)
                ).payload()
                same(after["case_revision"], "2")
                return {"schema_version": 1, "before": before, "after": after}
            except BaseException as error:
                primary = error
                raise
            finally:

                async def close_port(port: Any) -> None:
                    await port.close()

                outcomes = await asyncio.gather(
                    close_port(reader),
                    *([close_port(control)] if control is not None else []),
                    return_exceptions=True,
                )
                if any(isinstance(x, BaseException) for x in outcomes):
                    if primary is None:
                        raise GateError("cleanup_incomplete")
                else:
                    self.parent_ports.remove(reader)
                    if control is not None:
                        self.parent_ports.remove(control)

        return self.async_call(read)

    def browser_marker(self, filename: str, label: str, stage: str, revision: str) -> None:
        held = self.held[label]
        q = held["request"]
        if filename not in BROWSER_MARKERS:
            raise GateError("unsafe_path")
        publish_browser_marker(
            self.browser_directory / filename,
            canonical(
                {
                    "schema_version": 1,
                    "stage": stage,
                    "session_id": self.native_context["rtc"]["session_id"],
                    "work_id": held["work_id"],
                    "request_revision": q["request_revision"],
                    "input_fingerprint": q["input_fingerprint"],
                    "observed_case_revision": revision,
                }
            )
            + b"\n",
        )

    def stale(self, client: OwnedProcess, server: OwnedProcess, label: str) -> None:
        self.barrier(client, label, "native_ui_ready")
        endpoint = keys(
            common.decode(
                read_private(self.case_directories[label] / "native-policy-ui-endpoint.json")
            ),
            {"schema_version", "origin", "session_id"},
        )
        same(endpoint["schema_version"], 1)
        same(endpoint["session_id"], self.native_context["rtc"]["session_id"])
        env = {k: v for k, v in self.base.items() if k in durable.BASE_KEYS}
        env.update(
            P3_NATIVE_BROWSER_ORIGIN=endpoint["origin"],
            P3_NATIVE_BROWSER_OUTPUT=str(self.browser_directory),
            P3_NATIVE_BROWSER_ACCESS=self.tokens[2],
        )
        assert self.node is not None
        self.browser = self.start(
            [
                self.node,
                self.root / CONSOLE / "node_modules/@playwright/test/cli.js",
                "test",
                "--config",
                self.root / CONSOLE / "playwright.p3-background.config.ts",
            ],
            stage="browser",
            cwd=self.root / CONSOLE,
            environment=env,
        )
        self.barrier(client, label, "native_ui_ready", release=True)
        self.barrier(server, label, "native_policy_held")
        self.held[label] = self.held_state(label)
        self.browser_marker("parent-peer-held.json", label, "peer_held", "1")
        follow = keys(
            common.decode(
                self.wait_file(
                    self.browser, self.browser_directory / "browser-followup-observed.json", 4096
                )
            ),
            {
                "schema_version",
                "stage",
                "session_id",
                "work_id",
                "request_revision",
                "input_fingerprint",
                "useful_reply_sha256",
                "no_result",
            },
        )
        for k, x in {
            "schema_version": 1,
            "stage": "held_followup_observed",
            "session_id": self.native_context["rtc"]["session_id"],
            "work_id": self.held[label]["work_id"],
            "request_revision": 1,
            "input_fingerprint": self.held[label]["request"]["input_fingerprint"],
            "useful_reply_sha256": "3be46c35bdf54d5f5a95618f8351476610050e5adcd5af9b3a8feac1c96e62a7",
            "no_result": True,
        }.items():
            same(follow[k], x)
        same(self.held_state(label), self.held[label])
        self.cancelled_before = self.cancelled_case()
        self.stage = "owner-advance"
        advanced = self.public_case(advance=True)
        write_private(self.retained / "proofs/case-advance.json", common.json_bytes(advanced))
        self.browser_marker("parent-case-advanced.json", label, "case_advanced", "2")
        self.barrier(server, label, "native_policy_held", release=True)
        self.browser_marker("parent-result-released.json", label, "specialist_released", "2")
        self.finish(self.browser)
        self.barrier(client, label, "native_browser_finished")
        self.barrier(client, label, "native_browser_finished", release=True)

    def journey(self) -> None:
        self.lab_started = True
        self.python_mode("install")
        self.supplier_before, inquiry, applied = self.supplier()
        if inquiry or applied:
            fail()
        client = self.start(
            [self.client_python, "-I", self.native_python_fixture, "run"],
            stage="native-consumer",
            environment=self.native_environment("native-consumer"),
        )
        assert self.node is not None
        for label in LABELS:
            self.barrier(client, label, "native_node_ready")
            directory = self.case_directories[label]
            input_raw = read_private(directory / "native-policy-input.json", 131072)
            input_value = keys(
                common.decode(input_raw, 131072),
                {"schema_version", "owner_id", "request_utf8", "evidence"},
            )
            same(input_value["schema_version"], 1)
            same(input_value["owner_id"], self.native_context["cases"][label]["owner_id"])
            known = next(c for c in self.enrollment["cases"] if c["label"] == "known")
            request = common.decode(input_value["request_utf8"].encode(), 16384)
            same(canonical(request).decode(), input_value["request_utf8"])
            same(request["scope"], self.scope)
            same(request["context_snapshot"], known["context_snapshot"])
            same(request["evidence"], known["evidence"])
            same(request["result_route"], {"conversation_id": "conversation_" + label})
            same(request["attempt"], {"attempt_id": "proposal_" + label, "number": 1})
            expected_sources = [
                r
                for ref in known["evidence"]
                for r in self.enrollment["records"]
                if r["reference"] == ref and r["scope"] == self.scope
            ]
            same(input_value["evidence"], expected_sources)
            self.inputs_native[label] = input_value
            # Preserve the exact validated, token-free template before its peer can fail.
            self.retain(
                self.retained / "proofs" / label / "native-policy-input.json", input_raw, 131072
            )
            server = self.start(
                [self.node, self.native_node_fixture, "serve"],
                stage="node-server",
                environment=self.native_environment("node-server", label=label),
            )
            self.barrier(server, label, "native_policy_server_ready")
            endpoint = keys(
                common.decode(read_private(directory / "native-policy-endpoint.json")),
                {
                    "schema_version",
                    "kind",
                    "endpoint",
                    "owner_id",
                    "input_sha256",
                    "template_sha256",
                },
            )
            for k, x in {
                "schema_version": 1,
                "kind": "native-policy.endpoint",
                "owner_id": input_value["owner_id"],
                "input_sha256": digest(input_raw),
                "template_sha256": digest(input_value["request_utf8"].encode()),
            }.items():
                same(endpoint[k], x)
            ep = keys(endpoint["endpoint"], {"host", "port"})
            same(ep["host"], "127.0.0.1")
            natural(ep["port"], 65535, 1)
            self.barrier(client, label, "native_node_ready", release=True)
            if label == "native_stale":
                self.stale(client, server, label)
            else:
                self.barrier(server, label, "native_policy_held")
                self.held[label] = self.held_state(label)
                self.barrier(
                    client,
                    label,
                    "native_retained_ready" if label == "native_retained" else "native_followup",
                )
                same(self.held_state(label), self.held[label])
                self.barrier(server, label, "native_policy_held", release=True)
                self.barrier(
                    client,
                    label,
                    "native_retained_ready" if label == "native_retained" else "native_followup",
                    release=True,
                )
            self.barrier(client, label, "native_case_done")
            stop = directory / "native-policy-server.stop"
            FileBarrier._write_pid(stop, server.pid)
            reply = common.decode(self.finish(server))
            peer_raw = read_private(directory / "native-policy-peer.json", MAX_PROOF)
            same(
                reply,
                {
                    "schema_version": 1,
                    "status": "passed",
                    "mode": "serve",
                    "node_version": "24.22.2",
                    "peer_sha256": digest(peer_raw),
                    "cleanup_complete": True,
                },
            )
            peer = validate_peer(
                common.decode(peer_raw, MAX_PROOF), input_value, owner_id=input_value["owner_id"]
            )
            proof_raw = read_private(directory / "case-proof.json", MAX_PROOF)
            proof = validate_case(
                common.decode(proof_raw, MAX_PROOF),
                peer,
                input_value,
                label=label,
                **self.native_context["cases"][label],
            )
            same(proof["case_after"], self.public_case())
            self.peers[label] = peer
            self.cases[label] = proof
            for name, raw in [
                ("native-policy-peer.json", peer_raw),
                ("case-proof.json", proof_raw),
                (
                    "native-policy-endpoint.json",
                    read_private(directory / "native-policy-endpoint.json"),
                ),
            ]:
                self.retain(self.retained / "proofs" / label / name, raw, 131072)
            self.barrier(client, label, "native_case_done", release=True)
        reply_raw = self.finish(client)
        reply = keys(
            common.decode(reply_raw),
            {
                "schema_version",
                "kind",
                "status",
                "cases",
                "installed_prefix_verified",
                "shared_case_closed",
                "cleanup_complete",
            },
        )
        same(
            read_private(self.directory / "native-policy-consumer-proof.json"),
            reply_raw if reply_raw.endswith(b"\n") else reply_raw + b"\n",
        )
        for k, x in {
            "schema_version": 1,
            "kind": "native-policy.consumer",
            "status": "passed",
            "installed_prefix_verified": self.installed,
            "shared_case_closed": True,
            "cleanup_complete": True,
        }.items():
            same(reply[k], x)
        same(
            reply["cases"],
            [
                {
                    "name": n,
                    "path": "cases/" + n + "/case-proof.json",
                    "bytes": len(
                        read_private(self.case_directories[n] / "case-proof.json", MAX_PROOF)
                    ),
                    "sha256": digest(
                        read_private(self.case_directories[n] / "case-proof.json", MAX_PROOF)
                    ),
                }
                for n in LABELS
            ],
        )
        self.retain(
            self.retained / "proofs/native-policy-consumer-proof.json",
            read_private(self.directory / "native-policy-consumer-proof.json"),
        )
        self.stage = "proof"
        self.verify_native()
        self.passed.update(CASES[:-1])
        after = self.source_index()
        same(after, self.before)
        write_private(self.retained / "source-after.json", common.json_bytes(after))

    def retain(self, target: Path, raw: bytes, maximum: int = MAX_PROOF) -> None:
        if len(raw) > maximum or any(t.encode() in raw for t in self.tokens):
            raise GateError("unsafe_capture")
        write_private(target, raw)

    def inventory(self) -> dict[str, Any]:
        from psycopg import sql

        result = {}
        for kind in ("work", "case"):
            settings = self.owner_settings(kind)
            with closing(settings.connect(application_name="continuity-test")) as connection:
                identity = connection.execute(
                    "SELECT pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname=%s",
                    (settings.schema,),
                ).fetchone()
                if identity is None or identity["owner"] != "continuity_migrator":
                    fail()
                tables = connection.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename",
                    (settings.schema,),
                ).fetchall()
                if not 1 <= len(tables) <= 64:
                    fail()
                rows = {}
                for table in tables:
                    self.remaining()
                    data = connection.execute(
                        sql.SQL(
                            "SELECT to_jsonb(t)::text AS body FROM {}.{} t ORDER BY to_jsonb(t)::text LIMIT 129"
                        ).format(
                            sql.Identifier(settings.schema), sql.Identifier(table["tablename"])
                        )
                    ).fetchall()
                    if len(data) > 128:
                        fail()
                    rows[table["tablename"]] = [json.loads(x["body"]) for x in data]
                result[kind] = rows
        bounded(result, 1048576)
        return result

    def verify_native(self) -> None:
        inventory = self.inventory()
        if self.cancelled_before is None:
            fail()
        same(self.cancelled_case(), self.cancelled_before)
        joined = validate_inventory(inventory, self.cases, self.native_context, self.scope)
        same(self.supplier(), (self.supplier_before, 0, 0))
        browser_raw = read_private(self.browser_directory / "browser-proof.json", 4096)
        validate_browser(
            common.decode(browser_raw, 4096),
            self.cases["native_stale"],
            session_id=self.native_context["rtc"]["session_id"],
        )
        same(
            self.cases["native_stale"]["ownership"]["room_io"]["participant_identity"],
            self.native_context["rtc"]["participant_identity"],
        )
        self.retain(
            self.retained / "proofs/owner-inventory.json", common.json_bytes(inventory), 1048576
        )
        self.retain(self.retained / "proofs/owner-joins.json", common.json_bytes(joined))
        self.retain(self.retained / "proofs/browser-proof.json", browser_raw)
        for name in (*BROWSER_MARKERS, "browser-followup-observed.json"):
            self.retain(
                self.retained / "proofs/browser" / name,
                read_private(self.browser_directory / name, 4096),
                4096,
            )
        for name in SCREENSHOTS:
            raw = read_private(self.browser_directory / name, 2097152)
            if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                fail()
            self.retain(self.retained / "screenshots" / name, raw, 2097152)
        self.retain_browser_context(self.retained / "proofs/browser-context.json")
        self.browser_groups = 3

    def close_processes(self) -> None:
        primary: BaseException | None = None
        end = min(self.final_deadline, time.monotonic() + 20)
        for child in reversed(self.children):
            try:
                # finish() already closed and captured accounted handles; their
                # selectors are closed. Drain only an exited, unaccounted child.
                if child.returncode is not None and child.pid not in self.accounted:
                    child.wait(timeout=max(0.001, end - time.monotonic()))
            except BaseException as error:  # noqa: BLE001 - Preserve primary while every actual owner receives cleanup.
                if primary is None:
                    primary = error
            try:
                child.close()
                self.capture(child)
            except BaseException as error:  # noqa: BLE001 - Preserve primary while every actual owner receives cleanup.
                if primary is None:
                    primary = error
        if primary is not None:
            raise primary

    def cleanup_lab(self) -> None:
        if not self.children_settled() or not self.nested_cleanup_known:
            raise GateError("cleanup_incomplete")
        from livekit import api

        async def cleanup() -> None:
            pending = {
                t for t in self.async_tasks if not t.done() and t is not asyncio.current_task()
            }
            if pending:
                _, pending = await asyncio.wait(
                    pending, timeout=min(3, self.remaining(cleanup=True))
                )
                if pending:
                    raise GateError("cleanup_incomplete")
            self.async_tasks.clear()
            if self.parent_ports:
                results = await asyncio.gather(
                    *(p.close() for p in self.parent_ports), return_exceptions=True
                )
                if any(isinstance(x, BaseException) for x in results):
                    raise GateError("cleanup_incomplete")
                self.parent_ports.clear()
            if self.api_client is not None:
                if self.room_attempted:
                    rooms = await self.api_client.room.list_rooms(
                        api.ListRoomsRequest(names=[self.room_name])
                    )
                    for room in rooms.rooms:
                        if (
                            room.name != self.room_name
                            or json.loads(room.metadata) != self.room_metadata
                        ):
                            raise GateError("cleanup_incomplete")
                        if self.room_proof and room.sid != self.room_proof["sid"]:
                            raise GateError("cleanup_incomplete")
                        await self.api_client.room.delete_room(
                            api.DeleteRoomRequest(room=room.name)
                        )
                    if (
                        await self.api_client.room.list_rooms(
                            api.ListRoomsRequest(names=[self.room_name])
                        )
                    ).rooms:
                        raise GateError("cleanup_incomplete")
                await self.api_client.aclose()
                self.api_client = None
            self.room_cleaned = True

        if not self.room_cleaned:
            self.async_call(cleanup, cleanup=True)
        if self.async_tasks or self.parent_ports or self.api_client is not None:
            raise GateError("cleanup_incomplete")
        self.async_runner.close()
        target = self.retained / "room-cleanup.json"
        if not target.exists():
            write_private(
                target,
                common.json_bytes(
                    {
                        "schema_version": 1,
                        "name": self.room_name,
                        "metadata": self.room_metadata,
                        "possible_create": self.room_attempted,
                        "absent_after_cleanup": True,
                        "api_closed": True,
                    }
                ),
            )
        super().cleanup_lab()

    def remove_work(self) -> None:
        if (
            not self.room_cleaned
            or self.async_tasks
            or self.parent_ports
            or self.api_client is not None
            or not self.nested_cleanup_known
        ):
            self.retain_unresolved_work()
            raise GateError("cleanup_incomplete")
        super().remove_work()

    def retain_browser_context(self, target: Path) -> None:
        source = self.browser_directory / "browser-context.json"
        if not source.exists() or target.exists():
            return
        raw = read_private(source, 4096)
        v = keys(
            common.decode(raw, 4096),
            {
                "schema_version",
                "status",
                "stage",
                "phase",
                "code",
                "owned_client",
                "actual_requests",
                "cleanup_complete",
                "page_errors",
                "external_requests",
            },
        )
        same(v["schema_version"], 1)
        if v["status"] not in {"passed", "failed"} or v["stage"] not in {
            "opening",
            "held_followup",
            "outdated_result",
            "read_recovery",
            "forget",
            "complete",
        }:
            fail()
        if v["phase"] is not None and v["phase"] not in {
            "idle",
            "joining",
            "connected",
            "reconnecting",
            "ending",
            "cleanup_incomplete",
            "disconnected",
        }:
            fail()
        if v["code"] is not None and v["code"] not in {
            "invalid",
            "access_denied",
            "unavailable",
            "unknown",
            "overloaded",
            "closed",
            "cleanup_incomplete",
        }:
            fail()
        for name in ("owned_client", "actual_requests"):
            if v[name] is not None:
                natural(v[name], 1)
        if type(v["cleanup_complete"]) is not bool:
            fail()
        natural(v["page_errors"], 1000)
        natural(v["external_requests"], 1000)
        self.retain(target, raw, 4096)

    def retain_failure_inputs(self) -> None:
        for directory in self.case_directories.values():
            for name in (
                "case-proof.json",
                "native-policy-peer.json",
                "native-policy-node-failure.json",
                "native-policy-endpoint.json",
            ):
                source = directory / name
                target = self.retained / "failure-proofs" / directory.name / name
                if source.exists() and not target.exists():
                    try:
                        raw = read_private(source, MAX_PROOF)
                        common.decode(raw, MAX_PROOF)
                        if not any(t.encode() in raw for t in self.tokens):
                            write_private(target, raw)
                    except (GateError, OSError):
                        pass
        source = self.directory / "native-policy-consumer-failure.json"
        if source.exists():
            raw = read_private(source, 4096)
            if not any(t.encode() in raw for t in self.tokens):
                write_private(
                    self.retained / "failure-proofs/native-policy-consumer-failure.json", raw
                )
        try:
            self.retain_browser_context(self.retained / "failure-proofs/browser-context.json")
        except (GateError, OSError, KeyError, TypeError):
            pass
        self.retain_nested_failure()


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, '{"schema_version":1,"status":"failed","code":"invalid_input"}\n')


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--installed", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.plan:
        print(json.dumps(plan(installed=args.installed), sort_keys=True))
        return 0
    run: NativePolicyRun | None = None
    target: Path | None = None
    primary: GateError | None = None
    cleanup = False
    index_sha = None
    stage = "input"
    started = time.monotonic()
    try:
        target = target_path(
            root, args.report or Path(".local/validation/p3-native-policy/" + uuid4().hex + ".json")
        )
        private_directory(target.parent)
        run = NativePolicyRun(root, target, installed=args.installed)
        run.prepare()
        run.journey()
    except BaseException as error:  # noqa: BLE001 - Preserve primary while every actual owner receives cleanup.
        primary = durable._translate(error)
        if run is not None:
            stage = run.stage
            run.failed_mode = True
    if run is not None:
        try:
            run.cleanup_resources()
            cleanup = (
                run.nested_cleanup_known
                and run.children_settled()
                and not run.work.exists()
                and run.room_cleaned
                and (not run.lab_started or run.lab_cleaned)
            )
            if not cleanup:
                raise GateError("cleanup_incomplete")
        except BaseException as error:  # noqa: BLE001 - Preserve primary while every actual owner receives cleanup.
            if primary is None:
                primary = durable._translate(error)
                stage = "cleanup"
            run.retain_unresolved_work()
        try:
            write_private(
                run.retained / "owned-children.json",
                common.json_bytes(
                    {
                        "schema_version": 1,
                        "cleanup_complete": cleanup,
                        "children": [
                            {
                                "pid": c.pid,
                                "stage": run.child_roles[c.pid],
                                "returncode": c.returncode,
                                "cleanup_failed": c.cleanup_failed,
                                "group_settled": isinstance(c, GroupedOwnedProcess)
                                and c.group_settled,
                            }
                            for c in run.children
                        ],
                    }
                ),
            )
            if primary is not None:
                write_private(
                    run.retained / "failure-context.json",
                    common.json_bytes(
                        {
                            "schema_version": 1,
                            "status": "failed",
                            "code": primary.code,
                            "stage": stage,
                            "parent": run.parent_context,
                            "cleanup_complete": cleanup,
                        }
                    ),
                )
            files = [p for p in run.retained.rglob("*") if p.is_file()]
            if (
                len(files) > MAX_RETAINED_FILES
                or sum(p.stat().st_size for p in files) > MAX_RETAINED_BYTES
            ):
                raise GateError("retention_failed")
            for path in files:
                raw = read_private(path, 8388608, empty=True)
                if any(t.encode() in raw for t in run.tokens):
                    raise GateError("unsafe_capture")
            index_sha = run.retained_index()
            common.validate_manifest(
                run.retained, read_private(run.retained / "retained-index.json", 1048576)
            )
        except BaseException as error:  # noqa: BLE001 - Preserve primary while every actual owner receives cleanup.
            if primary is None:
                primary = durable._translate(error)
                stage = "proof"
    if run is not None and primary is None and cleanup:
        run.passed.add(CASES[-1])
    count = len(run.passed) if run is not None else 0
    if primary is None and (count != 12 or not cleanup):
        primary = GateError("component_failed")
    value = {
        "schema_version": 1,
        "status": "passed" if primary is None else "failed",
        "mode": "local_native_policy_installed" if args.installed else "local_native_policy_source",
        "tests": 12,
        "passed": count,
        "failures": int(primary is not None),
        "errors": 0,
        "skipped": 0,
        "duration_seconds": time.monotonic() - started,
        "child_commands": run.commands + run.nested_commands if run is not None else 0,
        "browser_groups": run.browser_groups if run is not None else 0,
        "package_assertions": 8 if run is not None and run.builder_report is not None else 0,
        "cleanup_complete": cleanup,
        "code": primary.code if primary is not None else "ok",
        "stage": stage if primary is not None else "complete",
        "retained_index_sha256": index_sha,
        "case_results": [{"name": n, "status": "passed"} for n in CASES[:count]],
    }
    raw = common.json_bytes(value)
    validated_report(raw)
    if target is not None:
        write_private(target, raw)
    sys.stdout.buffer.write(raw)
    return 0 if primary is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
