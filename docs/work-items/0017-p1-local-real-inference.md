# P1 Phase H4 local speech and model inference

Status: Active
Last reviewed: 10 November 2026

## Behavior and scope

Complete P1-I28 with an explicit fully local real-inference profile. Preserve the
scripted profile and its existing budgets. The user-approved target is a local
POC; GitHub publishing and remote CI are outside scope. Use actual Whisper speech
recognition, a local Qwen model through the native LiveKit LLM/plugin interface,
and generated Piper speech, with no scripted transcript/response mapping.

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P1-I28 speech/model | Explicit local profile, verified model cache and owned private engines | Real fixture PCM reaches AgentSession via WebRTC | Fixed local endpoints/headers/models, finite queues/bytes/time, no paid/provider fallback | Actual ASR text, model tool call, generated TTS and browser playback are observed | Native/model unit and actual local engine/browser qualification |
| P1-14/20 authority | Signed caller/current durable case | Model tools, interrupt, End and exact controller consent occur | Only three bound no-argument tools; no model confirmation; speech interruption never cancels business | Persisted applicable work remains inspectable and progresses independently | Real PostgreSQL, actual media and independent supplier/receiver truth |
| Local setup | Immutable model and engine declarations | Explicit prepare/start/stop commands run | No runtime model downloads, corrupt-cache replacement or secret/raw-content diagnostics | Repeatable prepared local stack and owned cleanup | Model-cache/security/process tests and actual pinned inference |

## Interfaces and ownership

Models are pinned by ten exact byte sizes/digests in local-setup/models; all files
total2,708,795,741 bytes including the859-byte Ollama manifest under a4GiB declaration. Explicit model preparation has a
hard1800s child/supervisor deadline and owned terminate/kill/reap before releasing
its file lock. Normal verification and runtime never download models. Public
model files are readable by the unprivileged engine UID; credentials remain private.
Ollama0.40.15/Qwen3:4b-instruct, whisper.cpp1.9.5/base.en and Piper1.8.0/LJSpeech
are separately bounded local engines. Retain model/engine licenses and the voice
card; the Piper process is separate from the agent. Root application adds only the
compatible pinned LiveKit OpenAI plugin1.8.11; OpenAI3.46.0/httpx2 2.16.0 remain
existing frozen versions. Existing external versions must not silently change.

Native providers own one active/one waiting HTTP operation, fixed private service
endpoints, bounded streamed response bytes and independently closed resources.
The actual wire transport clears ambient OpenAI headers/proxies; local dummy
credentials cannot become remote provider authority. Audio is PCM16 mono16kHz,
at most12s/turn; TTS is generated PCM16 mono22050Hz, at most20s/response. Real STT
and TTS each have10s native budgets around an8s engine child; LLM30s/128output
tokens/256chunks/4KiB output/64KiB context, no arbitrary tool arguments. Manual
flush STT is a supported streaming extension with vad=None; batch STT is not
silently swapped into an incompatible SDK node.

The authenticated session response and native readiness attribute bind the fixed
scripted/local_real mode. UI and trace/usage evidence must label the actual mode.
Real commit acknowledgement has its own12s browser budget; scripted8s, all other
RPC8s and media cleanup5s remain unchanged. Exact consent, original identities,
private credentials, source ownership and durable execution semantics remain.

## Failure cases and validation

Missing cache/engine/dependency or required inference is non-passing. Reject
unknown configuration/model/schema, unsafe cache/redirect paths, duplicate fields,
invalid/silent/truncated speech, excessive bytes/tokens/chunks/tasks, unsupported
media, unsafe function calls and unverified mode/readiness. Keep private captured
model/process output ephemeral; retain only fixed codes and numeric counters,
limits/timestamps/identity hashes, not prompts, transcripts, audio bodies, request
metadata, environment values or exception chains. Preserve cancellation/cleanup
and uncertain business facts separately. Model output grants no permission.

| Gate | Applicable and why | Exact tests/assertions | Prerequisite/resource/time bound | Expected status/artifacts |
| --- | --- | --- | --- | --- |
| G-READY | Freeze local model/engine/profile inputs | Exact declaration/digests, official releases/voice card, capacity preflight | Local host/Docker budget, no paid credentials | Declared inputs, not inference-quality evidence |
| G-FAST/CONTRACT | Real provider/transport and setup boundaries | Model-cache/redirect/process ownership, STT/WAV/SSE/tool/privacy/close/cancel negatives, UI mode binding | Offline synthetic transports; no provider/model downloads | Nonzero tests, zero required skips, strict types/lint/format |
| G-MODEL | Actual prepared local engines | Real speech decoding, real language-model/tool response and generated non-silent WAV | CPU/memory/PID limits, separate engine/native deadlines | Positive actual observations and safe failure handling |
| G-MEDIA/DURABLE | Complete voice/work independence | Browser WebRTC/playback/interruption/End with scoped durable result and exact controller consent | Installed final image, actual stores/supplier/receiver and fixed workload | No mock or health-only pass, owned cleanup |
| G-LOCAL-POC | Remaining P1 closure | Local artifact/API/reliability/acceptance gates and inspected real inference | User explicitly excludes remote CI/publishing | Local completion only after all applicable checks |

## Results and handoff

Implementation active. Native source draft passed25 focused and41 existing native
regression tests in review; actual root gates remain required. The final model-preparation helper and speech-engine server each passed19
offline tests. All ten pinned cache files were downloaded and verified; the
Whisper/Piper and application images built successfully. Actual real inference
and media qualification remain required. Keep declaration, download,
engine readiness, model result, browser playback and human hearing separate.
Evidence belongs under ignored .local/validation/p1-local-real with final source,
model/image/configuration provenance, measured timing/resources and owned cleanup.
