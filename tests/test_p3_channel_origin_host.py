"""Isolated private controls and fake public-port lifetimes; no database/provider."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import importlib.util
import inspect
import io
import json
import os
import socket
import stat
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from continuity_lab.work_api import (
    WorkCancellation,
    WorkError,
    WorkPayload,
    WorkRecord,
    WorkScope,
    WorkSubmission,
)
from delegation_reliability.contracts import Scope

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "local-setup/scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "phase44_real_origin_host_tested", SCRIPTS / "p3_channel_origin_host.py"
)
assert SPEC is not None and SPEC.loader is not None
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)
TEMPLATE = json.loads((ROOT / "contracts/delegation/fixed-policy-v2.json").read_bytes())[
    "producer_input"
]


def save(path, value):
    body = json.dumps(value, separators=(",", ":")).encode()
    if path.exists():
        path.write_bytes(body)
    else:
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
            stream.write(body)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.directory = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)
        self.supplier = self.directory / "supplier.sqlite3"
        self.supplier.write_bytes(b"synthetic unopened supplier fixture")
        self.supplier.chmod(0o600)
        self.environment = {
            "PATH": "/usr/bin:/bin",
            "LANG": "en_US.UTF-8",
            "CI": "1",
            "NO_COLOR": "1",
            "__CF_USER_TEXT_ENCODING": "0x1F5:0x0:0x0",
            "P3_ORIGIN_DIRECTORY": str(self.directory),
            "P3_ORIGIN_PG_PORT": "15432",
            "P3_ORIGIN_RUNTIME_PASSWORD": "PRIVATE_RUNTIME_SENTINEL",
            "P3_ORIGIN_WORK_TOKEN": "w" * 43,
            "P3_ORIGIN_CASE_TOKEN": "c" * 43,
            "P3_ORIGIN_OPERATION_TOKEN": "o" * 43,
        }
        template = copy.deepcopy(TEMPLATE)
        from delegation_reliability.fixed_policy_contracts import produce_fixed_policy_request

        template = produce_fixed_policy_request(template).to_wire()
        self.input = {
            "schema_version": 1,
            "profile_id": str(uuid4()),
            "scope": template["scope"],
            "case_id": template["case_id"],
            "conversation_id": template["result_route"]["conversation_id"],
            "sender_id": "native_sender",
            "task_id": str(uuid4()),
            "authority_case_id": str(uuid4()),
            "case_schema": "p3_completion_" + uuid4().hex,
            "work_schema": "p1_work_origin_" + uuid4().hex,
            "supplier_path": str(self.supplier),
            "template": template,
            "deadline_window_ms": 30000,
            "operation_key": str(uuid4()),
            "parent_deadline_monotonic": time.monotonic() + 60,
        }
        for role in m.ROLES:
            self.save_role(role)

    def save_role(self, role, **changes):
        value = copy.deepcopy(self.input)
        if role in {"origin-recovered", "origin-current"}:
            value["operation_key"] = None
        value.update(changes)
        save(self.directory / (role + "-config.json"), value)
        return value

    def load(self, role="origin-race-a"):
        return m.configuration(role, self.environment)


class ConfigTests(Fixture):
    def test_platform_encoding_is_optional_but_unknown_keys_stay_rejected(self):
        environment = {k: v for k, v in self.environment.items() if k != "__CF_USER_TEXT_ENCODING"}
        runtime, config = m.configuration("origin-race-a", environment)
        self.assertEqual(runtime.directory, self.directory)
        self.assertEqual(config.role, "origin-race-a")

    def test_business_deadline_stops_admission_before_final_cleanup_budget(self):
        runtime, config = self.load("origin-recovered")
        self.assertEqual(config.business_deadline, config.parent_deadline_monotonic - 20)
        host = m.OriginFixtureHost(runtime, config)
        with patch.object(m.time, "monotonic", return_value=config.business_deadline + 1):
            self.assertTrue(host.control.stopped())
            self.assertLess(m.time.monotonic(), config.parent_deadline_monotonic)
            with self.assertRaisesRegex(m.OriginHostError, "^deadline_exceeded$"):
                host._admit()
        self.assertEqual(host.observation(complete=False)["retained_owners"], [0, 0, 0])

    def test_all_fixed_roles_are_copied_and_basic_roles_have_no_fake_operation(self):
        for role in m.ROLES:
            runtime, config = self.load(role)
            self.assertEqual(config.role, role)
            self.assertEqual(runtime.pg_port, 15432)
            self.assertEqual(config.scope, Scope(**self.input["scope"]))
            self.assertEqual(
                config.operation_key,
                None
                if role in {"origin-recovered", "origin-current"}
                else self.input["operation_key"],
            )
            self.assertNotIn("PRIVATE_RUNTIME_SENTINEL", repr(runtime))
            self.assertNotIn("w" * 43, repr(runtime))
            self.assertNotIn("input_fingerprint", repr(config))

    def test_closed_environment_rejects_extra_missing_bad_secret_or_selectors_before_factories(
        self,
    ):
        invalid = [
            {**self.environment, "OPENAI_API_KEY": "PRIVATE_PROVIDER_SENTINEL"},
            {**self.environment, "PGHOST": "remote.invalid"},
            {k: v for k, v in self.environment.items() if k != "P3_ORIGIN_CASE_TOKEN"},
            {**self.environment, "P3_ORIGIN_PG_PORT": "0"},
            {**self.environment, "P3_ORIGIN_PG_PORT": "015432"},
            {**self.environment, "P3_ORIGIN_WORK_TOKEN": "short"},
            {**self.environment, "P3_ORIGIN_CASE_TOKEN": self.environment["P3_ORIGIN_WORK_TOKEN"]},
            {**self.environment, "P3_ORIGIN_RUNTIME_PASSWORD": "PRIVATE\nSENTINEL"},
            {**self.environment, "CI": "0"},
        ]
        with (
            patch.object(m, "open_postgres_client", side_effect=AssertionError("factory")),
            patch.object(m, "open_work_client", side_effect=AssertionError("factory")),
        ):
            for index, environment in enumerate(invalid):
                with (
                    self.subTest(index=index),
                    self.assertRaisesRegex(m.OriginHostError, "^invalid_configuration$"),
                ):
                    m.configuration("origin-race-a", environment)

    def test_unknown_environment_keys_are_rejected_without_reading_their_values(self):
        reads = []
        supplied = {**self.environment, "OPENAI_API_KEY": "PRIVATE_PROVIDER_SENTINEL"}

        class Guarded(Mapping):
            def __len__(self):
                return len(supplied)

            def __iter__(self):
                return iter(supplied)

            def __getitem__(self, key):
                reads.append(key)
                return supplied[key]

        with self.assertRaisesRegex(m.OriginHostError, "^invalid_configuration$"):
            m.configuration("origin-race-a", Guarded())
        self.assertEqual(reads, [])

    def test_config_shapes_bounds_scope_and_role_operation_are_strict(self):
        cases = [
            {"schema_version": True},
            {"extra": "PRIVATE_SENTINEL"},
            {"profile_id": "not-uuid"},
            {"scope": {"tenant_id": "Foreign", "account_id": "account"}},
            {"case_schema": "continuity"},
            {"work_schema": "p1_work_origin_" + "g" * 32},
            {"task_id": "00000000-0000-0000-0000-000000000000"},
            {"deadline_window_ms": True},
            {"deadline_window_ms": 19},
            {"deadline_window_ms": 60001},
            {"parent_deadline_monotonic": True},
            {"parent_deadline_monotonic": time.monotonic() - 1},
            {"parent_deadline_monotonic": time.monotonic() + 181},
            {"parent_deadline_monotonic": float("inf")},
            {"operation_key": None},
            {"sender_id": "x" * 129},
            {"case_id": "other_case"},
        ]
        for index, changes in enumerate(cases):
            self.save_role("origin-race-a", **changes)
            with (
                self.subTest(index=index),
                self.assertRaisesRegex(m.OriginHostError, "^invalid_configuration$"),
            ):
                self.load()
        self.save_role("origin-current", operation_key=self.input["operation_key"])
        with self.assertRaises(m.OriginHostError):
            self.load("origin-current")
        self.save_role("origin-current")
        self.assertIsNone(self.load("origin-current")[1].operation_key)

    def test_private_path_modes_symlinks_duplicate_json_and_foreign_supplier_reject(self):
        path = self.directory / "origin-race-a-config.json"
        original = path.read_bytes()
        path.chmod(0o644)
        with self.assertRaises(m.OriginHostError):
            self.load()
        path.chmod(0o600)
        path.write_bytes(
            original.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1', 1)
        )
        with self.assertRaises(m.OriginHostError):
            self.load()
        path.write_bytes(original)
        self.supplier.chmod(0o644)
        with self.assertRaises(m.OriginHostError):
            self.load()
        self.supplier.chmod(0o600)
        other = self.directory / "other-config.json"
        path.rename(other)
        path.symlink_to(other)
        with self.assertRaises(m.OriginHostError):
            self.load()
        path.unlink()
        other.rename(path)
        self.save_role(
            "origin-race-a", supplier_path=str(self.directory.parent / "foreign.sqlite3")
        )
        with self.assertRaises(m.OriginHostError):
            self.load()

    def test_import_and_configuration_are_inert_and_publication_never_overwrites(self):
        with (
            patch.object(socket.socket, "connect", side_effect=AssertionError("connected")),
            patch.object(socket.socket, "bind", side_effect=AssertionError("bound")),
            patch.object(asyncio, "create_task", side_effect=AssertionError("task")),
        ):
            SPEC.loader.exec_module(m)
            self.load()
        m.publish(self.directory, "one-observation.json", {"schema_version": 1})
        path = self.directory / "one-observation.json"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        with self.assertRaises(m.OriginHostError):
            m.publish(self.directory, "one-observation.json", {"changed": True})
        with self.assertRaises(m.OriginHostError):
            m.publish(self.directory, "../outside.json", {})
        self.assertEqual(json.loads(path.read_bytes()), {"schema_version": 1})

    def test_publication_is_complete_at_link_and_failed_publication_preserves_existing(self):
        expected = {"schema_version": 1, "pid": os.getpid(), "ready": True}
        final = self.directory / "atomic-observation.json"
        observed = []
        original_link = m.os.link

        def at_link(source, destination, *, follow_symlinks):
            source = Path(source)
            destination = Path(destination)
            self.assertFalse(destination.exists())
            self.assertEqual(json.loads(source.read_bytes()), expected)
            self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o600)
            original_link(source, destination, follow_symlinks=follow_symlinks)
            observed.append(destination.read_bytes())
            self.assertEqual(json.loads(observed[-1]), expected)

        with patch.object(m.os, "link", side_effect=at_link):
            m.publish(self.directory, final.name, expected)
        self.assertEqual(len(observed), 1)
        self.assertEqual(final.stat().st_nlink, 1)
        self.assertEqual(list(self.directory.glob("*.pending")), [])
        original = final.read_bytes()
        with self.assertRaisesRegex(m.OriginHostError, "^invalid_control$"):
            m.publish(self.directory, final.name, {"replacement": True})
        self.assertEqual(final.read_bytes(), original)
        self.assertEqual(list(self.directory.glob("*.pending")), [])
        missing = self.directory / "failed-observation.json"
        with (
            patch.object(m.os, "fsync", side_effect=OSError("PRIVATE_PUBLISH_SENTINEL")),
            self.assertRaisesRegex(m.OriginHostError, "^invalid_control$"),
        ):
            m.publish(self.directory, missing.name, expected)
        self.assertFalse(missing.exists())
        self.assertEqual(list(self.directory.glob("*.pending")), [])
        self.assertEqual(final.read_bytes(), original)


class FakeWork:
    def __init__(self, config, events=None):
        self.scope = WorkScope(config.scope.tenant_id, config.scope.account_id)
        self.pending_count = 0
        self.finds, self.submits, self.gets, self.cancels = [], [], [], []
        self.found = None
        self.created = True
        self.submit_entered = asyncio.Event()
        self.submit_release = None
        self.events = [] if events is None else events
        self.closed = 0
        self.payload = WorkPayload("booking.evaluate_policy", b"synthetic", 2000000060000)
        self.record = WorkRecord(
            str(uuid4()),
            self.scope,
            "p2_" + (config.operation_key or str(uuid4())).replace("-", ""),
            self.payload,
            1,
            False,
        )

    async def find(self, *, idempotency_key):
        self.finds.append(idempotency_key)
        return self.found

    async def submit(self, *, idempotency_key, payload):
        self.submits.append((idempotency_key, payload))
        self.submit_entered.set()
        if self.submit_release is not None:
            await self.submit_release.wait()
        self.record = replace(self.record, idempotency_key=idempotency_key, payload=payload)
        return WorkSubmission(self.record, self.created)

    async def get(self, *, work_id):
        self.gets.append(work_id)
        return self.record

    async def cancel(self, *, work_id, command_id):
        self.cancels.append((work_id, command_id))
        return WorkCancellation(str(uuid4()), work_id, command_id, 1)

    async def close(self):
        self.events.append("work")
        self.closed += 1


class AsyncFixture(unittest.IsolatedAsyncioTestCase, Fixture):
    async def asyncSetUp(self):
        self.runtime, self.config = self.load()
        self.control = m.FixtureControl(self.runtime, self.config)
        self.tasks = []

    async def asyncTearDown(self):
        self.control.stop.set()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)

    async def until(self, predicate):
        async with asyncio.timeout(2):
            while not predicate():
                await asyncio.sleep(0.001)


class HookTests(AsyncFixture):
    async def test_exact_role_ordinals_exclude_preflight_and_forward_each_real_read_once(self):
        for role, ordinal in (("origin-race-a", 2), ("origin-race-b", 1)):
            runtime, config = self.load(role)
            control = m.FixtureControl(runtime, config)
            inner = FakeWork(config)
            port = m.HookedTaskExecutionPort(inner, config, control)
            key = "p2_" + config.operation_key.replace("-", "")
            await port.find(idempotency_key="p2_origin_preflight")
            if ordinal == 2:
                self.assertIsNone(await port.find(idempotency_key=key))
            task = asyncio.create_task(port.find(idempotency_key=key))
            self.tasks.append(task)
            marker = self.directory / (role + "-read-miss.json")
            await self.until(marker.exists)
            self.assertFalse(task.done())
            self.assertEqual(
                json.loads(marker.read_bytes()),
                {
                    "schema_version": 1,
                    "pid": os.getpid(),
                    "key": key,
                    "ordinal": ordinal,
                    "found": False,
                },
            )
            self.assertEqual(inner.finds, ["p2_origin_preflight"] + [key] * ordinal)
            save(self.directory / "race-release.json", {"schema_version": 1, "release": True})
            self.assertIsNone(await task)
            (self.directory / "race-release.json").unlink()
            self.assertEqual(port.matching_find_count, ordinal)

    async def test_existing_record_never_fabricates_a_read_miss_or_barrier(self):
        config = self.load("origin-race-b")[1]
        inner = FakeWork(config)
        inner.found = inner.record
        port = m.HookedTaskExecutionPort(inner, config, m.FixtureControl(self.runtime, config))
        with self.assertRaisesRegex(WorkError, "^identity_conflict$"):
            await port.find(idempotency_key=inner.record.idempotency_key)
        self.assertFalse((self.directory / "origin-race-b-read-miss.json").exists())
        self.assertEqual(len(inner.finds), 1)

    async def test_ack_marker_is_after_actual_created_submit_and_reply_remains_held(self):
        config = self.load("origin-ack")[1]
        inner = FakeWork(config)
        inner.submit_release = asyncio.Event()
        control = m.FixtureControl(self.runtime, config)
        port = m.HookedTaskExecutionPort(inner, config, control)
        task = asyncio.create_task(
            port.submit(idempotency_key=inner.record.idempotency_key, payload=inner.payload)
        )
        self.tasks.append(task)
        await inner.submit_entered.wait()
        self.assertTrue((self.directory / "origin-ack-submit-entered.json").exists())
        committed = self.directory / "origin-ack-committed.json"
        self.assertFalse(committed.exists())
        inner.submit_release.set()
        await self.until(committed.exists)
        self.assertFalse(task.done())
        self.assertEqual(
            json.loads(committed.read_bytes()),
            {
                "schema_version": 1,
                "pid": os.getpid(),
                "work_id": inner.record.work_id,
                "key": inner.record.idempotency_key,
                "payload_sha256": inner.payload.sha256,
                "deadline_at_ms": inner.payload.deadline_at_ms,
            },
        )
        save(self.directory / "origin-ack-release.json", {"schema_version": 1, "release": True})
        observed = await task
        self.assertEqual(observed, WorkSubmission(inner.record, True))
        self.assertEqual(len(inner.submits), 1)
        self.assertEqual(inner.finds, [])

    async def test_ack_existing_submission_is_not_relabelled_as_new_commit(self):
        config = self.load("origin-ack")[1]
        inner = FakeWork(config)
        inner.created = False
        port = m.HookedTaskExecutionPort(inner, config, m.FixtureControl(self.runtime, config))
        observed = await port.submit(
            idempotency_key=inner.record.idempotency_key, payload=inner.payload
        )
        self.assertFalse(observed.created)
        self.assertFalse((self.directory / "origin-ack-committed.json").exists())
        self.assertEqual(port.submit_count, 1)

    async def test_basic_roles_forward_without_target_hooks_and_keep_public_operations(self):
        for role in ("origin-recovered", "origin-current"):
            config = self.load(role)[1]
            inner = FakeWork(config)
            port = m.HookedTaskExecutionPort(inner, config, m.FixtureControl(self.runtime, config))
            self.assertEqual(port.scope, inner.scope)
            await port.find(idempotency_key=inner.record.idempotency_key)
            await port.submit(idempotency_key=inner.record.idempotency_key, payload=inner.payload)
            self.assertEqual(await port.get(work_id=inner.record.work_id), inner.record)
            await port.cancel(work_id=inner.record.work_id, command_id="explicit_cancel")
            await port.close()
            self.assertEqual(
                (
                    len(inner.finds),
                    len(inner.submits),
                    len(inner.gets),
                    len(inner.cancels),
                    inner.closed,
                ),
                (1, 1, 1, 1, 1),
            )
            self.assertEqual(port.matching_find_count, 0)
            self.assertFalse((self.directory / (role + "-submit-entered.json")).exists())

    async def test_stop_before_race_write_rejects_but_postcommit_stop_retains_result(self):
        config = self.load("origin-race-b")[1]
        control = m.FixtureControl(self.runtime, config)
        inner = FakeWork(config)
        port = m.HookedTaskExecutionPort(inner, config, control)
        task = asyncio.create_task(port.find(idempotency_key=inner.record.idempotency_key))
        self.tasks.append(task)
        await self.until((self.directory / "origin-race-b-read-miss.json").exists)
        control.stop.set()
        with self.assertRaisesRegex(WorkError, "^closed$"):
            await task
        self.assertEqual(inner.submits, [])
        config = self.load("origin-ack")[1]
        control = m.FixtureControl(self.runtime, config)
        inner = FakeWork(config)
        port = m.HookedTaskExecutionPort(inner, config, control)
        task = asyncio.create_task(
            port.submit(idempotency_key=inner.record.idempotency_key, payload=inner.payload)
        )
        self.tasks.append(task)
        await self.until((self.directory / "origin-ack-committed.json").exists)
        control.stop.set()
        self.assertEqual((await task).record, inner.record)

    async def test_transient_two_link_controls_are_not_accepted_until_single_link(self):
        pending = self.directory / "stop.pending"
        stop = self.directory / (self.config.role + "-stop.json")
        save(pending, {"schema_version": 1, "stop": True})
        os.link(pending, stop)
        self.assertEqual(stop.stat().st_nlink, 2)
        self.assertFalse(self.control.stopped())
        pending.unlink()
        self.assertTrue(self.control.stopped())
        control = m.FixtureControl(self.runtime, self.config)
        stop.unlink()
        pending = self.directory / "release.pending"
        release = self.directory / "race-release.json"
        save(pending, {"schema_version": 1, "release": True})
        os.link(pending, release)
        task = asyncio.create_task(control.wait_release(release.name, committed=False))
        self.tasks.append(task)
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        self.assertEqual(release.stat().st_nlink, 2)
        pending.unlink()
        await task

    async def test_control_payloads_do_not_coerce_numeric_true(self):
        for flag in (1, False):
            save(
                self.directory / (self.config.role + "-stop.json"),
                {"schema_version": 1, "stop": flag},
            )
            with self.assertRaisesRegex(m.OriginHostError, "^invalid_control$"):
                self.control.stopped()
        (self.directory / (self.config.role + "-stop.json")).unlink()
        for flag in (1, False):
            save(self.directory / "race-release.json", {"schema_version": 1, "release": flag})
            with self.assertRaisesRegex(m.OriginHostError, "^invalid_control$"):
                await self.control.wait_release("race-release.json", committed=False)


class OwnedTests(AsyncFixture):
    async def test_cancelled_factory_waiter_retains_late_returned_client_and_closes_it(self):
        resources = m.OwnedResources()
        entered = threading.Event()
        release = threading.Event()
        events = []

        class Client:
            async def close(self):
                events.append("closed")

        client = Client()

        def factory():
            entered.set()
            release.wait(2)
            return client

        task = asyncio.create_task(resources.startup(factory, 2))
        try:
            await self.until(entered.is_set)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(resources.startup_pending, 1)
            self.assertFalse(await resources.close_once(time.monotonic() + 0.02))
            self.assertEqual(events, [])
        finally:
            release.set()
        await self.until(lambda: resources.startup_pending == 0)
        self.assertTrue(await resources.close_once(time.monotonic() + 1))
        self.assertEqual(events, ["closed"])

    async def test_tiers_retain_actual_close_after_waiter_cancel_and_preserve_order(self):
        resources = m.OwnedResources()
        events = []
        release = asyncio.Event()

        class Http:
            async def close(self):
                events.append("http_entered")
                await release.wait()
                events.append("http_closed")

        class Service:
            async def close(self):
                events.append("service")

        class Case:
            async def close(self):
                events.append("case")

        resources.add(Http(), 0)
        resources.add(Service(), 1)
        resources.add(Case(), 2)
        observer = asyncio.create_task(resources.close_once(time.monotonic() + 1))
        await self.until(lambda: events == ["http_entered"])
        observer.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await observer
        self.assertEqual([len(tier) for tier in resources.tiers], [1, 1, 1])
        self.assertFalse(await resources.close_once(time.monotonic() + 0.02))
        self.assertEqual(events, ["http_entered"])
        release.set()
        self.assertTrue(await resources.close_once(time.monotonic() + 1))
        self.assertEqual(events, ["http_entered", "http_closed", "service", "case"])

    async def test_startup_deadline_and_close_task_setup_failure_keep_actual_owners(self):
        resources = m.OwnedResources()
        entered = threading.Event()
        release = threading.Event()
        events = []

        class Client:
            async def close(self):
                events.append("client")

        client = Client()

        def factory():
            entered.set()
            release.wait(2)
            return client

        observer = asyncio.create_task(resources.startup(factory, 1, deadline=time.monotonic() + 1))
        try:
            await self.until(entered.is_set)
            with self.assertRaisesRegex(m.OriginHostError, "^deadline_exceeded$"):
                await observer
            self.assertEqual(resources.startup_pending, 1)
        finally:
            release.set()
        await self.until(lambda: resources.startup_pending == 0)
        with patch.object(
            m.asyncio, "create_task", side_effect=RuntimeError("PRIVATE_TASK_SENTINEL")
        ):
            self.assertFalse(await resources.close_once(time.monotonic() + 1))
        self.assertEqual(resources.tiers[1], [client])
        self.assertEqual(events, [])
        self.assertTrue(await resources.close_once(time.monotonic() + 1))
        self.assertEqual(events, ["client"])

    async def test_failed_owner_constructor_does_not_transfer_its_injected_port(self):
        events = []

        class Client:
            async def close(self):
                events.append("client")

        resources = m.OwnedResources()
        client = resources.add(Client(), 1)
        with self.assertRaises(RuntimeError):

            def failed():
                raise RuntimeError("PRIVATE_SENTINEL")

            resources.transfer(failed(), (client,), 1)
        self.assertIs(resources.tiers[1][0], client)
        self.assertTrue(await resources.close_once(time.monotonic() + 1))
        self.assertEqual(events, ["client"])


class HostTests(AsyncFixture):
    async def test_production_composition_uses_public_factories_and_closes_http_core_case(self):
        events = []

        class Case:
            pending_count = 0

            async def get(self, **kwargs):
                raise AssertionError("no implicit case read")

            async def close(self):
                events.append("case")

        case = Case()
        work = FakeWork(self.config, events)

        class Http:
            def __init__(self, service, *, operation_bearer, cleanup_timeout_s):
                self.service = service
                self.bearer = operation_bearer
                self.cleanup_timeout_s = cleanup_timeout_s
                self.ending = False

            async def start(self):
                return type("Endpoint", (), {"host": "127.0.0.1", "port": 12345})()

            def metrics(self):
                return {"handlers": 0, "active": 0, "sockets": 0}

            async def close(self):
                events.append("http")
                self.ending = True

        coordinator_class = m.ChannelPolicyCoordinator
        http_class = m.ChannelOriginHttp
        self.assertEqual(
            inspect.signature(coordinator_class).parameters["cleanup_ms"].default, 1000
        )
        self.assertEqual(inspect.signature(http_class).parameters["cleanup_timeout_s"].default, 1)
        host = m.OriginFixtureHost(self.runtime, self.config)
        with (
            patch.object(
                m, "ChannelPolicyCoordinator", wraps=coordinator_class
            ) as coordinator_factory,
            patch.object(m, "open_postgres_client", return_value=case) as cp,
            patch.object(m, "open_work_client", return_value=work) as wp,
            patch.object(m, "ChannelOriginHttp", Http),
        ):
            await host.start()
            self.assertEqual(cp.call_count, 1)
            self.assertEqual(wp.call_count, 1)
            self.assertEqual(coordinator_factory.call_args.kwargs["cleanup_ms"], 20)
            self.assertEqual(host.http.cleanup_timeout_s, 0.02)
            self.assertEqual(cp.call_args.kwargs["actor"].actor_id, "p3_completion_user")
            self.assertEqual(cp.call_args.kwargs["settings"].schema, self.config.case_schema)
            self.assertEqual(wp.call_args.kwargs["settings"].schema, self.config.work_schema)
            self.assertEqual(
                wp.call_args.kwargs["directory"]
                .authenticate(wp.call_args.kwargs["token"])
                .actor_id,
                "origin_fixture_actor",
            )
            self.assertEqual(
                json.loads((self.directory / (self.config.role + "-ready.json")).read_bytes()),
                {"schema_version": 1, "pid": os.getpid(), "host": "127.0.0.1", "port": 12345},
            )
            self.assertTrue(await host.close())
            self.assertTrue(await host.close())
        self.assertEqual(events, ["http", "work", "case"])
        observation = json.loads(
            (self.directory / (self.config.role + "-closed.json")).read_bytes()
        )
        self.assertTrue(observation["cleanup_complete"])
        self.assertEqual(observation["retained_owners"], [0, 0, 0])

    async def test_cancelled_host_start_keeps_late_case_owner_and_never_opens_work(self):
        entered = threading.Event()
        release = threading.Event()
        closed = []

        class Case:
            pending_count = 0

            async def close(self):
                closed.append("case")

        def factory(**kwargs):
            entered.set()
            release.wait(2)
            return Case()

        host = m.OriginFixtureHost(self.runtime, self.config)
        with (
            patch.object(m, "open_postgres_client", side_effect=factory),
            patch.object(m, "open_work_client", side_effect=AssertionError("next factory")) as wp,
        ):
            startup = asyncio.create_task(host.start())
            try:
                await self.until(entered.is_set)
                startup.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await startup
                closer = asyncio.create_task(host.close())
                await self.until(
                    (self.directory / (self.config.role + "-cleanup-incomplete.json")).exists
                )
                self.assertEqual(closed, [])
                self.assertFalse(closer.done())
            finally:
                release.set()
            self.assertTrue(await closer)
            self.assertEqual(wp.call_count, 0)
        self.assertEqual(closed, ["case"])
        self.assertFalse((self.directory / (self.config.role + "-ready.json")).exists())

    async def test_private_stop_during_factory_prevents_next_factory_and_retains_late_client(self):
        entered = threading.Event()
        release = threading.Event()
        events = []

        class Case:
            pending_count = 0

            async def close(self):
                events.append("case")

        def factory(**kwargs):
            entered.set()
            release.wait(2)
            return Case()

        host = m.OriginFixtureHost(self.runtime, self.config)
        with (
            patch.object(m, "open_postgres_client", side_effect=factory),
            patch.object(m, "open_work_client", side_effect=AssertionError("next factory")) as work,
        ):
            startup = asyncio.create_task(host.start())
            try:
                await self.until(entered.is_set)
                save(
                    self.directory / (self.config.role + "-stop.json"),
                    {"schema_version": 1, "stop": True},
                )
                with self.assertRaisesRegex(m.OriginHostError, "^closed$"):
                    await startup
                self.assertEqual(host.resources.startup_pending, 1)
                closer = asyncio.create_task(host.close())
                await self.until(
                    (self.directory / (self.config.role + "-cleanup-incomplete.json")).exists
                )
                self.assertFalse(closer.done())
                self.assertEqual(events, [])
            finally:
                release.set()
            self.assertTrue(await closer)
            self.assertEqual(work.call_count, 0)
        self.assertEqual(events, ["case"])

    async def test_failed_service_constructor_preserves_core_and_case_close_ownership(self):
        events = []

        class Case:
            pending_count = 0

            async def close(self):
                events.append("case")

        work = FakeWork(self.config, events)
        host = m.OriginFixtureHost(self.runtime, self.config)
        with (
            patch.object(m, "open_postgres_client", return_value=Case()),
            patch.object(m, "open_work_client", return_value=work),
            patch.object(
                m, "ChannelOriginService", side_effect=RuntimeError("PRIVATE_CONSTRUCTOR_SENTINEL")
            ),
        ):
            with self.assertRaisesRegex(m.OriginHostError, "^startup_failed$"):
                await host.start()
            self.assertEqual([len(tier) for tier in host.resources.tiers], [0, 1, 1])
            self.assertTrue(await host.close())
        self.assertEqual(events, ["work", "case"])

    async def test_actual_core_waiter_abandonment_blocks_case_close_until_work_settles(self):
        events = []
        entered = asyncio.Event()
        release = asyncio.Event()

        class Case:
            pending_count = 0

            async def close(self):
                events.append("case")

        class HeldWork(FakeWork):
            async def find(self, *, idempotency_key):
                self.finds.append(idempotency_key)
                self.pending_count = 1
                entered.set()
                try:
                    await release.wait()
                finally:
                    self.pending_count = 0

        class Http:
            def __init__(self, service, *, operation_bearer, cleanup_timeout_s):
                pass

            async def start(self):
                return type("Endpoint", (), {"host": "127.0.0.1", "port": 12345})()

            def metrics(self):
                return {"handlers": 0, "active": 0, "sockets": 0}

            async def close(self):
                events.append("http")

        work = HeldWork(self.config, events)
        host = m.OriginFixtureHost(self.runtime, self.config)
        with (
            patch.object(m, "open_postgres_client", return_value=Case()),
            patch.object(m, "open_work_client", return_value=work),
            patch.object(m, "ChannelOriginHttp", Http),
        ):
            await host.start()
            query = json.dumps(
                {
                    "operationKey": self.config.operation_key,
                    "scope": {
                        "tenantId": self.config.scope.tenant_id,
                        "accountId": self.config.scope.account_id,
                    },
                    "payloadDigest": "a" * 64,
                },
                separators=(",", ":"),
            ).encode()
            caller = asyncio.create_task(host.service.lookup(query))
            await entered.wait()
            caller.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await caller
            self.assertEqual(host.coordinator.pending_count, 1)
            self.assertEqual(work.pending_count, 1)
            closer = asyncio.create_task(host.close())
            try:
                marker = self.directory / (self.config.role + "-cleanup-incomplete.json")
                await self.until(marker.exists)
                observation = json.loads(marker.read_bytes())
                self.assertEqual(observation["coordinator_pending"], 1)
                self.assertEqual(observation["work_pending"], 1)
                self.assertEqual(events, ["http"])
                self.assertFalse(closer.done())
            finally:
                release.set()
            self.assertTrue(await closer)
        self.assertEqual(events, ["http", "work", "case"])
        self.assertEqual(len(work.finds), 1)

    async def test_serve_registers_stop_without_real_signals_and_never_masks_primary_failure(self):
        loop = asyncio.get_running_loop()
        for primary, complete in ((False, True), (False, False), (True, False)):
            callbacks = {}
            removed = []
            output = io.StringIO()

            class Host:
                def __init__(self, runtime, config):
                    self.stopped = False

                def request_stop(self):
                    self.stopped = True

                async def start(self, primary=primary):
                    if primary:
                        raise RuntimeError("PRIVATE_STARTUP_SENTINEL")

                async def wait_stop(self, callbacks=callbacks):
                    callbacks[m.signal.SIGTERM]()
                    self.assert_stopped()

                def assert_stopped(self):
                    if not self.stopped:
                        raise AssertionError("stop missing")

                async def close(self, complete=complete):
                    return complete

            with (
                patch.object(m, "OriginFixtureHost", Host),
                patch.object(
                    loop,
                    "add_signal_handler",
                    side_effect=lambda sig, callback, callbacks=callbacks: callbacks.update(
                        {sig: callback}
                    ),
                ),
                patch.object(
                    loop,
                    "remove_signal_handler",
                    side_effect=lambda sig, removed=removed: removed.append(sig),
                ),
                contextlib.redirect_stdout(output),
            ):
                code = await m.serve(self.runtime, self.config)
            value = json.loads(output.getvalue())
            self.assertEqual(code, 0 if complete and not primary else 1)
            self.assertEqual(value["cleanup_complete"], complete)
            self.assertEqual(
                value["code"],
                "startup_failed" if primary else "ok" if complete else "cleanup_incomplete",
            )
            self.assertEqual(removed, [m.signal.SIGTERM])
            self.assertNotIn("PRIVATE_STARTUP_SENTINEL", output.getvalue())

    async def test_expired_cleanup_does_not_publish_false_success(self):
        config = replace(self.config, parent_deadline_monotonic=time.monotonic() - 1)
        host = m.OriginFixtureHost(self.runtime, config)
        self.assertFalse(await host.close())
        self.assertFalse((self.directory / (config.role + "-closed.json")).exists())
        self.assertFalse(
            json.loads((self.directory / (config.role + "-cleanup-incomplete.json")).read_bytes())[
                "cleanup_complete"
            ]
        )
