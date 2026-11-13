"""Actual TCP client checks; the peer is explicitly a scripted response fixture."""

from __future__ import annotations

import asyncio
import json
import time
import unittest
from pathlib import Path

from delegation_reliability.contracts import ContractError, canonical
from delegation_reliability.fixed_policy import (
    FixedPolicySpecialistClient,
    verify_fixed_policy_facts,
)
from delegation_reliability.fixed_policy_contracts import (
    parse_fixed_policy_request,
    produce_fixed_policy_request,
)
from delegation_reliability.http_client import SpecialistEndpoint, SpecialistHttpError
from delegation_reliability.security import EvidenceRecord

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = json.loads((ROOT / "contracts/delegation/fixed-policy-v2.json").read_bytes())


class FixedPolicyClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.mode = "valid"
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.tasks: set[asyncio.Task[None]] = set()
        self.writers: set[asyncio.StreamWriter] = set()
        self.failures: list[type[BaseException]] = []
        self.received: list[dict[str, object]] = []
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0, limit=8192)
        self.port = self.server.sockets[0].getsockname()[1]
        self.client = FixedPolicySpecialistClient(
            SpecialistEndpoint(self.port), "Bearer " + "A" * 43
        )

    async def asyncTearDown(self) -> None:
        self.release.set()
        await self.client.close()
        self.server.close()
        for writer in tuple(self.writers):
            writer.close()
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        await self.server.wait_closed()
        self.assertEqual(self.client.active, 0)
        self.assertEqual(self.failures, [])

    def request(self):
        value = json.loads(json.dumps(FIXTURE["producer_input"]))
        value["deadline_at_ms"] = time.time_ns() // 1_000_000 + 60000
        return produce_fixed_policy_request(value)

    def records(self, request):
        return tuple(
            EvidenceRecord(request.scope, ref, FIXTURE[key].encode())
            for ref, key in zip(
                request.evidence, ["policy_body_utf8", "facts_body_utf8"], strict=True
            )
        )

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        self.tasks.add(task)
        self.writers.add(writer)
        try:
            header = (await reader.readuntil(b"\r\n\r\n")).decode("ascii").split("\r\n")
            headers = dict(line.split(": ", 1) for line in header[1:] if line)
            self.assertEqual(headers["Authorization"], "Bearer " + "A" * 43)
            length = int(headers["Content-Length"])
            self.assertTrue(0 < length <= 16384)
            wire = json.loads(await reader.readexactly(length))
            request = parse_fixed_policy_request(canonical(wire))
            self.received.append(wire)
            self.entered.set()
            if self.mode in {"held", "held_unsupported"}:
                await self.release.wait()
            if "/invoke " in header[0]:
                response = json.loads(json.dumps(FIXTURE["result"]))
                response.update(
                    scope=wire["scope"],
                    delegation_id=wire["delegation_id"],
                    case_id=wire["case_id"],
                    request_revision=wire["request_revision"],
                    attempt_id=request.attempt.attempt_id,
                    input_fingerprint=request.input_fingerprint,
                    completed_at_ms=time.time_ns() // 1_000_000,
                )
                if self.mode == "identity":
                    response["scope"]["account_id"] = "foreign_account"
                elif self.mode == "witness":
                    response["fact_refs"][0]["sha256"] = "0" * 64
                elif self.mode in {"unsupported", "held_unsupported"}:
                    response["eligible"] = False
                status = "200 OK"
            else:
                response = {
                    "schema_version": 1,
                    "kind": "specialist.attempt_observation",
                    "scope": wire["scope"],
                    "delegation_id": wire["delegation_id"],
                    "attempt_id": request.attempt.attempt_id,
                    "input_fingerprint": request.input_fingerprint,
                    "state": "running",
                    "cancel_requested": "/cancel " in header[0],
                    "deadline_exceeded": False,
                    "transport_disconnected": False,
                    "closing": False,
                    "durable": False,
                }
                status = "202 Accepted" if "/cancel " in header[0] else "200 OK"
            body = canonical(response)
            writer.write(
                (
                    f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n"
                ).encode()
                + body
            )
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        except Exception as error:  # noqa: BLE001 - test records the primary failure before closing every owned socket.
            self.failures.append(type(error))
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            self.writers.discard(writer)
            self.tasks.discard(task)

    async def test_real_wire_valid_result_status_cancel_and_metrics(self):
        request = self.request()
        observed = await self.client.invoke(request)
        self.assertTrue(observed.eligible)
        self.assertEqual(
            verify_fixed_policy_facts(
                request, observed, self.records(request), observed_at_ms=time.time_ns() // 1_000_000
            ),
            "candidate",
        )
        self.assertFalse((await self.client.status(request)).durable)
        self.assertTrue((await self.client.cancel(request)).cancel_requested)
        await self.client.close()
        self.assertEqual(self.client.metrics()["started"], 3)
        self.assertEqual(self.client.metrics()["validated"], 3)
        self.assertEqual(self.client.metrics()["active"], 0)

    async def test_wrong_identity_or_source_is_rejected_then_valid_progresses(self):
        for mode in ["identity", "witness"]:
            self.mode = mode
            with self.subTest(mode=mode), self.assertRaises(SpecialistHttpError) as caught:
                await self.client.invoke(self.request())
            self.assertEqual(caught.exception.code, "invalid_response")
        self.mode = "valid"
        self.assertTrue((await self.client.invoke(self.request())).eligible)
        self.assertEqual(self.client.metrics()["validation_failed"], 2)
        self.assertEqual(self.client.metrics()["validated"], 1)

    async def test_transport_correlation_is_not_factual_authority(self):
        self.mode = "unsupported"
        request = self.request()
        observed = await self.client.invoke(request)
        self.assertFalse(observed.eligible)
        with self.assertRaises(ContractError) as caught:
            verify_fixed_policy_facts(
                request, observed, self.records(request), observed_at_ms=time.time_ns() // 1_000_000
            )
        self.assertEqual(caught.exception.code, "unsupported_facts")

    async def test_held_call_prevents_second_registration_and_later_completes(self):
        await self.client.close()
        self.client = FixedPolicySpecialistClient(
            SpecialistEndpoint(self.port), "Bearer " + "A" * 43, max_active=1
        )
        self.mode = "held"
        pending = asyncio.create_task(self.client.invoke(self.request()))
        entry = asyncio.create_task(self.entered.wait())
        try:
            done, _ = await asyncio.wait(
                {pending, entry}, timeout=2, return_when=asyncio.FIRST_COMPLETED
            )
            self.assertIn(entry, done)
            with self.assertRaises(SpecialistHttpError) as caught:
                await self.client.invoke(self.request())
            self.assertEqual(caught.exception.code, "client_capacity")
            self.assertEqual(self.client.metrics()["started"], 1)
            self.release.set()
            self.assertTrue((await pending).eligible)
        finally:
            self.release.set()
            entry.cancel()
            await asyncio.gather(pending, entry, return_exceptions=True)
        self.assertEqual(self.client.metrics()["capacity_rejected"], 1)

    async def test_caller_cancellation_and_private_socket_owner_settle(self):
        self.mode = "held"
        pending = asyncio.create_task(self.client.invoke(self.request()))
        entry = asyncio.create_task(self.entered.wait())
        try:
            done, _ = await asyncio.wait(
                {pending, entry}, timeout=2, return_when=asyncio.FIRST_COMPLETED
            )
            self.assertIn(entry, done)
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
            await self.client.close()
            self.assertEqual(self.client.active, 0)
            # This only proves the client transport settled; the controlled remote handler remains held.
            self.assertTrue(self.tasks)
            self.release.set()
        finally:
            self.release.set()
            entry.cancel()
            await asyncio.gather(pending, entry, return_exceptions=True)

    async def test_observed_fully_verifies_facts_and_later_valid_progress(self):
        self.mode = "unsupported"
        value = self.request()
        with self.assertRaises(SpecialistHttpError) as caught:
            await self.client.invoke_observed(value, evidence=self.records(value))
        self.assertEqual(caught.exception.code, "invalid_response")
        self.mode = "valid"
        observed = await self.client.invoke_observed(value, evidence=self.records(value))
        self.assertEqual(observed.applicability, "candidate")
        self.assertTrue(observed.result.eligible)
        self.assertEqual(self.client.metrics()["validation_failed"], 1)

    async def test_observed_preserves_valid_expired_body_but_rejects_bad_facts_first(self):
        for mode in ["held", "held_unsupported"]:
            self.mode = mode
            self.entered.clear()
            self.release.clear()
            source = json.loads(json.dumps(FIXTURE["producer_input"]))
            source["deadline_at_ms"] = time.time_ns() // 1_000_000 + 60
            value = produce_fixed_policy_request(source)
            pending = asyncio.create_task(
                self.client.invoke_observed(value, evidence=self.records(value))
            )
            arrived = asyncio.create_task(self.entered.wait())
            try:
                done, _ = await asyncio.wait(
                    {pending, arrived}, timeout=1, return_when=asyncio.FIRST_COMPLETED
                )
                self.assertIn(arrived, done)
                await asyncio.sleep(0.08)
                self.release.set()
                if mode == "held":
                    observed = await pending
                    self.assertEqual(observed.applicability, "expired")
                else:
                    with self.assertRaises(SpecialistHttpError) as caught:
                        await pending
                    self.assertEqual(caught.exception.code, "invalid_response")
            finally:
                self.release.set()
                arrived.cancel()
                await asyncio.gather(pending, arrived, return_exceptions=True)

    async def test_observed_snapshots_request_and_sources_before_io(self):
        self.mode = "held"
        value = self.request()
        records = self.records(value)
        pending = asyncio.create_task(self.client.invoke_observed(value, evidence=records))
        arrived = asyncio.create_task(self.entered.wait())
        try:
            done, _ = await asyncio.wait(
                {pending, arrived}, timeout=1, return_when=asyncio.FIRST_COMPLETED
            )
            self.assertIn(arrived, done)
            object.__setattr__(value, "request_revision", 9)
            object.__setattr__(records[0], "body", b"not policy")
            self.release.set()
            observed = await pending
            self.assertEqual(observed.result.request_revision, 1)
            self.assertEqual(observed.applicability, "candidate")
        finally:
            self.release.set()
            arrived.cancel()
            await asyncio.gather(pending, arrived, return_exceptions=True)
