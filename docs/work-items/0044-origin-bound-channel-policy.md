# Origin-bound channel policy acceptance

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the plan, observed verification and handoff for origin-bound channel policy acceptance |
| Audience | Engineers changing channel-policy v3 contracts, the P2 operation client or the origin bridge; coding agents |
| Scope | Selected P3-I19 and P2-I22 origin-binding slice; excludes accepted-work discovery, whole-stack restart, provider inference, video and charter registration |
| Owns | Change plan, observed verification and handoff for the origin-binding slice of P3-I19 and P2-I22 |
| Related | [Work item 0043](0043-stable-result-delivery-and-return-context.md) · [Work item 0045](0045-joined-native-channel-policy.md) · [P2 task plan](../implementation/p2-channel-continuity.md) · [P3 task plan](../implementation/p3-delegation-reliability.md) · [Validation plan](../validation-plan.md) |

## Behavior and scope

This work item implements the next selected P3-I19/PLAN-20 and P2-I22
integration contribution, with P3-12 and selected P2-09/P2-12 prerequisites.

- One original P2 PreparedDispatch maps to one P1-owned policy work receipt.
- Equal replay and concurrent winners retain the first accepted deadline,
  evidence and full canonical request.
- A changed original payload cannot select a different key or replace accepted
  work.

The [completed 0043 handoff](0043-stable-result-delivery-and-return-context.md)
qualified the v2 delivery/read seam. Its durable local closeout binds 270 current
files, source twenty, package twenty-five stages, 2,669 Python/1,605 TypeScript
tests and complete cleanup. Preserve its immutable reports, archives and failures.

This slice adds original-input binding before the joined native/voice/SMS
journey. It introduces no new durable queue or P1/P2 storage version. Explicit
run/delivery is in scope. Accepted-work discovery, whole-stack restart, provider
inference, video and complete charter registration retain their later gates.

Contents of this record:

| Section | Contents |
| --- | --- |
| Behavior and scope | Terms and criteria |
| Interfaces and ownership | Schema3 persistence, submit/accept modes, P2 transport, frozen limits and source roles |
| Failure cases and validation | Gates, the fourteen source assertions and commands |
| Results and handoff | The progress checkpoint, actual source-gate construction, actual original-input qualification and the completed phase closeout |

### Terms used in this record

| Term | Meaning |
| --- | --- |
| Implementation task IDs | Such as P3-I19; identify tasks in the project task plans |
| Acceptance IDs | Such as P3-12; identify rows in the project charters |
| PLAN-20 | A work package in the [build plan](../build-plan.md) |
| Selected implementation and qualification | The gates chosen for this work item; passing them does not complete a full charter row |
| Gate names | Such as G-READY and G-DURABLE; refer to the engineering gates in the [validation plan](../validation-plan.md) |
| schema3 | Shorthand for the outer input/result schema version 3 that wraps the unchanged specialist v2 request/result |
| Acknowledgement (ACK) | A receiver's confirmation that it accepted a request; a lost ACK leaves the outcome unknown |
| Data definition language (DDL) | Schema-changing SQL; none runs while serving |
| Data transfer object (DTO) | A closed, validated record passed across a public boundary |
| TS | TypeScript |
| Real-time communication (RTC) | The WebRTC room path through LiveKit |
| SDK | Software development kit; here the LiveKit Agents SDK |
| Object identifier (OID) | PostgreSQL's internal identifier for a relation |
| Process ID (PID) | Identifies an operating-system process |
| M1 | The original confirmed-investigation intake data, which every phase preserves |

### Criteria

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| Original source | A validated original P2 canonical input and trusted publisher binding | The bridge accepts one explicit investigation | Preserve profile/op/input-receipt UUIDs, exact original SHA/UTF-8 length, scope/case/conversation/revision; no body-selected authority | Actual P1 work UUID becomes the existing P2 external receipt | Public TS client/producer, Python parser and independent real SQL joins |
| First winner | An accepted origin or concurrent equal origin with different proposal context | Explicit origin accept is called | Never refresh the stored deadline/evidence/body; changed origin or stable case fields conflict | Return the original request and work receipt, including after case change/expiry | Exact stored bytes, bounded actual race and replay |
| Exact submit | A new typed request or exact public submit | The P1 port reports newly created work | A created:true reply must retain every submitted byte, including attempt; no substituted first-winner proposal | Ordinary exact v1/v2/v3 submit remains useful | Bad-port negative tests plus real P1 acceptance |
| Uncertainty | Original P1 commit precedes observed HTTP acknowledgement | One owned host is killed and a fresh host handles lookup | Lookup only after uncertainty; one core reconciliation read and no internal resubmit/new key | Fresh original-key lookup recovers the actual work UUID | Actual commit barrier/process kill plus injected-port unavailable/missing controls |
| Bounds and scope | P2 permits wider IDs/revisions and a larger original frame | A mapped identifier/revision/encoded wrapper is unsupported | Reject before P1 writes; do not truncate, coerce zero or copy the full original body into P1 | Supported inputs retain exact identities and meaningful current work | Positive/negative size, Unicode, bool, duplicate-key and scope controls |
| Issuance/result/delivery | Accepted origin work has its original immutable evidence | Explicit run and delivery occur | Only fresh P1 issuance invokes; validate inner v2 facts and outer v3 identity; stale new delivery is denied | Current v3 result reaches the existing P2 receiver and native-grant data read | Real P1/P2, supplied scripted specialist port and independent policy oracle |
| Ownership | HTTP caller, P1 work or cleanup is held | Abort, timeout, close or exporter failure occurs | Retain actual slots/processes; preserve unknown outcome and primary error; no transaction spans specialist HTTP | Settlement permits useful reads, new work and explicit close retry | Controlled held calls/SQL waits, final actual process states and private indexes |

## Interfaces and ownership

P1's existing public work/execution/delivery profile v4 remains the only accepted
work, issuance and result authority. The stored operation stays
booking.evaluate_policy. P2 retains the original input/preparation and external
receipt in its existing profile; v8 result receipts/notices stay unchanged. No DDL
runs while serving, and no new migration is required for opaque versioned bodies.

### Closed schema3 persistence and unchanged specialist v2

Add inert channel_policy_contracts.py and thin channel_policy_execution.py.

ChannelPolicyOrigin is a frozen typed six-field record:

| Field | Rule |
| --- | --- |
| `kind` | `p2.prepared_dispatch.v1` |
| `profile_id` | UUID, canonical lowercase v4 |
| `operation_key` | UUID, canonical lowercase v4 |
| `input_receipt_id` | UUID, canonical lowercase v4 |
| `payload_sha256` | The digest, lowercase SHA256 |
| `payload_byte_length` | The byte length, a strict integer 1..32768 |

The kind proves no channel: native/SMS provenance requires the actual accepted P2
event/receipt join.

| Record | Wraps | Outer fields |
| --- | --- | --- |
| ChannelPolicyRequest | An unchanged FixedPolicyRequest v2 and that origin | Exactly schema_version 1, kind delegation.request, capability booking.evaluate_policy, input_schema_version 3, origin, request and input_fingerprint |
| ChannelPolicyResult | The unchanged FixedPolicyResult v2 | Outer schema_version 1, kind delegation.result, the same capability, result_schema_version 3, input_fingerprint and result |

Record, input/result and semantic notice_v1 versions remain distinct.

The outer fingerprint covers the origin and every nested logical request field.
It excludes the nested attempt and the independently validated redundant inner
fingerprint. Changing an issued attempt preserves both logical fingerprints.

- The inner request must use delegation_id p2_ followed by the original operation
  UUID's hexadecimal characters. P1 scope partitions this key.
- Profile, payload digest, receipt, clock, revision and room must never create an
  alternate key.
- A changed profile under the original scoped operation conflicts rather than
  forking work.

Keep the original v1/v2 parsers/defaults/bytes and TypeScript specialist HTTP v2.
A private typed invocation adapter unwraps the inner v2 request, uses the existing
FixedPolicyInvocationPort, independently verifies its facts and wraps the result
with the original outer fingerprint. Never synthesize a rewritten v2 WorkRecord.
New explicit ChannelPolicyCoordinator/Runner/DeliveryClient and typed views share
the existing closed cores. The raw P3 package inventory becomes 39, from 37.
Projection, refresh and guarded action remain at their existing supported
versions.

### Exact submit and original-origin accept

Only ChannelPolicyCoordinator.accept selects the sealed private channel_origin
identity mode. Its submit method retains exact logical matching.

- Existing/reconciled origin matching binds the entire origin plus inner scope,
  deterministic delegation key, case, positive revision and conversation. The
  first stored deadline, context and evidence win; return that original view
  unchanged.
- Exact matching removes only attempt metadata and otherwise preserves current
  full semantic comparison.

Carry the mode per call through the existing core schedule:

1. one initial find;
2. optionally one submit after case/deadline preflight;
3. one original-key find after conflict or unknown acknowledgement.

Do not stack an adapter catch/find loop or resubmit. For every created:true
WorkSubmission, require the complete returned canonical request to equal the
submitted candidate. Origin first-winner comparison applies only to existing,
reconciled or created:false observations. Known replay performs no new case read,
submit, invoke, delivery or send. Proposal construction cannot renew accepted
state. Later execution loads the winning request's original immutable records,
not a newer proposed source configuration.

### P2 transport and configured publisher

Reuse ExternalOperationClient and its exchange/ownership core. Add one explicit
operation-only constructor overload and public types, retaining the original
StarterConfig/RuntimeCredentials overload unchanged.

- The narrow configuration has schemaVersion 1, profileId, endpoint
  {host:127.0.0.1,port}, and one to 64 bindings.
- Each binding has alias, accountScope, caseId, conversationId, senderId and
  operationBearer.
- Validate/copy all data before awaits. Account and alias bindings are unique.
- This constructor needs no PostgreSQL password, carrier providerScope, callback,
  recovery or unrelated carrier bearer.
- It asserts transport configuration, not native authentication. Real P2 ingress
  supplies that provenance.

The bridge accepts only the existing fixed POST inspect-profile/lookup/accept
wire. It authenticates a separate operation publisher bearer and checks the
configured scope/case/conversation/sender before P1 entry. The profile UUID is
the retained receiver UUID returned by explicit owner v8 preparation and kept in
private runtime configuration. This is a trusted publisher source assertion; no
public outbox getter or fresh runtime DB attestation is claimed. The actual gate
joins it to real P2 outbox_settings.receiver_id independently.

OperationReceipt remains exactly operationKey, scope, payloadDigest and receiptId.
receiptId is the actual P1 work UUID. Lookup accepts the original scope/op/digest
and validates the stored origin against its trusted route; it never creates work.
The existing TS client conservatively maps non-200/malformed accept responses to
OutcomeUnknown and lookup failures to Unavailable. Python retains precise finite
local codes. Do not promise remote TS conflict classification that the wire lacks.

### Frozen limits

| Boundary | Frozen selected limit |
| --- | --- |
| Original P2 input | Existing canonical UTF-8 payload at most 32768 bytes; message body at most 4096 UTF-8 bytes; strict original SHA and canonical ordering |
| P2 external frame | Independently at most 32768 bytes after JSON string framing; response 4096 bytes, two actual client calls and two-second caller budget; no redirect/proxy fallback |
| Persisted v3 | Entire canonical request at most 16384 bytes and entire result at most 8192 bytes; independently enforce the complete wrapper cap; nested validity alone is insufficient |
| Identifier intersection | Only scope/case/conversation mapped into P3 use lowercase-first 64-character IDs; request revision 1..1000000. P2-only message/sender/event IDs keep their own supported bounds |
| Origin host | Literal loopback, fixed routes, four HTTP handlers/eight sockets; coordinator four actual calls and existing bounded public P1 clients; retain actual owners after waiter abandonment |
| Source qualification | Fourteen assertions, 180 seconds including twenty cleanup seconds, at most 24 process groups; fixed sixteen roles below, frozen against implemented assertions before measurement |
| Capture and storage | 64 KiB per stream, 2 MiB aggregate capture, three fresh UUID-owned schemas; private directories 0700/files 0600 and exact retained indexes; normal app/M1 preserved |

### Source roles and shutdown order

The frozen source roles are:

| # | Role |
| --- | --- |
| 1 | compile-public |
| 2 | compile-fixture |
| 3 | setup |
| 4 | origin-race-a |
| 5 | origin-race-b |
| 6 | race |
| 7 | origin-ack |
| 8 | ack-caller |
| 9 | origin-recovered |
| 10 | reconcile |
| 11 | negative |
| 12 | origin-current |
| 13 | result-host |
| 14 | p3-consumer |
| 15 | native-read |
| 16 | cleanup |

The sixteen groups share one 180-second final deadline. New business admission
stops at 160 seconds, reserving twenty seconds for actual cleanup. The additional
origin-current host keeps the original and current sender bindings explicit. The
one scheduled SIGKILL targets only the owned origin-ack host after actual P1
commit. Normal teardown kills, if required on failure, are separately observed.
No RTC room, provider call, carrier send or supplier mutation belongs to this new
gate.

HTTP active/handler gauges describe actual service-coroutine lifetimes. If the
coordinator's bounded waiter settles first, its underlying P1 call can remain
owned by the coordinator with a nonzero service active gauge. HTTP-only close is
not authority drain. Required application shutdown order is HTTP host,
service/core, then shared case readers. An incomplete service close retains its P1
client. Two maintained composition tests exercise both timeout orders without a
database.

### Ownership

| Owner | Owns |
| --- | --- |
| Root | Shared fixtures, the application parser/loopback host, actual orchestration, the independent oracle, documentation and harness discovery |
| Python agent | P3 models/codecs/facades/core changes and their tests |
| TypeScript agent | The existing operation client's narrow configuration, input containment and tests |

Register actual acceptance runners only after their complete assertions exist.
This phase adds no partial complete-charter runner.

## Failure cases and validation

| Gate | Applicable and why | Exact tests/assertions | Prerequisite/resource/time bound | Expected status/artifacts |
| --- | --- | --- | --- | --- |
| G-READY | New persisted origin and cross-language source boundary | Closed DTO, fingerprint and first-winner modes; created:true exact bytes; configured profile assertion; unchanged v2 HTTP | Reviewed source-bound Python/P2/wrapper audits; selected existing baseline remains frozen | This plan freezes implementation choices; no measured qualification yet |
| G-FAST | Shared typed cores/client and new discovery | Narrow new tests then full make check/frontend-check/format-check/docs | Existing pinned offline toolchain; zero required skips | No lint/type/format/discovery violations |
| G-CONTRACT | Untrusted input and independent fingerprints | Real TS producer/client bytes to Python; exact closed headers; changed origin/first-winner/size/Unicode/bool/error controls | Offline or local receiving fixtures; no provider credentials | Reject before authority and preserve original canonical bytes |
| G-DURABLE | Real original-input/work mapping | Fourteen named assertions below, actual SQL contention, owned commit-before-ACK kill, fresh lookup and current result | Isolated real PostgreSQL; exact source roles/bounds/cleanup frozen before execution | Independent joins along the chain P2 canonical input, P1 origin, request/issued/result and P2 receipt |
| G-MIGRATION | No new persisted table/profile | Preserve P1 v4/P2 v8 owner/runtime separation, original rows and no serving DDL | Existing explicit schema preparation and affected prior migration/restore regressions | No new migration or backup format claim |
| G-PACKAGE | New public third codec/facades and narrow TS client | Fresh direct/source/rebuilt Python and npm consumers; current 39/124/32 inventories and unchanged legacy probes | Reuse existing bounded offline builder/installer; new origin probes distinctly counted | No checkout product fallback; installed fake tests do not become actual source assertions |
| G-OBS | Honest uncertainty and physical ownership | Finite codes/events/metrics, secret sentinels, held actual call, incomplete close and later progress | Slots retained to settlement, indexed final owner states/private files | No raw body/token/dependency error; exporter outage cannot change acceptance |
| G-MEDIA | Joined journey depends on this seam | Preserve existing native/rehydration evidence; new integrated voice/text/SMS remains pending | No room, model or media inference in this backend qualification | One later P2 native SDK owner; no competing AgentSession |
| G-RELEASE | Full objective remains active | Configured-provider composition, discovery/restart, complete charters and sanitized final video | Separate actual evidence, no remote CI prerequisite | Missing/skipped/time-out requirements remain incomplete |

### The fourteen source assertions

| # | Assertion |
| --- | --- |
| 1 | Canonical producer/source agreement |
| 2 | One original P1 work/exact P2 receipt |
| 3 | Equal replay with zero extra work |
| 4 | Changed origin conflict |
| 5 | Foreign scope/route/publisher denial |
| 6 | Explicit width/revision/zero rejection |
| 7 | Stale new case versus known historical replay |
| 8 | Actual concurrent first-winner context |
| 9 | Commit-before-ACK kill/fresh recovery |
| 10 | Original deadline/evidence after config/clock change |
| 11 | Failed/missing ambiguous lookup without new submit/key |
| 12 | Held actual capacity and incomplete-close retry |
| 13 | Explicitly issued verified policy result |
| 14 | Current P2 result/read with stale new delivery denied |

Independent negative evidence fixtures must reject coordinated
ledger/origin/fingerprint forgeries, not merely count rows.

### Commands

Run existing commands first for affected regressions:

| Task | Command | Notes |
| --- | --- | --- |
| P2 regressions | `make p2-postgres-check`, `make p2-standalone-check`, `make p2-starter-p1-check` and `make p2-result-receiver-check` | None |
| P3 regressions | `make p3-completion-check` and `make p3-native-policy-check` | None |
| Other affected lanes | The relevant coordinator/execution/processing/action/deadline/native/rehydration lanes | None |

New origin plan/check and package targets now have asserted runners. The new
source runner passed all fourteen actual assertions; the package lane remains
separate fake-port evidence. Freeze and record their exact commands/role inventory
before actual measurement.

### Logging and metrics rules

- Logs expose fixed event/operation/code/outcome and bounded safe correlation
  only.
- Metrics use declared numeric counts/gauges/duration units, without raw
  input/token/route labels.
- Translate once to known safe codes. Retain primary errors through cleanup.
- An HTTP timeout or disconnect is not proof that P1 stopped.
- Supplier effects, receiver acceptance, playback and human acknowledgement remain
  separate.
- Keep Python public interfaces typed and all new sources/tests in maintained
  discovery.

## Results and handoff

The selected implementation is complete. These are implemented:

- the strict P2 wire parser;
- the data-only cross-language fixture;
- public v3 contracts/facades;
- the explicit local service and bounded loopback host;
- the narrow TypeScript operation-client configuration.

The exact P3 runtime inventory now includes the two new modules: 39 Python
payloads. Prior 37-payload reports and archives remain immutable historical
checkpoints.

### Progress checkpoint evidence

The following table preserves the first verified progress checkpoint. Final
source, package and shared outcomes appear in the closeout below.

| Evidence | Observed outcome | Limits |
| --- | --- | --- |
| Public P3 unit suite | 436 tests passed, zero skips; original v1/v2 and new v3 paths included | Offline/local loopback; no actual database claim |
| Origin service and wire | 18 service plus 12 wire tests passed; independent non-author review found no actionable defect | Explicit fake public P1 ports; no durable or channel-provenance qualification |
| HTTP transport | 19 socket/configuration tests passed after two independently found setup-error paths were corrected | Real local sockets with supplied fake service; transport drain is separate from authority drain |
| Composed timeout ownership | Two maintained actual-HTTP/public-P3 cases passed for HTTP-first and Core-first timeout | P1 port is held explicitly; actual PostgreSQL locks remain a source-gate requirement |
| Shared fast validation | 2,778 Python tests and 1,614 TypeScript tests passed, zero required skips; lint, 153 broad/171 selected strict source checks, 466 formatted files and 122 documentation checks passed | Local POC; no remote CI or complete charter claim |
| Isolated origin artifacts | Fresh 25-stage package lane passed in 55.260 seconds with complete cleanup: eight offline assertions, 20 legacy plus 41 origin fake-port tests, and nine P2 codec negatives | Real built/installed artifacts; source_actual_assertions and installed_actual_assertions remain zero |
| Existing database regressions | Twenty P2/P3 result-return assertions and thirteen P3 completion assertions passed in separate fresh lanes, zero skips and complete cleanup | Prior boundaries exercised after shared-core changes; these are not the fourteen new origin assertions |
| Public Node/Python wire | Three actual Node client cases passed against the real Python service/HTTP boundary, including Unicode, bounded NUL payload, replay, remote accept conflict as unknown and lookup conflict as unavailable | P1 ports are explicit fakes; no real P2 intake/SQL-provenance claim |

Existing result-return and completion regressions:

- **phase44-compat-first-01.json.** The first existing result-return regression
  stopped at runtime build parity after both compiler processes exited zero: the
  changed starter source had stale public example JavaScript. No test schema was
  created, and cleanup completed. Its report and captures are preserved. The
  runner now builds production, examples and starter declarations in its original
  compile-public group, retaining derivative configurations and all byte-parity
  checks. A new focused regression control verifies this build contract.
- **phase44-compat-second-02.json.** This fresh run passed sixteen storage plus
  four return assertions across sixteen groups in 10.813 seconds, with zero skips
  and complete cleanup. A subsequent independent review found that its whole-run
  snapshot did not bind every newly built example and compiler base. The runner
  now freezes all five compiler configurations and seven example sources.
- **phase44-compat-third-03.json.** This fresh run passed the same twenty
  assertions across sixteen groups in 11.051 seconds, with 216 before/after source
  bindings equal and current, zero skips and complete cleanup. The earlier second
  report remains its original 205-binding measured checkpoint. A nine-case pure
  runner suite includes negative controls for configuration/example edits.
- The separate P3 completion regression passed thirteen assertions in 17.708
  seconds with its explicit synthetic effect and complete cleanup.

The package report is
.local/validation/p2-result-receiver-package/phase44-origin-first-01.json. It
checks:

- exact 39 P3 Python, 77 P1 Python, 124 P2 npm and 32 specialist payloads;
- public strict consumers;
- twelve unadapted copied inputs;
- installed import paths, private indexes and actual final process states.

Its new 41 tests comprise nineteen contract, fourteen execution and eight
completion cases. Those installed fake-port tests do not repeat the new actual
database schedule. Run make channel-origin-package-plan before
make channel-origin-package-check.

Independent reviews covered the versioned core, wire/service, HTTP and package
mode. Reviews found two HTTP setup containment errors and two package diagnostic
containment errors. Each was fixed with a regression test and independently
re-reviewed. The source-wire diagnostic's first failure was its changed-payload
builder sorting canonical keys; its fresh second run constructs from the original
canonical string and passed. Preserve all first observations and superseding
reports separately. The final read-only local observation found zero selected UUID
schemas/backends, preserved the original M1 public row and reverified the
previously approved exact cleanup without any new mutation.

### Progress checkpoint commands

The selected progress checkpoint is .local/validation/phase44-progress-01.json,
with copied private diagnostics and current source bindings in its sibling
artifact directory. It records verified progress with phase_complete:false; that
checkpoint kept this work item Active. Its exact commands from the root were:

```sh
make channel-origin-unit
.venv/bin/python local-setup/scripts/p2_result_receiver_package_check.py --channel-origin --report .local/validation/p2-result-receiver-package/phase44-origin-first-01.json
.venv/bin/python local-setup/scripts/p2_result_receiver_check.py --report .local/validation/p2-result-receiver/phase44-compat-third-03.json
.venv/bin/python local-setup/scripts/p3_completion_check.py --report .local/validation/p3-completion/phase44-compat-first-01.json
make check
make frontend-check
make format-check
.venv/bin/python -m harness validate
.venv/bin/python -m harness.static_check --module all --groups docs
```

All commands used the pinned local toolchain; offline checks did not load provider
configuration. Additional source-only Node/Python wire diagnostics and independent
review commands are retained with their exact inputs and outputs. The later
actual-origin qualification below is separate evidence; it is not inferred from
these earlier checks.

### Actual source-gate construction

The new channel-origin-plan/check commands select the frozen sixteen-role,
three-schema schedule.

- The Python host uses only public P1 readers/work ports.
- The P2 fixture uses its public native and signed-SMS intake, dispatcher,
  receiver and current-native reader.
- A separate literal oracle recomputes canonical source bytes, both fingerprints
  and cross-store joins from complete owner SQL snapshots.
- The supplied specialist remains scripted, with no supplier mutation or media
  claim.

The parent owns admission/table lock holders and observes actual PostgreSQL
blocking graphs before releasing them. Four held lookups retain their actual slots
after caller abort and incomplete application close. Exactly one scheduled kill
targets the owned ACK host after an independently read P1 commit. Fresh lookup
recovers the same receipt without submit. An explicit database-clock read after
the stored deadline verifies immutable historical work. Every child derives its
business cutoff from the original final deadline minus twenty seconds; resource
cleanup observes the unchanged final deadline.

Focused parent tests cover inert plans, the closed environment, atomic private
publication, transient two-link visibility, malformed complete markers, finite
diagnostics, child-role bounds and report isolation. The independent oracle also
requires coordinated forgery negatives. No measured source success is claimed
until the actual run and retained artifacts pass independent review.

### Actual original-input qualification

#### Qualifying run

The fresh source-fifth-05.json report under .local/validation/p2-channel-origin
passed fourteen actual assertions in 15.057 seconds, with sixteen owned process
groups, zero skips and complete cleanup.

- Three real accepted inputs map to three original P1 work UUIDs.
- Two issued factual outer-v3 results remain distinct. Only the current result has
  a P2 receiver receipt/notice and a current native-grant data read.
- Stale new delivery is denied.
- The signed SMS path uses the declared local simulator. No carrier, RTC room,
  provider or supplier mutation occurs.

The schedule observes two concurrent admission waiters, one actual post-commit
ACK-host kill, original-key lookup recovery, an explicit database clock after the
stored deadline, and four held public P1 reads through abort/incomplete close.

#### Lock-graph evidence

PostgreSQL can queue one row-lock waiter behind another. Independent evidence
therefore requires every edge of the finite acyclic blocking graph to reach the
same owned holder. Runtime and migration observations use their existing separate
roles. Each waiter is bound through actual relation locks and the same table OID;
schema validation may block before the final parameterized work SELECT. No new
privilege is granted, and SQL-text matching cannot establish resource ownership.

The independent literal oracle has twenty offline tests, including:

- coordinated source/request/fingerprint/result forgeries;
- unsafe relation/OID/mode/grant rows;
- foreign or cyclic blocker edges;
- missing actual ownership.

Parent lifecycle controls retain the original failure, safely indexed partial
diagnostics and the owned failed directory when a child proof or group marker is
missing. Cleanup attempts independent P2, work and shared-reader tiers after
actual group reaping.

#### Earlier source runs

Preserve all earlier source reports. None of the failed runs qualifies any of the
fourteen assertions.

- **Source-first-01** stopped at fixture setup: Node's runtime environment has an
  exotic prototype. The environment boundary now copies only validated own data
  descriptors after rejecting unknown keys; JSON configuration remains strict. Its
  independent work-schema cleanup was repaired. An exact guarded recovery removed
  the sole leftover marked work schema while preserving the original report/index
  and failed directory.
- **Source-second-02** stopped at the migration role's limited runtime-query
  visibility.
- **Source-third-03** passed race and ACK recovery but stopped at SQL-text-based
  held-read observation.
- Both later failures completed cleanup.
- **Source-fourth-04** uses the corrected existing-role and relation-lock
  observations.

The source report freezes 218 execution-input bindings before/after measurement.
Independent review initially confirmed all 218 current before documentation
finalization. A subsequent fresh read of the retained bundle found verifier order
dependence in reconstructing P2 scope. Two tooling changes followed:

- The literal oracle now reconstructs tenantId/accountId explicitly and tests both
  winners after a sorted JSON roundtrip.
- The parent now validates the actual saved bundle rather than only its in-memory
  object.

These two tooling changes and later documentation edits make the fourth run a
historical source snapshot; none rewrites its report or index. The fresh fifth run
qualifies the corrected persisted-file verifier separately. Independent replay,
physical indexing, manual SQL joins, process/group absence and read-only
M1/namespace/lock probes all passed. Original M1 identity/payload and historical
failed artifacts remain preserved. Exact current commands, from the repository
root with the frozen local toolchain, are:

```sh
make channel-origin-plan
make channel-origin-unit
.venv/bin/python local-setup/scripts/p2_channel_origin_check.py --report .local/validation/p2-channel-origin/source-fifth-05.json
```

The explicit report path above identifies the retained completed run and cannot be
reused. Use make channel-origin-check for a fresh timestamped report. Source and
package results keep their actual/fake-port counts separate; neither is a complete
P2/P3 release registration.

### Completed selected phase closeout

The selected real source schedule now passed all fourteen assertions. The phase
closeout passed final shared checks, independently reviewed retained evidence and
documentation reconciliation. Integrated media/provider work, discovery,
whole-stack restart, complete charter registration and the final demo video
remain later gates. The installed package's fake-port assertions do not become an
installed repetition of the actual source schedule.

The selected origin-binding slice is complete. The final source-fifth-05 report
passed fourteen actual PostgreSQL assertions in 15.057 seconds, with sixteen owned
groups, zero skips and complete cleanup. Independent replay uses its exact saved
JSON bytes and independently checked source/result/native joins, relation lock
OIDs, actual PID/group absence and preserved M1. All fifteen UUID namespaces from
the five source attempts and selected relation locks are absent. Earlier failed
reports and their retained directories remain unchanged.

The fresh phase44-origin-third-03 package report passed twenty-five stages in
52.007 seconds. It binds the exact final package guide and unchanged current
77 P1/39 P3 Python, 124 P2 npm and 32 specialist payloads. Eight offline
assertions, 20 legacy plus 41 origin fake-port tests and nine P2 codec negatives
passed, with zero skips and complete cleanup. Independent retained-evidence
verification checked archive/RECORD/installed paths, twelve raw copied inputs,
private indexes and final group states. The package-mode author's separate
artifact audit is identified as such; the earlier non-author code review remains
separate.

Full final validation passed:

| Check | Result |
| --- | --- |
| Python tests | 2,870 (49 P1, 113 P2, 436 P3 and 2,272 root) |
| TypeScript tests | 1,648 (622 console, 847 P2 and 179 specialist) |
| Required skips | Zero |
| Static and discovery checks | Ruff, 153 broad/175 selected strict source checks, 475 formatted Python files, documentation and unchanged 55-case/24-registration discovery |

A scheduling-sensitive held-runner test now observes the actual result and both
port-close events before final close. All initial unknown/capacity/incomplete
assertions and twenty-millisecond limits remain. Its 41-test lane and twenty
fresh-loop repetitions passed. No production timeout was widened.

The local phase44-closeout-01.json checkpoint under .local/validation records the
qualified reports, copied private diagnostics, exact current source bindings,
measured documentation-only differences and indexed artifacts. Its phase_complete
flag applies only to this selected backend slice. The full goal remains active.
These still require their own proof: joined voice/text/signed simulated SMS,
current-route UI, discovery/whole-stack restart, applicable provider/model
evidence, complete P2/P3 charter gates and the final demo video.

AI coding agents contributed implementation and independent review. Ownership and
portfolio claims still require the user's inspected and explainable work. The next
bounded work item is the joined native/channel policy application, with one native
SDK session owner and no additional durable execution authority.
