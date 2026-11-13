"""Offline typed guard/controller values, pre-I/O configuration and nested snapshots."""

import asyncio
import dataclasses
import threading
import unittest
from datetime import date
from unittest.mock import patch
from uuid import uuid4

from continuity_lab.action_api import ActionClient, ActionError, open_action_client
from continuity_lab.action_models import ActionReceipt
from continuity_lab.action_store import ActionStore
from continuity_lab.authorization import AuthenticatedActor, TokenDirectory
from continuity_lab.case_models import ActionIntent, Confirmation, QuoteSnapshot, parse_confirmation
from continuity_lab.work_api import (
    BearerToken,
    PostgresSettings,
    WorkDirectory,
    WorkPrincipal,
    WorkScope,
)


def values():
    scope = WorkScope("tenant", "account")
    task = str(uuid4())
    case = str(uuid4())
    quote = QuoteSnapshot(
        str(uuid4()),
        task,
        2,
        "DEMO-BK-001",
        date(2030, 12, 10),
        12500,
        "USD",
        "2030-12-01T00:01:00+00:00",
        case,
        0,
        str(uuid4()),
    )
    confirmation = Confirmation(quote, True)
    intent = ActionIntent(
        str(uuid4()),
        task,
        "case_scope",
        "actor",
        2,
        parse_confirmation(confirmation.payload()).quote,
        str(uuid4()),
        str(uuid4()),
        str(uuid4()),
        "2030-12-01T00:00:00+00:00",
    )
    receipt = ActionReceipt(
        str(uuid4()),
        scope,
        str(uuid4()),
        str(uuid4()),
        "a" * 64,
        "case_profile",
        "case_scope",
        "actor",
        task,
        case,
        2,
        "approve",
        parse_confirmation(confirmation.payload()),
        intent,
        1922313600000,
    )
    return receipt, confirmation


class GuardedActionValues(unittest.TestCase):
    def test_receipt_is_immutable_exact_and_redacts_business_payload_in_repr(self):
        receipt, _ = values()
        self.assertNotIn("DEMO-BK-001", repr(receipt))
        self.assertNotIn("12500", repr(receipt))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            receipt.command_id = "changed"
        for change in (
            {"expected_revision": True},
            {"expected_revision": 3},
            {"result_sha256": "BAD"},
            {"case_actor_id": "different"},
            {"scope": "wrong"},
            {"case_id": str(uuid4())},
        ):
            with self.subTest(change=tuple(change)), self.assertRaises(ActionError) as invalid:
                dataclasses.replace(receipt, **change)
            self.assertEqual(invalid.exception.code, "invalid_input")
        self.assertEqual(ActionError("PRIVATE_DEPENDENCY_SENTINEL").code, "invalid_input")

    def test_cross_sql_target_and_unknown_work_credential_fail_before_store_creation(self):
        token = BearerToken("t" * 43)
        directory = WorkDirectory({token: WorkPrincipal("actor", WorkScope("tenant", "account"))})
        settings = PostgresSettings(password="synthetic-runtime-only", schema="p1_work_fixture")
        arguments = {
            "settings": settings,
            "directory": directory,
            "token": token,
            "case_settings": dataclasses.replace(settings, schema="case_profile"),
            "case_actor": AuthenticatedActor("actor", "case_scope"),
            "case_token": BearerToken("c" * 43),
        }
        with patch("continuity_lab.action_api.WorkStore") as store:
            for changed in (
                {
                    "case_settings": dataclasses.replace(
                        settings, schema="case_profile", port=settings.port + 1
                    )
                },
                {"case_settings": settings},
                {"token": BearerToken("z" * 43)},
            ):
                with self.subTest(change=tuple(changed)), self.assertRaises(ActionError):
                    open_action_client(**{**arguments, **changed})
            store.assert_not_called()


class GuardedActionSnapshot(unittest.IsolatedAsyncioTestCase):
    async def test_confirmation_is_deep_snapshotted_before_owned_thread_wait(self):
        receipt, confirmation = values()
        entered = threading.Event()
        release = threading.Event()
        observed = []
        store = object.__new__(ActionStore)
        token = BearerToken("t" * 43)
        case_token = BearerToken("c" * 43)
        directory = WorkDirectory({token: WorkPrincipal("actor", receipt.scope)})
        client = ActionClient(
            store,
            directory,
            token,
            TokenDirectory({case_token: AuthenticatedActor("actor", "case_scope")}),
            case_token,
        )

        def commit(*args, **kwargs):
            entered.set()
            if not release.wait(2):
                raise AssertionError("release_timeout")
            observed.append(kwargs["confirmation"].quote.amount_minor)
            return receipt

        with patch.object(store, "authorize", side_effect=commit):
            task = asyncio.create_task(
                client.authorize(
                    work_id=receipt.work_id,
                    attempt_id=receipt.attempt_id,
                    result_sha256=receipt.result_sha256,
                    expected_revision=2,
                    confirmation=confirmation,
                    command_id="approve",
                )
            )
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                object.__setattr__(confirmation.quote, "amount_minor", 99999)
            finally:
                release.set()
            self.assertEqual(await task, receipt)
        await client.close()
        self.assertEqual(client.pending_count, 0)
        self.assertEqual(observed, [12500])
