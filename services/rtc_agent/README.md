# Local transport diagnostic agent

Status: Active
Last reviewed: 9 November 2026

## Overview

Verify actual self-hosted LiveKit text and audio transport through the Agents SDK without model inference.

## Implementation status

Implemented deterministic foundation: named worker dispatch, bounded native text echo and audio-frame diagnostics. It provides no STT, LLM, TTS, durable workflow, SMS or specialist reasoning.

The application emits safe structured lifecycle/rejection/task events; native
SDK logs remain a separate boundary. Text requests are bounded to 16,384 UTF-8
bytes; echoed chat replies allow 16,390 bytes including the prefix. Exact and
excessive Unicode boundary fixtures are shared with the browser.

## Documentation

Read [AGENTS.md](AGENTS.md), [Design.md](Design.md), the [shared design](../../Design.md), and the [local setup guide](../../local-setup/README.md).

## Requirements

Install the root agent extra plus local settings dependencies. Set LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET through the local setup. Health listens on container port 8081. Model preloading is disabled because this worker performs no inference.

## Commands

Use the local setup lifecycle for the composed stack. The container process entry is:

```sh
python -m services.rtc_agent start
```

Run it from the repository root in the installed environment with the required configuration. The local setup supplies those values; do not source untrusted shell configuration.

## Validation

From the repository root:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_rtc*.py' -v
```

Unit tests use synthetic local adapters. Actual infrastructure/media evidence is recorded separately through local setup smoke checks.

## Next milestone

Add scripted AgentSession and real-model scenarios through explicit product checkpoints, preserving the distinction between transport and AI behavior.
