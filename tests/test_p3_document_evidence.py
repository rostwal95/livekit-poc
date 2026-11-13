"""Synthetic proof counterexamples over actual image truth; reviewed 12 November 2026.

No child, worker, PostgreSQL or provider is run. The helper and these tests share
an author; this is adversarial implementation coverage, not an independent audit.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local-setup/scripts"))
import p3_document_evidence as gate

CONTRACTS = (
    "cross_language_document_schema_canonical_fingerprint_and_exact_correlation",
    "legacy_policy_wire_defaults_and_public_types_unchanged",
    "strict_document_shape_dates_status_nullability_and_region_bounds",
    "schema_valid_wrong_extracted_value_fails_independent_fixture_verdict",
    "schema_valid_swapped_region_source_version_or_digest_fails_verdict",
    "actual_fixture_manifest_and_decoded_pixel_hash_parity",
    "imports_no_IO_no_mutation_send_or_policy_eligible_surface",
    "nested_request_provider_result_snapshots_before_await",
)
HTTP = (
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
F = ("booking_reference", "property_name", "check_in", "check_out")
D = ROOT / "contracts/delegation"
NOW = 1800000000000


def compact(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def pretty(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def case_results(names):
    return [{"name": n, "status": "passed", "code": "ok"} for n in names]


def wire(oracle, fixture_name, name, *, secondary=False, deadline=None):
    """Independent literal proof construction, not a provider/result factory."""
    base = json.loads((D / "document-v1.json").read_bytes())
    request = copy.deepcopy(base["request"])
    literal = oracle["fixtures"][fixture_name]
    request["delegation_id"] = "delegation_" + sha(name.encode())[:20]
    request["attempt"] = {"attempt_id": "attempt_" + sha(name.encode())[:20], "number": 1}
    request["context_snapshot"]["document_source_id"] = literal["source"]["source_id"]
    request["evidence"] = [copy.deepcopy(literal["source"])]
    request["deadline_at_ms"] = NOW + 30000 if deadline is None else deadline
    if secondary:
        request["scope"] = {"tenant_id": "tenant_document", "account_id": "account_document_other"}
        request["case_id"] = "case_document_other"
        request["result_route"] = {"conversation_id": "conversation_document_other"}
    request["input_fingerprint"] = sha(
        compact({k: v for k, v in request.items() if k not in {"attempt", "input_fingerprint"}})
    )
    result = copy.deepcopy(base["result"])
    for key in ("scope", "case_id", "delegation_id", "request_revision", "input_fingerprint"):
        result[key] = copy.deepcopy(request[key])
    result["attempt_id"] = request["attempt"]["attempt_id"]
    result["outcome"] = literal["outcome"]
    result["fields"] = {
        name: {
            "state": item["state"],
            "value": item["value"],
            "evidence_refs": [
                {
                    "source_id": literal["source"]["source_id"],
                    "version": literal["source"]["version"],
                    "sha256": literal["source"]["sha256"],
                    "region": copy.deepcopy(region),
                }
                for region in item["regions"]
            ],
        }
        for name, item in literal["fields"].items()
    }
    result["completed_at_ms"] = NOW + 20
    return {
        "name": name,
        "request_utf8": compact(request).decode(),
        "result_utf8": compact(result).decode(),
    }


def synthetic_bundle():
    oracle = json.loads((D / "documents/expected-v1.json").read_bytes())
    rows = []
    legacy = json.loads((D / "v1.json").read_bytes())
    for index, name in enumerate(CONTRACTS):
        item = wire(oracle, "complete", "contract_" + str(index))
        if index == 1:
            item["request_utf8"], item["result_utf8"] = (
                legacy["request_canonical"],
                legacy["result_canonical"],
            )
        elif index in (3, 4):
            result = json.loads(item["result_utf8"])
            if index == 3:
                result["fields"]["booking_reference"]["value"] = "WRONG-BOOKING"
            else:
                result["fields"]["check_in"]["evidence_refs"][0]["region"] = copy.deepcopy(
                    result["fields"]["check_out"]["evidence_refs"][0]["region"]
                )
            item["result_utf8"] = compact(result).decode()
        rows.append(
            {
                "label": name,
                "request_utf8": item["request_utf8"],
                "result_utf8": item["result_utf8"],
            }
        )
    producer = {"schema_version": 1, "kind": "document.producer", "rows": rows}
    contract_records = [
        {
            "name": name,
            "structural": "accepted",
            "factual": "incorrect" if i in (3, 4) else "not_evaluated" if i == 1 else "correct",
            "code": "unsupported_facts" if i in (3, 4) else "ok",
            "request_sha256": sha(row["request_utf8"].encode()),
            "result_sha256": sha(row["result_utf8"].encode()),
        }
        for i, (name, row) in enumerate(zip(CONTRACTS, rows, strict=True))
    ]
    contracts = {
        "schema_version": 1,
        "status": "passed",
        "kind": "document.contract-proof",
        "case_results": case_results(CONTRACTS),
        "producer_sha256": sha(pretty(producer)),
        "legacy_request_sha256": sha(legacy["request_canonical"].encode()),
        "legacy_result_sha256": sha(legacy["result_canonical"].encode()),
        "records": contract_records,
    }
    wire_rows = [
        wire(oracle, image, name)
        for image, name in zip(
            ("complete", "missing", "ambiguous", "adversarial"), HTTP[:4], strict=True
        )
    ]
    wire_rows.append(wire(oracle, "complete", "secondary_progress", secondary=True))
    wires = {"schema_version": 1, "kind": "document.http-canonical-wires", "records": wire_rows}
    records = []
    for index, name in enumerate(HTTP):
        item = wire_rows[index] if index < 4 else wire(oracle, "complete", "negative_" + str(index))
        records.append(
            {
                "name": name,
                "requests": 1,
                "validated_results": 1 if index < 4 else 0,
                "expected_rejections": 0 if index < 4 else 1,
                "code": "ok"
                if index < 4
                else "expired"
                if index == 9
                else "unauthorized"
                if index == 4
                else "invalid_contract",
                "source_sha256": oracle["fixtures"][
                    ("complete", "missing", "ambiguous", "adversarial")[index]
                    if index < 4
                    else "complete"
                ]["source"]["sha256"],
                "request_sha256": sha(item["request_utf8"].encode()),
                "result_sha256": sha(item["result_utf8"].encode()) if index < 4 else None,
            }
        )
    secondary = json.loads(wire_rows[4]["request_utf8"])
    expiry = {
        "before_start_denied": True,
        "post_decode_denied": True,
        "post_decode_worker_exit": 0,
        "deadline_at_ms": NOW + 500,
        "denial_observed_at_ms": NOW + 501,
        "secondary_progress_observed_at_ms": NOW + 502,
        "secondary_attempt_id": secondary["attempt"]["attempt_id"],
        "input_fingerprint": secondary["input_fingerprint"],
    }
    http = {
        "schema_version": 1,
        "status": "passed",
        "kind": "document.http-proof",
        "case_results": case_results(HTTP),
        "records": records,
        "provider_calls": 8,
        "other_principal_progress": True,
        "close_incomplete_observed": True,
        "client_active": 0,
        "wires": {
            "path": "document-http-wires.json",
            "bytes": len(pretty(wires)),
            "sha256": sha(pretty(wires)),
        },
        "expiry": expiry,
    }
    provider = []
    for kind, item in zip(
        ("complete", "missing", "ambiguous", "adversarial", "secondary_progress"),
        wire_rows,
        strict=True,
    ):
        request = json.loads(item["request_utf8"])
        provider.append(
            {
                "kind": kind,
                "attempt_id": request["attempt"]["attempt_id"],
                "input_fingerprint": request["input_fingerprint"],
                "source_sha256": request["evidence"][0]["sha256"],
                "result_sha256": sha(item["result_utf8"].encode()),
                "settled": True,
            }
        )
    for kind in ("timeout_held", "cancel_held", "close_held"):
        request = json.loads(wire(oracle, "complete", kind)["request_utf8"])
        provider.append(
            {
                "kind": kind,
                "attempt_id": request["attempt"]["attempt_id"],
                "input_fingerprint": request["input_fingerprint"],
                "source_sha256": request["evidence"][0]["sha256"],
                "result_sha256": None,
                "settled": True,
            }
        )
    server = {
        "schema_version": 1,
        "status": "passed",
        "kind": "document.server-proof",
        "node_version": "24.22.2",
        "provider_calls": 8,
        "provider_records": provider,
        "provider_active": 0,
        "worker_records": [
            {"thread_id": n, "exit_code": 0, "normal_result": True} for n in range(1, 10)
        ],
        "workers_active": 0,
        "requests": 0,
        "sockets": 0,
        "active": 0,
        "observerPending": 0,
        "close_incomplete_observed": True,
        "closed": True,
    }
    expired = json.loads(
        wire(oracle, "complete", "expired_after_decode", deadline=NOW + 500)["request_utf8"]
    )
    phase = {
        "schema_version": 1,
        "kind": "document.post-decode-held",
        "node_pid": 12345,
        "attempt_id": expired["attempt"]["attempt_id"],
        "input_fingerprint": expired["input_fingerprint"],
        "deadline_at_ms": NOW + 500,
        "worker_exit_code": 0,
    }
    values = {
        "document-producer.json": producer,
        "document-contract-proof.json": contracts,
        "document-http-proof.json": http,
        "document-http-wires.json": wires,
        "document-server-proof.json": server,
    }
    return values, oracle, phase


class DocumentEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.values, self.oracle, self.phase = synthetic_bundle()

    def raw(self):
        return {name: pretty(value) for name, value in self.values.items()}

    def reject_bundle(self):
        with self.assertRaises(gate.GateError):
            gate.validate_bundle(self.raw(), self.oracle, phase=self.phase)

    def test_complete_synthetic_proof_joins_real_oracle_without_product_imports(self):
        self.assertEqual(gate.CONTRACT_CASES, CONTRACTS)
        self.assertEqual(gate.HTTP_CASES, HTTP)
        self.assertEqual(
            gate.validate_bundle(self.raw(), self.oracle, phase=self.phase),
            {
                "provider_calls": 8,
                "canonical_http_results": 5,
                "contract_rows": 8,
                "worker_records": 9,
                "expired_before_and_after_decode": True,
            },
        )
        self.assertNotIn("packages", vars(gate))
        self.assertNotIn("OwnedProcess", vars(gate))

    def test_safe_codes_are_exact_current_public_declarations(self):
        ts = ROOT / "projects/delegation-reliability/specialist-ts/src"

        def codes(file, name):
            match = re.search(
                r"export const " + name + r" = \[(.*?)\] as const",
                (ts / file).read_text(),
                re.DOTALL,
            )
            self.assertIsNotNone(match)
            return set(re.findall(r"'([a-z_]+)'", match[1]))

        self.assertEqual(gate.CONTRACT_CODES, codes("contracts.ts", "ERROR_CODES"))
        self.assertEqual(gate.HTTP_CODES, codes("http-protocol.ts", "HTTP_CODES"))
        self.assertEqual(gate.SAFE_CODES, gate.CONTRACT_CODES | gate.HTTP_CODES | {"ok"})
        self.assertEqual(len(gate.SAFE_CODES), 25)

    def test_duplicate_nonobject_huge_nonfinite_deep_and_surrogate_JSON_reject(self):
        raw_cases = [
            b'{"a":1,"a":2}',
            b"[]",
            b"true",
            b"null",
            b'{"a":NaN}',
            b'{"a":1e9999}',
            b'{"a":9007199254740992}',
            b'{"a":' + b"9" * 5000 + b"}",
            b'{"a":"\\ud800"}',
            b'{"a":"\xff"}',
            b'{"a":' + b"[" * 25 + b"0" + b"]" * 25 + b"}",
        ]
        for raw in raw_cases:
            with self.subTest(raw=raw[:30]), self.assertRaises(gate.GateError):
                gate.decode(raw)

    def test_unhashable_enum_and_primitive_values_raise_fixed_GateError(self):
        targets = [
            ("document-contract-proof.json", "records", 0, "structural"),
            ("document-contract-proof.json", "records", 0, "factual"),
            ("document-http-proof.json", "records", 0, "code"),
            ("document-server-proof.json", "provider_records", 0, "kind"),
        ]
        for name, key, index, field in targets:
            for value in ([], {}, True, None):
                with self.subTest(name=name, field=field, value=value):
                    values = copy.deepcopy(self.values)
                    values[name][key][index][field] = value
                    with self.assertRaises(gate.GateError):
                        gate.validate_bundle(
                            {n: pretty(v) for n, v in values.items()}, self.oracle, phase=self.phase
                        )

    def test_guess_transport_code_and_unknown_fields_cannot_be_retained(self):
        self.values["document-http-proof.json"]["records"][4]["code"] = "transport_unavailable"
        self.reject_bundle()
        self.values, self.oracle, self.phase = synthetic_bundle()
        self.values["document-server-proof.json"]["raw_error"] = "SENTINEL_PRIVATE"
        self.reject_bundle()

    def test_server_requires_all_eight_individually_settled_provider_records(self):
        for mutation in (
            "missing",
            "duplicate_kind",
            "duplicate_attempt",
            "not_settled",
            "foreign_source",
        ):
            with self.subTest(mutation=mutation):
                self.values, self.oracle, self.phase = synthetic_bundle()
                records = self.values["document-server-proof.json"]["provider_records"]
                if mutation == "missing":
                    records.pop()
                elif mutation == "duplicate_kind":
                    records[-1]["kind"] = records[0]["kind"]
                elif mutation == "duplicate_attempt":
                    records[-1]["attempt_id"] = records[0]["attempt_id"]
                elif mutation == "not_settled":
                    records[-1]["settled"] = False
                else:
                    records[-1]["source_sha256"] = "0" * 64
                self.reject_bundle()

    def test_bool_counts_worker_success_and_actual_exit_are_distinct(self):
        for field, value in (
            ("provider_calls", True),
            ("workers_active", False),
            ("provider_active", False),
            ("observerPending", False),
        ):
            with self.subTest(field=field):
                v = copy.deepcopy(self.values)
                v["document-server-proof.json"][field] = value
                with self.assertRaises(gate.GateError):
                    gate.validate_bundle({n: pretty(x) for n, x in v.items()}, self.oracle)
        for mutation in ("only8", "failed_exit", "numeric_normal", "duplicate_thread"):
            with self.subTest(mutation=mutation):
                self.values, self.oracle, self.phase = synthetic_bundle()
                workers = self.values["document-server-proof.json"]["worker_records"]
                if mutation == "only8":
                    workers.pop()
                elif mutation == "failed_exit":
                    workers[0]["exit_code"] = 1
                elif mutation == "numeric_normal":
                    workers[0]["normal_result"] = 1
                else:
                    workers[-1]["thread_id"] = workers[0]["thread_id"]
                self.reject_bundle()

    def test_canonical_wire_and_fingerprint_not_just_JSON_semantics(self):
        item = self.values["document-http-wires.json"]["records"][0]
        for request in (
            item["request_utf8"] + " ",
            json.dumps(json.loads(item["request_utf8"]), indent=2),
        ):
            with self.subTest(request=request[:20]), self.assertRaises(gate.GateError):
                gate.match_wire({**item, "request_utf8": request}, self.oracle)
        request = json.loads(item["request_utf8"])
        request["context_snapshot"]["note"] = "changed accepted source context"
        with self.assertRaises(gate.GateError):
            gate.match_wire({**item, "request_utf8": compact(request).decode()}, self.oracle)

    def test_type_correct_wrong_facts_and_valid_swapped_regions_do_not_pass(self):
        item = self.values["document-http-wires.json"]["records"][0]
        for change in ("value", "region", "source"):
            result = json.loads(item["result_utf8"])
            if change == "value":
                result["fields"]["booking_reference"]["value"] = "OTHER-BK"
            elif change == "region":
                result["fields"]["check_in"]["evidence_refs"][0]["region"] = copy.deepcopy(
                    result["fields"]["check_out"]["evidence_refs"][0]["region"]
                )
            else:
                result["fields"]["check_in"]["evidence_refs"][0]["sha256"] = "0" * 64
            with self.subTest(change=change), self.assertRaises(gate.GateError):
                gate.match_wire({**item, "result_utf8": compact(result).decode()}, self.oracle)

    def test_expected_fixture_and_primary_secondary_scope_cannot_be_swapped(self):
        complete = self.values["document-http-wires.json"]["records"][0]
        with self.assertRaises(gate.GateError):
            gate.match_wire(complete, self.oracle, expected_fixture="missing")
        other = self.values["document-http-wires.json"]["records"][-1]
        with self.assertRaises(gate.GateError):
            gate.match_wire(other, self.oracle, expected_fixture="complete", secondary=False)
        gate.match_wire(other, self.oracle, expected_fixture="complete", secondary=True)

    def test_contract_factual_failure_flag_cannot_replace_actual_wrong_wire(self):
        row = self.values["document-producer.json"]["rows"][3]
        correct = wire(self.oracle, "complete", "contract_3")
        row["result_utf8"] = correct["result_utf8"]
        proof = self.values["document-contract-proof.json"]
        proof["records"][3]["result_sha256"] = sha(row["result_utf8"].encode())
        proof["producer_sha256"] = sha(pretty(self.values["document-producer.json"]))
        self.reject_bundle()

    def test_legacy_self_consistent_alteration_is_not_original_policy_compatibility(self):
        row = self.values["document-producer.json"]["rows"][1]
        request = json.loads(row["request_utf8"])
        request["context_snapshot"]["note"] = "changed policy baseline"
        row["request_utf8"] = compact(request).decode()
        proof = self.values["document-contract-proof.json"]
        proof["producer_sha256"] = sha(pretty(self.values["document-producer.json"]))
        proof["legacy_request_sha256"] = sha(row["request_utf8"].encode())
        proof["records"][1]["request_sha256"] = proof["legacy_request_sha256"]
        self.reject_bundle()

    def test_wires_descriptor_and_http_provider_join_hashes_are_independent(self):
        self.values["document-http-proof.json"]["wires"]["bytes"] += 1
        self.reject_bundle()
        self.values, self.oracle, self.phase = synthetic_bundle()
        self.values["document-server-proof.json"]["provider_records"][0]["result_sha256"] = "0" * 64
        self.reject_bundle()

    def test_expiry_order_and_phase_binding_reject_borrowed_progress(self):
        for mutation in (
            "denial_before_deadline",
            "same_time_progress",
            "wrong_attempt",
            "phase_deadline",
            "expired_provider",
        ):
            with self.subTest(mutation=mutation):
                self.values, self.oracle, self.phase = synthetic_bundle()
                expiry = self.values["document-http-proof.json"]["expiry"]
                if mutation == "denial_before_deadline":
                    expiry["denial_observed_at_ms"] = expiry["deadline_at_ms"] - 1
                elif mutation == "same_time_progress":
                    expiry["secondary_progress_observed_at_ms"] = expiry["denial_observed_at_ms"]
                elif mutation == "wrong_attempt":
                    expiry["secondary_attempt_id"] = "attempt_unrelated"
                elif mutation == "phase_deadline":
                    self.phase["deadline_at_ms"] += 1
                else:
                    self.values["document-server-proof.json"]["provider_records"][-1][
                        "attempt_id"
                    ] = self.phase["attempt_id"]
                self.reject_bundle()

    def test_record_counts_and_replies_are_closed_strict_primitives(self):
        v = self.values["document-http-proof.json"]
        v["records"][0]["requests"] = True
        self.reject_bundle()
        reply = {
            "schema_version": 1,
            "status": "passed",
            "mode": "node-producer",
            "cleanup_complete": True,
            "node_version": "24.22.2",
            "proof": "document-producer.json",
            "producer_rows": 8,
        }
        gate.validate_reply(pretty(reply), "node-producer")
        for change in ({"producer_rows": True}, {"cleanup_complete": 1}, {"raw": "SENTINEL"}):
            with self.subTest(change=change), self.assertRaises(gate.GateError):
                gate.validate_reply(pretty({**reply, **change}), "node-producer")


class DocumentFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            dir="/private/tmp", prefix="document-evidence-unit-"
        )
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def put(self, name, raw):
        p = self.root / name
        for parent in reversed(p.parents):
            if parent == self.root or self.root in parent.parents:
                parent.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        return p

    def inventory(self):
        self.put("commands/01-child/stdout.bin", b"")
        self.put("commands/01-child/stderr.bin", b"")
        self.put("package-builder/artifacts/summary.json", b'{"status":"synthetic"}\n')
        self.put(
            "package-builder/artifacts/retained-index.json", b'{"schema_version":1,"files":{}}\n'
        )
        records = {
            p.relative_to(self.root).as_posix(): {
                "bytes": p.stat().st_size,
                "sha256": sha(p.read_bytes()),
            }
            for p in self.root.rglob("*")
            if p.is_file()
        }
        raw = pretty({"schema_version": 1, "files": records})
        self.put("retained-index.json", raw)
        return raw

    def rewrite_index(self, value):
        raw = pretty(value)
        (self.root / "retained-index.json").write_bytes(raw)
        return raw

    def test_manifest_covers_nested_summaries_indexes_and_empty_captures(self):
        raw = self.inventory()
        result = gate.validate_manifest(self.root, raw)
        self.assertEqual(len(result["files"]), 4)
        self.assertIn("package-builder/artifacts/summary.json", result["files"])
        self.assertIn("package-builder/artifacts/retained-index.json", result["files"])

    def test_manifest_missing_nested_or_extra_physical_files_is_not_complete(self):
        raw = self.inventory()
        value = json.loads(raw)
        del value["files"]["package-builder/artifacts/summary.json"]
        with self.assertRaises(gate.GateError):
            gate.validate_manifest(self.root, self.rewrite_index(value))
        self.put("unexpected.bin", b"safe")
        with self.assertRaises(gate.GateError):
            gate.validate_manifest(self.root, raw)

    def test_manifest_root_self_entry_traversal_and_boolean_size_reject(self):
        raw = self.inventory()
        base = json.loads(raw)
        for key, item in (
            ("retained-index.json", {"bytes": 0, "sha256": "0" * 64}),
            ("../elsewhere", {"bytes": 0, "sha256": "0" * 64}),
            ("bad.bin", {"bytes": False, "sha256": "0" * 64}),
        ):
            value = copy.deepcopy(base)
            value["files"][key] = item
            with self.subTest(key=key), self.assertRaises(gate.GateError):
                gate.validate_manifest(self.root, self.rewrite_index(value))

    def test_public_modes_symlinks_hardlinks_and_directory_modes_reject(self):
        raw = self.inventory()
        file = self.root / "commands/01-child/stdout.bin"
        file.chmod(0o644)
        with self.assertRaises(gate.GateError):
            gate.validate_manifest(self.root, raw)
        file.chmod(0o600)
        os.link(file, self.root / "hardlink.bin")
        with self.assertRaises(gate.GateError):
            gate.validate_manifest(self.root, raw)
        (self.root / "hardlink.bin").unlink()
        (self.root / "link.bin").symlink_to(file)
        with self.assertRaises(gate.GateError):
            gate.validate_manifest(self.root, raw)
        (self.root / "link.bin").unlink()
        (self.root / "commands").chmod(0o755)
        with self.assertRaises(gate.GateError):
            gate.validate_manifest(self.root, raw)

    def test_private_read_empty_policy_bound_and_no_overwrite(self):
        p = self.put("empty.bin", b"")
        self.assertEqual(gate.read_private(p, empty=True), b"")
        with self.assertRaises(gate.GateError):
            gate.read_private(p)
        with self.assertRaises(gate.GateError):
            gate.write_private(p, b"replace")
        p = self.put("long.bin", b"1234")
        with self.assertRaises(gate.GateError):
            gate.read_private(p, maximum=3)

    def test_fresh_target_rejects_existing_or_ambiguous_artifact_family(self):
        requested = Path(".local/validation/p3-document/new.json")
        target = gate.target_path(self.root, requested)
        self.assertEqual(target, self.root / requested)
        artifact = target.with_name("new-artifacts")
        artifact.parent.mkdir(mode=0o700, parents=True)
        artifact.symlink_to(self.root / "absent")
        with self.assertRaises(gate.GateError):
            gate.target_path(self.root, requested)
        for path in (
            Path("/private/tmp/out.json"),
            Path("../out.json"),
            Path(".local/validation/p3-document/nested/out.json"),
        ):
            with self.subTest(path=path), self.assertRaises(gate.GateError):
                gate.target_path(self.root, path)

    def test_role_environment_is_explicit_and_private_without_ambient_authority(self):
        fixture = self.root / "fixtures"
        fixture.mkdir(mode=0o700)
        base = {
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "NO_COLOR": "1",
            "CI": "1",
            "COREPACK_HOME": str(self.root / "corepack"),
            "COREPACK_ENABLE_NETWORK": "0",
        }
        env = {
            **base,
            "P3_DOCUMENT_DIRECTORY": str(self.root),
            "P3_DOCUMENT_FIXTURES": str(fixture),
            "P3_DOCUMENT_TOKEN": "A" * 43,
            "P3_DOCUMENT_OTHER_TOKEN": "B" * 43,
        }
        gate.validate_environment(env, "node-server")
        gate.validate_environment(base, "build")
        for key in ("PGPASSWORD", "HTTP_PROXY", "NODE_OPTIONS", "PYTHONPATH", "OPENAI_API_KEY"):
            with self.subTest(key=key), self.assertRaises(gate.GateError):
                gate.validate_environment({**env, key: "synthetic"}, "node-server")
        for change in (
            {"CI": True},
            {"P3_DOCUMENT_OTHER_TOKEN": "A" * 43},
            {"P3_DOCUMENT_TOKEN": "A" * 42},
            {"LANG": "x\nSENTINEL"},
        ):
            with self.subTest(change=change), self.assertRaises(gate.GateError):
                gate.validate_environment({**env, **change}, "node-server")
        with self.assertRaises(gate.GateError):
            gate.validate_environment(env, "build")
        fixture.chmod(0o755)
        with self.assertRaises(gate.GateError):
            gate.validate_environment(env, "node-server")

    def test_wrong_input_error_code_does_not_reflect_private_text(self):
        for value in ([], {}, None, True, "SENTINEL_PRIVATE"):
            error = gate.GateError(value)
            self.assertEqual(error.code, "unexpected_error")
            self.assertNotIn("SENTINEL", str(error))


if __name__ == "__main__":
    unittest.main()
