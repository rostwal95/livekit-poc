"""Pure discovery codec tests; no database, provider, process or clock authority."""

from __future__ import annotations

import asyncio
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

from services.channel_policy_demo import discovery as codec


def uid(number):
    return "00000000-0000-4000-8000-" + f"{number:012d}"


def encoded(value, *, sorted_keys=False):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=sorted_keys, separators=(",", ":")
    ).encode()


def item(number=1, *, state="pending", possible=False, work=None):
    return {
        "receiptId": uid(number),
        "operationKey": uid(100 + number),
        "acceptanceSequence": str(number),
        "sourceBindingId": "sms" if number % 2 == 0 else "native",
        "state": state,
        "possibleExternal": possible,
        "externalReceiptId": work,
    }


def page(count=1, *, overflow=False):
    return {
        "schemaVersion": 1,
        "kind": "channel.policy_discovery",
        "profileId": uid(1000),
        "scope": {"tenantId": "tenant_demo", "accountId": "account_demo"},
        "caseId": "case_demo",
        "conversationId": "conversation_demo",
        "readCompletedAt": "2026-11-13T01:02:03.004Z",
        "items": [item(i + 1) for i in range(count)],
        "overflow": overflow,
        "nextCursor": str(count) if overflow else None,
    }


class DiscoveryTests(unittest.TestCase):
    def assert_bad(self, function, value):
        with self.assertRaisesRegex(codec.DiscoveryError, "^invalid_input$") as caught:
            function(value)
        self.assertEqual(caught.exception.code, "invalid_input")
        self.assertEqual(caught.exception.args, ("invalid_input",))

    def parse_bad(self, value):
        self.assert_bad(codec.parse_discovery_page, encoded(value))

    def test_request_is_closed_scope_free_and_roundtrips(self):
        request = codec.parse_discovery_request(b'{ "schemaVersion" : 1 }')
        self.assertEqual(request, codec.DiscoveryRequest())
        self.assertEqual(codec.encode_discovery_request(request), b'{"schemaVersion":1}')
        for value in (
            {"schemaVersion": True},
            {"schemaVersion": 1.0},
            {"schemaVersion": "1"},
            {"schemaVersion": 2},
            {"schemaVersion": 1, "after": "1"},
            {"schemaVersion": 1, "scope": {"tenantId": "foreign"}},
            {},
            [],
            None,
        ):
            with self.subTest(value=value):
                self.assert_bad(codec.parse_discovery_request, encoded(value))

    def test_every_supported_state_source_and_reconciliation_flag_is_an_observation(self):
        for state in ("pending", "running", "blocked", "exhausted", "uncertain"):
            for possible in (False, True):
                value = page()
                value["items"][0].update(state=state, possibleExternal=possible)
                parsed = codec.parse_discovery_page(encoded(value))
                self.assertEqual(parsed.items[0].possible_external, possible)
                self.assertEqual(json.loads(codec.encode_discovery_page(parsed)), value)
        value = page(2)
        value["items"][0].update(
            state="dispatched", possibleExternal=True, externalReceiptId=uid(200)
        )
        parsed = codec.parse_discovery_page(encoded(value))
        self.assertEqual([x.source_binding_id for x in parsed.items], ["native", "sms"])
        self.assertEqual(parsed.items[0].external_receipt_id, uid(200))

    def test_dispatched_work_truth_and_non_dispatched_null_are_strict(self):
        for state, possible, work in (
            ("dispatched", False, uid(200)),
            ("dispatched", True, None),
            ("dispatched", False, None),
            ("pending", False, uid(200)),
            ("running", True, uid(200)),
            ("uncertain", True, uid(200)),
            ("blocked", False, uid(200)),
            ("exhausted", False, uid(200)),
        ):
            value = page()
            value["items"][0].update(state=state, possibleExternal=possible, externalReceiptId=work)
            with self.subTest(state=state, possible=possible):
                self.parse_bad(value)
        self.assertEqual(len(codec.parse_discovery_page(encoded(page())).items), 1)

    def test_empty_complete_and_full_overflow_are_truthful_data(self):
        empty = codec.parse_discovery_page(encoded(page(0)))
        self.assertEqual(empty.items, ())
        full = codec.parse_discovery_page(encoded(page(16, overflow=True)))
        self.assertTrue(full.overflow)
        self.assertEqual(full.next_cursor, "16")
        self.assertEqual(len(full.items), 16)
        self.assertEqual(codec.parse_discovery_page(codec.encode_discovery_page(full)), full)
        self.assertFalse(codec.parse_discovery_page(encoded(page(16))).overflow)

    def test_overflow_never_silently_drops_entries_or_fabricates_complete_cursor(self):
        for count, overflow, cursor in (
            (17, False, None),
            (0, True, None),
            (15, True, "15"),
            (16, True, None),
            (16, True, "15"),
            (1, False, "1"),
            (16, False, "16"),
        ):
            value = page(count)
            value.update(overflow=overflow, nextCursor=cursor)
            with self.subTest(count=count, overflow=overflow, cursor=cursor):
                self.parse_bad(value)

    def test_sequences_remain_lossless_canonical_positive_i64(self):
        value = page()
        value["items"][0]["acceptanceSequence"] = "9223372036854775807"
        self.assertEqual(
            codec.parse_discovery_page(encoded(value)).items[0].acceptance_sequence,
            "9223372036854775807",
        )
        full = page(16, overflow=True)
        for index, row in enumerate(full["items"]):
            row["acceptanceSequence"] = str(9223372036854775807 - 15 + index)
        full["nextCursor"] = "9223372036854775807"
        self.assertEqual(
            codec.parse_discovery_page(encoded(full)).next_cursor, "9223372036854775807"
        )
        for sequence in (
            "0",
            "01",
            "+1",
            "-1",
            " 1",
            "1 ",
            "1.0",
            "1e3",
            "9223372036854775808",
            "99999999999999999999",
            "\u0661",
            True,
            1,
            1.0,
            None,
        ):
            value["items"][0]["acceptanceSequence"] = sequence
            with self.subTest(sequence=sequence):
                self.parse_bad(value)

    def test_order_is_strictly_increasing_but_gaps_are_preserved(self):
        value = page(3)
        for row, sequence in zip(value["items"], ["1", "12", "9007199254740993"], strict=True):
            row["acceptanceSequence"] = sequence
        self.assertEqual(
            [x.acceptance_sequence for x in codec.parse_discovery_page(encoded(value)).items],
            ["1", "12", "9007199254740993"],
        )
        for sequence in ("12", "1"):
            value["items"][2]["acceptanceSequence"] = sequence
            self.parse_bad(value)

    def test_duplicate_input_operation_or_nonnull_work_never_aliases_an_item(self):
        for field in ("receiptId", "operationKey", "externalReceiptId"):
            value = page(2)
            if field == "externalReceiptId":
                for row in value["items"]:
                    row.update(
                        state="dispatched", possibleExternal=True, externalReceiptId=uid(200)
                    )
            else:
                value["items"][1][field] = value["items"][0][field]
            with self.subTest(field=field):
                self.parse_bad(value)

    def test_unknown_missing_nested_fields_versions_and_bool_fields_reject(self):
        for mutation in (
            "top_extra",
            "top_missing",
            "scope_extra",
            "item_extra",
            "item_missing",
            "bool_version",
            "float_version",
            "kind",
            "overflow_int",
            "possible_int",
            "state",
            "source",
            "cursor_bool",
        ):
            value = page()
            if mutation == "top_extra":
                value["authority"] = True
            elif mutation == "top_missing":
                del value["readCompletedAt"]
            elif mutation == "scope_extra":
                value["scope"]["caseId"] = "foreign"
            elif mutation == "item_extra":
                value["items"][0]["body"] = "PRIVATE_BODY_SENTINEL"
            elif mutation == "item_missing":
                del value["items"][0]["externalReceiptId"]
            elif mutation == "bool_version":
                value["schemaVersion"] = True
            elif mutation == "float_version":
                value["schemaVersion"] = 1.0
            elif mutation == "kind":
                value["kind"] = "channel.execution_permission"
            elif mutation == "overflow_int":
                value["overflow"] = 0
            elif mutation == "possible_int":
                value["items"][0]["possibleExternal"] = 1
            elif mutation == "state":
                value["items"][0]["state"] = "completed"
            elif mutation == "source":
                value["items"][0]["sourceBindingId"] = "model_selected"
            else:
                value["nextCursor"] = True
            with self.subTest(mutation=mutation):
                self.parse_bad(value)

    def test_uuid4_and_p3_identifier_intersection_are_validated_without_coercion(self):
        for invalid in (
            uid(1).upper().replace("00000000", "AAAAAAAA", 1),
            "00000000-0000-1000-8000-000000000001",
            "00000000000040008000000000000001",
            "{00000000-0000-4000-8000-000000000001}",
            True,
            None,
            "PRIVATE_UUID_SENTINEL",
        ):
            value = page()
            value["items"][0]["receiptId"] = invalid
            self.parse_bad(value)
        for field in ("caseId", "conversationId"):
            for invalid in ("A", "1case", "a" * 65, "a.b", "a\n", "café", "a\ud800", True):
                value = page()
                value[field] = invalid
                if isinstance(invalid, str) and "\ud800" in invalid:
                    self.assert_bad(codec.parse_discovery_page, json.dumps(value).encode())
                else:
                    self.parse_bad(value)
        value = page()
        value["scope"] = {"tenantId": "a" * 64, "accountId": "b" * 64}
        value.update(caseId="c" * 64, conversationId="d" * 64)
        self.assertEqual(codec.parse_discovery_page(encoded(value)).case_id, "c" * 64)

    def test_timestamp_is_exact_valid_utc_milliseconds_and_grants_no_clock_permission(self):
        for stamp in (
            "0001-01-01T00:00:00.000Z",
            "2000-02-29T12:34:56.789Z",
            "9999-12-31T23:59:59.999Z",
        ):
            value = page()
            value["readCompletedAt"] = stamp
            self.assertEqual(codec.parse_discovery_page(encoded(value)).read_completed_at, stamp)
        for stamp in (
            "2026-11-13T01:02:03Z",
            "2026-11-13T01:02:03.00Z",
            "2026-11-13T01:02:03.0000Z",
            "2026-11-13T01:02:03.000+00:00",
            "2026-11-13t01:02:03.000z",
            "2026-02-29T01:02:03.000Z",
            "2026-02-30T01:02:03.000Z",
            "2026-11-13T24:02:03.000Z",
            "2026-11-13T24:00:00.000Z",
            "2026-11-13T24:00:00.001Z",
            "2026-11-13T01:02:60.000Z",
            "0000-01-01T00:00:00.000Z",
            True,
        ):
            value["readCompletedAt"] = stamp
            with self.subTest(stamp=stamp):
                self.parse_bad(value)

    def test_exact_raw_byte_caps_and_utf8_errors_are_rejected(self):
        request = b'{"schemaVersion":1}'
        self.assertEqual(
            codec.parse_discovery_request(request + b" " * (1024 - len(request))),
            codec.DiscoveryRequest(),
        )
        self.assert_bad(codec.parse_discovery_request, request + b" " * (1025 - len(request)))
        raw = encoded(page())
        self.assertEqual(len(codec.parse_discovery_page(raw + b" " * (8192 - len(raw))).items), 1)
        self.assert_bad(codec.parse_discovery_page, raw + b" " * (8193 - len(raw)))
        for invalid in (
            b"",
            b"\xff",
            b"\xed\xa0\x80",
            b"\xef\xbb\xbf{}",
            b"{} {}",
            bytearray(request),
            memoryview(request),
            "PRIVATE_RAW_SENTINEL",
        ):
            self.assert_bad(codec.parse_discovery_request, invalid)

    def test_duplicate_json_keys_nonfinite_values_and_malformed_json_are_finite_errors(self):
        for raw in (
            b'{"schemaVersion":1,"schemaVersion":1}',
            b'{"schemaVersion":NaN}',
            b'{"schemaVersion":Infinity}',
            b'{"schemaVersion":-Infinity}',
            b'{"schemaVersion":1,}',
            b'[{"schemaVersion":1}]',
        ):
            self.assert_bad(codec.parse_discovery_request, raw)
        raw = encoded(page()).replace(
            b'"tenantId":"tenant_demo"', b'"tenantId":"tenant_demo","tenantId":"tenant_demo"'
        )
        self.assert_bad(codec.parse_discovery_page, raw)
        self.assert_bad(codec.parse_discovery_page, b"[" * 2000 + b"]" * 2000)

    def test_sorted_json_roundtrip_and_scope_construction_order_do_not_select_authority(self):
        first = codec.DiscoveryScope(tenant_id="tenant_demo", account_id="account_demo")
        second = codec.DiscoveryScope(account_id="account_demo", tenant_id="tenant_demo")
        self.assertEqual(first, second)
        for scope in (first, second):
            value = codec.parse_discovery_page(encoded(page(2), sorted_keys=True))
            value = replace(value, scope=scope)
            sorted_wire = encoded(json.loads(codec.encode_discovery_page(value)), sorted_keys=True)
            self.assertEqual(codec.parse_discovery_page(sorted_wire), value)
            self.assertEqual(json.loads(sorted_wire)["scope"], page()["scope"])

    def test_frozen_records_copy_scope_items_and_external_containers(self):
        raw = page(2)
        parsed = codec.parse_discovery_page(encoded(raw))
        with self.assertRaises(FrozenInstanceError):
            parsed.case_id = "changed"
        with self.assertRaises(FrozenInstanceError):
            parsed.scope.tenant_id = "changed"
        with self.assertRaises(FrozenInstanceError):
            parsed.items[0].state = "blocked"
        source_scope = codec.DiscoveryScope("tenant_demo", "account_demo")
        source_item = codec.DiscoveryItem(uid(1), uid(101), "1", "native", "pending", False, None)
        source_items = [source_item]
        copied = codec.DiscoveryPage(
            uid(1000),
            source_scope,
            "case_demo",
            "conversation_demo",
            "2026-11-13T01:02:03.004Z",
            source_items,
            False,
            None,
        )
        before = codec.encode_discovery_page(copied)
        source_items.clear()
        object.__setattr__(source_scope, "tenant_id", "foreign")
        object.__setattr__(source_item, "state", "exhausted")
        raw["items"][0]["state"] = "blocked"
        self.assertEqual(codec.encode_discovery_page(copied), before)
        self.assertIs(type(copied.items), tuple)
        self.assertIsNot(copied.scope, source_scope)
        self.assertIsNot(copied.items[0], source_item)

    def test_encoders_revalidate_records_even_after_frozen_bypass_mutation(self):
        for field, invalid in (
            ("schema_version", True),
            ("kind", "other"),
            ("profile_id", uid(1).replace("4000", "1000")),
            ("overflow", 1),
            ("next_cursor", "1"),
            ("case_id", "X"),
            ("read_completed_at", "2030-01-01"),
        ):
            parsed = codec.parse_discovery_page(encoded(page()))
            object.__setattr__(parsed, field, invalid)
            self.assert_bad(codec.encode_discovery_page, parsed)
        parsed = codec.parse_discovery_page(encoded(page()))
        object.__setattr__(parsed.items[0], "possible_external", 1)
        self.assert_bad(codec.encode_discovery_page, parsed)
        request = codec.DiscoveryRequest()
        object.__setattr__(request, "schema_version", False)
        self.assert_bad(codec.encode_discovery_request, request)
        self.assertEqual(
            codec.encode_discovery_request(codec.DiscoveryRequest()), b'{"schemaVersion":1}'
        )

    def test_foreign_getter_objects_and_container_subclasses_are_not_inspected(self):
        class Getters:
            def __getattribute__(self, name):
                raise AssertionError("PRIVATE_GETTER_SENTINEL")

        class ListSubclass(list):
            def __iter__(self):
                raise AssertionError("PRIVATE_ITERATOR_SENTINEL")

        self.assert_bad(codec.encode_discovery_page, Getters())
        self.assert_bad(codec.encode_discovery_request, Getters())
        self.assert_bad(codec.parse_discovery_page, Getters())
        parsed = codec.parse_discovery_page(encoded(page()))
        object.__setattr__(parsed, "scope", Getters())
        self.assert_bad(codec.encode_discovery_page, parsed)
        parsed = codec.parse_discovery_page(encoded(page()))
        object.__setattr__(parsed, "items", ListSubclass())
        self.assert_bad(codec.encode_discovery_page, parsed)

    def test_encoders_contain_missing_slots_in_forged_public_records(self):
        self.assert_bad(codec.encode_discovery_request, object.__new__(codec.DiscoveryRequest))
        self.assert_bad(codec.encode_discovery_page, object.__new__(codec.DiscoveryPage))
        for field, value in (
            ("scope", object.__new__(codec.DiscoveryScope)),
            ("items", (object.__new__(codec.DiscoveryItem),)),
        ):
            parsed = codec.parse_discovery_page(encoded(page()))
            object.__setattr__(parsed, field, value)
            self.assert_bad(codec.encode_discovery_page, parsed)
        self.assertEqual(
            codec.parse_discovery_page(
                codec.encode_discovery_page(codec.parse_discovery_page(encoded(page())))
            ).profile_id,
            uid(1000),
        )

    def test_direct_constructors_reject_invalid_or_unsafe_values(self):
        self.assert_bad(lambda value: codec.DiscoveryScope(value, "account"), True)
        self.assert_bad(lambda value: codec.DiscoveryRequest(value), True)
        self.assert_bad(
            lambda value: codec.DiscoveryItem(uid(1), uid(2), "1", "native", value, False, None),
            "PRIVATE_STATE_SENTINEL",
        )
        parsed = codec.parse_discovery_page(encoded(page(2)))
        self.assert_bad(lambda value: replace(parsed, items=value), tuple(reversed(parsed.items)))
        self.assert_bad(
            lambda value: replace(parsed, scope=value),
            {"tenant_id": "tenant_demo", "account_id": "account_demo"},
        )

    def test_errors_never_reflect_private_json_or_underlying_exception_text(self):
        raw = b'{"schemaVersion":1,"PRIVATE_FIELD_SENTINEL":"PRIVATE_BODY_SENTINEL"}'
        with self.assertRaises(codec.DiscoveryError) as caught:
            codec.parse_discovery_request(raw)
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertEqual(str(caught.exception), "invalid_input")
        self.assertNotIn("PRIVATE_", rendered)
        value = page()
        value["profileId"] = "PRIVATE_UUID_SENTINEL".ljust(36, "x")
        with self.assertRaises(codec.DiscoveryError) as caught:
            codec.parse_discovery_page(encoded(value))
        self.assertNotIn("PRIVATE_UUID", "".join(traceback.format_exception(caught.exception)))

    def test_prepared_route_constants_never_add_a_second_body_or_permission_field(self):
        self.assertEqual(
            (codec.REQUEST_BYTES, codec.PAGE_BYTES, codec.PAGE_ITEMS), (1024, 8192, 16)
        )
        self.assertEqual(
            (codec.PREPARED_FRAME_BYTES, codec.PREPARED_FOUND_STATUS, codec.PREPARED_ABSENT_STATUS),
            (32768, 200, 204),
        )
        value = page()
        value["items"][0]["prepared"] = {"body": "must stay in P2"}
        self.parse_bad(value)

    def test_import_is_inert_without_network_process_task_environment_or_logging_configuration(
        self,
    ):
        filename = Path(codec.__file__)
        spec = importlib.util.spec_from_file_location(
            "channel_policy_discovery_inert_probe", filename
        )
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            with (
                patch.object(socket, "socket", side_effect=AssertionError("socket")),
                patch.object(subprocess, "Popen", side_effect=AssertionError("process")),
                patch.object(asyncio, "create_task", side_effect=AssertionError("task")),
                patch.object(os, "getenv", side_effect=AssertionError("environment")),
                patch.object(logging, "basicConfig", side_effect=AssertionError("logging")),
            ):
                spec.loader.exec_module(module)
            self.assertEqual(module.REQUEST_BYTES, 1024)
        finally:
            sys.modules.pop(spec.name, None)
        self.assertEqual(
            codec.parse_discovery_request(b'{"schemaVersion":1}'), codec.DiscoveryRequest()
        )
