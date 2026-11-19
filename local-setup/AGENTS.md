# Local setup coding agent instructions

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Give coding agents the reading order, ownership, rules and checks for local setup work |
| Audience | Coding agents and engineers changing Compose, lifecycle tooling, images or local gate tooling |
| Scope | Local orchestration, opt-in profiles and gate tooling; excludes service and console runtime code |
| Owns | Agent workflow for local setup: reading order, owned paths, development rules, verification and handoff |
| Related | [Root instructions](../AGENTS.md) · [README](README.md) · [Design](Design.md) · [Validation plan](../docs/validation-plan.md) |

## Read first

Read these documents:

| Document | Why read it |
| --- | --- |
| [Root instructions](../AGENTS.md) | Shared reading order, owned paths, development rules and verification |
| [README.md](README.md) | Lifecycle commands, opt-in profiles, validation gates and troubleshooting |
| [Design.md](Design.md) | Orchestration ownership, state and credential separation, failure containment and gates |
| [Technology baseline](../docs/technology-baseline.md) | Candidate versions, compatibility, promotion and updates |
| [Validation plan](../docs/validation-plan.md) | Test lanes, required fault scenarios, benchmarks and evidence |

Contents: Development rules first cover all local setup work, then each opt-in
profile or gate in delivery order. Verification lists the commands and when to run
each, then gate runs and recorded results under matching topics, and ends with
later-slice qualification.

## Owned paths

| Area | Responsibility |
| --- | --- |
| Compose, lifecycle management, local image/configuration files, Dockerfiles and transport smoke scripts | Owned here |
| Runtime application code | Belongs in services |
| Console | Belongs in apps |
| Orchestration | Keep it separate from business workflow logic |

## Development rules

### Images, configuration and credentials

- Use exact image versions/digests and frozen dependency installs.
- Never:
  - source configuration as shell code;
  - print expanded credentials;
  - bind operator endpoints publicly;
  - mount the Docker socket into services;
  - mutate another stack.
- Do not weaken TLS verification to repair a build.

### Volumes and reset

- Preserve named volumes during normal stop/start.
- Reset requires its explicit confirmation.

### Readiness, scripts and database roles

- Keep health/readiness distinct from actual media or product acceptance.
- Check browser and container Interactive Connectivity Establishment (ICE) paths
  with real traffic.
- Keep operational scripts bounded, resource limits coherent and output secret-safe.
- Use an independent restricted application database role.
- Never pass bootstrap credentials to the serving API.

### P2 loopback case bridge and owner setup tooling

- The explicit P2 loopback case bridge is application composition over
  preconstructed public P1 clients.
- Confirmation requires a separate opt-in binding.
- Keep opaque canonical quote bytes, original input command identity and mapped
  task/case checks before the one public atomic confirmation call.
- Revision unknowns have no command receipt.
- Confirmation original-command replay uses the existing P1 receipt.
- Keep current P2 association preflight distinct from an atomic cross-store fence.
- Retain actual sockets/calls through late close.
- Never expose provider secrets, quote issuance or model-facing mutation tools.
- P1 work v4/P3 projection setup is explicit owner tooling, with no new default
  service or runtime DDL (schema-changing SQL).

### P2 outbound reservation and P3 processing

- P2 outbound reservation and suppression/association checks share the inbox
  admission transaction.
- External carrier I/O is outside that transaction.
- Preserve immutable recipient/attempt routes and truthful possible-call uncertainty.
- P3 processing uses explicit owner metadata v2 and public P1 delivery/receiver ports only.
- No new P1 migration or default service is needed.
- The P3 processing scan cursor is not a terminal acknowledgement (ACK) watermark.
- Exact role-separated gate children must exclude ambient provider, proxy,
  Python-path and database selectors.
- Retain finite capture and PID ownership.

### Ordinary stack smoke

- The ordinary stack readiness/text/audio smoke preserves original M1 state. M1 is
  the existing confirmed-investigation intake.
- The smoke's observations remain transport evidence.
- Keep automatic booking-completion handoff, provider calls, ambiguous resend and
  new UI/native composition outside the selected P2-I12/P3-I10 gates.

### Native input and deadline fixtures (0036)

- Use the [completed handoff](../docs/work-items/0036-native-input-and-deadline-cancellation.md).
- Native composition is opt-in host SDK/gateway/browser against local Docker
  selective forwarding unit (SFU)/PostgreSQL.
- Native composition changes no default M1/P1 service.
- Owner-only quiescent v6 setup adds two native tables and preserves prior identities.
- Serving roles do no DDL.
- Native ingress, prepare, account/publisher and browser real-time communication
  (RTC) credentials have separate owners and must never be interchangeable.
- Ordinary local setup is sufficient.
- Do not read provider credentials or call paid inference.
- Keep fresh database expiry/revocation checks after admission/binding locks, retain
  known history and distinguish an already reserved possible call.
- Close every owned socket/task/room and report incomplete while actual I/O remains.

### Send-policy and protected-action profiles (0035)

- P2 policy APIs require explicit owner inbox v4-to-v5 maintenance/quiescence and
  preserve all old request/result/callback bytes.
- Ordinary possible sends remain held.
- A separately trusted cooperating provider may reuse frozen original operation
  bytes/key only under a new explicit recovery-controller command and current permission.
- Retain callback exact-attempt correlation and vetoes.
- Never retarget the original address.
- P3's new gate uses unchanged public work v4/booking v4 guards and independent
  supplier fixtures, with no projection upgrade or new daemon.
- The P3 gate's 31 modes/16 cases require two prewarmed SQL waiter graphs and three
  owned kills under a 180-second total budget: 165 seconds work and 15 seconds cleanup.
- No provider key, default Compose/UI change, named-volume reset or automatic
  booking-completion handoff is added.

### Callback and applicability profiles (0034)

- Callback APIs require explicit owner inbox v4 setup.
- P3 refresh/display metadata requires an explicit owner projection v3 upgrade.
- P1 work v4 and booking v4 remain unchanged.
- No new default daemon, Compose/UI route, provider credential or paid call is introduced.
- Callbacks authenticate a separate raw-byte hash-based message authentication code
  (HMAC) capability and correlate exact old attempts independently of current sender
  association.
- Callback evidence cannot open a resend.
- Refreshed applicability uses explicit per-result compare-and-set (CAS) and separate
  as-of source/case/time observations.
- Hiding display preserves all identities and unresolved processing.
- Callback bytes are capped at 4096.
- The signature window is 60 seconds and is rechecked against database time after
  admission.
- Callback bounds default to 10000 total/eight per attempt, maximum 100000/32.
- Refresh commands default to 3000 total/four per event, maximum 30000/eight, with
  receipts at most 4096 bytes.
- Equal replay remains available at capacity for the profile lifetime.
- No physical deletion or capacity reclamation exists.

### Local real-inference profile

- Read the [operations guide](../docs/local-real-inference.md) before changing model
  preparation or engines.
- models-fetch is the only explicit weight-download action.
- models-verify and all start actions verify without fetching.
- Keep the immutable manifest, exact byte/digest checks, owned preparation lock/child
  deadline and ignored cache.
- Runtime model mounts are read-only with no automatic empty host path.
- p1-models services expose no host ports or application credentials.
- Preserve scripted defaults and explicit start-local-real/stop-local-real behavior,
  ACTIVE v4/v5 same-scope read-only preflight, exact consent and existing data.
- Engine CPU/memory/PID/tmp ceilings are bounds, not a resource admission or capacity
  result.
- Record actual inference/media evidence separately from cache/readiness.
- Keep local host/container checks independent of optional hosted automation.

### Inference modes and provider keys

- Trusted inference modes are exactly scripted (default), local_real and provider_real.
- Preserve the selected mode through mint, native readiness, numeric usage and
  sanitized traces.
- A configured badge or process health is not actual inference/media qualification.
- No silent provider/model fallback exists.
- All modes preserve bound tools and separate exact human confirmation.
- Read the [provider operations guide](../docs/provider-demo.md) before changing
  provider composition.
- Offline validation must not read private key values or invoke providers.
- Never source, print, copy or include `local-setup/.env.providers` in reports or
  build contexts.
- Only the explicit native provider runtime receives the three keys.
- Preserve strict owned mode 0600 credential loading, presence-only checks and
  explicit start-provider/stop-provider.
- Stop must attempt credential-bearing native-container removal even if another
  drain/reset fails.
- Never forward keys to API, worker, collector or local engines.

### Provider certificate authority trust

- Explicit provider certificate authority (CA) setup uses approved public
  certificate-only data and a native-only read-only OS trust-file mount.
- Keep strict TLS hostname/CERT_REQUIRED verification, fixed routes and
  trust_env=False.
- Never copy trust data into images, keys into a CA file, or CA mounts/settings into
  API/worker/browser.
- Preserve the single atomic interactive configuration snapshot and per-run snapshot
  lifetime through verified native removal.
- Incomplete cleanup must retain the snapshot and fail.

### Origin publisher bridge (0044)

- Use the [0044 work item](../docs/work-items/0044-origin-bound-channel-policy.md)
  for the configured P2-input/P1-policy bridge.
- The bridge's literal loopback host retains four handler lifetimes and at most eight
  sockets.
- The coordinator separately owns four actual P1 calls.
- A settled HTTP/service waiter can leave P1 I/O owned by the coordinator.
- Close the host, then service/core, then shared case readers.
- Retain incomplete owners before any dependent cleanup.
- Never infer a database rollback or cancelled business effect from a disconnected
  socket.
- The original P2 owner-returned receiver UUID is a trusted publisher assertion, not
  fresh runtime database attestation.
- Keep all private paths, source bindings, failed reports and process indexes intact.

### Phase E operations

- Read [effect operations](../docs/effects-and-completion.md) for v3.
- Keep migration/bootstrap credentials out of runtime probes.
- Demo fixture volumes and schemas must be new, UUID-owned and checked before cleanup.
- Do not reset application state.

### Phase F workers and business profile

- Use the explicit p1-workers profile only after controlled ACTIVE v4 preparation.
- P1_WORKER_SCHEMA selects the optional worker/migration target, while M1 remains SQLite.
- Fixture initialization is explicit and retains provider/receiver identity.
- Never copy bootstrap credentials into the worker.
- Leases use database time, and runtime process occupancy uses monotonic time.
- Preserve stopped/uncertain work for another epoch instead of asserting that a
  killed external call failed.
- Business integration uses the p1-business profile and explicit start-business /
  stop-business commands.
- Keep business mode disabled for ordinary start.
- Inherited shell flags cannot activate business mode.
- Preflight must verify an existing ACTIVE v4 schema and seeded same-scope
  provider/receiver without mutation.
- Native receives runtime PostgreSQL and LiveKit credentials only.
- Preserve the API read-only supplier mount and 35-second worker drain.

### Phase H workload benchmark

- Read the [H1 work item](../docs/work-items/0014-p1-phase-h-workload-baseline.md).
- The opt-in benchmark drives installed API/workers in fresh UUID-owned
  schemas/fixtures, without altering the ordinary M1 stack.
- Freeze schedules, HTTP observation cadence, resource limits and deadlines before
  measurement.
- Admission, read, replay and cancellation share declared HTTP concurrency.
- Retain safe raw observations and independent supplier truth.
- Fail missing progress/setup/cleanup.
- Keep outcome/delivery/cancellation distinct.
- Cgroup accounted memory is not resident set size (RSS).
- No benchmark result establishes production capacity or speech/model performance.

### v7 communication profile

- The opt-in v7 communication profile adds three tables through explicit quiescent
  owner migration over v6.
- Serving credentials never perform DDL.
- Keep publisher, SDK, browser-report, account, native input, prepare, operator read
  and RTC roles separate.
- Store growth uses the existing four-operation/two-connection admission.
- Response sequences are account/conversation scoped, and observation sequences are
  response-local.
- Late original facts survive expiry/revoke without new preparation.

### Current-case context and standalone package (0038)

A and B are the first and second rooms in the selected media sequence.

- The read-only context facade derives scope from a current native grant or exact
  already accepted SMS/current epoch, not from old account-history access.
- Read coherent P2 state, release SQL for the external case read, then recheck
  disclosure permission under locks using fresh database time.
- Case/history times and source fingerprint are independent observations.
- Revision equality alone cannot make supplier/workflow state current.
- The new loopback current-case bridge performs one public ManagedCaseClient.get
  through a preconstructed mapped reader.
- Allowlist facts only.
- No quote, exact confirmation payload or mutation controls cross this read port.
- The bridge's listener and actual get tasks settle before the application closes the
  shared reader/boundary.
- A bounded close observer failing is not actual drain.
- Retry the public close while retaining ownership, and withhold dependent schema removal.
- Stage deadlines or close requests must not admit new fixture business stages after
  late I/O settles.
- The optional native profile displays P1 revision 0 but preserves the existing
  positive-revision native intake/prepare boundary.
- Never map 0 to 1 or auto-revise.
- The selected media sequence actually closes/deletes A, runs the fixed signed SMS
  with zero A/B rooms, then creates B and waits for its exact parent-owned marker.
- Original receipt/operation/history facts are inert context.
- Only new accepted input may generate a reply.
- Keep SDK output, client pulse-code modulation (PCM), supplier results and human
  acknowledgement separate.
- No timers may manufacture progress or hearing.
- Keep runtime/owner credentials role-separated, installed products isolated.
- Reap all owned children before DDL or temporary removal.
- Unresolved ownership retains work and cleanup:false.

### Workload and image operations (0039)

- Read the [completed handoff](../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md).
- P2-I19 uses fresh owner-marked v7 profiles and existing restricted runtime roles.
- Keep public setup/inspection windows at 64, retained capacity distinct from active
  work, no per-case rooms/agents and no physical identity deletion.
- Ordinary observer callbacks have a separate eight-slot cap from communication's
  eight callbacks.
- External observer transport remains application-owned after SQL close.
- P3-I16 source HTTP is database/provider-free.
- Installed mode reuses only fresh source-bound package output and declared
  unadapted consumer inputs.
- Preserve the finite two-capability dispatch and policy defaults.
- Check actual PNG bytes before provider entry.
- Retain fixed workers/provider promises until settlement.
- Retry public close after incomplete observation.
- P1 stays policy-only.
- Image text/result provides no tool, consent, projection or action permission.
- Aggregate child/capture budgets include the nested builder and owned process groups.
- Unknown ownership withholds private work removal.

### Operations profiles (0040)

- Normal setups use unique marked disposable profiles and distinct
  product-evidence/process-capture directories.
- Reap actual owners before dependent removal.
- Preserve failed reports and explicitly approved exact recovery as separate
  observations.
- Never retry a rejected destructive action through an alternate path.

### Stable result-return operations (0043)

- Use the [0043 handoff](../docs/work-items/0043-stable-result-delivery-and-return-context.md)
  for P2 v8 receipts and P3 v2 delivery.
- Only explicit owner maintenance performs DDL.
- Runtime credentials never repair schema drift.
- Stop and reap owned groups before dependent removal, index their actual final
  states and retain the original failed reports.
- Private nested directories must each be 0700.
- Never chmod a prior failed observation to make its evidence pass.

### Joined launcher

- The explicit scripted launcher consumes existing prepared profiles and prebuilt
  artifacts.
- Its three closed child roles are specialist, gateway and optional public Vite preview.
- Keep the child role environments distinct and bounded.
- Parent owns native room/SDK process lifetime and the background App.
- Begin UI close and Parent preparation independently. Keep App origins and Node
  dispatch live while Parent room cleanup drains original accepted inputs. Then
  observe gateway dispatch quiescence before final Parent application close and
  Node dependency removal.
- Reobserve retained cleanup automatically after observer failure; another stop
  signal may wake the wait but must not be required for progress.
- Preserve late factory/spawn/read ownership.
- Require actual pipe EOF, process reap and group absence before clean completion.
- Normal restart retains private operator/static configuration and all product state.
- An existing active marker fails closed.
- Never overwrite, silently recover, drop schemas or associate a sender during serving.
- Plan/import paths are inert.
- Serving reads only maintained infrastructure settings, never provider files.

## Verification

Run from the repository root:

```sh
python3.14 local-setup/stack.py config
python3.14 local-setup/stack.py doctor
python3.14 local-setup/stack.py smoke
.venv/bin/python -m unittest discover -s tests -p 'test_local_setup.py' -v
```

| Check | Command | When to run |
| --- | --- | --- |
| Configuration | `python3.14 local-setup/stack.py config` | Before actual startup |
| Doctor | `python3.14 local-setup/stack.py doctor` | Before a fresh start |
| Stack smoke | `python3.14 local-setup/stack.py smoke` | Against the actual stack after infrastructure or runtime changes |
| Local setup unit tests | `.venv/bin/python -m unittest discover -s tests -p 'test_local_setup.py' -v` | Before actual startup |
| P2 send-policy gate | `make p2-send-policy-check` | After affected changes, with the documented restricted-role setup |
| P3 action-race gate | `make p3-action-races-check` | After affected changes, with the documented restricted-role setup |
| Phase E demo | `make phase-e-demo` | After rebuilding changed runtime code |
| Phase F demo | `make phase-f-demo` | After image rebuild |
| P2 communication gate | `make p2-communication-check` | After affected changes, separately from the playback gate |
| P2 playback gate | `make p2-playback-check` | After affected changes, separately from the communication gate |
| P3 recovery gate | `make p3-recovery-check` | After affected changes |
| P2 rehydration gate | `make p2-rehydration-check` | After affected changes, separately from the rehydration media gate |
| P2 rehydration media gate | `make p2-rehydration-media-check` | After affected changes, separately from the rehydration gate |
| P3 package check | `make p3-package-check` | After affected changes |
| P3 package lab check | `make p3-package-lab-check` | After affected changes |
| P2 workload plan | `make p2-workload-plan` | Inspect before actual gates |
| P3 document plan | `make p3-document-plan` | Inspect before actual gates |

### All infrastructure changes

- Configuration and unit tests precede actual startup.
- Test actual readiness, text/audio, secret exclusion, shutdown and persistence when
  infrastructure changes.
- Do not run reset against existing user state as an ordinary check.

### Outbound and processing gates (P2-I12/P3-I10)

- P2-I12/P3-I10 selected backend and installed-consumer gates passed.

### Native input and deadline fixtures (0036)

- Selected actual native and isolated Python/npm artifact gates passed.
- Final selected phase regression/shared checks and the affected media rerun passed.
- Source/installed P3 eighteen-case and forty-six compatibility assertions passed.
- The [current playback/recovery handoff](../docs/work-items/0037-playback-evidence-and-process-recovery.md)
  owns selected I17/I14 results.
- I18 rehydration and P3-I15 standalone consumption passed selected qualification in
  the [completed handoff](../docs/work-items/0038-case-rehydration-and-standalone-release.md).

### Send-policy and protected-action profiles (0035)

- The [completed send-policy/action-race phase](../docs/work-items/0035-send-policy-and-action-races.md)
  completed the selected local gates for P2-I14 and P3-I12.
- With the documented restricted-role setup, `make p2-send-policy-check` and
  `make p3-action-races-check` passed their selected synthetic backend gates.
- Existing callback/applicability commands retain the previous checkpoint's passing scope.

### Callback and applicability profiles (0034)

- The [completed phase](../docs/work-items/0034-callback-evidence-and-applicability-refresh.md)
  completed selected local phase gates for P2-I13 and P3-I11.
- The isolated role-separated actual gates and offline installed consumers passed
  their selected assertions.
- Existing quickstarts retain their qualified scope.

### Provider certificate authority trust

- Repeat strict CA-file, restrictive-permission, mode-isolation and trust-evidence
  binding tests when changing this boundary.

### Origin publisher bridge (0044)

- Real origin qualification must independently join the owner-returned receiver UUID
  to the actual receiver row and original accepted input, as the selected fourteen
  source assertions do.
- The current 25-stage isolated package lane verifies 20 legacy plus 41 origin
  fake-port tests.
- The package lane does not repeat the fourteen separately passing actual PostgreSQL
  assertions.

### Phase E operations

- Run `make phase-e-demo` after rebuilding changed runtime code.
- Preserve the failure output and rerun serially when database checks or image
  builds contend.
- A timeout cannot count as a pass.

### Phase F workers and business profile

- Run `make phase-f-demo` after image rebuild.
- Require actual retained waits, useful progress, positive metrics, safe logs, same
  installed source and owned cleanup.
- Test `tests/test_business_setup.py` and the actual isolated Phase G demo.
- Missing Chrome/media/traces leave required assertions non-passing.

### Phase H workload benchmark

- Preserve closed Phase G evidence when running the actual browser regression.

### Playback and recovery gates

- Run `make p2-communication-check` and `make p2-playback-check` separately.
- The first has sixteen actual PostgreSQL groups and direct public API observations.
  Receiving HTTP and real SDK/browser media have separate evidence.
- The second has three media groups in one Playwright case.
- Preserve budgets, actual owned backend PID bindings and pre-lock/post-lock
  database clocks.
- A missing query under restricted-role redaction is not evidence that no waiter exists.
- Retain finite diagnostics before deleting private scratch.
- All cleanup owners run after the first failure.
- `make p3-recovery-check` uses unchanged P1/P3 runtime authority, eight actual owned
  kills, one SQL issuance graph and an independently observed fake supplier effect.
- Fresh installed consumers have their own proof.
- A source run cannot stand in for archive isolation.
- Complete charter/release registrations remain separate.

### Current-case context and standalone package (0038)

- Use the [completed handoff](../docs/work-items/0038-case-rehydration-and-standalone-release.md)
  for selected I18/P3-I15 qualification.
- Run `make p2-rehydration-check` and `make p2-rehydration-media-check` separately.
- P3 `make p3-package-check` runs eight offline assertions.
- `make p3-package-lab-check` explicitly adds eight actual lab assertions to those eight.
- The prior standalone checkpoint preserved 77 P1/30 P3 payloads.
- The prior image checkpoint preserved 77 P1 payloads and qualified 32 P3 runtime
  payloads.
- The current I17 checkpoint qualifies 34 P3 runtime payloads.
- The selected 18-group storage, three-group media and P3 combined 16-case gates passed.
- No hosted continuous integration (CI), provider calls, default Compose change or
  full charter claim follows from these lanes.

### Workload and image operations (0039)

- Inspect `make p2-workload-plan` / `make p3-document-plan` before actual gates.

### Operations profiles (0040)

- The [completed 0040 handoff](../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md)
  records P2's 16 operations groups, three browser groups, seven npm stages and 187
  compatibility assertions, plus P3's twenty source/twenty installed fixed-policy
  assertions and separate package/image/146-assertion compatibility outcomes.
- No provider/private-CA settings or default image/Compose changes were needed for
  this selected slice.

### Stable result-return operations (0043)

- Preserve the sixteen-group actual schedule and separately bounded twenty-five-group
  offline package lane.
- The twenty source assertions and twenty installed fake-port tests are different
  assertions.
- Native-grant data reads do not establish RTC media or provider inference.

### Joined launcher

- Actual joined media/provider gates remain required beyond component checks.

### Recorded qualification of later slices

- P2-I19 workload/dormancy and P3-I16 standalone image HTTP passed selected
  qualification.
- Selected P2-I20 joined-view/telemetry and P3-I17 fixed-policy evidence passed their
  0040 gates.
- Selected P2-I21/P3-I18A qualification passed in 0041 and P3-I18B native RTC text
  passed in 0042.
- Combined voice/text/SMS return routing and full release remain separate.
- Preserve the fifty-five catalog/twenty-four registered runner boundary.
- Full seventeen-row P2 and fourteen-row P3 acceptance remains planned.

## Handoff

- Record config/runtime versions, affected ports/services, exact validation, observed
  media path, persistence outcomes and limits.
- Keep credentials and raw source-control identifiers out of documentation.
- Update setup, design and capability status with changes.
- Preserve pending product acceptance cases.
