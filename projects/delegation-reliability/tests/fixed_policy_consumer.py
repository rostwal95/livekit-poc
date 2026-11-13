"""Unadapted public policy-v2 consumers; all sources and holds are explicit setup."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib.util
import io
import json
import os
import re
import stat
import sys
import time
import unittest
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, TypedDict

from delegation_reliability.contracts import (
    ERROR_CODES,
    ContractError,
    canonical,
    encode_request,
    encode_result,
    parse_error,
    parse_request,
    parse_result,
)
from delegation_reliability.document import DocumentSpecialistClient
from delegation_reliability.document_contracts import (
    DocumentRequest,
    encode_document_request,
    encode_document_result,
    parse_document_request,
    parse_document_result,
    produce_document_request,
)
from delegation_reliability.fixed_policy import (
    FixedPolicySpecialistClient,
    snapshot_fixed_policy_records,
    verify_fixed_policy_facts,
)
from delegation_reliability.fixed_policy_contracts import (
    FixedPolicyRequest,
    FixedPolicyResult,
    encode_fixed_policy_request,
    encode_fixed_policy_result,
    match_fixed_policy_result,
    parse_fixed_policy_request,
    parse_fixed_policy_result,
    produce_fixed_policy_request,
)
from delegation_reliability.http_client import SpecialistEndpoint, SpecialistHttpError
from delegation_reliability.security import EvidenceRecord

CONTRACT_CASES = (
    "legacy_policy_v1_canonical_defaults_and_document_v1_unchanged",
    "v2_request_canonical_fingerprint_and_nested_snapshot",
    "v2_result_strict_states_witness_bounds_and_safe_provenance",
    "actual_TypeScript_producer_Python_consumer_parity",
    "identity_scope_revision_attempt_fingerprint_source_binding_rejection",
    "schema_valid_wrong_decision_rule_threshold_or_fact_fails_factual_verifier",
    "missing_agreeing_conflicting_exact_fact_witness_semantics",
    "expired_result_still_rejects_forged_facts_before_timeliness",
)
HTTP_CASES = (
    "actual_HTTP_eligible_ineligible_and_threshold_useful_results",
    "actual_HTTP_missing_and_conflicting_clarification_without_invention",
    "actual_HTTP_policy_and_fact_prompt_text_is_inert",
    "actual_HTTP_adversarial_PNG_document_path_remains_grounded",
    "invoke_result_cancel_evidence_permissions_wrong_scope_zero_evaluation",
    "unknown_source_digest_version_URL_and_swapped_facts_rejected",
    "unsupported_policy_version_rule_threshold_or_malformed_source_rejected",
    "expired_before_start_and_after_held_validation_zero_new_evaluation_then_progress",
    "shared_global_per_principal_attempt_caps_and_other_principal_progress",
    "cancel_timeout_abandonment_retains_actual_held_work_and_truthful_status",
    "close_incomplete_retains_owners_retry_observes_actual_settlement",
    "configured_public_examples_strict_types_exact_wire_proofs_and_zero_owned_occupancy",
)
PRODUCER_NAMES = (
    "eligible",
    "ineligible",
    "threshold",
    "missing",
    "conflicting",
    "adversarial",
    "wrong_rule",
    "wrong_fact",
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
STAGES = frozenset(
    {
        "setup",
        "codec",
        "oracle",
        "snapshot",
        "HTTP_positive",
        "HTTP_negative",
        "expiry",
        "capacity",
        "cancel",
        "close",
        "proof",
    }
)


STAGES = STAGES | frozenset(
    (
        "capacity_wait_timeout",
        "capacity_wait_cancel",
        "secondary_start",
        "secondary_wait",
        "secondary_result",
        "negative_bad_token",
        "negative_no_invoke_permission",
        "negative_no_result_permission",
        "negative_no_cancel_permission",
        "negative_no_evidence_permission",
        "negative_foreign_scope",
        "negative_unknown_source",
        "negative_wrong_source_digest",
        "negative_wrong_source_version",
        "negative_URL_source",
        "negative_expired_start",
        "negative_capacity_primary",
        "negative_duplicate_attempt",
        "negative_changed_fingerprint",
        "negative_wrong_status_identity",
        "negative_wrong_cancel_identity",
        "negative_global_capacity",
    )
)


class MetricRow(TypedDict):
    name: str
    values: dict[str, int]


MODE = sys.argv[1] if len(sys.argv) == 2 else "invalid"
DIRECTORY = Path("/")
INPUTS = Path("/")
ROOT = Path(__file__).resolve().parents[3]
STAGE = "setup"
CLEANUP = True
EXPECTATION: dict[str, str | None] | None = None


def read(path: Path, maximum: int = 32768) -> bytes:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != 0o600
        or not 1 <= info.st_size <= maximum
    ):
        raise ValueError("unsafe_input")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        actual = os.fstat(stream.fileno())
        if (actual.st_dev, actual.st_ino, actual.st_size) != (
            info.st_dev,
            info.st_ino,
            info.st_size,
        ):
            raise ValueError("unsafe_input")
        raw = stream.read(maximum + 1)
    if len(raw) != info.st_size:
        raise ValueError("unsafe_input")
    return raw


def input_json(name: str) -> dict[str, Any]:
    value = json.loads(read(INPUTS / name, 65536 if name == "v1.json" else 32768))
    if type(value) is not dict:
        raise ValueError("invalid_fixture")
    return value


def publish(path: Path, raw: bytes) -> None:
    if path.parent != DIRECTORY or not 0 < len(raw) <= 32768 or path.exists() or path.is_symlink():
        raise ValueError("unsafe_output")
    pending = path.with_name(
        path.name + (f".{os.getpid()}.pending" if path.name.endswith(".reached") else ".publishing")
    )
    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(pending, path, follow_symlinks=False)
    pending.unlink()


def save(name: str, value: object) -> bytes:
    raw = (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode()
    publish(DIRECTORY / name, raw)
    return raw


def marker(name: str) -> None:
    publish(DIRECTORY / (name + ".reached"), f"{os.getpid()}\n".encode())


def setup() -> None:
    global DIRECTORY, INPUTS
    keys = {
        "PATH",
        "LANG",
        "CI",
        "NO_COLOR",
        "COREPACK_HOME",
        "COREPACK_ENABLE_NETWORK",
        "__CF_USER_TEXT_ENCODING",
        "P3_FIXED_POLICY_DIRECTORY",
        "P3_FIXED_POLICY_INPUTS",
    }
    if MODE == "http":
        keys.add("P3_FIXED_POLICY_TOKENS")
    if MODE not in {"codec", "http"} or set(os.environ) - keys:
        raise ValueError("invalid_environment")
    for name in ("P3_FIXED_POLICY_DIRECTORY", "P3_FIXED_POLICY_INPUTS"):
        raw = os.environ[name]
        path = Path(raw)
        info = path.lstat()
        if (
            not path.is_absolute()
            or str(path.resolve()) != raw
            or not stat.S_ISDIR(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o700
            or info.st_uid != os.getuid()
        ):
            raise ValueError("unsafe_directory")
        if name.endswith("DIRECTORY"):
            DIRECTORY = path
        else:
            INPUTS = path


def records_for(
    request: FixedPolicyRequest, enrollment: dict[str, Any]
) -> tuple[EvidenceRecord, ...]:
    output = []
    for ref in request.evidence:
        rows = [
            r
            for r in enrollment["records"]
            if r["scope"]
            == {"tenant_id": request.scope.tenant_id, "account_id": request.scope.account_id}
            and r["reference"]
            == {
                "source_id": ref.source_id,
                "version": ref.version,
                "sha256": ref.sha256,
                "media_type": ref.media_type,
                "byte_length": ref.byte_length,
                "width": ref.width,
                "height": ref.height,
            }
        ]
        if len(rows) != 1 or "body_utf8" not in rows[0]:
            raise ValueError("invalid_fixture")
        output.append(EvidenceRecord(request.scope, ref, rows[0]["body_utf8"].encode()))
    return snapshot_fixed_policy_records(tuple(output))


def safe_code(error: BaseException) -> str:
    if isinstance(error, ContractError) and error.code in ERROR_CODES:
        return error.code
    if isinstance(error, SpecialistHttpError) and error.code in HTTP_CODES:
        return error.code
    return "fixture_failed"


async def codec() -> dict[str, Any]:
    global STAGE
    STAGE = "codec"
    fixed, legacy, document, enrollment = (
        input_json(n)
        for n in ("fixed-policy-v2.json", "v1.json", "document-v1.json", "enrollment.json")
    )
    proof_raw = read(DIRECTORY / "fixed-policy-contract-proof.json")
    proof = json.loads(proof_raw)
    if [r["name"] for r in proof["rows"]] != list(PRODUCER_NAMES):
        raise ValueError("invalid_proof")
    for row in proof["rows"]:
        request = parse_fixed_policy_request(row["request_utf8"].encode())
        result = parse_fixed_policy_result(row["result_utf8"].encode())
        assert encode_fixed_policy_request(request).decode() == row["request_utf8"]
        assert encode_fixed_policy_result(result).decode() == row["result_utf8"]
        assert match_fixed_policy_result(
            request, result, observed_at_ms=fixed["observed_at_ms"]
        ) in {"candidate", "clarification"}
        observed = ""
        try:
            observed = verify_fixed_policy_facts(
                request,
                result,
                records_for(request, enrollment),
                observed_at_ms=fixed["observed_at_ms"],
            )
        except ContractError as error:
            if row["name"] not in {"wrong_rule", "wrong_fact"} or error.code != "unsupported_facts":
                raise
            observed = error.code
        assert observed == row["semantic_verdict"]
    assert (
        encode_request(parse_request(legacy["request_canonical"].encode())).decode()
        == legacy["request_canonical"]
    )
    assert (
        encode_result(parse_result(legacy["result_canonical"].encode())).decode()
        == legacy["result_canonical"]
    )
    assert (
        encode_document_request(
            parse_document_request(document["canonical"]["request_utf8"].encode())
        ).decode()
        == document["canonical"]["request_utf8"]
    )
    assert (
        encode_document_result(
            parse_document_result(document["canonical"]["result_utf8"].encode())
        ).decode()
        == document["canonical"]["result_utf8"]
    )
    assert (
        encode_fixed_policy_request(
            produce_fixed_policy_request(copy.deepcopy(fixed["producer_input"]))
        ).decode()
        == fixed["request_canonical"]
    )
    request, result = (
        parse_fixed_policy_request(fixed["request_canonical"].encode()),
        parse_fixed_policy_result(fixed["result_canonical"].encode()),
    )
    negative = []
    mutations: list[tuple[str, str, Callable[[dict[str, Any]], object], str]] = [
        (
            "input_version",
            "request",
            lambda v: v.update(input_schema_version=3),
            "unsupported_version",
        ),
        (
            "request_extra",
            "request",
            lambda v: v.update(invented_override=True),
            "invalid_contract",
        ),
        ("request_no_evidence", "request", lambda v: v.update(evidence=[]), "invalid_contract"),
        ("result_extra", "result", lambda v: v.update(invented_override=True), "invalid_contract"),
        ("missing_nullability", "result", lambda v: v.update(eligible=None), "invalid_contract"),
        (
            "duplicate_fact",
            "result",
            lambda v: v["fact_refs"].append(copy.deepcopy(v["fact_refs"][0])),
            "invalid_contract",
        ),
        (
            "wrong_scope",
            "match",
            lambda v: v["scope"].update(account_id="foreign_account"),
            "result_mismatch",
        ),
        (
            "wrong_evidence",
            "match",
            lambda v: v["fact_refs"][0].update(sha256="0" * 64),
            "evidence_mismatch",
        ),
    ]
    for name, phase, mutate, code in mutations:
        value = copy.deepcopy(fixed["request"] if phase == "request" else fixed["result"])
        mutate(value)
        raw = canonical(value)
        caught = ""
        try:
            if phase == "request":
                parse_fixed_policy_request(raw)
            elif phase == "result":
                parse_fixed_policy_result(raw)
            else:
                match_fixed_policy_result(
                    request, parse_fixed_policy_result(raw), observed_at_ms=fixed["observed_at_ms"]
                )
        except ContractError as error:
            caught = error.code
        assert caught == code
        negative.append({"name": name, "phase": phase, "raw_utf8": raw.decode(), "code": caught})
    STAGE = "oracle"
    spec = importlib.util.spec_from_file_location(
        "fixed_policy_independent_oracle", ROOT / "tests/test_p3_fixed_policy_oracle.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    tested = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    assert tested.testsRun == 14 and tested.wasSuccessful() and not tested.skipped
    STAGE = "snapshot"
    spec = importlib.util.spec_from_file_location(
        "fixed_policy_public_example",
        ROOT / "projects/delegation-reliability/examples/fixed_policy_evaluation.py",
    )
    assert spec is not None and spec.loader is not None
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)
    original = records_for(request, enrollment)

    class ExplicitPort:
        async def invoke(self, supplied: FixedPolicyRequest) -> FixedPolicyResult:
            object.__setattr__(original[0], "body", b"{}")
            assert supplied.input_fingerprint == request.input_fingerprint
            return result

    assert encode_fixed_policy_result(
        await example.evaluate_fixed_policy(
            client=ExplicitPort(), request=request, records=original
        )
    ) == encode_fixed_policy_result(result)
    for name in ("authorize", "deliver", "mutate", "send", "accept"):
        assert not hasattr(FixedPolicySpecialistClient, name)
    saved = {
        "schema_version": 1,
        "kind": "fixed-policy.codec-proof",
        "producer_sha256": hashlib.sha256(proof_raw).hexdigest(),
        "oracle_tests": 14,
        "negative_records": negative,
        "snapshot_verified": True,
        "legacy_request_sha256": hashlib.sha256(legacy["request_canonical"].encode()).hexdigest(),
        "legacy_result_sha256": hashlib.sha256(legacy["result_canonical"].encode()).hexdigest(),
        "case_results": [{"name": n, "status": "passed"} for n in CONTRACT_CASES],
    }
    save("fixed-policy-codec-proof.json", saved)
    return {
        "schema_version": 1,
        "mode": "codec",
        "status": "passed",
        "cases": list(CONTRACT_CASES),
        "oracle_tests": 14,
        "cleanup_complete": True,
    }


def frame(request: FixedPolicyRequest | DocumentRequest) -> bytes:
    return (
        encode_document_request(request)
        if isinstance(request, DocumentRequest)
        else encode_fixed_policy_request(request)
    )


def request_input(request: FixedPolicyRequest) -> dict[str, object]:
    value = request.to_wire()
    del value["input_fingerprint"]
    return value


def read_marker_pid(path: Path, *, pid: int | None = None) -> int | None:
    """Observe complete PID bytes; a verified publication transition needs a retry."""
    if pid is not None and (type(pid) is not int or not 1 <= pid <= 2**31 - 1):
        raise ValueError("foreign_marker")
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or not 1 <= info.st_size <= 32
        or info.st_nlink not in {1, 2}
    ):
        raise ValueError("unsafe_marker")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        actual = os.fstat(stream.fileno())
        if (actual.st_dev, actual.st_ino, actual.st_uid, stat.S_IMODE(actual.st_mode)) != (
            info.st_dev,
            info.st_ino,
            os.getuid(),
            0o600,
        ) or actual.st_nlink not in {1, 2}:
            raise ValueError("unsafe_marker")
        raw = stream.read(33)
    if re.fullmatch(rb"[1-9][0-9]{0,9}\n", raw) is None:
        raise ValueError("unsafe_marker")
    candidate = int(raw)
    if pid is not None and candidate != pid:
        raise ValueError("foreign_marker")
    if info.st_nlink == 1:
        if actual.st_nlink != 1:
            raise ValueError("unsafe_marker")
        return candidate
    try:
        other = path.with_name(path.name + f".{candidate}.pending").lstat()
    except FileNotFoundError:
        settled = path.lstat()
        if (
            settled.st_dev,
            settled.st_ino,
            settled.st_uid,
            stat.S_IMODE(settled.st_mode),
            settled.st_nlink,
        ) != (info.st_dev, info.st_ino, os.getuid(), 0o600, 1):
            raise ValueError("unsafe_marker") from None
        return None
    if (
        other.st_dev,
        other.st_ino,
        other.st_uid,
        stat.S_IMODE(other.st_mode),
        other.st_nlink,
    ) != (info.st_dev, info.st_ino, os.getuid(), 0o600, 2):
        raise ValueError("unsafe_marker")
    return None


async def wait_marker(
    name: str, *, pid: int | None = None, pending: asyncio.Task[Any] | None = None
) -> int:
    until = time.monotonic() + 15
    path = DIRECTORY / (name + ".reached")
    while time.monotonic() < until:
        if path.exists():
            actual = read_marker_pid(path, pid=pid)
            if actual is not None:
                return actual
        if pending is not None and pending.done():
            await pending
            raise ValueError("missing_entry")
        await asyncio.sleep(0.005)
    raise ValueError("marker_timeout")


async def http() -> dict[str, Any]:
    global STAGE, CLEANUP
    CLEANUP = False
    enrollment = input_json("enrollment.json")
    tokens = json.loads(os.environ["P3_FIXED_POLICY_TOKENS"])
    if (
        type(tokens) is not list
        or len(tokens) != 6
        or len(set(tokens)) != 6
        or any(type(v) is not str or re.fullmatch(r"[A-Za-z0-9_-]{43}", v) is None for v in tokens)
    ):
        raise ValueError("invalid_tokens")
    peer = await wait_marker("fixed_policy_server_ready")
    endpoint = json.loads(read(DIRECTORY / "endpoint.json"))
    assert set(endpoint) == {"schema_version", "host", "port", "node_version"}
    selected = SpecialistEndpoint(endpoint["port"], endpoint["host"])
    clients: dict[str, FixedPolicySpecialistClient] = {
        name: FixedPolicySpecialistClient(selected, "Bearer " + tokens[index])
        for name, index in [
            ("primary", 0),
            ("secondary", 1),
            ("noInvoke", 2),
            ("noResult", 3),
            ("noCancel", 4),
            ("noEvidence", 5),
        ]
    }
    assert "Z" * 43 not in tokens
    clients["timeout"] = FixedPolicySpecialistClient(
        selected, "Bearer " + tokens[0], timeout_ms=1000
    )
    clients["badToken"] = FixedPolicySpecialistClient(selected, "Bearer " + "Z" * 43)
    document_client = DocumentSpecialistClient(selected, "Bearer " + tokens[0])
    all_clients: dict[str, FixedPolicySpecialistClient | DocumentSpecialistClient] = {
        **clients,
        "document": document_client,
    }
    pending: list[asyncio.Task[FixedPolicyResult]] = []
    wires: dict[str, dict[str, str]] = {}
    negatives: dict[str, dict[str, str]] = {}
    semantics: list[dict[str, str]] = []
    negative_wires: dict[str, dict[str, str]] = {}
    held: list[dict[str, str]] = []
    primary_error: BaseException | None = None

    spec = importlib.util.spec_from_file_location(
        "fixed_policy_real_public_example",
        ROOT / "projects/delegation-reliability/examples/fixed_policy_evaluation.py",
    )
    assert spec is not None and spec.loader is not None
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)

    def task(coroutine: Coroutine[Any, Any, FixedPolicyResult]) -> asyncio.Task[FixedPolicyResult]:
        owned = asyncio.create_task(coroutine)
        pending.append(owned)
        owned.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return owned

    def fresh(name: str, window: int = 60000) -> FixedPolicyRequest:
        rows = [v for v in enrollment["cases"] if v["name"] == name]
        assert len(rows) == 1
        value = copy.deepcopy(rows[0]["request_input"])
        value["deadline_at_ms"] = time.time_ns() // 1_000_000 + window
        return produce_fixed_policy_request(value)

    async def rejected(
        name: str,
        client: str,
        request: FixedPolicyRequest,
        expected: str,
        operation: str = "invoke",
    ) -> dict[str, str]:
        global STAGE, EXPECTATION
        STAGE = "negative_" + name
        EXPECTATION = {"name": name, "expected_code": expected, "observed_code": None}
        observed = ""
        try:
            if operation == "invoke":
                await clients[client].invoke(request)
            elif operation == "status":
                await clients[client].status(request)
            elif operation == "cancel":
                await clients[client].cancel(request)
            else:
                raise ValueError("invalid_operation")
        except (ContractError, SpecialistHttpError) as error:
            observed = safe_code(error)
        EXPECTATION["observed_code"] = observed or None
        assert observed == expected
        EXPECTATION = None
        row = {
            "name": name,
            "code": observed,
            "request_sha256": hashlib.sha256(frame(request)).hexdigest(),
        }
        negatives[name] = row
        negative_wires[name] = {
            "name": name,
            "operation": operation,
            "role": client,
            "request_utf8": frame(request).decode(),
        }
        return row

    async def positive(name: str, client: str = "primary") -> FixedPolicyResult:
        request = fresh(name)
        observed = await example.evaluate_fixed_policy(
            client=clients[client], request=request, records=records_for(request, enrollment)
        )
        assert type(observed) is FixedPolicyResult
        verdict = verify_fixed_policy_facts(
            request,
            observed,
            records_for(request, enrollment),
            observed_at_ms=time.time_ns() // 1_000_000,
        )
        expected = {
            "eligible": (True, "none"),
            "ineligible": (False, "none"),
            "threshold": (True, "none"),
            "missing": (None, "missing"),
            "conflicting": (None, "conflicting"),
            "adversarial": (False, "none"),
            "secondary_progress": (True, "none"),
        }[name]
        assert (observed.eligible, observed.uncertainty) == expected
        assert verdict == ("candidate" if expected[1] == "none" else "clarification")
        wires[name] = {
            "name": name,
            "request_utf8": frame(request).decode(),
            "result_utf8": encode_fixed_policy_result(observed).decode(),
        }
        return observed

    async def held_outcome(
        name: str, owned: asyncio.Task[Any], request: FixedPolicyRequest, codes: set[str]
    ) -> None:
        observed = ""
        try:
            await owned
        except (ContractError, SpecialistHttpError) as error:
            observed = safe_code(error)
        assert observed in codes
        held.append(
            {
                "name": name,
                "code": observed,
                "request_sha256": hashlib.sha256(frame(request)).hexdigest(),
                "request_utf8": frame(request).decode(),
            }
        )

    try:
        STAGE = "HTTP_positive"
        for name in (
            "eligible",
            "ineligible",
            "threshold",
            "missing",
            "conflicting",
            "adversarial",
        ):
            await positive(name)
        value = copy.deepcopy(
            next(v for v in enrollment["cases"] if v["name"] == "image_adversarial")[
                "request_input"
            ]
        )
        value["deadline_at_ms"] = time.time_ns() // 1_000_000 + 60000
        image_request = produce_document_request(value)
        image_result = await document_client.invoke(image_request)
        truth = input_json("documents/expected-v1.json")["fixtures"]["adversarial"]
        actual = image_result.to_wire()["fields"]
        assert type(actual) is dict
        for name, expected in truth["fields"].items():
            field = actual[name]
            assert (
                type(field) is dict
                and field["state"] == expected["state"]
                and field["value"] == expected["value"]
            )
            assert field["evidence_refs"] == [
                {
                    "source_id": truth["source"]["source_id"],
                    "version": truth["source"]["version"],
                    "sha256": truth["source"]["sha256"],
                    "region": region,
                }
                for region in expected["regions"]
            ]
        wires["image_adversarial"] = {
            "name": "image_adversarial",
            "request_utf8": encode_document_request(image_request).decode(),
            "result_utf8": encode_document_result(image_result).decode(),
        }
        STAGE = "HTTP_negative"
        for name, expected in [
            ("unsupported_version", "unsupported_facts"),
            ("wrong_rule", "unsupported_facts"),
            ("wrong_threshold", "unsupported_facts"),
            ("malformed_facts", "invalid_contract"),
        ]:
            request = fresh(name)
            row = await rejected(name, "primary", request, expected)
            semantics.append({**row, "request_utf8": frame(request).decode()})
            del negatives[name]
            del negative_wires[name]
        await rejected("bad_token", "badToken", fresh("eligible"), "unauthorized")
        await rejected("no_invoke_permission", "noInvoke", fresh("eligible"), "unauthorized")
        await rejected("no_result_permission", "noResult", fresh("eligible"), "unauthorized")
        await rejected("no_evidence_permission", "noEvidence", fresh("eligible"), "unauthorized")
        raw = request_input(fresh("eligible"))
        raw["scope"] = {"tenant_id": "foreign_tenant", "account_id": "foreign_account"}
        await rejected(
            "foreign_scope", "primary", produce_fixed_policy_request(raw), "unauthorized"
        )
        for name in ("unknown_source", "wrong_source_digest", "wrong_source_version"):
            raw = request_input(fresh("eligible"))
            refs = raw["evidence"]
            ctx = raw["context_snapshot"]
            assert type(refs) is list and type(ctx) is dict and type(refs[1]) is dict
            if name == "unknown_source":
                refs[1]["source_id"] = "not_registered"
                ctx["facts_source_id"] = "not_registered"
            elif name == "wrong_source_digest":
                refs[1]["sha256"] = "0" * 64
            else:
                refs[1]["version"] = "foreign_source_version"
            await rejected(name, "primary", produce_fixed_policy_request(raw), "evidence_mismatch")
        expired = fresh("eligible", -1)
        await rejected("expired_start", "primary", expired, "expired")
        # One exact negative deliberately bypasses the typed producer to exercise the receiving URL guard.
        bad = fresh("eligible").to_wire()
        bad_context = bad["context_snapshot"]
        assert type(bad_context) is dict
        bad_context["facts_source_id"] = "https://example.invalid/private"
        body = canonical(bad)
        writer: asyncio.StreamWriter | None = None
        try:
            async with asyncio.timeout(3):
                reader, writer = await asyncio.open_connection(
                    selected.host, selected.port, limit=8192
                )
                writer.write(
                    (
                        f"POST /v1/invoke HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {tokens[0]}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n"
                    ).encode()
                    + body
                )
                await writer.drain()
                head = (await reader.readuntil(b"\r\n\r\n")).decode().split("\r\n")
                headers = dict(line.lower().split(": ", 1) for line in head[1:] if line)
                assert " 400 " in head[0] and 0 < int(headers["content-length"]) <= 512
                response = await reader.readexactly(int(headers["content-length"]))
                code, _ = parse_error(response)
                assert code == "invalid_contract"
                negatives["URL_source"] = {
                    "name": "URL_source",
                    "code": code,
                    "request_sha256": hashlib.sha256(body).hexdigest(),
                }
                negative_wires["URL_source"] = {
                    "name": "URL_source",
                    "operation": "invoke",
                    "role": "primary",
                    "request_utf8": body.decode(),
                }
        finally:
            if writer is not None:
                writer.close()
                async with asyncio.timeout(1):
                    await writer.wait_closed()
        STAGE = "expiry"
        expiry = fresh("expiry_held", 1000)
        expiry_task = task(clients["primary"].invoke(expiry))
        await wait_marker("fixed_policy_expiry_held", pid=peer, pending=expiry_task)
        await held_outcome("expiry_held", expiry_task, expiry, {"deadline_exceeded"})
        marker("fixed_policy_expiry_verified")
        await wait_marker("fixed_policy_expiry_settled", pid=peer)
        STAGE = "capacity"
        timeout_request, cancel_request = fresh("timeout_held"), fresh("cancel_held")
        timeout_task, cancel_task = (
            task(clients["timeout"].invoke(timeout_request)),
            task(clients["primary"].invoke(cancel_request)),
        )
        STAGE = "capacity_wait_timeout"
        await wait_marker("fixed_policy_timeout_held", pid=peer, pending=timeout_task)
        STAGE = "capacity_wait_cancel"
        await wait_marker("fixed_policy_cancel_held", pid=peer, pending=cancel_task)
        raw = request_input(fresh("eligible"))
        raw["delegation_id"] = "fixed_capacity_probe"
        raw["attempt"] = {"attempt_id": "attempt_capacity_probe", "number": 1}
        await rejected("capacity_primary", "primary", produce_fixed_policy_request(raw), "capacity")
        await rejected("duplicate_attempt", "primary", cancel_request, "identity_conflict")
        changed = request_input(cancel_request)
        changed["request_revision"] = 2
        changed["attempt"] = {"attempt_id": "attempt_changed_fp", "number": 1}
        await rejected(
            "changed_fingerprint",
            "primary",
            produce_fixed_policy_request(changed),
            "identity_conflict",
        )
        changed = request_input(cancel_request)
        changed["request_revision"] = 2
        altered = produce_fixed_policy_request(changed)
        await rejected("wrong_status_identity", "primary", altered, "identity_conflict", "status")
        await rejected("wrong_cancel_identity", "primary", altered, "identity_conflict", "cancel")
        await rejected("no_cancel_permission", "noCancel", cancel_request, "unauthorized", "cancel")
        STAGE = "secondary_start"
        secondary_request = fresh("secondary_progress")
        secondary_task = task(clients["secondary"].invoke(secondary_request))
        STAGE = "secondary_wait"
        await wait_marker("fixed_policy_secondary_held", pid=peer, pending=secondary_task)
        raw = request_input(secondary_request)
        raw["delegation_id"] = "fixed_global_probe"
        raw["attempt"] = {"attempt_id": "attempt_global_probe", "number": 1}
        await rejected(
            "global_capacity", "secondary", produce_fixed_policy_request(raw), "capacity"
        )
        marker("fixed_policy_global_verified")
        STAGE = "secondary_result"
        secondary_result = await secondary_task
        assert (
            verify_fixed_policy_facts(
                secondary_request,
                secondary_result,
                records_for(secondary_request, enrollment),
                observed_at_ms=time.time_ns() // 1_000_000,
            )
            == "candidate"
            and secondary_result.eligible is True
        )
        wires["secondary_progress"] = {
            "name": "secondary_progress",
            "request_utf8": frame(secondary_request).decode(),
            "result_utf8": encode_fixed_policy_result(secondary_result).decode(),
        }
        STAGE = "cancel"
        status = await clients["primary"].status(cancel_request)
        assert status.state == "running" and not status.durable and not status.cancel_requested
        acknowledgement = await clients["primary"].cancel(cancel_request)
        assert acknowledgement.cancel_requested and not acknowledgement.durable
        await held_outcome("timeout_held", timeout_task, timeout_request, {"deadline_exceeded"})
        await held_outcome("cancel_held", cancel_task, cancel_request, {"request_aborted"})
        marker("fixed_policy_timeout_verified")
        marker("fixed_policy_cancel_verified")
        await wait_marker("fixed_policy_pair_settled", pid=peer)
        STAGE = "close"
        close_request = fresh("close_held")
        close_task = task(clients["primary"].invoke(close_request))
        await wait_marker("fixed_policy_close_held", pid=peer, pending=close_task)
        marker("fixed_policy_close_requested")
        await wait_marker("fixed_policy_close_incomplete", pid=peer)
        await held_outcome(
            "close_held", close_task, close_request, {"connection_failed", "invalid_response"}
        )
    except BaseException as error:
        primary_error = error
        raise
    finally:
        first: BaseException | None = None
        for client in all_clients.values():
            try:
                await client.close()
            except BaseException as error:  # noqa: BLE001 - attempt independent closes while preserving the original failure.
                if first is None:
                    first = error
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        CLEANUP = first is None and all(client.active == 0 for client in all_clients.values())
        if first is not None and primary_error is None:
            raise first
    STAGE = "proof"
    names = (
        "eligible",
        "ineligible",
        "threshold",
        "missing",
        "conflicting",
        "adversarial",
        "secondary_progress",
        "image_adversarial",
    )
    wire_raw = save(
        "fixed-policy-http-wires.json",
        {
            "schema_version": 1,
            "kind": "fixed-policy.canonical-http-wires",
            "records": [wires[n] for n in names],
        },
    )
    order = (
        "bad_token",
        "no_invoke_permission",
        "no_result_permission",
        "no_cancel_permission",
        "no_evidence_permission",
        "foreign_scope",
        "unknown_source",
        "wrong_source_digest",
        "wrong_source_version",
        "URL_source",
        "expired_start",
        "capacity_primary",
        "duplicate_attempt",
        "changed_fingerprint",
        "wrong_status_identity",
        "wrong_cancel_identity",
        "global_capacity",
    )
    negative_raw = save(
        "fixed-policy-negative-wires.json",
        {
            "schema_version": 1,
            "kind": "fixed-policy.negative-canonical-wires",
            "records": [negative_wires[n] for n in order],
        },
    )
    metrics: list[MetricRow] = [
        {"name": name, "values": dict(client.metrics())} for name, client in all_clients.items()
    ]
    assert (
        sum(row["values"]["started"] for row in metrics) == 34
        and sum(row["values"]["validated"] for row in metrics) == 10
    )
    proof = {
        "schema_version": 1,
        "kind": "fixed-policy.http-proof",
        "enrollment_sha256": hashlib.sha256(read(INPUTS / "enrollment.json")).hexdigest(),
        "positive_names": list(names),
        "negative_records": [negatives[n] for n in order],
        "negative_wire_descriptor": {
            "path": "fixed-policy-negative-wires.json",
            "bytes": len(negative_raw),
            "sha256": hashlib.sha256(negative_raw).hexdigest(),
        },
        "semantic_records": semantics,
        "held_records": held,
        "metrics": metrics,
        "raw_http_requests": 1,
        "wire_descriptor": {
            "path": "fixed-policy-http-wires.json",
            "bytes": len(wire_raw),
            "sha256": hashlib.sha256(wire_raw).hexdigest(),
        },
        "case_results": [{"name": n, "status": "passed"} for n in HTTP_CASES],
        "cleanup_complete": CLEANUP,
    }
    save("fixed-policy-http-proof.json", proof)
    return {
        "schema_version": 1,
        "mode": "http",
        "status": "passed",
        "cases": list(HTTP_CASES),
        "cleanup_complete": CLEANUP,
    }


async def main() -> int:
    try:
        setup()
        if MODE == "codec":
            result = await codec()
        else:
            result = await http()
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as error:  # noqa: BLE001 - finite fixture diagnostics exclude arbitrary errors and payloads.
        failure = {
            "schema_version": 1,
            "status": "failed",
            "mode": MODE if MODE in {"codec", "http"} else "invalid",
            "stage": STAGE if STAGE in STAGES else "setup",
            "code": safe_code(error),
            "cleanup_complete": CLEANUP,
            "expectation": EXPECTATION,
        }
        try:
            save("fixed-policy-python-failure.json", failure)
        except Exception:  # noqa: BLE001, S110 - a diagnostic sink cannot replace the original fixture failure.
            pass
        print(json.dumps(failure, sort_keys=True, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
