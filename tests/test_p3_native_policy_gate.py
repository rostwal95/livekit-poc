"""Pure independent gate controls; no compiler, PG, RTC, browser or provider."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import importlib
import io
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local-setup/scripts"))
gate = importlib.import_module("p3_native_policy_check")


def encoded(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def report(installed: bool = False):
    return {
        "schema_version": 1,
        "status": "passed",
        "mode": "local_native_policy_installed" if installed else "local_native_policy_source",
        "tests": 12,
        "passed": 12,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "duration_seconds": 1.0,
        "child_commands": 32 if installed else 11,
        "browser_groups": 3,
        "package_assertions": 8 if installed else 0,
        "cleanup_complete": True,
        "code": "ok",
        "stage": "complete",
        "retained_index_sha256": "a" * 64,
        "case_results": [{"name": n, "status": "passed"} for n in gate.CASES],
    }


def browser_case():
    observation = json.loads(
        (ROOT / "contracts/delegation/native-policy-view-v1.json").read_text()
    )["observations"]["candidate"]
    return {
        "accepted": {"work_id": observation["work"]["work_id"]},
        "request": {"input_fingerprint": observation["binding"]["input_fingerprint"]},
        "observation": observation,
    }


def browser(case):
    result = case["observation"]["result"]
    return {
        "schema_version": 1,
        "status": "passed",
        "mode": "local_scripted_p3_native_text",
        "groups": [{"name": n, "status": "passed"} for n in gate.BROWSER_GROUPS],
        "session_id": "33333333-3333-4333-8333-333333333333",
        "work_id": case["accepted"]["work_id"],
        "request_revision": 1,
        "input_fingerprint": case["request"]["input_fingerprint"],
        "useful_reply_sha256": "3be46c35bdf54d5f5a95618f8351476610050e5adcd5af9b3a8feac1c96e62a7",
        "final_reply_observed": False,
        "states": {
            "held": {"state": "work", "owned_run": True, "result_observed": False},
            "outdated": {
                "state": "outdated",
                "result_sha256": result["sha256"],
                "attempt_id": result["attempt_id"],
                "disposition": result["disposition"],
                "applicability": "outdated",
            },
            "failed": {"code": "unavailable", "historical": True, "original_facts_retained": True},
            "recovered": {
                "state": "outdated",
                "result_sha256": result["sha256"],
                "historical": False,
            },
            "forgotten": {
                "owned_client": 0,
                "actual_requests": 0,
                "actual_sends": 0,
                "cleanup_complete": True,
                "private_facts_cleared": True,
                "password_empty": True,
                "composer_empty": True,
            },
        },
        "counters": {
            "browser_read_requests": 4,
            "fixture_read_interceptions": 1,
            "page_errors": 0,
            "external_requests": 0,
        },
        "screenshots": list(gate.SCREENSHOTS),
    }


class NativePolicyGateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def environment(self, role):
        env = {"PATH": "/usr/bin", "LANG": "C", "CI": "1", "NO_COLOR": "1"}
        if role == "node-server":
            env.update(P3_NATIVE_DIRECTORY=str(self.root), P3_NATIVE_TOKEN="A" * 43)
        elif role == "browser":
            env.update(
                P3_NATIVE_BROWSER_ORIGIN="http://127.0.0.1:13000",
                P3_NATIVE_BROWSER_OUTPUT=str(self.root),
                P3_NATIVE_BROWSER_ACCESS="B" * 43,
            )
        elif role in {"install", "cleanup", "native-consumer"}:
            env.update(
                P3_FIXED_WORK_DIRECTORY=str(self.root),
                P3_FIXED_WORK_WORK_SCHEMA="p1_work_fixedv2_" + "a" * 32,
                P3_FIXED_WORK_CASE_SCHEMA="p3_completion_" + "a" * 32,
                P3_FIXED_WORK_PG_PORT="5432",
            )
            if role == "native-consumer":
                env.update(
                    P3_FIXED_WORK_RUNTIME_PASSWORD="PRIVATE_ENV_SENTINEL",
                    P3_FIXED_WORK_TOKEN="C" * 43,
                )
            else:
                env["P3_FIXED_WORK_OWNER_PASSWORD"] = "PRIVATE_OWNER_SENTINEL"
        return env

    def test_plan_is_pure_and_separates_backend_browser_and_package_counts(self):
        with patch.object(gate, "private_directory", side_effect=AssertionError("created")):
            for installed in (False, True):
                value = gate.plan(installed=installed)
                self.assertEqual(value["status"], "planned")
                self.assertEqual(
                    (value["tests"], value["browser_groups"], value["package_assertions"]),
                    (12, 3, 8 if installed else 0),
                )
                self.assertEqual(value["child_commands"], 32 if installed else 11)
                self.assertEqual(
                    value["applications"],
                    ["native_known", "native_retained", "native_stale", "native_useful"],
                )
                self.assertEqual(
                    (value["deadline_seconds"], value["cleanup_seconds"]),
                    (360 if installed else 180, 20),
                )
        self.assertEqual(list(self.root.iterdir()), [])
        for invalid in (1, None, "installed"):
            with self.subTest(invalid=invalid), self.assertRaises(gate.GateError):
                gate.plan(installed=invalid)

    def test_cli_plan_does_not_construct_a_runner_or_touch_missing_setup(self):
        for installed in (False, True):
            output = io.StringIO()
            with (
                patch.object(gate, "NativePolicyRun", side_effect=AssertionError("constructed")),
                patch.object(gate, "private_directory", side_effect=AssertionError("created")),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(
                    gate.main(
                        ["--plan", *(["--installed"] if installed else [])],
                        root=self.root / "absent",
                    ),
                    0,
                )
            self.assertEqual(json.loads(output.getvalue()), gate.plan(installed=installed))
        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as result:
            gate.main(["--unknown", "PRIVATE_ARG_SENTINEL"], root=self.root)
        self.assertEqual(result.exception.code, 2)
        self.assertNotIn("PRIVATE_ARG_SENTINEL", error.getvalue())
        self.assertEqual(json.loads(error.getvalue())["code"], "invalid_input")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_prepare_failure_cannot_remove_work_with_retained_sfu_or_parent_owners(self):
        for changed in (
            {"room_cleaned": False},
            {"api_client": object()},
            {"async_tasks": {object()}},
            {"parent_ports": [object()]},
        ):
            run = object.__new__(gate.NativePolicyRun)
            run.room_cleaned, run.api_client, run.async_tasks, run.parent_ports = (
                True,
                None,
                set(),
                [],
            )
            run.nested_cleanup_known = True
            run.lab_started = False
            run.retain_unresolved_work = Mock()
            for key, value in changed.items():
                setattr(run, key, value)
            with (
                self.subTest(owner=tuple(changed)),
                patch.object(
                    gate.policy.FixedPolicyRun,
                    "remove_work",
                    side_effect=AssertionError("removed unresolved work"),
                ) as removed,
            ):
                with self.assertRaises(gate.GateError) as failure:
                    run.remove_work()
                self.assertEqual(failure.exception.code, "cleanup_incomplete")
                removed.assert_not_called()
        run = object.__new__(gate.NativePolicyRun)
        run.room_cleaned, run.api_client, run.async_tasks, run.parent_ports = True, None, set(), []
        run.nested_cleanup_known = True
        with patch.object(gate.policy.FixedPolicyRun, "remove_work") as removed:
            run.remove_work()
            removed.assert_called_once()

    def test_source_installed_and_failed_reports_remain_distinct(self):
        for installed in (False, True):
            self.assertEqual(gate.validated_report(encoded(report(installed))), report(installed))
        value = report()
        value.update(
            status="failed",
            passed=0,
            failures=1,
            code="component_failed",
            stage="native-consumer",
            child_commands=0,
            browser_groups=0,
            cleanup_complete=False,
            retained_index_sha256=None,
            case_results=[],
        )
        self.assertEqual(gate.validated_report(encoded(value))["status"], "failed")

    def test_forged_success_partial_groups_wrong_types_and_nonfinite_reports_fail(self):
        for key, replacement in (
            ("schema_version", True),
            ("tests", 15),
            ("passed", 11),
            ("failures", 1),
            ("errors", 1),
            ("skipped", 1),
            ("browser_groups", 2),
            ("browser_groups", True),
            ("child_commands", 10),
            ("package_assertions", 8),
            ("cleanup_complete", 1),
            ("retained_index_sha256", None),
            ("code", "untrusted"),
            ("stage", "room"),
            ("case_results", []),
            ("duration_seconds", True),
            ("duration_seconds", float("nan")),
            ("duration_seconds", float("inf")),
            ("duration_seconds", 181),
            ("unknown", "PRIVATE_SENTINEL"),
        ):
            value = report()
            value[key] = replacement
            with self.subTest(key=key, replacement=replacement), self.assertRaises(gate.GateError):
                gate.validated_report(encoded(value))
        value = report(True)
        value["package_assertions"] = 0
        with self.assertRaises(gate.GateError):
            gate.validated_report(encoded(value))
        for raw in (b"{}", b'{"schema_version":1,"schema_version":1}', b"[1]", b"{" * 4000):
            with self.subTest(raw=raw[:30]), self.assertRaises(gate.GateError):
                gate.validated_report(raw)

    def test_malformed_report_nested_types_remain_finite_safe_errors(self):
        for key, replacement in (
            ("mode", []),
            ("code", {}),
            ("stage", []),
            ("case_results", {"name": "PRIVATE_SENTINEL"}),
        ):
            value = report()
            value[key] = replacement
            with self.subTest(key=key):
                with self.assertRaises(gate.GateError) as caught:
                    gate.validated_report(encoded(value))
                self.assertNotIn("PRIVATE_SENTINEL", str(caught.exception))

    def test_roles_reject_ambient_credentials_proxies_and_other_role_authority(self):
        for role in ("node-server", "browser", "native-consumer", "install", "cleanup", "build"):
            original = self.environment(role)
            gate.validate_environment(original, role)
            for key in (
                "OPENAI_API_KEY",
                "DEEPGRAM_API_KEY",
                "ELEVENLABS_API_KEY",
                "HTTP_PROXY",
                "PYTHONPATH",
                "NODE_OPTIONS",
                "PGPASSWORD",
                "LIVEKIT_API_SECRET",
            ):
                changed = dict(original, **{key: "PRIVATE_ENV_SENTINEL"})
                with self.subTest(role=role, key=key), self.assertRaises(gate.GateError):
                    gate.validate_environment(changed, role)
        for role in ("node-server", "browser"):
            changed = self.environment(role)
            changed["P3_FIXED_WORK_OWNER_PASSWORD"] = "PRIVATE_OWNER_SENTINEL"
            with self.subTest(role=role), self.assertRaises(gate.GateError):
                gate.validate_environment(changed, role)
        changed = self.environment("native-consumer")
        changed["P3_FIXED_WORK_OWNER_PASSWORD"] = "PRIVATE_OWNER_SENTINEL"
        with self.assertRaises(gate.GateError):
            gate.validate_environment(changed, "native-consumer")

    def test_role_selectors_paths_and_origin_port_are_closed(self):
        for role in ("node-server", "browser", "native-consumer", "install", "cleanup"):
            original = self.environment(role)
            for key in tuple(original):
                if key not in {"PATH", "LANG", "CI", "NO_COLOR"}:
                    value = dict(original)
                    value.pop(key)
                    with self.subTest(role=role, missing=key), self.assertRaises(gate.GateError):
                        gate.validate_environment(value, role)
        for role, field in (
            ("node-server", "P3_NATIVE_DIRECTORY"),
            ("browser", "P3_NATIVE_BROWSER_OUTPUT"),
        ):
            for path in ("relative", str(self.root / ".." / "escape")):
                value = self.environment(role)
                value[field] = path
                with self.subTest(field=field, path=path), self.assertRaises(gate.GateError):
                    gate.validate_environment(value, role)
        for origin in (
            "http://127.0.0.1:65536",
            "http://127.0.0.1:0",
            "http://127.0.0.1:13000/",
            "https://127.0.0.1:13000",
            "http://user@127.0.0.1:13000",
        ):
            value = self.environment("browser")
            value["P3_NATIVE_BROWSER_ORIGIN"] = origin
            with self.subTest(origin=origin), self.assertRaises(gate.GateError):
                gate.validate_environment(value, "browser")
        with self.assertRaises(gate.GateError):
            gate.validate_environment(self.environment("build"), "unregistered")

    def test_browser_original_truth_recovery_and_actual_cleanup_must_all_join(self):
        case = browser_case()
        valid = browser(case)
        self.assertEqual(gate.validate_browser(valid, case, session_id=valid["session_id"]), valid)
        variants = []
        for key, value in (
            ("work_id", "44444444-4444-4444-8444-444444444444"),
            ("input_fingerprint", "0" * 64),
            ("request_revision", 2),
            ("final_reply_observed", 1),
            ("groups", []),
        ):
            changed = copy.deepcopy(valid)
            changed[key] = value
            variants.append(changed)
        for section, key, value in (
            ("held", "result_observed", True),
            ("held", "owned_run", False),
            ("outdated", "disposition", "expired"),
            ("outdated", "applicability", "candidate"),
            ("failed", "historical", False),
            ("recovered", "historical", True),
            ("forgotten", "owned_client", 1),
            ("forgotten", "actual_requests", 1),
            ("forgotten", "cleanup_complete", False),
            ("forgotten", "password_empty", False),
        ):
            changed = copy.deepcopy(valid)
            changed["states"][section][key] = value
            variants.append(changed)
        for key, value in (
            ("browser_read_requests", 17),
            ("fixture_read_interceptions", 2),
            ("page_errors", 1),
            ("external_requests", 1),
        ):
            changed = copy.deepcopy(valid)
            changed["counters"][key] = value
            variants.append(changed)
        for index, changed in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(gate.GateError):
                gate.validate_browser(changed, case, session_id=valid["session_id"])

    def test_cleanup_does_not_drain_already_closed_accounted_process_handles(self):
        events = []

        class Child:
            returncode = 0

            def __init__(self, pid, already_closed):
                self.pid = pid
                self.already_closed = already_closed

            def wait(self, **kwargs):
                events.append(("wait", self.pid))
                if self.already_closed:
                    raise ValueError("closed selector")

            def close(self):
                events.append(("close", self.pid))

        accounted, exited = Child(111, True), Child(222, False)
        run = object.__new__(gate.NativePolicyRun)
        run.children = [accounted, exited]
        run.accounted = {accounted.pid}
        run.final_deadline = time.monotonic() + 10

        def capture(child):
            events.append(("capture", child.pid))
            run.accounted.add(child.pid)
            return b"", b""

        run.capture = capture
        run.close_processes()
        self.assertEqual(
            events,
            [("wait", 222), ("close", 222), ("capture", 222), ("close", 111), ("capture", 111)],
        )
        events.clear()
        run.close_processes()
        self.assertEqual(
            events, [("close", 222), ("capture", 222), ("close", 111), ("capture", 111)]
        )

    def test_public_case_failure_survives_failed_close_and_retains_its_port(self):
        for fail_read in (True, False):
            primary = gate.GateError("invalid_proof")

            class Projection:
                def payload(self):
                    return {"case_revision": "1"}

            class Reader:
                def __init__(self, should_fail, original_error):
                    self.should_fail = should_fail
                    self.original_error = original_error
                    self.closes = 0

                async def get(self, **kwargs):
                    if self.should_fail:
                        raise self.original_error
                    return Projection()

                async def close(self):
                    self.closes += 1
                    raise RuntimeError("PRIVATE_CLOSE_SENTINEL")

            reader = Reader(fail_read, primary)
            run = object.__new__(gate.NativePolicyRun)
            run.directory = self.root
            run.lab_settings = {
                "POSTGRES_PORT": "5432",
                "POSTGRES_PASSWORD": "PRIVATE_ENV_SENTINEL",
            }
            run.tokens = ("A" * 43,)
            run.schemas = {"case": "p3_completion_" + "a" * 32}
            run.parent_ports = []
            run.async_call = lambda invoke: asyncio.run(invoke())
            state = {"case_fixed": {"task_id": "44444444-4444-4444-8444-444444444444"}}
            with (
                self.subTest(fail_read=fail_read),
                patch.object(gate, "read_private", return_value=encoded(state)),
                patch("continuity_lab.postgres_api.open_postgres_client", return_value=reader),
            ):
                with self.assertRaises(gate.GateError) as caught:
                    run.public_case()
                if fail_read:
                    self.assertIs(caught.exception, primary)
                else:
                    self.assertEqual(caught.exception.code, "cleanup_incomplete")
                self.assertEqual(reader.closes, 1)
                self.assertIn(reader, run.parent_ports)
                self.assertNotIn("PRIVATE_CLOSE_SENTINEL", str(caught.exception))

    def test_parent_marker_is_complete_before_its_final_name_becomes_visible(self):
        path = self.root / "parent-peer-held.json"
        raw = encoded({"schema_version": 1, "stage": "peer_held"}) + b"\n"
        link = os.link
        observed = []

        def inspect(source, destination, **kwargs):
            self.assertFalse(path.exists())
            self.assertEqual(Path(source).read_bytes(), raw)
            self.assertEqual(stat.S_IMODE(Path(source).stat().st_mode), 0o600)
            link(source, destination, **kwargs)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(path.stat().st_nlink, 2)
            observed.append(True)

        with patch.object(gate.os, "link", side_effect=inspect):
            gate.publish_browser_marker(path, raw)
        self.assertEqual(observed, [True])
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(path.stat().st_nlink, 1)
        self.assertFalse(path.with_name(path.name + ".publishing").exists())
        with self.assertRaises(OSError):
            gate.publish_browser_marker(path, b"changed")
        self.assertEqual(path.read_bytes(), raw)
        self.assertFalse(path.with_name(path.name + ".publishing").exists())
        for name, value in (
            ("other.json", raw),
            ("parent-case-advanced.json", b"x" * 4097),
            ("parent-result-released.json", b""),
        ):
            with self.subTest(name=name, size=len(value)), self.assertRaises(gate.GateError):
                gate.publish_browser_marker(self.root / name, value)

    def test_report_target_is_fresh_owned_scope_and_rejects_links(self):
        requested = Path(".local/validation/p3-native-policy/native-01.json")
        target = gate.target_path(self.root, requested)
        self.assertEqual(target, self.root / requested)
        self.assertEqual(list(self.root.iterdir()), [])
        for invalid in (
            Path("/tmp/elsewhere.json"),
            Path(".local/validation/elsewhere/native.json"),
            Path(".local/validation/p3-native-policy/../native.json"),
        ):
            with self.subTest(path=invalid), self.assertRaises(gate.GateError):
                gate.target_path(self.root, invalid)
        target.parent.mkdir(parents=True)
        target.write_text("original")
        with self.assertRaises(gate.GateError):
            gate.target_path(self.root, requested)
        fresh = target.with_name("fresh.json")
        fresh.symlink_to(target)
        with self.assertRaises(gate.GateError):
            gate.target_path(self.root, requested.with_name("fresh.json"))
        self.assertEqual(target.read_text(), "original")
        broken_artifacts = target.with_name("blocked-artifacts")
        broken_artifacts.symlink_to(self.root / "absent-target", target_is_directory=True)
        with self.assertRaises(gate.GateError):
            gate.target_path(self.root, requested.with_name("blocked.json"))


if __name__ == "__main__":
    unittest.main()
