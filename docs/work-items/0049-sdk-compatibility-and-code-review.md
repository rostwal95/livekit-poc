# SDK compatibility and code review

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Review the three projects and joined application against their implementation contracts and installed SDK APIs |
| Audience | Engineers reviewing the POC and preparing its technical defence |
| Scope | P1, P2, P3 and their LiveKit integration boundaries; excludes expanding the fixed product scope |
| Owns | This audit's coverage, findings, intentional differences and observed validation |
| Related | [Previous code audit](0048-code-audit-fixes-and-documentation-cleanup.md) · [Portfolio scope](../portfolio-scope.md) · [Validation](../validation-plan.md) · [Technology baseline](../technology-baseline.md) |

## Behavior and scope

Review the three projects and joined application against their public contracts,
the frozen installed SDKs and official documentation. Reference examples do not
authorize changes to consent, scope or recovery rules.

This is an audit across existing requirements rather than a new implementation
task or acceptance registration. A demonstrated defect may receive a contained
fix with a failing-before/passing-after regression. Broader lifecycle findings
retain their own required implementation and qualification gates.

| Criterion | Given | When | Then: safety | Then: useful progress | Evidence |
| --- | --- | --- | --- | --- | --- |
| SDK compatibility | Frozen Agents and RTC dependencies | Inspect actual calls and run selected genuine SDK tests | Unsupported examples are not adopted | Supported session/tool paths still work | Static call inventory and selected offline SDK suites |
| Existing authority | P1/P2/P3 public boundaries | Compare tasks, context, data and cancellation | No tutorial shortcut bypasses exact confirmation or original identity | Retained accepted work remains recoverable | Source/test-body review and focused tests |
| Honest scope | Deferred SIP, RAG, graph, hardware and production scale | Compare requirements with implemented boundaries | Missing optional features are not labelled implemented or defective by default | Remaining implementation gaps are explicit | Scope and source review |
| Lifecycle | Existing shutdown, interruption and acknowledgement boundaries | Review actual owner transitions and prior open findings | Uncertainty and live resource ownership remain visible | Later work can progress under the stated contract | Reproductions or source schedules with exact limits |

## Interfaces and ownership

| Area | Review owner | Responsibility |
| --- | --- | --- |
| P1 | P1 reviewer | Durable state, execution, effects, leases and package API |
| P2 | P2 reviewer | Native input, dispatch, channel data, playback and current authorization |
| P3 | P3 reviewer | Native task baseline, specialist I/O, validation and result/action authority |
| Joined services, frontend and setup | Coordinator | SDK/session composition, frontend grants/data, lifecycle and topology |

The selected baseline is recorded in the machine audit artifacts. No dependency,
schema, provider or deployment change follows from resemblance to a reference example.
Machine evidence is retained under `output/academy-code-audit`.

## Failure cases and validation

| Gate | Applicability | Planned evidence | Limits |
| --- | --- | --- | --- |
| G-READY | Audit scope | Read repository/area instructions, prior findings and current contracts | A source scan is not a release gate |
| G-CONTRACT | SDK integration | Selected actual SDK tests and signature checks | Does not establish browser media or provider quality |
| G-FAST | Any contained source fix or shared changes | Focused regressions, then shared fast checks | Missing setup, skips and timeouts remain non-passing |
| G-DURABLE | Any persisted-state repair | Existing actual PostgreSQL/process lane | Not replaced with a fake store |
| G-OBS | Telemetry and diagnostics | Numeric units, finite labels, privacy and closure review | A configured exporter is not inspected export |
| Media/provider gates | Only when affected implementation changes | Named actual lane from its owning work item | No provider invocation without explicit opt-in |

Start with narrow offline tests. Coordinate broad suites serially to avoid host
contention. Do not read private provider values, reset state or run serving DDL.

## Results and handoff

The audit inspected the three projects and joined application. The source
ledgers distinguish complete reads, selected bodies and
inventory-only coverage. The selected SDK call shapes agree with the installed
baseline; this is not a formal proof that every path is defect-free or a claim
that optional reference features belong in this POC.

### Repaired findings

| Finding | Repair | Evidence and boundary |
| --- | --- | --- |
| Failed P2 native close permanently cached its failed task | A later public close can retry a definitively failed attempt; pending/successful owners remain shared | The existing genuine-SDK regression no longer repairs a private field; it verifies concurrent retry and cancelled-waiter ownership |
| P3 native tool became stuck after definite initial capacity rejection | Reset its attempted flag only when the initial submit returns definite capacity; preserve frozen identity | Positive recovery plus unknown-ACK and post-acceptance capacity negatives; public coordinator with in-memory authority/specialist fixtures |
| Older P1 diagnostics could replace success or the primary failure | Contain ordinary logger failures in eight helpers and protect both inquiry error-code getters | Four regressions observed failing before their corresponding fixes; nineteen inquiry tests pass; fatal control flow remains observable |
| Provider prompt equated a noncurrent result with running work | Ask for a neutral no-current-answer response without inventing execution progress | Thirteen offline provider-mode tests pass; live model compliance is not established |

The root README now describes original-identity dispatch/reconciliation instead
of transport exactly-once execution. Seven existing documents were brought into
the current card/table format without advancing historical capability status.
The actual document fixture test now resolves the selected absolute Node
executable instead of assuming a particular Homebrew cellar path. Exact-version
fixture guards remain unchanged.

### Observed validation

The host had Node 24.22.3, while specialist fixtures require the retained 24.22.2
qualification baseline. An official temporary 24.22.2 distribution was verified
against its published checksum and used for the final runs. The system runtime
and repository pins were not changed. Exact executable paths, checksums, commands
and failed-run artifacts are recorded under `output/academy-code-audit`.

| Check | Command | Observed result | What it establishes |
| --- | --- | --- | --- |
| Complete fast lane | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh` with the verified Node on PATH and local networking | Passed: 49 P1, 125 P2, 453 P3 and 3,170 root tests; zero skips | Existing offline Python, structure and contract assertions; root cleanup completed |
| TypeScript packages | `pnpm test` with the verified Node and local networking | Passed: console 729, channel 905, specialist 188, gateway 234 | Existing package tests; not a browser/media qualification |
| TypeScript types | `pnpm check` | Passed | Four package type-check selections |
| Python types | `make typecheck` | Passed: 194 standard and 221 strict-selection files, with overlap | Maintained typing checks |
| Python formatting | `make format-check` | Passed: 568 files | Maintained format selection |
| Python lint | `.venv/bin/ruff check` over runtime sources and changed tests | Passed | Runtime/changed-test lint selection |
| Documentation | `.venv/bin/python -m harness.documentation_check` | Passed: 136 documents, zero violations | Corpus shape, tables and links under the current policy |
| Selected SDK signatures | `.venv/bin/python output/academy-code-audit/check_sdk_calls.py` | 209 Python files parsed, 51 recognized constructors checked, 21 event sites inventoried; no unexpected keyword found | Selected call shapes only; separate review/tests establish semantics |
| Fresh PostgreSQL and browser/media | Existing affected real lanes | Not run: Docker daemon unavailable | No fresh durable/media qualification claimed |
| Live providers | Existing explicit provider gate | Not run; no provider keys read or calls made | No fresh provider or model-quality qualification claimed |

Initial failures were retained and diagnosed: localhost sandbox denial,
documentation prerequisites, the exact Node version and the hardcoded test
executable. None was silently reclassified as passing or bypassed by weakening a
required assertion.

### Remaining work and interpretation

The table below retains this audit's handoff assessment. The subsequent
[lifecycle repair](0050-lifecycle-drain-and-documentation-cleanup.md) implements
GW-A1, GW-A2 and DEMO-A6 and records its separate regression, PostgreSQL and
scripted joined observations. It does not retroactively change this audit's
test results or complete the remaining joined release gates.

| Item | Current assessment | Next bounded step |
| --- | --- | --- |
| GW-A1 | Previously verified high-severity shutdown ordering remains | Fence/drain gateway dispatch before its Parent endpoints close; qualify actual persisted/process recovery |
| GW-A2 | Previously recorded high-severity, medium-confidence final-input race remains | Define room admission/drain ordering and reproduce the last accepted input with actual store/process/media evidence |
| DEMO-A6 | Larger cleanup budget/observation mismatch remains | Reconcile launcher, Parent, room and provider deadlines while retaining actual owners |
| P1-A2 | Post-reservation outages do not all receive persisted retry pacing | Preserve uncertainty while designing a separately qualified pacing extension |
| Model evaluation | Deterministic and genuine-SDK tests do not measure general model quality | Add a declared representative quality lane with calibrated judgments and independent business truth |

Manual turns, disabled competing SDK intake/SessionHost, durable work outside the
conversation and exact controller confirmation are deliberate boundaries, not
incompatibilities to remove. SIP service, general voice RAG, graph/MCP execution,
avatars, hardware and production failover remain outside the fixed implementation
scope. Scoped cross-principal specialist result/cancel grants are intentionally
tested delegation, not an unauthenticated bypass.

The prior book keeps its recorded source snapshot. The audit report includes a
crosswalk for its unchanged literal excerpts whose physical line numbers moved.
These fixes remain local and uncommitted. Prior selected qualifications are
historical; this audit does not complete the remaining P2/P3 acceptance or release
gates.

This work used parallel AI-assisted source review. The coordinator checked the
reported defects, reviewed the fixes, diagnosed validation prerequisites and ran
the final aggregate checks. The owner should claim personal contributions only
to the extent they can explain and reproduce them.
