"""Pure document gate boundaries; reviewed 12 November 2026.

No product imports, configuration reads, listeners, compilers or workers on import.
These validators bind declared synthetic evidence; they are not an execution ledger.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, TypeGuard

CONTRACT_CASES = (
    "cross_language_document_schema_canonical_fingerprint_and_exact_correlation",
    "legacy_policy_wire_defaults_and_public_types_unchanged",
    "strict_document_shape_dates_status_nullability_and_region_bounds",
    "schema_valid_wrong_extracted_value_fails_independent_fixture_verdict",
    "schema_valid_swapped_region_source_version_or_digest_fails_verdict",
    "actual_fixture_manifest_and_decoded_pixel_hash_parity",
    "imports_no_IO_no_mutation_send_or_policy_eligible_surface",
    "nested_request_provider_result_snapshots_before_await",
)
HTTP_CASES = (
    "actual_HTTP_complete_image_useful_fields_and_scoped_regions",
    "actual_HTTP_missing_required_field_clarification_without_invention",
    "actual_HTTP_ambiguous_conflicting_source_clarification",
    "actual_HTTP_adversarial_image_text_is_inert",
    "wrong_scope_or_missing_capability_result_cancel_evidence_grants_zero_provider",
    "inaccessible_source_unknown_reference_or_URL_zero_provider",
    "encoded_size_declared_length_actual_dimensions_and_pixel_bounds_zero_provider",
    "corrupt_CRC_truncation_trailing_APNG_unsupported_format_zero_provider",
    "bounded_IDAT_expansion_exact_scanlines_filter_and_worker_failure_zero_provider",
    "expired_before_start_zero_decode_provider_and_useful_current_progress",
    "timeout_cancel_held_provider_thread_ownership_incomplete_close_then_progress",
    "shared_attempt_capacity_identity_status_cancel_scope_and_second_principal_progress",
)
CASE_NAMES = CONTRACT_CASES + HTTP_CASES
FIELDS = ("booking_reference", "property_name", "check_in", "check_out")
MODE = "local_scripted_document"
MAX_CHILDREN = 32
MAX_STREAM = 65536
MAX_CAPTURE = 2097152
MAX_PROOF = 32768
MAX_REPORT = 32768
CLEANUP_SECONDS = 20
CONTRACT_CODES = frozenset(
    {
        "invalid_json",
        "invalid_contract",
        "unsupported_version",
        "unknown_capability",
        "identity_conflict",
        "result_mismatch",
        "evidence_mismatch",
        "unsupported_facts",
        "unauthorized",
        "expired",
        "capacity",
        "unknown_attempt",
    }
)
HTTP_CODES = frozenset(
    {
        "invalid_http",
        "body_limit",
        "body_timeout",
        "request_aborted",
        "deadline_exceeded",
        "closing",
        "internal_error",
        "cleanup_incomplete",
        "invalid_response",
        "connection_failed",
        "client_closed",
        "client_capacity",
    }
)
SAFE_CODES = CONTRACT_CODES | HTTP_CODES | {"ok"}
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_ARTIFACT_FILES = 2048
PROVIDER_KINDS = frozenset(
    {
        "complete",
        "missing",
        "ambiguous",
        "adversarial",
        "timeout_held",
        "cancel_held",
        "secondary_progress",
        "close_held",
    }
)
GATE_CODES = frozenset(
    {
        "invalid_input",
        "missing_setup",
        "invalid_report",
        "invalid_proof",
        "unsafe_path",
        "invalid_environment",
        "source_changed",
        "invalid_artifact",
        "child_budget",
        "deadline_exceeded",
        "component_failed",
        "unsafe_capture",
        "cleanup_incomplete",
        "retention_failed",
        "unexpected_error",
    }
)
BASE_REQUIRED = frozenset(
    {"PATH", "LANG", "NO_COLOR", "CI", "COREPACK_HOME", "COREPACK_ENABLE_NETWORK"}
)
BASE_KEYS = BASE_REQUIRED | {
    "HOME",
    "TMPDIR",
    "LC_ALL",
    "LC_CTYPE",
    "SYSTEMROOT",
    "__CF_USER_TEXT_ENCODING",
}
RUNTIME_KEYS = frozenset({"P3_DOCUMENT_TOKEN", "P3_DOCUMENT_OTHER_TOKEN"})
FIXTURE_KEYS = frozenset({"P3_DOCUMENT_DIRECTORY", "P3_DOCUMENT_FIXTURES"})
PROOF_NAMES = (
    "document-producer.json",
    "document-contract-proof.json",
    "document-http-proof.json",
    "document-http-wires.json",
    "document-server-proof.json",
)


class GateError(RuntimeError):
    """Fixed safe code without dependency output or fixture bodies."""

    def __init__(self, code: object) -> None:
        self.code = code if type(code) is str and code in GATE_CODES else "unexpected_error"
        super().__init__("Document capability qualification did not pass")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def natural(value: object, low: int = 0, high: int = 9007199254740991) -> bool:
    return type(value) is int and low <= value <= high


def is_hash(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def exact(actual: object, expected: object) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            exact(actual[k], v) for k, v in expected.items()
        )
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(
            exact(a, b) for a, b in zip(actual, expected, strict=True)
        )
    return bool(actual == expected)


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise GateError("invalid_report")
        value[key] = child
    return value


def _number(raw: str) -> int:
    if len(raw.lstrip("-")) > 16 or raw == "-0":
        raise GateError("invalid_report")
    value = int(raw)
    if abs(value) > 9007199254740991:
        raise GateError("invalid_report")
    return value


def _float(raw: str) -> float:
    value = float(raw)
    if not math.isfinite(value):
        raise GateError("invalid_report")
    return value


def decode(raw: bytes, maximum: int = MAX_PROOF) -> dict[str, Any]:
    if (
        type(raw) is not bytes
        or not natural(maximum, 1, MAX_ARTIFACT_BYTES)
        or not 1 <= len(raw) <= maximum
    ):
        raise GateError("invalid_report")
    depth, quoted, escaped = 0, False, False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
        elif char in (91, 123):
            depth += 1
            if depth > 24:
                raise GateError("invalid_report")
        elif char in (93, 125):
            depth -= 1
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique,
            parse_int=_number,
            parse_float=_float,
            parse_constant=_bad_constant,
        )
        _unicode(value)
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise GateError("invalid_report") from None
    if type(value) is not dict:
        raise GateError("invalid_report")
    return value


def cases(names: tuple[str, ...]) -> list[dict[str, str]]:
    return [{"name": name, "status": "passed", "code": "ok"} for name in names]


def validate_reply(raw: bytes, mode: str) -> dict[str, Any]:
    if type(mode) is not str:
        raise GateError("invalid_input")
    if type(mode) is not str or mode not in {
        "node-producer",
        "node-server",
        "python-contracts",
        "python-http",
    }:
        raise GateError("invalid_input")
    value = decode(raw)
    expected: dict[str, Any] = {
        "schema_version": 1,
        "status": "passed",
        "mode": mode,
        "cleanup_complete": True,
    }
    if mode.startswith("node-"):
        expected.update(
            node_version="24.22.2",
            proof="document-producer.json"
            if mode == "node-producer"
            else "document-server-proof.json",
        )
        if mode == "node-producer":
            expected["producer_rows"] = 8
    else:
        names = CONTRACT_CASES if mode == "python-contracts" else HTTP_CASES
        expected.update(
            tests=len(names),
            passed=len(names),
            failures=0,
            errors=0,
            skipped=0,
            cases=list(names),
            proof="document-contract-proof.json"
            if mode == "python-contracts"
            else "document-http-proof.json",
        )
    if not exact(value, expected):
        raise GateError("invalid_report")
    return value


def validate_environment(value: dict[str, str], role: str) -> None:
    if (
        type(value) is not dict
        or type(role) is not str
        or role not in {"build", "node-producer", "node-server", "python-contracts", "python-http"}
    ):
        raise GateError("invalid_environment")
    extra = FIXTURE_KEYS if role != "build" else frozenset()
    if role in {"node-server", "python-http"}:
        extra |= RUNTIME_KEYS
    if (
        not BASE_REQUIRED | extra <= value.keys()
        or not value.keys() <= BASE_KEYS | extra
        or any(type(k) is not str for k in value)
    ):
        raise GateError("invalid_environment")
    if any(
        type(v) is not str or not v or any(c in v for c in ("\0", "\n", "\r"))
        for v in value.values()
    ):
        raise GateError("invalid_environment")
    if value["COREPACK_ENABLE_NETWORK"] != "0" or value["CI"] != "1" or value["NO_COLOR"] != "1":
        raise GateError("invalid_environment")
    for key in extra & FIXTURE_KEYS:
        path = Path(value[key])
        try:
            _safe_absolute(path)
            info = path.lstat()
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o700
            ):
                raise GateError("invalid_environment")
        except (OSError, GateError):
            raise GateError("invalid_environment") from None
    if role in {"node-server", "python-http"}:
        first, second = (value[key] for key in sorted(RUNTIME_KEYS))
        if first == second or any(
            re.fullmatch(r"[A-Za-z0-9_-]{43}", token) is None for token in (first, second)
        ):
            raise GateError("invalid_environment")


def private_directory(path: Path) -> None:
    try:
        _safe_absolute(path)
        missing: list[Path] = []
        current = path
        while not current.exists():
            missing.append(current)
            current = current.parent
        for current in reversed(missing):
            current.mkdir(mode=0o700)
        info = path.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise GateError("unsafe_path")
    except OSError:
        raise GateError("unsafe_path") from None


def write_private(path: Path, raw: bytes) -> None:
    if type(raw) is not bytes or len(raw) > MAX_ARTIFACT_BYTES:
        raise GateError("unsafe_path")
    private_directory(path.parent)
    try:
        with os.fdopen(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
        ) as stream:
            stream.write(raw)
    except OSError:
        raise GateError("unsafe_path") from None


def json_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise GateError("invalid_report") from None


def read_private(path: Path, maximum: int = MAX_PROOF, *, empty: bool = False) -> bytes:
    if not natural(maximum, 1, MAX_ARTIFACT_BYTES) or type(empty) is not bool:
        raise GateError("invalid_proof")
    try:
        _safe_absolute(path)
        info = path.lstat()
        _private_file(info, maximum, empty)
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
            opened = os.fstat(stream.fileno())
            _private_file(opened, maximum, empty)
            if _file_identity(opened) != _file_identity(info):
                raise GateError("invalid_proof")
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        if len(raw) != opened.st_size or _file_identity(after) != _file_identity(opened):
            raise GateError("invalid_proof")
        return raw
    except (OSError, GateError):
        raise GateError("invalid_proof") from None


def target_path(root: Path, requested: Path) -> Path:
    if (
        requested.is_absolute()
        or ".." in requested.parts
        or re.fullmatch(r"[a-zA-Z0-9_-]{1,96}\.json", requested.name) is None
    ):
        raise GateError("unsafe_path")
    base = root / ".local/validation/p3-document"
    target = root / requested
    artifacts = target.with_name(target.stem + "-artifacts")
    _safe_absolute(target)
    if target.parent != base or target.exists() or artifacts.exists() or artifacts.is_symlink():
        raise GateError("unsafe_path")
    return target


def validate_producer(raw: bytes) -> dict[str, Any]:
    value = decode(raw)
    if (
        not _keys(value, {"schema_version", "kind", "rows"})
        or not exact(value["schema_version"], 1)
        or value["kind"] != "document.producer"
        or type(value["rows"]) is not list
        or len(value["rows"]) != 8
    ):
        raise GateError("invalid_proof")
    for row, name in zip(value["rows"], CONTRACT_CASES, strict=True):
        if not _keys(row, {"label", "request_utf8", "result_utf8"}) or row["label"] != name:
            raise GateError("invalid_proof")
        for key, maximum in (("request_utf8", 16384), ("result_utf8", 8192)):
            _canonical_wire(row[key], maximum)
    return value


def validate_proof(raw: bytes, name: str) -> dict[str, Any]:
    value = decode(raw)
    common = {"schema_version", "status", "kind"}
    if (
        not common <= value.keys()
        or not exact(value["schema_version"], 1)
        or value["status"] != "passed"
    ):
        raise GateError("invalid_proof")
    if name == "document-contract-proof.json":
        if (
            value.keys()
            != common
            | {
                "case_results",
                "producer_sha256",
                "legacy_request_sha256",
                "legacy_result_sha256",
                "records",
            }
            or value["kind"] != "document.contract-proof"
            or not exact(value["case_results"], cases(CONTRACT_CASES))
            or any(
                not is_hash(value[k])
                for k in ("producer_sha256", "legacy_request_sha256", "legacy_result_sha256")
            )
        ):
            raise GateError("invalid_proof")
        if type(value["records"]) is not list or not 8 <= len(value["records"]) <= 64:
            raise GateError("invalid_proof")
        names: set[str] = set()
        for record in value["records"]:
            if (
                not _keys(
                    record,
                    {"name", "structural", "factual", "code", "request_sha256", "result_sha256"},
                )
                or not _label(record["name"])
                or record["name"] in names
                or not _enum(record["structural"], {"accepted", "rejected"})
                or not _enum(
                    record["factual"], {"correct", "incorrect", "clarification", "not_evaluated"}
                )
                or not _enum(record["code"], CONTRACT_CODES | {"ok"})
                or not is_hash(record["request_sha256"])
                or not is_hash(record["result_sha256"])
            ):
                raise GateError("invalid_proof")
            names.add(record["name"])
    elif name == "document-server-proof.json":
        expected = common | {
            "node_version",
            "provider_calls",
            "provider_records",
            "provider_active",
            "worker_records",
            "workers_active",
            "requests",
            "sockets",
            "active",
            "observerPending",
            "close_incomplete_observed",
            "closed",
        }
        if (
            value.keys() != expected
            or value["kind"] != "document.server-proof"
            or value["node_version"] != "24.22.2"
            or not exact(value["provider_calls"], 8)
            or value["close_incomplete_observed"] is not True
            or value["closed"] is not True
            or any(
                not exact(value[k], 0)
                for k in (
                    "provider_active",
                    "workers_active",
                    "requests",
                    "sockets",
                    "active",
                    "observerPending",
                )
            )
        ):
            raise GateError("invalid_proof")
        records = value["provider_records"]
        if type(records) is not list or len(records) != 8:
            raise GateError("invalid_proof")
        kinds: set[str] = set()
        attempts: set[str] = set()
        for record in records:
            if (
                not _keys(
                    record,
                    {
                        "kind",
                        "attempt_id",
                        "input_fingerprint",
                        "source_sha256",
                        "result_sha256",
                        "settled",
                    },
                )
                or not _enum(record["kind"], PROVIDER_KINDS)
                or record["kind"] in kinds
                or not _identifier(record["attempt_id"])
                or record["attempt_id"] in attempts
                or not is_hash(record["input_fingerprint"])
                or not is_hash(record["source_sha256"])
                or (record["result_sha256"] is not None and not is_hash(record["result_sha256"]))
                or record["settled"] is not True
            ):
                raise GateError("invalid_proof")
            if (
                record["kind"]
                in {"complete", "missing", "ambiguous", "adversarial", "secondary_progress"}
                and record["result_sha256"] is None
            ):
                raise GateError("invalid_proof")
            kinds.add(record["kind"])
            attempts.add(record["attempt_id"])
        if (
            kinds != PROVIDER_KINDS
            or type(value["worker_records"]) is not list
            or not 9 <= len(value["worker_records"]) <= 64
        ):
            raise GateError("invalid_proof")
        ids: set[int] = set()
        normal = 0
        for record in value["worker_records"]:
            if (
                not _keys(record, {"thread_id", "exit_code", "normal_result"})
                or not natural(record["thread_id"], 1)
                or record["thread_id"] in ids
                or not natural(record["exit_code"], 0, 255)
                or type(record["normal_result"]) is not bool
                or (record["normal_result"] and record["exit_code"] != 0)
            ):
                raise GateError("invalid_proof")
            ids.add(record["thread_id"])
            normal += int(record["normal_result"])
        if normal < 9:
            raise GateError("invalid_proof")
    else:
        raise GateError("invalid_input")
    return value


def validate_http_proof(raw: bytes) -> dict[str, Any]:
    value = decode(raw)
    keys = {
        "schema_version",
        "status",
        "kind",
        "case_results",
        "records",
        "provider_calls",
        "other_principal_progress",
        "close_incomplete_observed",
        "client_active",
        "wires",
        "expiry",
    }
    if (
        value.keys() != keys
        or not exact(value["schema_version"], 1)
        or value["status"] != "passed"
        or value["kind"] != "document.http-proof"
        or not exact(value["case_results"], cases(HTTP_CASES))
        or not exact(value["provider_calls"], 8)
        or value["other_principal_progress"] is not True
        or value["close_incomplete_observed"] is not True
        or not exact(value["client_active"], 0)
    ):
        raise GateError("invalid_proof")
    records = value["records"]
    if type(records) is not list or len(records) != 12:
        raise GateError("invalid_proof")
    for record, name in zip(records, HTTP_CASES, strict=True):
        if (
            type(record) is not dict
            or record.keys()
            != {
                "name",
                "requests",
                "validated_results",
                "expected_rejections",
                "code",
                "source_sha256",
                "request_sha256",
                "result_sha256",
            }
            or record["name"] != name
            or any(
                not natural(record[k], 0, 32)
                for k in ("requests", "validated_results", "expected_rejections")
            )
            or not _enum(record["code"], SAFE_CODES)
            or not is_hash(record["source_sha256"])
            or not is_hash(record["request_sha256"])
            or (record["result_sha256"] is not None and not is_hash(record["result_sha256"]))
        ):
            raise GateError("invalid_proof")
        if (
            record["requests"] < 1
            or record["validated_results"] + record["expected_rejections"] > record["requests"]
        ):
            raise GateError("invalid_proof")
    for record in records[:4]:
        if record["validated_results"] < 1 or record["result_sha256"] is None:
            raise GateError("invalid_proof")
    for record in records[4:10]:
        if record["expected_rejections"] < 1:
            raise GateError("invalid_proof")
    wires = value["wires"]
    if (
        type(wires) is not dict
        or wires.keys() != {"path", "bytes", "sha256"}
        or wires["path"] != "document-http-wires.json"
        or not natural(wires["bytes"], 1, MAX_PROOF)
        or not is_hash(wires["sha256"])
    ):
        raise GateError("invalid_proof")
    expiry = value["expiry"]
    if (
        type(expiry) is not dict
        or expiry.keys()
        != {
            "before_start_denied",
            "post_decode_denied",
            "post_decode_worker_exit",
            "deadline_at_ms",
            "denial_observed_at_ms",
            "secondary_progress_observed_at_ms",
            "secondary_attempt_id",
            "input_fingerprint",
        }
        or expiry["before_start_denied"] is not True
        or expiry["post_decode_denied"] is not True
        or not exact(expiry["post_decode_worker_exit"], 0)
        or any(
            not natural(expiry[k], 1, 4102444800000)
            for k in (
                "deadline_at_ms",
                "denial_observed_at_ms",
                "secondary_progress_observed_at_ms",
            )
        )
        or not expiry["deadline_at_ms"]
        <= expiry["denial_observed_at_ms"]
        < expiry["secondary_progress_observed_at_ms"]
        or type(expiry["secondary_attempt_id"]) is not str
        or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", expiry["secondary_attempt_id"]) is None
        or not is_hash(expiry["input_fingerprint"])
    ):
        raise GateError("invalid_proof")
    return value


def canonical(raw: object) -> bytes:
    try:
        return json.dumps(
            raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise GateError("invalid_proof") from None


def factual_match(request: dict[str, Any], result: dict[str, Any], oracle: dict[str, Any]) -> bool:
    """Independent literal-fixture check only, never a general image truth oracle."""
    try:
        refs = request["evidence"]
        if type(refs) is not list or len(refs) != 1:
            return False
        source = refs[0]
        expected = next(
            item for item in oracle["fixtures"].values() if exact(item["source"], source)
        )
        if result["outcome"] != expected["outcome"] or result["fields"].keys() != set(FIELDS):
            return False
        for name in FIELDS:
            field, truth = result["fields"][name], expected["fields"][name]
            if (
                field.keys() != {"state", "value", "evidence_refs"}
                or field["state"] != truth["state"]
                or not exact(field["value"], truth["value"])
            ):
                return False
            witnesses = [
                {
                    "source_id": source["source_id"],
                    "version": source["version"],
                    "sha256": source["sha256"],
                    "region": region,
                }
                for region in truth["regions"]
            ]
            if not exact(field["evidence_refs"], witnesses):
                return False
        return True
    except (KeyError, TypeError, AttributeError, StopIteration, ValueError):
        return False


def match_wire(
    row: dict[str, Any],
    oracle: dict[str, Any],
    *,
    expected_fixture: str | None = None,
    secondary: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not _keys(row, {"name", "request_utf8", "result_utf8"}) or not _label(row["name"]):
        raise GateError("invalid_proof")
    request = _canonical_wire(row["request_utf8"], 16384)
    result = _canonical_wire(row["result_utf8"], 8192)
    _document_shape(request, result)
    fingerprint = digest(
        canonical({k: v for k, v in request.items() if k not in {"attempt", "input_fingerprint"}})
    )
    if fingerprint != request["input_fingerprint"]:
        raise GateError("invalid_proof")
    for key in ("scope", "delegation_id", "case_id", "request_revision", "input_fingerprint"):
        if not exact(request[key], result[key]):
            raise GateError("invalid_proof")
    if request["attempt"]["attempt_id"] != result["attempt_id"] or not factual_match(
        request, result, oracle
    ):
        raise GateError("invalid_proof")
    if expected_fixture is not None:
        expected = oracle["fixtures"].get(expected_fixture)
        if type(expected) is not dict or not exact(request["evidence"], [expected["source"]]):
            raise GateError("invalid_proof")
        account = "account_document_other" if secondary else "account_document"
        case = "case_document_other" if secondary else "case_document"
        conversation = "conversation_document_other" if secondary else "conversation_document"
        if (
            not exact(request["scope"], {"tenant_id": "tenant_document", "account_id": account})
            or request["case_id"] != case
            or not exact(request["result_route"], {"conversation_id": conversation})
        ):
            raise GateError("invalid_proof")
    return request, result


def validate_bundle(
    proofs: dict[str, bytes], oracle: dict[str, Any], *, phase: dict[str, Any] | None = None
) -> dict[str, Any]:
    if type(proofs) is not dict or set(proofs) != set(PROOF_NAMES):
        raise GateError("invalid_proof")
    validate_oracle(oracle)
    producer = validate_producer(proofs["document-producer.json"])
    contracts = validate_proof(
        proofs["document-contract-proof.json"], "document-contract-proof.json"
    )
    http = validate_http_proof(proofs["document-http-proof.json"])
    server = validate_proof(proofs["document-server-proof.json"], "document-server-proof.json")
    if digest(proofs["document-producer.json"]) != contracts["producer_sha256"]:
        raise GateError("invalid_proof")
    legacy = producer["rows"][1]
    if (
        digest(legacy["request_utf8"].encode())
        != "592984b5294543b2706bcae53a0ea4261a36e35ba3cebdc6a864b0917c9d9e1c"
        or digest(legacy["result_utf8"].encode())
        != "e25de12da8887602473a47d10fb93e0845bafdfb67e2eaa2ac877ae4ee5209a5"
    ):
        raise GateError("invalid_proof")
    if (
        digest(legacy["request_utf8"].encode()) != contracts["legacy_request_sha256"]
        or digest(legacy["result_utf8"].encode()) != contracts["legacy_result_sha256"]
    ):
        raise GateError("invalid_proof")
    fixed = {row["label"]: row for row in producer["rows"]}
    record_map = {record["name"]: record for record in contracts["records"]}
    if not set(CONTRACT_CASES) <= record_map.keys() or len(record_map) != len(contracts["records"]):
        raise GateError("invalid_proof")
    for name, row in fixed.items():
        record = record_map[name]
        if record["request_sha256"] != digest(row["request_utf8"].encode()) or record[
            "result_sha256"
        ] != digest(row["result_utf8"].encode()):
            raise GateError("invalid_proof")
    for name in CONTRACT_CASES[3:5]:
        record = record_map[name]
        request = _canonical_wire(fixed[name]["request_utf8"], 16384)
        result = _canonical_wire(fixed[name]["result_utf8"], 8192)
        _document_shape(request, result)
        if (
            record["structural"] != "accepted"
            or record["factual"] != "incorrect"
            or record["code"] != "unsupported_facts"
            or factual_match(request, result, oracle)
        ):
            raise GateError("invalid_proof")
    wire_raw = proofs["document-http-wires.json"]
    if http["wires"]["sha256"] != digest(wire_raw) or http["wires"]["bytes"] != len(wire_raw):
        raise GateError("invalid_proof")
    wires = decode(wire_raw)
    names = (*HTTP_CASES[:4], "secondary_progress")
    if (
        wires.keys() != {"schema_version", "kind", "records"}
        or not exact(wires["schema_version"], 1)
        or wires["kind"] != "document.http-canonical-wires"
        or type(wires["records"]) is not list
        or len(wires["records"]) != 5
        or [r.get("name") for r in wires["records"] if type(r) is dict] != list(names)
    ):
        raise GateError("invalid_proof")
    provider_records = server["provider_records"]
    by_kind = {record["kind"]: record for record in provider_records}
    sources = {item["source"]["sha256"] for item in oracle["fixtures"].values()}
    if any(record["source_sha256"] not in sources for record in provider_records):
        raise GateError("invalid_proof")
    if phase is not None:
        validate_phase(phase)
        if phase["deadline_at_ms"] != http["expiry"]["deadline_at_ms"] or any(
            record["attempt_id"] == phase["attempt_id"]
            or record["input_fingerprint"] == phase["input_fingerprint"]
            for record in provider_records
        ):
            raise GateError("invalid_proof")
    for index, row in enumerate(wires["records"]):
        request, result = match_wire(
            row,
            oracle,
            expected_fixture=("complete", "missing", "ambiguous", "adversarial", "complete")[index],
            secondary=index == 4,
        )
        provider = by_kind[
            ("complete", "missing", "ambiguous", "adversarial", "secondary_progress")[index]
        ]
        if (
            provider["attempt_id"] != result["attempt_id"]
            or provider["input_fingerprint"] != result["input_fingerprint"]
            or provider["source_sha256"] != request["evidence"][0]["sha256"]
            or provider["result_sha256"] != digest(row["result_utf8"].encode())
        ):
            raise GateError("invalid_proof")
        if index < 4:
            record = http["records"][index]
            if (
                record["request_sha256"] != digest(row["request_utf8"].encode())
                or record["result_sha256"] != digest(row["result_utf8"].encode())
                or record["source_sha256"] != provider["source_sha256"]
            ):
                raise GateError("invalid_proof")
        else:
            expiry = http["expiry"]
            if (
                expiry["secondary_attempt_id"] != result["attempt_id"]
                or expiry["input_fingerprint"] != result["input_fingerprint"]
            ):
                raise GateError("invalid_proof")
    return {
        "provider_calls": 8,
        "canonical_http_results": 5,
        "contract_rows": 8,
        "worker_records": len(server["worker_records"]),
        "expired_before_and_after_decode": True,
    }


def _bad_constant(value: str) -> Any:
    raise GateError("invalid_report")


def _unicode(value: object) -> None:
    if isinstance(value, str):
        value.encode("utf-8")
    elif isinstance(value, dict):
        for key, child in value.items():
            _unicode(key)
            _unicode(child)
    elif isinstance(value, list):
        for child in value:
            _unicode(child)


def _keys(value: object, keys: set[str]) -> TypeGuard[dict[str, Any]]:
    return type(value) is dict and value.keys() == keys


def _enum(value: object, allowed: set[str] | frozenset[str]) -> bool:
    return type(value) is str and value in allowed


def _identifier(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value) is not None


def _label(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[a-zA-Z0-9_]{1,160}", value) is not None


def _text(value: object, maximum: int, *, nonempty: bool = False) -> bool:
    try:
        return (
            type(value) is str
            and len(value.encode("utf-8")) <= maximum
            and (not nonempty or bool(value.strip()))
        )
    except UnicodeError:
        return False


def _safe_absolute(path: Path) -> None:
    if not isinstance(path, Path):
        raise GateError("unsafe_path")
    if (
        not path.is_absolute()
        or ".." in path.parts
        or path.resolve() != path
        or any(p.is_symlink() for p in (path, *path.parents))
    ):
        raise GateError("unsafe_path")


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_ino, info.st_dev, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _private_file(info: os.stat_result, maximum: int, empty: bool) -> None:
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
        or not (0 if empty else 1) <= info.st_size <= maximum
    ):
        raise GateError("invalid_proof")


def _canonical_wire(value: object, maximum: int) -> dict[str, Any]:
    if type(value) is not str:
        raise GateError("invalid_proof")
    try:
        raw = value.encode("utf-8")
    except UnicodeError:
        raise GateError("invalid_proof") from None
    decoded = decode(raw, maximum)
    if canonical(decoded) != raw:
        raise GateError("invalid_proof")
    return decoded


def _source(source: object) -> bool:
    if not _keys(
        source, {"source_id", "version", "sha256", "media_type", "byte_length", "width", "height"}
    ):
        return False
    return (
        _identifier(source["source_id"])
        and _identifier(source["version"])
        and is_hash(source["sha256"])
        and source["media_type"] == "image/png"
        and natural(source["byte_length"], 1, 2097152)
        and natural(source["width"], 1, 2048)
        and natural(source["height"], 1, 2048)
    )


def _region(region: object, width: int, height: int) -> bool:
    return (
        _keys(region, {"x", "y", "width", "height"})
        and natural(region["x"], 0, width - 1)
        and natural(region["y"], 0, height - 1)
        and natural(region["width"], 1, width)
        and natural(region["height"], 1, height)
        and region["x"] + region["width"] <= width
        and region["y"] + region["height"] <= height
    )


def _calendar(value: object) -> bool:
    if type(value) is not str or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        return False
    try:
        return 1970 <= date.fromisoformat(value).year <= 2100
    except ValueError:
        return False


def _field_shape(
    field: object, name: str, source: dict[str, Any], *, literal: bool = False
) -> bool:
    refs_key = "regions" if literal else "evidence_refs"
    if (
        not _keys(field, {"state", "value", refs_key})
        or not _enum(field["state"], {"known", "missing", "ambiguous"})
        or type(field[refs_key]) is not list
    ):
        return False
    state, value, refs = field["state"], field["value"], field[refs_key]
    if state == "known":
        if (
            not _text(value, 128, nonempty=True)
            or not 1 <= len(refs) <= 2
            or (name in {"check_in", "check_out"} and not _calendar(value))
        ):
            return False
    elif value is not None or len(refs) != (0 if state == "missing" else 2):
        return False
    distinct: set[bytes] = set()
    for ref in refs:
        if literal:
            region = ref
        else:
            if not _keys(ref, {"source_id", "version", "sha256", "region"}) or not all(
                exact(ref[key], source[key]) for key in ("source_id", "version", "sha256")
            ):
                return False
            region = ref["region"]
        if not _region(region, source["width"], source["height"]):
            return False
        encoded = canonical(region)
        if encoded in distinct:
            return False
        distinct.add(encoded)
    return True


def validate_oracle(oracle: dict[str, Any]) -> None:
    if (
        not _keys(oracle, {"schema_version", "reviewed_at", "scope", "pixel_codec", "fixtures"})
        or not exact(oracle["schema_version"], 1)
        or not _text(oracle["scope"], 2048, nonempty=True)
        or not _text(oracle["pixel_codec"], 1024, nonempty=True)
        or not _calendar(oracle["reviewed_at"])
        or not _keys(
            oracle["fixtures"], {"complete", "missing", "ambiguous", "adversarial", "other-source"}
        )
    ):
        raise GateError("invalid_proof")
    sources: set[str] = set()
    hashes: set[str] = set()
    for name, row in oracle["fixtures"].items():
        if (
            not _keys(row, {"file", "source", "channels", "pixel_sha256", "outcome", "fields"})
            or row["file"] != name + ".png"
            or not _source(row["source"])
            or type(row["channels"]) is not int
            or row["channels"] not in {3, 4}
            or not is_hash(row["pixel_sha256"])
            or not _keys(row["fields"], set(FIELDS))
        ):
            raise GateError("invalid_proof")
        source = row["source"]
        if source["source_id"] in sources or source["sha256"] in hashes:
            raise GateError("invalid_proof")
        sources.add(source["source_id"])
        hashes.add(source["sha256"])
        for field in FIELDS:
            if not _field_shape(row["fields"][field], field, source, literal=True):
                raise GateError("invalid_proof")
        _outcome(row)


def _outcome(value: dict[str, Any]) -> None:
    known = all(value["fields"][name]["state"] == "known" for name in FIELDS)
    if value["outcome"] != ("extracted" if known else "clarification_required"):
        raise GateError("invalid_proof")
    arrival, departure = (value["fields"][key] for key in ("check_in", "check_out"))
    if (
        arrival["state"] == departure["state"] == "known"
        and not arrival["value"] < departure["value"]
    ):
        raise GateError("invalid_proof")


def _document_shape(request: dict[str, Any], result: dict[str, Any]) -> None:
    request_keys = {
        "schema_version",
        "kind",
        "capability",
        "input_schema_version",
        "scope",
        "delegation_id",
        "case_id",
        "request_revision",
        "context_snapshot",
        "evidence",
        "deadline_at_ms",
        "result_route",
        "attempt",
        "input_fingerprint",
    }
    result_keys = {
        "schema_version",
        "kind",
        "capability",
        "result_schema_version",
        "scope",
        "delegation_id",
        "case_id",
        "request_revision",
        "attempt_id",
        "input_fingerprint",
        "outcome",
        "fields",
        "producer",
        "completed_at_ms",
    }
    if not _keys(request, request_keys) or not _keys(result, result_keys):
        raise GateError("invalid_proof")
    for item, kind, version in (
        (request, "delegation.request", "input_schema_version"),
        (result, "delegation.result", "result_schema_version"),
    ):
        if (
            not exact(item["schema_version"], 1)
            or not exact(item[version], 1)
            or item["kind"] != kind
            or item["capability"] != "booking.extract_document"
            or not _keys(item["scope"], {"tenant_id", "account_id"})
            or not all(_identifier(x) for x in item["scope"].values())
            or not _identifier(item["delegation_id"])
            or not _identifier(item["case_id"])
            or not natural(item["request_revision"], 1, 1000000)
            or not is_hash(item["input_fingerprint"])
        ):
            raise GateError("invalid_proof")
    context = request["context_snapshot"]
    if (
        not _keys(context, {"document_kind", "document_source_id", "requested_fields", "note"})
        or context["document_kind"] != "booking_confirmation_v1"
        or not exact(context["requested_fields"], list(FIELDS))
        or not _identifier(context["document_source_id"])
        or not _text(context["note"], 1024)
        or type(request["evidence"]) is not list
        or len(request["evidence"]) != 1
        or not _source(request["evidence"][0])
    ):
        raise GateError("invalid_proof")
    source = request["evidence"][0]
    if (
        context["document_source_id"] != source["source_id"]
        or not natural(request["deadline_at_ms"], 1, 4102444800000)
        or not _keys(request["result_route"], {"conversation_id"})
        or not _identifier(request["result_route"]["conversation_id"])
        or not _keys(request["attempt"], {"attempt_id", "number"})
        or not _identifier(request["attempt"]["attempt_id"])
        or not natural(request["attempt"]["number"], 1, 1000)
    ):
        raise GateError("invalid_proof")
    if (
        not _identifier(result["attempt_id"])
        or not natural(result["completed_at_ms"], 0, 4102444800000)
        or not _keys(result["fields"], set(FIELDS))
    ):
        raise GateError("invalid_proof")
    producer = result["producer"]
    if (
        not _keys(producer, {"producer_id", "model_id", "model_version", "config_fingerprint"})
        or producer["producer_id"] != "scripted_document_fixture_v1"
        or producer["model_id"] is not None
        or producer["model_version"] is not None
        or not is_hash(producer["config_fingerprint"])
    ):
        raise GateError("invalid_proof")
    for name in FIELDS:
        if not _field_shape(result["fields"][name], name, source):
            raise GateError("invalid_proof")
    _outcome(result)


def validate_phase(value: dict[str, Any]) -> dict[str, Any]:
    if (
        not _keys(
            value,
            {
                "schema_version",
                "kind",
                "node_pid",
                "attempt_id",
                "input_fingerprint",
                "deadline_at_ms",
                "worker_exit_code",
            },
        )
        or not exact(value["schema_version"], 1)
        or value["kind"] != "document.post-decode-held"
        or not natural(value["node_pid"], 1)
        or not _identifier(value["attempt_id"])
        or not is_hash(value["input_fingerprint"])
        or not natural(value["deadline_at_ms"], 1, 4102444800000)
        or not exact(value["worker_exit_code"], 0)
    ):
        raise GateError("invalid_proof")
    return value


def validate_manifest(directory: Path, raw: bytes) -> dict[str, Any]:
    """Exact physical private inventory; exclude only its own root filename."""
    manifest = decode(raw, MAX_ARTIFACT_BYTES)
    if (
        not _keys(manifest, {"schema_version", "files"})
        or not exact(manifest["schema_version"], 1)
        or type(manifest["files"]) is not dict
        or not 1 <= len(manifest["files"]) <= MAX_ARTIFACT_FILES
    ):
        raise GateError("invalid_proof")
    records = manifest["files"]
    for name, item in records.items():
        rel = PurePosixPath(name)
        if (
            not name
            or rel.is_absolute()
            or rel.as_posix() != name
            or ".." in rel.parts
            or "\\" in name
            or name == "retained-index.json"
            or any(
                part in {".git", ".venv", "node_modules", "__pycache__"}
                or part.startswith((".env", ".secrets"))
                for part in rel.parts
            )
            or rel.suffix in {".pem", ".key", ".crt"}
            or not _keys(item, {"bytes", "sha256"})
            or not natural(item["bytes"], 0, MAX_ARTIFACT_BYTES)
            or not is_hash(item["sha256"])
        ):
            raise GateError("invalid_proof")
    try:
        _safe_absolute(directory)
        todo = [directory]
        seen: set[str] = set()
        visited = total = 0
        while todo:
            folder = todo.pop()
            info = folder.lstat()
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o700
            ):
                raise GateError("invalid_proof")
            with os.scandir(folder) as entries:
                for entry in entries:
                    visited += 1
                    if visited > 4096:
                        raise GateError("invalid_proof")
                    path = Path(entry.path)
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        todo.append(path)
                    elif stat.S_ISREG(info.st_mode):
                        name = path.relative_to(directory).as_posix()
                        body = read_private(path, MAX_ARTIFACT_BYTES, empty=True)
                        if name == "retained-index.json":
                            if body != raw:
                                raise GateError("invalid_proof")
                            continue
                        total += len(body)
                        if (
                            total > MAX_ARTIFACT_BYTES
                            or name not in records
                            or records[name] != {"bytes": len(body), "sha256": digest(body)}
                        ):
                            raise GateError("invalid_proof")
                        seen.add(name)
                    else:
                        raise GateError("invalid_proof")
        if seen != records.keys() or not (directory / "retained-index.json").is_file():
            raise GateError("invalid_proof")
    except (OSError, GateError):
        raise GateError("invalid_proof") from None
    return manifest
