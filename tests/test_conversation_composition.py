"""Session identity, bounded native I/O and numeric SDK report consumers."""

import asyncio
import json
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from livekit.agents.metrics.usage import (
    AgentSessionUsage,
    LLMModelUsage,
    STTModelUsage,
    TTSModelUsage,
)
from livekit.agents.voice.events import SessionUsageUpdatedEvent

from continuity_lab.authorization import AuthenticatedActor, AuthenticationFailed, BearerToken
from continuity_lab.conversation_service import AsyncConversationService
from continuity_lab.models import BookingChange
from continuity_lab.postgres_api import ManagedCaseClient
from continuity_lab.session_grants import sign_grant, verify_grant
from continuity_lab.tracing import TraceRuntime, TraceSettings
from services.conversation_agent.composition import SessionBusinessPort, create_port
from services.conversation_agent.observations import SessionObserver, finite

TASK = "11111111-1111-4111-8111-111111111111"
SECRET = "s" * 40
TOKEN = BearerToken("t" * 40)
ACTOR = AuthenticatedActor("local-operator", "demo-traveller")
REQUEST = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)


def grant(task=None):
    raw = sign_grant(
        secret=SECRET,
        actor=ACTOR,
        room="business-test",
        participant="browser-test",
        request=REQUEST,
        request_key="original-key",
        task_id=task,
    )
    return raw, verify_grant(
        raw,
        secret=SECRET,
        room="business-test",
        expected_scope=ACTOR.scope_id,
        expected_actor=ACTOR.actor_id,
    )


def projection():
    return {
        "task_id": TASK,
        "case_revision": "9223372036854775807",
        "inquiry": {"state": "SUCCEEDED"},
        "lifecycle": {"state": "INQUIRY_COMPLETE"},
        "quote": None,
        "outcome": None,
    }


class CompositionTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_argument_tools_replay_original_request_and_do_not_offer_confirmation(self):
        service = Mock()
        service.submit.return_value = SimpleNamespace(
            projection=SimpleNamespace(payload=projection)
        )
        service.get.return_value = SimpleNamespace(payload=projection)
        service.cancel.return_value = SimpleNamespace(disposition=SimpleNamespace(value="stopped"))
        boundary = AsyncConversationService(service)
        _, binding = grant()
        port = SessionBusinessPort(ManagedCaseClient(boundary, TOKEN), binding)
        self.assertEqual((await port.get_case())["status"], "not_accepted")
        a = await port.submit_investigation()
        b = await port.submit_investigation()
        self.assertEqual(a, b)
        self.assertEqual(a["task_id"], TASK)
        self.assertEqual(a["case_revision"], "9223372036854775807")
        for call in service.submit.call_args_list:
            self.assertEqual(
                call.kwargs, {"token": TOKEN, "idempotency_key": "original-key", "request": REQUEST}
            )
        self.assertEqual((await port.get_case())["task_id"], TASK)
        await port.cancel_case()
        await port.cancel_case()
        self.assertEqual(service.cancel.call_args_list[0], service.cancel.call_args_list[1])
        self.assertNotIn("confirmation_payload", a)
        self.assertFalse(hasattr(port, "signal"))
        await port.aclose()
        with self.assertRaises(RuntimeError):
            await port.submit_investigation()
        self.assertEqual(boundary.pending_count, 0)

    async def test_lost_submit_acknowledgement_replays_frozen_request_before_get_or_cancel(self):
        frozen = {"token": TOKEN, "idempotency_key": "original-key", "request": REQUEST}
        for operation in ("get_case", "cancel_case"):
            with self.subTest(operation=operation):
                release = threading.Event()
                service = Mock()

                def held_submit(release=release, **_kwargs):
                    release.wait(5)
                    return SimpleNamespace(projection=SimpleNamespace(payload=projection))

                service.submit.side_effect = held_submit
                service.get.return_value = SimpleNamespace(payload=projection)
                service.cancel.return_value = SimpleNamespace(
                    disposition=SimpleNamespace(value="stopped")
                )
                boundary = AsyncConversationService(service)
                _, binding = grant()
                port = SessionBusinessPort(ManagedCaseClient(boundary, TOKEN), binding)
                command = getattr(port, operation)
                try:
                    self.assertEqual(
                        await command(), {"schema_version": 1, "status": "not_accepted"}
                    )
                    service.submit.assert_not_called()
                    with patch(
                        "services.conversation_agent.composition.OPERATION_TIMEOUT_SECONDS", 0.1
                    ):
                        with self.assertRaises(TimeoutError):
                            await port.submit_investigation()
                        # Still held: an unresolved submit is never reported as not accepted.
                        with self.assertRaises(TimeoutError):
                            await command()
                    release.set()
                    async with asyncio.timeout(5):
                        while boundary.pending_count:
                            await asyncio.sleep(0.01)
                    result = await command()
                    self.assertEqual(result["task_id"], TASK)
                    if operation == "get_case":
                        self.assertEqual(result["inquiry_state"], "SUCCEEDED")
                        self.assertEqual(service.get.call_args.kwargs["task_id"], TASK)
                        service.cancel.assert_not_called()
                    else:
                        self.assertEqual(result["disposition"], "stopped")
                        service.cancel.assert_called_once()
                        self.assertEqual(service.cancel.call_args.kwargs["task_id"], TASK)
                    self.assertEqual((await port.get_case())["task_id"], TASK)
                    self.assertEqual(
                        [call.kwargs for call in service.submit.call_args_list], [frozen] * 3
                    )
                finally:
                    release.set()
                    await port.aclose()
                self.assertEqual(boundary.pending_count, 0)

    async def test_invalid_signed_binding_never_constructs_a_business_service(self):
        with (
            patch.dict("os.environ", {"LIVEKIT_API_SECRET": SECRET}),
            patch("services.conversation_agent.composition.open_postgres_client") as build,
        ):
            with self.assertRaises(AuthenticationFailed):
                await create_port("not-a-grant", "business-test")
            build.assert_not_called()

    async def test_create_port_uses_server_bound_principal_and_frozen_request(self):
        raw, _ = grant(TASK)
        with (
            patch.dict(
                "os.environ", {"LIVEKIT_API_SECRET": SECRET, "P1_POSTGRES_PASSWORD": "private"}
            ),
            patch(
                "services.conversation_agent.composition.open_postgres_client",
                return_value=Mock(close=AsyncMock()),
            ) as build,
        ):
            port, binding = await create_port(raw, "business-test")
            self.assertEqual(binding.expected_participant, "browser-test")
            self.assertEqual(build.call_args.kwargs["actor"], ACTOR)
            self.assertNotEqual(build.call_args.kwargs["token"], TOKEN)
            await port.aclose()

    async def test_sdk_report_and_usage_export_only_finite_counts_with_private_bounded_retention(
        self,
    ):
        session = Mock()
        usage = AgentSessionUsage(
            [
                LLMModelUsage(
                    provider="SECRET_SENTINEL",
                    model="SECRET_SENTINEL",
                    input_tokens=3,
                    output_tokens=2,
                ),
                STTModelUsage(
                    provider="SECRET_SENTINEL", model="SECRET_SENTINEL", audio_duration=0.2
                ),
                TTSModelUsage(
                    provider="SECRET_SENTINEL",
                    model="SECRET_SENTINEL",
                    characters_count=7,
                    audio_duration=0.5,
                ),
            ]
        )
        session.usage = usage
        report = SimpleNamespace(
            events=[object(), object()], duration=0.8, chat_history="SECRET_SENTINEL"
        )
        ctx = Mock()
        ctx.make_session_report.return_value = report
        with (
            tempfile.TemporaryDirectory() as parent,
            patch(
                "services.conversation_agent.observations.DIRECTORY", Path(parent) / "observations"
            ),
            patch("services.conversation_agent.observations.set_tracer_provider"),
        ):
            observer = SessionObserver(session, TraceRuntime(TraceSettings("conversation-agent")))
            observer._usage(SessionUsageUpdatedEvent(usage=usage))
            await observer.aclose(session, ctx)
            await observer.aclose(session, ctx)
            files = list((Path(parent) / "observations").glob("*.json"))
            self.assertEqual(len(files), 1)
            text = files[0].read_text()
            self.assertNotIn("SECRET_SENTINEL", text)
            data = json.loads(text)
            self.assertTrue(data["sdk_report_observed"])
            self.assertEqual(data["values"]["llm_input_tokens"], 3)
            self.assertEqual(data["values"]["report_events"], 2)
            self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
            ctx.make_session_report.assert_called_once_with(session)

    async def test_numeric_report_labels_real_profile_without_serializing_model_content(self):
        session = Mock()
        session.usage = AgentSessionUsage([])
        ctx = Mock()
        ctx.make_session_report.return_value = SimpleNamespace(events=[], duration=0.1)
        with (
            tempfile.TemporaryDirectory() as parent,
            patch(
                "services.conversation_agent.observations.DIRECTORY", Path(parent) / "observations"
            ),
            patch("services.conversation_agent.observations.set_tracer_provider"),
        ):
            observer = SessionObserver(
                session, TraceRuntime(TraceSettings("conversation-agent", mode="local_real"))
            )
            await observer.aclose(session, ctx)
            files = list((Path(parent) / "observations").glob("*.json"))
            self.assertEqual(len(files), 1)
            self.assertEqual(json.loads(files[0].read_text())["mode"], "local_real")

    async def test_report_creation_failure_is_visible_and_trace_cleanup_still_runs(self):
        session = Mock()
        ctx = Mock()
        ctx.make_session_report.side_effect = ValueError("SECRET_SENTINEL")
        with (
            tempfile.TemporaryDirectory() as parent,
            patch(
                "services.conversation_agent.observations.DIRECTORY", Path(parent) / "observations"
            ),
            patch("services.conversation_agent.observations.set_tracer_provider"),
        ):
            observer = SessionObserver(session, TraceRuntime(TraceSettings("conversation-agent")))
            with self.assertRaisesRegex(ValueError, "SECRET_SENTINEL"):
                await observer.aclose(session, ctx)
            files = list((Path(parent) / "observations").glob("*.json"))
            self.assertEqual(len(files), 1)
            self.assertFalse(json.loads(files[0].read_text())["sdk_report_observed"])
            self.assertNotIn("SECRET_SENTINEL", files[0].read_text())
            self.assertTrue(observer.tracing.close())

    def test_nonfinite_boolean_and_extreme_numeric_counts_are_not_exported(self):
        for value in (True, -1, float("inf"), float("nan"), 10**1000, "SECRET_SENTINEL", object()):
            self.assertEqual(finite(value), 0)
        self.assertEqual(finite(0.25), 0.25)
