# Shared contracts

Status: Active
Last reviewed: 12 November 2026

## Overview

Language-neutral boundary fixtures consumed by actual producers and consumers.
Keep this area small; it is not a fourth project or an application platform.
Fixtures define compatibility examples and grant no scope, work or action authority.

## Implementation status

| Boundary | Current fixtures and consumers | Qualification scope |
| --- | --- | --- |
| Local transport | Audio diagnostic JSON and complete UTF-8 text echo; Python worker and browser policy | Fixture, actual transport and browser/media observations remain separate |
| Business case | Versioned case projection, decimal revisions and opaque exact confirmation; control API and console | Public state/consent boundaries; no permission inferred from a fixture |
| Channel | Versioned message contracts and Python/TypeScript producer/decoder fixtures | Selected channel/native/package gates are recorded in project handoffs |
| Delegation | Versioned policy-v1, document-v1 and fixed-policy-v2 contracts and adversarial document data | Selected source/installed contract and durable-v2 prerequisite gates passed in the linked project handoffs |
| Native policy view | Bounded observation/session DTOs implemented in [0042](../docs/work-items/0042-responsive-native-policy-and-compact-demo.md) | Selected source/installed native RTC text and browser qualification passed; audio/provider evidence is separate |

Source record version, semantic policy version, input/result schema version and
read-view schema version are distinct. Preserve existing defaults when adding an
explicit version. Native policy eligibility is bool or null: missing/conflicting
facts remain clarification, never an invented negative policy decision.

## Documentation

Read [AGENTS.md](AGENTS.md), [Design.md](Design.md), the
[shared architecture](../Design.md), [validation plan](../docs/validation-plan.md)
and the relevant project charter. Work items own exact observed test results;
these fixtures do not imply full project release or real-model qualification.

## Requirements

Use the frozen Python and pnpm environments from the root README. Offline fixture
checks require no provider keys, Docker daemon or microphone. Real storage, RTC
and installed-consumer gates have their own explicit prerequisites.

## Commands

From the repository root:

```sh
.venv/bin/python -m unittest discover -s tests -p test_rtc_agent.py -v
pnpm test
make check
```

Use the project commands linked from the root README for affected channel,
delegation and package gates. A diagnostic-only command does not qualify product
contract changes.

## Validation

Assert actual producer output against shared valid examples, then exercise both
language consumers with unsupported versions, malformed/duplicate/extra fields,
wrong scope/source identity, size boundaries and useful valid progress. Loading or
round-tripping the same fixture twice is insufficient producer evidence. Synthetic
session samples contain no real credential and do not prove a valid RTC grant.

Native observations preserve original request/work/attempt/result identities and
commit disposition independently of current as-of applicability. Application read
time is not authority time. RTC presence, SDK waiting and local ownership are not
a result, delivery receipt or consent. Test token privacy, abandoned reads and
actual close through the owning applications.

## Next milestone

The native observation/session producer, strict browser consumer and selected
held-work RTC text journey passed in 0042. The [result-delivery seam](../docs/work-items/0043-stable-result-delivery-and-return-context.md) adds exact P1 intent/receipt compatibility with P2; its actual storage and
installed qualification remain pending. Keep fixtures small and paired with real
implementations. Full charter, joined audio and live-model work remain separately gated.

## Business projection fixture

business/case-projection.json is the language-neutral full snapshot fixture used
by HTTP/native/browser boundary tests. Revisions/epochs are decimal strings;
confirmation is original opaque canonical JSON. Bounded recent observations and
projection_revision, cursor_reset and history_truncated explain display limits.
A native continuity.observed hint requests an authenticated read; it grants no
scope, selection or consent. P3's separately bounded original request revision is
not an authoritative current P1 case revision.
