"""Unadapted public document consumers; all images/holds are explicit test inputs."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib
import importlib.util
import json
import os
import re
import stat
import sys
import time
from collections.abc import Awaitable
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from unittest.mock import patch

from continuity_lab.work_models import WorkError, WorkPayload
from delegation_reliability.contracts import (
    ERROR_CODES,
    ContractError,
    canonical,
    encode_request,
    encode_result,
    parse_request,
    parse_result,
)
from delegation_reliability.document import DocumentSpecialistClient
from delegation_reliability.document_contracts import (
    DOCUMENT_CAPABILITY,
    DocumentRequest,
    DocumentResult,
    encode_document_request,
    encode_document_result,
    match_document_result,
    parse_document_request,
    parse_document_result,
    produce_document_request,
)
from delegation_reliability.http_client import SpecialistEndpoint, SpecialistHttpError

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
BASE_KEYS = frozenset(
    {
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "SYSTEMROOT",
        "__CF_USER_TEXT_ENCODING",
        "CI",
        "NO_COLOR",
        "COREPACK_HOME",
        "COREPACK_ENABLE_NETWORK",
    }
)
ENROLLMENT = (
    "bad_crc",
    "truncated",
    "trailing",
    "apng",
    "unsupported",
    "bomb",
    "bad_filter",
    "zlib_trailing",
    "huge_header",
)
ROOT = Path(__file__).resolve().parents[3]
MODE = sys.argv[1] if len(sys.argv) == 2 else "invalid"
STAGE = "setup"
DIRECTORY: Path
FIXTURES: Path


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def private_directory(value: str | None) -> Path:
    if value is None:
        raise AssertionError("missing_setup")
    path = Path(value)
    assert path.is_absolute() and path == path.resolve(strict=True) and ".." not in path.parts
    observed = path.lstat()
    assert stat.S_ISDIR(observed.st_mode) and observed.st_uid == os.geteuid()
    assert stat.S_IMODE(observed.st_mode) == 0o700
    return path


def read(path: Path, maximum: int = 32768) -> bytes:
    observed = path.lstat()
    assert stat.S_ISREG(observed.st_mode) and observed.st_uid == os.geteuid()
    assert observed.st_nlink == 1 and stat.S_IMODE(observed.st_mode) == 0o600
    assert 0 < observed.st_size <= maximum
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        actual = os.fstat(fd)
        assert (actual.st_dev, actual.st_ino, actual.st_size) == (
            observed.st_dev,
            observed.st_ino,
            observed.st_size,
        )
        raw = os.read(fd, maximum + 1)
        assert len(raw) == observed.st_size
        return raw
    finally:
        os.close(fd)


def decode(raw: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, value in pairs:
            assert name not in result
            result[name] = value
        return result

    value = json.loads(raw, object_pairs_hook=unique)
    assert type(value) is dict
    return value


def input_json(name: str) -> dict[str, Any]:
    return decode(read(FIXTURES / name, 65536 if name == "v1.json" else 32768))


def save(name: str, value: object) -> bytes:
    assert re.fullmatch(r"[a-z][a-z0-9-]*\.json", name)
    raw = (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()
    assert 0 < len(raw) <= 32768
    target, temporary = DIRECTORY / name, DIRECTORY / (name + ".publishing")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        # Link publishes complete bytes atomically and refuses an existing original.
        os.link(temporary, target, follow_symlinks=False)
    finally:
        temporary.unlink(missing_ok=True)
    return raw


def arrived(name: str) -> None:
    assert name in {
        "document_timeout_verified",
        "document_cancel_verified",
        "document_close_requested",
    }
    target = DIRECTORY / (name + ".reached")
    pending = target.with_name(f"{target.name}.{os.getpid()}.pending")
    owned = False
    try:
        fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        owned = True
        with os.fdopen(fd, "wb") as stream:
            stream.write((str(os.getpid()) + "\n").encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, target, follow_symlinks=False)
    finally:
        if owned:
            pending.unlink(missing_ok=True)


def marker_pid(path: Path, expected: int | None) -> int | None:
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
    assert stat.S_IMODE(info.st_mode) == 0o600 and 0 < info.st_size <= 32
    if info.st_nlink == 1:
        raw = read(path, 32)
    else:
        # A complete linked marker can be observed before its exact pending alias
        # is removed. Never accept an arbitrary linked file as ready.
        assert info.st_nlink == 2
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(fd)
            assert (opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino)
            raw = os.read(fd, 33)
        finally:
            os.close(fd)
        assert re.fullmatch(rb"[1-9][0-9]{0,19}\n", raw)
        actual = int(raw)
        assert expected is None or actual == expected
        pending = path.with_name(f"{path.name}.{actual}.pending")
        try:
            other = pending.lstat()
        except FileNotFoundError:
            return None  # The publication finished during observation; re-read.
        assert stat.S_ISREG(other.st_mode) and other.st_uid == os.geteuid()
        assert stat.S_IMODE(other.st_mode) == 0o600 and other.st_nlink == 2
        assert (other.st_dev, other.st_ino) == (info.st_dev, info.st_ino)
        return None
    assert re.fullmatch(rb"[1-9][0-9]{0,19}\n", raw)
    actual = int(raw)
    assert expected is None or actual == expected
    return actual


async def wait_arrival(name: str, node_pid: int | None) -> int:
    assert name in {
        "document_server_ready",
        "document_timeout_held",
        "document_cancel_held",
        "document_close_held",
        "document_close_incomplete",
    }
    until = asyncio.get_running_loop().time() + 12
    path = DIRECTORY / (name + ".reached")
    while True:
        if path.exists() or path.is_symlink():
            actual = marker_pid(path, node_pid)
            if actual is not None:
                return actual
        assert asyncio.get_running_loop().time() < until
        await asyncio.sleep(0.005)


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def public_example() -> ModuleType:
    return load(
        "configured_document_example",
        ROOT / "projects/delegation-reliability/examples/document_extraction.py",
    )


def oracle() -> ModuleType:
    return load("independent_document_oracle", Path(__file__).with_name("test_document_oracle.py"))


def result_for(request: DocumentRequest, positive: dict[str, Any]) -> DocumentResult:
    value = copy.deepcopy(positive["result"])
    value.update(
        scope=request.to_wire()["scope"],
        delegation_id=request.delegation_id,
        case_id=request.case_id,
        request_revision=request.request_revision,
        attempt_id=request.attempt.attempt_id,
        input_fingerprint=request.input_fingerprint,
        completed_at_ms=time.time_ns() // 1_000_000,
    )
    return parse_document_result(canonical(value))


async def contracts() -> dict[str, Any]:
    global STAGE
    STAGE = "contracts"
    producer_raw = read(DIRECTORY / "document-producer.json")
    producer = decode(producer_raw)
    assert producer.keys() == {"schema_version", "kind", "rows"}
    assert producer["schema_version"] == 1 and producer["kind"] == "document.producer"
    rows = producer["rows"]
    assert len(rows) == 8 and [row["label"] for row in rows] == list(CONTRACT_CASES)
    positive, legacy = input_json("document-v1.json"), input_json("v1.json")
    expected, manifest = (
        input_json("documents/expected-v1.json"),
        input_json("documents/manifest.json"),
    )
    independent = oracle()
    records: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        assert set(row) == {"label", "request_utf8", "result_utf8"}
        request_raw, result_raw = row["request_utf8"].encode(), row["result_utf8"].encode()
        structural, factual, code = "accepted", "not_evaluated", "ok"
        if index == 1:
            assert (
                encode_request(parse_request(request_raw))
                == legacy["request_canonical"].encode()
                == request_raw
            )
            assert (
                encode_result(parse_result(result_raw))
                == legacy["result_canonical"].encode()
                == result_raw
            )
        else:
            request = parse_document_request(request_raw)
            assert encode_document_request(request) == request_raw
            if index == 2:
                try:
                    parse_document_result(result_raw)
                except ContractError as error:
                    assert error.code == "invalid_contract"
                    structural, code = "rejected", error.code
                else:
                    raise AssertionError("malformed_result_accepted")
            else:
                result = parse_document_result(result_raw)
                assert encode_document_result(result) == result_raw
                assert (
                    match_document_result(
                        request, result, observed_at_ms=positive["observed_at_ms"]
                    )
                    == "candidate"
                )
                try:
                    independent.assert_fixture_result(
                        result.to_wire(), expected["fixtures"]["complete"]
                    )
                except ContractError as error:
                    assert index in (3, 4) and error.code == "unsupported_facts"
                    factual, code = "incorrect", error.code
                else:
                    assert index not in (3, 4)
                    factual = "correct"
        records.append(
            {
                "name": CONTRACT_CASES[index],
                "structural": structural,
                "factual": factual,
                "code": code,
                "request_sha256": sha(request_raw),
                "result_sha256": sha(result_raw),
            }
        )
    for label, fixture in manifest["fixtures"].items():
        STAGE = "pixels"
        raw = read(FIXTURES / "documents" / fixture["file"], 2097152)
        width, height, channels, pixels = independent.fixture_pixels(raw)
        literal = expected["fixtures"][label]
        assert sha(raw) == fixture["source"]["sha256"] == literal["source"]["sha256"]
        assert len(raw) == fixture["source"]["byte_length"]
        assert (width, height, channels, sha(pixels)) == (
            fixture["source"]["width"],
            fixture["source"]["height"],
            fixture["channels"],
            fixture["pixel_sha256"],
        )
        assert sha(pixels) == literal["pixel_sha256"]
    STAGE = "imports"
    import delegation_reliability.document as public_document
    import delegation_reliability.document_contracts as public_contracts

    with (
        patch("socket.socket", side_effect=AssertionError("import_socket")),
        patch("threading.Thread.start", side_effect=AssertionError("import_thread")),
        patch("asyncio.create_task", side_effect=AssertionError("import_task")),
    ):
        importlib.reload(public_contracts)
        importlib.reload(public_document)
    # No image submission is smuggled through the unchanged policy-only P1 operation.
    try:
        WorkPayload(DOCUMENT_CAPABILITY, b"{}", positive["producer_input"]["deadline_at_ms"])
    except WorkError as error:
        assert error.code == "invalid_input"
    else:
        raise AssertionError("image_authority_invented")
    assert not hasattr(parse_document_result(rows[0]["result_utf8"].encode()), "eligible")
    STAGE = "snapshots"
    example = public_example()
    entered, release = asyncio.Event(), asyncio.Event()
    fresh = copy.deepcopy(positive["producer_input"])
    fresh["deadline_at_ms"] = time.time_ns() // 1_000_000 + 60000
    request = public_contracts.produce_document_request(fresh)
    original = public_contracts.encode_document_request(request)

    class HeldPort:
        async def invoke(self, value: DocumentRequest) -> DocumentResult:
            assert public_contracts.encode_document_request(value) == original
            entered.set()
            await release.wait()
            assert public_contracts.encode_document_request(value) == original
            # Reloaded dataclasses must be returned by the current public parser.
            raw = copy.deepcopy(positive["result"])
            raw.update(
                scope=value.to_wire()["scope"],
                delegation_id=value.delegation_id,
                case_id=value.case_id,
                request_revision=value.request_revision,
                attempt_id=value.attempt.attempt_id,
                input_fingerprint=value.input_fingerprint,
                completed_at_ms=time.time_ns() // 1_000_000,
            )
            return public_contracts.parse_document_result(canonical(raw))

    task = asyncio.create_task(example.extract_document(client=HeldPort(), request=request))
    await entered.wait()
    object.__setattr__(request.scope, "account_id", "mutated_after_await")
    release.set()
    observed = await task
    assert observed.scope.account_id == "account_document"
    save(
        "document-contract-proof.json",
        {
            "schema_version": 1,
            "status": "passed",
            "kind": "document.contract-proof",
            "case_results": [
                {"name": name, "status": "passed", "code": "ok"} for name in CONTRACT_CASES
            ],
            "producer_sha256": sha(producer_raw),
            "legacy_request_sha256": sha(rows[1]["request_utf8"].encode()),
            "legacy_result_sha256": sha(rows[1]["result_utf8"].encode()),
            "records": records,
        },
    )
    return {
        "schema_version": 1,
        "status": "passed",
        "mode": MODE,
        "tests": 8,
        "passed": 8,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "cases": list(CONTRACT_CASES),
        "proof": "document-contract-proof.json",
        "cleanup_complete": True,
    }


async def http() -> dict[str, Any]:
    global STAGE
    positive, manifest = input_json("document-v1.json"), input_json("documents/manifest.json")
    expected, independent = input_json("documents/expected-v1.json"), oracle()
    endpoint = decode(read(DIRECTORY / "document-endpoint.json"))
    assert endpoint.keys() == {"schema_version", "host", "port", "node_version"}
    assert (
        endpoint["schema_version"] == 1
        and endpoint["host"] == "127.0.0.1"
        and endpoint["node_version"] == "24.22.2"
    )
    node_pid = await wait_arrival("document_server_ready", None)
    enrollment = decode(read(DIRECTORY / "document-image-references.json", 8192))
    assert enrollment.keys() == {"schema_version", "kind", "records"}
    assert enrollment["schema_version"] == 1 and enrollment["kind"] == "document.image-references"
    assert [r["name"] for r in enrollment["records"]] == list(ENROLLMENT)
    enrolled: dict[str, dict[str, Any]] = {}
    for row in enrollment["records"]:
        assert row.keys() == {"name", "reference"}
        ref = row["reference"]
        assert set(ref) == {
            "source_id",
            "version",
            "sha256",
            "media_type",
            "byte_length",
            "width",
            "height",
        }
        assert ref["source_id"] == "document_" + row["name"] and ref["version"] == "document_v1"
        assert ref["media_type"] == "image/png"
        enrolled[row["name"]] = ref
    token, other_token = os.environ["P3_DOCUMENT_TOKEN"], os.environ["P3_DOCUMENT_OTHER_TOKEN"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token) and re.fullmatch(
        r"[A-Za-z0-9_-]{43}", other_token
    )
    ep = SpecialistEndpoint(endpoint["port"])
    clients: list[DocumentSpecialistClient] = []

    def client(credential: str = token, timeout: int = 5000) -> DocumentSpecialistClient:
        value = DocumentSpecialistClient(ep, "Bearer " + credential, timeout_ms=timeout)
        clients.append(value)
        return value

    main, secondary, short = client(), client(other_token), client(timeout=500)
    example = public_example()
    sequence = 0

    def request(
        source: str = "complete",
        *,
        reference: dict[str, Any] | None = None,
        other_scope: bool = False,
        deadline: int | None = None,
    ) -> DocumentRequest:
        nonlocal sequence
        sequence += 1
        value = copy.deepcopy(positive["producer_input"])
        ref = copy.deepcopy(reference or manifest["fixtures"][source]["source"])
        value["context_snapshot"]["document_source_id"] = ref["source_id"]
        value["evidence"] = [ref]
        value["deadline_at_ms"] = (
            deadline if deadline is not None else time.time_ns() // 1_000_000 + 60000
        )
        value["delegation_id"] = f"document_http_{sequence}"
        value["attempt"]["attempt_id"] = f"document_attempt_{sequence}"
        if other_scope:
            value["scope"]["account_id"] = "account_document_other"
            value["case_id"] = "case_document_other"
            value["result_route"]["conversation_id"] = "conversation_document_other"
        return produce_document_request(value)

    rows: dict[str, dict[str, Any]] = {}
    wires: list[dict[str, str]] = []

    def record(
        index: int,
        req: DocumentRequest,
        *,
        requests: int,
        rejected: int = 0,
        result: DocumentResult | None = None,
        validated: int = 0,
        code: str = "ok",
    ) -> None:
        rows[HTTP_CASES[index]] = {
            "name": HTTP_CASES[index],
            "requests": requests,
            "validated_results": validated,
            "expected_rejections": rejected,
            "code": code,
            "source_sha256": req.evidence[0].sha256,
            "request_sha256": sha(encode_document_request(req)),
            "result_sha256": None if result is None else sha(encode_document_result(result)),
        }

    async def rejected(call: Awaitable[object], codes: set[str]) -> str:
        try:
            await call
        except (ContractError, SpecialistHttpError) as error:
            assert error.code in codes
            return error.code
        raise AssertionError("required_rejection_absent")

    async def settled(req: DocumentRequest) -> int:
        for count in range(1, 9):
            try:
                observed = await main.status(req)
            except ContractError as error:
                assert error.code == "unknown_attempt"
                return count
            assert observed.durable is False
            await asyncio.sleep(0.02)
        raise AssertionError("actual_attempt_not_settled")

    primary: BaseException | None = None
    pending: list[asyncio.Task[DocumentResult]] = []
    try:
        for index, label in enumerate(("complete", "missing", "ambiguous", "adversarial")):
            STAGE = "positive_" + label
            req = request(label)
            result = await example.extract_document(client=main, request=req)
            independent.assert_fixture_result(result.to_wire(), expected["fixtures"][label])
            assert not hasattr(result, "eligible")
            wires.append(
                {
                    "name": HTTP_CASES[index],
                    "request_utf8": encode_document_request(req).decode(),
                    "result_utf8": encode_document_result(result).decode(),
                }
            )
            record(index, req, requests=1, result=result, validated=1)
        STAGE = "grants"
        req = request()
        count = 0
        for role, operation in (
            ("invoke", "invoke"),
            ("result", "status"),
            ("cancel", "cancel"),
            ("evidence", "invoke"),
        ):
            credential = (
                __import__("base64")
                .urlsafe_b64encode(hashlib.sha256((token + ":" + role).encode()).digest())
                .decode()
                .rstrip("=")
            )
            restricted = client(credential)
            await rejected(getattr(restricted, operation)(req), {"unauthorized"})
            count += 1
        wrong = req.to_wire()
        wrong["scope"] = {"tenant_id": "tenant_foreign", "account_id": "account_foreign"}
        wrong.pop("input_fingerprint")
        foreign = produce_document_request(wrong)
        await rejected(main.invoke(foreign), {"unauthorized"})
        record(4, foreign, requests=count + 1, rejected=count + 1, code="unauthorized")
        STAGE = "inaccessible"
        ref = copy.deepcopy(manifest["fixtures"]["complete"]["source"])
        ref["source_id"] = "document_missing_record"
        req = request(reference=ref)
        await rejected(main.invoke(req), {"evidence_mismatch"})
        bad = cast(dict[str, Any], req.to_wire())
        bad.pop("input_fingerprint")
        bad["evidence"][0]["source_id"] = "https://invalid.test/image.png"
        try:
            produce_document_request(bad)
        except ContractError as error:
            assert error.code == "invalid_contract"
        else:
            raise AssertionError("URL_accepted")
        record(5, req, requests=1, rejected=1, code="evidence_mismatch")
        STAGE = "size_bounds"
        calls = 0
        for key, value in (("byte_length", 2097153), ("width", 2049), ("height", 2049)):
            bad = copy.deepcopy(positive["producer_input"])
            bad["evidence"][0][key] = value
            try:
                produce_document_request(bad)
            except ContractError as error:
                assert error.code == "invalid_contract"
            else:
                raise AssertionError("oversized_metadata_accepted")
            calls += 1
        ref = copy.deepcopy(manifest["fixtures"]["complete"]["source"])
        ref["byte_length"] += 1
        req = request(reference=ref)
        await rejected(main.invoke(req), {"evidence_mismatch"})
        req = request(reference=enrolled["huge_header"])
        await rejected(main.invoke(req), {"invalid_contract"})
        assert calls == 3
        record(6, req, requests=2, rejected=2, code="invalid_contract")
        STAGE = "corrupt_images"
        for label in ("bad_crc", "truncated", "trailing", "apng", "unsupported"):
            req = request(reference=enrolled[label])
            await rejected(
                main.invoke(req),
                {"unsupported_facts"}
                if label in {"apng", "unsupported"}
                else {"evidence_mismatch"},
            )
        record(7, req, requests=5, rejected=5, code="unsupported_facts")
        STAGE = "bounded_decode"
        for label in ("bomb", "bad_filter", "zlib_trailing"):
            req = request(reference=enrolled[label])
            decode_code = await rejected(
                main.invoke(req), {"evidence_mismatch", "invalid_contract"}
            )
        record(8, req, requests=3, rejected=3, code=decode_code)
        STAGE = "expiry"
        req = request(deadline=time.time_ns() // 1_000_000 - 1)
        await rejected(main.invoke(req), {"expired"})
        ref = copy.deepcopy(manifest["fixtures"]["complete"]["source"])
        ref["source_id"] = "document_post_decode"
        req = request(reference=ref, deadline=time.time_ns() // 1_000_000 + 1000)
        await rejected(main.invoke(req), {"deadline_exceeded"})
        denial_at = time.time_ns() // 1_000_000
        phase = decode(read(DIRECTORY / "document-phase.json"))
        assert (
            phase["attempt_id"] == req.attempt.attempt_id
            and phase["input_fingerprint"] == req.input_fingerprint
        )
        assert phase["worker_exit_code"] == 0 and phase["deadline_at_ms"] <= denial_at
        expiry_reads = await settled(req)
        record(9, req, requests=2 + expiry_reads, rejected=3, code="deadline_exceeded")
        STAGE = "timeout"
        ref = copy.deepcopy(manifest["fixtures"]["complete"]["source"])
        ref["source_id"] = "document_timeout_held"
        timeout_request = request(reference=ref)
        timeout_task = asyncio.create_task(short.invoke(timeout_request))
        pending.append(timeout_task)
        await wait_arrival("document_timeout_held", node_pid)
        await rejected(timeout_task, {"deadline_exceeded"})
        capacity_request = request()
        await rejected(main.invoke(capacity_request), {"capacity"})
        changed = cast(dict[str, Any], timeout_request.to_wire())
        changed.pop("input_fingerprint")
        changed["context_snapshot"]["note"] = "Changed semantic input for the same held attempt"
        await rejected(main.invoke(produce_document_request(changed)), {"identity_conflict"})
        secondary_request = request(other_scope=True)
        progress = await example.extract_document(client=secondary, request=secondary_request)
        independent.assert_fixture_result(progress.to_wire(), expected["fixtures"]["complete"])
        progress_at = time.time_ns() // 1_000_000
        assert progress_at > denial_at
        wires.append(
            {
                "name": "secondary_progress",
                "request_utf8": encode_document_request(secondary_request).decode(),
                "result_utf8": encode_document_result(progress).decode(),
            }
        )
        arrived("document_timeout_verified")
        timeout_reads = await settled(timeout_request)
        STAGE = "cancel"
        ref = copy.deepcopy(manifest["fixtures"]["complete"]["source"])
        ref["source_id"] = "document_cancel_held"
        cancel_request = request(reference=ref)
        cancel_task = asyncio.create_task(main.invoke(cancel_request))
        pending.append(cancel_task)
        await wait_arrival("document_cancel_held", node_pid)
        observation = await main.status(cancel_request)
        assert observation.durable is False and observation.cancel_requested is False
        acknowledgement = await main.cancel(cancel_request)
        assert acknowledgement.durable is False and acknowledgement.cancel_requested is True
        await rejected(cancel_task, {"request_aborted"})
        await rejected(main.invoke(request()), {"capacity"})
        arrived("document_cancel_verified")
        cancel_reads = await settled(cancel_request)
        record(
            11,
            secondary_request,
            requests=8 + timeout_reads + cancel_reads,
            rejected=7,
            result=progress,
            validated=1,
            code="capacity",
        )
        STAGE = "close"
        ref = copy.deepcopy(manifest["fixtures"]["complete"]["source"])
        ref["source_id"] = "document_close_held"
        close_request = request(reference=ref)
        close_task = asyncio.create_task(main.invoke(close_request))
        pending.append(close_task)
        await wait_arrival("document_close_held", node_pid)
        arrived("document_close_requested")
        await wait_arrival("document_close_incomplete", node_pid)
        close_code = await rejected(
            close_task, {"closing", "request_aborted", "connection_failed", "invalid_response"}
        )
        record(10, close_request, requests=1, rejected=1, code=close_code)
        for owner in clients:
            await owner.close()
        assert all(owner.active == 0 for owner in clients)
        wire_raw = save(
            "document-http-wires.json",
            {"schema_version": 1, "kind": "document.http-canonical-wires", "records": wires},
        )
        save(
            "document-http-proof.json",
            {
                "schema_version": 1,
                "status": "passed",
                "kind": "document.http-proof",
                "case_results": [
                    {"name": name, "status": "passed", "code": "ok"} for name in HTTP_CASES
                ],
                "records": [rows[name] for name in HTTP_CASES],
                "provider_calls": 8,
                "other_principal_progress": True,
                "close_incomplete_observed": True,
                "client_active": 0,
                "wires": {
                    "path": "document-http-wires.json",
                    "bytes": len(wire_raw),
                    "sha256": sha(wire_raw),
                },
                "expiry": {
                    "before_start_denied": True,
                    "post_decode_denied": True,
                    "post_decode_worker_exit": 0,
                    "deadline_at_ms": phase["deadline_at_ms"],
                    "denial_observed_at_ms": denial_at,
                    "secondary_progress_observed_at_ms": progress_at,
                    "secondary_attempt_id": secondary_request.attempt.attempt_id,
                    "input_fingerprint": secondary_request.input_fingerprint,
                },
            },
        )
    except (
        AssertionError,
        ContractError,
        SpecialistHttpError,
        OSError,
        ValueError,
        TypeError,
        RuntimeError,
        asyncio.CancelledError,
    ) as error:
        primary = error
    finally:
        for task in pending:
            if not task.done():
                task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        cleanup_error: BaseException | None = None
        for owner in clients:
            try:
                await owner.close()
            except (
                AssertionError,
                ContractError,
                SpecialistHttpError,
                OSError,
                ValueError,
                TypeError,
                RuntimeError,
                asyncio.CancelledError,
            ) as error:
                cleanup_error = cleanup_error or error
        if primary is not None:
            raise primary
        if cleanup_error is not None:
            raise cleanup_error
    return {
        "schema_version": 1,
        "status": "passed",
        "mode": MODE,
        "tests": 12,
        "passed": 12,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "cases": list(HTTP_CASES),
        "proof": "document-http-proof.json",
        "cleanup_complete": True,
    }


def main() -> None:
    global DIRECTORY, FIXTURES
    assert MODE in {"python-contracts", "python-http"}
    keys = BASE_KEYS | {"P3_DOCUMENT_DIRECTORY", "P3_DOCUMENT_FIXTURES"}
    if MODE == "python-http":
        keys |= {"P3_DOCUMENT_TOKEN", "P3_DOCUMENT_OTHER_TOKEN"}
    assert set(os.environ) <= keys
    DIRECTORY = private_directory(os.environ.get("P3_DOCUMENT_DIRECTORY"))
    FIXTURES = private_directory(os.environ.get("P3_DOCUMENT_FIXTURES"))
    result = asyncio.run(contracts() if MODE == "python-contracts" else http())
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except (
        AssertionError,
        ContractError,
        SpecialistHttpError,
        OSError,
        ValueError,
        TypeError,
        RuntimeError,
        asyncio.CancelledError,
    ) as error:
        code = (
            error.code
            if isinstance(error, (ContractError, SpecialistHttpError))
            and type(error) in (ContractError, SpecialistHttpError)
            and error.code in ERROR_CODES | HTTP_CODES
            else "fixture_failed"
        )
        failure = {
            "schema_version": 1,
            "status": "failed",
            "mode": MODE,
            "stage": STAGE,
            "code": code,
            "cleanup_complete": False,
        }
        try:
            save("document-python-failure.json", failure)
        except (AssertionError, OSError, ValueError):
            # Diagnostic sink failure never replaces the original safe failure.
            failure["cleanup_complete"] = False
        print(json.dumps(failure, separators=(",", ":")))
        raise SystemExit(1) from None
