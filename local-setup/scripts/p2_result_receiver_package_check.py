"""Fresh offline result-receiver package bridge; no actual PostgreSQL/media assertions.

Reuse the existing P2 installer and unchanged seventeen-command/eight-assertion
P3 builder. Four separately counted probes cover the selected new public ports.
Opt-in root-application mode adds seven fixed artifact/consumer roles.
Import and --plan allocate no resources. Actual storage/media gates run separately.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import io
import json
import os
import shutil
import stat
import sys
import tarfile
import tempfile
import time
import tomllib
import zipfile
from collections.abc import Callable
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TOTAL_SECONDS, CLEANUP_SECONDS = 360, 20
MAX_GROUPS, EXPECTED_GROUPS, MAX_CAPTURE, MAX_STREAM = 32, 25, 2097152, 65536
OUTER_ROLES = frozenset(
    {
        "compile",
        "pack",
        "install",
        "strict-consumer",
        "p2-result-types",
        "p2-result-codecs",
        "p3-result-types",
        "p3-result-execution",
    }
)
NESTED_ROLE_ORDER = (
    "build_p1",
    "build_p3",
    "build_p3",
    "rebuild_p3",
    "export",
    "install",
    "install",
    "install",
    "imports",
    "types",
    "baseline",
    "node_build",
    "npm_pack",
    "npm_install",
    "node_types",
    "imports",
    "node_example",
)
HELPER_TESTS = (
    "test_fixed_policy_completion.py",
    "test_completion.py",
    "test_fixed_policy_execution.py",
    "test_runner.py",
    "test_coordinator.py",
)
CONTRACTS = ("v1.json", "fixed-policy-v2.json", "result-receiver-v1.json")
ORIGIN_TEST_COUNTS = {
    "test_channel_policy_contracts.py": 19,
    "test_channel_policy_execution.py": 14,
    "test_channel_policy_completion.py": 8,
}
ORIGIN_CONTRACTS = ("channel-policy-v3.json",)
ROOT_APPLICATION_ROLES = (
    "app-build",
    "app-rebuild",
    "p2-python-build",
    "app-install",
    "app-check",
    "app-types",
    "app-execution",
)
ROOT_APPLICATION_TEST_COUNTS = {
    "test_p2_channel_origin_wire.py": 13,
    "test_p3_channel_origin.py": 18,
    "test_p3_channel_origin_http.py": 19,
    "test_p3_channel_origin_composition.py": 2,
    "test_channel_policy_discovery.py": 22,
    "test_channel_policy_current_result.py": 24,
    "test_channel_policy_current_result_producer.py": 43,
    "test_channel_policy_executor.py": 34,
    "test_channel_policy_worker_client.py": 20,
    "test_channel_policy_origin_router.py": 34,
    "test_channel_policy_jobs.py": 61,
    "test_channel_policy_public_clients.py": 21,
    "test_channel_policy_transport_canonical.py": 5,
    "test_channel_policy_owner_config.py": 22,
    "test_channel_policy_application.py": 33,
    "test_p2_current_case_bridge.py": 17,
    "test_p3_channel_receiver.py": 15,
    "test_channel_policy_cli.py": 22,
    "test_channel_policy_room_result_client.py": 25,
    "test_channel_policy_room_control.py": 15,
    "test_channel_policy_room_control_client.py": 14,
    "test_channel_policy_worker_current_result.py": 15,
    "test_channel_policy_current_result_context.py": 20,
    "test_channel_policy_native_models.py": 34,
    "test_channel_policy_native_prepare_http.py": 26,
    "test_channel_policy_current_result_http.py": 20,
    "test_channel_policy_native_worker_config.py": 26,
    "test_channel_policy_native_worker.py": 27,
    "test_channel_policy_native_room.py": 21,
    "test_channel_policy_native_room_admin.py": 12,
    "test_channel_policy_native_room_state.py": 14,
    "test_channel_policy_native_worker_process.py": 13,
    "test_channel_policy_operator_contract.py": 12,
    "test_channel_policy_operator_sms.py": 14,
    "test_channel_policy_operator_http.py": 12,
    "test_channel_policy_parent.py": 19,
}
ROOT_APPLICATION_HELPERS = (
    "local-setup/scripts/p2_channel_origin_wire.py",
    "local-setup/scripts/p3_channel_origin.py",
    "local-setup/scripts/p3_channel_origin_http.py",
    "local-setup/scripts/p3_channel_origin_host.py",
    "local-setup/scripts/p2_current_case_bridge.py",
    "local-setup/scripts/p3_channel_receiver.py",
)
ROOT_APPLICATION_INPUTS = (
    tuple("tests/" + n for n in ROOT_APPLICATION_TEST_COUNTS) + ROOT_APPLICATION_HELPERS
)
ROOT_APPLICATION_PAYLOADS, P2_PYTHON_PAYLOADS = 86, 9
NATIVE_SDK_PAYLOADS, NATIVE_CLIENT_DESCENDANTS = 124, 2
APPLICATION_CHILD_RETURNS = {
    "test_original_venv_path_fixed_role_environment_and_real_reap": (0,),
    "test_sdk_close_observation_is_terminal_for_admission_before_actual_reap": (0,),
    "test_late_spawn_after_cancel_remains_owned_and_stop_reaps_it": (0, -15),
    "test_partial_observer_allocation_retains_real_child_and_stop_backfills_pipe": (0,),
    "test_wrong_order_ready_never_becomes_sdk_ready_or_prepare_ready": (0,),
    "test_malformed_stdout_is_private_and_still_drains_and_reaps": (0,),
    "test_stderr_excess_is_not_retained_and_graceful_stop_still_reaps": (0,),
    "test_start_timeout_cannot_drop_held_actual_spawn": (0, -15),
    "test_early_exit_wakes_readiness_without_fabricating_prepare_fact": (2,),
    "test_held_signal_cleanup_retains_owner_until_actual_exit": (0,),
}


def modes(*, channel_origin: bool, root_application: bool = False) -> tuple[bool, bool]:
    require(type(channel_origin) is bool and type(root_application) is bool, "invalid_input")
    return channel_origin or root_application, root_application


def outer_roles(*, root_application: bool = False) -> frozenset[str]:
    require(type(root_application) is bool, "invalid_input")
    return OUTER_ROLES | (frozenset(ROOT_APPLICATION_ROLES) if root_application else frozenset())


def input_names(*, channel_origin: bool = False, root_application: bool = False) -> tuple[str, ...]:
    channel_origin, root_application = modes(
        channel_origin=channel_origin, root_application=root_application
    )
    tests = HELPER_TESTS + (tuple(ORIGIN_TEST_COUNTS) if channel_origin else ())
    contracts = CONTRACTS + (ORIGIN_CONTRACTS if channel_origin else ())
    return (
        tuple("projects/delegation-reliability/tests/" + name for name in tests)
        + tuple("contracts/delegation/" + name for name in contracts)
        + (ROOT_APPLICATION_INPUTS if root_application else ())
    )


SAFE_CODES = frozenset(
    {
        "invalid_input",
        "missing_setup",
        "invalid_artifact",
        "consumer_failed",
        "child_budget",
        "capture_budget",
        "source_changed",
        "cleanup_incomplete",
        "retention_failed",
        "package_failed",
        "deadline_exceeded",
    }
)


class PackageError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code if type(code) is str and code in SAFE_CODES else "package_failed"
        super().__init__(self.code)


def require(value: object, code: str = "invalid_artifact") -> None:
    if value is not True:
        raise PackageError(code)


def plan(*, channel_origin: bool = False, root_application: bool = False) -> dict[str, Any]:
    channel_origin, root_application = modes(
        channel_origin=channel_origin, root_application=root_application
    )
    result = {
        "schema_version": 1,
        "mode": package_mode(channel_origin=channel_origin, root_application=root_application),
        "status": "planned",
        "total_seconds": TOTAL_SECONDS,
        "cleanup_seconds": CLEANUP_SECONDS,
        "max_process_groups": MAX_GROUPS,
        "expected_process_groups": EXPECTED_GROUPS + (7 if root_application else 0),
        "aggregate_capture_bytes": MAX_CAPTURE,
        "max_stream_bytes": MAX_STREAM,
        "retained_maximum_files": 2048,
        "retained_maximum_bytes": 16777216,
        "retained_index_exclusion": "root retained-index.json only",
        "p2_direct_groups": 6,
        "p3_unchanged_builder_groups": 17,
        "p3_builder_roles": list(NESTED_ROLE_ORDER),
        "p3_new_probe_groups": 2,
        "p3_offline_assertions": 8,
        "p3_installed_fake_port_tests": 20
        + (sum(ORIGIN_TEST_COUNTS.values()) if channel_origin else 0),
        "p3_installed_legacy_fake_port_tests": 20,
        "p3_installed_origin_fake_port_tests": sum(ORIGIN_TEST_COUNTS.values())
        if channel_origin
        else 0,
        "p3_origin_test_counts": dict(ORIGIN_TEST_COUNTS) if channel_origin else {},
        "p2_codec_negative_cases": 9,
        "payloads": {"p2": 124, "p3_python": 39, "p1_python": 77, "specialist_npm": 32},
        "package_manifests_separate": True,
        "manifest_parity": "semantic_source_archive; raw_archive_install",
        "source_actual_assertions": 0,
        "installed_actual_assertions": 0,
        "database_calls": 0,
        "rtc_rooms": 0,
        "provider_calls": False,
        "platform": "darwin_arm64",
        "python": "3.14.10",
        "node": "24.22.2",
        "typescript": "7.0.2",
        "sdk": "1.8.11",
        "psycopg": "3.3.8",
        "helper_tests": list(HELPER_TESTS) + (list(ORIGIN_TEST_COUNTS) if channel_origin else []),
        "contracts": list(CONTRACTS) + (list(ORIGIN_CONTRACTS) if channel_origin else []),
        "channel_origin": channel_origin,
        "p2_operation_only_probe": channel_origin,
        "prerequisites": "frozen cached dependencies only; no credentials or provider configuration",
    }
    if root_application:
        result.update(
            root_application=True,
            root_application_groups=7,
            builder_process_groups=32,
            test_child_process_groups=10,
            total_process_groups=42,
            max_total_process_groups=42,
            process_group_scope="32 builder commands plus 10 explicitly recorded test children",
            root_application_child_fixture_bounds={
                "slots": 10,
                "records": 40,
                "record_bytes": 512,
                "registry_bytes": 20480,
                "go_seconds": 1,
                "child_lifetime_seconds": 5,
                "parent_loss_seconds": 0.5,
            },
            root_application_roles=list(ROOT_APPLICATION_ROLES),
            root_application_test_counts=dict(ROOT_APPLICATION_TEST_COUNTS),
            root_application_installed_fake_port_tests=sum(ROOT_APPLICATION_TEST_COUNTS.values()),
            root_application_inputs=list(ROOT_APPLICATION_INPUTS),
            root_application_payloads=ROOT_APPLICATION_PAYLOADS,
            p2_python_payloads=P2_PYTHON_PAYLOADS,
            root_application_extra="channel-demo",
            root_application_dependencies="fresh P1/P2/P3 wheels and cached frozen SDK dependencies",
            root_application_native_fixtures={
                "public_npm_sdk_payloads": NATIVE_SDK_PAYLOADS,
                "asset_manifest_only": True,
                "native_prepare_node_client_descendants": NATIVE_CLIENT_DESCENDANTS,
                "descendant_process_group": "app-execution",
                "node_version": "24.22.2",
                "checkout_product_fallback": False,
            },
        )
    return result


def package_mode(*, channel_origin: bool, root_application: bool = False) -> str:
    channel_origin, root_application = modes(
        channel_origin=channel_origin, root_application=root_application
    )
    if root_application:
        return "offline_root_application_package_bridge"
    return (
        "offline_channel_origin_package_bridge"
        if channel_origin
        else "offline_result_package_bridge"
    )


def combined_budget(
    outer_count: int,
    outer_capture: int,
    outer_reserved: int,
    nested_count: int,
    nested_capture: int,
    nested_reserved: int,
    *,
    new_outer_reservation: int = 0,
) -> None:
    values = (
        outer_count,
        outer_capture,
        outer_reserved,
        nested_count,
        nested_capture,
        nested_reserved,
        new_outer_reservation,
    )
    require(all(type(v) is int and v >= 0 for v in values), "child_budget")
    require(outer_count + nested_count <= MAX_GROUPS, "child_budget")
    require(
        outer_capture + outer_reserved + nested_capture + nested_reserved + new_outer_reservation
        <= MAX_CAPTURE,
        "capture_budget",
    )


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def private_parents(directory: Path) -> None:
    """Create each missing level under a verified private anchor; never repair old paths."""
    require(directory.is_absolute(), "invalid_input")
    missing: list[Path] = []
    anchor = directory
    try:
        while True:
            try:
                anchor.lstat()
                break
            except FileNotFoundError:
                require(anchor.parent != anchor, "invalid_input")
                missing.append(anchor)
                anchor = anchor.parent

        def check(path: Path) -> None:
            info = path.lstat()
            require(
                stat.S_ISDIR(info.st_mode)
                and stat.S_IMODE(info.st_mode) == 0o700
                and info.st_uid == os.geteuid()
                and not path.is_symlink()
                and path.resolve() == path,
                "invalid_input",
            )

        check(anchor)
        for path in reversed(missing):
            try:
                path.mkdir(mode=0o700)
            except FileExistsError:
                pass  # A concurrent creation still has to satisfy the same private contract.
            check(path)
    except (OSError, RuntimeError):
        raise PackageError("invalid_input") from None


def write(path: Path, raw: bytes) -> None:
    require(type(raw) is bytes and len(raw) <= 8388608)
    private_parents(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def helpers(root: Path) -> tuple[ModuleType, ModuleType, ModuleType]:
    # Host-only tooling imports. These paths are never forwarded to a product consumer.
    scripts = root / "local-setup/scripts"
    require(scripts.is_dir(), "missing_setup")
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(scripts))
    return (
        importlib.import_module("p2_standalone_check"),
        importlib.import_module("p3_document_package"),
        importlib.import_module("p3_package_check"),
    )


def copy_inputs(
    root: Path,
    application: Path,
    retained: Path,
    *,
    channel_origin: bool = False,
    root_application: bool = False,
) -> dict[str, dict[str, object]]:
    inventory: dict[str, dict[str, object]] = {}
    names = input_names(channel_origin=channel_origin, root_application=root_application)
    for name in names:
        source = root / name
        require(source.is_file() and not source.is_symlink())
        raw = source.read_bytes()
        require(0 < len(raw) <= 262144)
        write(application / name, raw)
        write(retained / "inputs" / name, raw)
        inventory[name] = {"bytes": len(raw), "sha256": digest(raw)}
    return inventory


def wheel_parity(raw: bytes, expected: dict[str, bytes], prefix: str, count: int) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)))
        actual = {name: archive.read(name) for name in names if name.startswith(prefix + "/")}
    require(len(actual) == count and actual == expected)
    return {
        "payload_count": count,
        "payloads": {name: digest(body) for name, body in sorted(actual.items())},
    }


def npm_parity(
    raw: bytes, payloads: dict[str, bytes], source_manifest: bytes
) -> tuple[dict[str, Any], bytes]:
    entries: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for member in archive:
            if member.isdir():
                continue
            require(
                member.isfile()
                and member.name.startswith("package/")
                and member.name not in entries
                and not member.issym()
                and not member.islnk()
            )
            stream = archive.extractfile(member)
            require(stream is not None and 0 <= member.size <= 8388608)
            assert stream is not None
            entries[member.name] = stream.read()
    require(set(entries) == {"package/" + name for name in payloads} | {"package/package.json"})
    require(all(entries["package/" + name] == body for name, body in payloads.items()))
    # pnpm rewrites manifest formatting. Bind both original bytes and exact JSON value,
    # then require installed manifest bytes to match this actual archive manifest.
    manifest = entries["package/package.json"]
    require(json_bytes(json.loads(manifest)) == json_bytes(json.loads(source_manifest)))
    return (
        {
            "payload_count": len(payloads),
            "manifest_semantic_equal": True,
            "source_manifest_sha256": digest(source_manifest),
            "archive_manifest_sha256": digest(manifest),
            "payloads": {name: digest(body) for name, body in sorted(payloads.items())},
        },
        manifest,
    )


def source_snapshot(
    root: Path, *, channel_origin: bool = False, root_application: bool = False
) -> dict[str, str]:
    channel_origin, root_application = modes(
        channel_origin=channel_origin, root_application=root_application
    )
    names: set[Path] = {
        root / n
        for n in (
            "uv.lock",
            "pnpm-lock.yaml",
            "pyproject.toml",
            "package.json",
            "projects/channel-continuity/package.json",
            "projects/channel-continuity/README.md",
            "projects/channel-continuity/STARTER.md",
            "projects/channel-continuity/starter/bounded-v1.json",
            "local-setup/scripts/p2_standalone_check.py",
            "local-setup/scripts/p3_package_check.py",
            "local-setup/scripts/p3_document_package.py",
            "local-setup/scripts/p2_result_receiver_package_check.py",
            "projects/channel-continuity/tsconfig.json",
            "projects/channel-continuity/tsconfig.examples.json",
            "projects/channel-continuity/tsconfig.starter.json",
            "projects/channel-continuity/tests/fixtures/installed-starter-consumer.ts",
            "projects/channel-continuity/tests/fixtures/starter-p1-consumer.ts",
            "projects/agent-continuity/python/pyproject.toml",
            "projects/agent-continuity/python/README.md",
            "projects/delegation-reliability/python/pyproject.toml",
            "projects/delegation-reliability/python/README.md",
            "projects/delegation-reliability/specialist-ts/package.json",
            "projects/delegation-reliability/specialist-ts/README.md",
        )
    }
    for folder, patterns in (
        ("projects/channel-continuity/src", ("*.ts",)),
        ("projects/channel-continuity/examples", ("*.ts",)),
        ("projects/agent-continuity/python/src", ("*.py", "*.typed")),
        ("projects/delegation-reliability/python/src", ("*.py", "*.typed")),
        ("projects/delegation-reliability/specialist-ts/src", ("*.ts",)),
        ("projects/delegation-reliability/specialist-ts/examples", ("*.mjs",)),
    ):
        for pattern in patterns:
            names.update((root / folder).rglob(pattern))
    names.update(
        root / name
        for name in input_names(channel_origin=channel_origin, root_application=root_application)
    )
    if root_application:
        names.update(root / name for name in application_payload(root))
        names.update(root / name for name in application_source_tests(root))
        names.update((root / "services").rglob("*.md"))
        names.update((root / "services").rglob("py.typed"))
        names.update(
            root / n
            for n in (
                "README.md",
                "projects/channel-continuity/python/pyproject.toml",
                "projects/channel-continuity/python/README.md",
            )
        )
        for pattern in ("*.py", "py.typed"):
            names.update((root / "projects/channel-continuity/python/src").rglob(pattern))
    result: dict[str, str] = {}
    for path in sorted(names):
        require(path.is_file() and not path.is_symlink())
        result[str(path.relative_to(root))] = digest(path.read_bytes())
    return result


P2_CONSUMER = r"""import assert from 'node:assert/strict';
import {readFileSync,realpathSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {sep} from 'node:path';
import {Socket,Server} from 'node:net';
import type {ChannelOutbox} from '@livekit-ecosystem/channel-continuity/outbox';
import type {ChannelInbox} from '@livekit-ecosystem/channel-continuity/postgres';
import type {CurrentCasePort} from '@livekit-ecosystem/channel-continuity/rehydration';
import type {ChannelResultReceiver,ChannelResultReader} from '@livekit-ecosystem/channel-continuity/result-receiver';
import type {ResultRouteBinding,P1ResultIntent,P1ResultReceipt} from '@livekit-ecosystem/channel-continuity/result-receiver-types';
const connect=Socket.prototype.connect,listen=Server.prototype.listen;
const denied=()=>{throw Error('import_started_IO');};
Socket.prototype.connect=denied;Server.prototype.listen=denied;
let api:typeof import('@livekit-ecosystem/channel-continuity/result-receiver');
let browser:typeof import('@livekit-ecosystem/channel-continuity/result-receiver-types');
try{api=await import('@livekit-ecosystem/channel-continuity/result-receiver');browser=await import('@livekit-ecosystem/channel-continuity/result-receiver-types');}finally{Socket.prototype.connect=connect;Server.prototype.listen=listen;}
function constructors(outbox:ChannelOutbox,inbox:ChannelInbox,cases:CurrentCasePort,receiverId:string,route:ResultRouteBinding,publisherToken:string):[ChannelResultReceiver,ChannelResultReader]{return[new api.ChannelResultReceiver(outbox,{receiverId,bindings:[{...route,publisherToken}]}),new api.ChannelResultReader(outbox,inbox,cases,{receiverId,bindings:[route]})];}
async function signatures(receiver:ChannelResultReceiver,reader:ChannelResultReader,token:string,intent:P1ResultIntent):Promise<P1ResultReceipt|null>{const accepted=await receiver.accept(token,intent);await reader.native(token,intent.delivery_id);await receiver.find(token,intent);return accepted;}
void constructors;void signatures;
const root=realpathSync(process.cwd());
for(const name of ['@livekit-ecosystem/channel-continuity/result-receiver','@livekit-ecosystem/channel-continuity/result-receiver-types'])assert.ok(realpathSync(fileURLToPath(import.meta.resolve(name))).startsWith(root+sep));
assert.equal(browser.RESULT_INTENT_BYTES,16384);assert.equal(browser.RESULT_BODY_BYTES,8192);
const wire=JSON.parse(readFileSync(process.argv[2]!,'utf8')) as {intent_canonical:string;receipt:unknown;notice:string;negative_intents:{name:string;canonical:string}[]};
const intent=api.parseResultIntent(wire.intent_canonical),receipt=api.resultReceipt(wire.receipt);
assert.equal(api.encodeResultIntent(intent),wire.intent_canonical);api.matchResultReceipt(intent,receipt);
assert.equal(wire.notice,browser.RESULT_NOTICE);assert.equal(wire.negative_intents.length,9);
for(const invalid of wire.negative_intents)assert.throws(()=>api.parseResultIntent(invalid.canonical),api.ResultReceiverError);
assert.notEqual(createHash('sha256').update(wire.notice).digest('hex'),receipt.result_sha256);
console.log(JSON.stringify({schema_version:1,status:'passed',private_npm_paths:true,imports_no_IO:true,canonical_equal:true,negative_cases:wire.negative_intents.length,original_result_sha:receipt.result_sha256,notice_hash_separate:true}));
"""

P3_TYPES = """from continuity_lab.delivery_api import DeliveryPort
from delegation_reliability import (FixedPolicyDeliveryClient, FixedPolicyResultReadPort,
    ResultReceiverPort, DeliveryBinding, CompletionError)
from delegation_reliability.contracts import Scope
from delegation_reliability.security import EvidenceRecord

def configured(results: FixedPolicyResultReadPort, deliveries: DeliveryPort,
               receiver: ResultReceiverPort, scope: Scope,
               evidence: tuple[EvidenceRecord, ...], bindings: tuple[DeliveryBinding, ...]) -> FixedPolicyDeliveryClient:
    return FixedPolicyDeliveryClient(results=results, deliveries=deliveries, receiver=receiver,
        scope=scope, evidence=evidence, bindings=bindings)

def finite_error() -> CompletionError:
    return CompletionError("not_eligible")
"""

P3_EXECUTION = """from pathlib import Path
import asyncio,json,socket,sys,unittest
from unittest.mock import patch
from importlib.metadata import version

def denied(*args: object, **kwargs: object) -> object:
    raise AssertionError("import_started_IO")
with patch.object(socket.socket,"connect",denied),patch.object(socket.socket,"bind",denied),patch.object(asyncio,"create_task",denied):
    import continuity_lab.delivery_api as p1
    import continuity_lab.work_api as work
    import delegation_reliability as p3
    import delegation_reliability.completion as completion
    import delegation_reliability.native_policy as native
for module in (p1,work,p3,completion,native):
    assert module.__file__ is not None and Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
assert version("livekit-agents")=="1.8.11" and version("psycopg")=="3.3.8"
root=Path(__file__).resolve().parent
suite=unittest.defaultTestLoader.discover(str(root/"projects/delegation-reliability/tests"),pattern="test_fixed_policy_completion.py")
assert suite.countTestCases()==20
result=unittest.TextTestRunner(verbosity=1).run(suite)
assert result.wasSuccessful() and result.testsRun==20 and not result.skipped
for name,module in tuple(sys.modules.items()):
    if name.split(".")[0] in {"continuity_lab","delegation_reliability"}:
        assert module.__file__ is not None and Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
print(json.dumps({"schema_version":1,"status":"passed","installed_prefix_paths":True,"imports_no_IO":True,"fake_port_tests":result.testsRun,"sdk_version":"1.8.11","provider_calls":False,"database_calls":0}))
"""


P3_CHANNEL_TYPES = """from continuity_lab.execution_api import ExecutionPort
from continuity_lab.work_api import TaskExecutionPort
from delegation_reliability import (CaseAuthorityPort, ChannelPolicyCoordinator,
    ChannelPolicyRunner, ChannelPolicyDeliveryClient, ChannelPolicyResultReadPort,
    ChannelPolicyRequest, ChannelPolicySubmission, ChannelPolicyExecutionView,
    FixedPolicyInvocationPort)

def channel_coordinator(work: TaskExecutionPort, cases: CaseAuthorityPort,
                        scope: Scope) -> ChannelPolicyCoordinator:
    coordinator = ChannelPolicyCoordinator(executions=work, case_authority=cases, scope=scope)
    configured_scope: Scope = coordinator.scope
    assert configured_scope == scope
    return coordinator

def channel_runner(execution: ExecutionPort, cases: CaseAuthorityPort, scope: Scope,
                   owner: str, specialist: FixedPolicyInvocationPort,
                   evidence: tuple[EvidenceRecord, ...]) -> ChannelPolicyRunner:
    return ChannelPolicyRunner(executions=execution, case_authority=cases, scope=scope,
        owner_id=owner, specialist=specialist, evidence=evidence)

def channel_delivery(results: ChannelPolicyResultReadPort, deliveries: DeliveryPort,
                     receiver: ResultReceiverPort, scope: Scope,
                     evidence: tuple[EvidenceRecord, ...],
                     bindings: tuple[DeliveryBinding, ...]) -> ChannelPolicyDeliveryClient:
    return ChannelPolicyDeliveryClient(results=results, deliveries=deliveries,
        receiver=receiver, scope=scope, evidence=evidence, bindings=bindings)

async def channel_methods(coordinator: ChannelPolicyCoordinator, runner: ChannelPolicyRunner,
                          request: ChannelPolicyRequest, work_id: str) -> ChannelPolicyExecutionView:
    accepted: ChannelPolicySubmission = await coordinator.accept(request)
    await coordinator.submit(request)
    await coordinator.find(request.delegation_id)
    await coordinator.get(accepted.view.record.work_id)
    await runner.run_once(work_id, "channel_run")
    reader: ChannelPolicyResultReadPort = runner
    return await reader.inspect(work_id)
"""


def p2_consumer(*, channel_origin: bool = False) -> str:
    require(type(channel_origin) is bool, "invalid_input")
    if not channel_origin:
        return P2_CONSUMER
    imported = "import type {OperationClientConfig,OperationClientBinding} from '@livekit-ecosystem/channel-continuity/starter';\n"
    probe = """const starter=await import('@livekit-ecosystem/channel-continuity/starter');
const binding:OperationClientBinding={alias:'origin',accountScope:{tenantId:'tenant_origin',accountId:'account_origin'},caseId:'case_origin',conversationId:'conversation_origin',senderId:'native_origin',operationBearer:'a'.repeat(43)};
const config:OperationClientConfig={schemaVersion:1,profileId:'00000000-0000-4000-8000-000000000001',endpoint:{host:'127.0.0.1',port:9},bindings:[binding]};
const client=new starter.ExternalOperationClient(config);
assert.equal(client.capabilities,'stable_idempotency_and_lookup');
assert.deepEqual(client.metrics(),{active:0,closing:false});
assert.throws(()=>new starter.ExternalOperationClient({...config,endpoint:{host:'127.0.0.1',port:0}}),starter.StarterError);
await client.close();assert.deepEqual(client.metrics(),{active:0,closing:true});
await assert.rejects(client.preflight(binding.alias,new AbortController().signal),starter.StarterError);
"""
    result = P2_CONSUMER.replace(
        ";}finally{Socket.prototype.connect=connect;",
        ";" + probe + "}finally{Socket.prototype.connect=connect;",
    )
    require(result != P2_CONSUMER)
    result = result.replace(
        "'@livekit-ecosystem/channel-continuity/result-receiver-types'])",
        "'@livekit-ecosystem/channel-continuity/result-receiver-types','@livekit-ecosystem/channel-continuity/starter'])",
    )
    result = result.replace(
        "notice_hash_separate:true}));", "notice_hash_separate:true,operation_only_config:true}));"
    )
    return imported + result


def p3_types(*, channel_origin: bool = False) -> str:
    require(type(channel_origin) is bool, "invalid_input")
    return P3_TYPES + (P3_CHANNEL_TYPES if channel_origin else "")


def p3_expected_report(*, channel_origin: bool = False) -> dict[str, Any]:
    require(type(channel_origin) is bool, "invalid_input")
    value: dict[str, Any] = {
        "schema_version": 1,
        "status": "passed",
        "installed_prefix_paths": True,
        "imports_no_IO": True,
        "fake_port_tests": 20 + (sum(ORIGIN_TEST_COUNTS.values()) if channel_origin else 0),
        "sdk_version": "1.8.11",
        "provider_calls": False,
        "database_calls": 0,
    }
    if channel_origin:
        value.update(
            legacy_fake_port_tests=20,
            origin_fake_port_tests=sum(ORIGIN_TEST_COUNTS.values()),
            origin_test_counts=dict(ORIGIN_TEST_COUNTS),
            readonly_scope=True,
        )
    return value


def p3_execution(*, channel_origin: bool = False) -> str:
    require(type(channel_origin) is bool, "invalid_input")
    if not channel_origin:
        return P3_EXECUTION
    result = P3_EXECUTION.replace(
        "    import delegation_reliability.native_policy as native\n",
        "    import delegation_reliability.native_policy as native\n"
        "    import delegation_reliability.channel_policy_contracts as channel_contracts\n"
        "    import delegation_reliability.channel_policy_execution as channel_execution\n",
    ).replace(
        "for module in (p1,work,p3,completion,native):",
        "for module in (p1,work,p3,completion,native,channel_contracts,channel_execution):",
    )
    start = "suite=unittest.defaultTestLoader.discover("
    end = "for name,module in tuple(sys.modules.items()):"
    before, tail = result.split(start, 1)
    _old_suite, after = tail.split(end, 1)
    suites = {"test_fixed_policy_completion.py": 20, **ORIGIN_TEST_COUNTS}
    replacement = """scope_property=vars(p3.ChannelPolicyCoordinator)["scope"]
assert isinstance(scope_property,property) and scope_property.fset is None
counts={}
for pattern,expected in SUITES.items():
    suite=unittest.defaultTestLoader.discover(str(root/"projects/delegation-reliability/tests"),pattern=pattern)
    assert suite.countTestCases()==expected
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    assert result.wasSuccessful() and result.testsRun==expected and not result.skipped
    counts[pattern]=result.testsRun
assert sum(counts.values())==61
""".replace("SUITES", repr(suites))
    result = before + replacement + end + after
    report_start = "print(json.dumps("
    prefix, _old_report = result.rsplit(report_start, 1)
    # The selected output is derived from enforced suite cardinalities, never from discovery alone.
    report = repr(p3_expected_report(channel_origin=True))
    result = prefix + report_start + report + "))\n"
    return result


def archive_name(value: str) -> None:
    require(type(value) is str)
    parts = PurePosixPath(value).parts
    require(
        type(value) is str
        and bool(value)
        and not value.startswith("/")
        and "\\" not in value
        and ":" not in value
        and "\x00" not in value
        and all(
            part not in {"", ".", "..", ".git", ".local", ".venv", "node_modules", "__pycache__"}
            and not part.startswith(".env")
            for part in value.rstrip("/").split("/")
        )
        and all(part not in {".", ".."} for part in parts)
    )


def application_payload(root: Path) -> dict[str, bytes]:
    """Inventory the exact declared root wheel payload without invoking its backend."""
    config = tomllib.loads((root / "pyproject.toml").read_text())
    project, setuptools = config["project"], config["tool"]["setuptools"]
    require(project["name"] == "livekit-agent-ecosystem" and project["version"] == "0.1.0")
    require(
        project["optional-dependencies"]["channel-demo"]
        == [
            "channel-continuity[native]==0.1.0",
            "delegation-reliability==0.1.0",
            "aiohttp==3.14.5",
            "h11==0.16.0",
            "livekit-api==1.2.2",
        ]
    )
    require(setuptools["packages"]["find"]["include"] == ["services*"])
    require(
        setuptools["package-data"]
        == {
            "services.channel_policy_demo": ["*.md", "py.typed"],
            "services.conversation_agent": ["assets/*.wav", "assets/*.json"],
        }
    )
    sources = set((root / "services").rglob("*.py"))
    for package, patterns in setuptools["package-data"].items():
        for pattern in patterns:
            sources.update((root / Path(package.replace(".", "/"))).glob(pattern))
    require(len(sources) == ROOT_APPLICATION_PAYLOADS)
    result: dict[str, bytes] = {}
    for path in sorted(sources):
        require(
            path.is_file()
            and not path.is_symlink()
            and path.resolve() == path
            and path.is_relative_to(root)
        )
        name = path.relative_to(root).as_posix()
        archive_name(name)
        raw = path.read_bytes()
        require(len(raw) <= 524288)
        result[name] = raw
    require("services/channel_policy_demo/py.typed" in result)
    return result


def application_source_tests(root: Path) -> dict[str, bytes]:
    """Default setuptools sdist test inputs, separately bound from selected suites."""
    require(not (root / "MANIFEST.in").exists())
    result: dict[str, bytes] = {}
    for folder in ("test", "tests"):
        for path in sorted((root / folder).glob("test*.py")):
            require(path.is_file() and not path.is_symlink() and path.resolve() == path)
            raw = path.read_bytes()
            require(len(raw) <= 524288)
            result[path.relative_to(root).as_posix()] = raw
    return result


def application_metadata(raw: bytes, root: Path) -> None:
    metadata = BytesParser().parsebytes(raw)
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    optional = project.get("optional-dependencies", {})
    declared = set(project.get("dependencies", [])) | {
        requirement + '; extra == "' + extra + '"'
        for extra, requirements in optional.items()
        for requirement in requirements
    }
    require(
        metadata.get("Name") == project["name"] and metadata.get("Version") == project["version"]
    )
    require(
        set(metadata.get_all("Provides-Extra", [])) == set(optional)
        and set(metadata.get_all("Requires-Dist", [])) == declared
    )
    require(
        set(metadata.get("Requires-Python", "").replace(" ", "").split(",")) == {">=3.14", "<3.15"}
    )
    require(raw.partition(b"\n\n")[2] == (root / "README.md").read_bytes())
    require(b"file://" not in raw)


def application_sdist(raw: bytes, root: Path, payloads: dict[str, bytes]) -> dict[str, bytes]:
    """Validate every tar entry before returning closed, extraction-safe relative files."""
    require(type(raw) is bytes and 0 < len(raw) <= 8388608)
    files: dict[str, bytes] = {}
    seen: set[str] = set()
    total = 0
    prefix = "livekit_agent_ecosystem-0.1.0"
    metadata = {
        "PKG-INFO",
        "setup.cfg",
        "livekit_agent_ecosystem.egg-info/PKG-INFO",
        "livekit_agent_ecosystem.egg-info/SOURCES.txt",
        "livekit_agent_ecosystem.egg-info/dependency_links.txt",
        "livekit_agent_ecosystem.egg-info/requires.txt",
        "livekit_agent_ecosystem.egg-info/top_level.txt",
    }
    source_tests = application_source_tests(root)
    allowed = set(payloads) | set(source_tests) | {"README.md", "pyproject.toml"} | metadata
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for position, member in enumerate(archive, 1):
            require(position <= 512)
            archive_name(member.name)
            name = member.name.rstrip("/")
            require(
                name not in seen
                and (member.isfile() or member.isdir())
                and not member.issym()
                and not member.islnk()
            )
            seen.add(name)
            require(name == prefix or name.startswith(prefix + "/"))
            relative = name.removeprefix(prefix).removeprefix("/")
            if member.isdir():
                require(not relative or any(path.startswith(relative + "/") for path in allowed))
                continue
            require(relative in allowed and 0 <= member.size <= 524288)
            total += member.size
            require(total <= 8388608)
            stream = archive.extractfile(member)
            require(stream is not None)
            assert stream is not None
            body = stream.read(member.size + 1)
            require(len(body) == member.size)
            files[relative] = body
    require({name: files.get(name) for name in payloads} == payloads)
    require({name: files.get(name) for name in source_tests} == source_tests)
    require(files.get("README.md") == (root / "README.md").read_bytes())
    require(files.get("pyproject.toml") == (root / "pyproject.toml").read_bytes())
    require(metadata <= set(files))
    require(files["PKG-INFO"] == files["livekit_agent_ecosystem.egg-info/PKG-INFO"])
    application_metadata(files["PKG-INFO"], root)
    # The manifest must describe only the same closed source tree. No workspace path
    # or ambient file may be smuggled into the rebuild through generated metadata.
    sources = files["livekit_agent_ecosystem.egg-info/SOURCES.txt"].decode().splitlines()
    require(
        len(sources) == len(set(sources)) and set(sources) == set(files) - {"PKG-INFO", "setup.cfg"}
    )
    return files


def extract_application(files: dict[str, bytes], target: Path) -> None:
    require(not target.exists() and not target.is_symlink(), "invalid_input")
    for name, raw in sorted(files.items()):
        archive_name(name)
        write(target / name, raw)


def application_wheel(
    path: Path, member: Path, distribution: str, expected: dict[str, bytes], packages: ModuleType
) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= 8388608)
    packages._wheel(path, member, distribution, expected)
    with zipfile.ZipFile(path) as archive:
        metadata = archive.read(distribution + "-0.1.0.dist-info/METADATA")
    return {
        "payload_count": len(expected),
        "payloads": {name: digest(raw) for name, raw in sorted(expected.items())},
        "metadata_sha256": digest(metadata),
        "archive_sha256": digest(path.read_bytes()),
    }


def native_sdk_fixture(
    app: Path,
    installed: Path,
    node: Path,
    payloads: dict[str, bytes],
    manifest: bytes,
    archive_sha256: str,
) -> dict[str, Any]:
    """Describe only the already qualified fresh public npm installation.

    The installed consumer revalidates every byte before creating one ephemeral
    package symlink. No product source or checkout dist is forwarded to Python.
    Node version qualification belongs to the unchanged nested public import
    assertion; the parent requires the same declared executable here.
    """
    require(app.is_absolute() and app.is_relative_to(Path("/private/tmp")))
    require(
        installed.is_absolute()
        and installed.resolve(strict=True) == installed
        and installed.is_dir()
        and installed.is_relative_to(app.parent / "consumer")
        and not installed.is_relative_to(app)
        and node.is_absolute()
        and node.is_file(),
        "missing_setup",
    )
    require(
        type(payloads) is dict
        and len(payloads) == NATIVE_SDK_PAYLOADS
        and {"dist/native.js", "dist/index.js"} <= payloads.keys()
        and type(manifest) is bytes
        and type(archive_sha256) is str
        and len(archive_sha256) == 64
        and all(character in "0123456789abcdef" for character in archive_sha256)
    )
    package = json.loads(manifest)
    require(
        package["name"] == "@livekit-ecosystem/channel-continuity" and package["version"] == "0.1.0"
    )
    require((installed / "package.json").read_bytes() == manifest)
    hashes = {}
    for name, raw in sorted(payloads.items()):
        archive_name(name)
        target = installed / name
        require(
            type(raw) is bytes
            and target.is_file()
            and not target.is_symlink()
            and target.resolve().is_relative_to(installed)
            and target.read_bytes() == raw
        )
        hashes[name] = digest(raw)
    descriptor = {
        "schema_version": 1,
        "package": str(installed),
        "node": str(node),
        "node_version": "24.22.2",
        "manifest_sha256": digest(manifest),
        "archive_sha256": archive_sha256,
        "payloads": hashes,
    }
    require(len(json_bytes(descriptor)) <= 32768)
    return descriptor


def child_record(path: Path) -> tuple[dict[str, Any], bytes]:
    """Read one private bounded fixture receipt; no PID action is authorized here."""
    try:
        parent = path.parent.lstat()
        require(
            stat.S_ISDIR(parent.st_mode)
            and stat.S_IMODE(parent.st_mode) == 0o700
            and parent.st_uid == os.geteuid()
            and path.parent.resolve() == path.parent,
            "cleanup_incomplete",
        )
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            before = os.fstat(source.fileno())
            require(
                stat.S_ISREG(before.st_mode)
                and stat.S_IMODE(before.st_mode) == 0o600
                and before.st_uid == os.geteuid()
                and before.st_nlink == 1
                and 0 < before.st_size <= 512,
                "cleanup_incomplete",
            )
            raw = source.read(513)
            after = os.fstat(source.fileno())
            require(
                (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                    before.st_ctime_ns,
                )
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                and path.lstat().st_ino == before.st_ino,
                "cleanup_incomplete",
            )

        def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
            value: dict[str, Any] = {}
            for key, item in items:
                require(key not in value, "cleanup_incomplete")
                value[key] = item
            return value

        value = json.loads(raw, object_pairs_hook=pairs)
        require(type(value) is dict, "cleanup_incomplete")
        return value, raw
    except (OSError, ValueError, UnicodeError):
        raise PackageError("cleanup_incomplete") from None


def application_child_records(
    directory: Path,
    nonce: str,
    *,
    complete: bool,
    parent_pid: int | None = None,
    retained: Path | None = None,
) -> dict[str, Any]:
    require(
        type(nonce) is str and len(nonce) == 32 and all(c in "0123456789abcdef" for c in nonce),
        "cleanup_incomplete",
    )
    require(type(complete) is bool, "cleanup_incomplete")
    meta = directory.lstat()
    require(
        stat.S_ISDIR(meta.st_mode)
        and stat.S_IMODE(meta.st_mode) == 0o700
        and meta.st_uid == os.geteuid()
        and directory.resolve() == directory,
        "cleanup_incomplete",
    )
    slots: list[Path] = []
    for slot in directory.iterdir():
        require(len(slots) < 10, "cleanup_incomplete")
        slots.append(slot)
    slots.sort()
    require(not complete or len(slots) == 10, "cleanup_incomplete")
    groups: list[dict[str, Any]] = []
    for number, slot in enumerate(slots, 1):
        require(slot.name == "child-" + str(number).zfill(2), "cleanup_incomplete")
        meta = slot.lstat()
        require(
            stat.S_ISDIR(meta.st_mode)
            and stat.S_IMODE(meta.st_mode) == 0o700
            and meta.st_uid == os.geteuid()
            and slot.resolve() == slot,
            "cleanup_incomplete",
        )
        names: set[str] = set()
        for child in slot.iterdir():
            require(len(names) < 4, "cleanup_incomplete")
            names.add(child.name)
        require(
            names == {"descriptor.json", "started.json", "go.json", "settled.json"},
            "cleanup_incomplete",
        )
        rows = {}
        for name in sorted(names):
            value, raw = child_record(slot / name)
            rows[name] = value
            if retained is not None:
                write(retained / slot.name / name, raw)
        descriptor, started, go, settled = (
            rows[n] for n in ("descriptor.json", "started.json", "go.json", "settled.json")
        )
        common = {"schemaVersion": 1, "nonce": nonce, "slot": slot.name}
        require(
            all(
                type(r.get("schemaVersion")) is int
                and all(r.get(k) == v for k, v in common.items())
                for r in rows.values()
            ),
            "cleanup_incomplete",
        )
        require(
            set(descriptor)
            == set(common) | {"parentPid", "testId", "programSha256", "lifetimeDeadlineNs"}
            and set(started) == set(common) | {"parentPid", "pid", "pgid"}
            and set(go) == set(common) | {"pid", "pgid"}
            and set(settled)
            == set(common)
            | {"pid", "pgid", "returncode", "directReaped", "pipesDrained", "groupAbsent"},
            "cleanup_incomplete",
        )
        test_id, program = descriptor["testId"], descriptor["programSha256"]
        require(
            type(descriptor["lifetimeDeadlineNs"]) is int
            and 0 < descriptor["lifetimeDeadlineNs"] < 2**63,
            "cleanup_incomplete",
        )
        require(
            type(test_id) is str
            and any(
                test_id == prefix + name
                for prefix in (
                    "test_channel_policy_native_worker_process.WorkerProcessTests.",
                    "tests.test_channel_policy_native_worker_process.WorkerProcessTests.",
                )
                for name in APPLICATION_CHILD_RETURNS
            ),
            "cleanup_incomplete",
        )
        require(
            type(program) is str
            and len(program) == 64
            and all(c in "0123456789abcdef" for c in program),
            "cleanup_incomplete",
        )
        pid, parent = started["pid"], descriptor["parentPid"]
        require(
            type(pid) is int
            and pid > 1
            and type(parent) is int
            and parent > 1
            and pid != parent
            and (parent_pid is None or parent == parent_pid),
            "cleanup_incomplete",
        )
        require(
            started["parentPid"] == parent
            and all(
                type(row["pid"]) is int
                and type(row["pgid"]) is int
                and row["pid"] == row["pgid"] == pid
                for row in (started, go, settled)
            ),
            "cleanup_incomplete",
        )
        require(
            type(settled["returncode"]) is int
            and settled["returncode"] in APPLICATION_CHILD_RETURNS[test_id.rsplit(".", 1)[-1]]
            and all(settled[k] is True for k in ("directReaped", "pipesDrained", "groupAbsent")),
            "cleanup_incomplete",
        )
        groups.append(
            {
                "test_id": test_id,
                "slot": slot.name,
                "parent_pid": parent,
                "pid": pid,
                "pgid": pid,
                "returncode": settled["returncode"],
                "direct_reaped": True,
                "pipes_drained": True,
                "group_absent": True,
            }
        )
    require(
        len({g["pid"] for g in groups}) == len(groups)
        and len({g["test_id"].rsplit(".", 1)[-1] for g in groups}) == len(groups)
        and len({g["parent_pid"] for g in groups}) <= 1,
        "cleanup_incomplete",
    )
    return {"schema_version": 1, "nonce": nonce, "groups": groups}


def native_fixture_report(descriptor: dict[str, Any], asset_manifest_sha256: str) -> dict[str, Any]:
    """Expected facts, counted separately from actual business/media assertions."""
    return {
        "schema_version": 1,
        "public_npm_payloads": NATIVE_SDK_PAYLOADS,
        "npm_manifest_sha256": descriptor["manifest_sha256"],
        "npm_archive_sha256": descriptor["archive_sha256"],
        "asset_manifest_sha256": asset_manifest_sha256,
        "node": descriptor["node"],
        "node_version": "24.22.2",
        "native_prepare_node_client_descendants": NATIVE_CLIENT_DESCENDANTS,
        "descendant_process_group": "app-execution",
        "node_client_exit_and_reap_assertions_passed": True,
        "checkout_product_fallback": False,
    }


NATIVE_APPLICATION_FIXTURES = r"""def prepare_native_fixtures(root, purelib, expected):
    raw=(root/"public-native-sdk-fixture.json").read_bytes()
    assert 0<len(raw)<=32768
    descriptor=json.loads(raw)
    assert type(descriptor)is dict and set(descriptor)=={"schema_version","package","node","node_version","manifest_sha256","archive_sha256","payloads"}
    assert type(descriptor["schema_version"])is int and descriptor["schema_version"]==1
    package=Path(descriptor["package"])
    assert package.is_absolute() and package.resolve(strict=True)==package and package.is_dir()
    assert package.is_relative_to(root.parent/"consumer") and not package.is_relative_to(root)
    node=Path(descriptor["node"])
    assert node.is_absolute() and node.is_file() and shutil.which("node")==str(node)
    assert descriptor["node_version"]=="24.22.2"
    assert hashlib.sha256((package/"package.json").read_bytes()).hexdigest()==descriptor["manifest_sha256"]
    payloads=descriptor["payloads"]
    assert type(payloads)is dict and len(payloads)==124 and {"dist/native.js","dist/index.js"}<=payloads.keys()
    for name,sha in payloads.items():
        assert type(name)is str and name and not name.startswith("/") and "\\"not in name
        assert all(part not in {"",".","..","node_modules",".env",".env.providers"} for part in name.split("/"))
        path=package/name
        assert path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(package)
        assert hashlib.sha256(path.read_bytes()).hexdigest()==sha
    def directory(path):
        if not path.exists():path.mkdir(mode=0o700)
        meta=path.lstat()
        assert stat.S_ISDIR(meta.st_mode) and stat.S_IMODE(meta.st_mode)==0o700 and meta.st_uid==os.geteuid() and not path.is_symlink()
    directory(root/"projects")
    link=root/"projects/channel-continuity"
    assert not link.exists() and not link.is_symlink()
    link.symlink_to(package,target_is_directory=True)
    assert link.resolve()==package
    assert not (root/"services").exists()
    for folder in (root/"services",root/"services/conversation_agent",root/"services/conversation_agent/assets"):
        directory(folder)
    name="services/conversation_agent/assets/manifest.json"
    manifest=(purelib/name).read_bytes()
    sha=hashlib.sha256(manifest).hexdigest()
    assert sha==expected[name]
    fd=os.open(root/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"wb")as output:output.write(manifest)
    assert {str(path.relative_to(root/"services"))for path in (root/"services").rglob("*")if path.is_file()or path.is_symlink()}=={"conversation_agent/assets/manifest.json"}
    return {"schema_version":1,"public_npm_payloads":124,"npm_manifest_sha256":descriptor["manifest_sha256"],"npm_archive_sha256":descriptor["archive_sha256"],"asset_manifest_sha256":sha,"node":str(node),"node_version":"24.22.2","native_prepare_node_client_descendants":2,"descendant_process_group":"app-execution","checkout_product_fallback":False}
"""


ROOT_APPLICATION_TYPES = """from channel_continuity import DecodedEvent, TrustedPrincipal, parse_event_json
from channel_continuity.native import NativeRuntime
from delegation_reliability import ChannelPolicyCoordinator, ChannelPolicyRunner, ChannelPolicyDeliveryClient
from delegation_reliability.coordinator import CaseAuthorityPort
from delegation_reliability.contracts import Scope
from delegation_reliability.delivery_contract import DeliveryBinding
from delegation_reliability.fixed_policy_contracts import FixedPolicyRequest
from services.channel_policy_demo.discovery import DiscoveryPage, DiscoveryRequest, encode_discovery_request, parse_discovery_page, parse_discovery_request
from services.channel_policy_demo.current_result import CurrentResultObservation, CurrentResultRequest, encode_current_result_observation, encode_current_result_request, parse_current_result_observation, parse_current_result_request
from services.channel_policy_demo.current_result_producer import CurrentResultProducer, ProducerBinding, InspectionPort, InspectionFactoryPort, NativeResultReadPort
from services.channel_policy_demo.executor import ChannelPolicyExecutor, DiscoveryPort, ExecutorBinding, JobRunnerPort, PreparedReadPort, RunnerFactory, ScanObservation, StoredWorkPort
from services.channel_policy_demo.origin import ChannelOriginBinding, ChannelOriginService
from services.channel_policy_demo.origin_http import ChannelOriginHttp
from services.channel_policy_demo.wire import PreparedChannelInput, parse_accept_frame
from services.channel_policy_demo.worker_client import ChannelPolicyWorkerClient, WorkerBinding, WorkerCredential, WorkerEndpoint, WorkerDiscoveryReader, WorkerPreparedReader, CoordinatorWorkerDiscoveryReader, CoordinatorWorkerPreparedReader
from services.channel_policy_demo.origin_router import ChannelOriginRouter, CoordinatorFactory, OriginRouterBinding, RevisionTemplateCatalog
from services.channel_policy_demo.jobs import ActualJob, ReadOnlyInspection, ChannelPolicyJobFactory, EvidenceCatalogue, ExecutionRunnerPort, GuardedDeliveryPort, JobClientFactory, JobObservation
from services.channel_policy_demo.public_clients import PublicClientFactory, PublicWorkConfig, PublicSpecialistConfig, PublicReceiverConfig
from services.channel_policy_demo.case_bridge import CurrentCaseBinding, CurrentCaseBridge, CurrentCaseReader, PublicCurrentCaseReader
from services.channel_policy_demo.result_receiver import ChannelResultReceiver
from services.channel_policy_demo.owner_config import OwnerProfile, encode_owner_profile, parse_owner_profile
from services.channel_policy_demo.application import ChannelPolicyApplication, CurrentResultReadPort
from services.channel_policy_demo.room_control import RoomPublisherCredential, RoomOpen, RoomObservation, RoomAttach, RoomAttachmentObservation
from services.channel_policy_demo.room_control_client import RoomControlHttpClient
from services.channel_policy_demo.room_result_client import RoomResultHttpClient, RoomResultEndpoint, RoomResultBinding, RoomViewCredential
from services.channel_policy_demo.worker_current_result import WorkerCurrentResultClient, WorkerCurrentResultReadPort
from services.channel_policy_demo.native_models import ScriptedModelProfile, ScriptedModelBundle, load_scripted_models
from services.channel_policy_demo.native_worker_config import NativeWorkerConfig, encode_native_worker_config, parse_native_worker_config
from services.channel_policy_demo.native_worker import NativeWorker
from services.channel_policy_demo.native_prepare_http import NativePrepareHttp, NativePreparePort
from services.channel_policy_demo.current_result_http import RoomCurrentResultHttp
from services.channel_policy_demo.current_result_context import with_current_result
from livekit.agents.llm import LLM
from typing import Any, Callable, Mapping
from pathlib import Path
from services.channel_policy_demo.native_room import NativeRoomOwner, NativeRoomRoute, NativeRoomPorts, RoomAdminPort, RoomControlPort, WorkerPort
from services.channel_policy_demo.native_room_admin import LiveKitRoomAdmin, LiveKitAdminSettings
from services.channel_policy_demo.native_room_state import StartCommand, EndCommand, NodeRoomCursor, NativeRoomStatus, BrowserRoomGrant, PrivateRoomState, parse_start_command, encode_start_command, parse_end_command, encode_end_command
from services.channel_policy_demo.native_worker_process import NativeWorkerProcess, WorkerProcessStatus
from services.channel_policy_demo.operator import ChannelPolicyOperator, RoomOperatorPort, ApplicationObservationPort, SmsOperatorPort
from services.channel_policy_demo.operator_contract import SmsCommand, SmsObservation, CaseObservation, ProgressObservation, parse_sms_command, progress_observation
from services.channel_policy_demo.operator_sms import ChannelPolicySmsClient, SmsRoute, signed_sms
from services.channel_policy_demo.operator_http import ChannelPolicyOperatorHttp
from services.channel_policy_demo.parent import ChannelPolicyParent, ParentSettings, ParentFactories, AppPort as ParentAppPort, RoomsPort as ParentRoomsPort, SmsPort as ParentSmsPort, HttpPort as ParentHttpPort
from services.channel_policy_demo.__main__ import ApplicationPort, ExecutorMode, run_application
import asyncio

def prepared(raw: bytes) -> PreparedChannelInput:
    return parse_accept_frame(raw)

def request(raw: bytes) -> DiscoveryRequest:
    return parse_discovery_request(encode_discovery_request(parse_discovery_request(raw)))

def page(raw: bytes) -> DiscoveryPage:
    return parse_discovery_page(raw)

def current_request(raw: bytes) -> CurrentResultRequest:
    return parse_current_result_request(encode_current_result_request(parse_current_result_request(raw)))

def current_result(raw: bytes) -> CurrentResultObservation:
    return parse_current_result_observation(encode_current_result_observation(parse_current_result_observation(raw)))

def executor(binding: ExecutorBinding, discovery: DiscoveryPort, prepared: PreparedReadPort, stored: StoredWorkPort, runners: RunnerFactory) -> ChannelPolicyExecutor:
    return ChannelPolicyExecutor(binding=binding, discovery=discovery, prepared=prepared, stored=stored, runners=runners)

async def scan(executor: ChannelPolicyExecutor) -> ScanObservation:
    return await executor.scan_once()

async def close_executor(executor: ChannelPolicyExecutor) -> None:
    await executor.close()

def current_producer(binding: ProducerBinding, discovery: DiscoveryPort, prepared: PreparedReadPort, stored: StoredWorkPort, inspections: InspectionFactoryPort, native: NativeResultReadPort, evidence: EvidenceCatalogue) -> CurrentResultProducer:
    return CurrentResultProducer(binding=binding, discovery=discovery, prepared=prepared, stored=stored, inspections=inspections, native=native, evidence=evidence)

def inspection_factory(jobs: ChannelPolicyJobFactory) -> InspectionFactoryPort:
    return jobs

def read_only_inspection(owner: ReadOnlyInspection) -> InspectionPort:
    return owner

async def read_current(producer: CurrentResultProducer) -> CurrentResultObservation:
    return await producer.read()

def executor_pending(executor: ChannelPolicyExecutor) -> int:
    return executor.pending_count

def origin(binding: ChannelOriginBinding, template: FixedPolicyRequest, coordinator: ChannelPolicyCoordinator) -> ChannelOriginService:
    return ChannelOriginService(binding=binding, template=template, coordinator=coordinator)

def transport(service: ChannelOriginService, bearer: str) -> ChannelOriginHttp:
    return ChannelOriginHttp(service, operation_bearer=bearer)

def native_type() -> type[NativeRuntime]:
    return NativeRuntime

def scoped_event(raw: str, principal: TrustedPrincipal) -> DecodedEvent:
    return parse_event_json(raw, principal)

def worker(endpoint: WorkerEndpoint, credential: WorkerCredential, binding: WorkerBinding) -> ChannelPolicyWorkerClient:
    return ChannelPolicyWorkerClient(endpoint, credential, binding)

def worker_ports(client: ChannelPolicyWorkerClient) -> tuple[DiscoveryPort, PreparedReadPort, DiscoveryPort, PreparedReadPort]:
    return WorkerDiscoveryReader(client), WorkerPreparedReader(client), CoordinatorWorkerDiscoveryReader(client), CoordinatorWorkerPreparedReader(client)

def startup_clients(work: PublicWorkConfig, specialist: PublicSpecialistConfig, receiver: PublicReceiverConfig, case: CaseAuthorityPort) -> PublicClientFactory:
    return PublicClientFactory(work=work, specialist=specialist, receiver=receiver, case_authority=case)

def factory_ports(clients: PublicClientFactory, jobs: ChannelPolicyJobFactory, job: ActualJob) -> tuple[JobClientFactory, CoordinatorFactory, RunnerFactory, JobRunnerPort]:
    return clients, clients, jobs, job

def sdk_job_ports(runner: ChannelPolicyRunner, delivery: ChannelPolicyDeliveryClient) -> tuple[ExecutionRunnerPort, GuardedDeliveryPort]:
    return runner, delivery

def observed_job(job: ActualJob) -> JobObservation:
    return job.observation

def router(binding: OriginRouterBinding, discovery: DiscoveryPort, prepared: PreparedReadPort, templates: RevisionTemplateCatalog, coordinators: CoordinatorFactory) -> ChannelOriginRouter:
    return ChannelOriginRouter(binding=binding, discovery=discovery, prepared=prepared, templates=templates, coordinators=coordinators)

def job_factory(scope: Scope, case: CaseAuthorityPort, binding: DeliveryBinding, catalogue: EvidenceCatalogue, clients: JobClientFactory) -> ChannelPolicyJobFactory:
    return ChannelPolicyJobFactory(scope=scope, case_authority=case, bindings=(binding,), catalogue=catalogue, clients=clients)

def current_case_reader(reader: PublicCurrentCaseReader) -> CurrentCaseReader:
    return reader

def current_case_transport(bindings: tuple[CurrentCaseBinding, ...]) -> CurrentCaseBridge:
    return CurrentCaseBridge(bindings)

def receiver(config: PublicReceiverConfig) -> ChannelResultReceiver:
    return ChannelResultReceiver(port=config.port, publisher_token=config.publisher_token, receiver_id=config.receiver_id, scope=config.scope, recipient_id=config.recipient_id)

def configured_profile(raw: bytes) -> OwnerProfile:
    return parse_owner_profile(encode_owner_profile(parse_owner_profile(raw)))

def application(profile: OwnerProfile) -> ChannelPolicyApplication:
    return ChannelPolicyApplication(profile)

async def supervise(application: ChannelPolicyApplication, stop: asyncio.Event, executor: ExecutorMode) -> int:
    checked: ApplicationPort = application
    return await run_application(checked, executor=executor, stop=stop)

def room_control(credential: RoomPublisherCredential) -> RoomControlHttpClient:
    return RoomControlHttpClient(credential)

async def publish_room(client: RoomControlHttpClient, request: RoomOpen) -> RoomObservation:
    return await client.open(request)

async def attach_room_agent(client: RoomControlHttpClient, request: RoomAttach) -> RoomAttachmentObservation:
    return await client.attach(request)

def native_result_transport(endpoint: RoomResultEndpoint, binding: RoomResultBinding, credential: RoomViewCredential) -> RoomResultHttpClient:
    return RoomResultHttpClient(endpoint, binding, credential)

def native_result_port(client: RoomResultHttpClient) -> NativeResultReadPort:
    return client

def scoped_current_reader(application: ChannelPolicyApplication, native: NativeResultReadPort) -> CurrentResultReadPort:
    return application.attach_current_result(native)

async def close_current_reader(application: ChannelPolicyApplication) -> None:
    await application.close_current_result()

def parent_current_http(reader: CurrentResultReadPort, is_current: Callable[[], bool], bearer: str) -> RoomCurrentResultHttp:
    return RoomCurrentResultHttp(reader, is_current=is_current, current_bearer=bearer)

def worker_current_port(client: WorkerCurrentResultClient) -> WorkerCurrentResultReadPort:
    return client

async def scripted_models(profile: ScriptedModelProfile) -> ScriptedModelBundle:
    return await load_scripted_models(profile)

def selected_current_model(models: ScriptedModelBundle, reader: WorkerCurrentResultReadPort) -> LLM[Any]:
    return with_current_result(models.llm, reader)

def native_prepare_http(runtime: NativeRuntime, bearer: str) -> NativePrepareHttp:
    port: NativePreparePort = runtime
    return NativePrepareHttp(port, prepare_bearer=bearer)

def configured_native_worker(raw: bytes) -> NativeWorker:
    value: NativeWorkerConfig = parse_native_worker_config(raw)
    return NativeWorker(parse_native_worker_config(encode_native_worker_config(value)))

def room_owner(route: NativeRoomRoute, epoch: str, application: ChannelPolicyApplication, admin: LiveKitAdminSettings, publisher: RoomPublisherCredential, cursor: NodeRoomCursor, directory: Path, python: Path, environment: Mapping[str, str], ports: NativeRoomPorts | None = None) -> NativeRoomOwner:
    return NativeRoomOwner(route, owner_epoch=epoch, app=application, admin=admin, publisher=publisher, cursor=cursor, directory=directory, python_executable=python, base_environment=environment, ports=ports)

def admin_owner(settings: LiveKitAdminSettings) -> RoomAdminPort:
    return LiveKitRoomAdmin(settings)

def publisher_port(client: RoomControlHttpClient) -> RoomControlPort:
    return client

def child_owner(python: Path, config: Path, environment: Mapping[str, str]) -> WorkerPort:
    return NativeWorkerProcess(python, config, environment)

def child_status(child: NativeWorkerProcess) -> WorkerProcessStatus:
    return child.status()

async def room_lifecycle(owner: NativeRoomOwner, start: StartCommand, end: EndCommand) -> tuple[BrowserRoomGrant, CurrentResultObservation, NativeRoomStatus]:
    grant = await owner.start(start)
    current = await owner.read_current(end)
    status = await owner.end(end)
    await owner.close()
    return grant, current, status

def room_commands(start: bytes, end: bytes) -> tuple[StartCommand, EndCommand]:
    return parse_start_command(encode_start_command(parse_start_command(start))), parse_end_command(encode_end_command(parse_end_command(end)))

def operator_ports(owner: NativeRoomOwner, application: ChannelPolicyApplication, sms: ChannelPolicySmsClient) -> tuple[RoomOperatorPort, ApplicationObservationPort, SmsOperatorPort]:
    return owner, application, sms

def operator(owner: RoomOperatorPort, application: ApplicationObservationPort, sms: SmsOperatorPort) -> ChannelPolicyOperator:
    return ChannelPolicyOperator(owner, application, sms)

def sms_client(route: SmsRoute) -> ChannelPolicySmsClient:
    return ChannelPolicySmsClient(route)

def sms_command(raw: bytes) -> SmsCommand:
    return parse_sms_command(raw)

def sign_sms(command: SmsCommand, route: SmsRoute, seconds: int) -> tuple[bytes, dict[str, str]]:
    return signed_sms(command, route, seconds)

async def observe_application(application: ChannelPolicyApplication) -> tuple[CaseObservation, ProgressObservation]:
    return await application.observe_case(), await application.observe_progress()

async def operator_exchange(owner: ChannelPolicyOperator, raw: bytes) -> bytes:
    return await owner.exchange(raw)

def operator_http(owner: ChannelPolicyOperator, bearer: str) -> ChannelPolicyOperatorHttp:
    return ChannelPolicyOperatorHttp(owner, bearer=bearer)

def parent_settings(profile: OwnerProfile, admin: LiveKitAdminSettings, bearer: str, epoch: str, directory: Path, python: Path, environment: Mapping[str, str]) -> ParentSettings:
    return ParentSettings(profile, admin, bearer, epoch, directory, python, environment)

def parent_protocols(application: ChannelPolicyApplication, rooms: NativeRoomOwner, sms: ChannelPolicySmsClient, http: ChannelPolicyOperatorHttp) -> tuple[ParentAppPort, ParentRoomsPort, ParentSmsPort, ParentHttpPort]:
    return application, rooms, sms, http

def parent_factories(app: Callable[[OwnerProfile], ParentAppPort], rooms: Callable[[ParentSettings, ParentAppPort, NodeRoomCursor], ParentRoomsPort], sms: Callable[[SmsRoute], ParentSmsPort], http: Callable[[ChannelPolicyOperator, str], ParentHttpPort]) -> ParentFactories:
    return ParentFactories(app=app, rooms=rooms, sms=sms, http=http)

def parent_owner(settings: ParentSettings, factories: ParentFactories | None = None) -> ChannelPolicyParent:
    return ChannelPolicyParent(settings, factories=factories)

async def parent_stages(owner: ChannelPolicyParent, cursor: NodeRoomCursor) -> tuple[str, int, bool, Mapping[str, int]]:
    await owner.start_sources()
    endpoint = await owner.start(cursor)
    ready, metrics = owner.ready, owner.metrics()
    await owner.close()
    return endpoint.host, endpoint.port, ready, metrics
"""


def application_expected_report() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "passed",
        "installed_prefix_paths": True,
        "installed_payloads_equal": True,
        "imports_no_IO": True,
        "unadapted_tests": True,
        "application_fake_port_tests": sum(ROOT_APPLICATION_TEST_COUNTS.values()),
        "application_test_counts": dict(ROOT_APPLICATION_TEST_COUNTS),
        "public_native_fixtures_verified": True,
        "native_worker_child_groups": 10,
        "native_prepare_node_client_descendants": NATIVE_CLIENT_DESCENDANTS,
        "descendant_process_group": "app-execution",
        "source_actual_assertions": 0,
        "installed_actual_assertions": 0,
        "database_calls": 0,
        "rtc_rooms": 0,
        "provider_calls": False,
    }


def application_execution() -> str:
    return (
        """from pathlib import Path
import asyncio,hashlib,json,os,shutil,socket,stat,subprocess,sys,sysconfig,unittest
from importlib.metadata import version
from unittest.mock import patch
root=Path(__file__).resolve().parent
prefix=Path(sys.prefix).resolve()
assert root.is_relative_to(Path("/private/tmp")) and not root.is_relative_to(prefix)
def denied(*args: object, **kwargs: object) -> object:
    raise AssertionError("import_started_IO")
with patch.object(socket.socket,"connect",denied),patch.object(socket.socket,"bind",denied),patch.object(subprocess,"Popen",denied),patch.object(asyncio,"create_task",denied):
    import services.channel_policy_demo as application
    from services.channel_policy_demo import wire,origin,origin_http,discovery,current_result,current_result_producer,executor
    from services.channel_policy_demo import worker_client,origin_router,jobs,public_clients,case_bridge,result_receiver,owner_config
    from services.channel_policy_demo import application as runtime_application
    import services.channel_policy_demo.__main__ as application_cli
    from services.channel_policy_demo import room_control,room_control_client,room_result_client,worker_current_result,current_result_context
    from services.channel_policy_demo import native_models,native_prepare_http,current_result_http,native_worker_config,native_worker
    from services.channel_policy_demo import native_room,native_room_admin,native_room_state,native_worker_process,operator,operator_contract,operator_sms,operator_http,parent
    import channel_continuity as channel
    import channel_continuity.native as native
    import continuity_lab.work_api as work
    import delegation_reliability as delegation
for module in (application,wire,origin,origin_http,discovery,current_result,current_result_producer,executor,worker_client,origin_router,jobs,public_clients,case_bridge,result_receiver,owner_config,runtime_application,application_cli,channel,native,work,delegation):
    assert module.__file__ is not None and Path(module.__file__).resolve().is_relative_to(prefix)
for module in (room_control,room_control_client,room_result_client,worker_current_result,current_result_context,native_models,native_prepare_http,current_result_http,native_worker_config,native_worker,native_room,native_room_admin,native_room_state,native_worker_process,operator,operator_contract,operator_sms,operator_http,parent):
    assert module.__file__ is not None and Path(module.__file__).resolve().is_relative_to(prefix)
assert version("livekit-agent-ecosystem")=="0.1.0" and version("channel-continuity")=="0.1.0"
assert version("agent-continuity")=="0.1.0" and version("delegation-reliability")=="0.1.0"
assert version("livekit-agents")=="1.8.11" and version("psycopg")=="3.3.8"
assert version("aiohttp")=="3.14.5" and version("h11")=="0.16.0" and version("livekit-api")=="1.2.2"
purelib=Path(sysconfig.get_path("purelib")).resolve()
assert purelib.is_relative_to(prefix)
expected=json.loads((root/"root-application-payloads.json").read_bytes())
for name,sha in expected.items():
    path=purelib/name
    assert path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(prefix)
    assert hashlib.sha256(path.read_bytes()).hexdigest()==sha
FIXTURE_SETUP
native_fixture=prepare_native_fixtures(root,purelib,expected)
counts={}
for pattern,expected in SUITES.items():
    suite=unittest.defaultTestLoader.discover(str(root/"tests"),pattern=pattern)
    assert suite.countTestCases()==expected
    if pattern=="test_channel_policy_native_worker_process.py":
        import importlib
        child_fixture=importlib.import_module("test_channel_policy_native_worker_process")
        policy=json.loads((root/"native-child-policy.json").read_bytes())
        assert set(policy)=={"schemaVersion","nonce"} and policy["schemaVersion"]==1
        child_fixture.configure_child_records(root/"native-child-groups",policy["nonce"])
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    assert result.wasSuccessful() and result.testsRun==expected and not result.skipped
    counts[pattern]=result.testsRun
assert sum(counts.values())==TOTAL
child_proof=child_fixture.child_group_proof()
assert len(child_proof["groups"])==10
fd=os.open(root/"native-child-groups-proof.json",os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,"w")as output:json.dump(child_proof,output,separators=(",",":"))
for name,module in tuple(sys.modules.items()):
    if name.split(".")[0] in {"services","channel_continuity","continuity_lab","delegation_reliability","livekit"}:
        filename=getattr(module,"__file__",None)
        if filename is not None:
            assert Path(filename).resolve().is_relative_to(prefix)
        else:
            paths=tuple(getattr(module,"__path__",()))
            assert paths and all(Path(path).resolve().is_relative_to(prefix) for path in paths)
native_fixture["node_client_exit_and_reap_assertions_passed"]=True
fd=os.open(root/"native-fixture-observed.json",os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,"w")as output:json.dump(native_fixture,output,separators=(",",":"))
print(json.dumps(REPORT))
""".replace("FIXTURE_SETUP", NATIVE_APPLICATION_FIXTURES)
        .replace("SUITES", repr(ROOT_APPLICATION_TEST_COUNTS))
        .replace("TOTAL", str(sum(ROOT_APPLICATION_TEST_COUNTS.values())))
        .replace("REPORT", repr(application_expected_report()))
    )


def application_checks(
    root: Path,
    work: Path,
    retained: Path,
    app: Path,
    python: Path,
    environment: dict[str, str],
    command: Callable[..., bytes],
    packages: ModuleType,
) -> dict[str, Any]:
    """Seven owned roles borrowing only the already-created isolated product prefix."""
    require(python.is_relative_to(Path("/private/tmp")) and not python.is_relative_to(root))
    payloads = application_payload(root)
    invocations: list[dict[str, Any]] = []
    archived: dict[str, Any] = {}
    descriptor_raw = (app / "public-native-sdk-fixture.json").read_bytes()
    require(0 < len(descriptor_raw) <= 32768)
    write(retained / "root-application/public-native-sdk-fixture.json", descriptor_raw)

    def invoke(role: str, argv: list[str], *, cwd: Path) -> bytes:
        require(
            role in ROOT_APPLICATION_ROLES and role not in {entry["role"] for entry in invocations},
            "child_budget",
        )
        value = {"role": role, "argv": list(argv), "cwd": str(cwd)}
        invocations.append(value)
        write(retained / "root-application/commands" / (role + ".json"), json_bytes(value))
        role_environment = dict(environment)
        if role == "app-execution":
            descriptor = json.loads((app / "public-native-sdk-fixture.json").read_bytes())
            role_environment["PATH"] = str(Path(descriptor["node"]).parent) + ":/usr/bin:/bin"
        return command(role, argv, cwd=cwd, environment=role_environment)

    def retain(label: str, path: Path) -> None:
        raw = path.read_bytes()
        require(0 < len(raw) <= 8388608)
        relative = (
            Path("root-application/artifacts")
            / ("rebuilt" if label == "root-rebuilt-wheel" else "direct")
            / path.name
        )
        write(retained / relative, raw)
        archived[label] = {"bytes": len(raw), "sha256": digest(raw), "path": relative.as_posix()}

    uv = str(root / ".venv/bin/uv")
    output = work / "root-built"
    private_parents(output)
    invoke(
        "app-build",
        [
            uv,
            "--no-config",
            "build",
            "--offline",
            "--no-sources",
            "--python",
            sys.executable,
            "--wheel",
            "--sdist",
            "--config-setting=--global-option=--quiet",
            "--out-dir",
            str(output),
            str(root),
        ],
        cwd=work,
    )
    wheels, sdists = list(output.glob("*.whl")), list(output.glob("*.tar.gz"))
    require(
        len(wheels) == len(sdists) == 1
        and not wheels[0].is_symlink()
        and not sdists[0].is_symlink()
    )
    retain("root-wheel", wheels[0])
    retain("root-sdist", sdists[0])
    direct = application_wheel(wheels[0], root, "livekit_agent_ecosystem", payloads, packages)
    source_raw = sdists[0].read_bytes()
    files = application_sdist(source_raw, root, payloads)
    extracted = work / "root-sdist-source"
    extract_application(files, extracted)
    rebuilt_output = work / "root-rebuilt"
    private_parents(rebuilt_output)
    rebuild = """import sys,tomllib
from pathlib import Path
from importlib.metadata import version
assert version("setuptools")=="84.2.1"
config=tomllib.loads(Path("pyproject.toml").read_text())
assert config["build-system"]=={"requires":["setuptools==84.2.1"],"build-backend":"setuptools.build_meta"}
from setuptools.build_meta import build_wheel
name=build_wheel(sys.argv[1],config_settings={"--global-option":["--quiet"]})
assert type(name)is str and name.endswith(".whl")
"""
    write(retained / "consumers/root-rebuild.py", rebuild.encode())
    invoke(
        "app-rebuild",
        [
            uv,
            "--no-config",
            "run",
            "--offline",
            "--no-project",
            "--isolated",
            "--with",
            "setuptools==84.2.1",
            "--python",
            sys.executable,
            "python",
            "-I",
            "-B",
            "-c",
            rebuild,
            str(rebuilt_output),
        ],
        cwd=extracted,
    )
    rebuilt = list(rebuilt_output.glob("*.whl"))
    require(len(rebuilt) == 1 and not rebuilt[0].is_symlink())
    retain("root-rebuilt-wheel", rebuilt[0])
    rebuilt_proof = application_wheel(
        rebuilt[0], root, "livekit_agent_ecosystem", payloads, packages
    )
    p2_member = root / "projects/channel-continuity/python"
    p2_payloads: dict[str, bytes] = packages._payload(p2_member, "channel_continuity")
    require(len(p2_payloads) == P2_PYTHON_PAYLOADS)
    p2_output = work / "p2-python-wheel"
    private_parents(p2_output)
    invoke(
        "p2-python-build",
        [
            uv,
            "--no-config",
            "build",
            "--offline",
            "--no-sources",
            "--python",
            sys.executable,
            "--wheel",
            "--out-dir",
            str(p2_output),
            str(p2_member),
        ],
        cwd=work,
    )
    p2_wheels = list(p2_output.glob("*.whl"))
    require(len(p2_wheels) == 1 and not p2_wheels[0].is_symlink())
    retain("p2-python-wheel", p2_wheels[0])
    p2_proof = application_wheel(
        p2_wheels[0], p2_member, "channel_continuity", p2_payloads, packages
    )
    invoke(
        "app-install",
        [
            uv,
            "--no-config",
            "pip",
            "install",
            "--offline",
            "--python",
            str(python),
            str(p2_wheels[0]),
            str(wheels[0]) + "[channel-demo]",
        ],
        cwd=app,
    )
    invoke(
        "app-check",
        [uv, "--no-config", "--offline", "pip", "check", "--python", str(python)],
        cwd=app,
    )
    for name, raw in (
        ("root-application-types.py", ROOT_APPLICATION_TYPES.encode()),
        ("root-application-execution.py", application_execution().encode()),
    ):
        write(app / name, raw)
        write(retained / "consumers" / name, raw)
    expected = {name: digest(raw) for name, raw in {**payloads, **p2_payloads}.items()}
    expected["livekit_agent_ecosystem-0.1.0.dist-info/METADATA"] = direct["metadata_sha256"]
    expected["channel_continuity-0.1.0.dist-info/METADATA"] = p2_proof["metadata_sha256"]
    write(app / "root-application-payloads.json", json_bytes(expected))
    write(retained / "root-application/installed-payloads.json", json_bytes(expected))
    invoke(
        "app-types",
        [
            str(Path(sys.executable).absolute()),
            "-I",
            "-m",
            "mypy",
            "--strict",
            "--follow-imports=silent",
            "--python-executable",
            str(python),
            "--cache-dir",
            str(work / "root-app-mypy-cache"),
            str(app / "root-application-types.py"),
        ],
        cwd=app,
    )
    write(
        app / "native-child-policy.json",
        json_bytes({"schemaVersion": 1, "nonce": os.urandom(16).hex()}),
    )
    private_parents(app / "native-child-groups")
    raw = invoke(
        "app-execution",
        [str(python), "-I", str(app / "root-application-execution.py")],
        cwd=app,
    )
    result = selected_report(raw, application_expected_report())
    policy, _ = child_record(app / "native-child-policy.json")
    child_proof = application_child_records(
        app / "native-child-groups", policy["nonce"], complete=True
    )
    require(
        json.loads((app / "native-child-groups-proof.json").read_bytes()) == child_proof,
        "consumer_failed",
    )
    require((app / "public-native-sdk-fixture.json").read_bytes() == descriptor_raw)
    fixture_raw = (app / "native-fixture-observed.json").read_bytes()
    require(0 < len(fixture_raw) <= 4096)
    descriptor = json.loads(descriptor_raw)
    fixture = selected_report(
        fixture_raw,
        native_fixture_report(
            descriptor, digest(payloads["services/conversation_agent/assets/manifest.json"])
        ),
    )
    write(retained / "root-application/native-fixture-observed.json", fixture_raw)
    require(tuple(entry["role"] for entry in invocations) == ROOT_APPLICATION_ROLES, "child_budget")
    return {
        "native_fixtures": fixture,
        "test_child_groups": child_proof,
        "root_wheel": direct,
        "root_rebuilt_wheel": rebuilt_proof,
        "root_sdist": {
            "sha256": digest(source_raw),
            "file_count": len(files),
            "payload_count": len(payloads),
            "bound_default_test_sources": len(application_source_tests(root)),
            "safe_extraction": True,
            "raw_guide_equal": True,
        },
        "p2_python": p2_proof,
        "artifacts": archived,
        "commands": invocations,
        "build_backend": "setuptools.build_meta",
        "root_extra": "channel-demo",
        "runtime_versions": {
            "python": "3.14.10",
            "livekit-agents": "1.8.11",
            "psycopg": "3.3.8",
            "setuptools": "84.2.1",
            "aiohttp": "3.14.5",
            "h11": "0.16.0",
            "livekit-api": "1.2.2",
        },
        "consumer": result,
    }


def selected_report(stdout: bytes, fields: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(stdout)
    except (ValueError, UnicodeError):
        raise PackageError("consumer_failed") from None
    require(type(value) is dict and json_bytes(value) == json_bytes(fields), "consumer_failed")
    return dict(value)


def finite_code(error: BaseException | None) -> str:
    try:
        code = getattr(error, "code", "package_failed")
    except Exception:  # noqa: BLE001 - a dependency getter cannot replace primary diagnostics
        return "package_failed"
    return code if type(code) is str and code in SAFE_CODES else "package_failed"


def partial_nested_cleanup(owner: Any, packages: ModuleType) -> bool:
    """Only this known builder constructor may have allocated its marked private work.

    Constructor code starts no children. Missing ownership/marker observations remain
    unknown and withhold outer removal; a close request alone never proves cleanup.
    """
    try:
        require(
            type(getattr(owner, "commands", None)) is int and owner.commands == 0,
            "cleanup_incomplete",
        )
        require(
            not getattr(owner, "children", ()) and not getattr(owner, "reservations", {}),
            "cleanup_incomplete",
        )
        work = getattr(owner, "work", None)
        require(isinstance(work, Path), "cleanup_incomplete")
        assert isinstance(work, Path)
        require(
            work.parent == Path("/private/tmp")
            and work.name.startswith("p3-standalone-package-")
            and not work.is_symlink(),
            "cleanup_incomplete",
        )
        info = work.lstat()
        require(
            stat.S_ISDIR(info.st_mode)
            and stat.S_IMODE(info.st_mode) == 0o700
            and info.st_uid == os.geteuid()
            and work.resolve() == work,
            "cleanup_incomplete",
        )
        require(
            packages._read_private(work / "owned-marker", 64) == b"p3-standalone-package-v1\n",
            "cleanup_incomplete",
        )
        shutil.rmtree(work)
        return not work.exists()
    except Exception:  # noqa: BLE001 - an unknown partial owner can never authorize removal.
        return False


def application_child_cleanup(work: Path | None, retained: Path, children: Any) -> dict[str, Any]:
    """Observe exact fixture receipts; unknown PIDs never authorize a kill or removal."""
    owners = [
        child for child in children.children if child.output_directory.name == "app-execution"
    ]
    require(len(owners) <= 1, "cleanup_incomplete")
    if not owners:
        return {"schema_version": 1, "nonce": None, "groups": []}
    require(work is not None, "cleanup_incomplete")
    assert work is not None
    app = work / "p3-application"
    policy, raw = child_record(app / "native-child-policy.json")
    require(
        set(policy) == {"schemaVersion", "nonce"}
        and type(policy["schemaVersion"]) is int
        and policy["schemaVersion"] == 1,
        "cleanup_incomplete",
    )
    write(retained / "root-application/native-child-policy.json", raw)
    proof = application_child_records(
        app / "native-child-groups",
        policy["nonce"],
        complete=False,
        parent_pid=owners[0].pid,
        retained=retained / "root-application/native-child-groups",
    )
    write(retained / "root-application/native-child-groups-proof.json", json_bytes(proof))
    return proof


def validate_child_group_entries(groups: Any, parent_pid: int) -> None:
    require(type(groups) is list and len(groups) == 10, "retention_failed")
    fields = {
        "test_id",
        "slot",
        "parent_pid",
        "pid",
        "pgid",
        "returncode",
        "direct_reaped",
        "pipes_drained",
        "group_absent",
    }
    names = set()
    pids = set()
    for number, group in enumerate(groups, 1):
        require(type(group) is dict and set(group) == fields, "retention_failed")
        test_id = group["test_id"]
        require(type(test_id) is str, "retention_failed")
        name = test_id.rsplit(".", 1)[-1]
        require(
            name in APPLICATION_CHILD_RETURNS
            and test_id
            in {
                "test_channel_policy_native_worker_process.WorkerProcessTests." + name,
                "tests.test_channel_policy_native_worker_process.WorkerProcessTests." + name,
            },
            "retention_failed",
        )
        require(
            group["slot"] == "child-" + str(number).zfill(2)
            and type(group["parent_pid"]) is int
            and group["parent_pid"] == parent_pid,
            "retention_failed",
        )
        require(
            type(group["pid"]) is int
            and group["pid"] > 1
            and type(group["pgid"]) is int
            and group["pgid"] == group["pid"]
            and group["pid"] != parent_pid,
            "retention_failed",
        )
        require(
            type(group["returncode"]) is int
            and group["returncode"] in APPLICATION_CHILD_RETURNS[name]
            and all(group[k] is True for k in ("direct_reaped", "pipes_drained", "group_absent")),
            "retention_failed",
        )
        names.add(name)
        pids.add(group["pid"])
    require(names == set(APPLICATION_CHILD_RETURNS) and len(pids) == 10, "retention_failed")


def observe_process_groups(
    outer: Any,
    nested: Any,
    *,
    root_application: bool = False,
    fixture: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Snapshot only directly retained owners; these observations never select a PID action."""
    roles = outer_roles(root_application=root_application)
    records: list[dict[str, Any]] = []

    def record(owner: str, role: str, child: Any) -> None:
        require(type(child.pid) is int and child.pid > 1, "retention_failed")
        require(child.returncode is None or type(child.returncode) is int, "retention_failed")
        require(type(child.cleanup_failed) is bool, "retention_failed")
        settled = getattr(child, "group_settled", False)
        require(type(settled) is bool, "retention_failed")
        records.append(
            {
                "owner": owner,
                "role": role,
                "owned_pid": child.pid,
                "returncode": child.returncode,
                "cleanup_failed": child.cleanup_failed,
                "group_settled": settled,
            }
        )

    for child in outer.children:
        role = child.output_directory.name
        require(role in roles, "retention_failed")
        record("outer", role, child)
    for number, child in enumerate(getattr(nested, "children", ()), 1):
        require(number <= len(NESTED_ROLE_ORDER), "retention_failed")
        role = NESTED_ROLE_ORDER[number - 1]
        require(nested.outputs[child.pid].name == f"{number:02d}-{role}", "retention_failed")
        record("p3_offline", role, child)
    require(len(records) <= MAX_GROUPS, "retention_failed")
    if root_application:
        child_groups = fixture["groups"] if fixture is not None else None
        return {
            "schema_version": 2,
            "groups": records,
            "test_child_groups": child_groups,
            "total_groups": len(records) + len(child_groups) if child_groups is not None else None,
        }
    return {"schema_version": 1, "groups": records}


def validate_process_groups(value: dict[str, Any], *, root_application: bool = False) -> None:
    roles = outer_roles(root_application=root_application)
    expected_groups = EXPECTED_GROUPS + (7 if root_application else 0)
    require(
        set(value)
        == (
            {"schema_version", "groups", "test_child_groups", "total_groups"}
            if root_application
            else {"schema_version", "groups"}
        )
        and type(value["schema_version"]) is int
        and value["schema_version"] == (2 if root_application else 1),
        "retention_failed",
    )
    groups = value["groups"]
    require(type(groups) is list and len(groups) == expected_groups, "retention_failed")
    for group in groups:
        require(
            type(group) is dict
            and set(group)
            == {"owner", "role", "owned_pid", "returncode", "cleanup_failed", "group_settled"},
            "retention_failed",
        )
        require(
            type(group["owner"]) is str
            and group["owner"] in {"outer", "p3_offline"}
            and type(group["role"]) is str,
            "retention_failed",
        )
        require(
            type(group["owned_pid"]) is int
            and group["owned_pid"] > 1
            and type(group["returncode"]) is int
            and group["returncode"] == 0
            and group["cleanup_failed"] is False
            and group["group_settled"] is True,
            "retention_failed",
        )
    outer = groups[: len(roles)]
    nested = groups[len(roles) :]
    require(
        all(g["owner"] == "outer" for g in outer)
        and {g["role"] for g in outer} == roles
        and all(g["owner"] == "p3_offline" for g in nested)
        and tuple(g["role"] for g in nested) == NESTED_ROLE_ORDER
        and len({g["owned_pid"] for g in groups}) == expected_groups,
        "retention_failed",
    )

    if root_application:
        parent = next(g["owned_pid"] for g in outer if g["role"] == "app-execution")
        validate_child_group_entries(value["test_child_groups"], parent)
        require(
            type(value["total_groups"]) is int
            and value["total_groups"] == 42
            and len(
                {g["owned_pid"] for g in groups} | {g["pid"] for g in value["test_child_groups"]}
            )
            == 42,
            "retention_failed",
        )


def run(
    root: Path, target: Path, *, channel_origin: bool = False, root_application: bool = False
) -> dict[str, Any]:
    channel_origin, root_application = modes(
        channel_origin=channel_origin, root_application=root_application
    )
    roles = outer_roles(root_application=root_application)
    starter, scoped, packages = helpers(root)
    started = time.monotonic()
    final, deadline = started + TOTAL_SECONDS, started + TOTAL_SECONDS - CLEANUP_SECONDS
    retained = target.with_name(target.stem + "-artifacts")
    require(
        not target.exists() and not target.is_symlink() and not retained.exists(), "invalid_input"
    )
    retained.mkdir(mode=0o700)
    work: Path | None = None
    commands = retained / "outer-commands"
    commands.mkdir(mode=0o700)
    children = starter.Children(commands, deadline, final, roles=roles)
    nested: Any = None
    nested_constructed = False
    nested_partial_verified: bool | None = None
    failure: BaseException | None = None
    failure_stage: str | None = None
    cleanup_errors: list[dict[str, str]] = []
    cleanup_complete = False
    proof: dict[str, Any] = {}
    fixture_proof: dict[str, Any] | None = None
    fixture_settled = not root_application
    initial: dict[str, str] = {}
    stage = "input"

    def usage() -> tuple[int, int, int]:
        if nested is None or not nested_constructed:
            return 0, 0, 0
        return nested.commands, nested.captured, sum(nested.reservations.values())

    def command(role: str, argv: list[str], *, cwd: Path, environment: dict[str, str]) -> bytes:
        n, captured, reserved = usage()
        combined_budget(
            children.count + 1,
            children.captured,
            children.reservations,
            n,
            captured,
            reserved,
            new_outer_reservation=2 * starter.MAX_STREAM_BYTES,
        )
        child = children.start(role, argv, environment, cwd=cwd)
        raw = children.finish(child)
        require(type(raw) is bytes, "consumer_failed")
        return bytes(raw)

    try:
        work = Path(tempfile.mkdtemp(prefix="p2-result-installed-", dir="/private/tmp")).resolve()
        write(work / "owned-marker", b"p2-result-package-bridge-v1\n")
        initial = source_snapshot(
            root, channel_origin=channel_origin, root_application=root_application
        )
        write(retained / "source-before.json", json_bytes(initial))
        write(
            retained / "plan.json",
            json_bytes(plan(channel_origin=channel_origin, root_application=root_application)),
        )
        stage = "p2_prepare_installed"
        # Four original commands and their exact archived/install payload verification.
        (retained / "p2").mkdir(mode=0o700)
        p2 = starter.prepare_installed(root, work, retained / "p2", children)
        require(len(p2["payloads"]) == 124)
        stage = "p2_archive_parity"
        manifest_raw = (root / "projects/channel-continuity/package.json").read_bytes()
        p2_parity, archive_manifest = npm_parity(
            p2["archive"].read_bytes(), p2["payloads"], manifest_raw
        )
        installed = (
            p2["consumer"] / "node_modules/@livekit-ecosystem/channel-continuity"
        ).resolve()
        require(installed.is_relative_to(p2["consumer"]) and not installed.is_relative_to(root))
        require((installed / "package.json").read_bytes() == archive_manifest)
        p2_parity["installed_manifest_raw_equal"] = True
        write(retained / "p2/source-package.json", manifest_raw)
        write(retained / "p2/archive-package.json", archive_manifest)
        write(retained / "p2-manifest-parity.json", json_bytes(p2_parity))
        consumer = p2["consumer"]
        p2_probe = p2_consumer(channel_origin=channel_origin).encode()
        write(consumer / "result-consumer.ts", p2_probe)
        write(retained / "consumers/result-consumer.ts", p2_probe)
        write(
            consumer / "tsconfig.result.json",
            json_bytes({"extends": "./tsconfig.json", "include": ["result-consumer.ts"]}),
        )
        wire = (root / "contracts/delegation/result-receiver-v1.json").read_bytes()
        write(consumer / "receiver-wire.json", wire)
        environment = starter.offline_environment()
        stage = "p2_result_types"
        command(
            "p2-result-types",
            [
                str(p2["node"]),
                str(consumer / "node_modules/typescript/lib/tsc.js"),
                "--project",
                "tsconfig.result.json",
            ],
            cwd=consumer,
            environment=environment,
        )
        stage = "p2_result_codecs"
        raw = command(
            "p2-result-codecs",
            [
                str(p2["node"]),
                str(consumer / "dist/result-consumer.js"),
                str(consumer / "receiver-wire.json"),
            ],
            cwd=consumer,
            environment=environment,
        )
        intent = json.loads(json.loads(wire)["intent_canonical"])
        proof["p2_new_api"] = selected_report(
            raw,
            {
                "schema_version": 1,
                "status": "passed",
                "private_npm_paths": True,
                "imports_no_IO": True,
                "canonical_equal": True,
                "negative_cases": 9,
                "original_result_sha": intent["result_sha256"],
                "notice_hash_separate": True,
                **({"operation_only_config": True} if channel_origin else {}),
            },
        )
        stage = "p3_offline_builder"
        nested_target = retained / "p3-offline.json"
        nested = scoped.ScopedPackageRun.__new__(scoped.ScopedPackageRun)
        scoped.ScopedPackageRun.__init__(
            nested,
            root,
            nested_target,
            outer_children=lambda: children.count,
            outer_capture=lambda: children.captured,
            outer_reservations=lambda: children.reservations,
            deadline=deadline,
            final_deadline=final,
        )
        nested_constructed = True
        nested.offline()
        require(nested.commands == 17 and nested.python is not None)
        stage = "p3_archive_parity"
        p1_expected = packages._payload(root / "projects/agent-continuity/python", "continuity_lab")
        p3_expected = packages._payload(
            root / "projects/delegation-reliability/python", "delegation_reliability"
        )
        proof["p1_payloads"] = wheel_parity(
            (nested.retained / packages.ARTIFACT_PATHS["p1-wheel"]).read_bytes(),
            p1_expected,
            "continuity_lab",
            77,
        )
        proof["p3_payloads"] = wheel_parity(
            (nested.retained / packages.ARTIFACT_PATHS["p3-wheel"]).read_bytes(),
            p3_expected,
            "delegation_reliability",
            39,
        )
        with tarfile.open(
            nested.retained / packages.ARTIFACT_PATHS["specialist-npm"], mode="r:gz"
        ) as archive:
            count = sum(
                member.isfile() and member.name != "package/package.json" for member in archive
            )
        require(count == 32)
        proof["specialist_npm_payloads"] = count
        app = work / "p3-application"
        app.mkdir(mode=0o700)
        proof["unadapted_inputs"] = copy_inputs(
            root, app, retained, channel_origin=channel_origin, root_application=root_application
        )
        p3_type_probe = p3_types(channel_origin=channel_origin).encode()
        p3_execution_probe = p3_execution(channel_origin=channel_origin).encode()
        write(app / "result-port-types.py", p3_type_probe)
        write(app / "result-port-execution.py", p3_execution_probe)
        write(retained / "consumers/result-port-types.py", p3_type_probe)
        write(retained / "consumers/result-port-execution.py", p3_execution_probe)
        stage = "p3_result_types"
        command(
            "p3-result-types",
            [
                str(Path(sys.executable).absolute()),
                "-I",
                "-m",
                "mypy",
                "--strict",
                "--follow-imports=silent",
                "--python-executable",
                str(nested.python),
                "--cache-dir",
                str(work / "new-api-mypy-cache"),
                str(app / "result-port-types.py"),
            ],
            cwd=app,
            environment=environment,
        )
        stage = "p3_result_execution"
        raw = command(
            "p3-result-execution",
            [str(nested.python), "-I", str(app / "result-port-execution.py")],
            cwd=app,
            environment=environment,
        )
        proof["p3_new_api"] = selected_report(
            raw,
            p3_expected_report(channel_origin=channel_origin),
        )
        if root_application:
            stage = "root_application_native_fixtures"
            require(
                type(nested.node) is str
                and Path(nested.node).absolute() == Path(p2["node"]).absolute(),
                "missing_setup",
            )
            descriptor = native_sdk_fixture(
                app,
                installed,
                Path(p2["node"]).absolute(),
                p2["payloads"],
                archive_manifest,
                digest(p2["archive"].read_bytes()),
            )
            write(app / "public-native-sdk-fixture.json", json_bytes(descriptor))
            # Same executable already passed the nested public Node24.22.2
            # assertion. application_checks narrows only app-execution's PATH.
            stage = "root_application"
            proof["root_application"] = application_checks(
                root, work, retained, app, nested.python, environment, command, packages
            )
        require(
            children.count == len(roles)
            and nested.commands == 17
            and children.count + nested.commands
            == EXPECTED_GROUPS + (7 if root_application else 0),
            "child_budget",
        )
        stage = "source_final"
        require(
            source_snapshot(root, channel_origin=channel_origin, root_application=root_application)
            == initial,
            "source_changed",
        )
    except BaseException as error:  # noqa: BLE001 - retain the primary error while closing all owned groups.
        failure, failure_stage = error, stage
    finally:

        def cleanup_failure(failed_stage: str, error: BaseException) -> None:
            nonlocal failure, failure_stage
            cleanup_errors.append({"stage": failed_stage, "code": finite_code(error)})
            if failure is None:
                failure, failure_stage = error, failed_stage

        # Outer probes borrow the nested installed prefix. Reap and capture them first.
        try:
            children.close()
        except BaseException as error:  # noqa: BLE001 - cleanup must preserve the primary failure.
            cleanup_failure("outer_cleanup", error)
        for child in children.children:
            if starter.settled(child):
                try:
                    children.capture(child)
                except BaseException as error:  # noqa: BLE001 - capture every independent settled child.
                    cleanup_failure("outer_capture", error)
        outer_settled = children.all_settled()
        if root_application and outer_settled:
            try:
                fixture_proof = application_child_cleanup(work, retained, children)
                fixture_settled = True
            except BaseException as error:  # noqa: BLE001 - incomplete new-session ownership preserves dependent state
                cleanup_failure("application_child_cleanup", error)
        nested_settled = nested is None
        if outer_settled and fixture_settled and nested is not None:
            if nested_constructed:
                try:
                    nested.cleanup_resources()
                    nested_settled = nested.children_settled() and not nested.work.exists()
                    if nested_settled and nested.passed == set(packages.OFFLINE_CASES):
                        proof["p3_offline"] = nested.successful_report()
                except BaseException as error:  # noqa: BLE001 - preserve failure and borrowed owner.
                    cleanup_failure("nested_cleanup", error)
            else:
                nested_partial_verified = partial_nested_cleanup(nested, packages)
                nested_settled = nested_partial_verified
                if not nested_settled:
                    cleanup_failure("nested_partial_cleanup", PackageError("cleanup_incomplete"))
        if outer_settled and fixture_settled and nested_settled and work is None:
            cleanup_complete = True
        if outer_settled and fixture_settled and nested_settled and work is not None:
            try:
                marker = work / "owned-marker"
                require(
                    work.parent == Path("/private/tmp")
                    and work.name.startswith("p2-result-installed-")
                    and not work.is_symlink()
                    and marker.read_bytes() == b"p2-result-package-bridge-v1\n",
                    "cleanup_incomplete",
                )
                shutil.rmtree(work)
                cleanup_complete = not work.exists()
            except BaseException as error:  # noqa: BLE001 - cleanup must preserve the primary failure.
                cleanup_failure("work_cleanup", error)
        try:
            n, captured, reserved = usage()
            combined_budget(
                children.count, children.captured, children.reservations, n, captured, reserved
            )
        except BaseException as error:  # noqa: BLE001 - retain actual settled capture accounting.
            cleanup_failure("final_accounting", error)
        process_groups_sha256: str | None = None
        try:
            groups = observe_process_groups(
                children, nested, root_application=root_application, fixture=fixture_proof
            )
            groups_raw = json_bytes(groups)
            require(len(groups_raw) <= 32768, "retention_failed")
            write(retained / "process-groups.json", groups_raw)
            process_groups_sha256 = digest(groups_raw)
            if failure is None and cleanup_complete:
                validate_process_groups(groups, root_application=root_application)
        except BaseException:  # noqa: BLE001 - owner observations fail closed without raw diagnostics.
            cleanup_failure("process_groups", PackageError("retention_failed"))
        nested_work = None if nested is None else getattr(nested, "work", None)
        proof["ownership"] = {
            **(
                {
                    "application_test_groups": len(fixture_proof["groups"])
                    if fixture_proof
                    else None,
                    "application_test_groups_settled": fixture_settled,
                    "application_test_ownership_unknown": not fixture_settled,
                    "total_owned_groups": children.count
                    + (0 if nested is None else getattr(nested, "commands", 0))
                    + len(fixture_proof["groups"])
                    if fixture_proof
                    else None,
                }
                if root_application
                else {}
            ),
            "outer_groups": children.count,
            "outer_capture_bytes": children.captured,
            "outer_reserved_bytes": children.reservations,
            "nested_groups": 0 if nested is None else getattr(nested, "commands", 0),
            "nested_capture_bytes": 0 if nested is None else getattr(nested, "captured", 0),
            "outer_settled": outer_settled,
            "nested_settled": nested_settled,
            "nested_construction_complete": nested_constructed,
            "nested_partial_cleanup_verified": nested_partial_verified,
            "nested_ownership_unknown": nested is not None
            and not nested_constructed
            and nested_partial_verified is not True,
            "cleanup_complete": cleanup_complete,
            "retained_work": str(work) if work is not None and work.exists() else None,
            "nested_retained_work": str(nested_work)
            if isinstance(nested_work, Path) and nested_work.exists()
            else None,
            "cleanup_errors": [dict(error) for error in cleanup_errors],
        }
        # Existing physical inventory enforces private files, <=2048 entries and16MiB.
        retained_index_sha256: str | None = None
        try:
            write(retained / "ownership.json", json_bytes(proof["ownership"]))
            index_raw = starter.json_bytes(starter.retained_inventory(retained))
            starter.write_private(retained / "retained-index.json", index_raw)
            starter.validate_retained_index(retained, index_raw)
            retained_index_sha256 = digest(index_raw)
        except BaseException:  # noqa: BLE001 - no retention failure may become a pass.
            cleanup_failure("retained_index", PackageError("retention_failed"))
    status = "passed" if failure is None and cleanup_complete else "failed"
    value = {
        "schema_version": 1,
        "mode": package_mode(channel_origin=channel_origin, root_application=root_application),
        "status": status,
        "code": "ok" if status == "passed" else finite_code(failure),
        "duration_seconds": time.monotonic() - started,
        "cleanup_complete": cleanup_complete,
        "failure_stage": failure_stage,
        "child_commands": children.count
        + (0 if nested is None else getattr(nested, "commands", 0)),
        "p3_offline_assertions": 8 if "p3_offline" in proof else 0,
        "p3_installed_legacy_fake_port_tests": 20 if "p3_new_api" in proof else 0,
        "p3_installed_origin_fake_port_tests": (
            sum(ORIGIN_TEST_COUNTS.values()) if channel_origin and "p3_new_api" in proof else 0
        ),
        "channel_origin": channel_origin,
        "source_actual_assertions": 0,
        "installed_actual_assertions": 0,
        "provider_calls": False,
        "retained_index_sha256": retained_index_sha256,
        "process_groups_sha256": process_groups_sha256,
        "cleanup_errors": [dict(error) for error in cleanup_errors],
        "proof": proof,
    }
    if root_application:
        value.update(
            root_application=True,
            builder_process_groups=children.count
            + (0 if nested is None else getattr(nested, "commands", 0)),
            test_child_process_groups=len(fixture_proof["groups"]) if fixture_proof else None,
            total_process_groups=children.count
            + (0 if nested is None else getattr(nested, "commands", 0))
            + len(fixture_proof["groups"])
            if fixture_proof
            else None,
            root_application_installed_fake_port_tests=sum(ROOT_APPLICATION_TEST_COUNTS.values())
            if "root_application" in proof
            else 0,
        )
    raw = json_bytes(value)
    # Absolute final fence follows nested reports, capture/index hashing and serialization.
    # There is no deadline extension for late cleanup, even when all owners finally settle.
    if value["status"] == "passed" and time.monotonic() >= final:
        value.update(status="failed", code="deadline_exceeded", failure_stage="final_deadline")
        raw = json_bytes(value)
    write(target, raw)
    return value


def report_path(root: Path, requested: Path | None) -> Path:
    base = root / ".local/validation/p2-result-receiver-package"
    target = requested or base / (str(time.time_ns()) + ".json")
    if not target.is_absolute():
        target = root / target
    require(
        target.parent == base and not target.exists() and not target.is_symlink(), "invalid_input"
    )
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(base.resolve() == base and stat.S_IMODE(base.stat().st_mode) == 0o700, "invalid_input")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--channel-origin", action="store_true")
    parser.add_argument("--root-application", action="store_true")
    args = parser.parse_args(argv)
    channel_origin, root_application = modes(
        channel_origin=args.channel_origin, root_application=args.root_application
    )
    if args.plan:
        print(
            json_bytes(
                plan(channel_origin=channel_origin, root_application=root_application)
            ).decode(),
            end="",
        )
        return 0
    try:
        value = run(
            ROOT,
            report_path(ROOT, args.report),
            channel_origin=channel_origin,
            root_application=root_application,
        )
    except Exception as error:  # noqa: BLE001 - only a finite code reaches the command boundary.
        code = finite_code(error)
        print(
            json_bytes(
                {
                    "schema_version": 1,
                    "mode": package_mode(
                        channel_origin=channel_origin, root_application=root_application
                    ),
                    "channel_origin": channel_origin,
                    **({"root_application": True} if root_application else {}),
                    "status": "failed",
                    "code": code,
                }
            ).decode(),
            end="",
        )
        return 1
    print(json_bytes(value).decode(), end="")
    return 0 if value["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
