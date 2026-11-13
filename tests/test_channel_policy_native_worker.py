"""Single-session composition and dependency lifetime; no remote providers or RTC."""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import signal
import socket
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from channel_continuity.codec import AccountScope, ProviderScope
from channel_continuity.native_models import NativeBinding, NativeCredential, NativeEndpoint
from services.channel_policy_demo import native_worker as m
from services.channel_policy_demo.native_worker_config import NativeWorkerConfig

PRIVATE = "PRIVATE_NATIVE_WORKER_DEPENDENCY"


def config():
    sockets = [socket.socket() for _ in range(4)]
    try:
        for item in sockets:
            item.bind(("127.0.0.1", 0))
        ports = [item.getsockname()[1] for item in sockets]
    finally:
        for item in sockets:
            item.close()
    return NativeWorkerConfig(
        profile_id=str(uuid4()),
        binding=NativeBinding(
            str(uuid4()),
            ProviderScope("tenant_demo", "livekit", "joined_rtc"),
            AccountScope("tenant_demo", "account_demo"),
            "case_demo",
            "conversation_demo",
            "room_demo",
            "caller_demo",
            "agent_demo",
        ),
        livekit_token="eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhZ2VudF9kZW1vIn0.c2ln",
        native_credential=NativeCredential("n" * 43),
        prepare_bearer="p" * 43,
        current_bearer="c" * 43,
        native_endpoint=NativeEndpoint("127.0.0.1", ports[0]),
        prepare_port=ports[1],
        rehydration_endpoint=NativeEndpoint("127.0.0.1", ports[2]),
        current_port=ports[3],
    )


class WorkerComposition(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Genuine selected modules are patched at their public constructor seam.
        # The separate real-SDK test below exercises the unpatched composition.
        from livekit import rtc

        from channel_continuity import native, native_rehydration
        from services.channel_policy_demo import current_result_context

        self.config = config()
        self.trace, self.instances, self.workers = [], {}, []
        self.holds, self.fail = {}, set()
        outer = self

        class Owner:
            def __init__(self, label):
                self.label = label
                outer.trace.append("new:" + label)
                outer.instances.setdefault(label, []).append(self)
                if "construct:" + label in outer.fail:
                    raise RuntimeError(PRIVATE)

            async def aclose(self):
                outer.trace.append("close:" + self.label)
                if event := outer.holds.get("close:" + self.label):
                    await event.wait()
                if "close:" + self.label in outer.fail:
                    raise RuntimeError(PRIVATE)
                outer.trace.append("closed:" + self.label)

            async def close(self):
                await self.aclose()

        class Models(Owner):
            def __init__(self):
                super().__init__("models")
                self.stt, self.llm, self.tts = object(), object(), object()

        async def load(profile):
            outer.trace.append("load")
            if event := outer.holds.get("load"):
                await event.wait()
            if "load" in outer.fail:
                raise RuntimeError(PRIVATE)
            return Models()

        class Intake(Owner):
            def __init__(self, endpoint, credential, binding):
                super().__init__("intake")
                self.binding, self.credential, self.endpoint = binding, credential, endpoint

        class Context(Owner):
            def __init__(self, endpoint, credential, binding):
                super().__init__("context")
                self.binding = binding

        class Runtime(Owner):
            def __init__(self, binding, intake, **kwargs):
                super().__init__("runtime")
                self.binding = binding
                self.arguments = kwargs
                self.closed = False
                self.session = SimpleNamespace(
                    on=lambda event, callback: setattr(self, "sdk_callback", callback),
                    off=lambda event, callback: None,
                )

            async def start(self, room):
                outer.trace.append("sdk:start")
                if event := outer.holds.get("sdk:start"):
                    await event.wait()
                if self.closed:
                    raise RuntimeError(PRIVATE)
                outer.trace.append("sdk:ready")

            async def aclose(self):
                self.closed = True
                await super().aclose()

        class Host(Owner):
            def __init__(self, runtime, *, prepare_bearer):
                super().__init__("host")
                self.runtime = runtime
                self.prepare_bearer = prepare_bearer

            async def start(self, *, port):
                outer.trace.append("host:start")
                return m.NativePrepareEndpoint("127.0.0.1", port)

        class Room(Owner):
            def __init__(self):
                super().__init__("room")
                self.remote_participants = {}
                self.callbacks = {}

            def on(self, name, callback):
                self.callbacks[name] = callback

            def off(self, name, callback):
                if self.callbacks.get(name) is callback:
                    del self.callbacks[name]

            async def connect(self, url, token, options):
                outer.trace.append("rtc:connect")
                self.values = url, token, options
                if event := outer.holds.get("rtc:connect"):
                    await event.wait()
                if "rtc:connect" in outer.fail:
                    raise RuntimeError(PRIVATE)
                outer.trace.append("rtc:connected")

            async def disconnect(self):
                await self.aclose()

            def participant(self, identity):
                value = SimpleNamespace(identity=identity)
                self.remote_participants[identity] = value
                if callback := self.callbacks.get("participant_connected"):
                    callback(value)

        patches = [
            patch.object(m, "load_scripted_models", load),
            patch.object(
                current_result_context, "with_current_result", lambda *args: Owner("wrapper")
            ),
            patch.object(native, "NativeHttpIntake", Intake),
            patch.object(native, "NativeRuntime", Runtime),
            patch.object(native_rehydration, "NativeContextHttpClient", Context),
            patch.object(m, "NativePrepareHttp", Host),
            patch.object(rtc, "Room", Room),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    async def asyncTearDown(self):
        self.fail.clear()
        for event in self.holds.values():
            event.set()
        async with asyncio.timeout(2):
            for worker in self.workers:
                while not worker.metrics()["closed"]:
                    try:
                        await worker.close()
                    except m.NativeWorkerError as error:
                        if error.code != "cleanup_incomplete":
                            raise

    def worker(self, **kwargs):
        worker = m.NativeWorker(self.config, **kwargs)
        self.workers.append(worker)
        return worker

    async def until(self, predicate):
        async with asyncio.timeout(1):
            while not predicate():
                await asyncio.sleep(0)

    async def test_sdk_close_event_fences_ready_and_retains_actual_worker_cleanup(self):
        from livekit.agents.voice import CloseEvent, CloseReason

        worker = self.worker(cleanup_timeout_s=0.02)
        await worker.start_prepare()
        connecting = asyncio.create_task(worker.connect_room())
        await self.until(lambda: "new:room" in self.trace)
        self.instances["room"][0].participant(self.config.binding.participant_id)
        await connecting
        self.assertEqual(worker.metrics()["ready"], 1)
        self.holds["close:runtime"] = asyncio.Event()
        self.instances["runtime"][0].sdk_callback(
            CloseEvent(reason=CloseReason.PARTICIPANT_DISCONNECTED)
        )
        self.assertEqual(worker.metrics()["ready"], 0)
        self.assertTrue(worker.session_closed)
        self.assertEqual(worker.session_close_reason, "participant_disconnected")
        await worker.wait_session_closed()
        with self.assertRaisesRegex(m.NativeWorkerError, "^cleanup_incomplete$"):
            await worker.close()
        self.assertIn("closed:host", self.trace)
        self.assertNotIn("close:models", self.trace)
        self.holds["close:runtime"].set()
        await worker.close()
        self.assertEqual(worker.metrics()["owned_resources"], 0)
        self.assertEqual(self.trace.count("close:runtime"), 1)

    async def test_sdk_close_during_start_cannot_emit_ready_after_late_sdk_return(self):
        from livekit.agents.voice import CloseEvent, CloseReason

        observed = []
        worker = self.worker(observer=observed.append)
        await worker.start_prepare()
        self.holds["sdk:start"] = asyncio.Event()
        connecting = asyncio.create_task(worker.connect_room())
        await self.until(lambda: "new:room" in self.trace)
        self.instances["room"][0].participant(self.config.binding.participant_id)
        await self.until(lambda: "sdk:start" in self.trace)
        self.instances["runtime"][0].sdk_callback(CloseEvent(reason=CloseReason.USER_INITIATED))
        self.holds["sdk:start"].set()
        with self.assertRaises((m.NativeWorkerError, asyncio.CancelledError)):
            await connecting
        await worker.close()
        self.assertNotIn("ready", observed)
        self.assertIn("session_closed", observed)
        self.assertEqual(worker.metrics()["owned_resources"], 0)

    async def test_sdk_close_allocation_failure_is_finite_and_cleanup_retry_keeps_owners(self):
        from livekit.agents.voice import CloseEvent, CloseReason

        worker = self.worker()
        await worker.start_prepare()
        self.instances["runtime"][0].sdk_callback(CloseEvent(reason=CloseReason.ERROR))
        with (
            patch.object(m.asyncio, "create_task", side_effect=RuntimeError(PRIVATE)),
            self.assertRaisesRegex(m.NativeWorkerError, "^cleanup_incomplete$"),
        ):
            worker._begin_close()
        self.assertEqual(worker.metrics()["ready"], 0)
        await worker.close()
        self.assertEqual(worker.metrics()["owned_resources"], 0)

    async def test_construction_and_unstarted_close_create_no_sdk_or_io_owners(self):
        worker = self.worker()
        self.assertEqual(self.trace, [])
        await worker.close()
        self.assertEqual(worker.metrics()["owned_resources"], 0)
        with self.assertRaisesRegex(m.NativeWorkerError, "^closed$"):
            await worker.start_prepare()

    async def test_prepare_is_ready_before_room_and_sole_session_uses_narrow_readers(self):
        worker = self.worker()
        endpoints = await asyncio.gather(worker.start_prepare(), worker.start_prepare())
        self.assertEqual(endpoints[0], endpoints[1])
        self.assertEqual(endpoints[0].port, self.config.prepare_port)
        self.assertNotIn("new:room", self.trace)
        self.assertEqual(self.trace.count("new:runtime"), 1)
        self.assertEqual(self.trace.count("load"), 1)
        runtime = self.instances["runtime"][0]
        self.assertEqual(runtime.binding, self.config.binding)
        self.assertEqual(runtime.arguments["rehydration"].port.binding, self.config.binding)
        self.assertEqual(self.instances["intake"][0].credential, self.config.native_credential)
        self.assertEqual(self.instances["host"][0].prepare_bearer, self.config.prepare_bearer)
        await worker.close()
        self.assertLess(self.trace.index("closed:runtime"), self.trace.index("close:wrapper"))
        self.assertLess(self.trace.index("closed:host"), self.trace.index("close:wrapper"))
        self.assertLess(self.trace.index("closed:wrapper"), self.trace.index("close:models"))
        self.assertEqual(worker.metrics()["owned_resources"], 0)

    async def test_wrong_participant_cannot_start_sdk_then_current_participant_progresses(self):
        stages = []
        worker = self.worker(observer=stages.append)
        await worker.start_prepare()
        first = asyncio.create_task(worker.connect_room())
        second = asyncio.create_task(worker.connect_room())
        await self.until(lambda: "new:room" in self.trace and self.instances["room"][0].callbacks)
        room = self.instances["room"][0]
        room.participant("foreign_caller")
        await asyncio.sleep(0)
        self.assertNotIn("sdk:start", self.trace)
        room.participant(self.config.binding.participant_id)
        await asyncio.gather(first, second)
        self.assertEqual(self.trace.count("rtc:connect"), 1)
        self.assertEqual(self.trace.count("sdk:start"), 1)
        self.assertEqual(worker.metrics()["ready"], 1)
        self.assertEqual(
            stages, ["prepare_ready", "room_connected", "waiting_participant", "ready"]
        )
        self.assertEqual(room.values[2].connect_timeout, 10)
        self.assertFalse(room.callbacks)
        await worker.close()
        self.assertLess(self.trace.index("closed:runtime"), self.trace.index("close:room"))

    async def test_cancelled_prepare_waiter_retains_one_actual_loader_and_late_owner(self):
        worker = self.worker()
        self.holds["load"] = asyncio.Event()
        starting = asyncio.create_task(worker.start_prepare())
        await self.until(lambda: "load" in self.trace)
        starting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await starting
        self.assertEqual(worker.metrics()["startup_active"], 1)
        self.holds["load"].set()
        await worker.start_prepare()
        self.assertEqual(self.trace.count("load"), 1)
        await worker.close()
        self.assertEqual(self.trace.count("close:models"), 1)

    async def test_end_during_model_load_closes_late_models_without_session_or_listener(self):
        worker = self.worker(cleanup_timeout_s=0.02)
        self.holds["load"] = asyncio.Event()
        starting = asyncio.create_task(worker.start_prepare())
        await self.until(lambda: "load" in self.trace)
        with self.assertRaisesRegex(m.NativeWorkerError, "^cleanup_incomplete$"):
            await worker.close()
        self.holds["load"].set()
        with self.assertRaisesRegex(m.NativeWorkerError, "^closed$"):
            await starting
        await worker.close()
        self.assertEqual(self.trace[-3:], ["new:models", "close:models", "closed:models"])
        self.assertNotIn("new:runtime", self.trace)
        self.assertNotIn("host:start", self.trace)

    async def test_original_startup_timeout_never_renews_or_allows_late_publication(self):
        worker = self.worker(startup_timeout_s=0.02)
        self.holds["load"] = asyncio.Event()
        with self.assertRaisesRegex(m.NativeWorkerError, "^unavailable$"):
            await worker.start_prepare()
        self.holds["load"].set()
        await self.until(lambda: not worker.metrics()["startup_active"])
        with self.assertRaisesRegex(m.NativeWorkerError, "^unavailable$"):
            await worker.start_prepare()
        self.assertNotIn("new:runtime", self.trace)
        await worker.close()
        self.assertEqual(self.trace.count("close:models"), 1)

    async def test_late_actual_rtc_connect_is_retained_then_disconnected_after_end(self):
        worker = self.worker(cleanup_timeout_s=0.02)
        await worker.start_prepare()
        self.holds["rtc:connect"] = asyncio.Event()
        connecting = asyncio.create_task(worker.connect_room())
        await self.until(lambda: "rtc:connect" in self.trace)
        with self.assertRaisesRegex(m.NativeWorkerError, "^cleanup_incomplete$"):
            await worker.close()
        self.assertEqual(worker.metrics()["connect_active"], 1)
        self.assertNotIn("close:room", self.trace)
        self.assertNotIn("sdk:start", self.trace)
        self.holds["rtc:connect"].set()
        with self.assertRaises(asyncio.CancelledError):
            await connecting
        await worker.close()
        self.assertLess(self.trace.index("rtc:connected"), self.trace.index("close:room"))
        self.assertEqual(self.trace.count("close:room"), 1)
        self.assertNotIn("sdk:start", self.trace)

    async def test_end_waiting_for_browser_removes_callback_and_never_starts_sdk(self):
        worker = self.worker()
        await worker.start_prepare()
        connecting = asyncio.create_task(worker.connect_room())
        await self.until(lambda: self.instances.get("room") and self.instances["room"][0].callbacks)
        await worker.close()
        with self.assertRaises(asyncio.CancelledError):
            await connecting
        self.assertFalse(self.instances["room"][0].callbacks)
        self.assertNotIn("sdk:start", self.trace)

    async def test_actual_sdk_start_retains_models_after_end_until_start_settles(self):
        worker = self.worker(cleanup_timeout_s=0.02)
        await worker.start_prepare()
        self.holds["sdk:start"] = asyncio.Event()
        connecting = asyncio.create_task(worker.connect_room())
        await self.until(lambda: self.instances.get("room") and self.instances["room"][0].callbacks)
        self.instances["room"][0].participant(self.config.binding.participant_id)
        await self.until(lambda: "sdk:start" in self.trace)
        with self.assertRaisesRegex(m.NativeWorkerError, "^cleanup_incomplete$"):
            await worker.close()
        self.assertEqual(worker.metrics()["sdk_start_active"], 1)
        self.assertIn("closed:runtime", self.trace)
        self.assertIn("closed:host", self.trace)
        self.assertNotIn("close:models", self.trace)
        self.holds["sdk:start"].set()
        with self.assertRaises(asyncio.CancelledError):
            await connecting
        await worker.close()
        self.assertEqual(worker.metrics()["ready"], 0)

    async def test_both_front_owners_receive_close_before_dependency_drain(self):
        worker = self.worker(cleanup_timeout_s=0.02)
        await worker.start_prepare()
        self.holds["close:runtime"] = asyncio.Event()
        with self.assertRaisesRegex(m.NativeWorkerError, "^cleanup_incomplete$"):
            await worker.close()
        self.assertIn("close:runtime", self.trace)
        self.assertIn("closed:host", self.trace)
        self.assertNotIn("close:wrapper", self.trace)
        self.holds["close:runtime"].set()
        await worker.close()
        self.assertEqual(self.trace.count("close:runtime"), 1)

    async def test_failed_dependency_close_is_finite_retained_and_retryable(self):
        worker = self.worker()
        await worker.start_prepare()
        self.fail.add("close:models")
        with self.assertRaisesRegex(m.NativeWorkerError, "^cleanup_incomplete$") as caught:
            await worker.close()
        self.assertNotIn(PRIVATE, str(caught.exception))
        self.assertEqual(worker.metrics()["owned_resources"], 1)
        self.assertIn("closed:intake", self.trace)
        self.assertIn("closed:context", self.trace)
        self.fail.clear()
        await worker.close()
        self.assertEqual(self.trace.count("close:models"), 2)

    async def test_partial_host_constructor_failure_drains_all_returned_dependencies(self):
        worker = self.worker()
        self.fail.add("construct:host")
        with self.assertRaisesRegex(m.NativeWorkerError, "^unavailable$"):
            await worker.start_prepare()
        await worker.close()
        self.assertEqual(worker.metrics()["owned_resources"], 0)
        self.assertIn("closed:runtime", self.trace)
        self.assertIn("closed:models", self.trace)
        self.assertNotIn("new:room", self.trace)

    async def test_cancelled_close_waiter_retains_same_actual_close(self):
        worker = self.worker()
        await worker.start_prepare()
        self.holds["close:runtime"] = asyncio.Event()
        closing = asyncio.create_task(worker.close())
        await self.until(lambda: "close:runtime" in self.trace)
        closing.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await closing
        self.holds["close:runtime"].set()
        await worker.close()
        self.assertEqual(self.trace.count("close:runtime"), 1)

    async def test_task_allocation_failure_keeps_admission_and_cleanup_retryable(self):
        worker = self.worker()
        with (
            patch.object(m.asyncio, "create_task", side_effect=RuntimeError(PRIVATE)),
            self.assertRaisesRegex(m.NativeWorkerError, "^unavailable$"),
        ):
            await worker.start_prepare()
        self.assertEqual(worker.metrics()["owned_resources"], 0)
        await worker.start_prepare()
        with (
            patch.object(m.asyncio, "create_task", side_effect=RuntimeError(PRIVATE)),
            self.assertRaisesRegex(m.NativeWorkerError, "^cleanup_incomplete$"),
        ):
            await worker.close()
        self.assertGreater(worker.metrics()["owned_resources"], 0)
        await worker.close()

    async def test_eager_loop_keeps_one_start_and_close_and_telemetry_cannot_block(self):
        def broken(stage):
            raise RuntimeError(PRIVATE)

        worker = self.worker(observer=broken)
        loop = asyncio.get_running_loop()
        previous = loop.get_task_factory()
        loop.set_task_factory(asyncio.eager_task_factory)
        try:
            await asyncio.gather(worker.start_prepare(), worker.start_prepare())
            await asyncio.gather(worker.close(), worker.close())
        finally:
            loop.set_task_factory(previous)
        self.assertEqual(self.trace.count("new:runtime"), 1)
        self.assertEqual(self.trace.count("close:runtime"), 1)
        self.assertGreater(worker.metrics()["telemetry_failed"], 0)

    async def test_invalid_configuration_and_budgets_are_finite_before_resources(self):
        for name in ("cleanup_timeout_s", "startup_timeout_s"):
            for value in (True, 0, 11, 10**1000, float("inf"), float("nan")):
                with (
                    self.subTest(name=name, value=str(value)[:20]),
                    self.assertRaisesRegex(m.NativeWorkerError, "^invalid_configuration$"),
                ):
                    m.NativeWorker(self.config, **{name: value})
        with self.assertRaisesRegex(m.NativeWorkerError, "^invalid_configuration$"):
            m.NativeWorker(object())
        self.assertEqual(self.trace, [])

    async def test_async_observer_is_rejected_before_resources(self):
        async def async_observer(stage):
            raise AssertionError("must never call")

        class AsyncObserver:
            async def __call__(self, stage):
                raise AssertionError("must never call")

        async def generator_observer(stage):
            yield stage

        class GeneratorObserver:
            async def __call__(self, stage):
                yield stage

        for observer in (async_observer, AsyncObserver(), generator_observer, GeneratorObserver()):
            with self.assertRaisesRegex(m.NativeWorkerError, "^invalid_configuration$"):
                m.NativeWorker(self.config, observer=observer)
        self.assertEqual(self.trace, [])


class GenuineComposition(unittest.IsolatedAsyncioTestCase):
    async def test_genuine_single_sdk_session_can_prepare_listener_and_close_without_rtc(self):
        from livekit.agents import AgentSession

        worker = m.NativeWorker(config())
        try:
            endpoint = await worker.start_prepare()
            self.assertEqual(endpoint.host, "127.0.0.1")
            self.assertIsInstance(worker._runtime.session, AgentSession)
            self.assertEqual(worker.metrics()["owned_resources"], 7)
            self.assertIsNone(worker._room)
            self.assertEqual(worker.metrics()["ready"], 0)
        finally:
            await worker.close()
        self.assertEqual(worker.metrics()["owned_resources"], 0)
        with socket.socket() as check:
            check.settimeout(0.2)
            self.assertNotEqual(check.connect_ex((endpoint.host, endpoint.port)), 0)

    def test_cold_worker_import_has_no_sdk_or_provider_loading(self):
        script = "import sys; import services.channel_policy_demo.native_worker; assert 'livekit.agents' not in sys.modules; assert 'livekit.rtc' not in sys.modules; assert 'openai' not in sys.modules; print('cold_ok')"
        done = subprocess.run(
            [sys.executable, "-c", script], check=False, capture_output=True, text=True, timeout=10
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "cold_ok")


class _CLIObservation:
    def __init__(self):
        self.session_closed = False
        self.session_close_reason = None
        self.sdk_closed = asyncio.Event()

    async def wait_session_closed(self):
        await self.sdk_closed.wait()


class WorkerCLI(unittest.IsolatedAsyncioTestCase):
    async def test_signal_end_reobserves_same_cleanup_and_removes_handlers(self):
        callbacks, removed, instances = {}, [], []
        loop = asyncio.get_running_loop()

        class Worker(_CLIObservation):
            def __init__(self, selected, *, observer):
                super().__init__()
                self.closed, self.closes = False, 0
                instances.append(self)

            async def start_prepare(self):
                return None

            async def connect_room(self):
                callbacks[signal.SIGTERM]()

            async def close(self):
                self.closes += 1
                if self.closes == 1:
                    raise m.NativeWorkerError("cleanup_incomplete")
                self.closed = True

            def metrics(self):
                return {"closed": int(self.closed)}

        with (
            patch.object(m, "NativeWorker", Worker),
            patch.object(
                loop,
                "add_signal_handler",
                side_effect=lambda name, callback: callbacks.__setitem__(name, callback),
            ),
            patch.object(
                loop, "remove_signal_handler", side_effect=lambda name: removed.append(name)
            ),
        ):
            self.assertEqual(await m._serve(config()), 0)
        self.assertEqual(instances[0].closes, 2)
        self.assertTrue(instances[0].closed)
        self.assertEqual(set(removed), {signal.SIGINT, signal.SIGTERM})

    async def test_partial_signal_install_failure_closes_worker_and_cancels_timer(self):
        installed, removed, instances, timers = [], [], [], []
        loop = asyncio.get_running_loop()
        schedule = loop.call_later

        class Worker(_CLIObservation):
            def __init__(self, selected, *, observer):
                super().__init__()
                self.closes = 0
                instances.append(self)

            async def close(self):
                self.closes += 1

        def install(name, callback):
            if name == signal.SIGTERM:
                raise RuntimeError(PRIVATE)
            installed.append(name)

        def later(*args, **kwargs):
            timer = schedule(*args, **kwargs)
            timers.append(timer)
            return timer

        output = io.StringIO()
        with (
            patch.object(m, "NativeWorker", Worker),
            patch.object(loop, "add_signal_handler", side_effect=install),
            patch.object(
                loop, "remove_signal_handler", side_effect=lambda name: removed.append(name)
            ),
            patch.object(loop, "call_later", side_effect=later),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(await m._serve(config()), 2)
        self.assertEqual(installed, [signal.SIGINT])
        self.assertEqual(removed, installed)
        self.assertEqual(instances[0].closes, 1)
        self.assertEqual(len(timers), 1)
        self.assertTrue(timers[0].cancelled())
        self.assertNotIn(PRIVATE, output.getvalue())

    async def test_persistent_cleanup_failure_has_three_observations_and_finite_failure(self):
        callbacks, instances = {}, []
        loop = asyncio.get_running_loop()

        class Worker(_CLIObservation):
            def __init__(self, selected, *, observer):
                super().__init__()
                self.closes = 0
                instances.append(self)

            async def start_prepare(self):
                raise RuntimeError(PRIVATE)

            async def connect_room(self):
                raise AssertionError("must not reach RTC")

            async def close(self):
                self.closes += 1
                raise m.NativeWorkerError("cleanup_incomplete")

            def metrics(self):
                return {"closed": 0}

        output = io.StringIO()
        with (
            patch.object(m, "NativeWorker", Worker),
            patch.object(
                loop,
                "add_signal_handler",
                side_effect=lambda name, callback: callbacks.__setitem__(name, callback),
            ),
            patch.object(loop, "remove_signal_handler", return_value=True),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(await m._serve(config()), 2)
        self.assertEqual(instances[0].closes, 3)
        self.assertNotIn(PRIVATE, output.getvalue())
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([event["code"] for event in events], ["unavailable", "cleanup_incomplete"])
        self.assertTrue(all(event["state"] == "failed" for event in events))

    async def test_sdk_close_and_signal_race_is_graceful_and_uses_one_worker(self):
        async def scenario(reason):
            callbacks, instances = {}, []
            loop = asyncio.get_running_loop()

            class Worker(_CLIObservation):
                def __init__(self, selected, *, observer):
                    super().__init__()
                    self.closes = 0
                    self.observer = observer
                    instances.append(self)

                async def start_prepare(self):
                    return None

                async def connect_room(self):
                    self.session_closed = True
                    self.session_close_reason = reason
                    self.sdk_closed.set()
                    self.observer("session_closed")
                    callbacks[signal.SIGTERM]()
                    raise m.NativeWorkerError("closed")

                async def close(self):
                    self.closes += 1

            output = io.StringIO()
            with (
                patch.object(m, "NativeWorker", Worker),
                patch.object(
                    loop,
                    "add_signal_handler",
                    side_effect=lambda name, callback: callbacks.__setitem__(name, callback),
                ),
                patch.object(loop, "remove_signal_handler", return_value=True),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(await m._serve(config()), 2 if reason in {None, "error"} else 0)
            self.assertEqual((len(instances), instances[0].closes), (1, 1))
            events = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(events[0]["state"], "session_closed")
            self.assertEqual(events[0]["reason"], reason)
            self.assertNotIn(PRIVATE, output.getvalue())

        for reason in (
            "participant_disconnected",
            "user_initiated",
            "task_completed",
            "error",
            None,
        ):
            with self.subTest(reason=reason):
                await scenario(reason)

    def test_plan_and_invalid_arguments_read_no_config_or_models(self):
        with patch.object(
            m, "load_native_worker_config", side_effect=AssertionError("no config read")
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(m.main(["--plan"]), 0)
            plan = json.loads(output.getvalue())
            self.assertEqual(plan["nativeSessions"], 1)
            self.assertEqual(plan["prepareDeadlineMs"], 4000)
            self.assertFalse(plan["providerKeys"])
            for args in ([], ["--provider-key", PRIVATE], ["--config"]):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(m.main(args), 2)
                event = json.loads(output.getvalue())
                self.assertEqual(event["code"], "invalid_configuration")
                self.assertNotIn(PRIVATE, output.getvalue())


if __name__ == "__main__":
    unittest.main()
