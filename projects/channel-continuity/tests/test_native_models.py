"""Public immutable native identity/ACK contract negatives."""

import json
import unittest
from uuid import uuid4

from channel_continuity.codec import AccountScope, ProviderScope
from channel_continuity.native import (
    NativeAck,
    NativeBinding,
    NativeCredential,
    NativeEndpoint,
    NativeError,
    NativeInput,
)
from channel_continuity.native_models import decode


class NativeModelTests(unittest.TestCase):
    def test_explicit_native_binding_is_not_sms_scope(self):
        with self.assertRaises(NativeError):
            NativeBinding(
                str(uuid4()),
                ProviderScope("t", "fake_sms", "p"),
                AccountScope("t", "a"),
                "c",
                "x",
                "r",
                "p",
                "agent",
            )

    def test_body_utf8_limit_and_surrogate_validation(self):
        for body in ("", "é" * 1025, "\ud800"):
            with self.subTest(bodylen=len(body)), self.assertRaises(NativeError):
                NativeInput(str(uuid4()), "web_chat", body, "r", "p")
        self.assertEqual(
            len(NativeInput(str(uuid4()), "voice_transcript", "é" * 1024, "r", "p").body), 1024
        )

    def test_canonical_uuid_not_transport_or_timestamp(self):
        for value in ("stream-id", str(uuid4()).upper(), str(uuid4()) + "\n"):
            with self.assertRaises(NativeError):
                NativeInput(value, "web_chat", "x", "r", "p")

    def test_unknown_ack_cannot_be_definitive_rejection(self):
        for status, code in (("unknown", "forbidden"), ("rejected", "acknowledgement_unknown")):
            with self.assertRaises(NativeError):
                NativeAck(str(uuid4()), str(uuid4()), "web_chat", status, code=code)

    def test_accepted_ack_requires_original_receipt_operation_sequence(self):
        with self.assertRaises(NativeError):
            NativeAck(str(uuid4()), str(uuid4()), "web_chat", "accepted")
        for revision in ("0", "01", "9223372036854775808", True):
            with self.assertRaises(NativeError):
                NativeAck(
                    str(uuid4()),
                    str(uuid4()),
                    "web_chat",
                    "accepted",
                    str(uuid4()),
                    str(uuid4()),
                    revision,
                )

    def test_credentials_are_not_repr_and_endpoints_are_fixed_loopback(self):
        self.assertNotIn("a" * 43, repr(NativeCredential("a" * 43)))
        for host, port in (("localhost", 1), ("127.0.0.1", True), ("remote", 8080)):
            with self.assertRaises(NativeError):
                NativeEndpoint(host, port)

    def test_raw_json_duplicate_nonfinite_and_size_rejected(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b"[]", b"x" * 32769):
            with self.assertRaises(NativeError):
                decode(raw, 32768)

    def test_schema_boolean_not_equal_integer(self):
        self.assertIs(
            type(decode(json.dumps({"schemaVersion": True}).encode(), 64)["schemaVersion"]), bool
        )


if __name__ == "__main__":
    unittest.main()
