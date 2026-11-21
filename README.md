# Continuity for LiveKit Agents

A local travel-support demo that keeps a case and its background work available
as a caller moves between a LiveKit room, browser chat, and simulated SMS.

[![Demo preview showing the conversation and current policy result](docs/media/demo.png)](docs/media/demo.mp4)

[Watch the 92-second captioned demo](docs/media/demo.mp4)

## Run it locally

Use Docker Desktop or Docker Engine with Compose v2 and a POSIX shell. The first
start downloads pinned images and builds the application. The default demo uses
scripted speech recognition and replies, real WebRTC audio, and synthetic booking
and SMS data. It requires no provider accounts.

```sh
./demo up
./demo key
```

Open [http://127.0.0.1:5189/](http://127.0.0.1:5189/). Choose **Open the
showcase**, select **Connection setup**, enter the key, and select **Use key**
and **Join session**. Ask, “Hi, can I move my booking to a later date?”

The [walkthrough](docs/demo.md) covers recorded voice, the SMS follow-up while the
room is closed, and the separate operator approval flow.

```sh
./demo down
```

Start again with `./demo up` to reuse the local case and work. To clear this
demo’s persisted data, run `./demo reset --yes` before starting again.

## What the demo shows

| Capability | What to look for |
| --- | --- |
| Durable work | A policy check runs independently of the room. In the operator console, a separate case goes from investigation through exact quote approval, synthetic supplier outcome, and receiver delivery. |
| Channel continuity | Submit a text turn, play a recorded voice turn over WebRTC, end the room, then send a simulated SMS. A fresh room reads the same case and its current result. |
| Read-only delegation | A specialist evaluates fixed booking rules in the background. Its result carries the case revision, and viewing it grants no permission to change the booking. |

LiveKit handles room connections, media transport, and the agent session.
PostgreSQL retains accepted inputs, case state, work, and results. The
[architecture guide](docs/architecture.md) shows how those responsibilities fit
together and links to the code.

This is an independent proof of concept built with LiveKit. The demo covers a
bounded local scenario using synthetic data.

After both fresh walkthroughs, run `./demo verify` to reconcile the inputs,
results, and delivery receipts with PostgreSQL and the two synthetic service
ledgers.
