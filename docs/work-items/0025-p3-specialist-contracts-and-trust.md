# P3 specialist contracts and local trust boundary

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the P3 specialist request, result and error contracts, the local trust boundary and their gates |
| Audience | Engineers changing P3 specialist contracts, local trust, evidence or attempt admission; reviewers; coding agents |
| Scope | Tasks P3-I03 and P3-I04 for `booking.evaluate_policy`; excludes HTTP, durable state, models and media |
| Owns | P3-I03 and P3-I04 change plan, contract bounds, observed verification and handoff |
| Related | [P3 native baseline](0023-p3-native-baseline.md) · [Specialist package](../../projects/delegation-reliability/specialist-ts/README.md) · [P3 charter](../projects/delegation-reliability-scope.md) · [Standalone and HTTP](0027-p2-standalone-and-p3-http.md) |

## Behavior and scope

This work item implements tasks P3-I03 and P3-I04 after the reviewed Phase P3-A
baseline. The slice provides:

- strict Python/TypeScript request, result and error codecs;
- a real TypeScript request producer consumed by installed Python;
- trusted local service grants;
- immutable scoped evidence;
- bounded live-attempt permits.

It contributes contract and trust assertions to acceptance IDs P3-01, P3-03 and
P3-11. No complete product row is registered.

Only `booking.evaluate_policy` is supported. Document extraction, model clients,
HTTP endpoints, coordinator acceptance, database state, durable retries, callback
recovery and actual media remain planned. A wire-valid candidate is not accepted
work, a current case decision or mutation permission.

| Criterion | Given / When | Safety | Useful progress and evidence |
| --- | --- | --- | --- |
| Cross-language contract | Real TypeScript producer emits the fixed Unicode request; Python consumes installed package | Exact canonical bytes/fingerprint; duplicate keys, invalid UTF-8, unsupported versions and malformed values fail | Both producers match one frozen fixture; valid result/error round trips |
| Identity | Same delegation retries under a new attempt or changes bound semantics | Attempt metadata alone preserves logical fingerprint; scope/case/revision/evidence/context/deadline/route changes conflict | A distinct logical delegation and exact current attempt still match |
| Local trust | Separately configured service grants invoke/result/cancel/evidence access | No body principal, provider text or token supplies business mutation authority; wrong scope/operation/header fails | Authorized scoped invocation/evidence and result/cancel inspection succeed |
| Evidence/factual checks | Swap a source/version or return valid JSON with incorrect known policy facts | Exact accepted source bytes/digest and rule required; uncertainty remains explicit | Correctly grounded current candidate progresses; no factual-generalization claim |
| Time/resources | Trusted caller supplies observed time; fill bounded live registry | Reported completion time cannot revive expiry; no queue/timer/retries; unknown/forged permit fails | Owned release frees capacity and a valid subsequent invocation progresses |

## Interfaces and ownership

### Source layout

| Component | Path | Responsibility |
| --- | --- | --- |
| Python source | `contracts.py` and `security.py` in the existing development-only P3 workspace member | Python implementation |
| TypeScript source | `specialist-ts/src` | TypeScript implementation, with no runtime dependency |
| Shared contract data | `contracts/delegation/v1.json` | Data-only; shared by the actual implementations |
| Root | Repository root | Shared workspace/lock, source-discovery, lint/type/build and documentation registration |

The Python native baseline remains unchanged.

### Request identity and results

The version-1 request binds:

- the schema/input version and capability;
- the trusted scope;
- the delegation, case and revision;
- immutable context and scoped evidence metadata;
- an absolute millisecond deadline;
- the logical conversation destination.

The fingerprint excludes only itself and the attempt identity/number. New attempts
require exact result attempt correlation. A transport retry never grants a new
logical business action. Results retain source/rule references, uncertainty and
bounded producer/model/configuration provenance. No provenance or confidence field grants
truth or authorization.

### Local trust

LocalTrust accepts bounded operator-created grant configuration. It contains token
SHA-256 digests, principal IDs and separate operation, capability and source
allowlists per scope. Bearer values are exactly 43 opaque ASCII characters after
the exact prefix. In real use, configuration must use strong randomly generated
tokens; tests use synthetic tokens only.

Constant-sized digest comparisons do not log or persist raw bearer values. No
credentials are read from the environment or files. Trusted code validates the
header; a scope or principal in request JSON is not trusted. This is a local
mechanism, not enterprise identity or credential rotation.

### Evidence registry

EvidenceRegistry owns a bounded immutable byte snapshot and exact source metadata.
Python bytes are immutable; TypeScript clones initial and returned byte buffers.
No arbitrary URL fetch or filesystem source resolution exists. Image metadata has
byte and dimension bounds; actual image decoding/extraction remains a later
capability.

Known fixed-policy evaluation distinguishes schema validity, source binding and
factual agreement. The case authority must still revalidate the current revision
and exact consent atomically before any action.

### Attempt boundary

AttemptBoundary is an ephemeral admission/observation registry, not acceptance or
execution ownership:

- Acquire requires current service authorization, a valid remaining deadline and
  scoped evidence.
- Result/cancel inspection requires its separate grant and a known exact live
  attempt.
- Only the original minted permit can release its slot.
- Active same-delegation changed payloads conflict.

Python map operations use a small process-local lock with no external work
inside; JavaScript methods are synchronous. No startup background task, timer,
acknowledgement queue, durable store or retry scheduler exists. Released history
remains P1's responsibility. P1 remains the only future execution owner.

## Failure cases and validation

### Bounds

| Limit | Value |
| --- | --- |
| JSON bodies | Request 16,384 bytes; result 8,192; error 512; strict UTF-8, duplicate-free exact fields |
| JSON structure | Depth at most 12 containers; at most 256 value nodes; no fractions, exponents, negative zero or unsafe integers; bounded canonical copy rejects cycles/hooks/amplification |
| Context | Note at most 1,024 UTF-8 bytes; case revision 1–1,000,000; days 0–3,650 |
| Evidence | 1–4 request/result references; JSON source at most 4,096 bytes; encoded source at most 2 MiB and image dimensions at most 2,048 each |
| Source registry | At most 32 records and 8 MiB total bytes; no source fetching or decode tasks |
| Trust configuration | At most 32 principals, 16 scopes each, 64 source IDs per scope; aggregate canonical structure/body bounds also apply |
| Time | Safe integer UTC milliseconds through 2100; trusted observed admission time requires 1–60,000 ms remaining; reported completion timestamp is diagnostic |
| Live attempts | Default 4 total and 2 per principal; configurable maximum 16, no waiting queue; caller owns explicit release |

### Negative coverage

Shared fixtures separate parser failures from result matching and factual
failures. Tests include:

- exact Unicode limits and late identifier line terminators;
- malformed JSON and numerics;
- altered semantics and a forged body principal;
- source replacement and wrong account/attempt;
- ignored embedded instructions and wrong known facts/rules;
- expired observed time, a missing operation grant and a malformed inspection
  operation;
- unknown or forged permits, capacity and useful valid progression.

Typed Python encoder regressions prove malicious deepcopy is never called before
size/type rejection. No native software development kit (SDK) lifecycle is mocked
or changed by this contract slice.

### Gates and commands

Gate names starting with G- refer to the engineering gates in the
[validation plan](../validation-plan.md).

| Gate | Exact lane | Completion requirement |
| --- | --- | --- |
| G-CONTRACT | Python unittest and TypeScript Vitest shared fixtures; actual TypeScript producer passed via stdin to workspace-installed Python in isolated-interpreter mode | Same canonical bytes and fixed safe codes; structural success separately fails incorrect factual fixtures |
| G-FAST | Ruff/format and strict mypy for Python; strict TypeScript source/test checks and build | Nonzero new tests and root discovery required; no skipped/missing lane passes |
| G-OBS | Fixed ContractError codes and exact error envelope | No raw note, evidence bytes, tokens, provider message or arbitrary detail in public error |
| G-DURABLE/G-MEDIA | Not claimed in this slice | Future actual store/process/media gates remain open |
| G-PACKAGE | Workspace installed consumer only | Standalone wheel/npm archive qualification remains P3-I15 |

Existing focused commands run from the repository root:

```sh
.venv/bin/python -m unittest discover -s projects/delegation-reliability/tests -p 'test_specialist_contracts.py' -v
.venv/bin/mypy --strict projects/delegation-reliability/python/src/delegation_reliability/contracts.py projects/delegation-reliability/python/src/delegation_reliability/security.py
corepack pnpm --filter @livekit-ecosystem/delegation-specialist typecheck
corepack pnpm --filter @livekit-ecosystem/delegation-specialist test
corepack pnpm --filter @livekit-ecosystem/delegation-specialist build
```

Use the pinned Node/pnpm environment documented at the root. The producer/consumer
test uses the installed root Python environment with isolated imports and a finite
subprocess budget. No repository `PYTHONPATH` or paid provider credentials are
used.

## Results and handoff

### Focused results

| Check | Observed result |
| --- | --- |
| Focused Python validation | Passed 39 Python tests, with zero skips: 18 unchanged native-baseline tests and 21 contract/trust tests |
| TypeScript tests | Passed 42 tests, including actual producer output consumed by workspace-installed Python under `-I` |
| Static checks and build | Ruff, formatting, strict mypy on all seven Python source modules, strict TypeScript source/test checks and the TypeScript build passed |
| Shared fixture | 28 named invalid rows across parse, match and factual lanes |

Counts are observations, not pass thresholds.

### Review corrections and shared gates

Independent read-only review identified and corrected:

- typed-dataclass deepcopy before bounds;
- early Unicode length checks;
- malformed inspection-operation access;
- large header slicing;
- exact byte-length/configuration primitive validation.

Regression tests cover those findings. A barrier-controlled eight-thread test
verifies that Python admission cannot exceed its cap. An admitted second principal
and post-release work still progress.

Final shared gates and independent automated review passed, completing
P3-I03/I04:

| Check | Observed result |
| --- | --- |
| `make check` | Passed 1,162 offline Python tests with zero skips, lint and maintained/strict typing |
| `make frontend-check` | Passed 504 tests, strict source/test checks, formatting and builds |
| Documentation and diagrams | All 99 documents passed; six project Mermaid diagrams parsed and the malformed fixture was rejected |

### Package and evidence

The final npm-pack smoke installed the built TypeScript archive in a fresh
consumer outside the checkout. It passed strict typing plus request decoding. The
Python parity lane uses a workspace-installed isolated interpreter; no built
Python wheel consumer is claimed. Full P3-I15 package qualification remains open.
No HTTP endpoint, durable acceptance or complete P3 product case is certified
here.

The retained evidence/source inventory is under
`.local/validation/p2-p3-intake-contracts/0a88373e034e4ef8b2dca5fb8d4a7eb5`,
shared with the [P2 intake handoff](0026-p2-postgres-inbox.md). AI assistance
implemented and independently reviewed this slice. Human review and real-model
quality are not manufactured.

### Next task

The next bounded task is P3-I05's authenticated read-only handler/client. It uses
these trust/resource checks for one P1-owned attempt. Complete its real boundary
tests before introducing coordinator durability. Breaking protocol changes require
an explicit version and coordinated producer/consumer fixtures. Adding document
extraction must not silently reinterpret this first-capability contract.
