"""Actual local TCP checks for the new typed client; raw peer is explicitly scripted."""

from __future__ import annotations

import asyncio
import json
import time
import unittest
from pathlib import Path
from typing import cast

from delegation_reliability.contracts import ContractError, canonical, parse_request
from delegation_reliability.document import DocumentSpecialistClient
from delegation_reliability.document_contracts import (
    DocumentRequest,
    parse_document_request,
    produce_document_request,
)
from delegation_reliability.http_client import SpecialistEndpoint, SpecialistHttpError

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = json.loads((ROOT / "contracts/delegation/document-v1.json").read_bytes())
POLICY = json.loads((ROOT / "contracts/delegation/v1.json").read_bytes())


class DocumentClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.mode = "valid"
        self.requests: list[dict[str, object]] = []
        self.tasks: set[asyncio.Task[None]] = set()
        self.writers: set[asyncio.StreamWriter] = set()
        self.arrived, self.release = asyncio.Event(), asyncio.Event()
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.client = DocumentSpecialistClient(SpecialistEndpoint(self.port), "Bearer " + "A" * 43)

    async def asyncTearDown(self) -> None:
        self.release.set()
        await self.client.close()
        self.server.close()
        for writer in self.writers:
            writer.close()
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        await self.server.wait_closed()
        self.assertEqual(self.client.active, 0)

    def request(self) -> DocumentRequest:
        value = json.loads(json.dumps(FIXTURE["producer_input"]))
        value["deadline_at_ms"] = time.time_ns() // 1_000_000 + 60000
        return produce_document_request(value)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        self.tasks.add(task)
        self.writers.add(writer)
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            rows = head.decode("ascii").split("\r\n")
            headers = dict(row.split(": ", 1) for row in rows[1:] if row)
            self.assertEqual(headers["Authorization"], "Bearer " + "A" * 43)
            value = json.loads(await reader.readexactly(int(headers["Content-Length"])))
            request = parse_document_request(canonical(value))
            self.requests.append(value)
            self.arrived.set()
            if self.mode == "held":
                await self.release.wait()
            if "/invoke " in rows[0]:
                result = json.loads(json.dumps(FIXTURE["result"]))
                result.update(
                    scope=value["scope"],
                    delegation_id=value["delegation_id"],
                    case_id=value["case_id"],
                    request_revision=value["request_revision"],
                    attempt_id=request.attempt.attempt_id,
                    input_fingerprint=request.input_fingerprint,
                    completed_at_ms=time.time_ns() // 1_000_000,
                )
                if self.mode == "scope":
                    result["scope"]["account_id"] = "foreign"
                if self.mode == "value":
                    result["fields"]["booking_reference"]["value"] = 7
                if self.mode == "evidence":
                    result["fields"]["booking_reference"]["evidence_refs"][0]["sha256"] = "0" * 64
                status = 200
            else:
                cancelled = "/cancel " in rows[0]
                result = {
                    "schema_version": 1,
                    "kind": "specialist.attempt_observation",
                    "scope": value["scope"],
                    "delegation_id": value["delegation_id"],
                    "attempt_id": request.attempt.attempt_id,
                    "input_fingerprint": request.input_fingerprint,
                    "state": "running",
                    "cancel_requested": cancelled and self.mode != "cancel_false",
                    "deadline_exceeded": False,
                    "transport_disconnected": False,
                    "closing": False,
                    "durable": False,
                }
                status = 202 if cancelled else 200
            raw = canonical(result)
            writer.write(
                f"HTTP/1.1 {status} OK\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\nConnection: close\r\n\r\n".encode()
                + raw
            )
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            self.writers.discard(writer)
            self.tasks.discard(task)

    async def test_real_loopback_document_result(self) -> None:
        result = await self.client.invoke(self.request())
        self.assertEqual(result.fields.booking_reference.value, "DEMO-BK-001")
        self.assertEqual(result.outcome, "extracted")
        self.assertFalse(hasattr(result, "eligible"))
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.client.metrics()["validated"], 1)

    async def test_wrong_scope_is_invalid_response(self) -> None:
        self.mode = "scope"
        with self.assertRaisesRegex(SpecialistHttpError, "invalid_response"):
            await self.client.invoke(self.request())
        self.assertEqual(self.client.metrics()["validation_failed"], 1)

    async def test_malformed_document_value_is_invalid_response(self) -> None:
        self.mode = "value"
        with self.assertRaisesRegex(SpecialistHttpError, "invalid_response"):
            await self.client.invoke(self.request())

    async def test_wrong_source_is_invalid_response(self) -> None:
        self.mode = "evidence"
        with self.assertRaisesRegex(SpecialistHttpError, "invalid_response"):
            await self.client.invoke(self.request())

    async def test_status_and_cancel_remain_nondurable_observations(self) -> None:
        request = self.request()
        status = await self.client.status(request)
        cancel = await self.client.cancel(request)
        self.assertFalse(status.cancel_requested)
        self.assertTrue(cancel.cancel_requested)
        self.assertEqual(status.input_fingerprint, request.input_fingerprint)

    async def test_cancel_success_requires_requested_flag(self) -> None:
        self.mode = "cancel_false"
        with self.assertRaisesRegex(SpecialistHttpError, "invalid_response"):
            await self.client.cancel(self.request())

    async def test_nested_request_snapshot_precedes_transport_await(self) -> None:
        self.mode = "held"
        request = self.request()
        original = request.input_fingerprint
        pending = asyncio.create_task(self.client.invoke(request))
        await self.arrived.wait()
        object.__setattr__(request.scope, "account_id", "mutated")
        object.__setattr__(request.context_snapshot, "document_source_id", "mutated")
        object.__setattr__(request, "input_fingerprint", "0" * 64)
        self.release.set()
        result = await pending
        self.assertEqual(result.scope.account_id, "account_document")
        self.assertEqual(result.input_fingerprint, original)

    async def test_policy_request_never_becomes_document_IO(self) -> None:
        with self.assertRaises(ContractError):
            await self.client.invoke(
                cast(DocumentRequest, parse_request(canonical(POLICY["request"])))
            )
        self.assertEqual(self.requests, [])
