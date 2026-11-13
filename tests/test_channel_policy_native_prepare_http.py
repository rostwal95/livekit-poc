"""Actual loopback/Public Node prepare interop; no room connect, PG or providers."""

from __future__ import annotations

import asyncio
import copy
import gc
import hashlib
import inspect
import json
import os
import shutil
import socket
import subprocess
import sys
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from services.channel_policy_demo import native_prepare_http as m

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "A" * 43
PRIVATE = "PRIVATE_PREPARE_HTTP_SENTINEL"
NODE = shutil.which("node")
if NODE is None:
    raise RuntimeError("missing_node_toolchain")


def context():
    event = str(uuid4())
    return {
        "schemaVersion": 1,
        "kind": "investigation",
        "operationKey": str(uuid4()),
        "scope": {"tenantId": "tenant-native", "accountId": "account-native"},
        "caseId": "case-native",
        "caseRevision": "1",
        "conversationId": "conversation-native",
        "message": {
            "receiptId": str(uuid4()),
            "eventId": event,
            "messageId": event,
            "senderId": str(uuid4()),
            "body": "Investigate 🧭 e\u0301",
        },
    }


def raw_context(value=None):
    return json.dumps(
        {
            "schemaVersion": 1,
            "kind": "agent.prepare",
            "context": context() if value is None else value,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()


def request_bytes(port, raw, *, bearer=TOKEN):
    return (
        f"POST /v1/native/prepare HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {bearer}\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\nConnection: close\r\n\r\n".encode()
        + raw
    )


async def exchange(port, *, raw=None, wire=None):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(
            request_bytes(port, raw_context() if raw is None else raw) if wire is None else wire
        )
        await writer.drain()
        async with asyncio.timeout(3):
            header = await reader.readuntil(b"\r\n\r\n")
            lines = header[:-4].split(b"\r\n")
            status = int(lines[0].split()[1])
            headers = {
                name.lower(): value.strip()
                for line in lines[1:]
                for name, _, value in (line.partition(b":"),)
            }
            length = int(headers[b"content-length"])
            if not 0 < length <= 2048:
                raise AssertionError("bounded body expected")
            body = await reader.readexactly(length)
            if await reader.read(1):
                raise AssertionError("one response expected")
        return status, headers, body
    finally:
        writer.close()
        await writer.wait_closed()


class Port:
    def __init__(self):
        self.calls = []
        self.entered = asyncio.Queue(8)
        self.release = None
        self.error = None
        self.answer = None
        self.mutate_revision = False
        self.cancelled = 0
        self.closed = 0

    async def prepare(self, value: object) -> dict[str, object]:
        self.calls.append(copy.deepcopy(value))
        self.entered.put_nowait(value)
        try:
            if self.release is not None:
                await self.release.wait()
            if self.error is not None:
                raise self.error
            if self.mutate_revision:
                value["caseRevision"] = "2"
            return (
                self.answer
                if self.answer is not None
                else {
                    "kind": "investigation",
                    "source": "scripted",
                    "caseRevision": value["caseRevision"],
                }
            )
        except asyncio.CancelledError:
            self.cancelled += 1
            raise

    async def aclose(self):
        self.closed += 1


class ConfigurationTests(unittest.TestCase):
    def test_closed_configuration_and_public_start_defaults(self):
        for changes in (
            {"prepare_bearer": "x"},
            {"prepare_bearer": "A" * 44},
            {"prepare_bearer": "A" * 42 + "\n"},
            {"call_timeout_s": 0},
            {"call_timeout_s": 4.1},
            {"cleanup_timeout_s": True},
            {"call_timeout_s": float("nan")},
            {"cleanup_timeout_s": float("inf")},
            {"call_timeout_s": 10**1000},
            {"cleanup_timeout_s": 10**1000},
        ):
            with (
                self.subTest(fields=tuple(changes)),
                self.assertRaises(m.NativePrepareHttpError) as error,
            ):
                m.NativePrepareHttp(Port(), **({"prepare_bearer": TOKEN} | changes))
            self.assertEqual(str(error.exception), "invalid_configuration")
        m.NativePrepareHttp(Port(), prepare_bearer=TOKEN)
        self.assertEqual(
            inspect.signature(m.NativePrepareHttp.start).parameters["port"].default, 11030
        )

    def test_sync_or_property_prepare_is_rejected_without_calls_or_getters(self):
        touched = []

        class Sync:
            def prepare(self, context):
                touched.append("sync")

        class Property:
            @property
            def prepare(self):
                touched.append("getter")
                raise RuntimeError(PRIVATE)

        for value in (Sync(), Property(), object()):
            with (
                self.subTest(kind=type(value).__name__),
                self.assertRaises(m.NativePrepareHttpError),
            ):
                m.NativePrepareHttp(value, prepare_bearer=TOKEN)
        self.assertEqual(touched, [])

    def test_import_is_inert_without_sdk_product_or_network(self):
        code = r"""import asyncio,importlib.abc,json,socket,sys,threading
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.startswith(('livekit','channel_continuity','services.conversation_agent')): raise AssertionError('unexpected serving import')
sys.meta_path.insert(0,Deny())
def denied(*args,**kwargs):raise AssertionError('import-time side effect')
socket.socket=denied
asyncio.create_task=denied
threading.Thread.start=denied
from services.channel_policy_demo import native_prepare_http
assert native_prepare_http.ROUTE==b'/v1/native/prepare'
print(json.dumps({'cold':True}))
"""
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code],
            cwd="/private/tmp",
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"cold": True})


class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.port = Port()
        self.host = m.NativePrepareHttp(
            self.port, prepare_bearer=TOKEN, call_timeout_s=0.05, cleanup_timeout_s=0.05
        )
        self.endpoint = await self.host.start(0)
        self.addAsyncCleanup(self.host.close)

    async def test_exact_raw_digest_unicode_and_three_node_compatible_headers(self):
        raw = b" " + raw_context() + b"\n"
        status, headers, body = await exchange(self.endpoint.port, raw=raw)
        self.assertEqual(status, 200)
        self.assertEqual(set(headers), {b"content-length", b"content-type", b"connection"})
        self.assertEqual(headers[b"content-type"], b"application/json")
        value = json.loads(body)
        self.assertEqual(value["inputDigest"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(value["kind"], "agent.prepared")
        self.assertEqual(
            value["decision"], {"kind": "investigation", "source": "scripted", "caseRevision": "1"}
        )
        self.assertEqual(self.port.calls[0]["message"]["body"], "Investigate 🧭 e\u0301")
        self.assertEqual(self.host.metrics()["prepared"], 1)
        await self.host.close()
        self.assertEqual(self.host.pending_count, 0)
        self.assertEqual(self.port.closed, 0)

    async def test_wrong_role_credentials_never_reach_borrowed_runtime(self):
        for token in ("B" * 43, "C" * 43, "D" * 43):
            status, _, body = await exchange(
                self.endpoint.port,
                wire=request_bytes(self.endpoint.port, raw_context(), bearer=token),
            )
            self.assertEqual(status, 401)
            self.assertNotIn(token.encode(), body)
        self.assertEqual(self.port.calls, [])
        self.assertEqual((await exchange(self.endpoint.port))[0], 200)

    async def test_closed_framing_paths_and_header_caps(self):
        raw = raw_context()
        base = request_bytes(self.endpoint.port, raw)
        replacements = [
            (b"POST ", b"GET "),
            (b"/v1/native/prepare ", b"/v1/native/prepare?other=1 "),
            (b"HTTP/1.1", b"HTTP/1.0"),
            (b"Content-Type: application/json", b"Content-Type: text/plain"),
            (b"Connection: close", b"Connection: keep-alive"),
            (f"Host: 127.0.0.1:{self.endpoint.port}".encode(), b"Host: example.invalid"),
            (b"Connection: close", b"Transfer-Encoding: chunked\r\nConnection: close"),
            (b"Connection: close", b"X-Private: " + PRIVATE.encode() + b"\r\nConnection: close"),
            (b"Connection: close", b"Content-Length: 1\r\nConnection: close"),
            (b"Content-Length: " + str(len(raw)).encode(), b"Content-Length: 32769"),
            (b"Content-Length: " + str(len(raw)).encode(), b"Content-Length: +1"),
            (b"Content-Length: " + str(len(raw)).encode(), b"Content-Length: 0"),
            (b"Connection: close", b"Connection: cl\tose"),
        ]
        for before, after in replacements:
            with self.subTest(header=before[:20]):
                status, _, body = await exchange(
                    self.endpoint.port, wire=base.replace(before, after, 1)
                )
                self.assertEqual(status, 400)
                self.assertNotIn(PRIVATE.encode(), body)
        self.assertEqual(self.port.calls, [])
        self.assertEqual((await exchange(self.endpoint.port))[0], 200)

    async def test_closed_json_duplicate_keys_versions_nan_and_depth_fail_before_runtime(self):
        raw = raw_context()
        variants = [
            b"{}",
            b"[]",
            b"\xff",
            raw.replace(b'"schemaVersion":1', b'"schemaVersion":true', 1),
            raw.replace(b'"schemaVersion":1', b'"schemaVersion":2', 1),
            raw.replace(
                b'"kind":"agent.prepare"', b'"kind":"agent.prepare","kind":"agent.prepare"', 1
            ),
            raw[:-1] + b',"inputDigest":"' + b"0" * 64 + b'"}',
            b'{"schemaVersion":1,"kind":"agent.prepare","context":NaN}',
            b'{"schemaVersion":1,"kind":"agent.prepare","context":'
            + b"[" * 1100
            + b"0"
            + b"]" * 1100
            + b"}",
        ]
        for value in variants:
            with self.subTest(length=len(value)):
                status, _, _ = await exchange(self.endpoint.port, raw=value)
                self.assertEqual(status, 400)
        self.assertEqual(self.port.calls, [])
        self.assertEqual((await exchange(self.endpoint.port))[0], 200)

    async def test_runtime_mutation_cannot_rebind_original_context_revision(self):
        self.port.mutate_revision = True
        status, _, body = await exchange(self.endpoint.port)
        self.assertEqual(status, 503)
        self.assertNotIn(b"agent.prepared", body)
        self.port.mutate_revision = False
        self.assertEqual((await exchange(self.endpoint.port))[0], 200)

    async def test_bad_decisions_are_finite_and_do_not_return_private_bytes(self):
        for answer in (
            {"kind": "investigation", "source": "provider_real", "caseRevision": "1"},
            {"kind": "investigation", "source": "scripted", "caseRevision": "2"},
            {
                "kind": "investigation",
                "source": "scripted",
                "caseRevision": "1",
                "private": PRIVATE,
            },
        ):
            self.port.answer = answer
            status, _, body = await exchange(self.endpoint.port)
            self.assertEqual(status, 503)
            self.assertNotIn(PRIVATE.encode(), body)
        self.port.answer = None
        self.assertEqual((await exchange(self.endpoint.port))[0], 200)

    async def test_dependency_error_getters_args_and_unhashable_codes_never_escape(self):
        touched = []

        class GetterError(Exception):
            @property
            def code(self):
                touched.append(True)
                raise RuntimeError(PRIVATE)

        class DataError(Exception):
            pass

        array = DataError(PRIVATE)
        array.code = []
        denied = DataError(PRIVATE)
        denied.code = "forbidden"
        for error, status in (
            (GetterError(PRIVATE), 503),
            (array, 503),
            (denied, 403),
            (RuntimeError(PRIVATE), 503),
        ):
            self.port.error = error
            observed, _, body = await exchange(self.endpoint.port)
            self.assertEqual(observed, status)
            self.assertNotIn(PRIVATE.encode(), body)
        self.assertEqual(touched, [])
        self.port.error = None
        self.assertEqual((await exchange(self.endpoint.port))[0], 200)

    async def test_static_prepare_snapshot_ignores_later_instance_override(self):
        async def changed(value):
            raise RuntimeError(PRIVATE)

        self.port.prepare = changed
        self.assertEqual((await exchange(self.endpoint.port))[0], 200)
        self.assertEqual(len(self.port.calls), 1)

    async def test_four_timedout_calls_keep_capacity_until_actual_settlement(self):
        self.port.release = asyncio.Event()
        self.addCleanup(self.port.release.set)
        requests = [asyncio.create_task(exchange(self.endpoint.port)) for _ in range(4)]
        for _ in range(4):
            async with asyncio.timeout(1):
                await self.port.entered.get()
        results = await asyncio.gather(*requests)
        self.assertTrue(all(status == 503 for status, _, _ in results))
        self.assertEqual(self.host.metrics()["active_calls"], 4)
        self.assertEqual(self.host.metrics()["handlers"], 4)
        self.assertLessEqual(self.host.metrics()["sockets"], 8)
        self.assertEqual((await exchange(self.endpoint.port))[0], 429)
        self.assertEqual(len(self.port.calls), 4)
        actual = tuple(self.host._calls)
        self.port.release.set()
        await asyncio.gather(*actual)
        self.assertEqual(self.host.metrics()["active_calls"], 0)
        self.assertEqual(self.host.metrics()["handlers"], 0)
        self.assertEqual((await exchange(self.endpoint.port))[0], 200)
        self.assertEqual(self.port.cancelled, 0)

    async def test_eight_actual_sockets_and_four_handlers_bound_slow_header_peers(self):
        entered, count = asyncio.Event(), 0
        actual_request = self.host._request

        async def request(connection):
            nonlocal count
            count += 1
            if count == 8:
                entered.set()
            return await actual_request(connection)

        peers = []
        with patch.object(self.host, "_request", request):
            try:
                peers = await asyncio.gather(
                    *(asyncio.open_connection("127.0.0.1", self.endpoint.port) for _ in range(8))
                )
                async with asyncio.timeout(1):
                    await entered.wait()
                self.assertEqual(self.host.metrics()["sockets"], 8)
                self.assertEqual(self.host.metrics()["handlers"], 4)
                self.assertEqual(self.host.metrics()["active_calls"], 0)
                self.assertEqual(self.port.calls, [])
                self.assertFalse(self.host._watching)
            finally:
                for _, writer in peers:
                    writer.close()
                await asyncio.gather(
                    *(writer.wait_closed() for _, writer in peers), return_exceptions=True
                )
                tasks = tuple(
                    connection.task
                    for connection in self.host._records
                    if connection.task is not None
                )
                async with asyncio.timeout(2):
                    await asyncio.gather(*tasks, return_exceptions=True)
        self.assertEqual(self.host.metrics()["sockets"], 0)
        self.assertEqual((await exchange(self.endpoint.port))[0], 200)

    async def test_timedout_call_keeps_host_close_incomplete_and_borrowed_runtime_open(self):
        self.port.release = asyncio.Event()
        self.addCleanup(self.port.release.set)
        status, _, _ = await exchange(self.endpoint.port)
        self.assertEqual(status, 503)
        with self.assertRaises(m.NativePrepareHttpError) as error:
            await self.host.close()
        self.assertEqual(str(error.exception), "cleanup_incomplete")
        self.assertEqual(self.host.pending_count, 1)
        self.assertEqual(self.host.metrics()["active_calls"], 1)
        self.assertEqual(self.port.closed, 0)
        self.port.release.set()
        await self.host.close()
        self.assertEqual(self.host.pending_count, 0)
        self.assertEqual(self.port.cancelled, 0)
        self.assertEqual(self.port.closed, 0)

    async def test_abandoned_peer_does_not_cancel_started_prepare(self):
        self.port.release = asyncio.Event()
        self.addCleanup(self.port.release.set)
        reader, writer = await asyncio.open_connection("127.0.0.1", self.endpoint.port)
        writer.write(request_bytes(self.endpoint.port, raw_context()))
        await writer.drain()
        async with asyncio.timeout(1):
            await self.port.entered.get()
        writer.close()
        await writer.wait_closed()
        self.assertEqual(self.host.metrics()["active_calls"], 1)
        self.port.release.set()
        await self.host.close()
        self.assertEqual(self.port.cancelled, 0)
        self.assertEqual(self.host.pending_count, 0)
        self.assertTrue(reader.at_eof() or writer.is_closing())

    async def test_cancelled_close_waiter_keeps_actual_close_and_port_owner(self):
        self.port.release = asyncio.Event()
        self.addCleanup(self.port.release.set)
        await exchange(self.endpoint.port)
        waiter = asyncio.create_task(self.host.close())
        await asyncio.sleep(0)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        self.assertEqual(self.host.pending_count, 1)
        self.port.release.set()
        await self.host.close()
        self.assertEqual(self.host.pending_count, 0)
        self.assertEqual(self.port.closed, 0)

    async def test_partial_headers_and_body_have_separate_one_second_bounds(self):
        raw = raw_context()
        full = request_bytes(self.endpoint.port, raw)
        wires = (full.split(b"\r\n\r\n")[0][:35], full[: len(full) - len(raw)] + raw[:1])
        # Independent connections exercise both real one-second clocks together.
        # This retains every framing/privacy/progress assertion and uses two of
        # the four handler slots; it does not shorten or fake either deadline.
        results = await asyncio.gather(*(exchange(self.endpoint.port, wire=wire) for wire in wires))
        for wire, (status, _, body) in zip(wires, results, strict=True):
            with self.subTest(length=len(wire)):
                self.assertEqual(status, 503)
                self.assertNotIn(PRIVATE.encode(), body)
        self.assertEqual(self.port.calls, [])
        self.assertEqual((await exchange(self.endpoint.port))[0], 200)

    async def test_telemetry_failure_cannot_replace_valid_preparation(self):
        with patch.object(m.LOGGER, "info", side_effect=RuntimeError(PRIVATE)):
            self.assertEqual((await exchange(self.endpoint.port))[0], 200)
        self.assertEqual(self.host.metrics()["telemetry_failed"], 1)
        self.assertEqual(self.host.metrics()["prepared"], 1)
        self.assertTrue(
            all(type(value) is int and value >= 0 for value in self.host.metrics().values())
        )

    async def test_call_task_allocation_failure_is_finite_and_coroutine_is_closed(self):
        loop = asyncio.get_running_loop()
        actual_create = loop.create_task
        operations = []

        def create(operation, **kwargs):
            if getattr(getattr(operation, "cr_code", None), "co_name", None) == "_invoke":
                operations.append(operation)
                raise RuntimeError(PRIVATE)
            return actual_create(operation, **kwargs)

        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always", RuntimeWarning)
            with patch.object(loop, "create_task", create):
                status, _, body = await exchange(self.endpoint.port)
            self.assertEqual(status, 503)
            self.assertNotIn(PRIVATE.encode(), body)
            self.assertEqual(self.port.calls, [])
            gc.collect()
            self.assertFalse(any("never awaited" in str(value.message) for value in observed))
        self.assertEqual(inspect.getcoroutinestate(operations[0]), inspect.CORO_CLOSED)
        self.assertEqual((await exchange(self.endpoint.port))[0], 200)

    async def test_close_task_allocation_failure_retains_listener_for_retry(self):
        loop = asyncio.get_running_loop()
        listener = self.host._listener
        with (
            patch.object(loop, "create_task", side_effect=RuntimeError(PRIVATE)),
            self.assertRaises(m.NativePrepareHttpError) as error,
        ):
            await self.host.close()
        self.assertEqual(str(error.exception), "cleanup_incomplete")
        self.assertGreaterEqual(listener.fileno(), 0)
        await self.host.close()
        self.assertEqual(listener.fileno(), -1)

    async def test_start_is_idempotent_and_closed_host_cannot_restart(self):
        self.assertEqual(await self.host.start(0), self.endpoint)
        with self.assertRaises(m.NativePrepareHttpError):
            await self.host.start(self.endpoint.port + 1 if self.endpoint.port < 65535 else 65534)
        await self.host.close()
        with self.assertRaises(m.NativePrepareHttpError) as error:
            await self.host.start(0)
        self.assertEqual(str(error.exception), "closed")


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_selector_setup_failure_releases_listener_and_fresh_start_progresses(self):
        host = m.NativePrepareHttp(Port(), prepare_bearer=TOKEN)
        self.addAsyncCleanup(host.close)
        loop = asyncio.get_running_loop()
        made = []
        actual = socket.socket

        def new_socket(*args, **kwargs):
            result = actual(*args, **kwargs)
            made.append(result)
            return result

        with (
            patch.object(m.socket, "socket", new_socket),
            patch.object(loop, "add_reader", side_effect=RuntimeError(PRIVATE)),
            self.assertRaises(m.NativePrepareHttpError) as error,
        ):
            await host.start(0)
        self.assertEqual(str(error.exception), "unavailable")
        self.assertEqual(made[0].fileno(), -1)
        endpoint = await host.start(0)
        self.assertEqual((await exchange(endpoint.port))[0], 200)

    async def test_accepted_socket_setup_failure_keeps_no_unowned_descriptor(self):
        port = Port()
        host = m.NativePrepareHttp(port, prepare_bearer=TOKEN)
        endpoint = await host.start(0)
        self.addAsyncCleanup(host.close)
        actual = socket.socket.setblocking
        accepted = []

        def setblocking(sock, flag):
            if sock.family == socket.AF_INET and sock.getsockname()[1] == endpoint.port:
                accepted.append(sock)
                raise RuntimeError(PRIVATE)
            return actual(sock, flag)

        with patch.object(socket.socket, "setblocking", setblocking):
            reader, writer = await asyncio.open_connection("127.0.0.1", endpoint.port)
            try:
                async with asyncio.timeout(1):
                    self.assertEqual(await reader.read(1), b"")
            finally:
                writer.close()
                await writer.wait_closed()
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0].fileno(), -1)
        self.assertEqual(host.pending_count, 0)
        self.assertEqual(host.metrics()["sockets"], 0)
        self.assertEqual(port.calls, [])
        await host.close()
        fresh = m.NativePrepareHttp(port, prepare_bearer=TOKEN)
        self.addAsyncCleanup(fresh.close)
        current = await fresh.start(0)
        self.assertEqual((await exchange(current.port))[0], 200)

    async def test_queued_cancellation_opens_no_listener_and_new_owner_progresses(self):
        host = m.NativePrepareHttp(Port(), prepare_bearer=TOKEN)
        self.addAsyncCleanup(host.close)

        async def stopped():
            asyncio.current_task().cancel()
            await host.start(0)

        with patch.object(m.socket, "socket") as create:
            task = asyncio.create_task(stopped())
            with self.assertRaises(asyncio.CancelledError):
                await task
            create.assert_not_called()
        endpoint = await host.start(0)
        self.assertEqual((await exchange(endpoint.port))[0], 200)


class PublicInteropTests(unittest.IsolatedAsyncioTestCase):
    async def test_genuine_unstarted_native_runtime_denies_foreign_binding_and_unready(self):
        from channel_continuity.codec import AccountScope, ProviderScope
        from channel_continuity.native import NativeRuntime
        from channel_continuity.native_models import NativeBinding
        from services.channel_policy_demo.native_models import load_scripted_models

        class Intake:
            async def accept(self, value):
                raise AssertionError("prepare cannot manufacture accepted input")

            async def aclose(self):
                pass

        models = await load_scripted_models()
        binding = NativeBinding(
            str(uuid4()),
            ProviderScope("tenant-native", "livekit", "native-local"),
            AccountScope("tenant-native", "account-native"),
            "case-native",
            "conversation-native",
            "room-native",
            "browser-native",
            "agent-native",
        )
        runtime = NativeRuntime(binding, Intake(), stt=models.stt, llm=models.llm, tts=models.tts)
        host = m.NativePrepareHttp(runtime, prepare_bearer=TOKEN)
        endpoint = await host.start(0)
        try:
            value = context()
            self.assertEqual((await exchange(endpoint.port, raw=raw_context(value)))[0], 403)
            value["message"]["senderId"] = binding.binding_id
            self.assertEqual((await exchange(endpoint.port, raw=raw_context(value)))[0], 503)
            self.assertEqual(models.metrics()["model_calls"], 0)
            self.assertEqual(models.metrics()["transcripts"], 0)
        finally:
            await asyncio.gather(host.close(), runtime.aclose())
            await models.aclose()
        self.assertEqual(host.pending_count, 0)
        self.assertEqual(models.pending_count, 0)

    async def test_actual_node_public_client_interop_and_wrong_digest_rejection(self):
        port = Port()
        host = m.NativePrepareHttp(port, prepare_bearer=TOKEN)
        endpoint = await host.start(0)
        self.addAsyncCleanup(host.close)
        native = (ROOT / "projects/channel-continuity/dist/native.js").as_uri()
        index = (ROOT / "projects/channel-continuity/dist/index.js").as_uri()
        script = r"""import {createServer,request} from 'node:http';
const {NativeAgentHttpClient}=await import(process.argv[1]);
const {produceTextEvent}=await import(process.argv[2]);
const options=JSON.parse(process.argv[3]);
const c=options.context,s=c.scope,p={tenantId:s.tenantId,provider:'livekit',providerAccountId:'native-local'};
const event=produceTextEvent({eventId:c.message.eventId,providerScope:p,accountScope:s,conversationId:c.conversationId,caseId:c.caseId,receivedAt:'2030-01-01T00:00:00.000Z',channel:'web_chat',messageId:c.message.eventId,senderId:c.message.senderId,body:c.message.body},{providerScope:p,accountScope:s}).event;
const input={message:{receipt:{receiptId:c.message.receiptId,eventId:c.message.eventId,messageId:c.message.eventId,acceptanceSequence:'1',acceptedAt:'2030-01-01T00:00:00.000Z'},event,operationKey:c.operationKey,processingState:'pending',associationVersion:'1'},currentCase:{scope:s,caseId:c.caseId,revision:c.caseRevision,source:'synthetic_read_only'}};
let proxy;
let target=options.port;
if(options.corrupt){
 proxy=createServer((incoming,outgoing)=>{
  const remote=request({host:'127.0.0.1',port:options.port,method:'POST',path:'/v1/native/prepare',agent:false,headers:{Authorization:'Bearer '+'A'.repeat(43),'Content-Type':'application/json','Content-Length':incoming.headers['content-length'],Connection:'close'}},reply=>{
   const chunks=[];reply.on('data',x=>chunks.push(x));reply.on('end',()=>{const value=JSON.parse(Buffer.concat(chunks).toString());value.inputDigest='0'.repeat(64);const body=JSON.stringify(value);outgoing.writeHead(200,{'Content-Type':'application/json','Content-Length':Buffer.byteLength(body),Connection:'close'});outgoing.end(body);});
  });remote.on('error',()=>outgoing.destroy());incoming.pipe(remote);
 });await new Promise(resolve=>proxy.listen(0,'127.0.0.1',resolve));target=proxy.address().port;
}
const client=new NativeAgentHttpClient({host:'127.0.0.1',port:target},'Bearer '+'A'.repeat(43),[{bindingId:c.message.senderId,scope:s,caseId:c.caseId,conversationId:c.conversationId}],{timeoutMs:1000,cleanupMs:1000});
try{
 let result;try{result={status:'known',decision:await client.port.prepare(input,new AbortController().signal)};}catch(error){result={status:'rejected',code:error.code};}
 await client.close();if(proxy)await new Promise(resolve=>proxy.close(resolve));
 console.log(JSON.stringify({...result,active:client.metrics().active}));
}finally{await client.close();if(proxy)proxy.close();}
"""
        for corrupt in (False, True):
            value = context()
            payload = json.dumps({"port": endpoint.port, "context": value, "corrupt": corrupt})
            process = await asyncio.create_subprocess_exec(
                NODE,
                "--input-type=module",
                "-e",
                script,
                native,
                index,
                payload,
                cwd="/private/tmp",
                env={"PATH": os.defpath, "LANG": "C.UTF-8", "NO_COLOR": "1"},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                async with asyncio.timeout(5):
                    output, error = await process.communicate()
            except BaseException:
                process.kill()
                await process.wait()
                raise
            self.assertEqual(process.returncode, 0, error.decode())
            observed = json.loads(output)
            self.assertEqual(observed["active"], 0)
            self.assertEqual(observed["status"], "rejected" if corrupt else "known")
            if corrupt:
                self.assertEqual(observed["code"], "DispatchUnavailable")
            else:
                self.assertEqual(
                    observed["decision"],
                    {"kind": "investigation", "source": "scripted", "caseRevision": "1"},
                )
        self.assertEqual(len(port.calls), 2)
        await host.close()
        self.assertEqual(host.pending_count, 0)


if __name__ == "__main__":
    unittest.main()
