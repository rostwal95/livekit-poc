# Bounded channel workload profile

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Describe the opt-in I19 bounded workload study, its fixed schedule and how to read its results |
| Audience | Engineers who run or change the P2 workload study; coding agents |
| Scope | Fake-SMS intake, persisted processing, overload, restart and dormant conversations through public P2 ports; excludes production capacity claims |
| Owns | I19 workload schedule, run budgets, study ceilings and quantitative interpretation |
| Related | [Project guide](README.md) · [Workload manifest](workloads/bounded-v1.json) · [0039 handoff](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md) · [Validation plan](../../docs/validation-plan.md) |

## Overview

The opt-in I19 workload profile exercises retained fake-SMS intake, persisted
processing, overload, process restart and dormant conversations through public P2
ports.

| Capability | Status | Evidence |
| --- | --- | --- |
| I19 bounded workload profile | Qualified | [0039 handoff](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md) |
| Complete P2 charter acceptance (all seventeen rows) | Planned | [V1 charter](../../docs/projects/channel-continuity-scope.md) |

- The fixed declaration is [bounded-v1.json](workloads/bounded-v1.json).
- [Work item 0039](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md)
  records the selected qualification and remaining release boundaries.
- This experiment does not establish production capacity, speech/model latency,
  carrier behavior or complete P2 charter acceptance.
- The I20 joined UI is a separate gate.

## Commands and ownership

### Running the plan and check

Run from the repository root with the pinned local toolchain and existing stack:

| Task | Command | Notes |
| --- | --- | --- |
| Declare the fixed schedule | `make p2-workload-plan` | Validates the manifest; starts no child |
| Run the actual workload | `make p2-workload-check` | Needs an already running restricted-role local stack |

```sh
make p2-workload-plan
make p2-workload-check
```

The plan command validates the fixed manifest and prints its digest, seed policy,
twenty-four named groups and budgets. It does not load stack settings, compile,
connect to PostgreSQL or LiveKit, or start a child.

The actual command requires an already running restricted-role local stack.

- It never starts, resets or upgrades application state.
- It creates only fresh UUID-owned schemas and an ephemeral private application
  directory.
- Owner and runtime credentials enter separate closed child environments.
- LiveKit API credentials stay in the parent, which only reads room inventory. No
  workload child can allocate a room or join an agent.

### Run budgets

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Parent total | 360 seconds | Whole run | Reserves twenty seconds for cleanup |
| Commands | Sixteen | Fixed normal schedule | Within a maximum of thirty-two |
| Child stream | 8192 bytes | Each child stream | None |
| Captures | 512 KiB | Total captures | None |
| Direct JSON proof | 2 MiB | Each direct JSON proof | None |
| Retained artifacts | 16 MiB | All retained artifacts | None |
| Final report | 32 KiB | Final report | None |

### Failure handling and cleanup

- Commands are declared before measurement. Setup, missing progress, deadline,
  evidence and cleanup failures remain failures.
- New host commands own a verified process group, including non-detached compiler
  descendants. This host-tooling helper is shared with the image gate. It adds no
  P3 product dependency.
- Raw exception bodies and credentials are not public diagnostics.
- An unresolved child retains its private work and prevents dependent schema
  removal.
- An interrupted container-side backup/restore remains uncertain after its host
  Docker CLI is reaped. Schemas and private backup/work are therefore retained with
  cleanup false, rather than claiming remote drain.

### Seed and study ceilings

The public fixed schedule seed is 39. It determines fixed offer labels and order. A
separate private nonce derives synthetic authentication and identity material.

The study ceilings are fixed before measurement:

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Process RSS | 512 MiB | Sampled process | Study ceiling |
| Maximum observed event-loop delay | 1000 ms | Sampled process | Study ceiling |
| Accepted admission | 5000 ms | Accepted admissions | Study ceiling |
| Useful fake-operation completion | 15000 ms | Useful fake operations | Study ceiling |

Crossing a ceiling fails this profile. It is not a production service-level
agreement (SLA). No threshold may be tuned after a failed normal run.

## Active schedule

### Retained capacity

The capacity schema retains at most sixty-four inputs. This is a lifetime retained
row limit, not a queue-depth or dynamic backlog limit. Dispatched inputs still
consume capacity, and completion does not make space for a new identity.

The sequence fills that capacity:

| Phase | Inputs |
| --- | --- |
| Steady | Sixteen |
| Admitted burst | Four |
| Slow/progress | Four |
| Fill | Forty |

### HTTP admission, replay and conflicts

- Four additional burst HTTP requests are rejected before acceptance while four
  requests remain admitted.
- One admitted HTTP caller abandons its socket. The underlying SQL work stays owned,
  and a later equal request must recover the original committed receipt.
- Changed content under the same identity conflicts. Two distinct IDs carrying the
  same text remain distinct inputs.

### Gateways, pools and SQL capacity

Two tenant-specific gateways share the schema. Each gateway owns an inbox pool and a
dispatch pool, each with two connections and four retained SQL operations.

| Scope | Connections | SQL operations |
| --- | --- | --- |
| One pool | 2 | 4 |
| Configured aggregate across four pools | 8 runtime connections | 16 |
| Parent admission locker and read-only observer during the burst proof | 2 additional control connections | Not applicable |
| Possible total in this isolated topology | 10 | Not applicable |

- The control connections' public backend identities and actual closure are
  retained separately from runtime pool observations.
- Each dispatcher retains at most two adapter tasks. The persisted claim limit of
  two is shared across workers in this schema. These are different scopes.
- In sampled pool fields, `occupied` means checked-out plus queued SQL operations,
  `total` counts open database connections and `waiting` counts queued connect
  calls. These quantities are not interchangeable.
- Held adapter calls and original receipts are observed independently.
- A private application wrapper captures public PostgreSQL backend IDs from acquired
  clients. The parent binds the exact child PID, schema and backend IDs to one real
  admission-lock graph with two waiters.

### Slow agent and lost responses

- A deliberately slow agent ignores cancellation. Caller timeout does not free its
  actual task.
- Releasing one tenant's held call must permit useful work from another admitted
  scope while the other held task remains. This proves selected progress, not a
  general fairness or per-tenant resource reservation guarantee.
- A known fake operation whose response is lost remains uncertain until a fresh
  process performs lookup-only reconciliation of the original immutable
  plan/key/digest.
- The fake operation ledger is independent of the P2 database. No P1 supplier or
  provider is called.

### Behavior at capacity

- At capacity, equal replay and scoped history remain available, changed content
  still conflicts, and new growth is rejected.
- A display window keeps the latest four public history cards and evicts older
  cards. The original payload, receipt, operation key and replay protection remain
  durable.
- There is no physical identity pruning, deletion, retention time to live (TTL) or
  reclaimed-capacity claim.

## Dormant schedule

### Seeding dormant conversations

The dormant schema permits 1024 retained inputs and 1024 challenges, associations
and senders. It receives one real public association and input for each of one
thousand conversations, five hundred per tenant.

- Credential windows contain at most sixty-four fixed public `SeededAccounts`
  entries, with each reader closed before the next opens.
- The experiment does not widen the production sixty-four entry constructor cap or
  seed SQL rows around authentication.

### Dormant observations

- Resource observations are taken at zero, sixty-four, 256 and one thousand dormant
  inputs.
- All one thousand original receipts are inspected through bounded public
  credential windows.
- No room, agent, timer or task is created per dormant case.
- The parent reads selective forwarding unit (SFU) inventory before seeding, at one
  thousand and after useful progress. Inventory is an allocation observation, not
  media qualification.

### Waking dormant cases

Two original dormant cases wake through the normal persisted dispatcher, and each
accepts one genuine new input. The final inventory is 1002 retained inputs: four
dispatched and 998 pending.

Pending, running, uncertain, blocked, exhausted and dispatched states are
reconciled separately. Retained input count alone does not prove completed
processing.

## Telemetry and quantitative interpretation

### Ordinary observer telemetry

`ChannelInbox.telemetryMetrics()` returns exactly `observerPending`,
`observerDropped` and `observerFailures` for ordinary inbox notifications.

- An ordinary callback slot is reserved before invoking user code and retained until
  its actual returned promise settles.
- Eight outstanding ordinary callbacks cause later notifications to be dropped
  without blocking useful SQL work.
- The existing communication observer has its own separate eight-slot lane and
  metrics.
- Existing `metrics()` and `communicationMetrics()` field sets are preserved.

### Observer transport ownership

The injected observer transport belongs to the application. SQL close neither closes
that transport nor claims its callback work drained, and pending callbacks stay
visible after SQL close. The workload releases every held application callback,
observes actual settlement and records final counters, including any dropped close
notification, before claiming cleanup.

### Latency and resource samples

- Latency cohorts use nearest-rank quantiles and report count, p50 and maximum
  (`maximumMs`) in milliseconds.
- A p95 is present only for cohorts with at least twenty samples. Steady, burst and
  slow observations are not relabelled as larger populations.
- Process resource samples identify RSS, heap and external memory in bytes and CPU
  user/system time in microseconds.
- Two gateways run in one Node process. RSS includes the runtime baseline and is not
  divided by case count or presented as per-case RAM, PostgreSQL memory or
  deployment scale.
- Configured limits and observed maxima remain distinct.

## Recovery and restore

The application gracefully stops and reopens against the same PostgreSQL volume. A
separate owner-only populated `pg_dump`/drop/`psql` restore covers both allocated
schemas.

- Fresh public readers verify every original receipt, canonical body, scoped
  sequence, operation key and processing state.
- The fake operation ledger must not gain another logical acceptance.
- Parent SQL snapshots and independent joins bind original receipts and plans to the
  external ledger. Sorted-key compact ASCII JSON hashes are reproducible from
  retained snapshot files.

No automatic sender retry follows an unknown external effect, no playback fact
becomes consent, and no workload receipt creates a business-action owner.

## Validation and evidence

The [0039 handoff](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md)
records the selected qualification. All listed gates passed with complete cleanup.
The full compatibility batch uses fresh reports rather than reusing focused runs.

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Local workload | `make p2-workload-check` | The declared active, restart, restore and dormant schedule through public ports | Passed (0039) |
| Installed npm | Recorded in the [0039 handoff](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md) | Public PostgreSQL/HTTP use of the installed package | Passed (0039) |
| Installed Python | Recorded in the [0039 handoff](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md) | The installed Python distribution and its public types | Passed (0039) |
| Fresh compatibility | Recorded in the [0039 handoff](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md) | Original validators still pass with complete cleanup | Passed (0039) |

### Selected qualification results

| Proof | Observed result |
| --- | --- |
| Local workload | 24 groups, sixteen owned commands, 81.819 seconds; 1000 dormant conversations and 1066 original inputs/68 fake operations preserved across restore |
| Installed npm | Seven stages, 2.680 seconds; public PostgreSQL/HTTP with supplied synthetic case, operation and communication ports |
| Installed Python | 113 unadapted tests, fifteen commands, 39.255 seconds; nine runtime payloads, offline default/native imports and public types |
| Fresh compatibility | 187 assertions in eleven serial lanes, 139.105 seconds; original validators, complete cleanup and settled owned process groups |

Quantitative observations from the sampled Node process:

| Observation | Value |
| --- | --- |
| Resident set size (RSS) | 236693808 bytes |
| Maximum event-loop delay | 28.869 milliseconds |
| Useful completion | 63 operations, with a 2578.128 millisecond maximum |

RSS includes the runtime baseline and both gateways in that process. These
observations are not per-case memory or deployment capacity. The handoff retains
exact cohort sizes, quantile policy, queue ages, restart lag and source-qualified
artifacts.

- The I20 joined UI and all seventeen complete P2 charter rows retain separate
  gates.
- Existing I12–I18 gates and isolated archive consumers keep their own scopes.
- The fifty-five scenario definitions, twenty-four registered runners and complete
  seventeen-row P2 acceptance boundary remain governed by the shared plans and
  charter. The fifty-five definitions and twenty-four registered runners are
  unchanged.
