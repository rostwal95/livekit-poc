# P1 hosted-provider qualification

Status: Completed
Last reviewed: 10 November 2026

## Behavior and scope

The explicitly selected provider_real v2 profile has passed the registered P1-20
live gate: two actual browser cases with zero required skips and verified cleanup.
The reference application, LiveKit, authority, workers, console and telemetry run
locally; Deepgram/OpenAI/ElevenLabs supply inference. The separately implemented
local_real profile remains unqualified under its original resource limits.
P2/P3 remain planned. Publication and remote CI are outside this local POC.

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P1-I28 / P1-20 | Explicit provider profile, trusted native binding and private keys | Synthetic speech crosses actual browser/native WebRTC | Models cannot change task scope, choose credentials or confirm a mutation | Real recognition, submit/get tools and generated playback progress | Passed two-case live report, numeric SDK usage and sanitized model/provider spans |
| Continuity | One foreground case and eight accepted pending inquiries | Speech is interrupted, voice ends and a fresh consumer joins | Media controls never cancel business work or grant mutation authority | Original work completes and the fresh consumer reads the same case | Independent durable identity, supplier/receiver and cleanup assertions |
| Exact approval | Slow persistence/supplier and a proposed change | Controls run while dependencies are held, then the human approves | No mutation occurs before exact quote/revision confirmation | One authorized synthetic mutation and receiver delivery progress | Actual held-dependency controls and protected controller commitment |

## Interfaces and ownership

The [v2 declaration](../../local-setup/workloads/p1-provider-real-v2.json) selects
Deepgram nova-3 English batch recognition after explicit manual flush, OpenAI
gpt-5.4-mini streaming Chat Completions and ElevenLabs eleven_v4_turbo chunked
HTTP PCM speech. LiveKit Agents/plugins remain pinned to 1.8.11. The LLM wire fixes
reasoning_effort=none, store=false and 128 output tokens. Only the three bound
no-argument investigation/inspection/cancellation tools are exposed; authenticated
exact quote/revision approval remains a separate controller action.

The ignored mode-0600 credential file has exactly DEEPGRAM_API_KEY, OPENAI_API_KEY
and ELEVEN_API_KEY. Strict bounded literal parsing rejects unsafe files and values;
only the selected native process receives keys through its private temporary
Docker env file. Keys never enter builds, browser, API, worker, collector or reports.
Optional approved certificate-only trust stays native-only and read-only, with
hostname/CERT_REQUIRED verification, exact selected digest/size and post-media
rehashing. The [operations guide](../provider-demo.md) owns setup/start/stop commands.

Prepared prerecorded input is silent until a strictly verified native turn_started
reply, then plays the unchanged WAV once from sample zero. Readiness/mode/SDK-state
and input/agent/start generations reject late replies. Physical microphone capture
is independent. Worker maintenance uses the actual post-child/post-SQL checkpoint,
strict health and OS pause; its original recovery clock includes resume overhead.
There is no model/provider fallback or timing/resource waiver.

## Failure cases and validation

| Gate | Required assertion | Bound and evidence |
| --- | --- | --- |
| G-READY | Explicit credentials/mode/trust and installed-source ownership | Presence checks make no provider calls; missing or unsafe configuration fails |
| G-FAST/CONTRACT | Positive, hostile, cancellation and cleanup fixtures | Frozen dependencies, exact schemas, finite logs/labels and maintained typing/lint/frontend checks |
| G-MODEL/MEDIA | Real ASR, model tools, generated TTS and actual playback | ASR/TTS 10 seconds; LLM 30 seconds; original 600-second work, 180-second cleanup and 840-second wrapper |
| G-DURABLE | Eight inquiries through End, fresh consumer, held-dependency controls and exact consent | Original identities/deadlines, independent supplier/receiver truth and owned cleanup |

Unknown acknowledgements preserve original identities for reconciliation. Missing
usage, required skips, unsafe consent, timeout or incomplete cleanup cannot pass.
Logs keep finite event/code fields; numeric SDK reports and sanitized span copies
exclude prompts, transcripts, audio bodies, keys and raw provider exceptions.

## Results and handoff

The fresh registered provider gate passed two actual browser cases in 113.567
seconds, with zero skips and verified cleanup. The retained run observed native
submit_investigation/get_case activity, generated playback, active interruption,
End with eight pending inquiries, completed background work and a fresh consumer
for the same case. PostgreSQL/supplier waits were actually held while media
controls remained responsive; exact human approval authorized the single mutation.

| Observation | Actual result | Interpretation |
| --- | --- | --- |
| SDK usage | Four reports; 3,645 input and 97 output tokens; 4.3 ASR seconds; 12.24 generated-TTS seconds | Aggregate observed usage, separate from invoice cost or model quality |
| Native tracing | 180 spans; exact nova-3/deepgram, gpt-5.4-mini/openai and eleven_v4_turbo/elevenlabs pairs | Current-task native tool/model observations; independent raw audit passed with the final release assessment |
| Durable cohort | Eight accepted/replayed inquiries survive End; eight results/cancellations/deliveries and nine matched inquiry receipts | Zero lost accepted work; fixture cancellation remains separate from booking mutation |
| Authority | Nine tasks, one committed intent and one signal consumption; independent supplier/receiver checks passed | Media/model statements grant no exact-confirmation authority |
| Cleanup | Quiescence/resume resolved and owned resources removed | No retained active/paused/quiesced cohort or credential-container ownership |

The current four-case H2 and 263-test PostgreSQL correctness gates also passed.
P1 V1 local release qualification passed with the selected provider_real v2
profile. Source-matching package, shared quality and independent index results
are recorded in the
[Phase H release work item](0019-p1-phase-h-release-qualification.md).

The retained API trace query is limited to 100 traces and includes one failed
continuity.get span of unresolved cause. Native/worker retained queries contained
no error spans. This run establishes required progression and invariants without
a global zero-error or complete trace-history claim.

Earlier failed attempts and their immutable inputs remain retained with their
original outcomes. V2 was explicitly selected after v1 model-access observations;
no failed run was relabelled or silently retried with another provider. The local
model attempt remains unqualified. This measured local POC establishes neither
hardware-microphone quality, human hearing, WER, production capacity, external
provider CPU/memory nor zero-data-retention. Monetary billing was not measured.
