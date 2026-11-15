# P1 operational safety extensions

| Field | Value |
| --- | --- |
| Status | Planned |
| Purpose | Plan bounded post-V1 operational safety slices for restore quarantine, adjudication and compaction |
| Audience | Engineers selecting P1 operational work after V1; reviewers; coding agents |
| Scope | Planned slices O1, O2 and O3 and their criteria; excludes any implementation, schema, runner or new acceptance ID |
| Owns | O1 to O3 change plan, planned validation criteria and handoff |
| Related | [Architecture review](0020-architecture-audit-reconciliation.md) · [Release work item](0019-p1-phase-h-release-qualification.md) · [P1 charter](../projects/agent-continuity-scope.md) · [Validation plan](../validation-plan.md) |

## Behavior and scope

This work item plans bounded operational improvements for after V1 (the fixed
version-1 project scope). The
[architecture review](0020-architecture-audit-reconciliation.md) identified them.
The completed [Phase H scope](0019-p1-phase-h-release-qualification.md) remains
unchanged. This work item implements no adjudication endpoint, recovery mode,
compaction runner or new acceptance ID.

Before coding:

1. Choose one slice below.
2. Freeze its contracts and budgets.
3. Create its implementation handoff.

Do not implement all three mechanisms together. Independent P2 and P3 contract
work can continue at its existing frontiers.

| Slice and order | Intended behavior | Existing context and scope boundary |
| --- | --- | --- |
| O1: restored-database quarantine | An operator can restore a snapshot into a new isolated target without replaying supplier effects that outlived that snapshot | Related P1-08/09/15/19; extends migration rollback and ordinary crash recovery, not proof they already cover supplier divergence |
| O2: append-only adjudication | A verified reviewer records a sourced operational determination about an uncertain case | Related P1-09/17; original supplier outcome/event remain immutable; no automatic supplier retry |
| O3: conditional core compaction | Reclaim capacity only under a reviewed replay/tombstone policy | Related P1-03/16/18; V1 already retains core identities indefinitely with finite fail-closed caps; diagnostic pruning remains separate |

O1 and O2 are the recommended next operational slices. O3 is optional until
sustained capacity reclamation is in scope. These are planning labels, not catalog
case IDs or qualified features. Re-estimate each slice after its schema and
failure schedule are reviewed. Prior project effort estimates do not include this
scope.

## Interfaces and ownership

P1 retains sole durable execution ownership. The case authority owns case
revisions and new explicit consent. Supplier and receiver ledgers remain
independent truth. Introduce owner-run versioned schema migrations before any new
persisted state. No serving process receives data definition language (DDL)
privileges. Public package changes require typed exports, isolated installed
consumers and advertised Python 3.14 qualification.

### O1: restored authority and external ledgers

A restore begins with dispatch disabled in a new isolated target. Bind the dump,
the restoration inventory and the reconciliation plan to the original
authority/deployment, scopes, and supplier and receiver identities. Explicitly
isolate or stop old consumers before enabling restored writes. Restored lease
epochs cannot fence old external requests. A recovery flag on the new database
cannot stop old processes.

Take snapshots both before dispatch reservation and before the original intent or
effect exists. Let the independent supplier and receiver advance after the
snapshot, and preserve independent evidence of those newer effects. Restore does
not imply the supplier rolled back.

A missing local effect record, an incomplete inventory or a missing reliable
lookup must hold the affected scope in quarantine. The quarantine includes new
submissions that could recreate the lost logical operation. Never manufacture a
fresh effect identity to replace missing history. An ordinary worker restart is
not an authorized restored-database activation procedure.

Reconcile only with original identities and reliable independent evidence:

- If the supplier lacks trustworthy enumeration or lookup, or the identity cannot
  be recovered, record unresolved status and retain quarantine.
- A scoped release decision must be authorized and persisted after
  reconciliation. It cannot silently clear another scope, an unknown effect or a
  pending old consumer.
- Customer confirmation must not be reconstructed from supplier output or
  restored guesses. New mutations require the current exact consent contract.

Keep existing runtime startup behavior unchanged until this protocol and its safe
upgrade path are implemented and tested.

### O2: operational determination without rewriting supplier truth

Add a separately authorized reviewer principal and a scoped append-only command.
The command binds:

- the original effect;
- the expected adjudication revision;
- a stable command ID;
- a bounded reason;
- an evidence reference.

Customer, native or worker authority alone cannot adjudicate. Validate source
provenance and access. Arbitrary model prose, confidence or an inaccessible
reference cannot establish verified supplier success.

Identical command replay returns the same decision. A changed payload,
cross-effect identity reuse and competing expected revisions conflict. Define one
current protected decision. If correction is supported, an explicit supersession
event preserves prior decisions. Commit audit metadata and the decision
atomically.

Original terminal BusinessOutcome, effect and completion-event bytes remain
unchanged. A determination records verified external evidence, operator judgement
or unresolved status distinctly. The UI and any new communication must preserve
that provenance. Use a separate stable communication identity, not a rewritten
completion event. Recording a decision never calls supplier apply, reopens
dispatch or grants new mutation consent. Later legitimate work remains separately
authorized.

### O3: retention policy before reclamation

V1 indefinitely retains core effect, attempt, cancellation, outcome, completion
and deduplication identities inside finite caps. At capacity, reject new growth
while preserving original replay and inspection. Only the diagnostic projection is
pruned. Keep this correct bounded default until a compaction design is reviewed.

Before deleting core data, specify:

- replay horizons;
- the authority clock;
- canonical payload/conflict tombstones;
- expired-identity rejection;
- unresolved-effect retention;
- backup/restore interoperability;
- maximum resource costs.

Commit sufficient protection before deletion. Expiry may reject an old identity;
it must never accept it as new. Do not select an arbitrary short retention period
merely to free space.

## Failure cases and validation

These criteria are planned and have no passing execution evidence yet. Use actual
PostgreSQL, independently persisted supplier and receiver fixtures, owned
processes and deterministic barriers. A reopened connection or mock cannot qualify
recovery.

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

Gate names starting with G- refer to the engineering gates in the
[validation plan](../validation-plan.md).

| Gate | Required evidence before completion |
| --- | --- |
| G-READY/CONTRACT | Reviewed principal, schemas, bounds, scope-release rules, safe error vocabulary and ordinary/negative/useful-progress fixtures |
| G-DURABLE | Actual migrations, isolated restore, independent ledgers, concurrent transactions, real child termination/restart and preserved original M1 (confirmed-investigation intake) data |
| G-OBS | Real bounded status/decision/recovery events; finite reason/status labels; no credentials, private evidence or raw document text; telemetry outage does not block recovery |
| G-PACKAGE | Isolated built-artifact examples if public APIs change; no source injection |
| G-MEDIA | Required only if native/browser behavior changes; actual scoped UI observations and no new model authorization |
| G-FAST/RELEASE | Full applicable fast/format/type gates and affected PostgreSQL/runtime/package assertions; missing prerequisites, required skips, zero tests and cleanup failures stay non-passing |

### Budgets, error codes and signals

Before executing each slice, freeze finite operation and shutdown budgets, control
group (cgroup) caps, maximum inventory sizes and safe evidence locations. Error
codes must distinguish unauthorized, revision conflict, quarantine, unavailable
evidence, capacity and unknown outcome. Exact names are chosen with the
implementation contract. Recovery retry retains its plan and command identity and
does not grant supplier retry authority.

Metrics count decisions, conflicts, quarantined scopes and reconciliation outcomes
with fixed dimensions. Identities belong only in authorized bounded logs and
spans. Measure recovery lag using declared clock sources, not model-reported
timestamps.

### Existing regression commands

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
when each runner exists. Source or runtime changes must rerun affected P1
acceptance and installed-consumer/media evidence. Preserve the old Phase H reports
unchanged.

## Results and handoff

This work item is planning only. O1, O2 and O3 have no implementation, schema,
runner or passing result. The next action is to freeze O1's restore inventory,
containment and quarantine contract and budgets before coding. Record each slice's
test results, independent review, limitations and decision before selecting the
next. No remote continuous integration (CI), publication, real-carrier account or
new infrastructure service is required.
