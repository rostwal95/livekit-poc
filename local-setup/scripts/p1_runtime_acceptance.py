"""Fresh local infrastructure acceptance; never adopt a previous G/H report.

The generic harness receives only the closed numeric report. Raw command output
stays byte bounded and private; retained references point to fresh owned evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import stat
import sys
import tempfile
import time
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from harness.process_control import (
    OwnedProcess,
    ProcessControlError,
    ProcessOutputLimit,
    ProcessTimeout,
)
from harness.report_runner import read_report

CASES = {"P1-14": 9, "P1-18": 1, "P1-20": 2}
DEADLINE_SECONDS = 840
MODEL_MANIFEST = "b57d52bed5e252bfe868aac75265e5318ce5de19f4a65e86b51125170b7b61e9"
POST_COMMIT_ASSERTIONS = (
    "pg_effect_cases.PostgresEffectCases.test_cancel_before_dispatch_retains_committed_intent_and_prevents_claim",
    "pg_effect_cases.PostgresEffectCases.test_dispatch_reservation_wins_cancel_then_known_success_wins_deadline",
    "pg_conversation_cases.PostgresConversationCases.test_business_outcome_delivery_and_later_cancel_remain_separate",
)


class EvidenceError(ValueError):
    """Only a fixed category is retained; dependency details remain private."""


def load_tool(path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location("runtime_tool_" + uuid4().hex, path)
    if specification is None or specification.loader is None:
        raise EvidenceError("required_tool_unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError("invalid_evidence")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise EvidenceError("invalid_evidence")


def parse_json(raw: bytes, maximum: int = 2097152) -> Any:
    if not 1 <= len(raw) <= maximum:
        raise EvidenceError("invalid_evidence")
    try:
        return json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise EvidenceError("invalid_evidence") from None


def read_json(path: Path) -> Any:
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 2097152:
                raise EvidenceError("invalid_evidence")
            return parse_json(stream.read(2097153))
    except OSError:
        raise EvidenceError("invalid_evidence") from None


def require(condition: bool) -> None:
    if not condition:
        raise EvidenceError("required_assertion_failed")


def count(value: object, expected: int) -> None:
    require(type(value) is int and value == expected)


def verify_worker_quiescence(value: object) -> None:
    """Require the producer's complete successful maintenance handshake."""
    require(type(value) is dict)
    assert isinstance(value, dict)
    observations = {"quiescence_checks", "resume_checks", "idle_snapshots"}
    signals = {"quiesce_signal_requests", "resume_signal_requests"}
    require(
        set(value)
        == {"schema_version", "phase", "quiescence_observed", "request_unresolved"}
        | observations
        | signals
    )
    count(value["schema_version"], 1)
    require(type(value["phase"]) is str and value["phase"] == "resumed")
    require(value["quiescence_observed"] is True and value["request_unresolved"] is False)
    for field in observations:
        number = value[field]
        require(type(number) is int and 1 <= number <= 2001)
    for field in signals:
        count(value[field], 1)


def positive(value: object) -> None:
    if type(value) not in {int, float}:
        raise EvidenceError("required_assertion_failed")
    assert isinstance(value, (int, float))
    require(0 < value <= 1e12 and math.isfinite(value))


def source_hashes(root: Path, *, native: bool) -> dict[str, str]:
    packages = {
        "continuity_lab": root / "projects/agent-continuity/python/src/continuity_lab",
        "services/control_api": root / "services/control_api",
    }
    if native:
        packages["services/conversation_agent"] = root / "services/conversation_agent"
    require(all((path / "__init__.py").is_file() for path in packages.values()))
    return {
        name + "/" + path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, source in packages.items()
        for path in source.glob("*.py")
    }


def selected_real_profile(environment: dict[str, str]) -> str:
    value = environment.get("P1_ACCEPTANCE_REAL_PROFILE", "local_real")
    require(type(value) is str and value in {"local_real", "provider_real"})
    return value


def read_trace_bytes(path: Path) -> bytes:
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 1 <= info.st_size <= 2097152)
        raw = stream.read(2097153)
    require(1 <= len(raw) <= 2097152)
    return raw


def verify_provider_trust(value: Any, artifact: Path) -> None:
    trust = value.get("provider_trust")
    require(type(trust) is dict)
    if trust == {"source": "image_os"}:
        require(not (artifact / "provider-trust.json").exists())
        return
    require(set(trust) == {"source", "bundle_sha256", "bundle_bytes", "native_only_mount_verified"})
    require(trust["source"] == "explicit_ca_bundle" and trust["native_only_mount_verified"] is True)
    require(
        type(trust["bundle_sha256"]) is str
        and re.fullmatch(r"[a-f0-9]{64}", trust["bundle_sha256"]) is not None
    )
    require(type(trust["bundle_bytes"]) is int and 1 <= trust["bundle_bytes"] <= 524288)
    require(read_json(artifact / "provider-trust.json") == trust)


def verify_browser(
    value: Any, *, root: Path, run_id: str, real: bool, artifact: Path, profile: str = "local_real"
) -> int:
    require(type(profile) is str and profile in {"local_real", "provider_real"})
    require(type(value) is dict and value.get("status") == "passed")
    require(value.get("cleanup_verified") is True and value.get("run_id") == run_id)
    require(value.get("mode") == (profile if real else "local_synthetic_scripted"))
    require(value.get("module_hashes") == source_hashes(root, native=True))
    browser = value.get("browser", {})
    expected = 2 if real else 6
    require(type(browser) is dict)
    count(browser.get("required_cases"), expected)
    count(browser.get("passed_cases"), expected)
    # Re-run the same exact public verifier over fresh raw browser assertions,
    # including actual runner skips/retries. Numeric summary counts alone cannot pass.
    verifier = load_tool(
        root / "local-setup/scripts" / ("p1_real_media.py" if real else "phase_g_demo.py")
    )
    observations = read_json(
        artifact
        / ("real-browser-observations.json" if real else "business-browser-observations.json")
    )
    if real:
        stats = read_json(artifact / "playwright-stats.json")
        require(type(stats) is dict and set(stats) == {"schema_version", "run_id", "stats"})
        require(
            type(stats["schema_version"]) is int
            and stats["schema_version"] == 1
            and stats["run_id"] == run_id
        )
        require(
            type(stats["stats"]) is dict
            and set(stats["stats"]) == {"expected", "unexpected", "skipped", "flaky"}
        )
        require(all(type(number) is int for number in stats["stats"].values()))
        runner = {"stats": stats["stats"]}
    else:
        runner = read_json(artifact / "playwright.json")
    observed = (
        verifier.verify_browser(observations, runner, run_id=run_id, mode=profile)
        if real
        else verifier.verify_browser(observations, runner)
    )
    require(observed == browser)
    traces = value.get("traces", {})
    require(
        type(traces) is dict
        and set(traces) == {"business-api", "conversation-agent", "durable-worker"}
    )
    for trace in traces.values():
        require(type(trace) is dict)
        positive(trace.get("span_count"))
        require(
            trace.get("privacy_verified") is True and trace.get("current_task_correlated") is True
        )
        require(trace.get("query_api") == "v3_raw_otlp")
    expected_tasks = 9 if real else 1
    authority = value.get("authority", {})
    require(type(authority) is dict)
    for field, number in {
        "revision": 1,
        "mutations": 1,
        "apply_calls": 1,
        "inquiries": expected_tasks,
        "receiver_events": expected_tasks,
    }.items():
        count(authority.get(field), number)
    require(
        value.get("durable_counts") == {"tasks": expected_tasks, "intents": 1, "consumptions": 1}
    )
    if real:
        require(type(value.get("schema_version")) is int and value["schema_version"] == 1)
        if profile == "local_real":
            require(value.get("model_manifest_sha256") == MODEL_MANIFEST)
            setup = value.get("model_setup", {})
            require(
                type(setup) is dict
                and setup.get("status") == "verified"
                and setup.get("profile") == "p1-local-real-v1"
                and setup.get("runtime_downloads") is False
            )
            count(setup.get("files"), 10)
        else:
            verify_provider_trust(value, artifact)
            require(
                not {
                    "model_manifest_sha256",
                    "model_setup",
                    "engine_provenance",
                    "engine_inference",
                }
                & value.keys()
            )
            require(
                value.get("provider_inference")
                == {
                    "profile": "provider_real",
                    "models": {"stt": "nova-3", "llm": "gpt-5.4-mini", "tts": "eleven_v4_turbo"},
                    "providers": {"stt": "deepgram", "llm": "openai", "tts": "elevenlabs"},
                    "external_resources": "unobserved",
                    "actual_sdk_usage": True,
                }
            )
            _, digest = verifier.declaration(root, mode=profile)
            require(
                value.get("declaration_sha256") == digest
                and value.get("gate_source_hashes") == verifier.gate_inventory(root, mode=profile)
            )
            versions = value.get("runtime_versions", {})
            require(
                type(versions) is dict
                and all(
                    versions.get("livekit-plugins-" + provider) == "1.8.11"
                    for provider in ("deepgram", "openai", "elevenlabs")
                )
            )
            pg, supplier = value.get("slow_postgres", {}), value.get("held_supplier", {})
            require(
                type(pg) is dict
                and pg.get("native_wait_observed") is True
                and pg.get("schema_advisory_wait_verified") is True
                and pg.get("release_within_lock_timeout") is True
            )
            positive(pg.get("native_wait_seconds"))
            require(
                type(supplier) is dict
                and supplier.get("sqlite_exclusive_observed") is True
                and supplier.get("controls_completed_while_held") is True
                and supplier.get("release_within_provider_timeout") is True
            )
            positive(supplier.get("quote_wait_seconds"))
        cohort = value.get("cohort", {})
        require(type(cohort) is dict)
        verify_worker_quiescence(cohort.get("worker_quiescence"))
        for field in (
            "accepted",
            "pending_before_end",
            "pending_after_end",
            "inquiry_succeeded_after_end",
            "explicitly_cancelled_after_measurement",
            "cleanup_deliveries",
        ):
            count(cohort.get(field), 8)
        count(cohort.get("lost_accepted"), 0)
        require(cohort.get("pre_human_zero_apply_proven") is True)
        for field in ("durable_identity_payload_matches", "independent_inquiry_receipts_matched"):
            count(cohort.get(field), 9)
        native = traces["conversation-agent"]
        require(
            set(native.get("models", []))
            == (
                {"nova-3", "gpt-5.4-mini", "eleven_v4_turbo"}
                if profile == "provider_real"
                else {"base.en", "qwen3:4b-instruct", "en_US-ljspeech-medium"}
            )
        )
        require({"submit_investigation", "get_case"} <= set(native.get("tools", [])))
        resources = value.get("resources", {})
        require(
            type(resources) is dict
            and set(resources)
            == (
                {"native", "api", "worker"}
                if profile == "provider_real"
                else {"native", "llm", "stt", "tts"}
            )
        )
        for role, observation in resources.items():
            require(type(observation) is dict)
            require(
                verifier.resource_window(
                    observation.get("before"), observation.get("after"), role=role, mode=profile
                )
                == observation
            )
        if profile == "local_real":
            engines = value.get("engine_inference", {})
            require(type(engines) is dict and set(engines) == {"stt", "tts"})
            # Exact engine counter projection is verified by the native gate; presence
            # alone is insufficient: both roles must prove real successful work.
            for engine in engines.values():
                require(type(engine) is dict)
                positive(engine.get("succeeded"))
                positive(engine.get("requests"))
                require(engine["requests"] == engine["succeeded"])
                positive(engine.get("processed_input_bytes"))
                positive(engine.get("processed_output_bytes"))
                positive(engine.get("duration_seconds"))
                count(engine.get("failed"), 0)
        else:
            expected_pairs = {
                "nova-3": "deepgram",
                "gpt-5.4-mini": "openai",
                "eleven_v4_turbo": "elevenlabs",
            }
            require(
                native.get("model_providers") == expected_pairs
                and set(native.get("providers", [])) == set(expected_pairs.values())
            )
            phase = load_tool(root / "local-setup/scripts/phase_g_demo.py")
            records = read_json(artifact / "provider-sdk-records.json")
            require(
                type(records) is dict
                and set(records) == {"schema_version", "run_id", "mode", "records"}
            )
            require(
                type(records["schema_version"]) is int
                and records["schema_version"] == 1
                and records["run_id"] == run_id
                and records["mode"] == profile
            )
            require(phase.verify_sdk(records["records"], mode=profile) == value.get("sdk"))
            task = value.get("original_task_id")
            require(type(task) is str)
            for service, summary in traces.items():
                raw = read_trace_bytes(artifact / ("provider-trace-" + service + ".json"))
                require(
                    phase.parse_jaeger_v3(raw, service=service, task_id=task, mode=profile)
                    == summary
                )

    else:
        pg = value.get("slow_postgres", {})
        supplier = value.get("held_supplier", {})
        require(type(pg) is dict and type(supplier) is dict)
        require(
            pg.get("native_wait_observed") is True
            and pg.get("schema_advisory_wait_verified") is True
            and pg.get("release_within_lock_timeout") is True
        )
        positive(pg.get("native_wait_seconds"))
        require(
            supplier.get("sqlite_exclusive_observed") is True
            and supplier.get("controls_completed_while_held") is True
            and supplier.get("release_within_provider_timeout") is True
        )
        positive(supplier.get("quote_wait_seconds"))
    return expected


def verify_h2(value: Any, *, root: Path, driver_sha256: str) -> int:
    require(
        type(value) is dict and value.get("schema_version") == 1 and value.get("status") == "passed"
    )
    require(
        value.get("driver_sha256") == driver_sha256 and value.get("coverage") == "selected_case"
    )
    require(value.get("selected_case_names") == ["slow-shutdown-w2"])
    declaration = read_json(root / "harness/workloads/p1-reliability-v1.json")
    require(type(declaration) is dict)
    digest = hashlib.sha256(
        json.dumps(declaration, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    require(value.get("manifest_sha256") == digest)
    require(value.get("base_manifest_sha256") == declaration.get("base_manifest_sha256"))
    count(value.get("declared_case_count"), 4)
    require(value.get("cleanup_failures") == [] and value.get("failure") is None)
    cases = value.get("cases")
    require(type(cases) is list and len(cases) == 1)
    item = cases[0]
    require(
        type(item) is dict
        and item.get("case") == "slow-shutdown-w2"
        and item.get("status") == "passed"
        and item.get("cleanup_verified") is True
    )
    require(
        item.get("original_deadlines_preserved") is True
        and item.get("old_containers_observed_stopped") is True
        and item.get("new_process_lifetimes_observed") is True
    )
    require(item.get("provenance", {}).get("module_hashes") == source_hashes(root, native=False))
    require(
        item.get("outcomes")
        == {
            "accepted": 8,
            "rejected": 24,
            "inquiry_succeeded": 8,
            "explicitly_cancelled_after_measurement": 8,
            "receiver_events": 8,
            "lost_accepted": 0,
            "apply_calls": 0,
            "mutations": 0,
        }
    )
    exits = item.get("stopped_exit_codes", {})
    expected_exits = {"api": 143, "worker-1": 0, "worker-2": 0}
    require(
        type(exits) is dict
        and exits == expected_exits
        and all(type(code) is int for code in exits.values())
    )
    require(item.get("expected_stop_exit_codes") == expected_exits)
    require(
        item.get("api_shutdown_observation")
        == {"application_shutdown_complete_events": 1, "server_process_finished_events": 1}
    )
    drain = item.get("drain_observation", {})
    require(type(drain) is dict and drain.get("ready") is False)
    count(drain.get("active_children"), 1)
    require(
        type(drain.get("observed_to_release_seconds")) in {int, float}
        and 1 <= drain["observed_to_release_seconds"] <= 4.5
    )
    return 1


def wait_child(child: OwnedProcess, deadline: float) -> int:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProcessTimeout("Original acceptance deadline exceeded")
        try:
            return child.wait(timeout=min(300.0, remaining)).returncode
        except ProcessTimeout:
            if time.monotonic() >= deadline:
                raise


def command(root: Path, argv: list[str], deadline: float) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="private-runtime-", dir=root / ".local") as temp:
        with OwnedProcess(
            argv,
            cwd=root,
            env=dict(os.environ),
            output_directory=Path(temp) / "capture",
            max_output_bytes=65536,
        ) as child:
            code = wait_child(child, deadline)
            output = child.output_tail("stdout", maximum_bytes=8192)
        if child.cleanup_failed:
            raise ProcessControlError("Owned acceptance child cleanup incomplete")
    return code, output


def publish(path: Path, value: dict[str, Any]) -> None:
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "w"
    ) as stream:
        json.dump(value, stream, allow_nan=False, separators=(",", ":"))
        stream.write("\n")


PREFLIGHT_ERROR_CATEGORIES = frozenset(
    (
        "AssertionError",
        "ValueError",
        "RuntimeError",
        "TypeError",
        "KeyError",
        "IndexError",
        "AttributeError",
        "OSError",
        "FileNotFoundError",
        "PermissionError",
        "TimeoutError",
        "ConnectionError",
        "ImportError",
        "ModuleNotFoundError",
        "OverflowError",
        "MemoryError",
        "RecursionError",
        "UnicodeError",
        "ZeroDivisionError",
        "other",
    )
)
PREFLIGHT_SOURCES = frozenset({"phase_g_demo", "p1_real_media", "stack", "unavailable"})


def child_failure_projection(output: str) -> dict[str, object] | None:
    """Accept only the helper's finite top-level failure; discard all other output."""
    if type(output) is not str or not 1 <= len(output) <= 8192:
        return None
    try:
        value = parse_json(output.encode("utf-8"), 8192)
        if (
            type(value) is not dict
            or set(value) != {"status", "code", "action", "failure"}
            or value["status"] != "failed"
            or value["code"] != "phase_g_demo_failed"
            or value["action"] != "inspect_retained_safe_evidence"
        ):
            return None
        failure = value["failure"]
        if (
            type(failure) is not dict
            or set(failure) != {"schema_version", "error_category", "source", "line"}
            or type(failure["schema_version"]) is not int
            or failure["schema_version"] != 1
            or type(failure["error_category"]) is not str
            or failure["error_category"] not in PREFLIGHT_ERROR_CATEGORIES
            or type(failure["source"]) is not str
            or failure["source"] not in PREFLIGHT_SOURCES
            or type(failure["line"]) is not int
            or not 0 <= failure["line"] <= 100000
            or ((failure["source"] == "unavailable") != (failure["line"] == 0))
        ):
            return None
        return dict(failure)
    except (EvidenceError, UnicodeError, RecursionError, OverflowError):
        return None


def browser_path(value: str | None) -> str | None:
    if value is None:
        return None
    path = Path(value)
    require(
        path.is_absolute() and not path.is_symlink() and path.is_file() and os.access(path, os.X_OK)
    )
    require(not any(char in value for char in "\x00\r\n") and len(value) <= 4096)
    return str(path)


def reference(root: Path, path: Path) -> dict[str, str]:
    require(path.is_relative_to(root / ".local/validation"))
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 2097152)
        raw = stream.read(2097153)
    parse_json(raw)
    return {"path": str(path.relative_to(root)), "sha256": hashlib.sha256(raw).hexdigest()}


def verify_cleanup(artifact: Path, run_id: str) -> Path:
    require(re.fullmatch(r"[a-f0-9]{32}", run_id) is not None)
    path = artifact / ("cleanup-" + run_id + ".json")
    value = read_json(path)
    require(
        type(value) is dict
        and set(value) == {"schema_version", "run_id", "status", "cleanup_verified", "codes"}
    )
    require(
        type(value["schema_version"]) is int
        and value["schema_version"] == 1
        and value["run_id"] == run_id
        and value["status"] == "passed"
        and value["cleanup_verified"] is True
        and value["codes"] == []
    )
    return path


def run_pg(report: Path, root: Path = ROOT) -> int:
    module = load_tool(root / "local-setup/scripts/p1_acceptance.py")
    module.__dict__["CASES"] = {"P1-14": POST_COMMIT_ASSERTIONS}
    value, code = module.run_case("P1-14", root=root)
    publish(report, value)
    return int(code)


def run_case(
    case_id: str,
    *,
    root: Path = ROOT,
    executable: str | None = None,
    real_profile: str = "local_real",
) -> tuple[dict[str, Any], int]:
    started = time.monotonic()
    deadline = started + DEADLINE_SECONDS
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "caseId": case_id,
        "mode": "live" if case_id == "P1-20" else "lab",
        "status": "failed",
        "testCount": 0,
        "skippedCount": 0,
        "failureCount": 0,
        "errorCount": 0,
        "durationSeconds": 0.0,
        "code": "mapping_invalid",
    }
    if type(real_profile) is not str or real_profile not in {"local_real", "provider_real"}:
        return report, 1
    if case_id not in CASES:
        return report, 1
    directory = (
        root / ".local/validation/p1-runtime-acceptance" / (case_id.lower() + "-" + uuid4().hex)
    )
    directory.parent.mkdir(parents=True, exist_ok=True)
    require(not any(path.is_symlink() for path in (directory, *directory.parents)))
    directory.mkdir(mode=0o700)
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "case_id": case_id,
        "real_profile": real_profile if case_id == "P1-20" else None,
        "status": "failed",
        "cleanup_verified": False,
        "failure_category": "runner_failure",
        "failure_stage": "setup",
        "child_artifact_directory": None,
        "artifacts": [],
    }
    try:
        if case_id == "P1-18":
            evidence["failure_stage"] = "reliability"
            source = root / "local-setup/scripts/p1_reliability.py"
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            evidence["child_driver_sha256"] = digest
            parent = root / ".local/validation/p1-phase-h2"
            existing = {path.name for path in parent.iterdir()} if parent.is_dir() else set()
            code, output = command(
                root, [sys.executable, str(source), "--run", "--case", "slow-shutdown-w2"], deadline
            )
            child = parse_json(output.encode(), 8192)
            require(type(child) is dict and set(child) == {"status", "cases_passed", "report"})
            candidate = Path(child["report"])
            require(
                candidate.parent == parent
                and re.fullmatch(r"[a-f0-9]{32}", candidate.name) is not None
                and candidate.name not in existing
            )
            require(not any(path.is_symlink() for path in (candidate, *candidate.parents)))
            evidence["child_exit_code"] = code
            evidence["child_artifact_directory"] = str(candidate.relative_to(root))
            target = candidate / "summary.json"
            evidence["artifacts"].append(reference(root, target))
            value = read_json(target)
            evidence["cleanup_verified"] = (
                type(value) is dict
                and value.get("cleanup_failures") == []
                and type(value.get("cases")) is list
                and len(value["cases"]) == 1
                and all(
                    type(case) is dict and case.get("cleanup_verified") is True
                    for case in value["cases"]
                )
            )
            require(code == 0 and child["status"] == "passed")
            count(child["cases_passed"], 1)
            report["testCount"] = verify_h2(value, root=root, driver_sha256=digest)
        else:
            evidence["failure_stage"] = "browser"
            artifact = directory / "browser"
            evidence["child_artifact_directory"] = str(artifact.relative_to(root))
            require(not artifact.exists())
            # The helper owns and mints its actual room/schema run ID. The fresh
            # absent artifact directory fences evidence reuse independently.
            source = root / "local-setup/scripts/phase_g_demo.py"
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            evidence["child_driver_sha256"] = digest
            argv = [
                sys.executable,
                str(source),
                "--mode",
                real_profile if case_id == "P1-20" else "scripted",
                "--work-seconds",
                "600",
                "--artifact-root",
                str(artifact),
            ]
            if executable is not None:
                argv.extend(["--browser-executable", executable])
            expected_provider_trust: dict[str, object] | None = None
            if case_id == "P1-20" and real_profile == "provider_real":
                expected_provider_trust = {"source": "image_os"}
                ca_bundle = os.environ.get("P1_PROVIDER_CA_BUNDLE")
                if ca_bundle is not None:
                    require(bool(ca_bundle) and len(ca_bundle) <= 4096 and "\x00" not in ca_bundle)
                    validator = load_tool(root / "local-setup/provider_config.py")
                    ca_bytes = validator.read_ca_bundle(Path(ca_bundle))
                    expected_provider_trust = {
                        "source": "explicit_ca_bundle",
                        "bundle_sha256": hashlib.sha256(ca_bytes).hexdigest(),
                        "bundle_bytes": len(ca_bytes),
                        "native_only_mount_verified": True,
                    }
                    argv.extend(["--provider-ca-bundle", ca_bundle])
                evidence["provider_trust_selection"] = expected_provider_trust
            code, output = command(root, argv, deadline)
            evidence["child_exit_code"] = code
            if code != 0:
                projection = child_failure_projection(output)
                if projection is not None:
                    evidence["child_failure"] = projection
            require(hashlib.sha256(source.read_bytes()).hexdigest() == digest)
            evidence["child_artifact_directory"] = str(artifact.relative_to(root))
            target = artifact / "container-demo.json"
            evidence["artifacts"].append(reference(root, target))
            value = read_json(target)
            require(type(value) is dict)
            run_id = value.get("run_id", "")
            require(type(run_id) is str and re.fullmatch(r"[a-f0-9]{32}", run_id) is not None)
            cleanup_path = verify_cleanup(artifact, run_id)
            evidence["artifacts"].append(reference(root, cleanup_path))
            evidence["cleanup_verified"] = value.get("cleanup_verified") is True
            require(code == 0)
            if expected_provider_trust is not None:
                require(value.get("provider_trust") == expected_provider_trust)
            report["testCount"] = verify_browser(
                value,
                root=root,
                run_id=run_id,
                real=case_id == "P1-20",
                artifact=artifact,
                profile=real_profile,
            )
            if case_id == "P1-14":
                evidence["failure_stage"] = "postgres"
                evidence["cleanup_verified"] = False
                with tempfile.TemporaryDirectory(prefix="private-pg-", dir=root / ".local") as temp:
                    pg_report = Path(temp) / "report.json"
                    pg_code, _ = command(
                        root,
                        [
                            sys.executable,
                            str(Path(__file__).resolve()),
                            "--case",
                            case_id,
                            "--report",
                            str(pg_report),
                            "--pg-only",
                        ],
                        min(deadline, time.monotonic() + 300),
                    )
                    evidence["postgres_child_exit_code"] = pg_code
                    pg = read_report(pg_report, case_id, "lab")
                    require(pg_code == 0 and pg["status"] == "passed")
                    count(pg["testCount"], 3)
                    publish(directory / "postgres.json", pg)
                    report["testCount"] += 3
        require(time.monotonic() <= deadline)
        count(report["testCount"], CASES[case_id])
        report.update(status="passed", code="passed")
        evidence.update(
            status="passed", failure_category=None, failure_stage=None, cleanup_verified=True
        )
        exit_code = 0
    except Exception as error:  # noqa: BLE001 - no exception body or raw child output escapes
        category = (
            "runner_timeout"
            if isinstance(error, ProcessTimeout)
            else "runner_output_limit"
            if isinstance(error, ProcessOutputLimit)
            else "required_assertion_failed"
            if isinstance(error, EvidenceError)
            else "runner_failure"
        )
        evidence["failure_category"] = category
        if case_id != "P1-18" and evidence["failure_stage"] == "browser":
            # Preserve the original assertion/process failure even when cleanup
            # evidence is absent or malformed. A successful cleanup is separate.
            try:
                cleanup_files = list((directory / "browser").glob("cleanup-*.json"))
                if len(cleanup_files) == 1:
                    name = cleanup_files[0].name
                    match = re.fullmatch(r"cleanup-([a-f0-9]{32})\.json", name)
                    if match is not None:
                        path = verify_cleanup(directory / "browser", match[1])
                        evidence["artifacts"].append(reference(root, path))
                        evidence["cleanup_verified"] = True
            except Exception:  # noqa: BLE001 - cleanup observation cannot replace the primary failure
                evidence["cleanup_observation_unavailable"] = True
        report.update(code="test_error", errorCount=1)
        exit_code = 1
    report["durationSeconds"] = round(time.monotonic() - started, 6)
    publish(directory / "evidence.json", evidence)
    return report, exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, choices=tuple(CASES))
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--browser-executable")
    parser.add_argument("--pg-only", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    try:
        if arguments.pg_only:
            require(arguments.case == "P1-14")
            return run_pg(arguments.report)
        executable = browser_path(
            arguments.browser_executable or os.environ.get("P1_ACCEPTANCE_BROWSER_EXECUTABLE")
        )
        value, code = run_case(
            arguments.case,
            executable=executable,
            real_profile=selected_real_profile(dict(os.environ)),
        )
        publish(arguments.report, value)
        print(json.dumps(value, allow_nan=False, separators=(",", ":")))
        return code
    except Exception:  # noqa: BLE001 - closed CLI boundary never formats dependencies
        print('{"status":"failed","code":"runtime_acceptance_failed"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
