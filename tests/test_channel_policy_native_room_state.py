"""Parent CAS and bounded real private-file ownership controls (no external I/O)."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from channel_continuity.codec import AccountScope, ProviderScope
from channel_continuity.native_models import NativeBinding, NativeCredential
from services.channel_policy_demo import native_room_state as state
from services.channel_policy_demo.native_worker_config import NativeWorkerConfig
from services.channel_policy_demo.room_control import RoomBinding, RoomOpen


def uid(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012d}"


def values(command: int = 2) -> tuple[state.RoomDescriptor, NativeWorkerConfig]:
    start = state.StartCommand(uid(1), "0", uid(command))
    binding = RoomBinding(
        uid(3), "a" * 43, "room_a", "browser_a", "agent_a", "2030-01-01T00:00:00.000Z"
    )
    config = NativeWorkerConfig(
        uid(4),
        NativeBinding(
            uid(3),
            ProviderScope("tenant_a", "livekit", "provider_a"),
            AccountScope("tenant_a", "account_a"),
            "case_a",
            "conversation_a",
            "room_a",
            "browser_a",
            "agent_a",
        ),
        "YQ.Yg.Yw",
        NativeCredential("a" * 43),
        "b" * 43,
        "c" * 43,
    )
    descriptor = state.RoomDescriptor(
        start,
        "1",
        RoomOpen(uid(5), "7", uid(6), binding, "d" * 43),
        "YQ.Yg.ZA",
        hashlib.sha256(state.encode_native_worker_config(config)).hexdigest(),
        state.room_metadata(start, uid(3)),
    )
    return descriptor, config


def receipt(descriptor: state.RoomDescriptor, digest: str | None) -> state.ClosedRoomReceipt:
    status = state.NativeRoomStatus(
        uid(1),
        "1",
        descriptor.start.command_id,
        "closed",
        "2030-01-01T00:00:00.000Z",
        state.NodeRoomCursor(uid(5), "8", False),
    )
    return state.ClosedRoomReceipt(
        status,
        state.RoomIdentity("room_a", descriptor.metadata),
        digest,
        None,
        "never_created",
        "never_started",
    )


class ParentRoomStateTests(unittest.TestCase):
    def test_cold_parent_import_does_not_load_agents_or_create_external_io(self) -> None:
        script = """
import sys
attempts=[]
def audit(event, args):
 if event in {'socket.connect','socket.bind','subprocess.Popen'}:
  attempts.append(event)
  raise RuntimeError('external_io_denied')
sys.addaudithook(audit)
import services.channel_policy_demo.native_room
assert 'livekit.agents' not in sys.modules
assert 'livekit.rtc' not in sys.modules
assert 'openai' not in sys.modules
assert not attempts
print('cold_parent_ok')
"""
        actual = subprocess.run(
            [sys.executable, "-I", "-B", "-c", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(actual.stdout.strip(), "cold_parent_ok")

    def test_browser_grant_uses_only_canonical_loopback_ws_urls(self) -> None:
        value = state.BrowserRoomGrant(
            uid(1),
            "1",
            uid(2),
            "YQ.Yg.Yw",
            "room_a",
            "browser_a",
            "agent_a",
            uid(3),
            "2030-01-01T00:00:00.000Z",
        )
        self.assertEqual(value.url, "ws://127.0.0.1:17880")
        for port in (1, 7880, 17880, 65535):
            self.assertEqual(
                replace(value, url=f"ws://127.0.0.1:{port}").payload()["rtc"]["url"],
                f"ws://127.0.0.1:{port}",
            )
        for url in (
            "ws://127.0.0.1:0",
            "ws://127.0.0.1:65536",
            "ws://127.0.0.1:017880",
            "ws://127.0.0.1:17880/",
            "ws://127.0.0.1:17880?x=1",
            "ws://127.0.0.1:17880#x",
            "ws://user:secret@127.0.0.1:17880",
            "ws://localhost:17880",
            "ws://127.0.0.2:17880",
            "wss://127.0.0.1:17880",
            "http://127.0.0.1:17880",
            None,
        ):
            with (
                self.subTest(url=url),
                self.assertRaisesRegex(state.NativeRoomError, "^invalid_input$"),
            ):
                replace(value, url=url)

    def test_closed_commands_roundtrip_and_parent_node_versions_are_separate(self) -> None:
        start = state.StartCommand(uid(1), "0", uid(2))
        ending = state.EndCommand(uid(1), "1", uid(2))
        self.assertEqual(state.parse_start_command(state.encode_start_command(start)), start)
        self.assertEqual(state.parse_end_command(state.encode_end_command(ending)), ending)
        descriptor, config = values()
        encoded = json.loads(state.encode_descriptor(descriptor, config))
        self.assertEqual(
            (encoded["generation"], encoded["nodeOpen"]["expectedGeneration"]), ("1", "7")
        )

    def test_command_shape_duplicate_keys_noncanonical_generation_and_secret_fields_denied(
        self,
    ) -> None:
        good = json.loads(state.encode_start_command(state.StartCommand(uid(1), "0", uid(2))))
        for modified in (
            {**good, "token": "PRIVATE_SENTINEL"},
            {**good, "expectedGeneration": "00"},
            {**good, "expectedGeneration": True},
            {**good, "schemaVersion": True},
            {**good, "ownerEpoch": "PRIVATE_SENTINEL"},
        ):
            with self.subTest(modified=tuple(modified)):
                with self.assertRaises(state.NativeRoomError) as caught:
                    state.parse_start_command(json.dumps(modified).encode())
                self.assertEqual(str(caught.exception), "invalid_input")
        with self.assertRaises(state.NativeRoomError):
            state.parse_start_command(b'{"schemaVersion":1,"schemaVersion":1}')

    def test_descriptor_requires_exact_worker_bytes_scope_binding_and_distinct_caps(self) -> None:
        descriptor, config = values()
        raw = state.encode_descriptor(descriptor, config)
        self.assertLessEqual(len(raw), state.DESCRIPTOR_BYTES)
        changed = NativeWorkerConfig(
            config.profile_id,
            config.binding,
            "YQ.Yg.ZQ",
            config.native_credential,
            config.prepare_bearer,
            config.current_bearer,
        )
        with self.assertRaises(state.NativeRoomError):
            state.encode_descriptor(descriptor, changed)
        conflicting = state.RoomDescriptor(
            descriptor.start,
            descriptor.generation,
            RoomOpen(
                descriptor.node_open.node_epoch,
                descriptor.node_open.expected_generation,
                descriptor.node_open.open_id,
                descriptor.node_open.binding,
                config.current_bearer,
            ),
            descriptor.browser_token,
            descriptor.worker_config_sha256,
            descriptor.metadata,
        )
        with self.assertRaises(state.NativeRoomError):
            state.encode_descriptor(conflicting, config)

    def test_private_creation_is_complete_0600_and_atomic_at_link_visibility(self) -> None:
        descriptor, config = values()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve() / "rooms"
            owner = state.PrivateRoomState(directory)
            linked: list[bytes] = []
            actual = os.link

            def observe(
                source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                target: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                **keywords: object,
            ) -> None:
                actual(source, target, **keywords)
                linked.append(Path(target).read_bytes())

            with patch.object(state.os, "link", side_effect=observe):
                files = owner.prepare(descriptor, config)
            self.assertEqual(len(linked), 2)
            self.assertEqual(linked[1], state.encode_descriptor(descriptor, config))
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(files.directory.stat().st_mode), 0o700)
            self.assertEqual(
                {entry.name for entry in files.directory.iterdir()},
                {"worker.json", "descriptor.json"},
            )
            for path, digest in (
                (files.worker_config_path, files.config_sha256),
                (files.descriptor_path, files.descriptor_sha256),
            ):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(path.stat().st_nlink, 1)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_existing_unresolved_active_files_are_not_reset_or_adopted(self) -> None:
        descriptor, config = values()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve() / "rooms"
            first = state.PrivateRoomState(directory)
            files = first.prepare(descriptor, config)
            before = files.descriptor_path.read_bytes()
            with self.assertRaises(state.NativeRoomError) as caught:
                state.PrivateRoomState(directory).prepare(descriptor, config)
            self.assertEqual(caught.exception.code, "recovery_required")
            self.assertEqual(files.descriptor_path.read_bytes(), before)

    def test_terminal_receipt_replaces_one_history_slot_without_secret_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve() / "rooms"
            for command in (2, 9):
                descriptor, config = values(command)
                owner = state.PrivateRoomState(directory)
                files = owner.prepare(descriptor, config)
                owner.finish(receipt(descriptor, files.descriptor_sha256))
                self.assertEqual({path.name for path in directory.iterdir()}, {"lastclosed.json"})
                raw = (directory / "lastclosed.json").read_bytes()
                self.assertEqual(json.loads(raw)["status"]["originalStartCommandId"], uid(command))
                for secret in (
                    config.livekit_token,
                    descriptor.browser_token,
                    config.native_credential.value,
                    config.prepare_bearer,
                    config.current_bearer,
                    descriptor.node_open.room_view_bearer,
                ):
                    self.assertNotIn(secret.encode(), raw)
            self.assertEqual(stat.S_IMODE((directory / "lastclosed.json").stat().st_mode), 0o600)

    def test_foreign_replacement_prevents_cleanup_and_is_preserved(self) -> None:
        descriptor, config = values()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve() / "rooms"
            owner = state.PrivateRoomState(directory)
            files = owner.prepare(descriptor, config)
            held = files.directory / "owned-held"
            files.descriptor_path.rename(held)
            files.descriptor_path.write_bytes(b"PRIVATE_FOREIGN_FILE")
            files.descriptor_path.chmod(0o600)
            with self.assertRaises(state.NativeRoomError):
                owner.finish(receipt(descriptor, files.descriptor_sha256))
            self.assertEqual(files.descriptor_path.read_bytes(), b"PRIVATE_FOREIGN_FILE")
            self.assertTrue(held.exists())

    def test_failed_atomic_publish_retains_exact_owned_partial_for_cleanup(self) -> None:
        descriptor, config = values()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve() / "rooms"
            owner = state.PrivateRoomState(directory)
            with (
                patch.object(state.os, "link", side_effect=OSError("PRIVATE_LINK_ERROR")),
                self.assertRaises(state.NativeRoomError) as caught,
            ):
                owner.prepare(descriptor, config)
            self.assertEqual(str(caught.exception), "unavailable")
            self.assertEqual(
                {entry.name for entry in (directory / "active").iterdir()}, {"worker.json.pending"}
            )
            owner.finish(receipt(descriptor, None))
            self.assertEqual({entry.name for entry in directory.iterdir()}, {"lastclosed.json"})

    def test_symlink_root_and_world_readable_file_are_never_adopted(self) -> None:
        descriptor, config = values()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real = root / "real"
            real.mkdir(mode=0o700)
            alias = root / "alias"
            alias.symlink_to(real, target_is_directory=True)
            with self.assertRaises(state.NativeRoomError):
                state.PrivateRoomState(alias).prepare(descriptor, config)
            final = real / "lastclosed.json"
            final.write_bytes(b"{}")
            final.chmod(0o644)
            with self.assertRaises(state.NativeRoomError):
                state.PrivateRoomState(real).prepare(descriptor, config)
            self.assertEqual(final.read_bytes(), b"{}")

    def test_asof_absence_and_actual_reap_are_not_invented_for_early_failure(self) -> None:
        descriptor, _ = values()
        proof = receipt(descriptor, None)
        wire = json.loads(state.encode_closed_receipt(proof))
        self.assertEqual(wire["room"]["disposition"], "never_created")
        self.assertIsNone(wire["room"]["sid"])
        self.assertEqual(wire["worker"]["disposition"], "never_started")
        self.assertIsNone(wire["worker"]["exitCode"])
        with self.assertRaises(state.NativeRoomError):
            state.ClosedRoomReceipt(
                proof.status, proof.room, None, None, "observed_absent", "never_started"
            )

    def test_private_read_rejects_same_inode_permission_link_and_same_size_content_races(
        self,
    ) -> None:
        def scenario(mutation: str) -> None:
            with tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary).resolve()
                path = directory / "private.json"
                original = b'{"value":"original"}'
                changed = b'{"value":"modified"}'
                self.assertEqual(len(original), len(changed))
                path.write_bytes(original)
                path.chmod(0o600)
                self.assertEqual(state._read_private(path, 4096), original)
                initial = path.stat()
                actual_read = os.read
                mutated = False

                def read(fd: int, size: int) -> bytes:
                    nonlocal mutated
                    chunk = actual_read(fd, size)
                    if not mutated:
                        mutated = True
                        if mutation == "permission":
                            path.chmod(0o644)
                        elif mutation == "hardlink":
                            os.link(path, directory / "linked.json")
                        else:
                            path.write_bytes(changed)
                            os.utime(path, ns=(initial.st_atime_ns, initial.st_mtime_ns + 1000000))
                    return chunk

                with (
                    patch.object(state.os, "read", side_effect=read),
                    self.assertRaises(state.NativeRoomError) as caught,
                ):
                    state._read_private(path, 4096)
                self.assertEqual(caught.exception.code, "recovery_required")
                self.assertTrue(path.exists())
                self.assertEqual(
                    path.read_bytes(), changed if mutation == "same_size_content" else original
                )
                self.assertEqual(path.stat().st_ino, initial.st_ino)
                if mutation == "permission":
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
                elif mutation == "hardlink":
                    self.assertEqual(path.stat().st_nlink, 2)
                    self.assertTrue((directory / "linked.json").is_file())

        for mutation in ("permission", "hardlink", "same_size_content"):
            with self.subTest(mutation=mutation):
                scenario(mutation)

    def test_room_metadata_is_nonsecret_exact_ownership_data_and_invalid_utf8_is_finite(
        self,
    ) -> None:
        descriptor, _ = values()
        value = json.loads(descriptor.metadata)
        self.assertEqual(
            set(value), {"schemaVersion", "kind", "ownerEpoch", "startCommandId", "bindingId"}
        )
        with self.assertRaises(state.NativeRoomError) as caught:
            state.RoomIdentity("room_a", "\ud800")
        self.assertEqual(str(caught.exception), "invalid_input")


if __name__ == "__main__":
    unittest.main()
