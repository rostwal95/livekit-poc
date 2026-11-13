# Joined showcase providers, hardening and demo

Status: Active
Last reviewed: 13 November 2026

## Behavior and scope

Make the [0045 joined application](0045-joined-native-channel-policy.md) a
demonstrable product: run the same journey with real Deepgram, OpenAI and
ElevenLabs models, make every transition visible in the browser, record a
narrated demo video and bring the root documentation to a release-quality
front door. This contributes to P2-I22/P3-I19 and the portfolio demo goal; it
registers no charter row and does not replace the 0045 qualification gates.

P1 remains the case/work/issuance/result/delivery authority, P2 owns input and
communication evidence, and P3 verifies results. Models still never select
durable work: the persisted dispatch decision stays the deterministic
investigation rule in both modes, and exact confirmation stays outside the
conversation. The default scripted mode, P1/P2/P3 storage versions and public
contracts are unchanged; serving performs no DDL.

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| Explicit provider mode | Three private keys in the owner-only file | The launcher starts with `--provider` | Keys reach only the per-room native worker; a mode mismatch between grant, worker frames and agent attribute fails closed | The browser shows `LOCAL / REAL PROVIDERS` and the agent answers with real STT/LLM/TTS | Provider-mode unit tests plus three actual browser journeys |
| Dispatch independent of speech | A long real reply is still playing | The next durable dispatch is prepared | Prepare returns once the reply is scheduled; at most four owned reply observers; communication capture keeps the playout contract | Durable dispatch fits its 4 s budget with real TTS | `NativeTiming` tests and actual journeys |
| Trusted current result in replies | A policy result exists or is still running | The agent answers a turn | The model receives one bounded as-of fact; an unreadable result says the check is still running | Replies state the applicable result as of the latest check | Actual journeys with all agent reads succeeding |
| Visible transitions | Inputs, results and speech change | The page renders | Display data never grants authority; foreign or SDK-forwarded user transcript streams change no state | Live captions grow in place, the transcript follows, counts and results update, abandoned rooms read as "Session in use" | Room, panel and model tests plus recorded frames |
| Reproducible demo | A running showcase on a fresh profile | The recorder runs | It reads only the local operator key; no provider key is touched; the overlay exists only in the recording | An aligned narrated MP4, poster and step timings | `make channel-policy-demo-record` and Deepgram timestamp alignment check |

## Interfaces and ownership

P2 (`channel_continuity.native`) adds the opt-in `NativeTiming` value: model,
commit and transcript budgets, `reply="playout"` (default, unchanged) or
`"scheduled"`, a reply observation window and a cap of four in-flight replies.
`NativeRuntime` accepts `timing`, bounded `instructions` and an explicit
`inference_mode` that it publishes as the `p2.inference_mode` attribute.

The joined application adds `native_provider_models.py`: the provider bundle
reuses P1's qualified adapters (`create_provider_llm`, `ProviderSTT`,
`ProviderTTS`) with a turn-binding Deepgram recognizer and a toolless OpenAI
plugin factory. Worker configuration schema 2 carries `inferenceMode`; room
descriptors and browser grants carry the mode; the launcher accepts `--provider`
and loads keys with the strict provider-config reader.

Runtime hardening, all inside `services/channel_policy_demo`:

| Component | Change |
| --- | --- |
| `CurrentResultProducer` | Concurrent readers share one published, unabandoned scan; only the last waiter's expiry abandons it |
| `ChannelPolicyExecutor` | Per-work rerun pacing (1 s doubling to 30 s); never-run work still starts at once; every scan still rereads every entry |
| `ChannelPolicyApplication` | Scan cadence backs off from 0.25 s to 1 s while idle; background readers share a one-slot lane; current-result reads retry transient `capacity` twice |
| `ChannelPolicyJobFactory` | Execution keeps two tickets; one more is reserved for read-only inspections |
| Loopback routes | Worker current-result ceiling raised from 1 s to 4 s (route 3.5 s, client 4 s) |
| Parent | Provider-mode rooms get an 8 s cleanup budget |

The browser (`apps/local-console`) adds provider labels and readiness, a
microphone or recorded-clip voice source, live captions, transcript follow,
the "Session in use" state and quiet release of transcription streams that are
not from the selected agent. Setup adds the `associate-sms` owner command, a
per-checkout `STACK_PROJECT` for an isolated Compose stack, the documented
`.env.providers.example` and serving-only Python image extras.

## Failure cases and validation

Running the journey with real models exposed defects that scripted fixtures had
masked. Each was reproduced, root-caused from runtime evidence and fixed with a
regression test.

| Symptom | Root cause | Fix and regression |
| --- | --- | --- |
| No agent reply in provider mode | OpenAI rejects `parallel_tool_calls` without tools; P1's bounded LLM always sends it | Toolless plugin factory; wire-level test asserts no tool fields and refused tool lists |
| Voice turns ended the session | The SDK forwards the user's transcript with the browser's own identity; the room client disconnected on any foreign stream | Release non-selected or excess streams without state change, as P1's console and the console Design require |
| Agent said the result was unavailable | Single-flight producer refused concurrent browser and agent reads | Shared scans; producer tests for sharing, last-waiter abandonment and refusal of abandoned scans |
| 60–80 background events per second at ten works | The executor replayed every finished job on each 250 ms scan, holding both job tickets | Rerun pacing and idle cadence; executor and cadence tests |
| Agent reads timed out | The worker route was capped at 1 s while a scan builds an inspection client stack | Raised route ceiling and client budget |
| Inputs left `exhausted` (`adapter_unavailable`) | Background scans held both shared reader slots during origin attestation; P2 retries once after 100 ms | Background lane; worker-client and application tests |
| Inspection `capacity` | Execution jobs took every job ticket | Reserved inspection ticket; jobs test |
| Brief `capacity` collisions | One- and two-slot source bounds overlap during dispatch | Two bounded side-effect-free read retries; application test |
| End reported cleanup incomplete | Provider sessions need longer than 2 s to close | 8 s provider-mode room cleanup budget |
| Raw timestamps and internal fields spoken | Instructions asked to state the observed time | State-to-wording instructions; never read timestamps, revisions or identifiers |

| Gate | Applicable and why | Exact tests/assertions | Prerequisite/resource/time bound | Expected status/artifacts |
| --- | --- | --- | --- | --- |
| Unit and component | Every changed module | Channel-policy suite (761 tests), provider mode (13), P2 native timing, P2 TypeScript (887), P3 Python (441), console Vitest (717) | Frozen environment | All pass except tests needing a free port 5179 while a showcase runs |
| Real PostgreSQL | Review fixes touch P2 connections and P3 delivery | `make p2-postgres-check`, `make p3-completion-check` | Restricted-role local PostgreSQL | Passed 23/23 and 13/13 with complete cleanup |
| G-FAST | Shared harness and documentation changes | `make check` | Python 3.14 environment | Passed: 3,764 Python tests, zero skips; Ruff; mypy 193 broad/221 strict files |
| Frontend | Console, P2, P3 and gateway | `make frontend-check` | Corepack pnpm | Passed: 2,023 TypeScript tests, types, formatting and builds |
| Stack | Runtime composition unchanged for the default stack | `harness validate`, `stack.py smoke` | Isolated livekit-poc stack | Catalog valid (55 cases, 24 registered); smoke eight checks, ten audio frames |
| Actual provider journey | Real models change timing and protocol | Three journeys through the `make` target: text, recorded voice, question, End | Running stack, provider keys, fresh profile | All inputs dispatched on the first attempt |
| Demo recording | Portfolio deliverable, not a qualification gate | Recorder plus Deepgram timestamp alignment | ffmpeg, provider keys | MP4, poster and steps in docs/media |

## Results and handoff

Three consecutive provider-mode journeys through
`make channel-policy-demo-start-provider` completed in 36–41 s each, including
End. All nine inputs were dispatched on their first attempt and every agent
read succeeded: the first turn reported that the check was still running and
later turns reported "Eligible under the policy as of the latest check." The
launcher reaped all children with exit code 0 after each run.

The [demo video](../media/channel-policy-demo.mp4) is 80 s of 1440×960 H.264
with AAC audio (about 2 MB), recorded with real providers on a fresh profile;
its [poster](../media/channel-policy-demo.png) shows the rejoined session. A
Deepgram pass over the captured track placed every agent reply and the user's
clip within half a second of its UI event.

Final shared validation passed on the isolated `livekit-poc` stack: `make check`
ran 3,764 Python tests (49 P1, 125 P2, 441 P3, 3,149 root) with zero skips plus
Ruff and broad/strict mypy; `make frontend-check` ran 2,023 TypeScript tests
(717 console, 887 P2, 187 specialist, 232 gateway) with types, formatting and
builds; the catalog validated and the stack smoke passed all eight checks. The
real PostgreSQL P2 lane (23/23) and P3 completion gate (13/13) passed after the
review fixes. The 0043 package-check inventory was updated for the two new
application payloads and the new tests.

Limitations and backlog, in priority order:

- Each profile holds sixteen inputs; discovery fails closed beyond that, so use
  a new profile per demonstration.
- A first launch right after setup intermittently reported `unavailable`
  (missing-file read); an immediate retry always started.
- Every job and inspection builds fresh P1, specialist and receiver clients;
  pooling them would cut scan latency and remove most capacity collisions.
- Current-result scans reread all history; cost grows with the window.
- The browser bundle exceeds 500 kB because of livekit-client; code-split it.
- The UI cannot show what speech recognition heard without a versioned P2
  acceptance contract that carries the committed transcript.
- Microphone input is implemented but physical capture is not qualified, and
  ffmpeg is an unpinned recording tool.

### Independent code review findings

Separate read-only reviews of P1, P2, P3 and the application services/UI found
no critical security defects: SQL is parameterized or composed from validated
identifiers, token and HMAC comparisons are constant-time, HTTP surfaces are
bounded and logs carry fixed codes. Findings fixed after the reviews:

| Area | Finding | Fix and evidence |
| --- | --- | --- |
| P2 | A checked-out `pg` client emits `error` on an unexpected disconnect and pg-pool drops its idle listener, so a database restart mid-query could crash the process | `PgPool`/`PgClient` attach a client listener; the failed query still rejects. New unit test; real PostgreSQL P2 lane passed 23/23 |
| P3 | A deadline or close between a created delivery `begin` and receiver `accept` left a possible-send marker that later calls only look up, so the result was never delivered | A created begin makes the call external and skips waiter checks until accept. Two new tests; real PostgreSQL completion gate passed 13/13 |
| Joined UI | Repeated audio-unlock clicks could fill the room's operation cap; the logo linked to a page the showcase does not serve | Single-flight audio unlock with a test; logo is now plain branding |
| Console | The dev server bound every interface; the P2/P3 cards still said "PLANNED" | Loopback dev server; cards describe the joined showcase |
| Tests | A PostgreSQL-lane test read its fixture from an absolute path outside the repository | Repository-relative fixture path |

Open findings, in priority order. Each needs its own versioned change and gates:

| Severity | Area | Finding | Direction |
| --- | --- | --- | --- |
| High | P1 | A pre-dispatch `dependency_unavailable` returns a confirmed mutation to pending without backoff, so a brief supplier outage exhausts its eight attempts | Persist a due time from the retry policy (owner v5 upgrade) and honor it in claims; add a pacing test |
| High | P1 | Every booking-v4 call, including reads, takes one schema-wide advisory lock and revalidates the catalog under it | Lock-free repeatable-read reads; revalidate only schema metadata under the lock |
| High | P1 | `claim_next` evaluates every admitted task in scope on each poll | Non-terminal predicate now; typed due column with a partial index in v5 |
| High | P2 | Every transaction revalidates the full catalog; hot paths recount whole tables under the admission lock | Validate at startup and check version/digest per transaction; trust maintained counters |
| High | P2 | The gateway polls every account every 100 ms with an unindexed eligibility query | One batched query per tick and a partial index for due work (v9) |
| High | P3 | `CompletionProcessor` stalls permanently on a row whose route is not in the frozen bindings | Record such rows as unACKed unavailable and let the scan advance; validate routes at submit |
| High | UI | No single entry page links P1, P2 and P3; the showcase is a separate build | One multi-page build with a landing page |
| Medium | P1/P2/P3 | No connection pooling; per-call validation and whole-table counts make cost grow with history | Pooled clients and incremental validation |
| Medium | P1 | The worker's failure budget is per process, so one failing task can stop a scope | Per-task failure tracking and backoff |
| Medium | P2 | Signed SMS and association take the global lock before HMAC verification; every error discards a pooled connection; v5 dropped indexes two outbox queries need; capacity caps are lifetime totals | Verify first; discard only uncertain connections; v9 indexes; tombstones with owner compaction |
| Medium | P3 | Coordinator `close()` does not abandon pending calls; a never-started native run cannot resume; six owner/close helpers have drifted | Shared owner helper with an explicit close policy |
| Medium | UI | Per-input status lives only in the evidence JSON; timestamps are raw UTC; the business panel polls terminal cases | Status chips, local times and terminal-state polling stop |
| Low | All | Duplicated helpers, synchronous throws from promise APIs, large static browser bundles, plain-env secrets with a shared grant HMAC key, broad CSP connect-src, no back/forward-cache re-init | Consolidate and harden as each area is next changed |

This work was implemented with AI assistance in Cursor under the repository
owner's direction; provider calls used the owner's private keys.
