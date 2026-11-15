# P1 hosted-provider qualification

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the `provider_real` v2 P1-20 live gate run, its declared provider pipeline and its observed limits |
| Audience | Engineers changing provider composition, credentials, certificate trust or media gates; reviewers; coding agents |
| Scope | Hosted Deepgram, OpenAI and ElevenLabs inference for the local POC; excludes `local_real`, P2/P3 and remote CI |
| Owns | Provider configuration and media results; provider-qualification observed verification and handoff |
| Related | [Provider operations guide](../provider-demo.md) · [v2 declaration](../../local-setup/workloads/p1-provider-real-v2.json) · [Release work item](0019-p1-phase-h-release-qualification.md) · [Local-real work item](0017-p1-local-real-inference.md) |

## Behavior and scope

The explicitly selected `provider_real` v2 profile passed the registered P1-20
live gate. The gate ran two actual browser cases with zero required skips and
verified cleanup.

The reference application, LiveKit, the authority, workers, the console and
telemetry run locally. Deepgram, OpenAI and ElevenLabs supply inference. The
separately implemented `local_real` profile remains unqualified under its original
resource limits. P2 and P3 remain planned. Publication and remote continuous
integration (CI) are outside this local proof of concept (POC).

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P1-I28 / P1-20 | Explicit provider profile, trusted native binding and private keys | Synthetic speech crosses actual browser/native WebRTC | Models cannot change task scope, choose credentials or confirm a mutation | Real recognition, submit/get tools and generated playback progress | Passed two-case live report, numeric software development kit (SDK) usage and sanitized model/provider spans |
| Continuity | One foreground case and eight accepted pending inquiries | Speech is interrupted, voice ends and a fresh consumer joins | Media controls never cancel business work or grant mutation authority | Original work completes and the fresh consumer reads the same case | Independent durable identity, supplier/receiver and cleanup assertions |
| Exact approval | Slow persistence/supplier and a proposed change | Controls run while dependencies are held, then the human approves | No mutation occurs before exact quote/revision confirmation | One authorized synthetic mutation and receiver delivery progress | Actual held-dependency controls and protected controller commitment |

## Interfaces and ownership

### Declared provider pipeline

The [v2 declaration](../../local-setup/workloads/p1-provider-real-v2.json) selects
these providers:

| Role | Selection |
| --- | --- |
| Automatic speech recognition (ASR) | Deepgram nova-3 English batch recognition after explicit manual flush |
| Large language model (LLM) | OpenAI gpt-5.4-mini streaming Chat Completions |
| Text-to-speech (TTS) | ElevenLabs eleven_v4_turbo chunked HTTP pulse-code modulation (PCM) speech |

LiveKit Agents and its plugins remain pinned to 1.8.11. The LLM wire request fixes
`reasoning_effort=none`, `store=false` and 128 output tokens. Only the three bound
no-argument tools are exposed: investigation, inspection and cancellation.
Authenticated exact quote/revision approval remains a separate controller action.

### Credentials and certificate trust

The ignored mode-0600 credential file has exactly `DEEPGRAM_API_KEY`,
`OPENAI_API_KEY` and `ELEVEN_API_KEY`. Strict bounded literal parsing rejects
unsafe files and values. Only the selected native process receives keys, through
its private temporary Docker env file. Keys never enter builds, the browser, the
API, workers, the collector or reports.

Optional approved certificate-only trust stays native-only and read-only. It uses
hostname and `CERT_REQUIRED` verification, the exact selected digest and size, and
rehashing after media. The [operations guide](../provider-demo.md) owns the setup,
start and stop commands.

### Prerecorded input and worker maintenance

Prepared prerecorded input is silent until a strictly verified native
`turn_started` reply arrives. It then plays the unchanged WAV once from sample
zero. Readiness, mode and SDK-state generations, and input, agent and start
generations, reject late replies. Physical microphone capture is independent.

Worker maintenance uses the actual checkpoint after the child process and SQL
work, strict health and an operating-system pause. Its original recovery clock
includes resume overhead. There is no model or provider fallback and no timing or
resource waiver.

## Failure cases and validation

Gate names starting with G- refer to the engineering gates in the
[validation plan](../validation-plan.md). G-MODEL is specific to this work item.

| Gate | Required assertion | Bound and evidence |
| --- | --- | --- |
| G-READY | Explicit credentials/mode/trust and installed-source ownership | Presence checks make no provider calls; missing or unsafe configuration fails |
| G-FAST/CONTRACT | Positive, hostile, cancellation and cleanup fixtures | Frozen dependencies, exact schemas, finite logs/labels and maintained typing/lint/frontend checks |
| G-MODEL/MEDIA | Real ASR, model tools, generated TTS and actual playback | ASR/TTS 10 seconds; LLM 30 seconds; original 600-second work, 180-second cleanup and 840-second wrapper |
| G-DURABLE | Eight inquiries through End, fresh consumer, held-dependency controls and exact consent | Original identities/deadlines, independent supplier/receiver truth and owned cleanup |

Unknown acknowledgements preserve original identities for reconciliation. Missing
usage, required skips, unsafe consent, a timeout or incomplete cleanup cannot
pass. Logs keep finite event and code fields. Numeric SDK reports and sanitized
span copies exclude prompts, transcripts, audio bodies, keys and raw provider
exceptions.

## Results and handoff

### Provider gate run

The fresh registered provider gate passed two actual browser cases in 113.567
seconds, with zero skips and verified cleanup. The retained run observed:

- native `submit_investigation` and `get_case` activity;
- generated playback and active interruption;
- End with eight pending inquiries;
- completed background work and a fresh consumer for the same case.

PostgreSQL and supplier waits were actually held while media controls remained
responsive. Exact human approval authorized the single mutation.

| Observation | Actual result | Interpretation |
| --- | --- | --- |
| SDK usage | Four reports; 3,645 input and 97 output tokens; 4.3 ASR seconds; 12.24 generated-TTS seconds | Aggregate observed usage, separate from invoice cost or model quality |
| Native tracing | 180 spans; exact nova-3/deepgram, gpt-5.4-mini/openai and eleven_v4_turbo/elevenlabs pairs | Current-task native tool/model observations; independent raw audit passed with the final release assessment |
| Durable cohort | Eight accepted/replayed inquiries survive End; eight results/cancellations/deliveries and nine matched inquiry receipts | Zero lost accepted work; fixture cancellation remains separate from booking mutation |
| Authority | Nine tasks, one committed intent and one signal consumption; independent supplier/receiver checks passed | Media/model statements grant no exact-confirmation authority |
| Cleanup | Quiescence/resume resolved and owned resources removed | No retained active/paused/quiesced cohort or credential-container ownership |

### Release context

The current four-case Phase H2 restart and slow-supplier workload (H2) and the
263-test PostgreSQL correctness gates also passed. P1 V1 (the fixed version-1
project scope) local release qualification passed with the selected
`provider_real` v2 profile. The source-matching package, shared quality and
independent index results are recorded in the
[Phase H release work item](0019-p1-phase-h-release-qualification.md).

### Trace limits

The retained API trace query is limited to 100 traces. It includes one failed
`continuity.get` span of unresolved cause. The native and worker retained queries
contained no error spans. This run establishes the required progression and
invariants. It makes no global zero-error or complete trace-history claim.

### Earlier attempts and limits

Earlier failed attempts and their immutable inputs remain retained with their
original outcomes. V2 was explicitly selected after v1 model-access observations.
No failed run was relabelled or silently retried with another provider. The local
model attempt remains unqualified.

This measured local POC establishes none of the following:

- hardware-microphone quality or human hearing;
- word error rate (WER);
- production capacity;
- external provider CPU/memory;
- zero data retention.

Monetary billing was not measured.
