# P1 Phase C PostgreSQL cutover and scoped access

Status: Completed
Last reviewed: 9 November 2026

## Behavior and scope

Implement S-I05 and P1-I08 through P1-I10 after the completed Phase B gate.
Preserve the first SQLite crash demonstration, add a restricted PostgreSQL runtime
adapter and explicit owner-only import, and bind application access to trusted
synthetic actors. Rich workflow lifecycle, distributed leases and the UI remain
later phases.

| Criterion | Given | When | Safety | Useful progress | Evidence |
| --- | --- | --- | --- | --- | --- |
| Controlled cutover | Existing SQLite v1 intake, executions and attempts | Quiesce, back up, import, verify and activate PostgreSQL | Source closes writes durably; identifiers and exact payloads persist; no dual writes | Accepted work continues on PostgreSQL | Real stores and interrupted checkpoints |
| Runtime restriction | Separate bootstrap, migration and runtime roles | Serve reads/admission/attempt changes | Runtime cannot create/drop schemas, change migration state or assume owner | Existing adapter contract progresses | Actual PostgreSQL negative privilege tests |
| Actor scope | Trusted actor directory | Submit/read/history/cancel/signal | Request data grants no scope; inaccessible and unknown IDs match | Valid own-account inquiries progress | SQLite and PostgreSQL actor tests |
| Recovery | Worker or migrator stops at a named barrier | Restart explicitly | Stable effect and import receipt survive; no target overwrite after progress | One inquiry completes with original identity | Independent processes and retained evidence |

## Interfaces and ownership

The migration owner alone controls target staging/activation. SQLite v2 contains
only the source cutover gate; the bounded v1 inquiry contract remains unchanged.
The runtime adapter owns business rows, not schema. A session advisory lock is a
cooperating single-worker slot, not a distributed lease. The read-only supplier
retains independent SQLite state. Source and target are not one atomic database.

## Failure cases and validation

G-READY requires Phase B. G-CONTRACT covers both adapters and scoped access.
G-DURABLE covers backups, precommit rollback, committed acknowledgement loss,
source/target checkpoints and independent worker crashes. G-OBS requires fixed
safe codes/events without DSNs, secrets, SQL or exception text. G-FAST requires
all unit, structural, lint, type, format and documentation checks. The explicit
G-POSTGRES lane must fail when setup is missing, with zero skipped requirements.
Rebuild the actual local image and run foundation smoke without resetting volumes.

## Results and handoff

Phase C is complete for S-I05 and P1-I08 through P1-I10. The first SQLite proof
remains available; PostgreSQL now supports the same bounded inquiry lifecycle.
The live console/API remains M1 intake and transport diagnostics. No existing
volume was reset or live M1 database cut over during verification.

Observed verification:

- make check passed 353 offline Python tests with zero skips and no
  ResourceWarning. Structural/documentation checks and Ruff passed. Mypy passed
  32 service/core files plus the strict process helper; the shared decoder and
  authorization boundary also passed strict checking. make format-check passed
  for 79 files.
- make postgres-check passed 49 real local PostgreSQL tests with zero failures,
  errors or skips: 20 adapter/scope/parity/worker tests, 19 schema/import/privilege
  tests and 10 cutover tests. Missing setup or a missing required suite fails.
  Default unittest discovery now finds offline tests instead of returning zero.
- All eight migration commit/failure checkpoints were exercised with controlled
  callbacks and independent child os._exit. Retry preserved original requests,
  payload bytes, timestamps, attempts, results and effect identities. Restoring
  the retained private v1 backup into a new isolated file was verified.
- Source quiescence rejects new M1 intake, enrollment and attempt writes inside
  their transactions; reads, original replay and payload conflicts remain. An
  active cooperating worker blocks quiescence. No supplier call can start after
  the source gate closes. Invalid target text is rejected before quiescence.
- Final activation locks all business tables and rechecks the durable digest in
  the activation transaction. Raw DML corruption/contention prevents activation;
  recorded source CUTOVER permits an explicit repaired retry. Matching completed
  receipts preserve legitimate target progress. A second destination is rejected
  without importing into or activating it.
- Real PostgreSQL worker process loss after supplier success recovers the same
  effect, leaves one logical inquiry and preserves the booking. Fixed-clock
  SQLite/PostgreSQL traces produce equal records, attempts and event/code output.
  Trusted actor guards reject cross-scope get/history/cancel/signal and forged
  scope inputs while own-account work progresses. Cancel/signal remain unsupported.
- Both retained-volume and fresh disposable PostgreSQL setup passed. Fresh setup
  ran twice, authenticated both roles with real TCP/SCRAM, denied runtime
  CREATE/schema/table/TEMP/role/control writes and ran the actual one-shot image
  schema command. It remained STAGING. Test containers and synthetic credential
  files were removed. Upgrade tests preserve existing secrets/owner labels;
  credentials use private atomic replacement with ignored interruption artifacts.
- From /tmp in the rebuilt Linux container, 20 installed application modules
  matched host hashes. A separate PostgreSQL worker completed and terminal replay
  retained one attempt/inquiry and unchanged booking. Required safe producer
  events were observed. Replaying cutover after that progress preserved it.
- Actual stack smoke passed dependency/authentication, original M1 replay/conflict,
  named dispatch, ordinary/full UTF-8 text and real audio-frame reception. The
  original pre-change M1 task ID was unchanged. No browser playback/model claim
  is inferred from native RTC traffic.
- Documentation policy checked 65 maintained files; all 33 Design Mermaid
  diagrams passed actual syntax parsing with a malformed negative fixture.
  Whitespace checks passed. Remote CI is wired for PostgreSQL but not claimed run.
- Complete harness remains correctly incomplete, exit 2: BASE-01 and P1-01 through
  P1-05 passed; 49 product requirements remain unimplemented. Phase C provides
  migration/backend/scope evidence without premature P1-15/P1-17 or complete
  supported-platform/release registration.

Independent implementation/review corrected integration logging/import issues,
backup foreign-key validation, final activation races, private backup validation,
destination binding, target text preflight, ignored credential interruption files,
safe malformed exception codes and shared persisted-row validation. AI assisted
implementation and separate infrastructure/store/migration/authorization reviews.

Retained evidence lives under .local/validation/p1-phase-c: fast.txt, postgres.txt,
postgres-gate.json, strict-boundaries.txt, format.txt, fresh-bootstrap.json,
container-probe.json, start.json, smoke.json, deep.json, documentation.json,
mermaid.json, source-manifest.json and phase-gate.json. The machine manifest
identifies the tested working-tree source without source identifiers in prose.

Next: P1-D, P1-I11/P1-I12, canonical case authority and exact quote/confirmation
validation on PostgreSQL. Durable waits, automatic retries/deadlines, signals,
cancellation, mutations, distributed leases, outbox, conversation/UI adapters,
product telemetry, isolated SDK consumer and complete media/model/platform gates
remain later work. Use the existing granular roadmap rather than expanding the
SQLite scheduler or claiming production/multi-region capacity from this lab.
