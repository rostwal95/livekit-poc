# Observability and failure handling

Status: Active
Last reviewed: 13 November 2026

## Current foundation

The control API exposes bearer-protected GET /api/metrics in Prometheus text
format. Each application instance owns a private registry without process/GC
collectors. Its counters reset on process restart; they are operational evidence,
not the durable business record. No Prometheus or Grafana server is required for
the local foundation. Optional Jaeger receives sanitized application and native SDK OTLP traces in the
explicit business profile. The [Phase G gate](work-items/0013-p1-phase-g-conversation-and-showcase.md)
inspects raw Jaeger v3 trace data and permitted attributes/correlation; a reachable
UI alone is insufficient. This is local evidence, not hosted CI or a load SLO.

Every control API HTTP response carries an internally generated X-Request-ID. Incoming values
cannot select the identifier. Completion/error logs are structured JSON with UTC
timestamp, fixed operation/method, status, duration and request ID. They exclude
request bodies, query strings, headers, model prompts, transcripts, room names,
booking references and provider exception messages.

| Current metric | Measurement | Labels |
| --- | --- | --- |
| livekit_control_http_requests_total | Completed API requests | Fixed operation, method, status class |
| livekit_control_http_errors_total | Requests ending in 4xx/5xx | Same fixed vocabulary |
| livekit_control_http_request_duration_seconds | End-to-end ASGI duration histogram | Fixed operation and method |
| livekit_control_http_requests_in_flight | Currently active API requests | Fixed operation and method |

Health/readiness and metrics scrapes are excluded from business counters and
successful request logs. Their failures remain diagnosable. Unknown paths use
one unknown-operation label; arbitrary URLs cannot create new series. Request,
case, tenant, room, task, delegation and effect IDs must never become metric labels.
Use bounded structured logs/traces for correlation instead.

For local inspection, retrieve the operator token explicitly using the setup
manager, then request /api/metrics with it in the Authorization header. Keep the
token out of URLs, screenshots, shell tracing and saved diagnostics. The
[local guide](../local-setup/README.md) owns ports and credential handling.

## Local and hosted observability

This POC runs its own media server. LiveKit's managed Agent insights requires a
LiveKit Cloud project/media connection and does not cover an entirely self-hosted
stack. Local API metrics, application counters and optional Jaeger traces therefore
remain our actual producers. A LiveKit-like timeline in the console must not be
labelled as the managed Agent insights product. See the official
[observability overview](https://docs.livekit.io/testing/observability/) and
[availability](https://docs.livekit.io/testing/observability/insights/).

The joined application adds finite executor scan/job/close events and aggregate
source-read/HTTP lifetime counts. Those are process observations with no raw body,
key or per-ID metric dimension. A failed or abandoned waiter does not release an
actual runner/read/socket slot. The joined UI and fleet exporter remain separate
integration work; a metrics method alone does not establish either.

## Diagnostic worker application events

The diagnostic worker now explicitly configures a dedicated application logger
at job admission and session entry. JSON records contain fixed service=rtc-agent,
UTC timestamp, severity, event and code, plus optional bounded integer task/track
counts. Module import does not attach handlers or modify the root/native SDK
logger. Repeated entry callbacks reuse one application-owned handler. The
configuration uses a local StreamHandler; this is not a claim that stdout or a
future exporter cannot block. Deployment log throughput needs its own budget.

| Producer | Event/category | Meaning |
| --- | --- | --- |
| Admission policy | job_rejected: invalid_room or job_capacity | Local decision to refuse the job, not a business outcome |
| Session boundary | session_started; session_failed; session_finished | Accepted session lifecycle, safe type-only error category and disconnect/duration/cancel/failure reason |
| Stream policy | stream_rejected: invalid_source, task_capacity or audio_capacity | Actual local admission rejection with bounded counts where relevant |
| Owned task completion | task_completed, task_failed or task_cancelled | Retrieved real task outcome; expected input/timeout differs from transport/unexpected failure; cancellation is informational |

These records exclude text, identities, rooms, track IDs, credentials, raw
exceptions, representations and chains. Native SDK logs retain their separate
configuration and review boundary; this helper does not certify all SDK output.
There is no worker-specific metrics endpoint, trace exporter or new durable
state. Existing transport tests plus telemetry fixtures exercise real task and
callback producers, safe JSON, handler/context isolation and propagation. Actual
stack smoke inspects runtime producers separately. The diagnostic path does not
establish browser playback; the separate G scripted business-media gate does. The local manager supports logs --service rtc-agent to
inspect that producer within its existing bounded redacted tail; logging commands
preserve both child output streams. Combined output can omit earlier events
from another service, so absence from the combined tail does not prove absence
at the producer.

## Error contract

Expected errors retain the existing detail field and add code, retryable,
retry_hint and request_id. Validation errors retain a detail list but omit submitted
values, private context and unknown field names. Responses preserve only relevant
allowlisted HTTP headers, such as Retry-After and WWW-Authenticate.

| Category | Examples | Caller behavior |
| --- | --- | --- |
| Input or permission | authentication_required, validation_error, forbidden | Correct credentials/input; do not automatically repeat |
| Changed-payload replay | idempotency_conflict | Preserve the original payload/key or deliberately create a new logical request |
| Admission or rate | capacity_exhausted, rate_limited | Honor retry hints within the caller deadline; never claim acceptance before acknowledgement |
| Dependency or storage | dependency_unavailable, dispatch_unavailable, storage_unavailable | Inspect dependency health; reconcile any possibly accepted request using the same identity |
| Unexpected boundary failure | internal_error | Return sanitized 500 and request ID; inspect before retry, never expose the exception text |
| Cancellation | request_cancelled or client_disconnected in logs | Propagate cancellation; retain held I/O capacity until already-started work actually finishes |

A disconnected client with no response is recorded as a local 499 observation,
not a server failure or an attempted response. Admission quota is checked inside
the SQLite write transaction for new work; replay/conflict and bounded inspection
remain available at capacity.

A retryable transport/service error is not permission to repeat a supplier effect.
A timeout can happen after persistence. The UI therefore preserves the same request
identity and displays an unknown outcome until acknowledgement or replay resolves
it. Business execution outcome, result applicability, delivery evidence and user
acknowledgement remain distinct. G exposes the durable P1 outcome/delivery states;
P2 result applicability/channel delivery and human acknowledgement retain their
own requirement/evidence boundaries.

## P1 inquiry foundation events

The new execution CLI explicitly configures a package logger with safe JSON
service/timestamp/severity/event/code fields. Library imports attach only a
NullHandler and do not configure root logging. Acceptance, replay, attempt start/
finish and storage failures have real producer events; request values and raw
exception chains are excluded. Migration command reports carry schema versions.
Phase B adds fixed supplier initialization/lookup/inquiry/replay and worker
dispatch/reconciliation/outcome events. Application CLI setup remains explicit,
with safe expected-error exit 2 and sanitized unexpected-defect exit 1. No
worker/provider traces or a new Prometheus exporter was part of that inquiry
checkpoint. F later adds actual worker snapshots; G adds the bounded local
application/SDK trace integration described below.

## PostgreSQL cutover observations

Phase C adds source_quiesced/source_cutover, postgres_schema_installed,
postgres_import_staged/replayed/activated and authentication_rejected producer
events. The same bounded service/timestamp/severity/event/code formatter excludes
SQL, DSNs, tokens, payloads, actor/scope values and exception chains. Operator
results deliberately include synthetic workflow state or migration row counts;
these results are distinct from logs and must not be redirected into telemetry.

source_quiesced is a non-retryable HTTP 503 with use_active_execution_backend;
repeating new writes against a closed source cannot repair cutover. Authentication
uses authentication_required and inaccessible IDs use execution_not_found. A
cutover failure preserves source/backup/receipt for explicit investigation.
The PostgreSQL gate report records test counts, failures, skips and monotonic
runtime. CLI processes do not expose a persistent metrics server; product queue/
recovery/supplier instruments and OTLP were later real-producer work at that
checkpoint; F/G now supply the implemented worker metrics and filtered trace path. Existing
API metrics observe the exercised cutover rejection with finite route/method/status
labels. No performance, throughput or full-tracing claim follows from these tests.

## Standalone intake and specialist HTTP observations

P2's standalone helper separates an acknowledged inbox receipt from a read-only
preview. Invalid/failed preview adapters return fixed StandaloneError codes;
unexpected or malformed intake acknowledgements become AcknowledgementUnknown
and must reconcile the original identity. activePreviews measures actual retained
preview lifetimes, including an adapter that ignored abort. The helper closes its
previews; the application owns the supplied inbox and its acceptance/pool lifetime.
The example report projects actual accepted/replayed receipt and operation IDs,
sequence and pending/not_executed state. It contains no message, token or proof.

P3's Node HTTP producer emits component delegation_specialist plus fixed event,
operation and code fields. Expected rejection, attempt start/finish, observation
and close are separate events. Raw request/response/source bytes, bearer values,
URLs and exception text never become fields. Unexpected boundary defects return
a safe internal_error HTTP 500. The existing contract-error envelope remains
separate from specialist.http_error transport failures; both prohibit automatic
retry advice. Importing either library configures no global logger/exporter.

| P3 metrics value | Unit and meaning | Cardinality / limit |
| --- | --- | --- |
| invoked / completed / rejected | Counts; admitted evaluations / successful computation / rejected HTTP operations | Fixed names; computed does not prove response delivery or business acceptance |
| cancellations / expirations / disconnects | Counts of actual boundary observations | Separate from computation stop, result applicability and business outcome |
| active / requests / sockets | Current retained evaluations / admitted HTTP handlers / connected TCP sockets | Independently bounded to four / 16 / 16 by default |
| observerFailures / observerDropped / observerPending | Failed / dropped notifications and current unsettled callbacks | At most eight unsettled callbacks; overflow drops instead of growing a queue |

Counters reset with the process and have no tenant/case/attempt labels. metrics()
returns values for an application-owned collector; it starts no metrics endpoint.
Observer failures cannot change successful computation, block its acknowledgement
indefinitely or imply a deployed trace/export pipeline. An observer owns external
resources it creates; the default console sink is not a nonblocking guarantee.
Use the [slice work item](work-items/0027-p2-standalone-and-p3-http.md) for actual
socket, sentinel, timeout, cleanup and useful-progress evidence. P3 remains a
scripted read-only foreground HTTP boundary with no durable queue or terminal
history. Native conversational/model metrics and complete product telemetry remain
separate phase requirements.

### Persisted dispatch and accepted-work observations

P2-I07 adds authenticated DispatchObservation inspection of actual persisted
claim epochs, bounded attempt history, prepared operation identity, possible
external acceptance and any reconciled receipt. pending/running, blocked/exhausted,
uncertain and dispatched remain distinct. Once a call may have reached the
cooperating operation port, failure cannot restore a not_executed claim. The older
standalone preview rejects nonpending processing state. ChannelDispatcher counters
and observer events use fixed event/code values, contain no message/token/proof
and reset with the process. Up to eight asynchronous observer notifications are
retained; their completion never replaces database truth.

P1's read-only work profile emits fixed readonly_work_operation events and
contains logger failures without altering acceptance or cancellation truth. P3's
coordinator emits delegation_port operation/outcome/code fields; its bounded
process-local counts distinguish owned port outcomes from cancelled or timed-out
waiters and retained active calls. A timed-out write can remain accepted and must
reconcile its original key. A succeeded port call is not completed specialist work.

The Python HTTP client distinguishes received framed responses from validated
public results/observations, validation failures, transport failures, cancellation,
retained active I/O and incomplete cleanup. These values describe actual local
boundary observations, not durable totals or case authority. No new exporter or
metrics endpoint is started. Fixed errors and logs exclude bodies, evidence,
credentials and raw exception text; application-owned synchronous logging adapters
still require their own execution/flush budgets.

The [current handoff](work-items/0029-p2-gateway-and-p3-issued-execution.md) owns
selected gateway/issued-runner gates. P2's actual gateway emits fixed http/poll/close
events and safe codes. Its process-local accepted/replayed/dispatched/pollErrors/
telemetryFailures counters and active/intakes/sockets/handlers/driver/observerPending
observations describe actual local ownership, not fleet totals or an exporter.
A successful HTTP response is separate from committed acceptance; post-acknowledgement
restart inspects persisted processing truth under the original receipt/key.

P1's optional work v2 profile adds fixed issue/complete/find_issue/result/observe
operations through the same contained logger and bounded I/O metrics. Issued leases
are logical authority, not evidence that a paused remote process has stopped.
The immutable eligible_at_commit disposition denotes P1 scope/time/lease/cancel
eligibility only; semantic facts and case applicability remain distinct. Historical
cancelled/expired/superseded/lease_expired results cannot become current authority.
An eligible known result is retained after later cancellation/deadline, with current
requested cancellation observed separately.

P3's runner emits delegation_run operation/code/outcome and bounded local counts for
invoked, not_reinvoked, active ownership, canceled/timed-out waiters and telemetry
failure. Counters distinguish owned outcome from caller observation. Only a newly
issued command invokes; unknown issue/result acknowledgement reconciles exact
original identity. Strict late HTTP observations still validate identity and facts;
expiry cannot bypass factual rejection. Read applicability may be candidate,
clarification, outdated, cancelled, expired, execution-ineligible or unavailable;
none authorizes an atomic current-case action. The later I07B adapter uses P1's
atomic guard rather than promoting this read observation into permission.

### Owned agent and explicit completion observations

The [agent recovery/completion phase](work-items/0030-p2-agent-recovery-and-p3-completion.md)
adds the following actual producers. Selected phase evidence remains separate
from complete product, browser/media, broader recovery and capacity qualification.

| Producer | Implemented values and meaning | Bounds and failure behavior |
| --- | --- | --- |
| P2 AgentProcess | started/succeeded/failed worker counts; active unreaped/group-present slots; telemetryFailures, observerDropped, observerPending and waiterRejected. Events use started/settled, numeric owned pid, fixed ok/failed code and signal. A validated reaped worker success is separate from delivery to the waiting caller. | Default one actual process, maximum two; eight pending observer callbacks. Worker limits default to 1000 ms execution and 1000 ms cleanup, configurable up to 5000/2000 ms; stdin/stdout/stderr bounds are 32/2/4 KiB. Process/pipe/group ownership survives waiter cancellation. No bodies, tokens, case context or exception reflection. |
| P1 work v3 delivery | Existing readonly_work_operation boundary records prepare/begin/inspect/record-receipt decisions through the bounded work client. Intent, possible-send marker and receiver receipt are immutable persisted facts. | One of each per work within existing WorkLimits; only new begin permits accept. Existing possible sends reconcile by lookup only, and receipt recording preserves known facts after cancellation/expiry. |
| P1 result receiver | result_receiver_operation plus fixed operation/code, bounded async I/O metrics and contained telemetry-failure count. Receipt identifies accepted bytes for an exact receiver/recipient/result. | Four actual I/O slots; default 1000 retained identities, configurable 1–10000; at most 64 trusted scope/recipient bindings. No automatic prune/retry, execution ledger, playback or human acknowledgement. |
| P1 guarded action | guarded_action plus fixed operation/code and finite public-client I/O metrics. Original action receipt and existing exact case intent commit together. | One action per work within WorkLimits; original command replay returns known facts after later cancellation/expiry. SQL-target/credential binding, booking→work→case lock order and database time guard current eligibility. External supplier execution remains separate. |
| P3 completion/action adapters | delegation_completion operation/code/outcome; started/succeeded/failed, active, capacity_rejected, timed_out_waiters, cancelled_waiters, telemetry_failed, receiver_invoked and reconciled counts. | Default two owned calls, maximum four, 5000 ms default waiter and 1000 ms cleanup budgets. Actual owned tasks retain slots after a waiter leaves; fixed sanitized errors and throwing-logger containment preserve committed receipts. |

These values start no metrics endpoint or exporter and reset with their owning
process. Identifiers never become metric dimensions; an owned child PID is an
optional bounded event observation, not a selector or business authority.
Physical process-group disappearance does not prove a remote provider stopped.
AgentProcess is closed explicitly by the application; the gateway does not infer
ownership of its supplied agent adapter. P3 completion clients close their P1
completion ports, while the application retains its result-inspector ownership.
A timeout after writing can be acknowledgement_unknown; reconcile original
identities instead of inventing a new send or action. Known byte acceptance,
exact intent commitment and observed supplier effect remain distinct facts.

### Explicit revision-routing observations

The [completed routing/acceptance phase](work-items/0031-revision-routing-and-delegation-acceptance.md)
adds process-local producers, with no new exporter or metric endpoint. These
observations do not replace case authority or create a command receipt.

| Producer | Actual values | Interpretation and limits |
| --- | --- | --- |
| RevisionRouter | started, revised, unchanged, conflicts, clarification, unknown, unavailable, waiterRejected, telemetryFailures, observerDropped; active and observerPending | Default 2 retained calls (maximum 4),2000 ms waiter/1000 ms cleanup; eight observer callbacks. Fixed case_routing completed/waiter_rejected events contain only code; app observer resources remain separately owned. |
| CaseAuthorityHttpClient | started, known, rejected, unknown, failed and active | One fresh literal-loopback socket per call; default 2 retained calls, 4096-byte response headers/8192-byte body and finite close. Possible revision delivery failure remains OutcomeUnknown; no retry. |
| Standalone ReferenceCaseAuthority | started, revised, unchanged, conflicts, unknown, failed and active | At most 2 retained SQL calls and 64 seeded case identities; owner-only explicit install. A selected standalone authority, never an integrated P1 case projection/copy. |
| Python public-P1 bridge | known, rejected, unknown, telemetry_failed, active_requests and sockets | Four actual calls/16 admitted sockets;4096-byte headers/8192-byte body and response;1000 ms default request/2000 ms close. Shielded actual close observers retain socket ownership after waiter timeout; rejected excess sockets abort without a task queue. Fixed p2_case_bridge code/outcome logs exclude request, identity, token and raw exceptions. |

A known revised/unchanged response, stale conflict, clarification and unknown are
distinct. Current-state inspection after lost ACK cannot turn the original command
into a known acceptance. Provider timestamps are observations, never arbitration.
The router's retained inbox authentication does not recheck current sender
association; no atomic revocation fence is claimed. Resetting these counters cannot
erase persisted input or current case truth.

### Linked exact consent and result projection observations

The completed phase implements the following process-local producers; selected local
qualification passed. No new metric endpoint/exporter is introduced.

| Producer | Actual values | Interpretation and bounds |
| --- | --- | --- |
| ConfirmationRouter | started, accepted, clarification, unknown, rejected, waiterRejected, telemetryFailures, observerDropped, active and observerPending | Default 2 retained calls, maximum 4; 2000 ms waiter/1000 ms cleanup, eight pending observers. Fixed confirmation_routing completed/waiter_rejected codes contain no input/quote/token. Accepted authority outcome and caller acknowledgement remain separate. |
| PromptRegistry | published, replayed, conflicts, lookups, rejected, unknown and active | At most 2 owned SQL calls; explicit owner cap 1–10000 immutable prompts, default 1000. Original response identity and changed-payload conflict survive capacity. Registry is metadata, not case authority. |
| ConfirmationHttpClient | started, known, rejected, unknown, failed and active | Shared finite literal-loopback transport; possible confirmation failure remains unknown. No retry or parsed/reserialized opaque quote bytes. |
| P1 result feed | Existing readonly_work_operation emits fixed result_feed_read/ok after a successful scoped page; public metrics expose pending and telemetry_failures | Four actual I/O slots and five-second close observation. Page≤100, source/cursor scope bound, current retained events≤30000. No result body or identifier metric dimensions, source ACK or execution permission. |
| P3 ProjectionClient and ProjectionProjector | started, succeeded, failed, timed_out_waiters, cancelled_waiters, capacity_rejected, telemetry_failed and active | Retain actual tasks after waiter loss. Projector batches≤8; durable checkpoint/rows are separate from process counts and contain immutable as-of observations. Read failure cannot advance a checkpoint. |

Revision ACK loss has no receipt; exact confirmation ACK loss can reconcile by
explicit original-command replay through the existing P1 receipt. Current P2
association preflight is not an atomic revocation fence. Projection applicability
is as-of its original reads; later cancellation, expiry or case changes do not
refresh stored observations or authorize action.

Selected P3 acceptance wrappers report exact named 13/8/12 assertion inventories,
case/mode/count, monotonic correctness-run duration and actual owned cleanup. They
bind fresh component report bytes to their SHA and reject mismatch/skip/timeout.
No model, native media, latency percentile or production-capacity claim follows.

### Outbound reservation and processing observations

The [completed phase](work-items/0033-outbound-replies-and-completion-processing.md)
adds the following locally qualified producers within its selected scope.
Queued reply, possible attempt, known provider acceptance/nonacceptance and unknown
remain separate observations. Route,
suppression and recipient identifiers remain private record fields, not metric
labels. Carrier calls and actual resource cleanup outlive a canceled waiter when
necessary; timeout does not prove external cancellation.

| Producer | Actual process-local values | Bounds and interpretation |
| --- | --- | --- |
| ChannelOutbox | enqueued, enqueueReplayed, enqueueConflicts, routeSelections, suppressionObserved, controlRejected; started, accepted, definitiveFailure, unknown, held, rejected, waiterRejected, telemetryFailures and observerDropped; active, observerPending and storageActive | Default two actual sends, maximum four; 2000 ms waiter/cleanup, up to 5000/2000 ms. Eight pending observer callbacks; SQL pool has two connections and at most four retained operations. Fixed channel_outbox events include only finite event/code. Control counters describe committed enqueue/route observations, not physical delivery. |
| FakeSmsSendClient | started, known, rejected, unknown, failed and active through the existing local transport | One fresh literal-loopback connection per call; request ceiling 32768 bytes, response ceiling 8192 and headers 4096. Unknown never authorizes an automatic new attempt. Application owns this configured carrier client separately from the outbox. |
| ProcessingClient and CompletionProcessor | started, succeeded, failed, timed_out_waiters, cancelled_waiters, capacity_rejected, telemetry_failed and active; processor also examined, acknowledged, unknown, unavailable and ack_reconciliations | Default two retained actual calls, maximum four. Processing client defaults 5000 ms waiter; processor 10000 ms; both default 1000 ms cleanup, configurable within 20–10000/20–5000 ms. Existing result_projection operation/code/outcome logs remain fixed. Processor row counters describe observed work, including replay; acknowledged is not a durable unique-delivery total. ack_reconciliations counts successful exact lookups after uncertain ACK or checkpoint conflict. A completed processing step may contain unknowns; succeeded is not a delivered-result count. |

P3 exposes discovery scan progress separately from terminal ACK watermark,
receipt-derived terminal acknowledgements and definite not-required as-of
decisions. Unknown/unavailable events are not acknowledged. Scan counts are work
observations, not counts of delivered results. Existing P1 receipt, receiver
acceptance, any user acknowledgement and processing ACK retain separate meaning.
No telemetry failure may change admission, send evidence or ACK truth; new gates
must exercise contained failures and useful progress.

### Callback evidence and applicability refresh signals

The [completed phase](work-items/0034-callback-evidence-and-applicability-refresh.md)
completed selected local phase gates for P2-I13 and P3-I11. Instrument actual callback authentication/admission,
original-event replay/conflict and reducer observations separately from outbox
reservation/provider response. A callback veto is not an external-send fence.
Provider occurrence time is diagnostic and never selects the winning evidence.

Refresh diagnostics distinguish original command replay, new local revision,
CAS conflict, ambiguous commit/exact lookup, raw unavailable reads, effective
invalidation and stable display hide. Persist the separate execution/case/time
observations; local host time is not a P1 database-time receipt. Keep immutable
processing ACK/receiver receipt and current display state distinct. The frozen
producers expose the following actual process-local values; the selected phase qualification passed. Never use account/route/work/event/body labels.

| Producer | Actual counters/gauges | Bounds and interpretation |
| --- | --- | --- |
| CallbackInbox | accepted, replayed, rejected, conflicts, webhookRejected, waiterRejected, telemetryFailures, observerDropped; active, observerPending, storageActive | Four retained actual operations, two SQL connections; default 2000 ms waiter/cleanup, maximum 5000/2000 ms. At most eight unsettled observers. Raw callback≤4096 bytes; signature window 60 seconds, rechecked with DB time after admission. Fixed channel_callbacks event/code records contain no payload or credential. accepted means a new durable provider observation, not delivery or consent; rejected covers public operation/preflight failures. |
| ApplicabilityClient | Inherited started, succeeded, failed, timed_out_waiters, cancelled_waiters, capacity_rejected, telemetry_failed, active; display_hides_observed, write_reconciliations, reconciliation_failed | Default two retained calls, maximum four; default waiter 5000 ms and cleanup 1000 ms, maxima 10000/5000 ms. Hide observations can include original tombstone replay; they are not unique durable-row counts. Reconciliation failure counts failed lookups; absence remains uncertainty/conflict. |
| ApplicabilityRefresher | Inherited operation counters/gauge above; refreshes_observed, command_replays, write_reconciliations, reconciliation_failed | Default two retained calls, maximum four; default waiter 10000 ms/cleanup 1000 ms, maxima 10000/5000 ms. Returned observations may include a concurrent original receipt. command_replays identifies early exact lookup; durable cardinality comes from metadata, not counters. Fixed result_projection operation/code/outcome records retain the existing logger boundary. |

Timeout/cancellation retains actual I/O ownership, and telemetry failure cannot
change callback evidence, refresh CAS or an original receipt. No placeholder zero
counter establishes qualification. Application-owned case clients/listeners and
observer resources remain distinct from each component's cleanup claim.


The callback boundary returns the fixed CallbackError codes InvalidCommand,
WebhookRejected, AccessDenied, NotFound, IdentityConflict, Overloaded,
UpgradeRequired, Unavailable, AcknowledgementUnknown, CleanupIncomplete and Closed.
WebhookRejected covers failed raw-byte/signature/window validation; an unknown
write is not permission to resubmit or send again.

P3 uses the fixed ProjectionError vocabulary. Transient feed reads report
storage_unavailable; contradictory immutable identity reports invalid_source_state
or source_mismatch. Stale local CAS/serialization is checkpoint_conflict, while
uncertain commitment is acknowledgement_unknown. One exact original lookup may
resolve either; failed/absent lookup preserves its original code. capacity never
deletes identity, and cleanup_incomplete means actual I/O is still owned. Raw
dependency messages, credentials and submitted bodies never become error fields.

### Explicit send recovery and protected-action schedules

The [completed selected phase](work-items/0035-send-policy-and-action-races.md)
qualified the local recovery producers. Instrument actual trusted-controller replay/conflict/hold,
lookup-known/absent/unavailable and retry-reservation outcomes separately from
provider call/acceptance and original callback evidence. A replay counter counts
an observed returned command, not a physical message; a lookup timestamp is as-of
provider evidence. The new ChannelOutbox recovery producers expose the counters
below; their selected local qualification passed. Retain fixed finite labels and
keep operation/attempt IDs, account/address/body and private errors out of dimensions.

| Actual recovery counters | Unit and interpretation |
| --- | --- |
| recoveryStarted, recoveryReplayed, recoveryKnown, recoveryUnknown, recoveryHeld, recoveryRejected | Explicit local controller operations and returned/rejected observations; replay performs no provider I/O. Known means validated provider evidence, never physical delivery or human ACK. |
| retryReservations, retryInvocations, lookupInvocations | New durable local retry attempts versus actual provider send/lookup method calls; multiple attempts can share one provider acceptance. |
| lookupAccepted, lookupDefinitiveFailure, lookupAbsent, lookupUnknown, lookupConflicts; retryAccepted, retryDefinitiveFailure, retryUnknown, retryConflicts | Validated lookup/send observations by fixed outcome; absence/unavailable does not grant another send. Contradictions remain separate retained facts. |
| ordinaryHolds, callbackVetoes, permissionVetoes, priorOperationVetoes, attemptLimitHolds, recoveryConflicts | Policy decisions observed under the guarded reservation path; a veto cannot retract an already admitted call. |
| recoveryAcknowledgementUnknown, recoveryAuthorizationRejected, recoveryCapacityRejected, recoveryIdentityConflicts, recoveryRevisionConflicts | Fixed safe failure/uncertainty classifications; a timed-out waiter does not establish rollback or free an active slot. |

Reuse the existing active, observerPending and storageActive gauges: default two
actual network operations (maximum four), four retained SQL calls over two
connections, default 2000 ms waiter/cleanup (maxima 5000/2000), eight unsettled
observers. Recovery commands default to 10000 global/eight per operation, maximum
100000/32; operation bytes≤32768, receipts≤4096 and lookup observations≤2048.
These are safety bounds, not measured throughput or provider resource use.

The unchanged P3 authorizer retains started/succeeded/failed, capacity_rejected,
timed_out_waiters, cancelled_waiters, telemetry_failed and reconciled observations
plus actual active calls. Existing P1 action metrics expose pending actual I/O and
telemetry_failures. These local observations do not prove supplier execution.
Race evidence must join the protected receipt to the independent supplier result,
and distinguish stale_revision, intent_committed, transition_conflict, cancellation
disposition and unknown acknowledgement. Observer failure never changes authority.
Waiter timeout/cancellation keeps work/slots owned through settlement and close.
The gate's two SQL graphs and three SIGKILLs are test observations, not production
metrics or proof that a database fence stopped an already admitted external call.

## Product instrumentation plan

Use SDK-native turn metrics, session reports, usage and OpenTelemetry spans before
adding custom instrumentation. AgentSession per-turn metrics and emitted output
are not browser playback evidence. Do not build against the deprecated session-level
metrics_collected event. Add application spans around durable boundaries without
recording raw sensitive payloads. [Native observability](https://docs.livekit.io/testing/observability/data/),
[session traces](https://docs.livekit.io/reference/agents/session-traces/).

| Project | Required events and spans | Required bounded metrics |
| --- | --- | --- |
| P1 | Intake commit, claim/renewal, attempt, supplier dispatch/reconciliation, confirmation/intent, outbox delivery | Accepted/completed/failed/uncertain counts; queue age; recovery lag; retry/lease rejection; supplier latency |
| P2 | Durable input acceptance, canonical deduplication, case association, channel route, send/callback, interruption/playback observation | Intake/dispatch lag; duplicate/conflict counts; delivery states; route/resumption latency; dormant-record resource use |
| P3 | Delegation acceptance, attempt invocation, result validation, applicability decision, cancellation observation, delivery | Inflight/admission; result latency; stale-result rejection plus valid-result progress; timeout/recovery; per-capability resource use |

Use fixed environment/service/capability/outcome/error-code dimensions. Keep metric
series finite across tenant and case counts. Define schema, units, histogram
buckets and collection points with each implementation slice. Workflow latency
uses monotonic durations where possible; business deadlines use persisted absolute
instants. Never subtract timestamps from unrelated clocks as a latency measurement.

## Local rollout and operational policy

1. Keep the implemented API counters, JSON logs and error envelope working now.
2. Retain the G bounded OTLP path to the optional local collector and its inspected
   raw Jaeger v3 trace/correlation evidence. Add later producers deliberately.
   Separate business exceptions from export failures; telemetry failure must not
   block acceptance, conversation or shutdown indefinitely.
3. Add project metrics/spans with the first real event producers, not placeholder
   zero counters. Retain event history as the correctness record.
4. At a measured load baseline, define scenario-specific budgets and alert
   conditions before judging results. Numeric SLOs follow the declared workload
   and hardware; no production latency or capacity is asserted by this plan.

Bound exporter queues, retries, buffers and shutdown. Redact at the producer;
restrict metric/trace access and keep local endpoints on loopback. Decide data
retention/replay horizons before cleanup; display-history pruning must not erase
effect/idempotency protection. Document any missing signal as unavailable.

A small demo needs a clear failure event, useful safe error, correlated trace/log
and actual final store state. Adding a dashboard stack before the underlying
signals exist is optional work and does not complete a release gate.

## H1 inquiry measurement semantics

The opt-in [H1 work item](work-items/0014-p1-phase-h-workload-baseline.md) owns the
completed local inquiry measurement and inspected results, distinct from full H/P1
release and broader workloads. The versioned
[manifest](../harness/workloads/p1-inquiry-v1.json) freezes seeded schedules,
HTTP/observation pressure, cgroup limits and deadlines before execution. Its
168 new offers, 120 expected admissions and 48 expected capacity rejections are
declarations. make p1-benchmark-plan validates/prints status not_started; only
make p1-benchmark executes the separate installed runtime lane. Setup and artifact
ownership are defined in the [local guide](../local-setup/README.md).

| Observation | Timestamp/unit and scope | Meaning and limit |
| --- | --- | --- |
| Scheduled offer | Host monotonic seconds relative to the experiment budget | Declared arrival; differs from actual HTTP start when caller slots queue |
| First HTTP start and offer queue delay | Same host clock, after acquiring the shared semaphore | Submit/replay/GET/cancel share the declared pool; the five-second network deadline starts after slot acquisition |
| HTTP attempt finish | Same host clock, one record per started attempt | Includes timeout/transport-failure finish; unknown is not an acknowledgement |
| Known admission acknowledgement | After validated successful response under the original key | Original first start to known ack includes unknown retries/backoff; no acceptance is fabricated from timeout |
| First observed inquiry success | First validated successful submit/replay/GET projection, with source | One result record per inquiry; includes queueing and observation lag, not exact supplier completion time |
| Resource probe | Host monotonic start/end/duration around each sequential docker exec | Actual bracket/ordering is retained; not an atomic simultaneous snapshot across roles |
| CPU usage | Cumulative cgroup microseconds, first/last/delta and observed window | Includes in-cgroup Python probe work and post-inquiry cancellation/delivery; no unqualified utilization or throughput claim |
| Memory and PIDs | memory.current bytes and pids.current kernel tasks/threads | Accounted cgroup memory, not RSS; sampled current values are not peaks; probe overhead is included |
| Queue | Current persisted outstanding/active limits, age and recovery lag | Observed authority state, not a second scheduler or full continuous history |

Case observation performs one global round-robin GET, then sleeps 250 ms. HTTP
and shared-slot delay extend the interval; it is not a per-task 250 ms refresh or
hard tick. A large pending cohort adds sweep lag. Resource sampling targets one
second and retains actual probe duration and skipped intervals; overdue slots are
skipped rather than replayed back-to-back. Fixed resource caps are verified exactly
and separately from observed usage. Temporary usage overage is retained instead
of being mislabelled configuration drift.

The CPU quota/period declares bandwidth, not a dedicated physical core. Cgroup
memory includes accounted userspace/kernel/cache components; PID accounting uses
TIDs. Kernel rules allow temporary memory overage and organisational PID overage.
See the official [cgroup-v2 interfaces](https://docs.kernel.org/admin-guide/cgroup-v2.html).
The isolated benchmark does not enable media or runtime trace export. Existing
HTTP/worker observations remain distinct from G's native/OTLP evidence.
Host, Docker VM, shared database and outside-cgroup driver overhead are excluded
from the API/worker samples. Record those exclusions alongside machine/runtime
provenance rather than advertising an end-to-end resource total.

The bounded raw JSONL vocabulary contains HTTP/resource/queue/result/observer
records with finite values; credentials, request bodies and raw dependency errors
are excluded. Correlation stays in controlled evidence, never dynamic metric
labels. The runner preserves the frozen manifest and source/image provenance.
A pre-cleanup measurement snapshot is not a passing phase; reconciliation and
verified owned cleanup are required. Independent inquiry receipts and zero supplier
mutations establish useful investigation progress.

Original failures retain a fixed-enum code/operation on the originating exception,
selected into safe failure evidence before temporary capture removal. Optional
command metadata contains only observed exit_code (or null), timed_out,
timeout_seconds and elapsed_seconds. Cleanup failure observations are separate,
so cleanup cannot replace the original failure. Raw argv/stdout/stderr, environment
values, request bodies and exception text/attributes are not public diagnostics.
Automatically recorded environment metadata is host system/architecture/Python
and installed runtime architecture/versions. A separately collected environment.json
can supply Docker-VM CPU/memory and shared-host context, but the controller does
not collect that hardware automatically.

Later explicit cancellation,
business outcome and receiver delivery remain separate facts. Missing observations
are unavailable, never zero-filled. Summaries retain sample count, minimum, median
and maximum only. No p95/p99, physical capture, model-quality, hosted CI or
production-scale claim follows from this inquiry slice.

## Verification and limits

The final provider run's retained API query is bounded to 100 traces and includes
one failed continuity.get span whose precise cause is unresolved. Retained native
and worker queries contain no error spans. Required progression, privacy, authority
and cleanup passed; complete API history and global zero-error claims are not
established. Per-run live-check state/private process logs, temporary credential envfiles
and copied CA snapshots were cleaned after producer inspection and owned-container
cleanup. The user's ignored .env.providers file and original approved public CA
bundle remain intact; independent review uses retained projections.


API tests check metric authentication, actual inflight work, duration/counter
observations, finite labels, per-app isolation, safe error/log output and
cancellation propagation. Actual stack checks inspect readiness, an authenticated
scrape and structured logs. Browser validation separately checks visible success,
replay/conflict and safe error recovery. A–F add independent process/backend
failure evidence; G adds actual scripted browser/native media and inspected
filtered traces. H declared-workload/resource, hardware/live-model and platform
requirements remain under the [validation plan](validation-plan.md). Local
observations do not establish production security or complete release tracing.

## Implemented case application observations

Phase D CaseTelemetry observes ScopedCaseService operations with a private
registry: continuity_case_operations_total and
continuity_case_operation_duration_seconds. Labels are operation (enroll, get,
revise, confirm, arm_wait, signal, advance, waits, lifecycle, cancel, effect,
completion, delivery) and outcome (success,
rejected, failed). At most 39 combinations can exist. No identifier, tenant,
quote, token, raw error or arbitrary route becomes a label. No persistent product
HTTP exporter or distributed trace pipeline is implied by render().

Case/quote/intent, continuation/attempt/wait/signal and upgrade producers emit
safe fixed event/code; public case_operation adds only validated operation/outcome.
Metrics/log failures cannot alter the business result or mask its original error.
Unit tests check real counter/duration samples, isolation, finite labels, privacy
and outages; the actual container demo checks positive samples and producer events.
Raw operator snapshots remain separate from telemetry and use synthetic data.

## Phase E effect and delivery observations

Actual mutation producers emit mutation_claimed, mutation_dispatch_reserved,
mutation_dispatched, mutation_applied, mutation_reconciled, mutation_finished and
mutation_worker_completed/failed. Cancellation emits cancellation_recorded.
Successful mutation, explicit uncertainty and pre-dispatch cancellation emit
completion_committed. Deadline/cap/negative paths must also be inspected through
the authoritative completion/outcome records; not every return emits that log.
Delivery emits
completion_delivery_started, completion_delivered/failed and
completion_delivery_observed. Supplier/sink replay and diagnostic pruning have
fixed events. The formatter permits only registered event/code values and the
13 bounded case operations; raw exceptions, SQL and DTO payloads are excluded.

The service's private Prometheus registry observes cancel/effect/completion/
delivery calls and duration with the same three outcomes. Counters describe calls,
not durable booking totals. Inspect protected effect snapshots for dispatch and
attempt counts, terminal business outcomes for known/uncertain truth, and delivery
snapshots for receiver, attempts, due time and exhaustion. No business success is
inferred from delivery or a metric sample. Phase E added no HTTP exporter or
trace pipeline; G later implements the filtered local application/SDK export and
inspected trace gate described below.

The Docker demo checks positive operation/duration samples and producer events
before each success/crash boundary, then inspects retained supplier/receiver
records after restart. Unit tests cover malformed/private diagnostics and logger
outage. Independent-process tests preserve outcomes when delivery fails/exhausts.
The [effects guide](effects-and-completion.md) defines bounded retries and safe
operator responses; unresolved external effects need review, never blind resend.

## Phase F worker and lease observations

Lease acquisition, renewal and release have fixed producer events and
lease_busy/lease_lost/lease_required safe error codes. The worker emits fixed
runtime/step start/finish, release failure, health failure and queue-observation
failure events. Child logs are reconstructed only from allowlisted event/code
JSON fields; arbitrary stdout/stderr, identifiers and exception text are dropped.
An epoch is authority evidence for operator inspection, never a metric label.

Each runtime owns a private Prometheus registry. continuity_worker_claims_total
uses finite acquired/empty/stopped outcomes; continuity_worker_steps_total and
continuity_worker_step_duration_seconds use four step kinds and finite process
outcomes. Process completion is distinct from business success. Local active-child
and durable outstanding/active/limit/oldest-age/recovery-lag gauges have no dynamic
identity labels. Lease rejection counts use only three fixed error codes.

Outstanding is unresolved accepted work, including waits and active work; it can
include a manual-review inquiry uncertainty and is not the runnable queue length.
Active counts current database leases. Recovery lag observes expired ownership
for outstanding work or pending delivery; completed and delivered history is
excluded. Retained core receipts and old epochs remain authoritative after metrics
reset. Very small lease settings reduce step occupancy and are not a measured
throughput guarantee. No production latency/HA capacity claim follows.

The worker writes private bounded health and Prometheus snapshots under /tmp;
worker_cli health and metrics inspect them without adding an HTTP endpoint.
Readiness checks freshness and the owned process, not business completion.
Observation is outside the active child monitor so telemetry cannot delay its
occupancy/stop checks. G subsequently adds optional bounded worker step spans and
application/native SDK traces; the local gate inspects raw Jaeger v3 records.
Actual process tests cover logger outage, private/oversized output, timeout,
SIGTERM and descendant cleanup; the installed demo checks real positive samples
and final durable facts separately.

## Business conversation observations

The business API adds fixed business_submit/get/quote/signal/cancel/session HTTP
operations. The shared case registry has sixteen operation values and three
outcomes (48 counter/histogram label combinations), including managed_submit,
projection and prepare_quote. Actor/task/booking/room identifiers never become
metric labels. The API exposes this private registry through its existing protected
metrics endpoint; worker .prom observations retain their independent lifecycle.

Before native speech or control input, the public RoomIO.wait_for_ready barrier
finishes within its ten-second budget. The selected native agent publishes
continuity.session_ready=true; the UI combines it with active SDK state. The
public session_host=False flag disables the alternate lk.agent.session ingress,
so caller/readiness checks remain on the owned bounded controls. These are media
preconditions, not business acceptance or mutation authority.

Native AgentSession session_usage_updated events provide finite numeric LLM token,
STT duration and TTS duration/character totals. After close, make_session_report is
called and only duration/event count are selected. No report.to_dict, chat history,
transcript, event body, provider/model label or tags are serialized. Up to 32 private
4 KiB JSON observations remain under /tmp/conversation-observations in the native
container; restart may remove them. sdk_report_observed is false when report
creation fails. This is diagnostic retention, not a business event store or billing
measurement. Local scripted providers are not inference-quality evidence.

Each trace runtime owns a private provider, a 128-span queue, one exporter thread,
64 KiB request limit and a finite 0.5-second HTTP export deadline. On overload it
drops diagnostic observations. Flush/close have explicit deadlines; shutdown does
not retain business work. The transport uses only the configured credential-free
loopback/Jaeger endpoint and ignores ambient OTLP headers/proxies/retry settings.
It does not read an exporter response body. Collector rejection, timeout and queue
saturation cannot rewrite an operation result.

Exported spans copy only allowlisted operation/model/tool enums, finite numeric
counts and canonical task/effect UUIDs. They strip span events, links, inherited
trace-state headers, exception/status descriptions, arbitrary resource/scope fields
and all content. Original SDK spans remain unchanged. Original provider memory is
bounded by span attribute/event limits; recording is disabled for audio/transcripts.
The dedicated native process sanitizes SDK console records to fixed codes. These
controls do not imply unrestricted third-party SDK logs are safe in other profiles.

G trace inspection validates the raw Jaeger v3 resource/span structure, safe
operation/tool/model enums and the required task/effect correlation. Reachability,
a screenshot or a nonempty response alone cannot pass. The H1 S-I06/P1-I27
work item owns the completed local inquiry baseline and its inspected measurements;
H2 reliability and I26 artifact/API/genuine-consumer checks passed separately. P1 V1 is qualified for the local POC using provider_real v2. local_real remains unqualified and complete P2/P3 acceptance remains pending. Physical microphone/live-model quality needs its own evidence; hosted
CI/publication are outside the local POC scope.

Primary interface references: [LiveKit tracing](https://docs.livekit.io/testing/observability/tracing/),
[session reports](https://docs.livekit.io/reference/agents/session-traces/) and
[OpenTelemetry exporters](https://opentelemetry.io/docs/languages/python/exporters/).
A trace ID expresses diagnostic ancestry, not business authority. External effect
truth, a committed business outcome, delivery receipt and browser playback remain
separate facts.


## Local real-inference observations

The explicit local_real implementation labels trusted profile mode in numeric SDK
usage and sanitized traces. The default scripted lane remains separate. Selecting
a configured profile or matching native readiness is not evidence of actual
recognition, reasoning, generated speech or browser playback; the
[operations guide](local-real-inference.md) owns setup and pending qualification.

| Producer | Implemented observation | Interpretation |
| --- | --- | --- |
| ASR/TTS private /metrics | Fixed engine stt/tts, requests, succeeded/failed, active/max_active, processed input/output bytes and cumulative duration seconds | Request/pressure evidence; not word accuracy, business success or production capacity |
| Native SDK usage/report | Finite numeric model/speech usage with scripted/local_real/provider_real mode | Actual invocation observations; inspect real model/tool outcome separately |
| Sanitized OTLP | Allowlisted finite mode/model/operation and numeric timing/usage fields | Export failure cannot own work; no prompt, transcript, credentials or raw exception chain |
| Browser | Expected profile, native matching readiness, received output and audio currentTime advancement | Configuration, producer state and observed playback remain distinct; playback is not human hearing |
| Durable authority and independent supplier/receiver | Original inquiry/effect/outcome/delivery identities and inspected persisted results | Source of business truth; generated language and engine metrics cannot replace these checks |

Engine health/metrics stay on the private inference network with no host ports.
Raw request files and child/provider diagnostics are ephemeral and removed after
completion or controlled failure. Retained reports contain fixed safe codes,
counts, validated model names, provenance digests and bounded timing/resource
observations. Model-generated strings never become metric labels. Report actual
cgroup memory and CPU windows honestly; limits, lifetime peaks, polling latency
and model quality are different measurements. Real inference/media qualification
remains pending until its actual evidence is inspected. Hosted CI/publication are
outside this local POC scope.


### Explicit provider-real profile

The trusted mode enum is scripted (default), local_real or provider_real.
provider_real uses livekit-plugins-deepgram, livekit-plugins-openai and
livekit-plugins-elevenlabs, all pinned to 1.8.11 with Agents 1.8.11. The fixed
pipeline is Deepgram nova-3 batch recognition on manual flush, OpenAI gpt-5.4-mini
streaming Chat Completions with none reasoning and at most 128 output tokens,
and ElevenLabs eleven_v4_turbo chunked HTTP PCM speech. It is a separately
selected profile, never an automatic fallback from a failed local engine.

The [provider operations guide](provider-demo.md) owns explicit setup/check/start/stop and
the trusted provider P1-20 selector. Three private keys reach only the native
process; local model caches and engines are unnecessary. The selected provider_real v2 gate passed both actual browser cases with cleanup. P1 V1 is qualified for the local POC using provider_real v2. External provider CPU/memory are
unobserved; no zero-retention or model-quality guarantee follows from local
content-free telemetry. Default offline/scripted checks make no provider calls.

Sanitized OTLP copies allow gen_ai.provider.name only as deepgram, openai or
elevenlabs and exact model IDs nova-3, gpt-5.4-mini or eleven_v4_turbo for this
profile. Known upstream display names Deepgram and ElevenLabs normalize only on
the copy; unknown/case-variant labels remain excluded and original SDK spans are
unchanged. Existing five-field finite native logs exclude raw exception text,
prompts, transcripts, audio and keys. Provider metrics are actual numeric SDK
observations, not local-engine counters or fabricated external resource samples.


### Startup and acceptance diagnostics

Native startup_progress records use the existing five-field log schema and six
fixed codes: startup_entry, startup_port_ready, startup_runtime_constructing,
startup_runtime_ready, startup_rtc_connecting and startup_rtc_connected. They are
diagnostic progress; controls/profile readiness and greeting still require the
public RoomIO barrier. No new payload, identity, model content or duration field
is emitted. Pinned SDK warning origins are classified without reading messages,
exception arguments or arbitrary metadata.

The host media helper retains only a closed preflight failure projection: exact
builtin category or other, a fixed owned-source identifier and bounded line
number. Its wrapper keeps that projection even when no runtime artifact exists.
Failure API logs are validated against the producer schema and aggregated by
finite operation/method/status/error category/severity with counts and durations;
timestamps, request IDs and raw records are discarded. Browser session-mint
observations keep numeric status and allowlisted categories, never response
bodies, tokens, prompts or provider errors. An unavailable category remains
unclassified rather than inventing a cause.

Session-mint retries are the existing HTTP invocation replay contract, distinct
from provider inference retries. Observe at most three attempts per logical join,
unchanged room/participant/task/invocation, allowed transient status and final
success; actual native readiness and playback remain separate assertions.

Explicit provider trust setup retains only the selected public CA bundle's byte
count/hash and verified native-only read-only mount proof in local artifacts.
Certificate contents, subjects and original input paths are not log fields or
metric labels. Invalid trust configuration has a finite setup failure; a failed
TLS connection does not establish an API-key, quota or model-access cause.

## Native input and temporal validation producers

The [completed native/deadline handoff](work-items/0036-native-input-and-deadline-cancellation.md)
adds implemented process-local native producer observations. The selected actual
six-group native gate and isolated Python/npm artifact gates passed; fifty-five
Python, 530 P2 TypeScript and sixty-five browser-policy tests exercise the producer
boundaries. Final selected phase gates passed. These fields are not a new
Prometheus exporter or inspected OTLP trace pipeline.

| Producer fields | Units and exact meaning |
| --- | --- |
| textStreamsSeen, voiceCaptures, voiceCommits, genuineFinalSnapshots | Cumulative SDK/input observations; a genuine final is distinct from interim promotion and from durable acceptance |
| durableAcceptCalls, nativeInputsAccepted, nativeInputsReplayed, nativeInputsRejected | Cumulative actual intake calls and validated ACK states; a timeout/lost ACK remains unknown, not rejection |
| nativeGenerationAttempts, nativeGeneratedReplies, defaultReplyInvocations | Cumulative explicit generation attempts, known SDK completions and observed automatic SDK reply events; no field proves playback or business completion |
| activeReaders, activePrepare, activeIntakes, activeVoiceWork | Current actual occupancy retained until owned work settles; never replace missing observations with zero |
| observerPending, observerFailures, observerDropped | Current bounded notice occupancy, cumulative callback/log-delivery failures and cap-driven drops; eight notices maximum; sync/async/log outage does not change accepted truth |

Those groups contain exactly eighteen native metrics. The runtime's fixed
native_state event carries finite native_event/native_code fields. The app's
explicit SDK log sanitizer emits at most 128 records using allowlisted event/code/
level only; it omits messages, transcript text, identifiers, exception strings,
credentials and paths. Failure context retains only a closed stage/error-code/type
and allowlisted owned source basenames/line observations. Observer/task exceptions
are retrieved and independent cleanup is attempted after an earlier close failure.

Reliable p2.generation observations have exactly schemaVersion, bindingId, inputId,
operationKey, generationId and status. The selected native AGENT publishes them;
the browser requires an already accepted matching input/operation and retains at
most 64 generation identities. started/completed/interrupted/unknown describe SDK
attempt observations. Browser audio playback remains separately observed, and
neither source supplies human acknowledgement or exact quote consent. A rejected
retry cannot erase an earlier unknown input acceptance.

P3-I13 adds validation composition and no new producer/exporter. Existing runner/
HTTP/completion metrics remain authoritative. Its retained direct proofs distinguish
nine computations/results from actual zero live peer occupancy after shutdown,
remote cancel requested, one non-durable running ACK and one lost ACK. P1 database
time after locks determines eligibility, while host/peer timestamps and refreshed
applicability are observations. The unchanged authorizer remains the only path to
an exactly confirmed current action. The selected source/installed eighteen-case
and forty-six compatibility assertions passed for I13. Selected I14 recovery then
passed as recorded in the current playback/recovery observations below; I15 release
completeness is now implemented and selected local installed qualification passed;
full charter release remains separately gated.

## Response evidence and recovery observations

The [playback/recovery handoff](work-items/0037-playback-evidence-and-process-recovery.md)
owns selected current source, package, process and media evidence. Original eighteen
native metrics and six-key p2.generation observations keep their meaning.

| Producer | Fields and meaning | Limits |
| --- | --- | --- |
| P2 communication store/gateway | responsesAccepted/responsesReplayed, observationsAccepted/observationsReplayed, identityConflicts, rejected, unknownAcknowledgements, capacityRejected, telemetryFailures | Fixed cumulative counters; no tenant/input/response/transcript label |
| Communication observer | observerPending and observerDropped | Actual bounded notification occupancy and cap-driven drops; outage cannot change accepted facts |
| Python communication capture | anchorsKnown, generatedFactsKnown, sdkFactsKnown, browserReportsKnown, unknownAcknowledgements, rejectedReports, observerFailures | Counts known original receipts or contained observation failures; a lost ACK stays unknown |
| Python actual ownership | activeNodes, activeProducers, activePublications, activeReports | Actual LLM/TTS/tasks/streams retained through ignored cancellation and late settlement; zero only after settlement |
| Browser playback | Non-silent and sampled PCM milliseconds, source state/count, actual reader/I/O/meter ownership | Continuous selected-track response window; neither hearing nor business success |
| P3 recovery fixtures | Finite stage/code/type, owned PID/return code, original receipt/digest joins, real SQL blocker graph and independent supplier apply count | Validation observations over unchanged authorities; no new exporter or automatic recovering queue |

Response mappings use a separate eight-key p2.response wire. Full generated text
is available through the bounded authenticated read, never metric labels or logs.
SDK synchronized text is its own observation. Contradictory source facts remain
inspectable and conflicted; timestamps do not select a winner. Client completion
is a report, and missing reports stay unknown.

Finite child and browser diagnostics are retained before private-tree cleanup.
Browser timeouts use the last actual finite observation when the page has already
closed. Exception messages, bodies, tokens, arbitrary URLs, paths and raw browser
assertions are excluded. Primary failures survive secondary sink/close failures;
all independent cleanup owners are still attempted. These are inspected local
producer proofs, not a newly qualified Prometheus/OTLP export pipeline.


## Read-only rehydration and standalone gate observations

The [completed handoff](work-items/0038-case-rehydration-and-standalone-release.md)
records selected eighteen-group storage and three-group actual media qualification,
Python/npm consumers and the sixteen-assertion P3 installed command. Preserve the original native eighteen and communication eleven metric
fields; the optional context profile exposes separate groups:

| Producer | Numeric fields | Interpretation |
| --- | --- | --- |
| P2 facade | started, known, denied, invalid, unavailable, overloaded, waiterRejected | Admitted read outcomes and bounded waiters; preflight listener rejection is separate |
| P2 facade ownership/sink | active, observerPending, telemetryFailures, observerDropped | Actual pending read/sink ownership; a timeout cannot free ignored I/O |
| Context HTTP listener | started, known, rejected, sockets, handlers | Explicit loopback endpoint outcomes and actual transport owners |
| Python context client | started, known, unavailable, active | Validated bounded reads; no input/generation side effect |
| Optional SDK profile | loads, loaded, failed, revisionMismatch, active | Context initialization/idle refresh; equal revision does not establish supplier/workflow freshness |
| Browser context view | phase, source revision, original history/response references, active reads | Protected display observations, not metric labels or current-room media authority |

Use fixed finite error/event codes and omit identifiers, text, quotes and credentials
from metric labels/logs. Translate semantic denial/cursor failures through the actual
transaction normalizer without reporting a storage outage. Retain actual rollback,
readers and close tasks after timeout. SDK/model context proofs bind actual public
message IDs and original receipt IDs while retaining only bounded metadata.

P3's package gate records eight offline/eight actual assertions, exact bounded
children/captures, built artifacts and three correlated source/authority/replay
proofs. A source-bound owned kill and zero new method entries on replay remain
separate from physical exactly-once or human acknowledgement claims. First failure
uses finite stage/code diagnostics; secondary sink/close failures cannot replace
it. Unreaped children or incomplete dependent readers withhold DDL/temp removal
and preserve private owned work with cleanup incomplete.


The selected media run observed three native accepts, one separate signed SMS,
four operation acceptances, three response identities and six SDK source facts;
client playback reports were disabled, so browser evidence remained unknown.
Actual rendered PCM and the new B reply were observed separately. Rehydration
loads generated zero replies. Original SDK/SQL receipt joins, as-of B context and
zero owned rooms during SMS were independently inspected. These observations do
not establish human acknowledgement, supplier delivery or a new telemetry export
pipeline. Selected P2-I19/P3-I16 qualification passed; P2-I20/P3-I17
passed their selected qualification in the 0040 handoff.

## Active workload and document observations

The [completed slice](work-items/0039-bounded-channel-workloads-and-image-evidence.md)
adds the producer surfaces below; selected source/installed/workload qualification passed in that handoff. Prior checkpoint counts above retain their historical scope.

| Producer | Current numeric fields | Bound and meaning |
| --- | --- | --- |
| P2 ordinary inbox telemetryMetrics | observerPending, observerDropped, observerFailures | Eight reserved ordinary callbacks, separate from the existing eight communication callbacks; pending remains observable until actual callback settlement, including after SQL close |
| P3 DocumentHandler | providerStarted, providerSettled, providerFailed, providerActive, active | Counts and occupancy for the configured scripted provider; four owned handler calls, with no OCR/model usage or action-authority meaning |
| P3 PNG decoder | workersStarted, workersSettled, workersActive, observerFailures, workerObserverPending, workerObserverDropped | Actual worker lifetime and bounded observation sink; a result is normal only after exit 0, and an incomplete close retains actual owners |
| Shared image transport | Existing HTTP/client outcome and active-owner counters | Finite capability/operation/error vocabulary only; unchanged policy defaults and no identifiers or source text as labels |

P2's study retains declared seed, sample cadence and observed process RSS/CPU,
event-loop and latency maxima. These are selected process observations, not per-case
RAM or production SLOs. The application owns external observer transport; SQL drain
cannot claim that a held callback stopped. Pending/dropped/failed telemetry never
blocks accepted business progress or creates unbounded callback work.

Image proofs distinguish structural acceptance from independent synthetic-image
factual verdicts, canonical client-returned wires, provider entries and worker exits.
Server result digests are joined after shutdown to those canonical wires, not an
independent raw-server serialization capture. Failure contexts retain only finite
mode/stage/error codes, with no raw exception text, tokens, headers or image bytes
in diagnostics. Image content cannot authorize instructions, consent or mutation.

## Operations read and fixed-policy observations

The [operations and policy handoff](work-items/0040-operations-ui-and-fixed-policy-evidence.md) owns selected P2-I20/P3-I17 qualification. The prior workload/image
producer table describes implemented surfaces; its normal gates passed in 0039.
Selected normal operations/policy qualification passed; full project release remains separate.

| Actual producer | Finite observations | Interpretation |
| --- | --- | --- |
| P2 operations reader | Caller started/known/denied/invalid/unavailable/overloaded/waiterRejected/active; actual readerStarted/readerKnown/readerWaiterRejected/readerActive; bounded observer ownership/failures/drops | Caller timeout and actual read settlement are separate; the reader retains its two-slot bound until the transaction and external case read settle |
| P2 collector | inbox, inbox_telemetry and operations snapshots, bounded getter/observer ownership and safe completed-read spans | Three real configured producers; absent producers stay absent. Up to eight callbacks/getters and thirty-two recent safe span rows; durations reflect actual milliseconds |
| P2 optional page | Observed context/as-of, historical/current state, last finite error, actual requests and close outcome | Refresh and signed cursor pages perform reads only. Last labelled facts survive failure; Forget fences the view while the client still owns unfinished work |
| P3 TypeScript HTTP client | started, settled, active, invokeStarted, statusStarted, cancelStarted, validated, validationFailed, capacityRejected | Actual transport ownership and correlation validation; validated does not mean factually correct or eligible for action |
| P3 fixed-policy handler | evaluated and clarified | Finite scripted-rule outcomes with separate immutable source witnesses; no model accuracy, execution or consent meaning |

The operations operator capability is distinct from current native-context access.
A context denial pauses current presentation; earlier diagnostics remain labelled
historical until Forget clears them. Metrics carry no case, tenant, input, source,
credential, cursor, transcript or prompt labels. Source-specific diagnostic rows
are authenticated bounded observations, never metric labels or execution authority.
The collector is process-local, not a fleet exporter or durable totals service.

Use stable typed error codes. Bad scope/cursors remain semantic failures; SQL or
transport outages become unavailable. The new HTTP adapter returns invalid 400,
access 403, stale 409, retained-reader overload 429, and unavailable/closed 503.
A hard listener/socket cap may close transport; it cannot promise a typed response.
Fixed-policy structural failure, unsupported rule/facts, permission, deadline and
capacity remain separate outcomes. Preserve the first failure and attempt every
independent cleanup tier; incomplete readers, sockets, workers or children remain
owned until settlement and block dependent removal.

The selected 0040 profile emits three actual sources: inbox, inbox_telemetry and
operations. The public adapter also accepts closed source-specific envelopes from
existing dispatch, gateway, outbox, callback and rehydration producers. Its 76
finite cause codes preserve real producer meanings; unknown envelopes, arbitrary
labels and accessors are dropped safely. These codes are not tenant/payload labels.

Observer and getter completion ownership is reserved before invoking configured
code, including returned thenable accessors. A reentrant close observes that
owner, stops later getter admission, and remains retryable after actual settlement.
The eight-callback/getter and two-active-span bounds, thirty-two-row ring and
existing metric names remain unchanged. Full real-producer and reentrant controls
failed before the fix and passed after it. The actual selected PG/browser gate
observed useful business progress despite a held/failed exporter and zero final
owned resources; this does not qualify an external Prometheus/OTLP pipeline.
