"""Pure gate guards; no child, Node, PostgreSQL, browser, SFU or provider starts."""

from __future__ import annotations

import contextlib
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
    "p2_result_receiver_gate_under_test",
    ROOT / "local-setup/scripts/p2_result_receiver_check.py",
)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)

COMMANDS = [
    "compile-public",
    "compile-fixture",
    "setup",
    "upgrade",
    "exercise",
    "commit-before-ack",
    "recover",
    "serve",
    "p3-consumer",
    "backup-container",
    "backup-dump",
    "backup-copy",
    "backup-restore",
    "restore-check",
    "cleanup",
    "backup-remove",
]


class ResultReceiverGateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name).resolve()
        self.values = {
            "POSTGRES_MIGRATION_PASSWORD": "synthetic-owner-password-" + "o" * 32,
            "POSTGRES_PASSWORD": "synthetic-runtime-password-" + "r" * 32,
        }
        self.common = {
            "P2_RESULT_SCHEMA": "p2_result_" + "a" * 32,
            "P2_RESULT_DIRECTORY": str(self.work),
            "P2_RESULT_PG_PORT": "5432",
            "P2_RESULT_SHARED_FIXTURE": str(ROOT / "contracts/delegation/result-receiver-v1.json"),
            "P2_RESULT_CASE_AUTHORIZATION": "Bearer " + "c" * 43,
        }
        self.tokens = {"P2_RESULT_" + name: "t" * 43 for name in m.CAPABILITIES}

    def environment(self, mode="serve"):
        with patch.object(m.core, "base_environment", return_value={"PATH": "/usr/bin"}):
            return m.child_environment(self.values, self.common, self.tokens, mode)

    def test_plan_has_exact_sixteen_groups_and_separate_bounds_without_resources(self):
        output = io.StringIO()
        with (
            patch.object(m.core, "load_setup", side_effect=AssertionError("setup forbidden")),
            patch.object(m, "Children", side_effect=AssertionError("children forbidden")),
            patch.object(m, "run", side_effect=AssertionError("actual run forbidden")),
            patch.object(
                m.evidence, "private_directory", side_effect=AssertionError("files forbidden")
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(m.main(["--plan"]), 0)
        plan = json.loads(output.getvalue())
        self.assertEqual(plan["status"], "planned")
        self.assertEqual(plan["commands"], COMMANDS)
        self.assertEqual(len(set(plan["commands"])), 16)
        self.assertEqual(plan["max_process_groups"], 16)
        self.assertEqual((len(plan["storage_assertions"]), len(plan["return_assertions"])), (16, 4))
        self.assertEqual((plan["deadline_seconds"], plan["cleanup_seconds"]), (180, 20))
        self.assertEqual(plan["deadline_seconds"] - plan["cleanup_seconds"], 160)
        self.assertEqual((plan["stream_bytes"], plan["aggregate_capture_bytes"]), (65536, 2097152))
        self.assertEqual((plan["rtc_rooms"], plan["carrier_calls"]), (0, 0))
        self.assertIs(plan["provider_calls"], False)
        self.assertIs(plan["private_provider_config_reads"], False)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_public_build_includes_current_examples_and_starter_in_one_owned_group(self):
        artifacts = self.work / "artifacts"
        artifacts.mkdir(mode=0o700)
        project = ROOT / "projects/channel-continuity"
        compiler = project / "node_modules/typescript/bin/tsc"
        with patch.object(m, "Children", side_effect=AssertionError("no child in preparation")):
            command = m.public_build_command(ROOT, self.work, artifacts, "/pinned/node", compiler)
        self.assertEqual(
            command,
            m.node_argv(
                "/pinned/node",
                compiler,
                "--build",
                "--force",
                *(
                    str(self.work / ("build-" + name + ".json"))
                    for name in ("production", "examples", "starter")
                ),
            ),
        )
        retained = m.load(artifacts / "compiler-configurations.json")
        self.assertEqual(
            set(retained), {"build-production.json", "build-examples.json", "build-starter.json"}
        )
        for name, base, output in (
            ("production", "tsconfig.json", project / "dist"),
            ("examples", "tsconfig.examples.json", project / "dist/examples"),
            ("starter", "tsconfig.starter.json", project / "dist/examples"),
        ):
            config = retained["build-" + name + ".json"]
            self.assertEqual(config["extends"], str(project / base))
            self.assertEqual(config["compilerOptions"]["outDir"], str(output))
            self.assertEqual(
                config["compilerOptions"]["tsBuildInfoFile"],
                str(self.work / (name + ".tsbuildinfo")),
            )
            self.assertEqual(
                stat.S_IMODE((self.work / ("build-" + name + ".json")).stat().st_mode), 0o600
            )
        self.assertEqual(m.plan()["public_compile_profiles"], ["production", "examples", "starter"])

    def test_source_snapshot_binds_all_compiler_bases_and_built_examples(self):
        base = m.source_snapshot(ROOT)
        expected = {
            "projects/channel-continuity/" + name
            for name in (
                "tsconfig.json",
                "tsconfig.examples.json",
                "tsconfig.starter.json",
                "tsconfig.pg.json",
                "tsconfig.test.json",
            )
        } | {
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "projects/channel-continuity/examples").rglob("*.ts")
        }
        self.assertTrue(expected.issubset(base))
        original_read = m.prior.source_bytes
        # Model a base-config or example edit during the run without changing the checkout.
        for name in (
            "projects/channel-continuity/tsconfig.examples.json",
            "projects/channel-continuity/examples/standalone/external-http.ts",
        ):
            selected = ROOT / name

            def read(path, selected=selected):
                raw = original_read(path)
                return raw + b"\n" if path == selected else raw

            with patch.object(m.prior, "source_bytes", side_effect=read):
                changed = m.source_snapshot(ROOT)
            self.assertEqual({key for key in base if base[key] != changed[key]}, {name})
            self.assertEqual(set(base), set(changed))

    def test_setup_has_both_roles_upgrade_cleanup_owner_only_and_other_modes_runtime_only(self):
        role_keys = {"P2_RESULT_OWNER_PASSWORD", "P2_RESULT_RUNTIME_PASSWORD"}
        for mode in sorted(m.ROLES):
            with self.subTest(mode=mode):
                env = self.environment(mode)
                expected = (
                    role_keys
                    if mode == "setup"
                    else {"P2_RESULT_OWNER_PASSWORD"}
                    if mode in {"upgrade", "cleanup"}
                    else {"P2_RESULT_RUNTIME_PASSWORD"}
                )
                self.assertEqual(set(env) & role_keys, expected)
                m.validate_child_environment(env, mode)
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "PRIVATE_PROVIDER_SENTINEL",
                "HTTPS_PROXY": "http://private.invalid",
                "PGSERVICE": "private-service",
                "PYTHONPATH": "/private/not-a-consumer",
            },
        ):
            env = m.child_environment(self.values, self.common, self.tokens, "serve")
        self.assertFalse({"OPENAI_API_KEY", "HTTPS_PROXY", "PGSERVICE", "PYTHONPATH"} & env.keys())

    def test_ambient_selectors_and_wrong_roles_fail_before_any_child_construction(self):
        with patch.object(m, "GroupedOwnedProcess") as constructor:
            for key in (
                "OPENAI_API_KEY",
                "DEEPGRAM_API_KEY",
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "PGHOST",
                "PGHOSTADDR",
                "PGSERVICE",
                "PGOPTIONS",
                "PYTHONPATH",
            ):
                with self.subTest(key=key), self.assertRaises(m.GateError) as caught:
                    m.validate_child_environment(
                        {**self.environment(), key: "PRIVATE_SENTINEL"}, "serve"
                    )
                self.assertEqual(caught.exception.code, "invalid_environment")
            for mode, key, remove in (
                ("setup", "P2_RESULT_OWNER_PASSWORD", True),
                ("setup", "P2_RESULT_RUNTIME_PASSWORD", True),
                ("upgrade", "P2_RESULT_RUNTIME_PASSWORD", False),
                ("cleanup", "P2_RESULT_RUNTIME_PASSWORD", False),
                ("serve", "P2_RESULT_OWNER_PASSWORD", False),
            ):
                env = self.environment(mode)
                if remove:
                    env.pop(key)
                else:
                    env[key] = "private-wrong-role-" + "x" * 32
                with self.subTest(mode=mode, key=key), self.assertRaises(m.GateError):
                    m.validate_child_environment(env, mode)
            with self.assertRaises(m.GateError):
                m.child_environment(self.values, self.common, self.tokens, "unknown")
            constructor.assert_not_called()

    def test_malformed_scope_port_tokens_and_paths_reject_without_admission(self):
        for key, value in (
            ("P2_RESULT_SCHEMA", "p2_result_" + "A" * 32),
            ("P2_RESULT_SCHEMA", "p2_result_" + "a" * 32 + "\n"),
            ("P2_RESULT_PG_PORT", "0"),
            ("P2_RESULT_PG_PORT", "65536"),
            ("P2_RESULT_PG_PORT", "05432"),
            ("P2_RESULT_PG_PORT", True),
            ("P2_RESULT_CASE_AUTHORIZATION", "Bearer " + "c" * 43 + "\n"),
            ("P2_RESULT_ACCOUNT_TOKEN", "short"),
            ("P2_RESULT_PUBLISHER_TOKEN", "t" * 42),
            ("P2_RESULT_DIRECTORY", "relative/work"),
            ("P2_RESULT_SHARED_FIXTURE", "relative/fixture.json"),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(m.GateError) as caught:
                m.validate_child_environment({**self.environment(), key: value}, "serve")
            self.assertEqual(caught.exception.code, "invalid_environment")
        with self.assertRaises(m.GateError):
            m.child_environment(
                self.values, {**self.common, "scope": "foreign"}, self.tokens, "serve"
            )

    def test_retention_preserves_exact_existing_bytes_and_never_copies_secrets_or_conflicts(self):
        source, target = self.work / "source.json", self.work / "retained.json"
        raw = b'{"schema_version":1,"status":"observed"}\n'
        m.evidence.write_private(source, raw)
        m.retain(source, target, ("PRIVATE_SENTINEL",))
        original_inode = target.stat().st_ino
        self.assertEqual(target.read_bytes(), raw)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        m.retain(source, target, ("PRIVATE_SENTINEL",))
        self.assertEqual(target.stat().st_ino, original_inode)
        other = self.work / "changed.json"
        m.evidence.write_private(other, b'{"changed":true}')
        with self.assertRaises(m.GateError) as caught:
            m.retain(other, target, ())
        self.assertEqual(caught.exception.code, "invalid_artifact")
        self.assertEqual(target.read_bytes(), raw)
        secret, rejected = self.work / "private.json", self.work / "must-not-exist.json"
        m.evidence.write_private(secret, b'{"value":"PRIVATE_SENTINEL"}')
        with self.assertRaises(m.GateError) as caught:
            m.retain(secret, rejected, ("PRIVATE_SENTINEL",))
        self.assertEqual(caught.exception.code, "unsafe_capture")
        self.assertFalse(rejected.exists())
        with self.assertRaises(m.GateError):
            m.retain(source, rejected, (), maximum=4)
        self.assertFalse(rejected.exists())

    def test_marker_wait_uses_public_wait_retains_timeout_and_never_signals_a_claimed_pid(self):
        marker = self.work / "ready.json"

        class Child:
            returncode = None

            def __init__(self, publish=False):
                self.publish = publish
                self.waits = []

            @property
            def pid(self):
                raise AssertionError("Marker bytes cannot select a process owner")

            def wait(self, *, timeout):
                self.waits.append(timeout)
                if self.publish:
                    m.evidence.write_private(marker, b'{"pid":999999999,"status":"ready"}')
                raise m.ProcessTimeout("still owned")

        children = m.Children(self.work, 20, 30)
        child = Child(publish=True)
        children.children.append(child)
        with (
            patch.object(m.time, "monotonic", side_effect=[10, 10.001]),
            patch.object(m.os, "kill", side_effect=AssertionError("signal forbidden")),
            patch.object(m.os, "killpg", side_effect=AssertionError("group signal forbidden")),
        ):
            self.assertEqual(
                children.wait_json(child, marker, timeout=0.02),
                {"pid": 999999999, "status": "ready"},
            )
        self.assertEqual(len(child.waits), 1)
        self.assertLessEqual(child.waits[0], 0.02)
        missing = self.work / "absent.json"
        held = Child()
        children.children.append(held)
        with (
            patch.object(m.time, "monotonic", side_effect=[10, 10.001, 10.03]),
            self.assertRaises(m.ProcessTimeout),
        ):
            children.wait_json(held, missing, timeout=0.02)
        self.assertEqual(len(held.waits), 1)
        self.assertIsNone(held.returncode)
        self.assertEqual(children.children, [child, held])

    def test_cleanup_children_keep_immutable_final_reject_duplicate_stage_and_account_once(self):
        now = time.monotonic()
        final = now + 180
        children = m.Children(self.work, now + 160, final)
        children.deadline = final
        child = SimpleNamespace(output_directory=self.work / "cleanup")
        with patch.object(m, "GroupedOwnedProcess", return_value=child) as constructor:
            self.assertIs(
                children.start("cleanup", ["/usr/bin/false"], {"PATH": "/usr/bin"}, cwd=self.work),
                child,
            )
            self.assertEqual(constructor.call_args.kwargs["final_deadline"], final)
            self.assertEqual(constructor.call_args.kwargs["max_output_bytes"], 65536)
            with self.assertRaises(m.GateError) as caught:
                children.start("cleanup", ["/usr/bin/false"], {}, cwd=self.work)
            self.assertEqual(caught.exception.code, "child_budget")
            constructor.assert_called_once()
        self.assertEqual((children.count, children.children), (1, [child]))
        with patch.object(m.core.CaptureBudget, "read", return_value=(b"out", b"err")):
            self.assertEqual(children.account(child), (b"out", b"err"))
            self.assertEqual(children.account(child), (b"out", b"err"))
        self.assertEqual(children.captured, 6)


if __name__ == "__main__":
    unittest.main()
