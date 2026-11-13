"""Actual fixed Worker callback interop and room fencing; no PG/provider/RTC."""

from __future__ import annotations

import asyncio
import gc
import inspect
import json
import os
import subprocess
import sys
import unittest
import warnings
from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4

from test_channel_policy_worker_current_result import fixture

from services.channel_policy_demo import current_result_http as m
from services.channel_policy_demo import worker_current_result as worker
from services.channel_policy_demo.current_result import encode_current_result_observation

TOKEN = "R" * 43
PRIVATE = "PRIVATE_CURRENT_HTTP_SENTINEL"
ROUTE = "/v1/channel-policy/current-result"


class Reader:
    def __init__(self, value):
        self.value = value
        self.calls = self.closes = self.pending = self.cancelled = 0
        self.entered = asyncio.Queue(8)
        self.release = None
        self.error = None

    async def read(self):
        self.calls += 1
        self.pending += 1
        self.entered.put_nowait(None)
        try:
            if self.release is not None:
                await self.release.wait()
            if self.error is not None:
                raise self.error
            return self.value
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.pending -= 1

    async def close(self):
        self.closes += 1


async def raw_exchange(endpoint, body, *, token=TOKEN):
    reader, writer = await asyncio.open_connection(endpoint.host, endpoint.port)
    try:
        wire = (
            f"POST {ROUTE} HTTP/1.1\r\nHost: 127.0.0.1:{endpoint.port}\r\nAuthorization: Bearer {token}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body
        )
        writer.write(wire)
        await writer.drain()
        async with asyncio.timeout(2):
            header = await reader.readuntil(b"\r\n\r\n")
            lines = header[:-4].split(b"\r\n")
            status = int(lines[0].split()[1])
            headers = {
                name.lower(): value.strip()
                for line in lines[1:]
                for name, _, value in (line.partition(b":"),)
            }
            assert headers.get(b"cache-control") == b"no-store"
            length = int(headers[b"content-length"])
            assert 0 < length <= 32768
            raw = await reader.readexactly(length)
            assert not await reader.read(1)
        return status, raw
    finally:
        writer.close()
        await writer.wait_closed()


class ConfigurationTests(unittest.TestCase):
    def test_closed_configuration_and_fixed_endpoint_defaults(self):
        _, value = fixture()
        reader = Reader(value)
        for fields in (
            {"current_bearer": "x"},
            {"current_bearer": TOKEN + "\n"},
            {"timeout_s": 0},
            {"timeout_s": 1.1},
            {"timeout_s": 10**1000},
            {"cleanup_timeout_s": -(10**1000)},
            {"cleanup_timeout_s": float("nan")},
            {"cleanup_timeout_s": True},
        ):
            with (
                self.subTest(fields=tuple(fields)),
                self.assertRaises(m.CurrentResultHttpError) as error,
            ):
                m.RoomCurrentResultHttp(
                    reader, **({"is_current": lambda: True, "current_bearer": TOKEN} | fields)
                )
            self.assertEqual(str(error.exception), "invalid_configuration")
        self.assertEqual(
            inspect.signature(m.RoomCurrentResultHttp.start).parameters["port"].default, 11031
        )
        self.assertEqual(reader.calls, 0)

    def test_sync_reader_property_and_async_predicates_rejected_without_execution(self):
        touched = []

        class Property:
            @property
            def read(self):
                touched.append(True)
                raise RuntimeError(PRIVATE)

        class Sync:
            def read(self):
                touched.append(True)

        for reader in (Property(), Sync(), object()):
            with self.assertRaises(m.CurrentResultHttpError):
                m.RoomCurrentResultHttp(reader, is_current=lambda: True, current_bearer=TOKEN)

        async def predicate():
            touched.append(True)
            return True

        async def generator():
            touched.append(True)
            yield True

        def sync_generator():
            touched.append(True)
            yield True

        _, value = fixture()
        for callback in (predicate, generator, sync_generator):
            with self.assertRaises(m.CurrentResultHttpError):
                m.RoomCurrentResultHttp(Reader(value), is_current=callback, current_bearer=TOKEN)
        self.assertEqual(touched, [])

    def test_import_does_not_load_sdk_application_or_start_io(self):
        code = r"""import asyncio,importlib.abc,json,socket,sys,threading
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.startswith(('livekit','services.channel_policy_demo.application')):raise AssertionError('SDK/app import')
sys.meta_path.insert(0,Deny())
def denied(*args,**kwargs):raise AssertionError('I/O before explicit start')
socket.socket=denied;asyncio.create_task=denied;threading.Thread.start=denied
from services.channel_policy_demo import current_result_http
assert not any(n.startswith('livekit') for n in sys.modules)
print(json.dumps({'cold':True}))
"""
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code],
            cwd="/private/tmp",
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            env={"PATH": os.defpath, "LANG": "C.UTF-8", "NO_COLOR": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"cold": True})


class CurrentHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.binding, self.value = fixture()
        self.reader = Reader(self.value)
        self.current = True
        self.host = m.RoomCurrentResultHttp(
            self.reader,
            is_current=lambda: self.current,
            current_bearer=TOKEN,
            timeout_s=0.05,
            cleanup_timeout_s=0.05,
        )
        self.endpoint = await self.host.start(0)
        self.clients = []
        self.addAsyncCleanup(self.host.close)

    def client(self, *, token=TOKEN, **options):
        client = worker.WorkerCurrentResultClient(
            worker.WorkerCurrentEndpoint(port=self.endpoint.port),
            self.binding,
            worker.CurrentResultCredential(token),
            **options,
        )
        self.clients.append(client)
        self.addAsyncCleanup(client.close)
        return client

    async def test_actual_public_client_observes_all_three_closed_states(self):
        client = self.client()
        for state in ("current", "no_delivery", "not_applicable"):
            self.reader.value = replace(
                self.value, state=state, result=self.value.result if state == "current" else None
            )
            observed = await client.read()
            self.assertEqual(observed, self.reader.value)
            self.assertEqual(worker.current_result_fact(observed).state, state)
        self.assertEqual(self.reader.calls, 3)
        await self.host.close()
        self.assertEqual(
            (self.host.pending_count, self.reader.pending, self.reader.closes), (0, 0, 0)
        )

    async def test_wrong_role_and_extra_authority_selectors_do_not_read_app(self):
        for token in ("A" * 43, "V" * 43):
            with self.assertRaises(worker.WorkerCurrentResultError) as error:
                await self.client(token=token).read()
            self.assertEqual(error.exception.code, "unauthorized")
        for extra in (
            {"scope": {}},
            {"workId": str(uuid4())},
            {"deliveryId": str(uuid4())},
            {"nativeGrant": PRIVATE},
            {"generation": "1"},
        ):
            status, raw = await raw_exchange(
                self.endpoint, json.dumps({"schemaVersion": 1, **extra}).encode()
            )
            self.assertEqual(status, 400)
            self.assertNotIn(PRIVATE.encode(), raw)
        self.assertEqual(self.reader.calls, 0)
        self.assertEqual((await self.client().read()).state, "current")

    async def test_request_caps_duplicates_and_versions_are_not_empty_success(self):
        for body in (
            b"{}",
            b'{"schemaVersion":true}',
            b'{"schemaVersion":2}',
            b'{"schemaVersion":1,"schemaVersion":1}',
            b'{"schemaVersion":NaN}',
            b" " * 1025,
        ):
            status, _ = await raw_exchange(self.endpoint, body)
            self.assertEqual(status, 400)
        self.assertEqual(self.reader.calls, 0)
        self.assertEqual((await self.client().read()).state, "current")

    async def test_physical_room_closed_before_request_denies_without_app_read(self):
        self.current = False
        with self.assertRaises(worker.WorkerCurrentResultError) as error:
            await self.client().read()
        self.assertEqual(error.exception.code, "closed")
        self.assertEqual(self.reader.calls, 0)
        self.current = True
        self.assertEqual((await self.client().read()).state, "current")

    async def test_end_during_read_never_discloses_old_result_bytes(self):
        self.reader.release = asyncio.Event()
        self.addCleanup(self.reader.release.set)
        read = asyncio.create_task(self.client().read())
        await self.reader.entered.get()
        self.current = False
        self.reader.release.set()
        with self.assertRaises(worker.WorkerCurrentResultError) as error:
            await read
        self.assertEqual(error.exception.code, "closed")
        self.assertEqual(self.reader.cancelled, 0)
        self.assertEqual(self.reader.closes, 0)

    async def test_room_end_after_exchange_settles_is_fenced_at_actual_response_admission(self):
        loop = asyncio.get_running_loop()
        actual_create = loop.create_task
        observed = []

        def create(operation, **kwargs):
            task = actual_create(operation, **kwargs)
            if getattr(getattr(operation, "cr_code", None), "co_name", None) == "_invoke":

                def end_room(done):
                    # Registered before the transport's waiter callback: all
                    # read-time checks passed, but End precedes response send.
                    observed.append(done.result())
                    self.current = False

                task.add_done_callback(end_room)
            return task

        with (
            patch.object(loop, "create_task", create),
            self.assertRaises(worker.WorkerCurrentResultError) as error,
        ):
            await self.client().read()
        self.assertEqual(error.exception.code, "closed")
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0], encode_current_result_observation(self.value))
        self.assertEqual(self.host.metrics()["read"], 0)
        self.current = True
        self.assertEqual((await self.client().read()).state, "current")

    async def test_held_actual_read_survives_timeout_and_close_observer(self):
        self.reader.release = asyncio.Event()
        self.addCleanup(self.reader.release.set)
        with self.assertRaises(worker.WorkerCurrentResultError) as error:
            await self.client().read()
        self.assertEqual(error.exception.code, "unavailable")
        self.assertEqual((self.host.metrics()["active_calls"], self.reader.pending), (1, 1))
        with self.assertRaises(m.CurrentResultHttpError) as incomplete:
            await self.host.close()
        self.assertEqual(str(incomplete.exception), "cleanup_incomplete")
        self.assertEqual(self.host.pending_count, 1)
        self.reader.release.set()
        await self.host.close()
        self.assertEqual(
            (self.host.pending_count, self.reader.pending, self.reader.closes), (0, 0, 0)
        )

    async def test_disconnected_worker_retains_actual_parent_read(self):
        self.reader.release = asyncio.Event()
        self.addCleanup(self.reader.release.set)
        client = self.client(timeout_s=0.02)
        read = asyncio.create_task(client.read())
        await self.reader.entered.get()
        await client.close()
        with self.assertRaises(worker.WorkerCurrentResultError):
            await read
        self.assertEqual(self.reader.pending, 1)
        self.assertEqual(self.reader.cancelled, 0)
        actual = tuple(self.host._calls)
        self.reader.release.set()
        # Observe the actual retained call and its registered settlement
        # callback, rather than racing a successful cleanup observation.
        await asyncio.gather(*actual, return_exceptions=True)
        await self.host.close()
        self.assertEqual(self.reader.pending, 0)

    async def test_cancelled_host_close_keeps_actual_owner_until_explicit_retry(self):
        self.reader.release = asyncio.Event()
        self.addCleanup(self.reader.release.set)
        with self.assertRaises(worker.WorkerCurrentResultError):
            await self.client().read()
        close = asyncio.create_task(self.host.close())
        await asyncio.sleep(0)
        close.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await close
        self.assertEqual(self.host.pending_count, 1)
        self.reader.release.set()
        await self.host.close()
        self.assertEqual(self.host.pending_count, 0)

    async def test_old_capability_cannot_select_new_room_at_reused_fixed_endpoint(self):
        old = self.client()
        self.assertEqual((await old.read()).state, "current")
        self.current = False
        await self.host.close()
        other = Reader(replace(self.value, state="no_delivery", result=None))
        host = m.RoomCurrentResultHttp(other, is_current=lambda: True, current_bearer="B" * 43)
        self.addAsyncCleanup(host.close)
        await host.start(self.endpoint.port)
        with self.assertRaises(worker.WorkerCurrentResultError) as error:
            await old.read()
        self.assertEqual(error.exception.code, "unauthorized")
        self.assertEqual(other.calls, 0)
        new = self.client(token="B" * 43)
        self.assertEqual((await new.read()).state, "no_delivery")
        self.assertEqual(
            (self.reader.calls, other.calls, self.reader.closes, other.closes), (1, 1, 0, 0)
        )

    async def test_client_rejects_foreign_parent_binding_even_for_empty_state(self):
        self.reader.value = replace(
            self.value, profile_id=str(uuid4()), state="no_delivery", result=None
        )
        with self.assertRaises(worker.WorkerCurrentResultError) as error:
            await self.client().read()
        self.assertEqual(error.exception.code, "unauthorized")
        self.reader.value = self.value
        self.assertEqual((await self.client().read()).state, "current")

    async def test_read_errors_remain_finite_operational_errors_and_never_empty(self):
        touched = []

        class Getter(Exception):
            @property
            def code(self):
                touched.append(True)
                raise RuntimeError(PRIVATE)

        class Error(Exception):
            pass

        capacity = Error(PRIVATE)
        capacity.code = "capacity"
        array = Error(PRIVATE)
        array.code = []
        for failure, code in (
            (Getter(PRIVATE), "unavailable"),
            (array, "unavailable"),
            (capacity, "capacity"),
            (RuntimeError(PRIVATE), "unavailable"),
        ):
            self.reader.error = failure
            with self.assertRaises(worker.WorkerCurrentResultError) as error:
                await self.client().read()
            self.assertEqual(error.exception.code, code)
            self.assertNotIn(PRIVATE, str(error.exception))
        self.assertEqual(touched, [])
        self.reader.error = None
        self.assertEqual((await self.client().read()).state, "current")

    async def test_current_predicate_fault_does_not_read_or_disclose(self):
        bad = m.RoomCurrentResultHttp(
            self.reader,
            is_current=lambda: (_ for _ in ()).throw(RuntimeError(PRIVATE)),
            current_bearer=TOKEN,
        )
        self.addAsyncCleanup(bad.close)
        endpoint = await bad.start(0)
        status, raw = await raw_exchange(endpoint, b'{"schemaVersion":1}')
        self.assertEqual(status, 503)
        self.assertNotIn(PRIVATE.encode(), raw)
        self.assertEqual(self.reader.calls, 0)
        self.assertEqual((await self.client().read()).state, "current")

    async def test_malformed_reader_observation_is_unavailable_not_current_or_empty(self):
        self.reader.value = {"private": PRIVATE}
        with self.assertRaises(worker.WorkerCurrentResultError) as error:
            await self.client().read()
        self.assertEqual(error.exception.code, "unavailable")
        self.reader.value = self.value
        self.assertEqual((await self.client().read()).state, "current")

    async def test_four_actual_read_lifetimes_remain_bounded_after_waiter_timeouts(self):
        self.reader.release = asyncio.Event()
        self.addCleanup(self.reader.release.set)
        requests = [
            asyncio.create_task(raw_exchange(self.endpoint, b'{"schemaVersion":1}'))
            for _ in range(4)
        ]
        for _ in range(4):
            await self.reader.entered.get()
        results = await asyncio.gather(*requests)
        self.assertTrue(all(status == 503 for status, _ in results))
        self.assertEqual((self.reader.pending, self.host.metrics()["handlers"]), (4, 4))
        self.assertEqual((await raw_exchange(self.endpoint, b'{"schemaVersion":1}'))[0], 429)
        self.assertEqual(self.reader.calls, 4)
        actual = tuple(self.host._calls)
        self.reader.release.set()
        await asyncio.gather(*actual, return_exceptions=True)
        self.assertEqual((await self.client().read()).state, "current")
        self.assertEqual(self.reader.closes, 0)

    async def test_allocation_failures_close_coroutines_and_preserve_existing_owner(self):
        loop = asyncio.get_running_loop()
        original = loop.create_task
        operations = []

        def failed(operation, **kwargs):
            if getattr(getattr(operation, "cr_code", None), "co_name", None) == "_invoke":
                operations.append(operation)
                raise RuntimeError(PRIVATE)
            return original(operation, **kwargs)

        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always", RuntimeWarning)
            with patch.object(loop, "create_task", failed):
                status, raw = await raw_exchange(self.endpoint, b'{"schemaVersion":1}')
            self.assertEqual(status, 503)
            self.assertNotIn(PRIVATE.encode(), raw)
            gc.collect()
            self.assertFalse(any("never awaited" in str(value.message) for value in observed))
        self.assertEqual(inspect.getcoroutinestate(operations[0]), inspect.CORO_CLOSED)
        self.assertEqual(self.reader.calls, 0)
        self.assertEqual((await self.client().read()).state, "current")
        listener = self.host._listener
        with (
            patch.object(loop, "create_task", side_effect=RuntimeError(PRIVATE)),
            self.assertRaises(m.CurrentResultHttpError),
        ):
            await self.host.close()
        self.assertGreaterEqual(listener.fileno(), 0)
        await self.host.close()
        self.assertEqual(listener.fileno(), -1)

    async def test_logger_failure_preserves_known_value_and_no_borrowed_close(self):
        with patch.object(m.LOGGER, "info", side_effect=RuntimeError(PRIVATE)):
            observed = await self.client().read()
        self.assertEqual(observed, self.value)
        self.assertEqual(self.host.metrics()["telemetry_failed"], 1)
        self.assertEqual(self.host.metrics()["read"], 1)
        await self.host.close()
        self.assertEqual(self.reader.closes, 0)
        self.assertTrue(
            all(type(value) is int and value >= 0 for value in self.host.metrics().values())
        )


if __name__ == "__main__":
    unittest.main()
