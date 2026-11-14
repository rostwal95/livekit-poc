"""Explicitly loaded, synthetic PCM models for one genuine P2 native runtime.

Importing this module loads neither the SDK nor assets. Scripted recognition
assigns a declared transcript to a non-silent manual turn; it does not recognize
arbitrary speech or authenticate received PCM as a particular spoken clip.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import math
import os
import stat
import wave
from collections.abc import Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol, TypeVar

if TYPE_CHECKING:
    from livekit.agents import llm as sdk_llm
    from livekit.agents import stt as sdk_stt
    from livekit.agents import tts as sdk_tts

    from channel_continuity.native_models import NativeRecognizer

InputFixture = Literal["input-investigate.wav", "input-status.wav"]
ReplyFixture = Literal[
    "checking.wav",
    "demo.wav",
    "accepted.wav",
    "status.wav",
    "guard.wav",
    "no-case.wav",
    "unavailable.wav",
    "cancelled.wav",
]
ModelCode = Literal[
    "invalid_configuration",
    "invalid_audio",
    "invalid_input",
    "capacity_exhausted",
    "closed",
    "unavailable",
    "cleanup_incomplete",
]
SAMPLE_RATE = 16000
MAX_TURN_SAMPLES = 12 * SAMPLE_RATE
MAX_SESSION_SAMPLES = 190 * SAMPLE_RATE
MANIFEST_SHA256 = "43366be51366074006ba1e9fd3d7f310d531e1db07a6b9453119bcbe4bd76c04"
# The showcase owns this short reply; P1's pinned conversation assets stay unchanged.
OWNED_FIXTURES: Final = frozenset({"checking.wav"})
# P2's native prepare plays the whole dispatched reply inside a fixed 4-second
# budget, so the default reply must leave ample headroom for generation and RTC.
DEFAULT_REPLY_FIXTURE: Final = "checking.wav"
MAX_DEFAULT_REPLY_SAMPLES: Final = 2 * SAMPLE_RATE


class NativeModelError(Exception):
    """Finite diagnostics: dependency arguments and audio/text are never copied."""

    def __init__(self, code: ModelCode = "unavailable") -> None:
        allowed = {
            "invalid_configuration",
            "invalid_audio",
            "invalid_input",
            "capacity_exhausted",
            "closed",
            "unavailable",
            "cleanup_incomplete",
        }
        self.code: ModelCode = code if type(code) is str and code in allowed else "unavailable"
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class _Asset:
    name: str
    sha256: str
    samples: int
    text: str


# Synthetic macOS Albert PCM assets. P1's pinned manifest owns the conversation
# agent's files; the showcase pins its own short reply by digest below.
_ASSETS = (
    _Asset(
        "input-investigate.wav",
        "11f5143ef2a1f0bdae93dfa136b5d5bed880c6dca4952ac28fb61340f3efe12f",
        63865,
        "investigate",
    ),
    _Asset(
        "input-status.wav",
        "fb9b5ed6b7824f05fce6fa6c5d3fd061eab3d7bc539f1e223fa5ff6e2cd2b78e",
        39345,
        "status",
    ),
    _Asset(
        "checking.wav",
        "653ca9a56c40152bad79c0bc4817452e48f7808f0fdb55766cbc99967c90c85c",
        27246,
        "Checking the policy.",
    ),
    _Asset(
        "demo.wav",
        "16823db29ea200ea34d02aae250e1ffee8fc7b5f267bb208a480da8c4eb8ca98",
        61219,
        "This is a scripted local voice demonstration.",
    ),
    _Asset(
        "accepted.wav",
        "35322c2d1c74c73cca050f948c7d2ce30387e743b57d0e5855c7e03739e83842",
        78035,
        "Your investigation was accepted and continues independently.",
    ),
    _Asset(
        "status.wav",
        "5006065301ff499dd682f967ada0fb744e47cc9f7a866f0f2efd75247dce82b2",
        65863,
        "The workflow panel shows the latest durable state.",
    ),
    _Asset(
        "guard.wav",
        "9508076b65fafb62c3a89ced214f3d092ee430d2f5d42f51bee4ac9fa558b962",
        65828,
        "Confirm the exact quote only in the workflow panel.",
    ),
    _Asset(
        "no-case.wav",
        "febbea19ec3850836e6808c7e81a3120abff5d333650e2c284874966e4a2b5fd",
        81756,
        "No investigation has been accepted for this conversation yet.",
    ),
    _Asset(
        "unavailable.wav",
        "8830882cb5a892dcf749014550820d03cd04e6f4d7598f1199ecd5030b315d56",
        106359,
        "The operation could not be completed; please inspect the workflow panel.",
    ),
    _Asset(
        "cancelled.wav",
        "e8f9d11a49eeb30741fee149121baf918ecf71b2523f50c1af144ecf9ed9d157",
        88809,
        "Your cancellation request was recorded for the current investigation.",
    ),
)


def _asset(name: object) -> _Asset:
    for item in _ASSETS:
        if type(name) is str and name == item.name:
            return item
    raise NativeModelError("invalid_configuration")


@dataclass(frozen=True, slots=True)
class ScriptedModelProfile:
    """Finite manual-turn script; fixture order is selected before room startup."""

    input_fixtures: tuple[InputFixture, ...] = ("input-investigate.wav", "input-status.wav")
    reply_fixture: ReplyFixture = DEFAULT_REPLY_FIXTURE
    cleanup_timeout_s: float = 1.0

    def __post_init__(self) -> None:
        if type(self.input_fixtures) is not tuple or not 1 <= len(self.input_fixtures) <= 32:
            raise NativeModelError("invalid_configuration")
        for name in self.input_fixtures:
            if type(name) is not str or name not in ("input-investigate.wav", "input-status.wav"):
                raise NativeModelError("invalid_configuration")
        if _asset(self.reply_fixture).name.startswith("input-"):
            raise NativeModelError("invalid_configuration")
        value = self.cleanup_timeout_s
        if type(value) not in (int, float) or not 0 < value <= 5 or not math.isfinite(value):
            raise NativeModelError("invalid_configuration")


@dataclass(frozen=True, slots=True)
class ScriptedAudio:
    """Original decoded PCM plus original WAV-file SHA; no received-wave identity claim."""

    fixture: str
    pcm: bytes
    wav_sha256: str
    sample_rate: int = SAMPLE_RATE
    channels: int = 1
    sample_width: int = 2

    def __post_init__(self) -> None:
        expected = _asset(self.fixture)
        if (
            type(self.pcm) is not bytes
            or len(self.pcm) != expected.samples * 2
            or type(self.wav_sha256) is not str
            or self.wav_sha256 != expected.sha256
            or type(self.sample_rate) is not int
            or self.sample_rate != SAMPLE_RATE
            or type(self.channels) is not int
            or self.channels != 1
            or type(self.sample_width) is not int
            or self.sample_width != 2
        ):
            raise NativeModelError("invalid_configuration")


class _BundlePort(Protocol):
    @property
    def pending_count(self) -> int: ...
    def metrics(self) -> dict[str, int]: ...
    async def aclose(self) -> None: ...


class ScriptedModelBundle:
    """Models only: the caller owns the sole NativeRuntime/session separately.

    Stop/close the native runtime first, then retry aclose until its actual model
    owners settle. A cancelled/timed-out close observer never frees model slots.
    SDK model imports/telemetry happen only during the explicit loader.
    """

    def __init__(
        self,
        *,
        stt: sdk_stt.STT[Any],
        llm: sdk_llm.LLM[Any],
        tts: sdk_tts.TTS[Any],
        recognizer: NativeRecognizer,
        owner: _BundlePort,
        assets: tuple[ScriptedAudio, ...],
        profile: ScriptedModelProfile,
    ) -> None:
        self._stt, self._llm, self._tts, self._recognizer = stt, llm, tts, recognizer
        self._owner, self._assets, self._profile = owner, assets, profile

    @property
    def stt(self) -> sdk_stt.STT[Any]:
        return self._stt

    @property
    def llm(self) -> sdk_llm.LLM[Any]:
        return self._llm

    @property
    def tts(self) -> sdk_tts.TTS[Any]:
        return self._tts

    @property
    def recognizer(self) -> NativeRecognizer:
        return self._recognizer

    @property
    def inference_mode(self) -> Literal["scripted"]:
        return "scripted"

    @property
    def pending_count(self) -> int:
        return self._owner.pending_count

    def metrics(self) -> dict[str, int]:
        return dict(self._owner.metrics())

    def input_audio(self, fixture: InputFixture) -> ScriptedAudio:
        if type(fixture) is not str or fixture not in self._profile.input_fixtures:
            raise NativeModelError("invalid_configuration")
        return next(item for item in self._assets if item.fixture == fixture)

    async def aclose(self) -> None:
        await self._owner.aclose()


_T = TypeVar("_T")


def _task(operation: Coroutine[Any, Any, _T], *, cleanup: bool = False) -> asyncio.Task[_T]:
    try:
        return asyncio.create_task(operation)
    except BaseException as error:
        operation.close()
        if isinstance(error, Exception):
            raise NativeModelError("cleanup_incomplete" if cleanup else "unavailable") from None
        raise


def _read(path: Path, maximum: int) -> bytes:
    before = path.lstat()
    # Installed wheel files may share a uv/pip cache inode. Fixed names,
    # regular-file/size checks and pinned bytes are the asset trust boundary.
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
        raise NativeModelError("invalid_configuration")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        actual = os.fstat(descriptor)
        if not stat.S_ISREG(actual.st_mode):
            raise NativeModelError("invalid_configuration")
        if (actual.st_dev, actual.st_ino, actual.st_size) != (
            before.st_dev,
            before.st_ino,
            before.st_size,
        ):
            raise NativeModelError("invalid_configuration")
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            data = source.read(maximum + 1)
        if len(data) != before.st_size:
            raise NativeModelError("invalid_configuration")
        return data
    finally:
        os.close(descriptor)


def _load_assets() -> tuple[ScriptedAudio, ...]:
    # Fixed installed-package-relative locations, never cwd or a user supplied path.
    directory = Path(__file__).resolve().parents[1] / "conversation_agent" / "assets"
    owned = Path(__file__).resolve().parent / "assets"
    try:
        manifest = _read(directory / "manifest.json", 16384)
        if hashlib.sha256(manifest).hexdigest() != MANIFEST_SHA256:
            raise NativeModelError("invalid_configuration")
        result = []
        for item in _ASSETS:
            folder = owned if item.name in OWNED_FIXTURES else directory
            data = _read(folder / item.name, MAX_TURN_SAMPLES * 2 + 4096)
            if hashlib.sha256(data).hexdigest() != item.sha256:
                raise NativeModelError("invalid_configuration")
            with wave.open(io.BytesIO(data), "rb") as source:
                if (
                    source.getnchannels(),
                    source.getsampwidth(),
                    source.getframerate(),
                    source.getcomptype(),
                    source.getnframes(),
                ) != (1, 2, SAMPLE_RATE, "NONE", item.samples):
                    raise NativeModelError("invalid_configuration")
                pcm = source.readframes(item.samples + 1)
            if len(pcm) != item.samples * 2:
                raise NativeModelError("invalid_configuration")
            result.append(ScriptedAudio(item.name, pcm, item.sha256))
        return tuple(result)
    except Exception:  # noqa: BLE001 - finite filesystem/decoder boundary
        # Explicit filesystem/decoder boundary; no path/decoder exception escapes.
        raise NativeModelError("invalid_configuration") from None


_DEFAULT_PROFILE = ScriptedModelProfile()


async def load_scripted_models(
    profile: ScriptedModelProfile = _DEFAULT_PROFILE,
) -> ScriptedModelBundle:
    """Validate shipped assets off-loop, then load genuine SDK models explicitly.

    Cancellation waits for the bounded read-only loader thread to settle and
    creates no SDK model/session after cancellation. No provider/env files load.
    """
    if type(profile) is not ScriptedModelProfile:
        raise NativeModelError("invalid_configuration")
    profile = ScriptedModelProfile(
        profile.input_fixtures, profile.reply_fixture, profile.cleanup_timeout_s
    )
    current = asyncio.current_task()
    if current is not None and current.cancelling():
        raise asyncio.CancelledError
    task = _task(asyncio.to_thread(_load_assets))
    try:
        assets = await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:  # noqa: BLE001 - retrieve abandoned loader outcome only
                break
        if not task.cancelled():
            task.exception()
        raise
    except NativeModelError:
        raise
    except Exception:  # noqa: BLE001 - finite explicit loader boundary
        raise NativeModelError("unavailable") from None
    # No await or resource transfer between construction and returned ownership.
    try:
        from ._native_models_sdk import build_models

        return build_models(profile, assets)
    except Exception:  # noqa: BLE001 - finite explicit SDK loading boundary
        raise NativeModelError("unavailable") from None
