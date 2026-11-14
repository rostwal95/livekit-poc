"""Native gate boundary tests run without private settings, database or media."""

import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "p2_native_gate_test", ROOT / "local-setup/scripts/p2_native_check.py"
)
assert SPEC is not None and SPEC.loader is not None
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def encoded(value):
    return json.dumps(value).encode()


def report():
    return {
        "schema_version": 1,
        "status": "passed",
        "mode": "local_scripted_p2_native",
        "tests": 6,
        "passed": 6,
        "errors": 0,
        "failures": 0,
        "skipped": 0,
        "cleanup_complete": True,
        "duration_seconds": 50.5,
        "node_version": "24.22.2",
        "browser_version": "130.0.0.1",
        "child_commands": 24,
        "case_results": [
            {"name": name, "status": "passed", "code": "ok"} for name in GATE.CASE_NAMES
        ],
        "inference_mode": "scripted",
        "provider_calls": False,
        "schema_version_observed": 6,
        "native_inputs": 2,
        "auxiliary_inputs": 3,
        "legacy_inputs": 1,
        "normal_prepared_plans": 2,
        "auxiliary_prepared_plans": 1,
        "normal_operation_acceptances": 2,
        "auxiliary_operation_acceptances": 1,
        "playwright_tests": 1,
        "owned_child_terminations": 1,
        "blocking_graphs_observed": 1,
        "native_generation_attempts": 2,
        "native_generated_replies": 2,
        "competing_default_replies": 0,
        "populated_restore_verified": True,
        "physical_microphone_qualification_claimed": False,
        "full_playback_or_room_resumption_claimed": False,
    }


def context():
    return {
        "P2_NATIVE_DIRECTORY": "/private/synthetic",
        "P2_NATIVE_SCHEMA": "p2_native_" + "a" * 32,
        "P2_NATIVE_PG_PORT": "15432",
    }


def values():
    return {
        "POSTGRES_PASSWORD": "runtime_sentinel",
        "POSTGRES_MIGRATION_PASSWORD": "owner_sentinel",
        "POSTGRES_PORT": "15432",
        "OPENAI_API_KEY": "provider_sentinel",
    }


def node_stage(mode):
    value = {
        "schemaVersion": 1,
        "status": "passed",
        "mode": mode,
        "cleanupComplete": True,
        "nodeVersion": "24.22.2",
    }
    if mode == "serve":
        value["metrics"] = {
            "accepted": 2,
            "replayed": 1,
            "dispatched": 2,
            "active": 0,
            "intakes": 0,
            "sockets": 0,
            "handlers": 0,
            "driver": 0,
            "observerPending": 0,
        }
    if mode == "verify":
        value.update(
            {
                "schemaVersionObserved": 6,
                "nativeInputs": 2,
                "auxInputs": 3,
                "legacyInputs": 1,
                "processingIntents": 6,
                "normalPreparedPlans": 2,
                "auxPreparedPlans": 1,
                "normalOperationAcceptances": 2,
                "auxOperationAcceptances": 1,
                "nativeBindings": 3,
                "exactIdentityJoins": True,
                "legacyPreserved": True,
                "auxReplayPreserved": True,
            }
        )
    return value


def python_report():
    return {
        "schemaVersion": 1,
        "status": "passed",
        "mode": "serve",
        "cleanupComplete": True,
        "sdkClosed": True,
        "roomClosed": True,
        "httpClosed": True,
        "metrics": {
            "textStreamsSeen": 2,
            "voiceCaptures": 1,
            "voiceCommits": 2,
            "genuineFinalSnapshots": 1,
            "durableAcceptCalls": 3,
            "nativeInputsAccepted": 2,
            "nativeInputsReplayed": 1,
            "nativeInputsRejected": 0,
            "nativeGenerationAttempts": 2,
            "nativeGeneratedReplies": 2,
            "defaultReplyInvocations": 0,
            "activeReaders": 0,
            "activePrepare": 0,
            "activeIntakes": 0,
            "activeVoiceWork": 0,
            "activeReplyObservers": 0,
            "observerPending": 0,
            "observerFailures": 0,
            "observerDropped": 0,
            "sdkSessionClosed": 1,
            "sdkCloseAllocationFailed": 0,
        },
    }


class NativeGateReportTests(unittest.TestCase):
    def test_complete_source_qualified_report_passes(self):
        self.assertEqual(GATE.validated_report(encoded(report())), report())
        self.assertEqual(len(GATE.CASE_NAMES), 6)

    def test_missing_duplicate_reordered_or_failed_cases_fail(self):
        for change in ("missing", "duplicate", "reordered", "failed"):
            value = report()
            if change == "missing":
                value["case_results"].pop()
            elif change == "duplicate":
                value["case_results"][0] = value["case_results"][1]
            elif change == "reordered":
                value["case_results"].reverse()
            else:
                value["case_results"][0]["status"] = "failed"
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(encoded(value))

    def test_missing_media_default_consumer_or_restore_cannot_pass(self):
        for key, value in (
            ("native_inputs", 1),
            ("native_generated_replies", 0),
            ("competing_default_replies", 1),
            ("populated_restore_verified", False),
            ("normal_operation_acceptances", 3),
            ("playwright_tests", 0),
            ("cleanup_complete", False),
            ("skipped", 1),
        ):
            with self.subTest(key=key), self.assertRaises(GATE.GateError):
                GATE.validated_report(encoded({**report(), key: value}))

    def test_primitive_types_unknown_fields_and_expanded_claims_fail(self):
        for key, value in (
            ("tests", True),
            ("cleanup_complete", 1),
            ("schema_version_observed", True),
            ("provider_calls", 0),
            ("inference_mode", "provider_real"),
            ("physical_microphone_qualification_claimed", True),
            ("full_playback_or_room_resumption_claimed", True),
            ("private_token", "SECRET"),
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(encoded({**report(), key: value}))

    def test_time_child_and_version_budgets_fail_closed(self):
        for key, value in (
            ("duration_seconds", 0),
            ("duration_seconds", -1),
            ("duration_seconds", True),
            ("duration_seconds", 241),
            ("duration_seconds", 10**4000),
            ("duration_seconds", float("inf")),
            ("child_commands", 25),
            ("child_commands", True),
            ("node_version", "25.0.0"),
            ("browser_version", "unknown"),
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(encoded({**report(), key: value}))

    def test_duplicate_unknown_malformed_and_oversized_json_fail(self):
        raw = encoded(report())
        for value in (
            b"",
            raw[:-1],
            b"[]",
            b"\xff",
            b"x" * (GATE.MAX_REPORT_BYTES + 1),
            raw.replace(b'"schema_version": 1', b'"schema_version": 1,"\\u0073chema_version": 1'),
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(value)

    def test_all_node_stage_shapes_are_exact_and_mode_bound(self):
        for mode in GATE.NODE_MODES:
            if mode == "upgrade-interrupt":
                with self.assertRaises(GATE.GateError):
                    GATE.validated_stage(encoded(node_stage(mode)), mode)
                continue
            self.assertEqual(
                GATE.validated_stage(encoded(node_stage(mode)), mode), node_stage(mode)
            )
        for changed in (
            {"mode": "seed"},
            {"schemaVersion": True},
            {"stage": []},
            {"errorType": {}},
            {"code": []},
            {"frames": [{"file": [], "line": 42}]},
            {"cleanupComplete": 1},
            {"nativeToken": "SECRET"},
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validated_stage(encoded({**node_stage("install"), **changed}), "install")

    def test_node_serve_requires_finite_actual_cleanup_gauges(self):
        for key in ("active", "intakes", "sockets", "handlers", "driver", "observerPending"):
            value = node_stage("serve")
            value["metrics"][key] = 1
            with self.assertRaises(GATE.GateError):
                GATE.validated_stage(encoded(value), "serve")
        value = node_stage("serve")
        value["metrics"] = {"arbitrary": 1}
        with self.assertRaises(GATE.GateError):
            GATE.validated_stage(encoded(value), "serve")

    def test_node_owner_proof_rejects_missing_or_unjoined_identities(self):
        for key, value in (
            ("nativeInputs", 3),
            ("auxInputs", 1),
            ("legacyInputs", 0),
            ("nativeBindings", 2),
            ("exactIdentityJoins", False),
            ("legacyPreserved", 1),
            ("auxReplayPreserved", False),
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validated_stage(encoded({**node_stage("verify"), key: value}), "verify")

    def test_python_actual_generation_and_cleanup_are_required(self):
        self.assertEqual(GATE.validated_python(encoded(python_report())), python_report())
        for key, value in (
            ("nativeGeneratedReplies", 1),
            ("defaultReplyInvocations", 1),
            ("activeReaders", 1),
            ("activePrepare", 1),
            ("activeIntakes", 1),
            ("activeVoiceWork", 1),
            ("genuineFinalSnapshots", 2),
            ("voiceCommits", True),
        ):
            changed = python_report()
            changed["metrics"][key] = value
            with self.assertRaises(GATE.GateError):
                GATE.validated_python(encoded(changed))

    def test_python_unknown_metrics_or_failed_sdk_close_fail(self):
        changed = python_report()
        changed["metrics"]["private_body"] = 1
        with self.assertRaises(GATE.GateError):
            GATE.validated_python(encoded(changed))
        for key in ("sdkClosed", "roomClosed", "httpClosed", "cleanupComplete"):
            with self.assertRaises(GATE.GateError):
                GATE.validated_python(encoded({**python_report(), key: False}))

    def test_browser_requires_each_observation_and_zero_external_requests(self):
        original = {
            "schema_version": 1,
            "browser_version": "130.0.0.1",
            "unexpected_network_requests": 0,
            **{key: True for key in GATE.BROWSER_FLAGS},
        }
        self.assertEqual(GATE.validated_browser(encoded(original)), original)
        for key in GATE.BROWSER_FLAGS:
            for value in (False, 1):
                with self.assertRaises(GATE.GateError):
                    GATE.validated_browser(encoded({**original, key: value}))
        with self.assertRaises(GATE.GateError):
            GATE.validated_browser(encoded({**original, "unexpected_network_requests": 1}))


class NativeGateEnvironmentTests(unittest.TestCase):
    def test_each_node_mode_gets_only_its_required_database_role(self):
        for mode in GATE.NODE_MODES:
            env = GATE.child_environment(values(), context(), mode=mode)
            self.assertEqual("P2_NATIVE_OWNER_PASSWORD" in env, mode in GATE.OWNER_MODES)
            self.assertEqual("P2_NATIVE_RUNTIME_PASSWORD" in env, mode not in GATE.OWNER_MODES)
            self.assertNotIn("OPENAI_API_KEY", env)

    def test_ambient_provider_proxy_and_interpreter_selectors_are_excluded(self):
        names = {
            "OPENAI_API_KEY": "SECRET",
            "HTTPS_PROXY": "SECRET",
            "PGPASSWORD": "SECRET",
            "NODE_OPTIONS": "--inspect",
            "PYTHONPATH": "/foreign",
        }
        with patch.dict(os.environ, names):
            env = GATE.child_environment(values(), context(), mode="serve")
        self.assertFalse(set(names) & set(env))

    def test_invalid_mode_scope_context_and_missing_role_fail(self):
        with self.assertRaises(GATE.GateError):
            GATE.child_environment(values(), context(), mode="other")
        for extra in (
            {"P2_NATIVE_SCHEMA": "other_schema"},
            {"OPENAI_API_KEY": "SECRET"},
            {"P2_NATIVE_PG_PORT": "12345"},
        ):
            with self.assertRaises(GATE.GateError):
                GATE.child_environment(values(), {**context(), **extra}, mode="serve")
        with self.assertRaises(GATE.GateError):
            GATE.child_environment({}, context(), mode="serve")


class NativeGateEvidenceTests(unittest.TestCase):
    def test_exclusive_private_report_and_stale_report_precedes_setup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            path = Path(".local/validation/p2-native/final.json")
            target = GATE.target_path(root, path)
            GATE.write_json(target, report())
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with patch.object(GATE.core, "load_setup") as setup, redirect_stdout(io.StringIO()):
                self.assertNotEqual(GATE.main(["--report", str(path)], root=root), 0)
            setup.assert_not_called()
            self.assertEqual(json.loads(target.read_bytes()), report())

    def test_traversal_foreign_absolute_symlink_and_existing_paths_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            for path in (
                Path("report.json"),
                Path("/tmp/report.json"),
                Path(".local/validation/p2-native/../other.json"),
                Path(".local/validation/p2-native/token.txt"),
            ):
                with self.assertRaises(GATE.GateError):
                    GATE.target_path(root, path)
            parent = root / ".local/validation/p2-native"
            parent.mkdir(parents=True, mode=0o700)
            (parent / "link").symlink_to(root, target_is_directory=True)
            with self.assertRaises(GATE.GateError):
                GATE.target_path(root, Path(".local/validation/p2-native/link/file.json"))

    def test_snapshot_hash_recomputes_sorted_ascii_exactly(self):
        expected = hashlib.sha256(b'{"a":"\\u00e9","z":1}').hexdigest()
        self.assertEqual(GATE.snapshot_digest({"z": 1, "a": "é"}), expected)
        self.assertEqual(GATE.snapshot_digest({"a": "é", "z": 1}), expected)
        with self.assertRaises(ValueError):
            GATE.snapshot_digest({"bad": float("nan")})

    def test_endpoint_requires_exact_loopback_numeric_port_and_no_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp).resolve()
            path = directory / "endpoint.json"
            for value in (
                {"host": "remote.example", "port": 12345},
                {"host": "127.0.0.1", "port": True},
                {"host": "127.0.0.1", "port": 65536},
                {"host": "127.0.0.1", "port": 12345, "token": "SECRET"},
            ):
                path.write_bytes(encoded(value))
                with self.assertRaises(GATE.GateError):
                    GATE.endpoint(path)
            path.write_bytes(encoded({"host": "127.0.0.1", "port": 12345}))
            self.assertEqual(GATE.endpoint(path), 12345)
            link = directory / "link.json"
            link.symlink_to(path)
            with self.assertRaises(GATE.GateError):
                GATE.endpoint(link)

    def test_copy_rejects_secrets_large_files_and_linked_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp).resolve()
            source = directory / "source"
            target = directory / "saved"
            source.write_bytes(b"safe synthetic evidence")
            GATE.safe_copy(source, target, ("SECRET_SENTINEL",))
            self.assertEqual(source.read_bytes(), target.read_bytes())
            source.write_bytes(b"contains SECRET_SENTINEL")
            with self.assertRaises(GATE.GateError):
                GATE.safe_copy(source, directory / "private", ("SECRET_SENTINEL",))
            source.write_bytes(b"x" * 10)
            with self.assertRaises(GATE.GateError):
                GATE.safe_copy(source, directory / "large", (), maximum=9)
            link = directory / "link"
            link.symlink_to(source)
            with self.assertRaises(GATE.GateError):
                GATE.safe_copy(link, directory / "linked", ())

    def test_unexpected_outer_failure_never_reflects_exception_secret(self):
        async def fail(*_args, **_kwargs):
            raise RuntimeError("PRIVATE_EXCEPTION_SENTINEL")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            path = Path(".local/validation/p2-native/failure.json")
            output = io.StringIO()
            with patch.object(GATE, "run", fail), redirect_stdout(output):
                result = GATE.main(["--report", str(path)], root=root)
            self.assertNotEqual(result, 0)
            self.assertNotIn("PRIVATE_EXCEPTION_SENTINEL", output.getvalue())
            self.assertEqual(json.loads((root / path).read_bytes())["code"], "gate_failed")


class NativeExpiryProofTests(unittest.TestCase):
    def proof(self):
        return {
            "schemaVersion": 1,
            "ownerBackendPid": 11,
            "waiters": [{"pid": 12, "blockers": [11]}],
            "bindingId": "11111111-1111-4111-8111-111111111111",
            "receiptId": "22222222-2222-4222-8222-222222222222",
            "reservedReceiptId": "33333333-3333-4333-8333-333333333333",
            "expiresAt": "2026-11-11T00:00:00.200000+00:00",
            "firstWaitObservedDbClock": "2026-11-11T00:00:00.100000+00:00",
            "releaseObservedDbClock": "2026-11-11T00:00:00.300000+00:00",
            "newPrepareCalls": 0,
            "newOperationCalls": 0,
            "reservedOperationCalls": 1,
            "blockedStatus": "blocked",
            "reservedStatus": "dispatched",
        }

    def test_real_waiter_crosses_expiry_and_reserved_call_still_progresses(self):
        value = self.proof()
        self.assertEqual(GATE.validated_expiry_proof(encoded(value)), value)

    def test_already_expired_waiter_cannot_claim_crossing_while_blocked(self):
        value = self.proof()
        for first in (value["expiresAt"], value["releaseObservedDbClock"]):
            with self.assertRaises(GATE.GateError):
                GATE.validated_expiry_proof(encoded({**value, "firstWaitObservedDbClock": first}))
        with self.assertRaises(GATE.GateError):
            GATE.validated_expiry_proof(
                encoded({**value, "releaseObservedDbClock": value["firstWaitObservedDbClock"]})
            )

    def test_naive_clock_bad_uuid_duplicate_receipt_and_unknown_fields_fail(self):
        for change in (
            {"firstWaitObservedDbClock": "2026-11-11T00:00:00.1"},
            {"bindingId": "wrong"},
            {"reservedReceiptId": self.proof()["receiptId"]},
            {"secret": "PRIVATE_SENTINEL"},
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validated_expiry_proof(encoded({**self.proof(), **change}))

    def test_bool_counter_self_blocking_and_extra_waiter_cannot_pass(self):
        for change in (
            {"ownerBackendPid": True},
            {"newPrepareCalls": False},
            {"newOperationCalls": 1},
            {"reservedOperationCalls": 0},
            {"waiters": [{"pid": 11, "blockers": [11]}]},
            {"waiters": [{"pid": 12, "blockers": [11]}, {"pid": 13, "blockers": [11]}]},
            {"reservedStatus": "blocked"},
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validated_expiry_proof(encoded({**self.proof(), **change}))


class NativeCleanupTests(unittest.TestCase):
    def test_api_failure_still_attempts_independent_child_owner(self):
        import asyncio

        calls = []
        state = {}

        async def api_close():
            calls.append("api")
            raise OSError("PRIVATE_CLOSE_SENTINEL")

        async def child_close():
            calls.append("child")

        with self.assertRaises(GATE.GateError):
            asyncio.run(GATE.cleanup_actions((api_close, child_close), state, None))
        self.assertEqual(calls, ["api", "child"])
        self.assertEqual(state, {"cleanup_complete": False})

    def test_cleanup_failure_preserves_an_existing_primary(self):
        import asyncio

        calls = []
        state = {}
        primary = RuntimeError("original")

        async def first():
            calls.append(1)
            raise RuntimeError("secondary")

        async def second():
            calls.append(2)

        asyncio.run(GATE.cleanup_actions((first, second), state, primary))
        self.assertEqual(calls, [1, 2])
        self.assertFalse(state["cleanup_complete"])

    def test_cancelled_cleanup_attempts_every_owner_then_propagates(self):
        import asyncio

        calls = []
        state = {}

        async def first():
            calls.append(1)
            raise asyncio.CancelledError()

        async def second():
            calls.append(2)

        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(GATE.cleanup_actions((first, second), state, None))
        self.assertEqual(calls, [1, 2])
        self.assertFalse(state["cleanup_complete"])

    def test_vite_owner_accepts_only_its_requested_encoded_signal_exit(self):
        import sys
        import time

        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            children = GATE.Children(work, time.monotonic() + 5)
            barrier = GATE.FileBarrier(work, "service_ready")
            code = "import os,pathlib,signal,sys,time; signal.signal(signal.SIGTERM, lambda s,f: sys.exit(143)); p=pathlib.Path(sys.argv[1]); t=p/'ready.pending'; t.write_text(str(os.getpid())+'\\n'); os.link(t,p/'service_ready.reached'); time.sleep(10)"
            child = children.start(
                "vite",
                [sys.executable, "-I", "-c", code, str(work)],
                GATE.core.base_environment(),
                cwd=work,
            )
            child.wait_for_barrier(barrier, timeout=2)
            children.stop(child, deadline=time.monotonic() + 3, require_zero=False)
            children.close()
            self.assertEqual(child.returncode, 143)
            self.assertFalse(child.cleanup_failed)

    def test_already_exited_nonzero_vite_is_not_graceful_shutdown(self):
        import sys
        import time

        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            children = GATE.Children(work, time.monotonic() + 5)
            child = children.start(
                "vite",
                [sys.executable, "-I", "-c", "raise SystemExit(143)"],
                GATE.core.base_environment(),
                cwd=work,
            )
            child.wait(timeout=2)
            with self.assertRaises(GATE.GateError):
                children.stop(child, deadline=time.monotonic() + 3, require_zero=False)
            children.close()

    def test_known_cleanup_absence_exit_requires_explicit_permission(self):
        import sys
        import time

        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp).resolve()
            children = GATE.Children(work, time.monotonic() + 5)
            self.assertEqual(
                children.call(
                    "known-absent",
                    [sys.executable, "-I", "-c", "raise SystemExit(1)"],
                    GATE.core.base_environment(),
                    cwd=work,
                    accepted_codes=(0, 1),
                ),
                b"",
            )
            with self.assertRaises(GATE.GateError):
                children.call(
                    "unexpected-failure",
                    [sys.executable, "-I", "-c", "raise SystemExit(1)"],
                    GATE.core.base_environment(),
                    cwd=work,
                )
            children.close()
            self.assertTrue(all(child.returncode is not None for child in children.children))


class NativeStartupTests(unittest.TestCase):
    def observation(self):
        return {
            "schemaVersion": 1,
            "stage": "ready",
            "participantWaitBudgetMs": 60000,
            "sdkReadinessBudgetMs": 10000,
            "expectedParticipantObserved": True,
            "milestonesMs": dict(
                zip(
                    (
                        "httpBound",
                        "nodeEndpointReady",
                        "roomConnected",
                        "participantObserved",
                        "sdkStart",
                        "sdkReady",
                    ),
                    (0, 10, 20, 50, 50, 100),
                    strict=True,
                )
            ),
        }

    def test_ordered_exact_bound_participant_startup_and_partial_failure(self):
        value = self.observation()
        self.assertEqual(GATE.validate_startup(encoded(value), require_ready=True), value)
        value.update(stage="waiting_participant", expectedParticipantObserved=False)
        value["milestonesMs"].update(participantObserved=None, sdkStart=None, sdkReady=None)
        self.assertEqual(GATE.validate_startup(encoded(value)), value)
        with self.assertRaises(GATE.GateError):
            GATE.validate_startup(encoded(value), require_ready=True)

    def test_expanded_budgets_unordered_times_unknown_fields_or_false_ready_fail(self):
        for change in (
            {"participantWaitBudgetMs": 60001},
            {"sdkReadinessBudgetMs": True},
            {"stage": "PRIVATE_SENTINEL"},
            {"body": "PRIVATE_SENTINEL"},
            {"expectedParticipantObserved": False},
            {"milestonesMs": {**self.observation()["milestonesMs"], "sdkReady": 10050}},
            {"milestonesMs": {**self.observation()["milestonesMs"], "sdkStart": True}},
            {"milestonesMs": {**self.observation()["milestonesMs"], "participantObserved": 19}},
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validate_startup(encoded({**self.observation(), **change}), require_ready=True)


class NativeRuntimeParityTests(unittest.TestCase):
    def test_public_runtime_matches_current_compilation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for directory in (root / "src", root / "dist", root / "compiled/src"):
                directory.mkdir(parents=True)
            (root / "src/native.ts").write_text("export const mode = 'native';")
            for path in (root / "dist/native.js", root / "compiled/src/native.js"):
                path.write_text("export const mode = 'native';")
            proof = GATE.verify_runtime_build(root, root / "compiled")
            self.assertEqual(proof["runtimeFiles"], 1)
            self.assertTrue(proof["sourceCompiledPublicDistEqual"])
            self.assertEqual(
                proof["files"]["native.js"]["runtime_sha256"],
                hashlib.sha256((root / "dist/native.js").read_bytes()).hexdigest(),
            )
            (root / "dist/native.js").write_text("stale")
            with self.assertRaises(GATE.GateError):
                GATE.verify_runtime_build(root, root / "compiled")

    def test_extra_or_symlinked_public_runtime_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for directory in (root / "src", root / "dist", root / "compiled/src"):
                directory.mkdir(parents=True)
            (root / "src/native.ts").write_text("source")
            (root / "compiled/src/native.js").write_text("compiled")
            (root / "dist/native.js").symlink_to(root / "compiled/src/native.js")
            with self.assertRaises(GATE.GateError):
                GATE.verify_runtime_build(root, root / "compiled")
            (root / "dist/native.js").unlink()
            (root / "dist/native.js").write_text("compiled")
            (root / "dist/stale.js").write_text("stale")
            with self.assertRaises(GATE.GateError):
                GATE.verify_runtime_build(root, root / "compiled")

    def test_symlinked_runtime_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for directory in (root / "src", root / "outside", root / "compiled/src"):
                directory.mkdir(parents=True)
            (root / "src/native.ts").write_text("source")
            (root / "outside/native.js").write_text("compiled")
            (root / "compiled/src/native.js").write_text("compiled")
            (root / "dist").symlink_to(root / "outside", target_is_directory=True)
            with self.assertRaises(GATE.GateError):
                GATE.verify_runtime_build(root, root / "compiled")

    def test_extra_compiled_module_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for directory in (root / "src", root / "dist", root / "compiled/src"):
                directory.mkdir(parents=True)
            (root / "src/native.ts").write_text("source")
            for path in (root / "dist/native.js", root / "compiled/src/native.js"):
                path.write_text("compiled")
            (root / "compiled/src/extra.js").write_text("unowned")
            with self.assertRaises(GATE.GateError):
                GATE.verify_runtime_build(root, root / "compiled")

    def test_known_cli_example_is_separate_from_native_runtime_parity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for directory in (
                root / "src",
                root / "dist/examples",
                root / "examples",
                root / "compiled/src",
            ):
                directory.mkdir(parents=True)
            (root / "src/native.ts").write_text("source")
            for path in (root / "dist/native.js", root / "compiled/src/native.js"):
                path.write_text("compiled")
            (root / "examples/fake-carrier.ts").write_text("example source")
            (root / "dist/examples/fake-carrier.js").write_text("example build")
            proof = GATE.verify_runtime_build(root, root / "compiled")
            self.assertEqual(proof["runtimeFiles"], 1)
            self.assertFalse(
                proof["ancillary"]["examples/fake-carrier.js"]["compiledParityClaimed"]
            )
            self.assertFalse(
                proof["ancillary"]["examples/fake-carrier.js"]["loadedByNativeFixture"]
            )

    def operations_tree(self, root):
        for directory in (
            root / "src",
            root / "dist/examples",
            root / "examples",
            root / "compiled/src",
            root / "compiled/examples",
        ):
            directory.mkdir(parents=True)
        (root / "src/native.ts").write_text("native source")
        for path in (root / "dist/native.js", root / "compiled/src/native.js"):
            path.write_text("native compiled")
        (root / "examples/operations-lab.ts").write_text("declared operations source")
        for path in (
            root / "dist/examples/operations-lab.js",
            root / "compiled/examples/operations-lab.js",
        ):
            path.write_text("same current operations compilation")

    def test_operations_example_requires_actual_current_compilation_parity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.operations_tree(root)
            proof = GATE.verify_runtime_build(root, root / "compiled")
            extra = proof["ancillary"]["examples/operations-lab.js"]
            self.assertTrue(extra["compiledParityClaimed"])
            self.assertFalse(extra["loadedByNativeFixture"])
            self.assertEqual(proof["runtimeFiles"], 1)
            self.assertEqual(
                extra["runtime_sha256"],
                hashlib.sha256(
                    (root / "compiled/examples/operations-lab.js").read_bytes()
                ).hexdigest(),
            )

    def test_operations_stale_or_missing_compilation_is_not_an_ancillary_exception(self):
        for missing in (False, True):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.operations_tree(root)
                expected = root / "compiled/examples/operations-lab.js"
                if missing:
                    expected.unlink()
                else:
                    expected.write_text("different compilation")
                with self.assertRaises(GATE.GateError):
                    GATE.verify_runtime_build(root, root / "compiled")

    def test_unknown_operations_like_example_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.operations_tree(root)
            (root / "dist/examples/operations-lab-debug.js").write_text("undeclared extra")
            with self.assertRaises(GATE.GateError):
                GATE.verify_runtime_build(root, root / "compiled")

    def test_operations_example_symlinks_are_rejected_at_every_bound_path(self):
        for relative in (
            "examples/operations-lab.ts",
            "dist/examples/operations-lab.js",
            "compiled/examples/operations-lab.js",
        ):
            with self.subTest(path=relative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.operations_tree(root)
                target = root / relative
                outside = root / "other"
                outside.write_bytes(target.read_bytes())
                target.unlink()
                target.symlink_to(outside)
                with self.assertRaises(GATE.GateError):
                    GATE.verify_runtime_build(root, root / "compiled")

    def starter_tree(self, root):
        self.operations_tree(root)
        names = [
            "standalone-channel",
            "standalone/config",
            "standalone/receipt-store",
            "standalone/external-http",
            "standalone/application",
        ]
        for name in names:
            for prefix, suffix in (
                ("examples", ".ts"),
                ("dist/examples", ".js"),
                ("compiled/examples", ".js"),
            ):
                target = root / prefix / (name + suffix)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("source" if suffix == ".ts" else "compiled " + name)
        return names

    def test_starter_bundle_requires_all_five_current_compilations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            names = self.starter_tree(root)
            proof = GATE.verify_runtime_build(root, root / "compiled")
            self.assertEqual(proof["runtimeFiles"], 1)
            for name in names:
                item = proof["ancillary"]["examples/" + name + ".js"]
                self.assertTrue(item["compiledParityClaimed"])
                self.assertFalse(item["loadedByNativeFixture"])
                self.assertEqual(
                    item["runtime_sha256"],
                    hashlib.sha256(
                        (root / "compiled/examples" / (name + ".js")).read_bytes()
                    ).hexdigest(),
                )

    def test_starter_missing_or_changed_member_is_rejected(self):
        for name in (
            "standalone-channel",
            "standalone/config",
            "standalone/receipt-store",
            "standalone/external-http",
            "standalone/application",
        ):
            for missing in (False, True):
                with (
                    self.subTest(name=name, missing=missing),
                    tempfile.TemporaryDirectory() as temporary,
                ):
                    root = Path(temporary)
                    self.starter_tree(root)
                    target = root / "compiled/examples" / (name + ".js")
                    if missing:
                        target.unlink()
                    else:
                        target.write_text("stale or changed")
                    with self.assertRaises(GATE.GateError):
                        GATE.verify_runtime_build(root, root / "compiled")

    def test_starter_unknown_extra_is_rejected_in_public_or_compiled_bundle(self):
        for base in (
            "dist/examples/standalone",
            "compiled/examples/standalone",
            "compiled/examples",
        ):
            with self.subTest(base=base), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.starter_tree(root)
                (
                    root
                    / base
                    / ("standalone-debug.js" if base == "compiled/examples" else "debug.js")
                ).write_text("unknown")
                with self.assertRaises(GATE.GateError):
                    GATE.verify_runtime_build(root, root / "compiled")

    def test_starter_bundle_symlink_parent_or_member_is_rejected(self):
        for relative in (
            "examples/standalone",
            "dist/examples/standalone",
            "compiled/examples/standalone",
            "compiled/examples/standalone-channel.js",
        ):
            with self.subTest(path=relative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.starter_tree(root)
                target = root / relative
                outside = root / "other"
                target.rename(outside)
                target.symlink_to(outside, target_is_directory=outside.is_dir())
                with self.assertRaises(GATE.GateError):
                    GATE.verify_runtime_build(root, root / "compiled")


class NativeFailureContextTests(unittest.TestCase):
    def context(self):
        return {
            "schemaVersion": 1,
            "status": "failed",
            "mode": "serve",
            "stage": "sdk_start",
            "errorType": "NativeError",
            "code": "closed",
            "frames": [{"file": "native.py", "line": 42}],
        }

    def retain(self, work, artifacts):
        children = GATE.Children(work, 1)
        GATE.retain_failure_context(
            work, artifacts, children, ("PRIVATE_SENTINEL",), GATE.GateError("child_failed")
        )

    def test_exact_safe_python_context_is_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            artifacts = work / "artifacts"
            artifacts.mkdir()
            (work / "python-failure-context.json").write_bytes(encoded(self.context()))
            self.retain(work, artifacts)
            self.assertEqual(
                json.loads((artifacts / "python-failure-context.json").read_bytes()), self.context()
            )

    def test_partial_producer_metrics_remain_failed_gate_evidence(self):
        value = {
            "schemaVersion": 1,
            "status": "passed",
            "mode": "serve",
            "cleanupComplete": True,
            "sdkClosed": True,
            "roomClosed": True,
            "httpClosed": True,
            "metrics": dict.fromkeys(GATE.PYTHON_METRICS, 0),
        }
        self.assertEqual(GATE.validate_partial_terminal(encoded(value), "python"), value)
        for change in (
            {"body": "PRIVATE_SENTINEL"},
            {"metrics": {**value["metrics"], "durableAcceptCalls": True}},
            {"sdkClosed": "true"},
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validate_partial_terminal(encoded({**value, **change}), "python")

    def test_browser_context_has_only_finite_stages_and_counts(self):
        value = {
            "schemaVersion": 1,
            "stage": "native_ready",
            "connection": "Connected",
            "pageErrors": 0,
            "inputStatuses": [],
            "counts": dict.fromkeys(
                ("sent", "accepted", "replayed", "rejected", "unknown", "invalid_ack"), 0
            ),
        }
        self.assertEqual(GATE.validate_browser_context(encoded(value)), value)
        with self.assertRaises(GATE.GateError):
            GATE.validate_browser_context(encoded(value), require_complete=True)
        completed = {**value, "stage": "complete", "connection": "Disconnected"}
        self.assertEqual(
            GATE.validate_browser_context(encoded(completed), require_complete=True), completed
        )
        with self.assertRaises(GATE.GateError):
            GATE.validate_browser_context(
                encoded({**completed, "pageErrors": 1}), require_complete=True
            )
        for change in (
            {"stage": "PRIVATE_SENTINEL"},
            {"connection": []},
            {"pageErrors": True},
            {"message": "PRIVATE_SENTINEL"},
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validate_browser_context(encoded({**value, **change}))

    def test_partial_browser_progress_is_safe_and_cannot_expand_schema(self):
        for private in (False, True):
            with tempfile.TemporaryDirectory() as temporary:
                work = Path(temporary)
                (work / "browser-report").mkdir()
                artifacts = work / "artifacts"
                artifacts.mkdir()
                observation = {
                    "schema_version": 1,
                    "browser_version": "130.0.1",
                    "unexpected_network_requests": 0,
                    "ready": False,
                }
                if private:
                    observation["message"] = "PRIVATE_SENTINEL"
                (work / "browser-report/native-browser-observations.json").write_bytes(
                    encoded(observation)
                )
                if private:
                    with self.assertRaises(GATE.GateError):
                        self.retain(work, artifacts)
                    self.assertFalse((artifacts / "failed-browser-observations.json").exists())
                else:
                    self.retain(work, artifacts)
                    self.assertEqual(
                        json.loads((artifacts / "failed-browser-observations.json").read_bytes()),
                        observation,
                    )

    def test_oversized_browser_diagnostics_reject_before_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            (work / "browser-report").mkdir()
            artifacts = work / "artifacts"
            artifacts.mkdir()
            (work / "browser-report/native-browser-observations.json").write_bytes(b"x" * 4097)
            with (
                patch.object(Path, "read_bytes", side_effect=AssertionError("must not allocate")),
                self.assertRaises(GATE.GateError),
            ):
                self.retain(work, artifacts)

    def test_failed_diagnostics_and_fallback_sink_preserve_cleanup_control(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            children = GATE.Children(work, 1)
            with (
                patch.object(
                    GATE, "retain_failure_context", side_effect=OSError("PRIVATE_SENTINEL")
                ) as retain,
                patch.object(
                    GATE, "write_json", side_effect=OSError("PRIVATE_SENTINEL")
                ) as fallback,
            ):
                self.assertFalse(
                    GATE.retain_failure_safely(work, work, children, (), RuntimeError("primary"))
                )
            retain.assert_called_once()
            fallback.assert_called_once()

    def test_unknown_and_reflected_diagnostics_are_rejected(self):
        for change in (
            {"message": "PRIVATE_SENTINEL"},
            {"stage": "PRIVATE_SENTINEL"},
            {"frames": [{"file": "/secret/private.py", "line": 42}]},
            {"schemaVersion": True},
            {"stage": []},
            {"errorType": {}},
            {"code": []},
            {"frames": [{"file": [], "line": 42}]},
            {"frames": [{"file": "native.py", "line": True}]},
        ):
            with tempfile.TemporaryDirectory() as temporary:
                work = Path(temporary)
                artifacts = work / "artifacts"
                artifacts.mkdir()
                (work / "python-failure-context.json").write_bytes(
                    encoded({**self.context(), **change})
                )
                with self.assertRaises(GATE.GateError):
                    self.retain(work, artifacts)
                self.assertFalse((artifacts / "python-failure-context.json").exists())


if __name__ == "__main__":
    unittest.main()
