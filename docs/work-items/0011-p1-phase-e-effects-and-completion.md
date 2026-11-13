# P1 Phase E supplier effects and durable completion

Status: Completed
Last reviewed: 9 November 2026

## Behavior and scope

Implement P1-I15 through P1-I18 after the completed Phase D gate: apply the exact
confirmed fake booking revision, reconcile a real mutation crash, expose honest
uncertainty for a noncooperating supplier, record idempotent cancellation and
commit/deliver a stable completion event. Use original task/case/intent/effect
identities and the same durable execution owner. No leases or voice-interruption
release claim is introduced.

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P1-06/07 | Versioned exact proposal, trusted owner and explicit confirmation | Confirm then execute apply | Actor/revision/price/expiry/target mismatch never invokes apply; supplier CAS protects expected booking revision | Exact confirmed date, amount/currency and next booking revision persist under original effect | Real PG and independent persisted supplier |
| P1-08/09 | Supplier success or possible dispatch; no local acknowledgement | Terminate worker and start a fresh process | Cooperating lookup/dedup discovers original result; noncooperation causes uncertainty and no unsafe resend | Eligible cooperating work reaches known outcome | Actual process/container barriers and supplier ledger |
| P1-13/14 contribution | Cancel command and confirmation/dispatch boundary | Race or replay cancellation | Precommit/pre-dispatch cancellation prevents mutation; post-dispatch request never claims reversal | Known results remain inspectable and completion progresses | Protected transaction races and ordinary paths |
| P1-16 | Terminal outcome and stable completion event | Crash before/after receiver commit, then deliver again | Outcome/event atomic; same logical event and receiver binding survive replay | Bounded delivery succeeds independently of business outcome | Real independent sink and owned processes |
| Retention | Diagnostic history pruned or delivery exhausted | Replay original event/command | Core effect, cancellation and receiver receipts remain; no identity is recreated | Existing replay remains available at capacity | Projection pruning and late replay assertions |
| Upgrade | Existing ACTIVE PostgreSQL v2 and legacy consent JSON | Explicit owner-only v3 upgrade or interruption | Original inquiry/case/wait/intent bytes remain; v1 consent is never filled from mutable supplier state | Versioned new work progresses; legacy history/replay is readable | Actual version chain, rollback/process loss and restricted-role tests |

## Interfaces and ownership

Quote/confirmation/intent payload v2 binds the independent case ID, workflow,
current case revision, exact booking/date/amount/currency/expiry, supplier identity
and expected supplier booking revision. Legacy payload v1 remains read/replay
compatible, but cannot authorize a new mutation. Reissue a fresh proposal rather
than inventing supplier revision or target at dispatch.

A new independent mutation supplier fixture owns current booking truth and a
read-only inquiry view over that same authority. The old read-only fixture remains
for compatibility evidence. Provider identity and cooperation mode are immutable.
External calls occur outside the protected PG transaction. Persist possible
dispatch before calling; generation is claim ownership, not a lease or generic
row revision. A fresh no-dispatch claim is distinct from a possible prior call.

Cancellation, confirmation and dispatch serialize under the shared authority
transaction. Cancellation intent/disposition, physical supplier result, business
outcome, event delivery and human acknowledgement remain separate. Preserve a
known inquiry result if cancellation arrives during its read-only call.
Terminal business outcome, immutable completion event and pending delivery commit
atomically. Receiver identity is bound before first delivery; a configuration
change cannot silently redirect a retry. No core receipt deletion is permitted.

## Failure cases and validation

| Gate | Why applicable | Required assertions | Setup/bounds | Evidence |
| --- | --- | --- | --- | --- |
| G-READY | Entire phase | Phase D passed; supplier revision/target and cancellation boundaries reviewed | Frozen dependency/image baseline | Phase D gate and this decision |
| G-CONTRACT | New effect/cancel/delivery contracts | Strict v1/v2 payload compatibility, scope/actor/identity binding and finite safe errors | Synthetic inputs only | Unit/public service and real store tests |
| G-DURABLE | Mutation, cancellation, outcome and event | Real stopped workers, independent supplier/receiver, commit-response loss, one logical effect/event and useful progress | Actual PostgreSQL; separately persisted SQLite fixtures | Named barriers/process/container evidence |
| G-OBS | Effect/cancel/outbox producers | Safe real events and metrics; no payload, token, SQL or exception text | Fixed labels; telemetry outage containment | Producer/CLI/sentinel tests and actual demo |
| G-FAST | All source and shared policy | Full offline checks, lint/types/format, docs and original acceptance runners | Existing interpreter/locks | Retained final gate output |
| G-MEDIA | Runtime rebuild regression | Existing native RTC/M1 checks preserve identity | Existing stack/volumes | Actual smoke, not human/browser playback |
| G-PACKAGE | Installed application | Runtime wheel imports outside source; process/container crash/replay | Owned isolated fixtures | Hashes and real installed consumer |

Keep attempts, backoff, buffers, locks and shutdown finite. Positive evidence of
no dispatch is a typed provider assertion, never an exception-text inference.
Quote expiry is checked at commitment; a committed intent is not retroactively
invalidated by quote expiry. Fresh dispatch still checks original business deadline
and cancellation. Known external truth survives later timeout/cancellation.
Required skips, missing setup, zero tests or timeouts cannot pass.

## Results and handoff

P1-I15 through P1-I18 completed. The final machine gate is
.local/validation/p1-phase-e/phase-gate.json. Runtime/dependency versions remain
frozen; no new direct dependency, image pin or public business API was introduced.

| Observed gate | Command or mode | Result |
| --- | --- | --- |
| Offline and shared harness | make check | 440 tests, zero skips; structure/ownership/negative fixtures pass; Ruff and normal service/core typing pass for 50 files |
| Strict changed boundaries | mypy --strict --follow-imports=silent over 16 authority/continuation/effect modules | Pass; separately strict process helper and installed probe pass; this is not whole-repository strict typing |
| Actual PostgreSQL | make postgres-check with phase report | 186 tests, zero failures/errors/skips: 116 retained earlier suites, 16 v3 upgrade, 21 mutation, 24 effect/outbox and 9 compatibility/lifecycle boundary tests |
| Frontend regression | make frontend-check | TypeScript, 66 tests in 3 files and production build pass; existing bundle size advisory retained |
| Documentation and diagrams | documentation checker and actual Mermaid parser | 71 documents pass; 33 diagrams across 11 designs parse and deliberately invalid fixture is rejected |
| Formatting | Ruff format check | 116 Python files pass |
| Installed local runtime | rebuild, then make phase-e-demo | Five fresh containers; 38 core modules match installed site-packages code from /tmp; real exits 71/72 after supplier/receiver commit; safe events and positive metrics in each stage |
| Real media/M1 regression | local-setup/stack.py smoke | Native text/UTF-8 boundary and 10 fixture-audio frames pass; original M1 investigation identity preserved |
| Product acceptance catalog | harness run --project all | Six registered runners pass; 49 remain not_implemented; expected exit 2 reports incomplete portfolio qualification |

The Docker proof retains exactly one physical supplier mutation/apply, one logical
receiver event, zero cancelled-task dispatches, the same completion/outcome and
retained dedup after diagnostic pruning. It verifies both missing local
acknowledgements before starting the next process. New labelled fixture volume,
containers and isolated schema are cleaned before the pass artifact is written;
normal M1 volumes remain intact. Synthetic clock values establish policy behavior,
not production latency. The actual run uses host macOS and Linux containers with
Python 3.14; the advertised full Python/platform matrix remains unverified.

Independent reviews corrected cross-effect active-attempt corruption: terminal
paths now validate intent, attempt number and guarded state before closing an
attempt. Two real-database regressions prove failure is contained and valid work
can progress after repair. Demo review also tightened independent cleanup,
commit-response-loss volume ownership and bounded redacted failure artifacts;
reporting failures cannot replace the original error. No lock/connection budget
was relaxed and no missing requirement was skipped.

Evidence includes fast/strict/format/PG/frontend outputs, catalog/deep status,
Mermaid parse results, runtime build, container stages, smoke and a source manifest
under the phase directory. Earlier phase artifacts remain separate. Implemented
and reviewed with Codex assistance; personal reproduction/explanation remains a
learning activity, not an asserted human implementation contribution.

Next is Phase F, P1-I19 through P1-I21: lease/epoch authority, stale external-call
safety, bounded admission/shutdown and actual product-worker orchestration.
Distributed leases, actual speech interruption, business UI/tools, production
identity/transport, full platform matrix and complete portfolio release remain
outside this completed phase. Uncertainty is immutable for automatic dispatch;
future manual adjudication needs a separately versioned observation contract.
