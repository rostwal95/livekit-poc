"""Genuine public token APIs and fake room ports test explicit admin ownership."""

from __future__ import annotations

import asyncio
import base64
import json
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from services.channel_policy_demo import native_room_admin as admin_module
from services.channel_policy_demo.native_room_state import (
    NativeRoomError,
    RoomIdentity,
    StartCommand,
    room_metadata,
)


def uid(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012d}"


class RoomCalls:
    def __init__(self) -> None:
        self.rooms: list[SimpleNamespace] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.created = self.deleted = self.listed = 0

    async def list_rooms(self, request: object) -> SimpleNamespace:
        self.listed += 1
        self.entered.set()
        await self.release.wait()
        return SimpleNamespace(rooms=tuple(self.rooms))

    async def create_room(self, request: object) -> SimpleNamespace:
        self.created += 1
        self.entered.set()
        await self.release.wait()
        room = SimpleNamespace(name=request.name, metadata=request.metadata, sid="RM_owned")
        self.rooms = [room]
        return room

    async def delete_room(self, request: object) -> None:
        self.deleted += 1
        self.entered.set()
        await self.release.wait()
        self.rooms = []


class FakeApi:
    def __init__(self, rooms: RoomCalls) -> None:
        self.room = rooms
        self.closed = 0
        self.fail_close = False

    async def aclose(self) -> None:
        self.closed += 1
        if self.fail_close:
            self.fail_close = False
            raise RuntimeError("PRIVATE_SDK_CLOSE")


class NativeRoomAdminTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from livekit import api

        self.api_module = api
        self.settings = admin_module.LiveKitAdminSettings("local_key", "test_secret_" + "x" * 43)
        self.identity = RoomIdentity(
            "room_a", room_metadata(StartCommand(uid(1), "0", uid(2)), uid(3))
        )
        self.rooms = RoomCalls()
        self.api = FakeApi(self.rooms)
        self.owners: list[admin_module.LiveKitRoomAdmin] = []

    async def asyncTearDown(self) -> None:
        self.rooms.release.set()
        for owner in self.owners:
            async with asyncio.timeout(2):
                for _ in range(3):
                    try:
                        await owner.close()
                        break
                    except NativeRoomError as error:
                        self.assertEqual(error.code, "cleanup_incomplete")

    def owner(self, **keywords: float) -> admin_module.LiveKitRoomAdmin:
        owner = admin_module.LiveKitRoomAdmin(self.settings, **keywords)
        self.owners.append(owner)
        return owner

    def sdk(self):
        def build(url: str, key: str, secret: str, *, session: object, failover: bool) -> FakeApi:
            self.assertEqual(
                (url, key, secret),
                (self.settings.url, self.settings.api_key, self.settings.api_secret),
            )
            self.assertIs(failover, False)
            self.assertFalse(session.closed)
            return self.api

        return patch.object(self.api_module, "LiveKitAPI", side_effect=build)

    async def test_admin_url_is_canonical_loopback_and_derives_exact_rtc_port(self) -> None:
        self.assertEqual(self.settings.url, "http://127.0.0.1:17880")
        for port in (1, 7880, 7881, 17880, 65535):
            selected = admin_module.LiveKitAdminSettings(
                self.settings.api_key, self.settings.api_secret, f"http://127.0.0.1:{port}"
            )
            self.assertEqual(selected.rtc_url, f"ws://127.0.0.1:{port}")
        for url in (
            "http://127.0.0.1:0",
            "http://127.0.0.1:65536",
            "http://127.0.0.1:017880",
            "http://127.0.0.1:17880/",
            "http://127.0.0.1:17880?key=x",
            "http://127.0.0.1:17880#x",
            "http://user:secret@127.0.0.1:17880",
            "http://localhost:17880",
            "http://127.0.0.2:17880",
            "https://127.0.0.1:17880",
            "ws://127.0.0.1:17880",
            "http://127.0.0.1",
            None,
            True,
        ):
            with self.subTest(url=url), self.assertRaisesRegex(NativeRoomError, "^invalid_input$"):
                admin_module.LiveKitAdminSettings(
                    self.settings.api_key, self.settings.api_secret, url
                )

    async def test_absence_create_owned_match_delete_and_independent_absence(self) -> None:
        owner = self.owner()
        with self.sdk():
            self.assertEqual((await owner.inspect(self.identity)).state, "absent")
            actual = await owner.create(self.identity)
            self.assertEqual(actual.sid, "RM_owned")
            self.assertEqual((await owner.inspect(actual)).state, "owned")
            await owner.delete(actual)
            self.assertEqual((await owner.inspect(actual)).state, "absent")
        self.assertEqual((self.rooms.created, self.rooms.deleted, self.rooms.listed), (1, 1, 3))
        self.assertEqual(owner.pending_count, 0)
        await owner.close()
        self.assertEqual(self.api.closed, 1)

    async def test_foreign_name_metadata_or_sid_is_never_adopted(self) -> None:
        owner = self.owner()
        with self.sdk():
            for name, metadata, sid in (
                ("other_room", self.identity.metadata, "RM_owned"),
                ("room_a", "{}", "RM_owned"),
                ("room_a", self.identity.metadata, "RM_other"),
            ):
                self.rooms.rooms = [SimpleNamespace(name=name, metadata=metadata, sid=sid)]
                expected = RoomIdentity(self.identity.name, self.identity.metadata, "RM_owned")
                self.assertEqual((await owner.inspect(expected)).state, "foreign")
        self.assertEqual(self.rooms.deleted, 0)

    async def test_unknown_create_is_retained_and_reconciles_original_identity_without_retry(
        self,
    ) -> None:
        owner = self.owner(timeout_s=0.02)
        self.rooms.release.clear()
        with self.sdk():
            caller = asyncio.create_task(owner.create(self.identity))
            await self.rooms.entered.wait()
            with self.assertRaises(NativeRoomError) as caught:
                await caller
            self.assertEqual(caught.exception.code, "outcome_unknown")
            self.assertEqual(owner.pending_count, 1)
            self.rooms.release.set()
            await owner.settle()
            observed = await owner.inspect(self.identity)
        self.assertEqual(observed.state, "owned")
        self.assertEqual(self.rooms.created, 1)
        self.assertEqual(owner.pending_count, 0)

    async def test_cancellation_retains_two_actual_calls_and_capacity_until_completion(
        self,
    ) -> None:
        owner = self.owner()
        self.rooms.release.clear()
        with self.sdk():
            first = asyncio.create_task(owner.inspect(self.identity))
            await self.rooms.entered.wait()
            second = asyncio.create_task(owner.inspect(self.identity))
            await asyncio.sleep(0)
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            with self.assertRaises(NativeRoomError) as caught:
                await owner.inspect(self.identity)
            self.assertEqual(caught.exception.code, "capacity")
            self.assertEqual(owner.pending_count, 2)
            self.rooms.release.set()
            await second
            await owner.settle()
            self.assertEqual((await owner.inspect(self.identity)).state, "absent")

    async def test_close_retains_held_calls_and_reobserves_same_actual_cleanup(self) -> None:
        owner = self.owner(cleanup_timeout_s=0.02)
        self.rooms.release.clear()
        with self.sdk():
            caller = asyncio.create_task(owner.inspect(self.identity))
            await self.rooms.entered.wait()
            with self.assertRaises(NativeRoomError) as caught:
                await owner.close()
            self.assertEqual(caught.exception.code, "cleanup_incomplete")
            self.assertEqual(owner.pending_count, 1)
            self.rooms.release.set()
            await caller
            await owner.close()
        self.assertEqual(owner.pending_count, 0)
        self.assertEqual(self.api.closed, 1)
        with self.assertRaises(NativeRoomError) as caught:
            await owner.inspect(self.identity)
        self.assertEqual(caught.exception.code, "closed")

    async def test_api_constructor_failure_keeps_custom_session_owned_until_close(self) -> None:
        owner = self.owner()
        with patch.object(self.api_module, "LiveKitAPI", side_effect=RuntimeError("PRIVATE_CTOR")):
            with self.assertRaises(NativeRoomError) as caught:
                await owner.inspect(self.identity)
            self.assertEqual(str(caught.exception), "unavailable")
        session = owner._session
        self.assertIsNotNone(session)
        self.assertFalse(session.closed)
        await owner.close()
        self.assertTrue(session.closed)

    async def test_independent_session_close_runs_even_when_sdk_close_fails(self) -> None:
        owner = self.owner()
        with self.sdk():
            await owner.inspect(self.identity)
        session = owner._session
        self.api.fail_close = True
        with self.assertRaises(NativeRoomError) as caught:
            await owner.close()
        self.assertEqual(str(caught.exception), "cleanup_incomplete")
        self.assertTrue(session.closed)
        await owner.close()
        self.assertEqual(self.api.closed, 2)

    async def test_genuine_sdk_jwts_have_only_narrow_fixed_room_grants_and_original_expiry(
        self,
    ) -> None:
        owner = self.owner()
        expiry = (
            (datetime.now(UTC) + timedelta(seconds=170))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        for role in ("browser", "agent"):
            token = owner.mint(room="room_a", identity=role + "_a", role=role, expires_at=expiry)
            verified = self.api_module.TokenVerifier(
                self.settings.api_key, self.settings.api_secret, leeway=timedelta(0)
            ).verify(token)
            raw = token.split(".")[1]
            payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
            self.assertLessEqual(payload["exp"], int(datetime.fromisoformat(expiry).timestamp()))
            self.assertEqual(verified.identity, role + "_a")
            self.assertEqual(verified.video.room, "room_a")
            self.assertTrue(verified.video.room_join)
            self.assertEqual(verified.video.can_publish_sources, ["microphone"])
            self.assertEqual(verified.video.can_update_own_metadata, role == "agent")
            for flag in (
                "room_create",
                "room_list",
                "room_admin",
                "room_record",
                "ingress_admin",
                "agent",
                "can_manage_agent_session",
            ):
                self.assertFalse(getattr(verified.video, flag))
        self.assertIsNone(owner._session)

    async def test_task_allocation_failure_is_finite_and_does_not_create_sdk_resources(
        self,
    ) -> None:
        owner = self.owner()
        with (
            patch.object(
                admin_module.asyncio, "create_task", side_effect=RuntimeError("PRIVATE_TASK")
            ),
            self.assertRaises(NativeRoomError) as caught,
        ):
            await owner.inspect(self.identity)
        self.assertEqual(str(caught.exception), "unavailable")
        self.assertEqual(owner.pending_count, 0)
        self.assertIsNone(owner._session)
        with self.sdk():
            self.assertEqual((await owner.inspect(self.identity)).state, "absent")

    async def test_actual_public_sdk_call_has_network_bound_despite_twirp_timeout_none(
        self,
    ) -> None:
        entered, release = asyncio.Event(), asyncio.Event()
        handlers = set()

        async def handle(reader, writer):
            try:
                await reader.readuntil(b"\r\n\r\n")
                entered.set()
                await release.wait()
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except ConnectionError:
                    pass

        def connected(reader, writer):
            task = asyncio.create_task(handle(reader, writer))
            handlers.add(task)
            task.add_done_callback(handlers.discard)

        server = await asyncio.start_server(connected, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        actual_api = self.api_module.LiveKitAPI

        def build(url, key, secret, *, session, failover):
            self.assertEqual(url, self.settings.url)
            self.assertIs(failover, False)
            self.assertEqual(session.timeout.total, 4)
            return actual_api(
                f"http://127.0.0.1:{port}", key, secret, session=session, failover=False
            )

        owner = self.owner(timeout_s=1)
        try:
            with (
                patch.object(self.api_module, "LiveKitAPI", side_effect=build),
                patch.object(admin_module, "NETWORK_SECONDS", 0.05),
            ):
                request = asyncio.create_task(owner.inspect(self.identity))
                await asyncio.wait_for(entered.wait(), 1)
                with self.assertRaises(NativeRoomError) as caught:
                    await request
            self.assertEqual(str(caught.exception), "unavailable")
            self.assertEqual(owner.pending_count, 0)
            await owner.close()
        finally:
            release.set()
            server.close()
            await server.wait_closed()
            if handlers:
                await asyncio.gather(*tuple(handlers))

    async def test_finite_bounds_and_expired_mint_reject_before_io(self) -> None:
        for budget in (True, 0, 5, 10**1000, -(10**1000), float("nan")):
            with (
                self.subTest(budget_type=type(budget).__name__),
                self.assertRaises(NativeRoomError),
            ):
                admin_module.LiveKitRoomAdmin(self.settings, timeout_s=budget)
        owner = self.owner()
        with self.assertRaises(NativeRoomError) as caught:
            owner.mint(
                room="room_a",
                identity="browser_a",
                role="browser",
                expires_at="2020-01-01T00:00:00.000Z",
            )
        self.assertEqual(str(caught.exception), "closed")
        self.assertIsNone(owner._session)


if __name__ == "__main__":
    unittest.main()
