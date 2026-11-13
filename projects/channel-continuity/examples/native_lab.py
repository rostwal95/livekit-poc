"""Explicit single-session local native composition. No listeners start on import."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import signal
import sys
import traceback
import wave
from array import array
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal, cast

from livekit import rtc

from channel_continuity.codec import AccountScope, ProviderScope
from channel_continuity.native import (
    NativeBinding,
    NativeCredential,
    NativeEndpoint,
    NativeError,
    NativeHttpIntake,
    NativeRuntime,
)
from channel_continuity.native_communication import (
    BrowserObservation,
    NativeCommunicationHttpClient,
    ObservationReceipt,
    ResponseAnchor,
    ResponseReceipt,
    ResponseView,
    SdkObservation,
)
from channel_continuity.native_models import CODES, decode, fields, uuid

STAGES = frozenset(
    (
        "initializing",
        "configuration",
        "http_binding",
        "waiting_node",
        "waiting_participant",
        "rtc_connect",
        "sdk_start",
        "ready",
        "cleanup",
        "finished",
    )
)
_STAGE = "initializing"


def stage(value: str) -> None:
    global _STAGE
    if value not in STAGES:
        raise NativeError()
    _STAGE = value


def failure_context(error: BaseException) -> dict[str, object]:
    code = (
        error.code
        if type(error) is NativeError and type(error.code) is str and error.code in CODES
        else None
    )
    kind = (
        "NativeError"
        if type(error) is NativeError
        else "TimeoutError"
        if isinstance(error, TimeoutError)
        else "OSError"
        if isinstance(error, OSError)
        else "RuntimeError"
        if type(error) is RuntimeError
        else "DependencyError"
    )
    allowed = {
        "native_lab.py",
        "native_capture.py",
        "native_communication.py",
        "native_scripted.py",
        "native.py",
        "native_http.py",
        "native_models.py",
        "native_rehydration.py",
    }
    frames = [
        {"file": Path(frame.filename).name, "line": frame.lineno}
        for frame in traceback.extract_tb(error.__traceback__)
        if Path(frame.filename).name in allowed
    ][-4:]
    return {
        "schemaVersion": 1,
        "status": "failed",
        "mode": "serve",
        "stage": _STAGE,
        "errorType": kind,
        "code": code,
        "frames": frames,
    }


async def wait_for_bound_participant(
    room: rtc.Room, identity: str, *, timeout: float = 60
) -> float:
    """Trusted RTC identity precondition, separate from the SDK readiness budget."""
    if type(timeout) not in (int, float) or not 0.02 <= timeout <= 60:
        raise NativeError()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    available: asyncio.Future[float] = loop.create_future()

    def seen(participant: rtc.RemoteParticipant) -> None:
        if participant.identity == identity and not available.done():
            available.set_result(loop.time())

    room.on("participant_connected", seen)
    try:
        for participant in tuple(room.remote_participants.values()):
            seen(participant)
        async with asyncio.timeout(timeout):
            observed = await available
        if loop.time() >= deadline:
            raise TimeoutError()
        return observed
    finally:
        room.off("participant_connected", seen)


class LabHttp:
    """Application-owned bounded HTTP/1.1; close owns real writers and handlers."""

    ALLOWED_PATHS = frozenset(("/p2/session", "/v1/native/prepare", "/p2/response"))
    LARGE_RESPONSE_PATHS = frozenset(("/p2/response",))

    def __init__(
        self,
        handler: Callable[[str, dict[str, str], bytes], Awaitable[tuple[int, dict[str, object]]]],
    ) -> None:
        self.handler = handler
        self.server: asyncio.Server | None = None
        self.writers: set[asyncio.StreamWriter] = set()
        self.tasks: set[asyncio.Task[None]] = set()
        self.active = 0
        self.closing = False
        self.cleanup_seconds = 5.0
        self._close_task: asyncio.Task[None] | None = None

    async def start(self) -> int:
        self.server = await asyncio.start_server(
            self.connected, "127.0.0.1", 0, limit=4096, backlog=16
        )
        return int(self.server.sockets[0].getsockname()[1])

    def connected(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self.closing or len(self.writers) >= 16:
            # Server owns transport closure; no application task/read buffer is created.
            writer.transport.abort()
            return
        self.writers.add(writer)
        task = asyncio.create_task(self.handle(reader, writer), name="native-application-http")
        self.tasks.add(task)

        def settled(done: asyncio.Task[None]) -> None:
            self.tasks.discard(done)
            if not done.cancelled():
                done.exception()

        task.add_done_callback(settled)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        admitted = False
        status = 400
        maximum_response = 8192
        value: dict[str, object] = {"schemaVersion": 1, "status": "unavailable"}
        try:
            async with asyncio.timeout(2):
                rawhead = await reader.readuntil(b"\r\n\r\n")
                if len(rawhead) > 4096:
                    raise NativeError()
                lines = rawhead.decode("ascii").split("\r\n")
                parts = lines[0].split(" ")
                if (
                    len(parts) != 3
                    or parts[0] != "POST"
                    or parts[2] != "HTTP/1.1"
                    or parts[1] not in self.ALLOWED_PATHS
                    or len(lines) > 36
                ):
                    raise NativeError()
                if parts[1] in self.LARGE_RESPONSE_PATHS:
                    maximum_response = 65536
                headers: dict[str, str] = {}
                for line in lines[1:-2]:
                    key, v = line.split(":", 1)
                    key = key.lower()
                    if (
                        key in headers
                        or key in ("transfer-encoding", "expect")
                        or not key.isascii()
                        or not key.replace("-", "").isalnum()
                    ):
                        raise NativeError()
                    headers[key] = v.strip()
                size = headers.get("content-length", "")
                if (
                    headers.get("content-type") != "application/json"
                    or not size.isascii()
                    or not size.isdecimal()
                    or size.startswith("0")
                    or not 1 <= int(size) <= 32768
                ):
                    raise NativeError()
                raw = await reader.readexactly(int(size))
            if self.active >= 4 or self.closing:
                status = 503
            else:
                self.active += 1
                admitted = True
                status, value = await self.handler(parts[1], headers, raw)
        except (
            NativeError,
            ValueError,
            UnicodeError,
            TimeoutError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ):
            status = 400
        except Exception:  # noqa: BLE001 - Fixed payload-free external response.
            status = 503
        finally:
            try:
                body = json.dumps(
                    value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ).encode("utf-8")
                if len(body) > maximum_response:
                    raise NativeError()
                writer.write(
                    f"HTTP/1.1 {status} Result\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode(
                        "ascii"
                    )
                    + body
                )
                async with asyncio.timeout(1):
                    await writer.drain()
            except (OSError, TimeoutError, NativeError):
                pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass
                self.writers.discard(writer)
                if admitted:
                    self.active -= 1

    async def close(self) -> None:
        self.closing = True
        if self._close_task is None:
            self._close_task = asyncio.create_task(
                self._close_owned(), name="native-application-http-close"
            )
            self._close_task.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
        async with asyncio.timeout(self.cleanup_seconds):
            await asyncio.shield(self._close_task)

    async def _close_owned(self) -> None:
        if self.server is not None:
            self.server.close()
        for writer in tuple(self.writers):
            writer.close()
        if self.server is not None:
            await self.server.wait_closed()
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        # Observe task completion directly; done callbacks can still be queued in this turn.
        for task in tuple(self.tasks):
            if task.done():
                self.tasks.discard(task)
                if not task.cancelled():
                    task.exception()
        if self.tasks or self.writers or self.active:
            raise NativeError("dependency_unavailable")


class SafeConsoleHandler(logging.Handler):
    """Explicit app-only bounded SDK log sanitizer; never copy message/exception text."""

    def __init__(self) -> None:
        super().__init__()
        self.records = 0

    def emit(self, record: logging.LogRecord) -> None:
        if self.records >= 128:
            return
        self.records += 1
        value = {
            "event": "native_dependency",
            "level": "error"
            if record.levelno >= logging.ERROR
            else "warning"
            if record.levelno >= logging.WARNING
            else "info",
        }
        event = getattr(record, "native_event", None)
        code = getattr(record, "native_code", None)
        if (
            type(event) is str
            and event in ("native", "input", "ack", "generation")
            and type(code) is str
            and code
            in (
                "accepted",
                "replayed",
                "rejected",
                "unknown",
                "invalid_input",
                "acknowledgement_unknown",
                "sdk_interruption_requested",
                "started",
                "completed",
                "interrupted",
            )
        ):
            value.update(event=event, code=code)
        sys.stderr.write(json.dumps(value, separators=(",", ":")) + "\n")


def _scripted() -> object:
    spec = importlib.util.spec_from_file_location(
        "p2_native_scripted_application", Path(__file__).with_name("native_scripted.py")
    )
    if spec is None or spec.loader is None:
        raise NativeError()
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RecordedCommunication:
    """Test application proof of actual public-node publications, never an authority."""

    def __init__(self, client: NativeCommunicationHttpClient) -> None:
        self.client = client
        self.anchors: dict[str, dict[str, object]] = {}
        self.facts: dict[str, dict[str, object]] = {}

    def proof(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "source": "native_sdk_public_nodes",
            "anchors": list(self.anchors.values()),
            "sdkFacts": list(self.facts.values()),
        }

    def _record(self, payload: dict[str, object], receipt: dict[str, object], anchor: bool) -> None:
        key = cast(str, payload["responseId"] if anchor else payload["eventId"])
        row: dict[str, object] = {"status": "known", "payload": payload, "receipt": receipt}
        target = self.anchors if anchor else self.facts
        old = target.get(key)
        if old is not None:
            if old != row:
                raise NativeError("idempotency_conflict")
            return
        if anchor and len(self.anchors) >= 64:
            raise NativeError("capacity_exhausted")
        if not anchor and (
            payload["responseId"] not in self.anchors
            or sum(
                cast(dict[str, object], item["payload"])["responseId"] == payload["responseId"]
                for item in self.facts.values()
            )
            >= 8
        ):
            raise NativeError("capacity_exhausted")
        candidate = self.proof()
        candidate["anchors" if anchor else "sdkFacts"] = [*target.values(), row]
        raw = json.dumps(
            candidate, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        if len(raw) > 1048576:
            raise NativeError("capacity_exhausted")
        target[key] = row

    async def begin_response(self, value: ResponseAnchor) -> ResponseReceipt:
        payload = cast(
            dict[str, object], json.loads(json.dumps(value.payload(), ensure_ascii=False))
        )
        receipt = await self.client.begin_response(value)
        self._record(payload, receipt.payload(), True)
        return receipt

    async def observe_sdk(self, value: SdkObservation) -> ObservationReceipt:
        payload = cast(
            dict[str, object], json.loads(json.dumps(value.payload(), ensure_ascii=False))
        )
        receipt = await self.client.observe_sdk(value)
        self._record(payload, receipt.payload(), False)
        return receipt

    async def observe_browser(self, value: BrowserObservation) -> ObservationReceipt:
        return await self.client.observe_browser(value)

    async def inspect_response(self, response_id: str) -> ResponseView:
        return await self.client.inspect_response(response_id)

    async def aclose(self) -> None:
        await self.client.aclose()


def save(directory: Path, name: str, value: object) -> None:
    path = directory / name
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(
            json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n"
        )


def reached(directory: Path, name: str) -> None:
    if name not in {"python_http_ready", "python_ready"}:
        raise NativeError()
    target = directory / (name + ".reached")
    pending = directory / (name + "." + str(os.getpid()) + ".pending")
    owned = False
    try:
        descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        owned = True
        with os.fdopen(descriptor, "wb") as stream:
            stream.write((str(os.getpid()) + "\n").encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, target, follow_symlinks=False)
    finally:
        if owned:
            pending.unlink(missing_ok=True)


async def serve(directory: Path) -> dict[str, object]:
    stage("configuration")
    started = asyncio.get_running_loop().time()
    milestones: dict[str, int | None] = {
        name: None
        for name in (
            "httpBound",
            "nodeEndpointReady",
            "roomConnected",
            "participantObserved",
            "sdkStart",
            "sdkReady",
        )
    }
    startup_sequence = 0

    def observe(startup_stage: str, key: str | None = None) -> None:
        nonlocal startup_sequence
        if key is not None:
            elapsed = int((asyncio.get_running_loop().time() - started) * 1000)
            if not 0 <= elapsed <= 240000:
                raise NativeError()
            milestones[key] = elapsed
        target = directory / "native-startup-observations.json"
        if startup_sequence == 0 and target.exists():
            raise NativeError()
        if target.is_symlink():
            raise NativeError()
        startup_sequence += 1
        temporary = directory / ("native-startup-" + str(startup_sequence) + ".pending")
        with temporary.open("x", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            json.dump(
                {
                    "schemaVersion": 1,
                    "stage": startup_stage,
                    "participantWaitBudgetMs": 60000,
                    "sdkReadinessBudgetMs": 10000,
                    "expectedParticipantObserved": milestones["participantObserved"] is not None,
                    "milestonesMs": milestones,
                },
                stream,
                separators=(",", ":"),
            )
            stream.write("\n")
        os.replace(temporary, target)

    config = decode((directory / "fixture.json").read_bytes(), 8192)
    media = fields(
        decode((directory / "media.json").read_bytes(), 16384),
        {
            "url",
            "roomId",
            "participantId",
            "agentId",
            "bindingId",
            "nativeToken",
            "browserToken",
            "browserAccessToken",
        },
    )
    for key in ("roomId", "participantId", "agentId", "bindingId"):
        if type(media[key]) is not str or media[key] != config[key]:
            raise NativeError()
    for key in ("nativeToken", "browserToken", "browserAccessToken", "url"):
        if type(media[key]) is not str or not 1 <= len(cast(str, media[key])) <= 4096:
            raise NativeError()
    p = fields(config["providerScope"], {"tenantId", "provider", "providerAccountId"})
    a = fields(config["scope"], {"tenantId", "accountId"})
    binding = NativeBinding(
        cast(str, config["bindingId"]),
        ProviderScope(
            cast(str, p["tenantId"]), cast(str, p["provider"]), cast(str, p["providerAccountId"])
        ),
        AccountScope(cast(str, a["tenantId"]), cast(str, a["accountId"])),
        cast(str, config["caseId"]),
        cast(str, config["conversationId"]),
        cast(str, config["roomId"]),
        cast(str, config["participantId"]),
        cast(str, config["agentId"]),
    )
    token = NativeCredential(cast(str, config["prepareToken"]))
    communication_values: dict[str, object] | None = None
    communication_path = directory / "communication.json"
    if communication_path.exists() or communication_path.is_symlink():
        if communication_path.is_symlink():
            raise NativeError()
        communication_values = fields(
            decode(communication_path.read_bytes(), 4096),
            {"schemaVersion", "publisherToken", "sdkToken", "browserToken", "inputIds"},
        )
        if (
            type(communication_values["schemaVersion"]) is not int
            or communication_values["schemaVersion"] != 1
        ):
            raise NativeError()
        values = communication_values["inputIds"]
        if type(values) is not list or len(values) != 3 or len({uuid(v) for v in values}) != 3:
            raise NativeError()
        tokens = [
            NativeCredential(cast(str, communication_values[k])).value
            for k in ("publisherToken", "sdkToken", "browserToken")
        ]
        originals = [
            cast(str, config[k])
            for k in ("accountToken", "publisherToken", "bindingToken", "prepareToken")
        ] + [cast(str, media["browserAccessToken"])]
        if len(set(tokens + originals)) != len(tokens + originals):
            raise NativeError()

    pcm_path = Path(__file__).parent / "assets" / "native-status.wav"
    with wave.open(str(pcm_path), "rb") as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (16000, 1, 2):
            raise NativeError()
        samples = array("h", source.readframes(source.getnframes()))
        # Explicit local fixture playback at twice source rate; no live synthesis is claimed.
        pcm = samples[::2].tobytes()
    scripted = cast(Any, _scripted())
    model, recognizer, voice = (
        scripted.ScriptedModel(),
        scripted.ScriptedRecognizer(),
        scripted.ScriptedVoice(pcm, pace=False),
    )
    stop = asyncio.Event()
    runtime: NativeRuntime | None = None
    intake: NativeHttpIntake | None = None
    communication_client: NativeCommunicationHttpClient | None = None
    recorded_communication: RecordedCommunication | None = None
    room = rtc.Room()
    http_closed = False
    room_closed = False

    async def handler(
        path: str, headers: dict[str, str], raw: bytes
    ) -> tuple[int, dict[str, object]]:
        response: dict[str, object]
        expected = (
            media["browserAccessToken"] if path in ("/p2/session", "/p2/response") else token.value
        )
        if headers.get("authorization") != "Bearer " + cast(str, expected):
            return 401, {"schemaVersion": 1, "status": "unavailable"}
        value = decode(raw, 2 if path == "/p2/session" else 32768)
        if path == "/p2/session":
            fields(value, set())
            if raw != b"{}":
                raise NativeError()
            response = {
                "schemaVersion": 1,
                "url": media["url"],
                "token": media["browserToken"],
                "roomId": binding.room_id,
                "participantId": binding.participant_id,
                "agentId": binding.agent_id,
                "bindingId": binding.binding_id,
            }
        elif path == "/p2/response":
            value = fields(value, {"schemaVersion", "responseId"})
            if (
                type(value["schemaVersion"]) is not int
                or value["schemaVersion"] != 1
                or runtime is None
                or communication_client is None
            ):
                raise NativeError()
            view = await runtime.communication_view(uuid(value["responseId"]))
            response = {"schemaVersion": 1, "status": "known", "result": view.payload()}
        else:
            fields(value, {"schemaVersion", "kind", "context"})
            if (
                type(value["schemaVersion"]) is not int
                or value["schemaVersion"] != 1
                or value["kind"] != "agent.prepare"
                or runtime is None
            ):
                raise NativeError()
            decision = await runtime.prepare(value["context"])
            response = {
                "schemaVersion": 1,
                "kind": "agent.prepared",
                "inputDigest": hashlib.sha256(raw).hexdigest(),
                "decision": decision,
            }
        return 200, response

    http = LabHttp(handler)

    async def startup() -> None:
        nonlocal runtime, intake, communication_client, recorded_communication
        stage("http_binding")
        port = await http.start()
        save(directory, "python-endpoint.json", {"host": "127.0.0.1", "port": port})
        observe("http_bound", "httpBound")
        reached(directory, "python_http_ready")
        stage("waiting_node")
        observe("waiting_node")
        deadline = asyncio.get_running_loop().time() + 25
        while not (directory / "node-endpoint.json").exists():
            if asyncio.get_running_loop().time() >= deadline:
                raise NativeError("dependency_unavailable")
            await asyncio.sleep(0.02)
        endpoint = fields(
            decode((directory / "node-endpoint.json").read_bytes(), 256), {"host", "port"}
        )
        observe("waiting_node", "nodeEndpointReady")
        intake = NativeHttpIntake(
            NativeEndpoint(
                cast(Literal["127.0.0.1"], endpoint["host"]), cast(int, endpoint["port"])
            ),
            NativeCredential(cast(str, config["bindingToken"])),
            binding,
        )
        if communication_values is not None:
            communication_client = NativeCommunicationHttpClient(
                NativeEndpoint(
                    cast(Literal["127.0.0.1"], endpoint["host"]), cast(int, endpoint["port"])
                ),
                NativeCredential(cast(str, communication_values["publisherToken"])),
                NativeCredential(cast(str, communication_values["sdkToken"])),
                NativeCredential(cast(str, communication_values["browserToken"])),
                NativeCredential(cast(str, config["accountToken"])),
                binding,
            )
            recorded_communication = RecordedCommunication(communication_client)
        stage("rtc_connect")
        await room.connect(cast(str, media["url"]), cast(str, media["nativeToken"]))
        observe("room_connected", "roomConnected")
        stage("waiting_participant")
        observe("waiting_participant")
        await wait_for_bound_participant(room, binding.participant_id)
        observe("waiting_participant", "participantObserved")
        runtime = NativeRuntime(
            binding,
            intake,
            stt=recognizer,
            llm=model,
            tts=voice,
            communication=recorded_communication,
        )
        stage("sdk_start")
        observe("sdk_starting", "sdkStart")
        async with asyncio.timeout(10):
            await runtime.start(room)
        observe("ready", "sdkReady")
        stage("ready")
        reached(directory, "python_ready")

    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(name, stop.set)
    launching = asyncio.create_task(startup(), name="native-application-startup")
    stopping = asyncio.create_task(stop.wait(), name="native-application-stop")
    primary: BaseException | None = None
    failed_stage: str | None = None
    try:
        completed, _ = await asyncio.wait(
            (launching, stopping), return_when=asyncio.FIRST_COMPLETED
        )
        if launching in completed:
            await launching
            await stopping
        else:
            raise NativeError("closed")
    except BaseException as error:  # noqa: BLE001 - Preserve primary failure and close every owner.
        primary = error
        failed_stage = _STAGE
    finally:
        for task in (launching, stopping):
            if not task.done():
                task.cancel()
        await asyncio.gather(launching, stopping, return_exceptions=True)
        stage("cleanup")
        actions = [http.close]
        if runtime is not None:
            actions.append(runtime.aclose)
        if intake is not None:
            actions.append(intake.aclose)
        if communication_client is not None:
            actions.append(communication_client.aclose)
        actions.extend((room.disconnect, model.aclose, recognizer.aclose, voice.aclose))
        for action in actions:
            try:
                await action()
            except BaseException as error:  # noqa: BLE001 - Preserve primary failure and close every owner.
                if primary is None:
                    primary = error
        http_closed = (
            not http.tasks
            and not http.writers
            and http.active == 0
            and http._close_task is not None
            and http._close_task.done()
            and not http._close_task.cancelled()
            and http._close_task.exception() is None
        )
        room_closed = not room.isconnected()
    if primary is not None:
        stage(failed_stage or "cleanup")
        raise primary
    if runtime is None:
        raise NativeError()
    stage("finished")
    report = {
        "schemaVersion": 1,
        "status": "passed",
        "mode": "serve",
        "cleanupComplete": http_closed,
        "metrics": runtime.metrics(),
        "sdkClosed": runtime.sdk_closed,
        "roomClosed": room_closed,
        "httpClosed": http_closed,
    }
    if communication_client is not None:
        report["communicationMetrics"] = runtime.communication_metrics()
        if recorded_communication is None:
            raise NativeError()
        save(directory, "communication-python-source-proof.json", recorded_communication.proof())
    save(directory, "python-terminal.json", report)
    save(
        directory,
        "python-private-proof.json",
        {
            "modelCalls": model.calls,
            "sttFrames": recognizer.frames,
            "sttAudioSeconds": recognizer.audio_seconds,
            "ttsFrames": voice.frames_emitted,
            "ttsSourceRateMultiplier": 2,
        },
    )
    return report


def main() -> int:
    logging.basicConfig(level=logging.INFO, handlers=[SafeConsoleHandler()], force=True)
    try:
        if len(sys.argv) != 2:
            raise NativeError()
        directory = Path(sys.argv[1])
        if not directory.is_absolute() or not directory.is_dir() or directory.is_symlink():
            raise NativeError()
        result = asyncio.run(serve(directory))
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except Exception as error:  # noqa: BLE001 - Fixed payload-free terminal failure.
        try:
            if (
                "directory" in locals()
                and directory.is_absolute()
                and directory.is_dir()
                and not directory.is_symlink()
            ):
                save(directory, "python-failure-context.json", failure_context(error))
        except OSError:
            pass
        print(
            '{"schemaVersion":1,"status":"failed","mode":"serve","cleanupComplete":false}',
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
