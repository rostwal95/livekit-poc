"""Exercise the actual local API, agent dispatch, RTC text and fixture audio."""

import asyncio
import json
import math
import os
import sys
from array import array
from uuid import uuid4

import httpx
from livekit import api, rtc

from services.rtc_agent.transport import ECHO_PREFIX, MAX_REPLY_BYTES, MAX_TEXT_BYTES


async def bounded_text(reader, maximum: int = MAX_TEXT_BYTES):
    parts, size = [], 0
    try:
        async with asyncio.timeout(10):
            async for part in reader:
                size += len(part.encode("utf-8"))
                if size > maximum:
                    raise RuntimeError("Oversized diagnostic response")
                parts.append(part)
        return "".join(parts)
    finally:
        reader.close()


CURRENT_STAGE = "initialization"


async def smoke():
    global CURRENT_STAGE
    api_url = os.environ.get("SMOKE_API_URL", "http://127.0.0.1:8080")
    rtc_url = os.environ.get("SMOKE_RTC_URL", os.environ["LIVEKIT_URL"])
    headers = {"Authorization": "Bearer " + os.environ["LOCAL_ACCESS_TOKEN"]}
    room_name = "lab-smoke-" + uuid4().hex[:12]
    identity = "smoke-" + uuid4().hex[:12]
    room = rtc.Room()
    echo, edge_echo, audio, joined, failed = (asyncio.Event() for _ in range(5))
    observations = {"frames": 0}
    tasks = set()
    source = None
    message = "Local transport check " + uuid4().hex[:8]
    boundary_message = "é" * (MAX_TEXT_BYTES // 2)

    async def receive(reader, participant, kind):
        if participant != observations.get("agent_identity"):
            reader.close()
            return
        text = await bounded_text(reader, MAX_REPLY_BYTES if kind == "echo" else MAX_TEXT_BYTES)
        if kind == "echo" and text == ECHO_PREFIX + message:
            echo.set()
        elif kind == "echo" and text == ECHO_PREFIX + boundary_message:
            edge_echo.set()
        elif kind == "audio":
            report = json.loads(text)
            if (
                report.get("type") == "audio.frames"
                and report.get("track_sid") == observations.get("published_track_sid")
                and int(report.get("frames", 0)) >= 10
            ):
                observations["frames"] = int(report["frames"])
                audio.set()

    def handler(kind):
        def start(reader, participant):
            task = asyncio.create_task(receive(reader, participant, kind))
            tasks.add(task)

            def completed(finished):
                tasks.discard(finished)
                if not finished.cancelled() and finished.exception() is not None:
                    failed.set()

            task.add_done_callback(completed)

        return start

    async def wait_for_signal(signal):
        expected = asyncio.create_task(signal.wait())
        problem = asyncio.create_task(failed.wait())
        try:
            await asyncio.wait({expected, problem}, return_when=asyncio.FIRST_COMPLETED)
            if failed.is_set():
                raise RuntimeError("Diagnostic stream handling failed")
        finally:
            for task in (expected, problem):
                task.cancel()
            await asyncio.gather(expected, problem, return_exceptions=True)

    room.register_text_stream_handler("lk.agent.chat", handler("echo"))
    room.register_text_stream_handler("lk.agent.events", handler("audio"))

    @room.on("participant_connected")
    def connected(participant):
        if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT:
            observations["agent_identity"] = participant.identity
            joined.set()

    try:
        async with httpx.AsyncClient(base_url=api_url, timeout=8, headers=headers) as client:
            CURRENT_STAGE = "dependency_readiness"
            ready = await client.get("/readyz")
            if ready.status_code != 200:
                raise RuntimeError("Dependencies are not ready")
            unauthorized = await client.post(
                "/api/session",
                headers={"Authorization": "Bearer invalid"},
                json={"room": room_name, "identity": identity},
            )
            if unauthorized.status_code != 401:
                raise RuntimeError("Operator authentication did not reject an invalid token")
            request = {
                "booking_reference": "DEMO-BK-001",
                "new_check_in": "2030-12-10",
                "confirmed": True,
                "idempotency_key": "local-foundation-smoke-v1",
            }
            CURRENT_STAGE = "investigation_intake"
            accepted = await client.post("/api/investigations", json=request)
            replay = await client.post("/api/investigations", json=request)
            if accepted.status_code not in {200, 201} or replay.status_code not in {200, 201}:
                raise RuntimeError("Investigation intake failed")
            original, repeated = accepted.json(), replay.json()
            if original["task"]["task_id"] != repeated["task"]["task_id"] or repeated["created"]:
                raise RuntimeError("Investigation replay lost its logical identity")
            conflict = await client.post(
                "/api/investigations", json={**request, "new_check_in": "2030-12-11"}
            )
            if conflict.status_code != 409:
                raise RuntimeError("Conflicting intake was not rejected")
            CURRENT_STAGE = "named_dispatch"
            response = await client.post(
                "/api/session",
                json={"room": room_name, "identity": identity, "dispatch_agent": True},
            )
            if response.status_code != 200:
                raise RuntimeError("Diagnostic agent dispatch failed")
            session = response.json()
        async with asyncio.timeout(35):
            CURRENT_STAGE = "rtc_connection"
            await room.connect(
                rtc_url,
                session["token"],
                rtc.RoomOptions(
                    rtc_config=rtc.RtcConfiguration(ice_servers=[]), connect_timeout=10
                ),
            )
            for participant in room.remote_participants.values():
                connected(participant)
            CURRENT_STAGE = "agent_join"
            await wait_for_signal(joined)
            CURRENT_STAGE = "text_echo"
            await room.local_participant.send_text(message, topic="lk.chat")
            await wait_for_signal(echo)
            CURRENT_STAGE = "text_utf8_boundary"
            await room.local_participant.send_text(boundary_message, topic="lk.chat")
            await wait_for_signal(edge_echo)
            CURRENT_STAGE = "audio_publish"
            source = rtc.AudioSource(48_000, 1)
            track = rtc.LocalAudioTrack.create_audio_track("local-smoke-audio", source)
            publication = await room.local_participant.publish_track(
                track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
            )
            observations["published_track_sid"] = publication.sid
            for index in range(50):
                samples = array(
                    "h",
                    (
                        int(800 * math.sin(2 * math.pi * 440 * (index * 960 + n) / 48_000))
                        for n in range(960)
                    ),
                )
                await source.capture_frame(rtc.AudioFrame(samples.tobytes(), 48_000, 1, 960))
            CURRENT_STAGE = "audio_reception"
            await wait_for_signal(audio)
        return {
            "status": "passed",
            "mode": "lab",
            "inference_enabled": False,
            "checks": [
                "dependency-readiness",
                "operator-authentication",
                "m1-idempotency",
                "m1-conflict",
                "named-agent-dispatch",
                "rtc-text-echo",
                "rtc-text-utf8-boundary",
                "rtc-audio-frames",
            ],
            "audio_frames_observed": observations["frames"],
            "investigation_task_id": original["task"]["task_id"],
            "product_acceptance": "not_certified",
        }
    finally:
        original_failure = sys.exc_info()[0] is not None
        cleanup_warnings = []
        try:
            await asyncio.wait_for(room.disconnect(), 5)
        except Exception:  # noqa: BLE001 - preserve and report each cleanup failure
            cleanup_warnings.append("room_disconnect")
        for task in list(tasks):
            task.cancel()
        if tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 5)
            except Exception:  # noqa: BLE001 - preserve and report each cleanup failure
                cleanup_warnings.append("reader_cleanup")
        if source is not None:
            try:
                await asyncio.wait_for(source.aclose(), 5)
            except Exception:  # noqa: BLE001 - preserve and report each cleanup failure
                cleanup_warnings.append("audio_source_cleanup")
        try:
            async with api.LiveKitAPI(
                url=os.environ["LIVEKIT_URL"],
                api_key=os.environ["LIVEKIT_API_KEY"],
                api_secret=os.environ["LIVEKIT_API_SECRET"],
            ) as admin:
                await asyncio.wait_for(
                    admin.room.delete_room(api.DeleteRoomRequest(room=room_name)), 5
                )
        except Exception:  # noqa: BLE001 - preserve and report each cleanup failure
            cleanup_warnings.append("room_deletion")
        if cleanup_warnings:
            print(
                json.dumps({"status": "cleanup_warning", "operations": cleanup_warnings}),
                file=sys.stderr,
            )
            if not original_failure:
                raise RuntimeError("Diagnostic cleanup was incomplete")


if __name__ == "__main__":
    try:
        print(json.dumps(asyncio.run(smoke()), indent=2))
    except Exception as error:  # noqa: BLE001 - secret-safe process boundary
        print(
            json.dumps(
                {
                    "status": "failed",
                    "failure_type": type(error).__name__,
                    "stage": CURRENT_STAGE,
                    "message": "Local smoke failed; inspect readiness and bounded service logs.",
                }
            )
        )
        sys.exit(1)
