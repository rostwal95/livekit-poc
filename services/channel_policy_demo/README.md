# Joined channel-policy application

Status: Active
Last reviewed: 13 November 2026

## Overview

An opt-in root application composes P2 native/channel continuity and origin-bound
P3 policy work through P1's existing public authority. The intended experience is
one responsive conversation, durable background work during dormancy, signed
simulated SMS and a returning current-result view.

## Implementation status

The joined application is under implementation. Phase 45A qualified the canonical
origin, public prepared read and installed application contracts. Phase 45B now
adds the worker client, source-attested native/SMS router, public client factories,
guarded job delivery, versioned private profile and Python source/executor owner.
Focused tests and independent reviews cover their stated boundaries.

The Python owner starts its case and two origin listeners first. Node starts its
read/result listeners before its two intake gateways. The executor starts only
after Node readiness. Accepted inputs and work remain in the existing P2/P1
stores; the private profile preserves configuration and stable owner identities.
Normal stop does not reset either store.

Explicit bootstrap succeeds against fresh P1/P2 schemas, and the launcher runs
the complete joined journey locally: native text and recorded voice, durable
dispatch, background policy results, End, signed simulated SMS and rejoin. The
explicit provider_real mode runs the same journey with Deepgram, OpenAI and
ElevenLabs; three consecutive actual journeys dispatched every input on the first
attempt, and the narrated demo video was recorded from it
([0046](../../docs/work-items/0046-joined-showcase-providers-and-demo.md)).
Concurrent current-result readers share one scan; the executor paces idempotent
reruns; background readers keep one of the two shared reader slots free for
dispatch; inspections keep a reserved job ticket. The completed
[0044 checkpoint](../../docs/work-items/0044-origin-bound-channel-policy.md)
retains its separate source and installed evidence. Selected actual journeys do
not complete joined installed/container qualification or charter release.

## Parent and operator components

The Parent room owner and separate operator HTTP boundary are implemented. The
launcher composes them from an existing prepared profile in scripted mode or,
with `--provider`, in provider_real mode; only each room's native worker receives
the provider keys.

One physical activation retains its original Start command and 180-second expiry.
SDK disconnect fences readiness immediately; final resource drain and actual
worker reap remain required before another room. End preserves the independently
running background executor and separately authorized dormant SMS/read surface.

The optional browser uses an explicit RAM-only operator credential through the
fixed local proxy. All routes below are POST under /v1/channel-policy-demo/;
responses use no-store. Input scope and sender are configured by the owner.

| Route | Request and observation |
| --- | --- |
| status | Version-only request; Parent lifecycle tuple, independent Node cursor and as-of readiness |
| start | Original Parent epoch, expected generation and command UUID; RTC-only grant |
| end | Exact Parent epoch/generation/original Start command; room closure observation |
| current | Exact activation tuple; five current-result facts, with a final room check before socket write |
| case | Version-only request; independently observed current revision/time |
| progress | Version-only request; bounded original P2 source/dispatch counts, not execution completion |
| sms | Original command UUID/body/time; fixed signed synthetic provider input and actual P2 receipt |

The operator listener retains at most four actual calls and eight sockets. Header
and body reads each have a one-second limit, input is at most 32768 bytes, output
16384 bytes and the command observer at most fifteen seconds. A timed-out command
can remain accepted/unknown; it is never silently retried under a new identity.
The native prepare and worker callback profiles retain their original contracts.

## Documentation

- [Design](Design.md) and [coding instructions](AGENTS.md).
- [Implementation work item](../../docs/work-items/0045-joined-native-channel-policy.md)
  and the [provider, hardening and demo follow-up](../../docs/work-items/0046-joined-showcase-providers-and-demo.md).
- [Local setup](../../local-setup/README.md), [validation](../../docs/validation-plan.md)
  and [provider operations](../../docs/provider-demo.md).

## Requirements

Use the repository's frozen Python/TypeScript/runtime dependencies and existing
Docker PostgreSQL/LiveKit. Explicit owner bootstrap and a declared root runtime
extra are required before application serving. Provider keys remain private and
are unnecessary for scripted/offline qualification. All business data and SMS
delivery in this reference application are synthetic.

## Commands

Use the validated host Node 24.22.2 and frozen workspace dependencies. Build the
public JavaScript dependencies before cross-language Python checks:

```sh
pnpm --filter @livekit-ecosystem/channel-continuity build
pnpm --filter @livekit-ecosystem/delegation-specialist build
pnpm --filter @livekit-ecosystem/channel-policy-gateway build
```

From the repository root, existing compatibility checks are:

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

The real source command needs the existing local PG/API and creates owned
disposable schemas. make p2-prepared-read-check creates one owned disposable P2
schema and verifies eight actual assertions. These commands perform no provider,
RTC or supplier call. The package check builds and consumes isolated artifacts;
its fake-port assertions are separate from actual database/media qualification.
The plan commands are inert. The native worker's internal --config entrypoint
requires a trusted private per-room JSON file and live parent/Node endpoints; the
launcher creates both. Run the complete application with the joined showcase
targets:

```sh
make channel-policy-demo-build
make channel-policy-demo-setup CHANNEL_POLICY_PROFILE=$PWD/.local/showcase-1
make channel-policy-demo-start CHANNEL_POLICY_PROFILE=$PWD/.local/showcase-1
make channel-policy-demo-start-provider CHANNEL_POLICY_PROFILE=$PWD/.local/showcase-1
make channel-policy-demo-record CHANNEL_POLICY_PROFILE=$PWD/.local/showcase-1
```

Setup prepares schemas, private configuration and the synthetic SMS sender
association. Each profile holds sixteen inputs, so prepare a new profile for each
fresh demonstration. The root README describes the browser steps and provider keys.

## Validation

45A requires canonical import identity, positive/negative DTOs, ownership and
safe diagnostics, the actual fourteen-assertion origin regression after promotion,
and rebuilt/installed root application compatibility. 45B adds actual discovery,
result/stale-route/restart evidence; 45C adds real native/browser media; 45D adds
reproducible installed/container and final handoff checks. Keep each scope separate.

## Next milestone

Freeze the persisted discovery/execution gate and repeat installed/shared
qualification for the current composition. Then reduce per-scan cost (pooled
per-job clients, cheaper current-result reads) so larger history windows keep
interactive latency, and broaden provider-mode evidence beyond the selected
journeys in 0046.
