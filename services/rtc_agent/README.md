# Local transport diagnostic agent

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Explain how to run and validate the local transport diagnostic worker |
| Audience | Engineers running or changing the diagnostic worker |
| Scope | Worker setup, commands and diagnostic evidence; excludes model inference and product workflows |
| Owns | Diagnostic worker onboarding, implementation status and validation commands |
| Related | [Agent instructions](AGENTS.md) · [Design](Design.md) · [Shared design](../../Design.md) · [Local setup](../../local-setup/README.md) |

## Overview

This worker verifies actual self-hosted LiveKit text and audio transport through
the LiveKit Agents SDK, without model inference. This README is for engineers who
run or change the diagnostic worker. [Design.md](Design.md) explains its design,
limits and failure handling.

## Implementation status

The deterministic foundation is implemented:

- named worker dispatch;
- bounded native text echo;
- audio-frame diagnostics.

The worker provides no speech-to-text (STT), large language model (LLM),
text-to-speech (TTS), durable workflow, SMS or specialist reasoning.

| Text limit | Value |
| --- | --- |
| Text request | 16,384 UTF-8 bytes |
| Echoed chat reply | 16,390 bytes, including the echo prefix |

Exact and excessive Unicode boundary fixtures are shared with the browser.

The application emits safe structured lifecycle, rejection and task events.
Native SDK logs remain a separate boundary.

## Documentation

| Document | Purpose |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Coding rules |
| [Design.md](Design.md) | Worker design |
| [Shared design](../../Design.md) | Ecosystem data flow and authority |
| [Local setup guide](../../local-setup/README.md) | Stack lifecycle and smoke checks |

## Requirements

| Requirement | Configuration or limit |
| --- | --- |
| Dependencies | Install the root `agent` extra plus the local settings dependencies |
| Credentials | Set `LIVEKIT_URL`, `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` through the local setup |
| Health endpoint | Container port 8081 |
| Model preloading | Disabled because this worker performs no inference |

## Commands

Use the local setup lifecycle for the composed stack.

| Command | Purpose |
| --- | --- |
| `python -m services.rtc_agent start` | Container process entry |

Run it from the repository root in the installed environment with the required
configuration. The local setup supplies those values. Do not source untrusted
shell configuration.

## Validation

| Check | Command and evidence |
| --- | --- |
| Unit tests | From the repository root: `.venv/bin/python -m unittest discover -s tests -p 'test_rtc*.py' -v`. Tests use synthetic local adapters |
| Infrastructure and media | Recorded separately through the local setup smoke checks |

## Next milestone

| Planned milestone | Evidence boundary |
| --- | --- |
| Maintain transport diagnostics as a separate regression while product conversation evolves in the [conversation agent](../conversation_agent/README.md) | Product AgentSession and selected provider scenarios have their own checkpoints; diagnostic success does not qualify them |
