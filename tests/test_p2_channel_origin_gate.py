"""Pure parent-gate controls; no process, database, media or provider starts."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "origin_parent_gate_tested", ROOT / "local-setup/scripts/p2_channel_origin_check.py"
)
assert SPEC is not None and SPEC.loader is not None
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


class GateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()

    def test_plan_is_inert_and_keeps_exact_required_scope(self):
        output = io.StringIO()
        with (
            patch.object(m, "run", side_effect=AssertionError("actual run forbidden")),
            patch.object(m.core, "load_setup", side_effect=AssertionError("settings forbidden")),
            patch.object(m, "Children", side_effect=AssertionError("process forbidden")),
            patch.object(m, "private_report", side_effect=AssertionError("files forbidden")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(m.main(["--plan"]), 0)
        value = json.loads(output.getvalue())
        self.assertEqual((len(value["assertions"]), len(set(value["assertions"]))), (14, 14))
        self.assertEqual((len(value["commands"]), len(set(value["commands"]))), (16, 16))
        self.assertIn("origin-current", value["commands"])
        self.assertEqual((value["expected_process_groups"], value["max_process_groups"]), (16, 24))
        self.assertEqual((value["deadline_seconds"], value["cleanup_seconds"]), (180, 20))
        self.assertEqual((value["schemas"], value["scheduled_owned_sigkills"]), (3, 1))
        self.assertEqual(
            (value["stream_bytes"], value["aggregate_capture_bytes"]), (65536, 2097152)
        )
        self.assertEqual(value["installed_actual_assertions"], 0)
        self.assertFalse(value["provider_calls"])
        self.assertEqual(
            (value["rtc_rooms"], value["carrier_sends"], value["supplier_mutations"]), (0, 0, 0)
        )
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_minimal_environment_never_inherits_provider_proxy_or_pg_selectors(self):
        original = {
            "PATH": "/pinned/bin",
            "LANG": "en_US.UTF-8",
            "CI": "old",
            "NO_COLOR": "old",
            "__CF_USER_TEXT_ENCODING": "0x0:0:0",
            "HOME": "/private/unrelated",
            "OPENAI_API_KEY": "PRIVATE_PROVIDER_SENTINEL",
            "HTTPS_PROXY": "http://private.invalid",
            "PGSERVICE": "unrelated",
            "PYTHONPATH": "/unrelated",
        }
        with patch.dict(m.os.environ, original, clear=True):
            value = m.base_environment()
        self.assertEqual(
            value,
            {
                "PATH": "/pinned/bin",
                "LANG": "en_US.UTF-8",
                "CI": "1",
                "NO_COLOR": "1",
                "__CF_USER_TEXT_ENCODING": "0x0:0:0",
            },
        )
        self.assertNotIn("PRIVATE_PROVIDER_SENTINEL", repr(value))
        with (
            patch.dict(m.os.environ, {}, clear=True),
            self.assertRaisesRegex(m.OriginGateError, "^missing_setup$"),
        ):
            m.base_environment()

    def test_atomic_publication_is_complete_before_visibility_and_remains_private(self):
        target = self.directory / "ready.json"
        value = {"schema_version": 1, "body": "synthetic" * 1000}
        actual_link = os.link

        def link(source, destination, **options):
            self.assertFalse(target.exists())
            self.assertEqual(Path(source).read_bytes(), m.json_bytes(value))
            self.assertEqual(stat.S_IMODE(Path(source).stat().st_mode), 0o600)
            return actual_link(source, destination, **options)

        with patch.object(m.os, "link", side_effect=link):
            m.publish(target, value)
        self.assertEqual(m.read(target), value)
        self.assertEqual((target.stat().st_nlink, stat.S_IMODE(target.stat().st_mode)), (1, 0o600))
        self.assertEqual(list(self.directory.iterdir()), [target])

    def test_existing_publication_and_failed_pending_write_preserve_prior_files(self):
        target = self.directory / "ready.json"
        m.publish(target, {"schema_version": 1, "original": True})
        original = target.read_bytes()
        with self.assertRaises(FileExistsError):
            m.publish(target, {"changed": True})
        self.assertEqual(target.read_bytes(), original)
        with (
            patch.object(m.os, "fsync", side_effect=OSError("PRIVATE_DISK_SENTINEL")),
            self.assertRaises(OSError),
        ):
            m.publish(self.directory / "failed.json", {"schema_version": 1})
        self.assertEqual(list(self.directory.iterdir()), [target])

    def test_private_reads_reject_aliases_modes_duplicates_and_oversized_data(self):
        target = self.directory / "ready.json"
        m.publish(target, {"schema_version": 1})
        linked = self.directory / "alias.json"
        linked.symlink_to(target)
        with self.assertRaises(m.OriginGateError):
            m.read(linked)
        linked.unlink()
        os.chmod(target, 0o644)
        with self.assertRaises(m.OriginGateError):
            m.read(target)
        os.chmod(target, 0o600)
        target.write_bytes(b'{"same":1,"same":2}')
        with self.assertRaises(m.core.GateError):
            m.read(target)
        target.write_bytes(b"x" * 65)
        with self.assertRaises(m.OriginGateError):
            m.read(target, 64)

    def test_transient_two_link_marker_is_deferred_and_completed_marker_not_reparsed(self):
        target = self.directory / "ready.json"
        m.publish(target, {"schema_version": 1, "value": "complete"})
        pending = self.directory / ".ready.pending"
        os.link(target, pending)
        read_links = []
        original_read = m.read

        class Child:
            returncode = None

            def wait(self, *, timeout):
                pending.unlink()
                raise m.ProcessTimeout("synthetic observer yield")

        children = m.Children(self.directory, time.monotonic() + 1, time.monotonic() + 2)
        children.children["race"] = Child()

        def read(path, maximum=262144):
            read_links.append(path.stat().st_nlink)
            return original_read(path, maximum)

        with patch.object(m, "read", side_effect=read):
            result = children.wait_json("race", target, 0.5)
        self.assertEqual(result, {"schema_version": 1, "value": "complete"})
        self.assertEqual(read_links, [1])

    def test_malformed_complete_marker_fails_without_retry_or_restart(self):
        target = self.directory / "ready.json"
        target.write_bytes(b'{"truncated":')
        os.chmod(target, 0o600)
        child = SimpleNamespace(
            returncode=None, wait=lambda **_: self.fail("invalid JSON was retried")
        )
        children = m.Children(self.directory, time.monotonic() + 1, time.monotonic() + 2)
        children.children["race"] = child
        with self.assertRaises(ValueError):
            children.wait_json("race", target, 0.5)

    def test_duplicate_or_unregistered_child_role_never_constructs_a_process(self):
        children = m.Children(self.directory, time.monotonic() + 1, time.monotonic() + 2)
        existing = SimpleNamespace()
        children.children["race"] = existing
        with patch.object(m, "GroupedOwnedProcess", side_effect=AssertionError("no process")):
            for role in ("race", "unregistered"):
                with self.subTest(role=role), self.assertRaises(m.OriginGateError):
                    children.start(role, ["/pinned/node"], {"PATH": "/pinned"}, self.directory)
        self.assertEqual(children.children, {"race": existing})

    def test_abandoned_or_expired_start_never_constructs_a_process(self):
        children = m.Children(self.directory, time.monotonic() - 1, time.monotonic() + 1)
        with (
            patch.object(m, "GroupedOwnedProcess", side_effect=AssertionError("no process")),
            self.assertRaisesRegex(m.OriginGateError, "^deadline_exceeded$"),
        ):
            children.start("race", ["/pinned/node"], {"PATH": "/pinned"}, self.directory)
        self.assertEqual(children.children, {})

    def test_changed_payload_preserves_original_p2_order_and_uses_exact_utf8_digest(self):
        original = (
            '{"schemaVersion":1,"kind":"investigation","operationKey":"original","body":"café😀"}'
        )
        result = m.changed_frame({"canonicalPayload": original}, body="changed café😀")
        expected = original.replace("café😀", "changed café😀")
        self.assertEqual(
            result,
            {
                "schemaVersion": 1,
                "canonicalPayload": expected,
                "payloadDigest": hashlib.sha256(expected.encode()).hexdigest(),
            },
        )
        self.assertEqual(json.loads(result["canonicalPayload"])["operationKey"], "original")

    def test_report_target_cannot_reuse_existing_report_or_artifact_or_other_parent(self):
        root = self.directory / "repo"
        root.mkdir(mode=0o700)
        target = m.private_report(root, None)
        self.assertEqual(target.parent, root / ".local/validation/p2-channel-origin")
        self.assertFalse(target.exists())
        m.publish(target, {"immutable": True})
        with self.assertRaises(m.OriginGateError):
            m.private_report(root, target)
        other = target.with_name("other.json")
        other.with_name(other.stem + "-artifacts").mkdir(mode=0o700)
        with self.assertRaises(m.OriginGateError):
            m.private_report(root, other)
        with self.assertRaises(m.OriginGateError):
            m.private_report(root, self.directory / "outside.json")

    def test_finite_diagnostics_contain_raising_getters_unhashable_and_private_codes(self):
        class Raising(Exception):
            @property
            def code(self):
                raise RuntimeError("PRIVATE_GETTER_SENTINEL")

        for error in (
            Raising(),
            SimpleNamespace(code=[]),
            SimpleNamespace(code={}),
            SimpleNamespace(code="PRIVATE_CODE_SENTINEL"),
        ):
            self.assertEqual(m.finite_code(error), "component_failed")
        self.assertEqual(m.finite_code(m.OriginGateError("source_changed")), "source_changed")

    def test_cli_failure_contains_no_private_dependency_text(self):
        output = io.StringIO()
        with (
            patch.object(m, "private_report", side_effect=RuntimeError("PRIVATE_PATH_SENTINEL")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(m.main([]), 1)
        self.assertEqual(
            json.loads(output.getvalue()),
            {"schema_version": 1, "status": "failed", "code": "component_failed"},
        )
        self.assertNotIn("PRIVATE", output.getvalue())


if __name__ == "__main__":
    unittest.main()
