# Operations UI and fixed-policy evidence

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the plan, observed verification and handoff for P2-I20 operations UI and P3-I17 fixed-policy evidence |
| Audience | Engineers changing the P2 operations page and read model or P3 fixed-policy version 2; coding agents |
| Scope | Selected P2-I20 and standalone P3-I17 gates; excludes durable v2 execution, full release and the demo video |
| Owns | Change plan, observed verification and handoff for P2-I20 and P3-I17 |
| Related | [Work item 0039](0039-bounded-channel-workloads-and-image-evidence.md) · [Work item 0041](0041-standalone-channel-and-durable-policy.md) · [P2 task plan](../implementation/p2-channel-continuity.md) · [P3 task plan](../implementation/p3-delegation-reliability.md) · [Validation plan](../validation-plan.md) |

## Behavior and scope

This work item implements P2-I20 and P3-I17 after the
[completed workload/image phase](0039-bounded-channel-workloads-and-image-evidence.md).
The [P2 task plan](../implementation/p2-channel-continuity.md),
[P3 task plan](../implementation/p3-delegation-reliability.md), project charters,
[shared design](../../Design.md) and [validation plan](../validation-plan.md) own
requirements.

| Project | Task | Behavior |
| --- | --- | --- |
| P2 | P2-I20 | Joined operations/telemetry view; contributes to P2-13/P2-17 |
| P3 | P3-I17 | Versioned fixed-policy evidence; contributes to P3-11/P3-15 |

Selected task completion does not register complete charter rows.

The closed prior checkpoint was reverified before edits: 3,876 retained artifact
hashes, 779 current public sources and the earlier 1,535-artifact checkpoint
matched. Preserve P1's 77 runtime payloads, original M1, default
services/console, dependency versions and image pins. The reviewed build exception
below adds one existing workspace dependency edge; previous checkpoint bytes
remain immutable. Local POC implementation and tests need no provider/private-CA
settings, paid inference, publication or remote CI.

### P2 operations page

P2 adds an opt-in operations page using actual bounded authorized reads.

- Show accepted input, processing, reply/provider evidence and separately observed
  native response/playback where present.
- Keep unknown outcomes and prior observations visible after refresh failure.
- Typed error/retry hints never authorize a resend, confirmation or mutation.
- Correlation belongs in safe traces/read observations. Identifiers and payloads
  cannot become metric labels.
- The default P1 page remains preserved. Transitions follow actual observations
  and respect reduced motion.

### P3 fixed-policy version 2

P3 adds explicit policy input/result version 2 under booking.evaluate_policy. Keep
version 1 canonical bytes, public default behavior and durable composition
unchanged.

- Separate scoped immutable policy and fact sources bind the supplied version,
  rule and field witnesses.
- Structural validation and factual verification remain separate.
- Missing or contradictory facts clarify. Invented rules, swapped sources and
  unsupported conclusions fail.
- Input text is untrusted data and grants no tools, notification, confirmation or
  mutation.

The version 2 consumer is standalone HTTP. P1 retains opaque policy bytes; it does
not itself reject v2 content. The current P3 durable coordinator/runner remains
version 1, so durable v2 execution needs a reviewed coherent extension. Scripted
fixtures do not certify model accuracy.

### Terms used in this record

| Term | Meaning |
| --- | --- |
| Implementation task IDs | Such as P2-I20; identify tasks in the project task plans |
| Acceptance IDs | Such as P2-13; identify rows in the project charters |
| Selected qualification | The gates chosen for this work item passed; it does not complete a full charter row |
| Gate names | Such as G-READY and G-DURABLE; refer to the engineering gates in the [validation plan](../validation-plan.md) |
| PostgreSQL (PG) | The actual database used by the durable gates |
| Selective forwarding unit (SFU) | The self-hosted LiveKit media server |
| Data definition language (DDL) | Schema-changing SQL; serving code runs none |
| M1 | The original confirmed-investigation intake data, which every phase preserves |
| Proof of concept (POC) | This local repository's delivery target |

### Criteria

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P2 joined view | Trusted scoped read access and retained durable records | Read bounded GET/cursor pages and refresh the operations page | Scope/cursor errors disclose no other account; no read accepts work or changes consent; unknown stays unknown | New actual durable observations appear without fake timed progress | Real PostgreSQL and loopback HTTP, independent durable joins, actual browser transitions |
| P2 lifecycle/telemetry | Slow reads, held or rejecting observers and a page lifecycle | Timeout, retry, refresh, forget or close | Bound bytes/tasks/readers; retain actual ownership and last labelled facts; telemetry cannot block business intake | A later valid read and useful admitted work succeed | Pure negative tests, actual producer observations and local browser evidence |
| P3 fixed policy | Accepted immutable policy/fact sources and an explicit v2 request | Evaluate the finite versioned rule and validate a candidate | Exact source/version/rule/fact joins; structural validity cannot establish factual correctness or action authority | Grounded complete facts yield a supported result; uncertainty clarifies | Cross-language fixtures, independent literal oracle and public HTTP |
| P3 adversarial/lifetime | Missing/conflicting/instruction-like facts or forged candidates | Validate, expire, cancel, overload or close | Instructions remain data; malformed/unauthorized/unsupported facts fail safely; waiter abandonment does not prove I/O stop | Capacity returns only after actual settlement and later valid work progresses | Actual bounded HTTP plus fault/unit coverage |
| Packaging/compatibility | Fresh current Python/npm artifacts | Install public consumers outside the checkout and exercise old APIs | No hidden checkout injection or changed v1 policy bytes/default behavior | New v2 public example and retained prior examples succeed | Isolated installed consumer and source-bound prior gates |

## Interfaces and ownership

### P2

P2 owns its operations read model/adapter, finite metrics integration, the
separate console page, project examples/tests and nearby guides. Existing P2
PostgreSQL v7 remains authoritative. No serving DDL, second queue, per-case process
or new execution authority is introduced. Native revision 0 stays read-only.

### P3

P3 owns the additive v2 policy types, handler/factual verification, public
consumers, shared data-only fixtures and project guides. Current v1 durable
execution and the image capability remain separate. Bound request/result/source
bytes, scope, permissions, deadlines and work ownership through the existing HTTP
contract.

### Root

Root owns shared documentation, harness/source discovery, command wiring,
independent protocol/oracle/evidence review, broad quality and the final
checkpoint.

- An independent preservation reviewer verifies prior evidence and protected P1
  inputs.
- Producers freeze exact cases, role environments, source inventories,
  resource/capture limits and cleanup contracts before normal measurement.
- PG/SFU lanes are serialized. No process may remove shared state before all its
  owned children and I/O settle.

## Failure cases and validation

| Gate | Applicable and why | Exact tests/assertions | Prerequisite/resource/time bound | Expected status/artifacts |
| --- | --- | --- | --- | --- |
| G-READY | Both substantial slices | Reviewed public interfaces, exact normal/fault/useful-progress inventory, authority and lifecycle contracts | Private preedit baseline plus producer protocols retained before normal execution | No normal gate before approved source/protocol freeze |
| G-FAST/G-CONTRACT | Public types, UI and shared discovery | Full Python/static/docs/types/format and frontend types/tests/format/build; positive/negative cross-language contracts | Frozen installed toolchain and locks; no providers | Zero required skips, missing checks or violations |
| P2 G-DURABLE/G-UI/G-OBS | Joined read model and actual transitions | Real durable rows, cursor/scope negatives, stale/unknown/error/recovery, bounded metrics and observer outages | Isolated local PostgreSQL, actual browser, fixed per-run limits in the approved producer protocol | Independently joined observations, safe screenshots and complete owned cleanup |
| P3 G-CONTRACT/G-OBS/G-PACKAGE | New versioned policy boundary | Positive/missing/conflicting/adversarial facts, invented rules/wrong values/source swaps, source/installed consumers and retained v1 behavior | Loopback HTTP with scripted synthetic sources; fixed per-run budgets in producer protocol | Separate structural/factual outcomes, useful progress and cleanup |
| Compatibility | Preserve qualified behavior | Source-bound affected P2/P3/native/package and ordinary doctor/smoke checks | Serial actual service lanes; exact old reports retained | No relabelled failures or unsupported release/media claims |
| Final handoff | Local POC scope | Independent API/evidence review, current source index, exact physical manifest, previous checkpoints and residual/M1 preservation | Private 0700 directories, regular owner-only 0600 single-link files, finite aggregate archive | Selected completion only after all required gates pass |

### Reviewed application build boundary

The optional page consumes P2 through its declared operations-types public
export. The console therefore declares one existing workspace dependency.

- Its frozen pnpm lock changes only the three-line console importer link. All
  third-party versions, integrities, package and snapshot sections remain
  byte-for-byte identical.
- This is an application dependency edge, not an external package or version
  upgrade.
- The original lock and exact delta are retained in private premeasurement
  evidence. An offline frozen install with scripts disabled verifies the new
  local link.

A separate tsconfig.operations.json checks the optional page.

- Default console compilation excludes those optional source files. It retains
  its existing build script and Dockerfile, whose build context contains the
  console without P2's dist.
- Explicit operations builds compile P2 first. Console test/type commands also
  prepare that public dependency.
- Generated operations output is excluded from Git and Docker contexts.
- No runtime alias or hidden checkout import replaces the package contract.
- Final preservation must identify the exact lock metadata delta, rather than
  claim the current lock is byte-identical to the prior checkpoint.

### Selected premeasurement limits

#### P2 study

The reviewed P2 study declares sixteen PostgreSQL/HTTP groups and three actual
browser groups in one browser case. Its bounds and the new endpoint limits:

| Limit | Value | Applies to |
| --- | --- | --- |
| Total ceiling | 240 seconds, with twenty reserved for cleanup | P2 study |
| Direct children | At most twenty-four | P2 study |
| Captures | 8,192 bytes per stream and 512 KiB aggregate | P2 study |
| Direct proof | 1 MiB per proof | P2 study |
| Retained artifacts | 16 MiB | P2 study |
| Report | 32 KiB | P2 study |
| Permitted bytes | 73,728 bytes: the unchanged 65,536-byte context plus at most 8,192 bytes of new framing | New context endpoint |
| Section cursors | Four signed cursors, individually bounded to 2,048 UTF-8 bytes and collectively subject to the frame bound | New context endpoint |
| Telemetry reply | At most 16,384 bytes | Separate volatile telemetry reply |

The application-configured cursor key/source identity survives restart; exact scoped
retained anchors, source and section must still validate. This does not change
the existing rehydration API or grant complete event-feed semantics.

#### P3 study

The reviewed P3 study declares twenty assertions, eight contract and twelve HTTP.

| Limit | Value | Applies to |
| --- | --- | --- |
| Total time | 120/360 seconds, with twenty reserved for cleanup | Source/installed modes |
| Direct children | At most thirty-two, including nested package commands | Both modes |
| Captures | 64 KiB per stream and 2 MiB aggregate | Both modes |
| Direct proofs/reports | 32 KiB | Both modes |

The new finite notice policy recognizes exactly version notice_v1, rule
notice_minimum_days and a seven-day threshold.

- Zero fact witnesses clarify as missing.
- Two distinct day values clarify as conflicting.
- One value, including two agreeing witnesses, is evaluated against seven days.
- All applicable witnesses are required.

Actual source/fact verification precedes returning an expired semantic
observation. The transport-only client explicitly separates correlation
validation from the full source verifier.

#### Shared rules

Producer protocols additionally freeze exact child argv/roles, stage chronology,
source closure, package payloads and proof schemas before normal execution. These
ceilings describe local tests, not latency or deployment-capacity promises.

- Use fixed safe event/operation/code/outcome labels and typed errors.
- Exclude credentials, bodies, prompts, image/policy contents and raw exception
  strings from logs and metrics.
- Record actual units/counts, and distinguish process-local gauges from durable
  totals or fleet capacity.
- Telemetry sink failure is contained.
- Preserve primary failures and unresolved owned work. A timeout or canceled
  waiter never proves that an external call, thread or child stopped.

## Results and handoff

Selected P2-I20 and standalone P3-I17 qualification passed. This completes the
selected phase, while the broader ecosystem and requested demo-video goal remain
active. Complete catalog registrations remain 24 of 55; all seventeen P2 and the
remaining fourteen P3 rows retain their full requirements.

| Check | Actual outcome | Interpretation |
| --- | --- | --- |
| P2 main | Sixteen PG/HTTP groups, three browser groups in one actual case, thirteen children; 13.779 seconds, complete cleanup | Actual pending/running/uncertain/dispatched observations, separate unknown ordinary send and delivered callback, read failure/recovery/Forget and fresh-process replay |
| P2 artifacts | Seven isolated npm stages; 105 payloads, strict NodeNext with no private PG declarations; offline 1.208 seconds and actual four stages 5.704 seconds | Original acceptance/replay and twelve actual operations reads per process, real metric producers and eight retained exporters through settlement |
| P2 compatibility | 187 assertions in eleven fresh serial lanes; 135.933 seconds, complete cleanup | Includes native six, playback three, required P2-I18 storage eighteen and rehydration media three; no prior report reused |
| P3 fixed policy | Twenty source and twenty isolated installed assertions; 6.727/66.082 seconds with six/twenty-seven children and complete cleanup | Independent structural/factual/source/wire joins; the nested eight offline package assertions (offline-eight) are counted separately |
| P3 compatibility | Image source 20 / installed 20, fresh offline artifact checks and 146 existing assertions in ten lanes; all passed | The maintained policy composition's 16 assertions are already included in 146; v1 defaults/bytes remain compatible |
| Shared quality | 2,370 Python and 1,439 TypeScript tests, zero required skips; broad/strict typing over 148/146 files, Python formatting over 414 files | All maintained lint, structural, frontend type/format/build checks passed |
| Documentation and diagrams | 117 maintained documents and 29 syntax-parsed design diagram bodies | Metadata/structure/syntax are checked separately from semantic design and code review |
| Preservation and cleanup | Original M1, P1's 77 runtime payloads, 50 default-service files and 47 legacy P2 runtime files, default/native UI, UV/images/Compose preserved | Exact reviewed pnpm importer-only metadata delta; no dependency version or image upgrade, no provider inference |

### Reviews and final probes

Independent reviews bind actual P2/P3 wires, sources, original receipts,
callbacks, physical retained files and owned resource settlement. Final read-only
probes observed no selected UUID test namespaces, selected SFU rooms or recorded
live process groups, and retained the original authenticated M1 result. Ordinary
stack checks passed eight checks and ten audio frames with inference disabled.

### Corrections

- The public telemetry adapter was corrected against actual producer emissions;
  source-specific finite causes remain distinct.
- Ownership placeholders precede observer/getter/thenable code, including
  reentrant close.
- Default and injected browser fetch run without an invalid client receiver.
- Meaningful controls failed before these fixes and passed after them.
- Cursor, scope, consent, byte and lifetime bounds were preserved.

### Retained evidence

Eight full owner snapshots retain all 29 inbox and two case tables in separate
canonical files of at most 1 MiB each, with exact hashes/bytes/table counts in a
manifest of at most 32 KiB. Aggregate retention remains 16 MiB. No rows or catalog
data were removed to fit a limit. The actual main run retained 57 indexed
artifacts plus its index, including all 25 direct proofs. Predecessor failed
attempts remain immutable. The separately approved exact recovery of one failed
test run did not rewrite that attempt's original incomplete-cleanup observation.

Packaged README prose was made qualification-neutral with exact before/after
reviews and archive equivalence. Fresh offline artifacts bind the current prose;
actual installed journeys retain their original archive scope. The only
additional foundation metadata discovers the new producer/lifetime test; no
catalog registration changed. Closing evidence binds the full current public
source census, ancestor/link safety, physical artifact set and prior sealed
checkpoint.

### Next scope

The next scope is P2-I21 full standalone consumption and P3-I18 responsive native
background work. Keep v2 standalone until its durable P3 consumer is coherently
versioned. Full release, integrated live-provider/model outcomes, a compact
portfolio UI and the final credential-free demo video remain separately gated.
