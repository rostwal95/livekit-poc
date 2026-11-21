# Demo-first LiveKit portfolio repository

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Build and verify an independently shareable LiveKit continuity demonstration |
| Audience | Portfolio reviewers and engineers reproducing the local demo |
| Scope | Selected continuity and operator flows, fresh database baseline, Compose, documentation and recording |
| Owns | Extraction plan, acceptance criteria and observed handoff |
| Related | [Portfolio README](../../README.md) · [Architecture](../architecture.md) · [Demo walkthrough](../demo.md) |

## Behavior and scope

Create a separate repository with fresh Git history for a reviewer with Docker
Compose and a browser. Show browser text and recorded voice, simulated SMS with
the room closed, and rejoin with the same durable case and delegated policy
result. Show a second case with revision-bound quote approval, one synthetic
supplier effect and a completion receipt. This work contributes selected
evidence to the reference release work package (PLAN-22). The reference retains
the full migration, experimental profile and qualification history.

The reference audit passed `make check`, the 2,072
TypeScript tests, the catalog and documentation checks, and a fresh showcase
build. The portfolio copy requires fresh database, container and media evidence.

### Criteria

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| Fresh install | Empty owned PostgreSQL volume | Owner installs baseline 1 | Runtime cannot apply DDL; drift blocks startup | Three schemas, stable identities and ready services | Real catalog, roles and restart checks |
| Channel continuity | Signed test sender and local LiveKit | Type, publish a recorded clip, End, send SMS and rejoin | Original inputs retain distinct stable receipts | Same case and current result appear after rejoin | Browser, RTC playback and durable reconciliation |
| Quote confirmation | Separate synthetic case | Approve the exact current quote | Replays and stale revisions cannot duplicate effects | Supplier outcome and receiver acceptance are visible | Browser and independent ledgers |
| Lifecycle | New owned Compose project | Build, start, stop, restart or explicitly reset | Only the new project and its state are eligible | Clean stop and fresh reset remain repeatable | Compose, process exit and volume evidence |
| Reviewer snapshot | Selected source and fixtures | Create fresh local Git history | Private files, credentials and build outputs stay private | README, design and recording reproduce the demonstrated behavior | Tree scan, docs check and recording review |

## Interfaces and ownership

| Component | Path | Responsibility | Status |
| --- | --- | --- | --- |
| Three continuity libraries | `projects/` | Case, channel and delegated work contracts | Extracted and tested |
| Joined runtime and browser | `services/` and `apps/local-console/` | LiveKit rooms, gateway, policy execution and exact confirmation UI | Verified on one browser origin |
| Baseline initializer | `local-setup/scripts/demo_runtime.py` and project stores | Direct final-layout installation, grants and stable seed state | Verified on PostgreSQL |
| Compose lifecycle | `compose.yaml` and `demo` | `up`, `key`, `verify`, `down` and confirmed `reset --yes` | Verified from the committed tree |
| Reviewer documentation | `README.md` and `docs/` | Captioned recording, runnable steps and architecture diagrams | Reviewed and rendered |

The new local database uses separate booking, work and channel schemas with one
fresh baseline. The owner initializes the schema and validates it before serving.
Retain final lease, retry, original-input and result-delivery semantics. Wire
versions, case revisions and lease epochs retain their distinct meanings. Use
synthetic fixtures and keep supplier and receiver ledgers independent.

## Failure cases and validation

| Gate | Applicable and why | Exact tests/assertions | Prerequisite/resource/time bound | Expected status/artifacts |
| --- | --- | --- | --- | --- |
| G-FAST and G-CONTRACT | Curated public dependencies and interfaces | Test frozen inputs, conflicts, lease, applicability, receiver binding and exact confirmation | Locked Python and TypeScript image toolchains | Sanitized test totals and failures |
| G-DURABLE | Fresh PostgreSQL baseline | Compare catalogs; test repeat setup, rollback, DDL denial, drift and restart | Owned synthetic volumes only | Stable identities, explicit failure codes and independent ledgers |
| G-MEDIA | Docker-only reviewer flow | Follow the README, observe actual playback, complete the three-input journey and exercise shutdown | Local LiveKit and Chromium | Browser assertions and a reviewed captioned recording |
| G-RELEASE | Local reviewer handoff | Validate links and Mermaid, inspect fresh history and test explicit reset | New local repository and its scoped Compose project | Snapshot digest, platform and gate status |

## Results and handoff

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Reference fast lane | `make check` | Current Python, lint, types and structural baseline | Passed before extraction |
| Reference TypeScript | `corepack pnpm test` | Four workspace suites | 2,072 passed before extraction |
| Portfolio Python and TypeScript | `python -m pytest -q tests` and retained package Vitest suites | Selected offline and loopback checks | 917 Python and 1,412 TypeScript tests passed |
| Baseline | Real PostgreSQL catalog and role probes, including `database/check_baseline.py` | Final layout parity, repeat setup, runtime DDL denial, stable identities, drift refusal, stale quote and lease takeover | Passed |
| Browser and media | `node apps/local-console/scripts/record-channel-policy-demo.mjs .local/recording-verified` | Real LiveKit playback, text, recorded voice, simulated SMS, rejoin and exact approval | Passed. Captioned H.264/AAC recording is 92.12 seconds |
| Independent state | `./demo verify` before and after `./demo down` and `./demo up` | Three inputs and three result deliveries across two rooms, one supplier effect and one receiver receipt | Passed with the same identity digest after restart |
| Active shutdown | Start a recorded turn in Chromium, then run `./demo down` | Graceful closure and observed process-group absence | Passed for specialist, gateway and UI |
| Clean checkout and reset | `./demo up` and `./demo reset --yes` in an independent clone with host Node and Python off the path | Source build, authenticated fresh profile and removal of exactly the owned demo containers and volumes | Passed on macOS 27.2.1 arm64, Docker Engine 29.9.3, Compose 5.7.0 and Chromium |
| Documentation and tree | Render three Mermaid blocks, check local links and scan reachable Git files | Reviewer navigation and shareable content | All three rendered, 20 links resolved and no matched key signatures or excluded artifacts |

The portfolio repository is `continuity-livekit-demo`. Its initial snapshot
contains 504 files, including the recording
and poster. The complete video decodes without errors. The state digest before
and after restart is
`f56b15dd208c97c7f0c3f661a6cd8778e387fdb8d7385376486959729c42b808`.

An initial browser text turn had an unknown outcome. The completed fresh run
observed all three intended inputs. The guide explains how to reconcile the
same text identity. The clean-clone check also exposed owner-only source modes,
so the final image assigns its application files to its non-root runtime user.

The verified demo projects were reset after validation. The owner creates the
hosted repository and makes the project-wide license decision.
