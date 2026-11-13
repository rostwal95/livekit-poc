"""Offline CA snapshot lifecycle and mode isolation; no keys or runtime commands."""

import hashlib
import importlib.util
import io
import json
import os
import shutil
import ssl
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import certifi

ROOT = Path.cwd()


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


stack = load("provider_ca_lifecycle_stack", "local-setup/stack.py")
demo = load("provider_ca_lifecycle_demo", "local-setup/scripts/phase_g_demo.py")
runner = load("provider_ca_lifecycle_runner", "local-setup/scripts/p1_runtime_acceptance.py")


class ProviderCASnapshotLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cafile=certifi.where())
        cls.public_pem = ssl.DER_cert_to_PEM_cert(context.get_ca_certs(binary_form=True)[0]).encode(
            "ascii"
        )

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name).resolve()
        self.setup = self.folder / "local-setup"
        self.setup.mkdir(mode=0o700)
        shutil.copyfile(ROOT / "local-setup/provider_config.py", self.setup / "provider_config.py")
        self.source = self.folder / "SYNTHETIC_TRUST_SOURCE.pem"
        self.source.write_bytes(self.public_pem)
        self.source.chmod(0o600)

    def test_restrictive_umask_still_produces_readable_native_snapshots_in_both_paths(self):
        owned = self.folder / "owned-demo"
        owned.mkdir(mode=0o700)
        previous = os.umask(0o077)
        try:
            persistent = stack.provider_ca_snapshot(self.setup, self.source)
            mount, evidence = demo.provider_ca_mount(self.setup, self.source, owned)
        finally:
            os.umask(previous)
        ephemeral = owned / "provider-ca.pem"
        for target in (persistent, ephemeral):
            self.assertEqual(target.stat().st_mode & 0o777, 0o644)
            self.assertEqual(target.stat().st_nlink, 1)
            self.assertEqual(target.read_bytes(), self.public_pem)
        self.assertTrue(mount.endswith(",dst=/etc/ssl/certs/ca-certificates.crt,readonly"))
        self.assertEqual(
            evidence,
            {
                "schema_version": 1,
                "bundle_sha256": hashlib.sha256(self.public_pem).hexdigest(),
                "bundle_bytes": len(self.public_pem),
            },
        )
        self.assertNotIn("SYNTHETIC_TRUST_SOURCE", json.dumps(evidence))
        self.assertNotIn("BEGIN CERTIFICATE", json.dumps(evidence))

    def test_persistent_repeat_uses_one_bounded_name_and_replaces_atomically(self):
        target = stack.provider_ca_snapshot(self.setup, self.source)
        original_inode = target.stat().st_ino
        changed = self.public_pem + b"\n"
        self.source.write_bytes(changed)
        actual_replace = os.replace
        observations = []

        def replace(source, destination):
            source, destination = Path(source), Path(destination)
            observations.append(
                (source.read_bytes(), destination.read_bytes(), source.stat().st_mode & 0o777)
            )
            return actual_replace(source, destination)

        with patch.object(stack.os, "replace", side_effect=replace):
            repeated = stack.provider_ca_snapshot(self.setup, self.source)
        self.assertEqual(repeated, target)
        self.assertEqual(observations, [(changed, self.public_pem, 0o644)])
        self.assertNotEqual(target.stat().st_ino, original_inode)
        self.assertEqual(target.read_bytes(), changed)
        for _ in range(8):
            self.assertEqual(stack.provider_ca_snapshot(self.setup, self.source), target)
        self.assertEqual(
            {path.name for path in target.parent.iterdir()}, {"initialize.lock", "provider-ca.pem"}
        )

    def test_failed_replace_preserves_original_and_removes_owned_temporary_file(self):
        target = stack.provider_ca_snapshot(self.setup, self.source)
        original = target.read_bytes()
        self.source.write_bytes(self.public_pem + b"\n")
        with (
            patch.object(stack.os, "replace", side_effect=OSError("SYNTHETIC_PRIVATE_FAILURE")),
            self.assertRaises(stack.SetupError) as caught,
        ):
            stack.provider_ca_snapshot(self.setup, self.source)
        self.assertEqual(target.read_bytes(), original)
        self.assertNotIn("SYNTHETIC_PRIVATE_FAILURE", str(caught.exception))
        self.assertEqual(
            {path.name for path in target.parent.iterdir()}, {"initialize.lock", "provider-ca.pem"}
        )

    def test_persistent_target_and_generated_directory_symlinks_are_not_followed(self):
        generated = self.setup / ".generated"
        generated.mkdir(mode=0o700)
        victim = self.folder / "untouched.pem"
        victim.write_bytes(b"SYNTHETIC_UNTOUCHED")
        target = generated / "provider-ca.pem"
        target.symlink_to(victim)
        with self.assertRaises(stack.SetupError):
            stack.provider_ca_snapshot(self.setup, self.source)
        self.assertTrue(target.is_symlink())
        self.assertEqual(victim.read_bytes(), b"SYNTHETIC_UNTOUCHED")
        target.unlink()
        (generated / "initialize.lock").unlink()
        generated.rmdir()
        outside = self.folder / "outside"
        outside.mkdir()
        generated.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(stack.SetupError):
            stack.provider_ca_snapshot(self.setup, self.source)
        self.assertEqual(list(outside.iterdir()), [])

    def test_demo_snapshot_refuses_existing_regular_or_symlink_target(self):
        owned = self.folder / "owned-demo"
        owned.mkdir(mode=0o700)
        target = owned / "provider-ca.pem"
        target.write_bytes(b"SYNTHETIC_EXISTING")
        with self.assertRaises(FileExistsError):
            demo.provider_ca_mount(self.setup, self.source, owned)
        self.assertEqual(target.read_bytes(), b"SYNTHETIC_EXISTING")
        target.unlink()
        victim = self.folder / "victim.pem"
        victim.write_bytes(b"SYNTHETIC_UNTOUCHED")
        target.symlink_to(victim)
        with self.assertRaises(OSError):
            demo.provider_ca_mount(self.setup, self.source, owned)
        self.assertTrue(target.is_symlink())
        self.assertEqual(victim.read_bytes(), b"SYNTHETIC_UNTOUCHED")

    def test_stack_ca_flag_is_refused_before_any_configuration_or_runtime_action(self):
        with (
            patch.object(stack, "provider_configuration") as configuration,
            patch.object(stack, "load_settings") as settings,
            patch.object(stack, "assert_owned_containers") as owned,
            patch.object(stack, "run") as run,
            patch.object(stack, "initialize") as initialize,
        ):
            for action in (
                "init",
                "start",
                "start-business",
                "start-local-real",
                "stop-provider",
                "check-providers",
                "models-verify",
            ):
                with self.subTest(action=action), redirect_stdout(io.StringIO()) as output:
                    code = stack.main(
                        [action, "--provider-ca-bundle", str(self.source)], setup=self.setup
                    )
                self.assertEqual(code, 2)
                observed = json.loads(output.getvalue())
                self.assertNotIn("SYNTHETIC_TRUST_SOURCE", json.dumps(observed))
            for dependency in (configuration, settings, owned, run, initialize):
                dependency.assert_not_called()

    def test_demo_ca_flag_is_refused_before_credentials_deadline_or_model_preparation(self):
        with (
            patch.object(demo, "load_provider_environment") as credentials,
            patch.object(demo.real_media, "WorkDeadline") as deadline,
            patch.object(demo.real_media, "model_manifest") as models,
            patch.object(demo.real_media, "declaration") as declaration,
        ):
            for mode in ("scripted", "local_real"):
                with self.subTest(mode=mode), redirect_stdout(io.StringIO()) as output:
                    code = demo.cli(["--mode", mode, "--provider-ca-bundle", str(self.source)])
                self.assertEqual(code, 1)
                observed = json.loads(output.getvalue())
                self.assertEqual(observed["code"], "phase_g_demo_failed")
                self.assertNotIn("SYNTHETIC_TRUST_SOURCE", json.dumps(observed))
            for dependency in (credentials, deadline, models, declaration):
                dependency.assert_not_called()

    def test_wrapper_forwards_ca_only_for_selected_provider_twenty_and_retains_digest_only(self):
        root = self.folder / "synthetic-repo"
        scripts = root / "local-setup/scripts"
        scripts.mkdir(parents=True)
        (root / ".local/validation").mkdir(parents=True)
        (scripts / "phase_g_demo.py").write_text("# no runtime in this synthetic fixture\n")
        shutil.copyfile(
            ROOT / "local-setup/provider_config.py", root / "local-setup/provider_config.py"
        )
        for case, mode, expected in (
            ("P1-20", "provider_real", True),
            ("P1-20", "local_real", False),
            ("P1-14", "provider_real", False),
        ):
            with (
                self.subTest(case=case, mode=mode),
                patch.dict(os.environ, {"P1_PROVIDER_CA_BUNDLE": str(self.source)}),
                patch.object(
                    runner, "command", side_effect=RuntimeError("SYNTHETIC_STOP_BEFORE_RUNTIME")
                ) as command,
            ):
                report, code = runner.run_case(case, root=root, real_profile=mode)
            self.assertEqual(code, 1)
            self.assertEqual(report["status"], "failed")
            argv = command.call_args.args[1]
            self.assertEqual("--provider-ca-bundle" in argv, expected)
            if expected:
                self.assertEqual(argv[argv.index("--provider-ca-bundle") + 1], str(self.source))
        for path in (root / ".local/validation/p1-runtime-acceptance").glob("*/evidence.json"):
            observed = json.loads(path.read_text())
            self.assertNotIn("SYNTHETIC_TRUST_SOURCE", json.dumps(observed))
            self.assertNotIn("SYNTHETIC_STOP_BEFORE_RUNTIME", json.dumps(observed))
            if observed["real_profile"] == "provider_real" and observed["case_id"] == "P1-20":
                self.assertEqual(
                    observed["provider_trust_selection"],
                    {
                        "source": "explicit_ca_bundle",
                        "bundle_sha256": hashlib.sha256(self.public_pem).hexdigest(),
                        "bundle_bytes": len(self.public_pem),
                        "native_only_mount_verified": True,
                    },
                )
