# Channel Continuity Kit coding instructions

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Give coding agents the reading order, owned paths, rules and checks for P2 changes |
| Audience | Coding agents and engineers changing the Channel Continuity Kit (P2) |
| Scope | P2 TypeScript SDK, gateway and Python member, from intake to origin integration; excludes P1 case authority and P3 delegation |
| Owns | P2 agent reading order, owned paths, development rules and verification |
| Related | [Root instructions](../../AGENTS.md) · [P2 guide](README.md) · [P2 design](Design.md) · [V1 charter](../../docs/projects/channel-continuity-scope.md) · [P2 task plan](../../docs/implementation/p2-channel-continuity.md) |

## Read first

Read these documents:

| Document | Why read it |
| --- | --- |
| [Root instructions](../../AGENTS.md) | Follow first: repository-wide reading order, rules and verification |
| [README.md](README.md) | Product onboarding, implementation status and gate commands |
| [Design.md](Design.md) | State ownership, interfaces and failure boundaries |
| [V1 charter](../../docs/projects/channel-continuity-scope.md) | Authoritative requirements and stable acceptance IDs |
| [Shared validation plan](../../docs/validation-plan.md) | Test lanes, required fault scenarios, benchmarks and evidence |
| Affected source and tests | Inspect them before editing |
| [Granular implementation plan](../../docs/implementation/p2-channel-continuity.md) | Phase gates, task prerequisites and failure evidence |

The implementation plan's task IDs are not product acceptance IDs. The charter
remains authoritative.

Contents: Development rules start with general, authentication and storage rules,
then cover each slice in delivery order: the standalone example, I07 dispatch
through the I21 installed starter, then the 0043 result receiver and the 0044
origin integration. Verification follows the same order and ends with charter status.

## Owned paths

| Area | Responsibility |
| --- | --- |
| `projects/channel-continuity/src` | TypeScript version-1 contracts and implemented intake/dispatch/gateway source |
| `tests` in this project | Project tests |
| `python/src/channel_continuity` | Python member; its default codec is SDK-free |
| Optional native adapter | Consumes the separately owned durable TypeScript runtime and does not own another queue |
| `contracts/channel` | Shared wire fixtures |
| Root workspace/check registration | Must cover both languages |
| [V1 charter](../../docs/projects/channel-continuity-scope.md) | Scope and acceptance IDs |
| [Root design](../../Design.md) | Shared authority and ports |

- Keep unrelated projects and user files intact.

## Development rules

### General channel rules

- Persist accepted input before acknowledgement.
- Preserve trusted tenant/account scope, scoped provider identities and
  changed-payload conflicts.
- Never deduplicate separate messages by text content.
- Keep `ProviderScope` distinct from verified end-user `AccountScope`.
- A recognized carrier account does not authorize case access.
- Use the case authority for revisioned intent and confirmation.
- An ambiguous SMS reply must not invent which revision the user approved.
- Consume native LiveKit text and interruption behavior.
- Preserve generated, playback, delivery and acknowledgement observations with their
  source.
- Unknown remains unknown, and playback is not consent.
- Keep dormant cases independent of live rooms.
- Standalone examples use fake SMS and narrow operation/agent ports without importing
  P1 or P3 application implementations.
- Real carriers and Cloud evaluation remain optional.
- Define provider replay horizons and receipt/delivery tombstones before cleanup.
- Display-history pruning cannot permit duplicate acceptance.
- At a real package-consumer boundary, test the npm-pack artifact from an isolated
  consumer.

### Authentication and intake boundary

- Parsing or constructing a TrustedPrincipal object is not authentication.
- Gateways use the implemented raw authenticated intake boundary,
  revalidate current association, and decode untrusted data at the actual boundary.
- Gateways must not trust a caller-constructed DecodedEvent or receipt.

### Storage, exports and runtime limits

- Server-only exports include `./security`, `./postgres`, `./migrations`,
  `./dispatch`, `./gateway` and `./agent-process`.
- Keep the default codec browser-safe.
- Runtime must not execute DDL (schema-changing SQL), delete canonical receipts,
  refresh schema baselines or enroll LINK proofs as business messages.
- Preserve stable operation identity, scoped sequence and original receipt after
  response loss.

### Standalone example

- The `./standalone` example requires all adapters and trusted scope binding before
  intake.
- Keep receipt acceptance separate from authenticated read-only preview.
- Runtime-validate case scope/revision, scripted reply and persisted operation key.
- pending/not_executed is the only example operation state.
- The example is not a scheduler, retry owner, business-action executor or case authority.
- A preview timeout retains its slot until the underlying adapter actually settles.
- Never free ignored work merely because a timer fired.
- Check monotonic deadlines after each awaited stage and before success.
- Helper close owns preview resources only.
- Callers also close the provided inbox.

### Dispatch (I07)

- For I07 dispatch, use only the explicit owner version1-to-version2 upgrade.
- Runtime never repairs drift or changes immutable input/receipt/key.
- Keep prepared scope/case/revision/plan/digest frozen before possible external
  acceptance.
- Recheck the original current association before each new accept.
- Reassignment cannot retarget prior input.
- Reserve possible_external/state uncertain in a committed transaction before
  calling a cooperating investigation adapter outside locks.
- Leases guard local observations and do not fence external execution.
- Keep stable key/scope/digest idempotency and lookup mandatory.
- Ordinary attempts are bounded.
- Lookup-only reconciliation may resolve known original work after exhaustion or
  sender revocation without new accept, plan generation or attempt-row growth.
- Standalone preview must reject every nonpending state instead of advertising
  not_executed after dispatch.
- Driver deadlines include synchronous observers and abort callbacks.
- Retain ignored adapter slots until actual settlement and report incomplete cleanup
  honestly.
- Outbox, broader restart schedules, case mutation/confirmation and native media
  remain later slices.

### Gateway (I08)

- For I08 gateway work, keep the literal-loopback raw HTTP boundary,
  four-request/16-socket admission and fixed header/body/response budgets.
- Import starts no listener.
- Explicit startup preflights owner-installed v2 without DDL.
- A startup timeout retains actual I/O and closes a late bind.
- Poll only bounded persisted eligible IDs using configured account credentials.
- Rotate accounts.
- Honor the tick budget before each SQL scan and revalidate authority in step.
- No incoming message may select worker scope or become the owner of a memory queue.
- Normal ingress cannot starve committed work.
- Only trusted test-hook mode may hold the acknowledgement-before-dispatch
  (ACK-before-dispatch) barrier.
- Keep application-created observer resources outside the listener's cleanup claim.
- Default Docker/UI, agent crash, revision routing and media remain their own slices.

The [lifecycle controls](README.md#gateway-lifecycle-controls) are trusted
process-local methods, not new browser or HTTP authority:

| Control | Existing contract to preserve |
| --- | --- |
| `ChannelDispatcher.quiesce()` and `ChannelGateway.quiesceDispatch()` | Sticky new-attempt/intake/polling fences retain actual dispatch owners and leave storage/reads available; caller timeout is not actual closure |
| `NativeGateway.fenceNativeInput(bearer)` | Fence the exact bearer before awaiting admitted actual accepts; register each actual owner before invoking a reentrant dependency; retain at most 1,024 bearer hashes per instance |
| `NativeGateway.drainNativeInput(accountToken, bindingId, bearer)` | Require the prior same-bearer fence, keep ordinary dispatch/origins live, inspect at most 16 total account/conversation history records before exact-provider/binding filtering; two actual drains and a 20-second monotonic budget |

Room drain precedes grant revocation, worker stop and whole-gateway quiescence.
Preserve original receipt/operation IDs and lookup-only possible-call
reconciliation. Blocked/exhausted work, overflow, expiry/revocation or unknown
outcomes may retain Closing; do not reset attempts, renew permission or invent a
new key to force cleanup. These HTTP fences do not replace persisted revocation
or protect against direct trusted inbox calls or process restart. See the
[lifecycle work item](../../docs/work-items/0050-lifecycle-drain-and-documentation-cleanup.md)
for evidence; earlier selected gates are not automatically requalified.

### Agent process (I09)

- For I09, AgentProcess owns only trusted Node modules inside its POSIX process group.
- Validate parent and worker allowed scopes independently.
- Bind every response to the entire normalized context digest and strict
  revision/source/decision.
- Use AgentProcess's plain `agent.port` object for the existing port registry.
- Received data cannot select modulePath, environment, executable, scope inventory or
  a PID.
- Forward only the finite explicitly configured P2_AGENT_ fields, never ambient
  PostgreSQL (PG), provider, proxy or Node selectors.
- No shell, import-time process or implicit retry is allowed.
- Waiter timeout/abort does not free actual process capacity.
- Observe actual child exit, pipes and group disappearance after TERM/KILL.
- Incomplete cleanup retains ownership.
- Module code must keep descendants in that group.
- Application observer resources and physical remote computation have separate owners.

### Revision routing (I10)

- For I10, `./routing` routes only a strict original accepted investigation-revision
  body.
- Derive scope/case/operation/receipt from authenticated input inspection and trusted
  allowed bindings.
- No call/body may override the derived scope/case/operation/receipt.
- Provider timestamps are observations, not revision order.
- Preserve decimal zero-through-int64 revisions and known revised/unchanged versus
  conflict/unknown.
- No automatic retry/rebase, matching-payload acceptance inference, command receipt
  or exact mutation consent is provided.
- I11 owns confirmation association.
- Standalone reference-case v1 is explicit owner-seeded state for independent use.
- Integrated mode selects the bounded local P1 public-case bridge and never copies P1
  revisions into that schema.
- Runtime does no DDL.
- Keep actual calls/socket/connection ownership after waiter timeout.
- Validate AbortSignal before admission.
- Discard failed rollback/unknown-commit connections.
- Router closes only its own calls.
- The application owns input and authority cleanup.
- Logs/metrics use fixed enums.
- Retained account history authentication is not current sender association.
- Do not change ChannelInbox.inspect or claim an atomic revocation fence here.

### Confirmation (I11)

- For I11, confirmation is a separate capability and requires a trusted immutable
  response/revision/exact-quote binding.
- Publish only through the distinct controller credential.
- Ordinary account credentials and model output cannot publish prompts.
- Keep full canonical supplier-bound quote bytes opaque through TypeScript.
- Preserve int64 decimal metadata and P1 UUIDv5 quote IDs.
- Command IDs are original inbox operation UUIDs.
- P1 public commit_confirmation owns atomic quote/revision/time/cancellation
  validation and intent commitment.
- Never replace commit_confirmation with a read then plain write, current-state
  inference, automatic retry/rebase or inferred consent.
- ConfirmationInputPort requires retained inspect and late inspectForConfirmation.
- After prompt lookup, revalidate current original sender/association epoch and exact
  original input before the possible authority call.
- History remains unchanged.
- Known revoked/reassigned input is denied.
- The preflight is not a cross-authority revocation fence.
- Replays after revocation remain denied by this facade, even when P1 retains a known
  receipt.
- No lookup-only fallback may start a new write.
- Keep fake-SMS v1 closed wire unchanged.
- Explicit YES responseID is linked through the immutable registry.
- Bare YES needs both existing trusted event links.
- Preserve unknown ACK and explicit same-command replay.
- Prompt storage has a persisted cap, immutable tenant/account/response identity,
  replay-at-cap and changed-payload conflicts.
- No prompt pruning, delivery/hearing assertion or duplicate case ledger.
- Reference-case v1 remains investigation-only.
- Default bridge bindings must not gain confirmation without explicit opt-in.
- The application closes router, input, registry and authority separately.
- Actual work/socket ownership survives waiter timeout.

### Outbound replies and ordinary fake sends (I12)

#### Storage upgrade and separation

- For I12, use the explicit owner `upgradeChannelSchemaV3` after v2 under a
  maintenance/quiescence boundary.
- Serving code never installs, upgrades or repairs storage.
- Old installation/v2 upgrade validate v3 without downgrading it.
- New inbox and dispatch calls remain compatible.
- Keep original receipts, canonical input, prepared plans, keys and dispatch history
  intact.
- The outbox is separate from P1 case intent, supplier effects, result-feed
  acknowledgements and exact consent.

#### Enqueue identity

- The `./outbox` publisher credential binds immutable tenant/account/case/conversation.
- Ordinary account credentials cannot enqueue.
- Stable outbound UUID, response reference and exact body bytes determine immutable
  enqueue identity.
- Body digest and envelope intent digest are distinct from any P1 result digest.
- A future 8192-byte result needs an explicit bounded notice/reference rather than
  silent SMS truncation.
- Receiver and enqueue receipt UUIDs persist through reopen.
- Queue acceptance is not provider delivery.

#### Routes, suppression and reservation

- Routes and suppression are keyed by tenant/account/conversation, not a global
  phone opt-out.
- Current association, recipient, route version and suppression are checked with new
  possible-send reservation under the existing inbox admission guard.
- This reservation is the local permission commitment point.
- Revoke/suppress before the reservation prevents a new call.
- Later changes cannot retract a paused admitted network call.
- A route change cannot transfer prior ownership or rewrite an old attempt.
- Route selection never clears suppression.
- Preserve retained recipient history access.

#### Send attempts and results

- Each explicit send has a distinct attempt UUID and immutable
  request/route/association/provider-operation snapshot.
- Results are separate immutable records.
- Possible without a validated result is unknown, even if a crash preceded the
  physical call.
- Unknown blocks another send or retarget.
- Only known definitive nonacceptance permits another bounded explicit attempt.
- I12 adds no daemon, automatic resend or physical exactly-once claim.
- I13 adds the separate callback rule below.
- I14 still owns ambiguous resend qualification.

#### Resource ownership and telemetry

- ChannelOutbox owns its store and actual send tasks.
- The application separately owns the supplied carrier client and inbox.
- Timeout/abort retains actual slots through settlement.
- A late known result can be saved while the caller remains uncertain.
- Fail incomplete cleanup, then close/reconcile the actual resources.
- Metrics and logs use fixed event/code enums only.
- Enqueue replay counters are historical acceptance observations, not current queued
  state or unique provider deliveries.

### Provider callback evidence (I13)

#### Storage, wire and authentication

- For I13, use owner `upgradeChannelSchemaV4` under quiescence.
- Never alter the closed v1 SMS/channel wire.
- Callback schema1 has exactly eight flat fields and a separate key-bearing
  integration/hash-based message authentication code (HMAC) domain.
- Authenticate fresh exact raw bytes before deduplication or attempt lookup.
- Recheck `clock_timestamp()` after admission locks.
- Retain original first raw bytes and canonical semantic fingerprint.
- Retry timestamp/signature are transport-only, while changed
  occurredAt/state/providerMessageId conflicts.

#### Correlation and ownership

- Correlate to original immutable attempt provider scope, operation key and request
  digest.
- Derive recipient/case from persisted original identity.
- Current routes, phone labels and provider message IDs cannot select ownership.
- No send result is required for an otherwise valid callback.
- Late reports after revocation/reassignment remain old recipient history, and the
  new owner gains no access.

#### Evidence reduction

- Keep callback observations separate from immutable send_results.
- Read both using one REPEATABLE READ snapshot before reduction.
- The fixed fake_sms_delivery_evidence_v1 rule is commutative: no arrival/occurredAt
  winner.
- Retain terminal contradictions, provider identity mismatch and positive evidence
  against definitive nonacceptance.
- Accepted then failed alone is compatible.
- Conflicted reports never become optimistic physical delivery, human
  acknowledgement, consent or resend permission.

#### Admission and reservation

- Callback acceptance and NEW v4 reservation first acquire existing admission.
- Only callback growth then acquires callback_admission.
- Reservation reads retained evidence on ANY of the reply's at most five prior
  attempts and vetoes a new call.
- pending is advisory.
- Callback first blocks.
- Reservation first cannot be retroactively fenced.
- Never rewrite an old send result, retarget or automatically retry.
- v3 behavior remains unchanged until explicit v4 upgrade.

#### Capacity and resources

- Default callback caps 10000/eight and maxima 100000/32 are persisted.
- Authenticate equal replay before capacity checks.
- Retain receipt identity for profile lifetime with no physical pruning.
- Keep fixed-code logs/metrics, four actual tasks/two SQL connections, monotonic
  waiter budgets and retained work after timeout/abort.
- App-created listeners and carrier clients have separate cleanup owners.
- Import starts no service.

### Uncertain-send policy (I14)

#### Storage upgrade and adoption

- For I14, use explicit owner version 5 after v4 under quiescence.
- Keep the four new policy tables and their counter separate from old outbox row shapes.
- The sole old catalog relaxation permits repeated provider keys across exact local
  attempts, with a scoped operation foreign key (FK).
- Adopt all old attempts permanently as ordinary.
- Never retrofit an old ambiguous send into an idempotent capability.
- Owner adoption is paged64/bounded50000 (pages of 64 rows, at most 50000 rows) and
  rejects malformed envelope/result/counter state atomically.

#### Provider operations

- Freeze provider namespace/capability, logical recipient/outbound/response, original
  address and body into the provider operation before its first possible call.
- New attempt IDs and route observations never enter that operation digest.
- Preserve callback-v1 attempt/key/requestDigest correlation.
- The cooperating fake's terminal negative must fence all later arrivals of that same key.
- Absence never grants a new key.

#### Recovery commands and permissions

- Use distinct trusted recovery-controller credentials and immutable UUID commands.
- Original-command replay is lookup of its retained receipt, with no provider I/O.
- Unknown permissions and possible sends do not retry automatically.
- Ordinary unknown always holds.
- New idempotent calls need current association/route/suppression plus all-prior
  callback and operation evidence checks under existing admission.
- Keep history valid using a specific immutable predecessor admission witness.
- Later conflicts veto future calls without retroactively corrupting admitted history.

#### Bounds, results and telemetry

- Keep the existing aggregate SQL/task/pool bounds.
- The policy SQL helper owns no second pool or worker.
- Preserve late actual results after waiter timeout.
- Expose acknowledgement uncertainty separately from definitive rejection.
- Metrics/logs use finite codes with no IDs or payloads.
- The app owns supplied carrier HTTP cleanup.
- No callback-driven resend, physical exactly-once, complete media row or automatic
  booking completion is introduced by this slice.

### Native text and committed voice (I15/I16)

- Use only the explicit `./native` opaque integration and version 6 owner upgrade.
- Never fabricate a native caller as a verified fake-SMS provider.
- Publisher, account, room-binding and prepare credentials are distinct.
- Browser real-time communication (RTC) tokens contain no native ingress credential.
- Fix tenant/account/case/conversation/room/participant in trusted construction.
- Stream IDs and provider/model output cannot select authority.
- Persist input and its stable UUID before ACK or generation.
- Keep the existing persisted dispatcher as the sole generation owner.
- No second queue or direct native business invocation.
- Disable `RoomOptions.text_input`, set `session_host=False`, use manual
  turns/preemptive generation disabled, and always `StopResponse` from
  completed-user-turn hooks.
- Count real default reply events so a zero assertion is observable.
- Genuine recognition snapshots capture original turn identity before awaits.
- Interim events and SDK promotion are observation only.
- Repeated commit must not add an input, context message or automatic reply.
- Retain actual sockets/readers/recognition/intake/prepare work through settlement.
- Use fresh PostgreSQL time after original admission/binding locks to block NEW
  prepare/reservation after expiry/revoke, while retaining account history.
- An already admitted possible call is not retrospectively cancelled.
- No disconnected-room implicit revoke, grant renewal or retarget is authorized.
- Preserve the optional pinned Agents dependency edge without refreshing versions.
- The default Python codec remains independently importable.

### Source-qualified response evidence (I17)

Read [COMMUNICATION.md](COMMUNICATION.md) and the
[I17 handoff](../../docs/work-items/0037-playback-evidence-and-process-recovery.md).

#### Storage, roles and sequences

- Use only explicit owner v6-to-v7 migration for the three additive communication tables.
- Keep old canonical rows and the original eighteen native metrics (`native18`) and
  six-key generation wire.
- Publisher/SDK/browser/account credentials have separate roles.
- Body source labels, model text and playback never authenticate or grant
  confirmation/business authority.
- Response/observation replay preserves exact original receipts at legitimate caps.
- Response sequence is scoped to tenant/account/conversation.
- Observations sequence within their original response.
- Global counters govern profile growth only.

#### Generation capture

- Capture the application ContextVar around synchronous generate_reply, bind the
  returned public handle, and retain actual public large language model
  (LLM)/text-to-speech (TTS) node tasks and producer work through settlement.
- Never borrow current_speech, SDK private fields, expected fixture text or
  SpeechHandle.done as proof actual generation drained.
- Preserve streaming, queue of 2/4096-byte/256-chunk limits and normal-exhaustion
  provenance.
- Full generation and synchronized SDK partial text are separate sources.
- An interruption request is not a stopped/playback-complete acknowledgement.

#### Browser evidence

- Browser evidence is a scoped original-response report.
- Never map delayed callbacks to a mutable current response, invent completion after
  disconnect, or infer human hearing.
- Late evidence appends to its retained original response after grant expiry.
- New response creation still requires current grant authority.
- SDK completed and browser unknown can coexist.
- Contradictions are retained without timestamp winners.

### Read-only current-case context (I18)

Read [REHYDRATION.md](REHYDRATION.md) and the
[I18 handoff](../../docs/work-items/0038-case-rehydration-and-standalone-release.md).

- Derive scope from the current native grant or exact authenticated already accepted
  SMS plus original current epoch.
- Do not use retained account history as current channel authority.
- Reuse the existing inbox transaction/pool.
- No second read store, case clone, session queue or automatic acceptance/generation
  is authorized.
- Capture coherent P2 history, release SQL for the public current-case read, then
  perform a new protected disclosure check using fresh database time.
- Later revocation cannot retract returned bytes.
- P1/P2 observations are not atomic.
- Allowlist public P1 facts and exclude quote/confirmation/control payloads.
- Preserve source fingerprints separately from revisions/cursors.
- Supplier/work state can advance at one case revision.
- Loaded facts are explicitly as-of, and refresh is idle/explicit with zero generation.
- Revision mismatch blocks preparation before SDK invocation.
- Keep pure read zero distinct from the existing positive-revision native
  dispatch/communication domain.
- Never auto-revise or pretend zero support.
- Bound total envelope bytes, not only rows or child text.
- Omit whole records with separate scoped continuation.
- Original source/receipt/operation/response identities are immutable history.
- New room bindings use fresh genuine input IDs.
- Never add old room responses to new speech controls.
- Preserve legacy `native18`/wires.

### Workload ownership (I19)

- Read [WORKLOAD.md](WORKLOAD.md) and the frozen workload manifest before changing its
  actual fixture or runner.
- Preserve the declared schedule and budgets before measurement.
- The inbox limit counts every retained row.
- Completion does not reclaim capacity.
- Use bounded public credential windows for dormant cases, never SQL seed bypass or a
  larger SeededAccounts cap.
- Report per-instance and actual aggregate pools/tasks separately.
- Selected cross-scope progress is not fairness.
- Ordinary inbox observers reserve a slot before invocation and retain it until
  actual promise settlement.
- The observers' three-key telemetryMetrics is separate from existing communication
  metrics.
- SQL close does not own an injected transport.
- Release application-held observer work before asserting complete cleanup.
- Keep selective forwarding unit (SFU) inventory read-only in the parent and provider
  credentials absent.
- A fresh process and populated restore must preserve old receipts/keys/body/conflicts.
- Display eviction must never delete canonical replay protection.

### Operations reads (I20)

Follow [OPERATIONS.md](OPERATIONS.md) and the fixed operations manifest.

#### Cursors and freshness

- Preserve legacy rehydration cursor/field limits and final current-grant admission.
- The new signed cursor is application-source/scope/section-bound and never read or
  mutation authority.
- Do not treat accepted-row paging as a complete status-event feed.
- Keep explicit refresh and separately observed as-of facts.
- Revision equality is not workflow/supplier freshness, and revision-zero reads grant
  no native execution.

#### Diagnostics and telemetry

- The independent operator diagnostic capability carries process facts only.
- Keep finite metric/log/span enums, actual reader owners separate from caller spans,
  no body/token labels and failed getters unavailable rather than zero.
- Use source-specific producer maps and the closed 76-code vocabulary.
- Unknown events, arbitrary labels and accessor fields fail closed.
- Reserve completion ownership before callbacks, getters and thenable access.
- Reentrant close keeps returned work owned until actual settlement and blocks later
  getter admission.
- Retain ignored async work until it settles.
- Observe actual overload, rejection, dropout and useful progress.
- No default listener, automatic business queue, resend control or exporter service
  is added.

#### UI client and close order

- Keep one retained UI client across Forget/Connect epochs.
- Clear private state immediately but withhold new admission until the old actual
  owner closes.
- Close dependent readers/dispatchers before shared inbox/case resources.
- Attempt every independent owner within a safe tier and preserve the first failure.
- Unresolved owners retain marked work and prevent schema deletion.

### Installed starter application (I21)

Follow [STARTER.md](STARTER.md), the fixed starter manifest and the
[0041 handoff](../../docs/work-items/0041-standalone-channel-and-durable-policy.md).

- Keep the executable inert on import and plan before any
  configuration/PostgreSQL/listener startup.
- The additive application export composes the unchanged SDK.
- The explicit owner bootstraps schemas.
- Runtime cannot rewrite immutable profile/catalog data.
- Keep route-versus-serve exclusion on one owned session mutex across processes and
  retain it until dependent I/O actually closes.
- No transaction spans external HTTP.
- The four-table application receipt ledger is synthetic external evidence, never a
  second work queue or business authority.
- Investigation/idempotent replay and conflict precede capacity.
- Equal ordinary port calls append distinct physical observations.
- No reliable lookup or automatic resend is implied.
- Preserve compact canonical operation bytes/digest/binding validation and the
  declared wire limits.
- Keep ordinary reply text nonempty and legacy carrier response-header contracts.
- Keep existing SDK/default service/native/P1 sources unchanged.

### Stable result receiver and current-grant read (0043)

The [0043 work item](../../docs/work-items/0043-stable-result-delivery-and-return-context.md)
owns the new v8 seam.

#### Upgrade, identities and receiver acceptance

- Use only the explicit quiescent owner v7-to-v8 upgrade.
- Serving code never runs DDL, rotates the retained receiver ID or adopts an
  unrelated ordinary outbox UUID.
- Accept/find authenticate a distinct trusted publisher capability.
- The original canonical P1 intent/result digest and logical recipient remain immutable.
- This profile accepts the explicit P3-compatible 64-character identifier subset.
- Reject wider unsupported identifiers without truncating or rewriting them.
- Result metadata and the fixed ordinary notice commit together under the existing
  outbox admission lock and maxReplies cap.
- A notice bodyDigest is never the P1 result_sha256.
- Exact replay/read remain available at capacity.
- Changed bytes conflict.
- Receiver acceptance grants no carrier send, hearing or action authority.

#### Current-channel reading

- Current-channel reading is separate: derive the route from a current native grant,
  release SQL for the public P1 read, then recheck the original grant under locks
  with fresh database time.
- Retain one shared outbox call slot through this entire sequence.
- No connection/transaction spans external I/O.
- Case/reply times and applicability are observations across separate reads, never
  an atomic snapshot.
- Keep the existing rehydration-v1 shape, native tools-disabled policy, unknown-send
  behavior and revision-zero read-only boundary unchanged.

### Operation-only origin integration (0044)

- The public `./starter` OperationClientConfig overload supplies only trusted profile,
  loopback endpoint and account/case/conversation/sender bindings with an operation
  bearer.
- Preserve the legacy two-argument constructor and actual two-call/socket ownership
  limits.
- Never fabricate SMS metadata for a native publisher or put this service credential
  in browser/model inputs.
- Keep encoded frame and original canonical input independently bounded, validating
  closed descriptors before I/O.
- The [0044 work item](../../docs/work-items/0044-origin-bound-channel-policy.md) keeps
  original payload bytes in P2 and returns the actual P1 work UUID as the external
  receipt.
- A kind/receipt does not establish channel provenance.
- Real accepted-event joins are required.
- Restrict only P3-mapped identifiers/revisions at the bridge, preserving P2-only
  sender/event/message bounds.
- Remote accept errors remain OutcomeUnknown and failed lookup remains Unavailable.
- Neither permits a replacement operation key.

## Verification

From the repository root:

| Check | Command | When to run |
| --- | --- | --- |
| TypeScript package typecheck | `corepack pnpm --filter @livekit-ecosystem/channel-continuity typecheck` | All changes |
| TypeScript package tests | `corepack pnpm --filter @livekit-ecosystem/channel-continuity test` | All changes |
| TypeScript package build | `corepack pnpm --filter @livekit-ecosystem/channel-continuity build` | All changes |
| Project Python unittest suite | `.venv/bin/python -m unittest discover -s projects/channel-continuity/tests -v` | All changes |
| Relevant implemented scenario | `.venv/bin/python -m harness run <ID>` | All changes, before handoff |
| Focused structural checks | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh --module p2` | All changes, before handoff |
| Full fast lane | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh` | All changes, before handoff |
| Full PostgreSQL lane (23 cases) | `make p2-postgres-check` | Storage or association changes, after restricted-role local setup |
| Standalone example lane | `.venv/bin/python local-setup/scripts/p2_postgres_check.py --example` | Standalone example, dispatch or storage changes |
| Dispatch lane | `.venv/bin/python local-setup/scripts/p2_postgres_check.py --dispatch` | Dispatch (I07) or storage changes |
| Gateway three-case subset | `.venv/bin/python local-setup/scripts/p2_postgres_check.py --gateway` | Gateway (I08) changes |
| Agent process fixture | `.venv/bin/python local-setup/scripts/p2_postgres_check.py --agent` | Agent process (I09) changes |
| Revision routing gate | `.venv/bin/python local-setup/scripts/p2_routing_check.py` | Revision routing (I10) changes |
| Confirmation gate | `.venv/bin/python local-setup/scripts/p2_confirmation_check.py` | Confirmation (I11) changes |
| Outbox gate | `.venv/bin/python local-setup/scripts/p2_outbox_check.py` | Outbound reply (I12) changes |
| 24-assertion callback gate (`callback24`) | `make p2-callbacks-check` | Provider callback evidence (I13) changes |
| 30-assertion gate (`actual30`) | `make p2-send-policy-check` | Uncertain-send policy (I14) changes |
| v7 storage (`storage16`) and browser/audio (`audio3`) gates | `make p2-communication-check` and `make p2-playback-check` | Source-qualified response evidence (I17) changes |
| Six-group native regression (`native6`) | `make p2-native-check` | Source-qualified response evidence (I17) changes |
| Current-case storage and media gates | `make p2-rehydration-check` and `make p2-rehydration-media-check` | Read-only current-case context (I18) changes |

The table indexes these checks; the rules below it remain authoritative.

### All changes

- Run the TypeScript package's typecheck/test/build and project Python unittest suite
  from the root as documented in README.md.
- Keep exact cross-language canonical bytes, duplicate-key/Unicode/numeric and UTF-8
  boundary fixtures.
- Use stable P2 acceptance IDs in the change plan and evidence.
- Run the relevant implemented scenario, focused structural checks and full fast lane
  before handoff.
- Commands in the README run from the repository root.
- Planned, skipped, missing and timed-out checks cannot count as passes.
- New behavioral runners need real assertions and useful failure artifacts.
- No hidden service setup is allowed.

### Storage and association changes

- For storage/association changes run `make p2-postgres-check` after restricted-role
  local setup.
- SMS-only qualification cannot close a complete product row.

### Standalone example

- Run `--example` and the full PostgreSQL lane for changes to the standalone example.

### Dispatch (I07)

- Use `--dispatch`, the full 23-case lane and `--example` for dispatch/storage changes.
- Keep the separate cooperating operation fixture outside the SDK and prove actual
  commit/kill/fresh-process lookup.

### Gateway (I08)

- Observe actual HTTP200 before the owned SIGKILL, verify zero prepared/external work
  before it, then prove fresh-process recovery/replay and cleanup.
- Preserve all old cases in the full 23-case lane and use `--gateway` for the
  three-case subset.

### Agent process (I09)

- The `--agent` fixture keeps a real gateway listening, sees its HTTP200 and an owned
  worker PID barrier, waits for PostgreSQL to observe claim expiry, verifies no plan
  or external operation, then kills only that known active worker.
- The next worker must receive identical original scope/case/revision/input and
  preserve one logical operation acceptance.
- Distinguish repeated scripted processing from business acceptance.
- Retain both dispatch attempts and independently persisted receipt.
- Run real child/descendant unit tests, `--agent` and the full 23-case lane.
- SMS/scripted process qualification does not close a complete charter row or native
  media gate.

### Revision routing (I10)

- Run `p2_routing_check.py`, its offline negative/report/environment tests, public
  artifact checks and the old full 23-case PostgreSQL lane.
- Its two authority fixtures must observe actual PostgreSQL blocking before release,
  one transition/one conflict, valid further progress and postcommit unknown with
  original receipt.
- Independent owner checks prove full P1 mapping/request and zero action effects.
- A report-retention failure cannot pass.
- Missing native/confirmation/revocation acceptance remains non-passing.
- No complete P2 row is registered by this slice.

### Confirmation (I11)

- Run `p2_confirmation_check.py` plus wrapper/HTTP/consent negatives, current I10 and
  old full 23-case (`old23`) regressions and isolated public package consumption.
- I11 selected evidence does not register a complete P2 row or qualify native
  media/UI/outbound delivery.

### Outbound replies and ordinary fake sends (I12)

- Run `p2_outbox_check.py`, wrapper negatives, all P2 tests, I10/I11/`old23`
  regressions and an isolated installed public npm consumer.
- The actual lane includes owner rollback/backup-restore, old/new dispatch on v3, real
  process kill, current-route barriers and independent fake-provider correlation.
- Preserve original failed runs.
- See [the stable phase handoff](../../docs/work-items/0033-outbound-replies-and-completion-processing.md)
  for qualification.
- No complete charter row is registered by I12.

### Provider callback evidence (I13)

- Run the 24-assertion callback gate (`callback24`), wrapper negatives, all P2
  unit/type/build gates and the prior 24-case outbox (`outbox24`), 22-case routing
  (`routing22`), 18-case confirmation (`confirmation18`) and 23-case recovery
  (`recovery23`) regressions.
- Prove actual SQL-cancel rollback, one owned commit-before-ACK SIGKILL, fresh
  original replay, independent provider/SQL binding and populated v4
  backup/restore/reopen.
- Do not count SQL cancellation as a process kill.
- Validate the installed npm artifact with strict public types and actual app-owned
  HTTP/PostgreSQL consumption.
- Preserve failed evidence and use the stable
  [phase handoff](../../docs/work-items/0034-callback-evidence-and-applicability-refresh.md).
- The I13 evidence qualifies only its selected callback slice.
- Use the separate I14 handoff below for current ordinary lost-response and explicit
  idempotent recovery evidence.
- That I13/I14 evidence alone did not qualify native/media behavior. The selected
  I15–I18 gates record it separately.
- Whole P2 rows and broader UI/load qualification remain pending.

### Uncertain-send policy (I14)

- Run the actual 30-assertion gate (`actual30`), retained regressions and isolated npm
  artifact consumer.
- See [the stable handoff](../../docs/work-items/0035-send-policy-and-action-races.md).

### Later slices overview (I15–I22)

- Selected I15/I16 native composition is described in its native handoff.
- The opt-in I17 implementation and qualification boundaries are recorded in its
  communication handoff.
- Selected I18 current-case rehydration and I19 bounded workloads have passed their
  separate gates.
- I20 joined observability passed selected qualification in 0040.
- I21 is the current installed starter slice in 0041. I22 and full release remain
  separate.
- Keep its media/lifetime evidence distinct from selected I12/I13/I14 fake-carrier
  qualification and installed-package checks.
- Never label queued acceptance or a provider report as physical delivery, human
  acknowledgement or booking completion.

### Native text and committed voice (I15/I16)

- Keep the parent native media gate's six browser groups separate from focused
  SDK/storage groups.
- Do not invent twelve browser tests or complete P2-15 registration.
- Use the stable [native handoff](../../docs/work-items/0036-native-input-and-deadline-cancellation.md)
  for evidence.
- I17 qualification is separate from the prior native gate.
- I18 current-case reading/profile has its separate contract and handoff.
- Real inference/recognition and full charter/load gates remain later.

### Source-qualified response evidence (I17)

- Run affected actual SDK and HTTP units, strict types, the explicit v7 16-group
  storage (`storage16`) and actual three-group browser/audio (`audio3`) gates, the
  six-group native (`native6`)/old storage regressions and isolated package consumers.
- Keep each proof layer honestly labelled.
- No complete charter row follows from these selected scripted scenarios or from a
  provider/client report.

### Read-only current-case context (I18)

- Test pure/model/HTTP, pinned SDK, actual storage/media and installed artifacts
  distinctly.
- The prior 0038 checkpoint passed selected I18 storage 18/media 3, isolated Python
  111/npm seven-stage and 166 compatibility assertions.
- The [0039 handoff](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md)
  records selected I19 workload 24, current isolated Python 113/npm seven-stage and
  fresh 187 compatibility assertions, all passed.
- Preserve those historical source/role/receipt/cleanup boundaries alongside the
  selected I20 handoff.
- Pure P1 revision-0 reading does not qualify zero-revision native dispatch or
  communication.

### Workload ownership (I19)

- Keep I20 and complete charter acceptance separate from the selected workload experiment.
- The selected I19 qualification preserves all original inputs and operation
  identities through restart and populated restore.
- Its quantitative observations belong to the declared local profile.
- The separately qualified I20 view does not extend those capacity claims.
- Current I21 installed-application qualification belongs to 0041.
- I22 and complete release acceptance retain their own gates.
- Keep the current installed Python 113-test proof distinct from the prior 111-test
  application snapshot.

### Operations reads (I20)

- Source-qualified browser, actual SQL, socket/mock and installed-package proofs must
  remain distinct.
- The [0040 handoff](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md)
  records selected I20 qualification: sixteen actual PostgreSQL/read assertions and
  three browser groups passed in thirteen owned commands, followed by the isolated
  105-payload npm consumer's seven stages and all 187 fresh compatibility assertions.
- All selected cleanup checks passed.
- Pure/model and real loopback producer tests are distinct from actual SQL/browser
  and installed-archive evidence.
- The Python nine-payload/113-test runtime and application snapshot is unchanged by
  this slice.
- I21 provides the standalone installed starter, with observed qualification in 0041.
- I22 owns fresh-agent and complete release evidence.

### Installed starter application (I21)

- Normal installed twenty and separate public-P1 six require their own frozen source,
  role, process, receipt, permission and populated-restore proofs.
- Preserve all failed attempts, exact whole-record snapshots and first errors.
- I22 and all complete charter rows retain separate release gates.

### Stable result receiver and current-grant read (0043)

- Selected sixteen storage/four return assertions passed.
- The work item records separate package and final shared outcomes.

### Operation-only origin integration (0044)

- Fourteen actual source assertions qualified original native/signed-SMS input, work
  and result joins.
- Integrated voice/text/SMS routing remains pending.
- Isolated package checks remain separate fake-port evidence.

### Charter status

- All seventeen complete P2 charter rows remain planned.

## Handoff

- Record the behavior changed, acceptance IDs, interface/migration decisions, exact
  commands, observed results and remaining work.
- Update implementation status only when evidence supports it.
- Keep offline, local-media and live-model results separate.
- Record assistance and personal contributions accurately.
