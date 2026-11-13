# Local control API coding instructions

Status: Active
Last reviewed: 9 November 2026

## Read first

Read [root instructions](../../AGENTS.md), [README.md](README.md), [Design.md](Design.md) and the [validation plan](../../docs/validation-plan.md).

## Owned paths

Own services/control_api and tests/test_control_api.py. Preserve the shared SDK/transport and M1 boundaries.

## Development rules

Use typed requests, bounded work and explicit lifecycle cleanup. Keep credentials out of logs and responses. Do not add provider calls to deterministic diagnostics or infer business authority from transport success. New behavior needs a normal case and a meaningful failure case.

Keep the error-code/retry envelope stable, generate request IDs internally and
limit metric dimensions to the fixed vocabulary. Log safe operation metadata,
never credentials, payloads or raw provider errors. Propagate cancellation and
fatal exceptions. Apply quota only to new work inside the intake transaction;
replay/conflict and bounded inspection must remain usable at capacity.

Trusted inference modes are exactly scripted (default), local_real and
provider_real. Preserve the selected mode through mint, native readiness, numeric
usage and sanitized traces. A configured badge or process health is not actual
inference/media qualification. No silent provider/model fallback exists. All modes
preserve bound tools and separate exact human confirmation. Read the
[provider operations guide](../../docs/provider-demo.md) before changing provider composition.
Offline validation must not read private key values or invoke providers. Never
source, print, copy or include local-setup/.env.providers in reports or build
contexts. Only the explicit native provider runtime receives the three keys.

The trusted mode enum is startup-only. Mint it from settings; reject request extras. The API must never receive provider keys, infer confirmation from model output or expose a profile selector in a business request.

## Verification

From the repository root:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_control_api.py' -v
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh
```

## Handoff

Record the interface change, exact validation, observed result and remaining limits. Keep transport, intake and model evidence separate.

Business routes live in business.py and business_dispatch.py. Their service uses
explicit PostgreSQL v4; M1 continues on SQLite. Test tests/test_business_api.py,
test_session_grants.py and test_quote_reader.py as well. Actor/scope and signing
credentials come from trusted configuration. Session grants bind room, participant,
original request/key and optional owned task; metadata from a participant is inert.
No model function can prepare or confirm a quote. Use an exact opaque canonical
proposal from a fresh projection and preserve decimal BIGINT fields.
