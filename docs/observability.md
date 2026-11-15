# Observability and failure handling

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Describe each observable signal of the local POC, what it means, its bounds and which signals remain planned |
| Audience | Engineers who add or change a producer, investigate a failure or judge what telemetry proves |
| Scope | Metrics, structured logs, traces and safe errors from every component; ports, credentials and test lanes are owned elsewhere |
| Owns | Current/future signals, safe errors, cardinality and operational evidence |
| Related | [Local setup guide](../local-setup/README.md) · [Validation plan](validation-plan.md) · [Root design](../Design.md) · [Python engineering](python-engineering.md) · [Demo plan](demo-plan.md) |

## Overview

This document describes the observable signals of the local proof of concept
(POC). It covers the metrics, structured logs, traces and error responses that
each component produces, what each signal means, its labels and bounds, and
which signals are still planned. It is for engineers who add or change a
producer, investigate a failure, or need to judge what a piece of telemetry
proves.

Keep these points in mind when reading the producer sections:

- Implemented producers are grouped by component. Planned instrumentation and
  rollout steps have their own sections near the end.
- Most producers are process-local. Their values reset when the owning process
  restarts. They are operational evidence, not the durable business record.
- Metrics, logs and traces are diagnostic observations. The durable authorities
  and the independent supplier and receiver records remain the source of
  business truth.
- A configured producer, a reachable UI or a placeholder counter qualifies
  nothing. Each section names the work item that owns the actual evidence.

The [local setup guide](../local-setup/README.md) owns ports and credential
handling. The [validation plan](validation-plan.md) owns test lanes and release
evidence.

Contents:

| Section | Covers |
| --- | --- |
| [Signal inventory](#signal-inventory) | Every producer group with its fields or labels and status |
| [Rules for every signal](#rules-for-every-signal) | Label, redaction, export, retention and missing-signal rules |
| [Self-hosted and managed LiveKit observability](#self-hosted-and-managed-livekit-observability) | Why local producers stand in for managed Agent insights |
| [Control API](#control-api) | HTTP metrics, request logs, readiness and local inspection |
| [Error contract](#error-contract) | The safe error envelope and expected caller behavior |
| [Diagnostic worker events](#diagnostic-worker-events) | The `rtc-agent` application logger |
| [P1 agent continuity producers](#p1-agent-continuity-producers) | Phases A to G, inference profiles, startup diagnostics and the work profile |
| [P1 inquiry workload measurement](#p1-inquiry-workload-measurement) | Phase H1 measurement semantics |
| [P2 channel continuity producers](#p2-channel-continuity-producers) | Channel Continuity Kit producers, by the work item that added them |
| [P3 delegation reliability producers](#p3-delegation-reliability-producers) | Delegation Reliability Kit producers, by the work item that added them |
| [Joined application](#joined-application) | Executor and lifetime observations of the joined composition |
| [Planned product instrumentation](#planned-product-instrumentation) | Planned events, spans, metrics and dimensions (planned) |
| [Rollout and operational policy](#rollout-and-operational-policy) | Rollout steps and minimum demonstration evidence |
| [Verification and limits](#verification-and-limits) | Test coverage, final provider trace evidence and qualification status |

## Signal inventory

Each row links to the section that defines the signal. Status uses the
implementation vocabulary in the
[documentation standards](documentation-standards.md#implementation-status-vocabulary):
a Qualified producer belongs to a capability that passed the named selected
gate. A qualified signal is still a diagnostic observation, not business truth.

| Signal | Producer | Fields or labels | Status |
| --- | --- | --- | --- |
| [HTTP metrics](#http-metrics) | Control API `GET /api/metrics` | Fixed operation, method and status class | Implemented |
| [Request logs](#request-identifiers-and-logs) | Control API | UTC timestamp, fixed operation and method, status, duration and `X-Request-ID` | Implemented |
| [Readiness](#readiness-responses) | Control API `GET /readyz` | `dependency_unavailable` with a per-dependency `detail` object | Implemented |
| [Safe error envelope](#error-contract) | Control API | `detail`, `code`, `retryable`, `retry_hint` and `request_id` | Implemented |
| [Diagnostic worker events](#diagnostic-worker-events) | `services/rtc_agent` application logger | `service=rtc-agent`, timestamp, severity, event, code and bounded counts | Implemented |
| [Inquiry foundation events](#inquiry-foundation-events-phases-a-and-b) | Execution CLI, supplier and worker loggers | Service, timestamp, severity, event and code | Qualified (P1 V1) |
| [Cutover events](#postgresql-cutover-events-phase-c) | Phase C cutover, import and authentication | Fixed events such as `source_cutover`; finite API labels | Qualified (P1 V1) |
| [Case operation metrics](#case-application-telemetry) | `CaseTelemetry` private registry | `operation` (16 values) and `outcome` (3 values) | Qualified (P1 V1) |
| [Effect, cancellation and delivery events](#effect-cancellation-and-delivery-events-phase-e) | Case service logger and private registry | Registered event and code values; three outcomes | Qualified (P1 V1) |
| [Worker and lease telemetry](#worker-and-lease-telemetry-phase-f) | Worker runtime private registry and snapshots | Finite claim outcomes, four step kinds and three lease error codes | Qualified (P1 V1) |
| [Native session readiness](#native-session-readiness-phase-g) | Native agent and UI | `continuity.session_ready=true` and active SDK state | Qualified (P1 V1) |
| [Native session usage and reports](#native-session-usage-and-reports-phase-g) | Native `AgentSession` | Numeric LLM tokens, STT and TTS durations and TTS characters | Qualified (P1 V1) |
| [Trace export](#trace-export) | Application and native SDK over OTLP to local Jaeger | Allowlisted operation, model and tool enums; task and effect UUIDs | Qualified (Phase G gate) |
| [Local real-inference observations](#local-real-inference-observations) | ASR and TTS `/metrics`, SDK usage, OTLP and browser | Fixed engine, request counts, bytes, durations and inference mode | Not qualified |
| [Provider-real observations](#provider-real-profile) | Native SDK usage and sanitized OTLP copies | `gen_ai.provider.name` and exact model IDs | Qualified (provider_real v2) |
| [Startup and acceptance diagnostics](#startup-and-acceptance-diagnostics) | Native startup, host media helper, failure aggregation and session mint | Six fixed startup codes; finite categories, counts and durations | Qualified (P1 V1) |
| [Work profile producers](#work-profile-producers) | P1 work profile, result receiver and guarded action | Fixed operation and code values; `pending` and `telemetry_failures` | Qualified (selected 0028 to 0032 gates) |
| [Inquiry workload records](#p1-inquiry-workload-measurement) | H1 workload runner | Bounded JSONL HTTP, resource, queue, result and observer records | Qualified (H1 local baseline) |
| [Standalone intake helper](#standalone-intake-helper) | P2 standalone helper | `activePreviews`; fixed `StandaloneError` codes | Qualified (selected 0027 gates) |
| [Persisted dispatch](#persisted-dispatch) | `DispatchObservation` and `ChannelDispatcher` | Fixed event and code values; claim epochs and attempt history | Qualified (selected 0028 gates) |
| [Gateway](#gateway) | P2 gateway | Fixed HTTP, poll and close events; process-local counters | Qualified (selected 0029 gates) |
| [Agent process](#agent-process) | `AgentProcess` | Worker counts, slot gauges and started and settled events | Qualified (selected 0030 gates) |
| [Revision routing](#revision-routing) | `RevisionRouter`, case authority clients and the Python bridge | Fixed `case_routing` and `p2_case_bridge` codes | Qualified (selected 0031 gates) |
| [Linked confirmation](#linked-confirmation) | `ConfirmationRouter`, `PromptRegistry` and `ConfirmationHttpClient` | Fixed `confirmation_routing` codes | Qualified (selected 0032 gates) |
| [Outbox and fake SMS carrier](#outbox-and-fake-sms-carrier) | `ChannelOutbox` and `FakeSmsSendClient` | Fixed `channel_outbox` events; control and send counters | Qualified (selected 0033 gates) |
| [Send recovery counters](#send-recovery-counters) | `ChannelOutbox` recovery path | Recovery, retry, lookup and veto counters | Qualified (selected 0035 gates) |
| [Callback inbox](#callback-inbox) | `CallbackInbox` | Fixed `channel_callbacks` events; `CallbackError` codes | Qualified (selected 0034 gates) |
| [Native input](#native-input) | Native runtime, SDK log sanitizer and browser | Eighteen native metrics; six-key `p2.generation` observations | Qualified (selected 0036 gates) |
| [Response and playback evidence](#response-and-playback-evidence) | Communication store, gateway, Python capture and browser | Fixed cumulative counters; eight-key `p2.response` wire | Qualified (selected 0037 gates) |
| [Read-only context rehydration](#read-only-context-rehydration) | P2 facade, context listener, Python client, SDK profile and browser | Numeric outcome and ownership fields | Qualified (selected 0038 gates) |
| [Ordinary inbox observers and workload study](#ordinary-inbox-observers-and-workload-study) | Ordinary inbox and the P2 study | `observerPending`, `observerDropped` and `observerFailures`; process maxima | Qualified (selected 0039 gates) |
| [Operations reader and collector](#operations-reader-and-collector) | P2 operations reader, collector and optional page | Finite outcomes, 76 cause codes and typed HTTP error codes | Qualified (selected 0040 gates) |
| [Specialist HTTP service](#specialist-http-service) | `delegation_specialist` Node producer | Fixed event, operation and code; fixed metric names | Qualified (selected 0027 gates) |
| [Coordinator and Python HTTP client](#coordinator-and-python-http-client) | P3 coordinator and Python HTTP client | `delegation_port` operation, outcome and code | Qualified (selected 0028 gates) |
| [Issued runner](#issued-runner) | P3 runner | `delegation_run` operation, code and outcome | Qualified (selected 0029 gates) |
| [Completion and action adapters](#completion-and-action-adapters) | P3 completion and action adapters | `delegation_completion` operation, code and outcome | Qualified (selected 0030 gates) |
| [Result projection](#result-projection) | `ProjectionClient` and `ProjectionProjector` | Process counts; durable checkpoint and rows | Qualified (selected 0032 gates) |
| [Registered lab acceptance wrappers](#registered-lab-acceptance-wrappers) | P3-01, P3-03 and P3-11 wrappers | Named assertion inventories, case, mode, count, duration and cleanup | Qualified (registered lab rows) |
| [Completion processing](#completion-processing) | `ProcessingClient` and `CompletionProcessor` | Fixed `result_projection` logs; row and ACK counters | Qualified (selected 0033 gates) |
| [Applicability refresh](#applicability-refresh) | `ApplicabilityClient` and `ApplicabilityRefresher` | Refresh and reconciliation counters; `ProjectionError` codes | Qualified (selected 0034 gates) |
| [Protected action authorizer](#protected-action-authorizer) | P3 authorizer | Operation counts plus reconciled observations and active calls | Qualified (selected 0035 gates) |
| [Deadline and cancellation validation](#deadline-and-cancellation-validation) | Validation composition only; no new producer | Existing runner, HTTP and completion metrics | Qualified (selected 0036 gates) |
| [Process recovery fixtures](#process-recovery-fixtures) | P3 recovery fixtures | Finite stage, code and type; PID, return code and receipt joins | Qualified (selected 0037 gates) |
| [Standalone package gate](#standalone-package-gate) | P3 package gate | Eight offline and eight actual assertions; finite stage and code | Qualified (selected 0038 gates) |
| [Document extraction producers](#document-extraction-producers) | `DocumentHandler`, PNG decoder and shared image transport | Provider and worker counters; finite capability, operation and error vocabulary | Qualified (selected 0039 gates) |
| [Fixed-policy HTTP client and handler](#fixed-policy-http-client-and-handler) | P3 TypeScript HTTP client and fixed-policy handler | Finite transport, validation and rule outcomes | Qualified (selected 0040 gates) |
| [Joined application](#joined-application) | Joined application executor | Finite scan, job and close events; aggregate source-read and HTTP lifetime counts | Implemented |
| [Planned project instrumentation](#planned-product-instrumentation) | P1, P2 and P3 product producers | Fixed environment, service, capability, outcome and error-code dimensions | Planned |

## Rules for every signal

The following rules apply across producers:

- Request, case, tenant, room, task, delegation and effect identifiers must
  never become metric labels. Use bounded structured logs and traces for
  correlation instead.
- Redact at the producer. Restrict access to metrics and traces, and keep local
  endpoints on loopback.
- Bound exporter queues, retries, buffers and shutdown.
- Decide data retention and replay horizons before cleanup. Display-history
  pruning must not erase effect or idempotency protection.
- Document any missing signal as unavailable.

## Self-hosted and managed LiveKit observability

This POC runs its own media server. LiveKit's managed Agent insights requires a
LiveKit Cloud project and media connection, and it does not cover an entirely
self-hosted stack. Local API metrics, application counters and optional Jaeger
traces are therefore the actual producers. A LiveKit-like timeline in the
console must not be labelled as the managed Agent insights product. See the
official [observability overview](https://docs.livekit.io/testing/observability/)
and [availability](https://docs.livekit.io/testing/observability/insights/)
pages.

## Control API

### Metrics endpoint

The control API exposes `GET /api/metrics` in Prometheus text format, protected
by the operator bearer token. Each application instance owns a private registry
without the default process and garbage-collection (GC) collectors. Its counters
reset when the process restarts. They are operational evidence, not the durable
business record. No Prometheus or Grafana server is required for the local
foundation.

In the business profile, the same endpoint also renders the P1 case registry
described in [Case application telemetry](#case-application-telemetry).

### Request identifiers and logs

Every control API HTTP response carries an internally generated `X-Request-ID`.
Incoming values cannot select the identifier. Completion and error logs are
structured JSON:

| Log content | Fields |
| --- | --- |
| Included | A UTC timestamp, fixed operation and method, status, duration and request ID |
| Excluded | Request bodies, query strings, headers, model prompts, transcripts, room names, booking references and provider exception messages |

### HTTP metrics

| Metric | Measurement | Labels |
| --- | --- | --- |
| `livekit_control_http_requests_total` | Completed API requests | Fixed operation, method and status class |
| `livekit_control_http_errors_total` | Requests ending in a 4xx or 5xx status | Same fixed vocabulary |
| `livekit_control_http_request_duration_seconds` | End-to-end duration histogram at the Asynchronous Server Gateway Interface (ASGI) layer | Fixed operation and method |
| `livekit_control_http_requests_in_flight` | Currently active API requests | Fixed operation and method |

The operation label has a fixed vocabulary. The business profile adds the
`business_submit`, `business_get`, `business_quote`, `business_signal`,
`business_cancel` and `business_session` operations. Unknown paths share one
unknown-operation label, so arbitrary URLs cannot create new series.

Health, readiness and metrics scrapes are excluded from business counters and
successful request logs. Their failures remain diagnosable.

### Readiness responses

`GET /readyz` probes the actual dependencies: PostgreSQL and the LiveKit server.
When any probe fails, it returns HTTP 503 with the code `dependency_unavailable`.
The error's `detail` is then a JSON object rather than text, for example
`{"status":"not_ready","dependencies":{"postgres":false,"livekit":true}}`. This
structured `detail` applies to the application's own errors, which pass an
object or list through unchanged. Framework HTTP errors keep their fixed
sanitized text, such as `Local service unavailable` for a framework 503.

### Inspecting metrics locally

For local inspection, retrieve the operator token explicitly with the setup
manager. Then request `/api/metrics` with the token in the `Authorization`
header. Keep the token out of URLs, screenshots, shell tracing and saved
diagnostics. The [local guide](../local-setup/README.md) owns ports and
credential handling.

## Error contract

The control API returns expected errors in one safe envelope. The categories
below state how callers should react.

### Response envelope

Expected errors keep the existing `detail` field and add `code`, `retryable`,
`retry_hint` and `request_id`. An application error's `detail` can be text, a
list or an object, as the [readiness response](#readiness-responses) shows.
Validation errors keep a `detail` list but omit submitted values, private
context and unknown field names. Responses keep only relevant allowlisted HTTP
headers, such as `Retry-After` and `WWW-Authenticate`.

### Error categories

| Category | Example codes | Caller behavior |
| --- | --- | --- |
| Input or permission | `authentication_required`, `validation_error`, `forbidden` | Correct the credentials or input. Do not repeat automatically. |
| Changed-payload replay | `idempotency_conflict` | Keep the original payload and key, or deliberately create a new logical request. |
| Admission or rate | `capacity_exhausted`, `rate_limited` | Honor retry hints within the caller deadline. Never claim acceptance before acknowledgement. |
| Dependency or storage | `dependency_unavailable`, `dispatch_unavailable`, `storage_unavailable` | Inspect dependency health. Reconcile any possibly accepted request using the same identity. |
| Unexpected boundary failure | `internal_error` | The API returns a sanitized 500 and the request ID. Inspect before retrying. The exception text is never exposed. |
| Cancellation | `request_cancelled` or `client_disconnected` in logs | Propagate cancellation. Keep held I/O capacity until already-started work actually finishes. |

### Disconnects and admission capacity

A disconnected client that receives no response is recorded as a local 499
observation. It is not a server failure or an attempted response. The admission
quota for new work is checked inside the SQLite write transaction. Replay,
conflict handling and bounded inspection remain available at capacity.

### Retries and unknown outcomes

A retryable transport or service error is not permission to repeat a supplier
effect. A timeout can happen after persistence. The UI therefore keeps the same
request identity and displays an unknown outcome until an acknowledgement or a
replay resolves it.

Business execution outcome, result applicability, delivery evidence and user
acknowledgement remain distinct. Phase G exposes the durable P1 outcome and
delivery states. P2 result applicability, channel delivery and human
acknowledgement keep their own requirement and evidence boundaries.

## Diagnostic worker events

The diagnostic transport worker (`services/rtc_agent`) has its own application
logger, separate from product workers.

### Application logger

The diagnostic worker explicitly configures a dedicated application logger at
job admission and session entry. JSON records contain the fixed
`service=rtc-agent`, a UTC timestamp, severity, event and code, plus optional
bounded integer task and track counts. Module import does not attach handlers or
modify the root logger or the native software development kit (SDK) logger.
Repeated entry callbacks reuse one application-owned handler.

The configuration uses a local `StreamHandler`. This is not a claim that stdout
or a future exporter cannot block. Deployment log throughput needs its own
budget.

### Events

| Producer | Event and codes | Meaning |
| --- | --- | --- |
| Admission policy | `job_rejected` with `invalid_room` or `job_capacity` | Local decision to refuse the job, not a business outcome |
| Session boundary | `session_started`, `session_failed`, `session_finished` | Accepted session lifecycle, with a safe type-only error category and the disconnect, duration, cancel or failure reason |
| Stream policy | `stream_rejected` with `invalid_source`, `task_capacity` or `audio_capacity` | Actual local admission rejection, with bounded counts where relevant |
| Owned task completion | `task_completed`, `task_failed` or `task_cancelled` | Retrieved real task outcome. Expected input or timeout failures differ from transport or unexpected failures. Cancellation is informational. |

### Exclusions, tests and inspection

These records exclude text, identities, rooms, track IDs, credentials, raw
exceptions, their representations and exception chains. Native SDK logs keep
their separate configuration and review boundary; this helper does not certify
all SDK output. There is no worker-specific metrics endpoint, trace exporter or
new durable state.

Existing transport tests plus telemetry fixtures exercise real task and callback
producers, safe JSON, handler and context isolation, and propagation. Actual
stack smoke inspects runtime producers separately. The diagnostic path does not
establish browser playback; the separate Phase G scripted business-media gate
does.

The local manager (`local-setup/stack.py`) supports `logs --service rtc-agent`
to inspect this producer within its existing bounded, redacted tail. Logging
commands preserve both child output streams. Combined output can omit earlier
events from another service, so absence from the combined tail does not prove
absence at the producer.

## P1 agent continuity producers

P1 producers belong to the `continuity_lab` package and the services that
compose it. The subsections follow the P1 delivery phases, then cover the
inference profiles, startup diagnostics and the optional work profile that
delegation integrations use. Phase H1 workload measurement has
[its own section](#p1-inquiry-workload-measurement).

### Inquiry foundation events (Phases A and B)

The execution command-line interface (CLI) explicitly configures a package
logger with safe JSON fields: service, timestamp, severity, event and code.
Library imports attach only a `NullHandler` and do not configure root logging.
Request values and raw exception chains are excluded.

| Signal | Producer | Fields or labels | Status |
| --- | --- | --- | --- |
| Acceptance, replay, attempt start and finish, and storage failure events | Execution CLI package logger | Real producer events with the safe JSON fields | Qualified (P1 V1) |
| Initialization, lookup, inquiry and replay events | Supplier, added in Phase B | Fixed event values | Qualified (P1 V1) |
| Dispatch, reconciliation and outcome events | Worker, added in Phase B | Fixed event values | Qualified (P1 V1) |
| Migration command reports | Migration commands | Schema versions | Qualified (P1 V1) |

Application CLI setup remains explicit.

| Outcome | Exit code |
| --- | --- |
| Expected error | 2, a safe exit |
| Unexpected defect | 1, a sanitized exit |

That inquiry checkpoint included no worker or provider traces and no new
Prometheus exporter. Phase F later adds actual worker snapshots. Phase G adds
the bounded local application and SDK trace integration described in
[Trace export](#trace-export).

### PostgreSQL cutover events (Phase C)

Phase C adds these producer events:

- `source_quiesced` and `source_cutover`
- `postgres_schema_installed`
- `postgres_import_staged`, `postgres_import_replayed` and
  `postgres_import_activated`
- `authentication_rejected`

The same bounded service, timestamp, severity, event and code formatter
excludes SQL, data source names (DSNs), tokens, payloads, actor and scope values,
and exception chains. Operator results deliberately include synthetic workflow
state or migration row counts. These results are distinct from logs and must
not be redirected into telemetry.

| Situation | Code |
| --- | --- |
| New write against the closed SQLite source after cutover | `source_quiesced`: a non-retryable HTTP 503 with the retry hint `use_active_execution_backend` |
| Authentication failure | `authentication_required` |
| Inaccessible identifier | `execution_not_found` |

Repeating new writes against a closed source cannot repair cutover. A cutover
failure preserves the source, backup and receipt for explicit investigation.
The PostgreSQL gate report records test counts, failures, skips and monotonic
runtime. Existing API metrics observe the exercised cutover rejection with
finite route, method and status labels.

CLI processes do not expose a persistent metrics server. At that checkpoint,
product queue, recovery and supplier instruments and OpenTelemetry Protocol
(OTLP) export were left for later real-producer work. Phases F and G now supply
the implemented worker metrics and filtered trace path. No performance, throughput
or full-tracing claim follows from these tests.

### Case application telemetry

Phase D's `CaseTelemetry` observes `ScopedCaseService` operations with a
private registry.

| Metric | Labels |
| --- | --- |
| `continuity_case_operations_total` | `operation`, `outcome` |
| `continuity_case_operation_duration_seconds` | `operation`, `outcome` |

| Label | Values |
| --- | --- |
| `operation` (Phase D) | `enroll`, `get`, `revise`, `confirm`, `arm_wait`, `signal`, `advance`, `waits`, `lifecycle`, `cancel`, `effect`, `completion`, `delivery` |
| `operation` (added by the Phase G business API) | `managed_submit`, `projection`, `prepare_quote` |
| `outcome` | `success`, `rejected`, `failed` |

At Phase D, at most 39 label combinations can exist. With Phase G, the shared
case registry has sixteen operation values and three outcomes: 48 counter and
histogram label combinations. No identifier, tenant, quote, token, raw error or
arbitrary route becomes a label, and actor, task, booking and room identifiers
never become metric labels.

Calling `render()` does not imply a persistent product HTTP exporter or a
distributed trace pipeline. Since Phase G, the control API exposes this private
registry through its existing protected metrics endpoint. Worker `.prom`
observations keep their independent lifecycle.

Case, quote and intent producers, continuation, attempt, wait and signal
producers, and upgrade producers emit safe fixed event and code values. The
public `case_operation` event adds only the validated operation and outcome.
Metrics and log failures cannot alter the business result or mask its original
error.

Unit tests check real counter and duration samples, isolation, finite labels,
privacy and outages. The actual container demo checks positive samples and
producer events. Raw operator snapshots remain separate from telemetry and use
synthetic data.

### Effect, cancellation and delivery events (Phase E)

| Area | Events |
| --- | --- |
| Mutation | `mutation_claimed`, `mutation_dispatch_reserved`, `mutation_dispatched`, `mutation_applied`, `mutation_reconciled`, `mutation_finished`, `mutation_worker_completed`, `mutation_worker_failed` |
| Cancellation | `cancellation_recorded` |
| Completion | `completion_committed`, for a successful mutation, explicit uncertainty and pre-dispatch cancellation |
| Delivery | `completion_delivery_started`, `completion_delivered`, `completion_delivery_failed`, `completion_delivery_observed` |

Not every return emits `completion_committed`. Inspect deadline, cap and
negative paths through the authoritative completion and outcome records as well.
Supplier and sink replay and diagnostic pruning also have fixed events. The
formatter permits only registered event and code values and the 13 bounded case
operations. Raw exceptions, SQL and data transfer object (DTO) payloads are
excluded.

The service's private Prometheus registry observes cancel, effect, completion
and delivery calls and their duration with the same three outcomes. Counters
describe calls, not durable booking totals. Inspect the durable records for
business facts:

| Fact | Where to inspect it |
| --- | --- |
| Dispatch and attempt counts | Protected effect snapshots |
| Known or uncertain truth | Terminal business outcomes |
| Receiver, attempts, due time and exhaustion | Delivery snapshots |

No business success is inferred from delivery or a metric sample. Phase E added
no HTTP exporter or trace pipeline. Phase G later implements the filtered local
application and SDK export and the inspected trace gate described in
[Trace export](#trace-export).

The Docker demo checks positive operation and duration samples and producer
events before each success or crash boundary. It then inspects retained supplier
and receiver records after restart. Unit tests cover malformed or private
diagnostics and logger outage. Independent-process tests preserve outcomes when
delivery fails or is exhausted. The [effects guide](effects-and-completion.md)
defines bounded retries and safe operator responses. Unresolved external effects
need review, never a blind resend.

### Worker and lease telemetry (Phase F)

Lease acquisition, renewal and release have fixed producer events and the safe
error codes `lease_busy`, `lease_lost` and `lease_required`. The worker emits
fixed events for runtime and step start and finish, release failure, health
failure and queue-observation failure. Child logs are reconstructed only from
allowlisted event and code JSON fields. Arbitrary stdout and stderr, identifiers
and exception text are dropped. An epoch is authority evidence for operator
inspection, never a metric label.

Each runtime owns a private Prometheus registry:

| Metric | Labels |
| --- | --- |
| `continuity_worker_claims_total` | Finite outcomes: `acquired`, `empty`, `stopped` |
| `continuity_worker_steps_total` | Four step kinds and finite process outcomes |
| `continuity_worker_step_duration_seconds` | Four step kinds and finite process outcomes |
| Local active-child gauge | No dynamic identity labels |
| Durable outstanding, active, limit, oldest-age and recovery-lag gauges | No dynamic identity labels |
| Lease rejection counts | Only the three fixed lease error codes |

Process completion is distinct from business success. The durable gauges mean
the following:

- Outstanding is unresolved accepted work, including waits and active work. It
  can include a manual-review inquiry uncertainty and is not the runnable queue
  length.
- Active counts current database leases.
- Recovery lag observes expired ownership for outstanding work or pending
  delivery. Completed and delivered history is excluded.

Retained core receipts and old epochs remain authoritative after a metrics
reset. Very small lease settings reduce step occupancy and are not a measured
throughput guarantee. No production latency or high-availability (HA) capacity
claim follows.

The worker writes private bounded health and Prometheus snapshots under `/tmp`.
`worker_cli health` and `worker_cli metrics` inspect them without adding an HTTP
endpoint. Readiness checks freshness and the owned process, not business
completion. Observation runs outside the active child monitor, so telemetry
cannot delay its occupancy and stop checks. Phase G subsequently adds optional
bounded worker step spans and application and native SDK traces, and the local
gate inspects raw Jaeger v3 records.

Actual process tests cover logger outage, private and oversized output, timeout,
SIGTERM and descendant cleanup. The installed demo checks real positive samples
and final durable facts separately.

### Native session readiness (Phase G)

Before native speech or control input, the public `RoomIO.wait_for_ready`
barrier finishes within its ten-second budget. The selected native agent
publishes `continuity.session_ready=true`, and the UI combines it with active
SDK state. The public `session_host=False` flag disables the alternate
`lk.agent.session` ingress, so caller and readiness checks remain on the owned
bounded controls. These are media preconditions, not business acceptance or
mutation authority.

### Native session usage and reports (Phase G)

Native `AgentSession` `session_usage_updated` events provide finite numeric
totals: large language model (LLM) tokens, speech-to-text (STT) duration, and
text-to-speech (TTS) duration and characters. After close, `make_session_report`
is called and only the duration and event count are selected. No `report.to_dict`
output, chat history, transcript, event body, provider or model label, or tags
are serialized.

Up to 32 private 4 KiB JSON observations remain under
`/tmp/conversation-observations` in the native container; a restart may remove
them. `sdk_report_observed` is false when report creation fails. This is
diagnostic retention, not a business event store or billing measurement. Local
scripted providers are not inference-quality evidence.

### Trace export

In the explicit business profile, an optional local Jaeger receives sanitized
application and native SDK traces over OTLP. The
[Phase G gate](work-items/0013-p1-phase-g-conversation-and-showcase.md) inspects
raw Jaeger v3 trace data, including the permitted attributes and correlation. A
reachable UI alone is insufficient. This is local evidence, not hosted
continuous integration (CI) or a load service-level objective (SLO).

#### Export runtime

Each trace runtime owns a private provider and these bounds:

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Span queue | 128 spans | Each trace runtime | On overload the runtime drops diagnostic observations |
| Exporter threads | One | Each trace runtime | None |
| Request size | 64 KiB | Each export request | None |
| HTTP export deadline | 0.5 seconds | Each export | Finite |
| Flush and close | Explicit deadlines | Shutdown | Shutdown does not retain business work |

The transport uses only the configured credential-free loopback or Jaeger
endpoint. It ignores ambient OTLP headers, proxies and retry settings, and it
does not read an exporter response body. Collector rejection, timeout and queue
saturation cannot rewrite an operation result.

#### Span sanitization

Exported spans copy only allowlisted operation, model and tool enums, finite
numeric counts and canonical task and effect UUIDs. They strip span events,
links, inherited trace-state headers, exception and status descriptions,
arbitrary resource and scope fields, and all content. Original SDK spans remain
unchanged.

Span attribute and event limits bound the original trace provider's memory, and
recording is disabled for audio and transcripts. The dedicated native process
sanitizes SDK console records to fixed codes. These controls do not imply that
unrestricted third-party SDK logs are safe in other profiles.

#### Trace inspection

Phase G trace inspection validates the raw Jaeger v3 resource and span
structure, the safe operation, tool and model enums, and the required task and
effect correlation. Reachability, a screenshot or a nonempty response alone
cannot pass.

A trace ID expresses diagnostic ancestry, not business authority. External
effect truth, a committed business outcome, a delivery receipt and browser
playback remain separate facts. Primary interface references:
[LiveKit tracing](https://docs.livekit.io/testing/observability/tracing/),
[session reports](https://docs.livekit.io/reference/agents/session-traces/) and
[OpenTelemetry exporters](https://opentelemetry.io/docs/languages/python/exporters/).

### Local real-inference observations

The explicit `local_real` implementation labels the trusted profile mode in
numeric SDK usage and sanitized traces. The default scripted lane remains
separate. Selecting a configured profile or matching native readiness is not
evidence of actual recognition, reasoning, generated speech or browser playback.
The [operations guide](local-real-inference.md) owns setup and pending
qualification.

| Producer | Implemented observation | Interpretation |
| --- | --- | --- |
| Automatic speech recognition (ASR) and TTS private `/metrics` | Fixed engine `stt` or `tts`, requests, succeeded and failed, active and max_active, processed input and output bytes, and cumulative duration seconds | Request and pressure evidence; not word accuracy, business success or production capacity |
| Native SDK usage and report | Finite numeric model and speech usage with the `scripted`, `local_real` or `provider_real` mode | Actual invocation observations; inspect the real model and tool outcome separately |
| Sanitized OTLP | Allowlisted finite mode, model and operation fields, and numeric timing and usage fields | Export failure cannot own work; no prompt, transcript, credentials or raw exception chain |
| Browser | Expected profile, native matching readiness, received output and audio `currentTime` advancement | Configuration, producer state and observed playback remain distinct; playback is not human hearing |
| Durable authority and independent supplier and receiver | Original inquiry, effect, outcome and delivery identities and inspected persisted results | Source of business truth; generated language and engine metrics cannot replace these checks |

Engine health and metrics stay on the private inference network with no host
ports. Raw request files and child and provider diagnostics are ephemeral and
are removed after completion or a controlled failure. Retained reports contain
fixed safe codes, counts, validated model names, provenance digests and bounded
timing and resource observations. Model-generated strings never become metric
labels.

Report actual cgroup memory and CPU windows honestly. Limits, lifetime peaks,
polling latency and model quality are different measurements. Qualification of
local real inference and media remains pending until its actual evidence is
inspected. Hosted CI and publication are outside this local POC scope.

### Provider-real profile

The trusted inference mode enum is `scripted` (the default), `local_real` or
`provider_real`. `provider_real` is a separately selected profile, never an
automatic fallback from a failed local engine. It uses
`livekit-plugins-deepgram`, `livekit-plugins-openai` and
`livekit-plugins-elevenlabs`, all pinned to 1.8.11 with Agents 1.8.11.

| Stage | Fixed pipeline |
| --- | --- |
| Speech recognition | Deepgram `nova-3` batch recognition on manual flush |
| Language model | OpenAI `gpt-5.4-mini` streaming Chat Completions, with reasoning effort `none` and at most 128 output tokens |
| Speech synthesis | ElevenLabs `eleven_v4_turbo` chunked HTTP pulse-code modulation (PCM) speech |

The [provider operations guide](provider-demo.md) owns the explicit setup,
check, start and stop procedures and the trusted provider P1-20 selector. Three
private keys reach only the native process; local model caches and engines are
unnecessary. The selected provider_real v2 gate passed both actual browser cases
with cleanup. P1 V1 (the fixed version 1 project scope) is qualified for the
local POC using provider_real v2.

External provider CPU and memory are unobserved. No zero-retention or
model-quality guarantee follows from local content-free telemetry. Default
offline and scripted checks make no provider calls.

Sanitized OTLP copies allow only these values for this profile:

| Field | Allowed values |
| --- | --- |
| `gen_ai.provider.name` | `deepgram`, `openai`, `elevenlabs` |
| Model ID (exact) | `nova-3`, `gpt-5.4-mini`, `eleven_v4_turbo` |

The known upstream display names `Deepgram` and `ElevenLabs` are normalized only
on the copy. Unknown or case-variant labels remain excluded, and original SDK
spans are unchanged. The existing five-field finite native logs exclude raw
exception text, prompts, transcripts, audio and keys. Provider metrics are
actual numeric SDK observations, not local-engine counters or fabricated
external resource samples.

### Startup and acceptance diagnostics

#### Native startup progress

Native `startup_progress` records use the existing five-field log schema and six
fixed codes: `startup_entry`, `startup_port_ready`,
`startup_runtime_constructing`, `startup_runtime_ready`,
`startup_rtc_connecting` and `startup_rtc_connected`. They show diagnostic
progress only. Controls, profile readiness and the greeting still require the
public `RoomIO` barrier. No new payload, identity, model content or duration
field is emitted. Pinned SDK warning origins are classified without reading
messages, exception arguments or arbitrary metadata.

#### Host media helper and failure aggregation

The host media helper retains only a closed preflight failure projection: the
exact builtin category or `other`, a fixed owned-source identifier and a bounded
line number. Its wrapper keeps that projection even when no runtime artifact
exists.

Failure API logs are validated against the producer schema and aggregated by
finite operation, method, status, error category and severity, with counts and
durations. Timestamps, request IDs and raw records are discarded. Browser
session-mint observations keep the numeric status and allowlisted categories,
never response bodies, tokens, prompts or provider errors. An unavailable
category remains unclassified rather than inventing a cause.

#### Session-mint retries

Session-mint retries follow the existing HTTP invocation replay contract and are
distinct from provider inference retries. Observe at most three attempts per
logical join, with an unchanged room, participant, task and invocation, an
allowed transient status and a final success. Actual native readiness and
playback remain separate assertions.

#### Provider certificate trust

Explicit provider trust setup retains only two things in local artifacts: the
selected public certificate authority (CA) bundle's byte count and hash, and a
verified native-only read-only mount proof. Certificate contents, subjects and
original input paths are not log fields or metric labels. Invalid trust
configuration has a finite setup failure. A failed TLS connection does not
establish an API-key, quota or model-access cause.

### Work profile producers

The opt-in P1 work profile stores read-only accepted delegation work. Later
versions add issued execution, delivery, guarded action and a result feed, and a
separate result receiver accepts delivered results.

| Producer | Event or operation names | Added by |
| --- | --- | --- |
| Read-only work profile | `readonly_work_operation` | [0028](work-items/0028-p2-dispatch-and-p3-coordinator.md) |
| Work v2 issued execution | `issue`, `complete`, `find_issue`, `result` and `observe` operations | [0029](work-items/0029-p2-gateway-and-p3-issued-execution.md) |
| Work v3 delivery | `readonly_work_operation` prepare, begin, inspect and record-receipt decisions | [0030](work-items/0030-p2-agent-recovery-and-p3-completion.md) |
| Result receiver | `result_receiver_operation` | [0030](work-items/0030-p2-agent-recovery-and-p3-completion.md) |
| Guarded action | `guarded_action` | [0030](work-items/0030-p2-agent-recovery-and-p3-completion.md) |
| Result feed (work v4) | `readonly_work_operation` with `result_feed_read`/`ok` | [0032](work-items/0032-linked-confirmation-and-result-projections.md) |

#### Read-only work profile

P1's read-only work profile emits fixed `readonly_work_operation` events. It
contains logger failures without altering acceptance or cancellation truth.

#### Work v2 issued execution

The optional work v2 profile adds the fixed issue, complete, find_issue, result
and observe operations through the same contained logger and bounded I/O
metrics.

- Issued leases are logical authority, not evidence that a paused remote
  process has stopped.
- The immutable `eligible_at_commit` disposition denotes P1 scope, time, lease
  and cancellation eligibility only. Semantic facts and case applicability
  remain distinct.
- Historical cancelled, expired, superseded or lease_expired results cannot
  become current authority.
- An eligible known result is retained after a later cancellation or deadline.
  Current requested cancellation is observed separately.

#### Work v3 delivery

The existing `readonly_work_operation` boundary records prepare, begin, inspect
and record-receipt decisions through the bounded work client. The delivery
intent, possible-send marker and receiver receipt are immutable persisted facts,
one of each per work within the existing `WorkLimits`. Only a new begin permits
an accept call. Existing possible sends reconcile by lookup only. Receipt
recording preserves known facts after cancellation or expiry.

#### Result receiver

The result receiver emits `result_receiver_operation` with fixed operation and
code values, bounded asynchronous I/O metrics and a contained telemetry-failure
count. A receipt identifies the accepted bytes for an exact receiver, recipient
and result.

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Actual I/O slots | Four | Result receiver | None |
| Retained identities | 1000 by default | Result receiver | Configurable from 1 to 10000 |
| Trusted scope and recipient bindings | At most 64 | Result receiver | None |

There is no automatic prune or retry, execution ledger, playback or human
acknowledgement.

#### Guarded action

The guarded action emits `guarded_action` with fixed operation and code values
and finite public-client I/O metrics. The original action receipt and the
existing exact case intent commit together. Each work allows one action within
`WorkLimits`. Replaying the original command returns known facts after a later
cancellation or expiry.

SQL-target and credential binding, the lock order (booking, then work, then
case) and database time guard current eligibility. External supplier execution
remains separate. P1 action metrics expose pending actual I/O and
`telemetry_failures`. These local observations do not prove supplier execution.

#### Result feed (work v4)

After a successful scoped page, the existing `readonly_work_operation` logger
emits fixed `result_feed_read`/`ok` records. Public metrics expose `pending` and
`telemetry_failures`.

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Actual I/O slots | Four | Result feed | None |
| Close observation | Five seconds | Result feed | None |
| Page size | At most 100 events | Each page | Bound to its source and cursor scope |
| Retained events | At most 30000 current events | Result feed | None |

There are no result body or identifier metric dimensions, no source
acknowledgement and no execution permission.

#### Shared rules for delivery and action

The v3 delivery, result receiver and guarded action values start no metrics
endpoint or exporter and reset with their owning process. Identifiers never
become metric dimensions. A timeout after writing can be
`acknowledgement_unknown`. Reconcile original identities instead of inventing a
new send or action. Known byte acceptance, exact intent commitment and observed
supplier effect remain distinct facts.

## P1 inquiry workload measurement

The opt-in [H1 work item](work-items/0014-p1-phase-h-workload-baseline.md) owns
the completed local inquiry measurement (Phase H1) and its inspected results. It
is distinct from full Phase H and P1 release and from broader workloads.

### Declared workload

The versioned [manifest](../harness/workloads/p1-inquiry-v1.json) freezes
seeded schedules, HTTP and observation pressure, cgroup limits and deadlines
before execution. Its 168 new offers, 120 expected admissions and 48 expected
capacity rejections are declarations. `make p1-benchmark-plan` validates the
plan and prints status `not_started`. Only `make p1-benchmark` executes the
separate installed runtime lane. The [local guide](../local-setup/README.md)
defines setup and artifact ownership.

### Observations

| Observation | Timestamp or unit, and scope | Meaning and limit |
| --- | --- | --- |
| Scheduled offer | Host monotonic seconds relative to the experiment budget | Declared arrival. It differs from the actual HTTP start when caller slots queue. |
| First HTTP start and offer queue delay | Same host clock, after acquiring the shared semaphore | Submit, replay, GET and cancel share the declared pool. The five-second network deadline starts after slot acquisition. |
| HTTP attempt finish | Same host clock, one record per started attempt | Includes timeout and transport-failure finishes. Unknown is not an acknowledgement. |
| Known admission acknowledgement | After a validated successful response under the original key | Measured from the original first start, so it includes unknown retries and backoff. No acceptance is fabricated from a timeout. |
| First observed inquiry success | First validated successful submit, replay or GET projection, with its source | One result record per inquiry. Includes queueing and observation lag, not the exact supplier completion time. |
| Resource probe | Host monotonic start, end and duration around each sequential `docker exec` | The actual bracket and ordering are retained. It is not an atomic simultaneous snapshot across roles. |
| CPU usage | Cumulative cgroup microseconds: first, last, delta and observed window | Includes in-cgroup Python probe work and post-inquiry cancellation and delivery. No unqualified utilization or throughput claim. |
| Memory and process IDs (PIDs) | `memory.current` bytes and `pids.current` kernel tasks or threads | Accounted cgroup memory, not resident set size (RSS). Sampled current values are not peaks. Probe overhead is included. |
| Queue | Current persisted outstanding and active limits, age and recovery lag | Observed authority state, not a second scheduler or a full continuous history. |

### Sampling cadence

Case observation performs one global round-robin GET, then sleeps 250 ms. HTTP
and shared-slot delay extend the interval, so it is not a per-task 250 ms
refresh or a hard tick. A large pending cohort adds sweep lag. Resource sampling
targets one second and retains the actual probe duration and skipped intervals.
Overdue slots are skipped rather than replayed back to back.

### Resource accounting

Fixed resource caps are verified exactly and separately from observed usage.
Temporary usage overage is retained instead of being mislabelled as
configuration drift. The CPU quota and period declare bandwidth, not a dedicated
physical core. Cgroup memory includes accounted userspace, kernel and cache
components, and PID accounting uses thread identifiers (TIDs). Kernel rules allow
temporary memory overage and organisational PID overage; see the official
[cgroup-v2 interfaces](https://docs.kernel.org/admin-guide/cgroup-v2.html).

Host, Docker virtual machine (VM), shared database and outside-cgroup driver
overhead are excluded from the API and worker samples. Record those exclusions
alongside machine and runtime provenance rather than advertising an end-to-end
resource total. The isolated benchmark does not enable media or runtime trace
export. Existing HTTP and worker observations remain distinct from Phase G's
native and OTLP evidence.

### Raw records and failure evidence

The bounded raw JSON Lines (JSONL) vocabulary contains HTTP, resource, queue,
result and observer records with finite values. Credentials, request bodies and
raw dependency errors are excluded. Correlation stays in controlled evidence,
never in dynamic metric labels. The runner preserves the frozen manifest and the
source and image provenance.

Original failures keep a fixed-enum code and operation on the originating
exception. They are selected into safe failure evidence before temporary capture
removal. Optional command metadata contains only the observed `exit_code` (or
null), `timed_out`, `timeout_seconds` and `elapsed_seconds`. Cleanup failure
observations are separate, so cleanup cannot replace the original failure. Raw
argv, stdout and stderr, environment values, request bodies and exception text
or attributes are not public diagnostics.

Automatically recorded environment metadata covers the host system,
architecture and Python, and the installed runtime architecture and versions. A
separately collected `environment.json` can supply Docker VM CPU and memory and
shared-host context, but the controller does not collect that hardware
automatically.

### Passing criteria and limits

A pre-cleanup measurement snapshot is not a passing phase. Reconciliation and
verified owned cleanup are required. Independent inquiry receipts and zero
supplier mutations establish useful investigation progress. Later explicit
cancellation, business outcome and receiver delivery remain separate facts.

Missing observations are unavailable, never zero-filled. Summaries keep sample
count, minimum, median and maximum only. No p95 or p99, physical capture,
model-quality, hosted CI or production-scale claim follows from this inquiry
slice.

## P2 channel continuity producers

P2 producers belong to the Channel Continuity Kit: its TypeScript library, its
small Python package and its gate tooling. Each subsection names the work item
that added the producers and records the qualification that work item reports.

### Standalone intake helper

Added by the [standalone and specialist HTTP slice](work-items/0027-p2-standalone-and-p3-http.md).
That work item owns the actual socket, sentinel, timeout, cleanup and
useful-progress evidence. Native conversational and model metrics and complete
product telemetry remain separate phase requirements.

The standalone helper separates an acknowledged inbox receipt from a read-only
preview. Invalid or failed preview adapters return fixed `StandaloneError`
codes. An unexpected or malformed intake acknowledgement becomes
`AcknowledgementUnknown` and must reconcile the original identity.

`activePreviews` measures actual retained preview lifetimes, including an
adapter that ignored abort. The helper closes its previews. The application owns
the supplied inbox and its acceptance and pool lifetime. The example report
projects the actual accepted or replayed receipt and operation IDs, the sequence
and the pending/not_executed state. It contains no message, token or proof.
Importing the library configures no global logger or exporter.

### Persisted dispatch

Added by the [dispatch and coordinator phase](work-items/0028-p2-dispatch-and-p3-coordinator.md)
(P2-I07).

P2-I07 adds authenticated `DispatchObservation` inspection of actual persisted
claim epochs, bounded attempt history, prepared operation identity, possible
external acceptance and any reconciled receipt. The states pending/running,
blocked/exhausted, uncertain and dispatched remain distinct. Once a call may
have reached the cooperating operation port, a failure cannot restore a
not_executed claim. The older standalone preview rejects any nonpending
processing state.

`ChannelDispatcher` counters and observer events use fixed event and code
values. They contain no message, token or proof and reset with the process. Up
to eight asynchronous observer notifications are retained. Their completion
never replaces database truth.

### Gateway

Added by the [gateway and issued-execution phase](work-items/0029-p2-gateway-and-p3-issued-execution.md)
(P2-I08), which owns the selected gateway and issued-runner gates.

The gateway emits fixed HTTP, poll and close events with safe codes. Its
process-local values are:

| Kind | Values |
| --- | --- |
| Counters | accepted, replayed, dispatched, pollErrors, telemetryFailures |
| Ownership observations | active, intakes, sockets, handlers, driver, observerPending |

These values describe actual local ownership, not fleet totals or an exporter.
A successful HTTP response is separate from committed acceptance. A restart
after acknowledgement inspects persisted processing truth under the original
receipt and key.

### Agent process

Added by the [agent recovery and completion phase](work-items/0030-p2-agent-recovery-and-p3-completion.md)
(P2-I09). Selected phase evidence remains separate from complete product,
browser and media, broader recovery and capacity qualification.

| `AgentProcess` signal | Values |
| --- | --- |
| Worker counts | started, succeeded, failed |
| Slot gauges | active unreaped slots, group-present slots |
| Telemetry and waiter values | telemetryFailures, observerDropped, observerPending, waiterRejected |
| Events | started and settled, with the numeric owned pid, a fixed ok or failed code, and the signal |

Bounds:

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Actual processes | One by default, at most two | `AgentProcess` | None |
| Pending observer callbacks | Eight | `AgentProcess` observers | None |
| Worker execution | 1000 ms by default | Each worker | Configurable up to 5000 ms |
| Cleanup | 1000 ms by default | Each worker | Configurable up to 2000 ms |
| Standard input, output and error | 32, 2 and 4 KiB | Worker pipes | None |

Interpretation:

- A validated, reaped worker success is separate from delivery to the waiting
  caller.
- Process, pipe and group ownership survives waiter cancellation.
- Signals contain no bodies, tokens, case context or exception reflection.
- The owned child PID is an optional bounded event observation, not a selector
  or business authority.
- Physical process-group disappearance does not prove that a remote provider
  stopped.
- The application closes `AgentProcess` explicitly. The gateway does not infer
  ownership of its supplied agent adapter.
- These values start no metrics endpoint or exporter and reset with their owning
  process. Identifiers never become metric dimensions.

### Revision routing

Added by the [completed routing and acceptance phase](work-items/0031-revision-routing-and-delegation-acceptance.md)
(P2-I10). Its producers are process-local, with no new exporter or metric
endpoint. These observations do not replace case authority or create a command
receipt.

| Producer | Values | Bounds |
| --- | --- | --- |
| `RevisionRouter` | started, revised, unchanged, conflicts, clarification, unknown, unavailable, waiterRejected, telemetryFailures, observerDropped; gauges active and observerPending | 2 retained calls by default (maximum 4); 2000 ms waiter and 1000 ms cleanup; 8 observer callbacks |
| `CaseAuthorityHttpClient` | started, known, rejected, unknown, failed, active | One fresh literal-loopback socket per call; 2 retained calls by default; 4096-byte response headers and 8192-byte body; finite close |
| Standalone `ReferenceCaseAuthority` | started, revised, unchanged, conflicts, unknown, failed, active | At most 2 retained SQL calls and 64 seeded case identities; owner-only explicit install |
| Python public-P1 bridge | known, rejected, unknown, telemetry_failed, active_requests, sockets | 4 actual calls and 16 admitted sockets; 4096-byte headers; 8192-byte body and response; 1000 ms default request and 2000 ms close |

Interpretation:

- Fixed `case_routing` completed and waiter_rejected events contain only a
  code. Application observer resources remain separately owned.
- A possible revision delivery failure in `CaseAuthorityHttpClient` remains
  `OutcomeUnknown`, with no retry.
- `ReferenceCaseAuthority` is a selected standalone authority, never an
  integrated P1 case projection or copy.
- The bridge's shielded actual close observers retain socket ownership after a
  waiter timeout. Rejected excess sockets abort without a task queue. Fixed
  `p2_case_bridge` code and outcome logs exclude the request, identity, token
  and raw exceptions.
- A known revised or unchanged response, a stale conflict, a clarification and
  an unknown are distinct. Current-state inspection after a lost acknowledgement
  (ACK) cannot turn the original command into a known acceptance.
- Provider timestamps are observations, never arbitration.
- The router's retained inbox authentication does not recheck the current sender
  association. No atomic revocation fence is claimed.
- Resetting these counters cannot erase persisted input or current case truth.

### Linked confirmation

Added by the [linked confirmation and result projection phase](work-items/0032-linked-confirmation-and-result-projections.md)
(P2-I11). Selected local qualification passed. The producers are process-local,
and no new metric endpoint or exporter is introduced.

| Producer | Values | Bounds |
| --- | --- | --- |
| `ConfirmationRouter` | started, accepted, clarification, unknown, rejected, waiterRejected, telemetryFailures, observerDropped, active, observerPending | 2 retained calls by default, maximum 4; 2000 ms waiter and 1000 ms cleanup; 8 pending observers |
| `PromptRegistry` | published, replayed, conflicts, lookups, rejected, unknown, active | At most 2 owned SQL calls; explicit owner cap of 1–10000 immutable prompts, default 1000 |
| `ConfirmationHttpClient` | started, known, rejected, unknown, failed, active | Shared finite literal-loopback transport |

Interpretation:

- Fixed `confirmation_routing` completed and waiter_rejected codes contain no
  input, quote or token. An accepted authority outcome and the caller's
  acknowledgement remain separate.
- The original response identity and changed-payload conflicts survive
  capacity. The registry is metadata, not case authority.
- A possible confirmation failure remains unknown. The client makes no retry and
  never parses or reserializes the opaque quote bytes.
- Revision ACK loss has no receipt. Exact confirmation ACK loss can be
  reconciled by explicitly replaying the original command through the existing
  P1 receipt.
- The current P2 association preflight is not an atomic revocation fence.

### Outbox and fake SMS carrier

Added by the [outbound replies and completion processing phase](work-items/0033-outbound-replies-and-completion-processing.md)
(P2-I12), which qualified these producers locally within its selected scope.
The later recovery counters are described in
[Send recovery counters](#send-recovery-counters).

A queued reply, a possible attempt, a known provider acceptance or
nonacceptance, and an unknown remain separate observations. Route, suppression
and recipient identifiers remain private record fields, not metric labels.
Carrier calls and actual resource cleanup outlive a canceled waiter when
necessary. A timeout does not prove external cancellation.

| Producer | Values | Bounds |
| --- | --- | --- |
| `ChannelOutbox` | Control counters: enqueued, enqueueReplayed, enqueueConflicts, routeSelections, suppressionObserved, controlRejected. Send counters: started, accepted, definitiveFailure, unknown, held, rejected, waiterRejected, telemetryFailures, observerDropped. Gauges: active, observerPending, storageActive. | 2 actual sends by default, maximum 4; 2000 ms waiter and cleanup, up to 5000 and 2000 ms; 8 pending observer callbacks; SQL pool of 2 connections with at most 4 retained operations |
| `FakeSmsSendClient` | started, known, rejected, unknown, failed and active, through the existing local transport | One fresh literal-loopback connection per call; request ceiling 32768 bytes, response ceiling 8192 bytes, headers 4096 bytes |

Interpretation:

- Fixed `channel_outbox` events include only a finite event and code.
- Control counters describe committed enqueue and route observations, not
  physical delivery.
- An unknown send never authorizes an automatic new attempt.
- The application owns the configured carrier client separately from the
  outbox.
- No telemetry failure may change admission, send evidence or ACK truth. New
  gates must exercise contained failures and useful progress.

### Send recovery counters

Added by the [completed send-policy and action-race phase](work-items/0035-send-policy-and-action-races.md)
(P2-I14), which qualified these local recovery producers. Their selected local
qualification passed.

Instrument actual trusted-controller replay, conflict and hold outcomes, lookup
known, absent and unavailable outcomes, and retry-reservation outcomes. Keep
them separate from the provider call and acceptance and from original callback
evidence. A replay counter counts an observed returned command, not a physical
message. A lookup timestamp is as-of provider evidence. Keep fixed finite
labels, and keep operation and attempt IDs, account, address, body and private
errors out of dimensions.

The new `ChannelOutbox` recovery producers expose these counters:

| Counters | Meaning |
| --- | --- |
| `recoveryStarted`, `recoveryReplayed`, `recoveryKnown`, `recoveryUnknown`, `recoveryHeld`, `recoveryRejected` | Explicit local controller operations and their returned or rejected observations. Replay performs no provider I/O. Known means validated provider evidence, never physical delivery or human acknowledgement. |
| `retryReservations`, `retryInvocations`, `lookupInvocations` | New durable local retry attempts, as distinct from actual provider send and lookup method calls. Multiple attempts can share one provider acceptance. |
| `lookupAccepted`, `lookupDefinitiveFailure`, `lookupAbsent`, `lookupUnknown`, `lookupConflicts`, `retryAccepted`, `retryDefinitiveFailure`, `retryUnknown`, `retryConflicts` | Validated lookup and send observations by fixed outcome. Absence or unavailability does not grant another send. Contradictions remain separate retained facts. |
| `ordinaryHolds`, `callbackVetoes`, `permissionVetoes`, `priorOperationVetoes`, `attemptLimitHolds`, `recoveryConflicts` | Policy decisions observed on the guarded reservation path. A veto cannot retract an already admitted call. |
| `recoveryAcknowledgementUnknown`, `recoveryAuthorizationRejected`, `recoveryCapacityRejected`, `recoveryIdentityConflicts`, `recoveryRevisionConflicts` | Fixed safe failure and uncertainty classifications. A timed-out waiter does not establish rollback or free an active slot. |

The recovery path reuses the existing `active`, `observerPending` and
`storageActive` gauges and these bounds:

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Actual network operations | 2 by default | Recovery path | Maximum 4 |
| Retained SQL calls | 4 over 2 connections | Recovery path | None |
| Waiter | 2000 ms by default | Recovery path | Maximum 5000 ms |
| Cleanup | 2000 ms by default | Recovery path | Maximum 2000 ms |
| Unsettled observers | 8 | Recovery path | None |
| Global recovery commands | 10000 by default | Recovery commands | Maximum 100000 |
| Recovery commands per operation | 8 by default | Recovery commands | Maximum 32 |
| Operation bytes | At most 32768 | Recovery path | None |
| Receipts | At most 4096 | Recovery path | None |
| Lookup observations | At most 2048 | Recovery path | None |

These are safety bounds, not measured throughput or provider resource use.

### Callback inbox

Added by the [completed callback evidence and applicability refresh phase](work-items/0034-callback-evidence-and-applicability-refresh.md),
which completed selected local phase gates for P2-I13 and P3-I11. The phase
froze these producers, and its selected qualification passed.

Instrument actual callback authentication and admission, original-event replay
and conflict, and reducer observations separately from outbox reservation and
the provider response. A callback veto is not an external-send fence. Provider
occurrence time is diagnostic and never selects the winning evidence. Never use
account, route, work, event or body labels.

| Producer | Counters and gauges | Bounds |
| --- | --- | --- |
| `CallbackInbox` | Counters: accepted, replayed, rejected, conflicts, webhookRejected, waiterRejected, telemetryFailures, observerDropped. Gauges: active, observerPending, storageActive. | 4 retained actual operations and 2 SQL connections; 2000 ms waiter and cleanup by default, maximum 5000 and 2000 ms; at most 8 unsettled observers; raw callback at most 4096 bytes; 60-second signature window, rechecked with database time after admission |

Interpretation:

- Fixed `channel_callbacks` event and code records contain no payload or
  credential.
- `accepted` means a new durable provider observation, not delivery or consent.
  `rejected` covers public operation and preflight failures.
- Timeout or cancellation retains actual I/O ownership. Telemetry failure cannot
  change callback evidence or an original receipt.
- No placeholder zero counter establishes qualification.
- Application-owned case clients, listeners and observer resources remain
  distinct from each component's cleanup claim.

The callback boundary returns the fixed `CallbackError` codes `InvalidCommand`,
`WebhookRejected`, `AccessDenied`, `NotFound`, `IdentityConflict`, `Overloaded`,
`UpgradeRequired`, `Unavailable`, `AcknowledgementUnknown`, `CleanupIncomplete`
and `Closed`. `WebhookRejected` covers failed raw-byte, signature or window
validation. An unknown write is not permission to resubmit or send again.

### Native input

Added by the [completed native input and deadline handoff](work-items/0036-native-input-and-deadline-cancellation.md)
(P2-I15 and P2-I16). The selected actual six-group native gate and the isolated
Python and npm artifact gates passed. Fifty-five Python, 530 P2 TypeScript and
sixty-five browser-policy tests exercise the producer boundaries. Final
selected phase gates passed. These process-local native producer observations
are not a new Prometheus exporter or an inspected OTLP trace pipeline.

| Fields | Units and exact meaning |
| --- | --- |
| `textStreamsSeen`, `voiceCaptures`, `voiceCommits`, `genuineFinalSnapshots` | Cumulative SDK and input observations. A genuine final is distinct from interim promotion and from durable acceptance. |
| `durableAcceptCalls`, `nativeInputsAccepted`, `nativeInputsReplayed`, `nativeInputsRejected` | Cumulative actual intake calls and validated ACK states. A timeout or lost ACK remains unknown, not rejection. |
| `nativeGenerationAttempts`, `nativeGeneratedReplies`, `defaultReplyInvocations` | Cumulative explicit generation attempts, known SDK completions and observed automatic SDK reply events. No field proves playback or business completion. |
| `activeReaders`, `activePrepare`, `activeIntakes`, `activeVoiceWork` | Current actual occupancy, retained until owned work settles. Never replace missing observations with zero. |
| `observerPending`, `observerFailures`, `observerDropped` | Current bounded notice occupancy, cumulative callback and log-delivery failures, and cap-driven drops. Eight notices at most. A synchronous, asynchronous or log outage does not change accepted truth. |

These groups contain exactly eighteen native metrics. The runtime's fixed
`native_state` event carries finite `native_event` and `native_code` fields.
The application's explicit SDK log sanitizer emits at most 128 records using
only allowlisted event, code and level values. It omits messages, transcript
text, identifiers, exception strings, credentials and paths. Failure context
keeps only a closed stage, error code and type, and allowlisted owned source
basenames and line observations. Observer and task exceptions are retrieved, and
independent cleanup is attempted after an earlier close failure.

Reliable `p2.generation` observations have exactly six keys: `schemaVersion`,
`bindingId`, `inputId`, `operationKey`, `generationId` and `status`. The
selected native AGENT participant publishes them. The browser requires an
already accepted matching input and operation, and it retains at most 64
generation identities. The statuses started, completed, interrupted and unknown
describe SDK attempt observations. Browser audio playback is observed
separately, and neither source supplies human acknowledgement or exact quote
consent. A rejected retry cannot erase an earlier unknown input acceptance.

### Response and playback evidence

Added by the [playback evidence and process recovery handoff](work-items/0037-playback-evidence-and-process-recovery.md)
(P2-I17), which owns the selected current source, package, process and media
evidence. The original eighteen native metrics and the six-key `p2.generation`
observations keep their meaning.

| Producer | Fields and meaning | Limits |
| --- | --- | --- |
| P2 communication store and gateway | responsesAccepted, responsesReplayed, observationsAccepted, observationsReplayed, identityConflicts, rejected, unknownAcknowledgements, capacityRejected, telemetryFailures | Fixed cumulative counters; no tenant, input, response or transcript label |
| Communication observer | observerPending and observerDropped: actual bounded notification occupancy and cap-driven drops | An outage cannot change accepted facts |
| Python communication capture | anchorsKnown, generatedFactsKnown, sdkFactsKnown, browserReportsKnown, unknownAcknowledgements, rejectedReports, observerFailures: counts of known original receipts or contained observation failures | A lost ACK stays unknown |
| Python actual ownership | activeNodes, activeProducers, activePublications, activeReports: actual LLM, TTS, task and stream work retained through ignored cancellation and late settlement | Zero only after settlement |
| Browser playback | Non-silent and sampled PCM milliseconds, source state and count, and actual reader, I/O and meter ownership | Continuous selected-track response window; neither hearing nor business success |

Response mappings use a separate eight-key `p2.response` wire. Full generated
text is available through the bounded authenticated read, never in metric labels
or logs. SDK synchronized text is its own observation. Contradictory source
facts remain inspectable and conflicted; timestamps do not select a winner.
Client completion is a report, and missing reports stay unknown.

#### Diagnostics retention and failure precedence

These rules cover the P2 rows above and the P3 recovery fixtures from the same
handoff. Finite child and browser diagnostics are retained before private-tree
cleanup. Browser timeouts use the last actual finite observation when the page
has already closed. Exception messages, bodies, tokens, arbitrary URLs, paths
and raw browser assertions are excluded. Primary failures survive secondary sink
and close failures, and all independent cleanup owners are still attempted.
These are inspected local producer proofs, not a newly qualified Prometheus or
OTLP export pipeline.

### Read-only context rehydration

Added by the [completed case rehydration and standalone release handoff](work-items/0038-case-rehydration-and-standalone-release.md)
(P2-I18). It records selected eighteen-group storage and three-group actual
media qualification and the Python and npm consumers. Preserve the original
eighteen native and eleven communication metric fields. The optional context
profile exposes separate groups:

| Producer | Numeric fields | Interpretation |
| --- | --- | --- |
| P2 facade | started, known, denied, invalid, unavailable, overloaded, waiterRejected | Admitted read outcomes and bounded waiters. Preflight listener rejection is separate. |
| P2 facade ownership and sink | active, observerPending, telemetryFailures, observerDropped | Actual pending read and sink ownership. A timeout cannot free ignored I/O. |
| Context HTTP listener | started, known, rejected, sockets, handlers | Explicit loopback endpoint outcomes and actual transport owners |
| Python context client | started, known, unavailable, active | Validated bounded reads, with no input or generation side effect |
| Optional SDK profile | loads, loaded, failed, revisionMismatch, active | Context initialization and idle refresh. An equal revision does not establish supplier or workflow freshness. |
| Browser context view | Phase, source revision, original history and response references, active reads | Protected display observations, not metric labels or current-room media authority |

Use fixed finite error and event codes, and omit identifiers, text, quotes and
credentials from metric labels and logs. Translate semantic denial and cursor
failures through the actual transaction normalizer without reporting a storage
outage. Retain actual rollback, readers and close tasks after a timeout. SDK and
model context proofs bind actual public message IDs and original receipt IDs
while retaining only bounded metadata.

#### Selected media run

The selected media run used a first native room session (A) and a fresh later
session (B). It observed three native accepts, one separate signed SMS, four
operation acceptances, three response identities and six SDK source facts.
Client playback reports were disabled, so browser evidence remained unknown.
Actual rendered PCM and the new B reply were observed separately. Rehydration
loads generated zero replies. Original SDK and SQL receipt joins, the as-of B
context and zero owned rooms during SMS were independently inspected. These
observations do not establish human acknowledgement, supplier delivery or a new
telemetry export pipeline.

### Ordinary inbox observers and workload study

Added by the [completed bounded workload and image evidence slice](work-items/0039-bounded-channel-workloads-and-image-evidence.md)
(P2-I19). Selected P2-I19 and P3-I16 source, installed and workload
qualification, including the normal gates for these implemented surfaces,
passed in that handoff. Counts recorded for earlier checkpoints keep their
historical scope.

The ordinary inbox's `telemetryMetrics` exposes `observerPending`,
`observerDropped` and `observerFailures`. It reserves eight ordinary callbacks,
separate from the existing eight communication callbacks. Pending remains
observable until actual callback settlement, including after SQL close.

The P2 study retains the declared seed, sample cadence and observed process RSS,
CPU, event-loop and latency maxima. These are selected process observations, not
per-case RAM or production SLOs. The application owns external observer
transport, and an SQL drain cannot claim that a held callback stopped. Pending,
dropped or failed telemetry never blocks accepted business progress or creates
unbounded callback work.

### Operations reader and collector

Added by the [operations and fixed-policy handoff](work-items/0040-operations-ui-and-fixed-policy-evidence.md)
(P2-I20), which owns the selected P2-I20 and P3-I17 qualification. Selected
normal operations and policy qualification passed; full project release remains
separate.

| Producer | Finite observations | Interpretation |
| --- | --- | --- |
| P2 operations reader | Caller: started, known, denied, invalid, unavailable, overloaded, waiterRejected, active. Actual reader: readerStarted, readerKnown, readerWaiterRejected, readerActive. Bounded observer ownership, failures and drops. | Caller timeout and actual read settlement are separate. The reader keeps its two-slot bound until the transaction and the external case read settle. |
| P2 collector | inbox, inbox_telemetry and operations snapshots; bounded getter and observer ownership; safe completed-read spans | Three real configured producers; absent producers stay absent. Up to eight callbacks or getters and thirty-two recent safe span rows. Durations reflect actual milliseconds. |
| P2 optional page | Observed context and as-of time, historical and current state, last finite error, actual requests and close outcome | Refresh and signed cursor pages perform reads only. Last labelled facts survive failure. Forget fences the view while the client still owns unfinished work. |

The operations operator capability is distinct from current native-context
access. A context denial pauses current presentation, and earlier diagnostics
remain labelled historical until Forget clears them. Metrics carry no case,
tenant, input, source, credential, cursor, transcript or prompt labels.
Source-specific diagnostic rows are authenticated bounded observations, never
metric labels or execution authority. The collector is process-local, not a
fleet exporter or a durable totals service.

Use stable typed error codes. Bad scope and cursors remain semantic failures,
while SQL or transport outages become unavailable. The new HTTP adapter maps its
codes to these statuses:

| Code | Condition | HTTP status |
| --- | --- | --- |
| `invalid_query` | Invalid query | 400 |
| `access_denied` | Access denied | 403 |
| `cursor_stale` | Stale cursor | 409 |
| `overloaded` | Retained-reader overload | 429 |
| `unavailable`, `closed` | Unavailable or closed | 503 |

A hard listener or socket cap may close the transport; it cannot promise a typed
response. Preserve the first failure and attempt every independent cleanup tier.
Incomplete readers, sockets, workers or children remain owned until settlement
and block dependent removal.

The selected 0040 profile emits three actual sources: `inbox`,
`inbox_telemetry` and `operations`. The public adapter also accepts closed
source-specific envelopes from the existing dispatch, gateway, outbox, callback
and rehydration producers. Its 76 finite cause codes preserve real producer
meanings. Unknown envelopes, arbitrary labels and accessors are dropped safely.
These codes are not tenant or payload labels.

Observer and getter completion ownership is reserved before invoking configured
code, including returned thenable accessors. A reentrant close observes that
owner, stops later getter admission and remains retryable after actual
settlement. The eight-callback and getter bound, the two-active-span bound, the
thirty-two-row ring and the existing metric names remain unchanged. Full
real-producer and reentrant controls failed before the fix and passed after it.
The actual selected PostgreSQL and browser gate observed useful business
progress despite a held or failed exporter, and zero final owned resources. This
does not qualify an external Prometheus or OTLP pipeline.

## P3 delegation reliability producers

P3 producers belong to the Delegation Reliability Kit: the Python coordinator,
runner and processors, and the TypeScript specialist. Each subsection names the
work item that added the producers and records the qualification that work item
reports.

### Specialist HTTP service

Added by the [standalone and specialist HTTP slice](work-items/0027-p2-standalone-and-p3-http.md).
That work item owns the actual socket, sentinel, timeout, cleanup and
useful-progress evidence.

The Node HTTP producer emits the component `delegation_specialist` plus fixed
event, operation and code fields. Expected rejection, attempt start and finish,
observation and close are separate events. Raw request, response and source
bytes, bearer values, URLs and exception text never become fields. Unexpected
boundary defects return a safe `internal_error` HTTP 500. The existing
contract-error envelope remains separate from `specialist.http_error` transport
failures, and both prohibit automatic retry advice. Importing the library
configures no global logger or exporter.

| Metric | Kind | Meaning | Default limit |
| --- | --- | --- | --- |
| `invoked` | Counter | Admitted evaluations | None |
| `completed` | Counter | Successful computations. Computation does not prove response delivery or business acceptance. | None |
| `rejected` | Counter | Rejected HTTP operations | None |
| `cancellations` | Counter | Actual cancellation observations at the boundary, separate from computation stop, result applicability and business outcome | None |
| `expirations` | Counter | Actual expiration observations at the boundary, with the same separation | None |
| `disconnects` | Counter | Actual disconnect observations at the boundary, with the same separation | None |
| `active` | Gauge | Current retained evaluations | 4 |
| `requests` | Gauge | Admitted HTTP handlers | 16 |
| `sockets` | Gauge | Connected TCP sockets | 16 |
| `observerFailures` | Counter | Failed notifications | None |
| `observerDropped` | Counter | Dropped notifications | None |
| `observerPending` | Gauge | Current unsettled callbacks | At most 8; overflow drops instead of growing a queue |

The metric names are fixed. The `active`, `requests` and `sockets` limits are
independent. Counters reset with the process and have no tenant, case or attempt
labels. `metrics()` returns
values for an application-owned collector and starts no metrics endpoint.

Observer failures cannot change a successful computation, block its
acknowledgement indefinitely or imply a deployed trace or export pipeline. An
observer owns any external resources it creates, and the default console sink is
not a nonblocking guarantee. At this slice, P3 remained a scripted, read-only,
foreground HTTP boundary with no durable queue or terminal history. Native
conversational and model metrics and complete product telemetry remain separate
phase requirements.

### Coordinator and Python HTTP client

Added by the [dispatch and coordinator phase](work-items/0028-p2-dispatch-and-p3-coordinator.md)
(P3-I06).

The coordinator emits `delegation_port` operation, outcome and code fields. Its
bounded process-local counts distinguish owned port outcomes from cancelled or
timed-out waiters and retained active calls. A timed-out write can remain
accepted and must reconcile its original key. A succeeded port call is not
completed specialist work.

The Python HTTP client distinguishes received framed responses from validated
public results and observations, validation failures, transport failures,
cancellation, retained active I/O and incomplete cleanup. These values describe
actual local boundary observations, not durable totals or case authority. The
client starts no new exporter or metrics endpoint. Fixed errors and logs exclude
bodies, evidence, credentials and raw exception text. Application-owned
synchronous logging adapters still require their own execution and flush
budgets.

### Issued runner

Added by the [gateway and issued-execution phase](work-items/0029-p2-gateway-and-p3-issued-execution.md)
(P3-I07A), which owns the selected gateway and issued-runner gates.

The runner emits `delegation_run` operation, code and outcome fields. Its
bounded local counts cover invoked, not_reinvoked, active ownership, canceled or
timed-out waiters and telemetry failure. Counters distinguish the owned outcome
from the caller's observation.

- Only a newly issued command invokes. An unknown issue or result
  acknowledgement reconciles the exact original identity.
- Strict late HTTP observations still validate identity and facts. Expiry
  cannot bypass factual rejection.
- Read applicability can be candidate, clarification, outdated, cancelled,
  expired, execution-ineligible or unavailable. None of these authorizes an
  atomic current-case action.
- The later P3-I07B adapter uses P1's atomic guard rather than promoting this
  read observation into permission.

### Completion and action adapters

Added by the [agent recovery and completion phase](work-items/0030-p2-agent-recovery-and-p3-completion.md)
(P3-I07B). Selected phase evidence remains separate from complete product,
browser and media, broader recovery and capacity qualification.

| Producer | Values | Bounds |
| --- | --- | --- |
| P3 completion and action adapters | `delegation_completion` operation, code and outcome; counts for started, succeeded, failed, active, capacity_rejected, timed_out_waiters, cancelled_waiters, telemetry_failed, receiver_invoked and reconciled | 2 owned calls by default, maximum 4; 5000 ms default waiter and 1000 ms cleanup budgets |

Interpretation:

- Actual owned tasks retain their slots after a waiter leaves. Fixed sanitized
  errors and throwing-logger containment preserve committed receipts.
- These values start no metrics endpoint or exporter and reset with their owning
  process. Identifiers never become metric dimensions.
- P3 completion clients close their P1 completion ports, while the application
  keeps ownership of its result inspector.
- A timeout after writing can be `acknowledgement_unknown`. Reconcile original
  identities instead of inventing a new send or action.
- Known byte acceptance, exact intent commitment and observed supplier effect
  remain distinct facts.

### Result projection

Added by the [linked confirmation and result projection phase](work-items/0032-linked-confirmation-and-result-projections.md)
(P3-I09). Selected local qualification passed, and no new metric endpoint or
exporter is introduced. The P1 result feed that the projector reads is described
in [Work profile producers](#work-profile-producers).

| Producer | Values | Bounds |
| --- | --- | --- |
| `ProjectionClient` and `ProjectionProjector` | started, succeeded, failed, timed_out_waiters, cancelled_waiters, capacity_rejected, telemetry_failed, active | Projector batches of at most 8 |

Interpretation:

- Actual tasks are retained after waiter loss.
- The durable checkpoint and rows are separate from process counts and contain
  immutable as-of observations. A read failure cannot advance a checkpoint.
- Projection applicability is as of its original reads. Later cancellation,
  expiry or case changes do not refresh stored observations or authorize action.

### Registered lab acceptance wrappers

The selected P3 acceptance wrappers for P3-01, P3-03 and P3-11 report exact
named inventories of 13, 8 and 12 assertions. They also report case, mode,
count, monotonic correctness-run duration and actual owned cleanup. They bind
fresh component report bytes to their SHA digest and reject a mismatch, skip or
timeout. No model, native media, latency percentile or production-capacity claim
follows.

### Completion processing

Added by the [outbound replies and completion processing phase](work-items/0033-outbound-replies-and-completion-processing.md)
(P3-I10), which qualified these producers locally within its selected scope.

| Producer | Values | Bounds |
| --- | --- | --- |
| `ProcessingClient` and `CompletionProcessor` | started, succeeded, failed, timed_out_waiters, cancelled_waiters, capacity_rejected, telemetry_failed, active; the processor also has examined, acknowledged, unknown, unavailable and ack_reconciliations | 2 retained actual calls by default, maximum 4. Default waiter: 5000 ms for the processing client and 10000 ms for the processor. Default cleanup: 1000 ms for both. Configurable within 20–10000 ms (waiter) and 20–5000 ms (cleanup). |

Interpretation:

- Existing `result_projection` operation, code and outcome logs remain fixed.
- Processor row counters describe observed work, including replay.
  `acknowledged` is not a durable unique-delivery total.
- `ack_reconciliations` counts successful exact lookups after an uncertain ACK
  or a checkpoint conflict.
- A completed processing step may contain unknowns. `succeeded` is not a
  delivered-result count.
- Discovery scan progress is exposed separately from the terminal ACK
  watermark, receipt-derived terminal acknowledgements and definite not-required
  as-of decisions.
- Unknown and unavailable events are not acknowledged. Scan counts are work
  observations, not counts of delivered results.
- The existing P1 receipt, receiver acceptance, any user acknowledgement and the
  processing ACK keep separate meanings.
- No telemetry failure may change admission, send evidence or ACK truth. New
  gates must exercise contained failures and useful progress.

### Applicability refresh

Added by the [callback evidence and applicability refresh phase](work-items/0034-callback-evidence-and-applicability-refresh.md)
(P3-I11), which completed selected local phase gates for P2-I13 and P3-I11. The
phase froze these producers, and its selected qualification passed. Never use
account, route, work, event or body labels.

Refresh diagnostics distinguish original command replay, a new local revision,
a compare-and-set (CAS) conflict, an ambiguous commit with exact lookup, raw
unavailable reads, effective invalidation and a stable display hide. Persist the
separate execution, case and time observations; local host time is not a P1
database-time receipt. Keep the immutable processing ACK and receiver receipt
distinct from current display state.

| Producer | Counters and gauges | Bounds |
| --- | --- | --- |
| `ApplicabilityClient` | Inherited started, succeeded, failed, timed_out_waiters, cancelled_waiters, capacity_rejected, telemetry_failed and active; plus display_hides_observed, write_reconciliations and reconciliation_failed | 2 retained calls by default, maximum 4; default waiter 5000 ms and cleanup 1000 ms, maxima 10000 and 5000 ms |
| `ApplicabilityRefresher` | The inherited operation counters and gauge above; plus refreshes_observed, command_replays, write_reconciliations and reconciliation_failed | 2 retained calls by default, maximum 4; default waiter 10000 ms and cleanup 1000 ms, maxima 10000 and 5000 ms |

Interpretation:

- Client hide observations can include an original tombstone replay. They are
  not unique durable-row counts.
- `reconciliation_failed` counts failed lookups. Absence remains uncertainty or
  conflict.
- Refresher observations may include a concurrent original receipt.
  `command_replays` identifies an early exact lookup. Durable cardinality comes
  from metadata, not counters.
- Fixed `result_projection` operation, code and outcome records keep the
  existing logger boundary.
- Timeout or cancellation retains actual I/O ownership. Telemetry failure cannot
  change a refresh CAS or an original receipt.
- No placeholder zero counter establishes qualification. Application-owned case
  clients, listeners and observer resources remain distinct from each
  component's cleanup claim.

P3 uses the fixed `ProjectionError` vocabulary:

| Condition | Code | Note |
| --- | --- | --- |
| Transient feed read failure | `storage_unavailable` | None |
| Contradictory immutable identity | `invalid_source_state` or `source_mismatch` | None |
| Stale local CAS or serialization failure | `checkpoint_conflict` | One exact original lookup may resolve it |
| Uncertain commitment | `acknowledgement_unknown` | One exact original lookup may resolve it |
| Capacity limit | `capacity` | Never deletes identity |
| Actual I/O still owned | `cleanup_incomplete` | None |

A failed or absent lookup preserves the original code. Raw dependency messages,
credentials and submitted bodies never become error fields.

### Protected action authorizer

Added by the [completed selected send-policy and action-race phase](work-items/0035-send-policy-and-action-races.md)
(P3-I12).

The unchanged P3 authorizer keeps its started, succeeded, failed,
capacity_rejected, timed_out_waiters, cancelled_waiters, telemetry_failed and
reconciled observations, plus actual active calls. P1's action metrics are
described in [Work profile producers](#work-profile-producers). These local
observations do not prove supplier execution.

Race evidence must join the protected receipt to the independent supplier
result. It must distinguish `stale_revision`, `intent_committed`,
`transition_conflict`, the cancellation disposition and unknown acknowledgement.
Observer failure never changes authority. Waiter timeout or cancellation keeps
work and slots owned through settlement and close. The gate's two SQL graphs and
three SIGKILLs are test observations, not production metrics or proof that a
database fence stopped an already admitted external call.

### Deadline and cancellation validation

Added by the [native input and deadline handoff](work-items/0036-native-input-and-deadline-cancellation.md)
(P3-I13).

P3-I13 adds validation composition and no new producer or exporter. The existing
runner, HTTP and completion metrics remain authoritative. Its retained direct
proofs distinguish nine computations and results from actual zero live peer
occupancy after shutdown, a requested remote cancel, one non-durable running ACK
and one lost ACK. P1 database time after locks determines eligibility, while
host and peer timestamps and refreshed applicability are observations. The
unchanged authorizer remains the only path to an exactly confirmed current
action.

The selected source and installed eighteen-case and forty-six compatibility
assertions passed for P3-I13. Selected P3-I14 recovery then passed, as recorded
in [Process recovery fixtures](#process-recovery-fixtures). P3-I15 release
completeness is now implemented and its selected local installed qualification
passed. Full charter release remains separately gated.

### Process recovery fixtures

Added by the [playback evidence and process recovery handoff](work-items/0037-playback-evidence-and-process-recovery.md)
(P3-I14).

The P3 recovery fixtures record finite stage, code and type values, the owned
PID and return code, original receipt and digest joins, a real SQL blocker graph
and the independent supplier apply count. These are validation observations
over unchanged authorities, with no new exporter or automatic recovering queue.
The [diagnostics retention and failure precedence rules](#diagnostics-retention-and-failure-precedence)
from the same handoff apply.

### Standalone package gate

Added by the [case rehydration and standalone release handoff](work-items/0038-case-rehydration-and-standalone-release.md)
(P3-I15), which records the sixteen-assertion P3 installed command.

The package gate records eight offline and eight actual assertions, exact
bounded children and captures, built artifacts and three correlated source,
authority and replay proofs. A source-bound owned kill and zero new method
entries on replay remain separate from physical exactly-once or human
acknowledgement claims. The first failure uses finite stage and code
diagnostics, and secondary sink or close failures cannot replace it. Unreaped
children or incomplete dependent readers withhold DDL and temporary-file removal
and preserve private owned work with cleanup marked incomplete.

### Document extraction producers

Added by the [bounded workload and image evidence slice](work-items/0039-bounded-channel-workloads-and-image-evidence.md)
(P3-I16). Selected P2-I19 and P3-I16 source, installed and workload
qualification, including the normal gates for these implemented surfaces,
passed in that handoff.

| Producer | Current numeric fields | Bound and meaning |
| --- | --- | --- |
| P3 `DocumentHandler` | providerStarted, providerSettled, providerFailed, providerActive, active | Counts and occupancy for the configured scripted provider. Four owned handler calls. No optical character recognition (OCR) or model usage or action-authority meaning. |
| P3 PNG decoder | workersStarted, workersSettled, workersActive, observerFailures, workerObserverPending, workerObserverDropped | Actual worker lifetime and a bounded observation sink. A result is normal only after exit 0, and an incomplete close retains actual owners. |
| Shared image transport | Existing HTTP and client outcome and active-owner counters | Finite capability, operation and error vocabulary only. Unchanged policy defaults. No identifiers or source text as labels. |

Image proofs distinguish structural acceptance from independent synthetic-image
factual verdicts, canonical client-returned wires, provider entries and worker
exits. Server result digests are joined after shutdown to those canonical wires,
not to an independent raw-server serialization capture. Failure contexts keep
only finite mode, stage and error codes, with no raw exception text, tokens,
headers or image bytes in diagnostics. Image content cannot authorize
instructions, consent or mutation.

### Fixed-policy HTTP client and handler

Added by the [operations and fixed-policy handoff](work-items/0040-operations-ui-and-fixed-policy-evidence.md)
(P3-I17). Selected normal operations and policy qualification passed; full
project release remains separate.

| Producer | Finite observations | Interpretation |
| --- | --- | --- |
| P3 TypeScript HTTP client | started, settled, active, invokeStarted, statusStarted, cancelStarted, validated, validationFailed, capacityRejected | Actual transport ownership and correlation validation. Validated does not mean factually correct or eligible for action. |
| P3 fixed-policy handler | evaluated, clarified | Finite scripted-rule outcomes with separate immutable source witnesses. No model accuracy, execution or consent meaning. |

Fixed-policy structural failure, unsupported rules or facts, permission,
deadline and capacity remain separate outcomes. Preserve the first failure and
attempt every independent cleanup tier. Incomplete readers, sockets, workers or
children remain owned until settlement and block dependent removal.

## Joined application

The [joined application](work-items/0045-joined-native-channel-policy.md)
composes P1, P2 and P3 through their public APIs. It adds finite executor scan,
job and close events and aggregate source-read and HTTP lifetime counts. These
are process observations with no raw body, key or per-ID metric dimension. A
failed or abandoned waiter does not release an actual runner, read or socket
slot. The joined UI and a fleet exporter remain separate integration work; a
metrics method alone does not establish either.

## Planned product instrumentation

This section is a plan. The producers implemented so far are described in the
sections above.

### Native SDK signals first

Use SDK-native turn metrics, session reports, usage and OpenTelemetry spans
before adding custom instrumentation. `AgentSession` per-turn metrics and
emitted output are not browser playback evidence. Do not build against the
deprecated session-level `metrics_collected` event. Add application spans around
durable boundaries without recording raw sensitive payloads. References:
[native observability](https://docs.livekit.io/testing/observability/data/) and
[session traces](https://docs.livekit.io/reference/agents/session-traces/).

### Required project events and metrics

| Project | Required events and spans | Required bounded metrics |
| --- | --- | --- |
| P1 | Intake commit, claim/renewal, attempt, supplier dispatch/reconciliation, confirmation/intent, outbox delivery | Accepted/completed/failed/uncertain counts; queue age; recovery lag; retry/lease rejection; supplier latency |
| P2 | Durable input acceptance, canonical deduplication, case association, channel route, send/callback, interruption/playback observation | Intake/dispatch lag; duplicate/conflict counts; delivery states; route/resumption latency; dormant-record resource use |
| P3 | Delegation acceptance, attempt invocation, result validation, applicability decision, cancellation observation, delivery | Inflight/admission; result latency; stale-result rejection plus valid-result progress; timeout/recovery; per-capability resource use |

### Dimensions, units and timing

Use fixed environment, service, capability, outcome and error-code dimensions.
Keep metric series finite across tenant and case counts. Define the schema,
units, histogram buckets and collection points with each implementation slice.
Workflow latency uses monotonic durations where possible, and business deadlines
use persisted absolute instants. Never subtract timestamps from unrelated clocks
as a latency measurement.

## Rollout and operational policy

### Rollout steps

1. Keep the implemented API counters, JSON logs and error envelope working now.
2. Retain the Phase G bounded OTLP path to the optional local collector and its
   inspected raw Jaeger v3 trace and correlation evidence. Add later producers
   deliberately. Separate business exceptions from export failures. Telemetry
   failure must not block acceptance, conversation or shutdown indefinitely.
3. Add project metrics and spans with the first real event producers, not
   placeholder zero counters. Retain event history as the correctness record.
4. At a measured load baseline, define scenario-specific budgets and alert
   conditions before judging results. Numeric SLOs follow the declared workload
   and hardware. This plan asserts no production latency or capacity.

The exporter, redaction, access, retention and missing-signal rules are listed
in [Rules for every signal](#rules-for-every-signal).

### Minimum demonstration evidence

A small demo needs a clear failure event, a useful safe error, a correlated
trace or log, and the actual final store state. Adding a dashboard stack before
the underlying signals exist is optional work and does not complete a release
gate.

## Verification and limits

### Test coverage

API tests check metric authentication, actual in-flight work, duration and
counter observations, finite labels, per-application isolation, safe error and
log output, and cancellation propagation. Actual stack checks inspect readiness,
an authenticated scrape and structured logs. Browser validation separately
checks visible success, replay and conflict, and safe error recovery.

Phases A to F add independent process and backend failure evidence. Phase G adds
actual scripted browser and native media and inspected filtered traces. Phase
H's declared-workload and resource, hardware and live-model, and platform
requirements remain under the [validation plan](validation-plan.md). Local
observations do not establish production security or complete release tracing.

### Final provider run trace evidence

The final provider run's retained API query is bounded to 100 traces. It
includes one failed `continuity.get` span whose precise cause is unresolved.
Retained native and worker queries contain no error spans. Required progression,
privacy, authority and cleanup passed, but complete API history and global
zero-error claims are not established.

Per-run live-check state, private process logs, temporary credential environment
files and copied CA snapshots were cleaned after producer inspection and
owned-container cleanup. The user's ignored `.env.providers` file and the
original approved public CA bundle remain intact. Independent review uses
retained projections.

### Qualification status

| Capability | Status | Evidence |
| --- | --- | --- |
| Completed local inquiry baseline (Phase H1) | Qualified | The [H1 work item](work-items/0014-p1-phase-h-workload-baseline.md) (S-I06 and P1-I27) owns it and its inspected measurements |
| Phase H2 reliability | Qualified | Passed separately |
| P1-I26 artifact, API and genuine-consumer checks | Qualified | Passed separately |
| P1 V1 for the local POC | Qualified | Qualified using provider_real v2 |
| local_real | Not qualified | Remains unqualified |
| Complete P2 and P3 acceptance | Partial | Remains pending |

Physical microphone and live-model quality need their own evidence. Hosted CI
and publication are outside the local POC scope.
