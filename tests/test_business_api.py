"""Offline HTTP tests exercise controller contracts without a provider or database."""

import asyncio
import copy
import json
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, create_autospec, patch

import jwt
from fastapi.testclient import TestClient
from livekit.protocol import agent, agent_dispatch

from continuity_lab.authorization import AuthenticatedActor, BearerToken, TokenDirectory
from continuity_lab.case_models import parse_quote
from continuity_lab.case_projection import CaseProjection
from continuity_lab.case_telemetry import CaseTelemetry
from continuity_lab.conversation_service import (
    AsyncConversationService,
    ConversationService,
    ManagedReceipt,
)
from continuity_lab.effect_models import CancellationDisposition
from continuity_lab.execution_models import ExecutionError, ExecutionNotFound
from continuity_lab.models import BookingChange, IdempotencyConflict
from continuity_lab.quote_producer import QuoteReceipt
from continuity_lab.session_grants import sign_grant, verify_grant
from services.control_api.app import create_app
from services.control_api.business import BUSINESS_AGENT_NAME
from services.control_api.business_dispatch import (
    BusinessDispatchConflict,
    BusinessDispatcher,
)
from services.control_api.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


class FakeBusinessDispatch:
    def __init__(self):
        self.calls = []
        self.failure = None

    async def dispatch(self, room, metadata):
        self.calls.append((room, metadata))
        if self.failure is not None:
            raise self.failure


class HostileDispatchError(ExecutionError):
    @property
    def code(self):
        raise RuntimeError("private-dispatch-metadata")


class BusinessApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = Settings(
            livekit_url="ws://livekit:7880",
            livekit_public_url="ws://localhost:17880",
            livekit_api_key="synthetic-key",
            livekit_api_secret="s" * 40,
            local_access_token="a" * 40,
            postgres_password="p" * 32,
            intake_database=Path(self.directory.name) / "intake.sqlite3",
        )
        self.wire = json.loads((ROOT / "contracts/business/case-projection.json").read_text())
        self.projection = CaseProjection.create(self.wire)
        self.task_id = self.wire["task_id"]
        self.quote = parse_quote(json.loads(self.wire["quote"]["confirmation_payload"]))
        self.service = create_autospec(ConversationService, instance=True)
        self.service.get.return_value = self.projection
        self.service.telemetry = CaseTelemetry()
        self.service.submit.return_value = ManagedReceipt(
            True, self.task_id, self.wire["case_id"], self.projection
        )
        self.service.prepare_quote.return_value = QuoteReceipt(self.quote, False, "wait-1")
        self.service.signal.return_value = SimpleNamespace(created=False, signal_id="signal-1")
        self.service.cancel.return_value = SimpleNamespace(
            created=True,
            cancellation_id="cancel-1",
            disposition=CancellationDisposition.BEFORE_COMMIT,
        )
        self.dispatcher = FakeBusinessDispatch()
        self.boundary = AsyncConversationService(self.service)
        self.boundary.close = AsyncMock(wraps=self.boundary.close)
        self.addCleanup(self.boundary.close.assert_awaited_once)
        self.app = create_app(
            self.settings, business=self.boundary, business_backend=self.dispatcher
        )
        self.client = self.enterContext(TestClient(self.app, raise_server_exceptions=False))
        self.headers = {"Authorization": "Bearer " + self.settings.local_access_token}
        self.investigation = {
            **self.wire["inquiry"]["request"],
            "idempotency_key": self.wire["request_key"],
        }
        self.case = f"/api/business/cases/{self.task_id}"

    def post(self, suffix, body, *, authenticated=True):
        return self.client.post(suffix, json=body, headers=self.headers if authenticated else {})

    def session(self, **updates):
        body = {
            "invocation_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "room": "business-unit",
            "identity": "browser-unit",
            "investigation": self.investigation,
        }
        body.update(updates)
        return self.post("/api/business/session", body)

    def assert_no_port_calls(self):
        self.assertEqual(self.service.method_calls, [])
        self.assertEqual(self.dispatcher.calls, [])

    def test_authentication_precedes_every_business_port(self):
        requests = (
            ("/api/business/investigations", self.investigation),
            (self.case + "/quote", {"expected_revision": "0", "command_id": "quote-1"}),
            (
                self.case + "/signal",
                {
                    "confirmation_payload": self.wire["quote"]["confirmation_payload"],
                    "explicit": True,
                    "command_id": "signal-1",
                },
            ),
            (self.case + "/cancel", {"command_id": "cancel-1"}),
            (
                "/api/business/session",
                {
                    "room": "business-unit",
                    "identity": "browser-unit",
                    "investigation": self.investigation,
                },
            ),
        )
        for path, body in requests:
            for headers in ({}, {"Authorization": "Bearer wrong"}):
                with self.subTest(path=path, headers=bool(headers)):
                    self.assertEqual(
                        self.client.post(path, json=body, headers=headers).status_code,
                        401,
                    )
        self.assertEqual(self.client.get(self.case).status_code, 401)
        self.assert_no_port_calls()

    def test_submit_preserves_managed_receipt_and_trusted_token(self):
        response = self.post("/api/business/investigations", self.investigation)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), self.service.submit.return_value.payload())
        call = self.service.submit.call_args.kwargs
        self.assertEqual(call["token"], BearerToken(self.settings.local_access_token))
        self.assertEqual(call["idempotency_key"], self.wire["request_key"])
        self.assertEqual(call["request"], BookingChange("DEMO-BK-001", date(2030, 12, 10), True))
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_full_projection_cursor_and_bigint_values_survive_get(self):
        response = self.client.get(
            self.case, headers=self.headers, params={"cursor": "opaque", "limit": 3}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.wire)
        self.assertEqual(response.json()["case_revision"], "9007199254740993")
        self.service.get.assert_called_once_with(
            token=BearerToken(self.settings.local_access_token),
            task_id=self.task_id,
            cursor="opaque",
            limit=3,
        )

    def test_quote_converts_only_canonical_decimal_revision_and_returns_known_replay(
        self,
    ):
        response = self.post(
            self.case + "/quote",
            {"expected_revision": "9007199254740993", "command_id": "quote-1"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.service.prepare_quote.assert_called_once_with(
            token=BearerToken(self.settings.local_access_token),
            task_id=self.task_id,
            expected_revision=9007199254740993,
            command_id="quote-1",
        )
        self.assertEqual(
            response.json()["receipt"],
            {
                "command_id": "quote-1",
                "created": False,
                "quote_id": self.quote.quote_id,
            },
        )
        self.assertEqual(response.json()["projection"], self.wire)

    def test_signal_preserves_exact_bigint_quote_and_human_explicit_flag(self):
        response = self.post(
            self.case + "/signal",
            {
                "confirmation_payload": self.wire["quote"]["confirmation_payload"],
                "explicit": True,
                "command_id": "signal-1",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        confirmation = self.service.signal.call_args.kwargs["confirmation"]
        self.assertEqual(confirmation.quote, self.quote)
        self.assertEqual(confirmation.quote.expected_supplier_revision, 9223372036854775806)
        self.assertIs(confirmation.explicit, True)
        self.assertEqual(
            response.json()["receipt"],
            {
                "command_id": "signal-1",
                "created": False,
                "signal_id": "signal-1",
            },
        )

    def test_route_mismatch_is_rejected_before_lifecycle_write(self):
        token = BearerToken(self.settings.local_access_token)
        directory = TokenDirectory({token: AuthenticatedActor("local-operator", "demo-traveller")})
        case_service = Mock()
        case_service.directory = directory
        actual = ConversationService(directory, Mock(), Mock(), case_service)
        self.service.signal.side_effect = actual.signal
        other = self.case.replace(self.task_id, "99999999-9999-4999-8999-999999999999")
        response = self.post(
            other + "/signal",
            {
                "confirmation_payload": self.wire["quote"]["confirmation_payload"],
                "explicit": True,
                "command_id": "signal-wrong-route",
            },
        )
        self.assertEqual(response.status_code, 422)
        case_service.signal.assert_not_called()
        self.service.get.assert_not_called()

    def test_cancel_preserves_best_effort_disposition(self):
        response = self.post(self.case + "/cancel", {"command_id": "cancel-1"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["receipt"],
            {
                "command_id": "cancel-1",
                "created": True,
                "cancellation_id": "cancel-1",
                "disposition": "cancelled_before_commit",
            },
        )
        self.assertEqual(response.json()["projection"], self.wire)

    def test_invalid_limits_and_revision_lexemes_never_reach_service(self):
        for params in (
            {"limit": 0},
            {"limit": 51},
            {"limit": "NaN"},
            {"cursor": "x" * 513},
        ):
            with self.subTest(params=params):
                self.assertEqual(
                    self.client.get(self.case, headers=self.headers, params=params).status_code,
                    422,
                )
        for value in (0, True, 0.0, "01", "-1", "1e3", "9223372036854775808", "1" * 20):
            with self.subTest(revision=value):
                self.assertEqual(
                    self.post(
                        self.case + "/quote",
                        {"expected_revision": value, "command_id": "q"},
                    ).status_code,
                    422,
                )
        self.assert_no_port_calls()

    def test_unknown_authority_fields_and_false_investigation_never_reach_service(self):
        for extra in (
            {"actor_id": "victim"},
            {"scope_id": "victim"},
            {"confirmed": False},
            {"confirmed": 1},
        ):
            response = self.post("/api/business/investigations", {**self.investigation, **extra})
            self.assertEqual(response.status_code, 422, response.text)
        for suffix, extra in (
            ("quote", {"expected_revision": "0", "actor_id": "victim"}),
            ("cancel", {"scope_id": "victim"}),
        ):
            self.assertEqual(
                self.post(self.case + "/" + suffix, {"command_id": "command", **extra}).status_code,
                422,
            )
        self.assert_no_port_calls()

    def test_noncanonical_or_nonexplicit_confirmation_is_rejected_before_service(self):
        raw = self.wire["quote"]["confirmation_payload"]
        bad = (
            raw + " ",
            raw.replace('"amount_minor":2500', '"amount_minor":2500.0'),
            raw.replace('"amount_minor":2500', '"amount_minor":NaN'),
            raw.replace("{", '{"amount_minor":2500,', 1),
        )
        for value in bad:
            with self.subTest(value=value[:60]):
                self.assertEqual(
                    self.post(
                        self.case + "/signal",
                        {
                            "confirmation_payload": value,
                            "explicit": True,
                            "command_id": "s",
                        },
                    ).status_code,
                    422,
                )
        for explicit in (False, "true", 1):
            self.assertEqual(
                self.post(
                    self.case + "/signal",
                    {
                        "confirmation_payload": raw,
                        "explicit": explicit,
                        "command_id": "s",
                    },
                ).status_code,
                422,
            )
        self.assert_no_port_calls()

    def test_direct_model_approval_endpoints_do_not_exist(self):
        for path in (
            self.case + "/confirm",
            "/api/business/tools/confirm",
            "/api/business/tools/quote",
        ):
            self.assertEqual(self.post(path, {"approved": True}).status_code, 404)
        self.assert_no_port_calls()

    def test_request_and_response_byte_budgets_fail_without_leaking_payload(self):
        response = self.post(
            "/api/business/investigations",
            {**self.investigation, "private": "x" * 17000},
        )
        self.assertEqual(response.status_code, 413)
        self.service.get.return_value = SimpleNamespace(payload=lambda: {"private": "é" * 33000})
        response = self.client.get(self.case, headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "response_too_large")
        self.assertNotIn("é", response.text)

    def test_domain_failures_have_finite_safe_codes_and_no_exception_text(self):
        for failure, status, code in (
            (ExecutionNotFound("private-booking-details"), 404, "execution_not_found"),
            (
                IdempotencyConflict("private-booking-details"),
                409,
                "idempotency_conflict",
            ),
            (
                HostileDispatchError("private-booking-details"),
                503,
                "dependency_unavailable",
            ),
        ):
            self.service.get.side_effect = failure
            response = self.client.get(self.case, headers=self.headers)
            self.assertEqual(response.status_code, status, response.text)
            self.assertEqual(response.json()["code"], code)
            self.assertNotIn("private-", response.text)

    def test_new_session_binds_configured_principal_and_returns_only_room_token(self):
        response = self.session()
        self.assertEqual(response.status_code, 200, response.text)
        room, metadata = self.dispatcher.calls[0]
        grant = verify_grant(
            metadata,
            secret=self.settings.livekit_api_secret,
            room=room,
            expected_scope=self.settings.business_scope,
            expected_actor=self.settings.business_actor,
        )
        self.assertEqual(grant.request.payload(), self.wire["inquiry"]["request"])
        self.assertEqual(grant.request_key, self.wire["request_key"])
        self.assertEqual(grant.participant, "browser-unit")
        self.assertIsNone(grant.task_id)
        self.assertEqual(grant.expires_at - grant.issued_at, 300)
        result = response.json()
        payload = jwt.decode(
            result["token"],
            self.settings.livekit_api_secret,
            algorithms=["HS256"],
            issuer="synthetic-key",
        )
        self.assertEqual(payload["sub"], "browser-unit")
        self.assertEqual(payload["video"]["room"], "business-unit")
        self.assertTrue(payload["video"]["roomJoin"])
        self.assertFalse(payload["video"].get("roomAdmin", False))
        self.assertFalse(payload["video"].get("roomCreate", False))
        self.assertGreaterEqual(payload["exp"] - time.time(), 295)
        self.assertLessEqual(payload["exp"] - time.time(), 300)
        self.assertEqual(result["expires_in"], 300)
        self.assertEqual(result["agent_name"], BUSINESS_AGENT_NAME)
        self.assertTrue(result["agent_dispatched"])
        self.assertEqual(result["mode"], "scripted")
        self.assertNotIn("request", payload)
        self.assertNotIn("metadata", result)
        self.assertNotIn("signature", result)
        for secret in (
            self.settings.local_access_token,
            self.settings.livekit_api_secret,
            self.settings.postgres_password,
            metadata,
        ):
            self.assertNotIn(secret, response.text)
        self.service.submit.assert_not_called()

    def test_session_profile_is_derived_only_from_trusted_server_configuration(self):
        self.app.state.settings = replace(self.settings, conversation_inference_mode="local_real")
        response = self.session()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["mode"], "local_real")
        self.assertEqual(response.json()["agent_name"], BUSINESS_AGENT_NAME)
        self.assertEqual(len(self.dispatcher.calls), 1)

    def test_provider_session_mode_is_minted_only_from_trusted_configuration_without_provider_credentials(
        self,
    ):
        self.app.state.settings = replace(
            self.settings, conversation_inference_mode="provider_real"
        )
        response = self.session()
        self.assertEqual(200, response.status_code)
        self.assertEqual("provider_real", response.json()["mode"])
        self.assertEqual(BUSINESS_AGENT_NAME, response.json()["agent_name"])
        self.assertEqual(1, len(self.dispatcher.calls))
        for forbidden in ("api_key", "provider_token", "deepgram", "elevenlabs", "openai"):
            self.assertNotIn(forbidden, response.text.lower())
        self.service.submit.assert_not_called()

    def test_session_request_cannot_override_the_configured_inference_profile(self):
        for mode in ("local_real", "provider_real"):
            for field in ("mode", "conversation_inference_mode", "inference_mode"):
                with self.subTest(field=field, mode=mode):
                    response = self.session(**{field: mode})
                    self.assertEqual(response.status_code, 422)
                    self.assertEqual(self.dispatcher.calls, [])

    def test_owned_task_session_uses_original_request_and_original_request_key(self):
        revised = copy.deepcopy(self.wire)
        revised["request"]["new_check_in"] = "2030-12-20"
        self.service.get.return_value = CaseProjection.create(revised)
        response = self.session(investigation=None, task_id=self.task_id)
        self.assertEqual(response.status_code, 200, response.text)
        self.service.get.assert_called_once_with(
            token=BearerToken(self.settings.local_access_token), task_id=self.task_id
        )
        room, metadata = self.dispatcher.calls[0]
        grant = verify_grant(
            metadata,
            secret=self.settings.livekit_api_secret,
            room=room,
            expected_scope=self.settings.business_scope,
            expected_actor=self.settings.business_actor,
        )
        self.assertEqual(grant.request.payload(), self.wire["inquiry"]["request"])
        self.assertEqual(grant.request_key, self.wire["request_key"])
        self.assertEqual(grant.task_id, self.task_id)
        self.service.submit.assert_not_called()

    def test_unowned_task_does_not_dispatch_or_return_a_token(self):
        self.service.get.side_effect = ExecutionNotFound("private-other-owner")
        response = self.session(investigation=None, task_id=self.task_id)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("token", response.json())
        self.assertEqual(self.dispatcher.calls, [])

    def test_invalid_session_bindings_fail_before_ports(self):
        variants = (
            {"invocation_id": None},
            {"invocation_id": True},
            {"invocation_id": "not-a-uuid"},
            {"investigation": None},
            {"task_id": self.task_id},
            {"scope_id": "victim"},
            {"actor_id": "victim"},
            {"room": "lab-diagnostic"},
            {"identity": "agent-identity"},
            {"investigation": {**self.investigation, "confirmed": False}},
            {"investigation": {**self.investigation, "idempotency_key": "bad\nkey"}},
        )
        for updates in variants:
            with self.subTest(updates=updates):
                response = self.session(**updates)
                self.assertEqual(response.status_code, 422, response.text)
        self.assert_no_port_calls()

    def test_dispatch_conflict_and_hostile_metadata_have_fixed_safe_details(self):
        for failure, status, code in (
            (
                BusinessDispatchConflict("private-provider-metadata"),
                409,
                "session_in_use",
            ),
            (ExecutionError("private-provider-metadata"), 503, "dispatch_unavailable"),
            (RuntimeError("private-provider-metadata"), 503, "dispatch_unavailable"),
            (
                HostileDispatchError("private-provider-metadata"),
                503,
                "dispatch_unavailable",
            ),
        ):
            with self.subTest(failure=type(failure).__name__):
                self.dispatcher.failure = failure
                response = self.session()
                self.assertEqual(response.status_code, status, response.text)
                self.assertEqual(response.json()["code"], code)
                self.assertNotIn("private-", response.text)
                self.assertNotIn("token", response.json())

    def test_jobless_dispatch_never_returns_a_room_token_or_spurious_replacement(self):
        metadata = sign_grant(
            secret=self.settings.livekit_api_secret,
            actor=AuthenticatedActor(self.settings.business_actor, self.settings.business_scope),
            room="business-unit",
            participant="browser-unit",
            request=BookingChange("DEMO-BK-001", date(2030, 12, 10), True),
            request_key=self.investigation["idempotency_key"],
            grant_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        )
        empty = agent_dispatch.AgentDispatch(
            id="AD_jobless",
            agent_name=BUSINESS_AGENT_NAME,
            room="business-unit",
            metadata=metadata,
            state=agent_dispatch.AgentDispatchState(),
        )
        for existing in ([], [empty]):
            with self.subTest(existing=bool(existing)):
                client = SimpleNamespace(
                    room=SimpleNamespace(create_room=AsyncMock()),
                    agent_dispatch=SimpleNamespace(
                        list_dispatch=AsyncMock(return_value=existing),
                        create_dispatch=AsyncMock(
                            side_effect=lambda request: agent_dispatch.AgentDispatch(
                                id="AD_jobless",
                                agent_name=BUSINESS_AGENT_NAME,
                                room="business-unit",
                                metadata=request.metadata,
                                state=agent_dispatch.AgentDispatchState(),
                            )
                        ),
                        get_dispatch=AsyncMock(return_value=empty),
                        delete_dispatch=AsyncMock(),
                    ),
                )
                context = AsyncMock()
                context.__aenter__.return_value = client
                actual_timeout = asyncio.timeout
                self.app.state.business_backend = BusinessDispatcher(
                    self.settings, readiness=SimpleNamespace(available=AsyncMock(return_value=True))
                )
                with (
                    patch(
                        "services.control_api.business_dispatch.api.LiveKitAPI",
                        return_value=context,
                    ),
                    patch(
                        "services.control_api.business_dispatch.asyncio.timeout",
                        side_effect=lambda seconds, actual=actual_timeout: actual(
                            0.08 if seconds == 4 else seconds
                        ),
                    ) as timeout,
                ):
                    response = self.session()
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(response.json()["code"], "dispatch_unavailable")
                self.assertNotIn("token", response.json())
                self.assertEqual(
                    client.agent_dispatch.create_dispatch.await_count,
                    0 if existing else 1,
                )
                client.agent_dispatch.delete_dispatch.assert_not_awaited()
                self.assertGreaterEqual(client.agent_dispatch.get_dispatch.await_count, 1)
                timeout.assert_any_call(4)
                self.assertEqual(sum(call.args == (4,) for call in timeout.call_args_list), 1)
                for private in (
                    metadata,
                    self.settings.livekit_api_secret,
                    self.settings.local_access_token,
                ):
                    self.assertNotIn(private, response.text)

    def test_lost_session_ack_reuses_the_same_signed_assigned_invocation(self):
        metadata = sign_grant(
            secret=self.settings.livekit_api_secret,
            actor=AuthenticatedActor(self.settings.business_actor, self.settings.business_scope),
            room="business-unit",
            participant="browser-unit",
            request=BookingChange("DEMO-BK-001", date(2030, 12, 10), True),
            request_key=self.investigation["idempotency_key"],
            grant_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        )
        assigned = agent_dispatch.AgentDispatch(
            id="AD_replay",
            agent_name=BUSINESS_AGENT_NAME,
            room="business-unit",
            metadata=metadata,
            state=agent_dispatch.AgentDispatchState(
                jobs=[
                    agent.Job(
                        id="AJ_replay",
                        state=agent.JobState(
                            status=agent.JobStatus.JS_RUNNING, worker_id="AW_replay"
                        ),
                    )
                ]
            ),
        )
        client = SimpleNamespace(
            room=SimpleNamespace(create_room=AsyncMock()),
            agent_dispatch=SimpleNamespace(
                list_dispatch=AsyncMock(return_value=[assigned]),
                create_dispatch=AsyncMock(),
                get_dispatch=AsyncMock(return_value=assigned),
                delete_dispatch=AsyncMock(),
            ),
        )
        context = AsyncMock()
        context.__aenter__.return_value = client
        readiness = SimpleNamespace(available=AsyncMock(return_value=False))
        self.app.state.business_backend = BusinessDispatcher(self.settings, readiness=readiness)
        with patch("services.control_api.business_dispatch.api.LiveKitAPI", return_value=context):
            response = self.session()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("token", response.json())
        readiness.available.assert_not_awaited()
        client.agent_dispatch.create_dispatch.assert_not_awaited()
        client.agent_dispatch.delete_dispatch.assert_not_awaited()
        client.agent_dispatch.get_dispatch.assert_not_awaited()


class BusinessDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings = Settings(
            "ws://livekit:7880",
            "ws://localhost:17880",
            "synthetic",
            "s" * 40,
            "a" * 40,
            "p" * 32,
        )
        self.actor = AuthenticatedActor(self.settings.business_actor, self.settings.business_scope)
        self.arguments = {
            "secret": self.settings.livekit_api_secret,
            "actor": self.actor,
            "room": "business-dispatch",
            "participant": "browser-unit",
            "request": BookingChange("DEMO-BK-001", date(2030, 12, 10), True),
            "request_key": "original-request",
            "grant_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        }
        self.metadata = sign_grant(**self.arguments)

    async def exercise(self, records):
        client = SimpleNamespace(
            room=SimpleNamespace(create_room=AsyncMock()),
            agent_dispatch=SimpleNamespace(
                list_dispatch=AsyncMock(return_value=records),
                create_dispatch=AsyncMock(return_value=self.record(self.metadata)),
                get_dispatch=AsyncMock(
                    return_value=self.record(self.metadata, status=agent.JobStatus.JS_RUNNING)
                ),
                delete_dispatch=AsyncMock(),
            ),
        )
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch(
            "services.control_api.business_dispatch.api.LiveKitAPI",
            return_value=context,
        ):
            await BusinessDispatcher(
                self.settings, readiness=SimpleNamespace(available=AsyncMock(return_value=True))
            ).dispatch("business-dispatch", self.metadata)
        return client

    def record(self, metadata, *, status=None, worker_id=None):
        return agent_dispatch.AgentDispatch(
            id="AD_business",
            agent_name=BUSINESS_AGENT_NAME,
            room="business-dispatch",
            metadata=metadata,
            state=agent_dispatch.AgentDispatchState(
                jobs=[]
                if status is None
                else [
                    agent.Job(
                        id="AJ_business",
                        state=agent.JobState(
                            status=status,
                            worker_id=(
                                "AW_business" if status == agent.JobStatus.JS_RUNNING else ""
                            )
                            if worker_id is None
                            else worker_id,
                        ),
                    )
                ]
            ),
        )

    async def test_fresh_dispatch_is_named_and_room_is_bounded(self):
        client = await self.exercise([])
        request = client.agent_dispatch.create_dispatch.call_args.args[0]
        self.assertEqual(
            (request.room, request.agent_name, request.metadata),
            ("business-dispatch", BUSINESS_AGENT_NAME, self.metadata),
        )
        room = client.room.create_room.call_args.args[0]
        self.assertEqual(
            (room.max_participants, room.empty_timeout, room.departure_timeout),
            (3, 60, 10),
        )

    async def test_same_active_binding_reuses_dispatch_despite_new_grant_nonce(self):
        original = sign_grant(**self.arguments)
        client = await self.exercise([self.record(original)])
        client.agent_dispatch.create_dispatch.assert_not_awaited()
        client.agent_dispatch.delete_dispatch.assert_not_awaited()

    async def test_active_changed_binding_and_untrusted_metadata_fail_closed(self):
        for metadata in (
            sign_grant(**{**self.arguments, "request_key": "different-request"}),
            "untrusted-private-metadata",
        ):
            with (
                self.subTest(metadata=metadata[:25]),
                self.assertRaises(BusinessDispatchConflict),
            ):
                await self.exercise([self.record(metadata, status=agent.JobStatus.JS_RUNNING)])

    async def test_terminal_binding_is_removed_before_new_dispatch(self):
        client = await self.exercise(
            [
                self.record(
                    sign_grant(
                        **{**self.arguments, "grant_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}
                    ),
                    status=agent.JobStatus.JS_SUCCESS,
                )
            ]
        )
        client.agent_dispatch.delete_dispatch.assert_awaited_once_with(
            "AD_business", "business-dispatch"
        )
        client.agent_dispatch.create_dispatch.assert_awaited_once()

    async def test_known_assigned_job_reuses_the_original_dispatch_without_poll_or_write(
        self,
    ):
        client = await self.exercise(
            [self.record(self.metadata, status=agent.JobStatus.JS_RUNNING)]
        )
        client.agent_dispatch.create_dispatch.assert_not_awaited()
        client.agent_dispatch.delete_dispatch.assert_not_awaited()
        client.agent_dispatch.get_dispatch.assert_not_awaited()

    async def test_job_completion_before_assignment_is_observed_cannot_count_as_admission(
        self,
    ):
        client = SimpleNamespace(
            room=SimpleNamespace(create_room=AsyncMock()),
            agent_dispatch=SimpleNamespace(
                list_dispatch=AsyncMock(return_value=[]),
                create_dispatch=AsyncMock(return_value=self.record(self.metadata)),
                get_dispatch=AsyncMock(
                    return_value=self.record(self.metadata, status=agent.JobStatus.JS_FAILED)
                ),
                delete_dispatch=AsyncMock(),
            ),
        )
        context = AsyncMock()
        context.__aenter__.return_value = client
        with (
            patch(
                "services.control_api.business_dispatch.api.LiveKitAPI",
                return_value=context,
            ),
            self.assertRaises(ExecutionError),
        ):
            await BusinessDispatcher(
                self.settings, readiness=SimpleNamespace(available=AsyncMock(return_value=True))
            ).dispatch("business-dispatch", self.metadata)
        client.agent_dispatch.create_dispatch.assert_awaited_once()
        client.agent_dispatch.delete_dispatch.assert_not_awaited()

    async def test_running_status_without_a_worker_is_unassigned_and_never_replaced(
        self,
    ):
        unassigned = self.record(self.metadata, status=agent.JobStatus.JS_RUNNING, worker_id="")
        client = SimpleNamespace(
            room=SimpleNamespace(create_room=AsyncMock()),
            agent_dispatch=SimpleNamespace(
                list_dispatch=AsyncMock(return_value=[unassigned]),
                create_dispatch=AsyncMock(),
                get_dispatch=AsyncMock(return_value=unassigned),
                delete_dispatch=AsyncMock(),
            ),
        )
        context = AsyncMock()
        context.__aenter__.return_value = client
        actual_timeout = asyncio.timeout
        with (
            patch(
                "services.control_api.business_dispatch.api.LiveKitAPI",
                return_value=context,
            ),
            patch(
                "services.control_api.business_dispatch.asyncio.timeout",
                side_effect=lambda seconds, actual=actual_timeout: actual(
                    0.08 if seconds == 4 else seconds
                ),
            ) as timeout,
            self.assertRaises(ExecutionError),
        ):
            await BusinessDispatcher(
                self.settings, readiness=SimpleNamespace(available=AsyncMock(return_value=True))
            ).dispatch("business-dispatch", self.metadata)
        client.agent_dispatch.create_dispatch.assert_not_awaited()
        client.agent_dispatch.delete_dispatch.assert_not_awaited()
        timeout.assert_called_once_with(4)

    async def test_poll_cannot_switch_to_another_record_or_another_signed_binding(self):
        switched = self.record(self.metadata, status=agent.JobStatus.JS_RUNNING)
        switched.id = "AD_other"
        changed = self.record(
            sign_grant(**{**self.arguments, "request_key": "different-request"}),
            status=agent.JobStatus.JS_RUNNING,
        )
        for observation in (switched, changed, None):
            with self.subTest(observation=observation is None):
                client = SimpleNamespace(
                    room=SimpleNamespace(create_room=AsyncMock()),
                    agent_dispatch=SimpleNamespace(
                        list_dispatch=AsyncMock(return_value=[]),
                        create_dispatch=AsyncMock(return_value=self.record(self.metadata)),
                        get_dispatch=AsyncMock(return_value=observation),
                        delete_dispatch=AsyncMock(),
                    ),
                )
                context = AsyncMock()
                context.__aenter__.return_value = client
                with (
                    patch(
                        "services.control_api.business_dispatch.api.LiveKitAPI",
                        return_value=context,
                    ),
                    self.assertRaises(ExecutionError),
                ):
                    await BusinessDispatcher(
                        self.settings,
                        readiness=SimpleNamespace(available=AsyncMock(return_value=True)),
                    ).dispatch("business-dispatch", self.metadata)
                client.agent_dispatch.create_dispatch.assert_awaited_once()
                client.agent_dispatch.delete_dispatch.assert_not_awaited()

    async def test_new_invocation_waits_for_known_terminal_before_retirement_and_readiness(self):
        old_metadata = sign_grant(
            **{**self.arguments, "grant_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}
        )
        old_running = self.record(old_metadata, status=agent.JobStatus.JS_RUNNING)
        old_ended = self.record(old_metadata, status=agent.JobStatus.JS_SUCCESS)
        new_assigned = self.record(self.metadata, status=agent.JobStatus.JS_RUNNING)
        actions = []
        readiness = SimpleNamespace(
            available=AsyncMock(side_effect=lambda: actions.append("ready") or True)
        )
        client = SimpleNamespace(
            room=SimpleNamespace(create_room=AsyncMock()),
            agent_dispatch=SimpleNamespace(
                list_dispatch=AsyncMock(return_value=[old_running]),
                create_dispatch=AsyncMock(
                    side_effect=lambda request: (
                        actions.append("create") or self.record(self.metadata)
                    )
                ),
                get_dispatch=AsyncMock(side_effect=[old_ended, new_assigned]),
                delete_dispatch=AsyncMock(side_effect=lambda *args: actions.append("retire")),
            ),
        )
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch("services.control_api.business_dispatch.api.LiveKitAPI", return_value=context):
            await BusinessDispatcher(self.settings, readiness=readiness).dispatch(
                "business-dispatch", self.metadata
            )
        self.assertEqual(actions, ["retire", "ready", "create"])
        client.agent_dispatch.delete_dispatch.assert_awaited_once()
        client.agent_dispatch.create_dispatch.assert_awaited_once()

    async def test_new_invocation_never_kills_an_active_or_unknown_prior_invocation(self):
        old_metadata = sign_grant(
            **{**self.arguments, "grant_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}
        )
        for previous in (
            self.record(old_metadata),
            self.record(old_metadata, status=agent.JobStatus.JS_RUNNING),
        ):
            with self.subTest(jobless=not previous.state.jobs):
                readiness = SimpleNamespace(available=AsyncMock(return_value=True))
                client = SimpleNamespace(
                    room=SimpleNamespace(create_room=AsyncMock()),
                    agent_dispatch=SimpleNamespace(
                        list_dispatch=AsyncMock(return_value=[previous]),
                        create_dispatch=AsyncMock(),
                        get_dispatch=AsyncMock(return_value=previous),
                        delete_dispatch=AsyncMock(),
                    ),
                )
                context = AsyncMock()
                context.__aenter__.return_value = client
                actual_timeout = asyncio.timeout
                with (
                    patch(
                        "services.control_api.business_dispatch.api.LiveKitAPI",
                        return_value=context,
                    ),
                    patch(
                        "services.control_api.business_dispatch.asyncio.timeout",
                        side_effect=lambda seconds, actual=actual_timeout: actual(0.08),
                    ),
                    self.assertRaises(ExecutionError),
                ):
                    await BusinessDispatcher(self.settings, readiness=readiness).dispatch(
                        "business-dispatch", self.metadata
                    )
                client.agent_dispatch.create_dispatch.assert_not_awaited()
                client.agent_dispatch.delete_dispatch.assert_not_awaited()
                readiness.available.assert_not_awaited()

    async def test_same_invocation_terminal_receipt_does_not_start_another_consumer(self):
        previous = self.record(self.metadata, status=agent.JobStatus.JS_SUCCESS)
        client = SimpleNamespace(
            room=SimpleNamespace(create_room=AsyncMock()),
            agent_dispatch=SimpleNamespace(
                list_dispatch=AsyncMock(return_value=[previous]),
                create_dispatch=AsyncMock(),
                get_dispatch=AsyncMock(),
                delete_dispatch=AsyncMock(),
            ),
        )
        context = AsyncMock()
        context.__aenter__.return_value = client
        with (
            patch("services.control_api.business_dispatch.api.LiveKitAPI", return_value=context),
            self.assertRaises(ExecutionError),
        ):
            await BusinessDispatcher(
                self.settings, readiness=SimpleNamespace(available=AsyncMock(return_value=True))
            ).dispatch("business-dispatch", self.metadata)
        client.agent_dispatch.create_dispatch.assert_not_awaited()
        client.agent_dispatch.delete_dispatch.assert_not_awaited()

    async def test_unavailable_worker_prevents_any_dispatch_creation(self):
        readiness = SimpleNamespace(available=AsyncMock(return_value=False))
        client = SimpleNamespace(
            room=SimpleNamespace(create_room=AsyncMock()),
            agent_dispatch=SimpleNamespace(
                list_dispatch=AsyncMock(return_value=[]),
                create_dispatch=AsyncMock(),
                get_dispatch=AsyncMock(),
                delete_dispatch=AsyncMock(),
            ),
        )
        context = AsyncMock()
        context.__aenter__.return_value = client
        actual_timeout = asyncio.timeout
        with (
            patch("services.control_api.business_dispatch.api.LiveKitAPI", return_value=context),
            patch(
                "services.control_api.business_dispatch.asyncio.timeout",
                side_effect=lambda seconds, actual=actual_timeout: actual(0.08),
            ),
            self.assertRaises(ExecutionError),
        ):
            await BusinessDispatcher(self.settings, readiness=readiness).dispatch(
                "business-dispatch", self.metadata
            )
        self.assertGreaterEqual(readiness.available.await_count, 1)
        client.agent_dispatch.create_dispatch.assert_not_awaited()
        client.agent_dispatch.delete_dispatch.assert_not_awaited()
