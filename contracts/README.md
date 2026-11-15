# Shared contracts

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | List the shared boundary fixtures, their producers and consumers, and the commands that check them |
| Audience | Engineers changing a fixture or one of its producers or consumers; coding agents |
| Scope | Language-neutral fixtures under `contracts`; excludes runtime services and project release gates |
| Owns | Shared producer/consumer fixture inventory, compatibility status and data-only ownership |
| Related | [Design](Design.md) · [Agent instructions](AGENTS.md) · [Shared architecture](../Design.md) · [Validation plan](../docs/validation-plan.md) |

## Overview

This directory holds small, language-neutral boundary fixtures that actual
producers and consumers test against. This README is for engineers who change a
fixture or one of its producers or consumers. [Design.md](Design.md) explains
the boundary rules in detail.

Keep this area small. It is not a fourth project or an application platform.
Fixtures define compatibility examples. They grant no scope, work or action
authority.

## Implementation status

| Capability | Status | Evidence |
| --- | --- | --- |
| Local transport | Implemented | Fixture, actual transport and browser/media observations remain separate |
| Business case | Implemented | Public state/consent boundaries; no permission is inferred from a fixture |
| Channel | Qualified | Selected channel/native/package gates are recorded in project handoffs |
| Delegation | Qualified | Selected source/installed contract and durable-v2 prerequisite gates passed in the linked project handoffs |
| Native policy view | Qualified | Selected source/installed native real-time communication (RTC) text and browser qualification passed in [0042](../docs/work-items/0042-responsive-native-policy-and-compact-demo.md); audio/provider evidence is separate |
| Result receiver | Qualified | Selected source storage/return and installed-artifact qualification passed in [0043](../docs/work-items/0043-stable-result-delivery-and-return-context.md) |
| Channel policy v3 | Qualified | Selected origin qualification is recorded in [0044](../docs/work-items/0044-origin-bound-channel-policy.md) |

### Fixtures

Fixture paths are relative to `contracts`.

| Fixture | Producer | Consumers | Purpose |
| --- | --- | --- | --- |
| `local-transport/diagnostics.json` | Python worker | Browser policy | Audio diagnostic JSON |
| `local-transport/text-echo.json` | Python worker | Browser policy | Complete UTF-8 text echo |
| `business/case-projection.json` | Control API | Console | Versioned case projection, decimal revisions and opaque exact confirmation |
| `channel/v1.json` | P2 Python and TypeScript producers | P2 Python and TypeScript decoders | Versioned message contracts |
| `delegation/v1.json` | P3 Python contracts and TypeScript specialist | The same two implementations | Versioned policy-v1 contract |
| `delegation/document-v1.json`, `document-adversarial-v1.json` and `documents/` | P3 Python and TypeScript specialist | The same two implementations | Versioned document-v1 contract and adversarial document data |
| `delegation/fixed-policy-v2.json` and `policies/` | P3 Python and TypeScript specialist | The same two implementations and the channel-policy application | Versioned fixed-policy-v2 contract |
| `delegation/native-policy-view-v1.json` | P3 native policy application | Console P3 background page | Bounded observation/session data transfer objects (DTOs) |
| `delegation/result-receiver-v1.json` | Public P1 producer | P2 result receiver and the channel-policy application | Exact P1 intent/receipt compatibility with P2 |
| `delegation/channel-policy-v3.json` | P2 TypeScript operation client | P3 Python v3 contracts and the application's P2 wire parser | Origin-bound channel-policy cases |

### Version and eligibility rules

- Source record version, semantic policy version, input/result schema version
  and read-view schema version are distinct.
- Preserve existing defaults when adding an explicit version.
- Native policy eligibility is bool or null. Missing or conflicting facts remain
  a clarification, never an invented negative policy decision.

### Business case projection fixture

`business/case-projection.json` is the language-neutral full-snapshot fixture
used by HTTP, native and browser boundary tests.

- Revisions and epochs are decimal strings.
- Confirmation is the original opaque canonical JSON.
- Bounded recent observations plus `projection_revision`, `cursor_reset` and
  `history_truncated` explain display limits.
- A native `continuity.observed` hint requests an authenticated read. It grants
  no scope, selection or consent.
- P3's separately bounded original request revision is not an authoritative
  current P1 case revision.

## Documentation

Read these before changing a fixture:

| Document | Purpose |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Coding rules for shared fixtures |
| [Design.md](Design.md) | Boundary rules in detail |
| [Shared architecture](../Design.md) | Shared data flow, state authority, interfaces and failure boundaries |
| [Validation plan](../docs/validation-plan.md) | Test lanes, required fault scenarios and evidence sufficiency |
| The relevant project charter: [P1](../docs/projects/agent-continuity-scope.md), [P2](../docs/projects/channel-continuity-scope.md) or [P3](../docs/projects/delegation-reliability-scope.md) | Project requirements and stable acceptance IDs |

Work items own exact observed test results. These fixtures do not imply full
project release or real-model qualification.

## Requirements

| Requirement | Version or value | Notes |
| --- | --- | --- |
| Python and pnpm environments | Frozen | Set up as the [root README](../README.md) describes |
| Provider keys | None | Offline fixture checks require none |
| Docker daemon | None | Offline fixture checks require none |
| Microphone | None | Offline fixture checks require none |
| Real storage, RTC and installed-consumer gates | Their own explicit prerequisites | See the owning project commands |

## Commands

From the repository root:

```sh
.venv/bin/python -m unittest discover -s tests -p test_rtc_agent.py -v
pnpm test
make check
```

| Task | Command | Notes |
| --- | --- | --- |
| Run the transport diagnostic fixture tests | `.venv/bin/python -m unittest discover -s tests -p test_rtc_agent.py -v` | Covers only the transport diagnostic fixtures |
| Run the workspace TypeScript tests | `pnpm test` | Frontend tests; run them for consumer changes |
| Run the shared fast gate | `make check` | Must keep passing after a contract or rule change |

A diagnostic-only command does not qualify product contract changes. Use the
project commands linked from the [root README](../README.md) for affected
channel, delegation and package gates.

## Validation

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Producer evidence | Owning producer tests; transport: `.venv/bin/python -m unittest discover -s tests -p test_rtc_agent.py -v` | Actual producer output matches the shared valid examples | Implemented for the current fixtures |
| Consumer evidence | Owning consumer tests; TypeScript: `pnpm test` | Both language consumers reject invalid input and accept useful valid progress | Implemented for the current fixtures |
| Native observation rules | Owning application tests | Original identities, commit disposition, token privacy and actual close | Selected held-work RTC text journey passed in [0042](../docs/work-items/0042-responsive-native-policy-and-compact-demo.md) |
| Shared fast gate | `make check` | Structural and language checks still pass | Required after a contract or rule change |

### Producer and consumer evidence

1. Assert actual producer output against the shared valid examples.
2. Exercise both language consumers with unsupported versions, malformed,
   duplicate or extra fields, wrong scope or source identity, size boundaries
   and useful valid progress.

Loading or round-tripping the same fixture twice is insufficient producer
evidence. Synthetic session samples contain no real credential and do not prove
a valid RTC grant.

### Native observation rules

- Native observations preserve the original request, work, attempt and result
  identities and the commit disposition, independently of current as-of
  applicability.
- Application read time is not authority time.
- RTC presence, software development kit (SDK) waiting and local ownership are
  not a result, delivery receipt or consent.
- Test token privacy, abandoned reads and actual close through the owning
  applications.

## Next milestone

The native observation/session producer, strict browser consumer and selected
held-work RTC text journey passed in
[0042](../docs/work-items/0042-responsive-native-policy-and-compact-demo.md).
The [result-delivery seam](../docs/work-items/0043-stable-result-delivery-and-return-context.md)
adds exact P1 intent/receipt compatibility with P2. Its selected source
storage/return and installed-artifact qualification passed.

| Step | Outcome | Gate |
| --- | --- | --- |
| Complete P3-I19 and P2-I22 | Both tasks complete; the 0043 seam contributes but completes neither task or a charter row | Their task gates in the [granular roadmap](../docs/implementation-plan.md) |
| Full charter, joined audio and live-model work | Product evidence beyond fixture compatibility | Separately gated |

Keep fixtures small and paired with real implementations.
