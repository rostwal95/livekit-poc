# Local transport diagnostic agent

Status: Active
Last reviewed: 15 November 2026

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

- [AGENTS.md](AGENTS.md) for coding rules and [Design.md](Design.md) for the design.
- The [shared design](../../Design.md) for ecosystem data flow and authority.
- The [local setup guide](../../local-setup/README.md) for the stack lifecycle and smoke checks.

## Requirements

- Install the root `agent` extra plus the local settings dependencies.
- Set `LIVEKIT_URL`, `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` through the local setup.
- The health endpoint listens on container port 8081.
- Model preloading is disabled because this worker performs no inference.

## Commands

Use the local setup lifecycle for the composed stack. The container process entry is:

```sh
python -m services.rtc_agent start
```

Run it from the repository root in the installed environment with the required
configuration. The local setup supplies those values. Do not source untrusted
shell configuration.

## Validation

From the repository root:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_rtc*.py' -v
```

Unit tests use synthetic local adapters. Actual infrastructure and media evidence
is recorded separately through the local setup smoke checks.

## Next milestone

Add scripted AgentSession and real-model scenarios through explicit product
checkpoints, preserving the distinction between transport and AI behavior.
