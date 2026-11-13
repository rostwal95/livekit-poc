# P1 Phase H3 standalone package and public API

Status: Completed
Last reviewed: 10 November 2026

## Behavior and scope

Complete P1-I26 with a genuine standalone agent-continuity distribution consumed by
the native service, rather than publishing the foundation application as a library.
Move the single canonical continuity_lab source into the project src tree while
preserving every import/module entrypoint and stored schema/payload identity. Add
explicit typed public inquiry and authenticated managed-case surfaces, a PEP 561
marker, standalone installed examples and independent API/failure review.

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P1-I26 artifact | Pinned Python 3.14 workspace and one canonical core source | Build wheel/sdist and rebuild the sdist | No service/harness or checkout path dependency in P1 wheel; declared extras only | Fresh isolated consumers execute original M1 and actual inquiry/result/replay | Direct/rebuilt archive payload comparison and three isolated environments |
| P1-I26 public client | Explicit validated actor/token/settings and ACTIVE v4 runtime role | Submit/read/cancel or separate trusted controller action | No actor/scope/callable overrides, no DDL, exact separate consent remains | Native consumer uses the public facade; valid work and foreign-scope rejection hold | Positive/negative unit, actual PGv3/v4 and same-image native/browser gates |
| P1-I26 resource/error contract | A real held synchronous operation and cancelled waiter | Close/cancel/capacity/error occur | Actual worker retains its finite slot and original exception; no false business cancellation | Useful operation completes and owned close eventually drains | Installed thread example and negative privacy fixtures |

## Interfaces and ownership

Canonical source is projects/agent-continuity/python/src/continuity_lab. The root
application owns services and depends on the locked workspace member; no duplicate
root source or compatibility shadow remains. The migration checkpoint preserved fifty-three original module contents; the
package docstring and new public modules were explicit changes. Subsequent
provider tracing changes are separately verified. The source move is backed up and hash-checked before removing
the original directory. Public imports/data/CLI stay compatible.

continuity_lab.api is the dependency-free inquiry boundary; postgres_api owns a
credential-bound typed managed client with read-only ACTIVE v4 startup validation;
testing exposes explicit synthetic inquiry fixtures. postgres/telemetry extras use
the existing exact dependency pins. The root/member declare Python 3.14 support,
matching executed evidence rather than advertising untested interpreter versions.
The migration resolution preserved the existing registry versions; the later
optional provider slice adds its explicitly pinned plugins separately.

## Failure cases and validation

Reject malformed archives, unexpected packages/dependencies/type markers, escaped
paths/links/oversized payloads, source injection and missing backend setup. The
package gate records fixed codes and hashes, removes private raw build/consumer
capture, preserves the validated archives and separates payload equality from
byte-identical archive reproducibility. Missing dependencies/models/credentials,
required skips/zero tests/timeouts and cleanup failures remain non-passing.

| Gate | Applicable and why | Exact tests/assertions | Prerequisite/resource/time bound | Expected status/artifacts |
| --- | --- | --- | --- | --- |
| G-FAST/CONTRACT | New public API, packaging and actual consumer | Typed request/auth/error/cancel/close, archive/metadata negatives, unchanged M1 types | Offline unit discovery plus full maintained types/lint/format | Nonzero tests, zero required skips |
| G-PACKAGE | Standalone reproducible installation | Direct wheel/sdist/rebuilt payload, actual legacy/inquiry/worker CLI and independent consumers | Pinned build backend/cache, fresh no-system-site venvs with isolated imports | Bounded gate and retained validated archives, no source injection |
| G-DURABLE | Public factory version/authority | ACTIVE v3 rejection without any state change; ACTIVE v4 positive leased inquiry/replay/foreign scope | Actual isolated owner/runtime PostgreSQL and supplier | Real assertions pass, no serving DDL |
| G-MEDIA | Genuine native consumer | Original three bound model tools/readiness/End and exact controller approval | Installed application/library image and real browser/RTC | Same-image inspected run, preserved closed evidence |
| G-RELEASE | Honest supported platforms and scope | Python 3.14 macOS host plus Linux container installed artifact; full P1 assessment separately | Actual executions, not CI YAML alone | Independent API review plus remaining I27/I28/platform evidence |

## Results and handoff

P1-I26 is complete for the tested Python 3.14 macOS and Linux ARM64 environments.
The final host artifact gate passed eighteen commands across three fresh isolated
virtual environments. All fifty-eight package payload files match the source,
direct wheel, sdist and rebuilt wheel. Original M1 and inquiry/worker CLI checks,
public consumer examples, metadata/type-marker checks and owned cleanup passed.
This establishes payload equality, not byte-identical archive reproducibility.

The Linux installed-wheel gate passed both consumers in 4.266 seconds with network
disabled, no checkout mount and verified cleanup. Independent API/failure review
passed, including a genuinely held thread and preserved exception/cancellation
semantics. The real PostgreSQL suite passed 258 tests, including positive ACTIVE v4
and refused ACTIVE v3 public-factory checks. The four later business-bootstrap
PostgreSQL tests passed separately without changing the serving M1 source.

The rebuilt installed native consumer passed six actual scripted browser cases,
including audio playback, interruption/recovery, durable work, exact controller
confirmation, inspected traces and cleanup. All eighty-two installed core/service
source hashes match the current checkout. Retained M1 intake kept its original
identity after the auxiliary business bootstrap. Evidence is retained under ignored
.local/validation/p1-package, p1-provider-scripted-diagnostic and
p1-business-bootstrap directories.

This closes the package/API/consumer work item. The combined P1 release still
requires the selected real-provider P1-20 run and final release assessment.
Provider keys and actual provider/media qualification are tracked in the
[provider work item](0018-p1-provider-demo.md). Remote CI and publishing remain
outside the user-approved local POC scope.
