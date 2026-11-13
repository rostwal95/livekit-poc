# Local control API

Status: Active
Last reviewed: 11 November 2026

## Overview

Provide authenticated local HTTP boundaries for preserved M1 intake, explicitly
enabled PostgreSQL business work, scoped current-case observations and room-scoped
media invocation grants. Independent workers own execution; this service does not
schedule durable work or establish supplier truth.

## Implementation status

The default profile provides health/readiness, short-lived room tokens, named
diagnostic-agent dispatch and SQLite M1 investigation intake. The opt-in business
profile adds atomic managed admission on ACTIVE PostgreSQL v4, authenticated full
current-case projections with bounded recent history, trusted quote preparation,
exact human confirmation, business cancellation and signed native-session grants.
Production identity and independent durable worker scheduling remain outside this
service. The [Phase G work item](../../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md)
owns combined local qualification rather than a full product release claim.

The protected /api/metrics endpoint exports bounded-label Prometheus counters,
request duration and inflight work. Every HTTP response has an internally generated
X-Request-ID. Safe error envelopes add code/retry hints and logs exclude credentials
and submitted payloads. Metrics reset on restart and are not durable business state.
See [observability](../../docs/observability.md) for the exact contract.

### Durable business workspace

The opt-in business profile installs /api/business/investigations, scoped case
GET with bounded cursor/limit, and quote/signal/cancel commands. POST
/api/business/session mints a five-minute signed room/participant binding and a
room-scoped LiveKit token. The invocation UUID is frozen across unknown mint or
initial-connect acknowledgement; explicit media End starts a later invocation
in a fresh room/participant for the same task. Bodies cannot supply
scope/actor/provider/price or inference mode. P1_CONVERSATION_INFERENCE is a
trusted startup setting accepting only scripted (default), local_real or provider_real; unknown
values fail startup. The response mode comes from that setting and keeps the
same named worker. Native matching mode/readiness still gates controls; minting
credentials does not prove that a model ran.
GET returns current state plus recent persisted observations, with truncation and
cursor-reset disclosure. Decimal strings preserve BIGINT versions/revisions.
Exact confirmation forwards the original opaque canonical quote JSON unchanged;
a model tool cannot prepare or approve a quote. Commands return a receipt and a
freshly read projection; a newer projection does not undo a prior command receipt.
Native continuity hints request a scoped GET and carry no persisted state authority.

Use the [conversation guide](../../docs/conversation-and-showcase.md) for setup,
consent, failure reconciliation and evidence. Business startup needs an explicitly
prepared ACTIVE v4 schema and separate existing supplier/receiver fixtures. The
normal API and existing M1 records remain independently available.


## Documentation

Read [AGENTS.md](AGENTS.md), [Design.md](Design.md), the [shared design](../../Design.md), and the [local setup guide](../../local-setup/README.md).

## Requirements

Install the root local extra. Configure LIVEKIT_URL, LIVEKIT_PUBLIC_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LOCAL_ACCESS_TOKEN, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD and INTAKE_DATABASE through the local setup. Never embed credentials in the browser bundle.

## Commands

Use the local setup lifecycle for the composed stack. The container process entry is:

```sh
uvicorn services.control_api.app:app --host 0.0.0.0 --port 8080
```

Run it from the repository root in the installed environment with the required configuration. The local setup supplies those values; do not source untrusted shell configuration.

The optional provider_real profile changes only trusted native composition and
its minted mode. The API receives no model-provider keys, request-selected mode,
provider endpoint or new business authority. The [provider guide](../../docs/provider-demo.md)
owns setup and pending actual qualification; configured readiness does not prove
recognition, generation or browser playback.

## Validation

From the repository root:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_control_api.py' -v
```

Run the affected business/session/quote tests as well when changing the opt-in
boundary. Unit adapters establish only their declared assertions. Real PostgreSQL,
installed runtime, browser WebRTC and inspected trace evidence run in separate
lanes documented in the [conversation guide](../../docs/conversation-and-showcase.md).
The default local smoke remains the transport/M1 compatibility lane.

## Next milestone

Use the measured
[H1 seeded inquiry baseline](../../docs/work-items/0014-p1-phase-h-workload-baseline.md)
alongside the passed H2 restart/slow-dependency/saturation/shutdown study.
P1 V1 is qualified for the local POC using provider_real v2. local_real remains unqualified and all 17 P2 and remaining 14 P3 rows remain planned alongside three passing registered P3 lab rows. P1-I26 isolated
host/Linux artifacts, independent API/failure review and genuine native consumer
have passed, with details in the package work item. Both real profiles are implemented. The selected provider_real v2 gate passed both actual browser cases with cleanup. P1 V1 is qualified for the local POC using provider_real v2. The optional local_real profile remains unqualified. Remote CI and publishing are
outside this local POC scope; production identity remains separate.
