"""One physical Parent activation using explicit fake public resource ports."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from channel_continuity.codec import AccountScope, ProviderScope
from services.channel_policy_demo import native_room as room
from services.channel_policy_demo.current_result import CurrentResultObservation
from services.channel_policy_demo.current_result_http import CurrentResultEndpoint
from services.channel_policy_demo.discovery import DiscoveryScope
from services.channel_policy_demo.native_room_admin import LiveKitAdminSettings, RoomPresence
from services.channel_policy_demo.native_room_state import (
    EndCommand,
    NativeRoomError,
    NodeRoomCursor,
    RoomIdentity,
    StartCommand,
    now_utc,
)
from services.channel_policy_demo.native_worker_config import load_native_worker_config
from services.channel_policy_demo.native_worker_process import WorkerProcessStatus
from services.channel_policy_demo.room_control import (
    RoomAttachmentObservation,
    RoomObservation,
    RoomPublication,
    RoomPublisherCredential,
    RoomRevocation,
)


def uid(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012d}"


class Reader:
    def __init__(self):
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def read(self):
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        return CurrentResultObservation(
            uid(4),
            DiscoveryScope("tenant_a", "account_a"),
            "case_a",
            "conversation_a",
            now_utc(),
            "no_delivery",
            None,
        )


class Application:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.attached = False
        self.close_entered = asyncio.Event()
        self.close_release = asyncio.Event()
        self.close_release.set()
        self.global_closed = 0
        self.readers = []

    def attach_current_result(self, view):
        if self.attached:
            raise AssertionError("another room attachment is live")
        self.attached = True
        self.log.append("producer_attach")
        reader = Reader()
        self.readers.append(reader)
        return reader

    async def close_current_result(self) -> None:
        self.log.append("producer_close_entered")
        self.close_entered.set()
        await self.close_release.wait()
        self.attached = False
        self.log.append("producer_closed")

    async def close(self) -> None:
        self.global_closed += 1
        raise AssertionError("Room End cannot close the borrowed application")


class Admin:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.found = None
        self.created = self.deleted = self.inspected = 0
        self.closed = False
        self.create_unknown = False
        self.create_absent_unknown = False
        self.foreign = False
        self.minted: list[tuple[str, str, str, str]] = []

    @property
    def pending_count(self) -> int:
        return 0

    def mint(self, *, room: str, identity: str, role: str, expires_at: str) -> str:
        self.minted.append((room, identity, role, expires_at))
        return "YQ.Yg.Yw" if role == "browser" else "YQ.Yg.ZA"

    async def inspect(self, identity):
        self.inspected += 1
        self.log.append("sfu_inspect")
        if self.foreign:
            return RoomPresence("foreign", now_utc())
        if self.found is None:
            return RoomPresence("absent", now_utc())
        if identity.sid is not None and identity.sid != self.found.sid:
            return RoomPresence("foreign", now_utc())
        return RoomPresence("owned", now_utc(), self.found)

    async def create(self, identity):
        self.created += 1
        self.log.append("sfu_create")
        if not self.create_absent_unknown:
            self.found = RoomIdentity(identity.name, identity.metadata, "RM_owned")
        if self.create_unknown or self.create_absent_unknown:
            raise NativeRoomError("outcome_unknown")
        return self.found

    async def delete(self, identity) -> None:
        if identity != self.found:
            raise AssertionError("wrong original SID/name/metadata")
        self.deleted += 1
        self.log.append("sfu_delete")
        self.found = None

    async def settle(self) -> None:
        return

    async def close(self) -> None:
        self.closed = True
        self.log.append("admin_closed")


class Control:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.request = None
        self.state = "ready"
        self.opens = self.attaches = self.closes = self.observes = 0
        self.closed = False
        self.close_unknown = False
        self.close_adapter_fail_once = False
        self.adapter_closes = 0

    @property
    def pending_count(self) -> int:
        return 0

    def observation(self):
        request = self.request
        assert request is not None
        command = request.command()
        publication = RoomPublication(
            request.binding.binding_id, "0" * 64, now_utc(), request.binding.expires_at
        )
        revoked = (
            RoomRevocation(request.binding.binding_id, "revoked", now_utc())
            if self.state == "closed"
            else None
        )
        return RoomObservation(
            command.node_epoch,
            command.generation,
            command.open_id,
            self.state,
            publication,
            revoked,
        )

    async def open(self, request):
        self.request = request
        self.opens += 1
        self.log.append("g_open")
        return self.observation()

    async def attach(self, request):
        self.attaches += 1
        self.log.append("g_attach")
        return RoomAttachmentObservation(
            request.node_epoch, request.generation, request.open_id, request.binding_id
        )

    async def observe(self, command, *, binding):
        self.observes += 1
        self.log.append("g_observe")
        self._original(command, binding)
        return self.observation()

    def _original(self, command, binding) -> None:
        if (
            self.request is None
            or command != self.request.command()
            or binding != self.request.binding
        ):
            raise AssertionError("another Node identity was selected")

    async def close_room(self, command, *, binding):
        self._original(command, binding)
        self.closes += 1
        self.log.append("g_close")
        self.state = "closed"
        if self.close_unknown:
            self.close_unknown = False
            raise NativeRoomError("outcome_unknown")
        return self.observation()

    async def close(self) -> None:
        self.adapter_closes += 1
        if self.close_adapter_fail_once:
            self.close_adapter_fail_once = False
            raise RuntimeError("PRIVATE_CONTROL_CLOSE")
        self.closed = True
        self.log.append("control_closed")


class View:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.closed = False

    @property
    def pending_count(self) -> int:
        return 0

    async def read(self, *, delivery_id: str):
        raise AssertionError("No current selection occurs in this lifecycle unit")

    async def close(self) -> None:
        self.closed = True
        self.log.append("view_closed")


class Host:
    def __init__(self, log: list[str], predicate) -> None:
        self.log, self.predicate = log, predicate
        self.closed = False

    @property
    def pending_count(self) -> int:
        return 0

    async def start(self, port: int = 11031):
        self.log.append("current_host_start")
        return CurrentResultEndpoint("127.0.0.1", port)

    async def close(self) -> None:
        self.assert_fenced()
        self.closed = True
        self.log.append("host_closed")

    def assert_fenced(self) -> None:
        if self.predicate():
            raise AssertionError("End did not synchronously close the room callback")


class Worker:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.started = asyncio.Event()
        self.prepare = asyncio.Event()
        self.prepare.set()
        self.exit = asyncio.Event()
        self.stop_entered = asyncio.Event()
        self.stop_release = asyncio.Event()
        self.stop_release.set()
        self.running = self.reaped = self.ready = False
        self.sdk_closed = False

    @property
    def pending_count(self) -> int:
        return int(self.running)

    def status(self):
        return WorkerProcessStatus(
            "closed"
            if self.reaped
            else "session_closed"
            if self.sdk_closed
            else "ready"
            if self.ready
            else "prepare_ready"
            if self.started.is_set()
            else "not_started",
            self.running,
            self.reaped,
            0 if self.reaped else None,
            self.started.is_set() and self.prepare.is_set(),
            self.ready and self.running and not self.sdk_closed,
            False,
            self.started.is_set(),
        )

    async def start(self) -> None:
        self.log.append("worker_start")
        self.running = True
        self.started.set()

    async def wait_prepare(self) -> None:
        await self.prepare.wait()
        self.log.append("worker_prepare_ready")

    async def wait_exit(self) -> int:
        await self.exit.wait()
        return 0

    async def wait_terminal(self) -> None:
        await self.exit.wait()

    async def stop(self) -> None:
        self.log.append("worker_stop_entered")
        self.stop_entered.set()
        await self.stop_release.wait()
        self.running = self.ready = False
        self.reaped = True
        self.exit.set()
        self.log.append("worker_reaped")


class NativeRoomOwnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name).resolve() / "rooms"
        self.log: list[str] = []
        self.app = Application(self.log)
        self.admins: list[Admin] = []
        self.controls: list[Control] = []
        self.views: list[View] = []
        self.hosts: list[Host] = []
        self.workers: list[Worker] = []
        self.next_admin = None
        self.next_worker = None

        def admin(settings):
            value = self.next_admin or Admin(self.log)
            self.next_admin = None
            value.settings = settings
            self.admins.append(value)
            return value

        def control(publisher, port):
            value = Control(self.log)
            self.controls.append(value)
            return value

        def view(cursor, command, token):
            self.assertEqual(command.node_epoch, cursor.node_epoch)
            value = View(self.log)
            self.views.append(value)
            return value

        def host(reader, predicate, token):
            value = Host(self.log, predicate)
            self.hosts.append(value)
            return value

        def worker(python, config, environment):
            self.assertTrue(config.is_file())
            self.assertEqual(set(environment), {"PATH", "LANG"})
            value = self.next_worker or Worker(self.log)
            self.next_worker = None
            self.workers.append(value)
            return value

        self.ports = room.NativeRoomPorts(admin, control, view, host, worker)
        route = room.NativeRoomRoute(
            uid(4),
            ProviderScope("tenant_a", "livekit", "provider_a"),
            AccountScope("tenant_a", "account_a"),
            "case_a",
            "conversation_a",
        )
        self.owner = room.NativeRoomOwner(
            route,
            owner_epoch=uid(1),
            app=self.app,
            admin=LiveKitAdminSettings("local_key", "test_secret_" + "x" * 43),
            publisher=RoomPublisherCredential("p" * 43),
            cursor=NodeRoomCursor(uid(5), "7", False),
            directory=self.directory,
            python_executable=Path("/trusted/.venv/bin/python"),
            base_environment={"PATH": "/usr/bin:/bin", "LANG": "C"},
            ports=self.ports,
        )

    async def asyncTearDown(self) -> None:
        self.app.close_release.set()
        for worker in self.workers:
            worker.prepare.set()
            worker.stop_release.set()
        try:
            async with asyncio.timeout(2):
                await self.owner.close()
        except NativeRoomError:
            # Specific unknown/foreign-owner controls deliberately stay blocked;
            # these fake ports own no actual process/socket/room/DB resources.
            pass
        self.assertEqual(self.app.global_closed, 0)
        self.temporary.cleanup()

    async def start(self, command: int = 2, expected: str = "0"):
        return await self.owner.start(StartCommand(uid(1), expected, uid(command)))

    async def end(self, generation: str = "1", command: int = 2):
        return await self.owner.end(EndCommand(uid(1), generation, uid(command)))

    async def test_trusted_admin_port_propagates_to_private_worker_and_browser_grant(self) -> None:
        self.owner = room.NativeRoomOwner(
            room.NativeRoomRoute(
                uid(4),
                ProviderScope("tenant_a", "livekit", "provider_a"),
                AccountScope("tenant_a", "account_a"),
                "case_a",
                "conversation_a",
            ),
            owner_epoch=uid(1),
            app=self.app,
            admin=LiveKitAdminSettings(
                "local_key", "test_secret_" + "x" * 43, "http://127.0.0.1:27880"
            ),
            publisher=RoomPublisherCredential("p" * 43),
            cursor=NodeRoomCursor(uid(5), "7", False),
            directory=self.directory,
            python_executable=Path("/trusted/.venv/bin/python"),
            base_environment={"PATH": "/usr/bin:/bin", "LANG": "C"},
            ports=self.ports,
        )
        grant = await self.start()
        configured = await asyncio.to_thread(
            load_native_worker_config, self.directory / "active" / "worker.json"
        )
        self.assertEqual(self.admins[0].settings.url, "http://127.0.0.1:27880")
        self.assertEqual(grant.url, "ws://127.0.0.1:27880")
        self.assertEqual(configured.livekit_url, grant.url)
        self.assertIs(await self.start(), grant)
        self.assertEqual(len(self.workers), 1)
        await self.end()

    async def test_original_start_returns_before_sdk_ready_and_exact_retry_reuses_grant(
        self,
    ) -> None:
        grant = await self.start()
        self.assertFalse(self.workers[0].ready)
        self.assertEqual(self.owner.status().stage, "waiting_browser")
        self.assertEqual((grant.generation, self.owner.status().node_cursor.generation), ("1", "8"))
        self.assertIs(await self.start(), grant)
        self.assertEqual(
            (self.admins[0].created, self.controls[0].opens, self.controls[0].attaches), (1, 1, 1)
        )
        self.assertEqual(len(self.admins[0].minted), 2)
        self.workers[0].ready = True
        self.assertTrue(self.owner.status().sdk_ready)
        self.assertEqual(self.owner.status().stage, "ready")
        payload = grant.payload()
        self.assertEqual(
            set(payload),
            {
                "schemaVersion",
                "ownerEpoch",
                "generation",
                "originalStartCommandId",
                "mode",
                "stage",
                "rtc",
            },
        )
        self.assertNotIn("bearer", repr(payload).lower())

    async def test_current_read_uses_exact_activation_while_waiting_browser(self) -> None:
        await self.start()
        observed = await self.owner.read_current(EndCommand(uid(1), "1", uid(2)))
        self.assertEqual(observed.state, "no_delivery")
        self.assertTrue(self.owner.is_current(EndCommand(uid(1), "1", uid(2))))
        self.assertFalse(self.owner.is_current(EndCommand(uid(1), "1", uid(9))))
        with self.assertRaises(NativeRoomError):
            self.owner.is_current(object())
        self.assertFalse(self.owner.status().sdk_ready)
        self.assertEqual(self.app.readers[0].calls, 1)
        with self.assertRaises(NativeRoomError):
            await self.owner.read_current(EndCommand(uid(1), "1", uid(9)))
        self.assertEqual(self.app.readers[0].calls, 1)

    async def test_late_current_read_a_is_denied_after_end_and_room_b(self) -> None:
        await self.start()
        reader = self.app.readers[0]
        reader.release.clear()
        reading = asyncio.create_task(self.owner.read_current(EndCommand(uid(1), "1", uid(2))))
        await reader.entered.wait()
        await self.end()
        await self.start(9, "1")
        self.assertFalse(self.owner.is_current(EndCommand(uid(1), "1", uid(2))))
        self.assertTrue(self.owner.is_current(EndCommand(uid(1), "2", uid(9))))
        reader.release.set()
        with self.assertRaises(NativeRoomError) as caught:
            await reading
        self.assertEqual(caught.exception.code, "closed")
        self.assertEqual(self.app.readers[1].calls, 0)

    async def test_observed_sdk_close_fences_status_and_current_before_monitor_runs(self) -> None:
        await self.start()
        worker = self.workers[0]
        worker.sdk_closed = True
        # Deliberately do not wake its monitor: the direct status/predicate
        # fence must already protect the event-to-monitor scheduling interval.
        self.assertEqual(self.owner.status().stage, "closing")
        self.assertFalse(self.owner.is_current(EndCommand(uid(1), "1", uid(2))))
        self.assertFalse(self.hosts[0].predicate())
        with self.assertRaises(NativeRoomError) as caught:
            await self.owner.read_current(EndCommand(uid(1), "1", uid(2)))
        self.assertEqual(caught.exception.code, "closed")
        self.assertEqual(self.app.readers[0].calls, 0)
        await self.end()

    async def test_end_drains_gateway_then_front_concurrently_then_view_sfu(self) -> None:
        await self.start()
        self.app.close_release.clear()
        self.workers[0].stop_release.clear()
        closing = asyncio.create_task(self.end())
        await self.app.close_entered.wait()
        await self.workers[0].stop_entered.wait()
        self.assertFalse(self.hosts[0].predicate())
        self.assertEqual(self.owner.status().stage, "closing")
        self.assertNotIn("view_closed", self.log)
        self.app.close_release.set()
        self.workers[0].stop_release.set()
        closed = await closing
        self.assertEqual(closed.stage, "closed")
        self.assertFalse(self.owner.is_current(EndCommand(uid(1), "1", uid(2))))
        for before, after in (
            ("g_close", "worker_stop_entered"),
            ("producer_closed", "view_closed"),
            ("worker_reaped", "view_closed"),
            ("view_closed", "sfu_delete"),
            ("sfu_delete", "admin_closed"),
        ):
            self.assertLess(self.log.index(before), self.log.index(after))
        self.assertEqual(self.owner.pending_count, 0)
        self.assertEqual(self.app.global_closed, 0)
        self.assertEqual({entry.name for entry in self.directory.iterdir()}, {"lastclosed.json"})

    async def test_last_accepted_input_reaches_original_operation_before_worker_stops(self) -> None:
        """Explicit stateful control fake; actual PostgreSQL qualification is separate."""
        await self.start()
        control, worker = self.controls[0], self.workers[0]
        entered, release = asyncio.Event(), asyncio.Event()
        original = {"receipt": uid(101), "operation": uid(102), "external": None}
        accepted = dict(original)
        real_close = control.close_room

        async def drain_then_close(command, *, binding):
            control._original(command, binding)
            self.log.append("native_input_fenced")
            entered.set()
            await release.wait()
            if worker.stop_entered.is_set():
                raise NativeRoomError("cleanup_incomplete")
            accepted["external"] = uid(103)
            self.log.append("original_operation_retained")
            return await real_close(command, binding=binding)

        control.close_room = drain_then_close
        closing = asyncio.create_task(self.end())
        try:
            async with asyncio.timeout(1):
                await entered.wait()
            self.assertEqual(self.owner.status().stage, "closing")
            self.assertFalse(self.owner.is_current(EndCommand(uid(1), "1", uid(2))))
            self.assertFalse(worker.stop_entered.is_set())
            self.assertEqual(accepted, original)
            self.assertEqual(control.state, "ready")
            self.assertFalse(closing.done())
        finally:
            release.set()
            await asyncio.gather(closing, return_exceptions=True)
        self.assertEqual((await closing).stage, "closed")
        self.assertEqual(accepted, {**original, "external": uid(103)})
        self.assertLess(
            self.log.index("original_operation_retained"), self.log.index("worker_stop_entered")
        )
        self.assertLess(self.log.index("g_close"), self.log.index("worker_stop_entered"))
        self.assertEqual(self.app.global_closed, 0)

    async def test_start_and_end_physical_cas_prevents_delayed_a_retry_from_creating_b(
        self,
    ) -> None:
        await self.start()
        closed_a = await self.end()
        with self.assertRaises(NativeRoomError) as caught:
            await self.start()
        self.assertEqual(caught.exception.code, "closed")
        with self.assertRaises(NativeRoomError):
            await self.owner.start(StartCommand(uid(1), "1", uid(2)))
        grant_b = await self.start(9, "1")
        self.assertEqual(grant_b.generation, "2")
        self.assertIs(await self.end(), closed_a)
        self.assertEqual(self.owner.status().original_start_command_id, uid(9))
        self.assertTrue(self.workers[1].running)
        await self.end("2", 9)

    async def test_changed_tuple_foreign_epoch_and_wrong_end_cannot_select_current_room(
        self,
    ) -> None:
        await self.start()
        for command in (
            StartCommand(uid(1), "1", uid(2)),
            StartCommand(uid(7), "0", uid(2)),
            StartCommand(uid(1), "0", uid(9)),
        ):
            with self.subTest(command=command):
                with self.assertRaises(NativeRoomError) as caught:
                    await self.owner.start(command)
                self.assertEqual(caught.exception.code, "conflict")
        with self.assertRaises(NativeRoomError):
            await self.owner.end(EndCommand(uid(1), "1", uid(9)))
        self.assertTrue(self.workers[0].running)
        self.assertEqual(len(self.workers), 1)

    async def test_start_reserves_before_held_setup_and_end_blocks_late_publication(self) -> None:
        import threading

        entered, release = threading.Event(), threading.Event()
        actual = room.PrivateRoomState.prepare

        def held(owner, descriptor, config):
            entered.set()
            release.wait(2)
            return actual(owner, descriptor, config)

        with patch.object(room.PrivateRoomState, "prepare", held):
            caller = asyncio.create_task(self.start())
            await asyncio.to_thread(entered.wait, 1)
            self.assertEqual(self.owner.status().generation, "1")
            closing = asyncio.create_task(self.end())
            await asyncio.sleep(0)
            self.assertEqual(self.owner.status().stage, "closing")
            with self.assertRaises(NativeRoomError):
                await self.start(9, "1")
            release.set()
            with self.assertRaises(NativeRoomError):
                await caller
            await closing
        self.assertEqual(
            (self.admins[0].created, self.admins[0].inspected, self.controls[0].opens), (0, 0, 0)
        )
        self.assertEqual(self.owner.pending_count, 0)

    async def test_cancelled_start_retains_worker_and_drains_before_next_activation(self) -> None:
        worker = Worker(self.log)
        worker.prepare.clear()
        worker.stop_release.clear()
        self.next_worker = worker
        caller = asyncio.create_task(self.start())
        await worker.started.wait()
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertEqual(self.owner.pending_count, 1)
        self.assertFalse(self.hosts[0].predicate())
        with self.assertRaises(NativeRoomError):
            await self.start(9, "1")
        worker.prepare.set()
        await worker.stop_entered.wait()
        worker.stop_release.set()
        await self.end()
        await self.start(9, "1")
        self.assertEqual(len(self.workers), 2)

    async def test_original_ready_grant_retry_does_not_reapply_expired_startup_budget(self) -> None:
        original = await self.start()
        assert self.owner._current is not None
        self.owner._current.startup_deadline = asyncio.get_running_loop().time() - 1
        self.assertIs(await self.start(), original)
        self.assertEqual(self.controls[0].opens, 1)

    async def test_unknown_create_adopts_only_same_metadata_and_deletes_original_once(self) -> None:
        admin = Admin(self.log)
        admin.create_unknown = True
        self.next_admin = admin
        with self.assertRaises(NativeRoomError) as caught:
            await self.start()
        self.assertEqual(caught.exception.code, "outcome_unknown")
        await self.end()
        self.assertEqual((admin.created, admin.deleted), (1, 1))
        self.assertEqual(self.controls[0].opens, 0)
        self.assertEqual(self.owner.pending_count, 0)

    async def test_unknown_create_plus_absence_is_not_treated_as_no_late_room(self) -> None:
        admin = Admin(self.log)
        admin.create_absent_unknown = True
        self.next_admin = admin
        with self.assertRaises(NativeRoomError):
            await self.start()
        with self.assertRaises(NativeRoomError) as caught:
            await self.end()
        self.assertEqual(caught.exception.code, "outcome_unknown")
        self.assertEqual((admin.created, admin.deleted), (1, 0))
        self.assertEqual(self.owner.pending_count, 1)
        with self.assertRaises(NativeRoomError):
            await self.start(9, "1")

    async def test_foreign_room_recreation_is_never_deleted_and_blocks_b(self) -> None:
        await self.start()
        self.admins[0].foreign = True
        with self.assertRaises(NativeRoomError):
            await self.end()
        self.assertEqual(self.admins[0].deleted, 0)
        self.assertEqual(self.owner.pending_count, 1)
        with self.assertRaises(NativeRoomError):
            await self.start(9, "1")

    async def test_unknown_g_close_reconciles_original_observation_without_mutation_retry(
        self,
    ) -> None:
        await self.start()
        self.controls[0].close_unknown = True
        self.assertEqual((await self.end()).stage, "closed")
        self.assertEqual((self.controls[0].opens, self.controls[0].closes), (1, 1))
        self.assertGreaterEqual(self.controls[0].observes, 2)
        self.assertEqual(self.owner.pending_count, 0)

    async def test_unresolved_gateway_drain_retains_worker_then_exact_end_retry_progresses(
        self,
    ) -> None:
        await self.start()
        self.owner._cleanup_budget = 0.03
        control, worker = self.controls[0], self.workers[0]
        original_close = control.close_room
        attempted = []
        unavailable = True

        async def closing(command, *, binding):
            control._original(command, binding)
            attempted.append((command, binding))
            if unavailable:
                control.state = "closing"
                raise NativeRoomError("cleanup_incomplete")
            return await original_close(command, binding=binding)

        control.close_room = closing
        with self.assertRaises(NativeRoomError) as failed:
            await self.end()
        self.assertEqual(failed.exception.code, "cleanup_incomplete")
        self.assertFalse(worker.stop_entered.is_set())
        self.assertEqual(self.owner.status().stage, "closing")
        self.assertIsNotNone(self.owner._current)
        await asyncio.gather(self.owner._current.ending, return_exceptions=True)
        unavailable = False
        self.assertEqual((await self.end()).stage, "closed")
        self.assertTrue(worker.reaped)
        self.assertGreaterEqual(len(attempted), 2)
        self.assertTrue(all(value == attempted[0] for value in attempted))
        self.assertEqual(control.opens, 1)

    async def test_unexpected_worker_exit_synchronously_fences_room_and_starts_end(self) -> None:
        await self.start()
        self.workers[0].running = False
        self.workers[0].reaped = True
        self.workers[0].exit.set()
        assert self.owner._current is not None and self.owner._current.monitor is not None
        await self.owner._current.monitor
        self.assertFalse(self.hosts[0].predicate())
        await self.end()
        self.assertEqual(self.owner.pending_count, 0)

    async def test_one_failed_final_close_does_not_prevent_other_owned_adapter_close(self) -> None:
        await self.start()
        self.controls[0].close_adapter_fail_once = True
        self.assertEqual((await self.end()).stage, "closed")
        self.assertTrue(self.admins[0].closed)
        self.assertEqual(self.owner.pending_count, 0)
        self.assertEqual(self.controls[0].adapter_closes, 2)
        self.assertEqual(
            (self.admins[0].created, self.admins[0].deleted, self.controls[0].closes), (1, 1, 1)
        )

    async def test_cancelled_end_observer_keeps_original_cleanup_reobservation(self) -> None:
        await self.start()
        assert self.owner._current is not None
        record = self.owner._current
        original = self.controls[0].close
        first, retry, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        calls = 0

        async def close():
            nonlocal calls
            calls += 1
            if calls == 1:
                first.set()
                raise NativeRoomError("cleanup_incomplete")
            retry.set()
            await release.wait()
            await original()

        self.controls[0].close = close
        observer = asyncio.create_task(self.end())
        try:
            await first.wait()
            observer.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await observer
            async with asyncio.timeout(1):
                await retry.wait()
            self.assertEqual(self.owner.status().stage, "closing")
            self.assertEqual(self.controls[0].opens, 1)
        finally:
            release.set()
        assert record.ending is not None
        await record.ending
        self.assertEqual(self.owner.status().stage, "closed")
        self.assertEqual(self.owner.pending_count, 0)
        self.assertEqual((calls, self.admins[0].deleted, self.controls[0].closes), (2, 1, 1))

    async def test_persistent_cleanup_failure_stops_automatic_retry_admission(self) -> None:
        await self.start()
        self.owner._cleanup_budget = 0.05
        original = self.controls[0].close
        calls = 0

        async def unavailable():
            nonlocal calls
            calls += 1
            raise NativeRoomError("cleanup_incomplete")

        self.controls[0].close = unavailable
        with self.assertRaisesRegex(NativeRoomError, "^cleanup_incomplete$"):
            await self.end()
        assert self.owner._current is not None
        await asyncio.gather(self.owner._current.ending, return_exceptions=True)
        self.assertGreaterEqual(calls, 2)
        observed = calls
        await asyncio.sleep(0.06)
        self.assertEqual(calls, observed)
        self.assertEqual(self.owner.status().stage, "closing")
        self.assertEqual((self.admins[0].deleted, self.controls[0].closes), (1, 1))
        self.controls[0].close = original
        self.assertEqual((await self.end()).stage, "closed")
        self.assertEqual((self.admins[0].deleted, self.controls[0].closes), (1, 1))

    async def test_expiry_fences_original_grant_and_ends_without_renewing_jwt(self) -> None:
        original = await self.start()
        assert self.owner._current is not None
        record = self.owner._current
        record.expires_monotonic = asyncio.get_running_loop().time() - 1
        self.owner._begin_end(record)
        self.assertFalse(self.hosts[0].predicate())
        with self.assertRaises(NativeRoomError):
            await self.start()
        await self.end()
        self.assertEqual(len(self.admins[0].minted), 2)
        self.assertEqual(original.expires_at, self.controls[0].request.binding.expires_at)

    async def test_task_allocation_failure_keeps_reserved_generation_and_allows_owned_close(
        self,
    ) -> None:
        with (
            patch.object(
                room.asyncio, "create_task", side_effect=RuntimeError("PRIVATE_ALLOCATION")
            ),
            self.assertRaises(NativeRoomError) as caught,
        ):
            await self.start()
        self.assertEqual(str(caught.exception), "unavailable")
        self.assertEqual((self.owner.status().generation, self.owner.pending_count), ("1", 1))
        await self.end()
        self.assertEqual(self.owner.pending_count, 0)
        self.assertEqual(len(self.admins), 0)
        await self.start(9, "1")

    async def test_old_descriptor_fail_closed_and_is_not_reset_on_new_parent_start(self) -> None:
        self.directory.mkdir(mode=0o700)
        (self.directory / "active").mkdir(mode=0o700)
        stale = self.directory / "active" / "descriptor.json"
        stale.write_bytes(b"PRIVATE_PRIOR_OWNER")
        stale.chmod(0o600)
        with self.assertRaises(NativeRoomError) as caught:
            await self.start()
        self.assertEqual(caught.exception.code, "recovery_required")
        with self.assertRaises(NativeRoomError):
            await self.end()
        self.assertEqual(self.owner.status().stage, "recovery_required")
        self.assertEqual(stale.read_bytes(), b"PRIVATE_PRIOR_OWNER")
        self.assertEqual(self.admins[0].created, 0)
        with self.assertRaises(NativeRoomError):
            await self.start(9, "1")

    async def test_queued_start_cancel_has_no_reservation_or_new_effect(self) -> None:
        async def cancelled() -> None:
            task = asyncio.current_task()
            assert task is not None
            task.cancel()
            await self.start()

        with self.assertRaises(asyncio.CancelledError):
            await asyncio.create_task(cancelled())
        self.assertEqual((self.owner.status().generation, self.owner.pending_count), ("0", 0))
        self.assertEqual(len(self.admins), 0)
        await self.start()


if __name__ == "__main__":
    unittest.main()
