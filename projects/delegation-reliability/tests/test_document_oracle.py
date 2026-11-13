"""Independent document fixture facts and public codec checks; reviewed 12 November 2026.

This is a test-only literal oracle, not OCR or a production authority. The PNG
reference decoder is independent of the TypeScript worker. No provider is called.
"""

from __future__ import annotations

import copy
import hashlib
import json
import struct
import unittest
import zlib
from pathlib import Path
from typing import Any

from delegation_reliability.contracts import ContractError, canonical
from delegation_reliability.document_contracts import (
    DOCUMENT_FIELDS,
    encode_document_request,
    encode_document_result,
    match_document_result,
    parse_document_request,
    parse_document_result,
    produce_document_request,
)

ROOT = Path(__file__).resolve().parents[3]
DIRECTORY = ROOT / "contracts" / "delegation"
FIELDS = ("booking_reference", "property_name", "check_in", "check_out")


def assert_fixture_result(payload: dict[str, Any], expected: dict[str, Any]) -> None:
    """Compare parsed facts with literal image truth; never grant authority."""
    try:
        assert payload["outcome"] == expected["outcome"]
        assert set(payload["fields"]) == set(FIELDS)
        reference = expected["source"]
        for name in FIELDS:
            actual = payload["fields"][name]
            literal = expected["fields"][name]
            assert set(actual) == {"state", "value", "evidence_refs"}
            assert actual["state"] == literal["state"]
            assert type(actual["value"]) is type(literal["value"])
            assert actual["value"] == literal["value"]
            assert len(actual["evidence_refs"]) == len(literal["regions"])
            for witness, region in zip(actual["evidence_refs"], literal["regions"], strict=True):
                assert set(witness) == {"source_id", "version", "sha256", "region"}
                assert all(
                    witness[key] == reference[key] for key in ("source_id", "version", "sha256")
                )
                assert set(witness["region"]) == {"x", "y", "width", "height"}
                assert all(type(value) is int for value in witness["region"].values())
                assert witness["region"] == region
    except (AssertionError, KeyError, TypeError, ValueError):
        raise ContractError("unsupported_facts") from None


def fixture_pixels(raw: bytes) -> tuple[int, int, int, bytes]:
    """Small independent standard-library decoder for the approved fixture subset."""
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    offset = 8
    chunks: list[tuple[bytes, bytes]] = []
    while offset < len(raw):
        length = int.from_bytes(raw[offset : offset + 4], "big")
        kind = raw[offset + 4 : offset + 8]
        body = raw[offset + 8 : offset + 8 + length]
        checksum = raw[offset + 8 + length : offset + 12 + length]
        assert len(body) == length and len(checksum) == 4
        assert zlib.crc32(kind + body) == int.from_bytes(checksum, "big")
        chunks.append((kind, body))
        offset += length + 12
    assert offset == len(raw)
    assert chunks[0][0] == b"IHDR" and len(chunks[0][1]) == 13
    assert chunks[-1] == (b"IEND", b"")
    assert all(kind == b"IDAT" for kind, _ in chunks[1:-1]) and len(chunks) >= 3
    width, height, depth, colour, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", chunks[0][1]
    )
    assert depth == 8 and colour in (2, 6) and compression == filtering == interlace == 0
    channels = 3 if colour == 2 else 4
    assert 1 <= width <= 2048 and 1 <= height <= 2048
    stride = width * channels
    expected_bytes = height * (stride + 1)
    inflater = zlib.decompressobj()
    data = inflater.decompress(b"".join(body for _, body in chunks[1:-1]), expected_bytes + 1)
    assert inflater.eof and not inflater.unused_data and not inflater.unconsumed_tail
    assert len(data) == expected_bytes
    pixels = bytearray()
    previous = bytearray(stride)
    for row in range(height):
        start = row * (stride + 1)
        mode = data[start]
        assert 0 <= mode <= 4
        decoded = bytearray(stride)
        for index, value in enumerate(data[start + 1 : start + 1 + stride]):
            left = decoded[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if mode == 0:
                predictor = 0
            elif mode == 1:
                predictor = left
            elif mode == 2:
                predictor = up
            elif mode == 3:
                predictor = (left + up) // 2
            else:
                target = left + up - upper_left
                distances = (abs(target - left), abs(target - up), abs(target - upper_left))
                predictor = (left, up, upper_left)[distances.index(min(distances))]
            decoded[index] = (value + predictor) & 255
        pixels.extend(decoded)
        previous = decoded
    return width, height, channels, bytes(pixels)


def _apply(base: dict[str, Any], patches: list[dict[str, Any]]) -> dict[str, Any]:
    value = copy.deepcopy(base)

    def get(path: list[str]) -> Any:
        node: Any = value
        for key in path:
            node = node[int(key)] if isinstance(node, list) else node[key]
        return node

    for patch in patches:
        path = patch["path"]
        node = get(path[:-1])
        key = int(path[-1]) if isinstance(node, list) else path[-1]
        assert patch["op"] in ("set", "copy")
        replacement = copy.deepcopy(patch["value"] if patch["op"] == "set" else get(patch["from"]))
        if isinstance(node, list) and key == len(node):
            node.append(replacement)
        else:
            node[key] = replacement
    return value


class DocumentOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads((DIRECTORY / "document-v1.json").read_bytes())
        cls.corpus = json.loads((DIRECTORY / "document-adversarial-v1.json").read_bytes())
        cls.expected = json.loads((DIRECTORY / "documents" / "expected-v1.json").read_bytes())

    def test_exact_public_four_field_request_and_canonical_result(self) -> None:
        self.assertEqual(tuple(DOCUMENT_FIELDS), FIELDS)
        request = produce_document_request(copy.deepcopy(self.fixture["producer_input"]))
        self.assertEqual(
            encode_document_request(request).decode(), self.fixture["canonical"]["request_utf8"]
        )
        result = parse_document_result(canonical(self.fixture["result"]))
        self.assertEqual(
            encode_document_result(result).decode(), self.fixture["canonical"]["result_utf8"]
        )
        self.assertEqual(
            match_document_result(request, result, observed_at_ms=self.fixture["observed_at_ms"]),
            "candidate",
        )
        assert_fixture_result(result.to_wire(), self.expected["fixtures"]["complete"])

    def test_shared_adversarial_cases_have_real_named_failures(self) -> None:
        names = [case["name"] for case in self.corpus["cases"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(len(names), 29)
        phases: set[str] = set()
        for case in self.corpus["cases"]:
            with self.subTest(case=case["name"]):
                phase = case["phase"]
                phases.add(phase)
                changed = _apply(
                    self.fixture["request" if phase == "request" else "result"], case["patches"]
                )
                with self.assertRaises(ContractError) as caught:
                    if phase == "request":
                        parse_document_request(canonical(changed))
                    else:
                        parsed = parse_document_result(canonical(changed))
                        if phase == "match":
                            request = parse_document_request(canonical(self.fixture["request"]))
                            match_document_result(
                                request, parsed, observed_at_ms=self.fixture["observed_at_ms"]
                            )
                        elif phase == "facts":
                            assert_fixture_result(
                                parsed.to_wire(), self.expected["fixtures"]["complete"]
                            )
                        else:
                            self.assertEqual(phase, "result")
                self.assertEqual(caught.exception.code, case["code"])
        self.assertEqual(phases, {"request", "result", "match", "facts"})

    def test_factual_negative_really_passes_structural_validation_first(self) -> None:
        facts = [case for case in self.corpus["cases"] if case["phase"] == "facts"]
        self.assertGreaterEqual(len(facts), 5)
        for case in facts:
            with self.subTest(case=case["name"]):
                parsed = parse_document_result(
                    canonical(_apply(self.fixture["result"], case["patches"]))
                )
                if case["name"] in {
                    "schema_valid_wrong_value_is_not_factual",
                    "schema_valid_swapped_region_is_not_factual",
                }:
                    request = parse_document_request(canonical(self.fixture["request"]))
                    self.assertEqual(
                        match_document_result(
                            request, parsed, observed_at_ms=self.fixture["observed_at_ms"]
                        ),
                        "candidate",
                    )
                with self.assertRaises(ContractError) as caught:
                    assert_fixture_result(parsed.to_wire(), self.expected["fixtures"]["complete"])
                self.assertEqual(caught.exception.code, "unsupported_facts")

    def test_actual_PNG_bytes_and_independent_native_pixel_digest(self) -> None:
        fixtures = self.expected["fixtures"]
        self.assertEqual(
            set(fixtures), {"complete", "missing", "ambiguous", "adversarial", "other-source"}
        )
        for name, expected in fixtures.items():
            with self.subTest(image=name):
                raw = (DIRECTORY / "documents" / expected["file"]).read_bytes()
                source = expected["source"]
                self.assertEqual(hashlib.sha256(raw).hexdigest(), source["sha256"])
                self.assertEqual(len(raw), source["byte_length"])
                width, height, channels, pixels = fixture_pixels(raw)
                self.assertEqual(
                    (width, height, channels),
                    (source["width"], source["height"], expected["channels"]),
                )
                self.assertEqual(hashlib.sha256(pixels).hexdigest(), expected["pixel_sha256"])

    def test_reference_unfilters_all_five_modes_against_literal_channel_bytes(self) -> None:
        # Hand-calculated residuals; this does not call the production PNG worker.
        first = bytes([10, 20, 30, 40, 50, 60])
        second = bytes([30, 50, 70, 80, 100, 120])
        residuals = (
            bytes([30, 50, 70, 80, 100, 120]),
            bytes([30, 50, 70, 50, 50, 50]),
            bytes([20, 30, 40, 40, 50, 60]),
            bytes([25, 40, 55, 45, 50, 55]),
            bytes([20, 30, 40, 40, 50, 50]),
        )

        def chunk(kind: bytes, body: bytes) -> bytes:
            return (
                len(body).to_bytes(4, "big")
                + kind
                + body
                + zlib.crc32(kind + body).to_bytes(4, "big")
            )

        for mode, residual in enumerate(residuals):
            with self.subTest(filter=mode):
                png = (
                    b"\x89PNG\r\n\x1a\n"
                    + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress(b"\x00" + first + bytes([mode]) + residual))
                    + chunk(b"IEND", b"")
                )
                self.assertEqual(fixture_pixels(png), (2, 2, 3, first + second))

    def test_literal_oracle_distinguishes_missing_and_ambiguous_truth(self) -> None:
        fixtures = self.expected["fixtures"]
        self.assertEqual(fixtures["complete"]["outcome"], "extracted")
        self.assertEqual(fixtures["missing"]["outcome"], "clarification_required")
        self.assertEqual(fixtures["ambiguous"]["outcome"], "clarification_required")
        for expected in fixtures.values():
            self.assertEqual(set(expected["fields"]), set(FIELDS))
            for field in expected["fields"].values():
                state, value, regions = field["state"], field["value"], field["regions"]
                if state == "missing":
                    self.assertIsNone(value)
                    self.assertEqual(regions, [])
                elif state == "ambiguous":
                    self.assertIsNone(value)
                    self.assertEqual(len(regions), 2)
                    self.assertNotEqual(regions[0], regions[1])
                else:
                    self.assertEqual(state, "known")
                    self.assertIsInstance(value, str)
                    self.assertTrue(value.strip())
                    self.assertIn(len(regions), (1, 2))


if __name__ == "__main__":
    unittest.main()
