# P1 operational safety extensions

Status: Planned
Last reviewed: 10 November 2026

## Behavior and scope

Plan bounded post-V1 operational improvements identified in the
[architecture review](0020-architecture-audit-reconciliation.md). The completed
[Phase H scope](0019-p1-phase-h-release-qualification.md) remains unchanged.
No adjudication endpoint, recovery mode, compaction runner or new acceptance ID
is implemented by this work item. Before coding, choose one slice below, freeze
its contracts/budgets and create its implementation handoff. Do not implement all
three mechanisms together. P2/P3 independent contract work can continue at its
existing frontiers.

| Slice and order | Intended behavior | Existing context and scope boundary |
| --- | --- | --- |
| O1: restored-database quarantine | An operator can restore a snapshot into a new isolated target without replaying supplier effects that outlived that snapshot | Related P1-08/09/15/19; extends migration rollback and ordinary crash recovery, not proof they already cover supplier divergence |
| O2: append-only adjudication | A verified reviewer records a sourced operational determination about an uncertain case | Related P1-09/17; original supplier outcome/event remain immutable; no automatic supplier retry |
| O3: conditional core compaction | Reclaim capacity only under a reviewed replay/tombstone policy | Related P1-03/16/18; V1 already retains core identities indefinitely with finite fail-closed caps; diagnostic pruning remains separate |

O1 and O2 are the recommended next operational slices. O3 is optional until
sustained capacity reclamation is in scope. These are planning labels, not catalog
case IDs or qualified features. Re-estimate each slice after its schema and failure
schedule are reviewed; prior project effort estimates do not include this scope.

## Interfaces and ownership

P1 retains sole durable execution ownership. Case authority owns case revisions
and new explicit consent; supplier/receiver ledgers remain independent truth.
Introduce owner-run versioned schema migrations before any new persisted state.
No serving process receives DDL privileges. Public package changes require typed
exports, isolated installed consumers and advertised Python 3.14 qualification.

### O1: restored authority and external ledgers

A restore begins with dispatch disabled in a new isolated target. Bind the dump,
restoration inventory and reconciliation plan to the original authority/deployment,
scopes, supplier and receiver identities. Explicitly isolate or stop old consumers
before enabling restored writes. Restored lease epochs cannot fence old external
requests; a recovery flag on the new database cannot stop old processes.

Take snapshots both before dispatch reservation and before the original intent or
effect exists. Let the independent supplier and receiver advance after the
snapshot. Preserve independent evidence of those newer effects. Restore does not
imply the supplier rolled back. A missing local effect record, incomplete inventory
or missing reliable lookup must hold the affected scope in quarantine, including
new submissions that could recreate the lost logical operation. Never manufacture
a fresh effect identity to replace missing history. An ordinary worker restart is
not an authorized restored-database activation procedure.

Reconcile only with original identities and reliable independent evidence. If the
supplier lacks trustworthy enumeration/lookup or the identity cannot be recovered,
record unresolved status and retain quarantine. A scoped release decision must be
authorized and persisted after reconciliation; it cannot silently clear another
scope, an unknown effect or a pending old consumer. Customer confirmation must not
be reconstructed from supplier output or restored guesses. New mutations require
the current exact consent contract. Keep existing runtime startup behavior unchanged
until this protocol and its safe upgrade path are implemented and tested.

### O2: operational determination without rewriting supplier truth

Add a separately authorized reviewer principal and a scoped append-only command
binding the original effect, expected adjudication revision, stable command ID,
bounded reason and evidence reference. Customer/native/worker authority alone
cannot adjudicate. Validate source provenance and access; arbitrary model prose,
confidence or an inaccessible reference cannot establish verified supplier success.

Identical command replay returns the same decision. Changed payload, cross-effect
identity reuse and competing expected revisions conflict. Define one current
protected decision; if correction is supported, an explicit supersession event
preserves prior decisions. Commit audit metadata and the decision atomically.
Original terminal BusinessOutcome, effect and completion-event bytes remain
unchanged. A determination records verified external evidence, operator judgement
or unresolved status distinctly; the UI and any new communication must preserve
that provenance. Use a separate stable communication identity, not a rewritten
completion event. Recording a decision never calls supplier apply, reopens dispatch
or grants new mutation consent. Later legitimate work remains separately authorized.

### O3: retention policy before reclamation

V1 indefinitely retains core effect, attempt, cancellation, outcome, completion and
deduplication identities inside finite caps. At capacity, reject new growth while
preserving original replay and inspection. Only the diagnostic projection is
pruned. Keep this correct bounded default until a compaction design is reviewed.

Before deleting core data, specify replay horizons, authority clock, canonical
payload/conflict tombstones, expired-identity rejection, unresolved-effect retention,
backup/restore interoperability and maximum resource costs. Commit sufficient
protection before deletion. Expiry may reject an old identity; it must never accept
it as new. Do not select an arbitrary short retention period merely to free space.

## Failure cases and validation

These criteria are planned and have no passing execution evidence yet. Use actual
PostgreSQL, independently persisted supplier/receiver fixtures, owned processes
and deterministic barriers; a reopened connection or mock cannot qualify recovery.

| Criterion | Given / When | Safety assertion | Useful-progress assertion |
| --- | --- | --- | --- |
| O1 early snapshot | Restore before intent exists after external apply and receiver acceptance | Affected scope remains quarantined; no fresh effect/duplicate apply, inferred consent or false success | Reliable inventory reconciles original identities, or clearly reports the unresolved hold |
| O1 reservation snapshot | Restore before reservation while supplier has committed | Reconcile original effect; no duplicate mutation or duplicate logical completion | Cooperating original lookup produces an inspectable known result |
| O1 no reliable lookup | Incomplete ledger, missing stable identity or noncooperating supplier | No resend, scope release or fabricated reconstruction | Unaffected independently cleared scope can progress; blocked scope remains inspectable |
| O1 old consumer and crash | Hold an old worker before I/O; isolate it, restore, crash during reconciliation, resume safely | Demonstrate actual old-consumer containment; no claim that restored epochs fence external I/O | Fresh reconciler resumes the same plan and safely cleared work completes |
| O2 identity and authority | Missing/wrong reviewer, cross-account effect, forged evidence, identical/changed command replay | Safe scoped rejection; immutable original bytes; no supplier call | Valid reviewer command commits once and remains inspectable after restart |
| O2 race and response loss | Two reviewers use the same expected revision; kill before/after commit acknowledgement | One current decision, original receipt on replay, atomic audit and explicit conflict | Eligible review or explicit supersession progresses without changing supplier truth |
| O2 presentation | Emit a decision/communication with evidence, judgement or unresolved status | Honest source labels; no cancellation/success/acknowledgement invention; zero apply | Authenticated UI exposes the decision and separate delivery observation |
| O3 replay/compaction | Race replay with compaction; crash between tombstone and delete; jump clock; replay changed payload | Original identity preserved/rejected, conflicts retained, uncertainty protected | Capacity is reclaimed only under the reviewed contract; new unrelated work progresses |

| Gate | Required evidence before completion |
| --- | --- |
| G-READY/CONTRACT | Reviewed principal, schemas, bounds, scope-release rules, safe error vocabulary and ordinary/negative/useful-progress fixtures |
| G-DURABLE | Actual migrations, isolated restore, independent ledgers, concurrent transactions, real child termination/restart and preserved original M1 data |
| G-OBS | Real bounded status/decision/recovery events; finite reason/status labels; no credentials, private evidence or raw document text; telemetry outage does not block recovery |
| G-PACKAGE | Isolated built-artifact examples if public APIs change; no source injection |
| G-MEDIA | Required only if native/browser behavior changes; actual scoped UI observations and no new model authorization |
| G-FAST/RELEASE | Full applicable fast/format/type gates and affected PostgreSQL/runtime/package assertions; missing prerequisites, required skips, zero tests and cleanup failures stay non-passing |

Freeze finite operation/shutdown budgets, cgroup caps, maximum inventory sizes and
safe evidence locations before executing each slice. Error codes must distinguish
unauthorized, revision conflict, quarantine, unavailable evidence, capacity and
unknown outcome. Exact names are chosen with the implementation contract. Recovery
retry retains its plan/command identity and does not grant supplier retry authority.
Metrics count decisions, conflicts, quarantined scopes and reconciliation outcomes
with fixed dimensions; identities belong only in authorized bounded logs/spans.
Measure recovery lag using declared clock sources, not model-reported timestamps.

Existing regression commands from the repository root are:

```sh
make test
make check
make format-check
make postgres-check
```

The PostgreSQL command requires documented restricted-role local setup. These
existing commands do not execute the unimplemented operational scenarios above.
Add exact targeted commands, nonzero assertion counts and artifact locations only
when each runner exists. Source/runtime changes must rerun affected P1 acceptance
and installed-consumer/media evidence; preserve the old Phase H reports unchanged.

## Results and handoff

Planning only. O1/O2/O3 have no implementation, schema, runner or passing result.
Next action is to freeze O1's restore inventory, containment and quarantine contract
and budgets before coding. Record each slice's test results, independent review,
limitations and decision before selecting the next. No remote CI, publication,
real-carrier account or new infrastructure service is required.
