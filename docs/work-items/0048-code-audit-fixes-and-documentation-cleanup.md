# Code audit fixes and documentation cleanup

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the deep code audit, its verified fixes, the open findings and the documentation standardization |
| Audience | Engineers and coding agents changing an audited area, the documentation standard or the root README |
| Scope | Eight audit areas, contained fixes with regression tests, documentation standard version 2 and the root README redesign; excludes lifecycle changes left as open findings |
| Owns | This item's findings, fix evidence, gate results and documentation outcome |
| Related | [0047](0047-open-findings-schema-upgrades-and-landing.md) · [Documentation standards](../documentation-standards.md) · [Documentation map](../README.md) · [Validation plan](../validation-plan.md) |

## Behavior and scope

On 15 November 2026 the repository owner asked three things: what is still left,
a deep code audit, and clean, well-structured documentation. The owner then asked
for highly standardized documents that use tables wherever they help, no review
dates, and a richer root README with a logo, technology badges, the embedded demo
and a table of supported features. This item records all of it.

- **Audit.** Eight read-only reviewers each audited one area: P1
  (`continuity_lab`), the P2 TypeScript library, P3 (Python and the TypeScript
  specialist), the control API and agent services, the joined showcase Parent, the
  showcase gateway with the P2 Python package, the browser console, and the local
  setup tooling. The coordinator verified the most consequential claims in code
  before any fix. Contained defects were fixed with regression tests. Larger
  lifecycle changes are recorded below as open findings with recommendations.
- **Fixes.** Each fix has a regression test that failed before the change and
  passes after it. No fix changes a public default for existing consumers.
- **Documentation.** Every maintained document was reviewed twice under the
  [documentation standards](../documentation-standards.md), keeping every fact,
  acceptance ID, command and diagram. The first pass fixed structure and
  readability and added a [documentation map](../README.md). The second pass
  applied standard version 2: one document card per file, no review dates, and
  tables wherever content is enumerable. Work items and decisions were treated as
  historical records: their layout and sentences were tidied, but no recorded
  outcome changed.

The audit found no critical defect and no security defect above low severity.

### Fixed findings

| ID | Severity | Defect | Fix | Regression evidence |
| --- | --- | --- | --- | --- |
| P1-A1 | High | After a prior dispatch reservation, a takeover worker whose lookup found nothing recorded `cancelled_before_dispatch` or `deadline_expired`, although the paused earlier call could still change the booking | `prepare_dispatch` takes those definite outcomes only when `dispatch_count` is 0; otherwise it records UNCERTAIN/`ambiguous_outcome` | Two new `pg_coordination_cases` tests (cancel and deadline during the paused window); both failed before the fix |
| DEMO-A1 | High | The scripted recognizer allowed one speech-to-text stream, but LiveKit Agents' `clear_user_turn` opens the replacement stream before closing the old one, so the first scripted voice turn per room produced no transcript | Two stream handles (one active, one closing), as the provider recognizer already allows | A real `AgentSession` test commits the first voice turn; the scripted showcase journey now links the recorded voice turn |
| DEMO-A2, GW-A3, P2-A6 | High | Inside the 5,000 ms dispatch step, the operation bridge (1.5 s default), the external client (2 s) and the origin hosts (2 s) still cut off slower accepts, and new joined profiles stored a claim lease equal to the step | Bridge `timeoutMs` 5,000, passed to the client as a new optional `callTimeoutMs` (20–5,000 ms, default 2,000); origin hosts 5 s; new joined profiles lease 8,000 ms | Bridge test: an accept answered after 2.3 s succeeds (it returned `AcknowledgementUnknown` before); client, runtime and setup tests |
| DEMO-A4 | Medium | After a peer reset, `wait_closed()` re-raised on every await, so loopback and worker clients kept the slot forever | Shared `close_writer` treats a connection-lost `OSError` as observed closure | Extended reset tests release both slots and close completes |
| P2-A1 | Medium | Uncertain inputs parked for a missing sender association were re-claimed every poll, defeating `idlePollMs` and able to starve newer inputs | Excluded from automatic eligibility (explicit step and lookup-only reconcile still work); idle backoff resets only on a dispatched step | Gateway backoff test and eligibility test |
| P2-A2 | Medium | A known carrier result could become permanently unknown when the outbox store's four shared call slots were busy | Result recording has its own four-slot admission | Tests with all ordinary slots held |
| P3-A1 | Medium | The completion processor's `close()` could not stop later rows in a step after the first row's commit | `close()` takes effect between rows | Two close-mid-step tests |
| P3-A2 | Medium | Transient dependency errors failed the whole processing step as `invalid_source_state` | Per-row unACKed `unavailable`; one shared mapping with the refresher | Feed, delivery and result-read capacity tests |
| P3-A3 | Medium | TypeScript `verifyPolicyFacts` reported `expired` for a late, factually wrong result that Python rejects | Factual support is checked before expiry, as in Python | Shared-fixture parity test |
| SVC-A1 | Medium | After a voice submit's acknowledgement was lost, the agent said nothing was accepted and dropped a spoken cancellation | `get_case` and `cancel_case` replay the frozen original submit first | Timeout-then-commit test for both tools |
| SVC-A2 | Medium | The diagnostic worker could accept two jobs despite its one-job cap | `JobAdmission` counts in-flight accepts | Concurrent admission test |
| UI-A1 | Medium | A definitive 401/403 on a P1 command was relabelled "possibly accepted" and wedged the panel | The token is forgotten after the failing command finishes | Two business-panel tests |
| UI-A2 | Medium | A double click or double Enter in the joined composer created a second durable input | One frozen input id until accepted or rejected; Enter follows the Send button and ignores key repeat; Retry adds no duplicate entry | Three tests |
| UI-A3 | Medium | The P2 native page decremented its context-read counter on response reads, disabling a concurrency guard | Stray decrement removed | Page-script test |
| OPS-A1 | Medium | Provider keys stayed in the native container after a failed `start-provider`, `stop-business` or `stop-local-real` | Cleanup after a serving failure (with a stage report); stop paths remove the container | Stack manager tests |
| OPS-A2 | Medium | The joined launcher ignored SIGHUP, orphaning its detached children | SIGHUP and SIGQUIT stop it like SIGTERM | Launcher test |
| P1-A4, P2-A3, P2-A5, SVC-A6, SVC-A8, UI-A5, OPS-A4, OPS-A7, OPS-A8, OPS-A9 | Low | Quadratic cutover check; non-retryable close after a failed attempt; v9 upgrade without explicit locks; stale audio-task cleanup; readiness 503 detail as a Python repr; background polls consuming the token field; busy post-deadline cleanup loop; `doctor` missing `.env.providers`; Makefile console URL reading secrets; `prepare-business` reporting read-only while upgrading | Each fixed in place | Each has a regression test, except P1-A4 (behavior unchanged; equivalence checked on 3,000 randomized snapshots, validation of 6,000 tasks fell from 1.78 s to 0.19 s) |

## Interfaces and ownership

| Component | Change |
| --- | --- |
| `continuity_lab.postgres_effects` | Prevention and deadline outcomes require zero prior dispatch reservations |
| `continuity_lab.postgres_migrations` | Attempt histories grouped once during cutover validation |
| P2 `ExternalOperationClient` (standalone starter) | Optional `callTimeoutMs` on the operation-only configuration; default unchanged |
| P2 dispatch, gateway, inbox, outbox, migrations | Parked uncertain inputs, progress-only backoff reset, retryable close, recording admission, v9 locks |
| `services/channel-policy-gateway` | Bridge per-call budget equals the 5,000 ms step |
| `services/channel_policy_demo` | Two scripted stream handles, shared writer close, origin hosts at 5 s |
| `local-setup/scripts/channel_policy_setup.py` | New joined profiles persist an 8,000 ms claim lease |
| P3 completion processor and refresher | Close between rows, per-row transient handling, shared error mapping |
| P3 specialist (TypeScript) | Fact-before-expiry check order |
| Conversation agent, diagnostic worker, control API | Frozen submit replay, job admission, stale cleanup guard, JSON readiness detail |
| Browser console | Frozen composer input, definitive 401/403, held-token background reads, read counter |
| `local-setup/stack.py`, launcher, `prepare_business.py`, Makefile | Provider cleanup and container removal, stop signals, post-deadline backoff, tracked-file check, console URL helper, `schemaActivation` report |
| `harness/documentation_check.py` | Requires the six-row document card between the title and the first section, rejects `Status:` and `Last reviewed:` lines, and checks local `src`, `href`, `poster` and `srcset` targets in embedded HTML |
| `harness/documentation.json` | Required tables for the README, instructions and design roles |
| Root README and `docs/media` | Light and dark logo, grouped static version badges, a 31-second animated preview linked to the full MP4, and feature, status and command tables |

No schema version changed. Serving code still runs no DDL.

## Failure cases and validation

| Gate | Applicable and why | Status |
| --- | --- | --- |
| G-FAST | Code and shared documentation | `make check` passed: 3,788 Python tests (49, 125, 450, 3,164), zero skips; Ruff; mypy 194 broad / 221 strict files |
| Frontend | Console, P2, specialist, gateway | `make frontend-check` passed: 2,056 TypeScript tests (console 729, P2 905, specialist 188, gateway 234), types, formatting, builds |
| Harness and documentation | Catalog and corpus | `harness validate` valid (55 cases, 24 registered); documentation checker passed on 134 documents with zero violations |
| P1 PostgreSQL | P1-A1 and the business bootstrap | Passed on targeted reruns; the last full run was not clean under host load. The first `make postgres-check` run (339 tests) found three stale business-bootstrap expectations of schema v4, because `prepare-business` has targeted v5 since 0047; they now assert v5 and the new `schemaActivation` values, and that module passed 4 of 4. The final full run (845 s, load average above 9) had no failures but five errors: one lost lease, three takeover tests whose child exited before the required observation and one delivery database-clock test. Rerunning `pg_coordination_cases` and `pg_result_delivery_cases` passed 27 of 27 in 66 s |
| P2 real lanes | Dispatch, gateway, outbox, starter, bridge | All 21 lanes passed. Nineteen passed on the first pass. `p2-workload-check` (the restored-replay stage overran its 30 s cap under load) and `p2-rehydration-media-check` (a listener failed to bind right after the playback lane) failed on the first pass and passed on an isolated rerun (122 s and 41 s) |
| P3 real lanes | Processing, applicability, recovery, packages | All 16 passed |
| Joined showcase | DEMO-A1 end to end | Scripted journey on a fresh profile: the recorded voice turn linked to durable work, and text, SMS, rejoin and question all completed |

`projects/channel-continuity/tests/agent-process.test.ts` spawns real worker
processes with 500 ms budgets. Its first, cold-start test failed 2 of 5 isolated
runs on this loaded host. That test now uses 1,500 ms, after which it failed once
in 24 runs. Other 500 ms tests in the file can still flake rarely.

## Results and handoff

### Open findings

These were verified or carefully reasoned, but not fixed in this item because they
need a lifecycle or design decision.

| ID | Severity | Finding |
| --- | --- | --- |
| GW-A1 | High | A normal stop can permanently exhaust pending inputs: dispatch keeps claiming attempts while the Parent's endpoints close first. Stop dispatch before closing the endpoints, or do not charge attempts while closing |
| GW-A2 | High (medium confidence) | End can strand the room's last input, because the worker stops before the gateway closes the room and revokes its binding |
| P1-A2 | Medium | v5 retry pacing does not cover outages after a dispatch reservation |
| DEMO-A3 | Medium | Origin dispatch shares two client-startup slots with background jobs |
| DEMO-A5 | Medium | Scripted dispatch's 4 s prepare includes the current-result read and the full reply playout |
| DEMO-A6 | Medium | Shutdown budgets are inverted (2 s scripted room, 5 s Parent, up to 8 s provider worker), and retained cleanup is never re-observed. This is the root of 0047's "one Ctrl-C" finding |
| GW-A4 | Medium | An interrupted scripted playout fails its dispatch, and the retry speaks the reply again |
| GW-A5 | Medium | Dispatch shares two-slot pools with read traffic |
| UI-A4 | Medium | The 5 s media deadline includes the microphone permission prompt |

| Area | Low-severity findings |
| --- | --- |
| P1 | Version-capability helper (A3); due-time validation (A5) |
| P2 | Communication reads repeat whole-table counts (A4); duplicated transaction wrappers (A7) |
| P3 | Unroutable rows pay full I/O (A4); the v1 projector quarantines v2 and v3 results (A5); remote rejections reported as invalid results (A6); native tool attempt flag (A7); per-transaction catalog validation (A8); status and cancel not bound to the starting principal (A9) |
| Services | Session grants signed with the key the diagnostic worker holds (SVC-A3); business re-authentication checks the server's own token (SVC-A4); receipt lost when the follow-up read fails (SVC-A5); cleanup masking cancellation (SVC-A7); duplicated offload and token helpers (SVC-A9) |
| Showcase | The scan loop has no backoff on failure (DEMO-A7); discovery runs one query per input (GW-A6); `commit_turn` reports `no_audio` while acceptance is unresolved (GW-A7) |
| Console | Page exit aborts End (UI-A6); no CSP on the showcase pages (UI-A7); polling re-render side effects (UI-A8); back-forward cache restore (UI-A9); diverged helpers (UI-A10) |
| Operations | Deadlines kill only the `docker` CLI (OPS-A3); subprocesses inherit every stack credential (OPS-A5); the runtime-role init script puts the password in SQL text (OPS-A6); LiveKit configuration changes need a recreate (OPS-A10); remaining container hardening (OPS-A11); stop paths that stop at the first failure (OPS-A12) |

| Other open item | State |
| --- | --- |
| First Join after a launcher start (from 0047) | Can exceed the worker's 10 s startup budget on a loaded host. It recurred once during this item's scripted check, and the following Join succeeded |
| One Ctrl-C during a live voice turn (from 0047) | Does not stop the launcher; see DEMO-A6 |
| Root unit-test budget | The lane took 112 s of its 120 s budget |

### Documentation outcome

- **Structure.** Every role document keeps its required sections in order, now
  with an orientation, a contents list for long files and plain sentences. Terms
  and abbreviations are expanded, and status tables link to their work items.
  Misplaced sections moved under the right headings; for example, about 750 lines
  of P3 component material had been filed under "Security and privacy".
- **Corrections.** Writers corrected stale statements only with evidence from code
  or completed work items, for example P1 schema v5 coverage, P1-01 to P1-20
  qualification wording, 0041 to 0044 completion and the 77 to 78 payload count.
- **Standard version 2.** Each document now opens with a Field/Value card
  (Status, Purpose, Audience, Scope, Owns and Related) instead of `Status:` and
  `Last reviewed:` lines. At the owner's direction, documents carry no review
  dates, and the root AGENTS.md handoff rule now asks for capability status only.
  Enumerable content (requirements, commands, gates, components, findings and
  status) moved into tables with standard column sets, and implementation status
  uses one vocabulary: Qualified, Implemented, Partial, Planned and Not qualified.
- **Root README.** A centered hero with a light and dark logo, a tagline, quick
  links and grouped badges whose versions match the locks and image pins. The
  demo is embedded as an animated WebP preview that links to the full MP4,
  because GitHub renders images inline but does not reliably play a
  repository-relative video. Features, status, requirements, commands,
  validation and the next milestone are all tables.
- **Owner decisions flagged, not changed:**
  - work item 0017 is still Active although 0019 completed its task;
  - work items 0029 to 0033 name an old personal checkout path;
  - the root Design.md sentence "Fake SMS remains qualified for P1" is garbled;
  - the charters' status sections stop at 0044;
  - the local-setup README still calls the final demo video separately gated;
  - the root AGENTS.md says origin binding remains, which predates 0044.

### Owner actions

| Action | Why |
| --- | --- |
| Commit the changes | Nothing in this item is committed |
| Run `git rm -r --cached apps/local-console/dist-channel-policy` | The folder is ignored but still tracked |
| Choose a licence | The repository has none |
| Rerun P1-20 with `P1_PROVIDER_CA_BUNDLE` set to your approved bundle | The provider row has not rerun since the v5 upgrade |
| Update the README badges when a pinned version changes | shields.io static badges do not read the locks |
| Optionally upload `docs/media/ecosystem-demo.mp4` through GitHub's editor | GitHub plays inline video, with sound, only from its own upload URLs |

This work was done with AI assistance in Cursor under the repository owner's
direction. Parallel AI reviewers and writers did the audit and drafted the
documentation; the coordinator verified the findings, reviewed the changes and ran
every gate listed above.
