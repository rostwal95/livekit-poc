"""Container entry points for explicit demo setup and supervised scripted serving."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import channel_policy_launch as launcher
import channel_policy_setup as setup

REPOSITORY = Path(__file__).resolve().parents[2]
PROFILE = REPOSITORY / ".local/showcase"
BOOKING = REPOSITORY / ".local/booking"
NODE = Path("/usr/local/bin/node")
INITIALIZED = PROFILE / "initialized.json"


def profile_ready() -> bool:
    from services.channel_policy_demo.owner_config import read_owner_profile

    if not INITIALIZED.exists():
        return False
    profile = read_owner_profile(PROFILE / "owner-profile.json")
    raw, _ = launcher.read_private(INITIALIZED)
    return launcher.decode(raw) == {"profileId": profile.route.profile_id}


async def initialize() -> None:
    from continuity_lab.worker_cli import main as worker_main

    if profile_ready():
        print("Demo profile already initialized.")
        return
    if PROFILE.exists() or BOOKING.exists():
        raise RuntimeError("Demo initialization is incomplete.")

    profile = await setup.prepare(PROFILE, NODE, repository=REPOSITORY, case_schema="continuity")
    await setup.associate_sms(PROFILE, NODE, repository=REPOSITORY)
    BOOKING.mkdir(mode=0o700)
    if worker_main(["init-fixtures"]) != 0:
        raise RuntimeError("Unable to initialize synthetic booking fixtures.")
    launcher.publish(INITIALIZED, launcher.encode({"profileId": profile.route.profile_id}))
    print("Demo profile initialized.")


def main(argv: list[str]) -> int:
    try:
        if argv == ["initialize"]:
            asyncio.run(setup._command(initialize()))
            return 0
        if argv == ["serve"] and profile_ready():
            return launcher.main(
                [
                    "serve",
                    "--profile",
                    str(PROFILE / "owner-profile.json"),
                    "--node",
                    str(NODE),
                    "--container",
                ]
            )
        print("Demo profile is unavailable.", file=sys.stderr)
    except (Exception, asyncio.CancelledError):  # noqa: BLE001 - private setup failures stay redacted
        print("Demo setup failed. Inspect ./demo status and ./demo logs.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
