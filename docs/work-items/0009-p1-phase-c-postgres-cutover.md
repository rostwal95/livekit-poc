# P1 Phase C PostgreSQL cutover and scoped access

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the plan, observed verification and handoff for shared task S-I05 and P1 Phase C tasks P1-I08 through P1-I10 |
| Audience | Engineers changing P1 PostgreSQL cutover, roles or scoped access; coding agents |
| Scope | Controlled SQLite-to-PostgreSQL cutover, restricted runtime adapter, owner-only import and trusted actor scope; excludes rich workflow lifecycle, distributed leases and the UI |
| Owns | Change plan, observed verification and handoff for S-I05 and P1-I08 through P1-I10 |
| Related | [Work item 0008](0008-p1-phase-b-inquiry-recovery.md) · [Work item 0010](0010-p1-phase-d-authority-and-waits.md) · [PostgreSQL cutover decision](../decisions/0003-postgres-cutover-and-scope.md) · [P1 task plan](../implementation/p1-agent-continuity.md) · [Validation plan](../validation-plan.md) |

## Behavior and scope

Implement shared task S-I05 and P1 (Agent Continuity Lab) tasks P1-I08 through
P1-I10 from the [granular roadmap](../implementation-plan.md) after the completed
Phase B gate. Preserve the first SQLite crash demonstration, add a restricted
PostgreSQL runtime adapter and explicit owner-only import, and bind application
access to trusted synthetic actors. Rich workflow lifecycle, distributed leases
and the UI remain later phases.

### Criteria

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| Controlled cutover | Existing SQLite v1 intake, executions and attempts | Quiesce, back up, import, verify and activate PostgreSQL | Source closes writes durably; identifiers and exact payloads persist; no dual writes | Accepted work continues on PostgreSQL | Real stores and interrupted checkpoints |
| Runtime restriction | Separate bootstrap, migration and runtime roles | Serve reads/admission/attempt changes | Runtime cannot create/drop schemas, change migration state or assume owner | Existing adapter contract progresses | Actual PostgreSQL negative privilege tests |
| Actor scope | Trusted actor directory | Submit/read/history/cancel/signal | Request data grants no scope; inaccessible and unknown IDs match | Valid own-account inquiries progress | SQLite and PostgreSQL actor tests |
| Recovery | Worker or migrator stops at a named barrier | Restart explicitly | Stable effect and import receipt survive; no target overwrite after progress | One inquiry completes with original identity | Independent processes and retained evidence |

## Interfaces and ownership

| Component | Responsibility |
| --- | --- |
| Migration owner | Alone controls target staging and activation |
| SQLite v2 | Contains only the source cutover gate |
| Runtime adapter | Owns business rows, not schema |
| Session advisory lock | A cooperating single-worker slot, not a distributed lease |
| Read-only supplier | Retains independent SQLite state |

The bounded v1 inquiry contract remains unchanged. Source and target are not one
atomic database.

## Failure cases and validation

The gate names below are the engineering gates defined in the
[validation plan](../validation-plan.md#engineering-gates-and-acceptance-authoring).

| Gate | Requirement in this phase |
| --- | --- |
| G-READY | Requires Phase B |
| G-CONTRACT | Covers both adapters and scoped access |
| G-DURABLE | Covers backups, precommit rollback, committed acknowledgement loss, source and target checkpoints and independent worker crashes |
| G-OBS | Requires fixed safe codes and events without data source names (DSNs), secrets, SQL or exception text |
| G-FAST | Requires all unit, structural, lint, type, format and documentation checks |
| G-POSTGRES | The explicit real PostgreSQL lane must fail when setup is missing, with zero skipped requirements |

Rebuild the actual local image and run foundation smoke without resetting volumes.

## Results and handoff

Phase C is complete for S-I05 and P1-I08 through P1-I10. The first SQLite proof
remains available. PostgreSQL now supports the same bounded inquiry lifecycle. The
live console and API remain M1 intake (the original SQLite confirmed-investigation
intake) and transport diagnostics. No existing volume was reset or live M1
database cut over during verification.

### Observed gates

| Observed gate | Command or mode | Result |
| --- | --- | --- |
| Offline checks | `make check` | 353 offline Python tests passed with zero skips and no ResourceWarning; structural and documentation checks and Ruff passed |
| Typing | Mypy and strict boundary checks | 32 service and core files plus the strict process helper passed; the shared decoder and authorization boundary also passed strict checking |
| Formatting | `make format-check` | 79 files passed |
| Real PostgreSQL | `make postgres-check` | 49 real local PostgreSQL tests passed with zero failures, errors or skips: 20 adapter, scope, parity and worker tests, 19 schema, import and privilege tests and 10 cutover tests |
| Migration checkpoints | Controlled callbacks and independent child `os._exit` | All eight migration commit and failure checkpoints exercised |
| PostgreSQL setup | Retained-volume and fresh disposable setup | Both passed; fresh setup ran twice |
| Installed container | Rebuilt Linux container, from /tmp | 20 installed application modules matched host hashes |
| Stack smoke | Actual stack smoke | Passed dependency and authentication checks, original M1 replay and conflict, named dispatch, ordinary and full UTF-8 text and real audio-frame reception |
| Documentation | Documentation policy | 65 maintained files checked |
| Diagrams | Actual Mermaid syntax parsing | All 33 Design Mermaid diagrams passed, with a malformed negative fixture |
| Whitespace | Whitespace checks | Passed |
| Complete harness | Complete harness result | Correctly incomplete (exit 2): BASE-01 and P1-01 through P1-05 passed, and 49 product requirements remain unimplemented |

Observation details:

- Missing PostgreSQL setup or a missing required suite fails. Default unittest
  discovery now finds offline tests instead of returning zero.
- Migration checkpoint retries preserved original requests, payload bytes,
  timestamps, attempts, results and effect identities. Restoring the retained
  private v1 backup into a new isolated file was verified.
- Source quiescence rejects new M1 intake, enrollment and attempt writes inside
  their transactions. Reads, original replay and payload conflicts remain. An
  active cooperating worker blocks quiescence. No supplier call can start after
  the source gate closes. Invalid target text is rejected before quiescence.
- Final activation locks all business tables and rechecks the durable digest in
  the activation transaction. Raw data manipulation language (DML) corruption or
  contention prevents activation. A recorded source CUTOVER permits an explicit
  repaired retry. Matching completed receipts preserve legitimate target progress.
  A second destination is rejected without importing into or activating it.
- Real PostgreSQL worker process loss after supplier success recovers the same
  effect, leaves one logical inquiry and preserves the booking. Fixed-clock SQLite
  and PostgreSQL traces produce equal records, attempts and event and code output.
  Trusted actor guards reject cross-scope get, history, cancel and signal calls
  and forged scope inputs, while own-account work progresses. Cancel and signal
  remain unsupported.
- Fresh setup authenticated both roles with real TCP and Salted Challenge Response
  Authentication Mechanism (SCRAM) authentication, denied runtime CREATE, schema,
  table, TEMP, role and control writes, and ran the actual one-shot image schema
  command. It remained STAGING. Test containers and synthetic credential files
  were removed. Upgrade tests preserve existing secrets and owner labels.
  Credentials use private atomic replacement with ignored interruption artifacts.
- In the rebuilt container, a separate PostgreSQL worker completed, and terminal
  replay retained one attempt and inquiry and an unchanged booking. Required safe
  producer events were observed. Replaying cutover after that progress preserved
  it.
- The original pre-change M1 task ID was unchanged. No browser playback or model
  claim is inferred from native real-time communication (RTC) traffic.
- Remote CI is wired for PostgreSQL but not claimed run.
- Phase C provides migration, backend and scope evidence without premature P1-15
  or P1-17 registration or complete supported-platform or release registration.

### Review corrections

Independent implementation and review corrected integration logging and import
issues, backup foreign-key validation, final activation races, private backup
validation, destination binding, target text preflight, ignored credential
interruption files, safe malformed exception codes and shared persisted-row
validation. AI assisted implementation and separate infrastructure, store,
migration and authorization reviews.

### Evidence and next step

Retained evidence lives under `.local/validation/p1-phase-c`:

| Artifact | Content |
| --- | --- |
| `fast.txt` | Fast lane output |
| `postgres.txt` | Real PostgreSQL lane output |
| `postgres-gate.json` | Real PostgreSQL gate report |
| `strict-boundaries.txt` | Strict boundary type check output |
| `format.txt` | Format check output |
| `fresh-bootstrap.json` | Fresh disposable PostgreSQL setup result |
| `container-probe.json` | Installed container probe |
| `start.json` | Local stack start result |
| `smoke.json` | Stack smoke result |
| `deep.json` | Complete harness result |
| `documentation.json` | Documentation policy result |
| `mermaid.json` | Mermaid parse results |
| `source-manifest.json` | Tested working-tree source |
| `phase-gate.json` | Phase gate result |

The machine manifest identifies the tested working-tree source without source
identifiers in prose.

Next: P1 Phase D (P1-D), tasks P1-I11 and P1-I12: canonical case authority and
exact quote and confirmation validation on PostgreSQL. Durable waits, automatic
retries and deadlines, signals, cancellation, mutations, distributed leases,
outbox, conversation and UI adapters, product telemetry, an isolated SDK consumer,
and complete media, model and platform gates remain later work. Use the existing
granular roadmap rather than expanding the SQLite scheduler or claiming production
or multi-region capacity from this lab.
