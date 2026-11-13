"""Fixed native-worker readiness observations cannot disclose or grant authority."""

import asyncio
import json
import os
import unittest
from unittest.mock import patch

import httpx

from services.control_api import business_availability as availability
from services.control_api.settings import Settings

URL = "http://conversation-agent:8082"
PRIVATE = "SECRET_SENTINEL"
BASE = {
    "worker_type": "JT_ROOM",
    "agent_name": "local-business-agent",
    "sdk_version": "1.8.11",
    "protocol_version": 1,
}


class WorkerAvailabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = httpx.AsyncClient
        self.calls = []
        self.options = []
        self.now = [0.0]
        self.adapter = availability.NativeWorkerAvailability(URL, clock=lambda: self.now[0])

    async def observe(self, payload=None, *, body=None, health=200, worker=200, headers=None):
        def response(request):
            self.calls.append(request)
            if request.url.path == "/":
                return httpx.Response(health, stream=httpx.ByteStream(PRIVATE.encode()))
            data = (
                body
                if body is not None
                else json.dumps(BASE if payload is None else payload).encode()
            )
            return httpx.Response(worker, stream=httpx.ByteStream(data), headers=headers or {})

        def create(**kwargs):
            self.options.append(kwargs)
            return self.client(**kwargs, transport=httpx.MockTransport(response))

        with patch.object(availability.httpx, "AsyncClient", side_effect=create):
            return await self.adapter.available()

    async def test_default_omitted_protobuf_zeros_and_explicit_float_zeros_are_idle(self):
        self.assertFalse(await self.observe())
        self.now[0] = 1.6
        self.assertTrue(await self.observe({**BASE, "active_jobs": 0.0, "worker_load": 0.0}))
        self.assertEqual([item.url.path for item in self.calls], ["/", "/worker", "/", "/worker"])
        self.assertTrue(all(item.method == "GET" for item in self.calls))
        self.assertTrue(all("Authorization" not in item.headers for item in self.calls))
        self.assertEqual(len(self.options), 2)
        self.assertTrue(
            all(
                value["trust_env"] is False
                and value["timeout"] == 0.25
                and value["follow_redirects"] is False
                for value in self.options
            )
        )

    async def test_stable_idle_is_consumed_and_resets_on_busy_unhealthy_and_clock_regression(self):
        self.assertFalse(await self.observe())
        self.now[0] = 1.59
        self.assertFalse(await self.observe())
        self.now[0] = 1.6
        self.assertTrue(await self.observe())
        self.now[0] = 10
        self.assertFalse(
            await self.observe()
        )  # Prior readiness cannot authorize another admission.
        self.now[0] = 11
        self.assertFalse(await self.observe({**BASE, "active_jobs": 1.0}))
        self.now[0] = 20
        self.assertFalse(await self.observe())
        self.now[0] = 21
        self.assertFalse(await self.observe(health=503))
        self.now[0] = 30
        self.assertFalse(await self.observe())
        self.now[0] = 29
        self.assertFalse(await self.observe())  # Clock regression starts a new window.
        self.now[0] = 30.6
        self.assertTrue(await self.observe())
        self.now[0] = 40
        self.assertFalse(await self.observe())
        self.now[0] = 41
        self.assertFalse(await self.observe(body=b"invalid"))
        self.now[0] = 50
        self.assertFalse(await self.observe())
        self.now[0] = 51.6
        self.assertTrue(await self.observe())

    async def test_nonfinite_bool_huge_or_negative_clock_resets_the_observation(self):
        for value in (True, "1", -1, float("nan"), float("inf"), 10**1000):
            with self.subTest(kind=type(value).__name__):
                self.now[0] = 0.0
                self.assertFalse(await self.observe())
                self.now[0] = value
                self.assertFalse(await self.observe())
                self.now[0] = 100.0
                self.assertFalse(await self.observe())
                self.now[0] = 101.61
                self.assertTrue(await self.observe())

    async def test_full_unregistered_missing_stale_health_and_wrong_worker_fail_closed(self):
        for health, worker in ((503, 200), (404, 200), (200, 503), (200, 404), (302, 200)):
            with self.subTest(health=health, worker=worker):
                self.assertFalse(await self.observe(health=health, worker=worker))
        for changes in (
            {"active_jobs": 1.0},
            {"worker_load": 1.0},
            {"worker_load": -0.1},
            {"agent_name": "local-transport-agent"},
            {"sdk_version": "future"},
            {"protocol_version": True},
            {"worker_type": "JT_PUBLISHER"},
            {"private": PRIVATE},
        ):
            with self.subTest(fields=tuple(changes)):
                self.assertFalse(await self.observe({**BASE, **changes}))
        for field in BASE:
            with self.subTest(missing=field):
                self.assertFalse(
                    await self.observe({key: value for key, value in BASE.items() if key != field})
                )

    async def test_malformed_duplicate_bool_nonfinite_and_huge_numbers_never_become_idle(self):
        for body in (
            b"",
            b"[]",
            b"null",
            b"not-json",
            b"\xff",
            b'{"agent_name":"a","agent_name":"b"}',
        ):
            with self.subTest(length=len(body)):
                self.assertFalse(await self.observe(body=body))
        for field in ("active_jobs", "worker_load"):
            for value in (True, "0", -1, float("inf"), float("nan"), 10**1000):
                with self.subTest(field=field, kind=type(value).__name__):
                    self.assertFalse(await self.observe({**BASE, field: value}))

    async def test_declared_streamed_and_encoded_responses_are_bounded(self):
        for headers in (
            {"Content-Length": "8193"},
            {"Content-Length": PRIVATE},
            {"Content-Encoding": "gzip"},
        ):
            with self.subTest(headers=tuple(headers)):
                self.assertFalse(await self.observe(headers=headers))
        self.assertFalse(await self.observe(body=b" " * 8193))

    async def test_unavailable_private_error_is_never_formatted_or_logged(self):
        class PrivateError(RuntimeError):
            def __str__(self):
                raise AssertionError("Do not format private health errors")

        def failed(request):
            raise PrivateError(PRIVATE)

        def create(**kwargs):
            return self.client(**kwargs, transport=httpx.MockTransport(failed))

        with patch.object(availability.httpx, "AsyncClient", side_effect=create):
            self.assertFalse(await availability.NativeWorkerAvailability(URL).available())
        self.assertFalse(await self.observe(body=("{" + PRIVATE).encode()))

    async def test_total_deadline_bounds_stalled_response_and_propagates_caller_cancellation(self):
        async def blocked(request):
            await asyncio.Event().wait()

        def create(**kwargs):
            return self.client(**kwargs, transport=httpx.MockTransport(blocked))

        with patch.object(availability.httpx, "AsyncClient", side_effect=create):
            async with asyncio.timeout(1):
                self.assertFalse(await availability.NativeWorkerAvailability(URL).available())
            task = asyncio.create_task(availability.NativeWorkerAvailability(URL).available())
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task


class WorkerURLSettingsTests(unittest.TestCase):
    def credentials(self):
        return {
            "livekit_url": "ws://livekit:7880",
            "livekit_public_url": "ws://localhost:17880",
            "livekit_api_key": "synthetic-key",
            "livekit_api_secret": "s" * 40,
            "local_access_token": "a" * 40,
            "postgres_password": "p" * 32,
        }

    def test_only_fixed_composed_or_owned_isolated_worker_is_valid(self):
        for url in (URL, "http://p1-g-" + "a" * 32 + "-native:8082"):
            self.assertEqual(availability.validate_worker_url(url), url)
            self.assertEqual(
                Settings(**self.credentials(), business_worker_url=url).business_worker_url, url
            )
        for url in (
            "http://localhost:8082",
            "https://conversation-agent:8082",
            "http://conversation-agent:8083",
            "http://conversation-agent:8082/",
            "http://conversation-agent:8082/worker",
            "http://secret@conversation-agent:8082",
            "http://conversation-agent:8082?secret=value",
            "http://conversation-agent:8082#secret",
            "http://CONVERSATION-AGENT:8082",
            "http://p1-g-short-native:8082",
            "http://conversation-agent:8082.evil.invalid",
        ):
            with self.subTest(length=len(url)), self.assertRaises(ValueError) as caught:
                Settings(**self.credentials(), business_worker_url=url)
            self.assertNotIn("secret", str(caught.exception).lower())
        self.assertEqual(Settings(**self.credentials()).business_worker_url, URL)

    def test_environment_uses_explicit_isolated_worker_and_keeps_secret_fields_private(self):
        endpoint = "http://p1-g-" + "b" * 32 + "-native:8082"
        environment = {
            "LIVEKIT_API_KEY": "synthetic-key",
            "LIVEKIT_API_SECRET": "s" * 40,
            "LOCAL_ACCESS_TOKEN": "a" * 40,
            "POSTGRES_PASSWORD": "p" * 32,
            "P1_BUSINESS_WORKER_URL": endpoint,
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.business_worker_url, endpoint)
        for key in ("LIVEKIT_API_SECRET", "LOCAL_ACCESS_TOKEN", "POSTGRES_PASSWORD"):
            self.assertNotIn(environment[key], repr(settings))
