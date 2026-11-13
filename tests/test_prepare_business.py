"""Host bootstrap contracts use real auxiliary SQLite and explicit fake PG ports."""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from continuity_lab.cutover import CutoverReport
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.source_transfer import bind_source_target, mark_source_cutover, prepare_source

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bootstrap = load("prepare_business_test", ROOT / "local-setup/scripts/prepare_business.py")
stack = load("prepare_business_stack_test", ROOT / "local-setup/stack.py")
OWNER = PostgresSettings(user="continuity_migrator", password="synthetic-owner-password")
RUNTIME = PostgresSettings(password="synthetic-runtime-password")


class FakePostgres:
    def __init__(self, target=None, fail=None):
        self.target = target or bootstrap.Target(0, "absent")
        self.calls = []
        self.fail = fail

    def inspect(self):
        self.calls.append("inspect")
        return self.target

    def activate(self, source, backup):
        self.calls.append("activate")
        snapshot = prepare_source(source, backup)
        bind_source_target(source, bootstrap.binding(OWNER, RUNTIME))
        mark_source_cutover(source, snapshot)
        self.target = bootstrap.Target(
            1, "active", snapshot.migration_id, snapshot.source_digest, (0, 0, 0)
        )
        return CutoverReport(snapshot.migration_id, snapshot.source_digest, "active", True, 0, 0, 0)

    def upgrade(self, version):
        self.calls.append(version)
        if self.fail == version:
            raise bootstrap.BootstrapError("bootstrap_failed")
        self.target = bootstrap.Target(
            max(version, self.target.version),
            "active",
            self.target.migration_id,
            self.target.source_digest,
            (0, 0, 0),
        )

    def ready(self):
        self.calls.append("ready")


class BusinessPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "business-bootstrap"
        self.main = self.root / "serving-m1.sqlite3"
        self.main.write_bytes(b"unrelated original M1 evidence")

    def prepare(self, port):
        return bootstrap.prepare(OWNER, RUNTIME, self.base, operations=port)

    def test_fresh_source_public_cutover_sequence_is_private_empty_and_separate_from_serving_m1(
        self,
    ):
        port = FakePostgres()
        value = self.prepare(port)
        self.assertEqual(["inspect", "activate", 2, 3, 4, "ready"], port.calls)
        self.assertTrue(value["changed"])
        self.assertFalse(value["fixture_initialization"])
        directory = self.base / value["bootstrap_run_id"]
        for name in ("source.sqlite3", "before-cutover.sqlite3", "before-inquiry-schema.sqlite3"):
            bootstrap.private_file(directory / name)
        self.assertEqual(b"unrelated original M1 evidence", self.main.read_bytes())
        state = json.loads((directory / "stage.json").read_text())
        self.assertEqual("passed", state["status"])

    def test_owned_partial_failure_resumes_same_identity_source_and_backups(self):
        port = FakePostgres(fail=3)
        with self.assertRaises(bootstrap.BootstrapError):
            self.prepare(port)
        entry = next(self.base.glob("target-*.json"))
        first = json.loads(entry.read_text())
        directory = self.base / first["run_id"]
        hashes = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.glob("*.sqlite3")
        }
        port.fail = None
        port.calls = []
        result = self.prepare(port)
        self.assertEqual(first["run_id"], result["bootstrap_run_id"])
        self.assertEqual(
            hashes,
            {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in directory.glob("*.sqlite3")
            },
        )
        self.assertEqual(first, json.loads(entry.read_text()))

    def test_valid_active_v4_is_readonly_ready_and_never_creates_an_auxiliary_source(self):
        port = FakePostgres(
            bootstrap.Target(4, "active", "11111111-1111-4111-8111-111111111111", "a" * 64)
        )
        result = self.prepare(port)
        self.assertFalse(result["changed"])
        self.assertIsNone(result["bootstrap_run_id"])
        self.assertEqual(["inspect", "ready"], port.calls)
        self.assertEqual([".prepare.lock"], [p.name for p in self.base.iterdir()])

    def test_unowned_imported_active_old_and_nonempty_targets_refuse_before_source_or_pg_mutation(
        self,
    ):
        for target in [
            bootstrap.Target(1, "staging", counts=(1, 0, 0)),
            bootstrap.Target(
                1, "staging", "11111111-1111-4111-8111-111111111111", "a" * 64, (0, 0, 0)
            ),
            bootstrap.Target(
                2, "active", "11111111-1111-4111-8111-111111111111", "a" * 64, (0, 0, 0)
            ),
        ]:
            with self.subTest(target=target):
                port = FakePostgres(target)
                with self.assertRaises(bootstrap.BootstrapError):
                    self.prepare(port)
                self.assertEqual(["inspect"], port.calls)
                self.assertFalse(list(self.base.glob("*/source.sqlite3")))

    def test_roles_endpoint_schema_and_equal_credentials_are_rejected_before_any_io(self):
        for owner, runtime in [
            (replace(OWNER, user="livekit_lab_admin"), RUNTIME),
            (OWNER, replace(RUNTIME, port=15433)),
            (OWNER, replace(RUNTIME, schema="other")),
            (OWNER, replace(RUNTIME, password=OWNER.password)),
            (replace(OWNER, host="postgres"), replace(RUNTIME, host="postgres")),
        ]:
            port = FakePostgres()
            with (
                self.subTest(owner=owner.user, runtime=runtime.user),
                self.assertRaises(bootstrap.BootstrapError),
            ):
                bootstrap.prepare(owner, runtime, self.base, operations=port)
            self.assertEqual([], port.calls)
            self.assertFalse(self.base.exists())

    def test_missing_backup_or_corrupt_receipt_never_recreates_source_for_partial_target(self):
        port = FakePostgres(fail=3)
        with self.assertRaises(bootstrap.BootstrapError):
            self.prepare(port)
        entry = next(self.base.glob("target-*.json"))
        value = json.loads(entry.read_text())
        directory = self.base / value["run_id"]
        (directory / "before-cutover.sqlite3").unlink()
        port.calls = []
        with self.assertRaises(bootstrap.BootstrapError):
            self.prepare(port)
        self.assertEqual(["inspect"], port.calls)
        self.assertFalse((directory / "before-cutover.sqlite3").exists())

    def test_failed_lock_contender_preserves_shared_inode_and_existing_artifacts(self):
        with bootstrap.owned_lock(self.base):
            lock = self.base / ".prepare.lock"
            inode = lock.stat().st_ino
            with (
                self.assertRaises(bootstrap.BootstrapError) as caught,
                bootstrap.owned_lock(self.base),
            ):
                self.fail("contender acquired")
            self.assertEqual("bootstrap_busy", caught.exception.code)
            self.assertEqual(inode, lock.stat().st_ino)
        self.assertTrue(lock.is_file())

    def test_symlink_insecure_directory_and_invalid_receipt_shapes_fail_without_mutation(self):
        self.base.mkdir(mode=0o755)
        with self.assertRaises(bootstrap.BootstrapError):
            self.prepare(FakePostgres())
        self.base.chmod(0o700)
        entry = self.base / ("target-" + bootstrap.binding(OWNER, RUNTIME) + ".json")
        entry.symlink_to(self.main)
        with self.assertRaises(bootstrap.BootstrapError):
            self.prepare(FakePostgres())
        self.assertEqual(b"unrelated original M1 evidence", self.main.read_bytes())

    def test_close_failure_retains_primary_fixed_error_and_separate_cleanup_flag(self):
        failure = bootstrap.BootstrapError("target_refused")
        close = os.close

        def close_then_fail(fd):
            close(fd)
            raise OSError("private-cleanup-sentinel")

        with (
            patch.object(bootstrap.os, "close", side_effect=close_then_fail),
            self.assertRaises(bootstrap.BootstrapError) as caught,
            bootstrap.owned_lock(self.base),
        ):
            raise failure
        self.assertIs(failure, caught.exception)
        self.assertTrue(failure.cleanup_incomplete)
        self.assertNotIn("sentinel", str(failure))

    def test_public_primary_failure_cause_survives_secondary_lock_close_failure(self):
        primary = RuntimeError("private-primary-sentinel")
        close = os.close

        def close_then_fail(fd):
            close(fd)
            raise OSError("private-cleanup-sentinel")

        with (
            patch.object(bootstrap.os, "close", side_effect=close_then_fail),
            self.assertRaises(bootstrap.BootstrapError) as caught,
            bootstrap.owned_lock(self.base),
        ):
            raise primary
        self.assertIs(primary, caught.exception.__cause__)
        self.assertTrue(caught.exception.cleanup_incomplete)
        self.assertNotIn("sentinel", str(caught.exception))

    def test_unowned_database_namespace_refuses_before_public_schema_install_or_validation(self):
        connection = Mock()
        connection.execute.return_value.fetchone.return_value = {"owner": "foreign"}
        with (
            patch.object(PostgresSettings, "connect", return_value=connection),
            patch.object(bootstrap, "read_import_state") as read,
            self.assertRaises(bootstrap.BootstrapError),
        ):
            bootstrap.PostgresBootstrap(OWNER, RUNTIME).inspect()
        read.assert_not_called()
        connection.close.assert_called_once()


class HostActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.setup = self.root / "local-setup"
        (self.setup / "scripts").mkdir(parents=True)
        (self.setup / "scripts/prepare_business.py").write_text("# host helper")
        interpreter = self.root / ".venv/bin/python"
        interpreter.parent.mkdir(parents=True)
        interpreter.write_text("# host interpreter")
        interpreter.chmod(0o700)

    def test_action_runs_only_fixed_venv_child_after_ownership_no_docker_or_fixture_actions(self):
        out = io.StringIO()
        with (
            patch.object(stack, "load_settings", return_value={}),
            patch.object(stack, "assert_owned_containers") as owned,
            patch.object(stack, "run", return_value='{"status":"business_ready"}') as run,
            contextlib.redirect_stdout(out),
        ):
            self.assertEqual(0, stack.main(["prepare-business"], setup=self.setup))
        owned.assert_called_once()
        run.assert_called_once()
        argv, _, setup, timeout = run.call_args.args
        self.assertEqual(
            [str(self.root / ".venv/bin/python"), str(self.setup / "scripts/prepare_business.py")],
            argv,
        )
        self.assertEqual(120, timeout)
        self.assertEqual(self.setup, setup)
        self.assertNotIn("docker", argv)
        self.assertFalse(json.loads(out.getvalue())["fixtureInitialization"])

    def test_foreign_ownership_missing_interpreter_and_nonzero_child_are_nonpassing(self):
        for error in (stack.SetupError("Foreign checkout"), stack.SetupError("Child failed")):
            with (
                patch.object(stack, "load_settings", return_value={}),
                patch.object(stack, "assert_owned_containers"),
                patch.object(stack, "run", side_effect=error),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(2, stack.main(["prepare-business"], setup=self.setup))
        (self.root / ".venv/bin/python").unlink()
        with (
            patch.object(stack, "load_settings", return_value={}),
            patch.object(stack, "assert_owned_containers"),
            patch.object(stack, "run") as run,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(2, stack.main(["prepare-business"], setup=self.setup))
        run.assert_not_called()

    def test_missing_optional_dependencies_emit_only_closed_setup_code(self):
        result = subprocess.run(
            [sys.executable, "-I", "-S", str(ROOT / "local-setup/scripts/prepare_business.py")],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertEqual("", result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("setup_required", payload["code"])
        self.assertEqual("preflight", payload["stage"])
        self.assertFalse(payload["partial_artifacts_retained"])
        self.assertNotIn("Traceback", result.stdout)

    def test_private_cli_error_stages_are_fixed_and_deadline_is_restored(self):
        # The child normally owns this process; unit capture prevents ambient test
        # state from being changed while exercising its closed exception boundary.
        fake = Mock()
        fake.load_settings.return_value = {
            "POSTGRES_PORT": "15432",
            "POSTGRES_PASSWORD": RUNTIME.password,
            "POSTGRES_MIGRATION_PASSWORD": OWNER.password,
        }
        spec = Mock()
        spec.loader = Mock()
        previous = signal.getsignal(signal.SIGALRM)
        with (
            patch.dict(os.environ, {}, clear=False),
            patch.object(bootstrap, "ROOT", self.root),
            patch.object(bootstrap.sys, "argv", ["prepare_business.py"]),
            patch.object(bootstrap.importlib.util, "spec_from_file_location", return_value=spec),
            patch.object(bootstrap.importlib.util, "module_from_spec", return_value=fake),
            patch.object(bootstrap, "prepare", side_effect=RuntimeError("private-sentinel")),
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(2, bootstrap.main())
        self.assertNotIn("private-sentinel", out.getvalue())
        self.assertNotIn(OWNER.password, out.getvalue())
        self.assertEqual(previous, signal.getsignal(signal.SIGALRM))
        self.assertEqual(0, signal.getitimer(signal.ITIMER_REAL)[0])


if __name__ == "__main__":
    unittest.main()
