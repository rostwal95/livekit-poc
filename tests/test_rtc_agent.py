"""Bounded transport diagnostics are tested without live media or inference."""

import asyncio
import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.rtc_agent.transport import (
    ECHO_PREFIX,
    MAX_REPLY_BYTES,
    MAX_TEXT_BYTES,
    BoundedTasks,
    TransportDiagnostics,
    read_text,
)


class Reader:
    def __init__(self, chunks):
        self.chunks, self.closed = iter(chunks), False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.chunks)
        except StopIteration:
            raise StopAsyncIteration

    def close(self):
        self.closed = True

    async def aclose(self):
        self.close()


class Participant:
    def __init__(self):
        self.messages = []

    async def send_text(self, text, **options):
        self.messages.append((text, options))


class Audio:
    def __init__(self, *_, **options):
        self.options, self.frames, self.closed = options, 0, False

    def __aiter__(self):
        return self

    async def __anext__(self):
        self.frames += 1
        if self.frames > 20:
            raise StopAsyncIteration
        return object()

    async def aclose(self):
        self.closed = True


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_is_bounded_in_utf8_and_reader_closed(self):
        reader = Reader(["hello", " world"])
        self.assertEqual(await read_text(reader), "hello world")
        self.assertTrue(reader.closed)
        oversized = Reader(["é" * 9])
        with self.assertRaises(ValueError):
            await read_text(oversized, maximum=16)
        self.assertTrue(oversized.closed)

    async def test_echo_routes_only_to_sender_and_does_not_claim_ai(self):
        participant = Participant()
        diagnostics = TransportDiagnostics(SimpleNamespace(local_participant=participant))
        reader = Reader(["test"])
        await diagnostics.echo(reader, "browser-fixture")
        self.assertEqual(
            participant.messages,
            [
                (
                    "Echo: test",
                    {"topic": "lk.agent.chat", "destination_identities": ["browser-fixture"]},
                )
            ],
        )

    async def test_exact_utf8_echo_boundaries_preserve_the_complete_request(self):
        fixture = json.loads(
            (
                Path(__file__).resolve().parents[1] / "contracts/local-transport/text-echo.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(MAX_TEXT_BYTES, fixture["max_request_bytes"])
        self.assertEqual(MAX_REPLY_BYTES, fixture["max_reply_bytes"])
        self.assertEqual(ECHO_PREFIX, fixture["prefix"])
        for case in fixture["boundary_cases"]:
            with self.subTest(case=case["name"]):
                text = case["unit"] * case["repeat"] + case["suffix"]
                participant = Participant()
                diagnostics = TransportDiagnostics(SimpleNamespace(local_participant=participant))
                midpoint = len(text) // 2
                reader = Reader([text[:midpoint], text[midpoint:]])
                if case["accepted"]:
                    self.assertEqual(len(text.encode("utf-8")), MAX_TEXT_BYTES)
                    await diagnostics.echo(reader, "browser-fixture")
                    self.assertEqual(len(participant.messages), 1)
                    reply, options = participant.messages[0]
                    self.assertEqual(reply, fixture["prefix"] + text)
                    self.assertEqual(len(reply.encode("utf-8")), MAX_REPLY_BYTES)
                    self.assertEqual(options["destination_identities"], ["browser-fixture"])
                else:
                    self.assertGreater(len(text.encode("utf-8")), MAX_TEXT_BYTES)
                    with self.assertRaises(ValueError):
                        await diagnostics.echo(reader, "browser-fixture")
                    self.assertEqual(participant.messages, [])
                self.assertTrue(reader.closed)

    async def test_task_admission_is_bounded_and_shutdown_cancels(self):
        tasks = BoundedTasks(maximum=1)
        barrier = asyncio.Event()
        admitted = tasks.spawn(barrier.wait)
        self.assertIsNotNone(admitted)
        self.assertIsNone(tasks.spawn(barrier.wait))
        await tasks.close()
        self.assertTrue(admitted.cancelled())
        await asyncio.sleep(0)
        self.assertEqual(len(tasks.tasks), 0)

    async def test_rejected_reader_is_closed_when_capacity_exhausted(self):
        diagnostics = TransportDiagnostics(SimpleNamespace(local_participant=Participant()))
        diagnostics.tasks = BoundedTasks(maximum=0)
        reader = Reader(["ignored"])
        diagnostics.on_text(reader, "browser-fixture")
        self.assertTrue(reader.closed)
        unauthorized = Reader(["ignored"])
        diagnostics.on_text(unauthorized, "untrusted")
        self.assertTrue(unauthorized.closed)

    async def test_audio_diagnostics_count_actual_frames_and_release_stream(self):
        participant = Participant()
        streams = []

        def factory(*args, **kwargs):
            stream = Audio(*args, **kwargs)
            streams.append(stream)
            return stream

        diagnostics = TransportDiagnostics(
            SimpleNamespace(local_participant=participant), audio_stream_factory=factory
        )
        await diagnostics.observe_audio(object(), "TR_fixture")
        messages = [json.loads(text) for text, options in participant.messages]
        fixture = json.loads(
            (
                Path(__file__).resolve().parents[1] / "contracts/local-transport/diagnostics.json"
            ).read_text()
        )
        self.assertEqual(messages, fixture["valid"])
        self.assertTrue(
            all(options["topic"] == "lk.agent.events" for _, options in participant.messages)
        )
        self.assertTrue(streams[0].closed)
        self.assertEqual(streams[0].options["capacity"], 32)


class WorkerSerializationTests(unittest.TestCase):
    def test_cli_launcher_callbacks_pickle_in_a_fresh_interpreter(self):
        # Reproduce the SDK boundary: callbacks serialized by the CLI process
        # must resolve in a child whose __main__ is unrelated to the worker.
        producer = """
import base64, pickle
from services.rtc_agent.worker import transport_session, accept_local_job, calculate_load
callbacks = (transport_session, accept_local_job, calculate_load)
assert all(callback.__module__ == 'services.rtc_agent.worker' for callback in callbacks)
print(base64.b64encode(pickle.dumps(callbacks)).decode('ascii'))
"""
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-c", producer],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        serialized = result.stdout.strip()
        consumer = """
import base64, pickle, sys
from types import SimpleNamespace
callbacks = pickle.loads(base64.b64decode(sys.argv[1]))
assert [callback.__name__ for callback in callbacks] == ['transport_session', 'accept_local_job', 'calculate_load']
assert all(callback.__module__ == 'services.rtc_agent.worker' for callback in callbacks)
assert callbacks[2](SimpleNamespace(active_jobs=[])) == 0.0
assert callbacks[2](SimpleNamespace(active_jobs=[object()])) == 1.0
print('worker_callbacks_deserialized')
"""
        result = subprocess.run(
            [sys.executable, "-c", consumer, serialized],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        self.assertEqual(result.stdout.strip(), "worker_callbacks_deserialized")


if __name__ == "__main__":
    unittest.main()
