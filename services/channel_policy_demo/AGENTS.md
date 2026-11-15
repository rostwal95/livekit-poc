# Joined channel-policy application coding instructions

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Give coding agents the reading order, ownership, rules and checks for joined channel-policy application work |
| Audience | Coding agents and engineers changing the joined Python application or its root application tests |
| Scope | `services/channel_policy_demo` and its root application tests; excludes product packages, local setup, browser and gateway |
| Owns | Agent workflow for the joined application: reading order, owned paths, development rules, verification and handoff |
| Related | [Root instructions](../../AGENTS.md) · [README](README.md) · [Design](Design.md) · [Work item 0045](../../docs/work-items/0045-joined-native-channel-policy.md) |

## Read first

Read these documents:

| Document | Why read it |
| --- | --- |
| [Root instructions](../../AGENTS.md) | Shared reading order, owned paths, development rules and verification |
| [README.md](README.md) | Implemented behavior, commands and validation |
| [Design.md](Design.md) | Design, limits and failure handling |
| [Active work item 0045](../../docs/work-items/0045-joined-native-channel-policy.md) | Active change plan, observed verification and handoff |
| [P2 charter](../../docs/projects/channel-continuity-scope.md) | P2 requirements and stable acceptance IDs |
| [P3 charter](../../docs/projects/delegation-reliability-scope.md) | P3 requirements and stable acceptance IDs |
| Affected public APIs and tests | Current interfaces and behavior that a change touches |

Follow the shared [Python](../../docs/python-engineering.md),
[documentation](../../docs/documentation-standards.md) and
[observability](../../docs/observability.md) standards.

- The completed [0044](../../docs/work-items/0044-origin-bound-channel-policy.md)
  checkpoint is historical evidence.
- New canonical locations require fresh qualification.

## Owned paths

| Area | Responsibility |
| --- | --- |
| `services/channel_policy_demo` and its root application tests | Owned here |
| Product authority | Stays in the P1/P2/P3 packages |
| Explicit bootstrap, packaging, Compose and gate orchestration | Owned by local setup |
| Browser and TypeScript gateway | Have separate owners |
| All default M1/P1 services and existing standalone examples | Preserve them |

M1 is the existing confirmed-investigation intake.

## Development rules

### Imports and dependencies

- Keep imports inert and serving code dependent only on public product APIs.
- Do not import local-setup or test fixtures.
- Compatibility helpers re-export one canonical class identity.
- Avoid duplicate importlib-loaded application types.
- Preserve fixed dependency locks.
- Declare root runtime extras explicitly. A dev dependency is insufficient for a
  frozen application wheel/container.
- Test the built app and public packages outside the checkout without product fallback.

### Product authority and consent

- P2 owns accepted input/preparation, P1 owns work/issuance/result/delivery, and P3
  validates immutable facts/applicability.
- Add no execution queue or authority.
- Never infer consent, supplier effect or playback from a model statement.
- Preserve investigation-only permission and separate exact revision/quote confirmation.
- Case revise uses the public typed controller with expected revision.
- A failed acknowledgement stays uncertain.

### Native worker and room lifecycle

- Preserve the qualified canonical origin wire/service/HTTP identity.
- The native worker owns one P2 NativeRuntime/AgentSession per room, with SDK default
  text ingress and SessionHost disabled.
- Parent room ownership remains separate from the background application.
- End must not stop accepted durable work.
- Native worker configuration is scripted-only and private.
- Keep codec/import paths free of environment, SDK, assets and provider access.
- Load heavy clients explicitly during startup.
- Provider mode requires a separate versioned contract.
- Close the prepare host and native runtime concurrently.
- Observe actual SDK startup before closing wrapper/model/transport dependencies.
- Retain and settle actual real-time communication (RTC) connect before the final
  room disconnect. An early disconnect cannot prove that a late connection is gone.
- Parent physical activation identity is separate from the observed Node cursor.
- Preserve the original Start command, capabilities and absolute expiry through
  uncertain responses.
- End fences admission synchronously and retains late process/file/HTTP work.
- No new room while cleanup is unresolved.
- The public SDK close event fences admission before its asynchronous drain.
- Readiness, SDK closure, room absence and process reap are separate observations.
- DeleteRoom has no expected-SID compare-and-swap. Disclose its as-of precheck.

### HTTP server and operator routes

- Reuse the private bounded HTTP server's three closed purposes.
- Preserve the prepare protocol's exact three response headers and four-second limit.
- The current-result callback adds no-store and a final current-room check before
  successful write.
- The separate operator profile permits only seven fixed browser routes, a distinct
  operator bearer, the configured same-origin proxy, no-store and the same final
  current-room fence for grants/results.
- Never add a body-selected route, role or work identifier.
- Keep operator authorization independent of native/RTC lifetime.
- Synthetic SMS retries preserve original command/body/time and refresh only the
  message authentication code (MAC) header.
- Use the declared public simulation material, never a real carrier credential.
- Case/progress reads borrow existing app clients.
- Dispatch is not completion.

### Inputs, discovery and job ownership

- Validate/copy external data transfer objects (DTOs) and configured principals
  before awaits.
- Reject wrong scope, route, original operation/receipt/digest/bytes and changed
  payloads.
- Native and signed-SMS source owners are separate.
- Select source owners from validated stored provider/event bindings, never an
  untrusted source label.
- Prepared reads create no plan/claim/case/model call.
- Discovery is a bounded as-of observation, never an acknowledgement (ACK) or permission.
- Detect overflow.
- Do not skip an unknown/pending gap.
- Preserve original deadline/evidence after restart.
- Use one persisted logical app-owner UUID, stable command per work and at most two
  actual job owners.
- A timed-out waiter cannot free an actual runner/HTTP slot.
- Keep late factories, calls and close observers until settlement.
- Drain dependent owners before shared case readers.
- Normal stop preserves stored facts.

### Errors, logs and telemetry

- Keep finite safe error codes and bounded numeric metrics.
- Do not log raw input, token, provider key, private dependency text or metric labels
  containing IDs.
- Telemetry failure cannot change accepted work or prevent bounded cleanup.

### Media profiles and provider keys

- Scripted is the first media profile.
- Provider modes require separate trusted configuration/readiness/usage evidence.
- Only native provider runtime receives provider keys.
- Offline checks never read provider keys.
- No fallback changes the label.

## Verification

1. Run narrow tests first.
2. Then run the affected real lane, public artifact checks and full fast validation.

From the repository root:

| Check | Command | When to run |
| --- | --- | --- |
| Origin unit tests | `make channel-origin-unit` | First, when origin code is affected |
| Origin real lane | `make channel-origin-check` | After narrow tests, when origin behavior is affected |
| Origin package check | `make channel-origin-package-check` | After narrow tests, when the origin package is affected |
| Full fast validation | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh` | Before handoff |

Also:

- Existing root commands include `make channel-origin-unit`,
  `make channel-origin-check` and `make channel-origin-package-check`.
- New application commands are unavailable until their asserted runners exist.
- Register sources in lint/strict typing/harness discovery with the implementation.
- No required skip, missing fixture, zero-test runner or timeout is a pass.

## Handoff

- Record behavior, acceptance IDs, exact commands/counts, actual/fake boundaries,
  artifacts, review findings and unresolved work in
  [0045](../../docs/work-items/0045-joined-native-channel-policy.md).
- Preserve earlier seals and failed observations.
- A selected gate cannot complete the full P2/P3 charters or the global demo goal.
- Keep AI assistance and personally explainable work accurate.
