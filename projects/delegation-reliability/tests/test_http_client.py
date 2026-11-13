"""Actual finite loopback sockets for the Python consumer; no provider or database."""

import asyncio
import copy
import json
import logging
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from delegation_reliability.contracts import (
    ContractError,
    canonical,
    encode_error,
    encode_request,
    encode_result,
    parse_result,
    produce_request,
)
from delegation_reliability.http_client import (
    SpecialistClient,
    SpecialistEndpoint,
    SpecialistHttpError,
    parse_observation,
)

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/delegation/v1.json").read_text()
)
HEADER = "Bearer " + "A" * 43


def request():
    value = copy.deepcopy(FIXTURE["producer_input"])
    value["deadline_at_ms"] = time.time_ns() // 1_000_000 + 30_000
    return produce_request(value)


def result_for(value):
    result = parse_result(canonical(FIXTURE["result"]))
    return replace(
        result,
        scope=value.scope,
        delegation_id=value.delegation_id,
        case_id=value.case_id,
        request_revision=value.request_revision,
        input_fingerprint=value.input_fingerprint,
        attempt_id=value.attempt.attempt_id,
        completed_at_ms=time.time_ns() // 1_000_000,
    )


def observation(value, **changes):
    wire = {
        "schema_version": 1,
        "kind": "specialist.attempt_observation",
        "scope": {"tenant_id": value.scope.tenant_id, "account_id": value.scope.account_id},
        "delegation_id": value.delegation_id,
        "attempt_id": value.attempt.attempt_id,
        "input_fingerprint": value.input_fingerprint,
        "state": "running",
        "durable": False,
        "cancel_requested": False,
        "deadline_exceeded": False,
        "transport_disconnected": False,
        "closing": False,
    }
    wire.update(changes)
    return canonical(wire)


def response(body, *, code=200, headers=()):
    return (
        f"HTTP/1.1 {code} Test\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n".encode()
        + b"".join(item + b"\r\n" for item in headers)
        + b"\r\n"
        + body
    )


class HttpClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.handlers = set()
        self.writers = set()
        self.clients = []
        self.servers = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()
        for server in self.servers:
            server.close()
            await server.wait_closed()
        for writer in tuple(self.writers):
            writer.close()
            await writer.wait_closed()
        if self.handlers:
            await asyncio.wait_for(asyncio.gather(*tuple(self.handlers), return_exceptions=True), 2)

    async def server(self, respond, **options):
        async def handler(reader, writer):
            task = asyncio.current_task()
            self.handlers.add(task)
            self.writers.add(writer)
            try:
                head = await reader.readuntil(b"\r\n\r\n")
                length = int(
                    next(
                        line.split(b":", 1)[1]
                        for line in head.split(b"\r\n")
                        if line.lower().startswith(b"content-length:")
                    )
                )
                body = await reader.readexactly(length)
                await respond(head, body, reader, writer)
            except (OSError, asyncio.IncompleteReadError):
                pass
            finally:
                writer.close()
                await writer.wait_closed()
                self.writers.discard(writer)
                self.handlers.discard(task)

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        self.servers.append(server)
        client = SpecialistClient(
            SpecialistEndpoint(server.sockets[0].getsockname()[1]), HEADER, **options
        )
        self.clients.append(client)
        return client

    async def test_actual_request_and_typed_result_no_proxy_or_retry(self):
        value = request()
        seen = []

        async def respond(head, body, _reader, writer):
            seen.append((head, body))
            writer.write(response(encode_result(result_for(value))))
            await writer.drain()

        client = await self.server(respond)
        with patch.dict(
            "os.environ",
            {"HTTP_PROXY": "http://secret.invalid:99", "ALL_PROXY": "http://secret.invalid:99"},
        ):
            result = await client.invoke(value)
        self.assertEqual(result.input_fingerprint, value.input_fingerprint)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][1], encode_request(value))
        self.assertIn(b"POST /v1/invoke HTTP/1.1\r\n", seen[0][0])
        self.assertEqual(client.active, 0)
        self.assertEqual(client.metrics()["validated"], 1)

    async def test_status_and_cancel_are_correlated_ephemeral_observations(self):
        value = request()

        async def respond(head, _body, _reader, writer):
            cancel = head.startswith(b"POST /v1/cancel ")
            writer.write(
                response(observation(value, cancel_requested=cancel), code=202 if cancel else 200)
            )

        client = await self.server(respond)
        self.assertFalse((await client.status(value)).durable)
        self.assertTrue((await client.cancel(value)).cancel_requested)

    async def test_bad_correlation_and_cancel_without_ack_are_rejected(self):
        value = request()
        for changes, operation in (({"attempt_id": "other"}, "status"), ({}, "cancel")):

            async def respond(_head, _body, _reader, writer, changes=changes, operation=operation):
                writer.write(
                    response(
                        observation(value, **changes), code=202 if operation == "cancel" else 200
                    )
                )

            client = await self.server(respond)
            with self.assertRaisesRegex(SpecialistHttpError, "^invalid_response$"):
                await getattr(client, operation)(value)
            self.assertEqual(client.metrics()["validated"], 0)
            self.assertEqual(client.metrics()["validation_failed"], 1)

    async def test_result_wrong_revision_and_expired_result_never_succeed(self):
        value = request()

        async def respond(_head, _body, _reader, writer):
            writer.write(
                response(
                    encode_result(
                        replace(result_for(value), request_revision=value.request_revision + 1)
                    )
                )
            )

        client = await self.server(respond)
        with self.assertRaisesRegex(SpecialistHttpError, "^invalid_response$"):
            await client.invoke(value)

        self.assertEqual(client.metrics()["validated"], 0)
        self.assertEqual(client.metrics()["validation_failed"], 1)

        async def valid(_head, _body, _reader, writer):
            writer.write(response(encode_result(result_for(value))))

        client = await self.server(valid)
        with (
            patch(
                "delegation_reliability.http_client.time.time_ns",
                return_value=(value.deadline_at_ms + 1) * 1_000_000,
            ),
            self.assertRaisesRegex(SpecialistHttpError, "^deadline_exceeded$"),
        ):
            await client.invoke(value)

    async def test_observed_api_preserves_strict_late_bytes_without_candidate_claim(self):
        value = request()

        async def valid(_head, _body, _reader, writer):
            writer.write(response(encode_result(result_for(value))))

        client = await self.server(valid)
        with patch(
            "delegation_reliability.http_client.time.time_ns",
            return_value=(value.deadline_at_ms + 1) * 1_000_000,
        ):
            observed = await client.invoke_observed(value)
        self.assertEqual(observed.timeliness, "expired")
        self.assertEqual(observed.observed_at_ms, value.deadline_at_ms + 1)
        self.assertEqual(observed.result.attempt_id, value.attempt.attempt_id)
        self.assertEqual(client.metrics()["validated"], 1)

    async def test_observed_api_still_rejects_wrong_identity_and_progresses(self):
        value = request()
        first = True

        async def valid(_head, _body, _reader, writer):
            nonlocal first
            result = result_for(value)
            if first:
                first = False
                result = replace(result, attempt_id="attempt_forged")
            writer.write(response(encode_result(result)))

        client = await self.server(valid)
        with self.assertRaisesRegex(SpecialistHttpError, "^invalid_response$"):
            await client.invoke_observed(value)
        self.assertEqual((await client.invoke_observed(value)).timeliness, "candidate")

    async def test_known_safe_remote_errors_and_malformed_error_envelopes(self):
        value = request()
        for body, expected in (
            (encode_error("unauthorized", "http_demo"), ContractError),
            (
                canonical(
                    {
                        "schema_version": 1,
                        "kind": "specialist.http_error",
                        "code": "closing",
                        "request_id": "http_demo",
                        "retryable": False,
                    }
                ),
                SpecialistHttpError,
            ),
            (b'{"secret":"SECRET_SENTINEL"}', SpecialistHttpError),
        ):

            async def respond(_head, _body, _reader, writer, body=body):
                writer.write(response(body, code=503))

            client = await self.server(respond)
            with self.assertRaises(expected) as caught:
                await client.invoke(value)
            self.assertNotIn("SECRET_SENTINEL", str(caught.exception))
            self.assertNotIn(HEADER, str(caught.exception))

    async def test_invalid_framing_status_duplicate_headers_and_limits(self):
        value = request()
        bodies = (
            response(b"{}", headers=(b"Content-Length: 2",)),
            response(b"{}", headers=(b"Content-Encoding: gzip",)),
            response(b"{}", headers=(b"Transfer-Encoding: chunked",)),
            response(b"{}", code=302, headers=(b"Location: http://secret.invalid/",)),
            response(b"{}", headers=tuple(f"x-{i}: a".encode() for i in range(17))),
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 8193\r\nConnection: close\r\n\r\n",
            b"HTTP/1.1 200 OK\r\nx: " + b"a" * 8200 + b"\r\n\r\n",
            response(b"{}") + b"EXTRA",
        )
        for raw in bodies:

            async def respond(_head, _body, _reader, writer, raw=raw):
                writer.write(raw)

            client = await self.server(respond)
            with self.assertRaisesRegex(SpecialistHttpError, "^invalid_response$"):
                await client.invoke(value)
            self.assertEqual(client.active, 0)

    async def test_truncated_and_slow_body_total_timeout_then_useful_progress(self):
        value = request()
        calls = 0

        async def respond(_head, _body, reader, writer):
            nonlocal calls
            calls += 1
            if calls == 1:
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100\r\nConnection: close\r\n\r\n{}"
                )
            elif calls == 2:
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100\r\nConnection: close\r\n\r\n"
                )
                await writer.drain()
                await reader.read()
            else:
                writer.write(response(encode_result(result_for(value))))

        client = await self.server(respond, timeout_ms=50)
        with self.assertRaisesRegex(SpecialistHttpError, "^invalid_response$"):
            await client.invoke(value)
        with self.assertRaisesRegex(SpecialistHttpError, "^deadline_exceeded$"):
            await client.invoke(value)
        self.assertEqual((await client.invoke(value)).delegation_id, value.delegation_id)

    async def test_caller_cancel_retains_slot_through_actual_cleanup(self):
        value = request()
        accepted = asyncio.Event()

        async def respond(_head, _body, reader, _writer):
            accepted.set()
            await reader.read()

        client = await self.server(respond, max_active=1)
        task = asyncio.create_task(client.invoke(value))
        await accepted.wait()
        self.assertEqual(client.active, 1)
        with self.assertRaisesRegex(SpecialistHttpError, "^client_capacity$"):
            await client.invoke(value)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        # Wait for the owned task/socket, not merely the cancelled waiter.
        await client.close()
        self.assertEqual(client.active, 0)
        self.assertEqual(client.metrics()["cancelled"], 1)
        await client.close()
        with self.assertRaisesRegex(SpecialistHttpError, "^client_closed$"):
            await client.invoke(value)

    async def test_close_during_call_observes_socket_cleanup_and_no_new_admission(self):
        value = request()
        accepted = asyncio.Event()

        async def respond(_head, _body, reader, _writer):
            accepted.set()
            await reader.read()

        client = await self.server(respond)
        task = asyncio.create_task(client.invoke(value))
        await accepted.wait()
        await asyncio.gather(client.close(), client.close())
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(client.active, 0)

    async def test_delayed_event_loop_cannot_convert_late_response_to_success(self):
        value = request()

        async def respond(_head, _body, _reader, writer):
            writer.write(response(encode_result(result_for(value))))
            await writer.drain()
            time.sleep(0.06)  # noqa: ASYNC251 - deliberate overdue-timer regression fixture

        client = await self.server(respond, timeout_ms=20)
        with self.assertRaisesRegex(SpecialistHttpError, "^deadline_exceeded$"):
            await client.invoke(value)

    async def test_safe_logger_failure_never_changes_success_or_leaks_input(self):
        value = request()

        async def respond(_head, _body, _reader, writer):
            writer.write(response(encode_result(result_for(value))))

        client = await self.server(respond)
        seen = []

        class Handler(logging.Handler):
            def emit(self, record):
                seen.append(record)
                raise OSError("SECRET_SENTINEL")

        logger = logging.getLogger("delegation_reliability.http_client")
        original = logger.level
        handler = Handler()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            await client.invoke(value)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(original)
        self.assertEqual(client.metrics()["telemetry_failed"], 2)
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0].getMessage(), "specialist_http")
        self.assertNotIn(value.context_snapshot.note, str(seen[0].__dict__))
        self.assertNotIn(HEADER, str(seen[0].__dict__))

    async def test_held_actual_socket_cleanup_keeps_permit_and_close_is_finite(self):
        value = request()
        entered, release = asyncio.Event(), asyncio.Event()
        original = asyncio.open_connection

        async def connect(*args, **kwargs):
            reader, writer = await original(*args, **kwargs)
            actual_close = writer.wait_closed

            async def held():
                entered.set()
                await release.wait()
                await actual_close()

            writer.wait_closed = held
            return reader, writer

        async def respond(_head, _body, _reader, writer):
            writer.write(response(encode_result(result_for(value))))

        client = await self.server(respond, max_active=1, cleanup_ms=20)
        with patch("delegation_reliability.http_client.asyncio.open_connection", connect):
            task = asyncio.create_task(client.invoke(value))
            await entered.wait()
            for _ in range(2):
                with self.assertRaisesRegex(SpecialistHttpError, "^cleanup_incomplete$"):
                    await client.close()
                self.assertEqual(client.active, 1)
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        await client.close()
        self.assertEqual(client.active, 0)
        fresh = await self.server(respond)
        self.assertEqual((await fresh.invoke(value)).delegation_id, value.delegation_id)

    async def test_invoke_cleanup_observation_is_bounded_without_explicit_close(self):
        value = request()
        entered, release = asyncio.Event(), asyncio.Event()
        original = asyncio.open_connection

        async def connect(*args, **kwargs):
            reader, writer = await original(*args, **kwargs)
            actual_close = writer.wait_closed

            async def held():
                entered.set()
                await release.wait()
                await actual_close()

            writer.wait_closed = held
            return reader, writer

        async def respond(_head, _body, _reader, writer):
            writer.write(response(encode_result(result_for(value))))

        client = await self.server(respond, max_active=1, timeout_ms=20, cleanup_ms=20)
        with patch("delegation_reliability.http_client.asyncio.open_connection", connect):
            with self.assertRaisesRegex(SpecialistHttpError, "^cleanup_incomplete$"):
                await asyncio.wait_for(client.invoke(value), 0.5)
            self.assertTrue(entered.is_set())
            self.assertEqual(client.active, 1)
            with self.assertRaisesRegex(SpecialistHttpError, "^client_capacity$"):
                await client.invoke(value)
            release.set()
            for _ in range(20):
                if client.active == 0:
                    break
                await asyncio.sleep(0)
        self.assertEqual(client.active, 0)
        self.assertEqual((await client.invoke(value)).delegation_id, value.delegation_id)

    async def test_unexpected_actual_socket_cleanup_failure_is_safe_nonpassing(self):
        value = request()
        original = asyncio.open_connection

        async def connect(*args, **kwargs):
            reader, writer = await original(*args, **kwargs)
            actual_close = writer.wait_closed

            async def broken():
                await actual_close()
                raise ValueError("SECRET_SENTINEL")

            writer.wait_closed = broken
            return reader, writer

        async def respond(_head, _body, _reader, writer):
            writer.write(response(encode_result(result_for(value))))

        client = await self.server(respond)
        with (
            patch("delegation_reliability.http_client.asyncio.open_connection", connect),
            self.assertRaisesRegex(SpecialistHttpError, "^cleanup_incomplete$"),
        ):
            await client.invoke(value)
        self.assertEqual(client.metrics()["validated"], 0)
        self.assertGreater(client.metrics()["cleanup_failed"], 0)
        self.assertEqual(client.active, 0)
        self.assertEqual((await client.invoke(value)).delegation_id, value.delegation_id)

    async def test_endpoint_options_auth_and_contract_rejected_without_socket(self):
        for endpoint in ((0, "127.0.0.1"), (80, "localhost"), (True, "127.0.0.1")):
            with self.assertRaisesRegex(SpecialistHttpError, "^invalid_http$"):
                SpecialistEndpoint(*endpoint)
        for options in ({"timeout_ms": True}, {"max_active": 17}, {"cleanup_ms": 1001}):
            with self.assertRaisesRegex(SpecialistHttpError, "^invalid_http$"):
                SpecialistClient(SpecialistEndpoint(1), HEADER, **options)
        with self.assertRaisesRegex(SpecialistHttpError, "^invalid_http$"):
            SpecialistClient(SpecialistEndpoint(1), HEADER + "\n")
        client = SpecialistClient(SpecialistEndpoint(1), HEADER)
        self.clients.append(client)
        with self.assertRaises(ContractError):
            await client.invoke({"untrusted": "SECRET_SENTINEL"})
        self.assertEqual(client.active, 0)

    async def test_connection_failure_is_fixed_without_private_diagnostics(self):
        probe = await asyncio.start_server(lambda _r, _w: None, "127.0.0.1", 0)
        port = probe.sockets[0].getsockname()[1]
        probe.close()
        await probe.wait_closed()
        client = SpecialistClient(SpecialistEndpoint(port), HEADER)
        self.clients.append(client)
        with self.assertRaisesRegex(SpecialistHttpError, "^connection_failed$"):
            await client.invoke(request())

    def test_observation_codec_strict_boolean_version_and_fields(self):
        value = request()
        for changes in (
            {"durable": True},
            {"cancel_requested": 1},
            {"schema_version": True},
            {"extra": "SECRET_SENTINEL"},
            {"scope": {"tenant_id": "Bad", "account_id": "x"}},
        ):
            with self.assertRaisesRegex(SpecialistHttpError, "^invalid_response$"):
                parse_observation(observation(value, **changes))
