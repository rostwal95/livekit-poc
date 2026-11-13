"""Offline generic result-feed values and authenticated pre-await snapshots."""

import asyncio
import dataclasses
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from continuity_lab.result_feed_api import (
    ResultFeedClient,
    ResultFeedCursor,
    ResultFeedEvent,
    ResultFeedPage,
    open_result_feed_client,
)
from continuity_lab.work_api import BearerToken, WorkDirectory, WorkError, WorkPrincipal, WorkScope


class ResultFeedValues(unittest.TestCase):
    def setUp(self):
        self.source = str(uuid4())
        self.scope = WorkScope("tenant", "account")

    def cursor(self, number=0):
        return ResultFeedCursor(self.source, self.scope, number)

    def event(self, number=1):
        return ResultFeedEvent(
            str(uuid4()),
            self.source,
            self.scope,
            number,
            str(uuid4()),
            str(uuid4()),
            "original-issue",
            "a" * 64,
            2000000000000,
            "eligible_at_commit",
            "live",
        )

    def test_cursor_and_events_are_strict_bounded_and_immutable(self):
        event = self.event()
        self.assertEqual(event.kind, "result_recorded")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            event.sequence = 9
        for number in (True, -1, 9_223_372_036_854_775_808, "1"):
            with self.assertRaises(WorkError):
                self.cursor(number)
        for change in (
            {"source_id": "not-uuid"},
            {"scope": object()},
            {"sequence": 0},
            {"origin": "invented"},
            {"disposition": "valid-now"},
            {"issue_command_id": "bad command"},
            {"result_sha256": "A" * 64},
            {"recorded_at_ms": True},
            {"kind": "cancelled"},
        ):
            with self.assertRaises(WorkError):
                dataclasses.replace(event, **change)
        self.assertEqual(self.cursor(9_223_372_036_854_775_807).sequence, 9_223_372_036_854_775_807)

    def test_page_rejects_gaps_foreign_identity_and_misleading_checkpoint(self):
        event = self.event()
        page = ResultFeedPage(
            self.source, self.scope, self.cursor(), (event,), self.cursor(1), self.cursor(2), True
        )
        for change in (
            {"events": [event]},
            {"events": (dataclasses.replace(event, sequence=2),)},
            {"next_cursor": self.cursor()},
            {"high_watermark": self.cursor()},
            {"has_more": False},
            {"has_more": 1},
            {"after": ResultFeedCursor(str(uuid4()), self.scope, 0)},
            {"events": (dataclasses.replace(event, scope=WorkScope("foreign", "account")),)},
        ):
            with self.assertRaises(WorkError):
                dataclasses.replace(page, **change)
        empty = ResultFeedPage(
            self.source, self.scope, self.cursor(2), (), self.cursor(2), self.cursor(2), False
        )
        self.assertEqual(empty.next_cursor, empty.after)

    def test_different_historical_dispositions_are_source_facts_not_authority(self):
        for status in ("eligible_at_commit", "cancelled", "expired", "superseded", "lease_expired"):
            event = dataclasses.replace(self.event(), disposition=status, origin="adopted_history")
            self.assertEqual(event.origin, "adopted_history")
            self.assertFalse(hasattr(event, "body"))
            self.assertFalse(hasattr(event, "confirmation"))

    def test_factory_authenticates_before_storage_or_io(self):
        directory = WorkDirectory(
            {BearerToken("synthetic-feed-" + "x" * 40): WorkPrincipal("actor", self.scope)}
        )
        with patch("continuity_lab.result_feed_api.WorkStore") as store:
            with self.assertRaises(WorkError) as caught:
                open_result_feed_client(
                    settings=object(),
                    directory=directory,
                    token=BearerToken("unknown-token-" + "y" * 40),
                )
            self.assertEqual(caught.exception.code, "unauthorized")
            store.assert_not_called()

    def test_read_snapshots_nested_scope_and_cursor_before_await(self):
        async def run():
            reached, release = asyncio.Event(), asyncio.Event()
            original = self.cursor()
            actual_scope = WorkScope("tenant", "account")
            captured = []

            async def held(operation):
                reached.set()
                await release.wait()
                return operation(actual_scope)

            def read(scope, after, limit):
                captured.append((scope, after, limit))
                return ResultFeedPage(self.source, scope, after, (), after, after, False)

            client = object.__new__(ResultFeedClient)
            client._source_id = self.source
            client._store = SimpleNamespace(read=read)
            client._boundary = SimpleNamespace(scope=WorkScope("tenant", "account"), _run=held)
            pending = asyncio.create_task(client.read(after=original, limit=8))
            await reached.wait()
            object.__setattr__(original.scope, "account_id", "changed")
            object.__setattr__(original, "sequence", 10)
            object.__setattr__(client._boundary.scope, "account_id", "changed")
            release.set()
            await pending
            self.assertEqual(
                captured[0], (actual_scope, ResultFeedCursor(self.source, actual_scope, 0), 8)
            )

        asyncio.run(run())

    def test_invalid_or_foreign_cursor_and_unbounded_limit_fail_before_io(self):
        async def run():
            called = False

            async def boundary(operation):
                nonlocal called
                called = True

            client = object.__new__(ResultFeedClient)
            client._source_id = self.source
            client._boundary = SimpleNamespace(scope=self.scope, _run=boundary)
            for limit in (0, 101, True, "8"):
                with self.assertRaises(WorkError):
                    await client.read(limit=limit)
            for cursor in (
                object(),
                ResultFeedCursor(str(uuid4()), self.scope, 0),
                ResultFeedCursor(self.source, WorkScope("other", "account"), 0),
            ):
                with self.assertRaises(WorkError):
                    await client.read(after=cursor)
            self.assertFalse(called)

        asyncio.run(run())

    def test_credential_scope_change_during_await_fails_closed(self):
        async def run():
            called = False

            def read(*args):
                nonlocal called
                called = True

            async def boundary(operation):
                return operation(WorkScope("other", "account"))

            client = object.__new__(ResultFeedClient)
            client._source_id = self.source
            client._store = SimpleNamespace(read=read)
            client._boundary = SimpleNamespace(scope=self.scope, _run=boundary)
            with self.assertRaises(WorkError) as caught:
                await client.read()
            self.assertEqual(caught.exception.code, "unauthorized")
            self.assertFalse(called)

        asyncio.run(run())
