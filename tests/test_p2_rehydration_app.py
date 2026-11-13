"""Application-only context handoff/ownership tests; no PostgreSQL or RTC connection."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from livekit.agents import llm

from channel_continuity.native import NativeError
from channel_continuity.native_rehydration import RehydrationContext, RehydrationQuery
from harness.process_control import FileBarrier, OwnedProcess

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "p2_rehydration_application_tests",
    ROOT / "projects/channel-continuity/examples/rehydration_lab.py",
)
assert SPEC and SPEC.loader
app = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = app
SPEC.loader.exec_module(app)


def configuration():
    fixture = {
        "schemaVersion": 1,
        "providerScope": {
            "tenantId": "tenant",
            "provider": "livekit",
            "providerAccountId": "local",
        },
        "scope": {"tenantId": "tenant", "accountId": "account"},
        "caseId": "case",
        "conversationId": "conversation",
        "accountToken": "a" * 43,
        "publisherToken": "p" * 43,
        "prepareToken": "q" * 43,
        "expiresAt": "2030-01-01T00:00:00.000Z",
        "bindings": {
            label: {
                "bindingId": str(uuid4()),
                "roomId": "room-" + label,
                "participantId": "browser-" + label,
                "agentId": "agent-" + label,
                "bindingToken": token * 43,
            }
            for label, token in (("A", "b"), ("B", "c"))
        },
        "ids": {key: str(uuid4()) for key in ("voice", "text", "sms", "newText")},
        "communication": {
            "publisherToken": "d" * 43,
            "sdkToken": "e" * 43,
            "browserToken": "f" * 43,
        },
        "sms": {},
        "referenceRequest": {},
    }
    media = {
        "schemaVersion": 1,
        "url": "ws://127.0.0.1:17880",
        "browserAccessToken": "z" * 43,
        "owner": "1" * 32,
        "bindings": {
            label: {"nativeToken": "native-jwt-" + label, "browserToken": "browser-jwt-" + label}
            for label in ("A", "B")
        },
    }
    return fixture, media, app.Configuration.parse(fixture, media)


def loaded(history=False):
    context_id, receipt = str(uuid4()), str(uuid4())
    value = {
        "contextId": context_id,
        "case": {"caseId": "case", "revision": "2", "sourceRevision": "a" * 64},
        "history": {
            "messages": [
                {"receipt": {"receiptId": receipt}, "event": {"body": "Original user — नमस्ते"}}
            ]
            if history
            else []
        },
    }
    # This observer consumes an already validated runtime value; it never creates authority.
    return RehydrationContext(json.dumps(value).encode()), value, receipt


class FakeSession:
    def __init__(self, config, shared, directory, stop):
        self.config, self.directory = config, directory
        self.ready, self.left = asyncio.Event(), asyncio.Event()
        self.closed, self.prepares, self.refreshes = False, 0, 0
        self.close_entered, self.close_release = asyncio.Event(), asyncio.Event()
        self.close_release.set()
        self.close_error = None

    async def start(self):
        self.ready.set()

    async def close(self):
        self.close_entered.set()
        await self.close_release.wait()
        self.closed = True
        if self.close_error:
            raise self.close_error

    async def prepare(self, context):
        self.prepares += 1
        return {"kind": "investigation", "source": "scripted", "caseRevision": "2"}

    async def refresh(self, query):
        self.refreshes += 1
        return loaded()[0]

    async def response(self, response_id):
        raise NativeError()

    def proof(self):
        return {
            "schemaVersion": 1,
            "label": self.config.label,
            "bindingId": self.config.binding.binding_id,
            "cleanupComplete": self.closed,
            "sdkClosed": self.closed,
            "roomClosed": self.closed,
        }


class ApplicationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="p2-rehydration-app-")
        self.directory = Path(self.temp.name)
        self.directory.chmod(0o700)
        self.fixture, self.media, self.config = configuration()
        self.application = None

    async def asyncTearDown(self):
        if self.application:
            self.application.stop.set()
            await self.application.http.close()
        self.temp.cleanup()

    def create(self):
        self.application = app.RehydrationApplication(
            self.directory, self.config, session_factory=FakeSession
        )
        return self.application

    def headers(self, prepare=False):
        return {
            "authorization": "Bearer "
            + (self.config.prepare if prepare else self.config.operator).value
        }

    def save(self, name, value):
        app._helpers().save(self.directory, name, value)

    def sms_result(self):
        return {
            "schemaVersion": 1,
            "status": "passed",
            "smsAccepted": 1,
            "caseRevision": "2",
            "receiptId": str(uuid4()),
            "operationKey": str(uuid4()),
            "eventId": self.config.sms_event_id,
        }

    async def settle(self):
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    async def test_configuration_copies_bindings_distinct_roles_and_explicit_owner(self):
        self.fixture["bindings"]["A"]["roomId"] = "changed"
        self.assertEqual(self.config.sessions["A"].binding.room_id, "room-A")
        with self.assertRaises(TypeError):
            self.config.sessions["A"] = self.config.sessions["B"]
        for key, value in (
            ("owner", "1" * 32 + "\n"),
            ("url", "ws://localhost:17880"),
            ("browserAccessToken", self.fixture["prepareToken"]),
        ):
            f, m, _ = configuration()
            m[key] = value
            with self.subTest(key=key), self.assertRaises(NativeError):
                app.Configuration.parse(f, m)
        f, m, _ = configuration()
        f["bindings"]["B"]["bindingId"] = f["bindings"]["A"]["bindingId"]
        with self.assertRaises(NativeError):
            app.Configuration.parse(f, m)

    async def test_private_files_and_markers_reject_links_public_modes_and_replacement(self):
        self.save("proof.json", {"safe": True})
        path = self.directory / "proof.json"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(json.loads(app.private_read(path, 128)), {"safe": True})
        with self.assertRaises(NativeError):
            app.private_read(path, 1)
        path.chmod(0o644)
        with self.assertRaises(NativeError):
            app.private_read(path, 128)
        (self.directory / "linked").symlink_to(path)
        with self.assertRaises(NativeError):
            app.private_read(self.directory / "linked", 128)
        app.marker(self.directory, "sms_requested")
        marker = self.directory / "sms_requested.reached"
        self.assertEqual(marker.read_bytes(), f"{os.getpid()}\n".encode())
        self.assertEqual(stat.S_IMODE(marker.stat().st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            app.marker(self.directory, "sms_requested")
        with self.assertRaises(NativeError):
            app.marker(self.directory, "../untrusted")
        self.assertFalse(list(self.directory.glob("*.pending")))

    def test_actual_file_barriers_accept_all_producer_stems_and_original_pid(self):
        directory = self.directory.resolve()
        names = (
            "python_http_ready",
            "python_a_ready",
            "python_a_closed",
            "python_b_ready",
            "sms_requested",
        )
        barriers = [FileBarrier(directory, name) for name in names]
        program = r"""
import importlib.util, os, sys, time
from pathlib import Path
spec = importlib.util.spec_from_file_location('marker_interop', sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
directory = Path(sys.argv[2])
for name in sys.argv[3:]:
    module.marker(directory, name)
    deadline = time.monotonic() + 10
    released = directory / (name + '.released')
    while not released.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError()
        time.sleep(0.005)
    assert released.read_bytes() == (str(os.getpid()) + '\n').encode()
"""
        with OwnedProcess(
            [
                sys.executable,
                "-I",
                "-c",
                program,
                str(ROOT / "projects/channel-continuity/examples/rehydration_lab.py"),
                str(directory),
                *names,
            ],
            cwd=directory,
            env={},
            output_directory=directory / "marker-child",
            max_output_bytes=4096,
        ) as child:
            for barrier in barriers:
                child.wait_for_barrier(barrier, timeout=10)
                self.assertEqual(
                    (directory / (barrier.name + ".reached")).read_bytes(),
                    f"{child.pid}\n".encode(),
                )
                self.assertEqual(
                    stat.S_IMODE((directory / (barrier.name + ".reached")).stat().st_mode), 0o600
                )
                child.release_barrier(barrier)
            self.assertEqual(child.wait(timeout=10).returncode, 0)
            self.assertFalse(child.cleanup_failed)

    async def test_mint_replay_returns_same_seven_fields_without_duplicate_start(self):
        a = self.create()
        _, first = await a.handle("/p2/session", self.headers(), b"{}")
        _, second = await a.handle("/p2/session", self.headers(), b"{}")
        self.assertEqual(first, second)
        self.assertEqual(
            set(first),
            {"schemaVersion", "url", "token", "roomId", "participantId", "agentId", "bindingId"},
        )
        self.assertEqual(set(a.sessions), {"A"})
        self.assertEqual(len(a.launching), 1)
        denied, body = await a.handle("/p2/session", self.headers(prepare=True), b"{}")
        self.assertEqual(denied, 401)
        self.assertNotIn("token", body)
        for raw in (b"{ }", b'{"schemaVersion":1}', b'{"x":1,"x":2}'):
            with self.subTest(raw=raw), self.assertRaises(NativeError):
                await a.handle("/p2/session", self.headers(), raw)
        await self.settle()

    async def test_sms_caller_abort_keeps_one_actual_owner_and_requires_b_ready(self):
        a = self.create()
        a._launch("A")
        await self.settle()
        old = a.sessions["A"]
        old.left.set()
        old.close_release.clear()
        first = asyncio.create_task(a.handle("/p2/sms", self.headers(), b'{"schemaVersion":1}'))
        await old.close_entered.wait()
        self.assertFalse((self.directory / "sms_requested.reached").exists())
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertFalse(a.retired.done())
        old.close_release.set()
        await a.retired
        self.assertTrue(old.closed)
        self.assertTrue((self.directory / "python_a_closed.reached").exists())
        waiter = asyncio.create_task(a.handle("/p2/sms", self.headers(), b'{"schemaVersion":1}'))
        await self.settle()
        self.assertEqual(a.sms.requests, 1)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        result = self.sms_result()
        self.save("rehydration-sms-result.json", result)
        await asyncio.sleep(0.025)
        self.assertIsNone(a.sms.known)
        self.assertFalse(a.sms.task.done())
        with self.assertRaises(NativeError):
            await a.handle("/p2/session", self.headers(), b"{}")
        self.save(
            "room_b_ready.json",
            {
                "schemaVersion": 1,
                "roomId": self.config.sessions["B"].binding.room_id,
                "owner": self.config.owner,
            },
        )
        _, original = await a.handle("/p2/sms", self.headers(), b'{"schemaVersion":1}')
        _, replay = await a.handle("/p2/sms", self.headers(), b'{"schemaVersion":1}')
        self.assertEqual(original, replay)
        self.assertEqual(a.sms.requests, 1)
        _, new = await a.handle("/p2/session", self.headers(), b"{}")
        _, new_replay = await a.handle("/p2/session", self.headers(), b"{}")
        self.assertEqual(new, new_replay)
        self.assertEqual(new["bindingId"], self.config.sessions["B"].binding.binding_id)
        await self.settle()

    async def test_sms_result_identity_and_ready_owner_are_closed_not_repaired(self):
        for change in (
            {"eventId": str(uuid4())},
            {"smsAccepted": True},
            {"caseRevision": "1"},
            {"extra": "private"},
        ):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                handshake = app.SmsHandshake(
                    directory,
                    self.config.sms_event_id,
                    asyncio.Event(),
                    room_id="room-B",
                    owner=self.config.owner,
                )
                value = self.sms_result() | change
                app._helpers().save(directory, "rehydration-sms-result.json", value)
                app._helpers().save(
                    directory,
                    "room_b_ready.json",
                    {"schemaVersion": 1, "roomId": "room-B", "owner": self.config.owner},
                )
                with self.assertRaises(NativeError):
                    await handshake.request()
                self.assertIsNone(handshake.known)
                with self.assertRaises(NativeError):
                    await handshake.request()
                self.assertEqual(handshake.requests, 1)
        self.save("rehydration-sms-result.json", self.sms_result())
        self.save("room_b_ready.json", {"schemaVersion": 1, "roomId": "room-B", "owner": "2" * 32})
        handshake = app.SmsHandshake(
            self.directory,
            self.config.sms_event_id,
            asyncio.Event(),
            room_id="room-B",
            owner=self.config.owner,
        )
        with self.assertRaises(NativeError):
            await handshake.request()
        self.assertIsNone(handshake.known)

    async def test_read_refresh_does_not_prepare_and_old_room_cannot_prepare_new_room(self):
        a = self.create()
        a._launch("B")
        a.selected = "B"
        await self.settle()
        body = {"schemaVersion": 1, "query": RehydrationQuery().payload()}
        status, reply = await a.handle("/p2/context", self.headers(), json.dumps(body).encode())
        self.assertEqual((status, reply["status"]), (200, "known"))
        self.assertEqual((a.sessions["B"].refreshes, a.sessions["B"].prepares), (1, 0))
        context = {
            "schemaVersion": 1,
            "kind": "agent-protocol.request",
            "operationKey": str(uuid4()),
            "scope": {"tenantId": "tenant", "accountId": "account"},
            "caseId": "case",
            "caseRevision": "2",
            "conversationId": "conversation",
            "message": {
                "receiptId": str(uuid4()),
                "eventId": str(uuid4()),
                "messageId": str(uuid4()),
                "senderId": self.config.sessions["A"].binding.binding_id,
                "body": "original",
            },
        }
        raw = json.dumps({"schemaVersion": 1, "kind": "agent.prepare", "context": context}).encode()
        with self.assertRaises(NativeError):
            await a.handle("/v1/native/prepare", self.headers(prepare=True), raw)
        self.assertEqual(a.sessions["B"].prepares, 0)
        context["message"]["senderId"] = self.config.sessions["B"].binding.binding_id
        raw = json.dumps({"schemaVersion": 1, "kind": "agent.prepare", "context": context}).encode()
        status, reply = await a.handle("/v1/native/prepare", self.headers(prepare=True), raw)
        self.assertEqual(status, 200)
        import hashlib

        self.assertEqual(reply["inputDigest"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(a.sessions["B"].prepares, 1)

    async def test_real_loopback_new_route_large_reply_and_old_helper_default_routes(self):
        a = self.create()
        a._launch("A")
        await self.settle()
        port = await a.http.start()

        async def request(target, body, token):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(
                f"POST {target} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Type: application/json\r\nAuthorization: Bearer {token}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                + body
            )
            await writer.drain()
            data = await reader.read()
            writer.close()
            await writer.wait_closed()
            return data

        response = await request(
            "/p2/context",
            json.dumps({"schemaVersion": 1, "query": RehydrationQuery().payload()}).encode(),
            self.config.operator.value,
        )
        self.assertTrue(response.startswith(b"HTTP/1.1 200"))
        self.assertIn(b"Connection: close", response)
        self.assertEqual(a.sessions["A"].prepares, 0)
        self.assertEqual(
            app._helpers().LabHttp.ALLOWED_PATHS,
            frozenset(("/p2/session", "/v1/native/prepare", "/p2/response")),
        )
        self.assertEqual(app._helpers().LabHttp.LARGE_RESPONSE_PATHS, frozenset(("/p2/response",)))
        await a.http.close()
        self.assertFalse(a.http.tasks or a.http.writers or a.http.active)
        with self.assertRaises(OSError):
            await asyncio.open_connection("127.0.0.1", port)

    async def test_run_preserves_primary_cancellation_and_closes_each_owner(self):
        a = self.create()
        running = asyncio.create_task(a.run())
        async with asyncio.timeout(1):
            while "A" not in a.sessions:
                await asyncio.sleep(0)
        a._launch("B")
        await self.settle()
        a.sessions["A"].close_error = RuntimeError("secondary")
        a.failure.set_result(asyncio.CancelledError("primary"))
        with self.assertRaises(asyncio.CancelledError):
            await running
        self.assertTrue(a.sessions["A"].closed)
        self.assertTrue(a.sessions["B"].closed)
        self.assertTrue(a.http.closing)
        self.assertFalse(a.http.tasks or a.http.writers)
        diagnostic = json.loads((self.directory / "rehydration-python-failure.json").read_bytes())
        self.assertEqual(diagnostic["errorType"], "CancelledError")
        self.assertTrue(diagnostic["cleanupComplete"])
        self.assertEqual(
            set(diagnostic),
            {"schemaVersion", "status", "mode", "stage", "errorType", "code", "cleanupComplete"},
        )
        self.assertNotIn("primary", json.dumps(diagnostic))
        self.assertNotIn("secondary", json.dumps(diagnostic))

    async def test_actual_startup_owner_is_retained_until_ignored_cancellation_finishes(self):
        class Room:
            def on(self, *args):
                pass

            def off(self, *args):
                pass

            def isconnected(self):
                return False

            async def disconnect(self):
                closed.append("room")

        closed, entered, release = [], asyncio.Event(), asyncio.Event()
        with patch.object(app.rtc, "Room", Room):
            session = app.NativeSession(
                self.config.sessions["A"], self.config, self.directory, asyncio.Event()
            )

        class LateOwner:
            sdk_closed = True

            async def aclose(self):
                closed.append("late-runtime")

        async def starting():
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            session.runtime = LateOwner()

        session._starting = asyncio.create_task(starting())
        await entered.wait()
        observer = asyncio.create_task(session.close())
        await self.settle()
        observer.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await observer
        self.assertFalse(session._closing.done())
        self.assertFalse(closed)
        release.set()
        await session.close()
        self.assertEqual(closed, ["late-runtime", "room"])
        self.assertTrue(session.closed)

    async def test_public_model_entry_proves_exact_system_history_without_retaining_bodies(self):
        observed, payload, receipt = loaded(history=True)
        scripted = app._helpers()._scripted()
        delegate = scripted.ScriptedModel()
        model = app.ContextModel(delegate, lambda: observed)
        chat = llm.ChatContext()
        chat.add_message(
            role="system",
            content="Verified CURRENT_CASE=" + json.dumps(payload["case"]),
            id="p2.context.case." + observed.context_id,
        )
        chat.add_message(
            role="user",
            content=payload["history"]["messages"][0]["event"]["body"],
            id="p2.history." + receipt,
        )
        stream = model.chat(chat_ctx=chat)
        chunks = [chunk async for chunk in stream]
        await stream.aclose()
        self.assertEqual(delegate.calls, 1)
        self.assertTrue(chunks)
        self.assertEqual(model.observations[0]["historyReceiptIds"], [receipt])
        raw = json.dumps(model.observations)
        self.assertNotIn("Original user", raw)
        self.assertNotIn("CURRENT_CASE", raw)
        await model.aclose()

    async def test_model_rejects_inert_body_spoof_wrong_role_duplicate_context_and_wrong_history(
        self,
    ):
        observed, payload, receipt = loaded(history=True)
        scripted = app._helpers()._scripted()
        for mode in (
            "wrong_role",
            "duplicate",
            "wrong_history",
            "inert_spoof",
            "stale_system",
            "duplicate_history",
        ):
            delegate = scripted.ScriptedModel()
            model = app.ContextModel(delegate, lambda: observed)
            chat = llm.ChatContext()
            case = "Verified CURRENT_CASE=" + json.dumps(payload["case"])
            if mode != "inert_spoof":
                chat.add_message(
                    role="user" if mode == "wrong_role" else "system",
                    content=case,
                    id="p2.context.case." + observed.context_id,
                )
            if mode == "duplicate":
                chat.add_message(
                    role="system", content=case, id="p2.context.case." + observed.context_id
                )
            chat.add_message(
                role="user",
                content=case
                if mode == "inert_spoof"
                else "changed"
                if mode == "wrong_history"
                else payload["history"]["messages"][0]["event"]["body"],
                id="p2.history." + receipt,
            )
            if mode == "stale_system":
                chat.add_message(role="system", content=case, id="p2.context.case." + str(uuid4()))
            if mode == "duplicate_history":
                chat.add_message(
                    role="user",
                    content=payload["history"]["messages"][0]["event"]["body"],
                    id="p2.history." + receipt,
                )
            with self.subTest(mode=mode), self.assertRaises(NativeError):
                model.chat(chat_ctx=chat)
            self.assertFalse(model.observations)
            self.assertEqual(delegate.calls, 0)
            await model.aclose()

    async def test_complete_application_handoff_saves_only_after_both_actual_fake_owners_close(
        self,
    ):
        a = self.create()
        running = asyncio.create_task(a.run())
        try:
            async with asyncio.timeout(1):
                while "A" not in a.sessions or not a.sessions["A"].ready.is_set():
                    await asyncio.sleep(0)
            a.sessions["A"].left.set()
            self.save("rehydration-sms-result.json", self.sms_result())
            self.save(
                "room_b_ready.json",
                {"schemaVersion": 1, "roomId": "room-B", "owner": self.config.owner},
            )
            await a.handle("/p2/sms", self.headers(), b'{"schemaVersion":1}')
            await a.handle("/p2/session", self.headers(), b"{}")
            await self.settle()
            a.stop.set()
            result = await running
            self.assertEqual(result["smsRequests"], 1)
            self.assertTrue(result["httpClosed"] and result["cleanupComplete"])
            self.assertTrue(all(session.closed for session in a.sessions.values()))
            self.assertEqual(
                json.loads((self.directory / "python-terminal.json").read_bytes()), result
            )
            self.assertEqual(
                json.loads((self.directory / "rehydration-python-session-A.json").read_bytes())[
                    "cleanupComplete"
                ],
                True,
            )
            self.assertEqual(
                stat.S_IMODE((self.directory / "python-terminal.json").stat().st_mode), 0o600
            )
            with self.assertRaises(NativeError):
                await a.handle("/p2/session", self.headers(), b"{}")
        finally:
            if not running.done():
                a.stop.set()
                await asyncio.gather(running, return_exceptions=True)

    async def test_private_reader_rechecks_actual_opened_mode_not_only_path_snapshot(self):
        self.save("proof.json", {"safe": True})
        path = self.directory / "proof.json"
        original_open = os.open

        def changed(*args, **kwargs):
            path.chmod(0o644)
            return original_open(*args, **kwargs)

        with patch.object(app.os, "open", side_effect=changed), self.assertRaises(NativeError):
            app.private_read(path, 128)

    async def test_failure_diagnostic_write_error_preserves_original_and_closes_http(self):
        a = self.create()
        original_save = app._helpers().save

        def denied(directory, name, value):
            if name == "rehydration-python-failure.json":
                raise OSError("private write failure")
            original_save(directory, name, value)

        with patch.object(app._helpers(), "save", side_effect=denied):
            running = asyncio.create_task(a.run())
            async with asyncio.timeout(1):
                while "A" not in a.sessions:
                    await asyncio.sleep(0)
            a.failure.set_result(NativeError("dependency_unavailable"))
            with self.assertRaises(NativeError) as failed:
                await running
            self.assertEqual(failed.exception.code, "dependency_unavailable")
        self.assertTrue(a.sessions["A"].closed and a.http_closed)
        self.assertFalse((self.directory / "rehydration-python-failure.json").exists())
