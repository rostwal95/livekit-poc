# Channel operations

Status: Active
Last reviewed: 12 November 2026

The selected I20 profile passed its sixteen PostgreSQL/read assertions and three
browser groups, the isolated 105-payload npm consumer and all 187 fresh affected
compatibility assertions. Exact source/evidence boundaries and retained failures
are recorded in the [0040 handoff](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md).
All selected cleanup checks passed. The complete standalone I21 starter and I22
release remain separate; all seventeen full P2 charter rows remain planned.

The opt-in operations reader joins retained channel facts with a separately observed
current case. Its operator capability permits reads only. The page has no resend,
revision, confirmation, dispatch or playback controls. Investigation consent and
exact mutation confirmation remain separate authorities.

`OperationsReader` in `./operations` uses the existing inbox transaction and pool.
It checks its configured native binding, takes the existing repeatable-read P2
snapshot, reads the public current-case port and performs a final protected grant
check before disclosure. These observations are not an atomic cross-system
snapshot. Case revision zero is supported for reading; it does not qualify native
zero-revision dispatch or communication. An observed revision protects the request
revision, not the freshness of workflow, supplier or delivery state.

## Reads and paging

`OperationsReadServer` serves literal-loopback GET requests at
`/v1/operations/context` and `/v1/operations/telemetry`. Applications configure one
fixed operator bearer, native grant, case scope, cursor source and stable cursor
key. Request bodies cannot select scope. Context queries select only a section and
an opaque cursor. Every request and response carries a bounded request UUID.

The context retains the existing nine-section rehydration model and its 65,536-byte
JSON envelope limit. The new wrapper permits an additional 8,192 bytes, with a
73,728-byte total bound. Every signed cursor is at most 2,048 bytes; the aggregate
frame limit still applies. Records are never silently truncated. Cursors bind the
original source, profile, native grant, scope, section and immutable retained
anchor. A changed case observation requires a new first-page read. Accepted-row
paging is not a status-event feed: use explicit current refresh for later changes.

Both `OperationsHttpClient` and the receiver validate framing, UTF-8, duplicate JSON
fields, byte limits, request correlation and fixed error codes. Read retry hints
refer only to another read. Transport saturation may close a connection without a
typed response. Once HTTP capacity is available, retained reader saturation returns
`overloaded`. A lost read response never authorizes another business operation.

## Process diagnostics

Telemetry reports explicitly process-local producer samples and bounded read spans.
It is not fleet telemetry or a claim that a user heard or acknowledged a response.
The independent operator diagnostic capability remains eligible after a native
context grant is revoked. The UI pauses polling on context denial, marks retained
diagnostics as historical and clears all facts and credentials on Forget.

Metric names, all 76 event codes and sources are finite. Source-specific mappings
consume the actual callback, gateway, outbox, dispatcher and inbox producer forms.
They preserve distinct causes, including unknown delivery and recovery outcomes;
unknown strings, fields and operation labels are dropped. Known success code
`ok` is represented as `known`, callback acceptance/replay or closed lifecycle
according to its fixed producer event. Request UUIDs appear only in
trace observations. Bodies, tokens and arbitrary labels do not enter metrics or
spans. A failed metric getter is unavailable; it does not become a zero sample.
Export callbacks reserve one of eight slots before invocation and retain it through
actual settlement. Their completion owner is registered before any application
callback, metric getter or returned thenable accessor runs. Reentrant close waits
for that owner, permits a successful close retry after release and admits no later
getters. Each source owns at most one actual getter; at most eight sources exist.
Exporter failure or saturation does not consume business read capacity.
Applications own and drain their injected exporter resources separately. Counters
reset with their actual producer instance. They are not durable input totals;
retained receipt/work history comes from its separately observed SQL projection.
Applications select allowlisted real metric fields rather than inventing missing
zeros or forwarding an arbitrary producer object.

## Lifetime and evidence

The reader owns at most two actual read tasks through ignored cancellation. A
caller timeout or socket close does not free that ownership. The HTTP server owns
its handlers and sockets; it does not close the reader, inbox, case port or
telemetry adapter. Applications close dependent readers before shared data owners
and release held exporters before claiming complete cleanup.

The operations page is separate from the default console. Credentials remain in
memory and are cleared from the field on use. Forget invalidates the view
immediately while retaining unfinished client ownership; a new connection waits
for the old actual owner to settle. Late responses cannot repopulate a forgotten
view. Polling, read requests, retained display rows and observation history are
bounded. Display eviction does not delete durable replay protection.

The selected I20 qualification requires real PostgreSQL/read-only HTTP cases, an
actual browser journey, isolated installed npm consumption and affected regression
lanes. Offline model and socket tests alone do not close that gate or any complete
P2 charter row. See the maintained phase work item for the frozen acceptance
inventory, source bindings and resulting artifacts.


## Running the optional page

`examples/operations-lab.ts` exports the typed `startOperationsLab` composition
factory. It is not a CLI and reads no environment or configuration files. The
application supplies every trusted owner before calling it; importing the file
starts no listener. Its compiled JavaScript is included in the npm archive.

| Supplied option | Application responsibility |
| --- | --- |
| `inbox` | Existing configured version-7 inbox; application owns its SQL pool. |
| `cases` | Read-only `CurrentCasePort` with a fixed trusted case mapping. |
| `sms` | Existing fake-SMS verification capability for retained source interpretation. |
| `profile` | Fixed reference, native binding/bearer, stable profile/source IDs and copied 32-byte cursor key. |
| `authorization` | Distinct operator header, `Bearer ` plus 43 base64url characters. |
| `observer` | Optional bounded observation callback; application owns its export transport. |

The host calls `startOperationsLab({ inbox, cases, sms, profile, authorization,
observer })` with those configured values and obtains `endpoint`, `reader`,
`telemetry`, `server` and `close`. Use `endpoint.port` as the Vite proxy target.
The dedicated proxy accepts only a numeric port from 1 through 65535 on
`127.0.0.1`; it does not mint account, native or operator credentials.

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

Enter only the operator token's 43-character value in the page. It remains in
memory; the field clears on use. No native bearer, cursor key or account credential
belongs in the page or URL. The existing default console command remains separate.

The fully owned scripted PostgreSQL/HTTP/browser journey is
`make p2-operations-check` after the reviewed restricted-role local setup. It owns
its isolated schemas, explicit producer commands, browser and cleanup. Its fake
operation/carrier ports and synthetic communication publications do not qualify
real providers or SDK media. The installed operations factory is qualified within this selected scope; the
later complete I21 standalone starter keeps its own gate.

On shutdown, settle the application's held exporter callbacks, then await
`app.close()`. Close supplied inbox/case resources only after that dependent close
actually succeeds. A timeout retains ownership and must not trigger dependent
schema deletion. The factory does not close those supplied owners for the caller.
