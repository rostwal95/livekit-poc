"""Finite, privacy-preserving evidence policy for the opt-in real media lane.

This tooling drives only a fresh UUID-owned stack. It does not manufacture model
responses and never treats health, a stale artifact or model text as acceptance.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import signal
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from types import FrameType, TracebackType
from typing import Any, NoReturn
from uuid import UUID, uuid4, uuid5

MODELS = {"stt": "base.en", "llm": "qwen3:4b-instruct", "tts": "en_US-ljspeech-medium"}
REAL_PROFILES = frozenset({"local_real", "provider_real"})
PROVIDER_MODELS = {"stt": "nova-3", "llm": "gpt-5.4-mini", "tts": "eleven_v4_turbo"}
PROVIDER_NAMES = {"stt": "deepgram", "llm": "openai", "tts": "elevenlabs"}
PROVIDER_RESOURCE_LIMITS = {role: (512 * 1024**2, 1.5, 256) for role in ("native", "api", "worker")}


def models_for(mode: str) -> dict[str, str]:
    if type(mode) is not str or mode not in REAL_PROFILES:
        raise ValueError("A declared real inference profile is required")
    return dict(PROVIDER_MODELS if mode == "provider_real" else MODELS)


PROVIDER_DECLARATION_SHA256 = "ca9f7d448dfdb8c736cbecae5a8fe9341e4c662a5951acfffedc73111a6e8793"
MODEL_MANIFEST_SHA256 = "b57d52bed5e252bfe868aac75265e5318ce5de19f4a65e86b51125170b7b61e9"
RESOURCE_LIMITS = {
    "llm": (4 * 1024**3, 4, 128),
    "stt": (1024**3, 4, 128),
    "tts": (512 * 1024**2, 2, 128),
    "native": (512 * 1024**2, 1.5, 256),
}


class MediaDeadline(TimeoutError):
    """Only a fixed diagnostic crosses a work or owned-cleanup deadline."""


class WorkDeadline:
    """A main-thread work alarm reserves a separate finite cleanup window."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.due = 0.0
        self.cleaning = False
        self.previous: dict[signal.Signals, Any] = {}

    def start(self) -> None:
        if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0) or self.previous:
            raise ValueError("The media runner must own its alarm")
        for number in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT):
            self.previous[number] = signal.getsignal(number)
            signal.signal(number, self._expired if number == signal.SIGALRM else self._terminated)
        self.due = self.clock() + 600
        signal.setitimer(signal.ITIMER_REAL, 600)

    def _expired(self, _number: int, _frame: FrameType | None) -> NoReturn:
        raise MediaDeadline("The declared media operation deadline expired")

    def _terminated(self, _number: int, _frame: FrameType | None) -> None:
        if not self.cleaning:
            raise MediaDeadline("The owned media runner received a shutdown request")

    def timeout(self, requested: float) -> float:
        remaining = self.due - self.clock()
        if remaining <= 0:
            raise MediaDeadline("The declared media operation deadline expired")
        return min(requested, remaining)

    def begin_cleanup(self) -> None:
        signal.setitimer(signal.ITIMER_REAL, 0)
        self.cleaning = True
        self.due = self.clock() + 180
        signal.setitimer(signal.ITIMER_REAL, 180)

    def finish(self) -> None:
        signal.setitimer(signal.ITIMER_REAL, 0)
        for number, previous in self.previous.items():
            signal.signal(number, previous)
        self.previous.clear()


SESSION_MINT_ERROR_CODES = frozenset(
    (
        "business_unavailable",
        "response_too_large",
        "execution_not_found",
        "unsupported_operation",
        "stale_revision",
        "transition_conflict",
        "quote_expired",
        "invalid_confirmation",
        "case_cancelled",
        "intent_committed",
        "invalid_stored_state",
        "schema_version_unsupported",
        "session_in_use",
        "source_quiesced",
        "authentication_required",
        "forbidden",
        "route_not_found",
        "method_not_allowed",
        "request_timeout",
        "idempotency_conflict",
        "request_too_large",
        "validation_error",
        "rate_limited",
        "capacity_exhausted",
        "dependency_unavailable",
        "dispatch_unavailable",
        "storage_limit_reached",
        "storage_unavailable",
        "service_unavailable",
        "http_error",
        "internal_error",
    )
)


REAL_FLAGS = frozenset(
    {
        "isolated_local_stack",
        "real_http",
        "native_room",
        "native_agent",
        "verified_real_profile",
        "explicit_fixture_publication",
        "fixture_input_committed",
        "generated_audio_played",
        "fresh_response_played",
        "active_speech_interrupted",
        "case_survived_voice_end",
        "same_task_fresh_consumer",
        "fresh_media_identities",
        "cohort_pending_before_end",
        "cohort_pending_after_end",
        "cohort_completed_after_end",
        "slow_pg_wait_observed",
        "slow_pg_interrupt_while_held",
        "slow_pg_mute_while_held",
        "slow_supplier_quote_pending",
        "slow_supplier_interrupt_while_held",
        "slow_supplier_mute_while_held",
        "no_mutation_before_human",
        "exact_quote_confirmed",
        "passwords_empty_before_screenshots",
    }
)
REAL_NUMBERS = frozenset(
    {
        "audio_current_time",
        "active_interrupt_seconds",
        "pg_interrupt_seconds",
        "supplier_interrupt_seconds",
    }
)
REAL_COUNTS = frozenset(
    {
        "unexpected_network_requests",
        "native_sessions",
        "background_accepted",
        "background_pending_at_end",
        "background_completed_after_end",
    }
)
REAL_FIELDS = (
    REAL_FLAGS
    | REAL_NUMBERS
    | REAL_COUNTS
    | {
        "schema_version",
        "mode",
        "run_id",
        "foreground_task_id",
        "browser_version",
        "playwright_version",
        "last_phase",
        "supplier_outcome",
        "delivery_state",
        "session_mint_http_status",
        "session_mint_error_code",
        "session_mint_joins",
    }
)
PHASES = frozenset(
    {
        "prepare",
        "submit",
        "join",
        "input",
        "cohort",
        "end",
        "reconnect",
        "slow_postgres",
        "held_supplier",
        "confirm",
    }
)
ENGINE_FIELDS = {
    "schema_version",
    "engine",
    "requests",
    "succeeded",
    "failed",
    "active",
    "max_active",
    "processed_input_bytes",
    "processed_output_bytes",
    "duration_seconds",
}


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def uuid_value(value: object) -> str:
    if type(value) is not str or str(UUID(value)) != value:
        raise ValueError("Evidence identity must be a canonical UUID")
    return value


def artifact_root(root: Path, value: Path) -> Path:
    """An explicit report destination is a fresh child of local validation."""
    base = root / ".local/validation"
    if not value.is_absolute() or ".." in value.parts:
        raise ValueError("A fresh repository-local artifact path is required")
    try:
        relative = value.relative_to(base)
    except ValueError:
        raise ValueError("Artifacts must remain under local validation") from None
    if not relative.parts or value.exists() or value.is_symlink():
        raise ValueError("The explicit artifact directory must not already exist")
    for path in (value, *value.parents):
        if path == root:
            break
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError("Artifact paths must not cross symlinks or files")
    return value


def declaration(root: Path, *, mode: str = "local_real") -> tuple[dict[str, Any], str]:
    models_for(mode)
    path = root / (
        "local-setup/workloads/p1-provider-real-v2.json"
        if mode == "provider_real"
        else "local-setup/workloads/p1-local-real-v1.json"
    )
    if path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size <= 16384:
        raise ValueError("The frozen media declaration is required")
    with path.open("rb") as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError("The media declaration exceeds its byte bound")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, entry in pairs:
            if key in result:
                raise ValueError("Declaration fields must be unique")
            result[key] = entry
        return result

    value = json.loads(raw, object_pairs_hook=unique)
    if mode == "provider_real":
        if hashlib.sha256(canonical(value)).hexdigest() != PROVIDER_DECLARATION_SHA256:
            raise ValueError("The frozen provider media workload changed")
        return value, hashlib.sha256(raw).hexdigest()
    if (
        type(value) is not dict
        or type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
        or value.get("declaration_id") != "p1-local-real-v1"
        or value.get("profile") != "local_real"
        or value.get("models") != MODELS
        or value.get("resource_limits")
        != {
            role: {"memory_bytes": limits[0], "cpus": limits[1], "pids": limits[2]}
            for role, limits in RESOURCE_LIMITS.items()
        }
        or value.get("fixture")
        != {
            "file": "input-investigate.wav",
            "sha256": "11f5143ef2a1f0bdae93dfa136b5d5bed880c6dca4952ac28fb61340f3efe12f",
            "frames": 63865,
            "sample_rate_hz": 16000,
            "channels": 1,
            "sample_width_bytes": 2,
            "capture_seconds": 4.25,
        }
        or any(
            type(value.get(key)) is not int
            for key in (
                "native_concurrency",
                "background_inquiries",
                "foreground_inquiries",
                "browser_cases",
                "browser_run_seconds",
            )
        )
        or value.get("native_concurrency") != 1
        or value.get("background_inquiries") != 8
        or value.get("foreground_inquiries") != 1
        or value.get("browser_cases") != 2
        or value.get("browser_run_seconds") != 300
        or value.get("native_budgets_seconds")
        != {
            "stt": 10,
            "llm": 30,
            "tts": 10,
            "commit_rpc": 11,
            "browser_commit": 12,
            "interruption": 1.5,
        }
        or value.get("final_counts")
        != {
            "tasks": 9,
            "inquiries": 9,
            "intents": 1,
            "consumptions": 1,
            "apply_calls": 1,
            "mutations": 1,
            "receiver_events": 9,
        }
    ):
        raise ValueError("The versioned real media workload changed")
    return value, hashlib.sha256(raw).hexdigest()


def model_manifest(root: Path) -> str:
    path = root / "local-setup/models/local-model-manifest.json"
    if path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size <= 16384:
        raise ValueError("The frozen local model manifest is required")
    with path.open("rb") as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError("The model manifest exceeds its byte bound")
    # The preparation contract pins canonical JSON, independently of whitespace.
    # Reuse its strict duplicate/type/path/schema verification rather than compare
    # that canonical digest with the formatted file's different raw-byte digest.
    from local_models import MANIFEST_DIGEST, files_from_manifest

    if MANIFEST_DIGEST != MODEL_MANIFEST_SHA256 or len(files_from_manifest(path)) != 10:
        raise ValueError("The declared model manifest changed")
    return MODEL_MANIFEST_SHA256


def platform_manifest(running: object, selected: object) -> str:
    """Compare exact platform manifests, separately from index/config identities."""
    for value in (running, selected):
        if (
            type(value) is not dict
            or set(value) != {"mediaType", "digest", "size", "platform"}
            or value["mediaType"]
            not in {
                "application/vnd.oci.image.manifest.v1+json",
                "application/vnd.docker.distribution.manifest.v2+json",
            }
            or type(value["digest"]) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", value["digest"]) is None
            or type(value["size"]) is not int
            or not 1 <= value["size"] <= 65536
            or value["platform"] != {"architecture": "arm64", "os": "linux"}
        ):
            raise ValueError("An exact supported platform manifest is required")
    if running != selected:
        raise ValueError("The running engine differs from the selected platform manifest")
    assert isinstance(running, dict)
    return str(running["digest"])


def gate_inventory(root: Path, *, mode: str = "local_real") -> dict[str, str]:
    models_for(mode)
    paths: tuple[str, ...] = (
        "local-setup/scripts/phase_g_demo.py",
        "local-setup/scripts/p1_real_media.py",
        "local-setup/scripts/p1_demo_ownership.py",
        "local-setup/scripts/local_models.py",
        "local-setup/workloads/p1-local-real-v1.json",
        "local-setup/models/local-model-manifest.json",
        "local-setup/inference/engine.py",
        "local-setup/inference/engine_child.py",
        "local-setup/inference/piper/pyproject.toml",
        "local-setup/inference/piper/uv.lock",
        "local-setup/docker/whisper.Dockerfile",
        "local-setup/docker/piper.Dockerfile",
        "apps/local-console/e2e/local-real.media.ts",
        "apps/local-console/playwright.real.config.ts",
        "apps/local-console/playwright.config.ts",
        "apps/local-console/tsconfig.e2e.json",
    )
    if mode == "provider_real":
        paths = tuple(
            path
            for path in paths
            if path
            in {
                "local-setup/scripts/phase_g_demo.py",
                "local-setup/scripts/p1_real_media.py",
                "local-setup/scripts/p1_demo_ownership.py",
                "apps/local-console/e2e/local-real.media.ts",
                "apps/local-console/playwright.real.config.ts",
                "apps/local-console/playwright.config.ts",
                "apps/local-console/tsconfig.e2e.json",
            }
        ) + ("local-setup/provider_config.py", "local-setup/workloads/p1-provider-real-v2.json")
    result = {}
    for relative in paths:
        path = root / relative
        if path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size <= 262144:
            raise ValueError("The actual media gate source must be bounded regular files")
        with path.open("rb") as stream:
            raw = stream.read(262145)
        if len(raw) > 262144:
            raise ValueError("The actual media gate source exceeds its byte bound")
        result[relative] = hashlib.sha256(raw).hexdigest()
    return result


def resource_window(
    before: object, after: object, *, role: str, mode: str = "local_real"
) -> dict[str, object]:
    models_for(mode)
    limits = PROVIDER_RESOURCE_LIMITS if mode == "provider_real" else RESOURCE_LIMITS
    fields = {
        "cpu_usage_usec",
        "cpu_quota_usec",
        "cpu_period_usec",
        "memory_current_bytes",
        "memory_peak_bytes",
        "memory_limit_bytes",
        "pids_current",
        "pids_limit",
        "oom_kills",
    }
    if role not in limits:
        raise ValueError("Unknown real model resource role")
    memory, cpus, pids = limits[role]
    for value in (before, after):
        if (
            type(value) is not dict
            or set(value) != fields
            or any(
                type(number) is not int or not 0 <= number <= 9223372036854775807
                for number in value.values()
            )
        ):
            raise ValueError("Resource accounting must be finite bounded integer observations")
        if (
            value["cpu_period_usec"] < 1
            or value["cpu_quota_usec"] != cpus * value["cpu_period_usec"]
            or value["memory_limit_bytes"] != memory
            or value["pids_limit"] != pids
            or not 1 <= value["memory_current_bytes"] <= value["memory_peak_bytes"] <= memory
            or not 1 <= value["pids_current"] <= pids
        ):
            raise ValueError("Actual resource limits do not match the frozen declaration")
    assert isinstance(before, dict) and isinstance(after, dict)
    cpu_delta = after["cpu_usage_usec"] - before["cpu_usage_usec"]
    if (
        cpu_delta <= 0
        or after["oom_kills"] != before["oom_kills"]
        or after["memory_peak_bytes"] < before["memory_peak_bytes"]
    ):
        raise ValueError("The real model window requires positive CPU and no OOM/reset")
    return {
        "samples": 2,
        "cpu_usage_delta_usec": cpu_delta,
        "before": before,
        "after": after,
        "memory_kind": "cgroup_accounted",
        "peak_scope": "container_lifetime_upper_bound_includes_measurement",
        "cpu_scope": "declared_browser_window",
    }


MINT_BINDING_FLAGS = frozenset(
    {"same_room", "same_identity", "same_task", "same_invocation", "same_body"}
)


def safe_mint_joins(
    value: object, *, native_sessions: object, passing: bool
) -> list[dict[str, Any]]:
    """Validate bounded retry observations; identities and response bodies are absent."""
    if (
        type(value) is not list
        or len(value) > 4
        or type(native_sessions) is not int
        or not 0 <= native_sessions <= 4
    ):
        raise ValueError("Logical session mint observations exceed their bound")
    safe: list[dict[str, Any]] = []
    completed = 0
    for joined in value:
        if (
            type(joined) is not dict
            or set(joined) != {"attempts", "overflowed", "completed"}
            or type(joined["overflowed"]) is not bool
            or type(joined["completed"]) is not bool
            or type(joined["attempts"]) is not list
            or len(joined["attempts"]) > 3
        ):
            raise ValueError("A logical mint join has unsupported observations")
        useful = passing or joined["completed"]
        if useful and (joined["overflowed"] or not joined["attempts"]):
            raise ValueError("A completed logical join requires at most three mint attempts")
        attempts = []
        for index, attempt in enumerate(joined["attempts"]):
            if (
                type(attempt) is not dict
                or set(attempt) != MINT_BINDING_FLAGS | {"http_status", "error_code"}
                or any(type(attempt[flag]) is not bool for flag in MINT_BINDING_FLAGS)
                or type(attempt["http_status"]) is not int
                or (attempt["http_status"] != 0 and not 100 <= attempt["http_status"] <= 599)
                or type(attempt["error_code"]) is not str
                or attempt["error_code"]
                not in SESSION_MINT_ERROR_CODES
                | {"none", "not_observed", "unclassified", "transport_error"}
                or (
                    attempt["http_status"] == 0
                    and attempt["error_code"] not in {"not_observed", "transport_error"}
                )
                or (attempt["http_status"] == 200 and attempt["error_code"] != "none")
                or (
                    attempt["http_status"] not in {0, 200}
                    and attempt["error_code"] in {"none", "not_observed", "transport_error"}
                )
            ):
                raise ValueError("Mint attempt fields must be finite and content free")
            if useful:
                if not all(attempt[flag] for flag in MINT_BINDING_FLAGS):
                    raise ValueError(
                        "Every mint attempt must preserve its original binding and body"
                    )
                if index == len(joined["attempts"]) - 1:
                    if attempt["http_status"] != 200 or attempt["error_code"] != "none":
                        raise ValueError("A logical join needs one final successful mint")
                elif attempt["http_status"] not in {503, 504} and not (
                    attempt["http_status"] == 0 and attempt["error_code"] == "transport_error"
                ):
                    raise ValueError(
                        "A successful join cannot hide a nonretryable earlier response"
                    )
            attempts.append(dict(attempt))
        if joined["completed"]:
            completed += 1
        if passing and not joined["completed"]:
            raise ValueError("Every passing logical join requires actual native readiness")
        safe.append(
            {
                "attempts": attempts,
                "overflowed": joined["overflowed"],
                "completed": joined["completed"],
            }
        )
    if completed != native_sessions or (passing and len(safe) != native_sessions):
        raise ValueError(
            "Mint joins must count successful logical native sessions rather than retries"
        )
    return safe


def safe_browser(
    value: object, *, run_id: str, passing: bool, mode: str = "local_real"
) -> dict[str, Any]:
    models_for(mode)
    if (
        type(value) is not dict
        or set(value) != REAL_FIELDS
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or any(
            type(value[key]) is not str
            for key in (
                "mode",
                "run_id",
                "foreground_task_id",
                "last_phase",
                "supplier_outcome",
                "delivery_state",
                "browser_version",
                "playwright_version",
            )
        )
        or value["mode"] != mode
        or value["run_id"] != run_id
        or re.fullmatch("[0-9a-f]{32}", run_id) is None
        or value["last_phase"] not in PHASES
        or value["supplier_outcome"] not in {"not_observed", "succeeded"}
        or value["delivery_state"]
        not in {"not_observed", "pending", "delivering", "delivered", "exhausted"}
        or type(value["browser_version"]) is not str
        or (
            value["browser_version"] != ""
            and re.fullmatch(r"\d{1,4}(?:\.\d{1,5}){3}", value["browser_version"]) is None
        )
        or value["playwright_version"] != "1.65.0"
    ):
        raise ValueError("Real browser evidence has an unsupported schema or invocation")
    safe_mint_joins(
        value["session_mint_joins"], native_sessions=value["native_sessions"], passing=passing
    )
    mint_status = value["session_mint_http_status"]
    mint_code = value["session_mint_error_code"]
    if (
        type(mint_status) is not int
        or (mint_status != 0 and not 100 <= mint_status <= 599)
        or type(mint_code) is not str
        or mint_code not in SESSION_MINT_ERROR_CODES | {"not_observed", "none", "unclassified"}
        or (mint_status == 0 and mint_code != "not_observed")
        or (mint_status == 200 and mint_code != "none")
        or (mint_status not in {0, 200} and mint_code in {"not_observed", "none"})
        or (passing and (mint_status != 200 or mint_code != "none"))
    ):
        raise ValueError("Session mint diagnostics require a fixed HTTP status and category")
    if value["foreground_task_id"] != "":
        uuid_value(value["foreground_task_id"])
    for key in REAL_FLAGS:
        if type(value[key]) is not bool or (passing and not value[key]):
            raise ValueError("A real browser requirement is missing")
    for key in REAL_NUMBERS | REAL_COUNTS:
        number = value[key]
        if (
            type(number) not in {int, float}
            or not math.isfinite(number)
            or not 0 <= number <= 1_000_000
        ):
            raise ValueError("Real browser counters must be finite and bounded")
        if key in REAL_COUNTS and type(number) is not int:
            raise ValueError("Real browser counts must be integers")
    if passing and (
        not value["foreground_task_id"]
        or not value["browser_version"]
        or value["unexpected_network_requests"] != 0
        or value["native_sessions"] != 4
        or value["background_accepted"] != 8
        or value["background_pending_at_end"] != 8
        or value["background_completed_after_end"] != 8
        or value["audio_current_time"] <= 0.05
        or any(not 0 < value[key] <= 1.5 for key in REAL_NUMBERS - {"audio_current_time"})
        or value["supplier_outcome"] != "succeeded"
    ):
        raise ValueError("Real media observations do not meet the frozen workload")
    return dict(value)


def verify_browser(
    value: object, report: object, *, run_id: str, mode: str = "local_real"
) -> dict[str, object]:
    observed = safe_browser(value, run_id=run_id, passing=True, mode=mode)
    if type(report) is not dict or type(report.get("stats")) is not dict:
        raise ValueError("The actual real browser runner report is required")
    stats = report["stats"]
    expected = {"expected": 2, "unexpected": 0, "skipped": 0, "flaky": 0}
    if any(
        type(stats.get(key)) is not int or stats[key] != number for key, number in expected.items()
    ):
        raise ValueError("Exactly two real media cases must pass without skips or retries")
    return {
        "required_cases": 2,
        "passed_cases": 2,
        "runner_stats": expected,
        "observations": observed,
    }


def safe_playwright_failure(
    report: object, *, source_root: Path, source_lines: int
) -> dict[str, object]:
    """Keep fixed case/status and numeric locations; never inspect message/stack."""
    if type(report) is not dict or type(source_lines) is not int or not 1 <= source_lines <= 10000:
        raise ValueError("The bounded real browser report and source size are required")
    case_ids = {
        "runs actual fixture inference, ends with eight accepted inquiries, and resumes the same case": 1,
        "keeps real media control responsive during actual waits and requires exact human quote approval": 2,
    }
    source_files = {
        str(source_root / "apps/local-console/e2e/local-real.media.ts"),
        "apps/local-console/e2e/local-real.media.ts",
        "e2e/local-real.media.ts",
        "local-real.media.ts",
    }
    statuses = {
        "failed": "browser_case_failed",
        "timedOut": "browser_case_timed_out",
        "interrupted": "browser_case_interrupted",
    }
    pending = [(report, 0)]
    visited = 0
    failures: list[dict[str, object]] = []
    while pending:
        node, depth = pending.pop()
        visited += 1
        if visited > 128 or depth > 8 or type(node) is not dict:
            raise ValueError("The real browser report exceeds its structural bound")
        suites = node.get("suites", [])
        specs = node.get("specs", [])
        if type(suites) is not list or len(suites) > 8 or type(specs) is not list or len(specs) > 2:
            raise ValueError("The real browser report exceeds its case bound")
        pending.extend((suite, depth + 1) for suite in suites)
        for spec in specs:
            if (
                type(spec) is not dict
                or type(spec.get("title")) is not str
                or spec["title"] not in case_ids
            ):
                continue
            tests = spec.get("tests", [])
            if type(tests) is not list or len(tests) > 1:
                raise ValueError("The real browser report contains undeclared projects")
            for test in tests:
                if type(test) is not dict:
                    continue
                results = test.get("results", [])
                if type(results) is not list or len(results) > 1:
                    raise ValueError("Real browser retries cannot qualify evidence")
                for result in results:
                    if (
                        type(result) is not dict
                        or type(result.get("status")) is not str
                        or result["status"] not in statuses
                    ):
                        continue
                    entry: dict[str, object] = {
                        "case": case_ids[spec["title"]],
                        "code": statuses[result["status"]],
                        "source_location_observed": False,
                        "source_line": 0,
                        "source_column": 0,
                    }
                    errors = result.get("errors", [])
                    if type(errors) is not list or len(errors) > 8:
                        errors = []
                    candidates = [result.get("error"), *errors]
                    for error in candidates:
                        if type(error) is not dict or type(error.get("location")) is not dict:
                            continue
                        location = error["location"]
                        filename, line, column = (
                            location.get("file"),
                            location.get("line"),
                            location.get("column"),
                        )
                        if (
                            type(filename) is str
                            and filename in source_files
                            and type(line) is int
                            and 1 <= line <= source_lines
                            and type(column) is int
                            and 0 <= column <= 10000
                        ):
                            entry.update(
                                source_location_observed=True,
                                source_line=line,
                                source_column=column,
                            )
                            break
                    failures.append(entry)
                    if len(failures) > 2:
                        raise ValueError("The real browser failure count exceeds its declaration")
    return {
        "schema_version": 1,
        "status": "observed" if failures else "unavailable",
        "code": "fixed_case_failure_observed" if failures else "no_validated_case_failure",
        "failures": failures,
    }


def engine_metrics(value: object, *, engine: str) -> dict[str, int | float | str]:
    if (
        type(value) is not dict
        or set(value) != ENGINE_FIELDS
        or value["engine"] != engine
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
    ):
        raise ValueError("Engine metrics schema is unsupported")
    for key in ENGINE_FIELDS - {"engine", "schema_version"}:
        number = value[key]
        if (
            type(number) not in ({int, float} if key == "duration_seconds" else {int})
            or not math.isfinite(number)
            or not 0 <= number <= 9223372036854775807
        ):
            raise ValueError("Engine metrics must be finite nonnegative numbers")
    if (
        value["requests"] != value["succeeded"] + value["failed"] + value["active"]
        or value["active"] > 1
        or value["max_active"] > 1
        or value["active"] > value["max_active"]
    ):
        raise ValueError("Engine occupancy or accounting is inconsistent")
    return dict(value)


def engine_delta(before: object, after: object, *, engine: str) -> dict[str, int | float]:
    first, last = (
        engine_metrics(before, engine=engine),
        engine_metrics(after, engine=engine),
    )
    keys = ENGINE_FIELDS - {"schema_version", "engine", "active", "max_active"}
    values: dict[str, int | float] = {}
    for key in keys:
        a, b = first[key], last[key]
        assert isinstance(a, (int, float)) and isinstance(b, (int, float))
        values[key] = b - a
    if (
        any(number < 0 for number in values.values())
        or last["active"] != 0
        or first["active"] != 0
        or last["max_active"] != 1
        or values["failed"] != 0
        or values["requests"] != values["succeeded"]
        or any(
            values[key] <= 0
            for key in (
                "requests",
                "succeeded",
                "processed_input_bytes",
                "processed_output_bytes",
                "duration_seconds",
            )
        )
    ):
        raise ValueError("Actual successful generated inference was not observed")
    return values


RECEIPT_SCRIPT = """import json,hashlib,sqlite3
from contextlib import closing
with closing(sqlite3.connect('file:/data/supplier.sqlite3?mode=ro',uri=True,timeout=1)) as c:
 c.execute('PRAGMA query_only=ON')
 rows=c.execute('SELECT effect_id,request_json,result_json FROM inquiry_receipts WHERE scope_id=? LIMIT 10',('demo-traveller',)).fetchall()
print(json.dumps([{'effect_id':r[0],'request_sha256':hashlib.sha256(r[1].encode()).hexdigest(),'result_sha256':hashlib.sha256(r[2].encode()).hexdigest()} for r in rows]))
"""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise ValueError("The owned local API must not redirect")


class _CohortStopped(Exception):
    """Intentional orchestrator stop; never qualifies incomplete cohort work."""


COHORT_PROJECTION_STATES = {
    "inquiry": frozenset({"accepted", "running", "succeeded", "failed"}),
    "lifecycle": frozenset(
        {
            "ready",
            "running",
            "retry_wait",
            "inquiry_complete",
            "waiting",
            "intent_committed",
            "completed",
            "cancelled",
            "failed",
            "uncertain",
        }
    ),
    "outcome": frozenset({"succeeded", "cancelled", "rejected", "uncertain"}),
    "delivery": frozenset({"pending", "delivering", "delivered", "exhausted"}),
}


COHORT_QUIESCENT_SCRIPT = (
    "from continuity_lab.worker_cli import WorkerSettings,WorkerHealth;"
    "s=WorkerSettings.from_env();"
    "print('true' if WorkerHealth(s.state_file).is_quiescent(maximum_age_seconds=10) else 'false')"
)
COHORT_READY_SCRIPT = (
    "from continuity_lab.worker_cli import WorkerSettings,WorkerHealth;"
    "s=WorkerSettings.from_env();"
    "print('true' if WorkerHealth(s.state_file).ready(maximum_age_seconds=10) else 'false')"
)
MAX_COHORT_HEALTH_OBSERVATIONS = 2001


class PendingCohort:
    """Withhold exactly one owned worker; accepted work must survive voice End."""

    def __init__(
        self,
        *,
        worker: str,
        label: str,
        directory: Path,
        token: str,
        control: Callable[..., str],
        runtime: Any,
    ) -> None:
        self.worker, self.label, self.directory = worker, label, directory
        self.token, self.control, self.runtime = token, control, runtime
        self.stop = threading.Event()
        self.error: BaseException | None = None
        self.cleanup_error: BaseException | None = None
        self.result: dict[str, object] | None = None
        self.accepted: list[dict[str, Any]] = []
        self.foreground: dict[str, Any] | None = None
        self.paused = False
        self.quiesce_requested = False
        self._cleanup_deadline: float | None = None
        self._resume_deadline: float | None = None
        self._quiescence_phase = "not_started"
        self._quiescence_counts = {
            "quiescence_checks": 0,
            "resume_checks": 0,
            "idle_snapshots": 0,
            "quiesce_signal_requests": 0,
            "resume_signal_requests": 0,
        }
        self._quiescence_observed = False
        self._recovery_phase = "not_started"
        self._recovery_started: float | None = None
        self._recovery_counts = {
            "inquiries_succeeded": 0,
            "cancellations_issued": 0,
            "deliveries_observed": 0,
        }
        self._recovery_marks: dict[str, float | None] = {
            "inquiry_completion_seconds": None,
            "receipt_reconciliation_seconds": None,
            "cancellation_issuance_seconds": None,
            "delivery_completion_seconds": None,
        }
        self._projection_states: dict[str, dict[str, str]] = {}
        self.thread = threading.Thread(target=self._run, name="p1-real-pending-cohort", daemon=True)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def _wait(self, marker: str, seconds: float, *, deadline: float | None = None) -> None:
        due = time.monotonic() + seconds if deadline is None else deadline
        while not (self.directory / marker).exists():
            if self.stop.wait(0.02):
                raise _CohortStopped()
            if time.monotonic() >= due:
                raise RuntimeError("The declared cohort milestone was not observed")

    @staticmethod
    def _remaining(deadline: float | None) -> float:
        if deadline is None:
            return 3
        remaining = deadline - time.monotonic()
        if not math.isfinite(remaining) or remaining <= 0:
            raise RuntimeError("The owned worker control deadline was exhausted")
        return min(3, remaining)

    def _setup_active(self, deadline: float) -> None:
        if self.stop.is_set():
            raise _CohortStopped()
        self._remaining(deadline)

    def _owned(self, *, deadline: float | None = None) -> None:
        if not self.control(
            [
                "docker",
                "ps",
                "-aq",
                "--filter",
                "name=^/" + self.worker + "$",
                "--filter",
                "label=" + self.label,
            ],
            timeout=self._remaining(deadline),
        ):
            raise ValueError("The cohort requires its exact owned worker")
        self._remaining(deadline)

    def _worker_health(self, *, quiescent: bool, deadline: float) -> bool:
        field = "quiescence_checks" if quiescent else "resume_checks"
        if self._quiescence_counts[field] >= MAX_COHORT_HEALTH_OBSERVATIONS:
            raise RuntimeError("The owned worker health observation count was exhausted")
        self._quiescence_counts[field] += 1
        result = self.control(
            [
                "docker",
                "exec",
                self.worker,
                "python",
                "-c",
                COHORT_QUIESCENT_SCRIPT if quiescent else COHORT_READY_SCRIPT,
            ],
            timeout=self._remaining(deadline),
        )
        self._remaining(deadline)
        if result not in {"true", "false"}:
            raise ValueError("The owned worker health response was not a fixed boolean")
        return result == "true"

    def _quiescence_observation(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "phase": self._quiescence_phase,
            "quiescence_observed": self._quiescence_observed,
            "request_unresolved": self.quiesce_requested,
            **self._quiescence_counts,
        }

    def _request(self, path: str, body: object | None = None) -> tuple[int, dict[str, Any]]:
        if self.stop.is_set():
            raise _CohortStopped()
        request = urllib.request.Request(
            "http://127.0.0.1:18081" + path,
            data=None if body is None else canonical(body),
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
            },
            method="GET" if body is None else "POST",
        )
        with self.opener.open(request, timeout=3) as response:
            raw = response.read(1_048_577)
            if len(raw) > 1_048_576:
                raise ValueError("The cohort response exceeded its byte bound")
            value = json.loads(raw)
            if type(value) is not dict:
                raise ValueError("The cohort requires an actual bounded JSON response")
            return response.status, value

    def _projection(self, item: dict[str, Any]) -> dict[str, Any]:
        status, value = self._request("/api/business/cases/" + item["task_id"] + "?limit=1")
        original = value.get("inquiry")
        if (
            status != 200
            or value.get("task_id") != item["task_id"]
            or value.get("case_id") != item["case_id"]
            or value.get("request_key") != item["key"]
            or value.get("request") != item["request"]
            or type(original) is not dict
            or original.get("request") != item["request"]
            or original.get("effect_id") != item["effect_id"]
        ):
            raise ValueError("The cohort changed its accepted identity or request")
        self._record_projection(item["task_id"], value)
        return value

    def _record_projection(self, task_id: str, value: object) -> None:
        # Last observations only: no extra requests, task IDs or payloads are exported.
        if type(value) is not dict or value.get("task_id") != task_id:
            return
        if task_id not in self._projection_states and len(self._projection_states) >= 9:
            return
        states: dict[str, str] = {}
        for role, allowed in COHORT_PROJECTION_STATES.items():
            part = value.get(role)
            state = part.get("state") if type(part) is dict else None
            states[role] = (
                state
                if type(state) is str and state in allowed
                else "none"
                if part is None
                else "unknown"
            )
        self._projection_states[task_id] = states

    def _recovery_elapsed(self) -> float | None:
        if self._recovery_started is None:
            return None
        elapsed = time.monotonic() - self._recovery_started
        return round(elapsed, 6) if math.isfinite(elapsed) and 0 <= elapsed <= 600 else None

    def _recovery_observation(self) -> dict[str, object]:
        snapshots = self._projection_states.copy()
        counts = {
            role: dict.fromkeys(sorted(allowed | {"none", "unknown"}), 0)
            for role, allowed in COHORT_PROJECTION_STATES.items()
        }
        for states in snapshots.values():
            for role, state in states.items():
                counts[role][state] += 1
        return {
            "schema_version": 1,
            "phase": self._recovery_phase,
            "deadline_seconds": 45,
            "elapsed_seconds": self._recovery_elapsed(),
            **self._recovery_counts,
            **self._recovery_marks,
            "last_projection_tasks": len(snapshots),
            "last_projection_states": counts,
        }

    def _run(self) -> None:
        from continuity_lab.postgres_store import PostgresExecutionStore
        from continuity_lab.postgres_work import PostgresWorkQueue

        try:
            setup_due = time.monotonic() + 100
            self._wait("real-cohort-arm", 100, deadline=setup_due)
            path = self.directory / "real-foreground-task"
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 64:
                raise ValueError("A bounded foreground task identity is required")
            foreground_id = uuid_value(path.read_text().strip())
            status, self.foreground = self._request(
                "/api/business/cases/" + foreground_id + "?limit=1"
            )
            if (
                status != 200
                or self.foreground.get("task_id") != foreground_id
                or self.foreground.get("inquiry", {}).get("state") != "succeeded"
                or self.foreground.get("outcome") is not None
            ):
                raise ValueError("The foreground inquiry must finish without an effect")
            self._record_projection(foreground_id, self.foreground)
            # The outer worker checkpoint follows child reap, lease release and
            # post-step SQL. An active=0 queue sample alone cannot prove that.
            self._setup_active(setup_due)
            self._owned(deadline=setup_due)
            self._setup_active(setup_due)
            running = self.control(
                ["docker", "inspect", "--format", "{{.State.Running}}", self.worker],
                timeout=self._remaining(setup_due),
            )
            self._setup_active(setup_due)
            if running != "true":
                raise ValueError("The exact owned worker must be running before quiescence")
            self.quiesce_requested = True  # cleanup owns a possibly lost signal acknowledgement
            self._quiescence_phase = "requested"
            self._quiescence_counts["quiesce_signal_requests"] += 1
            self.control(
                ["docker", "kill", "--signal", "SIGUSR1", self.worker],
                timeout=self._remaining(setup_due),
            )
            self._setup_active(setup_due)
            self._quiescence_phase = "waiting"
            while True:
                self._setup_active(setup_due)
                quiescent = self._worker_health(quiescent=True, deadline=setup_due)
                self._setup_active(setup_due)
                if quiescent:
                    self._quiescence_observed = True
                    self._quiescence_phase = "quiescent"
                    break
                if self.stop.wait(min(0.05, self._remaining(setup_due))):
                    raise _CohortStopped()
            queue = PostgresWorkQueue(PostgresExecutionStore(self.runtime))
            while True:
                self._setup_active(setup_due)
                snapshot = queue.snapshot(scope_id="demo-traveller")
                self._setup_active(setup_due)
                self._quiescence_counts["idle_snapshots"] = min(
                    self._quiescence_counts["idle_snapshots"] + 1,
                    MAX_COHORT_HEALTH_OBSERVATIONS,
                )
                if type(snapshot.active) is not int or snapshot.active < 0:
                    raise ValueError("The owned worker queue activity must be a bounded count")
                if snapshot.active == 0:
                    break
                if self.stop.wait(min(0.05, self._remaining(setup_due))):
                    raise _CohortStopped()
            self._owned(deadline=setup_due)
            self._setup_active(setup_due)
            self.paused = True  # cleanup owns a possibly lost pause acknowledgement
            self.control(["docker", "pause", self.worker], timeout=self._remaining(setup_due))
            self._setup_active(setup_due)
            if (
                self.control(
                    ["docker", "inspect", "--format", "{{.State.Paused}}", self.worker],
                    timeout=self._remaining(setup_due),
                )
                != "true"
            ):
                raise ValueError("The owned worker pause was not observed")
            self._setup_active(setup_due)
            self._quiescence_phase = "paused"
            request = {
                "booking_reference": "DEMO-BK-001",
                "new_check_in": "2030-12-10",
                "confirmed": True,
            }
            for _index in range(8):
                key = str(uuid4())
                body = {**request, "idempotency_key": key}
                status, receipt = self._request("/api/business/investigations", body)
                if status != 200 or receipt.get("created") is not True:
                    raise ValueError("Exactly eight new investigations must be accepted")
                task_id = uuid_value(receipt.get("task_id"))
                status, current = self._request("/api/business/cases/" + task_id + "?limit=1")
                item: dict[str, Any] = {
                    "task_id": task_id,
                    "case_id": uuid_value(current.get("case_id")),
                    "effect_id": uuid_value(current.get("inquiry", {}).get("effect_id")),
                    "key": key,
                    "request": request,
                }
                self.accepted.append(item)
                current = self._projection(item)
                if (
                    status != 200
                    or current["inquiry"]["state"] != "accepted"
                    or current.get("outcome") is not None
                ):
                    raise ValueError("The withheld worker must leave accepted work pending")
                status, replay = self._request("/api/business/investigations", body)
                if (
                    status != 200
                    or replay.get("created") is not False
                    or replay.get("task_id") != task_id
                ):
                    raise ValueError("Each pending investigation must replay its original identity")
            (self.directory / "real-cohort-pending").write_text("1\n")
            self._wait("real-voice-ended", 80)
            if any(
                self._projection(item)["inquiry"]["state"] != "accepted" for item in self.accepted
            ):
                raise ValueError("Accepted work did not remain pending through voice End")
            (self.directory / "real-cohort-survived-end").write_text("1\n")
            # Count unpause, resume signalling and ready acknowledgement in the
            # original recovery window; never restart 45 seconds after readiness.
            self._recovery_started = time.monotonic()
            self._recovery_phase = "inquiry_recovery"
            due = self._recovery_started + 45
            self._resume()
            self._setup_active(due)
            for item in self.accepted:
                while True:
                    self._setup_active(due)
                    current = self._projection(item)
                    self._setup_active(due)
                    if current["inquiry"]["state"] == "succeeded":
                        expected = {
                            "booking_reference": "DEMO-BK-001",
                            "new_check_in": "2030-12-10",
                            "available": True,
                        }
                        if current["inquiry"].get("result") != expected:
                            raise ValueError(
                                "The actual inquiry result does not match its frozen request"
                            )
                        self._recovery_counts["inquiries_succeeded"] += 1
                        break
                    if self.stop.wait(0.05):
                        raise _CohortStopped()
                    if time.monotonic() >= due:
                        raise RuntimeError("Accepted work did not progress after voice End")
            self._recovery_marks["inquiry_completion_seconds"] = self._recovery_elapsed()
            self._recovery_phase = "receipt_reconciliation"
            self.result = {
                "accepted": 8,
                "read_and_replayed_pending": 8,
                "pending_before_end": 8,
                "pending_after_end": 8,
                "inquiry_succeeded_after_end": 8,
                "lost_accepted": 0,
            }
            self._setup_active(due)
            receipts = json.loads(
                self.control(
                    ["docker", "exec", self.worker, "python", "-c", RECEIPT_SCRIPT], timeout=4
                )
            )
            self._setup_active(due)
            early_proof = self.reconcile(receipts)
            self._setup_active(due)
            self.result["independent_inquiry_receipts_matched_before_cleanup"] = early_proof[
                "independent_inquiry_receipts_matched"
            ]
            self._recovery_marks["receipt_reconciliation_seconds"] = self._recovery_elapsed()
            self._recovery_phase = "cancellation_issuance"
            # Cancellation is explicit postmeasurement fixture cleanup, not a
            # model decision and not a successful booking mutation.
            for item in self.accepted:
                self._setup_active(due)
                command_id = str(uuid5(UUID(item["task_id"]), "real-media-postmeasurement-cleanup"))
                status, receipt = self._request(
                    "/api/business/cases/" + item["task_id"] + "/cancel",
                    {"command_id": command_id},
                )
                self._setup_active(due)
                if (
                    status != 200
                    or receipt.get("receipt", {}).get("command_id") != command_id
                    or receipt.get("receipt", {}).get("disposition") != "cancelled_before_commit"
                ):
                    raise ValueError("Explicit cohort cleanup cancellation was not committed")
                self._recovery_counts["cancellations_issued"] += 1
                self._record_projection(item["task_id"], receipt.get("projection"))
            self._recovery_marks["cancellation_issuance_seconds"] = self._recovery_elapsed()
            self._recovery_phase = "delivery_recovery"
            for item in self.accepted:
                while True:
                    self._setup_active(due)
                    current = self._projection(item)
                    self._setup_active(due)
                    outcome, delivery = current.get("outcome"), current.get("delivery")
                    if any(
                        value is not None and type(value) is not dict
                        for value in (outcome, delivery)
                    ):
                        raise ValueError(
                            "Cohort cleanup requires nullable outcome/delivery objects"
                        )
                    if (
                        outcome is not None
                        and outcome.get("state") == "cancelled"
                        and delivery is not None
                        and delivery.get("state") == "delivered"
                    ):
                        self._recovery_counts["deliveries_observed"] += 1
                        break
                    if self.stop.wait(0.05):
                        raise _CohortStopped()
                    if time.monotonic() >= due:
                        raise RuntimeError(
                            "The actual receiver did not accept cohort cleanup results"
                        )
            self._recovery_marks["delivery_completion_seconds"] = self._recovery_elapsed()
            self._recovery_phase = "pre_human_verification"
            self.result.update(
                {"explicitly_cancelled_after_measurement": 8, "cleanup_deliveries": 8}
            )
            (self.directory / "real-cohort-complete").write_text("1\n")
            self._wait("real-before-human", 150)
            # Independent supplier truth and durable command commitment are
            # checked before the browser is permitted to send human approval.
            self._owned()
            counter_script = "import json;from continuity_lab.mutation_supplier import MutationSupplier;from continuity_lab.completion_sink import CompletionSink;s=MutationSupplier('/data/supplier.sqlite3');print(json.dumps({'inquiries':s.count_inquiries(scope_id='demo-traveller'),'apply_calls':s.count_calls(scope_id='demo-traveller'),'mutations':s.count_mutations(scope_id='demo-traveller'),'receiver_events':CompletionSink('/data/completion.sqlite3').count()}))"
            actual = json.loads(
                self.control(
                    ["docker", "exec", self.worker, "python", "-c", counter_script],
                    timeout=4,
                )
            )
            if actual != {
                "inquiries": 9,
                "apply_calls": 0,
                "mutations": 0,
                "receiver_events": 8,
            }:
                raise ValueError("Independent supplier truth changed before human approval")
            from psycopg import sql

            with closing(self.runtime.connect(application_name="continuity-test")) as connection:
                row = connection.execute(
                    sql.SQL(
                        "SELECT (SELECT COUNT(*) FROM {}) AS intents,(SELECT COUNT(*) FROM {}) AS consumptions"
                    ).format(
                        sql.Identifier(self.runtime.schema, "action_intents"),
                        sql.Identifier(self.runtime.schema, "execution_signal_consumptions"),
                    )
                ).fetchone()
            if row != {"intents": 0, "consumptions": 0}:
                raise ValueError("A durable action was committed before human approval")
            self.result["pre_human_zero_apply_proven"] = True
            self._recovery_phase = "complete"
            (self.directory / "real-zero-apply-observed").write_text("1\n")
        except _CohortStopped:
            # Stopping an unarmed/unfinished fixture is owned cleanup, not
            # successful workload completion. require_complete still fails it.
            return
        except BaseException as error:  # noqa: BLE001 - parent retains only fixed failure categories
            self.error = error
        finally:
            if self.paused or self.quiesce_requested:
                try:
                    self._resume()
                except BaseException as error:  # noqa: BLE001 - preserve cleanup as failure
                    self.cleanup_error = error

    def _resume(self) -> None:
        if not (self.paused or self.quiesce_requested):
            return
        if self._resume_deadline is None:
            self._resume_deadline = time.monotonic() + 12
        due = self._resume_deadline
        if self._cleanup_deadline is not None:
            due = min(due, self._cleanup_deadline)
        self._quiescence_phase = "resuming"
        self._owned(deadline=due)
        if self.paused:
            try:
                self.control(["docker", "unpause", self.worker], timeout=self._remaining(due))
            except Exception:  # noqa: BLE001,S110 - inspect reconciles a possibly lost acknowledgement
                pass
            if (
                self.control(
                    ["docker", "inspect", "--format", "{{.State.Paused}}", self.worker],
                    timeout=self._remaining(due),
                )
                != "false"
            ):
                raise RuntimeError("The owned worker did not acknowledge unpause")
            self._remaining(due)
            self.paused = False
        if self.quiesce_requested:
            self._quiescence_counts["resume_signal_requests"] = min(
                self._quiescence_counts["resume_signal_requests"] + 1,
                MAX_COHORT_HEALTH_OBSERVATIONS,
            )
            try:
                self.control(
                    ["docker", "kill", "--signal", "SIGUSR2", self.worker],
                    timeout=self._remaining(due),
                )
            except Exception:  # noqa: BLE001,S110 - only fresh ready health can settle ambiguous resume
                pass
            while True:
                if self._worker_health(quiescent=False, deadline=due):
                    self._remaining(due)
                    self.quiesce_requested = False
                    break
                # Cleanup must still resume after an owned stop; the shared
                # absolute deadline, not the already-set stop event, bounds it.
                time.sleep(min(0.05, self._remaining(due)))
        self._quiescence_phase = "resumed"
        self._resume_deadline = None

    def close(self) -> None:
        self.stop.set()
        if self._cleanup_deadline is None:
            self._cleanup_deadline = time.monotonic() + 12
        if self.thread.ident is None:
            if self.paused or self.quiesce_requested or self.cleanup_error is not None:
                raise RuntimeError("The unstarted cohort has unresolved worker ownership")
            return
        self.thread.join(timeout=max(0, self._cleanup_deadline - time.monotonic()))
        if (
            self.thread.is_alive()
            or self.paused
            or self.quiesce_requested
            or self.cleanup_error is not None
        ):
            raise RuntimeError("The owned real-media cohort did not close successfully") from None

    def require_complete(self) -> None:
        if (
            self.error is not None
            or self.cleanup_error is not None
            or self.paused
            or self.quiesce_requested
            or not self._quiescence_observed
            or self._quiescence_phase != "resumed"
            or self.thread.is_alive()
            or self.result is None
            or self.result.get("pre_human_zero_apply_proven") is not True
            or self.result.get("cleanup_deliveries") != 8
        ):
            raise RuntimeError(
                "The declared real-media cohort did not establish completion"
            ) from None

    @staticmethod
    def _failure(error: BaseException | None) -> dict[str, object] | None:
        """Project only fixed categories and this controller's own bounded frame."""
        if error is None:
            return None
        categories = (
            (AssertionError, "AssertionError"),
            (ValueError, "ValueError"),
            (RuntimeError, "RuntimeError"),
            (TypeError, "TypeError"),
            (KeyError, "KeyError"),
            (IndexError, "IndexError"),
            (AttributeError, "AttributeError"),
            (OSError, "OSError"),
            (FileNotFoundError, "FileNotFoundError"),
            (PermissionError, "PermissionError"),
            (TimeoutError, "TimeoutError"),
            (ConnectionError, "ConnectionError"),
            (ImportError, "ImportError"),
            (ModuleNotFoundError, "ModuleNotFoundError"),
            (OverflowError, "OverflowError"),
            (MemoryError, "MemoryError"),
            (RecursionError, "RecursionError"),
            (UnicodeError, "UnicodeError"),
            (ZeroDivisionError, "ZeroDivisionError"),
            (urllib.error.HTTPError, "HTTPError"),
        )
        category = next((name for kind, name in categories if type(error) is kind), "other")
        # Read the builtin slot directly; dependency subclass properties/formatters
        # and exception messages, chains, locals and source paths remain untouched.
        trace: TracebackType | None = BaseException.__dict__["__traceback__"].__get__(error)
        line = 0
        for _ in range(64):
            if trace is None:
                break
            if (
                trace.tb_frame.f_code is PendingCohort._run.__code__
                and 1 <= trace.tb_lineno <= 100000
            ):
                line = trace.tb_lineno
            trace = trace.tb_next
        result: dict[str, object] = {
            "schema_version": 1,
            "error_category": category,
            "source_line": line,
        }
        if type(error) is urllib.error.HTTPError:
            attributes = BaseException.__getattribute__(error, "__dict__")
            if type(attributes) is dict:
                code = dict.get(attributes, "code")
                if type(code) is int and 100 <= code <= 599:
                    result["http_status"] = code
        return result

    def observation(self) -> dict[str, object]:
        return {
            "status": "cleanup_incomplete"
            if self.cleanup_error is not None or self.paused or self.quiesce_requested
            else "failed"
            if self.error is not None
            else "complete"
            if self.result is not None and self.result.get("pre_human_zero_apply_proven") is True
            else "stopped"
            if self.stop.is_set()
            else "waiting",
            "accepted": len(self.accepted),
            "worker_pause_unresolved": self.paused,
            "worker_quiesce_unresolved": self.quiesce_requested,
            "quiescence": self._quiescence_observation(),
            "thread_started": self.thread.ident is not None,
            "thread_alive": self.thread.is_alive(),
            "operation_error_observed": self.error is not None,
            "cleanup_error_observed": self.cleanup_error is not None,
            "operation_failure": self._failure(self.error),
            "cleanup_failure": self._failure(self.cleanup_error),
            "recovery": self._recovery_observation(),
        }

    def reconcile(self, receipts: object) -> dict[str, object]:
        from psycopg import sql

        from continuity_lab.case_models import identity

        if self.result is None or self.foreground is None:
            raise ValueError("The complete fresh cohort observation is required")
        foreground = self.foreground
        items = self.accepted + [
            {
                "task_id": uuid_value(foreground["task_id"]),
                "effect_id": uuid_value(foreground["inquiry"]["effect_id"]),
                "key": identity(foreground["request_key"]),
                "request": foreground["inquiry"]["request"],
            }
        ]
        with closing(self.runtime.connect(application_name="continuity-test")) as connection:
            rows = connection.execute(
                sql.SQL(
                    "SELECT t.task_id,t.idempotency_key AS key,t.payload,e.effect_id FROM {} t JOIN {} e USING(task_id) WHERE t.scope_id=%s LIMIT 10"
                ).format(
                    sql.Identifier(self.runtime.schema, "tasks"),
                    sql.Identifier(self.runtime.schema, "executions"),
                ),
                ("demo-traveller",),
            ).fetchall()
        expected = {
            item["task_id"]: {
                "key": item["key"],
                "payload": canonical(item["request"]).decode(),
                "effect_id": item["effect_id"],
            }
            for item in items
        }
        if (
            len(expected) != 9
            or len({item["effect_id"] for item in items}) != 9
            or len({item["key"] for item in items}) != 9
            or len(rows) != 9
            or {
                row["task_id"]: {key: row[key] for key in ("key", "payload", "effect_id")}
                for row in rows
            }
            != expected
        ):
            raise ValueError(
                "Every accepted task must reconcile against durable identity and payload"
            )
        expected_receipts = {
            item["effect_id"]: {
                "request_sha256": hashlib.sha256(canonical(item["request"])).hexdigest(),
                "result_sha256": hashlib.sha256(
                    canonical(
                        {
                            "booking_reference": item["request"]["booking_reference"],
                            "new_check_in": item["request"]["new_check_in"],
                            "available": True,
                        }
                    )
                ).hexdigest(),
            }
            for item in items
        }
        if (
            type(receipts) is not list
            or len(receipts) != 9
            or any(
                type(row) is not dict
                or set(row) != {"effect_id", "request_sha256", "result_sha256"}
                for row in receipts
            )
            or {
                row["effect_id"]: {key: row[key] for key in ("request_sha256", "result_sha256")}
                for row in receipts
            }
            != expected_receipts
        ):
            raise ValueError("Independent supplier inquiry receipts must match all nine tasks")
        return {
            **self.result,
            "durable_identity_payload_matches": 9,
            "independent_inquiry_receipts_matched": 9,
            "worker_quiescence": self._quiescence_observation(),
        }
