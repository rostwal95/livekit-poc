# Open review findings, schema upgrades and landing page

Status: Active
Last reviewed: 14 November 2026

## Behavior and scope

This item closes the open findings recorded in
[0046](0046-joined-showcase-providers-and-demo.md) that the repository owner
selected on 14 November 2026: contained fixes, versioned schema upgrades
(P1 v5 and P2 v9), connection pooling and one landing page, followed by full
P1 requalification including the paid `provider_real` deep gate. Per-transaction
schema validation stays as a fail-closed control by the owner's decision; the
optimizations work around it.

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P3 processing liveness | A projected result whose case/conversation is not in the frozen v2 bindings | `process_once` scans it | It stays unACKed and is counted as `unroutable`; scope and identity failures still fail closed | The scan cursor advances and later results are processed | `test_processing` (29) and `make p3-processing-check` (16) |
| P3 close boundary | A submit is waiting on its case read | `close()` starts | A call that has not reached its write boundary is abandoned and never submits to P1; writing calls are retained | Close completes once retained work settles | `test_coordinator` (20) and `make p3-coordinator-check` |
| P2 authentication before admission | Forged SMS or association bytes | The gateway delivers them | They are rejected before a pooled connection or the admission lock is taken; database time still enforces freshness inside the transaction | Rejection metrics and events are unchanged | `inbox-admission.test.ts` and the P2 real lanes |
| P2 connection reuse | A business rejection or failed read | The transaction rolls back cleanly | A failed rollback or an uncertain commit still discards the connection | The pooled connection is reused | Same file plus updated rehydration, prepared-read and schema tests |
| P2 idle polling | An idle gateway | No eligible work for consecutive cycles | `idlePollMs` is opt-in (default equals `pollMs`); local intake wakes the loop at once | The joined showcase polls up to five times less while idle | `gateway.test.ts` |
| P1 retry pacing (v5) | A confirmed mutation hits `dependency_unavailable` before dispatch | The worker records the failure | v4 behavior is unchanged; on v5 the effect is held until a persisted due time (1 s doubling to 30 s, never past the deadline); cancellation is never held behind it | The next attempt runs when due instead of exhausting the budget in seconds | `pg_upgrade_v5_cases` (10) and `make postgres-check` (337) |
| P1 due selection | Many terminal tasks in a scope | `claim_next` polls | Selection is unchanged: the filter is the union of every branch's necessary condition | Terminal rows skip the per-branch subqueries; v5 adds `(state, task_id)` and effect due indexes | Real PostgreSQL lanes |
| P1 backup recovery | A populated v4 backed up with `pg_dump` and restored with `psql` | The runtime validates it | Only the one enumerated round-trip form of `limits_active` is accepted | A restored v4 validates and upgrades to v5 again | `test_pre_upgrade_backup_restores_an_exact_v4_that_upgrades_again` |
| P2 indexes (v9) | A populated v8 | The owner runs `upgradeChannelSchemaV9` | An interrupted upgrade rolls back exactly; older upgrades replay without changes; the restricted runtime revalidates per transaction | Three operating indexes serve due dispatch and send-history lookups | New result-receiver gate case (17 storage + 4 return) |
| Landing page | The showcase origin | A browser opens `http://127.0.0.1:5179/` | Only a validated loopback console URL is linked | One page links the joined showcase and the P1 console | `channel-policy-landing.test.ts` and the built page |
| UI status | Inputs are sent from the showcase | The transcript renders | Display data grants no authority | Each sent entry shows its durable input status and a local time; the P1 panel stops polling settled cases | Model, panel and business tests |

## Interfaces and ownership

| Component | Change |
| --- | --- |
| `continuity_lab.postgres_schema_v5` | New additive catalog: typed `mutation_effects.next_attempt_at`, `effects_retry_due` CHECK, `controls_state_task_idx`, `mutation_effect_due_idx` |
| `postgres_migrations.upgrade_v5` | Owner-only ACTIVE v4 to v5 upgrade with failpoints; replay at v5 is a validated no-op; `upgrade_v4` now replays at v4 or later |
| Runtime version gates | Exact `== 4` checks accept v4 and v5; serving code runs no DDL |
| `PostgresEffects` / `PostgresWorkQueue` | v5-only persisted due time and due-aware mutation selection |
| `postgres_cli` / `stack.py` | `upgrade-retry-pacing` owner command; `prepare-business` takes the additive v5 step; Phase F/G runners use v5 |
| P2 `migrations.ts` / `database.ts` | `upgradeChannelSchemaV9` and `INDEX_DEFINITION_DIGEST`; every store accepts v9 |
| P2 `ChannelGateway` | Opt-in `idlePollMs`; intake nudges the dispatch loop; optional `dispatchTimeoutMs` (defaults unchanged) |
| Joined setup | New showcase profiles are created at P2 v9 |
| Showcase build | Multi-page build: `landing.html` served at `/`; console URL injected from the configured UI port |
| Joined gateway composition | Native and SMS gateways both use the 5,000 ms dispatch step deadline |
| Console nginx | `/api/` resolves `control-api` per request through Docker's embedded DNS |
| Showcase Join | A Join blocked only by in-flight status/result reads is deferred until they settle |
| Demo recorder | `--complete` and `make ecosystem-demo-record`: landing page, showcase, one P1 business case |

## Decisions

* **Native-policy resume declined.** P3's documented design says repeated
  `evaluate` calls "only inspect original facts", and a qualified test asserts
  that a cancelled call never starts a run later. Resuming would be a design
  change, outside the selected contained scope.
* **P1/P3 pooling deferred.** Measured locally, connection setup costs 3.7 ms
  (median) and P1 schema validation 11.4 ms per transaction, so pooling would
  save about a quarter of per-operation overhead. P1/P3 stores are stateless,
  connection-per-operation objects without a lifecycle, the worker slot depends
  on a dedicated session for its advisory lock, and `psycopg_pool` would change
  the P1 distribution metadata. The recommended design is a reusable-connection
  provider owned and closed by long-lived composition roots, per-operation
  connections by default and a dedicated slot connection. P2 already pools; its
  pools now keep connections after clean rollbacks.
* **Per-task worker failure budget folded into v5.** The claim order comes from
  the database, so the durable fix is the persisted due time.

## Failure cases and validation

| Symptom | Root cause | Fix and regression |
| --- | --- | --- |
| Restored v4 schema rejected | `pg_dump` deparses `BETWEEN` as a flat `AND` chain; the validator compares exact text | One enumerated equivalent for `limits_active`; backup round-trip test |
| P2 backup gates could not find PostgreSQL | Three gates hardcoded the old compose project label | Use the configured per-checkout project |
| `p2-native-check` (and playback, rehydration-media) failed | Gate oracles predated `sdkSessionClosed`, `sdkCloseAllocationFailed` (baseline) and `activeReplyObservers` (0046) | Oracles updated; actual runtime lanes pass |
| `p2-starter-p1-check` failed at `p1-bridges` | The bridge re-exports `services.channel_policy_demo.case_bridge`, which the isolated installation did not ship (baseline break) | The gate ships that module in its private work directory |
| `p2-operations-check` failed | Standalone examples from 0041 were not in its allowed build outputs | Explicit allowance for those five files and four declarations |
| Package gates failed after v5 | P1 runtime payloads are pinned | 77 updated to 78 where pinned; plan digests updated |
| P1-14 and P1-20 failed at image provenance | 0046 added the showcase's `checking.wav` to P1's conversation-agent assets and manifest, so P1's qualified nine-recording set changed | The showcase owns that reply in `services/channel_policy_demo/assets/`, pinned by digest; P1's original manifest is restored and the root package still ships 86 payloads |
| `business_preflight` refused v5 | It required exactly ACTIVE v4 | Accepts v4 or v5 with the same fixed failure code; unit test added |

| P1-20 real-media suite could not start | `playwright.real.config.ts` matched every `*.media.ts`, including P2/P3 suites that need their own private fixtures | Match only `local-real.media.ts`; P2/P3 suites keep their own configs |

| Gate | Applicable and why | Status |
| --- | --- | --- |
| G-FAST | Shared code, harness and docs | `make check` passed: 3,770 Python tests (P1 49, P2 125, P3 443, root 3,153), zero skips; Ruff; mypy 194 broad / 221 strict files |
| Frontend | Console, P2, gateway | `make frontend-check` passed: 2,031 TypeScript tests (console 721, P2 891, specialist 187, gateway 232), types, formatting, builds |
| P1 PostgreSQL | v5, version gates, due selection, validator | `make postgres-check` passed: 337 tests, zero skips, including ten v5 cases |
| P2 real lanes | Inbox, dispatch, gateway, native, playback, rehydration (+media), result receiver (+v9 case), outbox, callbacks, send policy, communication, prepared read, standalone, agent, routing, confirmation, starter, operations, workload, result-receiver package | All passed |
| P3 real lanes | Processing, coordinator, execution, completion, contract, projection, applicability, recovery, deadlines, action races, package, package lab, fixed policy, fixed work, native policy | All passed; processing 16/16 |
| Stack | Runtime composition | `harness validate` (55 cases, 24 registered); `stack.py smoke` completed |
| P1 business profile | Owner-selected requalification | `prepare-business` bootstrapped and verified v5, fixtures initialized, `start-business` preflight passed and all four services healthy |
| P1 deep gate (`provider_real`) | Full requalification | 20 of 21 rows passed (BASE-01, P1-01 to P1-19; 104 tests, zero skips). P1-20 is blocked on this network: the passing reference run mounted an approved CA bundle into the native container; every run here used the image trust store and recorded zero STT/LLM/TTS usage before the agent's reply timed out |
| Joined showcase on v9 | P2 v9 setup, gateway, P3 processing, UI | A fresh profile was created at P2 v9 (three indexes present) and the full scripted journey passed: text result, End, durable SMS, rejoin with three linked inputs; landing page served at `/` |

## Complete demo recording

On 14 November 2026 the owner asked for one complete video. The recorder gained
`--complete`. Rehearsals and takes exposed three defects, which are fixed below.
Three further findings remain open.

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| Join during routine reads | Status/progress polls hold both ordinary tickets | The operator presses Join | Start is still refused while any command other than a read is in flight; End/Forget clear a deferred Join | Start runs once the reads settle instead of showing "must be reconciled first" | `channel-policy-policy.test.ts` (new case) and the recorded takes |
| Console after an API recreate | `start-business` recreated `control-api` after the console started | The console submits an investigation | Unresolvable upstreams fail per request (502/504) instead of preventing nginx startup | The request reaches the current container | Isolated network test below; `nginx -t` passes without a network |
| SMS dispatch budget | A loaded joined showcase | A simulated SMS dispatches through the P1 bridges | Defaults are unchanged for other consumers; a late possible accept still records uncertainty | The step has the same 5,000 ms as native input, so a slow committed accept is observed | `gateway.test.ts` (new case) and the final take |
| Complete recording | A provider showcase on a fresh profile and the P1 business profile | `make ecosystem-demo-record` runs | The console token comes from `stack.py token` into memory, is entered under a title card and is never logged | One take covers the landing page, showcase steps 1–6 and one P1 case | `docs/media/ecosystem-demo.mp4` |

| Symptom | Root cause | Fix and regression |
| --- | --- | --- |
| Join on a fresh profile failed with "The original activation or command must be reconciled first" | `beginStart` refuses with `conflict` while any ticket is held, and routine status/progress polls held both ordinary tickets | The application defers Join while only side-effect-free reads are in flight |
| Console business submit showed "Acknowledgement unknown" | nginx resolved `control-api` once at startup (21:33:40Z); `start-business` recreated the API at 22:12:34Z with a new address, so every call hit "upstream timed out while connecting" | Per-request resolution through `127.0.0.11` (valid 10 s). After recreating a stub upstream at a new address the new config still reached it (404 from the stub) and the old config returned 504 |
| SMS stayed at "1 dispatch outcome unknown" | The SMS gateway used P2's 2,000 ms standalone step deadline. Attempt 1 timed out after 2.08 s; attempt 2 timed out after 2.22 s, while its P1 accept committed 0.18 s later. With `maxAttempts` 2, no lookup could reconcile it | Optional `dispatchTimeoutMs`; the joined composition passes 5,000 ms to both gateways. The final take linked the SMS within a second |

| Gate | Applicable and why | Status |
| --- | --- | --- |
| G-FAST | Shared docs and configuration | `make check` passed: 3,770 Python tests, zero skips; Ruff; mypy 194 broad / 221 strict files; `harness validate` valid (24 registered) |
| Frontend | Console, P2, gateway | `make frontend-check` passed: 2,033 TypeScript tests (console 722, P2 892, specialist 187, gateway 232), types, formatting, builds |
| P2 real lanes | Gateway option and dispatcher construction | `p2-gateway-check` (3), `p2-dispatch-check` (5), `p2-native-check` (6) passed |
| Console proxy | nginx configuration | `nginx -t` in the pinned console image; isolated recreate test as above; rebuilt console reached the recreated API |
| Recording | Owner request | Final take in `provider_real` on a fresh P2 v9 profile: 2:08, 1440×960 H.264 with AAC audio, 3.06 MB (SHA-256 prefix `cf33b178a92081e0`). Video times: Ready 16.7 s, first reply 24.0 s, voice reply 44.1 s, SMS linked 59.4 s, rejoin 73.1 s, P1 case accepted 103.8 s, exact confirmation 115.8 s, delivery 118.9 s. Audible speech intervals match each reply |

Open findings from the recording:

* **First Join can exceed the worker startup budget on a loaded host.** In 2 of
  10 recorder-driven Joins, both the first after a launcher start, the Parent
  rejected Start exactly 10 s after room control, while the native worker had not
  reached `prepare_ready`.
  Instrumented successful Joins took 5.1–6.6 s, with spawn to `prepare_ready` in
  2.2–2.65 s. The host showed load averages of 5–7, the Docker VM near 85% CPU,
  endpoint antivirus scanning and Chromium video encoding. Candidates are a
  provider-mode budget aligned across the worker, room, Parent and operator
  layers, or a prewarmed worker. The README advises one Join and End before
  recording.
* **One Ctrl-C does not stop a launcher with a live voice turn.** The scripted
  room cleanup budget is 2 s, but the worker needed 3.9 s to close (session
  closed after 2.5 s), so the Parent reported `cleanup_incomplete`. The launcher
  then waits for another signal, although the retained close finished about
  1.9 s later. A second interrupt completes cleanly with every child graceful.
  Candidates are a budget that matches the measured close, or letting the
  launcher re-observe retained front-tier cleanup inside its 60 s shutdown
  window.
* **The scripted recorded-voice turn did not link once.** In one scripted
  rehearsal the text turn linked but the recorded voice turn did not within
  45 s. This is not root-caused. Provider-mode voice turns linked in all four
  recorded takes. Separately, the showcase exposes no control for P2's explicit
  lookup-only reconciliation of an uncertain, exhausted dispatch.

## Results and handoff

Open after this item: P1-20 with `P1_PROVIDER_CA_BUNDLE` pointing at the owner's
approved bundle; P1/P3 pooling (design above); batched gateway polling; P2
lifetime capacity tombstones; P1 lock-free reads and incremental validation
(owner kept per-transaction validation); the three recording findings above.
`git rm -r --cached apps/local-console/dist-channel-policy` and committing remain
with the owner.

This work was implemented with AI assistance in Cursor under the repository
owner's direction.
