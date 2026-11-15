# Harness coding agent instructions

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Give coding agents the reading order, owned paths, rules and checks for harness changes |
| Audience | Coding agents and engineers changing harness configuration, runners, scripts or their tests |
| Scope | Harness engine, configuration, runners, evidence rules and gate selectors; excludes product SDK packages |
| Owns | Harness agent reading order, owned paths, development rules and verification |
| Related | [Root instructions](../AGENTS.md) · [Harness guide](README.md) · [Harness design](Design.md) · [Validation plan](../docs/validation-plan.md) · [Documentation standards](../docs/documentation-standards.md) |

## Read first

Read these documents:

| Document | Why read it |
| --- | --- |
| [Root instructions](../AGENTS.md) | Follow first: repository-wide reading order, rules and verification |
| [README.md](README.md) | Implemented harness command-line interface and its exact commands |
| [Design.md](Design.md) | Structural and behavioral planes, runners and recorded evidence |
| [Validation plan](../docs/validation-plan.md) | Test lanes, required fault scenarios, benchmarks and evidence |
| [Documentation standard](../docs/documentation-standards.md) | Document card, role sections, tables and the documentation checks |

Contents: Development rules cover the engine, configuration, foundation policy,
runners and evidence, inference modes, then each phase gate. Verification lists
commands and recorded gate results.

## Owned paths

| Area | Responsibility |
| --- | --- |
| Harness configuration/runners, scripts and their tests | Owned here as repository tooling, separate from product SDK packages |
| Documentation manifest | Defines its corpus |
| Product module contracts and the separate `foundation.json` policy | Define implementation ownership |
| Infrastructure | Remains outside the three product acceptance namespaces |

## Development rules

### Engine, fixtures and offline checks

- Keep the structural/acceptance engine dependency-free.
- The full fast test lane uses the repository's already installed frozen dependencies.
- Offline checks must not install packages, call providers or mutate product state.
- Separate structural checks from actual behavior.
- Missing tests, required skips, timeouts and missing implementations are non-passing.
- Every rule/runner needs valid and deliberately invalid fixtures.

### Configuration and subprocesses

- Validate configuration shape, duplicate keys, scopes and safe paths.
- Use argv arrays, explicit working directories and bounded subprocesses.
- Preserve original failures and useful diagnostics without dumping environments
  or credentials.

### Foundation policy and change scope

- The mandatory foundation policy must fail closed if removed or malformed.
- Protect its entrypoints, source ownership and import rules with positive/negative
  fixtures, including a focused check against an unrelated product.
- Keep required architecture decisions in the audited documentation corpus.
- Unknown change ownership falls back to full scope.

### Runners, modes and time budgets

- Add language/browser/container runners only when their actual commands and
  prerequisites exist.
- Keep runner kinds explicit:
  - `unittest_discovery`/`python_json_report` retain a 300-second catalog maximum.
  - `python_infrastructure_report` permits at most 900 seconds and only lab/live modes.
- P1-14/P1-18 are lab.
- P1-20 is live with the trusted local_real or provider_real profile.
- Only provider_real needs external provider keys.
- Hosted deployment is not required.
- Report case and mode must exactly match the catalog.
- Never relabel another mode's artifact.
- Preserve the infrastructure wrapper's original 840-second deadline and browser
  600-second work/180-second cleanup budgets.
- Chunked observations do not reset the deadline.

### Fresh evidence and child capture

- Require fresh owned paths, source/input provenance, actual assertions and cleanup.
- Stale Phase G/H reports, health, zero tests, skips or timeout cannot pass.
- Both report kinds keep raw child capture private, byte-bounded and ephemeral.

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

### P1-20 real profiles

- P1-20 stays live for either selected real profile.
- Default local_real is preserved.
- provider_real requires the trusted `P1_ACCEPTANCE_REAL_PROFILE` selector and its
  reviewed versioned workload.
- Require fresh numeric usage, raw sanitized OpenTelemetry Protocol (OTLP) pairs,
  actual browser progress, independent durable truth and owned cleanup.
- Provider CPU/memory remain unobserved.

### P3 lab registrations and planned rows

- P3-01/P3-03/P3-11 are selected lab `python_json_report` registrations, not P3 release.
- Their fixed child inventories are 13/8/12 assertions.
- Preserve fresh owned component paths, exact mode/case/count and stdout/file
  equality, contained child credentials, real process/store assertions and cleanup.
- Seventeen P2/fourteen P3 rows remain planned.
- Never make a partial product aggregate pass by omitting them.

### Native input and deadline gates

Read the [completed handoff](../docs/work-items/0036-native-input-and-deadline-cancellation.md)
before changing these native/deadline gate selectors.

#### Native input gates

- Keep the native inventory at six actual browser groups.
- SDK/store/expiry assertions are separate and do not invent additional browser tests.
- Reject missing media, skipped assertions, unsafe captures, wrong roles and
  incomplete cleanup.

#### P3-I13 deadline gates

- Preserve clock-after-admission eligibility, one owned post-late-commit kill and
  three bounded direct proof joins.
- The ignoring peer is an explicit test fault.
- Never claim remote stop, human consent, default deployment or full charter release.
- Keep all previously closed checkpoints, exact child/report schemas and actual I/O
  ownership.
- The shared validation/observability guides own evidence and producer fields.

### Linked-confirmation and projection gates

- For linked-confirmation/projection changes, retain separate selected P2/P3 reports.
- Require exact named cases, source-bound fresh reports and owned cleanup.
- The work v4 feed is generic result history.
- P3 metadata/checkpoints must not become another execution queue.
- Preserve existing booking/provider gate provenance and all 24 catalog registrations.
- New partial assertions cannot register a complete row.

### Outbox and processing gates (phase 0033)

These rules cover the outbox/processing gates recorded in
[work item 0033](../docs/work-items/0033-outbound-replies-and-completion-processing.md).

- Keep producer acceptance, possible send, provider evidence and terminal processing
  acknowledgement (ACK) distinct.
- Require actual PID-owned barriers and exact frozen child inventories.
- Unknown possible calls cannot become automatic retries.
- Processing discovery cannot silently acknowledge a gap.
- P1 remains unchanged. Preserve all 77 source payloads and prior evidence.
- Keep broader resend/media/release scope and every planned charter row non-passing.

### Send-policy and action-race gates (phase 0035)

- Preserve the completed callback/applicability checkpoint.
- P2 requires 30 named actual assertions, including populated inbox v4-to-v5
  migration/restore, ordinary unknown holds, cooperating same-key retries, callback
  ordering and independent provider ledgers.
- P3 freezes 16 cases/31 one-time modes, three owned PID kills and two actual
  two-waiter SQL order graphs.
- The P3 gate's bounds are 180 seconds total/15 cleanup, at most 32 children,
  128 KiB aggregate capture, 2 KiB per stream and a 32 KiB final report.
- Prewarm both writers and the same owner locker/observer before lock contention.
- Never change P1's lock timeout.
- Validate exact keys and JSON primitive types, first-failure precedence,
  role-separated environments and complete cleanup.
- Optional diagnostic runs retain only bounded redacted failure streams and always
  remain non-qualifying.
- No complete charter registration or P1/P3 runtime change is introduced.
- Physical delivery/human ACK remains distinct from provider evidence.

### Workload contracts (Phase H1)

- The H1 workload model and versioned manifests are dependency-free tooling.
- Reject unknown/duplicate fields, unsafe paths and unbounded or nonfinite values
  before execution.
- Keep the manifest immutable through a run and retain its canonical digest.
- Separate declared schedules/budgets from actual samples, and client-observed
  latency from supplier completion.
- Never synthesize missing resource data or report unsupported small-sample percentiles.
- New models stay in maintained typing and adversarial fixture discovery.

### Operations and fixed-policy evidence

- Read the [completed 0040 handoff](../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md).
- Require closed source/role/case/proof inventories, actual producer and lifetime
  controls, original durable joins and isolated artifacts.
- Preserve every complete snapshot row in bounded per-phase files.
- The manifest and physical index bind all bytes.
- Source index membership must be recounted at final seal.
- Intermediate linked ancestors are unsafe even when the leaf looks regular and private.
- These selected tasks add no complete catalog registration.
- Keep twelve backend assertions, three browser groups and eight separate installed
  package assertions distinct.
- Full charter, combined voice/SMS and video remain active work.
- Do not register a complete acceptance row from these partial slices.

## Verification

From the repository root:

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m harness.documentation_check
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh
.venv/bin/ruff check harness/static_check.py tests/test_harness_static.py
```

| Check | Command | When to run |
| --- | --- | --- |
| Root unit tests | `.venv/bin/python -m unittest discover -s tests -v` | Harness changes |
| Documentation checks | `.venv/bin/python -m harness.documentation_check` | Harness changes |
| Full fast validation | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh` | Harness changes, including shared rule, config, runner or instruction changes |
| Static checker lint | `.venv/bin/ruff check harness/static_check.py tests/test_harness_static.py` | Harness changes |

The table indexes these checks; the rules below it remain authoritative.

- Shared rule, config, runner or instruction changes require full fast validation.
- Do not weaken existing fixtures to accept a newly introduced violation.

### Recorded selected qualification

- Native input gates: selected actual native and installed Python/npm package gates
  passed. Final selected phase regression/shared gates and the affected media rerun
  passed.
- P3-I13 deadline gates: source/installed eighteen-case and forty-six compatibility
  assertions passed.
- Phase 0033 outbox and processing gates: selected local qualification passed.
  Actual 24-case P2 and 16-case P3 gates, isolated installed consumers and old
  regression lanes retain exact reports.
- Phase 0035: the [completed send-policy/action-race phase](../docs/work-items/0035-send-policy-and-action-races.md)
  completed the selected local gates for P2-I14 and P3-I12. Actual, isolated
  installed and prior regression gates passed for this slice. Require them after
  affected changes.
- Selected P2-I21/P3-I18A qualification passed in 0041 and P3-I18B RTC text in
  [0042](../docs/work-items/0042-responsive-native-policy-and-compact-demo.md).

## Handoff

- Record affected IDs/rules, fixture coverage, exact commands, result and limits.
- Keep planned behavior explicit.
- Update the harness guide with CLI changes.
