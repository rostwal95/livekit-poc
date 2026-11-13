"""Offline consumer controls; these fake ports do not qualify PostgreSQL or media."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
import importlib.util
import inspect
import io
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from continuity_lab.execution_api import (
    AttemptResult,
    ExecutionObservation,
    Issuance,
    IssuedAttempt,
)
from continuity_lab.work_api import WorkPayload, WorkRecord, WorkScope
from delegation_reliability import (
    ChannelPolicyView,
    channel_policy_key,
    produce_channel_policy_request,
)
from delegation_reliability.contracts import Scope
from delegation_reliability.fixed_policy_contracts import produce_fixed_policy_request

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "local-setup/scripts/p3_channel_origin_consumer.py"
SPEC = importlib.util.spec_from_file_location("origin_consumer_tested", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)
SCOPE = Scope("tenant_origin", "account_origin")


def catalogue():
    return tuple(
        m.CatalogueEntry(
            label, *m.make_template(label, SCOPE, "case_origin", "conversation_origin")
        )
        for label in ("a", "b")
    )


def channel_request(entry, *, profile=None, revision=1, operation=None):
    operation = str(uuid4()) if operation is None else operation
    inner = entry.template.to_wire()
    inner.pop("input_fingerprint")
    inner.update(delegation_id=channel_policy_key(operation), request_revision=revision)
    return produce_channel_policy_request(
        {
            "schema_version": 1,
            "kind": "delegation.request",
            "capability": "booking.evaluate_policy",
            "input_schema_version": 3,
            "origin": {
                "kind": "p2.prepared_dispatch.v1",
                "profile_id": str(uuid4()) if profile is None else profile,
                "operation_key": operation,
                "input_receipt_id": str(uuid4()),
                "payload_sha256": "a" * 64,
                "payload_byte_length": 600,
            },
            "request": produce_fixed_policy_request(inner).to_wire(),
        }
    )


def config_fixture(directory):
    supplier = directory / "supplier.sqlite"
    supplier.write_bytes(b"synthetic supplier fixture only")
    supplier.chmod(0o600)
    value = {
        "schema_version": 1,
        "scope": {"tenant_id": SCOPE.tenant_id, "account_id": SCOPE.account_id},
        "case_id": "case_origin",
        "conversation_id": "conversation_origin",
        "recipient_id": "recipient_origin",
        "profile_id": str(uuid4()),
        "case_schema": "p3_completion_" + uuid4().hex,
        "work_schema": "p1_work_origin_" + uuid4().hex,
        "task_id": str(uuid4()),
        "authority_case_id": str(uuid4()),
        "supplier_path": str(supplier),
        "receiver_endpoint": {"host": "127.0.0.1", "port": 12345},
        "original_work_id": str(uuid4()),
        "ack_work_id": str(uuid4()),
        "owners": {"original": str(uuid4()), "current": str(uuid4())},
        "parent_deadline_monotonic": time.monotonic() + 120,
    }
    env = {
        "PATH": "/usr/bin:/bin",
        "LANG": "en_US.UTF-8",
        "CI": "1",
        "NO_COLOR": "1",
        "P3_ORIGIN_DIRECTORY": str(directory),
        "P3_ORIGIN_PG_PORT": "15432",
        "P3_ORIGIN_RUNTIME_PASSWORD": "r" * 43,
        "P3_ORIGIN_WORK_TOKEN": "w" * 43,
        "P3_ORIGIN_CASE_TOKEN": "c" * 43,
        "P3_ORIGIN_PUBLISHER_TOKEN": "p" * 43,
    }
    return value, env


def save_config(directory, value):
    path = directory / "origin-consumer-config.json"
    path.write_text(json.dumps(value))
    path.chmod(0o600)


class TemplateTests(unittest.TestCase):
    def test_two_closed_immutable_pairs_have_exact_scope_hashes_versions_and_facts(self):
        entries = catalogue()
        self.assertEqual([entry.label for entry in entries], ["a", "b"])
        for entry, days in zip(entries, (10, 14), strict=True):
            self.assertEqual(entry.template.scope, SCOPE)
            self.assertEqual(entry.template.request_revision, 1)
            self.assertGreater(entry.template.deadline_at_ms, time.time_ns() // 1000000)
            self.assertEqual(
                entry.template.evidence, tuple(record.reference for record in entry.evidence)
            )
            for record in entry.evidence:
                self.assertEqual(record.scope, SCOPE)
                self.assertEqual(record.reference.version, "distinct_" + entry.label)
                self.assertEqual(record.reference.byte_length, len(record.body))
                self.assertEqual(record.reference.sha256, hashlib.sha256(record.body).hexdigest())
                self.assertNotIn("scope", json.loads(record.body))
            self.assertEqual(json.loads(entry.evidence[0].body)["minimum_notice_days"], 7)
            self.assertEqual(
                json.loads(entry.evidence[1].body)["observations"][0]["days_before_arrival"], days
            )
        self.assertNotEqual(entries[0].template.evidence, entries[1].template.evidence)

    def test_stored_winning_pair_is_selected_without_selecting_new_proposal(self):
        entries = catalogue()
        for entry in entries:
            request = channel_request(entry)
            self.assertIs(m.select_evidence(request, entries), entry)
        changed = channel_request(entries[0]).to_wire()
        changed.pop("input_fingerprint")
        inner = changed["request"]
        inner.pop("input_fingerprint")
        inner["evidence"][1] = entries[1].template.to_wire()["evidence"][1]
        changed["request"] = produce_fixed_policy_request(inner).to_wire()
        with self.assertRaises(m.ConsumerError):
            m.select_evidence(produce_channel_policy_request(changed), entries)

    def test_scope_is_copied_and_invalid_catalogue_or_label_fails(self):
        scope = Scope(SCOPE.tenant_id, SCOPE.account_id)
        template, records = m.make_template("a", scope, "case_origin", "conversation_origin")
        object.__setattr__(scope, "tenant_id", "foreign")
        self.assertEqual(template.scope, SCOPE)
        self.assertEqual(records[0].scope, SCOPE)
        with self.assertRaises(m.ConsumerError):
            m.make_template("other", SCOPE, "case_origin", "conversation_origin")
        with self.assertRaises(m.ConsumerError):
            m.select_evidence(channel_request(catalogue()[0]), ())

    def test_whole_request_fingerprint_covers_selected_pair(self):
        entries = catalogue()
        operation, profile = str(uuid4()), str(uuid4())
        first = channel_request(entries[0], operation=operation, profile=profile)
        second = channel_request(entries[1], operation=operation, profile=profile)
        self.assertNotEqual(first.input_fingerprint, second.input_fingerprint)
        self.assertNotEqual(first.request.input_fingerprint, second.request.input_fingerprint)
        self.assertEqual(first.delegation_id, second.delegation_id)


class ConfigurationTests(unittest.TestCase):
    def test_private_config_exact_environment_and_secret_safe_copy(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            directory = Path(folder).resolve()
            value, env = config_fixture(directory)
            save_config(directory, value)
            config, selected = m.configuration(directory, env)
            self.assertEqual(config.scope, SCOPE)
            self.assertEqual(config.receiver_port, 12345)
            self.assertEqual(selected.pg_port, 15432)
            self.assertNotIn(env["P3_ORIGIN_RUNTIME_PASSWORD"], repr(selected))
            self.assertNotIn(env["P3_ORIGIN_WORK_TOKEN"], repr(selected))
            value["scope"]["tenant_id"] = "foreign"
            env["P3_ORIGIN_WORK_TOKEN"] = "changed"
            self.assertEqual(config.scope, SCOPE)
            self.assertEqual(selected.work_token, "w" * 43)

    def test_database_password_uses_public_bound_separately_from_bearer_shape(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            directory = Path(folder).resolve()
            value, env = config_fixture(directory)
            save_config(directory, value)
            for password in ("short", "ordinary-pg-password:with.punctuation!", "r" * 128):
                with self.subTest(length=len(password)):
                    _config, selected = m.configuration(
                        directory, dict(env, P3_ORIGIN_RUNTIME_PASSWORD=password)
                    )
                    self.assertEqual(selected.runtime_password, password)
                    self.assertNotIn(password, repr(selected))
            for password in (
                "",
                "r" * 129,
                "invalid\0password",
                "invalid\rpassword",
                "invalid\npassword",
            ):
                with self.subTest(length=len(password)), self.assertRaises(m.ConsumerError):
                    m.configuration(directory, dict(env, P3_ORIGIN_RUNTIME_PASSWORD=password))
            with self.assertRaises(m.ConsumerError):
                m.configuration(directory, dict(env, P3_ORIGIN_WORK_TOKEN="ordinary-password"))

    def test_unknown_or_unsafe_configuration_is_rejected_without_any_ports(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            directory = Path(folder).resolve()
            original, env = config_fixture(directory)
            mutations = [
                dict(original, extra=True),
                dict(original, schema_version=True),
                dict(original, receiver_endpoint={"host": "0.0.0.0", "port": 12345}),
                dict(original, receiver_endpoint={"host": "127.0.0.1", "port": True}),
                dict(original, parent_deadline_monotonic=float("nan")),
                dict(original, parent_deadline_monotonic=time.monotonic() + 181),
                dict(original, work_schema="continuity"),
                dict(original, profile_id="bad"),
                dict(original, original_work_id=original["ack_work_id"]),
                dict(original, supplier_path=str(directory.parent / "outside.sqlite")),
            ]
            with patch.object(m, "open_work_client", side_effect=AssertionError("port opened")):
                for value in mutations:
                    save_config(directory, value)
                    with (
                        self.subTest(keys=set(value)),
                        self.assertRaises((m.ConsumerError, ValueError)),
                    ):
                        m.configuration(directory, env)
            save_config(directory, original)
            for bad_env in (
                dict(env, OPENAI_API_KEY="PRIVATE_SENTINEL"),
                dict(env, P3_ORIGIN_RUNTIME_PASSWORD="x" * 129),
                dict(env, P3_ORIGIN_PG_PORT="0"),
            ):
                with self.assertRaises(m.ConsumerError):
                    m.configuration(directory, bad_env)

    def test_nonprivate_duplicate_symlink_and_preexisting_output_fail_closed(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            directory = Path(folder).resolve()
            value, env = config_fixture(directory)
            save_config(directory, value)
            path = directory / "origin-consumer-config.json"
            path.chmod(0o644)
            with self.assertRaises(m.ConsumerError):
                m.configuration(directory, env)
            path.chmod(0o600)
            raw = json.dumps(value)
            path.write_text(raw[:-1] + ',"schema_version":1}')
            with self.assertRaises(m.ConsumerError):
                m.configuration(directory, env)
            output = directory / "output.json"
            m.publish(output, {"schema_version": 1})
            with self.assertRaises(FileExistsError):
                m.publish(output, {"changed": True})
            self.assertEqual(json.loads(output.read_bytes()), {"schema_version": 1})
            path.unlink()
            path.symlink_to(output)
            with self.assertRaises(m.ConsumerError):
                m.configuration(directory, env)

    def test_publish_final_is_absent_until_complete_pending_is_fsynced(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            directory = Path(folder).resolve()
            final = directory / "origin-case-advanced.json"
            payload = {"schema_version": 1, "revision": 2}
            actual_fsync = m.os.fsync
            calls = []

            def observe_fsync(descriptor):
                self.assertFalse(final.exists())
                pending = tuple(directory.glob(".origin-publish-*.pending"))
                self.assertEqual(len(pending), 1)
                self.assertEqual(json.loads(pending[0].read_bytes()), payload)
                calls.append(True)
                actual_fsync(descriptor)

            with patch.object(m.os, "fsync", side_effect=observe_fsync):
                m.publish(final, payload)
            self.assertEqual(calls, [True])
            self.assertEqual(m.read_private(final), payload)
            self.assertEqual(tuple(directory.glob(".origin-publish-*.pending")), ())
            self.assertEqual(final.stat().st_nlink, 1)

    def test_failed_fsync_or_link_removes_only_owned_pending_and_preserves_other_files(self):
        for target in ("fsync", "link"):
            with (
                self.subTest(target=target),
                tempfile.TemporaryDirectory(dir="/private/tmp") as folder,
            ):
                directory = Path(folder).resolve()
                final = directory / "result.json"
                unrelated = directory / "unrelated.json"
                unrelated.write_bytes(b"preserve")
                with (
                    patch.object(m.os, target, side_effect=OSError("PRIVATE_SENTINEL publication")),
                    self.assertRaises(OSError),
                ):
                    m.publish(final, {"schema_version": 1})
                self.assertFalse(final.exists())
                self.assertEqual(tuple(directory.glob(".origin-publish-*.pending")), ())
                self.assertEqual(unrelated.read_bytes(), b"preserve")

    def test_existing_final_is_never_replaced_and_leaves_no_owned_pending(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            directory = Path(folder).resolve()
            final = directory / "result.json"
            m.publish(final, {"original": True})
            before = final.read_bytes()
            with self.assertRaises(FileExistsError):
                m.publish(final, {"changed": True})
            self.assertEqual(final.read_bytes(), before)
            self.assertEqual(tuple(directory.glob(".origin-publish-*.pending")), ())

    def test_current_marker_is_bound_to_actual_public_work_and_original_input(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            directory = Path(folder).resolve()
            value, env = config_fixture(directory)
            save_config(directory, value)
            config, _selected = m.configuration(directory, env)
            request = channel_request(catalogue()[0], profile=config.profile_id, revision=2)
            body = m.encode_channel_policy_request(request)
            record = WorkRecord(
                str(uuid4()),
                WorkScope(SCOPE.tenant_id, SCOPE.account_id),
                request.delegation_id,
                WorkPayload("booking.evaluate_policy", body, request.deadline_at_ms),
                time.time_ns() // 1000000,
                False,
            )
            view = ChannelPolicyView(record, request)
            marker = {
                "schema_version": 1,
                "receipt": {
                    "operationKey": request.origin.operation_key,
                    "scope": {"tenantId": SCOPE.tenant_id, "accountId": SCOPE.account_id},
                    "payloadDigest": request.origin.payload_sha256,
                    "receiptId": record.work_id,
                },
                "input_receipt_id": request.origin.input_receipt_id,
            }
            m.validate_current_marker(marker, view, config)
            for key in ("input_receipt_id", "schema_version"):
                changed = copy.deepcopy(marker)
                changed[key] = str(uuid4()) if key == "input_receipt_id" else True
                with self.assertRaises(m.ConsumerError):
                    m.validate_current_marker(changed, view, config)
            for key, changed_value in (
                ("receiptId", str(uuid4())),
                ("operationKey", str(uuid4())),
                ("payloadDigest", "b" * 64),
            ):
                changed = copy.deepcopy(marker)
                changed["receipt"][key] = changed_value
                with self.assertRaises(m.ConsumerError):
                    m.validate_current_marker(changed, view, config)

    def test_import_and_rejected_cli_start_no_io_and_never_read_dependency_getter(self):
        spec = importlib.util.spec_from_file_location("origin_consumer_inert", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        with (
            patch.object(socket.socket, "connect", side_effect=AssertionError("connect")),
            patch("subprocess.Popen", side_effect=AssertionError("process")),
            patch.object(Path, "read_bytes", side_effect=AssertionError("fixture read")),
        ):
            spec.loader.exec_module(module)
        output = io.StringIO()
        with (
            patch.object(module, "configuration", side_effect=AssertionError("config read")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(module.main(["unexpected"]), 1)
        self.assertEqual(json.loads(output.getvalue())["code"], "origin_consumer_failed")

        class PrivateError(RuntimeError):
            @property
            def code(self):
                raise AssertionError("PRIVATE_SENTINEL getter")

        output = io.StringIO()
        with (
            patch.object(
                module, "configuration", side_effect=PrivateError("PRIVATE_SENTINEL args")
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(module.main([]), 1)
        self.assertNotIn("PRIVATE_SENTINEL", output.getvalue())


class FakeExecution:
    def __init__(self, request):
        self.scope = WorkScope(request.scope.tenant_id, request.scope.account_id)
        self.pending_count, self.closed = 0, False
        self.record = WorkRecord(
            str(uuid4()),
            self.scope,
            request.delegation_id,
            WorkPayload(
                "booking.evaluate_policy",
                m.encode_channel_policy_request(request),
                request.deadline_at_ms,
            ),
            time.time_ns() // 1000000,
            False,
        )
        self.issued, self.saved = None, None

    async def observe(self, *, work_id):
        assert work_id == self.record.work_id
        return ExecutionObservation(
            self.record,
            self.issued,
            self.saved,
            int(self.issued is not None),
            "result_recorded"
            if self.saved is not None
            else "running"
            if self.issued is not None
            else "accepted",
        )

    async def issue(self, *, work_id, owner_id, command_id):
        assert work_id == self.record.work_id
        if self.issued is not None:
            assert self.issued.command_id == command_id
            return Issuance(self.issued, False)
        now = time.time_ns() // 1000000
        self.issued = IssuedAttempt(
            self.record, str(uuid4()), command_id, 1, owner_id, 1, now, now + 5000
        )
        return Issuance(self.issued, True)

    async def find_issue(self, *, command_id):
        return (
            self.issued
            if self.issued is not None and self.issued.command_id == command_id
            else None
        )

    async def complete(self, *, attempt, body):
        assert attempt == self.issued and self.saved is None
        self.saved = AttemptResult(
            self.record.work_id,
            attempt.attempt_id,
            body,
            time.time_ns() // 1000000,
            "eligible_at_commit",
        )
        return self.saved

    async def result(self, *, work_id, attempt_id):
        assert work_id == self.record.work_id
        return (
            self.saved if self.saved is not None and self.saved.attempt_id == attempt_id else None
        )

    async def close(self):
        self.closed = True


class AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_runner_issues_outer_v3_and_replay_does_not_reinvoke(self):
        for entry in catalogue():
            request = channel_request(entry)
            execution, specialist = FakeExecution(request), m.ScriptedPolicy(entry)
            runner = m.ChannelPolicyRunner(
                executions=execution,
                scope=request.scope,
                owner_id=str(uuid4()),
                specialist=specialist,
                case_authority=m.SimulatedCases(request),
                evidence=entry.evidence,
            )
            try:
                first = await runner.run_once(execution.record.work_id, "unit_origin_run")
                proof = m.execution_proof(first)
                self.assertEqual(
                    proof["result_sha256"], hashlib.sha256(execution.saved.body).hexdigest()
                )
                result = json.loads(proof["result_canonical"])
                self.assertEqual(result["result_schema_version"], 3)
                self.assertEqual(result["input_fingerprint"], request.input_fingerprint)
                self.assertEqual(
                    result["result"]["input_fingerprint"], request.request.input_fingerprint
                )
                replay = await runner.run_once(execution.record.work_id, "unit_origin_run")
                self.assertFalse(replay.invoked)
                self.assertEqual(specialist.invocations, 1)
            finally:
                await runner.close()
            self.assertTrue(execution.closed)
            self.assertTrue(specialist.closed)

    async def test_failed_facade_construction_preserves_raw_owned_ports(self):
        entry = catalogue()[0]
        request = channel_request(entry)
        resources = m.OwnedResources()
        execution = resources.add(FakeExecution(request), 1)
        specialist = resources.add(m.ScriptedPolicy(entry), 1)
        with self.assertRaisesRegex(RuntimeError, "^invalid_input$"):
            resources.transfer(
                m.ChannelPolicyRunner(
                    executions=execution,
                    scope=request.scope,
                    owner_id="invalid",
                    specialist=specialist,
                    case_authority=m.SimulatedCases(request),
                    evidence=entry.evidence,
                ),
                (execution, specialist),
                1,
            )
        self.assertEqual(resources.observation()["retained_tiers"], [0, 2, 0])
        self.assertFalse(execution.closed)
        self.assertFalse(specialist.closed)
        self.assertTrue(await resources.close(time.monotonic() + 1))
        self.assertTrue(execution.closed)
        self.assertTrue(specialist.closed)

    async def test_scripted_policy_returns_literal_grounded_v2_facts_for_both_winners(self):
        for entry, days in zip(catalogue(), (10, 14), strict=True):
            specialist = m.ScriptedPolicy(entry)
            observed = await specialist.invoke_observed(entry.template, evidence=entry.evidence)
            self.assertEqual(observed.applicability, "candidate")
            self.assertEqual(observed.result.fact_refs[0].days_before_arrival, days)
            self.assertEqual(observed.result.rule_refs[0].minimum_notice_days, 7)
            self.assertTrue(observed.result.eligible)
            self.assertEqual(specialist.invocations, 1)
            await specialist.close()
            with self.assertRaises(m.ConsumerError):
                await specialist.invoke_observed(entry.template, evidence=entry.evidence)
            self.assertEqual(specialist.invocations, 1)

    async def test_public_uncertainty_simulations_keep_one_key_and_never_resubmit(self):
        request = channel_request(catalogue()[0])
        with (
            patch.object(m, "open_work_client", side_effect=AssertionError("real port")),
            patch.object(socket.socket, "connect", side_effect=AssertionError("network")),
        ):
            result = await m.simulate_uncertainty(request)
        self.assertEqual([r["reconciliation"] for r in result], ["missing", "unavailable"])
        for proof in result:
            self.assertEqual((proof["finds"], proof["submits"]), (2, 1))
            self.assertEqual(proof["keys"], [request.delegation_id] * 3)
            self.assertFalse(proof["actual_database_fault"])
            self.assertTrue(proof["closed"])

    async def test_business_deadline_denies_late_admission_but_retains_cleanup_until_final(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            directory = Path(folder).resolve()
            value, env = config_fixture(directory)
            save_config(directory, value)
            config, _environment = m.configuration(directory, env)
            # Model the final cleanup interval after a previously valid startup.
            late = replace(config, parent_deadline_monotonic=time.monotonic() + 1)
            self.assertEqual(late.business_deadline_monotonic, late.parent_deadline_monotonic - 20)
            self.assertLess(late.business_deadline_monotonic, time.monotonic())
            with self.assertRaises(m.ConsumerError):
                late.progress()
            with (
                patch.object(m, "read_private", side_effect=AssertionError("late marker admitted")),
                self.assertRaises(m.ConsumerError),
            ):
                await m.wait_marker(directory, late)
            resources, entered, release = m.OwnedResources(), asyncio.Event(), asyncio.Event()

            class ActualOwner:
                async def close(self):
                    entered.set()
                    await release.wait()

            resources.add(ActualOwner(), 0)
            observer = asyncio.create_task(resources.close(late.parent_deadline_monotonic))
            try:
                await asyncio.wait_for(entered.wait(), 0.2)
                self.assertFalse(observer.done())
                self.assertEqual(resources.observation()["retained_tiers"], [1, 0, 0])
                self.assertEqual(resources.observation()["close_observers_pending"], 1)
                release.set()
                self.assertTrue(await asyncio.wait_for(observer, 0.5))
                self.assertTrue(resources.observation()["cleanup_complete"])
            finally:
                release.set()
                if not observer.done():
                    await observer

    async def test_startup_task_setup_failure_closes_coroutine_and_preserves_existing_owner(self):
        resources, operations, factory_calls = m.OwnedResources(), [], []

        class Existing:
            async def close(self):
                return None

        retained = resources.add(Existing(), 2)

        def reject(operation, **kwargs):
            operations.append(operation)
            raise RuntimeError("PRIVATE_SENTINEL task setup")

        def factory():
            factory_calls.append(True)
            return Existing()

        with (
            patch.object(m.asyncio, "create_task", side_effect=reject),
            self.assertRaises(RuntimeError),
        ):
            await resources.startup(factory, 1)
        self.assertEqual(len(operations), 1)
        self.assertEqual(inspect.getcoroutinestate(operations[0]), inspect.CORO_CLOSED)
        self.assertEqual(factory_calls, [])
        self.assertEqual(resources.startups, set())
        self.assertEqual(resources.tiers, [[], [], [retained]])
        self.assertTrue(await resources.close(time.monotonic() + 1))

    async def test_close_task_setup_failure_retains_owner_and_attempts_other_independent_close(
        self,
    ):
        resources, operations, order = m.OwnedResources(), [], []

        class Owner:
            def __init__(self, label):
                self.label = label

            async def close(self):
                order.append(self.label)

        first = resources.add(Owner("first"), 0)
        resources.add(Owner("second"), 0)
        case = resources.add(Owner("case"), 2)
        actual_create = m.asyncio.create_task

        def reject_first(operation, **kwargs):
            if not operations:
                operations.append(operation)
                raise RuntimeError("PRIVATE_SENTINEL task setup")
            return actual_create(operation, **kwargs)

        with patch.object(m.asyncio, "create_task", side_effect=reject_first):
            self.assertFalse(await resources.close(time.monotonic() + 1))
        self.assertEqual(inspect.getcoroutinestate(operations[0]), inspect.CORO_CLOSED)
        self.assertEqual(order, ["second"])
        self.assertEqual(resources.tiers, [[first], [], [case]])
        self.assertTrue(await resources.close(time.monotonic() + 1))
        self.assertEqual(order, ["second", "first", "case"])

    async def test_final_close_task_setup_failure_still_publishes_failed_retained_ownership(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            directory = Path(folder).resolve()
            raw, env = config_fixture(directory)
            save_config(directory, raw)
            config, environment = m.configuration(directory, env)
            late = replace(config, parent_deadline_monotonic=time.monotonic() + 5)
            resources, operations, closed = m.OwnedResources(), [], []

            class Existing:
                async def close(self):
                    closed.append(True)

            resources.add(Existing(), 0)

            def reject(operation, **kwargs):
                operations.append(operation)
                raise RuntimeError("PRIVATE_SENTINEL task setup")

            with (
                patch.object(m, "OwnedResources", return_value=resources),
                patch.object(m.asyncio, "create_task", side_effect=reject),
                patch.object(
                    m, "open_postgres_client", side_effect=AssertionError("late business admitted")
                ),
            ):
                result = await m.exercise(late, environment)
            self.assertEqual(result["status"], "failed")
            self.assertFalse(result["cleanup_complete"])
            self.assertEqual(result["ownership"]["retained_tiers"], [1, 0, 0])
            self.assertEqual(inspect.getcoroutinestate(operations[0]), inspect.CORO_CLOSED)
            self.assertEqual(closed, [])
            self.assertEqual(m.read_private(directory / "origin-p3-consumer.json"), result)
            self.assertNotIn("PRIVATE_SENTINEL", json.dumps(result))
            self.assertTrue(await resources.close(late.parent_deadline_monotonic))
            self.assertEqual(closed, [True])

    async def test_marker_wait_rejects_unsafe_nlink_two_metadata_before_deferral(self):
        for kind in ("mode", "uid", "fifo"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
                directory = Path(folder).resolve()
                value, env = config_fixture(directory)
                save_config(directory, value)
                config, _environment = m.configuration(directory, env)
                pending, final = (
                    directory / ".owned-test.pending",
                    directory / "origin-current-accepted.json",
                )
                if kind == "fifo":
                    m.os.mkfifo(pending, 0o600)
                else:
                    pending.write_text('{"schema_version":1}')
                    pending.chmod(0o644 if kind == "mode" else 0o600)
                m.os.link(pending, final, follow_symlinks=False)
                self.assertEqual(final.lstat().st_nlink, 2)
                check_uid = (
                    patch.object(m.os, "geteuid", return_value=m.os.geteuid() + 1)
                    if kind == "uid"
                    else contextlib.nullcontext()
                )
                with check_uid, self.assertRaises(m.ConsumerError):
                    await asyncio.wait_for(m.wait_marker(directory, config), 0.2)

    async def test_marker_wait_defers_atomic_nlink_two_then_reads_only_nlink_one(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            directory = Path(folder).resolve()
            value, env = config_fixture(directory)
            save_config(directory, value)
            config, _environment = m.configuration(directory, env)
            marker = {
                "schema_version": 1,
                "receipt": {
                    "operationKey": str(uuid4()),
                    "scope": {"tenantId": SCOPE.tenant_id, "accountId": SCOPE.account_id},
                    "payloadDigest": "a" * 64,
                    "receiptId": str(uuid4()),
                },
                "input_receipt_id": str(uuid4()),
            }
            pending = directory / ".owned-test.pending"
            pending.write_text(json.dumps(marker))
            pending.chmod(0o600)
            final = directory / "origin-current-accepted.json"
            m.os.link(pending, final, follow_symlinks=False)
            self.assertEqual(final.stat().st_nlink, 2)
            waiter = asyncio.create_task(m.wait_marker(directory, config))
            try:
                await asyncio.sleep(0.03)
                self.assertFalse(waiter.done())
                pending.unlink()
                self.assertEqual(await asyncio.wait_for(waiter, 1), marker)
            finally:
                if not waiter.done():
                    waiter.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await waiter

    async def test_marker_wait_does_not_retry_parse_or_closed_shape_failures(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            directory = Path(folder).resolve()
            value, env = config_fixture(directory)
            save_config(directory, value)
            config, _environment = m.configuration(directory, env)
            final = directory / "origin-current-accepted.json"
            final.write_bytes(b"not-json")
            final.chmod(0o600)
            with self.assertRaises(json.JSONDecodeError):
                await asyncio.wait_for(m.wait_marker(directory, config), 0.2)
            final.write_text('{"schema_version":1,"unexpected":true}')
            with self.assertRaises(m.ConsumerError):
                await asyncio.wait_for(m.wait_marker(directory, config), 0.2)

    async def test_cancelled_startup_retains_late_owner_before_case_clients_close(self):
        resources = m.OwnedResources()
        entered, release = threading.Event(), threading.Event()
        closed = []

        class Owner:
            async def close(self):
                closed.append("late")

        def factory():
            entered.set()
            release.wait(2)
            return Owner()

        waiter = asyncio.create_task(resources.startup(factory, 1))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
            self.assertEqual(resources.observation()["startup_pending"], 1)
        finally:
            release.set()
        await asyncio.gather(*resources.startups)
        self.assertEqual(resources.observation()["retained_tiers"], [0, 1, 0])
        self.assertTrue(await resources.close(time.monotonic() + 1))
        self.assertEqual(closed, ["late"])

    async def test_incomplete_close_retains_actual_observer_and_case_until_explicit_retry(self):
        resources, release = m.OwnedResources(), asyncio.Event()
        order = []

        class Outer:
            async def close(self):
                await release.wait()
                order.append("outer")

        class Case:
            async def close(self):
                order.append("case")

        resources.add(Outer(), 0)
        resources.add(Case(), 2)
        self.assertFalse(await resources.close(time.monotonic() + 0.02))
        self.assertEqual(order, [])
        self.assertEqual(resources.observation()["close_observers_pending"], 1)
        self.assertEqual(resources.observation()["retained_tiers"], [1, 0, 1])
        release.set()
        self.assertTrue(await resources.close(time.monotonic() + 1))
        self.assertEqual(order, ["outer", "case"])

    async def test_failed_close_still_attempts_other_independent_owner_and_defers_case(self):
        resources = m.OwnedResources()
        order = []

        class Owner:
            def __init__(self, label, fail=False):
                self.label, self.fail = label, fail

            async def close(self):
                order.append(self.label)
                if self.fail:
                    raise RuntimeError("PRIVATE_SENTINEL close")

        first = resources.add(Owner("first", True), 0)
        resources.add(Owner("second"), 0)
        resources.add(Owner("case"), 2)
        self.assertFalse(await resources.close(time.monotonic() + 1))
        self.assertEqual(order, ["first", "second"])
        self.assertEqual(resources.observation()["retained_tiers"], [1, 0, 1])
        first.fail = False
        self.assertTrue(await resources.close(time.monotonic() + 1))
        self.assertEqual(order, ["first", "second", "first", "case"])
        self.assertFalse(await resources.close(time.monotonic() - 1))


if __name__ == "__main__":
    unittest.main()
