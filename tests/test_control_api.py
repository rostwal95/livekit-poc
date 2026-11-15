"""Local control boundaries use synthetic fixtures and no network providers."""

import asyncio
import json
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jwt
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from livekit.protocol import agent, agent_dispatch
from prometheus_client.parser import text_string_to_metric_families

from services.control_api.app import (
    BodyLimitMiddleware,
    BoundedIO,
    DispatchUnavailable,
    LiveKitBackend,
    SessionLimiter,
    create_app,
)
from services.control_api.settings import Settings
from services.control_api.telemetry import HttpTelemetry, TelemetryMiddleware, http_error_handler


class FakeBackend:
    def __init__(self):
        self.rooms = []
        self.failure = False

    async def dispatch(self, room):
        if self.failure:
            raise DispatchUnavailable("private-provider-secret")
        self.rooms.append(room)


async def ready(_):
    return {"postgres": True, "livekit": True}


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = Settings(
            livekit_url="ws://livekit:7880",
            livekit_public_url="ws://localhost:17880",
            livekit_api_key="localkey",
            livekit_api_secret="s" * 40,
            local_access_token="a" * 40,
            postgres_password="p" * 32,
            intake_database=Path(self.directory.name) / "intake.sqlite3",
        )
        self.backend = FakeBackend()
        self.app = create_app(self.settings, backend=self.backend, readiness=ready)
        self.client = self.enterContext(TestClient(self.app))
        self.headers = {"Authorization": "Bearer " + self.settings.local_access_token}
        self.request = {
            "booking_reference": "DEMO-BK-001",
            "new_check_in": "2030-12-10",
            "confirmed": True,
            "idempotency_key": "inquiry-001",
        }

    def session(self, **changes):
        body = {"room": "lab-unit", "identity": "browser-unit", "dispatch_agent": True}
        body.update(changes)
        return self.client.post("/api/session", headers=self.headers, json=body)

    def test_only_the_three_explicit_conversation_profiles_are_validated_at_startup(self):
        self.assertEqual(self.settings.conversation_inference_mode, "scripted")
        self.assertFalse(self.settings.business_enabled)
        self.assertEqual(
            replace(
                self.settings, conversation_inference_mode="local_real"
            ).conversation_inference_mode,
            "local_real",
        )
        self.assertEqual(
            replace(
                self.settings, conversation_inference_mode="provider_real"
            ).conversation_inference_mode,
            "provider_real",
        )
        for value in (
            "",
            "real",
            "LOCAL_REAL",
            "local_real ",
            "provider_real ",
            "PROVIDER_REAL",
            "cloud",
            "private-mode-sentinel",
            True,
            [],
            None,
        ):
            with self.subTest(kind=type(value).__name__), self.assertRaises(ValueError) as caught:
                replace(self.settings, conversation_inference_mode=value)
            self.assertNotIn("private-mode-sentinel", str(caught.exception))

    def test_environment_selects_server_profile_and_rejects_unknown_configuration_safely(self):
        values = {
            "LIVEKIT_API_KEY": "synthetic-key",
            "LIVEKIT_API_SECRET": "s" * 40,
            "LOCAL_ACCESS_TOKEN": "a" * 40,
            "POSTGRES_PASSWORD": "p" * 32,
        }
        for mode in (None, "scripted", "local_real", "provider_real", "private-mode-sentinel"):
            with self.subTest(mode=mode), patch.dict(os.environ, values, clear=True):
                if mode is not None:
                    os.environ["P1_CONVERSATION_INFERENCE"] = mode
                if mode == "private-mode-sentinel":
                    with self.assertRaises(ValueError) as caught:
                        Settings.from_env()
                    self.assertNotIn(mode, str(caught.exception))
                else:
                    settings = Settings.from_env()
                    self.assertEqual(settings.conversation_inference_mode, mode or "scripted")
                    self.assertFalse(settings.business_enabled)

    def test_provider_profile_startup_is_trusted_and_keeps_credentials_out_of_http_and_trace_configuration(
        self,
    ):
        configured = replace(self.settings, conversation_inference_mode="provider_real")
        application = create_app(configured, backend=self.backend, readiness=ready)
        with TestClient(application) as client:
            self.assertEqual("provider_real", application.state.business_tracing.mode)
            for path in ("/healthz", "/readyz", "/api/config"):
                response = client.get(path)
                self.assertEqual(200, response.status_code)
                for secret in (
                    configured.local_access_token,
                    configured.livekit_api_secret,
                    configured.postgres_password,
                ):
                    self.assertNotIn(secret, response.text)
            self.assertFalse(client.get("/api/config").json()["inference_enabled"])

    def test_health_config_and_readiness_do_not_disclose_secrets(self):
        for path in ("/healthz", "/readyz", "/api/config"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            for secret in (
                self.settings.local_access_token,
                self.settings.livekit_api_secret,
                self.settings.postgres_password,
            ):
                self.assertNotIn(secret, response.text)
        self.assertFalse(self.client.get("/api/config").json()["inference_enabled"])
        self.assertNotIn(self.settings.livekit_api_secret, repr(self.settings))

    def test_quiesced_source_keeps_m1_replay_and_reads_but_rejects_new_work(self):
        from continuity_lab.migrations import migrate
        from continuity_lab.source_transfer import prepare_source

        original = self.client.post("/api/investigations", headers=self.headers, json=self.request)
        self.assertEqual(original.status_code, 200)
        database = self.settings.intake_database
        migrate(database, Path(self.directory.name) / "m1-backup.sqlite3")
        prepare_source(database, Path(self.directory.name) / "quiescence-backup.sqlite3")
        replay = self.client.post("/api/investigations", headers=self.headers, json=self.request)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["task"]["task_id"], original.json()["task"]["task_id"])
        new_request = {**self.request, "idempotency_key": "after-cutover"}
        response = self.client.post("/api/investigations", headers=self.headers, json=new_request)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "source_quiesced")
        self.assertFalse(response.json()["retryable"])
        self.assertEqual(response.json()["retry_hint"], "use_active_execution_backend")
        self.assertEqual(
            self.client.get("/api/investigations", headers=self.headers).status_code, 200
        )

    def test_token_and_intake_require_local_operator_bearer(self):
        for path in ("/api/session", "/api/investigations"):
            for headers in ({}, {"Authorization": "Bearer wrong"}):
                response = self.client.post(path, headers=headers, json={})
                self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.get("/api/investigations").status_code, 401)

    def test_token_is_short_lived_room_scoped_and_dispatch_named_agent(self):
        response = self.session()
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        payload = jwt.decode(
            result["token"],
            self.settings.livekit_api_secret,
            algorithms=["HS256"],
            issuer="localkey",
        )
        self.assertEqual(payload["sub"], "browser-unit")
        self.assertEqual(payload["video"]["room"], "lab-unit")
        self.assertTrue(payload["video"]["roomJoin"])
        self.assertFalse(payload["video"].get("roomAdmin", False))
        self.assertFalse(payload["video"].get("roomCreate", False))
        self.assertGreaterEqual(payload["exp"] - time.time(), 295)
        self.assertLessEqual(payload["exp"] - time.time(), 300)
        self.assertEqual(result["agent_name"], "local-transport-agent")
        self.assertEqual(self.backend.rooms, ["lab-unit"])

    async def exercise_dispatch(self, existing):
        actions = []
        client = SimpleNamespace(
            room=SimpleNamespace(create_room=AsyncMock()),
            agent_dispatch=SimpleNamespace(
                list_dispatch=AsyncMock(return_value=existing),
                create_dispatch=AsyncMock(
                    side_effect=lambda request: actions.append(("create", request.agent_name))
                ),
                delete_dispatch=AsyncMock(
                    side_effect=lambda dispatch_id, room: actions.append(("delete", dispatch_id))
                ),
            ),
        )
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch("services.control_api.app.api.LiveKitAPI", return_value=context):
            await LiveKitBackend(self.settings).dispatch("lab-backend")
        room = client.room.create_room.call_args.args[0]
        self.assertEqual((room.name, room.max_participants), ("lab-backend", 6))
        self.assertEqual((room.empty_timeout, room.departure_timeout), (60, 20))
        return client, actions

    @staticmethod
    def dispatch_record(
        statuses=(),
        *,
        deleted=False,
        name="local-transport-agent",
        identifier="AD_fixture",
    ):
        return agent_dispatch.AgentDispatch(
            id=identifier,
            agent_name=name,
            room="lab-backend",
            state=agent_dispatch.AgentDispatchState(
                deleted_at=1 if deleted else 0,
                jobs=[
                    agent.Job(id=f"AJ_fixture_{index}", state=agent.JobState(status=status))
                    for index, status in enumerate(statuses)
                ],
            ),
        )

    def test_backend_creates_bounded_room_and_reuses_existing_named_dispatch(self):
        fresh, actions = asyncio.run(self.exercise_dispatch([]))
        fresh.agent_dispatch.create_dispatch.assert_awaited_once()
        fresh.agent_dispatch.delete_dispatch.assert_not_awaited()
        self.assertEqual(actions, [("create", "local-transport-agent")])
        for statuses in (
            (),
            (agent.JobStatus.JS_PENDING,),
            (agent.JobStatus.JS_RUNNING,),
            (agent.JobStatus.JS_SUCCESS, agent.JobStatus.JS_RUNNING),
            (100,),
        ):
            with self.subTest(statuses=statuses):
                existing, actions = asyncio.run(
                    self.exercise_dispatch([self.dispatch_record(statuses)])
                )
                existing.agent_dispatch.create_dispatch.assert_not_awaited()
                existing.agent_dispatch.delete_dispatch.assert_not_awaited()
                self.assertEqual(actions, [])

    def test_backend_replaces_only_nondeleted_all_terminal_named_dispatches(self):
        for statuses in (
            (agent.JobStatus.JS_SUCCESS,),
            (agent.JobStatus.JS_FAILED,),
            (agent.JobStatus.JS_CANCELLED,),
            (agent.JobStatus.JS_FAILED, agent.JobStatus.JS_SUCCESS),
        ):
            with self.subTest(statuses=statuses):
                client, actions = asyncio.run(
                    self.exercise_dispatch([self.dispatch_record(statuses)])
                )
                client.agent_dispatch.delete_dispatch.assert_awaited_once_with(
                    "AD_fixture", "lab-backend"
                )
                client.agent_dispatch.create_dispatch.assert_awaited_once()
                self.assertEqual(
                    actions,
                    [("delete", "AD_fixture"), ("create", "local-transport-agent")],
                )
        deleted = self.dispatch_record((agent.JobStatus.JS_RUNNING,), deleted=True)
        unrelated = self.dispatch_record((agent.JobStatus.JS_SUCCESS,), name="other-agent")
        client, actions = asyncio.run(self.exercise_dispatch([deleted, unrelated]))
        client.agent_dispatch.delete_dispatch.assert_not_awaited()
        self.assertEqual(actions, [("create", "local-transport-agent")])
        running = self.dispatch_record((agent.JobStatus.JS_RUNNING,), identifier="AD_running")
        terminal = self.dispatch_record((agent.JobStatus.JS_SUCCESS,), identifier="AD_terminal")
        client, actions = asyncio.run(self.exercise_dispatch([terminal, running]))
        client.agent_dispatch.delete_dispatch.assert_not_awaited()
        client.agent_dispatch.create_dispatch.assert_not_awaited()
        self.assertEqual(actions, [])

    def test_session_rejects_arbitrary_room_identity_and_grant_fields(self):
        for changes in (
            {"room": "production-room"},
            {"identity": "admin"},
            {"room": "lab-" + "x" * 80},
            {"can_admin": True},
            {"dispatch_agent": "true"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(self.session(**changes).status_code, 422)
        self.assertEqual(self.backend.rooms, [])

    def test_dispatch_failure_is_explicit_without_provider_details(self):
        self.backend.failure = True
        response = self.session()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private-provider-secret", response.text)
        self.assertNotIn("token", response.json())

    def test_valid_no_dispatch_token_does_not_require_backend(self):
        self.backend.failure = True
        response = self.session(dispatch_agent=False)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["agent_dispatched"])
        self.assertEqual(self.backend.rooms, [])

    def test_unready_dependency_returns_503(self):
        async def unavailable(_):
            return {"postgres": False, "livekit": True}

        with TestClient(
            create_app(self.settings, backend=self.backend, readiness=unavailable)
        ) as client:
            response = client.get("/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            {"status": "not_ready", "dependencies": {"postgres": False, "livekit": True}},
        )
        self.assertEqual(response.json()["code"], "dependency_unavailable")
        framework = asyncio.run(
            http_error_handler(
                Request({"type": "http", "state": {"request_id": "0" * 32}}),
                HTTPException(503, detail={"private": "framework-detail"}),
            )
        )
        self.assertEqual(json.loads(bytes(framework.body))["detail"], "Local service unavailable")

    def test_m1_confirmed_intake_replay_conflict_and_fixed_scope(self):
        first = self.client.post("/api/investigations", headers=self.headers, json=self.request)
        self.assertEqual(first.status_code, 200, first.text)
        replay = self.client.post("/api/investigations", headers=self.headers, json=self.request)
        self.assertTrue(first.json()["created"])
        self.assertFalse(replay.json()["created"])
        self.assertEqual(first.json()["task"]["task_id"], replay.json()["task"]["task_id"])
        self.assertEqual(first.json()["task"]["scope_id"], "local-lab")
        changed = dict(self.request, new_check_in="2030-12-11")
        self.assertEqual(
            self.client.post("/api/investigations", headers=self.headers, json=changed).status_code,
            409,
        )
        listing = self.client.get("/api/investigations", headers=self.headers).json()
        self.assertEqual(len(listing["items"]), 1)
        self.assertEqual(listing["items"][0]["status"], "queued")

    def test_unconfirmed_invalid_or_injected_scope_input_is_not_accepted(self):
        for changes in (
            {"confirmed": False},
            {"confirmed": 1},
            {"new_check_in": "2030-02-31"},
            {"scope_id": "other-account"},
        ):
            with self.subTest(changes=changes):
                response = self.client.post(
                    "/api/investigations",
                    headers=self.headers,
                    json=dict(self.request, **changes),
                )
                self.assertEqual(response.status_code, 422)
        self.assertEqual(
            self.client.get("/api/investigations", headers=self.headers).json()["items"],
            [],
        )

    def test_oversize_body_and_unbounded_page_are_rejected(self):
        response = self.client.post(
            "/api/session",
            headers=self.headers,
            content=json.dumps({"room": "x" * 20_000}),
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(
            self.client.get("/api/investigations?limit=101", headers=self.headers).status_code,
            422,
        )

    def test_session_rate_limit_is_bounded(self):
        self.app.state.limiter = SessionLimiter(maximum=1)
        self.assertEqual(self.session(dispatch_agent=False).status_code, 200)
        self.assertEqual(self.session(dispatch_agent=False).status_code, 429)

    def test_storage_failure_is_not_a_false_acceptance(self):
        self.settings.intake_database.unlink()
        response = self.client.post("/api/investigations", headers=self.headers, json=self.request)
        self.assertEqual(response.status_code, 503)

    def test_capacity_rejects_only_new_intake_and_retains_replay_conflict_and_reads(
        self,
    ):
        first = self.client.post("/api/investigations", headers=self.headers, json=self.request)
        self.assertEqual(first.status_code, 200)
        with patch("services.control_api.app.MAX_DATABASE_BYTES", 1):
            replay = self.client.post(
                "/api/investigations", headers=self.headers, json=self.request
            )
            self.assertEqual(replay.status_code, 200)
            self.assertFalse(replay.json()["created"])
            self.assertEqual(replay.json()["task"], first.json()["task"])
            changed = self.client.post(
                "/api/investigations",
                headers=self.headers,
                json={**self.request, "new_check_in": "2030-12-11"},
            )
            self.assertEqual(changed.status_code, 409)
            self.assertEqual(changed.json()["code"], "idempotency_conflict")
            rejected = self.client.post(
                "/api/investigations",
                headers=self.headers,
                json={**self.request, "idempotency_key": "new-request-at-capacity"},
            )
            self.assertEqual(rejected.status_code, 503)
            self.assertEqual(rejected.json()["code"], "storage_limit_reached")
            self.assertFalse(rejected.json()["retryable"])
            listing = self.client.get("/api/investigations?limit=1", headers=self.headers)
            self.assertEqual(listing.status_code, 200)
            self.assertEqual(listing.json()["items"], [first.json()["task"]])
            self.assertFalse(listing.json()["truncated"])

    def test_listing_returns_bounded_prefix_and_more_rows_observation(self):
        tasks = []
        for index in range(3):
            response = self.client.post(
                "/api/investigations",
                headers=self.headers,
                json={**self.request, "idempotency_key": f"bounded-list-{index}"},
            )
            tasks.append(response.json()["task"])
        listing = self.client.get("/api/investigations?limit=1", headers=self.headers)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["items"], tasks[:1])
        self.assertTrue(listing.json()["truncated"])

    def metric_samples(self):
        response = self.client.get("/api/metrics", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        return [
            sample
            for family in text_string_to_metric_families(response.text)
            for sample in family.samples
        ]

    def metric(self, name, labels):
        return sum(
            sample.value
            for sample in self.metric_samples()
            if sample.name == name and sample.labels == labels
        )

    def test_metrics_require_auth_and_isolate_registry_without_health_scrape_noise(
        self,
    ):
        self.assertEqual(self.client.get("/api/metrics").status_code, 401)
        for path in ("/healthz", "/readyz"):
            self.assertEqual(self.client.get(path).status_code, 200)
        empty = self.client.get("/api/metrics", headers=self.headers)
        self.assertIn("text/plain", empty.headers["content-type"])
        self.assertNotIn("operation=", empty.text)
        self.assertNotIn("process_", empty.text)
        self.assertNotIn("python_gc_", empty.text)
        self.assertEqual(self.session(dispatch_agent=False).status_code, 200)
        self.assertGreater(len(self.metric_samples()), 0)
        with TestClient(create_app(self.settings, backend=self.backend, readiness=ready)) as other:
            separate = other.get("/api/metrics", headers=self.headers)
        self.assertNotIn("operation=", separate.text)

    def test_metrics_observe_success_failure_duration_and_only_bounded_labels(self):
        self.assertEqual(self.session(dispatch_agent=False).status_code, 200)
        self.assertEqual(self.client.get("/api/investigations").status_code, 401)
        secret_path = "/private-room-and-tenant?token=never-record-this"
        self.assertEqual(self.client.get(secret_path).status_code, 404)
        labels = {"operation": "session", "method": "POST", "status_class": "2xx"}
        self.assertEqual(self.metric("livekit_control_http_requests_total", labels), 1)
        error_labels = {
            "operation": "investigations",
            "method": "GET",
            "status_class": "4xx",
        }
        self.assertEqual(self.metric("livekit_control_http_errors_total", error_labels), 1)
        labels = {"operation": "session", "method": "POST"}
        self.assertEqual(
            self.metric("livekit_control_http_request_duration_seconds_count", labels),
            1,
        )
        self.assertGreater(
            self.metric("livekit_control_http_request_duration_seconds_sum", labels), 0
        )
        self.assertEqual(self.metric("livekit_control_http_requests_in_flight", labels), 0)
        for sample in self.metric_samples():
            self.assertLessEqual(set(sample.labels), {"operation", "method", "status_class", "le"})
            if "operation" in sample.labels:
                self.assertIn(sample.labels["operation"], {"session", "investigations", "unknown"})
        metrics = self.client.get("/api/metrics", headers=self.headers).text
        for private in (
            "lab-unit",
            "browser-unit",
            "private-room-and-tenant",
            "never-record-this",
            self.settings.local_access_token,
        ):
            self.assertNotIn(private, metrics)

    def test_inflight_gauge_observes_actual_pending_dispatch_and_releases(self):
        entered, release = threading.Event(), threading.Event()

        class HeldBackend:
            async def dispatch(self, room):
                entered.set()
                if not await asyncio.to_thread(release.wait, 2):
                    raise RuntimeError("fixture deadline")

        self.app.state.backend = HeldBackend()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.session)
            try:
                self.assertTrue(entered.wait(1))
                labels = {"operation": "session", "method": "POST"}
                self.assertEqual(self.metric("livekit_control_http_requests_in_flight", labels), 1)
            finally:
                release.set()
            self.assertEqual(pending.result(timeout=2).status_code, 200)
        self.assertEqual(self.metric("livekit_control_http_requests_in_flight", labels), 0)

    def test_unexpected_failure_is_sanitized_correlated_and_counted(self):
        secret = "private-provider-secret-" + self.settings.local_access_token
        self.app.state.backend = SimpleNamespace(
            dispatch=AsyncMock(side_effect=RuntimeError(secret))
        )
        with self.assertLogs("services.control_api.telemetry", level="INFO") as captured:
            response = self.session()
        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(body["detail"], "Internal server error")
        self.assertEqual(body["code"], "internal_error")
        self.assertFalse(body["retryable"])
        self.assertEqual(body["request_id"], response.headers["x-request-id"])
        self.assertRegex(body["request_id"], r"^[0-9a-f]{32}$")
        record = json.loads(captured.records[-1].getMessage())
        self.assertEqual(record["request_id"], body["request_id"])
        self.assertEqual(record["code"], "internal_error")
        self.assertEqual(record["status"], 500)
        self.assertEqual(record["severity"], "error")
        self.assertEqual(captured.records[-1].levelname, "ERROR")
        self.assertNotIn(secret, response.text + captured.output[0])
        self.assertIsNone(captured.records[-1].exc_info)
        self.assertEqual(
            self.metric(
                "livekit_control_http_errors_total",
                {"operation": "session", "method": "POST", "status_class": "5xx"},
            ),
            1,
        )
        self.assertEqual(
            self.metric(
                "livekit_control_http_requests_in_flight",
                {"operation": "session", "method": "POST"},
            ),
            0,
        )

    def test_completion_logs_exclude_payload_headers_query_and_supplied_request_id(
        self,
    ):
        caller_id = "caller-private-request-id"
        private = "private-query-secret"
        with self.assertLogs("services.control_api.telemetry", level="INFO") as captured:
            response = self.client.post(
                "/api/session?ignored=" + private,
                headers={**self.headers, "X-Request-ID": caller_id},
                json={
                    "room": "lab-private-room",
                    "identity": "browser-private-identity",
                    "dispatch_agent": False,
                },
            )
        self.assertEqual(response.status_code, 200)
        identifier = response.headers["x-request-id"]
        self.assertRegex(identifier, r"^[0-9a-f]{32}$")
        self.assertNotEqual(identifier, caller_id)
        record = json.loads(captured.records[-1].getMessage())
        self.assertEqual(record["event"], "http_request_completed")
        self.assertEqual(record["severity"], "info")
        self.assertEqual(captured.records[-1].levelname, "INFO")
        self.assertEqual(record["request_id"], identifier)
        self.assertEqual(
            set(record),
            {
                "severity",
                "timestamp",
                "event",
                "operation",
                "method",
                "status",
                "duration_seconds",
                "request_id",
            },
        )
        for forbidden in (
            caller_id,
            private,
            "lab-private-room",
            "browser-private-identity",
            self.settings.local_access_token,
        ):
            self.assertNotIn(forbidden, captured.output[0])

    def test_expected_errors_have_stable_code_retry_hint_and_safe_detail_shape(self):
        with self.assertLogs("services.control_api.telemetry", level="INFO") as captured:
            unauthorized = self.client.post("/api/session", json={})
        record = json.loads(captured.records[-1].getMessage())
        self.assertEqual(record["severity"], "warning")
        self.assertEqual(captured.records[-1].levelname, "WARNING")
        self.assertEqual(unauthorized.json()["code"], "authentication_required")
        self.assertEqual(unauthorized.json()["retry_hint"], "provide_operator_token")
        self.assertEqual(unauthorized.headers["www-authenticate"], "Bearer")
        self.backend.failure = True
        unavailable = self.session()
        self.assertEqual(unavailable.json()["code"], "dispatch_unavailable")
        self.assertTrue(unavailable.json()["retryable"])
        self.app.state.limiter = SessionLimiter(maximum=0)
        limited = self.session(dispatch_agent=False)
        self.assertEqual(limited.json()["code"], "rate_limited")
        self.assertEqual(limited.headers["retry-after"], "60")
        oversized = self.client.post("/api/session", content="x" * 20_000)
        self.assertEqual(oversized.json()["code"], "request_too_large")
        self.assertEqual(oversized.json()["request_id"], oversized.headers["x-request-id"])
        secret_field = "private-secret-field"
        malformed = self.client.post(
            "/api/session",
            headers=self.headers,
            json={secret_field: self.settings.local_access_token},
        )
        self.assertEqual(malformed.status_code, 422)
        self.assertEqual(malformed.json()["code"], "validation_error")
        self.assertIsInstance(malformed.json()["detail"], list)
        self.assertNotIn(secret_field, malformed.text)
        self.assertNotIn(self.settings.local_access_token, malformed.text)


class CapacityTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_body_disconnect_is_499_without_false_server_error_or_response(
        self,
    ):
        telemetry = HttpTelemetry()
        application = AsyncMock()
        middleware = TelemetryMiddleware(BodyLimitMiddleware(application), telemetry)
        scope = {"type": "http", "method": "POST", "path": "/api/session", "state": {}}
        receive = AsyncMock(
            side_effect=[
                {"type": "http.request", "body": b'{"room":', "more_body": True},
                {"type": "http.disconnect"},
            ]
        )
        send = AsyncMock()
        with self.assertLogs("services.control_api.telemetry", level="INFO") as captured:
            await middleware(scope, receive, send)
        application.assert_not_awaited()
        send.assert_not_awaited()
        self.assertEqual(receive.await_count, 2)
        record = json.loads(captured.records[-1].getMessage())
        self.assertEqual((record["status"], record["code"]), (499, "client_disconnected"))
        self.assertEqual(telemetry.requests.labels("session", "POST", "4xx")._value.get(), 1)
        self.assertEqual(telemetry.errors.labels("session", "POST", "5xx")._value.get(), 0)
        self.assertEqual(telemetry.inflight.labels("session", "POST")._value.get(), 0)

    async def test_disconnect_after_completed_response_keeps_successful_outcome(self):
        telemetry = HttpTelemetry()

        async def completed(scope, receive, send):
            await receive()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})
            await receive()

        scope = {"type": "http", "method": "GET", "path": "/api/config", "state": {}}
        receive = AsyncMock(
            side_effect=[
                {"type": "http.request", "body": b"", "more_body": False},
                {"type": "http.disconnect"},
            ]
        )
        send = AsyncMock()
        with self.assertLogs("services.control_api.telemetry", level="INFO") as captured:
            await TelemetryMiddleware(completed, telemetry)(scope, receive, send)
        self.assertEqual(send.await_count, 2)
        record = json.loads(captured.records[-1].getMessage())
        self.assertEqual(record["status"], 200)
        self.assertEqual(record["event"], "http_request_completed")
        self.assertNotIn("code", record)
        self.assertEqual(telemetry.requests.labels("config", "GET", "2xx")._value.get(), 1)
        self.assertEqual(telemetry.errors.labels("config", "GET", "4xx")._value.get(), 0)

    async def test_http_cancellation_propagates_and_releases_metrics_capacity(self):
        telemetry = HttpTelemetry()
        entered = asyncio.Event()

        async def held(scope, receive, send):
            entered.set()
            await asyncio.Event().wait()

        scope = {"type": "http", "method": "POST", "path": "/api/session", "state": {}}
        middleware = TelemetryMiddleware(held, telemetry)
        request = asyncio.create_task(middleware(scope, AsyncMock(), AsyncMock()))
        await asyncio.wait_for(entered.wait(), 1)
        self.assertEqual(telemetry.inflight.labels("session", "POST")._value.get(), 1)
        request.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await request
        self.assertEqual(telemetry.inflight.labels("session", "POST")._value.get(), 0)
        self.assertEqual(telemetry.requests.labels("session", "POST", "4xx")._value.get(), 1)

    async def test_post_start_failure_has_only_sanitized_server_exception(self):
        telemetry = HttpTelemetry()

        async def failed(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            raise RuntimeError("private-provider-secret")

        scope = {"type": "http", "method": "GET", "path": "/api/config", "state": {}}
        sent = AsyncMock()
        with self.assertRaises(RuntimeError) as caught:
            await TelemetryMiddleware(failed, telemetry)(scope, AsyncMock(), sent)
        self.assertNotIn("private-provider-secret", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertEqual(sent.await_count, 1)
        self.assertEqual(telemetry.inflight.labels("config", "GET")._value.get(), 0)
        self.assertEqual(telemetry.errors.labels("config", "GET", "5xx")._value.get(), 1)

    async def test_fatal_base_exception_is_not_swallowed(self):
        telemetry = HttpTelemetry()

        class FatalFixture(BaseException):
            pass

        async def failed(scope, receive, send):
            raise FatalFixture("synthetic fatal boundary")

        scope = {"type": "http", "method": "GET", "path": "/api/config", "state": {}}
        with self.assertRaises(FatalFixture):
            await TelemetryMiddleware(failed, telemetry)(scope, AsyncMock(), AsyncMock())
        self.assertEqual(telemetry.inflight.labels("config", "GET")._value.get(), 0)

    async def test_cancelled_caller_keeps_io_capacity_until_thread_finishes(self):
        gate = BoundedIO(limit=1)
        entered, release = threading.Event(), threading.Event()

        def blocking():
            entered.set()
            release.wait(timeout=2)

        caller = asyncio.create_task(gate.run(blocking))
        await asyncio.to_thread(entered.wait, 1)
        self.assertTrue(entered.is_set())
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        with self.assertRaises(HTTPException) as error:
            await gate.run(lambda: None)
        self.assertEqual(error.exception.status_code, 503)
        release.set()
        await gate.close()
        await asyncio.sleep(0)
        self.assertEqual(len(gate.pending), 0)


if __name__ == "__main__":
    unittest.main()
