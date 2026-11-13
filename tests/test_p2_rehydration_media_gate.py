"""Closed media evidence, source-safety and incomplete-cleanup negatives; no PG/RTC."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local-setup/scripts"))
import p2_rehydration_media_check as gate


def encoded(value: object) -> bytes:
    return json.dumps(value, allow_nan=False).encode()


def browser(f: dict) -> dict:
    inputs, responses = [], []
    for key, channel, sequence in (
        ("voice", "voice_transcript", "1"),
        ("text", "web_chat", "2"),
        ("newText", "web_chat", "4"),
    ):
        item = {
            "inputId": f["ids"][key],
            "channel": channel,
            "status": "accepted",
            "receiptId": str(uuid4()),
            "operationKey": str(uuid4()),
            "acceptanceSequence": sequence,
        }
        inputs.append(item)
        responses.append(
            {
                "responseId": str(uuid4()),
                "generationId": str(uuid4()),
                "inputId": item["inputId"],
                "operationKey": item["operationKey"],
                "sdkSpeechId": "speech-" + str(uuid4()),
                "observationCount": 2,
                "generated_observed": True,
                "sdk_state": "completed",
                "browser_state": "unknown",
                "conflicted": False,
                "observed_audio_ms": 500,
                "sampled_audio_ms": 600,
            }
        )
    return {
        "schemaVersion": 1,
        "status": "passed",
        "mode": "local_scripted_p2_rehydration_browser",
        "groups": list(gate.CASE_NAMES),
        "smsKnown": True,
        "refreshFailureRetained": True,
        "actualBrowserAudio": True,
        "physicalHearingClaimed": False,
        "readOnlyLoadGeneratedReplies": 0,
        "cleanupComplete": True,
        "pageErrors": 0,
        "unexpectedNetworkRequests": 0,
        "sessions": {
            "A": {
                "bindingId": f["bindings"]["A"]["bindingId"],
                "contextId": str(uuid4()),
                "caseRevision": "1",
                "inputs": inputs[:2],
                "responses": responses[:2],
            },
            "B": {
                "bindingId": f["bindings"]["B"]["bindingId"],
                "contextId": str(uuid4()),
                "caseRevision": "2",
                "input": inputs[2],
                "response": responses[2],
                "historyReceipts": [i["receiptId"] for i in inputs[:2]] + [str(uuid4())],
                "historyChannels": ["voice_transcript", "web_chat", "sms"],
                "historicalResponses": [
                    {
                        "responseId": r["responseId"],
                        "bindingId": f["bindings"]["A"]["bindingId"],
                        "generationId": r["generationId"],
                        "sdkSpeechId": r["sdkSpeechId"],
                        "sdkState": "completed",
                        "browserState": "unknown",
                        "historical": True,
                    }
                    for r in responses[:2]
                ],
            },
        },
    }


def report() -> dict:
    return {
        "schema_version": 1,
        "status": "passed",
        "mode": gate.MODE,
        "tests": 3,
        "passed": 3,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "cleanup_complete": True,
        "case_results": [{"name": n, "status": "passed", "code": "ok"} for n in gate.CASE_NAMES],
        "schema_version_observed": 7,
        "native_inputs": 3,
        "fake_sms_inputs": 1,
        "operation_acceptances": 4,
        "responses": 3,
        "sdk_observations": 6,
        "browser_observations": 0,
        "playwright_tests": 1,
        "provider_calls": False,
        "physical_hearing_claimed": False,
        "human_acknowledgement_claimed": False,
        "read_only_load_generated_replies": 0,
        "dormant_rooms_observed": 0,
        "node_version": "24.22.2",
        "duration_seconds": 30,
        "child_commands": 10,
        "retained_index_sha256": "a" * 64,
        "proofs": {
            k: {"bytes": 20, "sha256": "a" * 64}
            for k in ("browser", "python", "node", "sdk_source", "owner", "dormancy", "fixture")
        },
    }


def failure_context() -> dict:
    return {
        "schemaVersion": 1,
        "stage": "sms",
        "groups": list(gate.CASE_NAMES)[:1],
        "pageErrors": 0,
        "unexpectedNetworkRequests": 0,
        "connection": "Disconnected",
        "ready": False,
        "phase": "ended",
        "caseRevision": "1",
        "inputStates": ["accepted"],
        "responseStates": [
            {
                "sdkState": "completed",
                "browserState": "unknown",
                "generated": True,
                "observedAudioMs": 500,
            }
        ],
    }


class MediaEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.f = gate.storage.fixture("a" * 32)
        self.browser = browser(self.f)

    def test_valid_three_groups_are_distinct_from_one_playwright_test(self) -> None:
        self.assertEqual(gate.validated_browser(encoded(self.browser), self.f), self.browser)
        self.assertEqual(gate.validated_report(encoded(report()))["playwright_tests"], 1)

    def test_no_pcm_is_not_actual_browser_audio(self) -> None:
        for value in (0, 100, True, -1):
            altered = copy.deepcopy(self.browser)
            altered["sessions"]["B"]["response"]["observed_audio_ms"] = value
            with self.subTest(value=value), self.assertRaises(gate.GateError):
                gate.validated_browser(encoded(altered), self.f)

    def test_observed_frames_cannot_exceed_sampled_frames(self) -> None:
        self.browser["sessions"]["B"]["response"]["sampled_audio_ms"] = 499
        with self.assertRaises(gate.GateError):
            gate.validated_browser(encoded(self.browser), self.f)

    def test_repeated_old_response_does_not_prove_two_original_responses(self) -> None:
        b = self.browser["sessions"]["B"]
        b["historicalResponses"][1] = copy.deepcopy(b["historicalResponses"][0])
        with self.assertRaises(gate.GateError):
            gate.validated_browser(encoded(self.browser), self.f)

    def test_historical_response_cannot_be_rebound_to_room_b(self) -> None:
        b = self.browser["sessions"]["B"]
        b["historicalResponses"][0]["bindingId"] = b["bindingId"]
        with self.assertRaises(gate.GateError):
            gate.validated_browser(encoded(self.browser), self.f)

    def test_malformed_history_members_have_only_fixed_error(self) -> None:
        for field, value in (
            ("historyReceipts", [{}, [], None]),
            ("historyChannels", ["voice_transcript", "web_chat", "sms", "sms"]),
            ("historyChannels", [{}, "web_chat", "sms"]),
        ):
            altered = copy.deepcopy(self.browser)
            altered["sessions"]["B"][field] = value
            with self.subTest(field=field), self.assertRaises(gate.GateError):
                gate.validated_browser(encoded(altered), self.f)
        self.browser["sessions"]["B"]["historicalResponses"][0]["responseId"] = []
        with self.assertRaises(gate.GateError):
            gate.validated_browser(encoded(self.browser), self.f)

    def test_response_generation_and_speech_are_each_unique(self) -> None:
        for field in ("responseId", "generationId", "sdkSpeechId"):
            altered = copy.deepcopy(self.browser)
            altered["sessions"]["B"]["response"][field] = altered["sessions"]["A"]["responses"][0][
                field
            ]
            with self.subTest(field=field), self.assertRaises(gate.GateError):
                gate.validated_browser(encoded(altered), self.f)

    def test_boolean_counts_and_hearing_claims_are_not_accepted(self) -> None:
        for field, value in (
            ("pageErrors", False),
            ("physicalHearingClaimed", True),
            ("readOnlyLoadGeneratedReplies", False),
        ):
            altered = copy.deepcopy(self.browser)
            altered[field] = value
            with self.subTest(field=field), self.assertRaises(gate.GateError):
                gate.validated_browser(encoded(altered), self.f)

    def test_exact_ten_children_and_seven_named_proofs_are_required(self) -> None:
        for field, value in (
            ("child_commands", 1),
            ("child_commands", 32),
            ("child_commands", True),
            ("proofs", {}),
            ("retained_index_sha256", None),
        ):
            altered = report()
            altered[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(gate.GateError):
                gate.validated_report(encoded(altered))

    def test_missing_or_extra_named_proof_is_rejected(self) -> None:
        for name in ("missing", "extra"):
            altered = report()
            if name == "missing":
                del altered["proofs"]["sdk_source"]
            else:
                altered["proofs"]["invented"] = {"bytes": 1, "sha256": "b" * 64}
            with self.subTest(name=name), self.assertRaises(gate.GateError):
                gate.validated_report(encoded(altered))

    def test_report_strict_counts_bounds_and_proof_primitives(self) -> None:
        for field, value in (
            ("tests", True),
            ("duration_seconds", 241),
            ("retained_index_sha256", "../secret"),
        ):
            altered = report()
            altered[field] = value
            with self.subTest(field=field), self.assertRaises(gate.GateError):
                gate.validated_report(encoded(altered))
        altered = report()
        altered["proofs"]["owner"]["bytes"] = True
        with self.assertRaises(gate.GateError):
            gate.validated_report(encoded(altered))

    def test_valid_actual_connection_states_are_retained_on_failure(self) -> None:
        for state in (
            "Disconnected",
            "Joining",
            "Connected",
            "Reconnecting",
            "Closing",
            "Cleanup incomplete",
        ):
            value = failure_context()
            value["connection"] = state
            self.assertEqual(gate.validated_browser_context(encoded(value))["connection"], state)

    def test_malformed_failure_container_fields_never_escape_as_typeerror(self) -> None:
        for field in ("connection", "phase", "inputStates"):
            value = failure_context()
            value[field] = [{}] if field == "inputStates" else {}
            with self.subTest(field=field), self.assertRaises(gate.GateError):
                gate.validated_browser_context(encoded(value))
        for field in ("sdkState", "browserState"):
            value = failure_context()
            value["responseStates"][0][field] = []
            with self.subTest(field=field), self.assertRaises(gate.GateError):
                gate.validated_browser_context(encoded(value))

    def test_preflight_diagnostics_never_retain_exception_message_or_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            cleanup = {"cleanup_complete": False}
            gate.retain_gate_failure(
                directory, ValueError("SENTINEL_PRIVATE_BODY_AND_PATH"), cleanup
            )
            raw = (directory / "gate-failure-context.json").read_bytes()
            self.assertNotIn(b"SENTINEL", raw)
            value = json.loads(raw)
            self.assertEqual(value["stage"], "preflight")
            self.assertEqual(value["errorType"], "ValueError")
            self.assertFalse(value["cleanupComplete"])

    def test_known_private_proof_error_is_retained_without_arbitrary_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            cleanup = {"cleanup_complete": False}
            gate.retain_gate_failure(directory, gate.GateError("unsafe_proof_file"), cleanup)
            self.assertEqual(
                json.loads((directory / "gate-failure-context.json").read_bytes())["code"],
                "unsafe_proof_file",
            )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            gate.retain_gate_failure(directory, gate.GateError("SENTINEL_PRIVATE_CODE"), cleanup)
            raw = (directory / "gate-failure-context.json").read_bytes()
            self.assertNotIn(b"SENTINEL", raw)
            self.assertEqual(json.loads(raw)["code"], "gate_failed")

    def test_child_exec_creates_private_third_party_files_under_permissive_parent_umask(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            children = gate.Children(directory, time.monotonic() + 5)
            program = "from pathlib import Path;import os;Path('third-party.json').write_text(str(os.getpid()));Path('third-party').mkdir();Path('third-party/screenshot.bin').write_bytes(b'synthetic')"
            previous_mask = os.umask(0o022)
            try:
                child = children.start(
                    "default-writer",
                    [sys.executable, "-I", "-c", program],
                    gate.core.base_environment(),
                    cwd=directory,
                )
            finally:
                os.umask(previous_mask)
            try:
                children.finish(child)
                self.assertEqual((directory / "third-party.json").stat().st_mode & 0o777, 0o600)
                self.assertEqual((directory / "third-party").stat().st_mode & 0o777, 0o700)
                self.assertEqual(
                    (directory / "third-party/screenshot.bin").stat().st_mode & 0o777, 0o600
                )
                self.assertEqual(
                    gate.previous.bounded_read(directory / "third-party.json", maximum=64),
                    str(child.pid).encode(),
                )
                self.assertEqual(children.count, 1)
            finally:
                children.close()

    def test_failure_code_and_stage_cannot_carry_private_text(self) -> None:
        value = {
            "schemaVersion": 1,
            "status": "failed",
            "mode": "rehydration-serve",
            "stage": "sdk_start",
            "errorType": "NativeError",
            "code": "dependency_unavailable",
            "cleanupComplete": False,
        }
        self.assertEqual(gate.validated_python_failure(encoded(value)), value)
        for field in ("code", "stage", "errorType"):
            altered = {**value, field: "SENTINEL_PRIVATE_BODY"}
            with self.subTest(field=field), self.assertRaises(gate.GateError):
                gate.validated_python_failure(encoded(altered))

    def test_sms_requires_original_fixed_identity_and_revision(self) -> None:
        value = {
            "schemaVersion": 1,
            "status": "passed",
            "smsAccepted": 1,
            "caseRevision": "2",
            "receiptId": str(uuid4()),
            "operationKey": str(uuid4()),
            "eventId": self.f["ids"]["sms"],
        }
        self.assertEqual(gate.validated_sms(encoded(value), self.f), value)
        for field, changed in (
            ("eventId", str(uuid4())),
            ("caseRevision", "1"),
            ("smsAccepted", True),
        ):
            with self.subTest(field=field), self.assertRaises(gate.GateError):
                gate.validated_sms(encoded({**value, field: changed}), self.f)

    def test_ordered_history_channels_are_joined_to_original_sql_wire(self) -> None:
        b = self.browser["sessions"]["B"]
        rows = {
            receipt: {"wire_json": json.dumps({"channel": channel})}
            for receipt, channel in zip(b["historyReceipts"], b["historyChannels"], strict=True)
        }
        gate.validate_history_channels(self.browser, rows)
        b["historyChannels"][0], b["historyChannels"][1] = (
            b["historyChannels"][1],
            b["historyChannels"][0],
        )
        with self.assertRaises(gate.GateError):
            gate.validate_history_channels(self.browser, rows)

    def test_report_path_cannot_escape_or_replace_existing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for path in (
                Path("../outside.json"),
                root / "absolute.json",
                Path(".local/validation/p2-rehydration-media/../escape.json"),
            ):
                with self.subTest(path=path), self.assertRaises(gate.GateError):
                    gate.target_path(root, path)
            path = Path(".local/validation/p2-rehydration-media/fresh.json")
            target = gate.target_path(root, path)
            target.write_text("original")
            with self.assertRaises(gate.GateError):
                gate.target_path(root, path)
            self.assertEqual(target.read_text(), "original")

    def test_physical_retained_manifest_rejects_tamper_and_unindexed_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "proof.json").write_text("{}")
            gate.storage.retained_index(directory)
            sha = hashlib.sha256((directory / "retained-index.json").read_bytes()).hexdigest()
            gate.storage.validate_retained_index(directory, sha)
            (directory / "proof.json").write_text('{"changed":true}')
            with self.assertRaises(gate.GateError):
                gate.storage.validate_retained_index(directory, sha)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "proof.json").write_text("{}")
            gate.storage.retained_index(directory)
            sha = hashlib.sha256((directory / "retained-index.json").read_bytes()).hexdigest()
            (directory / "unexpected").write_text("extra")
            (directory / "unexpected").chmod(0o600)
            with self.assertRaises(gate.GateError):
                gate.storage.validate_retained_index(directory, sha)

    def test_public_source_symlinks_and_hardlinks_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.py"
            path.write_text("safe source")
            path.chmod(0o644)
            self.assertEqual(gate.storage.source_bytes(path), b"safe source")
            link = path.with_name("link.py")
            link.symlink_to(path)
            with self.assertRaises(gate.GateError):
                gate.storage.source_bytes(link)
            hardlink = path.with_name("hardlink.py")
            os.link(path, hardlink)
            with self.assertRaises(gate.GateError):
                gate.storage.source_bytes(hardlink)


class MediaOwnedWorkTests(unittest.TestCase):
    def test_incomplete_cleanup_retains_private_owned_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            scratch = root / "scratch"
            scratch.mkdir()
            work = Path(tempfile.mkdtemp(prefix="run-", dir=scratch))
            artifacts = root / "artifacts"
            artifacts.mkdir()
            (work / "still-owned").write_text("synthetic")
            cleanup = {"cleanup_complete": False}
            gate.finish_owned_work(
                root,
                artifacts,
                work,
                scratch,
                "schema",
                "case",
                time.monotonic() + 1,
                cleanup,
                gate.GateError("original"),
            )
            self.assertTrue(work.exists())
            retained = json.loads((artifacts / "owned-work-retained.json").read_text())
            self.assertFalse(retained["cleanupComplete"])

    def test_secondary_cleanup_and_diagnostic_failure_cannot_replace_primary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            cleanup = {"cleanup_complete": True}
            with (
                patch.object(gate.storage, "remove_owned_work", side_effect=OSError("private")),
                patch.object(gate.native, "write_json", side_effect=OSError("private")),
            ):
                gate.finish_owned_work(
                    root,
                    root,
                    root / "run-work",
                    root,
                    "schema",
                    "case",
                    time.monotonic() + 1,
                    cleanup,
                    gate.GateError("original"),
                )
            self.assertFalse(cleanup["cleanup_complete"])

    def test_cleanup_failure_without_primary_fails_instead_of_passing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            cleanup = {"cleanup_complete": True}
            with (
                patch.object(gate.storage, "remove_owned_work", side_effect=OSError("private")),
                self.assertRaises(gate.GateError),
            ):
                gate.finish_owned_work(
                    root,
                    root,
                    root / "run-work",
                    root,
                    "schema",
                    "case",
                    time.monotonic() + 1,
                    cleanup,
                    None,
                )
            self.assertFalse(cleanup["cleanup_complete"])

    def test_completed_cleanup_removes_only_marked_private_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            scratch = root / "scratch"
            scratch.mkdir()
            work = Path(tempfile.mkdtemp(prefix="run-", dir=scratch))
            gate.native.write_json(
                work / "rehydration-owned-work.json", {"schemaVersion": 1, "schema": "schema"}
            )
            cleanup = {"cleanup_complete": True}
            gate.finish_owned_work(
                root, root, work, scratch, "schema", "case", time.monotonic() + 1, cleanup, None
            )
            self.assertFalse(work.exists())
            self.assertTrue(cleanup["cleanup_complete"])


class MediaSchemaDependencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_unreaped_child_blocks_dependent_ddl_after_failed_close(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            children = gate.Children(work, time.monotonic() + 5)
            child = children.start(
                "held",
                [sys.executable, "-I", "-c", "import time; time.sleep(30)"],
                gate.core.base_environment(),
                cwd=work,
            )
            calls = []

            async def stage(mode: str, deadline: float | None) -> dict:
                calls.append((mode, deadline))
                return {}

            try:
                with (
                    patch.object(child, "close", side_effect=OSError("synthetic close failure")),
                    self.assertRaises(gate.GateError),
                ):
                    await gate.cleanup_schema_if_settled(
                        children, True, stage, time.monotonic() + 2
                    )
                self.assertIsNone(child.returncode)
                self.assertEqual(calls, [])
                child.close()
                self.assertIsNotNone(child.returncode)
                await gate.cleanup_schema_if_settled(children, True, stage, time.monotonic() + 2)
                self.assertEqual([mode for mode, _ in calls], ["media-cleanup"])
            finally:
                child.close()

    async def test_cancellation_of_one_close_still_attempts_other_owned_children_and_no_ddl(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            children = gate.Children(work, time.monotonic() + 5)
            first = children.start(
                "first",
                [sys.executable, "-I", "-c", "pass"],
                gate.core.base_environment(),
                cwd=work,
            )
            second = children.start(
                "second",
                [sys.executable, "-I", "-c", "pass"],
                gate.core.base_environment(),
                cwd=work,
            )
            calls = []

            async def stage(mode: str, deadline: float | None) -> dict:
                calls.append(mode)
                return {}

            real_first_close = first.close
            try:
                with (
                    patch.object(second, "close", side_effect=asyncio.CancelledError()),
                    patch.object(first, "close", wraps=real_first_close) as observed,
                    self.assertRaises(gate.GateError),
                ):
                    await gate.cleanup_schema_if_settled(
                        children, True, stage, time.monotonic() + 2
                    )
                observed.assert_called_once()
                self.assertEqual(calls, [])
            finally:
                first.close()
                second.close()


if __name__ == "__main__":
    unittest.main()
