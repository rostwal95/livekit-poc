# Bounded channel workload profile

Status: Active
Last reviewed: 12 November 2026

The opt-in I19 profile exercises retained fake-SMS intake, persisted processing,
overload, process restart and dormant conversations through public P2 ports. Its
fixed declaration is [bounded-v1.json](workloads/bounded-v1.json); the selected
qualification and remaining release boundaries are recorded in
[work item 0039](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md).
This experiment does not establish production capacity, speech/model latency,
carrier behavior or complete P2 charter acceptance. I20 joined UI remains separate.

## Selected local results

The [0039 handoff](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md)
records the selected qualification. All listed gates passed with complete cleanup;
the full compatibility batch uses fresh reports rather than reusing focused runs.

| Proof | Observed result and scope |
| --- | --- |
| Local workload | 24 groups, sixteen owned commands, 81.819 seconds; 1000 dormant conversations and 1066 original inputs/68 fake operations preserved across restore |
| Installed npm | Seven stages, 2.680 seconds; public PostgreSQL/HTTP with supplied synthetic case, operation and communication ports |
| Installed Python | 113 unadapted tests, fifteen commands, 39.255 seconds; nine runtime payloads, offline default/native imports and public types |
| Fresh compatibility | 187 assertions in eleven serial lanes, 139.105 seconds; original validators, complete cleanup and settled owned process groups |

The sampled Node process reached 236693808 bytes RSS and 28.869 milliseconds
maximum event-loop delay. Useful completion covered 63 operations, with a
2578.128 millisecond maximum. RSS includes runtime baseline and both gateways in
that process; these observations are not per-case memory or deployment capacity.
The handoff retains exact cohort sizes, quantile policy, queue ages, restart lag
and source-qualified artifacts. I20 joined UI and all seventeen complete P2
charter rows retain separate gates; the fifty-five definitions and twenty-four
registered runners are unchanged.

## Commands and ownership

Run from the repository root with the pinned local toolchain and existing stack:

```sh
make p2-workload-plan
make p2-workload-check
```

The plan command validates the fixed manifest and prints its digest, seed policy,
twenty-four named groups and budgets. It does not load stack settings, compile,
connect to PostgreSQL or LiveKit, or start a child. The actual command requires an
already running restricted-role local stack. It never starts, resets or upgrades
application state. It creates only fresh UUID-owned schemas and an ephemeral
private application directory. Owner and runtime credentials enter separate
closed child environments. LiveKit API credentials stay in the parent, which only
reads room inventory; no workload child can allocate a room or join an agent.

The parent has 360 seconds total, reserving twenty seconds for cleanup. The fixed
normal schedule has sixteen commands within a maximum of thirty-two. Each child
stream is capped at 8192 bytes, total captures at 512 KiB, each direct JSON proof
at 2 MiB, all retained artifacts at 16 MiB and the final report at 32 KiB. Commands
are declared before measurement; setup, missing progress, deadline, evidence and
cleanup failures remain failures. New host commands own a verified process group,
including non-detached compiler descendants. This host-tooling helper is shared
with the image gate; it adds no P3 product dependency. Raw exception bodies and credentials are not
public diagnostics. An unresolved child retains its private work and prevents
dependent schema removal. An interrupted container-side backup/restore remains
uncertain after its host Docker CLI is reaped, so schemas and private backup/work
are retained with cleanup false rather than claiming remote drain.

The public fixed schedule seed is 39. It determines fixed offer labels/order; a
separate private nonce derives synthetic authentication and identity material.
Before measurement the study ceilings are fixed at 512 MiB process RSS, 1000 ms
maximum observed event-loop delay, 5000 ms accepted admission and 15000 ms useful
fake-operation completion. Crossing a ceiling fails this profile; it is not a
production SLA. No threshold may be tuned after a failed normal run.

## Active schedule

The capacity schema retains at most sixty-four inputs. This is a lifetime retained
row limit, not a queue-depth or dynamic backlog limit. Dispatched inputs still
consume capacity; completion does not make space for new identity. The sequence is
sixteen steady inputs, four admitted burst inputs, four slow/progress inputs and
forty fill inputs. Four additional burst HTTP requests are rejected before
acceptance while four requests remain admitted. One admitted HTTP caller abandons
its socket; the underlying SQL work stays owned, and a later equal request must
recover the original committed receipt. Changed content under the same identity
conflicts; two distinct IDs carrying the same text remain distinct inputs.

Two tenant-specific gateways share the schema. Each gateway owns an inbox pool
and dispatch pool, each with two connections and four retained SQL operations.
The configured aggregate is therefore eight runtime connections and sixteen SQL
operations across four pools. The parent admission locker and read-only observer
can add two control connections during the burst proof: ten possible connections
in this isolated topology. Their public backend identities and actual closure are
retained separately from runtime pool observations. Each dispatcher retains at most two adapter tasks;
the persisted claim limit of two is shared across workers in this schema. These
are different scopes. The sampled pool field `occupied` means checked-out plus queued SQL operations;
`total` counts open database connections and `waiting` counts queued connect calls.
These quantities are not interchangeable. Held adapter calls and original
receipts are observed independently. A private application wrapper captures
public PostgreSQL backend IDs from acquired clients; the parent binds the exact
child PID/schema/backend IDs to one real admission-lock graph with two waiters.

A deliberately slow agent ignores cancellation. Caller timeout does not free its
actual task. Releasing one tenant's held call must permit useful work from another
admitted scope while the other held task remains. This proves selected progress,
not a general fairness or per-tenant resource reservation guarantee. A known fake
operation whose response is lost remains uncertain until a fresh process performs
lookup-only reconciliation of the original immutable plan/key/digest. The fake
operation ledger is independent of the P2 database; no P1 supplier or provider is
called.

At capacity, equal replay and scoped history remain available, changed content
still conflicts, and new growth is rejected. A display window keeps the latest
four public history cards and evicts older cards. The original payload, receipt,
operation key and replay protection remain durable. There is no physical identity
pruning, deletion, retention TTL or reclaimed-capacity claim.

## Dormant schedule

The dormant schema permits 1024 retained inputs and 1024 challenges, associations
and senders. It receives one real public association and input for each of one
thousand conversations, five hundred per tenant. Credential windows contain at
most sixty-four fixed public `SeededAccounts` entries, with each reader closed
before the next opens. The experiment does not widen the production sixty-four
entry constructor cap or seed SQL rows around authentication.

Resource observations are taken at zero, sixty-four, 256 and one thousand dormant
inputs. All one thousand original receipts are inspected through bounded public
credential windows. No room, agent, timer or task is created per dormant case.
The parent reads SFU inventory before seeding, at one thousand and after useful
progress. Inventory is an allocation observation, not media qualification.

Two original dormant cases wake through the normal persisted dispatcher and each
accepts one genuine new input. The final inventory is 1002 retained inputs: four
dispatched and 998 pending. Pending, running, uncertain, blocked, exhausted and
dispatched states are reconciled separately; retained input count alone does not
prove completed processing.

## Telemetry and quantitative interpretation

`ChannelInbox.telemetryMetrics()` returns exactly `observerPending`,
`observerDropped` and `observerFailures` for ordinary inbox notifications. An
ordinary callback slot is reserved before invoking user code and retained until
its actual returned promise settles. Eight outstanding ordinary callbacks cause
later notifications to be dropped without blocking useful SQL work. The existing
communication observer has its own separate eight-slot lane and metrics. Existing
`metrics()` and `communicationMetrics()` field sets are preserved.

The injected observer transport belongs to the application. SQL close neither
closes that transport nor claims its callback work drained. Pending callbacks stay
visible after SQL close. The workload releases every held application callback,
observes actual settlement and records final counters, including any dropped close
notification, before claiming cleanup.

Latency cohorts use nearest-rank quantiles and report count, p50 and maximum
(`maximumMs`) in milliseconds. A p95 is present
only for cohorts with at least twenty samples; steady, burst and slow observations
are not relabelled as larger populations. Process resource samples identify RSS,
heap and external memory in bytes and CPU user/system time in microseconds. Two
gateways run in one Node process. RSS includes runtime baseline and is not divided
by case count or presented as per-case RAM, PostgreSQL memory or deployment scale.
Configured limits and observed maxima remain distinct.

## Recovery and evidence

The application gracefully stops and reopens against the same PostgreSQL volume.
A separate owner-only populated `pg_dump`/drop/`psql` restore covers both allocated
schemas. Fresh public readers verify every original receipt, canonical body,
scoped sequence, operation key and processing state. The fake operation ledger
must not gain another logical acceptance. Parent SQL snapshots and independent
joins bind original receipts and plans to the external ledger; sorted-key compact
ASCII JSON hashes are reproducible from retained snapshot files.

No automatic sender retry follows an unknown external effect, no playback fact
becomes consent, and no workload receipt creates a business-action owner. Existing
I12–I18 gates and isolated archive consumers keep their own scopes. The fifty-five
scenario definitions, twenty-four registered runners and complete seventeen-row
P2 acceptance boundary remain governed by the shared plans and charter.
