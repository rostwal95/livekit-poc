# Joined channel-policy application coding instructions

Status: Active
Last reviewed: 13 November 2026

## Read first

Read the [root instructions](../../AGENTS.md), [README.md](README.md),
[Design.md](Design.md), [active work item](../../docs/work-items/0045-joined-native-channel-policy.md),
the P2/P3 charters, and affected public APIs/tests. Follow the shared Python,
documentation and observability standards. The completed 0044 checkpoint is
historical evidence; new canonical locations require fresh qualification.

## Owned paths

Own services/channel_policy_demo and its root application tests. Product authority
stays in the P1/P2/P3 packages. Local setup owns explicit bootstrap, packaging,
Compose and gate orchestration. The browser and TypeScript gateway have separate
owners. Preserve all default M1/P1 services and existing standalone examples.

## Development rules

- Keep imports inert and serving code dependent only on public product APIs.
  Do not import local-setup or test fixtures. Compatibility helpers re-export
  one canonical class identity; avoid duplicate importlib-loaded application types.
- Preserve the qualified canonical origin wire/service/HTTP identity. The native
  worker owns one P2 NativeRuntime/AgentSession per room, with SDK default text
  ingress and SessionHost disabled. Parent room ownership remains separate from
  the background application; End must not stop accepted durable work.
- Reuse the private bounded HTTP server's three closed purposes. Preserve the
  prepare protocol's exact three response headers and four-second limit. The
  current-result callback adds no-store and a final current-room check before
  successful write. The separate operator profile permits only seven fixed
  browser routes, a distinct operator bearer, the configured same-origin proxy,
  no-store and the same final current-room fence for grants/results. Never add a body-selected route, role or work identifier.
- Native worker configuration is scripted-only and private. Keep codec/import
  paths free of environment, SDK, assets and provider access. Load heavy clients
  explicitly during startup. Provider mode requires a separate versioned contract.
- Close the prepare host and native runtime concurrently. Observe actual SDK
  startup before closing wrapper/model/transport dependencies. Retain and settle
  actual RTC connect before the final room disconnect; an early disconnect
  cannot prove that a late connection is gone.
- Parent physical activation identity is separate from the observed Node cursor.
  Preserve the original Start command, capabilities and absolute expiry through
  uncertain responses. End fences admission synchronously and retains late
  process/file/HTTP work; no new room while cleanup is unresolved.
- The public SDK close event fences admission before its asynchronous drain.
  Readiness, SDK closure, room absence and process reap are separate observations.
  DeleteRoom has no expected-SID compare-and-swap; disclose its as-of precheck.
- Keep operator authorization independent of native/RTC lifetime. Synthetic SMS
  retries preserve original command/body/time and refresh only the MAC header.
  Use the declared public simulation material, never a real carrier credential.
  Case/progress reads borrow existing app clients; dispatch is not completion.
- P2 owns accepted input/preparation, P1 owns work/issuance/result/delivery, and
  P3 validates immutable facts/applicability. Add no execution queue or authority.
  Never infer consent, supplier effect or playback from a model statement.
- Validate/copy external DTOs and configured principals before awaits. Reject
  wrong scope, route, original op/receipt/digest/bytes and changed payloads.
  Native and signed-SMS source owners are separate; select them from validated
  stored provider/event bindings, never an untrusted source label.
- Prepared reads create no plan/claim/case/model call. Discovery is a bounded
  as-of observation, never an ACK or permission. Detect overflow, do not skip an
  unknown/pending gap, and preserve original deadline/evidence after restart.
- Use one persisted logical app-owner UUID, stable command per work and at most
  two actual job owners. A timed-out waiter cannot free an actual runner/HTTP slot.
  Keep late factories, calls and close observers until settlement. Drain dependent
  owners before shared case readers; normal stop preserves stored facts.
- Preserve investigation-only permission and separate exact revision/quote
  confirmation. Case revise uses the public typed controller with expected
  revision; a failed acknowledgement stays uncertain.
- Keep finite safe error codes and bounded numeric metrics. Do not log raw input,
  token, provider key, private dependency text or metric labels containing IDs.
  Telemetry failure cannot change accepted work or prevent bounded cleanup.
- Scripted is the first media profile. Provider modes require separate trusted
  configuration/readiness/usage evidence. Only native provider runtime receives
  provider keys; offline checks never read them. No fallback changes the label.
- Preserve fixed dependency locks. Declare root runtime extras explicitly; a dev
  dependency is insufficient for a frozen application wheel/container. Test the
  built app and public packages outside the checkout without product fallback.

## Verification

Run narrow tests first, then the affected real lane, public artifact checks and
full fast validation. Existing root commands include make channel-origin-unit,
make channel-origin-check and make channel-origin-package-check. New application
commands are unavailable until their asserted runners exist. Register sources in
lint/strict typing/harness discovery with the implementation. No required skip,
missing fixture, zero-test runner or timeout is a pass.

## Handoff

Record behavior, acceptance IDs, exact commands/counts, actual/fake boundaries,
artifacts, review findings and unresolved work in 0045. Preserve earlier seals and
failed observations. A selected gate cannot complete the full P2/P3 charters or
the global demo goal. Keep AI assistance and personally explainable work accurate.
