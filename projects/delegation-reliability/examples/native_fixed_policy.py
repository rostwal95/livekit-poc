"""Configured native RTC TEXT composition; import starts no session or network.

The caller supplies and owns one session, connected room, application and model.
The root-owned lab host separately authenticates fixed mint/observation routes.
RTC grants never become privileged read credentials. No P2 runtime is required.
"""

from __future__ import annotations

from livekit import rtc
from livekit.agents import AgentSession, room_io

from delegation_reliability import NativePolicyAgent, NativePolicyApplication
from delegation_reliability.contracts import identifier


async def start_native_fixed_policy(
    *,
    session: AgentSession[None],
    application: NativePolicyApplication,
    room: rtc.Room,
    participant_identity: str,
) -> NativePolicyAgent:
    """Start the supplied single session with exact-participant SDK text ownership.

    The host publishes its profile/session readiness only after actual RoomIO and
    participant readiness, and stops admission before bounded session/application
    closure. It retains close observers on timeout and attempts independent facade
    closes even if SDK close fails. A local pending count is not remote-stop proof.
    """
    participant = identifier(participant_identity)
    agent = NativePolicyAgent(application)
    await session.start(
        agent,
        room=room,
        room_options=room_io.RoomOptions(
            participant_identity=participant,
            text_input=True,
            text_output=True,
            audio_input=False,
            audio_output=False,
            video_input=False,
            close_on_disconnect=False,
            delete_room_on_close=False,
        ),
        session_host=False,
        record=False,
    )
    return agent
