"""Offline boundary tests for the installed starter host, not product qualification."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import importlib.util
import io
import json
import os
import tarfile
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "p2_standalone_under_test", ROOT / "local-setup/scripts/p2_standalone_check.py"
)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class StandaloneBoundaryTests(unittest.TestCase):
    def test_plan_is_pure_and_separates_twenty_from_six(self):
        for p1 in (False, True):
            output = io.StringIO()
            with (
                patch.object(m, "Children", side_effect=AssertionError("no spawn")),
                patch.object(m, "target_path", side_effect=AssertionError("no file")),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(m.main(["--plan", *(["--p1-contract"] if p1 else [])]), 0)
            value = json.loads(output.getvalue())
            self.assertFalse(value["measurement_started"])
            self.assertEqual(len(value["cases"]), 6 if p1 else 20)
            self.assertEqual(len(value["cases"]), len(set(value["cases"])))
            self.assertEqual(value["bounds"]["maximum_children"], 32)

    def test_default_report_is_fresh_uuid_under_the_same_safe_target_boundary(self):
        requested = []

        def target(root, path):
            requested.append(path)
            raise m.GateError("unsafe_path")

        output = io.StringIO()
        with (
            patch.object(m, "target_path", side_effect=target),
            patch.object(m, "run", side_effect=AssertionError("no driver")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(m.main([]), 1)
        self.assertEqual(requested[0].parts[:3], (".local", "validation", "p2-standalone"))
        self.assertEqual(len(requested[0].stem), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in requested[0].stem))
        self.assertEqual(json.loads(output.getvalue())["code"], "unsafe_path")

    def test_actual_source_census_resolves_all_transitive_host_inputs(self):
        value = m.source_snapshot(ROOT)
        self.assertIn("local-setup/stack.py", value)
        self.assertIn("local-setup/scripts/p3_document_evidence.py", value)
        self.assertIn("projects/channel-continuity/tests/fixtures/starter-p1-consumer.ts", value)
        for module in (
            "result-receiver",
            "result-receiver-access",
            "result-receiver-codec",
            "result-receiver-types",
        ):
            self.assertIn(f"projects/channel-continuity/src/{module}.ts", value)
        self.assertEqual(len(value), 81)
        self.assertTrue(all(len(sha) == 64 for sha in value.values()))

    def test_inherited_pg_target_selectors_rejected_before_driver_or_target_creation(self):
        for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"):
            output = io.StringIO()
            with (
                patch.dict(os.environ, {key: "PRIVATE_SENTINEL"}),
                patch.object(m, "run", side_effect=AssertionError("driver must not run")),
                patch.object(m, "target_path", side_effect=AssertionError("no target")),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(
                    m.main(["--report", ".local/validation/p2-standalone/test.json"]), 1
                )
            value = json.loads(output.getvalue())
            self.assertEqual(value["code"], "invalid_environment")
            self.assertNotIn("PRIVATE_SENTINEL", output.getvalue())

    def test_private_build_configs_resolve_only_the_declared_pinned_node_types(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory).resolve()
            configs = m.build_configurations(ROOT, work)
            project = ROOT / "projects/channel-continuity"
            for path, base, target in zip(
                configs,
                ("tsconfig.json", "tsconfig.examples.json", "tsconfig.starter.json"),
                (project / "dist", project / "dist/examples", project / "dist/examples"),
                strict=True,
            ):
                value = m.decode(m.bounded_read(path))
                self.assertEqual(set(value), {"extends", "compilerOptions"})
                self.assertEqual(value["extends"], str(project / base))
                self.assertEqual(
                    set(value["compilerOptions"]), {"outDir", "tsBuildInfoFile", "typeRoots"}
                )
                self.assertEqual(value["compilerOptions"]["outDir"], str(target))
                self.assertEqual(
                    value["compilerOptions"]["typeRoots"], [str(project / "node_modules/@types")]
                )
                self.assertEqual(Path(value["compilerOptions"]["tsBuildInfoFile"]).parent, work)
                self.assertTrue((project / "node_modules/@types/node/package.json").is_file())

    def test_compile_inputs_retained_before_any_spawn_or_fallible_compiler(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory).resolve() / "work"
            artifacts = Path(directory).resolve() / "artifacts"
            work.mkdir(mode=0o700)
            artifacts.mkdir(mode=0o700)
            observed = []

            def start(*args, **kwargs):
                observed.append(
                    m.decode(
                        m.bounded_read(artifacts / "compiler-configurations.json", 16384), 16384
                    )
                )
                raise m.GateError("child_budget")

            with self.assertRaises(m.GateError):
                m.prepare_installed(ROOT, work, artifacts, SimpleNamespace(start=start))
            self.assertEqual(len(observed), 1)
            self.assertEqual(
                set(observed[0]),
                {"build-production.json", "build-examples.json", "build-starter.json"},
            )
            for value in observed[0].values():
                self.assertEqual(
                    set(value["compilerOptions"]), {"outDir", "tsBuildInfoFile", "typeRoots"}
                )

    def test_exact_package_manager_and_install_inputs_retained_before_install_spawn(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory).resolve() / "work"
            artifacts = Path(directory).resolve() / "artifacts"
            work.mkdir(mode=0o700)
            artifacts.mkdir(mode=0o700)

            class FakeChildren:
                def start(self, name, argv, environment, *, cwd):
                    if name == "install":
                        package = m.decode(m.bounded_read(artifacts / "consumer-package.json"))
                        expected = json.loads((ROOT / "package.json").read_bytes())[
                            "packageManager"
                        ]
                        self_test.assertEqual(package["packageManager"], expected)
                        self_test.assertEqual(
                            m.bounded_read(artifacts / "consumer-package.json"),
                            m.bounded_read(cwd / "package.json"),
                        )
                        self_test.assertEqual(
                            m.bounded_read(artifacts / "consumer-tsconfig.json"),
                            m.bounded_read(cwd / "tsconfig.json"),
                        )
                        raise m.GateError("child_budget")
                    return SimpleNamespace(name=name)

                def finish(self, child):
                    if child.name == "pack":
                        (work / "archives/synthetic.tgz").write_bytes(b"synthetic")

            self_test = self
            with (
                patch.object(
                    m, "expected_public_payloads", return_value={"README.md": b"synthetic"}
                ),
                patch.object(m, "validate_archive", return_value={"archive_sha256": "a" * 64}),
                self.assertRaises(m.GateError) as caught,
            ):
                m.prepare_installed(ROOT, work, artifacts, FakeChildren())
            self.assertEqual(caught.exception.code, "child_budget")
            self.assertTrue((artifacts / "consumer-package.json").is_file())

    def test_argument_error_never_echoes_private_input(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(m.main(["--SECRET_SENTINEL"]), 1)
        self.assertNotIn("SENTINEL", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["code"], "invalid_arguments")

    def test_json_rejects_duplicate_nested_nonfinite_primitive_invalid_utf8(self):
        for raw in (
            b'{"x":1,"x":2}',
            b'{"x":{"a":0,"a":1}}',
            b'{"x":NaN}',
            b'{"x":Infinity}',
            b"[]",
            b"1",
            b"null",
            b'"s"',
            b"\xff",
            b'{"x":"\\ud800"}',
        ):
            with self.subTest(raw=raw), self.assertRaises(m.GateError):
                m.decode(raw)
        self.assertEqual(m.decode('{"x":"é"}'.encode()), {"x": "é"})

    def test_json_bound_and_type_exactness(self):
        with self.assertRaises(m.GateError):
            m.decode(b'{"x":1}', 6)
        self.assertFalse(m.exact({"x": True}, {"x": 1}))
        self.assertFalse(m.exact([1], [1.0]))
        self.assertFalse(m.natural(True, 100))
        self.assertFalse(m.uuid4_string("00000000-0000-0000-0000-000000000000"))
        with self.assertRaises(m.GateError):
            m.json_bytes({"x": float("nan")})

    def test_environment_roles_have_no_ambient_authority(self):
        required = frozenset({"P2_STARTER_DIRECTORY", "P2_STARTER_RUNTIME_CREDENTIALS"})
        env = {
            "P2_STARTER_DIRECTORY": "/private/tmp/synthetic",
            "P2_STARTER_RUNTIME_CREDENTIALS": "/private/tmp/synthetic/runtime.json",
        }
        m.validate_environment(env, required=required)
        for key in (
            "OPENAI_API_KEY",
            "HTTPS_PROXY",
            "NODE_OPTIONS",
            "PYTHONPATH",
            "PGHOSTADDR",
            "P2_STARTER_OWNER_CREDENTIALS",
        ):
            with self.subTest(key=key), self.assertRaises(m.GateError):
                m.validate_environment({**env, key: "private-sentinel"}, required=required)
        for wrong in ({}, {**env, "PATH": ""}, {**env, "PATH": True}):
            with self.assertRaises(m.GateError):
                m.validate_environment(wrong, required=required)

    def test_private_empty_file_roundtrip_and_exclusive_write(self):
        with tempfile.TemporaryDirectory() as d:
            parent = Path(d).resolve()
            path = parent / "empty.bin"
            m.write_private(path, b"")
            self.assertEqual(m.bounded_read(path, allow_empty=True), b"")
            with self.assertRaises(m.GateError):
                m.bounded_read(path)
            with self.assertRaises(m.GateError):
                m.write_private(path, b"replacement")
            self.assertEqual(path.read_bytes(), b"")

    def test_private_reader_rejects_links_modes_and_size(self):
        with tempfile.TemporaryDirectory() as d:
            parent = Path(d).resolve()
            path = parent / "proof.json"
            m.write_private(path, b"{}")
            linked = parent / "linked"
            linked.symlink_to(path)
            with self.assertRaises(m.GateError):
                m.bounded_read(linked)
            linked.unlink()
            os.link(path, linked)
            with self.assertRaises(m.GateError):
                m.bounded_read(path)
            linked.unlink()
            path.chmod(0o644)
            with self.assertRaises(m.GateError):
                m.bounded_read(path)
            path.chmod(0o600)
            with self.assertRaises(m.GateError):
                m.bounded_read(path, 1)

    def test_linked_parent_and_foreign_uid_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            parent = Path(d).resolve()
            real = parent / "real"
            real.mkdir(mode=0o700)
            link = parent / "link"
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaises(m.GateError):
                m.private_directory(link)
            with (
                patch.object(m.os, "getuid", return_value=os.getuid() + 1),
                self.assertRaises(m.GateError),
            ):
                m.private_directory(real)

    def test_target_allows_owned_755_shared_ancestors_but_not_777(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            (root / ".local").mkdir(mode=0o755)
            target = m.target_path(root, Path(".local/validation/p2-standalone/a.json"))
            self.assertEqual(target.parent.name, "p2-standalone")
            (root / ".local").chmod(0o777)
            with self.assertRaises(m.GateError):
                m.target_path(root, Path(".local/validation/p2-standalone/b.json"))

    def test_target_rejects_writable_repository_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            root.chmod(0o777)
            with self.assertRaises(m.GateError):
                m.target_path(root, Path(".local/validation/p2-standalone/a.json"))
            root.chmod(0o700)

    def test_trusted_role_catalog_cannot_escape_command_capture_root(self):
        with tempfile.TemporaryDirectory() as d:
            for roles in (
                frozenset({"../escape"}),
                frozenset({"/absolute"}),
                frozenset(),
                frozenset({"safe\n"}),
            ):
                with self.assertRaises(m.GateError):
                    m.Children(
                        Path(d).resolve(), time.monotonic() + 1, time.monotonic() + 2, roles=roles
                    )

    def test_target_rejects_wrong_lane_traversal_reuse_and_artifact_collision(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            for wrong in (
                Path("/absolute.json"),
                Path(".local/validation/p2-standalone/../a.json"),
                Path(".local/validation/p2-starter-p1/a.json"),
                Path("a.json"),
            ):
                with self.assertRaises(m.GateError):
                    m.target_path(root, wrong)
            path = m.target_path(root, Path(".local/validation/p2-standalone/a.json"))
            path.with_name("a-artifacts").mkdir(mode=0o700)
            with self.assertRaises(m.GateError):
                m.target_path(root, Path(".local/validation/p2-standalone/a.json"))

    def test_exact_physical_inventory_includes_nested_summaries_and_empty_captures(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            nested = root / "package"
            nested.mkdir(mode=0o700)
            m.write_private(nested / "summary.json", b"{}")
            m.write_private(nested / "retained-index.json", b"{}")
            m.write_private(root / "empty.bin", b"")
            inventory = m.retained_inventory(root)
            self.assertEqual(
                set(inventory["files"]),
                {"package/summary.json", "package/retained-index.json", "empty.bin"},
            )
            raw = m.json_bytes(inventory)
            m.write_private(root / "retained-index.json", raw)
            m.validate_retained_index(root, raw)
            m.write_private(root / "extra.json", b"{}")
            with self.assertRaises(m.GateError):
                m.validate_retained_index(root, raw)

    def test_manifest_cannot_exclude_special_nodes_or_claim_boolean_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            m.write_private(root / "proof.json", b"{}")
            value = m.retained_inventory(root)
            value["files"]["proof.json"]["bytes"] = True
            with self.assertRaises(m.GateError):
                m.validate_retained_index(root, m.json_bytes(value))
            (root / "linked").symlink_to(root / "proof.json")
            with self.assertRaises(m.GateError):
                m.retained_inventory(root)

    def test_secret_sentinel_cannot_enter_retained_evidence(self):
        secret = b"SYNTHETIC_PRIVATE_SENTINEL_41"
        m.scan_secrets(b"safe", (secret,))
        with self.assertRaises(m.GateError):
            m.scan_secrets(b"prefix:" + secret, (secret,))
        with self.assertRaises(m.GateError):
            m.scan_secrets(b"safe", (b"tiny",))

    def test_child_registered_before_wait_failure_and_all_close_attempted(self):
        with tempfile.TemporaryDirectory() as d:
            owner = m.Children(
                Path(d).resolve(),
                time.monotonic() + 10,
                time.monotonic() + 20,
                roles=frozenset({"first", "second"}),
            )
            closed = []
            first = SimpleNamespace(
                returncode=None,
                cleanup_failed=False,
                group_settled=False,
                close=lambda: closed.append("first"),
            )
            second = SimpleNamespace(
                returncode=0,
                cleanup_failed=False,
                group_settled=True,
                close=lambda: closed.append("second"),
            )
            with patch.object(m, "GroupedOwnedProcess", return_value=first):
                self.assertIs(owner.start("first", ["/trusted/node"], {}, cwd=Path(d)), first)
            self.assertEqual(owner.children, [first])
            owner.children.append(second)
            with self.assertRaises(m.GateError):
                owner.close()
            self.assertEqual(closed, ["second", "first"])
            self.assertFalse(owner.all_settled())

    def test_capture_reservation_happens_before_spawn(self):
        with tempfile.TemporaryDirectory() as d:
            owner = m.Children(
                Path(d).resolve(),
                time.monotonic() + 10,
                time.monotonic() + 20,
                roles=frozenset({"first"}),
            )
            owner.captured = m.MAX_CAPTURE_BYTES - 2 * m.MAX_STREAM_BYTES + 1
            with (
                patch.object(m, "GroupedOwnedProcess", side_effect=AssertionError("no spawn")),
                self.assertRaises(m.GateError),
            ):
                owner.start("first", ["/trusted/node"], {}, cwd=Path(d))
            self.assertEqual(owner.count, 0)


class StarterWireBoundaryTests(unittest.TestCase):
    def ready(self):
        return {
            "schemaVersion": 1,
            "owner": "11111111222243338444555555555555",
            "pid": 123,
            "kind": "gateway",
            "profileId": "11111111-2222-4333-8444-555555555555",
            "host": "127.0.0.1",
            "port": 15555,
        }

    def test_ready_binds_actual_child_profile_owner_and_loopback(self):
        value = self.ready()
        self.assertEqual(
            m.validate_ready(
                m.json_bytes(value), owner=value["owner"], process_id=123, kind="gateway"
            ),
            value,
        )
        for key, wrong in (
            ("schemaVersion", True),
            ("owner", "b" * 32),
            ("pid", 124),
            ("pid", True),
            ("profileId", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            ("host", "localhost"),
            ("port", 0),
            ("port", True),
            ("kind", "external"),
        ):
            with self.subTest(key=key, wrong=wrong), self.assertRaises(m.GateError):
                m.validate_ready(
                    m.json_bytes({**value, key: wrong}),
                    owner=value["owner"],
                    process_id=123,
                    kind="gateway",
                )

    def test_ready_rejects_unknown_or_primitive_payload_without_exposing_keys(self):
        value = self.ready()
        with self.assertRaises(m.GateError):
            m.validate_ready(
                m.json_bytes({**value, "token": "SENTINEL"}),
                owner=value["owner"],
                process_id=123,
                kind="gateway",
            )
        for raw in (b"[]", b"true", b'{"pid":1,"pid":2}'):
            with self.assertRaises(m.GateError):
                m.validate_ready(raw, owner=value["owner"], process_id=123, kind="gateway")

    def test_each_actor_requires_exact_true_settled_terminal(self):
        for mode in m.ACTOR_MODES:
            value = {"schemaVersion": 1, "status": "passed", "mode": mode, "cleanupComplete": True}
            self.assertEqual(m.validate_actor_stage(m.json_bytes(value), mode), value)
            for key, wrong in (
                ("schemaVersion", True),
                ("cleanupComplete", 1),
                ("cleanupComplete", False),
                ("mode", "unknown"),
                ("status", "prepared"),
            ):
                with self.subTest(mode=mode, key=key), self.assertRaises(m.GateError):
                    m.validate_actor_stage(m.json_bytes({**value, key: wrong}), mode)

    def test_actor_stage_has_no_private_extra_or_unexpected_selector(self):
        value = {"schemaVersion": 1, "status": "passed", "mode": "setup", "cleanupComplete": True}
        for mode in ({}, None, True, "setup\n"):
            with self.assertRaises(m.GateError):
                m.validate_actor_stage(m.json_bytes(value), mode)
        with self.assertRaises(m.GateError):
            m.validate_actor_stage(m.json_bytes({**value, "body": "SENTINEL"}), "setup")

    def failure(self):
        return {
            "schemaVersion": 1,
            "status": "failed",
            "mode": "setup",
            "stage": "startup",
            "errorType": "StarterError",
            "code": "Unavailable",
            "cleanupComplete": False,
        }

    def test_finite_failure_preserves_incomplete_truth_without_messages(self):
        value = self.failure()
        self.assertEqual(m.validate_actor_failure(m.json_bytes(value), "setup"), value)
        value["code"] = None
        self.assertEqual(m.validate_actor_failure(m.json_bytes(value), "setup")["code"], None)

    def test_p1_diagnostic_stages_are_finite_and_rejected_for_every_other_mode(self):
        stages = {
            "zero-read",
            "zero-release",
            "known-revise",
            "known-response",
            "unknown-entry",
            "unknown-outcome",
            "unknown-readback",
            "stale-reject",
        }
        self.assertEqual(m.P1_CONTRACT_STAGES, stages)
        for stage in stages:
            value = {**self.failure(), "mode": "p1-contract", "stage": stage}
            self.assertEqual(m.validate_actor_failure(m.json_bytes(value), "p1-contract"), value)
            for mode in m.ACTOR_MODES - {"p1-contract"}:
                with self.subTest(stage=stage, mode=mode), self.assertRaises(m.GateError):
                    m.validate_actor_failure(m.json_bytes({**value, "mode": mode}), mode)
        with self.assertRaises(m.GateError):
            m.validate_actor_failure(
                m.json_bytes({**value, "stage": "unknown-private-stage"}), "p1-contract"
            )

    def test_failure_unknown_body_code_bool_and_unhashable_values_reject(self):
        for key, wrong in (
            ("schemaVersion", True),
            ("stage", "private_stack"),
            ("stage", {}),
            ("errorType", []),
            ("code", "SENTINEL"),
            ("code", {}),
            ("cleanupComplete", 0),
            ("mode", "gateway-a"),
        ):
            value = {**self.failure(), key: wrong}
            with self.subTest(key=key), self.assertRaises(m.GateError):
                m.validate_actor_failure(m.json_bytes(value), "setup")
        value = copy.deepcopy(self.failure())
        value["message"] = "private-error"
        with self.assertRaises(m.GateError):
            m.validate_actor_failure(m.json_bytes(value), "setup")


class ArchiveBoundaryTests(unittest.TestCase):
    def archive(self, members):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            for name, body, kind in members:
                item = tarfile.TarInfo(name)
                if kind == "symlink":
                    item.type, item.linkname = tarfile.SYMTYPE, "/foreign/source"
                elif kind == "hardlink":
                    item.type, item.linkname = tarfile.LNKTYPE, "package/README.md"
                else:
                    item.size = len(body)
                archive.addfile(item, io.BytesIO(body) if item.isfile() else None)
        return output.getvalue()

    def values(self):
        manifest = {
            "name": "synthetic-starter",
            "private": True,
            "bin": {"p2-channel-starter": "dist/starter.js"},
        }
        payloads = {
            "README.md": "Raw README — unchanged\n".encode(),
            "dist/starter.js": b"export const value = 41;\n",
        }
        members = [
            ("package/package.json", m.json_bytes(manifest), "file"),
            *[("package/" + name, body, "file") for name, body in payloads.items()],
        ]
        return manifest, payloads, members

    def test_archive_derives_complete_raw_payload_inventory(self):
        manifest, payloads, members = self.values()
        value = m.validate_archive(self.archive(members), payloads, manifest)
        self.assertEqual(value["payload_count"], 2)
        self.assertEqual(set(value["payloads"]), set(payloads))
        self.assertTrue(value["manifest_semantics_equal"])
        self.assertFalse(value["raw_manifest_equality_claimed"])

    def test_duplicate_and_unknown_members_reject(self):
        manifest, payloads, members = self.values()
        for extra in (members[0], ("package/.env", b"private", "file")):
            with self.assertRaises(m.GateError):
                m.validate_archive(self.archive([*members, extra]), payloads, manifest)

    def test_symlink_hardlink_and_traversal_never_extract(self):
        manifest, payloads, members = self.values()
        for name, kind in (
            ("package/linked", "symlink"),
            ("package/linked", "hardlink"),
            ("package/../escape", "file"),
            ("/package/escape", "file"),
        ):
            with self.assertRaises(m.GateError):
                m.validate_archive(self.archive([*members, (name, b"x", kind)]), payloads, manifest)

    def test_changed_readme_or_runtime_bytes_and_missing_member_reject(self):
        manifest, payloads, members = self.values()
        for altered in (
            members[:-1],
            [*members[:-1], (members[-1][0], b"changed", "file")],
            [members[0], ("package/README.md", b"changed", "file"), members[2]],
        ):
            with self.assertRaises(m.GateError):
                m.validate_archive(self.archive(altered), payloads, manifest)

    def test_manifest_cannot_hide_semantic_or_type_change(self):
        manifest, payloads, members = self.values()
        for altered in ({**manifest, "private": 1}, {**manifest, "unknown": True}):
            with self.assertRaises(m.GateError):
                m.validate_archive(self.archive(members), payloads, altered)

    def test_malformed_or_bomb_sized_archive_rejects(self):
        manifest, payloads, _ = self.values()
        for raw in (b"not gzip", b"x" * (8 * 1024 * 1024 + 1)):
            with self.assertRaises(m.GateError):
                m.validate_archive(raw, payloads, manifest)


class StarterRuntimePermissionProofTests(unittest.TestCase):
    def test_expired_permission_budget_admits_no_connection_or_snapshot(self):
        with (
            patch.object(m, "owner_snapshot", side_effect=AssertionError("no snapshot")),
            self.assertRaises(m.GateError),
        ):
            m.runtime_permission_proof(
                lambda: (_ for _ in ()).throw(AssertionError("no runtime")),
                lambda: (_ for _ in ()).throw(AssertionError("no owner")),
                "a" * 32,
                deadline=time.monotonic() - 1,
            )

    def proof(self):
        return {
            "schemaVersion": 1,
            "owner": "a" * 32,
            "role": "livekit_lab",
            "denied": [{"operation": name, "sqlState": "42501"} for name in m.PERMISSION_DENIALS],
            "counterUpdateAllowed": True,
            "rolledBack": True,
            "beforeDigest": "b" * 64,
            "afterDigest": "b" * 64,
        }

    def test_exact_denials_require_permission_failure_not_only_rollback_equality(self):
        value = self.proof()
        self.assertEqual(m.validate_permission_proof(m.json_bytes(value), "a" * 32), value)
        for wrong in ("23514", "ok", None):
            value = self.proof()
            value["denied"][0]["sqlState"] = wrong
            with self.assertRaises(m.GateError):
                m.validate_permission_proof(m.json_bytes(value), "a" * 32)

    def test_missing_duplicate_or_unrelated_denial_cannot_fill_six_controls(self):
        for altered in (self.proof()["denied"][:-1], [self.proof()["denied"][0]] * 6):
            value = self.proof()
            value["denied"] = altered
            with self.assertRaises(m.GateError):
                m.validate_permission_proof(m.json_bytes(value), "a" * 32)

    def test_boolean_counter_flags_and_changed_owner_digest_fail(self):
        for key, wrong in (
            ("schemaVersion", True),
            ("owner", "c" * 32),
            ("counterUpdateAllowed", 1),
            ("rolledBack", False),
            ("role", "continuity_migrator"),
            ("afterDigest", "c" * 64),
        ):
            value = {**self.proof(), key: wrong}
            with self.subTest(key=key), self.assertRaises(m.GateError):
                m.validate_permission_proof(m.json_bytes(value), "a" * 32)


class StarterSnapshotRetentionTests(unittest.TestCase):
    # Synthetic frame input only. Empty rows here do not claim a valid installed
    # authority; the eventual business/SQL join requires populated metadata.
    owner = "a" * 32

    def snapshots(self):
        value = {
            name: {table: [] for table in tables}
            for name, tables in m.schema_tables(self.owner).items()
        }
        value["p2_inbox_" + self.owner]["schema_metadata"] = [
            {"catalog_snapshot": {"columns": ["id", "digest"]}, "version": 7}
        ]
        return {phase: copy.deepcopy(value) for phase in m.SNAPSHOT_PHASES}

    def test_all_ten_complete_35_table_snapshots_and_catalog_rows_survive_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            snapshots = self.snapshots()
            manifest = m.write_snapshots(root, snapshots, self.owner)
            raw = m.bounded_read(root / "starter-sql-snapshots.json")
            checked, restored = m.read_snapshots(root, raw, self.owner)
            self.assertEqual(checked, manifest)
            self.assertEqual(restored, snapshots)
            self.assertEqual(len(list(root.iterdir())), 11)
            for entry in manifest["snapshots"].values():
                self.assertEqual(sum(len(tables) for tables in entry["tableCounts"].values()), 35)
                self.assertEqual(entry["type"], "postgres_owner_snapshot")
            self.assertIn(b"catalog_snapshot", m.bounded_read(root / "starter-sql-setup.json"))

    def test_missing_extra_or_foreign_table_is_never_silently_pruned(self):
        for change in ("missing", "extra", "foreign"):
            snapshots = self.snapshots()
            tables = snapshots["setup"]["p2_inbox_" + self.owner]
            if change == "missing":
                tables.pop("inbox")
            elif change == "extra":
                tables["hidden_table"] = []
            else:
                snapshots["setup"]["p2_inbox_" + "b" * 32] = snapshots["setup"].pop(
                    "p2_inbox_" + self.owner
                )
            with tempfile.TemporaryDirectory() as d:
                root = Path(d).resolve()
                with self.assertRaises(m.GateError):
                    m.write_snapshots(root, snapshots, self.owner)
                self.assertEqual(list(root.iterdir()), [])

    def test_65th_row_fails_before_any_phase_is_written(self):
        snapshots = self.snapshots()
        snapshots["after-restore"]["p2_demo_" + self.owner]["ordinary_sms_attempts"] = [
            {"id": i} for i in range(65)
        ]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            with self.assertRaises(m.GateError):
                m.write_snapshots(root, snapshots, self.owner)
            self.assertEqual(list(root.iterdir()), [])

    def test_per_phase_byte_overflow_fails_before_any_write(self):
        snapshots = self.snapshots()
        snapshots["after-restore"]["p2_inbox_" + self.owner]["inbox"] = [
            {"body": "x" * m.MAX_PROOF_BYTES}
        ]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            with self.assertRaises(m.GateError):
                m.write_snapshots(root, snapshots, self.owner)
            self.assertEqual(list(root.iterdir()), [])

    def test_payload_tamper_and_manifest_type_or_path_change_reject(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            manifest = m.write_snapshots(root, self.snapshots(), self.owner)
            raw = m.json_bytes(manifest)
            for key, wrong in (
                ("bytes", True),
                ("path", "../foreign.json"),
                ("sha256", "b" * 64),
                ("type", "untrusted"),
            ):
                altered = copy.deepcopy(manifest)
                altered["snapshots"]["setup"][key] = wrong
                with self.assertRaises(m.GateError):
                    m.read_snapshots(root, m.json_bytes(altered), self.owner)
            target = root / manifest["snapshots"]["setup"]["path"]
            target.write_bytes(m.bounded_read(target).replace(b'"version":7', b'"version":6'))
            with self.assertRaises(m.GateError):
                m.read_snapshots(root, raw, self.owner)

    def test_snapshot_counts_do_not_accept_boolean_lengths_or_primitive_rows(self):
        snapshots = self.snapshots()
        for wrong in ([True], {}, None):
            value = copy.deepcopy(snapshots["setup"])
            value["p2_inbox_" + self.owner]["inbox"] = wrong
            with self.assertRaises(m.GateError):
                m.snapshot_counts(value, self.owner)

    def test_aggregate_evidence_bound_applies_before_output(self):
        snapshots = self.snapshots()
        for value in snapshots.values():
            value["p2_inbox_" + self.owner]["inbox"] = [{"body": "x" * 5000}]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            with patch.object(m, "MAX_EVIDENCE_BYTES", 20000), self.assertRaises(m.GateError):
                m.write_snapshots(root, snapshots, self.owner)
            self.assertEqual(list(root.iterdir()), [])


class StarterLifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_caller_retains_actual_thread_until_release(self):
        entered, release = threading.Event(), threading.Event()
        actual = m.ActualCalls()

        def held():
            entered.set()
            release.wait(2)
            return "settled"

        caller = asyncio.create_task(actual.call(held))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            caller.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await caller
            self.assertEqual(len(actual.tasks), 1)
            self.assertFalse(await actual.close(time.monotonic() + 0.01))
        finally:
            release.set()
            self.assertTrue(await actual.close(time.monotonic() + 1))
        self.assertEqual(len(actual.tasks), 0)

    async def test_unsettled_child_withholds_dependent_schema_cleanup(self):
        dropped = []
        children = SimpleNamespace(close=lambda: None, all_settled=lambda: False)
        self.assertFalse(
            await m.cleanup_dependencies(
                children, m.ActualCalls(), time.monotonic() + 1, lambda: dropped.append("drop")
            )
        )
        self.assertEqual(dropped, [])

    async def test_unsettled_actual_call_withholds_schema_and_retry_makes_progress(self):
        release, entered = threading.Event(), threading.Event()
        actual = m.ActualCalls()
        children = SimpleNamespace(close=lambda: None, all_settled=lambda: True)
        dropped = []

        def held():
            entered.set()
            release.wait(2)

        caller = asyncio.create_task(actual.call(held))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            self.assertFalse(
                await m.cleanup_dependencies(
                    children, actual, time.monotonic() + 0.01, lambda: dropped.append("drop")
                )
            )
            self.assertEqual(dropped, [])
        finally:
            release.set()
            await caller
        # Retry reobserves the retained owner; it must still be permitted to run
        # the dependent cleanup once the actual work has settled.
        self.assertTrue(
            await m.cleanup_dependencies(
                children, actual, time.monotonic() + 1, lambda: dropped.append("drop")
            )
        )
        self.assertEqual(dropped, ["drop"])


class StarterOwnerProofTests(unittest.TestCase):
    """Synthetic validator inputs derived from the closed ABI; no actual PG claim."""

    owner = "a" * 32

    def corpus(self):
        import hashlib

        uid = lambda n: "00000000-0000-4000-8000-" + format(n, "012x")
        raw = lambda v: json.dumps(v, separators=(",", ":"), ensure_ascii=False)
        sha = lambda v: hashlib.sha256(v.encode()).hexdigest()
        cfg = m.make_configuration(self.owner, 5432)
        binding = cfg["bindings"][0]
        scope = binding["accountScope"]
        provider = binding["providerScope"]
        ids = m.fixed_ids(self.owner)
        sql = {
            schema: {table: [] for table in names}
            for schema, names in m.schema_tables(self.owner).items()
        }
        inbox, case, external = tuple(sql)
        messages = []
        dispatches = []
        receipts = []
        for n, label in enumerate("RTKUV", 1):
            event = {
                "schemaVersion": 1,
                "type": "text.received",
                "eventId": ids["events"][label]["eventId"],
                "messageId": ids["events"][label]["messageId"],
                "accountScope": scope,
                "providerScope": provider,
                "conversationId": binding["conversationId"],
                "caseId": binding["caseId"],
                "senderId": binding["senderId"],
                "body": "equal" if label in "TU" else label,
                "occurredAt": "2030-12-01T10:00:00.000Z",
            }
            receipt = {
                "receiptId": uid(n),
                "eventId": event["eventId"],
                "messageId": event["messageId"],
                "acceptanceSequence": str(n),
                "acceptedAt": "2030-12-01T10:00:00.000Z",
            }
            message = {
                "event": event,
                "receipt": receipt,
                "operationKey": uid(10 + n),
                "processingState": "dispatched",
                "associationVersion": "1",
            }
            submission = {
                "operationKey": message["operationKey"],
                "scope": scope,
                "caseId": binding["caseId"],
                "conversationId": binding["conversationId"],
                "message": {"body": event["body"]},
            }
            wire = raw(submission)
            digest = sha(wire)
            messages.append(message)
            sql[inbox]["inbox"].append(
                {
                    "receipt_id": uid(n),
                    "event_id": event["eventId"],
                    "message_id": event["messageId"],
                    "tenant_id": scope["tenantId"],
                    "account_id": scope["accountId"],
                    "provider": provider["provider"],
                    "provider_account_id": provider["providerAccountId"],
                    "conversation_id": binding["conversationId"],
                    "wire_json": raw(event),
                    "acceptance_sequence": n,
                }
            )
            sql[inbox]["processing_intents"].append(
                {
                    "receipt_id": uid(n),
                    "operation_key": message["operationKey"],
                    "state": "dispatched",
                    "external_receipt_id": uid(20 + n),
                    "possible_external": True,
                    "attempt_count": 1,
                }
            )
            sql[inbox]["dispatch_plans"].append(
                {"receipt_id": uid(n), "payload_json": wire, "payload_digest": digest}
            )
            sql[external]["investigation_receipts"].append(
                {
                    "tenant_id": scope["tenantId"],
                    "account_id": scope["accountId"],
                    "operation_key": message["operationKey"],
                    "canonical_payload": wire,
                    "payload_digest": digest,
                    "receipt_id": uid(20 + n),
                }
            )
            dispatches.append(
                {
                    "state": "dispatched",
                    "operationKey": message["operationKey"],
                    "externalReceiptId": uid(20 + n),
                }
            )
            receipts.append(
                {
                    "status": "accepted",
                    "receipt": {
                        "operationKey": message["operationKey"],
                        "payloadDigest": digest,
                        "receiptId": uid(20 + n),
                        "scope": scope,
                    },
                }
            )
        fillers = []
        for n in range(11):
            content = {
                "scope": scope,
                "caseId": binding["caseId"],
                "conversationId": binding["conversationId"],
                "operationKey": ids["probes"]["investigations"][n],
                "message": {"body": "\x00" * 4096 if n == 0 else "" if n == 1 else "probe"},
            }
            wire = raw(content)
            sql[external]["investigation_receipts"].append(
                {
                    "tenant_id": scope["tenantId"],
                    "account_id": scope["accountId"],
                    "operation_key": content["operationKey"],
                    "canonical_payload": wire,
                    "payload_digest": sha(wire),
                    "receipt_id": uid(100 + n),
                }
            )
            fillers.append(
                {
                    "prepared": {
                        "submission": content,
                        "canonicalPayload": wire,
                        "payloadDigest": sha(wire),
                    },
                    "receipt": {"receiptId": uid(100 + n)},
                }
            )
        case_value = {
            "revision": "1",
            "request": {**binding["initialCase"]["request"], "newCheckIn": "2030-12-04"},
            "cancelled": False,
            "committed": False,
        }
        sql[case]["cases"] = [
            {
                "tenant_id": scope["tenantId"],
                "account_id": scope["accountId"],
                "case_id": binding["caseId"],
                "revision": 1,
                "request_json": raw(case_value["request"]),
                "cancelled": False,
                "committed": False,
            }
        ]
        sql[external]["receipt_metadata"] = [
            {
                "profile_id": cfg["profileId"],
                "version": 1,
                "definition_digest": "8ca1848028e76cf0d3eaab4546315a78449ec5b57c9af23bdfd6e6a18eeb54d1",
                "max_receipts": 16,
                "investigation_count": 16,
                "idempotent_count": 16,
                "ordinary_count": 16,
                "catalog_snapshot": {"owner": "continuity_migrator"},
            }
        ]
        observations = {}
        unknowns = {}
        for n, kind in enumerate(("ordinary", "idempotent")):
            request = {
                "attemptId": uid(200 + n),
                "providerOperationKey": uid(220 + n),
                "outboundId": ids["outbound"][kind],
                "scope": scope,
                "providerScope": provider,
                "caseId": binding["caseId"],
                "conversationId": binding["conversationId"],
            }
            wire = raw(request)
            sql[inbox]["send_attempts"].append(
                {
                    "attempt_id": request["attemptId"],
                    "outbound_id": request["outboundId"],
                    "canonical_request": wire,
                    "request_digest": sha(wire),
                }
            )
            sql[inbox]["reply_intents"].append({"outbound_id": request["outboundId"]})
            observations[kind] = {
                "state": "unknown",
                "receipt": {"outboundId": request["outboundId"]},
                "attempts": [{"request": request, "requestDigest": sha(wire), "result": None}],
            }
            unknowns[kind] = {**observations[kind], "state": "unknown"}
        physical = {
            **observations["ordinary"]["attempts"][0]["request"],
            **ids["probes"]["ordinaryPhysical"],
        }
        physical_results = [{"providerMessageId": uid(500)}, {"providerMessageId": uid(501)}]
        for n in range(16):
            request = (
                physical
                if n < 2
                else observations["ordinary"]["attempts"][0]["request"]
                if n == 2
                else {**physical, "attemptId": uid(510 + n)}
            )
            wire = raw(request)
            sql[external]["ordinary_sms_attempts"].append(
                {
                    "tenant_id": scope["tenantId"],
                    "provider": provider["provider"],
                    "provider_account_id": provider["providerAccountId"],
                    "attempt_id": request["attemptId"],
                    "canonical_request": wire,
                    "request_digest": sha(wire),
                    "provider_message_id": uid(500 + n),
                }
            )
            wire = raw(observations["idempotent"]["attempts"][0]["request"])
            sql[external]["idempotent_sms_receipts"].append(
                {
                    "tenant_id": scope["tenantId"],
                    "provider": provider["provider"],
                    "provider_account_id": provider["providerAccountId"],
                    "canonical_operation": wire,
                    "operation_digest": sha(wire),
                    "provider_operation_key": uid(221) if n == 0 else uid(700 + n),
                    "provider_message_id": uid(600 + n),
                }
            )
        recoveries = []
        for n, command in enumerate(ids["recovery"].values()):
            receipt = {
                "commandId": command,
                "receiptId": uid(300 + n),
                "code": "ordinary_no_resend" if n < 2 else "reconciled",
            }
            wire = raw(receipt)
            command_wire = raw({"commandId": command, "scope": scope})
            recoveries.append({"receipt": receipt, "observation": None})
            sql[inbox]["send_recovery_commands"].append(
                {
                    "command_id": command,
                    "receipt_json": wire,
                    "receipt_digest": sha(wire),
                    "canonical_command": command_wire,
                    "command_digest": sha(command_wire),
                    "tenant_id": scope["tenantId"],
                    "account_id": scope["accountId"],
                }
            )
        wire = raw(observations["idempotent"]["attempts"][0]["request"])
        sql[inbox]["send_operations"] = [
            {
                "provider_operation_key": uid(221),
                "operation_digest": sha(wire),
                "canonical_operation": wire,
            }
        ]
        recoveries[2]["receipt"].update(providerOperationKey=uid(221), operationDigest=sha(wire))
        receipt_wire = raw(recoveries[2]["receipt"])
        sql[inbox]["send_recovery_commands"][2].update(
            receipt_json=receipt_wire, receipt_digest=sha(receipt_wire)
        )
        recovery_observation = {
            "commandId": ids["recovery"]["idempotent"],
            "source": "lookup",
            "state": "accepted_by_provider",
            "providerMessageId": uid(600),
            "providerOperationKey": uid(221),
            "operationDigest": sha(wire),
        }
        recoveries[2]["observation"] = recovery_observation
        observation_wire = raw(recovery_observation)
        sql[inbox]["send_recovery_observations"] = [
            {
                "command_id": ids["recovery"]["idempotent"],
                "canonical_observation": observation_wire,
                "observation_digest": sha(observation_wire),
            }
        ]
        retained = []
        callbacks = []
        for n, label in enumerate(("delivered", "sent")):
            observation = {
                "eventId": ids["callbacks"][label],
                "attemptId": uid(200),
                "providerMessageId": uid(502),
                "providerOperationKey": uid(220),
                "requestDigest": sha(raw(observations["ordinary"]["attempts"][0]["request"])),
                "state": "delivered" if n == 0 else "accepted_by_provider",
            }
            wire = raw(observation)
            receipt = {"receiptId": uid(400 + n), "payloadDigest": sha(wire)}
            retained.append({"observation": observation, "receipt": receipt})
            callbacks.append(receipt)
            sql[inbox]["callback_observations"].append(
                {
                    "event_id": observation["eventId"],
                    "receipt_id": receipt["receiptId"],
                    "payload_digest": sha(wire),
                    "attempt_id": uid(200),
                    "canonical_payload": wire,
                    "tenant_id": provider["tenantId"],
                    "provider_account_id": provider["providerAccountId"],
                }
            )
        zero = {"before": 0, "after": 0, "requests": []}
        facts = {
            "messages": messages,
            "dispatches": dispatches,
            "externalReceipts": receipts,
            "cases": [case_value],
            "replies": [observations["ordinary"], observations["idempotent"]],
            "callbacks": [{"observations": retained}],
            "recoveries": recoveries,
            "historyPages": [
                {"messages": messages[:2]},
                {"messages": messages[2:4]},
                {"messages": messages[4:]},
            ],
            "recoveryReplay": zero,
        }
        proofs = {
            name: {"schemaVersion": 1, "owner": self.owner, **{key: None for key in keys.split()}}
            for name, keys in m.PROOF_KEYS.items()
        }
        proofs["starter-original.json"].update(facts)
        for name in ("starter-fresh.json", "starter-restored.json"):
            proofs[name].update(facts=copy.deepcopy(facts), metrics={})
        proofs["starter-baseline.json"].update(
            messages=messages[:2],
            dispatches=dispatches[:2],
            externalReceipts=receipts[:2],
            historyPages=[{"messages": messages[:2]}],
            replay={"replayed": True, "receipt": messages[1]["receipt"]},
            conflictStatus=409,
            foreignStatus=401,
        )
        proofs["starter-restored.json"]["metrics"] = {
            "application": {
                "commandsActive": 0,
                "retainedGraphs": 0,
                "gatewayActive": False,
                "closing": True,
            },
            "external": {
                "started": 5,
                "known": 5,
                "rejected": 0,
                "active": 0,
                "sockets": 0,
                "closing": True,
                "profileReads": 0,
            },
        }
        proofs["starter-setup.json"].update(
            initialCase=binding["initialCase"],
            afterCase=case_value,
            route={"status": "revised"},
            messages=messages[:2],
            association={"associationVersion": "1"},
        )
        ack_message = copy.deepcopy(messages[2])
        ack_message["processingState"] = "pending"
        proofs["starter-ack.json"].update(
            httpStatus=200, receipt=ack_message["receipt"], message=ack_message
        )
        proofs["starter-before-restart.json"].update(
            message=ack_message, dispatch={"state": "pending"}, lookup={"status": "absent"}
        )
        proofs["starter-recovered.json"].update(
            originalMessage={**ack_message, "processingState": "dispatched"},
            replayedReceipt=ack_message["receipt"],
            dispatch={"state": "dispatched"},
            laterDispatch={"state": "dispatched"},
        )

        def relay(path, request, response):
            a = raw(request)
            b = raw(response)
            return {
                "path": path,
                "request": a,
                "requestDigest": sha(a),
                "requestBytes": len(a.encode()),
                "response": b,
                "responseDigest": sha(b),
                "responseBytes": len(b.encode()),
                "httpStatus": 200,
            }

        v = sql[external]["investigation_receipts"][4]
        record = relay(
            "/v1/investigations/accept",
            {"canonicalPayload": v["canonical_payload"], "payloadDigest": v["payload_digest"]},
            {"receipt": {"receiptId": v["receipt_id"]}},
        )
        proofs["starter-external-held.json"].update(message=messages[4], record=record)
        proofs["starter-unknown.json"].update(
            message=messages[4],
            operationOutcome={"ok": False, "code": "DispatchUnavailable"},
            dispatch={"state": "uncertain"},
            ordinary=unknowns["ordinary"],
            idempotent=unknowns["idempotent"],
            relay=[
                record,
                relay(
                    "/v1/sms/send",
                    observations["ordinary"]["attempts"][0]["request"],
                    {
                        "result": {
                            "status": "accepted_by_provider",
                            "providerMessageId": uid(502),
                            "attemptId": uid(200),
                            "requestDigest": observations["ordinary"]["attempts"][0][
                                "requestDigest"
                            ],
                        }
                    },
                ),
                relay(
                    "/v1/idempotent-sms/send",
                    {
                        "operation": observations["idempotent"]["attempts"][0]["request"],
                        "operationDigest": sha(
                            raw(observations["idempotent"]["attempts"][0]["request"])
                        ),
                    },
                    {
                        "result": {
                            "status": "accepted_by_provider",
                            "providerMessageId": uid(600),
                            "attemptId": uid(201),
                            "requestDigest": observations["idempotent"]["attempts"][0][
                                "requestDigest"
                            ],
                        }
                    },
                ),
            ],
            outcomes=[],
        )
        proofs["starter-delivery.json"].update(
            operation={"status": "dispatched"},
            ordinary=observations["ordinary"],
            idempotent=observations["idempotent"],
            callbacks=[*callbacks, callbacks[0]],
            callbackFacts={
                "evidence": {"strongestReported": "delivered"},
                "observations": retained,
            },
            recoveries=recoveries,
            replayedRecoveries=copy.deepcopy(recoveries),
            providerCalls=zero,
        )
        proofs["starter-capacity.json"].update(
            investigation={
                "rows": fillers,
                "replay": {},
                "conflict": {"code": "IdentityConflict"},
                "overloaded": {"code": "Overloaded"},
            },
            idempotent={
                "rows": [{}] * 15,
                "replay": {},
                "conflict": {"code": "IdentityConflict"},
                "overloaded": {"code": "Overloaded"},
            },
            ordinary={"rows": [{}] * 13, "overloaded": {"code": "Overloaded"}},
            ordinaryPhysicalProbe={"request": physical, "results": physical_results},
        )
        snapshots = {phase: copy.deepcopy(sql) for phase in m.SNAPSHOT_PHASES}
        pending = snapshots["ack-before-kill"][inbox]
        snapshots["ack-before-kill"][external]["investigation_receipts"] = [
            r
            for r in snapshots["ack-before-kill"][external]["investigation_receipts"]
            if r["operation_key"] != messages[2]["operationKey"]
        ]
        pending["processing_intents"][2].update(
            state="pending", possible_external=False, attempt_count=0
        )
        pending["dispatch_plans"] = [
            r for r in pending["dispatch_plans"] if r["receipt_id"] != uid(3)
        ]
        snapshots["external-unknown"][inbox]["processing_intents"][4].update(
            state="uncertain", possible_external=True, external_receipt_id=None
        )
        return cfg, proofs, snapshots

    def test_complete_independently_constructed_owner_graph(self):
        cfg, proofs, snapshots = self.corpus()
        result = m.validate_owner_joins(proofs, snapshots, cfg, self.owner)
        self.assertEqual(len(result["originalReceipts"]), 5)
        self.assertEqual(len(result["logicalOperationKeys"]), 5)
        self.assertFalse(result["ordinaryResend"])

    def test_foreign_scope_canonical_tamper_duplicate_callback_restore_and_early_effect_fail(self):
        cfg, proofs, snapshots = self.corpus()
        inbox, _, external = tuple(m.schema_tables(self.owner))
        mutations = [
            lambda p, s: p["starter-fresh.json"]["facts"]["messages"][0]["event"].update(
                body="changed"
            ),
            lambda p, s: s["before-restore"][external]["investigation_receipts"][0].update(
                account_id="foreign"
            ),
            lambda p, s: s["before-restore"][inbox]["dispatch_plans"][0].update(
                payload_digest="0" * 64
            ),
            lambda p, s: p["starter-delivery.json"]["callbacks"][2].update(receiptId="wrong"),
            lambda p, s: s["ack-before-kill"][inbox]["processing_intents"][2].update(
                possible_external=True
            ),
            lambda p, s: s["external-unknown"][inbox]["processing_intents"][4].update(
                external_receipt_id="unexpected"
            ),
            lambda p, s: p["starter-delivery.json"]["providerCalls"].update(after=1),
            lambda p, s: p["starter-unknown.json"]["ordinary"].update(state="accepted_by_provider"),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                a, b = copy.deepcopy(proofs), copy.deepcopy(snapshots)
                mutate(a, b)
                with self.assertRaises(m.GateError):
                    m.validate_owner_joins(a, b, cfg, self.owner)

    def test_relay_unicode_actual_byte_count_and_digest_not_character_count(self):
        _cfg, p, _s = self.corpus()
        record = p["starter-external-held.json"]["record"]
        m.relay_record(record)
        for key, value in [
            ("requestBytes", True),
            ("httpStatus", True),
            ("requestDigest", "f" * 64),
            ("unknown", "value"),
        ]:
            altered = {**record, key: value}
            with self.subTest(key=key), self.assertRaises(m.GateError):
                m.relay_record(altered)

    def test_proof_envelope_closed_keys_owner_and_schema_boolean(self):
        _, proofs, _ = self.corpus()
        name = "starter-ack.json"
        value = proofs[name]
        self.assertEqual(m.validate_proof(json.dumps(value).encode(), name, self.owner), value)
        for changed in (
            {**value, "schemaVersion": True},
            {**value, "owner": "b" * 32},
            {**value, "secret": "disallowed"},
        ):
            with self.assertRaises(m.GateError):
                m.validate_proof(json.dumps(changed).encode(), name, self.owner)


class StarterReportTests(unittest.TestCase):
    def report(self):
        return {
            "schema_version": 1,
            "status": "passed",
            "mode": m.MODE,
            "tests": 20,
            "passed": 20,
            "cases": list(m.CASE_NAMES),
            "child_commands": 26,
            "owned_sigkills": 1,
            "logical_investigations": 5,
            "synthetic_carrier_acceptances": 32,
            "callback_offers": 3,
            "callback_observations": 2,
            "recovery_commands": 3,
            "archive_payloads": 116,
            "cleanup_complete": True,
            "duration_seconds": 100.0,
            "retained_index_sha256": "a" * 64,
            "proofs": {
                name: {"bytes": 100, "sha256": "b" * 64}
                for name in (
                    *m.PROOF_KEYS,
                    "starter-runtime-permissions.json",
                    "starter-sql-snapshots.json",
                    "independent-owner-joins.json",
                    "owned-kill.json",
                )
            },
        }

    def test_report_closed_exact_counts_and_derived_archive_inventory(self):
        value = self.report()
        self.assertEqual(m.validated_report(json.dumps(value).encode()), value)
        for key, changed in (
            ("tests", True),
            ("child_commands", 27),
            ("owned_sigkills", 2),
            ("duration_seconds", 361),
            ("duration_seconds", True),
            ("archive_payloads", True),
            ("mode", []),
            ("cleanup_complete", False),
            ("unknown", 0),
        ):
            with self.subTest(key=key, changed=changed), self.assertRaises(m.GateError):
                m.validated_report(json.dumps({**value, key: changed}).encode())

    def test_missing_extra_or_changed_proof_descriptor_rejected(self):
        for mutate in (
            lambda p: p.pop("owned-kill.json"),
            lambda p: p.update({"foreign.json": {"bytes": 1, "sha256": "b" * 64}}),
            lambda p: p["owned-kill.json"].update(bytes=True),
            lambda p: p["owned-kill.json"].update(sha256="../foreign"),
        ):
            value = self.report()
            mutate(value["proofs"])
            with self.assertRaises(m.GateError):
                m.validated_report(json.dumps(value).encode())


class StarterActualRunCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_run_retains_primary_and_private_work_when_child_owner_is_unknown(self):
        import p3_coordinator_check as core

        cleanup = {"cleanup_complete": False}
        fake_children = []

        class UnknownChildren:
            def __init__(self, directory, deadline, final_deadline, *, roles):
                self.directory = directory
                self.children = []
                self.count = 0
                self.work = directory.parent
                fake_children.append(self)

            def start(self, name, argv, environment, *, cwd):
                child = SimpleNamespace(
                    output_directory=self.directory / name,
                    pid=123,
                    returncode=0,
                    cleanup_failed=False,
                    group_settled=False,
                )
                self.children.append(child)
                self.count += 1
                return child

            def finish(self, child, *, accepted_codes=(0,), secrets=()):
                name = child.output_directory.name
                if name == "plan":
                    import hashlib

                    return m.json_bytes(
                        {
                            "schemaVersion": 1,
                            "command": "plan",
                            "status": "not_started",
                            "groups": list(m.CASE_NAMES),
                            "setupStarted": False,
                            "providersInvoked": False,
                            "manifestSha256": hashlib.sha256(
                                (
                                    ROOT / "projects/channel-continuity/starter/bounded-v1.json"
                                ).read_bytes()
                            ).hexdigest(),
                        }
                    )
                if name == "config-negative":
                    m.write_private(
                        self.work / "stage-config-negative.json",
                        m.json_bytes(
                            {"schemaVersion": 1, "owner": "a" * 32, "mode": "config-negative"}
                        ),
                    )
                    return m.json_bytes(
                        {
                            "schemaVersion": 1,
                            "status": "passed",
                            "mode": name,
                            "cleanupComplete": True,
                        }
                    )
                if name == "bootstrap":
                    m.write_private(
                        self.work / "terminal-bootstrap.json",
                        m.json_bytes({"inboxVersion": 7, "caseVersion": 1, "externalVersion": 1}),
                    )
                    return m.json_bytes(
                        {
                            "schemaVersion": 1,
                            "command": "bootstrap",
                            "requestId": "00000000-0000-4000-8000-000000000001",
                            "status": "known",
                            "code": "ok",
                            "result": {},
                            "cleanupComplete": True,
                        }
                    )
                raise AssertionError("unexpected mock command")

            def close(self):
                raise m.GateError("cleanup_incomplete")

            def all_settled(self):
                return False

            def capture(self, child, *, secrets=()):
                return b"", b""

        def prepare(root, work, artifacts, children):
            consumer = work / "consumer"
            consumer.mkdir(mode=0o700)
            bindir = consumer / "node_modules/.bin"
            bindir.mkdir(parents=True, mode=0o700)
            script = consumer / "bin.js"
            script.write_text("")
            (bindir / "p2-channel-starter").symlink_to(script)
            return {"consumer": consumer, "node": Path("/usr/bin/true")}

        setup = SimpleNamespace(
            load_settings=lambda: {
                "POSTGRES_PORT": "5432",
                "POSTGRES_PASSWORD": "unit-runtime-password",
                "POSTGRES_MIGRATION_PASSWORD": "unit-owner-password",
            }
        )
        primary = AssertionError("primary synthetic proof failure")
        with tempfile.TemporaryDirectory() as directory:
            artifacts = Path(directory).resolve() / "artifacts"
            artifacts.mkdir(mode=0o700)
            try:
                with (
                    patch.object(m, "Children", UnknownChildren),
                    patch.object(m, "source_snapshot", return_value={"synthetic": "0" * 64}),
                    patch.object(core, "load_setup", return_value=setup),
                    patch.object(m, "prepare_installed", side_effect=prepare),
                    patch.object(m, "runtime_permission_proof", side_effect=primary),
                    patch(
                        "psycopg.connect",
                        side_effect=AssertionError("dependent DDL must be withheld"),
                    ),
                    self.assertRaises(AssertionError) as observed,
                ):
                    await m.run(ROOT, artifacts, time.monotonic(), cleanup)
                self.assertIs(observed.exception, primary)
                self.assertFalse(cleanup["cleanup_complete"])
                retained = m.decode(m.bounded_read(artifacts / "owned-work-retained.json"))
                self.assertEqual(retained["path"], str(fake_children[0].work))
                self.assertTrue(fake_children[0].work.is_dir())
            finally:
                # No process or database was created by these test doubles.
                for children in fake_children:
                    import shutil

                    shutil.rmtree(children.work)


class StarterInstalledBinTests(unittest.TestCase):
    def fixture(self, directory, *, symlink=False):
        import re

        consumer = Path(directory).resolve() / "consumer"
        consumer.mkdir(mode=0o700)
        package = consumer / "node_modules/@livekit-ecosystem/channel-continuity"
        target = package / "dist/examples/standalone-channel.js"
        target.parent.mkdir(parents=True)
        body = b"#!/usr/bin/env node\nexport {};\n"
        target.write_bytes(body)
        target.chmod(0o755)
        manifest = {"bin": {"p2-channel-starter": "dist/examples/standalone-channel.js"}}
        (package / "package.json").write_text(json.dumps(manifest))
        binpath = consumer / "node_modules/.bin/p2-channel-starter"
        binpath.parent.mkdir()
        if symlink:
            binpath.symlink_to(target)
        else:
            raw = (ROOT / "projects/channel-continuity/node_modules/.bin/tsc").read_bytes()
            original = re.search(rb"^# cmd-shim-target=(.+)$", raw, re.MULTILINE)[1]
            for item in set(re.findall(rb'"\$basedir_abs"/\x27([^\x27]+)\x27', raw)):
                if item != original:
                    raw = raw.replace(b"/'" + item + b"'", b"/'../.pnpm/node_modules'")
            raw = raw.replace(
                original,
                b"../@livekit-ecosystem/channel-continuity/dist/examples/standalone-channel.js",
            )
            binpath.write_bytes(raw)
            binpath.chmod(0o755)
        return consumer, manifest, {"dist/examples/standalone-channel.js": body}, binpath, target

    def test_actual_pinned_regular_shim_and_contained_symlink_are_accepted(self):
        for symlink in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                consumer, manifest, payloads, path, _target = self.fixture(
                    directory, symlink=symlink
                )
                selected, proof, raw = m.installed_bin(consumer, manifest, payloads)
                self.assertEqual(selected, path)
                self.assertEqual(proof["kind"], "symlink" if symlink else "pnpm_regular_shim")
                self.assertEqual(proof["bytes"], len(raw))
                self.assertEqual(proof["target"], "dist/examples/standalone-channel.js")

    def test_replaced_target_or_escaping_symlink_is_rejected(self):
        for attack in ("changed-payload", "foreign-link"):
            with tempfile.TemporaryDirectory() as directory:
                consumer, manifest, payloads, path, target = self.fixture(
                    directory, symlink=attack == "foreign-link"
                )
                if attack == "changed-payload":
                    target.write_bytes(b"changed")
                else:
                    path.unlink()
                    path.symlink_to(Path(directory) / "foreign.js")
                with self.assertRaises(m.GateError):
                    m.installed_bin(consumer, manifest, payloads)

    def test_regular_shim_unknown_command_path_escape_and_write_permission_fail_closed(self):
        for attack in ("command", "path", "mode"):
            with tempfile.TemporaryDirectory() as directory:
                consumer, manifest, payloads, path, _target = self.fixture(directory)
                raw = path.read_bytes()
                if attack == "command":
                    path.write_bytes(raw.replace(b"#!/bin/sh\n", b"#!/bin/sh\necho unsafe\n", 1))
                elif attack == "path":
                    path.write_bytes(raw.replace(b"../.pnpm/node_modules", b"../../../../outside"))
                else:
                    path.chmod(0o775)
                with self.assertRaises(m.GateError):
                    m.installed_bin(consumer, manifest, payloads)


class StarterTerminalEvidenceTests(unittest.TestCase):
    def terminal(self):
        return {
            "stopped": True,
            "port": 12345,
            "metrics": {
                "application": {
                    "commandsActive": 0,
                    "retainedGraphs": 0,
                    "gatewayActive": False,
                    "closing": True,
                },
                "gateway": {
                    "active": 0,
                    "intakes": 0,
                    "sockets": 0,
                    "handlers": 0,
                    "observerPending": 0,
                    "driver": 0,
                },
            },
        }

    def test_actual_closed_driver_zero_passes_and_retained_loop_one_fails(self):
        value = self.terminal()
        m.validate_closed_metrics(value, "gateway")
        value["metrics"]["gateway"]["driver"] = 1
        with self.assertRaises(m.GateError):
            m.validate_closed_metrics(value, "gateway")

    def test_safe_terminal_bytes_retained_before_decode_or_semantic_rejection(self):
        for raw in (
            b"{malformed",
            m.json_bytes(
                {
                    **self.terminal(),
                    "metrics": {
                        **self.terminal()["metrics"],
                        "gateway": {**self.terminal()["metrics"]["gateway"], "driver": 1},
                    },
                }
            ),
        ):
            with tempfile.TemporaryDirectory() as directory:
                source = Path(directory).resolve() / "source.json"
                destination = Path(directory).resolve() / "terminal.json"
                m.write_private(source, raw)
                with self.assertRaises(m.GateError):
                    m.retain_terminal(source, destination, "gateway", ())
                self.assertEqual(m.bounded_read(destination), raw)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory).resolve() / "source.json"
            destination = Path(directory).resolve() / "terminal.json"
            m.write_private(source, b"PRIVATE_SENTINEL")
            with self.assertRaises(m.GateError):
                m.retain_terminal(source, destination, "gateway", (b"PRIVATE_SENTINEL",))
            self.assertFalse(destination.exists())


class BackupOwnershipTests(unittest.TestCase):
    owner = "2" * 32
    container = "818b698e8126"

    def test_copy_preserves_archive_and_restore_uses_separately_pinned_container_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory).resolve() / "dump.sql"
            raw = b"-- synthetic private backup\n"
            m.write_private(source, raw)
            copy, restore, identity = m.backup_restore_commands(
                "/trusted/docker", self.container, self.owner, source, raw
            )
            info = source.lstat()
            self.assertEqual(copy[:3], ["/trusted/docker", "cp", "--archive"])
            self.assertEqual(copy[3], str(source))
            self.assertEqual(
                restore[:6],
                [
                    "/trusted/docker",
                    "exec",
                    "--user",
                    "999:999",
                    "-e",
                    "PGPASSWORD",
                ],
            )
            self.assertEqual(identity["hostUid"], info.st_uid)
            self.assertEqual(identity["hostGid"], info.st_gid)
            self.assertEqual(identity["containerUid"], 999)
            self.assertEqual(identity["containerGid"], 999)
            self.assertEqual(identity["mode"], "0600")
            self.assertEqual(identity["links"], 1)
            self.assertEqual(identity["bytes"], len(raw))
            self.assertNotIn("chown", restore[-1])
            self.assertNotIn("chmod", restore[-1])
            self.assertIn("--host=127.0.0.1 --username=continuity_migrator", restore[-1])

    def test_backup_host_symlink_hardlink_public_mode_and_changed_bytes_fail(self):
        for changed in ("symlink", "hardlink", "mode", "bytes"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as directory:
                base = Path(directory).resolve()
                source = base / "dump.sql"
                raw = b"-- synthetic private backup\n"
                m.write_private(source, raw)
                if changed == "symlink":
                    source.rename(base / "real.sql")
                    source.symlink_to(base / "real.sql")
                elif changed == "hardlink":
                    os.link(source, base / "linked.sql")
                elif changed == "mode":
                    source.chmod(0o644)
                else:
                    source.write_bytes(raw + b"changed")
                with self.assertRaises(m.GateError):
                    m.backup_restore_commands(
                        "/trusted/docker", self.container, self.owner, source, raw
                    )

    def test_actual_shell_guards_before_psql_and_preserves_restore_or_removal_failure(self):
        import subprocess
        import sys

        # The host is BSD; these two tiny tool fixtures provide GNU-compatible
        # stat/hash output from actual fixture metadata/bytes for the container
        # shell. psql and rm are separately controlled, without a database.
        stat_tool = """import os,sys
s=os.lstat(sys.argv[-1]);print(f'{s.st_uid}:{s.st_gid}:{s.st_mode & 0o777:o}:{s.st_nlink}:{s.st_size}')
"""
        hash_tool = """import hashlib,pathlib,sys
p=pathlib.Path(sys.argv[-1]);print(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+str(p))
"""
        psql_tool = """import os,pathlib,sys
pathlib.Path(os.environ['CALL_MARKER']).write_text('called');sys.exit(int(os.environ['PSQL_STATUS']))
"""
        rm_tool = """import os,sys
code=int(os.environ['RM_STATUS'])
if not code: os.unlink(sys.argv[-1])
sys.exit(code)
"""
        for psql_status, rm_status, change, expected in (
            (0, 0, None, 0),
            (7, 0, None, 7),
            (0, 9, None, 9),
            (7, 9, None, 7),
            (0, 0, "bytes", 91),
            (0, 0, "mode", 91),
            (0, 0, "hardlink", 91),
            (0, 0, "symlink", 91),
        ):
            with (
                self.subTest(psql=psql_status, rm=rm_status, change=change),
                tempfile.TemporaryDirectory() as directory,
            ):
                base = Path(directory).resolve()
                source, marker = base / "dump.sql", base / "psql-called"
                raw = b"-- synthetic private backup\n"
                m.write_private(source, raw)
                _, restore, _ = m.backup_restore_commands(
                    "/trusted/docker", self.container, self.owner, source, raw
                )
                script = restore[-1].replace("/tmp/p2-starter-" + self.owner + ".sql", str(source))
                # This CPU-only host test cannot chown files to the container
                # identity. Substitute only that expected numeric owner for the
                # local shell control; the argv test checks the real 999:999.
                info = source.lstat()
                script = script.replace("'999:999:600:1:", f"'{info.st_uid}:{info.st_gid}:600:1:")
                for name, body in (
                    ("stat", stat_tool),
                    ("sha256sum", hash_tool),
                    ("psql", psql_tool),
                    ("rm", rm_tool),
                ):
                    target = base / name
                    target.write_text("#!" + sys.executable + "\n" + body)
                    target.chmod(0o700)
                if change == "bytes":
                    source.write_bytes(raw + b"changed")
                elif change == "mode":
                    source.chmod(0o644)
                elif change == "hardlink":
                    os.link(source, base / "linked.sql")
                elif change == "symlink":
                    source.rename(base / "real.sql")
                    source.symlink_to(base / "real.sql")
                result = subprocess.run(
                    ["/bin/sh", "-c", script],
                    env={
                        "PATH": str(base),
                        "CALL_MARKER": str(marker),
                        "PSQL_STATUS": str(psql_status),
                        "RM_STATUS": str(rm_status),
                    },
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=3,
                    check=False,
                )
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(marker.exists(), change is None)
                self.assertEqual(source.exists(), change is not None or rm_status != 0)


if __name__ == "__main__":
    unittest.main()
