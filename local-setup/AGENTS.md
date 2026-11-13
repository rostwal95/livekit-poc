# Local setup coding agent instructions

Status: Active
Last reviewed: 13 November 2026

## Read first

Read [root instructions](../AGENTS.md), [README.md](README.md),
[Design.md](Design.md), the [technology baseline](../docs/technology-baseline.md)
and the [validation plan](../docs/validation-plan.md).

## Owned paths

Own Compose, lifecycle management, local image/configuration files, Dockerfiles
and transport smoke scripts. Runtime application code belongs in services and the
console in apps. Keep orchestration separate from business workflow logic.

## Development rules

Use exact image versions/digests and frozen dependency installs. Never source
configuration as shell code, print expanded credentials, bind operator endpoints
publicly, mount the Docker socket into services or mutate another stack. Preserve
named volumes during normal stop/start. Reset requires its explicit confirmation.

Keep health/readiness distinct from actual media or product acceptance. Check
browser and container ICE paths with real traffic. Keep operational scripts
bounded, resource limits coherent and output secret-safe. Use an independent
restricted application database role; never pass bootstrap credentials to the
serving API. Do not weaken TLS verification to repair a build.

The explicit P2 loopback case bridge is application composition over preconstructed
public P1 clients. Confirmation requires a separate opt-in binding; keep opaque
canonical quote bytes, original input command identity and mapped task/case checks
before the one public atomic confirmation call. Revision unknowns have no command
receipt; confirmation original-command replay uses the existing P1 receipt. Keep
current P2 association preflight distinct from an atomic cross-store fence.
Retain actual sockets/calls through late close and never expose provider secrets,
quote issuance or model-facing mutation tools. P1 work v4/P3 projection setup is
explicit owner tooling, with no new default service or runtime DDL.

P2 outbound reservation and suppression/association checks share the inbox
admission transaction; external carrier I/O is outside it. Preserve immutable
recipient/attempt routes and truthful possible-call uncertainty. P3 processing
uses explicit owner metadata v2 and public P1 delivery/receiver ports only; no
new P1 migration or default service is needed. Its scan cursor is not a terminal
ACK watermark. Exact role-separated gate children must exclude ambient provider,
proxy, Python-path and database selectors; retain finite capture and PID ownership.

P2-I12/P3-I10 selected backend and installed-consumer gates passed. The ordinary
stack readiness/text/audio smoke preserves original M1 state; its observations
remain transport evidence. Keep automatic booking-completion handoff, provider
calls, ambiguous resend and new UI/native composition outside those selected gates.

### Native/deadline fixture operations

Use the [completed handoff](../docs/work-items/0036-native-input-and-deadline-cancellation.md).
Native composition is opt-in host SDK/gateway/browser against local Docker SFU/PG;
it changes no default M1/P1 service. Owner-only quiescent v6 setup adds two native
tables and preserves prior identities; serving roles do no DDL. Native ingress,
prepare, account/publisher and browser RTC credentials have separate owners and
must never be interchangeable. Ordinary local setup is sufficient; do not read
provider credentials or call paid inference.

Keep fresh database expiry/revocation checks after admission/binding locks, retain
known history and distinguish an already reserved possible call. Close every owned
socket/task/room and report incomplete while actual I/O remains. Selected actual
native and isolated Python/npm artifact gates passed; final selected phase regression/shared
checks and the affected media rerun passed. Source/installed P3 eighteen-case
and forty-six compatibility assertions passed. The [current playback/recovery handoff](../docs/work-items/0037-playback-evidence-and-process-recovery.md)
owns selected I17/I14 results; I18 rehydration and P3-I15 standalone consumption
passed selected qualification in the [completed handoff](../docs/work-items/0038-case-rehydration-and-standalone-release.md).

## Current send-policy and protected-action validation

The [completed send-policy/action-race phase](../docs/work-items/0035-send-policy-and-action-races.md)
completed the selected local gates for P2-I14 and P3-I12. P2 policy APIs
require explicit owner inbox v4-to-v5 maintenance/quiescence and preserve all old
request/result/callback bytes. Ordinary possible sends remain held. A separately
trusted cooperating provider may reuse frozen original operation bytes/key only
under a new explicit recovery-controller command and current permission. Retain
callback exact-attempt correlation and vetoes; never retarget the original address.
P3's new gate uses unchanged public work v4/booking v4 guards and independent
supplier fixtures, with no projection upgrade or new daemon. Its 31 modes/16 cases
require two prewarmed SQL waiter graphs and three owned kills under a 180-second
total budget: 165 seconds work and 15 seconds cleanup. With the documented
restricted-role setup, make p2-send-policy-check and make p3-action-races-check
passed their selected synthetic backend gates. Existing callback/applicability commands
retain the previous checkpoint's passing scope. No provider key, default Compose/
UI change, named-volume reset or automatic booking-completion handoff is added.

## Previously qualified callback and applicability profiles

The [completed phase](../docs/work-items/0034-callback-evidence-and-applicability-refresh.md)
completed selected local phase gates for P2-I13 and P3-I11. Callback APIs require explicit owner inbox v4 setup;
P3 refresh/display metadata requires an explicit owner projection v3 upgrade.
P1 work v4 and booking v4 remain unchanged. No new default daemon, Compose/UI
route, provider credential or paid call is introduced.

Callbacks authenticate a separate raw-byte HMAC capability and correlate exact
old attempts independently of current sender association. Their evidence cannot
open a resend. Refreshed applicability uses explicit per-result CAS and separate
as-of source/case/time observations; hiding display preserves all identities and
unresolved processing. Callback bytes are capped at 4096; the signature window
is 60 seconds and is rechecked against database time after admission. Callback
bounds default to 10000 total/eight per attempt, maximum 100000/32. Refresh commands default to 3000 total/four per event,
maximum 30000/eight, with receipts at most 4096 bytes. Equal replay remains
available at capacity for the profile lifetime; no physical deletion or capacity
reclamation exists. The isolated role-separated actual gates and offline installed
consumers passed their selected assertions; existing quickstarts retain their qualified scope.

## Local real-inference profile

Read the [operations guide](../docs/local-real-inference.md) before changing model
preparation or engines. models-fetch is the only explicit weight-download action;
models-verify and all start actions verify without fetching. Keep the immutable
manifest, exact byte/digest checks, owned preparation lock/child deadline and
ignored cache. Runtime model mounts are read-only with no automatic empty host
path, and p1-models services expose no host ports or application credentials.

Preserve scripted defaults and explicit start-local-real/stop-local-real behavior,
ACTIVE v4/same-scope read-only preflight, exact consent and existing data. Engine
CPU/memory/PID/tmp ceilings are bounds, not a resource admission or capacity result.
Record actual inference/media evidence separately from cache/readiness and keep
local host/container checks independent of optional hosted automation.

Trusted inference modes are exactly scripted (default), local_real and
provider_real. Preserve the selected mode through mint, native readiness, numeric
usage and sanitized traces. A configured badge or process health is not actual
inference/media qualification. No silent provider/model fallback exists. All modes
preserve bound tools and separate exact human confirmation. Read the
[provider operations guide](../docs/provider-demo.md) before changing provider composition.
Offline validation must not read private key values or invoke providers. Never
source, print, copy or include local-setup/.env.providers in reports or build
contexts. Only the explicit native provider runtime receives the three keys.

Preserve strict owned mode 0600 credential loading, presence-only checks and explicit start-provider/stop-provider. Stop must attempt credential-bearing native-container removal even if another drain/reset fails. Never forward keys to API, worker, collector or local engines.

### Origin publisher ownership

Use the [0044 work item](../docs/work-items/0044-origin-bound-channel-policy.md)
for the configured P2-input/P1-policy bridge. Its literal loopback host retains
four handler lifetimes and at most eight sockets; the coordinator separately owns
four actual P1 calls. A settled HTTP/service waiter can leave P1 I/O owned by the
coordinator. Close the host, then service/core, then shared case readers, and retain
incomplete owners before any dependent cleanup. Never infer a database rollback
or cancelled business effect from a disconnected socket.

The original P2 owner-returned receiver UUID is a trusted publisher assertion,
not fresh runtime DB attestation. Real origin qualification must independently join it to the actual receiver row
and original accepted input, as the selected fourteen source assertions do. The current
25-stage isolated package lane verifies 20 legacy plus 41 origin fake-port tests;
it does not repeat the fourteen separately passing actual PostgreSQL assertions. Keep all
private paths, source bindings, failed reports and process indexes intact.

## Verification

Run from the repository root:

```sh
python3.14 local-setup/stack.py config
python3.14 local-setup/stack.py doctor
python3.14 local-setup/stack.py smoke
.venv/bin/python -m unittest discover -s tests -p 'test_local_setup.py' -v
```

Configuration and unit tests precede actual startup. Test actual readiness,
text/audio, secret exclusion, shutdown and persistence when infrastructure
changes. Do not run reset against existing user state as an ordinary check.

## Handoff

Record config/runtime versions, affected ports/services, exact validation,
observed media path, persistence outcomes and limits. Keep credentials and raw
source-control identifiers out of documentation. Update setup, design and
capability status with changes; preserve pending product acceptance cases.

## Phase E operations

Read [effect operations](../docs/effects-and-completion.md) for v3 and run
make phase-e-demo after rebuilding changed runtime code. Keep migration/bootstrap
credentials out of runtime probes. Demo fixture volumes and schemas must be
new, UUID-owned and checked before cleanup; do not reset application state.
Preserve the failure output and rerun serially when database checks or image
builds contend. A timeout cannot count as a pass.

## Phase F operations

Use the explicit p1-workers profile only after controlled ACTIVE v4 preparation.
P1_WORKER_SCHEMA selects the optional worker/migration target, while M1 remains
SQLite. Fixture initialization is explicit and retains provider/receiver identity;
never copy bootstrap credentials into the worker. Leases use database time, and
runtime process occupancy uses monotonic time. Preserve stopped/uncertain work
for another epoch instead of asserting that a killed external call failed.
Run make phase-f-demo after image rebuild; require actual retained waits, useful
progress, positive metrics, safe logs, same installed source and owned cleanup.

Business integration uses the p1-business profile and explicit start-business /
stop-business commands. Keep business mode disabled for ordinary start; inherited
shell flags cannot activate it. Preflight must verify an existing ACTIVE v4 schema
and seeded same-scope provider/receiver without mutation. Native receives runtime
PG and LiveKit credentials only. Preserve the API read-only supplier mount and
35-second worker drain. Test tests/test_business_setup.py and the actual isolated
Phase G demo; missing Chrome/media/traces leave required assertions non-passing.

## Phase H workload operations

Read the [H1 work item](../docs/work-items/0014-p1-phase-h-workload-baseline.md). The opt-in benchmark drives installed API/workers in fresh UUID-owned schemas/fixtures, without altering the ordinary M1 stack. Freeze schedules, HTTP observation cadence, resource limits and deadlines before measurement. Admission, read, replay and cancellation share declared HTTP concurrency. Retain safe raw observations and independent supplier truth, fail missing progress/setup/cleanup, and keep outcome/delivery/cancellation distinct. Cgroup accounted memory is not RSS. Preserve closed G evidence when running the actual browser regression. No benchmark result establishes production capacity or speech/model performance.

Explicit provider CA setup uses approved public certificate-only data and a
native-only read-only OS trust-file mount. Keep strict TLS hostname/CERT_REQUIRED
verification, fixed routes and trust_env=False. Never copy trust data into images,
keys into a CA file, or CA mounts/settings into API/worker/browser. Preserve the
single atomic interactive configuration snapshot and per-run snapshot lifetime
through verified native removal; incomplete cleanup must retain it and fail.
Repeat strict CA-file, restrictive-permission, mode-isolation and trust-evidence
binding tests when changing this boundary.

## Playback and recovery gate ownership

The opt-in v7 communication profile adds three tables through explicit quiescent
owner migration over v6. Serving credentials never perform DDL. Keep publisher,
SDK, browser-report, account, native input, prepare, operator read and RTC roles
separate. Store growth uses the existing four-operation/two-connection admission;
response sequences are account/conversation scoped and observation sequences are
response-local. Late original facts survive expiry/revoke without new preparation.

Run make p2-communication-check and make p2-playback-check separately. The first
has sixteen actual PG groups and direct public API observations; receiving HTTP and
real SDK/browser media have separate evidence. The second has three media groups
in one Playwright case. Preserve budgets, actual owned backend PID bindings and
pre-lock/post-lock database clocks. A missing query under restricted-role redaction
is not evidence that no waiter exists. Retain finite diagnostics before deleting
private scratch; all cleanup owners run after the first failure.

make p3-recovery-check uses unchanged P1/P3 runtime authority, eight actual owned
kills, one SQL issuance graph and an independently observed fake supplier effect.
Fresh installed consumers have their own proof; a source run cannot stand in for
archive isolation. Complete charter/release registrations remain separate.


## Current-case and standalone ownership

Use the [completed handoff](../docs/work-items/0038-case-rehydration-and-standalone-release.md) for selected I18/P3-I15 qualification. The read-only context facade derives
scope from a current native grant or exact already accepted SMS/current epoch,
not from old account-history access. Read coherent P2 state, release SQL for the
external case read, then recheck disclosure permission under locks using fresh
DB time. Case/history times and source fingerprint are independent observations;
revision equality alone cannot make supplier/workflow state current.

The new loopback current-case bridge performs one public ManagedCaseClient.get
through a preconstructed mapped reader. Allowlist facts only; no quote, exact
confirmation payload or mutation controls cross this read port. Its listener and
actual get tasks settle before the application closes the shared reader/boundary.
A bounded close observer failing is not actual drain; retry the public close while
retaining ownership, and withhold dependent schema removal. Stage deadlines or
close requests must not admit new fixture business stages after late I/O settles.

The optional native profile displays P1 revision 0 but preserves the existing
positive-revision native intake/prepare boundary. Never map 0 to 1 or auto-revise.
The selected media sequence actually closes/deletes A, runs the fixed signed SMS
with zero A/B rooms, then creates B and waits for its exact parent-owned marker.
Original receipt/operation/history facts are inert context; only new accepted input
may generate a reply. Keep SDK output, client PCM, supplier results and human
acknowledgement separate. No timers may manufacture progress or hearing.

Run make p2-rehydration-check and make p2-rehydration-media-check separately.
P3 make p3-package-check is offline8; make p3-package-lab-check explicitly adds8
actual lab assertions to those8. Keep runtime/owner credentials role-separated,
installed products isolated. The prior standalone checkpoint preserved 77 P1/30 P3
payloads; the prior image checkpoint preserved 77 P1 payloads and qualified
32 P3 runtime payloads. The current I17 checkpoint qualifies 34 P3 runtime payloads. Reap all
owned children before DDL or temporary removal; unresolved ownership retains work
and cleanup:false. The selected 18-group storage, three-group media and P3 combined 16-case gates passed; no hosted CI,
provider calls, default Compose change or full charter claim follows from these lanes.
P2-I19 workload/dormancy and P3-I16 standalone image HTTP passed selected
qualification; selected P2-I20 joined-view/telemetry and P3-I17 fixed-policy
evidence also passed their 0040 gates. Selected P2-I21/P3-I18A qualification
passed in 0041 and P3-I18B native RTC text passed in 0042; integrated voice/SMS
return routing remains separate. Preserve the fifty-five catalog/twenty-four registered
runner boundary; full seventeen-row P2 and fourteen-row P3 acceptance remains planned.

## Active workload and image operations

Read the [completed handoff](../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md)
and inspect make p2-workload-plan / make p3-document-plan before actual gates.
P2-I19 uses fresh owner-marked v7 profiles and existing restricted runtime roles;
keep public setup/inspection windows at 64, retained capacity distinct from active
work, no per-case rooms/agents and no physical identity deletion. Ordinary observer
callbacks have a separate eight-slot cap from communication's eight callbacks.
External observer transport remains application-owned after SQL close.

P3-I16 source HTTP is database/provider-free; installed mode reuses only fresh
source-bound package output and declared unadapted consumer inputs. Preserve the
finite two-capability dispatch and policy defaults. Check actual PNG bytes before
provider entry, retain fixed workers/provider promises until settlement and retry
public close after incomplete observation. P1 stays policy-only; image text/result
provides no tool, consent, projection or action permission. Aggregate child/capture
budgets include the nested builder and owned process groups. Unknown ownership
withholds private work removal. Both selected qualification lanes passed;
Selected P2-I20/P3-I17 passed the 0040 gates, P2-I21/P3-I18A passed 0041,
and P3-I18B native RTC text passed 0042. Combined voice/text/SMS return routing
and full release remain separate.

### Operations profile closure

The [completed 0040 handoff](../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md)
records P2's 16 operations groups, three browser groups, seven npm stages and
187 compatibility assertions, plus P3's twenty source/twenty installed fixed-policy
assertions and separate package/image/146-assertion compatibility outcomes. Normal setups
use unique marked disposable profiles and distinct product-evidence/process-capture
directories. Reap actual owners before dependent removal. Preserve failed reports
and explicitly approved exact recovery as separate observations; never retry a
rejected destructive action through an alternate path. No provider/private-CA
settings or default image/Compose changes were needed for this selected slice.

### Stable result-return operations

Use the [0043 handoff](../docs/work-items/0043-stable-result-delivery-and-return-context.md)
for P2 v8 receipts and P3 v2 delivery. Preserve the sixteen-group actual schedule
and separately bounded twenty-five-group offline package lane. Only explicit owner
maintenance performs DDL. Runtime credentials never repair schema drift. Stop and
reap owned groups before dependent removal, index their actual final states and
retain the original failed reports. Private nested directories must each be 0700;
never chmod a prior failed observation to make its evidence pass. The twenty source assertions and
twenty installed fake-port tests are different assertions; native-grant data reads do not
establish RTC media or provider inference.


### Joined launcher ownership

The explicit scripted launcher consumes existing prepared profiles and prebuilt
artifacts. Its three closed child roles are specialist, gateway and optional
public Vite preview; keep their environments distinct and bounded. Parent owns
native room/SDK process lifetime and the background App. Begin UI and Parent
closure independently before awaiting slow owners, then drain both before Node
dependencies. Preserve late factory/spawn/read ownership and require actual pipe
EOF, process reap and group absence before clean completion.

Normal restart retains private operator/static configuration and all product
state. An existing active marker fails closed; never overwrite, silently recover,
drop schemas or associate a sender during serving. Plan/import paths are inert.
Serving reads only maintained infrastructure settings, never provider files.
Actual joined media/provider gates remain required beyond component checks.
