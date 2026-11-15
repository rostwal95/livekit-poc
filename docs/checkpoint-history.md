# Checkpoint history

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Keep the per-slice qualification summaries, newest first, with links to the work items that own their evidence |
| Audience | Readers who want to know what each slice qualified and where its evidence lives |
| Scope | Selected P1, P2, P3 and joined-showcase checkpoints; excludes the current capability summary, which the root README owns |
| Owns | Historical per-slice qualification summaries that previously lived in the root README |
| Related | [Root README](../README.md) · [Documentation map](README.md#history) · [Granular roadmap](implementation-plan.md) · [Qualification gates](qualification-gates.md) |

This guide keeps the per-slice qualification summaries that previously lived in
the root README, newest first. It is for readers who want to know what each slice
qualified and where its evidence lives. The [root README](../README.md) owns the
current capability summary.

- Each linked work item owns the exact assertions, failures, artifacts and limits.
- The counts below are historical results at that checkpoint. They must be rerun
  when behavior or inputs change.
- Task IDs such as P2-I21 or P3-I18 refer to tasks in the
  [granular roadmap](implementation-plan.md), not acceptance IDs.
- The [documentation map](README.md#history) lists every work item, including
  0001 to 0028.

## Review findings, schema upgrades and landing page (0047)

The [0047 work item](work-items/0047-open-findings-schema-upgrades-and-landing.md)
adds:

- P1 v5 persisted retry pacing;
- P2 v9 operating indexes;
- the contained P2/P3/UI review fixes;
- the landing page.

It also repairs gate drift found on the way and records the P1 requalification on
v5. In that requalification, 20 of the 21 P1 deep-gate rows passed. P1-20 stays
open until it is rerun with `P1_PROVIDER_CA_BUNDLE` set to the approved
certificate authority (CA) bundle.

## Joined showcase, providers and demo (0046)

The [0046 work item](work-items/0046-joined-showcase-providers-and-demo.md) adds:

- the explicit provider_real mode for the joined showcase;
- the reliability fixes found while running it with real models;
- live captions;
- the recorded demo.

## Joined application composition (0045)

The active [0045 work item](work-items/0045-joined-native-channel-policy.md)
composes the qualified seams into one local application.

| Part | Responsibility |
| --- | --- |
| Python | Source listeners, public client construction, and bounded background discovery and execution |
| Node | Native/SMS intake, original source reads and result receipts |
| Private owner profile | Preserves stable configuration across normal restart |

## Original channel-input binding (0044)

| Gate | Result |
| --- | --- |
| Selected source gate | Fourteen actual assertions passed across sixteen owned process groups with complete cleanup |
| Separate package check | Validates built and installed public artifacts with explicit fake ports |

The source gate joins native and signed simulated-SMS input to original P1 work,
issued policy results and the current P2 receipt/read. See the
[origin work item](work-items/0044-origin-bound-channel-policy.md).

## Stable result delivery and return context (0043)

| Gate | Result |
| --- | --- |
| Receiver gate | Sixteen storage and four return assertions passed with real P1/P2 PostgreSQL, original-receipt reconciliation and populated backup/restore |
| Isolated consumers | Python and npm consumers were checked separately |

The [0043 work item](work-items/0043-stable-result-delivery-and-return-context.md)
records the individual outcomes and preserved failures.

## Native policy, standalone channel and fixed policy (0040 to 0042)

### Responsive native policy and compact demo (0042)

The [native policy handoff](work-items/0042-responsive-native-policy-and-compact-demo.md)
records responsive real-time communication (RTC) text and the compact optional
result view.

| Gate | Result |
| --- | --- |
| Backend/SDK and browser | Twelve backend/SDK assertions and three browser groups passed in both source and installed modes |
| Offline package | Eight separate offline package assertions passed |
| Shared checks | 2,590 Python and 1,580 TypeScript tests passed with zero required skips |

### Standalone channel and durable policy (0041)

The [standalone/durable-policy work item](work-items/0041-standalone-channel-and-durable-policy.md)
implements P2-I21's installed application and P3-I18's typed durable-v2
prerequisite.

| Project | Result |
| --- | --- |
| P2 | Twenty installed standalone assertions, six public-P1 adapter assertions and 187 compatibility assertions passed |
| P3 | Twelve source and twelve installed durable assertions, eight offline package assertions and 146 selected regressions passed |

### Operations UI and fixed-policy evidence (0040)

The [operations and policy handoff](work-items/0040-operations-ui-and-fixed-policy-evidence.md)
qualifies selected P2-I20/P3-I17. The operations page follows real durable
input/dispatch/reply/callback observations with bounded authenticated reads. P3
adds explicit policy-v2 evaluation from separate immutable policy/fact records.

| Project | Result |
| --- | --- |
| P2 | Sixteen PostgreSQL/HTTP groups, three browser groups, seven isolated npm stages and 187 compatibility assertions passed |
| P3 | Twenty source and twenty installed fixed-policy assertions and 146 compatibility assertions passed |

## Workloads and document capability (0039)

The [completed handoff](work-items/0039-bounded-channel-workloads-and-image-evidence.md)
implements two selected tasks:

| Task | Scope |
| --- | --- |
| P2-I19 | Seeded capacity/dormancy study |
| P3-I16 | Standalone `booking.extract_document` capability |

The capability uses a bounded scripted fixture provider, actual PNG guards and
separate structural/factual checks.

- It provides no optical character recognition (OCR), real vision inference or P1
  durable image execution.
- Shared gates passed 2,272 Python and 1,318 TypeScript tests with zero required
  skips.

## Case rehydration and standalone release (0038)

The [completed phase](work-items/0038-case-rehydration-and-standalone-release.md)
qualifies selected P2-I18 and P3-I15.

| Project | Result |
| --- | --- |
| P2 | Eighteen storage assertions, three actual media groups, the 111-test P2 Python distribution, seven npm consumer stages and 166 compatibility assertions |
| P3 | Eight offline plus eight installed assertions passed |

Native continuation of a fresh P1 revision-0 case still needs a coherent
versioned change before integrated release.

## Playback evidence and process recovery (0037)

The [handoff](work-items/0037-playback-evidence-and-process-recovery.md) records
two results:

| Area | Recorded result |
| --- | --- |
| Playback evidence | Generated text, software development kit (SDK) output and client playback reports stay separately inspectable, with exact-response interruption |
| Process recovery | Original issued work, results, delivery and action reconcile through existing P1 authority after process loss |

## Native input and deadlines (0036)

The [handoff](work-items/0036-native-input-and-deadline-cancellation.md) records:

| Task | Gate |
| --- | --- |
| P3-I13 | Eighteen-case deadline/cancellation gates |
| P2-I15/I16 | Six-group actual native gate: browser text, WAV committed voice, returned text/audio, v6 restore and complete cleanup, plus isolated Python and npm artifacts |

## Earlier P2/P3 phases (0029 to 0035)

| Work item | Selected scope |
| --- | --- |
| [0035](work-items/0035-send-policy-and-action-races.md) | P2-I14 explicit uncertain-send policy and P3-I12 protected revision/intent races |
| [0034](work-items/0034-callback-evidence-and-applicability-refresh.md) | P2-I13 authenticated callback evidence and P3-I11 applicability refresh/display retention |
| [0033](work-items/0033-outbound-replies-and-completion-processing.md) | P2-I12 outbound reply intents/reservations and P3-I10 gap-aware completion processing |
| [0032](work-items/0032-linked-confirmation-and-result-projections.md) | P2-I11 linked exact confirmation and P3-I09 resumable applicability metadata |
| [0031](work-items/0031-revision-routing-and-delegation-acceptance.md) | P2-I10 expected-revision routing and P3-I08 concurrent replay/conflict |
| [0030](work-items/0030-p2-agent-recovery-and-p3-completion.md) | P2-I09 owned scripted-worker recovery and P3-I07B first delivery and guarded action |
| [0029](work-items/0029-p2-gateway-and-p3-issued-execution.md) | P2 gateway and P3-I07A P1-issued execution |

## P1 qualification

| Capability | Status | Evidence |
| --- | --- | --- |
| P1 V1, the fixed first-version scope of P1 | Qualified: implemented and locally qualified with the explicitly selected provider_real v2 profile | [Phase H release work item](work-items/0019-p1-phase-h-release-qualification.md) |
| Optional local_real profile | Not qualified, under unchanged limits | [Local real-inference operations](local-real-inference.md) |

The Phase H release work item records the 20-case index, runtime/H2/PostgreSQL
gates, isolated host/Linux artifacts, shared quality and independent reviews.
