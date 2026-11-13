# Local transport diagnostic agent coding instructions

Status: Active
Last reviewed: 9 November 2026

## Read first

Read [root instructions](../../AGENTS.md), [README.md](README.md), [Design.md](Design.md) and the [validation plan](../../docs/validation-plan.md).

## Owned paths

Own services/rtc_agent, tests/test_rtc_agent.py and tests/test_rtc_telemetry.py. Preserve the shared SDK/transport and M1 boundaries.

## Development rules

Use typed requests, bounded work and explicit lifecycle cleanup. Keep credentials out of logs and responses. Do not add provider calls to deterministic diagnostics or infer business authority from transport success. New behavior needs normal, negative and useful-progress assertions. Configure the
application JSON logger only at actual worker entrypoints; keep fixed event/code
pairs and bounded numeric fields. Never serialize exception text/chains or
participant/room/track content. Propagate cancellation and fatal exceptions.
Request/audio/API bounds remain 16,384 UTF-8 bytes; diagnostic chat replies allow
16,390 bytes including the echo prefix. Shared fixtures test both boundaries.

## Verification

From the repository root:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_rtc*.py' -v
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh
```

## Handoff

Record the interface change, exact validation, observed result and remaining limits. Keep transport, intake and model evidence separate.
