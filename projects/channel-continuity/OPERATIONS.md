# Channel operations

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Describe the opt-in I20 read-only operations profile and how to compose, run and close it |
| Audience | Engineers who compose or change the P2 operations profile; coding agents |
| Scope | The `./operations` reader, loopback HTTP reads, process diagnostics and the optional operator page; excludes mutation controls |
| Owns | Operations reads: current versus historical facts, explicit refresh, metric and span sources, exporter isolation and owner retention |
| Related | [Project guide](README.md) · [Rehydration contract](REHYDRATION.md) · [0040 handoff](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md) · [Local console](../../apps/local-console/README.md) |

## Overview

This guide describes the opt-in I20 read-only operations profile: the `./operations`
reader, its loopback HTTP reads, process diagnostics and the optional operator page.

The operations reader joins retained channel facts with a separately observed
current case.

| Capability | Status | Evidence |
| --- | --- | --- |
| I20 read-only operations profile | Qualified | [0040 handoff](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md) |
| I22 release | Planned | [Project guide](README.md#next-milestone) |
| Full P2 charter rows (all seventeen) | Planned | [V1 charter](../../docs/projects/channel-continuity-scope.md) |

- Its operator capability permits reads only.
- The page has no resend, revision, confirmation, dispatch or playback controls.
- Investigation consent and exact mutation confirmation remain separate
  authorities.
- The complete standalone I21 starter and I22 release remain separate.

## Reader composition

`OperationsReader` in `./operations` uses the existing inbox transaction and pool.
For each read it:

1. Checks its configured native binding.
2. Takes the existing repeatable-read P2 snapshot.
3. Reads the public current-case port.
4. Performs a final protected grant check before disclosure.

These observations are not an atomic cross-system snapshot.

- Case revision zero is supported for reading. It does not qualify native
  zero-revision dispatch or communication.
- An observed revision protects the request revision, not the freshness of
  workflow, supplier or delivery state.

## Reads and paging

### HTTP routes and configuration

`OperationsReadServer` serves literal-loopback GET requests at
`/v1/operations/context` and `/v1/operations/telemetry`.

- Applications configure one fixed operator bearer, native grant, case scope,
  cursor source and stable cursor key.
- Request bodies cannot select scope.
- Context queries select only a section and an opaque cursor.
- Every request and response carries a bounded request UUID.

### Envelope and cursor bounds

The context retains the existing nine-section rehydration model and its JSON
envelope limit:

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Rehydration JSON envelope | 65,536 bytes | Context envelope | Existing limit |
| Wrapper allowance | 8,192 bytes | The new wrapper | Additional to the envelope |
| Total | 73,728 bytes | Context response | Envelope plus wrapper |
| Signed cursor | 2,048 bytes | Each cursor | The aggregate frame limit still applies |

- Records are never silently truncated.
- Cursors bind the original source, profile, native grant, scope, section and
  immutable retained anchor.
- A changed case observation requires a new first-page read.
- Accepted-row paging is not a status-event feed. Use an explicit current refresh
  for later changes.

### Client validation and errors

Both `OperationsHttpClient` and the receiver validate framing, UTF-8, duplicate
JSON fields, byte limits, request correlation and fixed error codes.

- Read retry hints refer only to another read.
- Transport saturation may close a connection without a typed response.
- Once HTTP capacity is available, retained reader saturation returns
  `overloaded`.
- A lost read response never authorizes another business operation.

## Process diagnostics

### What telemetry reports

Telemetry reports explicitly process-local producer samples and bounded read spans.
It is not fleet telemetry or a claim that a user heard or acknowledged a response.

- The independent operator diagnostic capability remains eligible after a native
  context grant is revoked.
- The UI pauses polling on context denial and marks retained diagnostics as
  historical. It clears all facts and credentials on Forget.

### Event codes and labels

- Metric names, all 76 event codes and sources are finite.
- Source-specific mappings consume the actual callback, gateway, outbox, dispatcher
  and inbox producer forms. They preserve distinct causes, including unknown
  delivery and recovery outcomes. Unknown strings, fields and operation labels are
  dropped.
- The known success code `ok` is represented as `known`, callback
  acceptance/replay or closed lifecycle, according to its fixed producer event.
- Request UUIDs appear only in trace observations.
- Bodies, tokens and arbitrary labels do not enter metrics or spans.
- A failed metric getter is unavailable. It does not become a zero sample.

### Export callbacks and getters

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Export callback slots | 8 | Export callbacks | Reserved before invocation and retained through actual settlement |
| Actual getters | 1 | Each source | None |
| Sources | 8 | Diagnostics | None |

- The completion owner is registered before any application callback, metric
  getter or returned thenable accessor runs.
- Reentrant close waits for that owner, permits a successful close retry after
  release and admits no later getters.
- Exporter failure or saturation does not consume business read capacity.
- Applications own and drain their injected exporter resources separately.

### Counters

Counters reset with their actual producer instance. They are not durable input
totals: retained receipt and work history comes from its separately observed SQL
projection. Applications select allowlisted real metric fields rather than
inventing missing zeros or forwarding an arbitrary producer object.

## Lifetime and ownership

### Reader and server owners

- The reader owns at most two actual read tasks through ignored cancellation. A
  caller timeout or socket close does not free that ownership.
- The HTTP server owns its handlers and sockets. It does not close the reader,
  inbox, case port or telemetry adapter.
- Applications close dependent readers before shared data owners, and release held
  exporters before claiming complete cleanup.

### Operations page state

The operations page is separate from the default console.

- Credentials remain in memory and are cleared from the field on use.
- Forget invalidates the view immediately while retaining unfinished client
  ownership. A new connection waits for the old actual owner to settle.
- Late responses cannot repopulate a forgotten view.
- Polling, read requests, retained display rows and observation history are
  bounded.
- Display eviction does not delete durable replay protection.

## Running the optional page

### Composition factory

`examples/operations-lab.ts` exports the typed `startOperationsLab` composition
factory. It is not a command-line interface (CLI) and reads no environment or
configuration files. The application supplies every trusted owner before calling
it. Importing the file starts no listener. Its compiled JavaScript is included in
the npm archive.

| Option | Default | Allowed values | Description |
| --- | --- | --- | --- |
| `inbox` | Required | Existing configured version-7 inbox | The application owns its SQL pool |
| `cases` | Required | Read-only `CurrentCasePort` with a fixed trusted case mapping | Current-case source |
| `sms` | Required | Existing fake-SMS verification capability | Retained source interpretation |
| `profile` | Required | Fixed reference, native binding/bearer, stable profile/source IDs and copied 32-byte cursor key | Fixed read profile |
| `authorization` | Required | `Bearer ` plus 43 base64url characters | Distinct operator header |
| `observer` | None (optional) | Bounded observation callback | The application owns its export transport |

The host calls `startOperationsLab({ inbox, cases, sms, profile, authorization,
observer })` with those configured values. It obtains `endpoint`, `reader`,
`telemetry`, `server` and `close`.

- Use `endpoint.port` as the Vite proxy target.
- The dedicated proxy accepts only a numeric port from 1 through 65535 on
  `127.0.0.1`. It does not mint account, native or operator credentials.

### Building and serving the page

| Task | Command | Notes |
| --- | --- | --- |
| Build the dedicated console page | `make p2-operations-build` | Separate from the default P1 console and native controls |
| Inspect the fixed declaration | `make p2-operations-plan` | Starts no services |
| Serve the page | Vite command below | Needs the owning host's actual `endpoint.port` |
| Run the owned journey check | `make p2-operations-check` | Needs the reviewed restricted-role local setup |

Build and inspect the fixed declaration without starting services:

```sh
make p2-operations-build
make p2-operations-plan
```

After the owning host has started, replace `43123` below with its actual
`endpoint.port`, then open `http://127.0.0.1:3101/p2-operations.html`:

```sh
P2_OPERATIONS_API_PORT=43123 corepack pnpm --filter @livekit-ecosystem/local-console exec vite --config vite.operations.config.ts --host 127.0.0.1 --port 3101 --strictPort
```

- Enter only the operator token's 43-character value in the page. It remains in
  memory, and the field clears on use.
- No native bearer, cursor key or account credential belongs in the page or URL.
- The existing default console command remains separate.

### Owned journey check

The fully owned scripted PostgreSQL/HTTP/browser journey is
`make p2-operations-check`, run after the reviewed restricted-role local setup. It
owns its isolated schemas, explicit producer commands, browser and cleanup.

- Its fake operation/carrier ports and synthetic communication publications do not
  qualify real providers or SDK media.
- The installed operations factory is qualified within this selected scope. The
  later complete I21 standalone starter keeps its own gate.

### Shutdown order

1. Settle the application's held exporter callbacks.
2. Await `app.close()`.
3. Close supplied inbox and case resources only after that dependent close actually
   succeeds.

A timeout retains ownership and must not trigger dependent schema deletion. The
factory does not close those supplied owners for the caller.

## Validation and evidence

The selected I20 qualification requires real PostgreSQL/read-only HTTP cases, an
actual browser journey, isolated installed npm consumption and affected regression
lanes.

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Owned PostgreSQL, read-only HTTP and browser journey | `make p2-operations-check` | Real PostgreSQL/read-only HTTP cases and an actual browser journey | Passed (0040) |
| Isolated installed npm consumption | Recorded in the [0040 handoff](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md) | The installed operations factory outside the checkout | Passed (0040) |
| Affected regression lanes | Recorded in the [0040 handoff](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md) | Earlier P2 behavior is preserved | Passed (0040) |

### Selected qualification results

| Proof | Observed result |
| --- | --- |
| PostgreSQL/read | Sixteen assertions passed |
| Browser | Three browser groups passed |
| Isolated npm consumer | The 105-payload consumer passed |
| Compatibility | All 187 fresh affected assertions passed |
| Cleanup | All selected cleanup checks passed |

- Offline model and socket tests alone do not close that gate or any complete P2
  charter row.
- Exact source/evidence boundaries and retained failures are recorded in the
  [0040 handoff](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md).
  The maintained phase work item also holds the frozen acceptance inventory,
  source bindings and resulting artifacts.
