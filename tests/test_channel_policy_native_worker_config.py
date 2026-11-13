"""Offline scripted worker data and actual private-file race controls; no provider/RTC."""

from __future__ import annotations

import copy
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from channel_continuity.codec import AccountScope, ProviderScope
from channel_continuity.native_models import NativeBinding, NativeCredential, NativeEndpoint
from services.channel_policy_demo import native_worker_config as m
from services.channel_policy_demo.native_models import ScriptedModelProfile

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhZ2VudCJ9." + "S" * 43
CAPS = tuple(character * 43 for character in "ABC")


def fixture():
    return m.NativeWorkerConfig(
        str(uuid4()),
        NativeBinding(
            str(uuid4()),
            ProviderScope("tenant_demo", "livekit", "native-local"),
            AccountScope("tenant_demo", "account_demo"),
            "case_demo",
            "conversation_demo",
            "room-demo",
            "browser-demo",
            "agent-demo",
        ),
        JWT,
        NativeCredential(CAPS[0]),
        CAPS[1],
        CAPS[2],
    )


def wire(value=None):
    return json.loads(m.encode_native_worker_config(value or fixture()))


def raw(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


class CodecTests(unittest.TestCase):
    def assert_invalid(self, value):
        with self.assertRaisesRegex(m.NativeWorkerConfigError, "^invalid_configuration$"):
            m.parse_native_worker_config(raw(value))

    def test_closed_roundtrip_genuine_public_values_defaults_and_hidden_capabilities(self):
        value = fixture()
        encoded = m.encode_native_worker_config(value)
        restored = m.parse_native_worker_config(encoded)
        self.assertEqual(restored, value)
        self.assertEqual(m.encode_native_worker_config(restored), encoded)
        self.assertTrue(encoded.endswith(b"\n"))
        self.assertIs(type(restored.binding), NativeBinding)
        self.assertIs(type(restored.native_endpoint), NativeEndpoint)
        self.assertIs(type(restored.native_credential), NativeCredential)
        self.assertIs(type(restored.model_profile), ScriptedModelProfile)
        self.assertEqual(restored.binding.provider_scope.provider, "livekit")
        self.assertEqual(restored.worker_binding.profile_id, restored.profile_id)
        self.assertEqual(restored.worker_binding.scope.tenant_id, "tenant_demo")
        self.assertEqual(
            (
                restored.native_endpoint.port,
                restored.prepare_port,
                restored.rehydration_endpoint.port,
                restored.current_endpoint.port,
            ),
            (11024, 11030, 11032, 11031),
        )
        for secret in (*CAPS, JWT):
            self.assertNotIn(secret, repr(restored))
        with self.assertRaises(FrozenInstanceError):
            restored.prepare_port = 12000
        self.assertEqual(
            set(wire(value)),
            {
                "schemaVersion",
                "profileId",
                "scope",
                "providerAccountId",
                "caseId",
                "conversationId",
                "bindingId",
                "roomId",
                "participantId",
                "agentId",
                "livekit",
                "native",
                "prepare",
                "rehydration",
                "currentResult",
                "scripted",
            },
        )

    def test_whitespace_is_accepted_and_encoded_canonically_without_input_mutation(self):
        payload = wire()
        source = copy.deepcopy(payload)
        parsed = m.parse_native_worker_config(json.dumps(payload, indent=2).encode())
        payload["scope"]["tenantId"] = "changed"
        payload["scripted"]["inputFixtures"].append("input-status.wav")
        self.assertEqual(json.loads(m.encode_native_worker_config(parsed)), source)

    def test_root_and_nested_missing_unknown_fields_and_provider_modes_fail_closed(self):
        original = wire()
        for name in original:
            changed = copy.deepcopy(original)
            changed.pop(name)
            self.assert_invalid(changed)
        for selector in [
            None,
            "scope",
            "livekit",
            "native",
            "prepare",
            "rehydration",
            "currentResult",
            "scripted",
        ]:
            changed = copy.deepcopy(original)
            target = changed if selector is None else changed[selector]
            target["providerKey"] = "PRIVATE_WORKER_CONFIG_SENTINEL"
            self.assert_invalid(changed)
        for version in [True, 0, 2, "1", 1.0]:
            self.assert_invalid(original | {"schemaVersion": version})
        for mode in ["scripted", "provider_real", "local_real"]:
            self.assert_invalid(original | {"inferenceMode": mode})

    def test_noncanonical_uuid_identity_and_scope_limits_are_rejected(self):
        original = wire()
        for key in ["profileId", "bindingId"]:
            for value in [
                "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
                UUID(original[key]).hex,
                str(UUID(int=1)),
                "x",
                None,
            ]:
                self.assert_invalid(original | {key: value})
        for key in [
            "caseId",
            "conversationId",
            "roomId",
            "participantId",
            "agentId",
            "providerAccountId",
        ]:
            for value in ["", "../secret", "a" * 129, True]:
                self.assert_invalid(original | {key: value})
        for scope in [
            {"tenantId": "Tenant", "accountId": "account_demo"},
            {"tenantId": "tenant_demo", "accountId": "a" * 65},
        ]:
            self.assert_invalid(original | {"scope": scope})
        self.assert_invalid(original | {"caseId": "CaseUpper"})
        self.assert_invalid(original | {"conversationId": "ConversationUpper"})

    def test_ports_are_required_exact_integers_distinct_and_bounded(self):
        original = wire()
        names = ["native", "prepare", "rehydration", "currentResult"]
        for name in names:
            for value in [True, 0, -1, 65536, "11024", 11024.0, None]:
                changed = copy.deepcopy(original)
                changed[name]["port"] = value
                self.assert_invalid(changed)
            for other in names:
                if name != other:
                    changed = copy.deepcopy(original)
                    changed[name]["port"] = changed[other]["port"]
                    self.assert_invalid(changed)
        changed = copy.deepcopy(original)
        for name, value in zip(names, [1, 2, 65534, 65535], strict=True):
            changed[name]["port"] = value
        self.assertEqual(m.parse_native_worker_config(raw(changed)).current_endpoint.port, 65535)

    def test_three_capabilities_are_exact_pairwise_distinct_and_not_jwt_segments(self):
        original = wire()
        names = ["native", "prepare", "currentResult"]
        for name in names:
            for value in ["", "X" * 42, "X" * 44, "X" * 42 + "\n", "X" * 42 + "é", None, JWT]:
                changed = copy.deepcopy(original)
                changed[name]["bearer"] = value
                self.assert_invalid(changed)
            for other in names:
                if name != other:
                    changed = copy.deepcopy(original)
                    changed[name]["bearer"] = changed[other]["bearer"]
                    self.assert_invalid(changed)
            changed = copy.deepcopy(original)
            changed[name]["bearer"] = "S" * 43
            self.assert_invalid(changed)

    def test_canonical_loopback_port_configuration_roundtrips_without_loading_sdk(self):
        self.assertEqual(fixture().livekit_url, "ws://127.0.0.1:17880")
        for port in (1, 7880, 7881, 17880, 65535):
            with self.subTest(port=port):
                selected = replace(fixture(), livekit_url=f"ws://127.0.0.1:{port}")
                self.assertEqual(
                    m.parse_native_worker_config(m.encode_native_worker_config(selected)), selected
                )
                self.assertEqual(
                    m.validate_livekit_url(f"http://127.0.0.1:{port}", scheme="http"),
                    f"http://127.0.0.1:{port}",
                )

    def test_local_rtc_url_and_syntax_only_jwt_are_bounded_without_claim_authority(self):
        original = wire()
        for value in [
            "wss://remote.invalid",
            "ws://localhost:7880",
            "ws://127.0.0.1:0",
            "ws://127.0.0.1:65536",
            "ws://127.0.0.1:07880",
            "ws://127.0.0.1:7880?token=x",
            "ws://127.0.0.1:7880#fragment",
            "ws://user:token@127.0.0.1:7880",
            "ws://127.0.0.2:7880",
            "ws://[::1]:7880",
            "ws://127.0.0.1",
            "ws://127.0.0.1:7880/",
            "http://127.0.0.1:7880",
            None,
        ]:
            changed = copy.deepcopy(original)
            changed["livekit"]["url"] = value
            self.assert_invalid(changed)
        for value in [
            "",
            "one",
            "one.two",
            ".one.two",
            "one..two",
            "one.two.three.four",
            "one.two.three=",
            "one.two.thréé",
            "one.two.three\n",
            "a.b." + "s" * 8189,
            None,
        ]:
            changed = copy.deepcopy(original)
            changed["livekit"]["token"] = value
            self.assert_invalid(changed)
        changed = copy.deepcopy(original)
        changed["livekit"]["token"] = "a.b." + "s" * 8188
        self.assertEqual(len(m.parse_native_worker_config(raw(changed)).livekit_token), 8192)

    def test_scripted_declared_inputs_replies_and_count_are_fixed(self):
        original = wire()
        for value in [
            [],
            ["unknown.wav"],
            ["../input-status.wav"],
            [True],
            ["input-investigate.wav"] * 33,
            "input-status.wav",
        ]:
            changed = copy.deepcopy(original)
            changed["scripted"]["inputFixtures"] = value
            self.assert_invalid(changed)
        for value in ["input-status.wav", "unknown.wav", "provider_real", None]:
            changed = copy.deepcopy(original)
            changed["scripted"]["replyFixture"] = value
            self.assert_invalid(changed)
        changed = copy.deepcopy(original)
        changed["scripted"]["inputFixtures"] = ["input-status.wav"] * 32
        changed["scripted"]["replyFixture"] = "guard.wav"
        result = m.parse_native_worker_config(raw(changed))
        self.assertEqual(result.model_profile.input_fixtures, ("input-status.wav",) * 32)
        self.assertEqual(result.model_profile.reply_fixture, "guard.wav")

    def test_duplicate_invalid_utf8_nonfinite_surrogates_depth_and_byte_bounds(self):
        original = m.encode_native_worker_config(fixture())
        values = [
            b"",
            b"[1]",
            b"\xff",
            b"NaN",
            b"{" + b'"schemaVersion":1,' + original[1:],
            original.replace(b'"port":11024', b'"port":NaN'),
            original.replace(
                b'"providerAccountId":"native-local"', b'"providerAccountId":"\\ud800"'
            ),
            b'{"unexpected":' + b"[" * 1100 + b"0" + b"]" * 1100 + b"}",
            b" " * (m.CONFIG_BYTES + 1),
        ]
        for value in values:
            with (
                self.subTest(size=len(value)),
                self.assertRaisesRegex(m.NativeWorkerConfigError, "^invalid_configuration$"),
            ):
                m.parse_native_worker_config(value)
        with self.assertRaises(m.NativeWorkerConfigError):
            m.parse_native_worker_config(original.decode())

    def test_constructor_clones_nested_public_values_and_rejects_role_scope_bypasses(self):
        value = fixture()
        original_binding = value.binding
        rebuilt = replace(value)
        self.assertIsNot(rebuilt.binding, original_binding)
        self.assertIsNot(rebuilt.binding.account_scope, original_binding.account_scope)
        object.__setattr__(original_binding.account_scope, "account_id", "changed_account")
        self.assertEqual(rebuilt.binding.account_scope.account_id, "account_demo")
        for mutate in [
            lambda x: object.__setattr__(x.binding.provider_scope, "provider", "sms"),
            lambda x: object.__setattr__(x.binding.provider_scope, "tenant_id", "other_tenant"),
            lambda x: object.__setattr__(x.binding, "binding_id", str(UUID(int=1))),
            lambda x: object.__setattr__(x.native_endpoint, "host", "remote.invalid"),
            lambda x: object.__setattr__(x.rehydration_endpoint, "host", "remote.invalid"),
            lambda x: object.__setattr__(x, "current_port", x.prepare_port),
            lambda x: object.__setattr__(x.native_credential, "value", "short"),
            lambda x: object.__setattr__(x, "current_bearer", x.prepare_bearer),
            lambda x: object.__setattr__(x.model_profile, "input_fixtures", ["input-status.wav"]),
            lambda x: object.__setattr__(x.model_profile, "cleanup_timeout_s", 2),
            lambda x: object.__setattr__(x, "livekit_url", "ws://remote.invalid"),
            lambda x: object.__setattr__(x, "livekit_token", "PRIVATE_WORKER_CONFIG_SENTINEL"),
        ]:
            changed = fixture()
            mutate(changed)
            with self.assertRaisesRegex(m.NativeWorkerConfigError, "^invalid_configuration$"):
                m.encode_native_worker_config(changed)
        with self.assertRaises(m.NativeWorkerConfigError):
            m.encode_native_worker_config(object())

    def test_pure_codec_and_import_never_load_sdk_assets_environment_or_network(self):
        value = fixture()
        encoded = m.encode_native_worker_config(value)
        with (
            patch.object(m.os, "open", side_effect=AssertionError("file")),
            patch.object(socket, "socket", side_effect=AssertionError("socket")),
        ):
            self.assertEqual(
                m.encode_native_worker_config(m.parse_native_worker_config(encoded)), encoded
            )
        script = r"""import asyncio,builtins,json,os,socket,subprocess,sys,threading
from unittest.mock import patch
def denied(*args,**kwargs):raise AssertionError('unexpectedI/O')
class NoEnvironment(dict):
 __getitem__=get=__iter__=__contains__=items=keys=values=copy=denied
with patch.object(os,'open',denied),patch.object(builtins,'open',denied),patch.object(os,'getenv',denied),patch.object(os,'environ',NoEnvironment()),patch.object(socket,'socket',denied),patch.object(subprocess,'Popen',denied),patch.object(threading.Thread,'start',denied),patch.object(asyncio,'create_task',denied):
 import services.channel_policy_demo.native_worker_config as config
 parsed=config.parse_native_worker_config(sys.argv[1].encode())
 assert config.encode_native_worker_config(parsed)==sys.argv[1].encode()
assert 'livekit.agents' not in sys.modules
assert 'services.channel_policy_demo._native_models_sdk' not in sys.modules
assert 'delegation_reliability' not in sys.modules
assert 'continuity_lab' not in sys.modules
assert 'psycopg' not in sys.modules
print(json.dumps({'cold':True}))
"""
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", script, encoded.decode()],
            cwd="/private/tmp",
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"cold": True})


class ClientComposition(unittest.IsolatedAsyncioTestCase):
    async def test_config_values_compose_genuine_narrow_clients_without_io(self):
        from channel_continuity.native_http import NativeHttpIntake
        from channel_continuity.native_rehydration import NativeContextHttpClient
        from services.channel_policy_demo.worker_current_result import WorkerCurrentResultClient

        value = fixture()
        with patch.object(socket, "socket", side_effect=AssertionError("network")):
            intake = NativeHttpIntake(value.native_endpoint, value.native_credential, value.binding)
            rehydration = NativeContextHttpClient(
                value.rehydration_endpoint, value.native_credential, value.binding
            )
            current = WorkerCurrentResultClient(
                value.current_endpoint, value.worker_binding, value.current_credential
            )
            self.assertEqual(intake.metrics()["active"], 0)
            self.assertEqual(current.pending_count, 0)
            await intake.aclose()
            await rehydration.aclose()
            await current.close()


class PrivateFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.parent = self.root / "worker"
        self.parent.mkdir(mode=0o700)
        self.path = self.parent / "worker.json"
        self.encoded = m.encode_native_worker_config(fixture())
        self.path.write_bytes(self.encoded)
        self.path.chmod(0o600)

    def test_actual_private_file_load_roundtrip_and_no_extra_reads(self):
        result = m.load_native_worker_config(self.path)
        self.assertEqual(m.encode_native_worker_config(result), self.encoded)
        self.assertEqual(self.path.read_bytes(), self.encoded)
        self.assertEqual(self.path.stat().st_nlink, 1)

    def test_absolute_canonical_json_path_required_before_any_content_read(self):
        for path in [
            str(self.path),
            Path("worker.json"),
            self.parent / ".." / "worker" / "worker.json",
            self.parent / ".env.providers",
        ]:
            with (
                patch.object(m.os, "read", side_effect=AssertionError("content read")) as read,
                self.assertRaisesRegex(m.NativeWorkerConfigError, "^invalid_configuration$"),
            ):
                m.load_native_worker_config(path)
            read.assert_not_called()

    def test_private_file_and_parent_modes_are_required(self):
        for mode in [0o644, 0o640, 0o400, 0o700]:
            self.path.chmod(mode)
            with self.assertRaises(m.NativeWorkerConfigError):
                m.load_native_worker_config(self.path)
        self.path.chmod(0o600)
        self.parent.chmod(0o755)
        with self.assertRaises(m.NativeWorkerConfigError):
            m.load_native_worker_config(self.path)
        self.parent.chmod(0o700)
        self.assertEqual(
            m.encode_native_worker_config(m.load_native_worker_config(self.path)), self.encoded
        )

    def test_effective_owner_is_checked_without_chown(self):
        with (
            patch.object(m.os, "getuid", return_value=os.getuid() + 1),
            self.assertRaises(m.NativeWorkerConfigError),
        ):
            m.load_native_worker_config(self.path)

    def test_zero_and_oversized_regular_files_are_rejected(self):
        for body in [b"", b" " * (m.CONFIG_BYTES + 1)]:
            self.path.write_bytes(body)
            with self.assertRaises(m.NativeWorkerConfigError):
                m.load_native_worker_config(self.path)

    def test_symlink_file_and_parent_aliases_are_rejected(self):
        alias = self.parent / "alias.json"
        alias.symlink_to(self.path)
        with self.assertRaises(m.NativeWorkerConfigError):
            m.load_native_worker_config(alias)
        parent_alias = self.root / "alias"
        parent_alias.symlink_to(self.parent, target_is_directory=True)
        with self.assertRaises(m.NativeWorkerConfigError):
            m.load_native_worker_config(parent_alias / "worker.json")

    def test_hard_link_regular_file_is_rejected_without_reading(self):
        alias = self.parent / "alias.json"
        os.link(self.path, alias)
        with (
            patch.object(m.os, "read", side_effect=AssertionError("hardlink content")) as read,
            self.assertRaises(m.NativeWorkerConfigError),
        ):
            m.load_native_worker_config(self.path)
        read.assert_not_called()

    def test_fifo_and_directory_paths_reject_without_opening_content(self):
        self.path.unlink()
        os.mkfifo(self.path, 0o600)
        with (
            patch.object(m.os, "read", side_effect=AssertionError("FIFO read")) as read,
            self.assertRaises(m.NativeWorkerConfigError),
        ):
            m.load_native_worker_config(self.path)
        read.assert_not_called()
        self.path.unlink()
        self.path.mkdir(mode=0o700)
        with self.assertRaises(m.NativeWorkerConfigError):
            m.load_native_worker_config(self.path)

    def test_regular_to_fifo_open_race_is_nonblocking_and_closes_descriptors(self):
        actual = os.open
        opened = []

        def raced(path, flags, mode=0o777, *, dir_fd=None):
            if path == "worker.json":
                self.assertTrue(flags & os.O_NONBLOCK)
                self.assertTrue(flags & os.O_NOFOLLOW)
                self.path.unlink()
                os.mkfifo(self.path, 0o600)
            descriptor = actual(path, flags, mode, dir_fd=dir_fd)
            opened.append(descriptor)
            return descriptor

        with (
            patch.object(m.os, "open", raced),
            patch.object(m.os, "read", side_effect=AssertionError("FIFO read")) as read,
            self.assertRaises(m.NativeWorkerConfigError),
        ):
            m.load_native_worker_config(self.path)
        read.assert_not_called()
        self.assertEqual(len(opened), 2)
        for descriptor in opened:
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def race_after_read(self, change):
        actual = os.read
        changed = False

        def raced(descriptor, maximum):
            nonlocal changed
            value = actual(descriptor, maximum)
            if value and not changed:
                changed = True
                change()
            return value

        with (
            patch.object(m.os, "read", raced),
            patch.object(
                m, "parse_native_worker_config", side_effect=AssertionError("raced bytes parsed")
            ) as parse,
            self.assertRaisesRegex(m.NativeWorkerConfigError, "^invalid_configuration$"),
        ):
            m.load_native_worker_config(self.path)
        self.assertTrue(changed)
        parse.assert_not_called()

    def test_same_inode_content_metadata_change_after_read_is_rejected(self):
        def change():
            before = self.path.stat()
            self.path.write_bytes(self.encoded)
            os.utime(self.path, ns=(before.st_atime_ns, before.st_mtime_ns + 1000000))

        self.race_after_read(change)

    def test_file_path_replacement_after_read_is_rejected(self):
        def change():
            self.path.rename(self.parent / "saved.json")
            self.path.write_bytes(self.encoded)
            self.path.chmod(0o600)

        self.race_after_read(change)

    def test_parent_path_replacement_after_read_is_rejected(self):
        def change():
            self.parent.rename(self.root / "saved")
            self.parent.mkdir(mode=0o700)
            self.path.write_bytes(self.encoded)
            self.path.chmod(0o600)

        self.race_after_read(change)

    def test_file_or_parent_permissions_changed_after_read_are_rejected(self):
        self.race_after_read(lambda: self.path.chmod(0o644))
        self.path.chmod(0o600)
        self.race_after_read(lambda: self.parent.chmod(0o755))
        self.parent.chmod(0o700)


if __name__ == "__main__":
    unittest.main()
