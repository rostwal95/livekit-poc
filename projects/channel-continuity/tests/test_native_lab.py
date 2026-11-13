"""Application HTTP ownership under real sockets and held closing observers."""

import asyncio
import importlib.util
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness.process_control import FileBarrier

spec = importlib.util.spec_from_file_location(
    "p2_native_lab_test", Path(__file__).parents[1] / "examples" / "native_lab.py"
)
assert spec and spec.loader
lab = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = lab
spec.loader.exec_module(lab)


class NativeLabTests(unittest.IsolatedAsyncioTestCase):
    async def test_markers_publish_complete_private_pid_for_actual_file_barriers(self):
        with tempfile.TemporaryDirectory(prefix="native-marker-") as temporary:
            directory = Path(temporary).resolve()
            original_link = os.link
            for name in ("python_http_ready", "python_ready"):
                barrier = FileBarrier(directory, name)
                target = directory / (name + ".reached")
                observed = []

                def at_publication(
                    source,
                    destination,
                    *,
                    barrier=barrier,
                    target=target,
                    observed=observed,
                    **kwargs,
                ):
                    self.assertEqual(destination, target)
                    self.assertIsNone(barrier._read_pid(target))
                    self.assertEqual(barrier._read_pid(source), os.getpid())
                    self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o600)
                    observed.append(True)
                    return original_link(source, destination, **kwargs)

                old_umask = os.umask(0o022)
                try:
                    with patch.object(lab.os, "link", at_publication):
                        lab.reached(directory, name)
                finally:
                    os.umask(old_umask)
                self.assertEqual(observed, [True])
                self.assertEqual(barrier._read_pid(target), os.getpid())
                self.assertEqual(target.read_bytes(), f"{os.getpid()}\n".encode("ascii"))
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
                self.assertEqual(target.stat().st_nlink, 1)
                self.assertFalse(list(directory.glob("*.pending")))
                with self.assertRaises(FileExistsError):
                    lab.reached(directory, name)
                self.assertEqual(target.read_bytes(), f"{os.getpid()}\n".encode("ascii"))
                self.assertFalse(list(directory.glob("*.pending")))

    async def test_markers_reject_unknown_names_and_preserve_foreign_pending_and_symlink(self):
        with tempfile.TemporaryDirectory(prefix="native-marker-negative-") as temporary:
            directory = Path(temporary).resolve()
            with self.assertRaises(lab.NativeError):
                lab.reached(directory, "python-A-ready")
            self.assertFalse(list(directory.iterdir()))
            pending = directory / f"python_ready.{os.getpid()}.pending"
            pending.write_bytes(b"foreign pending")
            with self.assertRaises(FileExistsError):
                lab.reached(directory, "python_ready")
            self.assertEqual(pending.read_bytes(), b"foreign pending")
            pending.unlink()
            foreign = directory / "foreign"
            foreign.write_bytes(b"foreign target")
            target = directory / "python_ready.reached"
            target.symlink_to(foreign)
            with self.assertRaises(FileExistsError):
                lab.reached(directory, "python_ready")
            self.assertTrue(target.is_symlink())
            self.assertEqual(foreign.read_bytes(), b"foreign target")
            self.assertFalse(list(directory.glob("*.pending")))

    async def test_private_proof_save_is_exclusive_0600_and_rejects_symlink(self):
        with tempfile.TemporaryDirectory(prefix="native-proof-") as temporary:
            directory = Path(temporary)
            old = os.umask(0o022)
            try:
                lab.save(directory, "proof.json", {"schemaVersion": 1, "value": "café"})
            finally:
                os.umask(old)
            proof = directory / "proof.json"
            self.assertEqual(stat.S_IMODE(proof.stat().st_mode), 0o600)
            original = proof.read_bytes()
            with self.assertRaises(FileExistsError):
                lab.save(directory, "proof.json", {"schemaVersion": 1, "value": "replacement"})
            self.assertEqual(proof.read_bytes(), original)
            target = directory / "target.json"
            target.write_bytes(b"original target")
            (directory / "linked.json").symlink_to(target)
            with self.assertRaises(FileExistsError):
                lab.save(directory, "linked.json", {"schemaVersion": 1, "value": "must not follow"})
            self.assertTrue((directory / "linked.json").is_symlink())
            self.assertEqual(target.read_bytes(), b"original target")

    async def test_recording_port_retains_actual_sdk_payload_receipt_and_finite_cap(self):
        from channel_continuity.native_communication import (
            ObservationReceipt,
            ResponseAnchor,
            ResponseReceipt,
            SdkObservation,
        )
        from channel_continuity.native_models import NativeError

        rid = "11111111-1111-4111-8111-111111111111"
        generation = "22222222-2222-4222-8222-222222222222"
        anchor = ResponseAnchor(rid, generation, "speech", rid, rid, rid, rid, "1")
        known = ResponseReceipt(rid, generation, "a" * 64, "1", "2030-01-01T00:00:00.000Z")

        class Client:
            async def begin_response(self, value):
                return known

            async def observe_sdk(self, value):
                return ObservationReceipt(
                    value.response_id,
                    value.event_id,
                    value.event_id,
                    "b" * 64,
                    "1",
                    "2030-01-01T00:00:00.000Z",
                )

        recorder = lab.RecordedCommunication(Client())
        self.assertIs(await recorder.begin_response(anchor), known)
        for n in range(8):
            fact = SdkObservation(
                f"0000000{n}-1111-4111-8111-111111111111",
                rid,
                generation,
                "speech",
                "generated_complete",
                text="Actual stream café 🧭",
            )
            receipt = await recorder.observe_sdk(fact)
            self.assertEqual(recorder.proof()["sdkFacts"][n]["payload"], fact.payload())
            self.assertEqual(recorder.proof()["sdkFacts"][n]["receipt"], receipt.payload())
        self.assertEqual(len(recorder.proof()["anchors"]), 1)
        self.assertEqual(len(recorder.proof()["sdkFacts"]), 8)
        with self.assertRaises(NativeError):
            await recorder.observe_sdk(
                SdkObservation(
                    "99999999-1111-4111-8111-111111111111",
                    rid,
                    generation,
                    "speech",
                    "generated_complete",
                    text="overflow",
                )
            )
        self.assertEqual(len(recorder.proof()["sdkFacts"]), 8)

    async def test_rejected_closing_transport_is_synchronously_aborted_without_handler_task(self):
        async def handler(*args):
            self.fail("not_admitted")

        app = lab.LabHttp(handler)
        app.closing = True
        app.cleanup_seconds = 0.02
        entered = asyncio.Event()
        release = asyncio.Event()
        aborted = []

        class Transport:
            def abort(self):
                aborted.append(True)

        class Writer:
            transport = Transport()

        class Server:
            def close(self):
                pass

            async def wait_closed(self):
                entered.set()
                await release.wait()

        app.server = Server()
        app.connected(asyncio.StreamReader(), Writer())
        self.assertEqual(aborted, [True])
        self.assertFalse(app.tasks)
        self.assertFalse(app.writers)
        try:
            with self.assertRaises(TimeoutError):
                await app.close()
            self.assertTrue(entered.is_set())
            self.assertFalse(app._close_task.done())
        finally:
            release.set()
        await app.close()
        self.assertTrue(app._close_task.done())

    async def request(self, port, body=b"{}", extra=b""):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(
            b"POST /p2/session HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\n"
            + extra
            + b"\r\n"
            + body
        )
        await writer.drain()
        try:
            return await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_real_socket_duplicate_header_rejection_and_later_progress(self):
        calls = []

        async def handler(path, headers, body):
            calls.append(body)
            return 200, {"schemaVersion": 1, "status": "known"}

        app = lab.LabHttp(handler)
        port = await app.start()
        try:
            self.assertIn(b" 400 ", await self.request(port, extra=b"Content-Length: 2\r\n"))
            self.assertEqual(calls, [])
            self.assertIn(b" 200 ", await self.request(port))
            self.assertEqual(calls, [b"{}"])
        finally:
            await app.close()
        self.assertEqual(app.active, 0)
        self.assertFalse(app.tasks)
        self.assertFalse(app.writers)

    async def test_actual_http_operation_cap_timeout_retention_and_later_progress(self):
        arrived = asyncio.Queue()
        release = asyncio.Event()

        async def handler(*args):
            arrived.put_nowait(True)
            await release.wait()
            return 200, {"schemaVersion": 1}

        app = lab.LabHttp(handler)
        app.cleanup_seconds = 0.02
        port = await app.start()
        tasks = []
        try:
            for _ in range(4):
                tasks.append(asyncio.create_task(self.request(port)))
                await arrived.get()
            self.assertEqual(app.active, 4)
            self.assertIn(b" 503 ", await self.request(port))
            self.assertEqual(app.active, 4)
            release.set()
            await asyncio.gather(*tasks)
            self.assertIn(b" 200 ", await self.request(port))
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            await app.close()

    async def test_held_application_handler_cannot_produce_false_close_success(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def handler(*args):
            entered.set()
            await release.wait()
            return 200, {"schemaVersion": 1}

        app = lab.LabHttp(handler)
        app.cleanup_seconds = 0.02
        port = await app.start()
        request = asyncio.create_task(self.request(port))
        await entered.wait()
        try:
            with self.assertRaises(TimeoutError):
                await app.close()
            self.assertEqual(app.active, 1)
            self.assertEqual(len(app.tasks), 1)
        finally:
            release.set()
            await request
        await app.close()
        self.assertEqual(app.active, 0)
        self.assertFalse(app.tasks)

    def test_app_sdk_log_sanitizer_never_copies_payload_exception_or_identifier(self):
        import io
        import logging
        from unittest.mock import patch

        capture = io.StringIO()
        handler = lab.SafeConsoleHandler()
        record = logging.LogRecord(
            "untrusted_SECRET_SENTINEL",
            logging.ERROR,
            "private",
            1,
            "secret SECRET_SENTINEL",
            (),
            None,
        )
        record.exc_text = "SECRET_SENTINEL"
        record.native_event = "input"
        record.native_code = "rejected"
        with patch.object(sys, "stderr", capture):
            for _ in range(130):
                handler.emit(record)
        self.assertNotIn("SECRET_SENTINEL", capture.getvalue())
        self.assertEqual(len(capture.getvalue().splitlines()), 128)

    async def test_sixteen_admitted_sockets_reject_extra_without_task_growth_then_progress(self):
        async def handler(*_):
            return 200, {"schemaVersion": 1}

        app = lab.LabHttp(handler)
        port = await app.start()
        clients = []
        try:
            for _ in range(16):
                clients.append(await asyncio.open_connection("127.0.0.1", port))
            async with asyncio.timeout(1):
                while len(app.writers) != 16:
                    await asyncio.sleep(0)
            extra_reader, extra_writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                try:
                    self.assertEqual(await extra_reader.read(), b"")
                except ConnectionResetError:
                    pass
            finally:
                extra_writer.close()
                try:
                    await extra_writer.wait_closed()
                except ConnectionResetError:
                    pass
            self.assertEqual(len(app.writers), 16)
            self.assertEqual(len(app.tasks), 16)
            clients[0][1].close()
            await clients[0][1].wait_closed()
            async with asyncio.timeout(1):
                while len(app.writers) != 15:
                    await asyncio.sleep(0)
            self.assertIn(b" 200 ", await self.request(port))
        finally:
            for _, writer in clients:
                writer.close()
            await asyncio.gather(
                *(writer.wait_closed() for _, writer in clients), return_exceptions=True
            )
            await app.close()

    def test_failure_context_retains_only_closed_stage_code_and_own_basename(self):
        import json

        try:
            raise RuntimeError("SECRET_SENTINEL /private/sensitive")
        except RuntimeError as error:
            proof = lab.failure_context(error)
        self.assertNotIn("SECRET_SENTINEL", json.dumps(proof))
        self.assertNotIn("/private", json.dumps(proof))
        self.assertEqual(proof["errorType"], "RuntimeError")
        self.assertIn(proof["stage"], lab.STAGES)
        self.assertEqual(proof["frames"], [])

    async def test_expected_participant_precondition_ignores_other_authenticated_identity(self):
        from types import SimpleNamespace

        class Room:
            def __init__(self):
                self.remote_participants = {}
                self.listener = None
                self.registered = asyncio.Event()

            def on(self, name, callback):
                self.listener = callback
                self.registered.set()

            def off(self, name, callback):
                self.asserted = callback is self.listener
                self.listener = None

        room = Room()
        pending = asyncio.create_task(lab.wait_for_bound_participant(room, "browser", timeout=0.2))
        await room.registered.wait()
        room.listener(SimpleNamespace(identity="other"))
        self.assertFalse(pending.done())
        room.listener(SimpleNamespace(identity="browser"))
        self.assertIsInstance(await pending, float)
        self.assertIsNone(room.listener)
        self.assertTrue(room.asserted)

    async def test_expected_participant_registered_before_current_map_inspection(self):
        from types import SimpleNamespace

        class Room:
            def __init__(self):
                self.remote_participants = {}
                self.listener = None

            def on(self, name, callback):
                self.listener = callback
                self.remote_participants["browser"] = SimpleNamespace(identity="browser")

            def off(self, name, callback):
                self.listener = None

        room = Room()
        self.assertIsInstance(
            await lab.wait_for_bound_participant(room, "browser", timeout=0.1), float
        )
        self.assertIsNone(room.listener)

    async def test_expected_participant_precondition_timeout_removes_event_owner(self):
        class Room:
            def __init__(self):
                self.remote_participants = {}

            def on(self, name, callback):
                self.listener = callback

            def off(self, name, callback):
                self.listener = None

        room = Room()
        with self.assertRaises(TimeoutError):
            await lab.wait_for_bound_participant(room, "browser", timeout=0.02)
        self.assertIsNone(room.listener)

    async def test_expected_participant_precondition_cancellation_removes_event_owner(self):
        class Room:
            def __init__(self):
                self.remote_participants = {}
                self.registered = asyncio.Event()

            def on(self, name, callback):
                self.listener = callback
                self.registered.set()

            def off(self, name, callback):
                self.listener = None

        room = Room()
        pending = asyncio.create_task(lab.wait_for_bound_participant(room, "browser", timeout=0.2))
        await room.registered.wait()
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertIsNone(room.listener)


if __name__ == "__main__":
    unittest.main()
