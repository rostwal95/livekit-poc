"""Importable LiveKit worker callbacks, safe for spawn/forkserver serialization."""

import asyncio
import os
import re

# This worker never uses inference. Disable implicit local-model preloading.
os.environ.setdefault("LIVEKIT_AGENTS_PRELOAD_LOCAL_INFERENCE", "0")

from livekit import rtc
from livekit.agents import AgentServer, JobContext, JobRequest

from services.control_api.settings import AGENT_NAME

from .telemetry import classify_error, configure_logging, emit_event
from .transport import TransportDiagnostics

MAX_JOBS = 1


def calculate_load(server: AgentServer) -> float:
    return min(len(server.active_jobs) / MAX_JOBS, 1.0)


server = AgentServer(
    num_idle_processes=0,
    load_fnc=calculate_load,
    load_threshold=1.0,
    job_memory_warn_mb=192,
    job_memory_limit_mb=256,
    drain_timeout=20,
    shutdown_process_timeout=8,
    session_end_timeout=8,
    host="0.0.0.0",
    port=8081,
    max_retry=8,
)


async def accept_local_job(request: JobRequest) -> None:
    configure_logging()
    if not re.fullmatch(r"lab-[a-z0-9][a-z0-9-]{0,47}", request.room.name):
        emit_event("job_rejected", code="invalid_room")
        await request.reject()
    elif len(server.active_jobs) >= MAX_JOBS:
        emit_event("job_rejected", code="job_capacity")
        await request.reject(terminate=False)
    else:
        await request.accept(name="Local transport diagnostic")


@server.rtc_session(agent_name=AGENT_NAME, on_request=accept_local_job)
async def transport_session(ctx: JobContext) -> None:
    configure_logging()
    room = ctx.room
    diagnostics = TransportDiagnostics(room)
    disconnected = asyncio.Event()

    room.register_text_stream_handler("lk.chat", diagnostics.on_text)

    @room.on("track_subscribed")
    def subscribed(track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO and participant.identity.startswith(
            ("browser-", "smoke-")
        ):
            diagnostics.on_audio(track, publication.sid)

    @room.on("track_unsubscribed")
    def unsubscribed(track, publication, participant):
        diagnostics.remove_audio(publication.sid)

    @room.on("disconnected")
    def on_disconnected(*_):
        disconnected.set()

    ctx.add_shutdown_callback(diagnostics.close)
    reason = "failed"
    emit_event("session_started", code="accepted")
    try:
        await ctx.connect()
        try:
            await asyncio.wait_for(disconnected.wait(), timeout=600)
            reason = "disconnected"
        except TimeoutError:
            reason = "duration_limit"
            ctx.shutdown(reason="Local diagnostic session duration reached")
    except asyncio.CancelledError:
        reason = "cancelled"
        raise
    except Exception as error:  # Observe once, then preserve the original SDK failure.
        emit_event("session_failed", code=classify_error(error))
        raise
    finally:
        try:
            await diagnostics.close()
        finally:
            emit_event("session_finished", code=reason)
