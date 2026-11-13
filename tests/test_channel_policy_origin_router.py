"""Real public P3 coordinators with typed fake P1/P2 ports; no DB/providers/RTC."""

from __future__ import annotations

import asyncio
import copy
import gc
import hashlib
import json
import subprocess
import sys
import time
import unittest
import warnings
from dataclasses import FrozenInstanceError, replace
from inspect import markcoroutinefunction
from pathlib import Path
from typing import cast
from unittest.mock import patch
from uuid import uuid4

from continuity_lab.work_api import (
    TaskExecutionPort,
    WorkCancellation,
    WorkError,
    WorkPayload,
    WorkRecord,
    WorkScope,
    WorkSubmission,
)
from delegation_reliability import (
    ChannelPolicyCoordinator,
    CoordinatorError,
    encode_channel_policy_request,
    parse_channel_policy_request,
    produce_channel_policy_request,
)
from delegation_reliability.contracts import Scope
from delegation_reliability.coordinator import CaseAuthorityPort, CaseSnapshot
from delegation_reliability.fixed_policy_contracts import (
    FixedPolicyRequest,
    produce_fixed_policy_request,
)
from services.channel_policy_demo import origin_router as m
from services.channel_policy_demo.discovery import (
    DiscoveryItem,
    DiscoveryPage,
    DiscoveryScope,
    SourceBindingId,
)
from services.channel_policy_demo.origin_http import ChannelOriginPort
from services.channel_policy_demo.wire import parse_accept_frame

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "contracts/delegation/fixed-policy-v2.json").read_bytes())


def encoded(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def template(revision: int = 1, version: str = "facts_v1") -> FixedPolicyRequest:
    raw = copy.deepcopy(FIXTURE["producer_input"])
    raw["request_revision"] = revision
    raw["evidence"][1]["version"] = version
    raw["deadline_at_ms"] = time.time_ns() // 1000000 + 30000
    return produce_fixed_policy_request(raw)


def frame(revision: int = 1, sender: str | None = None) -> bytes:
    value = {
        "schemaVersion": 1,
        "kind": "investigation",
        "operationKey": str(uuid4()),
        "scope": {"tenantId": "tenant_demo", "accountId": "account_demo"},
        "caseId": "case_demo",
        "caseRevision": str(revision),
        "conversationId": "conversation_demo",
        "message": {
            "receiptId": str(uuid4()),
            "eventId": str(uuid4()),
            "messageId": str(uuid4()),
            "senderId": str(uuid4()) if sender is None else sender,
            "body": "Original café 🧭; investigate only.",
        },
    }
    return wrap(value)


def wrap(value: object) -> bytes:
    payload = encoded(value)
    return encoded(
        {
            "schemaVersion": 1,
            "canonicalPayload": payload.decode(),
            "payloadDigest": hashlib.sha256(payload).hexdigest(),
        }
    )


def query(raw: bytes) -> bytes:
    return encoded(parse_accept_frame(raw).lookup().to_wire())


class Discovery:
    def __init__(self, binding: m.OriginRouterBinding) -> None:
        self.page = DiscoveryPage(
            binding.profile_id,
            DiscoveryScope(binding.scope.tenant_id, binding.scope.account_id),
            binding.case_id,
            binding.conversation_id,
            "2026-11-13T00:00:00.000Z",
            (),
            False,
            None,
        )
        self.calls = 0
        self.release: asyncio.Event | None = None
        self.entered = asyncio.Event()

    async def read(self) -> DiscoveryPage:
        self.calls += 1
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        return self.page


class Prepared:
    """Stored provider chooses role; caller expected role only checks consistency."""

    def __init__(self) -> None:
        self.plans: dict[str, tuple[SourceBindingId, bytes | None]] = {}
        self.calls: list[tuple[SourceBindingId, str]] = []
        self.release: asyncio.Event | None = None
        self.entered = asyncio.Event()
        self.error: Exception | None = None

    def add(self, raw: bytes, source: SourceBindingId = "native") -> None:
        self.plans[parse_accept_frame(raw).input_receipt_id] = source, raw

    async def read(self, *, source_binding_id: SourceBindingId, receipt_id: str) -> bytes | None:
        self.calls.append((source_binding_id, receipt_id))
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        if receipt_id not in self.plans:
            raise CoordinatorError("not_found")
        source, raw = self.plans[receipt_id]
        if source != source_binding_id:
            raise CoordinatorError("unauthorized")
        return raw


class Cases:
    def __init__(self, binding: m.OriginRouterBinding) -> None:
        self.current = CaseSnapshot(binding.scope, binding.case_id, 1, False)
        self.calls = 0

    async def snapshot(self, *, case_id: str) -> CaseSnapshot:
        self.calls += 1
        if case_id != self.current.case_id:
            raise CoordinatorError("not_found")
        return self.current


class Ledger:
    def __init__(self) -> None:
        self.records: dict[str, WorkRecord] = {}
        self.lock = asyncio.Lock()


class Work:
    def __init__(self, scope: Scope, ledger: Ledger) -> None:
        self.scope, self.ledger = WorkScope(scope.tenant_id, scope.account_id), ledger
        self.finds = self.submits = self.closed = self.pending_count = 0
        self.find_release: asyncio.Event | None = None
        self.submit_release: asyncio.Event | None = None
        self.close_release: asyncio.Event | None = None
        self.find_entered, self.submit_entered, self.close_entered = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )
        self.fail_close = False
        self.ack_loss = False
        self.swap_second = False
        self.second_read: WorkRecord | None = None

    async def find(self, *, idempotency_key: str) -> WorkRecord | None:
        self.finds += 1
        self.pending_count += 1
        self.find_entered.set()
        try:
            if self.find_release is not None:
                await self.find_release.wait()
            if self.swap_second and self.finds == 2:
                return self.second_read
            return self.ledger.records.get(idempotency_key)
        finally:
            self.pending_count -= 1

    async def submit(self, *, idempotency_key: str, payload: WorkPayload) -> WorkSubmission:
        self.submits += 1
        self.pending_count += 1
        self.submit_entered.set()
        try:
            if self.submit_release is not None:
                await self.submit_release.wait()
            async with self.ledger.lock:
                old = self.ledger.records.get(idempotency_key)
                if old is not None:
                    if old.payload != payload:
                        raise WorkError("identity_conflict")
                    return WorkSubmission(old, False)
                record = WorkRecord(
                    str(uuid4()),
                    self.scope,
                    idempotency_key,
                    payload,
                    time.time_ns() // 1000000,
                    False,
                )
                self.ledger.records[idempotency_key] = record
                if self.ack_loss:
                    raise WorkError("acknowledgement_unknown")
                return WorkSubmission(record, True)
        finally:
            self.pending_count -= 1

    async def get(self, *, work_id: str) -> WorkRecord:
        raise AssertionError("router only finds by original operation")

    async def cancel(self, *, work_id: str, command_id: str) -> WorkCancellation:
        raise AssertionError("no business cancellation authority")

    async def close(self) -> None:
        self.close_entered.set()
        if self.close_release is not None:
            await self.close_release.wait()
        if self.fail_close:
            raise WorkError("cleanup_incomplete")
        if self.pending_count:
            raise AssertionError("client closed under actual P1 call")
        self.closed += 1


class Factory:
    def __init__(self, binding: m.OriginRouterBinding, cases: Cases, ledger: Ledger) -> None:
        self.binding, self.cases, self.ledger = binding, cases, ledger
        self.calls = 0
        self.clients: list[Work] = []
        self.cores: list[ChannelPolicyCoordinator] = []
        self.release: asyncio.Event | None = None
        self.entered = asyncio.Event()
        self.error: BaseException | None = None
        self.returned: ChannelPolicyCoordinator | None = None
        self.find_release: asyncio.Event | None = None
        self.submit_release: asyncio.Event | None = None
        self.close_release: asyncio.Event | None = None
        self.busy = False
        self.tasks: list[asyncio.Task[object]] = []
        self.scope = binding.scope
        self.swap_second = False
        self.second_read: WorkRecord | None = None

    async def open(self) -> ChannelPolicyCoordinator:
        self.calls += 1
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        if self.returned is not None:
            return self.returned
        client = Work(self.scope, self.ledger)
        client.swap_second, client.second_read = self.swap_second, self.second_read
        client.find_release, client.submit_release, client.close_release = (
            self.find_release,
            self.submit_release,
            self.close_release,
        )
        work: TaskExecutionPort = client
        cases: CaseAuthorityPort = self.cases
        core = ChannelPolicyCoordinator(
            executions=work,
            scope=self.scope,
            case_authority=cases,
            max_active=1,
            timeout_ms=500,
            cleanup_ms=20,
        )
        self.clients.append(client)
        self.cores.append(core)
        if self.busy:
            task = asyncio.create_task(core.find("p2_busy"))
            self.tasks.append(cast(asyncio.Task[object], task))
            await client.find_entered.wait()
        return core


async def until(predicate) -> None:
    async with asyncio.timeout(1):
        while not predicate():
            await asyncio.sleep(0)


class RouterTests(unittest.IsolatedAsyncioTestCase):
    def configure(self, *, revisions: tuple[int, ...] = (1, 2), **options) -> m.ChannelOriginRouter:
        self.binding = m.OriginRouterBinding(
            str(uuid4()), Scope("tenant_demo", "account_demo"), "case_demo", "conversation_demo"
        )
        self.discovery, self.prepared = Discovery(self.binding), Prepared()
        self.cases, self.ledger = Cases(self.binding), Ledger()
        self.factory = Factory(self.binding, self.cases, self.ledger)
        discovery: m.DiscoveryPort = self.discovery
        prepared: m.PreparedReadPort = self.prepared
        factory: m.CoordinatorFactory = self.factory
        self.router = m.ChannelOriginRouter(
            binding=self.binding,
            discovery=discovery,
            prepared=prepared,
            templates=m.RevisionTemplateCatalog(
                tuple(template(revision, "facts_" + str(revision)) for revision in revisions)
            ),
            coordinators=factory,
            **options,
        )
        native: ChannelOriginPort = self.router.native
        sms: ChannelOriginPort = self.router.sms
        self.assertIs(native, self.router.native)
        self.assertIs(sms, self.router.sms)
        return self.router

    async def asyncTearDown(self) -> None:
        if not hasattr(self, "router"):
            return
        for event in (
            self.discovery.release,
            self.prepared.release,
            self.factory.release,
            self.factory.find_release,
            self.factory.submit_release,
            self.factory.close_release,
        ):
            if event is not None:
                event.set()
        for client in self.factory.clients:
            client.fail_close = False
            for event in (client.find_release, client.submit_release, client.close_release):
                if event is not None:
                    event.set()
        if self.factory.tasks:
            await asyncio.gather(*self.factory.tasks, return_exceptions=True)
        for _ in range(4):
            try:
                await self.router.close()
                break
            except CoordinatorError:
                await asyncio.sleep(0)
        self.assertEqual(self.router.pending_count, 0)

    async def test_native_sms_and_fresh_native_sender_revision_use_real_coordinators(self) -> None:
        router = self.configure()
        a, c, b = frame(), frame(sender="signed_sender"), frame(2)
        self.prepared.add(a)
        self.prepared.add(c, "sms")
        self.prepared.add(b)
        first = await router.native.accept(a)
        sms = await router.sms.accept(c)
        self.cases.current = replace(self.cases.current, request_revision=2)
        last = await router.native.accept(b)
        await router.close()
        self.assertEqual(len({first["receiptId"], sms["receiptId"], last["receiptId"]}), 3)
        self.assertNotEqual(parse_accept_frame(a).sender_id, parse_accept_frame(b).sender_id)
        self.assertEqual([client.closed for client in self.factory.clients], [1, 1, 1])
        self.assertEqual(sum(client.submits for client in self.factory.clients), 3)
        self.assertEqual(
            [parse_accept_frame(raw).case_revision for raw in (a, c, b)], ["1", "1", "2"]
        )
        self.assertEqual(
            self.prepared.calls,
            [
                ("native", parse_accept_frame(a).input_receipt_id),
                ("sms", parse_accept_frame(c).input_receipt_id),
                ("native", parse_accept_frame(b).input_receipt_id),
            ],
        )

    async def test_known_accept_and_lookup_preserve_winner_after_template_eviction_case_change_and_expiry(
        self,
    ) -> None:
        router = self.configure(deadline_window_ms=20)
        raw = frame()
        self.prepared.add(raw)
        receipt = await router.native.accept(raw)
        original = next(iter(self.ledger.records.values())).payload.body
        await router.close()
        self.cases.current = replace(self.cases.current, request_revision=2)
        await asyncio.sleep(0.03)
        router = m.ChannelOriginRouter(
            binding=self.binding,
            discovery=self.discovery,
            prepared=self.prepared,
            templates=m.RevisionTemplateCatalog((template(2, "new_facts"),)),
            coordinators=self.factory,
            deadline_window_ms=60000,
        )
        self.router = router
        self.assertEqual(await router.native.accept(raw), receipt)
        self.assertEqual(await router.native.lookup(query(raw)), receipt)
        self.assertEqual(next(iter(self.ledger.records.values())).payload.body, original)
        await router.close()
        self.assertEqual(sum(client.submits for client in self.factory.clients), 1)

    async def test_wrong_fixed_source_cannot_accept_or_lookup_another_source(self) -> None:
        router = self.configure()
        raw = frame(sender="sms_sender")
        self.prepared.add(raw, "sms")
        with self.assertRaisesRegex(CoordinatorError, "^unauthorized$"):
            await router.native.accept(raw)
        self.assertEqual(self.factory.calls, 0)
        receipt = await router.sms.accept(raw)
        with self.assertRaisesRegex(CoordinatorError, "^unauthorized$"):
            await router.native.lookup(query(raw))
        self.assertEqual(await router.sms.lookup(query(raw)), receipt)
        self.assertEqual(sum(client.submits for client in self.factory.clients), 1)

    async def test_changed_original_frame_is_denied_before_factory_or_submit(self) -> None:
        router = self.configure()
        raw = frame()
        self.prepared.add(raw)
        original = json.loads(json.loads(raw)["canonicalPayload"])
        for key in ("body", "senderId", "eventId", "messageId"):
            changed = copy.deepcopy(original)
            changed["message"][key] = "changed"
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(CoordinatorError, "^identity_conflict$"),
            ):
                await router.native.accept(wrap(changed))
        self.assertEqual((self.factory.calls, self.ledger.records), (0, {}))
        self.assertIsInstance(await router.native.accept(raw), dict)

    async def test_foreign_scope_route_unsupported_revision_and_bad_frame_fail_before_reads(
        self,
    ) -> None:
        router = self.configure()
        original = json.loads(json.loads(frame())["canonicalPayload"])
        for key, value in (
            ("caseId", "foreign_case"),
            ("conversationId", "foreign_conversation"),
            ("scope", {"tenantId": "foreign", "accountId": "account_demo"}),
            ("caseRevision", "0"),
        ):
            changed = copy.deepcopy(original)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(CoordinatorError):
                await router.native.accept(wrap(changed))
        for raw in (b"{}", b'{"schemaVersion":1,"schemaVersion":1}', b"x" * 32769):
            with self.assertRaisesRegex(CoordinatorError, "^invalid_input$"):
                await router.native.accept(raw)
        self.assertEqual((self.prepared.calls, self.factory.calls), ([], 0))

    async def test_profile_preflight_uses_real_discovery_and_reserved_read_without_sender(
        self,
    ) -> None:
        router = self.configure()
        raw = encoded({"schemaVersion": 1, "profileId": self.binding.profile_id})
        with patch.object(
            m, "ChannelOriginService", side_effect=AssertionError("fake preflight sender")
        ):
            await router.native.inspect_profile(raw)
            await router.sms.inspect_profile(raw)
        self.assertEqual((self.discovery.calls, self.prepared.calls), (2, []))
        self.assertEqual([client.finds for client in self.factory.clients], [1, 1])
        self.assertEqual(self.ledger.records, {})

    async def test_profile_rejects_wrong_profile_foreign_ready_page_and_overflow_before_factory(
        self,
    ) -> None:
        router = self.configure()
        with self.assertRaisesRegex(CoordinatorError, "^unauthorized$"):
            await router.native.inspect_profile(
                encoded({"schemaVersion": 1, "profileId": str(uuid4())})
            )
        self.assertEqual(self.discovery.calls, 0)
        actual = self.discovery.page
        self.discovery.page = replace(actual, conversation_id="foreign")
        with self.assertRaisesRegex(CoordinatorError, "^unauthorized$"):
            await router.native.inspect_profile(
                encoded({"schemaVersion": 1, "profileId": self.binding.profile_id})
            )
        items = tuple(
            DiscoveryItem(str(uuid4()), str(uuid4()), str(i + 1), "native", "pending", False, None)
            for i in range(16)
        )
        self.discovery.page = replace(actual, items=items, overflow=True, next_cursor="16")
        with self.assertRaisesRegex(CoordinatorError, "^capacity$"):
            await router.sms.inspect_profile(
                encoded({"schemaVersion": 1, "profileId": self.binding.profile_id})
            )
        self.assertEqual(self.factory.calls, 0)
        self.discovery.page = actual
        await router.native.inspect_profile(
            encoded({"schemaVersion": 1, "profileId": self.binding.profile_id})
        )

    async def test_final_lookup_read_revalidates_all_origin_and_immutable_work_fields_then_replays_honestly(
        self,
    ) -> None:
        router = self.configure()
        raw = frame()
        self.prepared.add(raw)
        receipt = await router.native.accept(raw)
        await until(lambda: self.factory.clients[-1].closed == 1)
        original = next(iter(self.ledger.records.values()))
        variants: list[WorkRecord | None] = [None, replace(original, work_id=str(uuid4()))]
        for field, value in (
            ("input_receipt_id", str(uuid4())),
            ("payload_byte_length", 1),
            ("profile_id", str(uuid4())),
        ):
            producer = parse_channel_policy_request(original.payload.body).to_wire()
            producer.pop("input_fingerprint")
            producer["origin"][field] = value
            changed = produce_channel_policy_request(producer)
            variants.append(
                replace(
                    original,
                    payload=WorkPayload(
                        "booking.evaluate_policy",
                        encode_channel_policy_request(changed),
                        changed.deadline_at_ms,
                    ),
                )
            )
        for field in ("evidence", "deadline"):
            request = parse_channel_policy_request(original.payload.body)
            inner = request.request.to_wire()
            inner.pop("input_fingerprint")
            if field == "evidence":
                inner["evidence"][1]["version"] = "coordinated_different_facts"
            else:
                inner["deadline_at_ms"] += 1
            outer = request.to_wire()
            outer.pop("input_fingerprint")
            outer["request"] = produce_fixed_policy_request(inner).to_wire()
            changed = produce_channel_policy_request(outer)
            variants.append(
                replace(
                    original,
                    payload=WorkPayload(
                        "booking.evaluate_policy",
                        encode_channel_policy_request(changed),
                        changed.deadline_at_ms,
                    ),
                )
            )
        for returned in variants:
            self.factory.swap_second, self.factory.second_read = True, returned
            with self.assertRaises(CoordinatorError):
                await router.native.lookup(query(raw))
            client = self.factory.clients[-1]
            self.assertEqual((client.finds, client.submits), (2, 0))
            await until(lambda client=client: client.closed == 1)
            self.factory.second_read = original
            self.assertEqual(await router.native.lookup(query(raw)), receipt)
            client = self.factory.clients[-1]
            self.assertEqual((client.finds, client.submits), (2, 0))
            await until(lambda client=client: client.closed == 1)
        self.assertEqual(sum(client.submits for client in self.factory.clients), 1)

    async def test_static_method_snapshots_never_invoke_owner_getters_and_survive_replacement(
        self,
    ) -> None:
        self.configure()
        await self.router.close()
        hits = 0

        class GuardedDiscovery(Discovery):
            def __getattribute__(self, name):
                nonlocal hits
                if name == "read":
                    hits += 1
                    raise RuntimeError("PRIVATE_DISCOVERY_GETTER")
                return object.__getattribute__(self, name)

        class GuardedPrepared(Prepared):
            def __getattribute__(self, name):
                nonlocal hits
                if name == "read":
                    hits += 1
                    raise RuntimeError("PRIVATE_PREPARED_GETTER")
                return object.__getattribute__(self, name)

        class GuardedFactory(Factory):
            def __getattribute__(self, name):
                nonlocal hits
                if name == "open":
                    hits += 1
                    raise RuntimeError("PRIVATE_FACTORY_GETTER")
                return object.__getattribute__(self, name)

        self.discovery, self.prepared = GuardedDiscovery(self.binding), GuardedPrepared()
        self.factory = GuardedFactory(self.binding, self.cases, self.ledger)
        router = m.ChannelOriginRouter(
            binding=self.binding,
            discovery=self.discovery,
            prepared=self.prepared,
            templates=m.RevisionTemplateCatalog((template(),)),
            coordinators=self.factory,
        )
        self.router = router

        async def replaced(*args, **kwargs):
            nonlocal hits
            hits += 1
            raise AssertionError("replacement should not be invoked")

        self.discovery.read = replaced
        self.prepared.read = replaced
        self.factory.open = replaced
        raw = frame()
        self.prepared.add(raw)
        await router.native.accept(raw)
        await router.native.inspect_profile(
            encoded({"schemaVersion": 1, "profileId": self.binding.profile_id})
        )
        self.assertEqual(hits, 0)
        await router.close()
        # Explicit static/class/bound-method support, without an owner getter.
        discovery, prepared, factory = (
            Discovery(self.binding),
            Prepared(),
            Factory(self.binding, self.cases, self.ledger),
        )

        class StaticDiscovery:
            @staticmethod
            async def read():
                return await discovery.read()

        class ClassPrepared:
            @classmethod
            async def read(cls, *, source_binding_id, receipt_id):
                return await prepared.read(
                    source_binding_id=source_binding_id, receipt_id=receipt_id
                )

        class BoundFactory:
            pass

        bound = BoundFactory()
        bound.open = factory.open
        router = m.ChannelOriginRouter(
            binding=self.binding,
            discovery=cast(m.DiscoveryPort, StaticDiscovery()),
            prepared=cast(m.PreparedReadPort, ClassPrepared()),
            templates=m.RevisionTemplateCatalog((template(),)),
            coordinators=cast(m.CoordinatorFactory, bound),
        )
        self.router, self.discovery, self.prepared, self.factory = (
            router,
            discovery,
            prepared,
            factory,
        )
        raw = frame()
        prepared.add(raw)
        await router.native.accept(raw)
        await router.native.inspect_profile(
            encoded({"schemaVersion": 1, "profileId": self.binding.profile_id})
        )
        await router.close()
        self.assertEqual(hits, 0)

    async def test_missing_plan_and_new_uncatalogued_revision_never_submit(self) -> None:
        router = self.configure(revisions=(1,))
        raw = frame(2)
        self.prepared.add(raw)
        with self.assertRaisesRegex(CoordinatorError, "^case_state_unavailable$"):
            await router.native.accept(raw)
        self.prepared.plans[parse_accept_frame(raw).input_receipt_id] = "native", None
        with self.assertRaisesRegex(CoordinatorError, "^not_found$"):
            await router.native.accept(raw)
        self.assertEqual(sum(client.submits for client in self.factory.clients), 0)
        good = frame()
        self.prepared.add(good)
        await router.native.accept(good)

    async def test_new_stale_revision_denied_by_public_case_authority_then_current_work_progresses(
        self,
    ) -> None:
        router = self.configure()
        self.cases.current = replace(self.cases.current, request_revision=2)
        stale, current = frame(), frame(2)
        self.prepared.add(stale)
        self.prepared.add(current)
        with self.assertRaisesRegex(CoordinatorError, "^case_changed$"):
            await router.native.accept(stale)
        self.assertEqual(self.ledger.records, {})
        await router.native.accept(current)
        self.assertEqual(len(self.ledger.records), 1)

    async def test_global_two_factory_slots_remain_after_cancelled_waiters_and_late_returns_close_once(
        self,
    ) -> None:
        router = self.configure(cleanup_timeout_s=0.02)
        self.factory.release = asyncio.Event()
        a, c = frame(), frame(sender="sms_sender")
        self.prepared.add(a)
        self.prepared.add(c, "sms")
        waiters = [
            asyncio.create_task(router.native.accept(a)),
            asyncio.create_task(router.sms.accept(c)),
        ]
        await until(lambda: self.factory.calls == 2)
        with self.assertRaisesRegex(CoordinatorError, "^capacity$"):
            await router.native.lookup(query(a))
        for waiter in waiters:
            waiter.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)
        with self.assertRaisesRegex(CoordinatorError, "^cleanup_incomplete$"):
            await router.close()
        self.assertEqual(router.pending_count, 2)
        self.factory.release.set()
        await router.close()
        self.assertEqual([client.closed for client in self.factory.clients], [1, 1])
        self.assertEqual(sum(client.finds + client.submits for client in self.factory.clients), 0)

    async def test_two_actual_call_and_close_slots_are_shared_by_fixed_facets(self) -> None:
        for stage in ("submit", "close"):
            with self.subTest(stage=stage):
                router = self.configure()
                gate = asyncio.Event()
                if stage == "submit":
                    self.factory.submit_release = gate
                else:
                    self.factory.close_release = gate
                a, c = frame(), frame(sender="signed_sender")
                self.prepared.add(a)
                self.prepared.add(c, "sms")
                waiting = [
                    asyncio.create_task(router.native.accept(a)),
                    asyncio.create_task(router.sms.accept(c)),
                ]
                await until(lambda: len(self.factory.clients) == 2)
                if stage == "submit":
                    await asyncio.gather(
                        *(client.submit_entered.wait() for client in self.factory.clients)
                    )
                else:
                    await asyncio.gather(*waiting)
                    await asyncio.gather(
                        *(client.close_entered.wait() for client in self.factory.clients)
                    )
                    await until(lambda router=router: router.metrics()["cleanup_incomplete"] >= 2)
                self.assertEqual(router.pending_count, 2)
                with self.assertRaisesRegex(CoordinatorError, "^capacity$"):
                    await router.native.lookup(query(a))
                self.assertEqual(self.factory.calls, 2)
                gate.set()
                await asyncio.gather(*waiting)
                await router.close()
                self.assertEqual([client.closed for client in self.factory.clients], [1, 1])
                self.assertEqual(sum(client.submits for client in self.factory.clients), 2)

    async def test_late_outer_find_cannot_start_accept_after_observer_deadline(self) -> None:
        router = self.configure(timeout_s=0.02)
        raw = frame()
        self.prepared.add(raw)
        self.factory.find_release = asyncio.Event()
        with self.assertRaisesRegex(CoordinatorError, "^deadline_exceeded$"):
            await router.native.accept(raw)
        self.assertEqual(
            (router.pending_count, sum(client.submits for client in self.factory.clients)), (1, 0)
        )
        self.factory.find_release.set()
        await until(lambda: self.factory.clients[0].closed == 1)
        self.assertEqual(self.ledger.records, {})
        await router.native.accept(raw)
        await router.close()
        self.assertEqual(sum(client.submits for client in self.factory.clients), 1)

    async def test_abandoned_attestation_retains_slot_and_prevents_later_factory(self) -> None:
        router = self.configure(timeout_s=0.02)
        raw = frame()
        self.prepared.add(raw)
        self.prepared.release = asyncio.Event()
        with self.assertRaisesRegex(CoordinatorError, "^deadline_exceeded$"):
            await router.native.accept(raw)
        self.assertEqual((router.pending_count, self.factory.calls), (1, 0))
        self.prepared.release.set()
        await until(lambda: router.metrics()["failed"] == 1)
        self.assertIsInstance(await router.native.accept(raw), dict)
        await router.close()
        self.assertEqual(self.factory.calls, 1)

    async def test_already_started_accept_keeps_uncertain_commit_and_close_ownership(self) -> None:
        router = self.configure(timeout_s=0.02, cleanup_timeout_s=0.02)
        raw = frame()
        self.prepared.add(raw)
        self.factory.submit_release = asyncio.Event()
        with self.assertRaisesRegex(CoordinatorError, "^acknowledgement_unknown$"):
            await router.native.accept(raw)
        self.assertEqual(sum(client.submits for client in self.factory.clients), 1)
        with self.assertRaisesRegex(CoordinatorError, "^cleanup_incomplete$"):
            await router.close()
        self.assertEqual(router.pending_count, 1)
        self.factory.submit_release.set()
        await router.close()
        self.assertEqual((len(self.ledger.records), self.factory.clients[0].closed), (1, 1))
        self.assertEqual(sum(client.submits for client in self.factory.clients), 1)

    async def test_successful_receipt_is_not_erased_by_actual_close_still_held(self) -> None:
        router = self.configure(cleanup_timeout_s=0.02)
        raw = frame()
        self.prepared.add(raw)
        self.factory.close_release = asyncio.Event()
        receipt = await router.native.accept(raw)
        await self.factory.clients[0].close_entered.wait()
        self.assertIn("receiptId", receipt)
        self.assertEqual(router.pending_count, 1)
        with self.assertRaisesRegex(CoordinatorError, "^cleanup_incomplete$"):
            await router.close()
        self.factory.close_release.set()
        await until(lambda: self.factory.clients[0].closed == 1)
        await router.close()
        self.assertEqual(self.factory.clients[0].closed, 1)

    async def test_fresh_busy_coordinator_is_quarantined_until_actual_p1_io_settles(self) -> None:
        router = self.configure(cleanup_timeout_s=0.02)
        raw = frame()
        self.prepared.add(raw)
        self.factory.find_release = asyncio.Event()
        self.factory.busy = True
        with self.assertRaisesRegex(CoordinatorError, "^invalid_input$"):
            await router.native.accept(raw)
        with self.assertRaisesRegex(CoordinatorError, "^cleanup_incomplete$"):
            await router.close()
        self.assertEqual((router.pending_count, self.factory.clients[0].closed), (1, 0))
        self.factory.find_release.set()
        await asyncio.gather(*self.factory.tasks, return_exceptions=True)
        await router.close()
        self.assertEqual((router.pending_count, self.factory.clients[0].closed), (0, 1))

    async def test_fresh_malformed_return_keeps_slot_until_close_and_pending_can_be_observed(
        self,
    ) -> None:
        router = self.configure(cleanup_timeout_s=0.02)
        raw = frame()
        self.prepared.add(raw)

        class Partial:
            broken = True
            closes = 0

            @property
            def pending_count(self) -> int:
                if self.broken:
                    raise RuntimeError("PRIVATE_PENDING_SENTINEL")
                return 0

            async def close(self) -> None:
                self.closes += 1

        returned = Partial()
        self.factory.returned = cast(ChannelPolicyCoordinator, returned)
        with self.assertRaisesRegex(CoordinatorError, "^invalid_input$"):
            await router.native.accept(raw)
        with self.assertRaisesRegex(CoordinatorError, "^cleanup_incomplete$"):
            await router.close()
        self.assertEqual(router.pending_count, 1)
        returned.broken = False
        await router.close()
        self.assertEqual(router.pending_count, 0)
        self.assertGreater(returned.closes, 0)
        self.assertEqual(self.ledger.records, {})

    async def test_catalogue_and_binding_are_private_copies_of_original_configuration(self) -> None:
        router = self.configure()
        await router.close()
        original = template()
        profile = self.binding.profile_id
        router = m.ChannelOriginRouter(
            binding=self.binding,
            discovery=self.discovery,
            prepared=self.prepared,
            templates=m.RevisionTemplateCatalog((original,)),
            coordinators=self.factory,
        )
        self.router = router
        object.__setattr__(original.evidence[1], "version", "replaced_by_caller")
        object.__setattr__(self.binding, "profile_id", str(uuid4()))
        raw = frame()
        self.prepared.add(raw)
        await router.native.accept(raw)
        request = parse_channel_policy_request(
            next(iter(self.ledger.records.values())).payload.body
        )
        self.assertEqual(
            (request.origin.profile_id, request.request.evidence[1].version), (profile, "facts_v1")
        )

    async def test_known_full_origin_cannot_be_coordinately_replaced_in_p1_only(self) -> None:
        router = self.configure()
        raw = frame()
        self.prepared.add(raw)
        await router.native.accept(raw)
        key, original = next(iter(self.ledger.records.items()))
        for field, value in (
            ("input_receipt_id", str(uuid4())),
            ("payload_sha256", "0" * 64),
            ("payload_byte_length", 1),
            ("profile_id", str(uuid4())),
        ):
            request = parse_channel_policy_request(original.payload.body)
            producer = request.to_wire()
            producer.pop("input_fingerprint")
            producer["origin"][field] = value
            changed = produce_channel_policy_request(producer)
            self.ledger.records[key] = replace(
                original,
                payload=WorkPayload(
                    "booking.evaluate_policy",
                    encode_channel_policy_request(changed),
                    changed.deadline_at_ms,
                ),
            )
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(CoordinatorError, "^identity_conflict$"),
            ):
                await router.native.accept(raw)
        self.ledger.records[key] = original
        self.assertEqual((await router.native.lookup(query(raw)))["receiptId"], original.work_id)

    async def test_commit_ack_loss_reconciles_original_key_once(self) -> None:
        router = self.configure()
        raw = frame()
        self.prepared.add(raw)
        self.factory.submit_release = asyncio.Event()
        waiter = asyncio.create_task(router.native.accept(raw))
        await until(lambda: bool(self.factory.clients))
        client = self.factory.clients[0]
        await client.submit_entered.wait()
        client.ack_loss = True
        self.factory.submit_release.set()
        receipt = await waiter
        self.assertEqual(receipt["receiptId"], next(iter(self.ledger.records.values())).work_id)
        self.assertEqual(client.submits, 1)

    async def test_cancelled_close_waiter_does_not_cancel_an_already_started_accept(self) -> None:
        router = self.configure()
        raw = frame()
        self.prepared.add(raw)
        self.factory.submit_release = asyncio.Event()
        accepting = asyncio.create_task(router.native.accept(raw))
        await until(lambda: bool(self.factory.clients))
        await self.factory.clients[0].submit_entered.wait()
        closing = asyncio.create_task(router.close())
        await asyncio.sleep(0)
        closing.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await closing
        self.assertEqual(router.pending_count, 1)
        self.factory.submit_release.set()
        self.assertIn("receiptId", await accepting)
        await router.close()
        self.assertEqual((router.pending_count, self.factory.clients[0].closed), (0, 1))

    async def test_dependency_code_getter_is_never_invoked_or_reflected(self) -> None:
        router = self.configure()
        raw = frame()
        self.prepared.add(raw)
        hits = 0

        class Hostile(CoordinatorError):
            def __init__(self):
                RuntimeError.__init__(self, "PRIVATE_ARGS")

            @property
            def code(self):
                nonlocal hits
                hits += 1
                raise RuntimeError("PRIVATE_GETTER")

        self.prepared.error = Hostile()
        with self.assertRaisesRegex(CoordinatorError, "^internal_error$"):
            await router.native.accept(raw)
        self.assertEqual(hits, 0)
        self.prepared.error = None
        await router.native.accept(raw)

    async def test_wrong_scope_real_coordinator_closes_its_own_client_without_business(
        self,
    ) -> None:
        router = self.configure()
        raw = frame()
        self.prepared.add(raw)
        self.factory.scope = Scope("foreign", "account_demo")
        with self.assertRaisesRegex(CoordinatorError, "^unauthorized$"):
            await router.native.accept(raw)
        await router.close()
        self.assertEqual(
            (
                self.factory.clients[0].finds,
                self.factory.clients[0].submits,
                self.factory.clients[0].closed,
            ),
            (0, 0, 1),
        )

    async def test_factory_cancellation_and_private_error_preserve_useful_progress(self) -> None:
        router = self.configure()
        raw = frame()
        self.prepared.add(raw)
        self.factory.error = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await router.native.accept(raw)
        self.factory.error = RuntimeError("PRIVATE_FACTORY_SENTINEL")
        with self.assertRaisesRegex(CoordinatorError, "^storage_unavailable$"):
            await router.native.accept(raw)
        self.factory.error = None
        self.assertIsInstance(await router.native.accept(raw), dict)
        await router.close()
        self.assertEqual(self.factory.clients[0].closed, 1)

    async def test_alias_of_borrowed_reader_never_closes_that_reader(self) -> None:
        router = self.configure()
        raw = frame()
        self.prepared.add(raw)
        self.factory.returned = cast(ChannelPolicyCoordinator, self.prepared)
        with self.assertRaisesRegex(CoordinatorError, "^invalid_input$"):
            await router.native.accept(raw)
        self.factory.returned = None
        await router.native.accept(raw)
        await router.close()
        self.assertEqual(self.factory.clients[0].closed, 1)

    async def test_coordinator_cannot_be_owned_by_two_simultaneous_calls(self) -> None:
        router = self.configure()
        raw = frame()
        self.prepared.add(raw)
        gate = asyncio.Event()
        self.factory.find_release = gate
        first = asyncio.create_task(router.native.accept(raw))
        await until(lambda: len(self.factory.cores) == 1)
        await self.factory.clients[0].find_entered.wait()
        self.factory.returned = self.factory.cores[0]
        with self.assertRaisesRegex(CoordinatorError, "^invalid_input$"):
            await router.native.lookup(query(raw))
        self.assertEqual(self.factory.clients[0].closed, 0)
        gate.set()
        await first
        await router.close()
        self.assertEqual(self.factory.clients[0].closed, 1)

    async def test_safe_error_code_copy_and_telemetry_outage_do_not_change_receipts(self) -> None:
        router = self.configure()
        raw = frame()
        self.prepared.add(raw)
        error = CoordinatorError("capacity")
        error.code = "PRIVATE_CODE"
        error.args = ("PRIVATE_ARGS",)
        self.prepared.error = error
        with (
            self.assertLogs(m.LOGGER, level="INFO") as logs,
            self.assertRaisesRegex(CoordinatorError, "^internal_error$") as raised,
        ):
            await router.native.accept(raw)
        self.assertIsNot(raised.exception, error)
        self.assertNotIn(
            "PRIVATE",
            repr((raised.exception.args, [(record.msg, record.code) for record in logs.records])),
        )
        self.prepared.error = None
        with patch.object(m.LOGGER, "info", side_effect=RuntimeError("PRIVATE_LOG_SENTINEL")):
            await router.native.accept(raw)
            await router.close()
        self.assertGreater(router.metrics()["telemetry_failed"], 0)
        self.assertEqual(len(self.ledger.records), 1)

    async def test_task_creation_cancel_and_failure_leave_no_empty_owner_or_coroutine_warning(
        self,
    ) -> None:
        router = self.configure()
        raw = frame()
        self.prepared.add(raw)
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always", RuntimeWarning)
            for failure in (asyncio.CancelledError(), RuntimeError("PRIVATE_ALLOCATION")):
                with (
                    patch.object(asyncio, "create_task", side_effect=failure),
                    self.assertRaises(
                        type(failure)
                        if isinstance(failure, asyncio.CancelledError)
                        else CoordinatorError
                    ),
                ):
                    await router.native.accept(raw)
                self.assertEqual(router.pending_count, 0)
            await router.native.accept(raw)
            await router.close()
            gc.collect()
        self.assertFalse(
            [warning for warning in observed if issubclass(warning.category, RuntimeWarning)]
        )

    async def test_constructor_catalogue_are_immutable_copied_and_no_io_is_started(self) -> None:
        router = self.configure()
        with self.assertRaises(FrozenInstanceError):
            router.native.source_binding_id = "sms"
        with self.assertRaises(TypeError):
            router.metrics()["active"] = 3
        with self.assertRaisesRegex(CoordinatorError, "^invalid_input$"):
            m.RevisionTemplateCatalog((template(), template()))
        with self.assertRaisesRegex(CoordinatorError, "^invalid_input$"):
            m.RevisionTemplateCatalog(())
        for option in (
            {"deadline_window_ms": True},
            {"deadline_window_ms": 60001},
            {"timeout_s": float("nan")},
            {"cleanup_timeout_s": False},
            {"timeout_s": 10**1000},
            {"timeout_s": -(10**1000)},
            {"cleanup_timeout_s": 10**1000},
            {"cleanup_timeout_s": -(10**1000)},
        ):
            with self.subTest(option=option), self.assertRaises(CoordinatorError):
                m.ChannelOriginRouter(
                    binding=self.binding,
                    discovery=self.discovery,
                    prepared=self.prepared,
                    templates=m.RevisionTemplateCatalog((template(),)),
                    coordinators=self.factory,
                    **option,
                )
        self.assertEqual(
            (self.discovery.calls, self.prepared.calls, self.factory.calls), (0, [], 0)
        )

    async def test_async_factory_and_descriptor_contract_rejects_before_ownership(self) -> None:
        self.configure()
        hits = 0

        class SyncFactory:
            def open(self):
                nonlocal hits
                hits += 1
                raise AssertionError("sync construction must never execute")

        class MarkedSyncFactory:
            @markcoroutinefunction
            def open(self):
                nonlocal hits
                hits += 1
                raise AssertionError("marked sync construction must never execute")

        class GetterDiscovery:
            @property
            def read(self):
                nonlocal hits
                hits += 1
                raise RuntimeError("PRIVATE_METHOD_GETTER")

        for discovery, factory in (
            (self.discovery, cast(m.CoordinatorFactory, SyncFactory())),
            (self.discovery, cast(m.CoordinatorFactory, MarkedSyncFactory())),
            (cast(m.DiscoveryPort, GetterDiscovery()), self.factory),
        ):
            with self.assertRaisesRegex(CoordinatorError, "^invalid_input$"):
                m.ChannelOriginRouter(
                    binding=self.binding,
                    discovery=discovery,
                    prepared=self.prepared,
                    templates=m.RevisionTemplateCatalog((template(),)),
                    coordinators=factory,
                )
        self.assertEqual(hits, 0)
        raw = frame()
        self.prepared.add(raw)
        await self.router.native.accept(raw)

    async def test_wrong_event_loop_fails_before_stopping_admission(self) -> None:
        router = self.configure()
        raw = frame()
        self.prepared.add(raw)
        await router.native.lookup(query(raw))

        def foreign() -> str:
            try:
                asyncio.run(router.close())
            except CoordinatorError as error:
                return error.code
            return "unexpected"

        self.assertEqual(await asyncio.to_thread(foreign), "invalid_input")
        self.assertEqual(router.metrics()["closing"], 0)
        await router.native.accept(raw)
        await router.close()


class Inert(unittest.TestCase):
    def test_import_allocates_no_socket_process_or_async_task(self) -> None:
        script = """import asyncio,socket,subprocess,sys
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
def denied(*args,**kwargs): raise AssertionError('import_IO')
with patch.object(socket.socket,'bind',denied),patch.object(socket.socket,'connect',denied),patch.object(subprocess,'Popen',denied),patch.object(asyncio,'create_task',denied):
 import services.channel_policy_demo.origin_router
print('inert')
"""
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", script, str(ROOT)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual((result.returncode, result.stdout), (0, "inert\n"), result.stderr)
