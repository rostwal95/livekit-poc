# Local control API

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Explain what the local control API provides and how to configure, run and validate it |
| Audience | Engineers who run or change the control API; coding agents |
| Scope | The `services/control_api` HTTP service; excludes durable worker scheduling, supplier truth and production identity |
| Owns | Control API runtime behavior, configuration, commands and validation |
| Related | [Design](Design.md) · [Agent instructions](AGENTS.md) · [Shared design](../../Design.md) · [Local setup](../../local-setup/README.md) · [Conversation guide](../../docs/conversation-and-showcase.md) |

## Overview

The control API provides authenticated local HTTP boundaries for:

- the preserved M1 intake, which is the existing confirmed-investigation intake on SQLite;
- explicitly enabled PostgreSQL business work;
- scoped current-case observations;
- room-scoped media invocation grants.

Independent workers own execution. This service does not schedule durable work
or establish supplier truth.

This README is for engineers who run or change the API. [Design.md](Design.md)
explains its design, limits and failure handling.

### Terms

| Term | Meaning |
| --- | --- |
| M1 | The existing confirmed-investigation intake, preserved on SQLite |
| Phase G | The P1 conversation and showcase phase |
| P1 V1 | The fixed first-version P1 scope |
| POC | Proof of concept |
| BIGINT | 64-bit integer |

## Implementation status

| Capability | Status | Evidence |
| --- | --- | --- |
| Health and readiness checks (default profile) | Implemented | Service unit tests; default local smoke |
| Short-lived room tokens (default profile) | Implemented | Service unit tests; default local smoke |
| Named diagnostic-agent dispatch (default profile) | Implemented | Service unit tests; default local smoke |
| SQLite M1 investigation intake (default profile) | Implemented | Service unit tests; default local smoke |
| Atomic managed admission on ACTIVE PostgreSQL v4 (business profile) | Qualified | [Phase G work item](../../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md) combined local gate |
| Authenticated full current-case projections with bounded recent history (business profile) | Qualified | Phase G combined local gate |
| Trusted quote preparation (business profile) | Qualified | Phase G combined local gate |
| Exact human confirmation (business profile) | Qualified | Phase G combined local gate |
| Business cancellation (business profile) | Qualified | Phase G combined local gate |
| Signed native-session grants (business profile) | Qualified | Phase G combined local gate |
| Metrics, request IDs and safe errors | Implemented | Service unit tests; [observability contract](../../docs/observability.md) |
| P1 V1 for the local POC using `provider_real` v2 | Qualified | The selected `provider_real` v2 gate passed both actual browser cases with cleanup |
| Optional `local_real` profile | Not qualified | Implemented; remains unqualified |
| P1-I26 isolated host/Linux artifacts, independent API/failure review and genuine native consumer | Qualified | Passed; details in the [package work item](../../docs/work-items/0016-p1-standalone-package.md) |

The provider qualification above is retained checkpoint evidence. A fresh P1-20
run after the v5 upgrade remains open, as recorded in the
[current qualification guide](../../docs/qualification-gates.md).

Both real profiles are implemented. Production identity and independent durable
worker scheduling remain outside this service. The Phase G work item owns
combined local qualification rather than a full product release claim.

### Metrics, request IDs and errors

| Signal | Behavior |
| --- | --- |
| `/api/metrics` | Protected endpoint that exports bounded-label Prometheus counters, request duration and in-flight work |
| Metric lifetime | Metrics reset on restart and are not durable business state |
| `X-Request-ID` | Internally generated on every HTTP response |
| Error envelope | Safe; adds code and retry hints |
| Logs | Exclude credentials and submitted payloads |
| `ApiError` detail | An object or list detail stays JSON, for example the readiness failure (HTTP 503) detail `{"status":"not_ready","dependencies":{...}}` |
| Framework HTTP errors | Keep their fixed text |

See [observability](../../docs/observability.md) for the exact contract.

### Durable business workspace

The opt-in business profile installs these routes:

| Route | Behavior |
| --- | --- |
| `POST /api/business/investigations` | Atomic managed investigation admission |
| `GET /api/business/cases/{task_id}` | Scoped case read with a bounded cursor and limit |
| `POST /api/business/cases/{task_id}/quote` | Trusted quote preparation command |
| `POST /api/business/cases/{task_id}/signal` | Exact confirmation signal command |
| `POST /api/business/cases/{task_id}/cancel` | Business cancellation command |
| `POST /api/business/session` | Mints a five-minute signed room/participant binding and a room-scoped LiveKit token |

**Media invocations.** The invocation UUID is frozen across an unknown mint or
initial-connect acknowledgement. An explicit media End starts a later
invocation in a fresh room and participant for the same task.

**Trusted inputs and inference mode.** Request bodies cannot supply scope,
actor, provider, price or inference mode. The response mode comes from the
trusted `P1_CONVERSATION_INFERENCE` startup setting (see [Settings](#settings))
and keeps the same named worker. Native matching mode and readiness still gate
the controls: minting credentials does not prove that a model ran.

**Case reads.** `GET` returns the current state plus recent persisted
observations, with truncation and cursor-reset disclosure. Decimal strings
preserve BIGINT (64-bit integer) versions and revisions.

**Commands and confirmation.** Exact confirmation forwards the original opaque
canonical quote JSON unchanged. A model tool cannot prepare or approve a quote.
Commands return a receipt and a freshly read projection. A newer projection does
not undo a prior command receipt.

**Continuity hints.** Native continuity hints request a scoped `GET` and carry
no persisted state authority.

Use the [conversation guide](../../docs/conversation-and-showcase.md) for setup,
consent, failure reconciliation and evidence. The normal API and existing M1
records remain independently available.

## Documentation

| Document | Purpose |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Coding rules for this service |
| [Design.md](Design.md) | Design, limits and failure handling |
| [Shared design](../../Design.md) | Ecosystem data flow and authority |
| [Local setup guide](../../local-setup/README.md) | Stack lifecycle and smoke checks |
| [Conversation guide](../../docs/conversation-and-showcase.md) | Business profile setup, consent, failure reconciliation and evidence lanes |
| [Provider operations guide](../../docs/provider-demo.md) | Provider profile setup and qualification |
| [Observability](../../docs/observability.md) | Exact metrics, request ID and error contract |

## Requirements

| Requirement | Version or value | Notes |
| --- | --- | --- |
| Python dependencies | Root `local` extra | Installed by the root `make bootstrap` |
| LiveKit endpoints and credentials | `LIVEKIT_URL`, `LIVEKIT_PUBLIC_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | Configured through the local setup |
| Local operator bearer token | `LOCAL_ACCESS_TOKEN` | Configured through the local setup |
| PostgreSQL connection | `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Configured through the local setup |
| M1 SQLite intake database | `INTAKE_DATABASE` | Configured through the local setup |
| Business profile startup | An explicitly prepared ACTIVE v4 or v5 schema and separate existing supplier and receiver fixtures | `prepare-business` upgrades through v5; `start-business` performs read-only preflight |

Never embed credentials in the browser bundle.

### Settings

| Option | Default | Allowed values | Description |
| --- | --- | --- | --- |
| `P1_CONVERSATION_INFERENCE` | `scripted` | `scripted`, `local_real`, `provider_real` | Trusted startup setting for the minted inference mode; unknown values fail startup |

## Commands

| Task | Command | Notes |
| --- | --- | --- |
| Run the composed stack | [Local setup lifecycle](../../local-setup/README.md) | Supplies the required configuration |
| Start the API process | `uvicorn services.control_api.app:app --host 0.0.0.0 --port 8080` | Container process entry; run from the repository root in the installed environment |

Use the local setup lifecycle for the composed stack. The container process entry is:

```sh
uvicorn services.control_api.app:app --host 0.0.0.0 --port 8080
```

Run it from the repository root in the installed environment with the required
configuration. The local setup supplies those values. Do not source untrusted
shell configuration.

### Optional provider profile

The optional `provider_real` profile changes only the trusted native composition
and its minted mode. The API receives no model-provider keys, request-selected
mode, provider endpoint or new business authority. The
[provider guide](../../docs/provider-demo.md) owns setup and qualification.
Configured readiness does not prove recognition, generation or browser playback.

## Validation

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Service unit tests | `.venv/bin/python -m unittest discover -s tests -p 'test_control_api.py' -v` | Only the declared unit-adapter assertions | Required per change |
| Opt-in boundary tests | Affected business, session and quote tests, listed in [AGENTS.md](AGENTS.md) | The changed opt-in business boundary | Required when changing the opt-in boundary |
| Business evidence lanes | Separate lanes in the [conversation guide](../../docs/conversation-and-showcase.md) | Real PostgreSQL, installed runtime, browser WebRTC and inspected trace evidence | Required for affected changes |
| Default local smoke | [Local setup](../../local-setup/README.md) smoke checks | The transport and M1 compatibility lane | Required for affected changes |

From the repository root:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_control_api.py' -v
```

Unit adapters establish only their declared assertions. Real PostgreSQL,
installed runtime, browser WebRTC and inspected trace evidence run in separate
lanes, and the default local smoke remains the transport and M1 compatibility
lane.

## Next milestone

| Step | Outcome | Gate |
| --- | --- | --- |
| Repeat affected API and PostgreSQL gates after changes | Fresh evidence for the changed boundary | Service tests and applicable durable lanes |
| Rerun P1-20 after the v5 upgrade with the approved certificate bundle | Current provider-media evidence | [Provider guide](../../docs/provider-demo.md) |

| Open or out-of-scope item | Status |
| --- | --- |
| Optional `local_real` profile | Not qualified |
| All 17 P2 rows and the remaining 14 P3 rows | Planned, alongside three passing registered P3 lab rows |
| Remote CI and publishing | Outside this local POC scope |
| Production identity | Remains separate |
