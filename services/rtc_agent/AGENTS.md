# Local transport diagnostic agent coding instructions

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Give coding agents the reading order, ownership, rules and checks for transport diagnostic agent work |
| Audience | Coding agents and engineers changing the diagnostic worker or its tests |
| Scope | `services/rtc_agent` and its tests; excludes business intake and model inference |
| Owns | Agent workflow for the diagnostic agent: reading order, owned paths, development rules, verification and handoff |
| Related | [Root instructions](../../AGENTS.md) · [README](README.md) · [Design](Design.md) · [Validation plan](../../docs/validation-plan.md) |

## Read first

Read these documents:

| Document | Why read it |
| --- | --- |
| [Root instructions](../../AGENTS.md) | Shared reading order, owned paths, development rules and verification |
| [README.md](README.md) | Implemented behavior, commands and validation |
| [Design.md](Design.md) | Design, limits and failure handling |
| [Validation plan](../../docs/validation-plan.md) | Test lanes, required fault scenarios, benchmarks and evidence |

## Owned paths

| Area | Responsibility |
| --- | --- |
| `services/rtc_agent`, `tests/test_rtc_agent.py` and `tests/test_rtc_telemetry.py` | Owned here |
| Shared SDK/transport and M1 boundaries | Preserve them |

M1 is the existing confirmed-investigation intake.

## Development rules

### Requests and lifecycle

- Use typed requests, bounded work and explicit lifecycle cleanup.
- Propagate cancellation and fatal exceptions.
- Do not add provider calls to deterministic diagnostics.
- Do not infer business authority from transport success.
- New behavior needs normal, negative and useful-progress assertions.

### Logging and credentials

- Keep credentials out of logs and responses.
- Configure the application JSON logger only at actual worker entrypoints.
- Keep fixed event/code pairs and bounded numeric fields.
- Never serialize exception text/chains or participant/room/track content.

### Size bounds

- Request/audio/API bounds remain 16,384 UTF-8 bytes.
- Diagnostic chat replies allow 16,390 bytes including the echo prefix.
- Shared fixtures test both boundaries.

## Verification

From the repository root:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_rtc*.py' -v
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh
```

| Check | Command | When to run |
| --- | --- | --- |
| Diagnostic agent tests | `.venv/bin/python -m unittest discover -s tests -p 'test_rtc*.py' -v` | First, for every change |
| Full fast validation | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh` | Before handoff |

## Handoff

- Record the interface change, exact validation, observed result and remaining limits.
- Keep transport, intake and model evidence separate.
