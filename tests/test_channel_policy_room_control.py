"""Closed parent-only control/CAS wire; no socket, database or provider use."""

from __future__ import annotations

import copy
import json
import unittest
from dataclasses import FrozenInstanceError, replace
from uuid import uuid4

from services.channel_policy_demo import room_control as m


def fixture():
    return m.RoomOpen(
        str(uuid4()),
        "0",
        str(uuid4()),
        m.RoomBinding(
            str(uuid4()),
            "n" * 43,
            "demo_room_a",
            "demo_caller_a",
            "demo_agent_a",
            "2030-01-01T00:02:00.000Z",
        ),
        "v" * 43,
    )


def wire(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


def observed(opened, state="ready"):
    return {
        "schemaVersion": 1,
        "nodeEpoch": opened.node_epoch,
        "generation": opened.command().generation,
        "openId": opened.open_id,
        "state": state,
        "publication": {
            "bindingId": opened.binding.binding_id,
            "bindingDigest": "a" * 64,
            "publishedAt": "2030-01-01T00:00:00.000Z",
            "expiresAt": opened.binding.expires_at,
        },
        "revocation": None,
        "globalReaderDrained": False,
    }


class RoomControlTests(unittest.TestCase):
    def test_worker_attachment_has_one_bound_identity_and_private_prepare_capability(self):
        opened = fixture()
        value = m.RoomAttach(
            opened.node_epoch, "1", opened.open_id, opened.binding.binding_id, "w" * 43
        )
        raw = m.encode_room_attach(value)
        self.assertEqual(
            json.loads(raw),
            {
                "schemaVersion": 1,
                "nodeEpoch": opened.node_epoch,
                "generation": "1",
                "openId": opened.open_id,
                "bindingId": opened.binding.binding_id,
                "prepareBearer": "w" * 43,
            },
        )
        self.assertNotIn("w" * 43, repr(value))
        self.assertFalse(raw.endswith(b"\n"))
        self.assertLessEqual(len(raw), m.CONTROL_BYTES)

    def test_attachment_ack_rejects_scope_endpoint_and_foreign_identity(self):
        opened = fixture()
        request = m.RoomAttach(
            opened.node_epoch, "1", opened.open_id, opened.binding.binding_id, "w" * 43
        )
        ack = {key: value for key, value in request.to_wire().items() if key != "prepareBearer"}
        ack["state"] = "attached"
        result = m.parse_room_attachment(wire(ack), request=request)
        self.assertEqual(result.binding_id, request.binding_id)
        for key, value in (
            ("schemaVersion", True),
            ("nodeEpoch", str(uuid4())),
            ("generation", "2"),
            ("openId", str(uuid4())),
            ("bindingId", str(uuid4())),
            ("state", "ready"),
            ("prepareBearer", "w" * 43),
            ("endpoint", "http://foreign/"),
            ("scope", {}),
        ):
            changed = dict(ack)
            changed[key] = value
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(m.RoomControlError, "^invalid_state$"),
            ):
                m.parse_room_attachment(wire(changed), request=request)
        duplicate = wire(ack)[:-1] + b',"state":"attached"}'
        for raw in (duplicate, b"NaN", b"null", b" ", b"x" * (m.OBSERVATION_BYTES + 1)):
            with self.subTest(raw=raw[:20]), self.assertRaises(m.RoomControlError):
                m.parse_room_attachment(raw, request=request)

    def test_attachment_revalidates_bypassed_objects_and_generation(self):
        opened = fixture()
        value = m.RoomAttach(
            opened.node_epoch, "1", opened.open_id, opened.binding.binding_id, "w" * 43
        )
        for name, invalid in (
            ("node_epoch", "bad"),
            ("generation", "0"),
            ("open_id", str(uuid4()).upper()),
            ("binding_id", None),
            ("prepare_bearer", "SECRET_INVALID"),
        ):
            changed = copy.copy(value)
            object.__setattr__(changed, name, invalid)
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(m.RoomControlError, "^invalid_input$"),
            ):
                m.encode_room_attach(changed)
        with self.assertRaisesRegex(m.RoomControlError, "^invalid_input$"):
            m.encode_room_attach(object())

    def test_open_preserves_exact_private_identity_and_has_no_scope_or_authority_selector(self):
        opened = fixture()
        raw = m.encode_room_control(opened)
        value = json.loads(raw)
        self.assertEqual(
            set(value),
            {
                "schemaVersion",
                "nodeEpoch",
                "expectedGeneration",
                "openId",
                "binding",
                "roomViewBearer",
            },
        )
        self.assertEqual(value["binding"]["nativeBearer"], opened.binding.native_bearer)
        self.assertEqual(value["roomViewBearer"], opened.room_view_bearer)
        self.assertNotIn("scope", value)
        self.assertNotIn("tenantId", value["binding"])
        self.assertEqual(m.encode_room_control(opened), raw)
        self.assertFalse(raw.endswith(b"\n"))
        self.assertLessEqual(len(raw), m.CONTROL_BYTES)

    def test_known_response_is_bound_to_original_epoch_generation_open_binding_and_expiry(self):
        opened = fixture()
        command = opened.command()
        value = observed(opened)
        result = m.parse_room_observation(wire(value), command=command, binding=opened.binding)
        self.assertEqual(
            (result.node_epoch, result.generation, result.open_id),
            (command.node_epoch, "1", command.open_id),
        )
        self.assertEqual(result.publication.binding_id, opened.binding.binding_id)
        self.assertFalse(result.global_reader_drained)
        for key, replacement in (
            ("nodeEpoch", str(uuid4())),
            ("openId", str(uuid4())),
            ("generation", "2"),
        ):
            changed = copy.deepcopy(value)
            changed[key] = replacement
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(m.RoomControlError, "^invalid_state$"),
            ):
                m.parse_room_observation(wire(changed), command=command, binding=opened.binding)
        for key, replacement in (
            ("bindingId", str(uuid4())),
            ("expiresAt", "2030-01-01T00:03:00.000Z"),
        ):
            changed = copy.deepcopy(value)
            changed["publication"][key] = replacement
            with self.subTest(key=key), self.assertRaises(m.RoomControlError):
                m.parse_room_observation(wire(changed), command=command, binding=opened.binding)

    def test_unresolved_publication_and_read_only_expired_observation_are_not_ready(self):
        opened = fixture()
        for state in ("opening", "publication_unknown", "closing"):
            value = observed(opened, state)
            if state != "closing":
                value["publication"] = None
            result = m.parse_room_observation(
                wire(value), command=opened.command(), binding=opened.binding
            )
            self.assertEqual(result.state, state)
            self.assertIsNone(result.revocation)
        value = observed(opened)
        value["publication"] = None
        with self.assertRaises(m.RoomControlError):
            m.parse_room_observation(wire(value), command=opened.command(), binding=opened.binding)

    def test_known_revocation_can_be_observed_before_full_close_finishes(self):
        opened = fixture()
        for state in ("closing", "closed"):
            value = observed(opened, state)
            value["revocation"] = {
                "bindingId": opened.binding.binding_id,
                "state": "revoked",
                "revokedAt": "2030-01-01T00:01:00.000Z",
            }
            result = m.parse_room_observation(
                wire(value), command=opened.command(), binding=opened.binding
            )
            self.assertEqual(result.revocation.binding_id, opened.binding.binding_id)
            self.assertEqual(result.state, state)
            self.assertFalse(result.global_reader_drained)
        value["globalReaderDrained"] = True
        with self.assertRaises(m.RoomControlError):
            m.parse_room_observation(wire(value), command=opened.command(), binding=opened.binding)

    def test_closed_unpublished_and_confirmed_absent_are_distinct(self):
        opened = fixture()
        for state in ("unpublished", "absent"):
            value = observed(opened, "closed")
            value["publication"] = None
            value["revocation"] = {
                "bindingId": opened.binding.binding_id,
                "state": state,
                "revokedAt": None,
            }
            result = m.parse_room_observation(
                wire(value), command=opened.command(), binding=opened.binding
            )
            self.assertEqual(result.revocation.state, state)
            value["revocation"]["revokedAt"] = "2030-01-01T00:01:00.000Z"
            with self.assertRaises(m.RoomControlError):
                m.parse_room_observation(
                    wire(value), command=opened.command(), binding=opened.binding
                )

    def test_known_publication_cannot_be_acknowledged_as_never_published(self):
        opened = fixture()
        for state in ("closing", "closed"):
            value = observed(opened, state)
            value["revocation"] = {
                "bindingId": opened.binding.binding_id,
                "state": "unpublished",
                "revokedAt": None,
            }
            with (
                self.subTest(state=state),
                self.assertRaisesRegex(m.RoomControlError, "^invalid_state$"),
            ):
                m.parse_room_observation(
                    wire(value), command=opened.command(), binding=opened.binding
                )

    def test_recovery_advances_exact_generation_without_reconstructing_a_room(self):
        opened = fixture()
        request = m.RoomRecover(opened.node_epoch, "0", opened.binding.binding_id)
        value = {
            "schemaVersion": 1,
            "nodeEpoch": opened.node_epoch,
            "generation": "1",
            "bindingId": opened.binding.binding_id,
            "state": "recovered",
            "revocation": {
                "bindingId": opened.binding.binding_id,
                "state": "absent",
                "revokedAt": None,
            },
        }
        result = m.parse_room_recovery(wire(value), request=request)
        self.assertEqual(result.generation, "1")
        self.assertEqual(result.revocation.state, "absent")
        for key, replacement in (
            ("generation", "0"),
            ("generation", "2"),
            ("bindingId", str(uuid4())),
            ("state", "ready"),
            ("schemaVersion", True),
        ):
            changed = copy.deepcopy(value)
            changed[key] = replacement
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(m.RoomControlError, "^invalid_state$"),
            ):
                m.parse_room_recovery(wire(changed), request=request)
        self.assertEqual(json.loads(m.encode_room_control(request))["expectedGeneration"], "0")

    def test_no_wraparound_numeric_coercion_or_role_alias(self):
        opened = fixture()
        for generation in (True, 1, 1.0, "01", "-1", "1000001", "9" * 10000):
            with (
                self.subTest(generation=str(generation)[:15]),
                self.assertRaises(m.RoomControlError),
            ):
                replace(opened, expected_generation=generation)
        maximum = replace(opened, expected_generation="1000000")
        with self.assertRaisesRegex(m.RoomControlError, "^capacity$"):
            maximum.command()
        for changed in (
            lambda: replace(opened, room_view_bearer=opened.binding.native_bearer),
            lambda: replace(opened.binding, agent_id=opened.binding.participant_id),
            lambda: replace(opened.binding, expires_at="2030-02-30T00:00:00.000Z"),
        ):
            with self.assertRaises(m.RoomControlError):
                changed()

    def test_unknown_duplicate_nan_oversized_and_utf8_frames_are_finite(self):
        opened = fixture()
        value = observed(opened)
        cases = [
            wire(value | {"roomViewBearer": "PRIVATE_CONTROL_SENTINEL"}),
            wire(value).replace(b'"schemaVersion":1', b'"schemaVersion":1,"schemaVersion":1', 1),
            wire(value | {"generation": float("nan")}),
            b"x" * 4097,
            b"\xff",
            b"[" * 2000,
        ]
        for raw in cases:
            with (
                self.subTest(bytes=len(raw)),
                self.assertRaisesRegex(m.RoomControlError, "^invalid_state$"),
            ):
                m.parse_room_observation(raw, command=opened.command(), binding=opened.binding)

    def test_error_status_and_finite_code_must_match(self):
        for status, code in (
            (400, "invalid_input"),
            (401, "unauthorized"),
            (409, "conflict"),
            (409, "recovery_required"),
            (429, "capacity"),
            (503, "outcome_unknown"),
            (503, "cleanup_incomplete"),
        ):
            error = m.parse_room_control_error(
                wire({"schemaVersion": 1, "status": "unavailable", "code": code}), status
            )
            self.assertEqual(error.code, code)
            self.assertEqual(str(error), code)
        for raw, status in (
            (b"null", 503),
            (
                wire(
                    {
                        "schemaVersion": 1,
                        "status": "unavailable",
                        "code": "PRIVATE_CONTROL_SENTINEL",
                    }
                ),
                503,
            ),
            (wire({"schemaVersion": 1, "status": "unavailable", "code": "unauthorized"}), 200),
        ):
            self.assertEqual(m.parse_room_control_error(raw, status).code, "outcome_unknown")

    def test_capabilities_are_private_frozen_and_bypassed_dtos_fail_closed(self):
        opened = fixture()
        self.assertNotIn(opened.binding.native_bearer, repr(opened))
        self.assertNotIn(opened.room_view_bearer, repr(opened))
        credential = m.RoomPublisherCredential("p" * 43)
        self.assertNotIn(credential.value, repr(credential))
        with self.assertRaises(FrozenInstanceError):
            opened.open_id = str(uuid4())
        bypassed = object.__new__(m.RoomOpen)
        with self.assertRaisesRegex(m.RoomControlError, "^invalid_input$"):
            m.encode_room_control(bypassed)
        object.__setattr__(opened.binding, "native_bearer", "PRIVATE_CONTROL_SENTINEL")
        with self.assertRaisesRegex(m.RoomControlError, "^invalid_input$"):
            m.encode_room_control(opened)

    def test_close_command_contains_no_new_binding_or_bearer(self):
        command = fixture().command()
        value = json.loads(m.encode_room_control(command))
        self.assertEqual(set(value), {"schemaVersion", "nodeEpoch", "generation", "openId"})
        self.assertEqual(value["generation"], "1")


if __name__ == "__main__":
    unittest.main()
