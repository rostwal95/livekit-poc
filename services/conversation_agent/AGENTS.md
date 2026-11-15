# Native conversation agent coding instructions

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Give coding agents the reading order, ownership, rules and checks for native conversation agent work |
| Audience | Coding agents and engineers changing the conversation worker, its provider extensions or its tests |
| Scope | `services/conversation_agent` and its tests; excludes shared tracing, durable authority, browser and HTTP controller |
| Owns | Agent workflow for the conversation agent: reading order, owned paths, development rules, verification and handoff |
| Related | [Root instructions](../../AGENTS.md) · [README](README.md) · [Design](Design.md) · [Phase G work item](../../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md) |

## Read first

Read these documents:

| Document | Why read it |
| --- | --- |
| [Root instructions](../../AGENTS.md) | Shared reading order, owned paths, development rules and verification |
| [README.md](README.md) | Implemented behavior, commands and validation |
| [Design.md](Design.md) | Design, limits and failure handling |
| [P1 charter](../../docs/projects/agent-continuity-scope.md) | P1 requirements and stable acceptance IDs |
| [Phase G work item](../../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md) | Phase G change plan, named real lanes and handoff |

Follow the shared [Python](../../docs/python-engineering.md),
[observability](../../docs/observability.md), and
[documentation](../../docs/documentation-standards.md) standards.

Inspect the actual installed SDK and affected tests before changing a provider extension.

## Owned paths

| Area | Responsibility |
| --- | --- |
| `services/conversation_agent`, `tests/test_conversation_agent.py` and `tests/test_conversation_composition.py` | Owned here |
| Shared tracing | Belongs to `projects/agent-continuity/python/src/continuity_lab/tracing.py` and its tests |
| Durable authority | Belongs to `continuity_lab` |
| Browser workspace and authenticated HTTP controller | Have separate owners |
| Original `services/rtc_agent` diagnostic and M1 intake | Keep them working |

M1 is the existing confirmed-investigation intake.

## Development rules

### Native SDK session

- Keep the native AgentSession, Agent and function_tool execution path.
- Use the frozen compatible SDK baseline.
- Qualify SDK changes before changing its pins.
- Keep `AgentSession.start(session_host=False)`.
- The SDK RemoteSession byte channel must not provide an alternate unbound path
  around signed-caller/readiness checks.
- Regression tests must prove the default SDK handler exists in a positive control
  and is absent from this profile, while the three bounded custom remote procedure
  calls (RPCs) remain.

### Readiness and controls

- After AgentSession.start, await the public `session.room_io.wait_for_ready()` with
  a ten-second budget before speech or any interrupting input.
- SDK listening state alone does not establish that audio output is subscribed.
- Then mark controls ready and publish `continuity.session_ready='true'`.
- The browser requires this exact attribute, a `continuity.inference_mode` match to
  its authenticated mint mode and an active SDK state.
- The runtime publishes ready and its finite mode together.
- The barrier needs the expected participant and output subscription, not microphone
  publication.
- Reject RPC/text controls before readiness.
- Readiness timeout/cancellation must not publish success or greet. The worker still
  owns independent SDK/observer/port cleanup.
- Closure invalidates controls before awaiting owned cleanup.
- Retain the deterministic gated-subscription regression: premature controls cannot
  cancel the SDK subscription future, and a later STATUS produces real audio and text.
- Require the signed caller for controls.
- Own at most two bounded text readers.
- Close rejected/read/abandoned streams and reject calls after service closure.

### Business tools and authority

- Expose only no-argument `submit_investigation`, `get_case` and `cancel_case` tools.
- Trusted composition binds actor, scope, request, replay key and current task.
- Add no model confirmation, quote mutation, signal or arbitrary task/scope tool.
- Verify signed room/participant grants before constructing a business port.
- Participant-editable metadata and transcript content grant no authority.
- Preserve investigation-only consent and the separate authenticated exact quote
  confirmation.
- Voice activity, playback and refresh hints are observations.
- Native business tools inject SDK RunContext and emit one silent pending update
  before awaiting the port.
- The pending update releases the speech turn through the supported async-tool
  lifecycle. It does not acknowledge business acceptance.
- Keep ToolFlag.NONE and the three model-visible tools.
- Do not expose companion model task cancellation/listing tools to repair media
  interruption.
- Keep the actual storage offload and its capacity owned until the operation
  finishes, even after speech interruption.
- Only a validated final receipt can trigger a refresh hint or deferred acceptance reply.
- SDK background tasks are bounded session resources, not persisted workflow authority.
- Session interruption, disconnect and cleanup never issue business cancellation.
- Preserve the original replay identity after an ambiguous tool acknowledgement.

### Inference profiles

- Preserve manual turns, vad=None and disabled inference preloading.
- Scripted is the default and retains its declared fixture mapping.
- local_real is explicit trusted configuration, with prepared local Whisper/Qwen/Piper
  and fixed private endpoints. Never silently download a model, fall back to a paid
  provider or reflect ambient OpenAI/proxy headers.
- Read the [operations guide](../../docs/local-real-inference.md) before changing
  local_real.
- Keep native/manual-flush automatic speech recognition (ASR) integration and owned
  model/session cleanup.
- Label configured mode, fixture input and actual qualified model/media results
  separately.
- Trusted inference modes are exactly scripted (default), local_real and provider_real.
- Preserve the selected mode through mint, native readiness, numeric usage and
  sanitized traces.
- A configured badge or process health is not actual inference/media qualification.
- No silent provider/model fallback exists.
- All modes preserve bound tools and separate exact human confirmation.
- Read the [provider operations guide](../../docs/provider-demo.md) before changing
  provider composition.
- Offline validation must not read private key values or invoke providers.
- Never source, print, copy or include `local-setup/.env.providers` in reports or
  build contexts.
- Only the explicit native provider runtime receives the three keys.

### Provider ASR adapter and provider limits

- Provider ASR is batch recognize after explicit manual flush, not continuous streaming.
- Preserve the SDK's active/closing recognition handoff: at most two owned handles,
  released only after successful full SDK close.
- This handoff does not increase the one-active/one-waiting ASR operation pool or
  audio/time caps.
- Keep genuine SDK usage and exact nova-3/deepgram, gpt-5.4-mini/openai and
  eleven_v4_turbo/elevenlabs trace pairs.
- Retain finite 10-second ASR/text-to-speech (TTS) and 30-second large language model
  (LLM) limits and owned cleanup.
- Do not claim provider zero retention.

### Bounded LLM input

- The bounded LLM input admits plain text and the exact canonical SDK
  CacheBreakpoint control marker.
- Preserve the marker's sole literal field and reject subclasses, extra data,
  malformed markers and media content.
- Serialized byte/item caps still include markers.

### Resources, logs and cleanup

- Keep blocking storage/export/file work off the media event loop.
- Retain finite turn, text, audio, task, queue, RPC, worker capacity and cleanup budgets.
- Keep safe finite application logs.
- Never render exception text/chains, SDK transcript bodies, grant metadata,
  credentials or full session reports.
- Export sanitized span copies.
- Do not mutate the SDK's original observations.
- Finish native session cleanup before numeric report/export cleanup, then close the
  business adapter independently.
- Incomplete cleanup remains a visible failure.

### Fixtures and evidence labels

- Update synthetic asset provenance and hashes when changing WAV fixtures.
- Keep real microphone, general speech recognition and live-model evidence separate.

## Verification

Run from the repository root with the frozen local, agent and inference extras installed:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_conversation*.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_provider*.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_tracing.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_worker_tracing.py' -v
.venv/bin/python -m harness.documentation_check
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh
```

| Check | Command | When to run |
| --- | --- | --- |
| Conversation tests | `.venv/bin/python -m unittest discover -s tests -p 'test_conversation*.py' -v` | First, for every change |
| Provider tests | `.venv/bin/python -m unittest discover -s tests -p 'test_provider*.py' -v` | First, for every change |
| Tracing tests | `.venv/bin/python -m unittest discover -s tests -p 'test_tracing.py' -v` | First, for every change |
| Worker tracing tests | `.venv/bin/python -m unittest discover -s tests -p 'test_worker_tracing.py' -v` | First, for every change |
| Documentation check | `.venv/bin/python -m harness.documentation_check` | For every change |
| Real PostgreSQL and actual browser/media lanes | Named in the [Phase G work item](../../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md) | After focused checks |
| Full fast validation | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh` | Before handoff |

- Tracing wire tests create a loopback-only receiver. They require local socket binding.
- Run the real PostgreSQL and actual browser/media lanes named in the Phase G work
  item after focused checks.
- Native audio injection and SDK tool tests alone do not establish browser playback
  or business recovery.
- Missing, skipped or timed-out required checks remain non-passing.

### Regressions to repeat

- When changing the provider ASR adapter, repeat actual AgentSession
  clear/capture/commit and cancelled-close regressions.
- When changing SDK context handling, repeat the actual AgentSession manual-turn
  positive/old-guard-negative regression. A direct factory request omits the
  CacheBreakpoint voice-pipeline control and cannot qualify that integration.

## Handoff

- Record selected acceptance/task IDs, changed boundaries, exact commands, useful
  progress and failure assertions, artifacts and unresolved limits.
- Distinguish unit, real SDK, PostgreSQL, browser transport, human microphone and
  real inference results.
- Update capability status only after inspecting the corresponding evidence.
