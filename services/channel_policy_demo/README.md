# Joined channel-policy application

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Explain how to run, change and validate the Python side of the joined voice/SMS showcase |
| Audience | Engineers who run or change the joined showcase; coding agents |
| Scope | Python Parent, operator API, background executor and native worker; excludes the Node gateway |
| Owns | Joined application runtime behavior, operator routes, resource limits and validation |
| Related | [Design](Design.md) · [Agent instructions](AGENTS.md) · [Gateway README](../channel-policy-gateway/README.md) · [Work item 0045](../../docs/work-items/0045-joined-native-channel-policy.md) · [Work item 0046](../../docs/work-items/0046-joined-showcase-providers-and-demo.md) |

## Overview

This opt-in root application joins the three projects: P1 agent continuity, P2
channel continuity and P3 delegation reliability. It composes P2's native and
channel continuity with origin-bound P3 policy work, through P1's existing public
authority. The intended experience is:

- one responsive conversation;
- durable background work while no room is open (dormancy);
- signed simulated SMS;
- a returning current-result view.

This README is for engineers who run or change the Python side of the joined
showcase. [Design.md](Design.md) explains its design, and the
[gateway README](../channel-policy-gateway/README.md) covers the Node side.

## Implementation status

The joined application is under implementation. The
[0045 work item](../../docs/work-items/0045-joined-native-channel-policy.md)
defines its phases, 45A to 45D. Focused tests and independent reviews cover the
stated boundaries of phases 45A and 45B.

| Capability | Status | Evidence |
| --- | --- | --- |
| Canonical origin, public prepared read and installed application contracts | Qualified | Phase 45A in [0045](../../docs/work-items/0045-joined-native-channel-policy.md) |
| Worker client and source-attested native/SMS router | Implemented | Phase 45B; focused tests and independent reviews |
| Public client factories and guarded job delivery | Implemented | Phase 45B; focused tests and independent reviews |
| Versioned private profile and Python source/executor owner | Implemented | Phase 45B; focused tests and independent reviews |
| Explicit owner bootstrap | Implemented | Succeeds against fresh P1/P2 schemas |
| Joined journey in `scripted` mode | Not qualified | Runs locally through the launcher; joined gates pending in [0045](../../docs/work-items/0045-joined-native-channel-policy.md) |
| Joined journey in `provider_real` mode | Not qualified | Selected evidence: three consecutive actual journeys in [0046](../../docs/work-items/0046-joined-showcase-providers-and-demo.md) |
| Parent room owner and operator HTTP boundary | Implemented | Parent and operator component baseline in [0045](../../docs/work-items/0045-joined-native-channel-policy.md) |
| Shared current-result scans, rerun pacing, background reader lane and reserved inspection ticket | Implemented | Runtime hardening in [0046](../../docs/work-items/0046-joined-showcase-providers-and-demo.md) |
| Origin call deadline, connection-lost writer close and two scripted STT stream handles | Implemented | Audit fixes in [0048](../../docs/work-items/0048-code-audit-fixes-and-documentation-cleanup.md) |

### Startup order and persistence

1. The Python owner starts its case listener and two origin listeners first.
2. Node starts its read and result listeners before its two intake gateways.
3. The executor starts only after Node readiness.

Accepted inputs and work remain in the existing P2 and P1 stores. The private
profile preserves configuration and stable owner identities. Normal stop does
not reset either store.

### Joined journey

Explicit bootstrap succeeds against fresh P1/P2 schemas. The launcher runs the
complete joined journey locally: native text and recorded voice, durable
dispatch, background policy results, End, signed simulated SMS and rejoin.

The scripted recognizer allows two speech-to-text (STT) stream handles, one
active and one closing. LiveKit Agents' `clear_user_turn` opens the replacement
stream before it closes the old one. With a single handle, the first scripted
voice turn in each room produced an empty transcript.

The explicit `provider_real` mode runs the same journey with Deepgram, OpenAI and
ElevenLabs. Three consecutive actual journeys dispatched every input on the first
attempt, and the narrated demo video was recorded from this mode
([0046](../../docs/work-items/0046-joined-showcase-providers-and-demo.md)).

Selected actual journeys do not complete joined installed/container
qualification or charter release. The completed
[0044 checkpoint](../../docs/work-items/0044-origin-bound-channel-policy.md)
retains its separate source and installed evidence.

### Parent and operator components

The Parent room owner and the separate operator HTTP boundary are implemented.
The launcher composes them from an existing prepared profile, in `scripted` mode
or, with `--provider`, in `provider_real` mode. Only each room's native worker
receives the provider keys.

- One physical activation retains its original Start command and 180-second
  expiry.
- An SDK disconnect fences readiness immediately. Final resource drain and actual
  worker reap remain required before another room.
- End preserves the independently running background executor and the separately
  authorized dormant SMS/read surface.

### Operator routes

The optional browser uses an explicit RAM-only operator credential through the
fixed local proxy. All routes below are `POST` under `/v1/channel-policy-demo/`,
and responses are marked `no-store`. The owner configures the input scope and
sender. An as-of observation is true only at the time it was read. RTC means
real-time communication, the LiveKit media path.

| Route | Request and observation |
| --- | --- |
| `status` | Version-only request; Parent lifecycle tuple, independent Node cursor and as-of readiness |
| `start` | Original Parent epoch, expected generation and command UUID; RTC-only grant |
| `end` | Exact Parent epoch/generation/original Start command; room closure observation |
| `current` | Exact activation tuple; five current-result facts, with a final room check before socket write |
| `case` | Version-only request; independently observed current revision/time |
| `progress` | Version-only request; bounded original P2 source/dispatch counts, not execution completion |
| `sms` | Original command UUID/body/time; fixed signed synthetic provider input and actual P2 receipt |

### Limits and deadlines

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Origin call timeout (`ORIGIN_CALL_TIMEOUT_S` in `application.py`) | 5 s | Both origin hosts | Matches the 5,000 ms dispatch step that both gateways allow |
| Origin call timeout class default | 2 s | `ChannelOriginHttp` | The class default stays 2 s |
| Physical activation expiry | 180 seconds | One Parent activation | Retained with the original Start command |
| Shared reader slots | Two | Background readers and dispatch | Background readers keep one free for dispatch |
| Reserved job ticket | One | Read-only inspections | Reserved beside the two execution tickets |
| Current-result scans | One shared scan | Concurrent current-result readers | Readers share the published scan |
| Rerun pacing | 1 s, doubling to 30 s | Executor reruns of the same work | Delays idempotent reruns; never skips them |
| Retained actual calls | At most four | Operator listener | Retained through a waiter timeout |
| Sockets | At most eight | Operator listener | None |
| Header read | One second | Operator listener | None |
| Body read | One second | Operator listener | None |
| Input | At most 32768 bytes | Operator listener | None |
| Output | At most 16384 bytes | Operator listener | None |
| Command observer | At most fifteen seconds | Operator listener | None |

The loopback JSON and worker clients treat a connection-lost `OSError` from
`wait_closed()` as observed closure and release the slot. Any other close
failure keeps the slot owned.

A timed-out command can remain accepted or unknown. It is never silently retried
under a new identity. The native prepare and worker callback profiles retain
their original contracts.

## Documentation

| Document | Purpose |
| --- | --- |
| [Design](Design.md) | Design, state ownership and failure boundaries of this application |
| [Coding instructions](AGENTS.md) | Agent rules for changing this application |
| [Implementation work item](../../docs/work-items/0045-joined-native-channel-policy.md) | Phases 45A to 45D, their gates and measured outcomes |
| [Provider, hardening and demo follow-up](../../docs/work-items/0046-joined-showcase-providers-and-demo.md) | Provider-mode journeys, runtime hardening and the demo video |
| [Audit fixes](../../docs/work-items/0048-code-audit-fixes-and-documentation-cleanup.md) | Origin deadline, writer close and stream-handle fixes |
| [Local setup](../../local-setup/README.md) | Local stack lifecycle and setup |
| [Validation plan](../../docs/validation-plan.md) | Test lanes and evidence rules |
| [Provider operations](../../docs/provider-demo.md) | Opt-in provider setup and private key handling |
| [Node gateway](../channel-policy-gateway/README.md) | The Node gateway that this application composes |

## Requirements

| Requirement | Version or value | Notes |
| --- | --- | --- |
| Python, TypeScript and runtime dependencies | Repository frozen versions | Use the repository's frozen dependencies |
| Host Node | 24.22.2 | Validated host version for the JavaScript builds |
| Local services | Existing Docker PostgreSQL and LiveKit | From the [local setup](../../local-setup/README.md) |
| Owner bootstrap | Explicit | Required before application serving |
| Root runtime extra | Declared | Required before application serving |
| Provider keys | Private | Unnecessary for scripted or offline qualification |
| Business data and SMS delivery | Synthetic | Everything in this reference application |

## Commands

### Build the JavaScript dependencies

Use the validated host Node 24.22.2 and frozen workspace dependencies. Build the
public JavaScript dependencies before cross-language Python checks:

```sh
pnpm --filter @livekit-ecosystem/channel-continuity build
pnpm --filter @livekit-ecosystem/delegation-specialist build
pnpm --filter @livekit-ecosystem/channel-policy-gateway build
```

### Compatibility checks

From the repository root, the existing compatibility checks are:

```sh
make channel-origin-unit
make channel-origin-plan
make channel-origin-check
make channel-origin-package-plan
make p2-prepared-read-plan
make p2-prepared-read-unit
make channel-policy-unit
make channel-policy-package-plan
make channel-policy-setup-plan
make channel-policy-python-plan
make channel-policy-native-worker-plan
make channel-policy-launch-plan
```

| Task | Command | Notes |
| --- | --- | --- |
| Origin unit tests | `make channel-origin-unit` | Python unit tests |
| Origin plan | `make channel-origin-plan` | Inert |
| Origin source check | `make channel-origin-check` | Real source command; needs the existing local PostgreSQL and API and creates owned disposable schemas |
| Origin package plan | `make channel-origin-package-plan` | Inert |
| Prepared-read plan | `make p2-prepared-read-plan` | Inert |
| Prepared-read unit tests | `make p2-prepared-read-unit` | Python unit tests |
| Prepared-read check | `make p2-prepared-read-check` | Creates one owned disposable P2 schema and verifies eight actual assertions |
| Channel-policy unit tests | `make channel-policy-unit` | Python unit tests and the gateway `test` script |
| Package plan | `make channel-policy-package-plan` | Inert |
| Setup plan | `make channel-policy-setup-plan` | Inert |
| Python plan | `make channel-policy-python-plan` | Inert |
| Native worker plan | `make channel-policy-native-worker-plan` | Inert |
| Launch plan | `make channel-policy-launch-plan` | Inert |

- These commands perform no provider, RTC or supplier call.
- The package check builds and consumes isolated artifacts. Its fake-port
  assertions are separate from actual database and media qualification.
- The native worker's internal `--config` entrypoint requires a trusted private
  per-room JSON file and live Parent and Node endpoints. The launcher creates both.

### Run the joined showcase

Run the complete application with the joined showcase targets:

```sh
make channel-policy-demo-build
make channel-policy-demo-setup CHANNEL_POLICY_PROFILE=$PWD/.local/showcase-1
make channel-policy-demo-start CHANNEL_POLICY_PROFILE=$PWD/.local/showcase-1
make channel-policy-demo-start-provider CHANNEL_POLICY_PROFILE=$PWD/.local/showcase-1
make channel-policy-demo-record CHANNEL_POLICY_PROFILE=$PWD/.local/showcase-1
```

| Task | Command | Notes |
| --- | --- | --- |
| Build | `make channel-policy-demo-build` | Builds the three JavaScript packages above |
| Prepare a profile | `make channel-policy-demo-setup CHANNEL_POLICY_PROFILE=$PWD/.local/showcase-1` | Prepares schemas, private configuration and the synthetic SMS sender association |
| Start in `scripted` mode | `make channel-policy-demo-start CHANNEL_POLICY_PROFILE=$PWD/.local/showcase-1` | Needs no provider keys |
| Start in `provider_real` mode | `make channel-policy-demo-start-provider CHANNEL_POLICY_PROFILE=$PWD/.local/showcase-1` | Passes `--provider`; makes paid Deepgram, OpenAI and ElevenLabs calls |
| Record the demo | `make channel-policy-demo-record CHANNEL_POLICY_PROFILE=$PWD/.local/showcase-1` | Records the narrated demo against a running showcase |

Each profile holds sixteen inputs, so prepare a new profile for each fresh
demonstration. The [root README](../../README.md) describes the browser steps and
provider keys.

## Validation

Each phase of the [0045 work item](../../docs/work-items/0045-joined-native-channel-policy.md)
has its own evidence. Keep each scope separate.

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Phase 45A gate | `make channel-origin-check`, `make p2-prepared-read-check` and the package check | Canonical import identity, positive/negative data transfer objects (DTOs), ownership and safe diagnostics, the actual fourteen-assertion origin regression after promotion, and rebuilt/installed root application compatibility | Passed |
| Phase 45B gate | Not yet available | Adds actual discovery, result, stale-route and restart evidence | Pending |
| Phase 45C gate | Not yet available | Adds real native/browser media | Pending |
| Phase 45D gate | Not yet available | Adds reproducible installed/container and final handoff checks | Pending |

New application commands for the pending gates are unavailable until their
asserted runners exist.

## Next milestone

| Step | Outcome | Gate |
| --- | --- | --- |
| Freeze the persisted discovery/execution gate | Installed and shared qualification repeated for the current composition | Frozen discovery/execution gate, then installed and shared qualification |
| Reduce per-scan cost with pooled per-job clients and cheaper current-result reads | Larger history windows keep interactive latency | None named yet |
| Broaden provider-mode evidence | Evidence beyond the selected journeys in [0046](../../docs/work-items/0046-joined-showcase-providers-and-demo.md) | None named yet |
