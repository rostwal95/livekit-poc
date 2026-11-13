"""Run isolated installed HTTP, native RTC, browser, supplier and trace evidence.

Reuse only the owned main PostgreSQL/LiveKit network. All serving containers,
application/fixture volumes and the ACTIVE v4 schema belong to one fresh UUID.
Passing evidence is published only after independent exact-resource cleanup.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import math
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from livekit.protocol.agent_dispatch import AgentDispatch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import p1_real_media as real_media
from p1_demo_ownership import SchemaOwnership, volume_prepare

PROVIDER_ENV_KEYS = frozenset({"DEEPGRAM_API_KEY", "OPENAI_API_KEY", "ELEVEN_API_KEY"})


def load_provider_environment(setup: Path) -> dict[str, str]:
    path = setup / "provider_config.py"
    spec = importlib.util.spec_from_file_location("p1_demo_provider_config", path)
    if spec is None or spec.loader is None:
        raise ValueError("The strict provider configuration loader is required")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.read_credentials(setup / ".env.providers").environment()


def provider_ca_mount(setup: Path, source: Path, folder: Path) -> tuple[str, dict[str, object]]:
    """Snapshot explicit public trust; no CA contents or original path enter reports."""
    spec = importlib.util.spec_from_file_location(
        "p1_demo_provider_ca", setup / "provider_config.py"
    )
    if spec is None or spec.loader is None:
        raise ValueError("The provider CA validator is required")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    raw = module.read_ca_bundle(source)
    target = folder / "provider-ca.pem"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(descriptor, "wb") as stream:
        os.fchmod(stream.fileno(), 0o644)
        stream.write(raw)
    return (
        "type=bind,src=" + str(target) + ",dst=/etc/ssl/certs/ca-certificates.crt,readonly",
        {
            "schema_version": 1,
            "bundle_sha256": hashlib.sha256(raw).hexdigest(),
            "bundle_bytes": len(raw),
        },
    )


def private_environment_file(
    folder: Path, name: str, settings: dict[str, str], *, mode: str
) -> Path:
    if mode not in {"scripted", "local_real", "provider_real"} or name not in {
        "worker",
        "native",
        "api",
    }:
        raise ValueError("Unknown owned runtime environment")
    present = PROVIDER_ENV_KEYS & settings.keys()
    if present and (name != "native" or mode != "provider_real"):
        raise ValueError("Provider credentials belong only to the selected native process")
    if name == "native" and mode == "provider_real" and present != PROVIDER_ENV_KEYS:
        raise ValueError("All three provider credentials are required")
    if any(
        type(key) is not str
        or re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is None
        or type(value) is not str
        or not value
        or any(character in value for character in "\r\n\x00")
        for key, value in settings.items()
    ):
        raise ValueError("Runtime environment contains unsupported data")
    path = folder / (name + ".env")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write("\n".join(key + "=" + value for key, value in settings.items()) + "\n")
    return path


MAX_JSON_BYTES = 1048576
MAX_TRACE_BYTES = 2097152
OBSERVATION_FIELDS = frozenset(
    {
        "llm_input_tokens",
        "llm_output_tokens",
        "stt_audio_seconds",
        "tts_audio_seconds",
        "tts_characters",
        "usage_updates",
        "report_events",
        "report_duration_seconds",
        "trace_exported",
        "trace_dropped",
        "trace_failed",
    }
)
BROWSER_FLAGS = frozenset(
    {
        "isolated_local_stack",
        "real_http",
        "native_room",
        "native_agent",
        "explicit_input_publication",
        "scripted_browser_input",
        "scripted_input_stopped",
        "input_committed",
        "native_submit_acknowledged",
        "audio_played",
        "native_status_requested",
        "speech_interrupt_acknowledged",
        "active_speech_interrupted",
        "same_task_reconnected",
        "fresh_room_reconnected",
        "native_reconnect_status_verified",
        "case_survived_voice_end",
        "reload_resumed_same_task",
        "microphone_denial_verified",
        "exact_quote_confirmed",
        "slow_pg_native_wait_observed",
        "slow_pg_media_control_responsive",
        "slow_pg_replay_same_task",
        "slow_pg_native_interrupt_acknowledged",
        "slow_supplier_quote_pending",
        "slow_supplier_native_interrupt_acknowledged",
        "slow_supplier_media_control_responsive",
        "slow_supplier_quote_resumed",
    }
)
BROWSER_DIAGNOSTIC_FLAGS = frozenset(
    {
        "voice_diagnostics_observed",
        "voice_connected",
        "voice_agent_present",
        "voice_session_ready",
    }
)
BROWSER_DIAGNOSTIC_COUNTERS = frozenset(
    {
        "voice_text_streams_received",
        "voice_text_chunks_received",
        "voice_text_received_bytes",
        "voice_text_sender_rejected",
        "voice_text_sender_rejected_closed",
        "voice_text_sender_rejected_missing",
        "voice_text_sender_rejected_non_agent",
        "voice_text_sender_rejected_no_selection",
        "voice_text_sender_rejected_identity_mismatch",
        "voice_text_sender_rejected_local",
        "voice_text_capacity_rejected",
        "voice_text_read_completed",
        "voice_text_read_failed",
        "voice_text_completed_bytes",
        "voice_text_after_read_rejected",
        "voice_text_callback_accepted",
        "voice_text_callback_rejected",
        "voice_text_callback_stale",
    }
)
INSTALLED_MODULE_SCRIPT = "import continuity_lab,services.conversation_agent,services.control_api,json,hashlib,platform,importlib.metadata; from pathlib import Path; roots={'continuity_lab':Path(continuity_lab.__file__).parent,'services/conversation_agent':Path(services.conversation_agent.__file__).parent,'services/control_api':Path(services.control_api.__file__).parent}; a=roots['services/conversation_agent']/'assets'; print(json.dumps({'roots':{k:str(r) for k,r in roots.items()},'modules':{k+'/'+p.name:hashlib.sha256(p.read_bytes()).hexdigest() for k,r in roots.items() for p in r.glob('*.py')},'assets':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in a.iterdir() if p.suffix in {'.wav','.json'}},'versions':{'python':platform.python_version(),**{n:importlib.metadata.version(n) for n in ('livekit-agents','livekit-api','opentelemetry-sdk')}}}))"


def installed_module_script(mode: str) -> str:
    if mode not in {"scripted", "local_real", "provider_real"}:
        raise ValueError("An explicit installed profile is required")
    if mode != "provider_real":
        return INSTALLED_MODULE_SCRIPT
    return INSTALLED_MODULE_SCRIPT.replace(
        "'livekit-agents','livekit-api','opentelemetry-sdk'",
        "'livekit-agents','livekit-api','opentelemetry-sdk','livekit-plugins-deepgram','livekit-plugins-openai','livekit-plugins-elevenlabs'",
    )


def require_provider_versions(value: object) -> None:
    if type(value) is not dict or any(
        value.get("livekit-plugins-" + name) != "1.8.11"
        for name in ("deepgram", "openai", "elevenlabs")
    ):
        raise ValueError("The exact declared provider plugins are required")


def remove_owned_container(
    name: str,
    label: str,
    control: Callable[..., str],
    *,
    clock: Callable[[], float] = time.monotonic,
    pause: Callable[[float], None] = time.sleep,
) -> None:
    """Reconcile a lost remove acknowledgement only from exact ID and name absence."""
    if (
        re.fullmatch(r"p1-g-[a-f0-9]{32}-[a-z0-9-]{1,32}", name) is None
        or re.fullmatch(r"io\.livekit-ecosystem\.demo=[a-f0-9]{32}", label) is None
    ):
        raise ValueError("An exact invocation-owned container is required")
    due = clock() + 10

    def call(argv: list[str]) -> str:
        remaining = due - clock()
        if remaining <= 0:
            raise TimeoutError("Owned container removal was not independently observed")
        return control(argv, timeout=min(2.0, remaining)).strip()

    def named() -> str:
        return call(["docker", "ps", "-aq", "--no-trunc", "--filter", "name=^/" + name + "$"])

    identifier = named()
    if not identifier:
        return
    if re.fullmatch(r"[a-f0-9]{64}", identifier) is None:
        raise ValueError("One exact owned container is required")
    identity = json.loads(
        call(
            [
                "docker",
                "inspect",
                "--format",
                '{"name":{{json .Name}},"labels":{{json .Config.Labels}}}',
                identifier,
            ]
        )
    )
    key, expected = label.split("=", 1)
    if (
        identity.get("name") != "/" + name
        or type(identity.get("labels")) is not dict
        or identity["labels"].get(key) != expected
    ):
        raise ValueError("Container ownership changed before cleanup")
    try:
        call(["docker", "rm", "-f", identifier])
    except Exception:  # noqa: BLE001,S110 - reconcile only exact absence, never dependency text
        pass  # Missing acknowledgement is not proof of removal; exact observations below decide.
    while True:
        current = call(["docker", "ps", "-aq", "--no-trunc", "--filter", "id=" + identifier])
        same_name = named()
        if not current and not same_name:
            return
        if current not in {"", identifier} or same_name not in {"", identifier}:
            raise ValueError("Container identity changed during cleanup")
        pause(min(0.1, max(0.0, due - clock())))


READ_REPORTS_SCRIPT = """import itertools,json
from pathlib import Path
p=Path('/tmp/conversation-observations')
if p.is_symlink() or (p.exists() and not p.is_dir()):
    raise ValueError('Invalid observation directory')
files=list(itertools.islice(p.glob('*.json'),33))
if len(files)>32:
    raise ValueError('Too many numeric observations')
records=[]
for path in sorted(files):
    if path.is_symlink() or not path.is_file() or not 1<=path.stat().st_size<=4096:
        raise ValueError('Invalid numeric observation file')
    with path.open('rb') as stream:
        raw=stream.read(4097)
    if len(raw)>4096:
        raise ValueError('Numeric observation file exceeds its byte bound')
    records.append(json.loads(raw))
print(json.dumps(records,allow_nan=False))
"""


def installed_source_inventory(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Snapshot the same core/service and speech assets at both provenance checks."""
    packages = {
        "continuity_lab": root / "projects/agent-continuity/python/src/continuity_lab",
        "services/conversation_agent": root / "services/conversation_agent",
        "services/control_api": root / "services/control_api",
    }
    if any(not (source / "__init__.py").is_file() for source in packages.values()):
        raise ValueError("Canonical core and service source packages are required")
    modules = {
        package + "/" + path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for package, source in packages.items()
        for path in source.glob("*.py")
    }
    assets = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (root / "services/conversation_agent/assets").iterdir()
        if path.suffix in {".wav", ".json"}
    }
    if (
        len(assets) != 10
        or "manifest.json" not in assets
        or sum(name.endswith(".wav") for name in assets) != 9
    ):
        raise ValueError("Nine installed speech assets and their manifest are required")
    return modules, assets


def browser_executable(value: str) -> str:
    """Accept one explicitly selected local browser executable, without discovery."""
    if type(value) is not str or not 1 <= len(value) <= 4096 or "\0" in value:
        raise ValueError("An explicit bounded browser executable path is required")
    path = Path(value)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or path.is_symlink()
        or not path.is_file()
        or not os.access(path, os.X_OK)
    ):
        raise ValueError("Browser executable must be an existing absolute executable regular file")
    return str(path)


def browser_sample_provenance(payload: bytes, expected_sha256: str) -> dict[str, object]:
    """Bind the actual browser-served WAV to the native packaged input fixture."""
    if (
        type(payload) is not bytes
        or not 44 <= len(payload) <= 524288
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
    ):
        raise ValueError("The browser sample must be a bounded trusted WAV fixture")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != expected_sha256:
        raise ValueError("The browser sample differs from the native packaged input")
    return {
        "source": "packaged_wav_webaudio",
        "sha256": digest,
        "bytes": len(payload),
        "physical_microphone_capture_verified": False,
    }


def console_provenance(directory: Path, fetch: Callable[[str, int], bytes]) -> dict[str, object]:
    """Verify served index and compiled assets before opening a browser session."""
    assets = directory / "assets"
    if (
        directory.is_symlink()
        or not directory.is_dir()
        or assets.is_symlink()
        or not assets.is_dir()
    ):
        raise ValueError("A current compiled console distribution is required")
    files = sorted(assets.iterdir())
    if not 1 <= len(files) <= 16 or any(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.(?:js|css)", path.name) is None
        for path in files
    ):
        raise ValueError("Compiled console assets exceed their fixed inventory bounds")
    selected = [("index.html", directory / "index.html", 65536)] + [
        ("assets/" + path.name, path, 2097152) for path in files
    ]
    hashes = {}
    total = 0
    for relative, path, maximum in selected:
        if path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size <= maximum:
            raise ValueError("Compiled console files must be bounded regular files")
        with path.open("rb") as stream:
            expected = stream.read(maximum + 1)
        total += len(expected)
        if not 1 <= len(expected) <= maximum or total > 4194304:
            raise ValueError("Compiled console bytes exceed their fixed budget")
        served = fetch("/" + relative, maximum)
        if type(served) is not bytes or not 1 <= len(served) <= maximum:
            raise ValueError("Served console bytes exceed their fixed budget")
        digest = hashlib.sha256(expected).hexdigest()
        if hashlib.sha256(served).hexdigest() != digest:
            raise ValueError("The serving console differs from the current compiled distribution")
        hashes[relative] = digest
    return {"files": hashes, "count": len(hashes)}


def verify_native_record(record: object) -> str:
    """Native logs expose only their fixed service, level, event and code."""
    from services.conversation_agent.telemetry import CODES, EVENTS

    if type(record) is not dict or set(record) != {
        "service",
        "timestamp",
        "severity",
        "event",
        "code",
    }:
        raise ValueError("Native producer log fields are outside the safe schema")
    if record["service"] != "conversation-agent" or record["severity"] not in {
        "debug",
        "info",
        "warning",
        "error",
        "critical",
    }:
        raise ValueError("Native producer service or severity is unsupported")
    if type(record["timestamp"]) is not str or not 1 <= len(record["timestamp"]) <= 64:
        raise ValueError("Native producer timestamp is unbounded")
    if record["event"] not in EVENTS or record["code"] not in CODES:
        raise ValueError("Native producer event or code is outside the finite vocabulary")
    return record["event"]


def safe_native_log_summary(raw: str) -> dict[str, object]:
    """Aggregate only validated finite native records; discard every raw body."""
    if type(raw) is not str or len(raw.encode("utf-8")) > 262144:
        raise ValueError("Native diagnostics exceed their byte bound")
    lines = raw.splitlines()
    if len(lines) > 500:
        raise ValueError("Native diagnostics exceed their line bound")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Native diagnostic fields must be unique")
            result[key] = value
        return result

    counts: dict[tuple[str, str, str], int] = {}
    discarded = accepted = 0
    for line in lines:
        try:
            record = json.loads(line, object_pairs_hook=unique)
            event = verify_native_record(record)
            key = event, record["code"], record["severity"]
        except (ValueError, TypeError, RecursionError):
            discarded += 1
            continue
        counts[key] = counts.get(key, 0) + 1
        accepted += 1
    return {
        "schema_version": 1,
        "status": "observed" if accepted else "unavailable",
        "accepted_lines": accepted,
        "discarded_lines": discarded,
        "records": [
            {"event": event, "code": code, "severity": severity, "count": count}
            for (event, code, severity), count in sorted(counts.items())
        ],
    }


API_ERROR_CODES = frozenset(
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
API_OPERATIONS = frozenset(
    (
        "business_cancel",
        "business_get",
        "business_quote",
        "business_session",
        "business_signal",
        "business_submit",
        "config",
        "health",
        "investigations",
        "metrics",
        "readiness",
        "session",
        "unknown",
    )
)
API_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "OTHER"})
API_LOG_FIELDS = frozenset(
    {
        "severity",
        "timestamp",
        "event",
        "operation",
        "method",
        "status",
        "duration_seconds",
        "request_id",
    }
)


def safe_api_log_summary(raw: str) -> dict[str, object]:
    """Aggregate fixed HTTP producer observations; discard identities and raw data."""
    if type(raw) is not str or len(raw.encode("utf-8")) > 262144:
        raise ValueError("API diagnostics exceed their byte bound")
    lines = raw.splitlines()
    if len(lines) > 500:
        raise ValueError("API diagnostics exceed their line bound")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("API diagnostic fields must be unique")
            result[key] = value
        return result

    def nonfinite(_value):
        raise ValueError("API diagnostic numbers must be finite")

    groups: dict[tuple[str, str, int, str, str], tuple[int, float, float]] = {}
    accepted = discarded = 0
    for line in lines:
        try:
            record = json.loads(line, object_pairs_hook=unique, parse_constant=nonfinite)
            if type(record) is not dict or set(record) not in (
                API_LOG_FIELDS,
                API_LOG_FIELDS | {"code"},
            ):
                raise ValueError("API producer fields are unsupported")
            if (
                type(record["timestamp"]) is not str
                or not 1 <= len(record["timestamp"]) <= 64
                or datetime.fromisoformat(record["timestamp"]).utcoffset() is None
                or type(record["request_id"]) is not str
                or re.fullmatch("[a-f0-9]{32}", record["request_id"]) is None
                or type(record["operation"]) is not str
                or record["operation"] not in API_OPERATIONS
                or type(record["method"]) is not str
                or record["method"] not in API_METHODS
                or type(record["status"]) is not int
                or not 100 <= record["status"] <= 599
                or type(record["duration_seconds"]) not in {int, float}
                or not 0 <= record["duration_seconds"] <= 3600
                or not math.isfinite(record["duration_seconds"])
            ):
                raise ValueError("API producer dimensions are unsupported")
            status = record["status"]
            code = record.get("code", "none")
            if (
                type(code) is not str
                or (status >= 400 and code not in API_ERROR_CODES)
                or (status < 400 and "code" in record)
                or record["severity"]
                != ("error" if status >= 500 else "warning" if status >= 400 else "info")
                or record["event"]
                != ("http_request_error" if status >= 400 else "http_request_completed")
            ):
                raise ValueError("API producer result is unsupported")
            key = record["operation"], record["method"], status, code, record["severity"]
            count, total, maximum = groups.get(key, (0, 0.0, 0.0))
            duration = float(record["duration_seconds"])
            groups[key] = count + 1, total + duration, max(maximum, duration)
            accepted += 1
        except (ValueError, TypeError, RecursionError, OverflowError):
            discarded += 1
    return {
        "schema_version": 1,
        "status": "observed" if accepted else "unavailable",
        "accepted_lines": accepted,
        "discarded_lines": discarded,
        "records": [
            {
                "operation": operation,
                "method": method,
                "status": status,
                "code": code,
                "severity": severity,
                "count": count,
                "duration_seconds_total": round(total, 6),
                "duration_seconds_max": maximum,
            }
            for (operation, method, status, code, severity), (count, total, maximum) in sorted(
                groups.items()
            )
        ],
    }


def native_worker_counts(value: object) -> dict[str, object]:
    """Retain stock SDK occupancy fields without worker, room or participant IDs."""
    if type(value) is not dict:
        raise ValueError("Native worker observation must be an object")
    jobs, load = value.get("active_jobs", 0), value.get("worker_load", 0)
    if (
        type(jobs) not in {int, float}
        or not 0 <= jobs <= 100
        or jobs != int(jobs)
        or type(load) not in {int, float}
        or not 0 <= load <= 100
        or not math.isfinite(load)
    ):
        raise ValueError("Native worker occupancy must be bounded numeric data")
    return {"active_jobs": int(jobs), "worker_load": load}


def dispatch_counts(records: Sequence[AgentDispatch]) -> dict[str, object]:
    """Summarize already scope-verified control-plane records without their content."""
    from livekit.protocol.agent import JobStatus

    if len(records) > 32:
        raise ValueError("Dispatch diagnostic records exceed their bound")
    statuses = {
        JobStatus.JS_PENDING: "pending",
        JobStatus.JS_RUNNING: "running",
        JobStatus.JS_SUCCESS: "succeeded",
        JobStatus.JS_FAILED: "failed",
        JobStatus.JS_CANCELLED: "cancelled",
    }
    jobs = dict.fromkeys((*statuses.values(), "unknown"), 0)
    zero_jobs = assigned = 0
    for record in records:
        observations = record.state.jobs
        if len(observations) > 16:
            raise ValueError("Dispatch diagnostic job observations exceed their bound")
        zero_jobs += not observations
        for job in observations:
            jobs[statuses.get(job.state.status, "unknown")] += 1
            assigned += bool(job.state.worker_id)
    return {
        "dispatches": len(records),
        "zero_job_dispatches": zero_jobs,
        "jobs": jobs,
        "assigned_jobs": assigned,
    }


async def conversation_dispatch_observations(
    url: str, key: str, secret: str, task_ids: set[str]
) -> dict[str, object]:
    from livekit import api
    from livekit.protocol.models import ParticipantInfo

    from continuity_lab.execution_models import ExecutionError
    from continuity_lab.session_grants import verify_grant

    records = []
    rooms = agents = browsers = 0
    async with (
        asyncio.timeout(4),
        api.LiveKitAPI(url=url, api_key=key, api_secret=secret) as client,
    ):
        response = await client.room.list_rooms(api.ListRoomsRequest())
        if len(response.rooms) > 64:
            raise ValueError("Dispatch room observations exceed their bound")
        for room in response.rooms:
            if re.fullmatch(r"business-[a-z0-9][a-z0-9-]{0,39}", room.name) is None:
                continue
            dispatches = await client.agent_dispatch.list_dispatch(room.name)
            if len(dispatches) > 32:
                raise ValueError("Dispatch room records exceed their bound")
            owned_room = False
            for item in dispatches:
                if item.agent_name != "local-business-agent" or item.state.deleted_at:
                    continue
                try:
                    grant = verify_grant(
                        item.metadata,
                        secret=secret,
                        room=room.name,
                        expected_scope="demo-traveller",
                        expected_actor="local-operator",
                    )
                except ExecutionError:
                    continue
                if grant.task_id not in task_ids:
                    continue
                owned_room = True
                records.append(item)
            if owned_room:
                rooms += 1
                participants = await client.room.list_participants(
                    api.ListParticipantsRequest(room=room.name)
                )
                if len(participants.participants) > 8:
                    raise ValueError("Dispatch participant observations exceed their bound")
                for participant in participants.participants:
                    agents += participant.kind == ParticipantInfo.AGENT
                    browsers += participant.kind != ParticipantInfo.AGENT
    return {
        "status": "observed",
        "rooms": rooms,
        "agent_participants": agents,
        "non_agent_participants": browsers,
        **dispatch_counts(records),
    }


def bounded_json(path: Path) -> object:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("Evidence must be a bounded regular JSON file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("Evidence exceeded its byte bound")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Evidence contains duplicate JSON fields")
            value[key] = item
        return value

    def nonfinite(_value):
        raise ValueError("Evidence contains nonfinite JSON numbers")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def jaeger_v3_query(service: str, started_us: int, ended_us: int) -> str:
    """Use the pinned collector's bounded OTLP-native raw query contract."""
    from continuity_lab.tracing import SERVICES

    if (
        type(service) is not str
        or service not in SERVICES
        or type(started_us) is not int
        or type(ended_us) is not int
        or not 0 < started_us <= ended_us <= 9007199254740991
    ):
        raise ValueError("Trace query scope and time bounds are invalid")
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    try:
        start = (epoch + timedelta(microseconds=started_us)).isoformat().replace("+00:00", "Z")
        end = (epoch + timedelta(microseconds=ended_us)).isoformat().replace("+00:00", "Z")
    except OverflowError as error:
        raise ValueError("Trace query time bounds exceed the supported range") from error
    return "/api/v3/traces?" + urllib.parse.urlencode(
        {
            "query.service_name": service,
            "query.start_time_min": start,
            "query.start_time_max": end,
            "query.search_depth": 100,
            "query.raw_traces": "true",
        }
    )


def _otlp_fields(value: object, allowed: set[str], required: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) - allowed or required - set(value):
        raise ValueError("Collector OTLP fields are unsupported")
    return value


def _otlp_decimal(value: object, maximum: int) -> int:
    if type(value) is not str or re.fullmatch(r"0|[1-9][0-9]{0,19}", value) is None:
        raise ValueError("Collector OTLP integer must be canonical decimal text")
    number = int(value)
    if number > maximum:
        raise ValueError("Collector OTLP integer exceeds its bound")
    return number


def _otlp_attributes(
    value: object, *, resource: bool = False, mode: str = "scripted"
) -> dict[str, object]:
    from continuity_lab.tracing import ATTR_ENUMS, NUMERIC, SERVICES, UUID_ATTRS

    if type(value) is not list or len(value) > 32:
        raise ValueError("Collector attributes exceed their count bound")
    result: dict[str, object] = {}
    resource_values = {
        "service.name": SERVICES,
        "service.version": {"0.1.0"},
        "continuity.mode": {mode},
    }
    for entry in value:
        item = _otlp_fields(entry, {"key", "value"}, {"key", "value"})
        key = item["key"]
        if type(key) is not str or key in result:
            raise ValueError("Collector attributes must have unique known names")
        field = _otlp_fields(item["value"], {"stringValue", "intValue", "doubleValue"}, set())
        if len(field) != 1:
            raise ValueError("Collector attribute must have exactly one typed value")
        if resource or key in ATTR_ENUMS:
            allowed = (
                resource_values
                if resource
                else {
                    **ATTR_ENUMS,
                    "continuity.mode": frozenset({mode}),
                    "gen_ai.provider.name": frozenset(real_media.PROVIDER_NAMES.values())
                    if mode == "provider_real"
                    else frozenset(),
                    "gen_ai.request.model": frozenset(real_media.models_for(mode).values())
                    if mode in real_media.REAL_PROFILES
                    else frozenset(
                        {
                            "scripted-business-v1",
                            "scripted-audio-turn-v1",
                            "scripted-pcm-speech-v1",
                        }
                    ),
                }
            )
            number = field.get("stringValue")
            if key not in allowed or type(number) is not str or number not in allowed[key]:
                raise ValueError("Collector enum attributes are unsupported")
        elif key in UUID_ATTRS:
            number = field.get("stringValue")
            if type(number) is not str or str(UUID(number)) != number:
                raise ValueError("Collector identity attributes must be canonical UUIDs")
        elif key in NUMERIC:
            if "intValue" in field:
                number = _otlp_decimal(field["intValue"], 9223372036854775807)
            else:
                numeric = field.get("doubleValue")
                if isinstance(numeric, bool) or not isinstance(numeric, (int, float)):
                    raise ValueError("Collector numeric attributes must be finite and bounded")
                if not 0 <= numeric <= 9223372036854775807 or not math.isfinite(numeric):
                    raise ValueError("Collector numeric attributes must be finite and bounded")
                number = numeric
        else:
            raise ValueError("Collector attribute names are unsupported")
        result[key] = number
    if resource and set(result) != set(resource_values):
        raise ValueError("Collector resource identity is incomplete")
    return result


class JaegerTraceSummary(TypedDict):
    trace_count: int
    span_count: int
    operations: list[str]
    privacy_verified: bool
    current_task_correlated: bool
    status_counts: dict[str, int]
    kind_counts: dict[str, int]
    query_api: str
    models: NotRequired[list[str]]
    tools: NotRequired[list[str]]
    providers: NotRequired[list[str]]
    model_providers: NotRequired[dict[str, str]]


def parse_jaeger_v3(
    raw: bytes, *, service: str, task_id: str, mode: str = "scripted"
) -> JaegerTraceSummary:
    """Validate exported OTLP data, excluding collector-generated enrichments."""
    from continuity_lab.tracing import SERVICES, SPAN_NAMES

    if (
        type(mode) is not str
        or mode not in {"scripted", "local_real", "provider_real"}
        or type(raw) is not bytes
        or not 0 < len(raw) <= MAX_TRACE_BYTES
        or type(service) is not str
        or service not in SERVICES
        or type(task_id) is not str
        or str(UUID(task_id)) != task_id
    ):
        raise ValueError("Collector response scope or byte bound is invalid")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Collector JSON fields must be unique")
            result[key] = value
        return result

    def nonfinite(_value):
        raise ValueError("Collector JSON numbers must be finite")

    decoder = json.JSONDecoder(object_pairs_hook=unique, parse_constant=nonfinite)
    text = raw.decode("utf-8")
    cursor = chunks = 0
    resources: list[object] = []
    while cursor < len(text):
        while cursor < len(text) and text[cursor] in " \r\n\t":
            cursor += 1
        if cursor == len(text):
            break
        chunks += 1
        if chunks > 256:
            raise ValueError("Collector streaming response exceeds its chunk bound")
        value, cursor = decoder.raw_decode(text, cursor)
        envelope = _otlp_fields(value, {"result"}, {"result"})
        payload = _otlp_fields(envelope["result"], {"resourceSpans"}, set())
        items = payload.get("resourceSpans", [])
        if type(items) is not list or len(items) + len(resources) > 4096:
            raise ValueError("Collector resource count exceeds its bound")
        resources.extend(items)
    if chunks == 0:
        raise ValueError("Collector returned no result envelope")
    traces: set[str] = set()
    operations: set[str] = set()
    models: set[str] = set()
    tools: set[str] = set()
    providers: set[str] = set()
    model_providers: dict[str, str] = {}
    count = total = 0
    correlated = False
    statuses = {"unset": 0, "ok": 0, "error": 0}
    kinds = {"internal": 0, "server": 0, "client": 0, "producer": 0, "consumer": 0}
    for entry in resources:
        resource = _otlp_fields(
            entry, {"resource", "scopeSpans", "schemaUrl"}, {"resource", "scopeSpans"}
        )
        if resource.get("schemaUrl", "") != "":
            raise ValueError("Collector resource schemas are unsupported")
        facts = _otlp_fields(
            resource["resource"],
            {"attributes", "droppedAttributesCount"},
            {"attributes"},
        )
        if (
            type(facts.get("droppedAttributesCount", 0)) is not int
            or facts.get("droppedAttributesCount", 0) != 0
        ):
            raise ValueError("Collector resource attributes were dropped")
        attributes = _otlp_attributes(facts["attributes"], resource=True, mode=mode)
        scopes = resource["scopeSpans"]
        if type(scopes) is not list or len(scopes) > 16:
            raise ValueError("Collector scope count exceeds its bound")
        for entry in scopes:
            scope = _otlp_fields(entry, {"scope", "spans", "schemaUrl"}, {"scope", "spans"})
            if scope.get("schemaUrl", "") != "" or scope["scope"] != {
                "name": "continuity.safe",
                "version": "1",
            }:
                raise ValueError("Collector instrumentation scope is unsupported")
            spans = scope["spans"]
            if type(spans) is not list or len(spans) > 4096:
                raise ValueError("Collector span count exceeds its bound")
            for entry in spans:
                total += 1
                if total > 4096:
                    raise ValueError("Collector total span count exceeds its bound")
                span = _otlp_fields(
                    entry,
                    {
                        "traceId",
                        "spanId",
                        "parentSpanId",
                        "flags",
                        "name",
                        "kind",
                        "startTimeUnixNano",
                        "endTimeUnixNano",
                        "attributes",
                        "status",
                        "traceState",
                        "events",
                        "links",
                        "droppedAttributesCount",
                        "droppedEventsCount",
                        "droppedLinksCount",
                    },
                    {
                        "traceId",
                        "spanId",
                        "name",
                        "kind",
                        "startTimeUnixNano",
                        "endTimeUnixNano",
                    },
                )
                for key, size in (
                    ("traceId", 32),
                    ("spanId", 16),
                    ("parentSpanId", 16),
                ):
                    if key in span and (
                        type(span[key]) is not str
                        or re.fullmatch("[0-9a-f]{" + str(size) + "}", span[key]) is None
                        or (key != "parentSpanId" and int(span[key], 16) == 0)
                    ):
                        raise ValueError("Collector span identities are unsupported")
                if (
                    span["name"] not in SPAN_NAMES | {"continuity.sdk"}
                    or type(span["kind"]) is not int
                    or span["kind"] not in {1, 2, 3, 4, 5}
                    or type(span.get("flags", 0)) is not int
                    or not 0 <= span.get("flags", 0) <= 1023
                    or span.get("traceState", "") != ""
                    or span.get("events", []) != []
                    or span.get("links", []) != []
                    or any(
                        type(span.get(key, 0)) is not int or span.get(key, 0) != 0
                        for key in (
                            "droppedAttributesCount",
                            "droppedEventsCount",
                            "droppedLinksCount",
                        )
                    )
                ):
                    raise ValueError("Collector span metadata or content is unsupported")
                start = _otlp_decimal(span["startTimeUnixNano"], 18446744073709551615)
                end = _otlp_decimal(span["endTimeUnixNano"], 18446744073709551615)
                if not 0 < start <= end:
                    raise ValueError("Collector span times are invalid")
                status = _otlp_fields(span.get("status", {}), {"code", "message"}, set())
                code = status.get("code", 0)
                if (
                    type(code) is not int
                    or code not in {0, 1, 2}
                    or status.get("message", "") != ""
                ):
                    raise ValueError("Collector status must contain only a finite code")
                values = _otlp_attributes(span.get("attributes", []), mode=mode)
                if attributes["service.name"] == service:
                    count += 1
                    traces.add(span["traceId"])
                    operations.add(span["name"])
                    if type(values.get("gen_ai.request.model")) is str:
                        models.add(str(values["gen_ai.request.model"]))
                    if type(values.get("gen_ai.tool.name")) is str:
                        tools.add(str(values["gen_ai.tool.name"]))
                    if mode == "provider_real" and type(values.get("gen_ai.request.model")) is str:
                        model_name = str(values["gen_ai.request.model"])
                        expected_provider = {
                            real_media.PROVIDER_MODELS[role]: provider
                            for role, provider in real_media.PROVIDER_NAMES.items()
                        }[model_name]
                        if values.get("gen_ai.provider.name") != expected_provider:
                            raise ValueError(
                                "Provider model spans require their exact declared provider"
                            )
                        providers.add(expected_provider)
                        model_providers[model_name] = expected_provider
                    statuses[("unset", "ok", "error")[code]] += 1
                    kinds[
                        ("internal", "server", "client", "producer", "consumer")[span["kind"] - 1]
                    ] += 1
                    correlated = correlated or values.get("continuity.task_id") == task_id
    summary: JaegerTraceSummary = {
        "trace_count": len(traces),
        "span_count": count,
        "operations": sorted(operations),
        "privacy_verified": True,
        "current_task_correlated": correlated,
        "status_counts": statuses,
        "kind_counts": kinds,
        "query_api": "v3_raw_otlp",
    }
    if mode in real_media.REAL_PROFILES:
        summary["models"] = sorted(models)
        summary["tools"] = sorted(tools)
    if mode == "provider_real":
        summary["providers"] = sorted(providers)
        summary["model_providers"] = model_providers
    return summary


def verify_browser(value: object, report: object) -> dict[str, object]:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("Browser observations have an unsupported schema")
    if any(value.get(name) is not True for name in BROWSER_FLAGS):
        raise ValueError("A declared browser requirement lacks passing evidence")
    if (
        value.get("unexpected_network_requests") != 0
        or value.get("supplier_outcome") != "succeeded"
    ):
        raise ValueError("The browser did not observe its scoped successful outcome")
    if not isinstance(report, dict) or not isinstance(report.get("stats"), dict):
        raise ValueError("The actual browser runner report is required")  # noqa: TRY004 - evidence validation uses one failure type
    stats = report["stats"]
    if (
        stats.get("unexpected") != 0
        or stats.get("skipped") != 0
        or stats.get("flaky") != 0
        or stats.get("expected") != 6
    ):
        raise ValueError("Exactly six required browser cases must pass without retries or skips")
    if (
        value.get("playwright_version") != "1.65.0"
        or type(value.get("browser_version")) is not str
        or not value["browser_version"]
    ):
        raise ValueError("Actual browser and pinned runner versions are required")
    return {"required_cases": 6, "passed_cases": 6, "observations": value}


def browser_stage_evidence(
    value: object, report: object, private_values: tuple[str, ...]
) -> dict[str, object]:
    """Retain only the verified browser stage when a later aggregate check fails."""
    observations = safe_browser_failure(value, private_values)
    verified = verify_browser(observations, report)
    assert isinstance(report, dict) and isinstance(report["stats"], dict)
    stats = {key: report["stats"][key] for key in ("expected", "unexpected", "skipped", "flaky")}
    if any(type(number) is not int for number in stats.values()):
        raise ValueError("Browser runner statistics must be exact integer counts")
    return {
        "schema_version": 1,
        "stage": "browser",
        "status": "passed",
        "phase_status": "not_established",
        "verified": verified,
        "runner_stats": stats,
    }


class AuthorityCounts(TypedDict):
    provider_matches: bool
    revision: int
    mutations: int
    apply_calls: int
    inquiries: int
    receiver_events: int


def safe_authority_counts(value: object, expected_provider_id: str) -> AuthorityCounts:
    """Expose independent fixture counts and an identity comparison, never raw IDs."""
    fields = {
        "provider_id",
        "revision",
        "mutations",
        "apply_calls",
        "inquiries",
        "receiver_events",
    }
    if type(value) is not dict or set(value) != fields:
        raise ValueError("Independent authority observations have an unsupported schema")
    for provider in (expected_provider_id, value["provider_id"]):
        if type(provider) is not str or str(UUID(provider)) != provider:
            raise ValueError("Independent authority identity must be a canonical UUID")
    counts: dict[str, int] = {}
    for field in fields - {"provider_id"}:
        number = value[field]
        if type(number) is not int or not 0 <= number <= 9223372036854775807:
            raise ValueError("Independent authority counts must be bounded nonnegative integers")
        counts[field] = number
    return {
        "provider_matches": value["provider_id"] == expected_provider_id,
        "revision": counts["revision"],
        "mutations": counts["mutations"],
        "apply_calls": counts["apply_calls"],
        "inquiries": counts["inquiries"],
        "receiver_events": counts["receiver_events"],
    }


def wait_for_authority(
    read: Callable[[float], object],
    record: Callable[[dict[str, object]], None],
    expected_provider_id: str,
    *,
    timeout_seconds: float = 15,
    clock: Callable[[], float] = time.monotonic,
    pause: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Wait only for receipt delivery; incorrect already-completed effects fail now."""
    if (
        type(timeout_seconds) not in {int, float}
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= 15
    ):
        raise ValueError("Authority observation deadline must be finite and at most 15 seconds")
    started = clock()
    deadline = started + timeout_seconds
    for attempt in range(1, 32):
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError("Independent completion delivery was not observed within its budget")
        value = read(min(4.0, remaining))
        observed = safe_authority_counts(value, expected_provider_id)
        elapsed = clock() - started
        if not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("Authority observation clock must be finite and monotonic")
        record({"attempt": attempt, "elapsed_seconds": elapsed, **observed})
        if (
            observed["provider_matches"] is not True
            or observed["revision"] != 1
            or observed["mutations"] != 1
            or observed["inquiries"] != 1
            or observed["apply_calls"] < 1
        ):
            raise ValueError("Independent supplier state does not match the one accepted effect")
        if elapsed > timeout_seconds:
            raise TimeoutError("Independent completion delivery exceeded its observation budget")
        if observed["receiver_events"] >= 1:
            assert isinstance(value, dict)
            return dict(value)
        remaining = deadline - clock()
        if remaining <= 0:
            break
        pause(min(0.5, remaining))
    raise TimeoutError("Independent completion delivery was not observed within its budget")


def numeric_sdk_values(
    record: object, *, require_report: bool, mode: str = "scripted"
) -> dict[str, int | float]:
    """Validate the same exact numeric-only schema for passing and failed runs."""
    if (
        type(mode) is not str
        or mode not in {"scripted", "local_real", "provider_real"}
        or type(record) is not dict
        or set(record) != {"schema_version", "mode", "sdk_report_observed", "values"}
        or type(record.get("schema_version")) is not int
        or record["schema_version"] != 1
        or record["mode"] != mode
        or type(record["sdk_report_observed"]) is not bool
        or (require_report and record["sdk_report_observed"] is not True)
    ):
        raise ValueError("Native SDK report must contain only numeric observations")
    values = record["values"]
    if type(values) is not dict or set(values) != OBSERVATION_FIELDS:
        raise ValueError("Native SDK observation fields are unsupported")
    for number in values.values():
        if (
            type(number) not in {int, float}
            or not 0 <= number <= 9223372036854775807
            or not math.isfinite(number)
        ):
            raise ValueError("Native SDK observations must be finite nonnegative numbers")
    return dict(values)


def safe_sdk_failure(records: object, *, mode: str = "scripted") -> dict[str, object]:
    """Keep zero/unobserved reports as diagnosis without satisfying a passing gate."""
    if type(mode) is not str or mode not in {"scripted", "local_real", "provider_real"}:
        raise ValueError("A fixed native observation profile is required")
    if type(records) is not list or len(records) > 32:
        raise ValueError("Failure SDK observation count exceeds its declared bound")
    safe = []
    totals = dict.fromkeys(OBSERVATION_FIELDS, 0.0)
    for record in records:
        values = numeric_sdk_values(record, require_report=False, mode=mode)
        safe.append(
            {
                "schema_version": 1,
                "mode": mode,
                "sdk_report_observed": record["sdk_report_observed"],
                "values": values,
            }
        )
        for key, number in values.items():
            totals[key] += number
    return {
        "status": "observed",
        "reports": len(safe),
        "records": safe,
        "totals": totals,
        (
            "real_inference_usage_only"
            if mode in real_media.REAL_PROFILES
            else "scripted_usage_only"
        ): True,
    }


def verify_sdk(records: list[object], *, mode: str = "scripted") -> dict[str, object]:
    if type(mode) is not str or mode not in {"scripted", "local_real", "provider_real"}:
        raise ValueError("A fixed native observation profile is required")
    if not (2 if mode in real_media.REAL_PROFILES else 3) <= len(records) <= 32:
        raise ValueError("Native SDK report count is outside its declared bound")
    totals = dict.fromkeys(OBSERVATION_FIELDS, 0.0)
    for record in records:
        for key, number in numeric_sdk_values(record, require_report=True, mode=mode).items():
            totals[key] += number
    if any(
        totals[key] <= 0
        for key in (
            "llm_input_tokens",
            "stt_audio_seconds",
            "tts_audio_seconds",
            "usage_updates",
            "report_events",
            "trace_exported",
        )
    ):
        raise ValueError("Actual native speech, SDK reports and exported traces must be positive")
    if mode in real_media.REAL_PROFILES and totals["llm_output_tokens"] <= 0:
        raise ValueError("Actual local model output token usage must be positive")
    if mode == "provider_real" and any(
        totals[field] != 0 for field in ("trace_dropped", "trace_failed")
    ):
        raise ValueError("Provider evidence requires successful complete trace export")
    return {
        "reports": len(records),
        "totals": totals,
        (
            "real_inference_usage_only"
            if mode in real_media.REAL_PROFILES
            else "scripted_usage_only"
        ): True,
    }


def safe_browser_failure(value: object, private_values: tuple[str, ...]) -> dict[str, object]:
    """Keep finite application observations, never arbitrary browser objects."""
    extras = {
        "schema_version",
        "browser_version",
        "playwright_version",
        "audio_current_time",
        "unexpected_network_requests",
        "supplier_outcome",
        "delivery_state",
        "last_phase",
        "last_status",
        "voice_displayed_transcripts",
    }
    if (
        type(value) is not dict
        or set(value)
        - BROWSER_FLAGS
        - BROWSER_DIAGNOSTIC_FLAGS
        - BROWSER_DIAGNOSTIC_COUNTERS
        - extras
    ):
        raise ValueError("Failure observations contain unsupported fields")
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("Failure observations have an unsupported schema")
    result = dict(value)
    for key, item in value.items():
        if key in BROWSER_FLAGS or key in BROWSER_DIAGNOSTIC_FLAGS:
            if type(item) is not bool:
                raise ValueError("Failure behavior observations must be booleans")
        elif key in BROWSER_DIAGNOSTIC_COUNTERS or key == "voice_displayed_transcripts":
            maximum = 40 if key == "voice_displayed_transcripts" else 1000000000
            if type(item) is not int or not 0 <= item <= maximum:
                raise ValueError("Failure voice diagnostics must be bounded integers")
        elif key in {"audio_current_time", "unexpected_network_requests"}:
            if (
                type(item) not in {int, float}
                or not 0 <= item <= 1000000
                or not math.isfinite(item)
            ):
                raise ValueError("Failure counts must be finite and bounded")
        elif key == "supplier_outcome":
            if item not in {
                "not_observed",
                "succeeded",
                "failed",
                "uncertain",
                "cancelled",
            }:
                raise ValueError("Failure outcome observations are unsupported")
        elif key == "delivery_state":
            if item not in {
                "not_observed",
                "pending",
                "delivering",
                "delivered",
                "exhausted",
            }:
                raise ValueError("Failure delivery observations are unsupported")
        elif key == "last_phase":
            if item not in {
                "submit",
                "resume",
                "join",
                "input",
                "interrupt",
                "reconnect",
                "slow_postgres",
                "held_supplier",
                "confirm",
            }:
                raise ValueError("Failure phase must use a fixed application vocabulary")
        elif key == "last_status":
            if type(item) is not str or len(item.encode("utf-8")) > 512:
                raise ValueError("Failure application status must be bounded")
            result[key] = " ".join(item.split())
        elif key in {"browser_version", "playwright_version"} and (
            type(item) is not str or re.fullmatch(r"[0-9.]{0,64}", item) is None
        ):
            raise ValueError("Failure runtime versions are unsupported")
    raw = json.dumps(result, allow_nan=False)
    if any(private in raw for private in private_values):
        raise ValueError("Failure observations contain private credentials")
    return result


def pg_wait_result(
    wait_started: datetime,
    observed_db: datetime,
    *,
    observed_unix_ms: int,
    released_unix_ms: int,
    observed_hold_seconds: float,
) -> dict[str, object]:
    """Preserve actual server wait age and local milestone times without identities."""
    if (
        type(wait_started) is not datetime
        or type(observed_db) is not datetime
        or wait_started.utcoffset() is None
        or observed_db.utcoffset() is None
    ):
        raise ValueError("PostgreSQL wait clocks must be aware timestamps")
    age = (observed_db - wait_started).total_seconds()
    if (
        not 0 <= age <= 60
        or type(observed_hold_seconds) not in {int, float}
        or not 0 <= observed_hold_seconds <= 60
        or not math.isfinite(observed_hold_seconds)
    ):
        raise ValueError("PostgreSQL wait duration must be finite and bounded")
    if (
        type(observed_unix_ms) is not int
        or type(released_unix_ms) is not int
        or not 0 <= observed_unix_ms <= released_unix_ms <= 9007199254740991
    ):
        raise ValueError("PostgreSQL wait wall clocks must be bounded integers")
    estimated_total = age + observed_hold_seconds
    return {
        "native_wait_observed": True,
        "schema_advisory_wait_verified": True,
        "native_wait_seconds": observed_hold_seconds,
        "actual_wait_age_at_observation_seconds": age,
        "actual_wait_seconds_estimate": estimated_total,
        "wait_started_unix_ms": int(wait_started.timestamp() * 1000),
        "observed_db_unix_ms": int(observed_db.timestamp() * 1000),
        "observed_unix_ms": observed_unix_ms,
        "released_unix_ms": released_unix_ms,
        "release_within_lock_timeout": estimated_total < 0.9,
    }


class SlowPostgresProbe:
    """Coordinate a real native PostgreSQL wait with a bounded browser control."""

    def __init__(
        self, runtime, native_ip: str, directory: Path, *, detection_seconds: int = 20
    ) -> None:
        if type(detection_seconds) is not int or detection_seconds not in {20, 45}:
            raise ValueError("The declared PostgreSQL detection budget is required")
        self.detection_seconds = detection_seconds
        self.runtime, self.native_ip, self.directory = runtime, native_ip, directory
        self.stop = threading.Event()
        self.error: BaseException | None = None
        self.result: dict[str, object] | None = None
        self.thread = threading.Thread(target=self._run, name="phase-g-slow-postgres", daemon=True)

    def _run(self) -> None:
        from continuity_lab.postgres_settings import advisory_keys

        try:
            while not (self.directory / "slow-pg-arm").exists():
                if self.stop.wait(0.02):
                    return
            with closing(self.runtime.connect(application_name="continuity-test")) as connection:
                keys = advisory_keys(self.runtime.schema, "admission")
                connection.execute("SELECT pg_advisory_lock(%s,%s)", keys)
                try:
                    (self.directory / "slow-pg-held").write_text("1\n")
                    deadline = time.monotonic() + self.detection_seconds
                    while time.monotonic() < deadline:
                        row = connection.execute(
                            "SELECT COUNT(*) AS n,MIN(l.waitstart) AS wait_started_at,clock_timestamp() AS observed_at FROM pg_stat_activity a JOIN pg_locks l ON l.pid=a.pid AND l.database=a.datid WHERE a.client_addr=%s::inet AND a.usename=current_user AND a.datname=current_database() AND a.wait_event_type='Lock' AND a.wait_event='advisory' AND l.locktype='advisory' AND NOT l.granted AND l.objsubid=2 AND l.classid=%s::oid AND l.objid=%s::oid AND l.waitstart IS NOT NULL",
                            (
                                self.native_ip,
                                keys[0] & 0xFFFFFFFF,
                                keys[1] & 0xFFFFFFFF,
                            ),
                        ).fetchone()
                        if row is not None and row["n"] > 0:
                            observed = time.monotonic()
                            observed_wall = time.time_ns() // 1000000
                            (self.directory / "slow-pg-observed").write_text("1\n")
                            # Native store lock_timeout is one second; release a
                            # real observed wait inside that budget.
                            time.sleep(0.5)
                            connection.execute("SELECT pg_advisory_unlock(%s,%s)", keys)
                            released = time.monotonic()
                            (self.directory / "slow-pg-released").write_text("1\n")
                            self.result = pg_wait_result(
                                row["wait_started_at"],
                                row["observed_at"],
                                observed_unix_ms=observed_wall,
                                released_unix_ms=time.time_ns() // 1000000,
                                observed_hold_seconds=released - observed,
                            )
                            return
                        if self.stop.wait(0.01):
                            return
                    raise RuntimeError(
                        "A native PostgreSQL wait was not observed before the fault deadline"
                    )
                finally:
                    connection.execute("SELECT pg_advisory_unlock(%s,%s)", keys)
        except BaseException as error:  # noqa: BLE001 - main thread preserves sanitized failure
            self.error = error

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=6)
        if self.thread.is_alive():
            raise RuntimeError("The owned PostgreSQL probe did not close")
        if self.error is not None:
            raise RuntimeError("The owned PostgreSQL probe failed") from self.error


class HeldSupplierProbe:
    """Hold the independent SQLite authority while actual RTC control proceeds."""

    HELD = "/tmp/phase-g-supplier-held"
    RELEASE = "/tmp/phase-g-supplier-release"
    HOLD_SCRIPT = r"""import sqlite3,time
from pathlib import Path
connection=sqlite3.connect('file:/data/supplier.sqlite3?mode=rw',uri=True,timeout=1)
connection.execute('BEGIN EXCLUSIVE')
Path('/tmp/phase-g-supplier-held').write_text('1\n')
deadline=time.monotonic()+8
try:
    while not Path('/tmp/phase-g-supplier-release').exists():
        if time.monotonic()>=deadline: raise RuntimeError('Owned supplier release deadline exceeded')
        time.sleep(.01)
finally:
    connection.rollback()
    connection.close()
"""

    def __init__(
        self, worker: str, directory: Path, output: Path, environment: dict[str, str]
    ) -> None:
        self.worker, self.directory, self.output, self.environment = (
            worker,
            directory,
            output,
            environment,
        )
        self.stop = threading.Event()
        self.error: BaseException | None = None
        self.result: dict[str, object] | None = None
        self.thread = threading.Thread(target=self._run, name="phase-g-held-supplier", daemon=True)

    def _marker(self, *, release: bool = False) -> bool:
        script = (
            "from pathlib import Path; Path(" + repr(self.RELEASE) + ").write_text('1\\n')"
            if release
            else "from pathlib import Path; import sys; sys.exit(not Path("
            + repr(self.HELD)
            + ").exists())"
        )
        result = subprocess.run(
            ["docker", "exec", self.worker, "python", "-c", script],
            cwd=ROOT,
            env=self.environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
        if result.returncode not in {0, 1}:
            raise RuntimeError("Owned supplier marker operation failed")
        return result.returncode == 0

    def _run(self) -> None:
        from harness.process_control import OwnedProcess

        try:
            while not (self.directory / "slow-supplier-arm").exists():
                if self.stop.wait(0.02):
                    return
            script = self.HOLD_SCRIPT
            with OwnedProcess(
                ["docker", "exec", self.worker, "python", "-c", script],
                cwd=ROOT,
                env=self.environment,
                output_directory=self.output,
                max_output_bytes=4096,
            ) as child:
                try:
                    due = time.monotonic() + 4
                    while not self._marker():
                        if child.returncode is not None or time.monotonic() >= due:
                            raise RuntimeError("The owned supplier exclusive lock was not observed")
                        time.sleep(0.02)
                    (self.directory / "slow-supplier-held").write_text("1\n")
                    requested = self.directory / "slow-supplier-requested"
                    while not requested.exists():
                        if self.stop.wait(0.01) or child.returncode is not None:
                            raise RuntimeError("The actual quote request was not observed")
                    observed = time.monotonic()
                    controls = self.directory / "slow-supplier-controls-done"
                    while not controls.exists() and time.monotonic() - observed < 0.65:
                        if self.stop.wait(0.005):
                            break
                    controls_observed = controls.exists()
                    if not self._marker(release=True):
                        raise RuntimeError("The owned supplier release was not acknowledged")
                    result = child.wait(timeout=3)
                    released = time.monotonic()
                    (self.directory / "slow-supplier-released").write_text("1\n")
                    if result.returncode != 0:
                        raise RuntimeError("The supplier lock holder did not exit successfully")
                    self.result = {
                        "sqlite_exclusive_observed": True,
                        "controls_completed_while_held": controls_observed,
                        "quote_wait_seconds": released - observed,
                        "release_within_provider_timeout": released - observed < 0.8,
                    }
                finally:
                    if child.returncode is None:
                        self._marker(release=True)
                        child.wait(timeout=3)
        except BaseException as error:  # noqa: BLE001 - main thread retains a safe failure
            self.error = error

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=6)
        if self.thread.is_alive():
            raise RuntimeError("The owned supplier lock probe did not close")
        if self.error is not None:
            raise RuntimeError("The owned supplier lock probe failed") from self.error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--browser-executable",
        type=browser_executable,
        help="Explicit installed executable; defaults to Playwright-managed Chromium",
    )
    parser.add_argument(
        "--mode", choices=("scripted", "local_real", "provider_real"), default="scripted"
    )
    parser.add_argument(
        "--provider-ca-bundle",
        type=Path,
        help="Explicit approved public CA bundle, provider_real only",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        help="Fresh absent report directory under repository .local/validation",
    )
    parser.add_argument(
        "--work-seconds",
        type=int,
        choices=(600,),
        help="Explicit 600-second work and 180-second cleanup budget for fresh runtime wrappers",
    )
    args = parser.parse_args(argv)
    mode = args.mode
    if args.provider_ca_bundle is not None and mode != "provider_real":
        raise ValueError("A provider CA bundle requires the explicit provider profile")
    provider_environment = (
        load_provider_environment(ROOT / "local-setup") if mode == "provider_real" else {}
    )
    deadlines: real_media.WorkDeadline | None = None
    if mode in real_media.REAL_PROFILES or args.work_seconds is not None:
        deadlines = real_media.WorkDeadline()
        deadlines.start()
    model_manifest_sha256 = real_media.model_manifest(ROOT) if mode == "local_real" else ""
    gate_source_hashes = (
        real_media.gate_inventory(ROOT, mode=mode) if mode in real_media.REAL_PROFILES else {}
    )
    media_declaration, declaration_sha256 = (
        real_media.declaration(ROOT, mode=mode) if mode in real_media.REAL_PROFILES else ({}, "")
    )
    from psycopg import sql

    from continuity_lab.cutover import cutover
    from continuity_lab.lease_models import CoordinationPolicy
    from continuity_lab.migrations import migrate
    from continuity_lab.postgres_migrations import (
        install_schema,
        upgrade_v2,
        upgrade_v3,
        upgrade_v4,
    )
    from continuity_lab.postgres_settings import PostgresSettings
    from harness.process_control import OwnedProcess

    spec = importlib.util.spec_from_file_location("phase_g_stack", ROOT / "local-setup/stack.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Local stack tooling is unavailable")
    stack = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stack)
    setup = ROOT / "local-setup"
    values = stack.load_settings(setup)
    stack.assert_owned_containers(setup, values)
    base = stack.compose_arguments(setup)

    def control(argv, timeout=30):
        bounded_timeout = deadlines.timeout(timeout) if deadlines is not None else timeout
        return stack.run(argv, values, setup, bounded_timeout).strip()

    main_api = control(base + ["ps", "-q", "control-api"])
    network = stack.PROJECT + "_lab"
    if mode in real_media.REAL_PROFILES:
        check_native = control(base + ["ps", "-q", "conversation-agent"])
        if check_native:
            raise RuntimeError(
                "Stop the ordinary conversation worker before isolated real-media qualification"
            )
    main_networks = json.loads(
        control(
            [
                "docker",
                "inspect",
                "--format",
                "{{json .NetworkSettings.Networks}}",
                main_api,
            ]
        )
    )
    if network not in main_networks:
        raise RuntimeError("The owned main runtime network is required")
    image = control(
        [
            "docker",
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            "livekit-agent-ecosystem-python:local",
        ]
    )
    console_image = control(
        [
            "docker",
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            "livekit-agent-ecosystem-console:local",
        ]
    )
    if not all(value.startswith("sha256:") for value in (image, console_image)):
        raise RuntimeError("Exact built runtime images are required")
    for port in (13001, 18081):
        with socket.socket() as port_socket:
            port_socket.bind(("127.0.0.1", port))
    run_id = uuid4().hex
    schema = "p1_conversation_demo_" + run_id
    label_key = "io.livekit-ecosystem.demo"
    label = label_key + "=" + run_id
    prefix = "p1-g-" + run_id
    volumes = [prefix + "-application", prefix + "-fixtures"]
    created_volumes: list[str] = []
    names: list[str] = []
    service_names = {key: prefix + "-" + key for key in ("api", "worker", "native", "console")}
    operator_token = secrets.token_urlsafe(36)
    private_values = tuple(values[key] for key in stack.SECRET_KEYS if values.get(key)) + (
        operator_token,
        *provider_environment.values(),
    )
    owner = PostgresSettings(
        port=int(values["POSTGRES_PORT"]),
        user="continuity_migrator",
        password=values["POSTGRES_MIGRATION_PASSWORD"],
        schema=schema,
    )
    runtime = PostgresSettings(
        port=int(values["POSTGRES_PORT"]),
        password=values["POSTGRES_PASSWORD"],
        schema=schema,
    )
    ownership = SchemaOwnership(owner)
    reports = (
        ROOT / ".local/validation/p1-phase-g"
        if mode == "scripted"
        else ROOT
        / (
            ".local/validation/p1-provider-real"
            if mode == "provider_real"
            else ".local/validation/p1-local-real"
        )
        / run_id
    )
    if args.artifact_root is not None:
        reports = real_media.artifact_root(ROOT, args.artifact_root)
    reports.mkdir(parents=True, exist_ok=mode == "scripted" and args.artifact_root is None)
    if mode in real_media.REAL_PROFILES:
        (reports / "declaration.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "declaration_sha256": declaration_sha256,
                    "declaration": media_declaration,
                },
                indent=2,
            )
            + "\n"
        )
    parent = ROOT / (
        ".local/phase-g-demo"
        if mode == "scripted"
        else (".local/p1-provider-real" if mode == "provider_real" else ".local/p1-local-real")
    )
    parent.mkdir(mode=0o700, exist_ok=True)
    started_at = int(time.time() * 1000000)
    state: dict[str, object] = {"stage": "prepare"}
    sdk_failure_observations: dict[str, object] = {"status": "not_observed"}
    authority_observations: list[dict[str, object]] = []
    result = None
    foreground_task_id: str | None = None
    probe: SlowPostgresProbe | None = None
    supplier_probe: HeldSupplierProbe | None = None
    cohort: real_media.PendingCohort | None = None
    engine_before: dict[str, object] = {}
    engine_after: dict[str, object] = {}
    engine_observations: dict[str, object] = {}
    cohort_observations: dict[str, object] = {}
    engine_provenance: dict[str, object] = {}
    resources_before: dict[str, object] = {}
    resource_observations: dict[str, object] = {}
    model_setup: dict[str, object] = {}
    provider_ca_folder: Path | None = None
    commands = 0

    def redact(raw: str) -> str:
        for private in private_values:
            raw = raw.replace(private, "[redacted]")
        return raw

    def failure(name: str, record: object) -> None:
        try:
            (reports / name).write_text(redact(json.dumps(record, indent=2)) + "\n")
        except OSError:
            return

    def check(condition: object, code: str) -> None:
        if not condition:
            state["invariant"] = code
            raise RuntimeError("A declared Phase G demo invariant failed")

    def retain_stage(stage: str, payload: object) -> None:
        if stage not in {"browser", "sdk", "authority"}:
            raise ValueError("Only fixed verified evidence stages may be retained")
        raw = json.dumps(payload, indent=2, allow_nan=False) + "\n"
        check(len(raw.encode("utf-8")) <= 131072, "bounded_stage_evidence")
        check(
            all(private not in raw for private in private_values),
            "stage_evidence_secret_exclusion",
        )
        path = reports / ("stage-" + run_id + "-" + stage + ".json")
        pending = path.with_suffix(".pending")
        descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w") as stream:
                stream.write(raw)
            pending.replace(path)
        finally:
            pending.unlink(missing_ok=True)

    try:
        with tempfile.TemporaryDirectory(prefix=run_id + "-", dir=parent) as folder_name:
            folder = Path(folder_name)
            coordination = folder / "coordination"
            coordination.mkdir(mode=0o700)
            browser_reports = folder / "browser-reports"
            browser_reports.mkdir(mode=0o700)

            def command(argv, *, timeout=30, include_stderr=False, environment=None):
                nonlocal commands
                commands += 1
                if commands > 1000:
                    raise RuntimeError("The demo command bound was exceeded")
                out = folder / ("command-" + str(commands))
                with OwnedProcess(
                    argv,
                    cwd=ROOT,
                    env=environment or stack.child_environment(values),
                    output_directory=out,
                    max_output_bytes=524288,
                ) as child:
                    try:
                        observed = child.wait(
                            timeout=deadlines.timeout(timeout) if deadlines is not None else timeout
                        )
                        if observed.returncode != 0:
                            raise RuntimeError("An owned demo command failed")
                        stdout = (out / "stdout.bin").read_bytes()
                        stderr = (out / "stderr.bin").read_bytes() if include_stderr else b""
                        if len(stdout) + len(stderr) > 262144:
                            raise RuntimeError("An owned demo result exceeded its byte bound")
                        return (
                            b"\n".join(part for part in (stdout, stderr) if part).decode().strip()
                        )
                    except Exception:
                        if child.returncode is None:
                            try:
                                # Give the exact still-owned child a finite chance
                                # to close its browser/fork children before the
                                # OwnedProcess context uses its SIGKILL fallback.
                                os.kill(child.pid, signal.SIGTERM)
                                child.wait(timeout=3)
                            except Exception:  # noqa: BLE001 - owned fallback still reaps
                                state["child_shutdown"] = "fallback_required"
                        failure(
                            "failed-" + run_id + "-command-" + str(commands) + ".json",
                            {
                                "stage": state["stage"],
                                "exit": child.returncode,
                                **(
                                    {"code": "owned_command_failed"}
                                    if mode in real_media.REAL_PROFILES
                                    else {
                                        "stdout": child.output_tail(
                                            "stdout",
                                            maximum_bytes=8192,
                                            redact_values=private_values,
                                        ),
                                        "stderr": child.output_tail(
                                            "stderr",
                                            maximum_bytes=8192,
                                            redact_values=private_values,
                                        ),
                                    }
                                ),
                            },
                        )
                        raise

            def envfile(name: str, settings: dict[str, str]) -> Path:
                return private_environment_file(folder, name, settings, mode=mode)

            if mode == "local_real":
                state["stage"] = "pinned-model-cache-verification"
                model_setup = json.loads(
                    command(
                        [
                            sys.executable,
                            str(ROOT / "local-setup/scripts/local_models.py"),
                        ],
                        timeout=90,
                    )
                )
                check(
                    type(model_setup) is dict
                    and model_setup.get("status") == "verified"
                    and model_setup.get("profile") == "p1-local-real-v1"
                    and model_setup.get("files") == 10
                    and type(model_setup.get("files")) is int
                    and model_setup.get("model_bytes") == 2708795741
                    and type(model_setup.get("model_bytes")) is int
                    and model_setup.get("runtime_downloads") is False,
                    "fresh_pinned_cache_verification_without_fetch",
                )
            pg_env = {
                "P1_POSTGRES_HOST": "postgres",
                "P1_POSTGRES_PORT": "5432",
                "P1_POSTGRES_DB": "livekit_lab",
                "P1_POSTGRES_USER": "livekit_lab",
                "P1_POSTGRES_PASSWORD": values["POSTGRES_PASSWORD"],
                "P1_POSTGRES_SCHEMA": schema,
                "P1_WORKER_SCOPE": "demo-traveller",
                "P1_TRACE_ENDPOINT": "http://jaeger:4318/v1/traces",
                "P1_TRACE_MODE": mode,
                "P1_CONVERSATION_INFERENCE": mode,
            }
            livekit_env = {
                "LIVEKIT_URL": "ws://livekit:7880",
                "LIVEKIT_API_KEY": values["LIVEKIT_API_KEY"],
                "LIVEKIT_API_SECRET": values["LIVEKIT_API_SECRET"],
                "LIVEKIT_AGENTS_PRELOAD_LOCAL_INFERENCE": "0",
                "LIVEKIT_LOG_LEVEL": "warn",
            }
            worker_env = envfile(
                "worker",
                {
                    **pg_env,
                    "P1_WORKER_SUPPLIER_DB": "/data/supplier.sqlite3",
                    "P1_WORKER_SINK_DB": "/data/completion.sqlite3",
                    "P1_WORKER_STATE_FILE": "/tmp/p1-worker.json",
                },
            )
            native_env = envfile("native", {**pg_env, **livekit_env, **provider_environment})
            native_ca_mounts: tuple[str, ...] = ()
            provider_ca_evidence: dict[str, object] | None = None
            if args.provider_ca_bundle is not None:
                provider_ca_folder = Path(tempfile.mkdtemp(prefix=run_id + "-ca-", dir=parent))
                ca_mount, provider_ca_evidence = provider_ca_mount(
                    setup, args.provider_ca_bundle, provider_ca_folder
                )
                native_ca_mounts = (ca_mount,)
            api_env = envfile(
                "api",
                {
                    **pg_env,
                    **livekit_env,
                    "LIVEKIT_PUBLIC_URL": "ws://127.0.0.1:" + values["LIVEKIT_HTTP_PORT"],
                    "LOCAL_ACCESS_TOKEN": operator_token,
                    "POSTGRES_HOST": "postgres",
                    "POSTGRES_PORT": "5432",
                    "POSTGRES_DB": "livekit_lab",
                    "POSTGRES_USER": "livekit_lab",
                    "POSTGRES_PASSWORD": values["POSTGRES_PASSWORD"],
                    "INTAKE_DATABASE": "/data/intake.sqlite3",
                    "P1_BUSINESS_ENABLED": "1",
                    "P1_BUSINESS_SUPPLIER_DB": "/business/supplier.sqlite3",
                    "P1_BUSINESS_WORKER_URL": "http://" + service_names["native"] + ":8082",
                },
            )
            # A new empty source explicitly activates only this UUID-owned target.
            source = folder / "source.sqlite3"
            migrate(source, folder / "before-v1.sqlite3")
            ownership.prepare(install_schema)
            cutover(source, folder / "before-cutover.sqlite3", owner)
            upgrade_v2(owner)
            upgrade_v3(owner)
            upgrade_v4(owner, policy=CoordinationPolicy(20, 2, 100, 30))
            for volume in volumes:
                volume_prepare(
                    volume,
                    label_key=label_key,
                    run_id=run_id,
                    candidates=created_volumes,
                    command=command,
                )
            bootstrap = prefix + "-volume"
            names.append(bootstrap)
            command(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    bootstrap,
                    "--label",
                    label,
                    "--network",
                    "none",
                    "--user",
                    "0:0",
                    "--mount",
                    "type=volume,src=" + volumes[0] + ",dst=/data",
                    "--mount",
                    "type=volume,src=" + volumes[1] + ",dst=/business",
                    image,
                    "chown",
                    "10001:10001",
                    "/data",
                    "/business",
                ]
            )

            def run_python(name, config, argv, *, mounts=(), ports=(), detached=True):
                names.append(name)
                args = [
                    "docker",
                    "run",
                    "--name",
                    name,
                    "--label",
                    label,
                    "--network",
                    network,
                    "--network-alias",
                    name,
                    "--user",
                    "10001:10001",
                    "--workdir",
                    "/tmp",
                    "--init",
                    "--read-only",
                    "--security-opt",
                    "no-new-privileges:true",
                    "--cap-drop",
                    "ALL",
                    "--tmpfs",
                    "/tmp:rw,nosuid,noexec,size=64m,mode=1777",
                    "--pids-limit",
                    "256",
                    "--memory",
                    "512m",
                    "--cpus",
                    "1.5",
                    "--stop-timeout",
                    "35",
                    "--env-file",
                    str(config),
                ]
                if detached:
                    args.append("-d")
                else:
                    args.append("--rm")
                for mount in mounts:
                    args += ["--mount", mount]
                for port in ports:
                    args += ["--publish", port]
                return command(args + [image] + list(argv), timeout=45)

            state["stage"] = "fixture-initialization"
            initialized = json.loads(
                run_python(
                    prefix + "-init",
                    worker_env,
                    ["python", "-m", "continuity_lab.worker_cli", "init-fixtures"],
                    mounts=["type=volume,src=" + volumes[1] + ",dst=/data"],
                    detached=False,
                )
            )
            check(initialized.get("status") == "fixtures_ready", "explicit_fixture_seed")
            # Reuse a running owned collector; otherwise create one exact labelled
            # collector/alias without changing the main Compose lifecycle.
            jaeger = control(base + ["--profile", "observability", "ps", "-q", "jaeger"])
            if jaeger:
                jaeger_url = "http://127.0.0.1:" + values["JAEGER_UI_PORT"]
            else:
                jaeger_name = prefix + "-jaeger"
                names.append(jaeger_name)
                with socket.socket() as port_probe:
                    port_probe.bind(("127.0.0.1", 26687))
                command(
                    [
                        "docker",
                        "run",
                        "-d",
                        "--name",
                        jaeger_name,
                        "--label",
                        label,
                        "--network",
                        network,
                        "--network-alias",
                        "jaeger",
                        "--user",
                        "10001:10001",
                        "--read-only",
                        "--security-opt",
                        "no-new-privileges:true",
                        "--cap-drop",
                        "ALL",
                        "--tmpfs",
                        "/tmp:rw,nosuid,noexec,size=16m,mode=1777",
                        "--memory",
                        "256m",
                        "--cpus",
                        "0.5",
                        "--pids-limit",
                        "128",
                        "--publish",
                        "127.0.0.1:26687:16686",
                        values["JAEGER_IMAGE"],
                    ]
                )
                jaeger_url = "http://127.0.0.1:26687"
            stack.wait_for_http(jaeger_url + "/")
            state["stage"] = "serving-startup"
            run_python(
                service_names["worker"],
                worker_env,
                ["python", "-m", "continuity_lab.worker_cli", "run"],
                mounts=["type=volume,src=" + volumes[1] + ",dst=/data"],
            )
            run_python(
                service_names["native"],
                native_env,
                ["python", "-m", "services.conversation_agent", "start"],
                mounts=native_ca_mounts,
            )
            if mode == "local_real":
                inference_network = stack.PROJECT + "_inference"
                check(
                    control(
                        [
                            "docker",
                            "network",
                            "inspect",
                            "--format",
                            '{{index .Labels "com.docker.compose.project"}}',
                            inference_network,
                        ]
                    )
                    == stack.PROJECT,
                    "owned_internal_inference_network",
                )
                check(
                    control(
                        [
                            "docker",
                            "network",
                            "inspect",
                            "--format",
                            "{{.Internal}}",
                            inference_network,
                        ]
                    )
                    == "true",
                    "internal_only_inference_network",
                )
                command(
                    [
                        "docker",
                        "network",
                        "connect",
                        inference_network,
                        service_names["native"],
                    ]
                )
            run_python(
                service_names["api"],
                api_env,
                [
                    "uvicorn",
                    "services.control_api.app:app",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "8080",
                    "--workers",
                    "1",
                    "--limit-concurrency",
                    "32",
                    "--no-access-log",
                ],
                mounts=[
                    "type=volume,src=" + volumes[0] + ",dst=/data",
                    "type=volume,src=" + volumes[1] + ",dst=/business,readonly",
                ],
                ports=["127.0.0.1:18081:8080"],
            )
            provider_trust: dict[str, object] = {"source": "image_os"}
            if provider_ca_evidence is not None:
                assert provider_ca_folder is not None
                for role in ("native", "api", "worker"):
                    mounted = json.loads(
                        control(
                            [
                                "docker",
                                "inspect",
                                "--format",
                                "{{json .Mounts}}",
                                service_names[role],
                            ]
                        )
                    )
                    ca_entries = [
                        item
                        for item in mounted
                        if item.get("Destination") == "/etc/ssl/certs/ca-certificates.crt"
                    ]
                    check(
                        (
                            len(ca_entries) == 1
                            and ca_entries[0].get("RW") is False
                            and ca_entries[0].get("Type") == "bind"
                            and ca_entries[0].get("Source")
                            == str(provider_ca_folder / "provider-ca.pem")
                        )
                        if role == "native"
                        else not ca_entries,
                        "explicit_ca_native_only_readonly_mount",
                    )
                check(
                    hashlib.sha256(
                        (provider_ca_folder / "provider-ca.pem").read_bytes()
                    ).hexdigest()
                    == provider_ca_evidence["bundle_sha256"],
                    "explicit_ca_snapshot_unchanged",
                )
                loaded = json.loads(
                    command(
                        [
                            "docker",
                            "exec",
                            service_names["native"],
                            "python",
                            "-I",
                            "-B",
                            "-c",
                            (
                                "import hashlib,json,ssl,os;from pathlib import Path;from httpcore2 import default_ssl_context;"
                                "p=Path('/etc/ssl/certs/ca-certificates.crt');raw=p.read_bytes();c=default_ssl_context(_trust_env=False);a=ssl.create_default_context();"
                                "print(json.dumps({'bundle_sha256':hashlib.sha256(raw).hexdigest(),'bundle_bytes':len(raw),"
                                "'default_target_verified':Path(ssl.get_default_verify_paths().openssl_cafile).resolve()==p,"
                                "'verified_tls':c.check_hostname and c.verify_mode==ssl.CERT_REQUIRED and a.check_hostname and a.verify_mode==ssl.CERT_REQUIRED,"
                                "'ambient_ca_absent':not any(k in os.environ for k in ('SSL_CERT_FILE','SSL_CERT_DIR','SSLKEYLOGFILE'))}))"
                            ),
                        ]
                    )
                )
                check(
                    loaded
                    == {
                        "bundle_sha256": provider_ca_evidence["bundle_sha256"],
                        "bundle_bytes": provider_ca_evidence["bundle_bytes"],
                        "default_target_verified": True,
                        "verified_tls": True,
                        "ambient_ca_absent": True,
                    },
                    "explicit_ca_native_bytes_and_verified_tls",
                )
                provider_trust = {
                    "source": "explicit_ca_bundle",
                    "bundle_sha256": provider_ca_evidence["bundle_sha256"],
                    "bundle_bytes": provider_ca_evidence["bundle_bytes"],
                    "native_only_mount_verified": True,
                }
                (reports / "provider-trust.json").write_text(
                    json.dumps(provider_trust, indent=2) + "\n"
                )
            nginx = folder / "nginx.conf"
            nginx.write_text(
                (ROOT / "apps/local-console/nginx.conf")
                .read_text()
                .replace(
                    "http://control-api:8080",
                    "http://" + service_names["api"] + ":8080",
                )
            )
            nginx.chmod(0o644)
            console = service_names["console"]
            names.append(console)
            command(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    console,
                    "--label",
                    label,
                    "--network",
                    network,
                    "--user",
                    "101:101",
                    "--read-only",
                    "--security-opt",
                    "no-new-privileges:true",
                    "--cap-drop",
                    "ALL",
                    "--tmpfs",
                    "/tmp:rw,nosuid,noexec,size=16m,mode=1777",
                    "--pids-limit",
                    "64",
                    "--memory",
                    "128m",
                    "--cpus",
                    "0.5",
                    "--mount",
                    "type=bind,src=" + str(nginx) + ",dst=/etc/nginx/conf.d/default.conf,readonly",
                    "--publish",
                    "127.0.0.1:13001:8080",
                    console_image,
                ]
            )
            stack.wait_for_http("http://127.0.0.1:18081/readyz")
            stack.wait_for_http("http://127.0.0.1:13001/healthz")
            state["stage"] = "image-provenance"
            early_modules, early_assets = installed_source_inventory(ROOT)
            early_installed = json.loads(
                command(
                    [
                        "docker",
                        "exec",
                        "--workdir",
                        "/tmp",
                        service_names["native"],
                        "python",
                        "-c",
                        installed_module_script(mode),
                    ]
                )
            )
            if mode == "provider_real":
                require_provider_versions(early_installed.get("versions"))
            check(
                early_installed["modules"] == early_modules,
                "preflight_installed_source",
            )
            check(early_installed["assets"] == early_assets, "preflight_installed_assets")
            check(
                all(
                    "site-packages" in Path(path).parts
                    for path in early_installed["roots"].values()
                ),
                "preflight_installed_package_locations",
            )

            def fetch_console(relative: str, maximum: int) -> bytes:
                with urllib.request.urlopen(
                    "http://127.0.0.1:13001" + relative, timeout=3
                ) as response:
                    return response.read(maximum + 1)

            console_distribution = console_provenance(
                ROOT / "apps/local-console/dist", fetch_console
            )
            sample_sha256 = hashlib.sha256(
                (ROOT / "services/conversation_agent/assets/input-investigate.wav").read_bytes()
            ).hexdigest()
            with urllib.request.urlopen(
                "http://127.0.0.1:13001/fixtures/input-investigate.wav", timeout=3
            ) as sample_response:
                sample_bytes = sample_response.read(524289)
            browser_audio = browser_sample_provenance(sample_bytes, sample_sha256)
            deadline = time.monotonic() + 45
            readiness_script = """import urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:8082/',timeout=2) as reply:
        print('ready' if reply.status==200 else 'pending')
except (OSError,ValueError):
    print('pending')
"""
            while True:
                native_state = json.loads(
                    control(
                        [
                            "docker",
                            "inspect",
                            "--format",
                            "{{json .State}}",
                            service_names["native"],
                        ]
                    )
                )
                check(
                    native_state.get("Running") is True,
                    "native_running_during_readiness",
                )
                readiness = command(
                    [
                        "docker",
                        "exec",
                        service_names["native"],
                        "python",
                        "-c",
                        readiness_script,
                    ]
                )
                if readiness == "ready":
                    break
                check(time.monotonic() < deadline, "bounded_native_readiness")
                time.sleep(0.2)
            native_ip = control(
                [
                    "docker",
                    "inspect",
                    "--format",
                    '{{with index .NetworkSettings.Networks "'
                    + network
                    + '"}}{{.IPAddress}}{{end}}',
                    service_names["native"],
                ]
            )
            check(bool(native_ip), "native_container_network_identity")
            probe = SlowPostgresProbe(
                runtime,
                native_ip,
                coordination,
                detection_seconds=45 if mode in real_media.REAL_PROFILES else 20,
            )
            probe.thread.start()
            supplier_probe = HeldSupplierProbe(
                service_names["worker"],
                coordination,
                folder / "supplier-lock-output",
                stack.child_environment(values),
            )
            supplier_probe.thread.start()

            def read_engine_metrics() -> dict[str, object]:
                script = "import json,urllib.request;print(json.dumps({k:json.loads(urllib.request.urlopen(u,timeout=2).read(4097)) for k,u in (('stt','http://p1-stt:8080/metrics'),('tts','http://p1-tts:5000/metrics'))}))"
                observed = json.loads(
                    command(
                        [
                            "docker",
                            "exec",
                            service_names["native"],
                            "python",
                            "-c",
                            script,
                        ],
                        timeout=6,
                    )
                )
                check(
                    type(observed) is dict and set(observed) == {"stt", "tts"},
                    "exact_real_engine_observations",
                )
                return {
                    engine: real_media.engine_metrics(observed[engine], engine=engine)
                    for engine in ("stt", "tts")
                }

            resource_targets = {"native": service_names["native"]}

            def read_resources() -> dict[str, object]:
                observed: dict[str, object] = {}
                for role, target in resource_targets.items():
                    cpu = dict(
                        line.split()
                        for line in command(
                            ["docker", "exec", target, "cat", "/sys/fs/cgroup/cpu.stat"]
                        ).splitlines()
                    )
                    quota, period = command(
                        ["docker", "exec", target, "cat", "/sys/fs/cgroup/cpu.max"]
                    ).split()
                    events = dict(
                        line.split()
                        for line in command(
                            [
                                "docker",
                                "exec",
                                target,
                                "cat",
                                "/sys/fs/cgroup/memory.events",
                            ]
                        ).splitlines()
                    )
                    value = {
                        "cpu_usage_usec": int(cpu["usage_usec"]),
                        "cpu_quota_usec": int(quota),
                        "cpu_period_usec": int(period),
                        "oom_kills": int(events["oom_kill"]),
                    }
                    for filename, key in (
                        ("memory.current", "memory_current_bytes"),
                        ("memory.peak", "memory_peak_bytes"),
                        ("memory.max", "memory_limit_bytes"),
                        ("pids.current", "pids_current"),
                        ("pids.max", "pids_limit"),
                    ):
                        value[key] = int(
                            command(
                                [
                                    "docker",
                                    "exec",
                                    target,
                                    "cat",
                                    "/sys/fs/cgroup/" + filename,
                                ]
                            )
                        )
                    observed[role] = value
                return observed

            if mode == "local_real":
                wrapper_hashes = {
                    name: hashlib.sha256(
                        (ROOT / "local-setup/inference" / name).read_bytes()
                    ).hexdigest()
                    for name in ("engine.py", "engine_child.py")
                }
                for engine in ("llm", "stt", "tts"):
                    target = control(base + ["ps", "-q", "p1-" + engine])
                    check(
                        bool(target) and "\n" not in target,
                        "one_exact_real_engine_" + engine,
                    )
                    check(
                        control(
                            [
                                "docker",
                                "inspect",
                                "--format",
                                '{{index .Config.Labels "com.docker.compose.project"}}',
                                target,
                            ]
                        )
                        == stack.PROJECT,
                        "owned_real_engine_project_" + engine,
                    )
                    check(
                        control(
                            [
                                "docker",
                                "inspect",
                                "--format",
                                "{{.State.Running}}",
                                target,
                            ]
                        )
                        == "true",
                        "actual_real_engine_running_" + engine,
                    )
                    mounts = json.loads(
                        control(
                            [
                                "docker",
                                "inspect",
                                "--format",
                                "{{json .Mounts}}",
                                target,
                            ]
                        )
                    )
                    model_mounts = [
                        mount for mount in mounts if mount.get("Destination") == "/models"
                    ]
                    check(
                        len(model_mounts) == 1
                        and model_mounts[0].get("Type") == "bind"
                        and model_mounts[0].get("RW") is False
                        and model_mounts[0].get("Source")
                        == str(ROOT / "local-setup/.local/models"),
                        "exact_readonly_pinned_model_cache_" + engine,
                    )
                    engine_image = control(["docker", "inspect", "--format", "{{.Image}}", target])
                    check(
                        re.fullmatch(r"sha256:[0-9a-f]{64}", engine_image) is not None,
                        "real_engine_image_identity_" + engine,
                    )
                    if engine == "llm":
                        manifest = json.loads(
                            (ROOT / "local-setup/models/local-model-manifest.json").read_bytes()
                        )
                        check(
                            control(
                                [
                                    "docker",
                                    "image",
                                    "inspect",
                                    "--format",
                                    "{{.Id}}",
                                    manifest["engines"]["llm"]["image"],
                                ]
                            )
                            == engine_image,
                            "exact_pinned_ollama_image",
                        )
                    else:
                        tag = (
                            "livekit-agent-ecosystem-"
                            + ("whisper" if engine == "stt" else "piper")
                            + ":local"
                        )
                        running_manifest = json.loads(
                            control(
                                [
                                    "docker",
                                    "inspect",
                                    "--format",
                                    "{{json .ImageManifestDescriptor}}",
                                    target,
                                ]
                            )
                        )
                        selected_manifest = json.loads(
                            control(
                                [
                                    "docker",
                                    "image",
                                    "inspect",
                                    "--platform",
                                    "linux/arm64",
                                    "--format",
                                    "{{json .Descriptor}}",
                                    tag,
                                ]
                            )
                        )
                        real_media.platform_manifest(running_manifest, selected_manifest)
                        script = "import hashlib,json;from pathlib import Path;p=Path('/opt/inference');print(json.dumps({n:hashlib.sha256((p/n).read_bytes()).hexdigest() for n in ('engine.py','engine_child.py')}))"
                        check(
                            json.loads(command(["docker", "exec", target, "python", "-c", script]))
                            == wrapper_hashes,
                            "actual_installed_inference_wrapper_" + engine,
                        )
                    engine_provenance[engine] = {
                        "image_id": engine_image,
                        "platform_manifest_digest": running_manifest["digest"]
                        if engine != "llm"
                        else engine_image,
                        "model_cache": "exact_readonly_pinned_cache",
                        "wrapper_hashes": wrapper_hashes if engine != "llm" else {},
                    }
                    resource_targets[engine] = target
                members = json.loads(
                    control(
                        [
                            "docker",
                            "network",
                            "inspect",
                            "--format",
                            "{{json .Containers}}",
                            stack.PROJECT + "_inference",
                        ]
                    )
                )
                expected_members = {
                    control(["docker", "inspect", "--format", "{{.Id}}", target])
                    for target in resource_targets.values()
                }
                check(
                    set(members) == expected_members,
                    "isolated_inference_network_has_no_other_consumers",
                )
            if mode in real_media.REAL_PROFILES:
                if mode == "provider_real":
                    resource_targets.update(
                        {role: service_names[role] for role in ("api", "worker")}
                    )
                resources_before = read_resources()
                if mode == "local_real":
                    engine_before = read_engine_metrics()
                cohort = real_media.PendingCohort(
                    worker=service_names["worker"],
                    label=label,
                    directory=coordination,
                    token=operator_token,
                    control=control,
                    runtime=runtime,
                )
                cohort.thread.start()
            state["stage"] = "actual-browser"
            browser_environment = {
                key: value
                for key, value in stack.child_environment(values).items()
                if key not in stack.SECRET_KEYS
                and not key.startswith(("P1_", "POSTGRES_", "LIVEKIT_", "LOCAL_", "COMPOSE_"))
            }
            browser_environment.pop("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", None)
            if args.browser_executable is not None:
                browser_environment["PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"] = args.browser_executable
            browser_env = {
                **browser_environment,
                "E2E_BASE_URL": "http://127.0.0.1:13001",
                "E2E_OPERATOR_TOKEN": operator_token,
                "E2E_REPORT_DIR": str(browser_reports),
                "E2E_COORDINATION_DIR": str(coordination),
                "E2E_BOOKING_REFERENCE": "DEMO-BK-001",
                "E2E_NEW_CHECK_IN": "2030-12-10",
                "E2E_RUN_ID": run_id,
                "E2E_REAL_PROFILE": mode if mode in real_media.REAL_PROFILES else "local_real",
            }
            node = shutil.which("node")
            check(node is not None, "host_node_available")
            try:
                command(
                    [
                        node,
                        str(ROOT / "apps/local-console/node_modules/@playwright/test/cli.js"),
                        "test",
                        "--config",
                        str(
                            ROOT
                            / "apps/local-console"
                            / (
                                "playwright.real.config.ts"
                                if mode in real_media.REAL_PROFILES
                                else "playwright.config.ts"
                            )
                        ),
                    ],
                    timeout=300,
                    environment=browser_env,
                )
            except Exception:
                # Keep only allowlisted observations before the private working
                # directory exits. Runner errors are already in redacted tails.
                try:
                    sdk_failure_observations = safe_sdk_failure(
                        json.loads(
                            command(
                                [
                                    "docker",
                                    "exec",
                                    service_names["native"],
                                    "python",
                                    "-c",
                                    READ_REPORTS_SCRIPT,
                                ],
                                timeout=4,
                            )
                        ),
                        mode=mode,
                    )
                except Exception:  # noqa: BLE001 - preserve the original browser failure
                    sdk_failure_observations = {
                        "status": "unavailable",
                        "code": "numeric_sdk_observation_unavailable",
                    }
                failure(
                    "failed-" + run_id + "-native-sdk-observations.json",
                    sdk_failure_observations,
                )
                try:
                    observed_failure = (
                        real_media.safe_browser(
                            bounded_json(browser_reports / "real-browser-observations.json"),
                            run_id=run_id,
                            passing=False,
                            mode=mode,
                        )
                        if mode in real_media.REAL_PROFILES
                        else safe_browser_failure(
                            bounded_json(browser_reports / "business-browser-observations.json"),
                            private_values,
                        )
                    )
                    failure(
                        "failed-" + run_id + "-browser-observations.json",
                        observed_failure,
                    )
                    runner_failure = bounded_json(browser_reports / "playwright.json")
                    if mode in real_media.REAL_PROFILES:
                        failure(
                            "failed-" + run_id + "-playwright-location.json",
                            real_media.safe_playwright_failure(
                                runner_failure,
                                source_root=ROOT,
                                source_lines=len(
                                    (ROOT / "apps/local-console/e2e/local-real.media.ts")
                                    .read_text()
                                    .splitlines()
                                ),
                            ),
                        )
                    if isinstance(runner_failure, dict) and isinstance(
                        runner_failure.get("stats"), dict
                    ):
                        stats = runner_failure["stats"]
                        safe_stats = {
                            key: stats[key]
                            for key in ("expected", "unexpected", "skipped", "flaky")
                            if type(stats.get(key)) is int
                            and 0 <= stats[key] <= (2 if mode in real_media.REAL_PROFILES else 6)
                        }
                        failure(
                            "failed-" + run_id + "-playwright-stats.json",
                            {"schema_version": 1, "stats": safe_stats},
                        )
                except (OSError, ValueError, TypeError):
                    failure(
                        "failed-" + run_id + "-browser-retention.json",
                        {
                            "status": "unavailable",
                            "code": "bounded_failure_observation_unavailable",
                        },
                    )
                raise
            finally:
                # Close the marker/SQL owner before its private directory exits.
                try:
                    probe.close()
                finally:
                    try:
                        supplier_probe.close()
                    finally:
                        if cohort is not None:
                            cohort.close()
            check(
                probe.result is not None and probe.result["release_within_lock_timeout"],
                "actual_native_postgres_wait",
            )
            check(
                supplier_probe.result is not None
                and supplier_probe.result["controls_completed_while_held"]
                and supplier_probe.result["release_within_provider_timeout"],
                "actual_held_supplier_native_control",
            )
            if mode in real_media.REAL_PROFILES:
                real_browser_value = real_media.safe_browser(
                    bounded_json(browser_reports / "real-browser-observations.json"),
                    run_id=run_id,
                    passing=True,
                    mode=mode,
                )
                foreground_task_id = real_media.uuid_value(real_browser_value["foreground_task_id"])
                browser = real_media.verify_browser(
                    bounded_json(browser_reports / "real-browser-observations.json"),
                    bounded_json(browser_reports / "playwright.json"),
                    run_id=run_id,
                    mode=mode,
                )
                retain_stage(
                    "browser",
                    {
                        "schema_version": 1,
                        "stage": "browser",
                        "status": "passed",
                        "phase_status": "not_established",
                        "verified": browser,
                    },
                )
                resources_after = read_resources()
                resource_observations = {
                    role: real_media.resource_window(
                        resources_before[role], resources_after[role], role=role, mode=mode
                    )
                    for role in resource_targets
                }
                if mode == "local_real":
                    check(
                        real_media.model_manifest(ROOT) == model_manifest_sha256,
                        "unchanged_frozen_model_manifest_during_media",
                    )
                check(
                    real_media.gate_inventory(ROOT, mode=mode) == gate_source_hashes,
                    "unchanged_current_gate_source_during_measurement",
                )
                if provider_ca_folder is not None and provider_ca_evidence is not None:
                    check(
                        hashlib.sha256(
                            (provider_ca_folder / "provider-ca.pem").read_bytes()
                        ).hexdigest()
                        == provider_ca_evidence["bundle_sha256"],
                        "unchanged_explicit_ca_during_media",
                    )
                if mode == "local_real":
                    engine_after = read_engine_metrics()
                    engine_observations = {
                        engine: real_media.engine_delta(
                            engine_before[engine], engine_after[engine], engine=engine
                        )
                        for engine in ("stt", "tts")
                    }
                check(cohort is not None, "actual_cohort_created")
                assert cohort is not None
                cohort.require_complete()
                cohort_observations = cohort.reconcile(
                    json.loads(
                        command(
                            [
                                "docker",
                                "exec",
                                service_names["worker"],
                                "python",
                                "-c",
                                real_media.RECEIPT_SCRIPT,
                            ]
                        )
                    )
                )
            else:
                browser = verify_browser(
                    bounded_json(browser_reports / "business-browser-observations.json"),
                    bounded_json(browser_reports / "playwright.json"),
                )
                retain_stage(
                    "browser",
                    browser_stage_evidence(
                        bounded_json(browser_reports / "business-browser-observations.json"),
                        bounded_json(browser_reports / "playwright.json"),
                        private_values,
                    ),
                )
            # Native reports contain no conversation bodies, prompts or tokens.
            state["stage"] = "sdk-report-and-authority"
            sdk_deadline = time.monotonic() + 15
            while True:
                sdk_records = json.loads(
                    command(
                        [
                            "docker",
                            "exec",
                            service_names["native"],
                            "python",
                            "-c",
                            READ_REPORTS_SCRIPT,
                        ]
                    )
                )
                try:
                    sdk = verify_sdk(sdk_records, mode=mode)
                    break
                except ValueError:
                    if time.monotonic() >= sdk_deadline:
                        raise
                    time.sleep(0.2)
            retain_stage(
                "sdk",
                {
                    "schema_version": 1,
                    "stage": "sdk",
                    "status": "passed",
                    "phase_status": "not_established",
                    "verified": sdk,
                },
            )
            authority_script = "import json; from continuity_lab.mutation_supplier import MutationSupplier; from continuity_lab.completion_sink import CompletionSink; s=MutationSupplier('/data/supplier.sqlite3'); b=s.booking(scope_id='demo-traveller',booking_reference='DEMO-BK-001'); print(json.dumps({'provider_id':s.provider_id,'revision':b.revision,'mutations':s.count_mutations(scope_id='demo-traveller'),'apply_calls':s.count_calls(scope_id='demo-traveller'),'inquiries':s.count_inquiries(scope_id='demo-traveller'),'receiver_events':CompletionSink('/data/completion.sqlite3').count()}))"

            def read_authority(remaining: float) -> object:
                return json.loads(
                    command(
                        [
                            "docker",
                            "exec",
                            service_names["worker"],
                            "python",
                            "-c",
                            authority_script,
                        ],
                        timeout=remaining,
                    )
                )

            def record_authority(observed: dict[str, object]) -> None:
                authority_observations.append(observed)
                retain_stage(
                    "authority",
                    {
                        "schema_version": 1,
                        "stage": "independent_authority",
                        "status": "observing",
                        "phase_status": "not_established",
                        "samples": authority_observations,
                    },
                )

            if mode in real_media.REAL_PROFILES:
                due = time.monotonic() + 15
                while True:
                    authority = read_authority(4)
                    observed = safe_authority_counts(authority, initialized["provider_id"])
                    record_authority(dict(observed))
                    check(
                        observed["provider_matches"]
                        and observed["revision"]
                        == observed["mutations"]
                        == observed["apply_calls"]
                        == 1
                        and observed["inquiries"] == 9
                        and observed["receiver_events"] <= 9,
                        "real_exact_effect_and_inquiry_truth",
                    )
                    if observed["receiver_events"] == 9:
                        break
                    check(time.monotonic() < due, "real_nine_receiver_deliveries")
                    time.sleep(0.2)
            else:
                authority = wait_for_authority(
                    read_authority, record_authority, initialized["provider_id"]
                )
            verified_authority = safe_authority_counts(authority, initialized["provider_id"])
            check(
                verified_authority["provider_matches"]
                and verified_authority["revision"] == verified_authority["mutations"] == 1
                and verified_authority["apply_calls"] >= 1
                and verified_authority["inquiries"]
                == (9 if mode in real_media.REAL_PROFILES else 1)
                and verified_authority["receiver_events"]
                >= (9 if mode in real_media.REAL_PROFILES else 1),
                "independent_supplier_receiver_truth",
            )
            retain_stage(
                "authority",
                {
                    "schema_version": 1,
                    "stage": "independent_authority",
                    "status": "passed",
                    "phase_status": "not_established",
                    "samples": authority_observations,
                },
            )
            with closing(runtime.connect(application_name="continuity-test")) as connection:
                counts = connection.execute(
                    sql.SQL(
                        "SELECT (SELECT COUNT(*) FROM {}) AS tasks,(SELECT COUNT(*) FROM {}) AS intents,(SELECT COUNT(*) FROM {}) AS consumptions"
                    ).format(
                        sql.Identifier(schema, "tasks"),
                        sql.Identifier(schema, "action_intents"),
                        sql.Identifier(schema, "execution_signal_consumptions"),
                    )
                ).fetchone()
                task_identity = connection.execute(
                    sql.SQL(
                        "SELECT task_id FROM {} WHERE scope_id=%s AND (%s::text IS NULL OR task_id=%s) ORDER BY task_id LIMIT 1"
                    ).format(sql.Identifier(schema, "tasks")),
                    (
                        "demo-traveller",
                        foreground_task_id,
                        foreground_task_id,
                    ),
                ).fetchone()
            check(
                task_identity is not None
                and type(task_identity["task_id"]) is str
                and str(UUID(task_identity["task_id"])) == task_identity["task_id"],
                "current_run_canonical_task_identity",
            )
            assert task_identity is not None
            authority_task_id = task_identity["task_id"]
            check(
                counts is not None
                and counts["tasks"] == (9 if mode in real_media.REAL_PROFILES else 1)
                and counts["intents"] == counts["consumptions"] == 1,
                "one_original_task_one_exact_confirmation",
            )
            # Installed code proof uses module bytes from site-packages, not the
            # source checkout or a source-code bind mount.
            expected, expected_assets = installed_source_inventory(ROOT)
            installed = json.loads(
                command(
                    [
                        "docker",
                        "exec",
                        "--workdir",
                        "/tmp",
                        service_names["native"],
                        "python",
                        "-c",
                        installed_module_script(mode),
                    ]
                )
            )
            if mode == "provider_real":
                require_provider_versions(installed.get("versions"))
            check(
                installed["modules"] == expected,
                "same_installed_core_and_service_source",
            )
            check(
                installed["assets"] == expected_assets,
                "same_nine_installed_wavs_and_manifest",
            )
            check(
                all("site-packages" in Path(path).parts for path in installed["roots"].values()),
                "proven_installed_package_locations",
            )
            for kind in ("api", "native", "worker"):
                check(
                    control(
                        [
                            "docker",
                            "inspect",
                            "--format",
                            "{{.Image}}",
                            service_names[kind],
                        ]
                    )
                    == image,
                    "same_exact_serving_runtime_image",
                )
            state["stage"] = "safe-producer-logs"
            log_events = {}
            for kind in ("api", "native", "worker"):
                text = command(
                    ["docker", "logs", "--tail", "500", service_names[kind]],
                    include_stderr=True,
                )
                check(
                    all(secret not in text for secret in private_values),
                    "producer_secret_exclusion",
                )
                events = []
                for line in text.splitlines():
                    try:
                        record = json.loads(line)
                    except ValueError:
                        check(kind != "native", "native_producer_requires_safe_json")
                        continue  # API/console startup banners are outside product observations.
                    check(isinstance(record, dict), "producer_json_shape")
                    if kind == "native":
                        verify_native_record(record)
                    check(
                        not any(
                            key in record
                            for key in (
                                "metadata",
                                "token",
                                "request",
                                "transcript",
                                "prompt",
                                "exception",
                            )
                        ),
                        "producer_content_exclusion",
                    )
                    if isinstance(record.get("event"), str):
                        events.append(record["event"])
                if kind == "native":
                    check(
                        {"session_started", "session_finished"} <= set(events),
                        "native_producer_lifecycle_events",
                    )
                    check(
                        "cleanup_failed" not in events and "session_failed" not in events,
                        "native_cleanup_completed_without_failure",
                    )
                log_events[kind] = sorted(set(events))
            command(
                [
                    "docker",
                    "stop",
                    "--time",
                    "35",
                    service_names["native"],
                    service_names["worker"],
                    service_names["api"],
                ],
                timeout=120,
            )
            state["stage"] = "actual-jaeger"
            traces: dict[str, Any] = {}
            privacy_values = private_values + (
                "DEMO-BK-001",
                "2030-12-10",
                "demo-traveller",
                "local-operator",
            )
            for service in ("business-api", "conversation-agent", "durable-worker"):
                due = time.monotonic() + 20
                while True:
                    query = jaeger_v3_query(service, started_at, time.time_ns() // 1000)
                    with urllib.request.urlopen(jaeger_url + query, timeout=3) as reply:
                        raw = reply.read(MAX_TRACE_BYTES + 1)
                    check(len(raw) <= MAX_TRACE_BYTES, "bounded_trace_query")
                    check(
                        all(private not in raw.decode("utf-8") for private in privacy_values),
                        "actual_trace_content_privacy",
                    )
                    observed_trace = parse_jaeger_v3(
                        raw, service=service, task_id=authority_task_id, mode=mode
                    )
                    required_native = service != "conversation-agent" or {
                        "continuity.session",
                        "function_tool",
                    } <= set(observed_trace["operations"])
                    if (
                        observed_trace["span_count"] > 0
                        and observed_trace["current_task_correlated"]
                        and required_native
                    ):
                        break
                    if time.monotonic() >= due:
                        raise RuntimeError("The actual collector did not observe required traces")
                    time.sleep(0.2)
                check(observed_trace["span_count"] > 0, "actual_positive_trace_spans")
                check(
                    observed_trace["current_task_correlated"],
                    "actual_current_task_uuid_correlation_" + service,
                )
                traces[service] = observed_trace
                if mode == "provider_real":
                    (reports / ("provider-trace-" + service + ".json")).write_bytes(raw)
            check(
                "continuity.session" in traces["conversation-agent"]["operations"]
                and "function_tool" in traces["conversation-agent"]["operations"],
                "actual_sdk_and_session_trace_spans",
            )
            if mode in real_media.REAL_PROFILES:
                native_trace = traces["conversation-agent"]
                check(
                    set(native_trace["models"]) == set(real_media.models_for(mode).values()),
                    "actual_three_local_model_trace_identities",
                )
                check(
                    {"submit_investigation", "get_case"} <= set(native_trace["tools"]),
                    "actual_real_inference_bound_tools",
                )
            if mode == "provider_real":
                check(
                    traces["conversation-agent"].get("model_providers")
                    == {
                        real_media.PROVIDER_MODELS[role]: provider
                        for role, provider in real_media.PROVIDER_NAMES.items()
                    },
                    "actual_exact_provider_model_pairs",
                )
                (reports / "provider-sdk-records.json").write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "run_id": run_id,
                            "mode": mode,
                            "records": sdk_records,
                        },
                        allow_nan=False,
                    )
                    + "\n"
                )
            result = {
                "status": "passed",
                "mode": mode if mode in real_media.REAL_PROFILES else "local_synthetic_scripted",
                **(
                    {
                        "schema_version": 1,
                        "run_id": run_id,
                        "declaration_sha256": declaration_sha256,
                        "cohort": cohort_observations,
                        "gate_source_hashes": gate_source_hashes,
                        "resources": resource_observations,
                    }
                    if mode in real_media.REAL_PROFILES
                    else {}
                ),
                **(
                    {"run_id": run_id}
                    if args.artifact_root is not None and mode == "scripted"
                    else {}
                ),
                **(
                    {
                        "engine_inference": engine_observations,
                        "model_manifest_sha256": model_manifest_sha256,
                        "model_setup": model_setup,
                        "engine_provenance": engine_provenance,
                    }
                    if mode == "local_real"
                    else {}
                ),
                **(
                    {
                        "provider_trust": provider_trust,
                        "provider_inference": {
                            "profile": "provider_real",
                            "models": real_media.PROVIDER_MODELS,
                            "providers": real_media.PROVIDER_NAMES,
                            "external_resources": "unobserved",
                            "actual_sdk_usage": True,
                        },
                    }
                    if mode == "provider_real"
                    else {}
                ),
                "runtime_image_id": image,
                "console_image_id": console_image,
                "console_distribution": console_distribution,
                "module_hashes": expected,
                "asset_hashes": expected_assets,
                "installed_package_roots": installed["roots"],
                "runtime_versions": installed["versions"],
                "browser_selection": "explicit_executable"
                if args.browser_executable
                else "playwright_managed_chromium",
                "browser": browser,
                "browser_audio_sample": browser_audio,
                "sdk": sdk,
                "slow_postgres": probe.result,
                "held_supplier": supplier_probe.result,
                "authority": authority,
                "authority_observations": authority_observations,
                "durable_counts": counts,
                "original_task_id": authority_task_id,
                "traces": traces,
                "producer_events": log_events,
                "main_m1_backend": "unchanged",
                "owned_serving_containers": 4,
                "owned_volumes": 2,
            }
            # Retain only secret-free numeric/browser summaries and the actual
            # successful runner statistics, never browser network archives.
            for filename in (
                ("real-browser-observations.json",)
                if mode in real_media.REAL_PROFILES
                else ("business-browser-observations.json", "playwright.json")
            ):
                raw = (browser_reports / filename).read_text()
                check(
                    all(private not in raw for private in private_values),
                    "browser_artifact_secret_exclusion",
                )
                (reports / filename).write_text(raw)
            if mode in real_media.REAL_PROFILES:
                (reports / "playwright-stats.json").write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "run_id": run_id,
                            "stats": browser["runner_stats"],
                        }
                    )
                    + "\n"
                )
            for filename in ("workspace.png", "case-completed.png"):
                screenshot = browser_reports / filename
                check(
                    screenshot.is_file()
                    and not screenshot.is_symlink()
                    and screenshot.stat().st_size <= 2097152,
                    "bounded_credential_empty_ui_screenshot",
                )
                shutil.copyfile(screenshot, reports / filename)
    except Exception as error:
        if isinstance(error, real_media.MediaDeadline):
            failure(
                "failed-" + run_id + "-deadline.json",
                {
                    "status": "failed",
                    "code": "owned_work_deadline_exceeded",
                    "stage": state["stage"],
                    "cleanup_status": "pending",
                },
            )
            raise
        dispatch_observations: dict[str, object] = {"status": "unavailable"}
        worker_observations: dict[str, object] = {"status": "unavailable"}
        try:
            with closing(runtime.connect(application_name="continuity-test")) as connection:
                task_rows = connection.execute(
                    sql.SQL(
                        "SELECT task_id FROM {} WHERE scope_id=%s ORDER BY task_id LIMIT 21"
                    ).format(sql.Identifier(schema, "tasks")),
                    ("demo-traveller",),
                ).fetchall()
            if len(task_rows) <= 20:
                dispatch_observations = asyncio.run(
                    conversation_dispatch_observations(
                        "ws://127.0.0.1:" + values["LIVEKIT_HTTP_PORT"],
                        values["LIVEKIT_API_KEY"],
                        values["LIVEKIT_API_SECRET"],
                        {row["task_id"] for row in task_rows},
                    )
                )
        except Exception:  # noqa: BLE001 - diagnostics cannot replace scenario failure
            dispatch_observations = {
                "status": "unavailable",
                "code": "dispatch_observation_unavailable",
            }
        try:
            worker_script = "import json,urllib.request; d=json.loads(urllib.request.urlopen('http://127.0.0.1:8082/worker',timeout=2).read(4097)); print(json.dumps({'active_jobs':d.get('active_jobs',0),'worker_load':d.get('worker_load',0)}))"
            native_owned = control(
                [
                    "docker",
                    "ps",
                    "-aq",
                    "--filter",
                    "name=^/" + service_names["native"] + "$",
                    "--filter",
                    "label=" + label,
                ]
            )
            if not native_owned:
                raise ValueError(
                    "The private worker observation requires its owned native container"
                )
            observed_worker = stack.run(
                ["docker", "exec", native_owned, "python", "-c", worker_script],
                values,
                setup,
                4,
            )
            worker_observations = {
                "status": "observed",
                **native_worker_counts(json.loads(observed_worker)),
            }
        except Exception:  # noqa: BLE001 - diagnostics cannot replace scenario failure
            worker_observations = {
                "status": "unavailable",
                "code": "worker_observation_unavailable",
            }
        log_tails: dict[str, object] = {}
        for kind, name in service_names.items():
            if kind == "api":
                try:
                    owned = control(
                        [
                            "docker",
                            "ps",
                            "-aq",
                            "--filter",
                            "name=^/" + name + "$",
                            "--filter",
                            "label=" + label,
                        ]
                    )
                    if not owned:
                        raise ValueError("An exact owned API process is required")
                    raw_api = stack.run(
                        ["docker", "logs", "--tail", "500", owned],
                        values,
                        setup,
                        10,
                        merge_output=True,
                    )
                    log_tails[kind] = safe_api_log_summary(raw_api)
                except Exception:  # noqa: BLE001 - diagnostics preserve the original scenario failure
                    log_tails[kind] = {
                        "status": "unavailable",
                        "code": "validated_api_events_unavailable",
                    }
                continue
            if mode in real_media.REAL_PROFILES:
                if kind != "native":
                    log_tails[kind] = "content_not_retained"
                    continue
                try:
                    owned = control(
                        [
                            "docker",
                            "ps",
                            "-aq",
                            "--filter",
                            "name=^/" + name + "$",
                            "--filter",
                            "label=" + label,
                        ]
                    )
                    if not owned:
                        raise ValueError("An exact owned native process is required")
                    raw_native = stack.run(
                        ["docker", "logs", "--tail", "500", owned],
                        values,
                        setup,
                        10,
                        merge_output=True,
                    )
                    log_tails[kind] = safe_native_log_summary(raw_native)
                except Exception:  # noqa: BLE001 - no raw model diagnostics are retained
                    log_tails[kind] = {
                        "status": "unavailable",
                        "code": "validated_native_events_unavailable",
                    }
                continue
            try:
                owned = control(
                    [
                        "docker",
                        "ps",
                        "-aq",
                        "--filter",
                        "name=^/" + name + "$",
                        "--filter",
                        "label=" + label,
                    ]
                )
                if owned:
                    log_tails[kind] = redact(
                        stack.run(
                            ["docker", "logs", "--tail", "50", owned],
                            values,
                            setup,
                            10,
                            merge_output=True,
                        )
                    )[-8192:]
            except Exception:  # noqa: BLE001 - preserve scenario failure during diagnostics
                log_tails[kind] = "unavailable"

        failure(
            "failed-" + run_id + "-scenario.json",
            {
                "status": "failed",
                "state": state,
                "error_type": type(error).__name__,
                "safe_log_tails": log_tails,
                "dispatch_observations": dispatch_observations,
                "native_worker_observations": worker_observations,
                "native_sdk_observations": sdk_failure_observations,
                "independent_authority_observations": authority_observations,
                "slow_postgres": None if probe is None else probe.result,
                "cohort": None if cohort is None else cohort.observation(),
            },
        )
        raise
    finally:
        if deadlines is not None:
            try:
                deadlines.begin_cleanup()
            except real_media.MediaDeadline:
                deadlines.begin_cleanup()
        cleanup = []
        if cohort is not None:
            try:
                cohort.close()
            except Exception:  # noqa: BLE001 - all owned cleanup continues
                cleanup.append("owned_cohort_cleanup_failed")
        if probe is not None:
            try:
                probe.close()
            except Exception:  # noqa: BLE001 - independent owned cleanup must continue
                cleanup.append("owned_fault_probe_cleanup_failed")
        if supplier_probe is not None:
            try:
                supplier_probe.close()
            except Exception:  # noqa: BLE001 - independent owned cleanup must continue
                cleanup.append("owned_supplier_probe_cleanup_failed")
        native_removed = service_names["native"] not in names
        for name in reversed(names):
            try:
                remove_owned_container(name, label, control)
                if name == service_names["native"]:
                    native_removed = True
            except Exception:  # noqa: BLE001 - independent owned cleanup must continue
                cleanup.append("owned_container_cleanup_failed")
        if provider_ca_folder is not None:
            if native_removed:
                try:
                    (provider_ca_folder / "provider-ca.pem").unlink(missing_ok=True)
                    provider_ca_folder.rmdir()
                except OSError:
                    cleanup.append("owned_provider_ca_snapshot_cleanup_failed")
            else:
                cleanup.append("owned_provider_ca_snapshot_retained")
        for volume in created_volumes:
            try:
                check(
                    volume in {prefix + "-application", prefix + "-fixtures"},
                    "exact_volume_name_cleanup",
                )
                existing_volume = control(
                    ["docker", "volume", "ls", "-q", "--filter", "name=^" + volume + "$"]
                )
                if not existing_volume:
                    continue
                check(
                    control(
                        [
                            "docker",
                            "volume",
                            "inspect",
                            "--format",
                            '{{ index .Labels "' + label_key + '" }}',
                            volume,
                        ]
                    )
                    == run_id,
                    "exact_volume_label_cleanup",
                )
                control(["docker", "volume", "rm", volume])
            except Exception:  # noqa: BLE001 - independent owned cleanup must continue
                cleanup.append("owned_volume_cleanup_failed")
        try:
            if deadlines is not None:
                deadlines.timeout(5)
            ownership.cleanup()
        except Exception:  # noqa: BLE001 - independent owned cleanup must continue
            cleanup.append("owned_schema_cleanup_failed")
        if deadlines is not None:
            deadlines.finish()
            failure(
                "cleanup-" + run_id + ".json",
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "status": "failed" if cleanup else "passed",
                    "cleanup_verified": not cleanup,
                    "codes": cleanup,
                },
            )
        if cleanup:
            failure(
                "failed-" + run_id + "-cleanup.json",
                {"status": "failed", "codes": cleanup},
            )
            if sys.exc_info()[0] is None:
                raise RuntimeError("Owned cleanup did not complete")
    if result is None:
        raise RuntimeError("The demonstration did not establish passing evidence")
    result["cleanup_verified"] = True
    (reports / "container-demo.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return 0


# Fixed source identifiers only: no absolute paths, message, cause, locals or args.
PREFLIGHT_SOURCE_FILES = {
    "phase_g_demo": "local-setup/scripts/phase_g_demo.py",
    "p1_real_media": "local-setup/scripts/p1_real_media.py",
    "stack": "local-setup/stack.py",
}
PREFLIGHT_ERROR_TYPES = (
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
)


def safe_top_level_failure(error: BaseException) -> dict[str, object]:
    """Project the original exception without formatting arbitrary dependency data."""
    category = next((name for kind, name in PREFLIGHT_ERROR_TYPES if type(error) is kind), "other")
    source, line = "unavailable", 0
    trace: TracebackType | None = BaseException.__getattribute__(error, "__traceback__")
    allowed = {str(ROOT / path): name for name, path in PREFLIGHT_SOURCE_FILES.items()}
    # A malformed/deep dependency traceback cannot create unbounded diagnostic work.
    for _ in range(256):
        if trace is None:
            break
        filename = trace.tb_frame.f_code.co_filename
        if filename in allowed and 1 <= trace.tb_lineno <= 100000:
            source, line = allowed[filename], trace.tb_lineno
        trace = trace.tb_next
    return {
        "status": "failed",
        "code": "phase_g_demo_failed",
        "action": "inspect_retained_safe_evidence",
        "failure": {
            "schema_version": 1,
            "error_category": category,
            "source": source,
            "line": line,
        },
    }


def cli(argv: list[str] | None = None) -> int:
    try:
        return main(argv)
    except Exception as error:  # noqa: BLE001 - secret-safe local operator boundary
        print(json.dumps(safe_top_level_failure(error), allow_nan=False, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
