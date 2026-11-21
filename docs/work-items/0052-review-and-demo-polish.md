# Portfolio review and demo polish

Reviewed the Docker entry point, the browser walkthrough, repository docs, and
the Python paths for room handoff, delegated execution, case reads, and booking
confirmation. The [README](../../README.md) leads with the behavior a reviewer
can reproduce. Runtime pins and record ownership sit in the
[architecture guide](../architecture.md).

## Changes and evidence

| Finding | Change and check |
| --- | --- |
| A warm `./demo up` probed only the UI. A stopped operator or worker could be missed. | Compose now checks the full dependency graph on a warm start and reuses the running showcase. [Demo entry point](../../demo) |
| The PostgreSQL role bootstrap used the server image and inherited an unused anonymous volume. | Mount the unused data directory in memory for the bootstrap client. The two named demo volumes are the only persistent mounts. [Compose services](../../compose.yaml) |
| A cancelled or rejected native turn could occupy a handoff slot before intake. | Admit handoff capacity before opening recognition. Release an unused slot when its last owner settles, and preserve accepted or uncertain inputs for reconciliation. [Runtime](../../projects/channel-continuity/python/src/channel_continuity/native.py) · [Regression tests](../../projects/channel-continuity/tests/test_native_sdk.py) |
| Delegated execution and delivery writes repeated a full schema check inside the protected callback. | The shared store still validates before and after admission locking. A pinned PostgreSQL test run counted 44 validation statements per write, down from 66. [Execution store](../../projects/agent-continuity/python/src/continuity_lab/execution_store.py) |
| The operator API encoded response bodies twice to apply a byte limit. | It now serves the same UTF-8 bytes it measures. The body, status, headers, and byte-limit behavior were checked with Unicode and at the size boundary. [Operator responses](../../services/control_api/business.py) |
| The original recording used a single robotic voice at a low speech level. | Recorded separate caller and agent voices through the actual browser flow. Captions identify prerecorded recognition and simulated SMS. [Recording guide](../demo.md#record-a-fresh-walkthrough) |

## Remaining technical observations

- Background discovery can issue a prepared-input read and a stored-work read
  for each of the 16 profile inputs on a scan. The stored-work read also opens
  a connection and validates the catalog. Failed scans or unresolved inputs
  can hold the poll interval at 250 ms. Measure idle scans and short bursts
  before batching or changing the backoff. Each lookup must retain the original
  receipt and work binding. [Executor](../../services/channel_policy_demo/executor.py) · [Scan cadence](../../services/channel_policy_demo/application.py)
- The current-result reader constructs specialist and receiver clients through a
  shared job factory. A narrower read-only path could reduce that setup cost.
  Preserve result, case revision, and receiver-binding checks across reads.
  [Job factory](../../services/channel_policy_demo/jobs.py)
- Result feed checks aggregate retained rows. The booking worker's telemetry
  snapshot also uses the admission lock. At the demo's bounded data size, the
  next step for either path is a contention measurement on PostgreSQL.
  [Result feed](../../projects/agent-continuity/python/src/continuity_lab/result_feed_store.py) · [Booking worker](../../projects/agent-continuity/python/src/continuity_lab/worker_cli.py)
- The initializer commits the schemas separately and writes a profile marker
  after seeding. A partial profile blocks setup. On repeated setup the
  initializer checks its marker and serving processes validate their storage
  layouts before readiness. The scope of rollback is each schema installation.
  [Initializer](../../local-setup/scripts/demo_runtime.py) · [Setup](../../local-setup/scripts/channel_policy_setup.py)

## Verification

The audited Python suite passed 1,028 tests and 1,242 subtests. A room retry
test hit its 30 ms test budget on an earlier run and passed on isolated and
full reruns. The four TypeScript suites passed 1,412 tests. Ruff and strict
mypy on the touched runtime modules passed, as did four baseline checks against
PostgreSQL 18.6. Chromium rendered all three architecture diagrams.

With the showcase still running, the warm start recovered the stopped operator
and booking worker and confirmed both were healthy. The verifier's input,
case, room, result, and effect identities were unchanged after that recovery
and after a full stop and restart. A failed recording attempt on that populated
profile explicitly ended its room before exiting.

An empty-volume browser walkthrough on macOS 27.2.1 arm64 with Docker Engine
29.9.3 and Compose 5.7.0 verified actual media playback and a new policy read
after joining the second room. The independent verifier found one case, three
original inputs, two closed rooms, three delivered delegated results, one
supplier effect, and one completion receipt. The published recording decodes
at 1440 × 960, runs 89.72 seconds, and measured −17.9 LUFS integrated with a
−1.99 dBTP peak.

The final Compose check found exactly two owned volumes after `./demo down`.
`./demo reset --yes` removed the test project's containers and volumes. The
inventories of other Docker containers and volumes matched before and after.
