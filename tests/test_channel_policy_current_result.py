"""Pure current-result wire controls; no current-grant or applicability authority."""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import importlib.util
import json
import logging
import os
import socket
import subprocess
import sys
import traceback
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import patch

from services.channel_policy_demo import current_result as codec
from services.channel_policy_demo.discovery import DiscoveryScope

ROOT = Path(__file__).resolve().parents[1]
T = 1900000000000


def uid(number):
    return "00000000-0000-4000-8000-" + f"{number:012d}"


def encoded(value, *, sorted_keys=False):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=sorted_keys, separators=(",", ":")
    ).encode()


def observation(body=b'{"result_schema_version":3,"synthetic":true}'):
    digest = hashlib.sha256(body).hexdigest()
    return {
        "schemaVersion": 1,
        "kind": "channel.policy_current_result",
        "profileId": uid(1),
        "scope": {"tenantId": "tenant_demo", "accountId": "account_demo"},
        "caseId": "case_demo",
        "conversationId": "conversation_demo",
        "readCompletedAt": "2026-11-13T01:02:03.009Z",
        "state": "current",
        "result": {
            "inputReceiptId": uid(2),
            "operationKey": uid(3),
            "intent": {
                "delivery_id": uid(4),
                "scope": {"tenant_id": "tenant_demo", "account_id": "account_demo"},
                "work_id": uid(5),
                "attempt_id": uid(6),
                "result_sha256": digest,
                "receiver_id": uid(7),
                "recipient_id": "recipient_demo",
                "body": base64.b64encode(body).decode(),
                "prepared_at_ms": T,
            },
            "receipt": {
                "delivery_id": uid(4),
                "receipt_id": uid(8),
                "receiver_id": uid(7),
                "recipient_id": "recipient_demo",
                "result_sha256": digest,
                "accepted_at_ms": T + 1,
            },
            "case": {"source": "p1_public_v4", "revision": "2"},
            "observed": {
                "p2ObservedAt": "2026-11-13T01:02:03.001Z",
                "caseObservedAt": "2026-11-13T01:02:03.002Z",
                "disclosureAdmittedAt": "2026-11-13T01:02:03.003Z",
                "atomic": False,
            },
        },
    }


class CurrentResultTests(unittest.TestCase):
    def bad(self, value):
        with self.assertRaisesRegex(codec.CurrentResultError, "^invalid_input$") as caught:
            codec.parse_current_result_observation(encoded(value))
        self.assertEqual(caught.exception.args, ("invalid_input",))
        self.assertEqual(caught.exception.code, "invalid_input")

    def test_closed_scope_free_request_never_accepts_browser_selected_authority(self):
        value = codec.parse_current_result_request(b'{"schemaVersion":1}')
        self.assertEqual(value, codec.CurrentResultRequest())
        self.assertEqual(codec.encode_current_result_request(value), b'{"schemaVersion":1}')
        for extra in (
            {"scope": {}},
            {"deliveryId": uid(1)},
            {"nativeGrant": "private"},
            {"operationKey": uid(2)},
        ):
            with self.subTest(extra=extra), self.assertRaises(codec.CurrentResultError):
                codec.parse_current_result_request(encoded({"schemaVersion": 1, **extra}))
        for version in (True, 1.0, "1", 0, 2, None):
            with self.subTest(version=version), self.assertRaises(codec.CurrentResultError):
                codec.parse_current_result_request(encoded({"schemaVersion": version}))

    def test_current_roundtrip_preserves_public_intent_receipt_and_original_source_ids(self):
        wire = observation()
        parsed = codec.parse_current_result_observation(encoded(wire))
        self.assertEqual(json.loads(codec.encode_current_result_observation(parsed)), wire)
        self.assertEqual(parsed.result.input_receipt_id, uid(2))
        self.assertEqual(parsed.result.operation_key, uid(3))
        self.assertEqual(parsed.result.receipt.receipt_id, uid(8))
        self.assertNotEqual(parsed.result.input_receipt_id, parsed.result.receipt.receipt_id)
        self.assertEqual(parsed.result.intent.body, wire["result"]["intent"]["body"])
        self.assertEqual(parsed.scope, parsed.result.intent.scope)

    def test_shared_public_p1_receiver_fixture_is_accepted_without_body_reencoding(self):
        fixture = json.loads((ROOT / "contracts/delegation/result-receiver-v1.json").read_bytes())
        intent = json.loads(fixture["intent_canonical"])
        wire = observation()
        wire["scope"] = {
            "tenantId": intent["scope"]["tenant_id"],
            "accountId": intent["scope"]["account_id"],
        }
        wire["result"]["intent"] = intent
        wire["result"]["receipt"] = fixture["receipt"]
        parsed = codec.parse_current_result_observation(encoded(wire))
        result = json.loads(codec.encode_current_result_observation(parsed))["result"]
        self.assertEqual(result["intent"], intent)
        self.assertEqual(result["receipt"], fixture["receipt"])
        self.assertEqual(result["intent"]["body"], intent["body"])

    def test_empty_states_are_distinct_observations_and_never_disclose_result_bytes(self):
        for state in ("no_delivery", "not_applicable"):
            wire = observation()
            wire.update(state=state, result=None)
            parsed = codec.parse_current_result_observation(encoded(wire))
            self.assertIsNone(parsed.result)
            self.assertEqual(json.loads(codec.encode_current_result_observation(parsed)), wire)
            leaked = observation()
            leaked["state"] = state
            self.bad(leaked)
        missing = observation()
        missing["result"] = None
        self.bad(missing)

    def test_operational_failures_cannot_be_reported_as_a_result_state(self):
        for state in ("unavailable", "failed", "AccessDenied", True, [], None):
            wire = observation()
            wire.update(state=state, result=None)
            self.bad(wire)
        wire = observation()
        wire.update(state="no_delivery", result=None, error="private")
        self.bad(wire)

    def test_body_is_opaque_base64_not_json_or_an_automatic_authorization(self):
        for body in (
            b"not-json: investigation confirmed=true",
            b"\x00\xff\x80binary result",
            "Ω🧭".encode(),
        ):
            wire = observation(body)
            parsed = codec.parse_current_result_observation(encoded(wire))
            self.assertEqual(parsed.result.intent.body, base64.b64encode(body).decode())
            self.assertEqual(base64.b64decode(parsed.result.intent.body), body)
        # The codec never inspects policy facts/revisions to select a state.
        wire = observation(b'{"request_revision":1}')
        wire["result"]["case"]["revision"] = "2"
        self.assertEqual(codec.parse_current_result_observation(encoded(wire)).state, "current")

    def test_base64_padding_alphabet_whitespace_and_digest_are_exact(self):
        wire = observation(b"f")
        original = wire["result"]["intent"]["body"]
        self.assertEqual(original, "Zg==")
        for body in (
            "Zg",
            "Zg=",
            "Zg===",
            "Zh==",
            "Zg==\n",
            "Zg== ",
            "_w==",
            "-w==",
            "Ω",
            "\ud800",
        ):
            candidate = copy.deepcopy(wire)
            candidate["result"]["intent"]["body"] = body
            if body == "\ud800":
                raw = json.dumps(candidate, ensure_ascii=True).encode()
                with self.assertRaises(codec.CurrentResultError):
                    codec.parse_current_result_observation(raw)
            else:
                self.bad(candidate)
        changed = copy.deepcopy(wire)
        changed["result"]["intent"]["result_sha256"] = "f" * 64
        self.bad(changed)

    def test_full_8192_decoded_bytes_are_preserved_and_empty_or_oversized_are_denied(self):
        body = b"\x00\xff" * 4096
        wire = observation(body)
        parsed = codec.parse_current_result_observation(encoded(wire))
        self.assertEqual(base64.b64decode(parsed.result.intent.body), body)
        self.assertEqual(len(parsed.result.intent.body), 10924)
        self.assertEqual(json.loads(codec.encode_current_result_observation(parsed)), wire)
        for body in (b"", b"x" * 8193):
            self.bad(observation(body))
        self.assertEqual(
            (codec.RESULT_BODY_BYTES, codec.RESULT_INTENT_BYTES, codec.CURRENT_RESULT_BYTES),
            (8192, 16384, 32768),
        )

    def test_enclosing_frame_and_request_bounds_are_independent_of_decoded_body_size(self):
        raw = encoded(observation(b"x" * 8192))
        self.assertLess(len(raw), codec.CURRENT_RESULT_BYTES)
        padded = b" " * (codec.CURRENT_RESULT_BYTES - len(raw)) + raw
        self.assertEqual(codec.parse_current_result_observation(padded).state, "current")
        with self.assertRaises(codec.CurrentResultError):
            codec.parse_current_result_observation(b" " + padded)
        request = b'{"schemaVersion":1}'
        padded = b" " * (1024 - len(request)) + request
        self.assertEqual(codec.parse_current_result_request(padded), codec.CurrentResultRequest())
        with self.assertRaises(codec.CurrentResultError):
            codec.parse_current_result_request(b" " + padded)

    def test_all_intent_receipt_identity_and_sha_joins_are_mandatory(self):
        for field, value in (
            ("delivery_id", uid(10)),
            ("receiver_id", uid(11)),
            ("recipient_id", "other_recipient"),
            ("result_sha256", "f" * 64),
        ):
            wire = observation()
            wire["result"]["receipt"][field] = value
            self.bad(wire)
        wire = observation()
        wire["scope"]["accountId"] = "foreign_account"
        self.bad(wire)

    def test_all_uuid_fields_require_canonical_lowercase_version_four(self):
        for path in (
            ("profileId",),
            ("result", "inputReceiptId"),
            ("result", "operationKey"),
            ("result", "intent", "work_id"),
            ("result", "intent", "attempt_id"),
            ("result", "receipt", "receipt_id"),
        ):
            for bad in (
                "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
                "00000000-0000-1000-8000-000000000001",
                "00000000-0000-4000-7000-000000000001",
                uid(1) + "\n",
                None,
            ):
                wire = observation()
                selected = wire
                for key in path[:-1]:
                    selected = selected[key]
                selected[path[-1]] = bad
                with self.subTest(path=path, bad=bad):
                    self.bad(wire)

    def test_p1_identifier_intersection_is_preserved_without_truncation_or_case_folding(self):
        wire = observation()
        maximum = "a" * 64
        wire["scope"] = {"tenantId": maximum, "accountId": maximum}
        wire["caseId"] = wire["conversationId"] = maximum
        wire["result"]["intent"]["scope"] = {"tenant_id": maximum, "account_id": maximum}
        wire["result"]["intent"]["recipient_id"] = wire["result"]["receipt"]["recipient_id"] = (
            maximum
        )
        self.assertEqual(codec.parse_current_result_observation(encoded(wire)).case_id, maximum)
        for value in ("a" * 65, "Uppercase", "colon:id", "dot.id", "\ud800"):
            wire = observation()
            wire["caseId"] = value
            raw = json.dumps(wire, ensure_ascii=True).encode()
            with self.assertRaises(codec.CurrentResultError):
                codec.parse_current_result_observation(raw)

    def test_p1_millisecond_domain_never_coerces_bools_floats_or_out_of_range_values(self):
        for edge in (0, 4102444800000):
            wire = observation()
            wire["result"]["intent"]["prepared_at_ms"] = edge
            wire["result"]["receipt"]["accepted_at_ms"] = edge
            self.assertEqual(
                codec.parse_current_result_observation(encoded(wire)).result.receipt.accepted_at_ms,
                edge,
            )
        for path in ("intent", "receipt"):
            field = "prepared_at_ms" if path == "intent" else "accepted_at_ms"
            for value in (-1, 4102444800001, True, 1.0, "1"):
                wire = observation()
                wire["result"][path][field] = value
                self.bad(wire)

    def test_current_case_revision_is_the_lossless_public_p2_domain(self):
        for value in ("0", "1", "1000001", "9223372036854775807"):
            wire = observation()
            wire["result"]["case"]["revision"] = value
            self.assertEqual(
                codec.parse_current_result_observation(encoded(wire)).result.case.revision, value
            )
        for value in ("01", "-1", "9223372036854775808", "1.0", 1, True, None):
            wire = observation()
            wire["result"]["case"]["revision"] = value
            self.bad(wire)
        wire = observation()
        wire["result"]["case"]["source"] = "standalone_reference_v1"
        self.bad(wire)

    def test_native_observations_are_non_atomic_and_do_not_invent_cross_clock_order(self):
        wire = observation()
        wire["result"]["observed"].update(
            p2ObservedAt="2026-11-13T01:02:04.001Z", caseObservedAt="2026-11-13T01:02:02.001Z"
        )
        self.assertFalse(
            codec.parse_current_result_observation(encoded(wire)).result.observed.atomic
        )
        for value in (True, 0, "false", None):
            candidate = copy.deepcopy(wire)
            candidate["result"]["observed"]["atomic"] = value
            self.bad(candidate)

    def test_all_timestamps_require_valid_exact_utc_milliseconds(self):
        for value in (
            "2026-11-13T01:02:03Z",
            "2026-11-13T01:02:03.000000Z",
            "2026-11-13T01:02:03.000+00:00",
            "2026-02-29T01:02:03.000Z",
            "2026-11-13T24:00:00.000Z",
            True,
        ):
            for path in (
                "readCompletedAt",
                "p2ObservedAt",
                "caseObservedAt",
                "disclosureAdmittedAt",
            ):
                wire = observation()
                if path == "readCompletedAt":
                    wire[path] = value
                else:
                    wire["result"]["observed"][path] = value
                self.bad(wire)
        wire = observation()
        wire["readCompletedAt"] = "2000-02-29T01:02:03.000Z"
        self.assertEqual(
            codec.parse_current_result_observation(encoded(wire)).read_completed_at,
            wire["readCompletedAt"],
        )

    def test_every_object_is_closed_including_nested_scope_and_observation(self):
        for path in (
            (),
            ("scope",),
            ("result",),
            ("result", "intent"),
            ("result", "intent", "scope"),
            ("result", "receipt"),
            ("result", "case"),
            ("result", "observed"),
        ):
            wire = observation()
            selected = wire
            for key in path:
                selected = selected[key]
            selected["mutation_authority"] = "PRIVATE_EXTRA"
            with self.subTest(path=path):
                self.bad(wire)
            wire = observation()
            selected = wire
            for key in path:
                selected = selected[key]
            selected.pop(next(iter(selected)))
            with self.subTest(missing=path):
                self.bad(wire)

    def test_duplicate_json_keys_nonfinite_invalid_utf8_and_bad_roots_are_rejected(self):
        raw = encoded(observation())
        for bad in (
            b"",
            b"\xff",
            b"null",
            b"[]",
            raw.replace(b'"schemaVersion":1', b'"schemaVersion":1,"schemaVersion":1', 1),
            raw.replace(b'"accepted_at_ms":1900000000001', b'"accepted_at_ms":NaN'),
            raw.replace(b'"accepted_at_ms":1900000000001', b'"accepted_at_ms":Infinity'),
        ):
            with self.subTest(raw_bytes=len(bad)), self.assertRaises(codec.CurrentResultError):
                codec.parse_current_result_observation(bad)

    def test_sorted_persisted_json_scope_order_and_whitespace_preserve_original_body(self):
        wire = observation('{\n  "original": "UTF8 Ω"\n}'.encode())
        sorted_raw = encoded(wire, sorted_keys=True)
        self.assertEqual(list(json.loads(sorted_raw)["scope"]), ["accountId", "tenantId"])
        parsed = codec.parse_current_result_observation(b"\n " + sorted_raw + b" \n")
        self.assertEqual(json.loads(codec.encode_current_result_observation(parsed)), wire)
        self.assertEqual(parsed.result.intent.body, wire["result"]["intent"]["body"])

    def test_records_copy_nested_owners_and_remain_frozen_after_external_changes(self):
        parsed = codec.parse_current_result_observation(encoded(observation()))
        scope = DiscoveryScope("tenant_demo", "account_demo")
        intent = replace(parsed.result.intent, scope=scope)
        projection = replace(parsed.result, intent=intent)
        current = replace(parsed, scope=scope, result=projection)
        self.assertIsNot(current.scope, scope)
        self.assertIsNot(current.result, projection)
        self.assertIsNot(current.result.intent, intent)
        self.assertIsNot(current.result.intent.scope, intent.scope)
        original = codec.encode_current_result_observation(current)
        object.__setattr__(scope, "account_id", "foreign")
        object.__setattr__(intent, "body", "PRIVATE_BAD_BODY")
        object.__setattr__(projection, "operation_key", "changed")
        self.assertEqual(codec.encode_current_result_observation(current), original)
        with self.assertRaises(FrozenInstanceError):
            current.state = "not_applicable"

    def test_encoders_revalidate_frozen_bypass_mutation_in_every_public_record(self):
        for mutate in (
            lambda value: object.__setattr__(value, "schema_version", True),
            lambda value: object.__setattr__(value, "state", "no_delivery"),
            lambda value: object.__setattr__(value.result.intent, "body", "bad"),
            lambda value: object.__setattr__(value.result.receipt, "delivery_id", uid(99)),
            lambda value: object.__setattr__(value.result.case, "source", "private"),
            lambda value: object.__setattr__(value.result.observed, "atomic", True),
        ):
            parsed = codec.parse_current_result_observation(encoded(observation()))
            mutate(parsed)
            with self.assertRaises(codec.CurrentResultError):
                codec.encode_current_result_observation(parsed)
        request = codec.CurrentResultRequest()
        object.__setattr__(request, "schema_version", 1.0)
        with self.assertRaises(codec.CurrentResultError):
            codec.encode_current_result_request(request)

    def test_foreign_getters_and_forged_missing_slots_are_not_inspected_or_leaked(self):
        class Foreign:
            @property
            def scope(self):
                raise AssertionError("PRIVATE_GETTER")

            @property
            def schema_version(self):
                raise AssertionError("PRIVATE_GETTER")

        for method in (
            codec.encode_current_result_request,
            codec.encode_current_result_observation,
        ):
            with self.assertRaises(codec.CurrentResultError):
                method(Foreign())
        parsed = codec.parse_current_result_observation(encoded(observation()))
        for cls, field in (
            (codec.CurrentResultProjection, "result"),
            (codec.CurrentResultIntent, "intent"),
            (codec.CurrentResultReceipt, "receipt"),
            (codec.CurrentResultCase, "case"),
            (codec.CurrentResultObserved, "observed"),
        ):
            current = codec.parse_current_result_observation(encoded(observation()))
            owner = current if field == "result" else current.result
            object.__setattr__(owner, field, object.__new__(cls))
            with self.assertRaises(codec.CurrentResultError):
                codec.encode_current_result_observation(current)
        for cls, method in (
            (codec.CurrentResultRequest, codec.encode_current_result_request),
            (codec.CurrentResultObservation, codec.encode_current_result_observation),
        ):
            with self.assertRaises(codec.CurrentResultError):
                method(object.__new__(cls))
        with self.assertRaises(codec.CurrentResultError):
            replace(parsed, scope=Foreign())

    def test_safe_diagnostics_and_repr_do_not_expose_private_body(self):
        body = b"PRIVATE_RESULT_BYTES_SENTINEL"
        wire = observation(body)
        parsed = codec.parse_current_result_observation(encoded(wire))
        self.assertNotIn(body.decode(), repr(parsed))
        self.assertNotIn(base64.b64encode(body).decode(), repr(parsed))
        wire["result"]["intent"]["result_sha256"] = "PRIVATE_DIGEST_SENTINEL"
        try:
            codec.parse_current_result_observation(encoded(wire))
        except codec.CurrentResultError as error:
            self.assertEqual(error.args, ("invalid_input",))
            self.assertNotIn("PRIVATE_", "".join(traceback.format_exception(error)))
        else:
            self.fail("invalid digest accepted")

    def test_import_starts_no_io_environment_read_task_or_logging_configuration(self):
        name = "services.channel_policy_demo.current_result_inert_probe"
        spec = importlib.util.spec_from_file_location(name, codec.__file__)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            with (
                patch.object(socket, "socket", side_effect=AssertionError("socket")),
                patch.object(subprocess, "Popen", side_effect=AssertionError("process")),
                patch.object(asyncio, "create_task", side_effect=AssertionError("task")),
                patch.object(os, "getenv", side_effect=AssertionError("environment")),
                patch.object(logging, "basicConfig", side_effect=AssertionError("logging")),
            ):
                spec.loader.exec_module(module)
            self.assertEqual(module.CURRENT_RESULT_BYTES, 32768)
            self.assertEqual(
                module.parse_current_result_request(b'{"schemaVersion":1}').schema_version, 1
            )
        finally:
            sys.modules.pop(name, None)
        self.assertEqual(
            codec.parse_current_result_observation(encoded(observation())).state, "current"
        )


if __name__ == "__main__":
    unittest.main()
