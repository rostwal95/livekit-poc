"""Importable native agent callbacks for the explicitly configured business profile."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from uuid import UUID

os.environ.setdefault("LIVEKIT_AGENTS_PRELOAD_LOCAL_INFERENCE", "0")

from livekit import rtc
from livekit.agents import AgentServer, AutoSubscribe, JobContext, JobProcess, JobRequest

from .inference_settings import LocalInferenceSettings, selected_profile
from .scripted import SpeechBank
from .session import ConversationRuntime, Receipt, create_runtime
from .telemetry import configure_logging, emit, session_failure_code

AGENT_NAME = "local-business-agent"
MAX_JOBS = 1
MAX_SESSION_SECONDS = 180


class ConversationCleanupIncomplete(RuntimeError):
    """The job failed to observe complete owned-resource cleanup."""


class JobAdmission:
    """Serialize acceptance through assignment so pending jobs count as load."""

    def __init__(self) -> None:
        self.pending = 0
        self._lock = asyncio.Lock()

    async def accept(self, request: JobRequest) -> None:
        configure_logging()
        if re.fullmatch(r"business-[a-z0-9][a-z0-9-]{0,39}", request.room.name) is None:
            emit("job_rejected", "invalid_room")
            await request.reject()
            return
        async with self._lock:
            if len(server.active_jobs) >= MAX_JOBS:
                emit("job_rejected", "job_capacity")
                await request.reject(terminate=False)
                return
            self.pending += 1
            try:
                await request.accept(
                    name=(
                        "Cloud provider workflow assistant"
                        if selected_profile(os.environ) == "provider_real"
                        else "Local model workflow assistant"
                        if selected_profile(os.environ) == "local_real"
                        else "Local scripted workflow assistant"
                    )
                )
            finally:
                self.pending -= 1


admission = JobAdmission()


def calculate_load(server: AgentServer) -> float:
    return min((len(server.active_jobs) + admission.pending) / MAX_JOBS, 1.0)


def prewarm(proc: JobProcess) -> None:
    configure_logging()
    mode = selected_profile(os.environ)
    proc.userdata["inference_mode"] = mode
    if mode == "scripted":
        proc.userdata["speech_bank"] = SpeechBank.load(Path(__file__).parent / "assets")


server = AgentServer(
    num_idle_processes=0,
    load_fnc=calculate_load,
    load_threshold=1.0,
    job_memory_warn_mb=192,
    job_memory_limit_mb=256,
    drain_timeout=20,
    shutdown_process_timeout=20,
    session_end_timeout=18,
    host="0.0.0.0",
    port=8082,
    max_retry=8,
    setup_fnc=prewarm,
    log_level="WARN",
)


async def accept_business_job(request: JobRequest) -> None:
    await admission.accept(request)


async def publish_observation(room: rtc.Room, result: Receipt, expected_participant: str) -> None:
    task_id = result.get("task_id")
    if type(task_id) is not str:
        return
    try:
        if str(UUID(task_id)) != task_id:
            return
    except ValueError:
        return
    payload = json.dumps({"schema_version": 1, "task_id": task_id}, separators=(",", ":"))
    try:
        async with asyncio.timeout(1):
            await room.local_participant.publish_data(
                payload,
                reliable=True,
                destination_identities=[expected_participant],
                topic="continuity.observed",
            )
    except Exception:  # noqa: BLE001 - best-effort refresh hint never grants authority
        emit("hint_failed", "notification_unavailable")


@server.rtc_session(agent_name=AGENT_NAME, on_request=accept_business_job, on_session_end=None)
async def conversation_session(ctx: JobContext) -> None:
    configure_logging()
    emit("startup_progress", "startup_entry")
    from .composition import SessionBusinessPort, create_port, observe_session

    try:
        async with asyncio.timeout(10):
            port, binding = await create_port(ctx.job.metadata, ctx.room.name)
        emit("startup_progress", "startup_port_ready")
    except Exception as error:  # SDK boundary never serializes dependency content.
        emit("session_failed", session_failure_code("setup", error))
        raise
    runtime: ConversationRuntime | None = None
    observer = None
    close_lock = asyncio.Lock()
    cleaned = False
    incomplete = False
    cleanup_cancellation: asyncio.CancelledError | None = None
    reason = "unexpected_error"
    ended = asyncio.Event()
    phase = "setup"

    async def cleanup() -> None:
        nonlocal cleaned, incomplete, cleanup_cancellation
        async with close_lock:
            if cleaned:
                if cleanup_cancellation is not None:
                    raise cleanup_cancellation
                return
            failures = 0
            if runtime is not None:
                try:
                    async with asyncio.timeout(5):
                        await runtime.aclose()
                except asyncio.CancelledError as error:
                    failures += 1
                    cleanup_cancellation = cleanup_cancellation or error
                    emit("cleanup_failed", session_failure_code("cleanup_runtime", error))
                except Exception as error:  # noqa: BLE001 - independently close observer and port
                    failures += 1
                    emit("cleanup_failed", session_failure_code("cleanup_runtime", error))
                try:
                    runtime.controls.unregister(ctx.room)
                except asyncio.CancelledError as error:
                    failures += 1
                    cleanup_cancellation = cleanup_cancellation or error
                    emit("cleanup_failed", session_failure_code("cleanup_controls", error))
                except Exception as error:  # noqa: BLE001 - best-effort release of registered methods
                    failures += 1
                    emit("cleanup_failed", session_failure_code("cleanup_controls", error))
            if observer is not None and runtime is not None:
                try:
                    async with asyncio.timeout(2):
                        await observer.aclose(runtime.session, ctx)
                except asyncio.CancelledError as error:
                    failures += 1
                    cleanup_cancellation = cleanup_cancellation or error
                    emit("cleanup_failed", session_failure_code("cleanup_observer", error))
                except Exception as error:  # noqa: BLE001 - exporter/report cleanup cannot skip port close
                    failures += 1
                    emit("cleanup_failed", session_failure_code("cleanup_observer", error))
            try:
                async with asyncio.timeout(5):
                    await port.aclose()
            except asyncio.CancelledError as error:
                failures += 1
                cleanup_cancellation = cleanup_cancellation or error
                emit("cleanup_failed", session_failure_code("cleanup_port", error))
            except Exception as error:  # noqa: BLE001 - preserve original failure after all cleanup
                failures += 1
                emit("cleanup_failed", session_failure_code("cleanup_port", error))
            cleaned = True
            if failures:
                incomplete = True
                emit("cleanup_failed", "shutdown_incomplete")
            if cleanup_cancellation is not None:
                raise cleanup_cancellation

    try:

        async def hint(result: Receipt) -> None:
            await publish_observation(ctx.room, result, binding.expected_participant)

        mode = ctx.proc.userdata.get("inference_mode", "scripted")
        emit("startup_progress", "startup_runtime_constructing")
        if mode == "provider_real":
            from .provider_inference import create_provider_runtime

            runtime = await create_provider_runtime(port, binding, on_observation=hint)
        elif mode == "local_real":
            from .local_inference import create_local_runtime

            runtime = await create_local_runtime(
                port, binding, LocalInferenceSettings(), on_observation=hint
            )
        elif mode == "scripted":
            bank = ctx.proc.userdata.get("speech_bank")
            if type(bank) is not SpeechBank:
                raise ValueError("The scripted speech bank was not prewarmed")
            runtime = create_runtime(port, binding, bank, on_observation=hint)
        else:
            raise ValueError("Invalid trusted conversation inference mode")
        emit("startup_progress", "startup_runtime_ready")
        observer = observe_session(runtime.session, ctx, runtime.inference_mode)
        if isinstance(port, SessionBusinessPort):
            port.attach_tracing(observer.tracing)
        runtime.session.on("close", lambda _event: ended.set())
        ctx.room.on("disconnected", lambda *_args: ended.set())
        ctx.add_shutdown_callback(cleanup)
        phase = "rtc_connect"
        emit("startup_progress", "startup_rtc_connecting")
        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
        emit("startup_progress", "startup_rtc_connected")
        phase = "media_ready"
        await runtime.start(ctx.room)
        phase = "session"
        emit("session_started", "accepted")
        try:
            await asyncio.wait_for(ended.wait(), timeout=MAX_SESSION_SECONDS)
            reason = "disconnected"
        except TimeoutError:
            reason = "duration_limit"
    except asyncio.CancelledError:
        reason = "cancelled"
        raise
    except Exception as error:  # SDK boundary logs only the safe fixed application code.
        emit("session_failed", session_failure_code(phase, error))
        raise
    finally:
        original_failure = sys.exc_info()[0] is not None
        try:
            await cleanup()
        except asyncio.CancelledError:
            if not original_failure:
                raise
        finally:
            # Session closure and a connected entrypoint returning do not end an
            # SDK job. Resolve its shutdown hook so the owned process/room can
            # exit and the one-job admission slot becomes available again.
            try:
                ctx.shutdown(reason="Local scripted conversation ended")
            except Exception:  # noqa: BLE001 - preserve any original failure after owned cleanup
                incomplete = True
                emit("cleanup_failed", "shutdown_incomplete")
            emit("session_finished", "shutdown_incomplete" if incomplete else reason)
        if incomplete and not original_failure:
            raise ConversationCleanupIncomplete("Conversation cleanup did not complete")
