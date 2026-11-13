"""Opt-in two-room local continuity composition; no listeners start on import.

The application owns RTC/HTTP/SDK instances. P2 remains the durable input owner.
A room's retirement precedes the next room; a read refresh never generates work.
The fixed SMS handshake only asks the parent fixture to handle one original input.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib.util
import json
import logging
import os
import re
import signal
import stat
import sys
import wave
from array import array
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit
from uuid import uuid4

from livekit import rtc
from livekit.agents import llm
from livekit.agents.types import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectOptions,
    NotGivenOr,
)

from channel_continuity.codec import AccountScope, ProviderScope
from channel_continuity.native import (
    NativeBinding,
    NativeCredential,
    NativeEndpoint,
    NativeError,
    NativeHttpIntake,
    NativeRuntime,
)
from channel_continuity.native_communication import NativeCommunicationHttpClient, ResponseView
from channel_continuity.native_models import CODES, decode, fields, identifier, uuid
from channel_continuity.native_rehydration import (
    NativeContextHttpClient,
    NativeRehydrationProfile,
    RehydrationContext,
    RehydrationQuery,
)

STAGES = frozenset(
    (
        "http_binding",
        "waiting_node",
        "rtc_connect",
        "waiting_participant",
        "sdk_start",
        "ready",
        "serving",
        "cleanup",
        "closed",
    )
)


def failure_context(error: BaseException, stage: str, cleanup_complete: bool) -> dict[str, object]:
    """Only finite application facts survive a failed run; never exception text."""
    return {
        "schemaVersion": 1,
        "status": "failed",
        "mode": "rehydration-serve",
        "stage": stage if stage in STAGES else "serving",
        "errorType": "NativeError"
        if type(error) is NativeError
        else "TimeoutError"
        if isinstance(error, TimeoutError)
        else "OSError"
        if isinstance(error, OSError)
        else "CancelledError"
        if isinstance(error, asyncio.CancelledError)
        else "DependencyError",
        "code": error.code if type(error) is NativeError and error.code in CODES else None,
        "cleanupComplete": cleanup_complete,
    }


def _helpers() -> Any:
    name = "p2_rehydration_native_application_helpers"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("native_lab.py"))
    if spec is None or spec.loader is None:
        raise NativeError()
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def private_read(path: Path, maximum: int) -> bytes:
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_uid != os.geteuid()
        or before.st_nlink != 1
        or not 1 <= before.st_size <= maximum
    ):
        raise NativeError()
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        current = os.fstat(stream.fileno())
        if (
            (before.st_dev, before.st_ino, before.st_size)
            != (current.st_dev, current.st_ino, current.st_size)
            or not stat.S_ISREG(current.st_mode)
            or stat.S_IMODE(current.st_mode) != 0o600
            or current.st_uid != os.geteuid()
            or current.st_nlink != 1
        ):
            raise NativeError()
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    if (
        len(raw) != before.st_size
        or len(raw) > maximum
        or (after.st_dev, after.st_ino, after.st_size)
        != (before.st_dev, before.st_ino, before.st_size)
        or stat.S_IMODE(after.st_mode) != 0o600
        or after.st_uid != os.geteuid()
        or after.st_nlink != 1
    ):
        raise NativeError()
    return raw


def marker(directory: Path, name: str) -> None:
    if name not in {
        "python_http_ready",
        "python_a_ready",
        "python_a_closed",
        "python_b_ready",
        "sms_requested",
    }:
        raise NativeError()
    target = directory / (name + ".reached")
    temporary = directory / (name + "." + uuid4().hex + ".pending")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write((str(os.getpid()) + "\n").encode("ascii"))
        os.link(temporary, target, follow_symlinks=False)
    finally:
        temporary.unlink(missing_ok=True)


def _text(value: object, maximum: int = 4096) -> str:
    if (
        type(value) is not str
        or not 1 <= len(value.encode("utf-8")) <= maximum
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise NativeError()
    return value


@dataclass(frozen=True, slots=True)
class SessionConfig:
    label: Literal["A", "B"]
    binding: NativeBinding
    native_token: str = field(repr=False)
    browser_token: str = field(repr=False)
    binding_token: NativeCredential = field(repr=False)


@dataclass(frozen=True, slots=True)
class Configuration:
    url: str
    owner: str
    operator: NativeCredential = field(repr=False)
    prepare: NativeCredential = field(repr=False)
    account: NativeCredential = field(repr=False)
    communication: tuple[NativeCredential, NativeCredential, NativeCredential] = field(repr=False)
    sessions: Mapping[str, SessionConfig]
    sms_event_id: str

    @classmethod
    def parse(cls, fixture: object, media: object) -> Configuration:
        f = fields(
            fixture,
            {
                "schemaVersion",
                "providerScope",
                "scope",
                "caseId",
                "conversationId",
                "accountToken",
                "publisherToken",
                "prepareToken",
                "expiresAt",
                "bindings",
                "ids",
                "communication",
                "sms",
                "referenceRequest",
            },
        )
        m = fields(media, {"schemaVersion", "url", "browserAccessToken", "owner", "bindings"})
        if (
            type(f["schemaVersion"]) is not int
            or f["schemaVersion"] != 1
            or type(m["schemaVersion"]) is not int
            or m["schemaVersion"] != 1
        ):
            raise NativeError()
        if (
            type(m["owner"]) is not str
            or re.fullmatch("[a-f0-9]{32}", m["owner"], re.ASCII) is None
        ):
            raise NativeError()
        address = urlsplit(_text(m["url"]))
        if (
            address.scheme != "ws"
            or address.hostname != "127.0.0.1"
            or address.port is None
            or not 1 <= address.port <= 65535
            or address.username is not None
            or address.password is not None
            or address.path not in ("", "/")
            or address.query
            or address.fragment
        ):
            raise NativeError()
        provider = fields(f["providerScope"], {"tenantId", "provider", "providerAccountId"})
        account = fields(f["scope"], {"tenantId", "accountId"})
        p = ProviderScope(
            identifier(provider["tenantId"]),
            identifier(provider["provider"]),
            identifier(provider["providerAccountId"]),
        )
        a = AccountScope(identifier(account["tenantId"]), identifier(account["accountId"]))
        if p.tenant_id != a.tenant_id or p.provider != "livekit":
            raise NativeError()
        rows, credentials = fields(f["bindings"], {"A", "B"}), fields(m["bindings"], {"A", "B"})
        sessions = {}
        tokens = [
            NativeCredential(cast(str, f["publisherToken"])),
            NativeCredential(cast(str, f["prepareToken"])),
            NativeCredential(cast(str, f["accountToken"])),
            NativeCredential(cast(str, m["browserAccessToken"])),
        ]
        for label in ("A", "B"):
            b = fields(
                rows[label], {"bindingId", "roomId", "participantId", "agentId", "bindingToken"}
            )
            t = fields(credentials[label], {"nativeToken", "browserToken"})
            grant = NativeCredential(cast(str, b["bindingToken"]))
            tokens.append(grant)
            binding = NativeBinding(
                uuid(b["bindingId"]),
                p,
                a,
                identifier(f["caseId"]),
                identifier(f["conversationId"]),
                identifier(b["roomId"]),
                identifier(b["participantId"]),
                identifier(b["agentId"]),
            )
            sessions[label] = SessionConfig(
                label, binding, _text(t["nativeToken"]), _text(t["browserToken"]), grant
            )
        if any(
            getattr(sessions["A"].binding, key) == getattr(sessions["B"].binding, key)
            for key in ("binding_id", "room_id", "participant_id", "agent_id")
        ):
            raise NativeError()
        c = fields(f["communication"], {"publisherToken", "sdkToken", "browserToken"})
        communication = tuple(
            NativeCredential(cast(str, c[key]))
            for key in ("publisherToken", "sdkToken", "browserToken")
        )
        tokens.extend(communication)
        if len({token.value for token in tokens}) != len(tokens):
            raise NativeError()
        ids = fields(f["ids"], {"voice", "text", "sms", "newText"})
        if len({uuid(value) for value in ids.values()}) != 4:
            raise NativeError()
        return cls(
            cast(str, m["url"]),
            m["owner"],
            tokens[3],
            tokens[1],
            tokens[2],
            cast(tuple[NativeCredential, NativeCredential, NativeCredential], communication),
            MappingProxyType(sessions),
            uuid(ids["sms"]),
        )


class ContextModel(llm.LLM[Any]):
    """Observe public context at actual model entry, then delegate scripted inference."""

    def __init__(
        self, delegate: llm.LLM[Any], loaded: Callable[[], RehydrationContext | None]
    ) -> None:
        super().__init__()
        self.delegate, self.loaded = delegate, loaded
        self.observations: list[dict[str, object]] = []

    @property
    def model(self) -> str:
        return "rehydration-scripted-context-v1"

    @property
    def provider(self) -> str:
        return "local-fixture"

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool] | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[llm.ToolChoice] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
    ) -> llm.LLMStream:
        loaded = self.loaded()
        if loaded is None or len(self.observations) >= 8 or len(chat_ctx.items) > 32:
            raise NativeError()
        payload = loaded.payload()
        expected = "p2.context.case." + loaded.context_id
        found = []
        history = {
            "p2.history." + cast(str, cast(dict[str, object], raw["receipt"])["receiptId"]): cast(
                str, cast(dict[str, object], raw["event"])["body"]
            )
            for raw in cast(
                list[dict[str, object]], cast(dict[str, object], payload["history"])["messages"]
            )
        }
        matched = set()
        for item in chat_ctx.items:
            if not isinstance(item, llm.ChatMessage):
                continue
            if item.id.startswith("p2.context.case.") and item.id != expected:
                raise NativeError()
            if item.id.startswith("p2.history.") and item.id not in history:
                raise NativeError()
            if item.id == expected and item.role == "system":
                text = "".join(part for part in item.content if type(part) is str)
                if (
                    " CURRENT_CASE=" not in text
                    or json.loads(text.split(" CURRENT_CASE=", 1)[1]) != payload["case"]
                ):
                    raise NativeError()
                found.append(item.id)
            if item.id in history:
                if item.id in matched or item.role != "user" or item.content != [history[item.id]]:
                    raise NativeError()
                matched.add(item.id)
        if len(found) != 1 or matched != set(history):
            raise NativeError()
        case = cast(dict[str, object], payload["case"])
        self.observations.append(
            {
                "contextId": loaded.context_id,
                "caseId": case["caseId"],
                "revision": case["revision"],
                "sourceRevision": case["sourceRevision"],
                "historyReceiptIds": sorted(key.removeprefix("p2.history.") for key in matched),
            }
        )
        return self.delegate.chat(
            chat_ctx=chat_ctx,
            tools=tools,
            conn_options=conn_options,
            parallel_tool_calls=parallel_tool_calls,
            tool_choice=tool_choice,
            extra_kwargs=extra_kwargs,
        )

    async def aclose(self) -> None:
        await self.delegate.aclose()


class SessionPort(Protocol):
    closed: bool
    config: SessionConfig
    left: asyncio.Event
    ready: asyncio.Event

    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def prepare(self, context: object) -> dict[str, object]: ...
    async def refresh(self, query: RehydrationQuery) -> RehydrationContext: ...
    async def response(self, response_id: str) -> ResponseView: ...
    def proof(self) -> dict[str, object]: ...


async def wait_file(
    directory: Path, name: str, maximum: int, stop: asyncio.Event, *, seconds: float = 25
) -> bytes:
    deadline = asyncio.get_running_loop().time() + seconds
    path = directory / name
    while not path.exists() and not path.is_symlink():
        if stop.is_set() or asyncio.get_running_loop().time() >= deadline:
            raise NativeError("closed" if stop.is_set() else "dependency_unavailable")
        await asyncio.sleep(0.01)
    return private_read(path, maximum)


class NativeSession:
    def __init__(
        self, config: SessionConfig, shared: Configuration, directory: Path, stop: asyncio.Event
    ) -> None:
        self.config, self.shared, self.directory, self.stop = config, shared, directory, stop
        self.ready, self.left = asyncio.Event(), asyncio.Event()
        self.room = rtc.Room()
        self.runtime: NativeRuntime | None = None
        self.intake: NativeHttpIntake | None = None
        self.context: NativeContextHttpClient | None = None
        self.communication: NativeCommunicationHttpClient | None = None
        self.recorded: Any = None
        self.recognizer: Any = None
        self.voice: Any = None
        self.model: ContextModel | None = None
        self.delegate: Any = None
        self.closed = False
        self.stage = "waiting_node"
        self._starting: asyncio.Task[None] | None = None
        self._closing: asyncio.Task[None] | None = None
        self.room.on("participant_disconnected", self._left)

    def _left(self, participant: rtc.RemoteParticipant) -> None:
        if self.ready.is_set() and participant.identity == self.config.binding.participant_id:
            self.left.set()

    async def start(self) -> None:
        if self.closed or self._closing is not None:
            raise NativeError("closed")
        if self._starting is None:
            self._starting = asyncio.create_task(self._start(), name="rehydration-session-start")
            self._starting.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
        await asyncio.shield(self._starting)

    async def _start(self) -> None:
        helpers = _helpers()
        gateway = fields(
            decode(await wait_file(self.directory, "node-endpoint.json", 256, self.stop), 256),
            {"host", "port"},
        )
        read = fields(
            decode(
                await wait_file(self.directory, "rehydration-endpoint.json", 256, self.stop), 256
            ),
            {"host", "port"},
        )
        endpoint, read_endpoint = (
            NativeEndpoint(cast(Literal["127.0.0.1"], gateway["host"]), cast(int, gateway["port"])),
            NativeEndpoint(cast(Literal["127.0.0.1"], read["host"]), cast(int, read["port"])),
        )
        self.intake = NativeHttpIntake(endpoint, self.config.binding_token, self.config.binding)
        self.context = NativeContextHttpClient(
            read_endpoint, self.config.binding_token, self.config.binding
        )
        self.communication = NativeCommunicationHttpClient(
            endpoint, *self.shared.communication, self.shared.account, self.config.binding
        )
        self.recorded = helpers.RecordedCommunication(self.communication)
        with wave.open(str(Path(__file__).parent / "assets/native-status.wav"), "rb") as source:
            if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (
                16000,
                1,
                2,
            ):
                raise NativeError()
            pcm = array("h", source.readframes(source.getnframes()))[::2].tobytes()
        scripted = helpers._scripted()
        self.delegate, self.recognizer, self.voice = (
            scripted.ScriptedModel(),
            scripted.ScriptedRecognizer(),
            scripted.ScriptedVoice(pcm, pace=False),
        )
        self.model = ContextModel(
            self.delegate, lambda: None if self.runtime is None else self.runtime.loaded_context
        )
        self.runtime = NativeRuntime(
            self.config.binding,
            self.intake,
            stt=self.recognizer,
            llm=self.model,
            tts=self.voice,
            communication=self.recorded,
            rehydration=NativeRehydrationProfile(self.context),
        )
        self.stage = "rtc_connect"
        await self.room.connect(self.shared.url, self.config.native_token)
        self.stage = "waiting_participant"
        await helpers.wait_for_bound_participant(self.room, self.config.binding.participant_id)
        self.stage = "sdk_start"
        async with asyncio.timeout(10):
            await self.runtime.start(self.room)
        if self.stop.is_set() or self._closing is not None:
            raise NativeError("closed")
        self.stage = "ready"
        self.ready.set()
        marker(self.directory, "python_" + self.config.label.lower() + "_ready")

    def _runtime(self) -> NativeRuntime:
        if (
            self.closed
            or self._closing is not None
            or not self.ready.is_set()
            or self.runtime is None
        ):
            raise NativeError("closed")
        return self.runtime

    async def prepare(self, context: object) -> dict[str, object]:
        return await self._runtime().prepare(context)

    async def refresh(self, query: RehydrationQuery) -> RehydrationContext:
        return await self._runtime().refresh_context(query)

    async def response(self, response_id: str) -> ResponseView:
        return await self._runtime().communication_view(response_id)

    def proof(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "label": self.config.label,
            "bindingId": self.config.binding.binding_id,
            "cleanupComplete": self.closed,
            "sdkClosed": self.runtime.sdk_closed if self.runtime is not None else False,
            "roomClosed": not self.room.isconnected(),
            "metrics": self.runtime.metrics() if self.runtime is not None else {},
            "communicationMetrics": self.runtime.communication_metrics()
            if self.runtime is not None
            else {},
            "rehydrationMetrics": self.runtime.rehydration_metrics()
            if self.runtime is not None
            else {},
            "contextClientMetrics": self.context.metrics() if self.context is not None else {},
            "modelCalls": self.delegate.calls if self.delegate is not None else 0,
            "modelContexts": json.loads(json.dumps(self.model.observations))
            if self.model is not None
            else [],
            "sttFrames": self.recognizer.frames if self.recognizer is not None else 0,
            "sttAudioSeconds": self.recognizer.audio_seconds if self.recognizer is not None else 0,
            "ttsFrames": self.voice.frames_emitted if self.voice is not None else 0,
            "ttsSourceRateMultiplier": 2,
        }

    async def close(self) -> None:
        if (
            self._closing is not None
            and self._closing.done()
            and (self._closing.cancelled() or self._closing.exception() is not None)
        ):
            self._closing = None
        if self._closing is None:

            async def actual() -> None:
                primary: BaseException | None = None
                # A cancelled observer cannot let late startup create owners behind cleanup.
                if self._starting is not None and not self._starting.done():
                    self._starting.cancel()
                    # Original startup failure remains owned by the launching observer.
                    await asyncio.gather(self._starting, return_exceptions=True)
                self.stage = "cleanup"
                actions: list[Callable[[], Awaitable[object]]] = []
                for owner, method in (
                    (self.runtime, "aclose"),
                    (self.intake, "aclose"),
                    (self.context, "aclose"),
                    (self.communication, "aclose"),
                    (self.room, "disconnect"),
                    (self.model, "aclose"),
                    (self.recognizer, "aclose"),
                    (self.voice, "aclose"),
                ):
                    if owner is not None:
                        actions.append(
                            cast(Callable[[], Awaitable[object]], getattr(owner, method))
                        )
                for action in actions:
                    try:
                        await action()
                    except BaseException as error:  # noqa: BLE001 - Preserve primary cancellation and attempt every owner.
                        primary = primary or error
                if primary is not None:
                    raise primary
                if (
                    self.room.isconnected()
                    or self.runtime is not None
                    and not self.runtime.sdk_closed
                ):
                    raise NativeError("dependency_unavailable")
                self.closed = True
                self.stage = "closed"
                self.room.off("participant_disconnected", self._left)

            self._closing = asyncio.create_task(actual(), name="rehydration-session-close")
            self._closing.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
        async with asyncio.timeout(5):
            await asyncio.shield(self._closing)


class SmsHandshake:
    def __init__(
        self, directory: Path, event_id: str, stop: asyncio.Event, *, room_id: str, owner: str
    ) -> None:
        self.directory, self.event_id, self.stop = directory, uuid(event_id), stop
        self.room_id, self.owner = room_id, owner
        self.task: asyncio.Task[dict[str, object]] | None = None
        self.requests = 0
        self.known: dict[str, object] | None = None

    async def request(self) -> dict[str, object]:
        if self.task is None:
            self.requests += 1
            marker(self.directory, "sms_requested")

            async def actual() -> dict[str, object]:
                value = fields(
                    decode(
                        await wait_file(
                            self.directory,
                            "rehydration-sms-result.json",
                            4096,
                            self.stop,
                            seconds=20,
                        ),
                        4096,
                    ),
                    {
                        "schemaVersion",
                        "status",
                        "smsAccepted",
                        "caseRevision",
                        "receiptId",
                        "operationKey",
                        "eventId",
                    },
                )
                if (
                    type(value["schemaVersion"]) is not int
                    or value["schemaVersion"] != 1
                    or type(value["smsAccepted"]) is not int
                    or value["smsAccepted"] != 1
                    or value["status"] != "passed"
                    or value["caseRevision"] != "2"
                    or uuid(value["eventId"]) != self.event_id
                ):
                    raise NativeError()
                uuid(value["receiptId"])
                uuid(value["operationKey"])
                ready = fields(
                    decode(
                        await wait_file(
                            self.directory, "room_b_ready.json", 1024, self.stop, seconds=20
                        ),
                        1024,
                    ),
                    {"schemaVersion", "roomId", "owner"},
                )
                if (
                    type(ready["schemaVersion"]) is not int
                    or ready["schemaVersion"] != 1
                    or ready["roomId"] != self.room_id
                    or ready["owner"] != self.owner
                ):
                    raise NativeError()
                self.known = value
                return value

            self.task = asyncio.create_task(actual(), name="rehydration-fixed-sms-handshake")
            self.task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        return dict(await asyncio.shield(self.task))


class RehydrationApplication:
    def __init__(
        self,
        directory: Path,
        config: Configuration,
        *,
        session_factory: Callable[
            [SessionConfig, Configuration, Path, asyncio.Event], SessionPort
        ] = NativeSession,
    ) -> None:
        self.directory, self.config, self.session_factory = directory, config, session_factory
        self.stop = asyncio.Event()
        self.sessions: dict[str, SessionPort] = {}
        self.launching: dict[str, asyncio.Task[None]] = {}
        self.retired: asyncio.Task[None] | None = None
        self.selected = "A"
        self.failure: asyncio.Future[BaseException] = asyncio.get_running_loop().create_future()
        self.sms = SmsHandshake(
            directory,
            config.sms_event_id,
            self.stop,
            room_id=config.sessions["B"].binding.room_id,
            owner=config.owner,
        )
        helpers = _helpers()
        http_type = type(
            "RehydrationHttp",
            (helpers.LabHttp,),
            {
                "ALLOWED_PATHS": frozenset(
                    ("/p2/session", "/p2/response", "/p2/context", "/p2/sms", "/v1/native/prepare")
                ),
                "LARGE_RESPONSE_PATHS": frozenset(("/p2/response", "/p2/context")),
            },
        )
        self.http: Any = http_type(self.handle)
        self._closed = False
        self._saved: dict[str, dict[str, object]] = {}
        self.stage = "http_binding"
        self.http_closed = False

    def _own(self, task: asyncio.Task[None]) -> None:
        def settled(done: asyncio.Task[None]) -> None:
            if not done.cancelled() and done.exception() is not None and not self.failure.done():
                self.failure.set_result(cast(BaseException, done.exception()))

        task.add_done_callback(settled)

    def _launch(self, label: str) -> SessionPort:
        if self.stop.is_set() or self._closed:
            raise NativeError("closed")
        if label not in self.sessions:
            owner = self.session_factory(
                self.config.sessions[label], self.config, self.directory, self.stop
            )
            self.sessions[label] = owner
            task = asyncio.create_task(owner.start(), name="rehydration-session-" + label)
            self.launching[label] = task
            self._own(task)
        return self.sessions[label]

    async def _retire_a(self) -> None:
        if self.retired is None:

            async def actual() -> None:
                owner = self.sessions["A"]
                async with asyncio.timeout(5):
                    await owner.left.wait()
                await owner.close()
                self._save_session("A")
                marker(self.directory, "python_a_closed")

            self.retired = asyncio.create_task(actual(), name="rehydration-retire-A")
            self._own(self.retired)
        await asyncio.shield(self.retired)

    def _save_session(self, label: str) -> None:
        helpers = _helpers()
        path = self.directory / ("rehydration-python-session-" + label + ".json")
        if label not in self._saved:
            observed = self.sessions[label].proof()
            helpers.save(self.directory, path.name, observed)
            owner = self.sessions[label]
            if isinstance(owner, NativeSession) and owner.recorded is not None:
                helpers.save(
                    self.directory,
                    "communication-python-source-" + label + ".json",
                    owner.recorded.proof(),
                )
            self._saved[label] = observed

    async def handle(
        self, path: str, headers: dict[str, str], raw: bytes
    ) -> tuple[int, dict[str, object]]:
        if self.stop.is_set() or self._closed:
            raise NativeError("closed")
        expected = (
            self.config.prepare.value
            if path == "/v1/native/prepare"
            else self.config.operator.value
        )
        if not hmac.compare_digest(headers.get("authorization", ""), "Bearer " + expected):
            return 401, {"schemaVersion": 1, "status": "unavailable"}
        value = decode(raw, 2 if path == "/p2/session" else 32768)
        if path == "/p2/session":
            if raw != b"{}":
                raise NativeError()
            fields(value, set())
            if self.sessions.get("A") is not None and self.sessions["A"].left.is_set():
                await self._retire_a()
                if self.sms.known is None:
                    raise NativeError("dependency_unavailable")
                self.selected = "B"
            self._launch(self.selected)
            configured = self.config.sessions[self.selected]
            return 200, {
                "schemaVersion": 1,
                "url": self.config.url,
                "token": configured.browser_token,
                "roomId": configured.binding.room_id,
                "participantId": configured.binding.participant_id,
                "agentId": configured.binding.agent_id,
                "bindingId": configured.binding.binding_id,
            }
        if path == "/p2/sms":
            fields(value, {"schemaVersion"})
            if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
                raise NativeError()
            await self._retire_a()
            return 200, await self.sms.request()
        owner = self.sessions.get(self.selected)
        if owner is None or not owner.ready.is_set():
            raise NativeError("dependency_unavailable")
        if path == "/p2/context":
            value = fields(value, {"schemaVersion", "query"})
            if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
                raise NativeError()
            observed = await owner.refresh(RehydrationQuery.from_payload(value["query"]))
            return 200, {"schemaVersion": 1, "status": "known", "context": observed.payload()}
        if path == "/p2/response":
            value = fields(value, {"schemaVersion", "responseId"})
            if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
                raise NativeError()
            response = await owner.response(uuid(value["responseId"]))
            return 200, {"schemaVersion": 1, "status": "known", "result": response.payload()}
        if path != "/v1/native/prepare":
            raise NativeError()
        value = fields(value, {"schemaVersion", "kind", "context"})
        if (
            type(value["schemaVersion"]) is not int
            or value["schemaVersion"] != 1
            or value["kind"] != "agent.prepare"
        ):
            raise NativeError()
        context = fields(
            value["context"],
            {
                "schemaVersion",
                "kind",
                "operationKey",
                "scope",
                "caseId",
                "caseRevision",
                "conversationId",
                "message",
            },
        )
        message = fields(
            context["message"], {"receiptId", "eventId", "messageId", "senderId", "body"}
        )
        if message["senderId"] != owner.config.binding.binding_id:
            raise NativeError("forbidden")
        decision = await owner.prepare(context)
        return 200, {
            "schemaVersion": 1,
            "kind": "agent.prepared",
            "inputDigest": hashlib.sha256(raw).hexdigest(),
            "decision": decision,
        }

    async def run(self) -> dict[str, object]:
        primary: BaseException | None = None
        failed_stage = self.stage
        try:
            port = await self.http.start()
            _helpers().save(
                self.directory, "python-endpoint.json", {"host": "127.0.0.1", "port": port}
            )
            marker(self.directory, "python_http_ready")
            self._launch("A")
            self.stage = "serving"
            stopping = asyncio.create_task(self.stop.wait())
            try:
                async with asyncio.timeout(180):
                    done, _ = await asyncio.wait(
                        (stopping, self.failure), return_when=asyncio.FIRST_COMPLETED
                    )
                if self.failure in done:
                    raise self.failure.result()
            finally:
                stopping.cancel()
                await asyncio.gather(stopping, return_exceptions=True)
        except BaseException as error:  # noqa: BLE001 - Preserve primary cancellation and attempt every owner.
            primary = error
            failed_stage = next(
                (
                    owner.stage
                    for owner in self.sessions.values()
                    if isinstance(owner, NativeSession) and owner.stage not in ("ready", "closed")
                ),
                self.stage,
            )
        finally:
            self.stop.set()
            self.stage = "cleanup"
            # Stop admissions first. Actual handlers/owners are still observed below.
            self.http.closing = True
            if self.http.server is not None:
                self.http.server.close()
            owned = [
                *self.launching.values(),
                *([self.retired] if self.retired else []),
                *([self.sms.task] if self.sms.task else []),
            ]
            for task in owned:
                if not task.done():
                    task.cancel()
            if owned:
                settlement = asyncio.gather(*owned, return_exceptions=True)
                try:
                    async with asyncio.timeout(5):
                        await asyncio.shield(settlement)
                except BaseException as error:  # noqa: BLE001 - Preserve primary cancellation and attempt every owner.
                    primary = primary or error
            # Every close is attempted even after an earlier cancellation/failure.
            actions: list[Callable[[], Awaitable[object]]] = [
                owner.close for owner in self.sessions.values()
            ]
            for action in actions:
                try:
                    await action()
                except BaseException as error:  # noqa: BLE001 - Preserve primary cancellation and attempt every owner.
                    primary = primary or error
            try:
                await self.http.close()
                self.http_closed = True
            except BaseException as error:  # noqa: BLE001 - Preserve primary cancellation and attempt every owner.
                primary = primary or error
        if primary is None and (
            set(self.sessions) != {"A", "B"}
            or self.sms.known is None
            or self.http.tasks
            or self.http.writers
            or self.http.active
        ):
            primary = NativeError("dependency_unavailable")
        if primary is not None:
            cleanup_complete = (
                self.http_closed
                and all(owner.closed for owner in self.sessions.values())
                and all(task.done() for task in self.launching.values())
                and (self.retired is None or self.retired.done())
                and (self.sms.task is None or self.sms.task.done())
            )
            try:
                _helpers().save(
                    self.directory,
                    "rehydration-python-failure.json",
                    failure_context(primary, failed_stage, cleanup_complete),
                )
            except OSError:
                self.stage = "cleanup"  # Retention failure never replaces the primary failure.
            raise primary
        for label in self.sessions:
            self._save_session(label)
        result = {
            "schemaVersion": 1,
            "status": "passed",
            "mode": "rehydration-serve",
            "cleanupComplete": True,
            "httpClosed": self.http_closed,
            "smsRequests": self.sms.requests,
            "smsKnown": self.sms.known is not None,
            "sessions": {label: owner.proof() for label, owner in self.sessions.items()},
        }
        _helpers().save(self.directory, "rehydration-python-terminal.json", result)
        _helpers().save(self.directory, "python-terminal.json", result)
        self._closed = True
        self.stage = "closed"
        return result


async def serve(directory: Path) -> dict[str, object]:
    info = directory.lstat()
    if (
        not directory.is_absolute()
        or directory.is_symlink()
        or stat.S_IMODE(info.st_mode) != 0o700
        or info.st_uid != os.geteuid()
    ):
        raise NativeError()
    config = Configuration.parse(
        decode(private_read(directory / "fixture.json", 16384), 16384),
        decode(private_read(directory / "media.json", 32768), 32768),
    )
    app = RehydrationApplication(directory, config)
    loop = asyncio.get_running_loop()
    for name in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(name, app.stop.set)
    try:
        return await app.run()
    finally:
        for name in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(name)


def main() -> int:
    logging.basicConfig(level=logging.INFO, handlers=[_helpers().SafeConsoleHandler()], force=True)
    try:
        if len(sys.argv) != 2:
            raise NativeError()
        result = asyncio.run(serve(Path(sys.argv[1])))
        print(json.dumps(result, separators=(",", ":")), flush=True)
        return 0
    except Exception:  # noqa: BLE001 - Fixed payload-free application failure.
        print(
            '{"schemaVersion":1,"status":"failed","mode":"rehydration-serve","cleanupComplete":false}',
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
