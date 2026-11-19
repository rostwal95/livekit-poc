# Local control API coding instructions

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Give coding agents the reading order, ownership, rules and checks for local control API work |
| Audience | Coding agents and engineers changing the control API, its business routes or its tests |
| Scope | `services/control_api`, its business routes and tests; excludes other services and the console |
| Owns | Agent workflow for the control API: reading order, owned paths, development rules, verification and handoff |
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
| `services/control_api` and `tests/test_control_api.py` | Owned here |
| Business routes | Live in `business.py` and `business_dispatch.py` |
| Shared SDK/transport and M1 boundaries | Preserve them |

M1 is the existing confirmed-investigation intake.

## Development rules

### Requests and lifecycle

- Use typed requests, bounded work and explicit lifecycle cleanup.
- Keep the error-code/retry envelope stable.
- Generate request IDs internally.
- Propagate cancellation and fatal exceptions.
- Do not add provider calls to deterministic diagnostics.
- Do not infer business authority from transport success.
- New behavior needs a normal case and a meaningful failure case.

### Logs, metrics and credentials

- Keep credentials out of logs and responses.
- Log safe operation metadata, never credentials, payloads or raw provider errors.
- Limit metric dimensions to the fixed vocabulary.

### Quota and capacity

- Apply quota only to new work inside the intake transaction.
- Replay/conflict and bounded inspection must remain usable at capacity.

### Business routes

- The business route service validates an explicitly ACTIVE PostgreSQL v4 or v5
  target; owner preparation upgrades through v5. M1 continues on SQLite.
- Actor/scope and signing credentials come from trusted configuration.
- Session grants bind room, participant, original request/key and optional owned task.
- Metadata from a participant is inert.
- No model function can prepare or confirm a quote.
- Use an exact opaque canonical proposal from a fresh projection.
- Preserve decimal BIGINT fields.

### Inference modes and provider keys

- Trusted inference modes are exactly scripted (default), local_real and provider_real.
- Preserve the selected mode through mint, native readiness, numeric usage and
  sanitized traces.
- A configured badge or process health is not actual inference/media qualification.
- No silent provider/model fallback exists.
- All modes preserve bound tools and separate exact human confirmation.
- Read the [provider operations guide](../../docs/provider-demo.md) before changing
  provider composition.
- Offline validation must not read private key values or invoke providers.
- Never source, print, copy or include `local-setup/.env.providers` in reports or
  build contexts.
- Only the explicit native provider runtime receives the three keys.
- The trusted mode enum is startup-only.
- Mint the mode from settings, and reject request extras.
- The API must never receive provider keys.
- The API must never infer confirmation from model output.
- The API must never expose a profile selector in a business request.

## Verification

From the repository root:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_control_api.py' -v
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh
```

| Check | Command | When to run |
| --- | --- | --- |
| Control API tests | `.venv/bin/python -m unittest discover -s tests -p 'test_control_api.py' -v` | First, for every change |
| Full fast validation | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh` | Before handoff |

Test `tests/test_business_api.py`, `tests/test_session_grants.py` and
`tests/test_quote_reader.py` as well.

## Handoff

- Record the interface change, exact validation, observed result and remaining limits.
- Keep transport, intake and model evidence separate.
