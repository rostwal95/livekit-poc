"""Opt-in fixed P2 workload observations; no provider, room allocation or production capacity claim."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import shutil
import stat
import sys
import tempfile
import time
import traceback
from contextlib import closing
from pathlib import Path
from typing import Any, Never
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import p2_native_check as native
import p2_rehydration_check as storage
import p2_rehydration_media_check as previous
import p3_coordinator_check as core
from p3_document_package import GroupedOwnedProcess

from harness.process_control import FileBarrier, OwnedProcess

GateError = native.GateError
MODE = "local_synthetic_p2_bounded_workload"
TOTAL_SECONDS, CLEANUP_SECONDS = 360, 20
MAX_CHILDREN, EXPECTED_CHILDREN = 32, 16
MAX_STREAM_BYTES, MAX_CAPTURE_BYTES = 8192, 524288
MAX_PROOF_BYTES, MAX_EVIDENCE_BYTES, MAX_REPORT_BYTES = 2097152, 16777216, 32768
CASE_NAMES = (
    "frozen_profile_catalog_and_roles",
    "steady_rate_exact_acceptance",
    "burst_http_preacceptance_rejection",
    "sql_pending_pool_and_waiter_bounds",
    "abandoned_http_request_late_committed_receipt",
    "changed_payload_conflict_under_load",
    "two_equal_text_messages_remain_distinct",
    "persisted_claim_capacity_across_gateways",
    "ignored_agent_cancellation_retains_capacity",
    "second_admitted_tenant_progress",
    "retained_limit_rejects_no_reclamation",
    "equal_replay_and_history_at_full_limit",
    "display_window_eviction_late_replay",
    "bounded_observer_outage_with_business_progress",
    "malformed_oversize_and_auth_rejection_under_load",
    "graceful_shutdown_dependent_close",
    "same_schema_fresh_process_restart",
    "original_prepared_operation_reconciliation",
    "dormant_0_64_256_1000_resource_observations",
    "every_dormant_receipt_inspectable_in_64_windows",
    "dormant_no_per_case_room_or_agent_allocation",
    "dormant_two_case_wakeup_progress",
    "populated_dump_restore_original_replay",
    "final_source_proof_roles_resource_cleanup",
)
MODES = (
    "install",
    "seed",
    "serve",
    "reopen",
    "dormant-wake",
    "verify",
    "drop",
    "restored-replay",
    "restored-verify",
    "cleanup",
)
OWNER_MODES = frozenset({"install", "verify", "drop", "restored-verify", "cleanup"})
COMMON = frozenset({"P2_WORKLOAD_DIRECTORY", "P2_WORKLOAD_RUN_ID", "P2_WORKLOAD_PG_PORT"})
NORMAL_COMMANDS = (
    "compile",
    "install",
    "seed",
    "serve",
    "reopen",
    "dormant-wake",
    "verify",
    "backup-container",
    "backup-directory",
    "backup-dump",
    "backup-copy",
    "backup-restore",
    "restored-replay",
    "restored-verify",
    "cleanup",
    "backup-remove",
)
STAGES: dict[str, dict[str, Any]] = {
    "install": {"schemas": 2, "storageVersion": 7, "completedGroups": [CASE_NAMES[0]]},
    "seed": {
        "dormantInputs": 1000,
        "capacityInputs": 0,
        "credentialWindows": 16,
        "completedGroups": list(CASE_NAMES[18:20]),
    },
    "serve": {
        "capacityInputs": 64,
        "operationAcceptances": 63,
        "abandonedCallers": 1,
        "preacceptanceRejected": 4,
        "completedGroups": list(CASE_NAMES[1:16]),
    },
    "reopen": {
        "capacityInputs": 64,
        "operationAcceptances": 64,
        "originalPreparedReconciled": True,
        "completedGroups": list(CASE_NAMES[16:18]),
    },
    "dormant-wake": {
        "dormantInputs": 1002,
        "wokenOriginalCases": 2,
        "operationAcceptances": 4,
        "completedGroups": [CASE_NAMES[21]],
    },
    "verify": {
        "schemas": 2,
        "capacityInputs": 64,
        "dormantInputs": 1002,
        "operationAcceptances": 68,
        "rolesSeparated": True,
        "completedGroups": [CASE_NAMES[23]],
    },
    "drop": {"ownedSchemasAbsent": True, "cleanupComplete": True, "completedGroups": []},
    "restored-replay": {
        "originalReceipts": 1066,
        "operationAcceptances": 68,
        "newOperationAcceptances": 0,
        "completedGroups": [CASE_NAMES[22]],
    },
    "restored-verify": {
        "schemas": 2,
        "capacityInputs": 64,
        "dormantInputs": 1002,
        "operationAcceptances": 68,
        "rolesSeparated": True,
        "completedGroups": [CASE_NAMES[22], CASE_NAMES[23]],
    },
    "cleanup": {"ownedSchemasAbsent": True, "cleanupComplete": True, "completedGroups": []},
}
PROOFS = (
    "workload-dormant-originals.json",
    "workload-dormant-resources.json",
    "workload-capacity-originals.json",
    "workload-capacity-resources.json",
    "workload-wake-originals.json",
    "workload-operations.json",
    "workload-owner-proof.json",
    "workload-restored-owner-proof.json",
    "workload-before-digests.json",
)
BARRIERS = (
    "workload_dormant_ready",
    "workload_burst_ready",
    "workload_burst_waiting",
    "workload_slow_held",
)


EXPECTED_MANIFEST: dict[str, Any] = {
    "activeSchedule": {
        "burstAccepted": 4,
        "burstPreacceptanceRejected": 4,
        "callerAbandoned": 1,
        "capfill": 40,
        "gatewayInstances": 2,
        "persistedClaimsPerSchema": 2,
        "retained": 64,
        "slow": 4,
        "steady": 16,
    },
    "bounds": {
        "captureBytes": 524288,
        "cleanupSeconds": 20,
        "directProofBytes": 2097152,
        "evidenceBytes": 16777216,
        "expectedChildren": 16,
        "maximumChildren": 32,
        "reportBytes": 32768,
        "streamBytes": 8192,
        "totalSeconds": 360,
    },
    "cases": [
        "frozen_profile_catalog_and_roles",
        "steady_rate_exact_acceptance",
        "burst_http_preacceptance_rejection",
        "sql_pending_pool_and_waiter_bounds",
        "abandoned_http_request_late_committed_receipt",
        "changed_payload_conflict_under_load",
        "two_equal_text_messages_remain_distinct",
        "persisted_claim_capacity_across_gateways",
        "ignored_agent_cancellation_retains_capacity",
        "second_admitted_tenant_progress",
        "retained_limit_rejects_no_reclamation",
        "equal_replay_and_history_at_full_limit",
        "display_window_eviction_late_replay",
        "bounded_observer_outage_with_business_progress",
        "malformed_oversize_and_auth_rejection_under_load",
        "graceful_shutdown_dependent_close",
        "same_schema_fresh_process_restart",
        "original_prepared_operation_reconciliation",
        "dormant_0_64_256_1000_resource_observations",
        "every_dormant_receipt_inspectable_in_64_windows",
        "dormant_no_per_case_room_or_agent_allocation",
        "dormant_two_case_wakeup_progress",
        "populated_dump_restore_original_replay",
        "final_source_proof_roles_resource_cleanup",
    ],
    "catalog": {
        "ownerDdlSha256": "4c386cd2a3719e85f3417a004520631109d7ebc7d20759f6f7e04b2ae31894a6",
        "storageVersion": 7,
        "tables": [
            "admission",
            "associations",
            "callback_admission",
            "callback_observations",
            "callback_settings",
            "challenges",
            "communication_settings",
            "conversations",
            "dispatch_attempts",
            "dispatch_plans",
            "dispatch_settings",
            "inbox",
            "native_bindings",
            "native_observations",
            "native_responses",
            "native_settings",
            "outbound_routes",
            "outbox_admission",
            "outbox_settings",
            "processing_intents",
            "reply_intents",
            "schema_metadata",
            "send_attempts",
            "send_operations",
            "send_policy_settings",
            "send_recovery_commands",
            "send_recovery_observations",
            "send_results",
            "sender_heads",
        ],
    },
    "dormantSchedule": {
        "conversations": 1000,
        "credentialWindows": 16,
        "finalDispatched": 4,
        "finalPending": 998,
        "finalRetained": 1002,
        "maximumCredentialWindow": 64,
        "tenants": 2,
        "wakeNewInputs": 2,
        "wakeOldInputs": 2,
    },
    "normalCommands": [
        "compile",
        "install",
        "seed",
        "serve",
        "reopen",
        "dormant-wake",
        "verify",
        "backup-container",
        "backup-directory",
        "backup-dump",
        "backup-copy",
        "backup-restore",
        "restored-replay",
        "restored-verify",
        "cleanup",
        "backup-remove",
    ],
    "performanceBudgets": {
        "acceptedAdmissionMaxMs": 5000,
        "eventLoopMaxMs": 1000,
        "nodeRssBytes": 536870912,
        "usefulCompletionMaxMs": 15000,
    },
    "populations": [0, 64, 256, 1000],
    "profile": "p2-bounded-v1",
    "profiles": {
        "capacity": {"maxAssociations": 4, "maxChallenges": 4, "maxInbox": 64, "maxSenders": 4},
        "dormant": {
            "maxAssociations": 1024,
            "maxChallenges": 1024,
            "maxInbox": 1024,
            "maxSenders": 1024,
        },
    },
    "resourceSemantics": {
        "activeGatewayInstances": 2,
        "aggregateConfiguredConnections": 8,
        "aggregateConfiguredSqlOperations": 16,
        "connectionsPerPool": 2,
        "defaultServiceChanges": False,
        "dispatcherTasksPerInstance": 2,
        "observerPromisesCommunicationPerInbox": 8,
        "observerPromisesOrdinaryPerInbox": 8,
        "p95MinimumSamples": 20,
        "physicalIdentityPruning": False,
        "poolsPerGateway": 2,
        "rssScope": "one_node_process_not_per_case",
        "sfuInventoryOnly": True,
        "sqlPerStore": 4,
    },
    "schemaVersion": 1,
    "status": "frozen_experiment_not_capacity_result",
    "workloadSeed": 39,
}


def derived_uuid(seed_hex: str, run_id: str, purpose: str) -> str:
    if (
        type(seed_hex) is not str
        or re.fullmatch("[a-f0-9]{64}", seed_hex) is None
        or type(run_id) is not str
        or re.fullmatch("[a-f0-9]{32}", run_id) is None
        or type(purpose) is not str
        or re.fullmatch("[a-z0-9:_-]{1,96}", purpose) is None
    ):
        raise GateError("invalid_identity")
    digest = hmac.new(
        bytes.fromhex(seed_hex),
        b"p2.workload.v1\n" + run_id.encode() + b"\n" + purpose.encode(),
        hashlib.sha256,
    ).digest()
    bits = bytearray(digest[:16])
    bits[6] = (bits[6] & 15) | 64
    bits[8] = (bits[8] & 63) | 128
    from uuid import UUID

    return str(UUID(bytes=bytes(bits)))


def schemas(run_id: str) -> tuple[str, str]:
    if type(run_id) is not str or re.fullmatch("[a-f0-9]{32}", run_id) is None:
        raise GateError("invalid_identity")
    return tuple("p2_workload_" + run_id + "_" + p for p in ("capacity", "dormant"))  # type: ignore[return-value]


def validate_child_environment(environment: dict[str, str], mode: str) -> None:
    if mode not in MODES:
        raise GateError("invalid_child_mode")
    key = "P2_WORKLOAD_OWNER_PASSWORD" if mode in OWNER_MODES else "P2_WORKLOAD_RUNTIME_PASSWORD"
    if (
        type(environment) is not dict
        or not COMMON | {key} <= environment.keys()
        or environment.keys() - COMMON - {key} - core.BASE_ENVIRONMENT_KEYS
        or any(
            type(v) is not str or not v or len(v) > 4096 or "\0" in v for v in environment.values()
        )
    ):
        raise GateError("invalid_environment")
    schemas(environment["P2_WORKLOAD_RUN_ID"])
    port = environment["P2_WORKLOAD_PG_PORT"]
    directory = Path(environment["P2_WORKLOAD_DIRECTORY"])
    if (
        re.fullmatch("[1-9][0-9]{0,4}", port) is None
        or not 1 <= int(port) <= 65535
        or not directory.is_absolute()
        or directory != directory.resolve()
        or directory.is_symlink()
    ):
        raise GateError("invalid_environment")


def child_environment(values: dict[str, str], common: dict[str, str], mode: str) -> dict[str, str]:
    if mode not in MODES or type(common) is not dict or set(common) != COMMON:
        raise GateError("invalid_environment")
    key = "P2_WORKLOAD_OWNER_PASSWORD" if mode in OWNER_MODES else "P2_WORKLOAD_RUNTIME_PASSWORD"
    source = "POSTGRES_MIGRATION_PASSWORD" if mode in OWNER_MODES else "POSTGRES_PASSWORD"
    if not values.get(source) or values.get("POSTGRES_PORT") != common["P2_WORKLOAD_PG_PORT"]:
        raise GateError("missing_setup")
    result = {**core.base_environment(), **common, key: values[source]}
    validate_child_environment(result, mode)
    return result


def validated_stage(raw: bytes, mode: str) -> dict[str, Any]:
    if mode not in STAGES:
        raise GateError("invalid_stage")
    result = native.decode(raw)
    expected = {
        "schemaVersion": 1,
        "status": "passed",
        "mode": mode,
        "nodeVersion": "24.22.2",
        **STAGES[mode],
    }
    if not native.exact(result, expected):
        raise GateError("invalid_stage_report")
    return result


class Children(previous.Children):
    def __init__(self, work: Path, deadline: float, *, final_deadline: float | None = None) -> None:
        super().__init__(work, deadline)
        self.final_deadline = final_deadline if final_deadline is not None else deadline
        self.start_failed = False

    def start(
        self, name: str, argv: list[str], environment: dict[str, str], *, cwd: Path
    ) -> OwnedProcess:
        if (
            self.count >= 32
            or type(name) is not str
            or re.fullmatch("[a-z0-9-]{1,48}", name) is None
        ):
            raise GateError("child_budget")
        native.remaining(self.deadline)
        self.count += 1
        try:
            child = GroupedOwnedProcess(
                argv,
                cwd=cwd,
                env=environment,
                output_directory=self.work / name,
                max_output_bytes=8192,
                final_deadline=self.final_deadline,
            )
        except BaseException:
            self.start_failed = True
            raise
        self.children.append(child)
        return child

    def close(self) -> None:
        failed = False
        for child in reversed(self.children):
            try:
                child.close()
                failed |= (
                    child.returncode is None
                    or child.cleanup_failed
                    or getattr(child, "group_settled", False) is not True
                )
            except BaseException:  # noqa: BLE001 - attempt every independently owned child.
                failed = True
        if failed or self.start_failed:
            raise GateError("cleanup_incomplete")

    def finish(
        self,
        child: OwnedProcess,
        *,
        deadline: float | None = None,
        require_zero: bool = True,
        accepted_codes: tuple[int, ...] | None = None,
    ) -> bytes:
        result = child.wait(timeout=min(240, native.remaining(deadline or self.deadline)))
        stdout, stderr = core.CaptureBudget.read(child.output_directory, MAX_STREAM_BYTES)
        self.captured += len(stdout) + len(stderr)
        if self.captured > MAX_CAPTURE_BYTES or child.cleanup_failed:
            raise GateError("capture_or_cleanup_failed")
        child.close()
        if child.cleanup_failed or getattr(child, "group_settled", False) is not True:
            raise GateError("cleanup_incomplete")
        native.remaining(deadline or self.deadline)
        if result.returncode not in (
            accepted_codes if accepted_codes is not None else ((0,) if require_zero else (0, -15))
        ):
            raise GateError("child_failed")
        return stdout


def owned_children_settled(children: Children) -> bool:
    return not children.start_failed and all(
        c.returncode is not None
        and not c.cleanup_failed
        and getattr(c, "group_settled", False) is True
        for c in children.children
    )


class ControlConnections:
    """Public psycopg ownership; no connection is forgotten if close observation fails."""

    def __init__(self) -> None:
        self.entries: list[tuple[Any, int]] = []
        self.maximum_live = 0

    def retain(self, connection: Any) -> Any:
        self.entries.append((connection, connection.info.backend_pid))
        self.maximum_live = max(self.maximum_live, sum(not c.closed for c, _ in self.entries))
        if self.maximum_live > 2 or not _counter(self.entries[-1][1], 1, 2147483647):
            raise GateError("control_connection_budget")
        return connection

    def settled(self) -> bool:
        return all(c.closed for c, _ in self.entries)

    def close(self) -> bool:
        complete = True
        for connection, _ in reversed(self.entries):
            try:
                connection.close()
            except BaseException:  # noqa: BLE001 - attempt every independent control connection.
                complete = False
        return complete and self.settled()

    def proof(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "scope": "parent_control_only",
            "maximumLive": self.maximum_live,
            "configuredRuntimeConnections": 8,
            "possibleRuntimePlusControlConnections": 10,
            "connections": [
                {"backendPid": pid, "closed": bool(c.closed)} for c, pid in self.entries
            ],
            "allClosed": self.settled(),
        }


def bounded_read(path: Path, maximum: int = MAX_PROOF_BYTES, *, allow_empty: bool = False) -> bytes:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != 0o600
        or not (0 if allow_empty else 1) <= info.st_size <= maximum
    ):
        raise GateError("unsafe_proof_file")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        current = os.fstat(stream.fileno())
        if (current.st_dev, current.st_ino, current.st_size) != (
            info.st_dev,
            info.st_ino,
            info.st_size,
        ):
            raise GateError("unsafe_proof_file")
        result = stream.read(maximum + 1)
    if len(result) != info.st_size:
        raise GateError("unsafe_proof_file")
    return result


def json_file(path: Path) -> Any:
    raw = bounded_read(path)
    try:
        return json.loads(
            raw.decode(),
            object_pairs_hook=core.unique_object,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (ValueError, UnicodeError, RecursionError, core.GateError):
        raise GateError("invalid_proof") from None


def snapshot_digest(value: Any) -> str:
    try:
        raw = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise GateError("invalid_proof") from None
    return hashlib.sha256(raw).hexdigest()


def source_snapshot(root: Path) -> dict[str, str]:
    files = [
        *sorted((root / "projects/channel-continuity/src").glob("*.ts")),
        *(
            root / "projects/channel-continuity" / n
            for n in (
                "package.json",
                "tsconfig.pg.json",
                "tests/workload-model.ts",
                "tests/workload-model.test.ts",
                "tests/pg_workload_cases.ts",
                "tests/inbox-observer.test.ts",
                "workloads/bounded-v1.json",
            )
        ),
        *(
            root / "local-setup/scripts" / n
            for n in (
                "p2_workload_check.py",
                "p2_native_check.py",
                "p2_rehydration_check.py",
                "p2_rehydration_media_check.py",
                "p3_coordinator_check.py",
                "p3_document_package.py",
                "p3_document_evidence.py",
                "p3_package_check.py",
            )
        ),
        root / "harness/process_control.py",
        root / "tests/test_p2_workload_gate.py",
    ]
    result = {}
    for p in files:
        info = p.lstat()
        if info.st_uid != os.getuid():
            raise GateError("unsafe_source_file")
        result[str(p.relative_to(root))] = hashlib.sha256(storage.source_bytes(p)).hexdigest()
    return dict(sorted(result.items()))


def validated_backends(raw: bytes, *, run_id: str, process_id: int) -> tuple[int, int]:
    v = native.decode(raw)
    if (
        set(v) != {"schemaVersion", "phase", "processId", "schema", "backendIds"}
        or not native.exact(v["schemaVersion"], 1)
        or v["phase"] != "burst"
        or type(v["processId"]) is not int
        or v["processId"] != process_id
        or v["schema"] != schemas(run_id)[0]
        or type(v["backendIds"]) is not list
        or len(v["backendIds"]) != 2
        or any(type(x) is not int or not 1 <= x <= 2147483647 for x in v["backendIds"])
        or v["backendIds"] != sorted(set(v["backendIds"]))
    ):
        raise GateError("invalid_backend_identity")
    return (v["backendIds"][0], v["backendIds"][1])


def burst_schedule(
    children: Children,
    child: OwnedProcess,
    barriers: dict[str, FileBarrier],
    work: Path,
    connect: Any,
    run_id: str,
) -> dict[str, Any]:
    from psycopg import sql

    child.wait_for_barrier(barriers["workload_burst_ready"], timeout=20)
    with closing(connect()) as locker, locker.transaction():
        locker.execute(
            sql.SQL("SELECT * FROM {}.admission WHERE singleton FOR UPDATE").format(
                sql.Identifier(schemas(run_id)[0])
            )
        ).fetchone()
        locker_pid = locker.execute("SELECT pg_backend_pid()").fetchone()[0]
        child.release_barrier(barriers["workload_burst_ready"])
        child.wait_for_barrier(barriers["workload_burst_waiting"], timeout=1.1)
        exact = validated_backends(
            bounded_read(work / "workload-burst-backends.json", 4096),
            run_id=run_id,
            process_id=child.pid,
        )
        with closing(connect()) as observer:
            end = time.monotonic() + 0.2
            while True:
                rows = observer.execute(
                    "SELECT pid,pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid=ANY(%s)",
                    [list(exact)],
                ).fetchall()
                graph = {pid: list(blockers) for pid, blockers in rows}

                def reaches(
                    pid: int, seen: set[int], observed: dict[int, list[int]] = graph
                ) -> bool:
                    if pid in seen:
                        return False
                    return any(
                        b == locker_pid or reaches(b, seen | {pid}) for b in observed.get(pid, [])
                    )

                if set(graph) == set(exact) and all(reaches(pid, set()) for pid in exact):
                    break
                if time.monotonic() >= end:
                    raise GateError("owned_waiters_not_observed")
                time.sleep(0.01)
            proof = {
                "schemaVersion": 1,
                "schema": schemas(run_id)[0],
                "processId": child.pid,
                "lockerPid": locker_pid,
                "observerPid": observer.info.backend_pid,
                "controlBackendIds": [locker_pid, observer.info.backend_pid],
                "runtimeBackendIds": list(exact),
                "edges": [{"pid": pid, "blockers": graph[pid]} for pid in exact],
                "waiters": 2,
                "graphs": 1,
            }
    return proof


def _counter(v: Any, low: int = 0, high: int = 10**12) -> bool:
    return type(v) is int and low <= v <= high


def bounded_number(value: Any, low: float, high: float) -> bool:
    if type(value) is int:
        return low <= value <= high
    return type(value) is float and math.isfinite(value) and low <= value <= high


def validate_latency(v: Any) -> None:
    if (
        type(v) is not dict
        or not {"count", "p50Ms", "maximumMs"} <= v.keys()
        or v.keys() - {"count", "p50Ms", "maximumMs", "p95Ms"}
        or not _counter(v["count"], 0, 2000)
    ):
        raise GateError("invalid_quantitative_proof")
    n = v["count"]
    if ("p95Ms" in v) != (n >= 20):
        raise GateError("invalid_quantitative_proof")
    if not n:
        if v["p50Ms"] is not None or v["maximumMs"] is not None:
            raise GateError("invalid_quantitative_proof")
        return
    for k in ("p50Ms", "maximumMs", *(["p95Ms"] if n >= 20 else [])):
        if not bounded_number(v[k], 0, 360000):
            raise GateError("invalid_quantitative_proof")
    if v["p50Ms"] > v["maximumMs"] or (n >= 20 and not v["p50Ms"] <= v["p95Ms"] <= v["maximumMs"]):
        raise GateError("invalid_quantitative_proof")


def _validate_resources(work: Path) -> dict[str, Any]:
    dormant = json_file(work / "workload-dormant-resources.json")
    capacity = json_file(work / "workload-capacity-resources.json")
    if (
        type(dormant) is not dict
        or set(dormant)
        != {
            "workloadSeed",
            "performanceBudgets",
            "processSamples",
            "schemaVersion",
            "scope",
            "samples",
            "cohort",
            "latencyMs",
            "readersConcurrent",
            "maximumCredentialWindow",
            "roomsAllocated",
            "agentsAllocated",
        }
        or not native.exact(dormant["schemaVersion"], 1)
        or type(capacity) is not dict
        or set(capacity)
        != {
            "workloadSeed",
            "performanceBudgets",
            "usefulCompletionMs",
            "schemaVersion",
            "scope",
            "configured",
            "observed",
            "samples",
            "cohorts",
            "observer",
            "terminalGateways",
            "cleanupComplete",
        }
        or not native.exact(capacity["schemaVersion"], 1)
        or dormant["cohort"] != "public_associate_accept_inspect_1000"
    ):
        raise GateError("invalid_resource_envelope")

    if (
        dormant.get("schemaVersion") != 1
        or dormant.get("scope") != "one_node_process_sequential_reader_windows"
        or not native.exact(
            [r.get("population") for r in dormant.get("samples", [])], [0, 64, 256, 1000]
        )
        or not native.exact(dormant.get("readersConcurrent"), 1)
        or not native.exact(dormant.get("maximumCredentialWindow"), 64)
        or not native.exact(dormant.get("roomsAllocated"), 0)
        or not native.exact(dormant.get("agentsAllocated"), 0)
    ):
        raise GateError("invalid_dormant_resources")
    validate_latency(dormant.get("latencyMs"))
    if dormant["latencyMs"]["count"] != 1000:
        raise GateError("invalid_quantitative_proof")
    if (
        capacity.get("scope") != "one_node_process_two_gateways"
        or not native.exact(capacity.get("cleanupComplete"), True)
        or not native.exact(
            capacity.get("configured"),
            {
                "gateways": 2,
                "pools": 4,
                "connections": 8,
                "retainedSqlOperations": 16,
                "dispatcherTasksPerInstance": 2,
                "persistedClaimsPerSchema": 2,
            },
        )
    ):
        raise GateError("invalid_capacity_resources")
    observed = capacity.get("observed", {})
    if not native.exact(observed.get("prepareMaximum"), 2) or not _counter(
        observed.get("httpMaximum"), 4, 8
    ):
        raise GateError("invalid_capacity_resources")
    rejections = observed.get("preacceptance")
    if (
        type(rejections) is not list
        or len(rejections) != 4
        or any(
            type(r) is not dict
            or set(r) != {"eventId", "status", "code", "receiptPresent"}
            or type(r["eventId"]) is not str
            or re.fullmatch(
                "[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", r["eventId"]
            )
            is None
            or not native.exact(r["status"], 429)
            or r["code"] != "capacity"
            or not native.exact(r["receiptPresent"], False)
            for r in rejections
        )
        or len({r["eventId"] for r in rejections}) != 4
    ):
        raise GateError("invalid_preacceptance_proof")
    pools = observed.get("pools")
    if (
        type(pools) is not list
        or len(pools) != 4
        or any(
            type(p) is not dict
            or set(p) != {"total", "waiting", "occupied"}
            or not _counter(p["total"], 1, 2)
            or not _counter(p["waiting"], 0, 2)
            or not _counter(p["occupied"], 1, 4)
            for p in pools
        )
    ):
        raise GateError("invalid_pool_resources")
    snaps = observed.get("snapshots")
    if (
        type(snaps) is not list
        or len(snaps) != 1
        or snaps[0].get("phase") != "burst_held"
        or not native.exact(snaps[0]["pools"][2], {"total": 2, "idle": 0, "waiting": 2})
        or snaps[0]["gateway"][0].get("active") != 4
    ):
        raise GateError("invalid_pool_resources")
    expected_budgets = EXPECTED_MANIFEST["performanceBudgets"]
    if (
        not native.exact(dormant.get("workloadSeed"), 39)
        or not native.exact(capacity.get("workloadSeed"), 39)
        or not native.exact(dormant.get("performanceBudgets"), expected_budgets)
        or not native.exact(capacity.get("performanceBudgets"), expected_budgets)
    ):
        raise GateError("invalid_performance_budget")
    process_samples = dormant.get("processSamples")
    if (
        type(process_samples) is not list
        or not 1 <= len(process_samples) <= 4096
        or type(capacity.get("samples")) is not list
        or not 1 <= len(capacity["samples"]) <= 2000
    ):
        raise GateError("invalid_quantitative_proof")
    for row in (*dormant["samples"], *process_samples, *capacity["samples"]):
        if (
            type(row) is not dict
            or set(row)
            != {
                "population",
                "eventLoopMaxMs",
                "monotonicMs",
                "rssBytes",
                "heapUsedBytes",
                "externalBytes",
                "cpuUserMicroseconds",
                "cpuSystemMicroseconds",
            }
            or type(row["population"]) is not int
            or row["population"] not in (-1, 0, 64, 256, 1000)
            or not bounded_number(row["rssBytes"], 1, 536870912)
            or not bounded_number(row["eventLoopMaxMs"], 0, 1000)
            or any(
                not bounded_number(row[k], 0, 10**12)
                for k in (
                    "heapUsedBytes",
                    "externalBytes",
                    "cpuUserMicroseconds",
                    "cpuSystemMicroseconds",
                    "monotonicMs",
                )
            )
        ):
            raise GateError("performance_budget_exceeded")
    validate_latency(capacity.get("usefulCompletionMs"))
    if (
        capacity["usefulCompletionMs"]["count"] != 63
        or capacity["usefulCompletionMs"]["maximumMs"] > 15000
    ):
        raise GateError("performance_budget_exceeded")
    cohorts = capacity.get("cohorts")
    if type(cohorts) is not dict or set(cohorts) != {"steady", "burst", "slow", "capfill"}:
        raise GateError("invalid_quantitative_proof")
    for key, count in [("steady", 16), ("burst", 3), ("slow", 4), ("capfill", 40)]:
        validate_latency(cohorts[key])
        if cohorts[key]["count"] != count or cohorts[key]["maximumMs"] > 5000:
            raise GateError("invalid_quantitative_proof")
    observer = capacity.get("observer", {})
    if not native.exact(
        observer.get("beforeSqlClose"),
        {"observerPending": 8, "observerDropped": 12, "observerFailures": 0},
    ):
        raise GateError("invalid_observer_proof")
    if not native.exact(
        observer.get("afterSqlClose"),
        {"observerPending": 8, "observerDropped": 13, "observerFailures": 0},
    ) or not native.exact(
        observer.get("afterActualCallbackSettlement"),
        {"observerPending": 0, "observerDropped": 13, "observerFailures": 0},
    ):
        raise GateError("invalid_observer_proof")
    gws = capacity.get("terminalGateways")
    if (
        type(gws) is not list
        or len(gws) != 2
        or any(
            not native.exact(g.get(k), 0)
            for g in gws
            for k in ["active", "intakes", "sockets", "handlers", "driver", "observerPending"]
        )
    ):
        raise GateError("invalid_cleanup_proof")
    return {
        "dormant": dormant,
        "capacity": capacity,
        "interpretation": {
            "poolOccupied": "checked_out_plus_pool_waiting_SQL_operations",
            "poolTotal": "actual_open_connections",
            "poolWaiting": "queued_connect_calls",
            "memory": "one_Node_process_bytes_not_per_case",
            "cpu": "cumulative_process_user_system_microseconds",
            "quantiles": "nearest_rank",
        },
    }


def validate_resources(work: Path) -> dict[str, Any]:
    try:
        return _validate_resources(work)
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError, IndexError):
        raise GateError("invalid_resource_proof") from None


def validate_catalog_names(value: Any) -> list[str]:
    expected = EXPECTED_MANIFEST["catalog"]["tables"]
    if type(value) is not list or any(type(name) is not str for name in value) or value != expected:
        raise GateError("invalid_catalog_inventory")
    return value


def independent_snapshot(connect: Any, run_id: str) -> dict[str, dict[str, Any]]:
    from psycopg import sql

    result = {}
    with closing(connect()) as c:
        for schema in schemas(run_id):
            names = [
                r[0]
                for r in c.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename",
                    [schema],
                )
            ]
            validate_catalog_names(names)
            tables = {}
            for table in names:
                rows = [
                    r[0]
                    for r in c.execute(
                        sql.SQL(
                            "SELECT to_jsonb(t) FROM {}.{} t ORDER BY to_jsonb(t)::text LIMIT 10001"
                        ).format(sql.Identifier(schema), sql.Identifier(table))
                    )
                ]
                if len(rows) > 10000:
                    raise GateError("invalid_snapshot")
                if len(json.dumps(rows, separators=(",", ":")).encode()) > MAX_PROOF_BYTES:
                    raise GateError("proof_limit")
                tables[table] = rows
            result[schema] = tables
    return result


def validate_originals(
    snapshot: dict[str, dict[str, Any]], work: Path, run_id: str
) -> dict[str, Any]:
    ledger = json_file(work / "workload-operations.json")
    if type(ledger) is not list or len(ledger) != 68:
        raise GateError("invalid_ledger")
    entropy = json_file(work / "fixture.json")["seedHex"]
    rejected = [derived_uuid(entropy, run_id, "rejected:event:" + str(i)) for i in range(4)]
    if any(r["event_id"] in rejected for tables in snapshot.values() for r in tables["inbox"]):
        raise GateError("preacceptance_id_was_accepted")
    ids: set[str] = set()
    keys: set[str] = set()
    receipts = 0
    for profile, expected in [("capacity", 64), ("dormant", 1002)]:
        tables = snapshot[schemas(run_id)[0 if profile == "capacity" else 1]]
        inbox = tables["inbox"]
        intents = tables["processing_intents"]
        plans = tables["dispatch_plans"]
        if len(inbox) != expected or len(intents) != expected:
            raise GateError("invalid_retained_count")
        counts: dict[tuple[str, str, str], list[int]] = {}
        for row in inbox:
            scope = (row["tenant_id"], row["account_id"], row["conversation_id"])
            counts.setdefault(scope, []).append(int(row["acceptance_sequence"]))
        if len(counts) != (2 if profile == "capacity" else 1000):
            raise GateError("invalid_scope_population")
        for scope, sequences in counts.items():
            if sorted(sequences) != list(range(1, len(sequences) + 1)):
                raise GateError("invalid_scope_sequence")
            if not scope[0] in {"workload-tenant-0", "workload-tenant-1"}:
                raise GateError("invalid_scope_population")
            if profile == "capacity" and len(sequences) != (
                33 if scope[0] == "workload-tenant-0" else 31
            ):
                raise GateError("invalid_scope_population")
        if profile == "dormant" and sorted(len(v) for v in counts.values()) != [1] * 998 + [2] * 2:
            raise GateError("invalid_scope_population")

        if tables["admission"][0]["inbox_count"] != expected:
            raise GateError("invalid_retained_count")
        states = {
            state: sum(r["state"] == state for r in intents)
            for state in ("pending", "running", "dispatched", "blocked", "exhausted", "uncertain")
        }
        if states != (
            {
                "pending": 0,
                "running": 0,
                "dispatched": 64,
                "blocked": 0,
                "exhausted": 0,
                "uncertain": 0,
            }
            if profile == "capacity"
            else {
                "pending": 998,
                "running": 0,
                "dispatched": 4,
                "blocked": 0,
                "exhausted": 0,
                "uncertain": 0,
            }
        ):
            raise GateError("invalid_processing_inventory")
        originals = json_file(work / ("workload-" + profile + "-originals.json"))
        if profile == "dormant":
            originals += json_file(work / "workload-wake-originals.json")
        if type(originals) is not list or len(originals) != expected:
            raise GateError("invalid_original_receipts")
        for original in originals:
            receipt = original["receipt"]
            row = next((r for r in inbox if r["receipt_id"] == receipt["receiptId"]), None)
            if row is None or receipt["receiptId"] in ids or original["operationKey"] in keys:
                raise GateError("invalid_original_receipts")
            ids.add(receipt["receiptId"])
            keys.add(original["operationKey"])
            receipts += 1
            wire = json.loads(row["wire_json"])
            canonical = json.loads(row["canonical_payload"])
            intent = next((r for r in intents if r["receipt_id"] == row["receipt_id"]), None)
            at = str(row["accepted_at"]).replace("+00:00", "Z")
            original_at = receipt["acceptedAt"]
            from datetime import datetime

            if (
                receipt["eventId"] != row["event_id"]
                or receipt["messageId"] != row["message_id"]
                or str(receipt["acceptanceSequence"]) != str(row["acceptance_sequence"])
                or datetime.fromisoformat(at) != datetime.fromisoformat(original_at)
                or intent is None
                or original["operationKey"] != intent["operation_key"]
                or wire["eventId"] != receipt["eventId"]
                or wire["accountScope"]
                != {"tenantId": row["tenant_id"], "accountId": row["account_id"]}
                or wire["conversationId"] != row["conversation_id"]
                or wire["providerScope"]
                != {
                    "tenantId": row["tenant_id"],
                    "provider": row["provider"],
                    "providerAccountId": row["provider_account_id"],
                }
                or hashlib.sha256(canonical["body"].encode()).hexdigest() != original["bodyDigest"]
                or hashlib.sha256(
                    json.dumps(wire, separators=(",", ":"), ensure_ascii=False).encode()
                ).hexdigest()
                != original["eventDigest"]
            ):
                raise GateError("invalid_original_receipts")
        selected = [
            r for r in ledger if r["prepared"]["submission"]["caseId"].startswith("case-" + profile)
        ]
        if len(selected) != (64 if profile == "capacity" else 4) or len(plans) != len(selected):
            raise GateError("invalid_operation_inventory")
        for item in selected:
            prepared, receipt = item["prepared"], item["receipt"]
            submission = prepared["submission"]
            plan = next(
                (p for p in plans if p["receipt_id"] == submission["message"]["receiptId"]), None
            )
            intent = next(
                (r for r in intents if r["receipt_id"] == submission["message"]["receiptId"]), None
            )
            original_row = next(
                (r for r in inbox if r["receipt_id"] == submission["message"]["receiptId"]), None
            )
            wire = json.loads(original_row["wire_json"]) if original_row else {}
            if (
                original_row is None
                or submission["scope"]
                != {"tenantId": original_row["tenant_id"], "accountId": original_row["account_id"]}
                or submission["caseId"] != wire.get("caseId")
                or submission["conversationId"] != original_row["conversation_id"]
                or submission["caseRevision"] != "1"
                or json.loads(prepared["canonicalPayload"]) != submission
                or submission["message"]
                != {
                    "receiptId": original_row["receipt_id"],
                    "eventId": original_row["event_id"],
                    "messageId": original_row["message_id"],
                    "senderId": wire.get("senderId"),
                    "body": wire.get("body"),
                }
            ):
                raise GateError("invalid_operation_identity")

            if (
                plan is None
                or intent is None
                or plan["payload_json"] != prepared["canonicalPayload"]
                or plan["payload_digest"] != prepared["payloadDigest"]
                or hashlib.sha256(prepared["canonicalPayload"].encode()).hexdigest()
                != prepared["payloadDigest"]
                or receipt["payloadDigest"] != prepared["payloadDigest"]
                or receipt["scope"] != submission["scope"]
                or receipt["operationKey"] != submission["operationKey"]
                or receipt["operationKey"] != intent["operation_key"]
                or intent["external_receipt_id"] != receipt["receiptId"]
            ):
                raise GateError("invalid_operation_identity")
    if receipts != 1066:
        raise GateError("invalid_original_receipts")
    return {
        "schemaVersion": 1,
        "originalReceipts": 1066,
        "preacceptanceRejectedEventIds": rejected,
        "preacceptanceRejectedIdsAbsent": 4,
        "logicalOperationAcceptances": 68,
        "capacityDispatched": 64,
        "dormantDispatched": 4,
        "dormantPending": 998,
        "allOriginalReceiptScopeBodyOperationJoins": True,
    }


def evidence_index(directory: Path) -> dict[str, Any]:
    entries = {}
    total = 0
    for path in sorted(directory.iterdir()):
        if path.name == "retained-index.json":
            raise GateError("evidence_exists")
        raw = bounded_read(path, MAX_EVIDENCE_BYTES, allow_empty=path.suffix == ".bin")
        total += len(raw)
        if total > MAX_EVIDENCE_BYTES:
            raise GateError("evidence_limit")
        entries[path.name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    if not entries:
        raise GateError("missing_evidence")
    result = {"schemaVersion": 1, "files": entries, "totalBytes": total}
    native.write_json(directory / "retained-index.json", result, maximum=MAX_PROOF_BYTES)
    return result


def validate_evidence_index(directory: Path, expected_sha256: str) -> dict[str, Any]:
    raw = bounded_read(directory / "retained-index.json")
    value = native.decode(raw, maximum=MAX_PROOF_BYTES)
    if (
        hashlib.sha256(raw).hexdigest() != expected_sha256
        or set(value) != {"schemaVersion", "files", "totalBytes"}
        or not native.exact(value["schemaVersion"], 1)
        or type(value["files"]) is not dict
        or not _counter(value["totalBytes"], 1, MAX_EVIDENCE_BYTES)
    ):
        raise GateError("invalid_evidence_index")
    physical = {p.name for p in directory.iterdir()}
    if physical != set(value["files"]) | {"retained-index.json"}:
        raise GateError("invalid_evidence_index")
    total = 0
    for name, entry in value["files"].items():
        if (
            type(name) is not str
            or re.fullmatch("[a-zA-Z0-9_.-]{1,128}", name) is None
            or name == "retained-index.json"
            or type(entry) is not dict
            or set(entry) != {"bytes", "sha256"}
        ):
            raise GateError("invalid_evidence_index")
        data = bounded_read(
            directory / name, MAX_EVIDENCE_BYTES, allow_empty=Path(name).suffix == ".bin"
        )
        total += len(data)
        if (
            not _counter(
                entry["bytes"], 0 if Path(name).suffix == ".bin" else 1, MAX_EVIDENCE_BYTES
            )
            or entry["bytes"] != len(data)
            or entry["sha256"] != hashlib.sha256(data).hexdigest()
        ):
            raise GateError("invalid_evidence_index")
    if total != value["totalBytes"] or total > MAX_EVIDENCE_BYTES:
        raise GateError("invalid_evidence_index")
    return value


def validated_report(raw: bytes) -> dict[str, Any]:
    v = native.decode(raw)
    fixed = {
        "schema_version": 1,
        "status": "passed",
        "mode": MODE,
        "tests": 24,
        "passed": 24,
        "cases": list(CASE_NAMES),
        "workload_seed": 39,
        "child_commands": 16,
        "capacity_inputs": 64,
        "dormant_inputs": 1002,
        "operation_acceptances": 68,
        "owned_sql_graphs": 1,
        "owned_sql_waiters": 2,
        "rooms_allocated": 0,
        "agents_allocated": 0,
        "cleanup_complete": True,
        "node_version": "24.22.2",
        "capacity_claimed": False,
    }
    if (
        set(v) != set(fixed) | {"duration_seconds", "retained_index_sha256"}
        or any(not native.exact(v[k], x) for k, x in fixed.items())
        or not bounded_number(v["duration_seconds"], 0.000001, TOTAL_SECONDS - 0.000001)
        or type(v["retained_index_sha256"]) is not str
        or re.fullmatch("[a-f0-9]{64}", v["retained_index_sha256"]) is None
    ):
        raise GateError("invalid_report")
    return v


async def run(
    root: Path, artifacts: Path, started: float, cleanup: dict[str, bool]
) -> dict[str, Any]:
    import aiohttp
    import psycopg
    from livekit import api
    from psycopg import sql

    final = started + TOTAL_SECONDS
    deadline = final - CLEANUP_SECONDS
    setup = core.load_setup(root)
    values = setup.load_settings()
    node, docker = shutil.which("node"), shutil.which("docker")
    project = root / "projects/channel-continuity"
    if not node or not docker:
        raise GateError("missing_setup")
    frozen = source_snapshot(root)
    native.write_json(artifacts / "source-before.json", frozen, maximum=MAX_PROOF_BYTES)
    run_id = uuid4().hex
    scratch = project / ".local/workload-check"
    core.private_directory(scratch)
    work = Path(tempfile.mkdtemp(prefix="run-", dir=scratch)).resolve()
    os.chmod(work, 0o700)
    native.write_json(
        work / "workload-owned-work.json",
        {"schemaVersion": 1, "runId": run_id, "schemas": list(schemas(run_id))},
    )
    native.write_json(
        work / "fixture.json",
        {"schemaVersion": 1, "runId": run_id, "seedHex": secrets.token_hex(32)},
    )
    children = Children(work, deadline, final_deadline=final)
    barriers = {name: FileBarrier(work, name) for name in BARRIERS}
    common = {
        "P2_WORKLOAD_DIRECTORY": str(work),
        "P2_WORKLOAD_RUN_ID": run_id,
        "P2_WORKLOAD_PG_PORT": values["POSTGRES_PORT"],
    }
    script = work / "compiled/tests/pg_workload_cases.js"
    installed = False
    backup = False
    container = ""
    backup_dir = "/tmp/p2-workload-" + run_id
    groups: set[str] = set()
    sfu: Any = None
    exclusions = tuple(values[k] for k in setup.SECRET_KEYS)
    auth_nonce = json_file(work / "fixture.json")["seedHex"]

    def private_value(purpose: str) -> bytes:
        return hmac.new(
            bytes.fromhex(auth_nonce),
            b"p2.workload.v1\n" + run_id.encode() + b"\n" + purpose.encode(),
            hashlib.sha256,
        ).digest()

    import base64

    capture_exclusions = (
        *exclusions,
        auth_nonce,
        *(
            base64.urlsafe_b64encode(private_value("account:" + profile + "-" + str(i).zfill(4)))
            .decode()
            .rstrip("=")
            for profile, count in [("capacity", 2), ("dormant", 1000)]
            for i in range(count)
        ),
        *(private_value("hmac:" + str(t)).hex() for t in [0, 1]),
    )

    controls = ControlConnections()

    def connect() -> Any:
        return controls.retain(
            psycopg.connect(
                host="127.0.0.1",
                port=int(values["POSTGRES_PORT"]),
                dbname="livekit_lab",
                user="continuity_migrator",
                password=values["POSTGRES_MIGRATION_PASSWORD"],
                sslmode="disable",
                connect_timeout=2,
                options="-c search_path=pg_catalog -c statement_timeout=3000 -c lock_timeout=1500",
                autocommit=True,
            )
        )

    async def stage(mode: str, end: float | None = None) -> dict[str, Any]:
        cap = 180 if mode == "seed" else 70 if mode == "serve" else 30
        limit = min(end or deadline, time.monotonic() + cap)
        native.remaining(limit)
        raw = await asyncio.to_thread(
            children.call,
            mode,
            [node, str(script), mode],
            child_environment(values, common, mode),
            cwd=work,
            deadline=limit,
        )
        result = validated_stage(raw, mode)
        groups.update(result["completedGroups"])
        return result

    async def inventory() -> dict[str, Any]:
        response = await asyncio.wait_for(sfu.room.list_rooms(api.ListRoomsRequest()), timeout=3)
        # Names/SIDs are consumed only to compare inventory; retained evidence contains no room data.
        identities = sorted((r.name, r.sid) for r in response.rooms)
        return {"rooms": len(identities), "inventorySha256": snapshot_digest(identities)}

    before: dict[str, dict[str, Any]] = {}
    first: BaseException | None = None
    try:
        sfu = api.LiveKitAPI(
            url="http://127.0.0.1:" + values["LIVEKIT_HTTP_PORT"],
            api_key=values["LIVEKIT_API_KEY"],
            api_secret=values["LIVEKIT_API_SECRET"],
            timeout=aiohttp.ClientTimeout(total=3),
            failover=False,
        )
        room_before = await inventory()
        await asyncio.to_thread(
            children.call,
            "compile",
            [
                node,
                str(project / "node_modules/typescript/bin/tsc"),
                "--project",
                str(project / "tsconfig.pg.json"),
                "--outDir",
                str(work / "compiled"),
            ],
            core.base_environment(),
            cwd=project,
            deadline=min(deadline, time.monotonic() + 30),
        )
        native.write_json(
            artifacts / "runtime-build-parity.json",
            native.verify_runtime_build(project, work / "compiled"),
            maximum=MAX_PROOF_BYTES,
        )
        installed = True
        await stage("install")
        seed_end = min(deadline, time.monotonic() + 180)
        seed = children.start(
            "seed", [node, str(script), "seed"], child_environment(values, common, "seed"), cwd=work
        )
        await asyncio.to_thread(
            seed.wait_for_barrier,
            barriers["workload_dormant_ready"],
            timeout=min(179, native.remaining(seed_end)),
        )
        room_dormant = await inventory()
        if room_dormant != room_before:
            raise GateError("sfu_inventory_changed")
        seed.release_barrier(barriers["workload_dormant_ready"])
        groups.update(
            validated_stage(
                await asyncio.to_thread(children.finish, seed, deadline=seed_end), "seed"
            )["completedGroups"]
        )
        groups.add(CASE_NAMES[20])
        serve_end = min(deadline, time.monotonic() + 70)
        child = children.start(
            "serve",
            [node, str(script), "serve"],
            child_environment(values, common, "serve"),
            cwd=work,
        )
        graph = await asyncio.to_thread(
            burst_schedule, children, child, barriers, work, connect, run_id
        )
        native.write_json(artifacts / "sql-blocking-proof.json", graph)
        await asyncio.to_thread(
            child.wait_for_barrier,
            barriers["workload_slow_held"],
            timeout=min(20, native.remaining(serve_end)),
        )
        with closing(connect()) as observer:
            observed = observer.execute(
                sql.SQL(
                    "SELECT i.event_id::text,d.state,d.attempt_count,d.possible_external FROM {}.processing_intents d JOIN {}.inbox i USING(receipt_id) WHERE d.claim_owner IS NOT NULL AND d.claim_until>clock_timestamp() ORDER BY i.event_id"
                ).format(sql.Identifier(schemas(run_id)[0]), sql.Identifier(schemas(run_id)[0]))
            ).fetchall()
        workload_entropy = bytes.fromhex(json_file(work / "fixture.json")["seedHex"])

        def event_id(index: int) -> str:
            digest = hmac.new(
                workload_entropy,
                b"p2.workload.v1\n" + run_id.encode() + b"\ncapacity:event:" + str(index).encode(),
                hashlib.sha256,
            ).digest()
            bits = bytearray(digest[:16])
            bits[6] = (bits[6] & 15) | 64
            bits[8] = (bits[8] & 63) | 128
            from uuid import UUID

            return str(UUID(bytes=bytes(bits)))

        if sorted(r[0] for r in observed) != sorted([event_id(20), event_id(21)]) or any(
            r[1:] != ("running", 1, False) for r in observed
        ):
            raise GateError("persisted_claim_bound_not_observed")
        native.write_json(
            artifacts / "persisted-claim-proof.json",
            {
                "schemaVersion": 1,
                "activeClaims": 2,
                "maxActive": 2,
                "originalHeldEventIds": sorted(r[0] for r in observed),
                "abortedAdapterCallbacksRetained": 2,
                "source": "owner_sql_plus_exact_owned_application_barrier",
            },
        )
        child.release_barrier(barriers["workload_slow_held"])

        serve_raw = await asyncio.to_thread(children.finish, child, deadline=serve_end)
        serve_observed_exit = time.monotonic()
        groups.update(validated_stage(serve_raw, "serve")["completedGroups"])
        await stage("reopen")
        reopen_completed = time.monotonic()
        reopened_child = children.children[-1]
        if (
            child.pid == reopened_child.pid
            or child.returncode != 0
            or reopened_child.returncode != 0
            or child.cleanup_failed
            or reopened_child.cleanup_failed
        ):
            raise GateError("restart_owner_identity")
        native.write_json(
            artifacts / "restart-observation.json",
            {
                "schemaVersion": 1,
                "source": "parent_monotonic_observed_actual_exit_to_completed_fresh_stage",
                "includesProcessStartupAndVerification": True,
                "serveProcessId": child.pid,
                "reopenProcessId": reopened_child.pid,
                "serveActualExitVerified": True,
                "reopenActualExitVerified": True,
                "elapsedMs": (reopen_completed - serve_observed_exit) * 1000,
                "existingReopenStageDeadlineMs": 30000,
            },
        )
        await stage("dormant-wake")
        queue = {}
        with closing(connect()) as queue_reader:
            for label, target in zip(("capacity", "dormant"), schemas(run_id), strict=True):
                row = queue_reader.execute(
                    sql.SQL(
                        "WITH observed AS MATERIALIZED(SELECT clock_timestamp() AS at) SELECT (SELECT at FROM observed),count(*)::integer,min(i.accepted_at),CASE WHEN count(*)=0 THEN NULL ELSE EXTRACT(epoch FROM ((SELECT at FROM observed)-min(i.accepted_at)))*1000 END FROM {}.inbox i JOIN {}.processing_intents p USING(receipt_id) WHERE p.state<>'dispatched'"
                    ).format(sql.Identifier(target), sql.Identifier(target))
                ).fetchone()
                observed, count, oldest, age = row
                if (
                    type(count) is not int
                    or count != (0 if label == "capacity" else 998)
                    or (count == 0 and (oldest is not None or age is not None))
                    or (count and (oldest is None or age is None or not 0 <= float(age) <= 360000))
                ):
                    raise GateError("invalid_queue_age")
                queue[label] = {
                    "nonDispatched": count,
                    "observedAt": observed.isoformat(),
                    "oldestAcceptedAt": oldest.isoformat() if oldest else None,
                    "oldestPendingAgeMs": float(age) if age is not None else None,
                }
        native.write_json(
            artifacts / "queue-observation.json",
            {
                "schemaVersion": 1,
                "source": "postgres_clock_timestamp_single_statement_per_profile",
                "profiles": queue,
            },
        )
        await stage("verify")
        before = await asyncio.to_thread(independent_snapshot, connect, run_id)
        joins = validate_originals(before, work, run_id)
        native.write_json(artifacts / "independent-original-joins.json", joins)
        resources = validate_resources(work)
        if [r["eventId"] for r in resources["capacity"]["observed"]["preacceptance"]] != joins[
            "preacceptanceRejectedEventIds"
        ]:
            raise GateError("preacceptance_identity_mismatch")
        native.write_json(
            artifacts / "quantitative-observations.json", resources, maximum=MAX_PROOF_BYTES
        )
        container = (
            (
                await asyncio.to_thread(
                    children.call,
                    "backup-container",
                    [
                        docker,
                        "ps",
                        "--filter",
                        "label=com.docker.compose.service=postgres",
                        "--filter",
                        "label=com.docker.compose.project.working_dir=" + str(root / "local-setup"),
                        "--format",
                        "{{.ID}}",
                    ],
                    core.base_environment(),
                    cwd=work,
                    deadline=min(deadline, time.monotonic() + 10),
                )
            )
            .decode()
            .strip()
        )
        if re.fullmatch("[a-f0-9]{12,64}", container) is None:
            raise GateError("wrong_backup_container")
        backup = True
        await asyncio.to_thread(
            children.call,
            "backup-directory",
            [docker, "exec", container, "mkdir", "-m", "700", backup_dir],
            core.base_environment(),
            cwd=work,
            deadline=min(deadline, time.monotonic() + 10),
        )
        pg_env = {**core.base_environment(), "PGPASSWORD": values["POSTGRES_MIGRATION_PASSWORD"]}
        await asyncio.to_thread(
            children.call,
            "backup-dump",
            [
                docker,
                "exec",
                "-e",
                "PGPASSWORD",
                container,
                "sh",
                "-c",
                'umask 077; exec "$@"',
                "sh",
                "pg_dump",
                "--host=127.0.0.1",
                "--username=continuity_migrator",
                "--dbname=livekit_lab",
                *("--schema=" + s for s in schemas(run_id)),
                "--inserts",
                "--no-owner",
                "--file=" + backup_dir + "/schema.sql",
            ],
            pg_env,
            cwd=work,
            deadline=min(deadline, time.monotonic() + 30),
        )
        await asyncio.to_thread(
            children.call,
            "backup-copy",
            [
                docker,
                "cp",
                container + ":" + backup_dir + "/schema.sql",
                str(work / "workload-backup.sql"),
            ],
            core.base_environment(),
            cwd=work,
            deadline=min(deadline, time.monotonic() + 20),
        )
        # Docker copy may preserve mode from the explicitly owned dump. No unsafe proof is read.
        dump = work / "workload-backup.sql"
        info = dump.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_size > MAX_EVIDENCE_BYTES
        ):
            raise GateError("unsafe_backup")

        if stat.S_IMODE(info.st_mode) != 0o600:
            raise GateError("unsafe_backup")
        if not owned_children_settled(children) or not controls.settled():
            raise GateError("dependent_owner_unsettled")
        with closing(connect()) as c:
            for target in schemas(run_id):
                row = c.execute(
                    "SELECT pg_get_userbyid(nspowner),obj_description(oid,'pg_namespace') FROM pg_namespace WHERE nspname=%s",
                    [target],
                ).fetchone()
                if row != ("continuity_migrator", "p2-channel-schema-v7"):
                    raise GateError("backup_owner_mismatch")
                c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(target)))
        await asyncio.to_thread(
            children.call,
            "backup-restore",
            [
                docker,
                "exec",
                "-e",
                "PGPASSWORD",
                container,
                "psql",
                "-X",
                "--quiet",
                "--host=127.0.0.1",
                "--username=continuity_migrator",
                "--dbname=livekit_lab",
                "--set=ON_ERROR_STOP=1",
                "--single-transaction",
                "--file=" + backup_dir + "/schema.sql",
            ],
            pg_env,
            cwd=work,
            deadline=min(deadline, time.monotonic() + 30),
        )
        after = await asyncio.to_thread(independent_snapshot, connect, run_id)
        if before != after:
            raise GateError("restored_rows_changed")
        await stage("restored-replay")
        await stage("restored-verify")
        reopened = await asyncio.to_thread(independent_snapshot, connect, run_id)
        if before != reopened:
            raise GateError("reopened_rows_changed")
        validate_originals(reopened, work, run_id)
        native.write_json(
            artifacts / "restore-proof.json",
            {
                "schemaVersion": 1,
                "codec": "json_sorted_keys_compact_ascii",
                "beforeDigest": snapshot_digest(before),
                "afterDigest": snapshot_digest(after),
                "reopenedDigest": snapshot_digest(reopened),
                "rowsIdentical": True,
                "schemas": 2,
                "originalReceipts": 1066,
                "newOperationAcceptances": 0,
            },
        )
        room_after = await inventory()
        if room_after != room_before:
            raise GateError("sfu_inventory_changed")
        native.write_json(
            artifacts / "sfu-inventory.json",
            {
                "schemaVersion": 1,
                "before": room_before,
                "at1000Dormant": room_dormant,
                "after": room_after,
                "roomsAllocated": 0,
                "mediaQualified": False,
            },
        )
        if groups != set(CASE_NAMES):
            raise GateError("missing_named_assertions")
        for name in PROOFS:
            native.safe_copy(work / name, artifacts / name, exclusions, maximum=MAX_PROOF_BYTES)
        for path in sorted(work.glob("workload-*-before.json")) + sorted(
            work.glob("workload-*-restored.json")
        ):
            native.safe_copy(path, artifacts / path.name, exclusions, maximum=MAX_PROOF_BYTES)
        native.safe_copy(dump, artifacts / dump.name, exclusions, maximum=MAX_EVIDENCE_BYTES)
        native.safe_copy(
            script, artifacts / "pg_workload_cases.js", exclusions, maximum=MAX_PROOF_BYTES
        )
    except BaseException as error:  # noqa: BLE001 - preserve first failure while attempting every independently owned cleanup.
        first = error
    finally:
        children.deadline = final
        failed = False
        try:
            children.close()
        except BaseException:  # noqa: BLE001 - preserve first failure while attempting every independently owned cleanup.
            failed = True
        settled = owned_children_settled(children)
        if not settled:
            failed = True
        if first is not None:
            try:
                native.write_json(
                    artifacts / "failure-context.json",
                    {
                        "schemaVersion": 1,
                        "status": "failed",
                        "errorType": "GateError"
                        if isinstance(first, GateError)
                        else "DependencyError",
                        "code": first.code if isinstance(first, GateError) else "gate_failed",
                        "frames": [
                            {"file": Path(fr.filename).name, "line": fr.lineno}
                            for fr in traceback.extract_tb(first.__traceback__)
                            if Path(fr.filename).name == "p2_workload_check.py"
                        ][-4:],
                        "children": [
                            {
                                "name": c.output_directory.name,
                                "pid": c.pid,
                                "returncode": c.returncode,
                            }
                            for c in children.children
                        ],
                    },
                )
                for mode in MODES:
                    path = work / ("workload-failure-" + mode + ".json")
                    if path.exists():
                        native.safe_copy(path, artifacts / path.name, exclusions, maximum=4096)
            except BaseException:  # noqa: BLE001 - preserve first failure while attempting every independently owned cleanup.
                failed = True
        if first is not None:
            # Retain available closed synthetic proofs before deleting quiescent private inputs.
            partial = [work / name for name in PROOFS]
            partial += sorted(work.glob("workload-*-before.json")) + sorted(
                work.glob("workload-*-restored.json")
            )
            if script.exists():
                partial.append(script)
            for path in partial:
                try:
                    if path.exists():
                        proof_target = artifacts / (
                            "pg_workload_cases.js" if path == script else path.name
                        )
                        if proof_target.exists():
                            if bounded_read(proof_target) != bounded_read(path):
                                raise GateError("diagnostic_identity_mismatch")
                        else:
                            native.safe_copy(
                                path, proof_target, exclusions, maximum=MAX_PROOF_BYTES
                            )
                except BaseException:  # noqa: BLE001 - diagnostics preserve the first failure and cannot skip cleanup.
                    failed = True
        if sfu is not None:
            try:
                close_seconds = min(3, native.remaining(final))
                await asyncio.wait_for(sfu.aclose(), timeout=close_seconds)
            except BaseException:  # noqa: BLE001 - preserve first failure while attempting every independently owned cleanup.
                failed = True
        # A reaped host docker CLI cannot prove an interrupted container exec settled.
        docker_uncertain = any(
            c.output_directory.name in {"backup-directory", "backup-dump", "backup-restore"}
            and (
                c.returncode != 0
                or c.cleanup_failed
                or getattr(c, "group_settled", False) is not True
            )
            for c in children.children
        )
        if docker_uncertain:
            failed = True
        control_closed = controls.close()
        if not control_closed:
            failed = True
        try:
            native.write_json(artifacts / "control-connection-proof.json", controls.proof())
        except BaseException:  # noqa: BLE001 - retain original failure and continue independent cleanup.
            failed = True
        if installed and settled and control_closed and not docker_uncertain:
            try:
                await stage("cleanup", final)
            except BaseException:  # noqa: BLE001 - preserve first failure while attempting every independently owned cleanup.
                failed = True
        elif installed:
            failed = True
        if backup and settled and not docker_uncertain:
            try:
                await asyncio.to_thread(
                    children.call,
                    "backup-remove",
                    [docker, "exec", container, "rm", "-rf", "--", backup_dir],
                    core.base_environment(),
                    cwd=work,
                    deadline=final,
                )
            except BaseException:  # noqa: BLE001 - preserve first failure while attempting every independently owned cleanup.
                failed = True
        elif backup:
            failed = True
        try:
            children.close()
        except BaseException:  # noqa: BLE001 - preserve first failure while attempting every independently owned cleanup.
            failed = True
        captures: list[dict[str, Any]] = []
        for owned_child in children.children:
            for stream in ("stdout", "stderr"):
                try:
                    data = bounded_read(
                        owned_child.output_directory / (stream + ".bin"), 8192, allow_empty=True
                    )
                    if any(secret.encode() in data for secret in capture_exclusions if secret):
                        raise GateError("private_artifact")
                    name = "capture-" + owned_child.output_directory.name + "-" + stream + ".bin"
                    with os.fdopen(
                        os.open(
                            artifacts / name,
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                            0o600,
                        ),
                        "wb",
                    ) as captured:
                        captured.write(data)
                    captures.append(
                        {
                            "file": name,
                            "bytes": len(data),
                            "sha256": hashlib.sha256(data).hexdigest(),
                        }
                    )
                except BaseException:  # noqa: BLE001 - preserve primary and attempt all safe captures before work removal.
                    failed = True
        try:
            native.write_json(
                artifacts / "owned-children.json",
                {
                    "schemaVersion": 1,
                    "commands": [
                        {
                            "name": c.output_directory.name,
                            "pid": c.pid,
                            "returncode": c.returncode,
                            "groupSettled": getattr(c, "group_settled", False),
                            "cleanupFailed": c.cleanup_failed,
                        }
                        for c in children.children
                    ],
                    "captures": captures,
                    "captureBytes": sum(c["bytes"] for c in captures),
                    "allOwnedChildrenSettled": owned_children_settled(children),
                },
            )
        except BaseException:  # noqa: BLE001 - capture metadata cannot replace a primary or skip remaining cleanup.
            failed = True
        cleanup["cleanup_complete"] = not failed and owned_children_settled(children)
        if cleanup["cleanup_complete"]:
            try:
                native.remaining(final)
                owned = json_file(work / "workload-owned-work.json")
                if (
                    not native.exact(
                        owned,
                        {"schemaVersion": 1, "runId": run_id, "schemas": list(schemas(run_id))},
                    )
                    or work.parent != scratch.resolve()
                    or work.is_symlink()
                ):
                    raise GateError("unsafe_owned_work")
                shutil.rmtree(work)
                native.remaining(final)
            except BaseException as error:  # noqa: BLE001 - preserve first failure while attempting every independently owned cleanup.
                cleanup["cleanup_complete"] = False
                first = first or error
        if not cleanup["cleanup_complete"]:
            try:
                native.write_json(
                    artifacts / "owned-work-retained.json",
                    {
                        "schemaVersion": 1,
                        "directory": str(work.relative_to(root)),
                        "schemas": list(schemas(run_id)),
                        "cleanupComplete": False,
                    },
                )
            except BaseException:  # noqa: BLE001 - preserve first failure while attempting every independently owned cleanup.
                cleanup["cleanup_complete"] = False
        if failed and first is None:
            first = GateError("cleanup_incomplete")
    if first is not None:
        raise first
    if source_snapshot(root) != frozen:
        raise GateError("source_changed_during_measurement")
    if children.count != EXPECTED_CHILDREN or [
        c.output_directory.name for c in children.children
    ] != list(NORMAL_COMMANDS):
        raise GateError("unexpected_child_count")
    evidence_index(artifacts)
    index_sha = hashlib.sha256(bounded_read(artifacts / "retained-index.json")).hexdigest()
    validate_evidence_index(artifacts, index_sha)
    return validated_report(
        json.dumps(
            {
                "schema_version": 1,
                "status": "passed",
                "mode": MODE,
                "tests": 24,
                "passed": 24,
                "cases": list(CASE_NAMES),
                "workload_seed": 39,
                "child_commands": children.count,
                "capacity_inputs": 64,
                "dormant_inputs": 1002,
                "operation_acceptances": 68,
                "owned_sql_graphs": 1,
                "owned_sql_waiters": 2,
                "rooms_allocated": 0,
                "agents_allocated": 0,
                "cleanup_complete": True,
                "node_version": "24.22.2",
                "capacity_claimed": False,
                "duration_seconds": time.monotonic() - started,
                "retained_index_sha256": index_sha,
            }
        ).encode()
    )


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise GateError("invalid_arguments")


def validate_manifest(raw: bytes) -> dict[str, Any]:
    value = native.decode(raw, maximum=32768)
    if not native.exact(value, EXPECTED_MANIFEST):
        raise GateError("invalid_manifest")
    return value


def plan(root: Path = ROOT) -> dict[str, Any]:
    path = root / "projects/channel-continuity/workloads/bounded-v1.json"
    raw = storage.source_bytes(path)
    manifest = validate_manifest(raw)
    return {
        "schema_version": 1,
        "status": "not_started",
        "mode": MODE,
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "workload_seed": 39,
        "seed_policy": "fixed_public_schedule_39_with_separate_private_auth_nonce",
        "cases": manifest["cases"],
        "bounds": manifest["bounds"],
        "normal_commands": manifest["normalCommands"],
        "measurement_started": False,
        "capacity_claimed": False,
    }


def target_path(root: Path, path: Path) -> Path:
    if (
        path.is_absolute()
        or path.parts[:3] != (".local", "validation", "p2-workload")
        or len(path.parts) != 4
        or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}\.json", path.name) is None
    ):
        raise GateError("unsafe_report_path")
    current = root
    for part in path.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise GateError("unsafe_report_path")
        current.mkdir(mode=0o700, exist_ok=True)
        if not current.is_dir() or current.stat().st_mode & 0o022:
            raise GateError("unsafe_report_path")
    target = current / path.name
    if (
        target.exists()
        or target.is_symlink()
        or target.with_name(target.stem + "-artifacts").exists()
    ):
        raise GateError("report_exists")
    return target


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    started = time.monotonic()
    cleanup = {"cleanup_complete": False}
    target = None
    try:
        parser = SafeParser(description=__doc__)
        parser.add_argument("--report", type=Path)
        parser.add_argument("--plan", action="store_true")
        args = parser.parse_args(argv)
        if args.plan:
            if args.report is not None:
                raise GateError("invalid_arguments")
            print(json.dumps(plan(root), sort_keys=True))
            return 0
        validate_manifest(
            storage.source_bytes(root / "projects/channel-continuity/workloads/bounded-v1.json")
        )
        target = target_path(
            root, args.report or Path(".local/validation/p2-workload/" + uuid4().hex + ".json")
        )
        artifacts = target.with_name(target.stem + "-artifacts")
        artifacts.mkdir(mode=0o700)
        result = asyncio.run(run(root, artifacts, started, cleanup))
    except (native.GateError, core.GateError) as error:
        result = {
            "schema_version": 1,
            "status": "failed",
            "mode": MODE,
            "code": error.code,
            "duration_seconds": time.monotonic() - started,
            **cleanup,
        }
    except BaseException:  # noqa: BLE001 - fixed diagnostics contain arbitrary dependency failures.
        result = {
            "schema_version": 1,
            "status": "failed",
            "mode": MODE,
            "code": "gate_failed",
            "duration_seconds": time.monotonic() - started,
            **cleanup,
        }
    try:
        if target is not None:
            native.write_json(target, result)
    except (OSError, GateError):
        result = {
            "schema_version": 1,
            "status": "failed",
            "mode": MODE,
            "code": "evidence_not_retained",
            **cleanup,
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
