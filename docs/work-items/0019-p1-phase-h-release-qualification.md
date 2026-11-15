# P1 Phase H release qualification

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the final P1 V1 release qualification for the selected `provider_real` v2 local scope |
| Audience | Reviewers assessing P1 release evidence; engineers rerunning affected P1 gates; coding agents |
| Scope | Tasks P1-I26 to P1-I28 and all twenty registered P1 reports; excludes `local_real`, P2/P3 and remote CI |
| Owns | P1 release-qualification evidence, index provenance and handoff |
| Related | [P1 charter](../projects/agent-continuity-scope.md) · [P1 task plan](../implementation/p1-agent-continuity.md) · [Provider work item](0018-p1-provider-demo.md) · [Provider operations guide](../provider-demo.md) |

## Behavior and scope

P1's registered runtime gates passed on the final catalog-batched source:

- P1-18 reliability;
- P1-14 scripted controls;
- P1-20 media with the `provider_real` v2 profile.

The complete four-case Phase H2 restart and slow-supplier workload (H2) and the
real PostgreSQL correctness suite passed. The final source-matching artifact,
shared-quality and independent-index gates also passed. Together they complete
the selected `provider_real` v2 local scope of P1 V1, the fixed version-1 project
scope. The optional `local_real` profile remains unqualified. P2 and P3 remain
planned. Remote continuous integration (CI) and publication are outside the
completion requirements of this local proof of concept (POC).

| Criterion | Required safety | Required useful progression | Evidence owner |
| --- | --- | --- | --- |
| P1-I26 | Typed installed API without checkout injection; M1 (original confirmed-investigation intake) compatibility preserved | Host direct wheel, source distribution (sdist) and rebuilt wheel, and independent Linux consumers | Source-matching artifact reports and independent package/API review |
| P1-I27 reliability | No lost accepted work, incorrect duplicate effect or false cancellation | All accepted inquiries and receiver events reconcile after declared crash/shutdown faults | Full four-case current H2 plus registered P1-18 |
| P1-I27/I28 and P1-20 | Native-only keys, signed scope and separate exact human consent | Actual inference/playback, End/fresh consumer and responsive held-dependency controls | Two actual browser cases, numeric software development kit (SDK) records and sanitized raw OpenTelemetry Protocol (OTLP) data |
| Release | Nonzero assertions, zero required skips, current source/input bindings and cleanup | One reviewable handoff for all twenty P1 rows | Final quality, explicit reviewed reports and independent release index |

## Interfaces and ownership

### Owning documents

| Document | Owns |
| --- | --- |
| [Charter](../projects/agent-continuity-scope.md) | Acceptance IDs P1-01 through P1-20 |
| [Task plan](../implementation/p1-agent-continuity.md#phase-p1-h-reusable-artifact-and-release-proof) | Sequencing of tasks P1-I26, P1-I27 and P1-I28 |
| [Provider work item](0018-p1-provider-demo.md) | Provider configuration and media results |
| The provider work item's [operations guide](../provider-demo.md) | Private credentials, explicit trust and lifecycle commands |

### Runtime boundaries

The reviewed v2 workload selects nova-3, gpt-5.4-mini and eleven_v4_turbo with the
same original schedule, caps and authority assertions. Native tools only submit,
inspect and request cancellation. Exact quote approval belongs to the protected
authenticated controller. The image builds frozen, non-editable installed
bytecode.

Worker ready-pull and cooperative quiescence preserve:

- one-child and lease ownership;
- sticky shutdown;
- original admission limits;
- the unchanged recovery clock.

Fresh catalog batching retains every schema, role, access control list (ACL),
index and constraint check on each connection and after admission locking. No
cache or dropped check exists.

## Failure cases and validation

Gate names starting with G- refer to the engineering gates in the
[validation plan](../validation-plan.md). G-SCRIPTED and G-MODEL are specific to
this work item.

| Gate | Exact requirement | Acceptance and evidence boundary |
| --- | --- | --- |
| G-SCRIPTED | Six actual browser cases plus three PostgreSQL postcommit assertions | Fresh P1-14 lab report, current source/driver and cleanup |
| G-DURABLE/OBS | All four original fault schedules, deadlines, process lifetimes/exit/drain checks and positive resource epochs | Fresh complete H2 and separate registered P1-18; fragments from different runs cannot be combined |
| G-MODEL/MEDIA | Both browser cases, positive automatic speech recognition (ASR)/token/text-to-speech (TTS) usage, exact model/provider pairs, durable truth and exact approval | Fresh provider_real v2 P1-20 live report and independently reviewed raw observations |
| G-PACKAGE | All 58 source payloads, metadata and three archives; three host virtual environments (venvs) and two Linux consumers | Source-matching package proof; Linux has no network/source mount and binds the exact host report/wheel |
| G-FAST/CONTRACT | Python/frontend/type/lint/format/docs/Mermaid checks after the final change | Actual nonzero counts and zero required skips; no remote-CI prerequisite |
| G-RELEASE | All twenty passing registered reports with honest provenance scope | Explicit paths/hashes, current runtime/artifacts, historical baselines and independent index review |

Resource-heavy runs are serialized. The explicit provider selector and the
optional approved certificate authority (CA) follow the operations guide.
Presence or health, a configured badge or a single intermediate tool response
cannot qualify a whole scenario. Retain failed runs unchanged. Business outcome,
cancellation receipt, receiver delivery and human acknowledgement remain separate.
Logs, metrics and traces retain only bounded safe fields. External-provider
resources and monetary billing are unobserved.

## Results and handoff

### Final evidence

| Final evidence | Result | Scope |
| --- | --- | --- |
| PostgreSQL correctness | 263 tests passed, zero failures/errors/skips, 437.093 seconds | Actual PostgreSQL; fresh schema validation and all prior predicates preserved |
| Current full H2 | Four cases passed, 162.589 seconds, 1,125 raw observations and cleanup | 128 offers = 32 accepted + 96 rejected; 32 results/receiver events; zero lost/apply/mutations; current 64 core/API files; independent audit passed |
| P1-18 | One assertion passed, zero skips, 30.185 seconds and cleanup | Fresh registered saturation/drain case under original bounds |
| P1-14 | Nine assertions passed, zero skips, 112.113 seconds and cleanup | Six actual scripted browser cases plus three PostgreSQL postcommit checks |
| P1-20 | Two actual browser cases passed, zero skips, 113.567 seconds and cleanup | Explicit provider_real v2; real recognition/tools/TTS/playback, End/fresh consumer, slow-dependency controls and exact confirmation |
| Final host/Linux package | Passed: 58 current payload files and metadata across three archives; 18 commands/three host venvs; two isolated Linux consumers, exact host/wheel binding and cleanup | Current 58-file payload, metadata/three archives and exact isolated-consumer binding |
| Final shared quality | Passed: 1,100 Python tests (21 package + 1,079 root), zero skips; 326 frontend tests/seven files plus app/end-to-end (E2E) types/build; structural zero violations, Ruff, 88 maintained/28 strict typing sources and formatting for 222 Python files | Actual final Python/frontend/types/lint/format/docs/Mermaid results |
| Default stack refresh/smoke | Passed: eight transport/authentication/M1/dispatch/text/audio checks and ten audio frames; original M1 identity preserved | Transport/M1 proof, separate from the provider gate |
| Independent release index | Passed: unchanged v3 auditor index_verified for all 20 P1 cases; current runtime/package/source/input bindings and independent raw-provider/H2/control reviews verified | All twenty reports, current runtime/artifacts and explicit historical/source scope |

### Provider run details

The provider run recorded four numeric SDK reports with 3,645 input and 97 output
tokens, 4.3 ASR seconds and 12.24 generated-TTS seconds. Those are aggregate usage observations. The retained
native trace includes the submit and get tools and all three exact model/provider
pairs. Independent raw review passed with the final index.

The eight-inquiry cohort preserved and replayed identities through End. It
reconciled results, explicit cleanup cancellations, receiver delivery and nine
supplier receipts. One separate exact approval produced the authorized foreground
mutation.

### Traces, cleanup and resource limits

The bounded retained API query contains 100 traces and one failed
`continuity.get` span of unresolved cause. Retained native and worker queries
contain no error spans. This supports neither global zero errors nor complete API
trace history.

Per-run live-check state, private process logs, temporary credential env files and
copied CA snapshots were cleaned after producer inspection and owned-container
cleanup. The user's ignored `.env.providers` file and the original approved public
CA bundle remain intact. Independent review revalidated retained projections
without reading secrets or requerying services. Memory and lifetime peaks
accounted by Linux control groups (cgroups) include setup and measurement. They
are not isolated-model resident set size (RSS).

### Release index provenance

The index uses explicit reviewed paths and hashes and never selects a latest run.
Legacy deterministic and PostgreSQL reports preserve their original
observed-command scope. Current runtime reports bind their exact source, input,
driver and raw artifacts. The Phase H1 inquiry workload baseline (H1) and earlier
H2 and package checkpoints remain historical measurements of their own source
snapshots. A failed fault setup is not evidence of a crash-recovery defect, and no
failed artifact is relabelled. Local resource samples establish the declared
workload bounds without claiming production capacity or a stable speed
improvement.

### Completion

These results complete tasks P1-I26, P1-I27 and P1-I28 and the selected
`provider_real` v2 local V1 release assessment. Both work items, this one and the
[provider work item](0018-p1-provider-demo.md), are completed. Affected gates must
be repeated after subsequent code or input changes. The selected provider-real POC
remains distinct from the unqualified local-engine profile, from hardware
capture, hearing and model quality, and from the planned P2 and P3 projects.
