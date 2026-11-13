"""Explicit provider_real plumbing for the joined showcase; no provider call or real key."""

from __future__ import annotations

import asyncio
import dataclasses
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import services

ROOT = Path(services.__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_channel_policy_native_worker_config import fixture as worker_fixture
from test_channel_policy_owner_config import fixture as profile_fixture

from services.channel_policy_demo import native_worker_config as config_module
from services.channel_policy_demo import native_worker_process as process_module
from services.channel_policy_demo.native_models import NativeModelError
from services.channel_policy_demo.native_provider_models import (
    PROVIDER_ENVIRONMENT_KEYS,
    PROVIDER_INSTRUCTIONS,
    provider_environment,
    provider_timing,
)
from services.channel_policy_demo.native_room_state import NativeRoomError

KEYS = {
    name: name.lower().replace("_", "-") + "-synthetic-0123456789"
    for name in PROVIDER_ENVIRONMENT_KEYS
}
BASE = {"PATH": "/usr/bin:/bin", "LANG": "C"}
LAUNCH = ROOT / "local-setup/scripts/channel_policy_launch.py"
SPEC = importlib.util.spec_from_file_location("_provider_mode_launch", LAUNCH)
assert SPEC and SPEC.loader
launch = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = launch
SPEC.loader.exec_module(launch)


def frame(state: str, mode: str) -> bytes:
    value = {"schemaVersion": 1, "component": "channel_policy_native_worker", "mode": mode}
    return (json.dumps({**value, "state": state}, separators=(",", ":")) + "\n").encode()


class ProviderKeyTests(unittest.TestCase):
    def test_exactly_three_bounded_keys_are_copied_and_values_never_reflected(self):
        self.assertEqual(provider_environment(KEYS), KEYS)
        for values in (
            {k: v for k, v in KEYS.items() if k != "OPENAI_API_KEY"},
            {**KEYS, "PGPASSWORD": "x" * 32},
            {**KEYS, "OPENAI_API_KEY": "short"},
            {**KEYS, "OPENAI_API_KEY": "contains space " + "x" * 20},
            {**KEYS, "OPENAI_API_KEY": "PRIVATE_SENTINEL_" + "x" * 600},
        ):
            with self.subTest(keys=sorted(values)), self.assertRaises(NativeModelError) as caught:
                provider_environment(values)
            self.assertNotIn("PRIVATE_SENTINEL", str(caught.exception))
            self.assertEqual(str(caught.exception), "invalid_configuration")

    def test_provider_profile_is_explicit_about_budgets_and_authority(self):
        timing = provider_timing()
        self.assertEqual(
            (timing.reply, timing.commit_seconds, timing.transcript_seconds), ("scheduled", 11, 10)
        )
        self.assertIn("Never claim that a booking was changed", PROVIDER_INSTRUCTIONS)
        self.assertIn("No tools are available", PROVIDER_INSTRUCTIONS)


class WorkerConfigModeTests(unittest.TestCase):
    def test_scripted_records_remain_schema_one_and_provider_records_are_schema_two(self):
        scripted = worker_fixture()
        raw = config_module.encode_native_worker_config(scripted)
        self.assertEqual(json.loads(raw)["schemaVersion"], 1)
        self.assertNotIn("inferenceMode", json.loads(raw))
        self.assertEqual(config_module.parse_native_worker_config(raw).inference_mode, "scripted")
        provider = dataclasses.replace(scripted, inference_mode="provider_real")
        encoded = config_module.encode_native_worker_config(provider)
        value = json.loads(encoded)
        self.assertEqual((value["schemaVersion"], value["inferenceMode"]), (2, "provider_real"))
        self.assertEqual(config_module.parse_native_worker_config(encoded), provider)
        for name in PROVIDER_ENVIRONMENT_KEYS:
            self.assertNotIn(name.encode(), encoded)

    def test_mismatched_schema_and_mode_fail_closed(self):
        value = json.loads(config_module.encode_native_worker_config(worker_fixture()))
        for changed in (
            {**value, "schemaVersion": 2},
            {**value, "schemaVersion": 2, "inferenceMode": "scripted"},
            {**value, "inferenceMode": "provider_real"},
            {**value, "schemaVersion": 3, "inferenceMode": "provider_real"},
        ):
            with (
                self.subTest(changed=sorted(set(changed) - set(value))),
                self.assertRaises(config_module.NativeWorkerConfigError),
            ):
                config_module.parse_native_worker_config(json.dumps(changed).encode())
        with self.assertRaises(config_module.NativeWorkerConfigError):
            dataclasses.replace(worker_fixture(), inference_mode="local_real")


class WorkerProcessModeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        directory = Path(self.temporary.name).resolve()
        self.config = directory / "worker.json"
        self.config.write_bytes(b"{}")
        self.python = Path(sys.executable)

    async def test_keys_reach_only_the_spawned_worker_environment(self):
        owner = process_module.NativeWorkerProcess(
            self.python, self.config, BASE, provider_environment=KEYS
        )
        seen = []

        async def capture(*arguments, **keywords):
            seen.append(dict(keywords["env"]))
            raise OSError("no process in this unit test")

        with (
            patch.object(process_module.asyncio, "create_subprocess_exec", side_effect=capture),
            self.assertRaises(NativeRoomError),
        ):
            await owner.start()
        self.assertEqual(seen, [{**BASE, **KEYS}])
        scripted = process_module.NativeWorkerProcess(self.python, self.config, BASE)
        seen.clear()
        with (
            patch.object(process_module.asyncio, "create_subprocess_exec", side_effect=capture),
            self.assertRaises(NativeRoomError),
        ):
            await scripted.start()
        self.assertEqual(seen, [BASE])

    async def test_provider_keys_never_enter_through_the_closed_base_environment(self):
        with self.assertRaises(NativeRoomError):
            process_module.NativeWorkerProcess(self.python, self.config, {**BASE, **KEYS})
        with self.assertRaises(NativeRoomError):
            process_module.NativeWorkerProcess(
                self.python, self.config, BASE, provider_environment={"OPENAI_API_KEY": "x" * 32}
            )

    async def read(self, owner, frames: bytes):
        reader = asyncio.StreamReader()
        reader.feed_data(frames)
        reader.feed_eof()
        await owner._read_stdout(reader)
        return owner.status()

    async def test_lifecycle_frames_must_report_the_configured_mode(self):
        provider = process_module.NativeWorkerProcess(
            self.python, self.config, BASE, provider_environment=KEYS
        )
        status = await self.read(provider, frame("prepare_ready", "provider_real"))
        self.assertEqual((status.stage, status.protocol_failed), ("prepare_ready", False))
        scripted = process_module.NativeWorkerProcess(self.python, self.config, BASE)
        status = await self.read(scripted, frame("prepare_ready", "provider_real"))
        self.assertTrue(status.protocol_failed)
        mismatched = process_module.NativeWorkerProcess(
            self.python, self.config, BASE, provider_environment=KEYS
        )
        status = await self.read(mismatched, frame("prepare_ready", "scripted"))
        self.assertTrue(status.protocol_failed)


class ParentModeTests(unittest.TestCase):
    def settings(self, **changes):
        from services.channel_policy_demo.native_room_admin import LiveKitAdminSettings
        from services.channel_policy_demo.parent import ParentSettings

        values: dict[str, object] = {
            "profile": profile_fixture(),
            "admin": LiveKitAdminSettings("local_key", "synthetic_admin_secret_" + "x" * 43),
            "operator_bearer": "k" * 43,
            "owner_epoch": str(uuid4()),
            "room_directory": Path("/trusted/rooms"),
            "python_executable": Path("/trusted/.venv/bin/python"),
            "base_environment": BASE,
        }
        values.update(changes)
        return ParentSettings(**values)

    def test_keys_exist_exactly_for_the_explicit_provider_mode(self):
        from services.channel_policy_demo.parent import ParentError

        self.assertIsNone(self.settings().provider_environment)
        provider = self.settings(inference_mode="provider_real", provider_environment=KEYS)
        self.assertEqual(dict(provider.provider_environment), KEYS)
        self.assertNotIn("synthetic-0123456789", repr(provider))
        for changes in (
            {"inference_mode": "provider_real"},
            {"provider_environment": KEYS},
            {"inference_mode": "local_real", "provider_environment": KEYS},
            {"inference_mode": "provider_real", "provider_environment": {**KEYS, "X": "y" * 20}},
        ):
            with self.subTest(changes=sorted(changes)), self.assertRaises(ParentError):
                self.settings(**changes)


class LauncherModeTests(unittest.TestCase):
    def test_flags_are_explicit_unique_and_order_independent(self):
        requests = []

        def captured(request):
            # patch.object wraps the async serve in an AsyncMock that awaits this.
            requests.append(request)
            return 0

        with patch.object(launch, "serve", side_effect=captured):
            for flags in ([], ["--provider"], ["--no-ui", "--provider"], ["--provider", "--no-ui"]):
                with self.subTest(flags=flags):
                    self.assertEqual(
                        launch.main(
                            ["serve", "--profile", "/p/owner.json", "--node", "/n"] + flags
                        ),
                        0,
                    )
        self.assertEqual(
            [(r.inference_mode, r.no_ui) for r in requests],
            [
                ("scripted", False),
                ("provider_real", False),
                ("provider_real", True),
                ("provider_real", True),
            ],
        )
        for flags in (["--provider", "--provider"], ["--real"], ["--no-ui", "--no-ui"]):
            out = io.StringIO()
            with self.subTest(flags=flags), patch.object(launch.sys, "stdout", out):
                self.assertEqual(
                    launch.main(["serve", "--profile", "/p/owner.json", "--node", "/n"] + flags), 2
                )
            self.assertEqual(json.loads(out.getvalue())["code"], "invalid_arguments")

    def test_plan_discloses_the_optional_provider_profile_without_reading_keys(self):
        out = io.StringIO()
        with (
            patch.object(launch.sys, "stdout", out),
            patch.object(launch, "provider_credentials", side_effect=AssertionError("no key read")),
        ):
            self.assertEqual(launch.main(["--plan"]), 0)
        value = json.loads(out.getvalue())
        self.assertEqual((value["mode"], value["optionalModes"]), ("scripted", ["provider_real"]))
        self.assertFalse(value["providerFiles"] or value["providerCalls"])

    def test_provider_credentials_use_the_strict_owner_only_file(self):
        with tempfile.TemporaryDirectory() as raw:
            repository = Path(raw).resolve()
            setup = repository / "local-setup"
            setup.mkdir()
            shutil.copy(ROOT / "local-setup/provider_config.py", setup / "provider_config.py")
            path = setup / ".env.providers"
            path.write_text("".join(f"{k}={v}\n" for k, v in sorted(KEYS.items())))
            path.chmod(0o600)
            self.assertEqual(launch.provider_credentials(repository), KEYS)
            path.chmod(0o644)
            with self.assertRaises(Exception) as caught:
                launch.provider_credentials(repository)
            self.assertNotIn("synthetic-0123456789", str(caught.exception))


class RecognizerTurnTests(unittest.IsolatedAsyncioTestCase):
    async def test_flushed_transcript_binds_only_to_the_open_turn(self):
        from livekit import rtc
        from livekit.agents import stt
        from livekit.agents.language import LanguageCode

        from services.channel_policy_demo.native_provider_models import _recognizer_type

        class Upstream(stt.STT):
            def __init__(self):
                super().__init__(
                    capabilities=stt.STTCapabilities(streaming=False, interim_results=False)
                )
                self.calls = 0

            async def _recognize_impl(self, buffer, *, language=None, conn_options=None):
                self.calls += 1
                return stt.SpeechEvent(
                    type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                    alternatives=[
                        stt.SpeechData(language=LanguageCode("en"), text="move my booking")
                    ],
                )

        class Session:
            async def close(self):
                return None

        upstream = Upstream()
        recognizer = _recognizer_type()(upstream, Session())
        self.addAsyncCleanup(recognizer.aclose)
        voiced = rtc.AudioFrame(b"\x10\x27" * 1600, 16000, 1, 1600)
        stream = recognizer.stream()
        stream.push_frame(voiced)
        self.assertEqual(recognizer.dropped_frames, 1)
        turn = str(uuid4())
        recognizer.begin_turn(turn)
        for _ in range(4):
            stream.push_frame(voiced)
        stream.flush()
        events = []
        async with asyncio.timeout(5):
            async for event in stream:
                events.append(event.type)
                if event.type is stt.SpeechEventType.END_OF_SPEECH:
                    break
        snapshot = recognizer.final_snapshot(turn)
        self.assertEqual(snapshot.body, "move my booking")
        self.assertTrue(snapshot.request_id.startswith("provider-stt-"))
        self.assertIn(stt.SpeechEventType.FINAL_TRANSCRIPT, events)
        self.assertEqual((upstream.calls, recognizer.pending_work()), (1, 0))
        recognizer.end_turn(turn)
        with self.assertRaises(NativeModelError):
            recognizer.begin_turn(turn)
        await stream.aclose()


class ToollessLLMTests(unittest.IsolatedAsyncioTestCase):
    async def test_wire_omits_tool_settings_and_tool_lists_never_reach_the_wire(self):
        import httpx2
        from livekit.agents import llm

        from services.channel_policy_demo.native_provider_models import toolless_llm_factory
        from services.conversation_agent.inference_settings import LocalInferenceError
        from services.conversation_agent.provider_llm import create_provider_llm
        from services.conversation_agent.provider_settings import PROVIDER_LLM_MODEL

        bodies = []

        def wire(request):
            bodies.append(json.loads(request.content))
            chunk = {
                "id": "toolless-fixture",
                "model": PROVIDER_LLM_MODEL,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": "Synthetic reply."},
                        "finish_reason": None,
                    }
                ],
            }
            return httpx2.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode(),
            )

        model = await create_provider_llm(
            KEYS["OPENAI_API_KEY"],
            plugin_factory=toolless_llm_factory(),
            transport=httpx2.MockTransport(wire),
        )
        self.addAsyncCleanup(model.aclose)
        context = llm.ChatContext()
        context.add_message(role="system", content=PROVIDER_INSTRUCTIONS)
        context.add_message(role="user", content="Can I move my booking?")
        reply = []
        async with model.chat(chat_ctx=context, tool_choice="none") as stream:
            async for chunk in stream:
                if chunk.delta and chunk.delta.content:
                    reply.append(chunk.delta.content)
        self.assertEqual("".join(reply), "Synthetic reply.")
        self.assertEqual(len(bodies), 1)
        for field in ("tools", "tool_choice", "parallel_tool_calls"):
            self.assertNotIn(field, bodies[0])
        self.assertEqual(
            (bodies[0]["model"], bodies[0]["store"], bodies[0]["reasoning_effort"]),
            (PROVIDER_LLM_MODEL, False, "none"),
        )

        @llm.function_tool
        async def lookup() -> str:
            """Synthetic tool that must never be offered to this model."""
            return "never"

        with self.assertRaises(LocalInferenceError) as caught:
            async with model.chat(chat_ctx=context, tools=[lookup]) as stream:
                async for _ in stream:
                    pass
        self.assertEqual(caught.exception.code, "invalid_configuration")
        self.assertEqual(len(bodies), 1)


if __name__ == "__main__":
    unittest.main()
