"""Offline private-profile/configuration controls; no SQL, media or providers."""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from delegation_reliability.fixed_policy_contracts import produce_fixed_policy_request
from services.channel_policy_demo import owner_config as m

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    source = json.loads((ROOT / "contracts/delegation/fixed-policy-v2.json").read_bytes())
    template = produce_fixed_policy_request(copy.deepcopy(source["producer_input"]))
    route = m.ProfileRoute(
        str(uuid4()),
        str(uuid4()),
        template.scope,
        template.case_id,
        template.conversation_id,
        "recipient_demo",
    )
    credentials = m.ProfileCredentials(
        "synthetic_password_only" * 2, *(character * 43 for character in "abcdefghij")
    )
    return m.OwnerProfile(
        route,
        m.ProfilePorts(),
        m.ProfileDatabase(15432, "p1_demo_case", "p1_work_demo", "p2_demo_channel"),
        m.ProfileCase("demo_actor", "demo_scope", str(uuid4()), str(uuid4())),
        credentials,
        str(uuid4()),
        "joined_rtc",
        "joined_sms",
        (
            m.ProfilePolicy(
                template, (source["policy_body_utf8"].encode(), source["facts_body_utf8"].encode())
            ),
        ),
    )


def wire(profile=None):
    return json.loads(m.encode_owner_profile(profile or fixture()))


def raw(value):
    return (json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


class ProfileValues(unittest.TestCase):
    def test_round_trip_keeps_stable_identities_and_exact_evidence(self):
        original = fixture()
        encoded = m.encode_owner_profile(original)
        restored = m.parse_owner_profile(encoded)
        self.assertEqual(m.encode_owner_profile(restored), encoded)
        self.assertEqual(restored.app_owner_id, original.app_owner_id)
        self.assertEqual(restored.case, original.case)
        self.assertEqual(restored.policies[0].records(), original.policies[0].records())
        self.assertEqual(
            restored.templates().for_revision(original.policies[0].template.request_revision),
            original.policies[0].template,
        )
        self.assertEqual(restored.case_settings().schema, "p1_demo_case")
        self.assertEqual(restored.work_settings().schema, "p1_work_demo")
        self.assertEqual(restored.actor().actor_id, "demo_actor")
        self.assertEqual(restored.case_token().value, original.credentials.p1_case_token)

    def test_node_configuration_is_secret_free_and_role_environment_is_minimal(self):
        profile = fixture()
        node = profile.node_configuration()
        encoded = raw(node).decode()
        for secret in profile.credentials.node_environment().values():
            self.assertNotIn(secret, encoded)
        self.assertEqual(
            node["listen"],
            {"nativePort": 11024, "smsPort": 11025, "readPort": 11026, "receiverPort": 11027},
        )
        self.assertEqual(node["simulationHmac"], "public_synthetic_v1")
        self.assertEqual(len(profile.credentials.node_environment()), 8)
        self.assertEqual(
            profile.credentials.node_environment()["P2_DEMO_CASE_AUTHORIZATION"],
            "Bearer " + profile.credentials.case_bearer,
        )
        self.assertNotIn(
            profile.credentials.p1_case_token, profile.credentials.node_environment().values()
        )
        self.assertNotIn(
            profile.credentials.specialist_bearer, profile.credentials.node_environment().values()
        )

    def test_specialist_configuration_is_exact_secret_free_and_independent(self):
        profile = fixture()
        config = profile.specialist_configuration()
        self.assertEqual(set(config), {"schemaVersion", "label", "scope", "port", "evidence"})
        self.assertEqual(
            (config["schemaVersion"], config["label"], config["port"]), (1, "scripted", 11028)
        )
        self.assertEqual(
            config["scope"],
            {
                "tenantId": profile.route.scope.tenant_id,
                "accountId": profile.route.scope.account_id,
            },
        )
        self.assertEqual(len(config["evidence"]), 2)
        for emitted, record in zip(config["evidence"], profile.policies[0].records(), strict=True):
            self.assertEqual(base64.b64decode(emitted["bodyBase64"], validate=True), record.body)
            self.assertEqual(
                emitted["reference"]["sha256"], hashlib.sha256(record.body).hexdigest()
            )
            self.assertEqual(emitted["reference"]["byte_length"], len(record.body))
        for credential in wire(profile)["credentials"].values():
            self.assertNotIn(credential, raw(config).decode())
        config["evidence"][0]["reference"]["sha256"] = "0" * 64
        config["scope"]["tenantId"] = "other"
        self.assertEqual(
            profile.specialist_configuration()["scope"]["tenantId"], profile.route.scope.tenant_id
        )
        self.assertNotEqual(
            profile.specialist_configuration()["evidence"][0]["reference"]["sha256"], "0" * 64
        )

    def test_specialist_registry_rejects_same_source_with_conflicting_version_or_bytes(self):
        profile = fixture()
        first = profile.policies[0]
        for change in ("version", "body"):
            template = first.template.to_wire()
            template.pop("input_fingerprint")
            template["request_revision"] += 1
            bodies = list(first.bodies)
            if change == "version":
                template["evidence"][1]["version"] = "source_v2"
            else:
                facts = json.loads(bodies[1])
                facts["note"] += " Changed inert evidence prose."
                bodies[1] = raw(facts)
                template["evidence"][1]["sha256"] = hashlib.sha256(bodies[1]).hexdigest()
                template["evidence"][1]["byte_length"] = len(bodies[1])
            second = m.ProfilePolicy(produce_fixed_policy_request(template), tuple(bodies))
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(m.ProfileError, "^invalid_profile$"),
            ):
                replace(profile, policies=(first, second))

    def test_profile_and_credentials_repr_hide_every_secret_and_body(self):
        profile = fixture()
        rendered = repr(profile) + repr(profile.credentials) + repr(profile.policies)
        for key, value in wire(profile)["credentials"].items():
            with self.subTest(key=key):
                self.assertNotIn(value, rendered)
        self.assertNotIn(profile.policies[0].bodies[0].decode(), rendered)

    def test_values_are_frozen_and_generated_configuration_is_independent(self):
        profile = fixture()
        with self.assertRaises(FrozenInstanceError):
            profile.app_owner_id = str(uuid4())
        node = profile.node_configuration()
        node["route"]["caseId"] = "other"
        self.assertEqual(profile.node_configuration()["route"]["caseId"], profile.route.case_id)
        environment = profile.credentials.node_environment()
        environment.clear()
        self.assertEqual(len(profile.credentials.node_environment()), 8)

    def test_unknown_duplicate_and_noncanonical_json_are_rejected(self):
        value = wire()
        variants = [
            raw(value).replace(b'"schemaVersion":1', b'"schemaVersion":1,"schemaVersion":1', 1),
            json.dumps(value, indent=2).encode(),
            raw(value)[:-1],
            b"\xff",
            b"{" * 2000,
            b"x" * (m.PROFILE_BYTES + 1),
        ]
        value["providerKey"] = "not_a_supported_field"
        variants.append(raw(value))
        for payload in variants:
            with (
                self.subTest(length=len(payload)),
                self.assertRaisesRegex(m.ProfileError, "^invalid_profile$"),
            ):
                m.parse_owner_profile(payload)

    def test_wrong_scope_route_and_duplicate_revisions_are_rejected(self):
        original = wire()
        for path, value in [
            (("route", "case_id"), "other_case"),
            (("route", "conversation_id"), "other_conversation"),
            (("route", "scope", "account_id"), "other_account"),
        ]:
            changed = copy.deepcopy(original)
            parent = changed
            for key in path[:-1]:
                parent = parent[key]
            parent[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(m.ProfileError):
                m.parse_owner_profile(raw(changed))
        changed = copy.deepcopy(original)
        changed["policies"].append(copy.deepcopy(changed["policies"][0]))
        with self.assertRaises(m.ProfileError):
            m.parse_owner_profile(raw(changed))

    def test_equal_immutable_evidence_can_support_two_distinct_revision_templates(self):
        profile = fixture()
        first = profile.policies[0]
        second_wire = first.template.to_wire()
        second_wire.pop("input_fingerprint")
        second_wire["request_revision"] += 1
        second = m.ProfilePolicy(produce_fixed_policy_request(second_wire), first.bodies)
        result = replace(profile, policies=(first, second))
        self.assertEqual(len(result.templates().templates), 2)
        self.assertEqual(
            m.encode_owner_profile(m.parse_owner_profile(m.encode_owner_profile(result))),
            m.encode_owner_profile(result),
        )
        result.evidence()
        self.assertEqual(len(result.specialist_configuration()["evidence"]), 2)

    def test_invalid_ports_schemas_roles_tokens_and_numeric_limits_are_finite(self):
        original = wire()
        cases = [
            (("ports", "read"), 0),
            (("ports", "read"), True),
            (("ports", "read"), 10**1000),
            (("ports", "read"), 11021),
            (("ports", "read"), 65536),
            (("database", "port"), 1.5),
            (("database", "work_schema"), "p1_demo_case"),
            (("database", "case_schema"), "bad;schema"),
            (("database", "work_schema"), "other_work_schema"),
            (("credentials", "worker_bearer"), "a" * 43),
            (("credentials", "postgres_password"), "bad password"),
            (("credentials", "postgres_password"), "short_but_private_22xxx"),
            (("credentials", "postgres_password"), "😀" * 65),
            (("credentials", "p1_case_token"), "i" * 43),
            (("route", "profile_id"), str(uuid4()).upper()),
            (("case", "task_id"), "not_uuid"),
            (("deadlineWindowMs",), True),
            (("deadlineWindowMs",), 60001),
            (("deadlineWindowMs",), 10**1000),
            (("schemaVersion",), True),
        ]
        for path, value in cases:
            changed = copy.deepcopy(original)
            parent = changed
            for key in path[:-1]:
                parent = parent[key]
            parent[path[-1]] = value
            with (
                self.subTest(path=path),
                self.assertRaisesRegex(m.ProfileError, "^invalid_profile$"),
            ):
                m.parse_owner_profile(raw(changed))

    def test_evidence_rejects_changed_digest_oversize_noncanonical_base64_and_missing_pair(self):
        original = wire()
        for bodies in [
            [base64.b64encode(b"changed").decode(), original["policies"][0]["bodiesBase64"][1]],
            ["A" * 5468, "AAAA"],
            ["AB==", original["policies"][0]["bodiesBase64"][1]],
            [original["policies"][0]["bodiesBase64"][0]],
            [],
        ]:
            changed = copy.deepcopy(original)
            changed["policies"][0]["bodiesBase64"] = bodies
            with self.subTest(length=len(bodies)), self.assertRaises(m.ProfileError):
                m.parse_owner_profile(raw(changed))

    def test_template_catalogue_capacity_and_unknown_nested_fields_are_rejected(self):
        value = wire()
        value["policies"] *= 17
        with self.assertRaises(m.ProfileError):
            m.parse_owner_profile(raw(value))
        for area in ["route", "ports", "database", "case", "credentials"]:
            value = wire()
            value[area]["unexpected"] = "private"
            with self.subTest(area=area), self.assertRaises(m.ProfileError):
                m.parse_owner_profile(raw(value))

    def _profile_with_bodies(self, bodies):
        value = wire()
        entry = value["policies"][0]
        template = entry["template"]
        template.pop("input_fingerprint")
        for reference, body in zip(template["evidence"], bodies, strict=True):
            reference["sha256"] = hashlib.sha256(body).hexdigest()
            reference["byte_length"] = len(body)
        entry["template"] = produce_fixed_policy_request(template).to_wire()
        entry["bodiesBase64"] = [base64.b64encode(body).decode("ascii") for body in bodies]
        return m.parse_owner_profile(raw(value))

    def test_supported_evidence_shapes_are_required_even_with_honest_reference_digests(self):
        original = fixture().policies[0].bodies
        policy = json.loads(original[0])
        facts = json.loads(original[1])
        variants = [
            ({"unsupported_policy": True}, facts),
            (policy | {"minimum_notice_days": 8}, facts),
            (policy | {"kind": "unknown_policy"}, facts),
            (policy, facts | {"kind": "unknown_facts"}),
            (
                policy,
                facts | {"observations": [{"fact_id": "same", "days_before_arrival": 10}] * 2},
            ),
            (
                policy,
                facts | {"observations": [{"fact_id": "notice", "days_before_arrival": True}]},
            ),
        ]
        for policy_value, facts_value in variants:
            with (
                self.subTest(policy_kind=policy_value.get("kind")),
                self.assertRaisesRegex(m.ProfileError, "^invalid_profile$"),
            ):
                self._profile_with_bodies((raw(policy_value), raw(facts_value)))
        for observations in (
            [],
            [
                {"fact_id": "first", "days_before_arrival": 5},
                {"fact_id": "second", "days_before_arrival": 10},
            ],
        ):
            result = self._profile_with_bodies(
                (original[0], raw(facts | {"observations": observations}))
            )
            self.assertEqual(json.loads(result.policies[0].bodies[1])["observations"], observations)

    def test_surrogate_credential_fails_with_finite_error_and_utf8_password_round_trips(self):
        original = fixture()
        invalid = chr(0xD800) * 20
        with self.assertRaisesRegex(m.ProfileError, "^invalid_profile$"):
            replace(original.credentials, postgres_password=invalid)
        good = replace(
            original, credentials=replace(original.credentials, postgres_password="µ" * 32)
        )
        self.assertEqual(
            m.parse_owner_profile(m.encode_owner_profile(good)).credentials.postgres_password,
            "µ" * 32,
        )
        object.__setattr__(original.credentials, "postgres_password", invalid)
        with self.assertRaisesRegex(m.ProfileError, "^invalid_profile$"):
            m.encode_owner_profile(original)

    def test_import_performs_no_open_socket_or_configuration_read(self):
        name = "services.channel_policy_demo._owner_config_inert_probe"
        spec = importlib.util.spec_from_file_location(name, m.__file__)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            with patch.object(m.os, "open", side_effect=AssertionError("unexpected file read")):
                spec.loader.exec_module(module)
        finally:
            sys.modules.pop(name, None)


class PrivateProfileFile(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="channel-profile-test-")
        self.directory = Path(self.temporary.name).resolve()
        self.path = self.directory / "owner-profile.json"
        self.profile = fixture()
        self.path.write_bytes(m.encode_owner_profile(self.profile))
        self.path.chmod(0o600)

    def tearDown(self):
        self.temporary.cleanup()

    def test_private_regular_file_round_trips(self):
        self.assertEqual(
            m.encode_owner_profile(m.read_owner_profile(self.path)), self.path.read_bytes()
        )

    def test_public_permissions_and_noncanonical_path_are_denied(self):
        self.path.chmod(0o644)
        with self.assertRaises(m.ProfileError):
            m.read_owner_profile(self.path)
        self.path.chmod(0o600)
        self.directory.chmod(0o755)
        with self.assertRaises(m.ProfileError):
            m.read_owner_profile(self.path)
        self.directory.chmod(0o700)
        with self.assertRaises(m.ProfileError):
            m.read_owner_profile(Path("owner-profile.json"))

    def test_symlink_and_hardlink_are_denied_before_read(self):
        link = self.directory / "alias.json"
        link.symlink_to(self.path)
        with self.assertRaises(m.ProfileError):
            m.read_owner_profile(link)
        link.unlink()
        os.link(self.path, link)
        with (
            patch.object(m.os, "read", side_effect=AssertionError("aliased file read")),
            self.assertRaises(m.ProfileError),
        ):
            m.read_owner_profile(self.path)

    def test_fifo_and_oversized_file_are_denied_before_read(self):
        fifo = self.directory / "fifo.json"
        os.mkfifo(fifo, 0o600)
        with patch.object(m.os, "read", side_effect=AssertionError("invalid file read")):
            with self.assertRaises(m.ProfileError):
                m.read_owner_profile(fifo)
            self.path.write_bytes(b"x" * (m.PROFILE_BYTES + 1))
            with self.assertRaises(m.ProfileError):
                m.read_owner_profile(self.path)

    def test_dotenv_path_is_denied_without_opening(self):
        with (
            patch.object(m.os, "open", side_effect=AssertionError("dotenv read")),
            self.assertRaises(m.ProfileError),
        ):
            m.read_owner_profile(self.directory / ".env.providers")

    def test_permissions_changed_during_read_are_rejected_even_with_unchanged_bytes(self):
        original_read = m.os.read
        changed = False

        def read(descriptor, maximum):
            nonlocal changed
            data = original_read(descriptor, maximum)
            if not changed:
                changed = True
                self.path.chmod(0o644)
            return data

        with (
            patch.object(m.os, "read", side_effect=read),
            self.assertRaisesRegex(m.ProfileError, "^invalid_profile$"),
        ):
            m.read_owner_profile(self.path)
        self.assertEqual(self.path.read_bytes(), m.encode_owner_profile(self.profile))

    def test_file_changed_during_read_is_rejected(self):
        original_read = m.os.read
        changed = False

        def read(descriptor, maximum):
            nonlocal changed
            data = original_read(descriptor, maximum)
            if not changed:
                changed = True
                with self.path.open("ab") as stream:
                    stream.write(b" ")
            return data

        with patch.object(m.os, "read", side_effect=read), self.assertRaises(m.ProfileError):
            m.read_owner_profile(self.path)


if __name__ == "__main__":
    unittest.main()
