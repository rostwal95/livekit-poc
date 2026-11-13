"""Offline negative checks for action-race fixture protocol, never authority mocks."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import stat
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from delegation_reliability.contracts import (
    Attempt,
    ContractError,
    encode_request,
    match_result,
    parse_request,
)

ROOT = Path(__file__).resolve().parents[3]


def load_fixture() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "p3_action_schedule_tests",
        ROOT / "projects/delegation-reliability/tests/pg_action_race_cases.py",
    )
    assert spec is not None and spec.loader is not None
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


FIXTURE = load_fixture()


class ActionScheduleTests(unittest.TestCase):
    def test_inventory_is_closed_and_finite(self) -> None:
        self.assertEqual(len(FIXTURE.CASES), 16)
        self.assertEqual(len(set(FIXTURE.CASES)), 16)
        self.assertEqual(len(FIXTURE.MODES), 31)
        self.assertEqual(len(set(FIXTURE.MODES)), 31)
        self.assertEqual(
            set(FIXTURE.OWNER_MODES),
            {"install", "lock-b-first", "lock-a-first", "owner-check", "cleanup"},
        )

    def test_runtime_cannot_receive_owner_password_or_ambient_provider_selector(self) -> None:
        valid = {
            "P3_RACE_WORK_SCHEMA": "p1_work_actionrace_" + uuid4().hex,
            "P3_RACE_CASE_SCHEMA": "p3_completion_" + uuid4().hex,
            "P3_RACE_DIRECTORY": "/tmp",
            "P3_RACE_PG_PORT": "5432",
            "P3_RACE_RUNTIME_PASSWORD": "synthetic",
            "P3_RACE_TOKEN": "synthetic",
        }
        with patch.dict(os.environ, valid, clear=True):
            FIXTURE.environment("prepare-claim")
        for name in (
            "P3_RACE_OWNER_PASSWORD",
            "OPENAI_API_KEY",
            "PYTHONPATH",
            "DATABASE_URL",
            "HTTPS_PROXY",
        ):
            with (
                self.subTest(name=name),
                patch.dict(os.environ, {**valid, name: "inert-sentinel"}, clear=True),
                self.assertRaises(AssertionError),
            ):
                FIXTURE.environment("prepare-claim")

    def test_owner_cannot_receive_runtime_credentials(self) -> None:
        valid = {
            "P3_RACE_WORK_SCHEMA": "p1_work_actionrace_" + uuid4().hex,
            "P3_RACE_CASE_SCHEMA": "p3_completion_" + uuid4().hex,
            "P3_RACE_DIRECTORY": "/tmp",
            "P3_RACE_PG_PORT": "5432",
            "P3_RACE_OWNER_PASSWORD": "synthetic",
        }
        with patch.dict(os.environ, valid, clear=True):
            FIXTURE.environment("install")
        with (
            patch.dict(os.environ, {**valid, "P3_RACE_TOKEN": "synthetic"}, clear=True),
            self.assertRaises(AssertionError),
        ):
            FIXTURE.environment("install")

    def test_immutable_fixture_save_refuses_overwrite_and_symlink(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(os.environ, {"P3_RACE_DIRECTORY": temporary}),
        ):
            FIXTURE.save("original.json", {"scope": "original"})
            with self.assertRaises(FileExistsError):
                FIXTURE.save("original.json", {"scope": "changed"})
            path = Path(temporary) / "original.json"
            self.assertEqual(json.loads(path.read_text()), {"scope": "original"})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            (Path(temporary) / "redirect.json").symlink_to(path)
            with self.assertRaises(FileExistsError):
                FIXTURE.save("redirect.json", {"scope": "changed"})

    def test_marker_is_complete_owned_exclusive_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "guard.reached"
            FIXTURE.HELPER.marker(path)
            self.assertEqual(path.read_text(), str(os.getpid()) + "\n")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                FIXTURE.HELPER.marker(path)
            self.assertFalse(list(Path(temporary).glob("*.pending")))

    def test_strict_scripted_result_preserves_issued_identity_and_evidence(self) -> None:
        original = FIXTURE.request("b_first_b", 4)
        value = replace(original, attempt=Attempt("attempt_" + uuid4().hex, 1))
        result = asyncio.run(FIXTURE.LocalPolicy().invoke_observed(value))
        match_result(value, result.result, observed_at_ms=result.observed_at_ms)
        self.assertEqual(value.case_id, "case_b_first")
        self.assertEqual(result.result.scope, value.scope)
        self.assertEqual(result.result.request_revision, 4)
        self.assertEqual(value.evidence[0].sha256, FIXTURE.evidence()[0].reference.sha256)
        changed = replace(result.result, attempt_id="attempt_foreign")
        with self.assertRaises(ContractError):
            match_result(value, changed, observed_at_ms=result.observed_at_ms)

    def test_request_producer_recomputes_binding_and_rejects_malformed_input(self) -> None:
        value = FIXTURE.request("precommit", 2)
        self.assertEqual(parse_request(encode_request(value)), value)
        raw = json.loads(encode_request(value))
        raw["case_id"] = "case_other"
        with self.assertRaises(ContractError):
            parse_request(json.dumps(raw).encode())

    def test_fixture_install_preserves_public_authority_markers(self) -> None:
        from continuity_lab.work_api import PostgresSettings

        settings = PostgresSettings(
            schema="p1_work_actionrace_" + uuid4().hex,
            user="continuity_migrator",
            password="synthetic",
        )
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(os.environ, {"P3_RACE_DIRECTORY": temporary}),
            patch.object(FIXTURE, "settings", return_value=settings),
            patch.object(
                PostgresSettings,
                "connect",
                side_effect=AssertionError("fixture_must_not_rewrite_public_marker"),
            ),
            patch.object(FIXTURE, "install_work_schema"),
            patch.object(FIXTURE, "upgrade_work_schema_v2"),
            patch.object(FIXTURE, "upgrade_work_schema_v3"),
            patch.object(FIXTURE, "upgrade_work_schema_v4"),
            patch.object(FIXTURE.HELPER, "install"),
            patch.object(FIXTURE, "initialize_result_receiver", return_value=str(uuid4())),
        ):
            self.assertEqual(
                FIXTURE.install(), {"status": "passed", "work_version": 4, "case_version": 4}
            )
            self.assertEqual(FIXTURE.load("work_owner.json")["schema"], settings.schema)

    def test_activity_inventory_refreshes_before_each_lock_observation(self) -> None:
        calls: list[str] = []

        class Cursor:
            def fetchall(self):
                return [{"pid": 12, "blockers": [11]}]

        class Connection:
            def execute(self, query, values=None):
                calls.append(query)
                if values is not None:
                    self_test.assertEqual(calls[-2], "SELECT pg_stat_clear_snapshot()")
                    self_test.assertEqual(values, (0xFFFFFFFF, 2))
                return Cursor()

        self_test = self
        for _ in range(2):
            self.assertEqual(
                FIXTURE.HELPER.lock_waiters(Connection(), -1, 2), [{"pid": 12, "blockers": [11]}]
            )
        self.assertEqual(len(calls), 4)

    def test_fresh_terminal_command_does_not_reuse_original_cancel_identity(self) -> None:
        commands: list[str] = []

        class Client:
            async def cancel(self, *, task_id, command_id):
                commands.append(command_id)
                return SimpleNamespace(
                    cancellation_id=command_id,
                    task_id=task_id,
                    case_id="case",
                    command_id=command_id,
                    reason=SimpleNamespace(value="user_requested"),
                    disposition=SimpleNamespace(
                        value="already_terminal"
                        if command_id.startswith("terminal_")
                        else "requested_best_effort"
                    ),
                    created_at="2030-01-01T00:00:00+00:00",
                    created=commands.count(command_id) == 1,
                )

            async def close(self):
                pass

        async def exercise():
            self.assertEqual(await FIXTURE.cancel("applied"), "requested_best_effort")
            self.assertEqual(await FIXTURE.cancel("applied"), "requested_best_effort")
            self.assertEqual(
                await FIXTURE.cancel("applied", command_id="terminal_applied"), "already_terminal"
            )

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(os.environ, {"P3_RACE_DIRECTORY": temporary}),
            patch.object(FIXTURE, "client", return_value=Client()),
            patch.object(FIXTURE, "case_data", return_value={"task_id": "task"}),
        ):
            asyncio.run(exercise())
            self.assertEqual(commands, ["cancel_applied", "cancel_applied", "terminal_applied"])
            self.assertNotEqual(
                FIXTURE.load("cancellation_cancel_applied.json")["cancellation_id"],
                FIXTURE.load("cancellation_terminal_applied.json")["cancellation_id"],
            )

    def test_evidence_digest_frames_exact_record_count_order_and_boundaries(self) -> None:
        from delegation_reliability.contracts import canonical

        records = [{"work_id": "a", "result_sha256": "b"}, {"work_id": "c", "result_sha256": "d"}]
        digest = hashlib.sha256(
            b"p3-action-race-reconciliation-v1\x00" + len(records).to_bytes(2, "big")
        )
        for record in records:
            body = canonical(record)
            digest.update(len(body).to_bytes(4, "big") + body)
        original = FIXTURE.inventory_digest(records)
        self.assertEqual(original, digest.hexdigest())
        self.assertNotEqual(original, FIXTURE.inventory_digest(list(reversed(records))))
        self.assertNotEqual(original, FIXTURE.inventory_digest(records[:1]))
        changed = [{**records[0], "result_sha256": "changed"}, records[1]]
        self.assertNotEqual(original, FIXTURE.inventory_digest(changed))
        # Evidence is not a wire request: its aggregate may exceed wire nodes,
        # while each exact canonical record and total bytes remain bounded.
        many = [{"a": "a", "b": "b", "c": "c", "d": "d"} for _ in range(64)]
        with self.assertRaises(ContractError):
            canonical(many)
        self.assertEqual(len(FIXTURE.inventory_digest(many)), 64)

    def test_evidence_digest_rejects_record_and_aggregate_capacity_overflow(self) -> None:
        for records in ([], [{"v": "x"}] * 65, [{"v": "x" * 4096}], [{"v": "x" * 2040}] * 33):
            with self.subTest(count=len(records)), self.assertRaises(AssertionError):
                FIXTURE.inventory_digest(records)
        # Exactly64KiB accepted, one extra byte rejected; per-record stays<4KiB.
        boundary = [{"v": "x" * 1016} for _ in range(64)]
        self.assertEqual(len(FIXTURE.inventory_digest(boundary)), 64)
        boundary[-1] = {"v": "x" * 1017}
        with self.assertRaises(AssertionError):
            FIXTURE.inventory_digest(boundary)

    def test_owned_lock_refuses_foreign_schema_before_connect(self) -> None:
        from continuity_lab.work_api import PostgresSettings

        settings = PostgresSettings(
            schema="not_owned", user="continuity_migrator", password="synthetic"
        )
        with self.assertRaises(ValueError):
            FIXTURE.HELPER.ordered_lock(settings, Path("/tmp"), "b_first")
