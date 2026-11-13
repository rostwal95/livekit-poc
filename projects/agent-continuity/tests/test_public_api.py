"""Public exports and real finite-I/O barriers, independent of media or a server."""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
import unittest
from datetime import date
from unittest.mock import Mock, patch

from continuity_lab import api
from continuity_lab.authorization import TokenDirectory
from continuity_lab.case_projection import CaseProjection
from continuity_lab.conversation_service import AsyncConversationService, ConversationService
from continuity_lab.postgres_api import (
    AuthenticatedActor,
    AuthenticationFailed,
    BearerToken,
    ManagedCaseClient,
    ManagedReceipt,
    PostgresSettings,
    QuoteSnapshot,
    open_postgres_client,
    parse_confirmation_payload,
)

TOKEN = BearerToken("synthetic-token-" + "x" * 32)
ACTOR = AuthenticatedActor("test-operator", "test-traveller")
TASK = "11111111-1111-4111-8111-111111111111"
CASE = "22222222-2222-4222-8222-222222222222"
REQUEST = api.BookingChange("DEMO-BK-001", date(2030, 12, 10), True)


class ExportTests(unittest.TestCase):
    def test_exports_are_explicit_and_legacy_values_keep_identity(self):
        from continuity_lab.execution import ExecutionStore
        from continuity_lab.models import BookingChange
        from continuity_lab.store import TaskStore

        self.assertIs(api.BookingChange, BookingChange)
        self.assertIs(api.ExecutionStore, ExecutionStore)
        self.assertIs(api.TaskStore, TaskStore)
        self.assertEqual(len(api.__all__), len(set(api.__all__)))
        self.assertTrue(all(hasattr(api, name) for name in api.__all__))
        self.assertNotIn("BoundedAsyncIO", api.__all__)
        self.assertNotIn("safe_error_code", dir(ManagedCaseClient))
        self.assertFalse(hasattr(ManagedCaseClient, "run"))

    def test_failure_codes_never_serialize_private_message_cause_or_unknown_metadata(self):
        sentinel = "private-error-and-provider-sentinel"
        failure = api.StorageUnavailable(sentinel)
        failure.__cause__ = RuntimeError(sentinel)
        self.assertEqual(api.safe_error_code(failure), "storage_unavailable")
        failure.code = sentinel
        self.assertEqual(api.safe_error_code(failure), "execution_error")
        failure.code = object()
        self.assertEqual(api.safe_error_code(failure), "execution_error")
        values = [
            api.safe_error_code(api.IdempotencyConflict(sentinel)),
            api.safe_error_code(ValueError(sentinel)),
            api.safe_error_code(RuntimeError(sentinel)),
        ]
        self.assertEqual(values, ["idempotency_conflict", "invalid_input", "unexpected_error"])
        self.assertNotIn(sentinel, json.dumps(values))

    def test_tampered_error_property_cannot_replace_the_original_failure(self):
        class BadMetadata(api.ExecutionError):
            @property
            def code(self):
                raise RuntimeError("private-metadata-sentinel")

        self.assertEqual(api.safe_error_code(BadMetadata("private")), "execution_error")

    def test_client_methods_have_no_token_scope_actor_or_callable_input(self):
        for name in ("submit", "get", "cancel", "prepare_quote", "signal"):
            parameters = inspect.signature(getattr(ManagedCaseClient, name)).parameters
            self.assertFalse({"scope_id", "actor", "token", "action"} & set(parameters))

    def test_invalid_client_composition_is_rejected_without_work(self):
        with self.assertRaises(ValueError):
            ManagedCaseClient(object(), TOKEN)

    def test_managed_factory_requires_active_v4_before_constructing_a_boundary(self):
        settings = PostgresSettings(password="synthetic-test-password")
        connection = Mock()
        failure = api.SchemaVersionError("Unsupported fixture schema")
        with (
            patch.object(PostgresSettings, "connect", return_value=connection),
            patch("continuity_lab.postgres_api._validate_schema", side_effect=failure) as validate,
            patch("continuity_lab.postgres_api.build_conversation_service") as compose,
        ):
            with self.assertRaises(api.SchemaVersionError) as caught:
                open_postgres_client(actor=ACTOR, token=TOKEN, settings=settings)
            self.assertIs(caught.exception, failure)
            validate.assert_called_once_with(
                connection, settings.schema, require_active=True, minimum_version=4
            )
            connection.close.assert_called_once_with()
            compose.assert_not_called()

    def test_managed_factory_rejects_untyped_configuration_before_any_connection(self):
        settings = PostgresSettings(password="synthetic-test-password")
        for values in (
            {"actor": object(), "token": TOKEN, "settings": settings},
            {"actor": ACTOR, "token": object(), "settings": settings},
            {"actor": ACTOR, "token": TOKEN, "settings": object()},
        ):
            with (
                self.subTest(values=tuple(values)),
                patch.object(PostgresSettings, "connect") as connect,
            ):
                with self.assertRaises(ValueError):
                    open_postgres_client(**values)
                connect.assert_not_called()


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_running_loop()
        self.boundaries = []
        self.releases = []
        self.callers = []

    async def asyncTearDown(self):
        for release in self.releases:
            release.set()
        if self.callers:
            await asyncio.gather(*self.callers, return_exceptions=True)
        for boundary in self.boundaries:
            boundary.shutdown_timeout = 2
            await boundary.close()

    def client(self, service, *, shutdown_timeout=0.03):
        boundary = AsyncConversationService(
            service, maximum=1, admission_timeout=0.02, shutdown_timeout=shutdown_timeout
        )
        self.boundaries.append(boundary)
        return ManagedCaseClient(boundary, TOKEN)

    def held(self):
        started, finished = asyncio.Event(), asyncio.Event()
        release = threading.Event()
        self.releases.append(release)
        service = Mock()
        receipt = ManagedReceipt(True, TASK, CASE, CaseProjection.create({"task_id": TASK}))

        def submit(**kwargs):
            self.loop.call_soon_threadsafe(started.set)
            try:
                if not release.wait(timeout=5):
                    raise TimeoutError("Owned unit barrier was not released")
                return receipt
            finally:
                self.loop.call_soon_threadsafe(finished.set)

        service.submit.side_effect = submit
        return service, started, finished, release, receipt

    async def test_authenticated_operations_bind_the_original_token_and_typed_values(self):
        service = Mock()
        receipt = ManagedReceipt(True, TASK, CASE, CaseProjection.create({"task_id": TASK}))
        service.submit.return_value = receipt
        service.get.return_value = receipt.projection
        client = self.client(service)
        self.assertIs(await client.submit(idempotency_key="original", request=REQUEST), receipt)
        self.assertIs(await client.get(task_id=TASK, cursor=None, limit=1), receipt.projection)
        await client.cancel(task_id=TASK, command_id="original-cancel")
        self.assertEqual(
            service.submit.call_args.kwargs,
            {"token": TOKEN, "idempotency_key": "original", "request": REQUEST},
        )
        self.assertEqual(
            service.get.call_args.kwargs,
            {"token": TOKEN, "task_id": TASK, "cursor": None, "limit": 1},
        )
        self.assertEqual(
            service.cancel.call_args.kwargs,
            {"token": TOKEN, "task_id": TASK, "command_id": "original-cancel"},
        )
        await client.close()
        with self.assertRaises(api.ExecutionPortClosed):
            await client.get(task_id=TASK)

    async def test_unknown_credential_fails_before_authority_and_owner_is_not_overridable(self):
        directory = TokenDirectory({TOKEN: ACTOR})
        cases = Mock(directory=directory)
        projections = Mock()
        projections.get.return_value = CaseProjection.create({"task_id": TASK})
        service = ConversationService(directory, Mock(), projections, cases)
        client = self.client(service)
        await client.get(task_id=TASK)
        self.assertEqual(projections.get.call_args.kwargs["actor"], ACTOR)
        unknown = ManagedCaseClient(
            self.boundaries[-1], BearerToken("unknown-test-token-" + "y" * 32)
        )
        projections.reset_mock()
        with self.assertRaises(AuthenticationFailed):
            await unknown.get(task_id=TASK)
        projections.get.assert_not_called()
        with self.assertRaises(TypeError):
            await client.get(task_id=TASK, scope_id="another-account")
        projections.get.assert_not_called()

    async def test_controller_signal_keeps_exact_confirmation_and_rejects_another_route(self):
        directory = TokenDirectory({TOKEN: ACTOR})
        cases = Mock(directory=directory)
        service = ConversationService(directory, Mock(), Mock(), cases)
        client = self.client(service)
        quote = QuoteSnapshot(
            "33333333-3333-4333-8333-333333333333",
            TASK,
            2,
            REQUEST.booking_reference,
            REQUEST.new_check_in,
            2500,
            "USD",
            "2030-12-01T00:02:00+00:00",
            CASE,
            7,
            "44444444-4444-4444-8444-444444444444",
        )
        payload = json.dumps(quote.payload(), sort_keys=True, separators=(",", ":"))
        confirmation = parse_confirmation_payload(payload, explicit=True)
        await client.signal(task_id=TASK, confirmation=confirmation, command_id="exact-original")
        self.assertIs(cases.signal.call_args.kwargs["confirmation"], confirmation)
        self.assertEqual(cases.signal.call_args.kwargs["token"], TOKEN)
        self.assertEqual(cases.signal.call_args.kwargs["event_id"], "exact-original")
        cases.reset_mock()
        with self.assertRaises(ValueError):
            await client.signal(task_id=CASE, confirmation=confirmation, command_id="another-route")
        cases.signal.assert_not_called()
        with self.assertRaises(ValueError):
            parse_confirmation_payload(payload, explicit=False)

    async def test_cancelled_waiter_keeps_slot_and_close_timeout_until_actual_work_finishes(self):
        service, started, finished, release, _receipt = self.held()
        client = self.client(service)
        caller = asyncio.create_task(client.submit(idempotency_key="original", request=REQUEST))
        self.callers.append(caller)
        await asyncio.wait_for(started.wait(), timeout=1)
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertEqual(client.pending_count, 1)
        service.cancel.assert_not_called()
        with self.assertRaises(api.ExecutionCapacityExceeded):
            await client.get(task_id=TASK)
        service.get.assert_not_called()
        with self.assertRaises(TimeoutError):
            await client.close()
        self.assertEqual(client.pending_count, 1)
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=1)
        await client.close()
        self.assertEqual(client.pending_count, 0)
        self.assertEqual(service.submit.call_count, 1)
        service.cancel.assert_not_called()
        with self.assertRaises(api.ExecutionPortClosed):
            async with client:
                self.fail("Closed client entered")

    async def test_context_preserves_body_error_when_close_is_incomplete(self):
        service, started, finished, release, _receipt = self.held()
        client = self.client(service)
        original = RuntimeError("private-original-error")
        with self.assertRaises(RuntimeError) as caught:
            async with client:
                caller = asyncio.create_task(
                    client.submit(idempotency_key="original", request=REQUEST)
                )
                self.callers.append(caller)
                await asyncio.wait_for(started.wait(), timeout=1)
                raise original
        self.assertIs(caught.exception, original)
        self.assertEqual(client.pending_count, 1)
        self.assertTrue(any("cleanup incomplete" in note for note in original.__notes__))
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=1)
        await client.close()
        self.assertEqual(client.pending_count, 0)

    async def test_underlying_domain_failure_propagates_and_releases_capacity(self):
        service = Mock()
        original = api.StorageUnavailable("private-underlying-message")
        service.get.side_effect = original
        client = self.client(service)
        with self.assertRaises(api.StorageUnavailable) as caught:
            await client.get(task_id=TASK)
        self.assertIs(caught.exception, original)
        self.assertEqual(client.pending_count, 0)
        self.assertEqual(api.safe_error_code(caught.exception), "storage_unavailable")


if __name__ == "__main__":
    unittest.main()
