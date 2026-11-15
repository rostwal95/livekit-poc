/** Isolated native P2 demo. Only an application ACK can establish input acceptance. */
import { DataPacket_Kind, ParticipantKind, Room, RoomEvent, Track } from 'livekit-client';
import type { RemoteParticipant, RemoteTrack } from 'livekit-client';
import { createScriptedInput } from './scripted-input';
import type { ScriptedInputSource } from './scripted-input';
import { readNativeVoiceText } from './voice';
import {
  freezeNativeInput,
  NativeInputs,
  NativeGenerations,
  NativeUiError,
  nativeReady,
  NATIVE_INPUT_ATTRIBUTE,
  parseNativeAck,
  parseNativeGeneration,
  parseNativeSession,
  parseNativeTurnReply,
  turnPayload,
} from './p2-native-policy';
import type { NativeSession, TurnMethod } from './p2-native-policy';
import { NativePlaybackMeter, PlaybackMeterError } from './p2-playback-meter';
import {
  NativeResponses,
  parseResponseMapping,
  parseResponseView,
  playbackPayload,
  interruptPayload,
  validateInterruptReply,
  validatePlaybackReply,
} from './p2-response-policy';
import {
  CurrentContext,
  DEFAULT_CONTEXT_QUERY,
  parseRehydrationContext,
} from './p2-context-policy';
import { ContextPanel } from './p2-context-panel';
import { parseBusinessJson } from './business';
import './p2-native.css';

function element<T extends HTMLElement>(id: string): T {
  const result = document.getElementById(id);
  if (!result) throw new Error('The native demo view is incomplete.');
  return result as T;
}
const access = element<HTMLInputElement>('native-access');
const message = element<HTMLTextAreaElement>('native-message');
const textId = element<HTMLInputElement>('native-text-id');
const voiceId = element<HTMLInputElement>('native-voice-id');
const status = element('native-status');
const history = element<HTMLOListElement>('native-history');
const audioHost = element('native-audio');
const playbackReports = element<HTMLInputElement>('native-playback-reports');
const currentContext = new CurrentContext();
const contextPanel = new ContextPanel(element('native-context-body'));
const contextRefresh = element<HTMLButtonElement>('native-context-refresh');
const contextForget = element<HTMLButtonElement>('native-context-forget');
const smsButton = element<HTMLButtonElement>('native-sms');
let rehydrationRequired = false;
let contextBoundId: string | null = null;
let contextAutoAttempted: string | null = null;
let contextReads = 0;
let smsPending = false;
let smsController: AbortController | null = null;
let smsKnown = false;

const controls = Object.fromEntries(
  ['join', 'end', 'send', 'retry', 'publish', 'start', 'commit', 'interrupt', 'enable-audio'].map(
    (name) => [name, element<HTMLButtonElement>('native-' + name)],
  ),
) as Record<string, HTMLButtonElement>;
const inputs = new NativeInputs();
let generations = new NativeGenerations();
let responses = new NativeResponses();
let browserAccess = '';
let meter: NativePlaybackMeter | null = null;
let meterCreating = false;
let meterTrackId: string | null = null;
const retainedMeters = new Set<NativePlaybackMeter>();
let activeResponse: string | null = null;
let communicationEnabled = false;
const attemptedAutoStart = new Set<string>();
const reportEvents = new Map<string, { eventId: string; payload: string; known: boolean }>();
const reporting = new Set<string>();
const responseElements = new Map<string, HTMLElement>();
const responseReads = new Map<string, { unavailable: boolean }>();
let renderedHistory = '';
const outputs: string[] = [];
const actual = new Set<Promise<unknown>>();
const ackTimers = new Map<string, ReturnType<typeof setTimeout>>();
const audio = new Map<string, { track: RemoteTrack; element: HTMLMediaElement }>();
let room: Room | null = null;
let bound: NativeSession | null = null;
let lifetime = new AbortController();
let generation = 0;
let connection = 'Disconnected';
let ready = false;
let joining = false;
let closing: Promise<void> | null = null;
let cleanupIncomplete = false;
let fixture: ScriptedInputSource | null = null;
let fixtureBusy = false;
let turnBusy = false;
let turnStarted = false;
let currentTurn: string | null = null;
let readers = 0;
let playbackObserved = false;
let sessionTimer: ReturnType<typeof setTimeout> | null = null;
const counts = {
  sent: 0,
  accepted: 0,
  replayed: 0,
  rejected: 0,
  unknown: 0,
  invalid_ack: 0,
  generation_events: 0,
  invalid_generation: 0,
  incoming_streams: 0,
  stream_bytes: 0,
  stream_rejected: 0,
  completed_streams: 0,
};
textId.value = crypto.randomUUID();
voiceId.value = crypto.randomUUID();

function notice(text: string): void {
  status.textContent = text;
}
function lastText() {
  return (
    inputs
      .values()
      .filter((row) => row.channel === 'web_chat')
      .at(-1) ?? null
  );
}
function selected(participant: RemoteParticipant | undefined): boolean {
  return (
    bound !== null &&
    participant?.identity === bound.agentId &&
    participant.kind === ParticipantKind.AGENT
  );
}
function render(): void {
  const contextValue = currentContext.value;
  element('native-context').hidden = !rehydrationRequired && contextValue === null;
  element('native-context-phase').textContent =
    currentContext.phase === 'loading'
      ? 'Checking current access'
      : currentContext.phase === 'ready'
        ? contextValue?.case.revision === '0'
          ? 'Case restored · read only'
          : 'Case restored'
        : currentContext.phase === 'unavailable'
          ? 'Current read unavailable'
          : currentContext.phase === 'ended'
            ? 'Room ended · observations retained'
            : 'No case loaded';
  contextPanel.render(
    contextValue,
    currentContext.phase,
    room !== null && connection === 'Connected',
  );
  contextRefresh.disabled =
    !bound ||
    !browserAccess ||
    !rehydrationRequired ||
    contextReads > 0 ||
    actual.size >= 4 ||
    turnBusy;
  contextForget.disabled =
    room !== null || joining || closing !== null || actual.size > 0 || contextValue === null;
  smsButton.disabled =
    room !== null ||
    joining ||
    closing !== null ||
    actual.size >= 4 ||
    contextValue === null ||
    smsPending ||
    smsKnown;

  controls.join!.disabled =
    joining || room !== null || closing !== null || cleanupIncomplete || actual.size > 0;
  controls.end!.disabled = !room && !joining;
  controls.send!.disabled = !ready || turnBusy || actual.size >= 4;
  controls.retry!.disabled = !ready || lastText() === null || actual.size >= 4;
  controls.publish!.disabled = !ready || fixtureBusy || fixture !== null;
  controls.start!.disabled = !ready || fixture === null || turnBusy || turnStarted;
  controls.commit!.disabled = !ready || currentTurn === null || turnBusy;
  controls.interrupt!.disabled = !ready || turnBusy;
  controls['enable-audio']!.disabled = room === null;
  message.disabled = !ready;
  textId.disabled = !ready;
  voiceId.disabled = !ready || currentTurn !== null;
  element('native-connection').textContent = connection;
  element('native-readiness').textContent = ready
    ? 'Native agent ready'
    : rehydrationRequired && currentContext.value?.case.revision === '0'
      ? 'Case restored · native continuation unavailable'
      : rehydrationRequired && currentContext.phase !== 'ready'
        ? 'Restoring current case'
        : 'Waiting for agent';
  element('native-readiness').dataset.active = String(ready);
  element('native-playback').textContent = playbackObserved
    ? 'Playback observed'
    : 'Playback unobserved';
  const rows = inputs.values();
  const voice = rows.find(
    (row) => row.inputId === currentTurn && row.channel === 'voice_transcript',
  );
  if (!turnStarted && voice?.receiptId) {
    const completed = generations
      .values()
      .some((item) => item.inputId === voice.inputId && item.status === 'completed');
    element('native-turn').textContent = completed
      ? 'Voice input durably accepted · native reply complete'
      : 'Voice input durably accepted';
  }
  element('native-count').textContent = `${rows.length} INPUT${rows.length === 1 ? '' : 'S'}`;
  const signature = JSON.stringify([rows, outputs, generations.values()]);
  if (signature !== renderedHistory) {
    renderedHistory = signature;
    history.replaceChildren();
    for (const row of rows) {
      const li = document.createElement('li');
      li.dataset.status = row.status;
      li.dataset.inputId = row.inputId;
      const source = document.createElement('div');
      source.className = 'native-entry-source';
      source.textContent =
        row.channel === 'web_chat' ? 'Your text · committed input' : 'Your voice · committed input';
      const body = document.createElement('p');
      body.className = 'native-entry-body';
      body.textContent = row.body ?? 'Voice turn';
      const state = document.createElement('div');
      state.className = 'native-entry-state';
      state.textContent =
        row.status === 'pending'
          ? 'Awaiting durable acceptance'
          : row.status === 'unknown'
            ? 'Acceptance unknown · retain the original input'
            : row.status === 'accepted'
              ? 'Durably accepted'
              : row.status === 'replayed'
                ? 'Original acceptance replayed'
                : 'Input rejected';
      const ids = document.createElement('div');
      ids.className = 'native-entry-ids';
      ids.textContent = row.receiptId
        ? `Receipt ${row.receiptId} · operation ${row.operationKey}`
        : `Input ${row.inputId}`;
      const generated = generations.values().filter((item) => item.inputId === row.inputId);
      if (generated.some((item) => item.status === 'completed'))
        state.textContent += ' · Native SDK reply complete';
      else if (generated.some((item) => item.status === 'started'))
        state.textContent += ' · Native processing started';
      li.append(source, body, state, ids);
      history.append(li);
    }
    for (const text of outputs) {
      const li = document.createElement('li');
      const source = document.createElement('div');
      source.className = 'native-entry-source';
      source.textContent = 'Native transcription · source observation';
      const body = document.createElement('p');
      body.className = 'native-entry-body';
      body.textContent = text;
      li.append(source, body);
      history.append(li);
    }
  }
  element('native-empty').hidden = rows.length + outputs.length !== 0;
  renderResponses();
  element('native-evidence').textContent = JSON.stringify(
    {
      connection,
      ready,
      bindingId: bound?.bindingId ?? null,
      inputs: rows.map(
        ({ inputId, channel, status: state, receiptId, operationKey, acceptanceSequence }) => ({
          inputId,
          channel,
          status: state,
          receiptId,
          operationKey,
          acceptanceSequence,
        }),
      ),
      responses: responses.values().map(({ mapping, view, sample }) => ({
        responseId: mapping.responseId,
        generationId: mapping.generationId,
        inputId: mapping.inputId,
        operationKey: mapping.operationKey,
        sdkSpeechId: mapping.sdkSpeechId,
        observationCount: view?.observationCount ?? mapping.observationCount,
        generated_observed: view?.generatedText !== null && view?.generatedText !== undefined,
        sdk_state: view?.sdkState ?? 'unknown',
        browser_state: view?.browserState ?? 'unknown',
        conflicted: view?.conflicted ?? false,
        observed_audio_ms: sample?.observedAudioMs ?? 0,
        sampled_audio_ms: sample?.sampledAudioMs ?? 0,
      })),
      rehydration: {
        required: rehydrationRequired,
        phase: currentContext.phase,
        ready: currentContext.ready,
        contextId: currentContext.value?.contextId ?? null,
        bindingId: currentContext.value?.access.bindingId ?? null,
        caseId: currentContext.value?.case.caseId ?? null,
        caseRevision: currentContext.value?.case.revision ?? null,
        caseSource: currentContext.value?.case.source ?? null,
        historyReceipts:
          currentContext.value?.history.messages.map((m) => m.receipt.receiptId) ?? [],
        historyChannels:
          currentContext.value?.history.messages.map((m) => m.event.channel ?? m.event.type) ?? [],
        pendingOperations: currentContext.value?.work.items.map((w) => w.operationKey) ?? [],
        historicalResponses:
          currentContext.value?.responses.items.map((r) => ({
            responseId: r.anchor.responseId,
            bindingId: r.anchor.bindingId,
            generationId: r.anchor.generationId,
            sdkSpeechId: r.anchor.sdkSpeechId,
            sdkState: r.sdk.state,
            browserState: r.browserState,
            historical: r.historical,
          })) ?? [],
        actualReads: contextReads,
        smsKnown,
      },
      observations: {
        ...counts,
        active_io: actual.size,
        active_readers: readers,
        fixture_live: fixture?.track.readyState === 'live',
        native_transcriptions: outputs.length,
        completed_inputs: generations.completedInputs(),
        generation_observations: generations
          .values()
          .map(({ generationId, inputId, status }) => ({ generationId, inputId, status })),
        playback_observed: playbackObserved,
        playback_meters: retainedMeters.size,
        playback_meter_creating: meterCreating,
        cleanup_incomplete: cleanupIncomplete,
      },
    },
    null,
    2,
  );
}

function renderResponses(): void {
  const host = element('native-responses');
  for (const entry of responses.values()) {
    const id = entry.mapping.responseId;
    let card = responseElements.get(id);
    if (!card) {
      card = document.createElement('li');
      card.dataset.responseId = id;
      card.className = 'native-response';
      const title = document.createElement('h3');
      title.textContent = 'Agent response';
      card.append(title);
      for (const [key, label] of [
        ['generated', 'Generated text'],
        ['sdk', 'SDK output'],
        ['browser', 'Browser report'],
      ] as const) {
        const lane = document.createElement('div');
        lane.className = 'native-response-lane';
        const heading = document.createElement('h4');
        heading.textContent = label;
        const body = document.createElement('p');
        body.dataset.lane = key;
        lane.append(heading, body);
        card.append(lane);
      }
      const readStatus = document.createElement('p');
      readStatus.dataset.lane = 'read-status';
      readStatus.setAttribute('role', 'status');
      readStatus.className = 'native-muted';
      card.append(readStatus);
      const live = document.createElement('p');
      live.dataset.lane = 'samples';
      live.className = 'native-muted';
      card.append(live);
      const actions = document.createElement('div');
      actions.className = 'native-actions';
      for (const [name, label, action] of [
        ['interrupt', 'Interrupt this response', () => void interruptResponse(id)],
        ['complete', 'Report playback complete', () => void reportPlayback(id, 'completed')],
        ['refresh', 'Refresh evidence', () => void refreshResponse(id)],
      ] as const) {
        const button = document.createElement('button');
        button.className = 'secondary';
        button.dataset.action = name;
        button.textContent = label;
        button.addEventListener('click', action);
        actions.append(button);
      }
      const refs = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = 'Response references';
      const value = document.createElement('p');
      value.className = 'native-entry-ids';
      value.textContent = `Response ${id} · generation ${entry.mapping.generationId} · speech ${entry.mapping.sdkSpeechId}`;
      refs.append(summary, value);
      card.append(actions, refs);
      host.append(card);
      responseElements.set(id, card);
    }
    const view = entry.view;
    const unavailable = responseReads.get(id)?.unavailable ?? false;
    card.dataset.readStatus = unavailable ? 'unavailable' : view ? 'available' : 'unknown';
    const readStatus = card.querySelector<HTMLElement>('[data-lane="read-status"]')!;
    readStatus.textContent = unavailable
      ? 'Latest evidence read unavailable. Retained source observations remain visible.'
      : 'Latest observed source evidence';
    card.dataset.sdkState = view?.sdkState ?? 'unknown';
    card.dataset.browserState = view?.browserState ?? 'unknown';
    card.dataset.conflicted = String(view?.conflicted ?? false);
    card.querySelector<HTMLElement>('[data-lane="generated"]')!.textContent =
      view?.generatedText ?? 'Full generation unobserved';
    card.querySelector<HTMLElement>('[data-lane="sdk"]')!.textContent =
      `${view?.sdkState ?? 'unknown'} · ${view?.sdkText ?? 'Synchronized text unavailable'}`;
    card.querySelector<HTMLElement>('[data-lane="browser"]')!.textContent = view?.conflicted
      ? 'Conflicting source observations · inspect retained evidence'
      : view?.browserState === 'completed_reported'
        ? 'Completion reported by this client'
        : `${view?.browserState ?? 'unknown'} · completion unconfirmed`;
    card.querySelector<HTMLElement>('[data-lane="samples"]')!.textContent = entry.sample
      ? `${entry.sample.observedAudioMs} ms of non-silent PCM in this response window while output was playing. Continuous-track samples do not establish exact speech delivery or hearing.`
      : 'No response-window audio samples observed.';
    for (const button of card.querySelectorAll<HTMLButtonElement>('button')) {
      const action = button.dataset.action;
      button.disabled =
        !ready ||
        !bound ||
        actual.size >= 4 ||
        (action === 'interrupt' && (activeResponse !== id || actual.size >= 3)) ||
        (action === 'complete' && (!playbackReports.checked || !entry.sample?.observedAudioMs));
    }
  }
  element('native-responses-empty').hidden = responses.values().length !== 0;
}
async function refreshResponse(responseId: string): Promise<void> {
  const entry = responses.values().find((row) => row.mapping.responseId === responseId);
  if (!entry || !bound || !browserAccess || actual.size >= 4) return;
  const epoch = generation,
    session = bound,
    token = browserAccess,
    observation = { unavailable: responseReads.get(responseId)?.unavailable ?? false };
  responseReads.set(responseId, observation);
  const read = async () => {
    const response = await fetch('/p2/response', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ schemaVersion: 1, responseId }),
      credentials: 'omit',
      cache: 'no-store',
      redirect: 'error',
      signal: lifetime.signal,
    });
    if (!response.ok || !response.body) {
      await response.body?.cancel();
      throw new Error('Evidence unavailable.');
    }
    const reader = response.body.getReader(),
      parts: Uint8Array[] = [];
    let size = 0;
    try {
      while (true) {
        const next = await reader.read();
        if (next.done) break;
        size += next.value.byteLength;
        if (size > 65536) throw new Error('Evidence exceeded limit.');
        parts.push(next.value);
      }
    } finally {
      await reader.cancel().catch(() => undefined);
      reader.releaseLock();
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const part of parts) {
      bytes.set(part, offset);
      offset += part.byteLength;
    }
    const view = parseResponseView(bytes, entry.mapping, session, inputs);
    if (epoch === generation && bound === session) {
      responses.inspect(view);
      if (responseReads.get(responseId) === observation) observation.unavailable = false;
    }
  };
  try {
    await deadline(
      trackActual(
        read().finally(() => {
          observeReady();
        }),
      ),
      5000,
    );
  } catch {
    if (epoch === generation && bound === session && responseReads.get(responseId) === observation)
      observation.unavailable = true;
  } finally {
    render();
  }
}
async function reportPlayback(
  responseId: string,
  state: 'started' | 'partial' | 'interrupted' | 'completed',
): Promise<void> {
  const entry = responses.values().find((row) => row.mapping.responseId === responseId);
  const owned = room,
    session = bound,
    epoch = generation,
    key = responseId + ':' + state;
  if (
    !entry ||
    !owned ||
    !session ||
    !ready ||
    !playbackReports.checked ||
    actual.size >= 4 ||
    reporting.has(key)
  )
    return;
  let event = reportEvents.get(key);
  if (!event) {
    const eventId = crypto.randomUUID();
    event = {
      eventId,
      payload: playbackPayload(eventId, responseId, state, entry.sample?.observedAudioMs ?? 0),
      known: false,
    };
    reportEvents.set(key, event);
  }
  if (event.known) return;
  reporting.add(key);
  try {
    const reply = await deadline(
      trackActual(
        owned.localParticipant.performRpc({
          destinationIdentity: session.agentId,
          method: 'p2.playback',
          payload: event.payload,
          responseTimeout: 8000,
        }),
      ),
    );
    validatePlaybackReply(reply, responseId, event.eventId);
    if (epoch === generation && bound === session) {
      event.known = true;
      await refreshResponse(responseId);
    }
  } catch {
    if (epoch === generation)
      notice(
        'Playback report acknowledgement is unknown. Retry preserves its original observation.',
      );
  } finally {
    reporting.delete(key);
    render();
  }
}
async function interruptResponse(responseId: string): Promise<void> {
  const owned = room,
    session = bound,
    epoch = generation;
  if (!owned || !session || !ready || activeResponse !== responseId || actual.size >= 3) return;
  void reportPlayback(responseId, 'partial');
  try {
    const reply = await deadline(
      trackActual(
        owned.localParticipant.performRpc({
          destinationIdentity: session.agentId,
          method: 'p2.interrupt_response',
          payload: interruptPayload(responseId),
          responseTimeout: 8000,
        }),
      ),
    );
    validateInterruptReply(reply, responseId);
    if (epoch === generation)
      notice('Interruption requested for this response. Accepted input remains durable.');
  } catch {
    if (epoch === generation)
      notice('Interruption acknowledgement is unknown. Inspect this response before retrying.');
  }
}
function observeReady(): void {
  const participant = bound ? room?.remoteParticipants.get(bound.agentId) : undefined;
  const native = nativeReady(
    connection === 'Connected',
    bound,
    participant?.identity ?? null,
    participant?.kind === ParticipantKind.AGENT ? 'agent' : 'other',
    participant?.attributes ?? {},
  );
  const profile = participant?.attributes['p2.rehydration_profile'];
  if (selected(participant) && profile !== undefined) rehydrationRequired = true;
  if (rehydrationRequired && bound && contextBoundId !== bound.bindingId) {
    contextBoundId = bound.bindingId;
    currentContext.bind(bound);
  }
  const loaded =
    profile === 'current_case_v1' && participant?.attributes['p2.context_ready'] === 'true';
  ready =
    native &&
    (!rehydrationRequired ||
      (loaded && currentContext.ready && currentContext.value?.case.revision !== '0'));
  if (
    native &&
    rehydrationRequired &&
    loaded &&
    bound &&
    contextAutoAttempted !== bound.bindingId &&
    actual.size < 4
  ) {
    contextAutoAttempted = bound.bindingId;
    void refreshContext();
  }
  if (!ready && fixture) fixture.track.enabled = false;
  if (ready && fixture) fixture.track.enabled = true;
  render();
}
async function readContextBody(response: Response): Promise<Uint8Array> {
  if (!response.ok || !response.body) {
    await response.body?.cancel();
    throw new NativeUiError('unknown', 'Context unavailable.');
  }
  const reader = response.body.getReader(),
    parts: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      size += next.value.byteLength;
      if (size > 65536) throw new NativeUiError('invalid', 'Context exceeded its bound.');
      parts.push(next.value);
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const part of parts) {
    body.set(part, offset);
    offset += part.length;
  }
  return body;
}
async function refreshContext(): Promise<void> {
  if (
    !bound ||
    !browserAccess ||
    !rehydrationRequired ||
    contextReads > 0 ||
    actual.size >= 4 ||
    turnBusy
  )
    return;
  const ticket = currentContext.begin();
  if (!ticket) return;
  const epoch = generation,
    session = bound,
    token = browserAccess,
    signal = lifetime.signal;
  contextReads++;
  ready = false;
  render();
  const read = async () => {
    const raw = await readContextBody(
      await fetch('/p2/context', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ schemaVersion: 1, query: DEFAULT_CONTEXT_QUERY }),
        credentials: 'omit',
        cache: 'no-store',
        redirect: 'error',
        signal,
      }),
    );
    if (epoch !== generation || bound !== session) return;
    currentContext.accept(ticket, parseRehydrationContext(raw, session, currentContext.identity));
  };
  try {
    await deadline(
      trackActual(
        read().finally(() => {
          contextReads--;
          observeReady();
        }),
      ),
      5000,
    );
  } catch {
    if (epoch === generation && bound === session) currentContext.unavailable(ticket);
  } finally {
    observeReady();
  }
}
async function deliverDemoSms(): Promise<void> {
  if (
    room ||
    joining ||
    closing ||
    smsPending ||
    smsKnown ||
    actual.size >= 4 ||
    !currentContext.value
  )
    return;
  const token = access.value;
  access.value = '';
  if (!/^[A-Za-z0-9_-]{32,256}$/.test(token)) {
    notice('Enter demo access to deliver the configured SMS.');
    return;
  }
  const epoch = generation;
  const controller = new AbortController();
  smsController = controller;
  smsPending = true;
  element('native-sms-state').textContent = 'Awaiting the local carrier acknowledgement';
  render();
  try {
    const operation = async () => {
      const raw = await readContextBody(
        await fetch('/p2/sms', {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
          body: '{"schemaVersion":1}',
          credentials: 'omit',
          cache: 'no-store',
          redirect: 'error',
          signal: controller.signal,
        }),
      );
      if (raw.length > 4096)
        throw new NativeUiError('invalid', 'Carrier reply exceeded its bound.');
      const v = parseBusinessJson(new TextDecoder('utf-8', { fatal: true }).decode(raw));
      if (!v || typeof v !== 'object' || Array.isArray(v))
        throw new NativeUiError('invalid', 'Carrier reply unavailable.');
      const r = v as Record<string, unknown>;
      if (
        Object.keys(r).sort().join() !==
          'caseRevision,eventId,operationKey,receiptId,schemaVersion,smsAccepted,status' ||
        r.schemaVersion !== 1 ||
        r.status !== 'passed' ||
        r.smsAccepted !== 1 ||
        r.caseRevision !== '2' ||
        ['eventId', 'receiptId', 'operationKey'].some(
          (k) =>
            typeof r[k] !== 'string' ||
            !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])/u.test(
              r[k] as string,
            ),
        )
      )
        throw new NativeUiError('invalid', 'Carrier acknowledgement could not be verified.');
      if (epoch === generation) {
        smsKnown = true;
        element('native-sms-state').textContent = 'SMS accepted. Rejoin to load the current case.';
      }
    };
    await deadline(
      trackActual(
        operation().finally(() => {
          smsPending = false;
          if (smsController === controller) smsController = null;
          render();
        }),
      ),
      8000,
    );
  } catch {
    if (epoch === generation)
      element('native-sms-state').textContent =
        'SMS acknowledgement unknown. Retry the same configured request.';
  } finally {
    render();
  }
}
function trackActual<T>(work: Promise<T>): Promise<T> {
  actual.add(work);
  render();
  void work.then(
    () => {
      actual.delete(work);
      render();
    },
    () => {
      actual.delete(work);
      render();
    },
  );
  return work;
}
async function deadline<T>(work: Promise<T>, milliseconds = 8000): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      work,
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(
          () =>
            reject(
              new NativeUiError(
                'unknown',
                'The acknowledgement is unknown. Retain the original input.',
              ),
            ),
          milliseconds,
        );
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}
function awaitingAck(inputId: string): void {
  const old = ackTimers.get(inputId);
  if (old !== undefined) clearTimeout(old);
  ackTimers.set(
    inputId,
    setTimeout(() => {
      ackTimers.delete(inputId);
      inputs.uncertain(inputId);
      render();
    }, 5000),
  );
}
async function mint(token: string): Promise<NativeSession> {
  const response = await fetch('/p2/session', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: '{}',
    credentials: 'omit',
    cache: 'no-store',
    redirect: 'error',
    signal: lifetime.signal,
  });
  if (!response.ok || !response.body) {
    await response.body?.cancel();
    throw new NativeUiError('unknown', 'The local demo session could not be joined.');
  }
  const reader = response.body.getReader();
  const parts: Uint8Array[] = [];
  let bytes = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      bytes += next.value.byteLength;
      if (bytes > 16384)
        throw new NativeUiError('invalid', 'The session response exceeded its limit.');
      parts.push(next.value);
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
  const joined = new Uint8Array(bytes);
  let offset = 0;
  for (const part of parts) {
    joined.set(part, offset);
    offset += part.byteLength;
  }
  return parseNativeSession(
    JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(joined)) as unknown,
  );
}
function attachOutput(track: RemoteTrack, participant: RemoteParticipant): void {
  if (
    !selected(participant) ||
    track.kind !== Track.Kind.Audio ||
    !track.sid ||
    audio.size >= 2 ||
    audio.has(track.sid)
  )
    return;
  const output = track.attach();
  output.autoplay = true;
  output.controls = true;
  output.setAttribute('aria-label', 'Native P2 audio output');
  output.addEventListener(
    'playing',
    () => {
      playbackObserved = true;
      if (track.sid === meterTrackId) meter?.playing(true);
      render();
    },
    { signal: lifetime.signal },
  );
  for (const event of ['pause', 'waiting', 'ended', 'emptied'])
    output.addEventListener(
      event,
      () => {
        if (track.sid === meterTrackId) meter?.playing(false);
      },
      { signal: lifetime.signal },
    );
  audio.set(track.sid, { track, element: output });
  audioHost.append(output);
  if (communicationEnabled) startMeter(track, output);
}
function startMeter(track: RemoteTrack, output: HTMLMediaElement): void {
  if (!track.sid) return;
  const epoch = generation;
  if (!meter && !meterCreating && retainedMeters.size === 0) {
    meterCreating = true;
    meterTrackId = track.sid;
    const preparation = NativePlaybackMeter.create(track.mediaStreamTrack, (sample) => {
      if (epoch !== generation || !responses.sample(sample)) return;
      render();
      if (
        sample.observedAudioMs > 0 &&
        !attemptedAutoStart.has(sample.responseId) &&
        actual.size < 4 &&
        playbackReports.checked
      ) {
        attemptedAutoStart.add(sample.responseId);
        void reportPlayback(sample.responseId, 'started');
      }
    })
      .then(async (created) => {
        retainedMeters.add(created);
        if (
          epoch !== generation ||
          lifetime.signal.aborted ||
          !track.sid ||
          !audio.has(track.sid)
        ) {
          await created.close();
          retainedMeters.delete(created);
          return;
        }
        meter = created;
        if (activeResponse) created.response(activeResponse);
        created.playing(!output.paused && output.readyState >= 2);
        await created.resume();
      })
      .finally(() => {
        meterCreating = false;
      });
    void trackActual(preparation).catch((error: unknown) => {
      if (error instanceof PlaybackMeterError && error.owner) {
        retainedMeters.add(error.owner);
        cleanupIncomplete = true;
      }
      if (epoch === generation)
        notice('Audio playback observation is unavailable. Completion remains unconfirmed.');
    });
  }
}

async function join(): Promise<void> {
  if (joining || room || closing || cleanupIncomplete || actual.size > 0) return;
  const token = access.value;
  access.value = '';
  if (!/^[A-Za-z0-9_-]{32,256}$/.test(token)) {
    notice('Enter the generated local demo access token.');
    return;
  }
  joining = true;
  playbackObserved = false;
  outputs.length = 0;
  generations = new NativeGenerations();
  responses = new NativeResponses();
  responseElements.clear();
  responseReads.clear();
  element('native-responses').replaceChildren();
  reportEvents.clear();
  reporting.clear();
  activeResponse = null;
  communicationEnabled = false;
  attemptedAutoStart.clear();
  generation++;
  const epoch = generation;
  lifetime = new AbortController();
  rehydrationRequired = false;
  contextBoundId = null;
  contextAutoAttempted = null;
  currentContext.end();
  connection = 'Joining';
  render();
  try {
    const minted = await deadline(trackActual(mint(token)), 5000);
    if (epoch !== generation || lifetime.signal.aborted) return;
    bound = minted;
    browserAccess = token;
    const owned = new Room({ adaptiveStream: false, dynacast: false });
    room = owned;
    owned.on(RoomEvent.ParticipantConnected, observeReady);
    owned.on(RoomEvent.ParticipantDisconnected, observeReady);
    owned.on(RoomEvent.ParticipantAttributesChanged, observeReady);
    owned.on(RoomEvent.Reconnecting, () => {
      if (epoch === generation) {
        connection = 'Reconnecting';
        observeReady();
      }
    });
    owned.on(RoomEvent.Reconnected, () => {
      if (epoch === generation) {
        connection = 'Connected';
        observeReady();
      }
    });
    owned.on(RoomEvent.Disconnected, () => {
      if (epoch === generation) {
        ready = false;
        connection = 'Disconnected';
        void end();
      }
    });
    owned.on(RoomEvent.TrackSubscribed, (track, _publication, participant) => {
      if (epoch === generation) attachOutput(track, participant);
    });
    owned.on(RoomEvent.TrackUnsubscribed, (track) => {
      if (!track.sid) return;
      const entry = audio.get(track.sid);
      if (entry) {
        entry.track.detach(entry.element);
        if (track.sid === meterTrackId && meter) {
          const ownedMeter = meter;
          meter = null;
          meterTrackId = null;
          void trackActual(
            ownedMeter.close().then(() => {
              retainedMeters.delete(ownedMeter);
            }),
          ).catch(() => {
            cleanupIncomplete = true;
            render();
          });
        }
        entry.element.remove();
        audio.delete(track.sid);
      }
    });
    owned.on(RoomEvent.DataReceived, (payload, participant, kind, topic) => {
      if (
        epoch !== generation ||
        !['p2.acceptance', 'p2.generation', 'p2.response'].includes(topic ?? '') ||
        kind !== DataPacket_Kind.RELIABLE ||
        !selected(participant) ||
        bound === null
      )
        return;
      if (topic === 'p2.response') {
        try {
          const mapping = parseResponseMapping(payload, bound.bindingId);
          const isNew = !responses
            .values()
            .some((row) => row.mapping.responseId === mapping.responseId);
          if (responses.apply(mapping, inputs)) {
            communicationEnabled = true;
            if (isNew) {
              activeResponse = mapping.responseId;
              meter?.response(mapping.responseId);
              for (const entry of audio.values()) {
                startMeter(entry.track, entry.element);
                break;
              }
            }
            void refreshResponse(mapping.responseId);
          }
        } catch {
          notice('A response observation could not be verified.');
        }
        render();
        return;
      }
      if (topic === 'p2.generation') {
        try {
          const observation = parseNativeGeneration(payload, bound.bindingId);
          generations.apply(observation, inputs);
          counts.generation_events++;
        } catch {
          counts.invalid_generation++;
        }
        render();
        return;
      }
      try {
        const ack = parseNativeAck(payload, bound.bindingId);
        if (inputs.apply(ack)) {
          if (
            (ack.status === 'accepted' || ack.status === 'replayed') &&
            ack.channel === 'web_chat' &&
            textId.value === ack.inputId
          ) {
            textId.value = crypto.randomUUID();
            message.value = '';
          }
          if (
            (ack.status === 'accepted' || ack.status === 'replayed') &&
            ack.channel === 'voice_transcript' &&
            voiceId.value === ack.inputId
          )
            voiceId.value = crypto.randomUUID();
          counts[ack.status]++;
          const timer = ackTimers.get(ack.inputId);
          if (timer !== undefined) clearTimeout(timer);
          ackTimers.delete(ack.inputId);
        }
      } catch {
        counts.invalid_ack++;
      }
      render();
    });
    owned.registerTextStreamHandler('lk.transcription', (reader, source) => {
      if (
        epoch !== generation ||
        !selected(owned.remoteParticipants.get(source.identity)) ||
        readers >= 2
      ) {
        counts.stream_rejected++;
        void reader[Symbol.asyncIterator]()
          .return()
          .catch(() => undefined);
        return;
      }
      readers++;
      counts.incoming_streams++;
      const work = readNativeVoiceText(reader, lifetime.signal, (bytes) => {
        counts.stream_bytes += bytes;
      });
      trackActual(work)
        .then(
          (text) => {
            if (epoch === generation && selected(owned.remoteParticipants.get(source.identity))) {
              if (outputs.length >= 32) outputs.shift();
              outputs.push(text);
              counts.completed_streams++;
            }
          },
          () => {
            counts.stream_rejected++;
          },
        )
        .finally(() => {
          readers--;
          render();
        });
    });
    await deadline(
      trackActual(
        owned.connect(bound.url, bound.token, {
          rtcConfig: { iceServers: [] },
          websocketTimeout: 10000,
          peerConnectionTimeout: 10000,
        }),
      ),
      12000,
    );
    if (epoch !== generation) {
      await owned.disconnect(true);
      return;
    }
    connection = 'Connected';
    for (const participant of owned.remoteParticipants.values())
      if (selected(participant))
        for (const publication of participant.audioTrackPublications.values())
          if (publication.track) attachOutput(publication.track, participant);
    notice('Connected. Inputs become available when the native agent is ready.');
    observeReady();
    sessionTimer = setTimeout(() => {
      notice('The local session ended. Accepted work remains durable.');
      void end();
    }, 180000);
  } catch {
    if (epoch === generation) {
      notice(
        'The native session could not be joined. Inspect local readiness and retry after cleanup.',
      );
      await end();
    }
  } finally {
    joining = false;
    render();
  }
}
async function send(retry: boolean): Promise<void> {
  if (!ready || !room || actual.size >= 4) return;
  const epoch = generation;
  let input;
  try {
    input = retry
      ? lastText()
      : inputs.add(freezeNativeInput(textId.value, 'web_chat', message.value));
    if (!input || input.channel !== 'web_chat' || input.body === null) return;
    if (retry && input.receiptId === null) inputs.uncertain(input.inputId);
    awaitingAck(input.inputId);
    render();
    await deadline(
      trackActual(
        room.localParticipant.sendText(input.body, {
          topic: 'lk.chat',
          attributes: { [NATIVE_INPUT_ATTRIBUTE]: input.inputId },
        }),
      ),
    );
    counts.sent++;
    if (epoch === generation)
      notice('Text transport completed. The durable receipt is reported separately.');
  } catch (error) {
    if (input) inputs.uncertain(input.inputId);
    if (epoch === generation)
      notice(
        error instanceof NativeUiError && error.code === 'invalid'
          ? error.message
          : 'Input acknowledgement is unknown. Retry the original text unchanged.',
      );
  } finally {
    render();
  }
}
async function publishFixture(): Promise<void> {
  if (!ready || fixture || fixtureBusy || !room) return;
  fixtureBusy = true;
  const epoch = generation;
  const ownedRoom = room;
  let abandoned = false;
  const preparation = createScriptedInput({ signal: lifetime.signal }).then(async (source) => {
    if (abandoned || epoch !== generation || lifetime.signal.aborted) {
      source.track.stop();
      await source.close();
      throw new NativeUiError('unknown', 'The abandoned fixture was closed.');
    }
    fixture = source;
    return source;
  });
  try {
    const source = await deadline(trackActual(preparation), 5000);
    if (epoch !== generation || !ready) {
      source.track.stop();
      await source.close();
      if (fixture === source) fixture = null;
      return;
    }
    await deadline(
      trackActual(
        ownedRoom.localParticipant.publishTrack(source.track, { source: Track.Source.Microphone }),
      ),
    );
    if (epoch !== generation) {
      source.track.stop();
      await source.close();
      if (fixture === source) fixture = null;
      return;
    }
    notice('Voice fixture enabled. Start a turn to play the local recording.');
  } catch {
    abandoned = true;
    notice('The voice fixture could not be published. End the session to settle owned media.');
  } finally {
    fixtureBusy = false;
    render();
  }
}
async function turn(method: TurnMethod): Promise<void> {
  if (!ready || !room || !bound || turnBusy || actual.size >= 4) return;
  const epoch = generation;
  const source = fixture;
  let inputId = currentTurn;
  try {
    if (method === 'p2.start_turn') {
      if (!source || turnStarted) return;
      inputId = inputs.add(freezeNativeInput(voiceId.value, 'voice_transcript', null)).inputId;
      currentTurn = inputId;
    }
    if (method !== 'p2.interrupt' && inputId === null) return;
    turnBusy = true;
    render();
    const reply = await deadline(
      trackActual(
        room.localParticipant.performRpc({
          destinationIdentity: bound.agentId,
          method,
          payload: turnPayload(method, method === 'p2.interrupt' ? null : inputId),
          responseTimeout: 8000,
        }),
      ),
    );
    const outcome = parseNativeTurnReply(reply, method, method === 'p2.interrupt' ? null : inputId);
    if (epoch !== generation || !ready) return;
    if (method === 'p2.start_turn') {
      if (fixture !== source || !source) return;
      source.replay();
      turnStarted = true;
      element('native-turn').textContent = 'Capturing committed voice input';
    } else if (method === 'p2.commit_turn') {
      turnStarted = false;
      element('native-turn').textContent =
        outcome === 'no_audio'
          ? 'No committed audio observed'
          : 'Voice turn committed · awaiting durable receipt';
      if (inputId && !inputs.values().find((row) => row.inputId === inputId)?.receiptId)
        awaitingAck(inputId);
    } else element('native-turn').textContent = 'Reply interrupted · accepted input unchanged';
  } catch {
    if (inputId && method !== 'p2.interrupt') inputs.uncertain(inputId);
    if (epoch === generation)
      notice('Turn acknowledgement is unknown. Preserve its original reference.');
  } finally {
    turnBusy = false;
    render();
  }
}
async function end(): Promise<void> {
  if (closing) return closing;
  generation++;
  ready = false;
  connection = 'Closing';
  currentContext.end();
  lifetime.abort();
  smsController?.abort();
  access.value = '';
  browserAccess = '';
  activeResponse = null;
  bound = null;
  if (sessionTimer !== null) clearTimeout(sessionTimer);
  sessionTimer = null;
  for (const timer of ackTimers.values()) clearTimeout(timer);
  ackTimers.clear();
  for (const row of inputs.values()) inputs.uncertain(row.inputId);
  const owned = room;
  const source = fixture;
  meter = null;
  meterTrackId = null;
  source?.track.stop();
  for (const entry of audio.values()) {
    entry.track.detach(entry.element);
    entry.element.remove();
  }
  audio.clear();
  closing = (async () => {
    try {
      owned?.unregisterTextStreamHandler('lk.transcription');
      // Already failed/cancelled calls still count as settled ownership. Only
      // actual disconnect/track closure errors make cleanup incomplete.
      await deadline(
        Promise.all([
          owned?.disconnect(true),
          source?.close(),
          Promise.all(
            [...retainedMeters].map(async (ownedMeter) => {
              await ownedMeter.close();
              retainedMeters.delete(ownedMeter);
            }),
          ),
          (async () => {
            await Promise.allSettled([...actual]);
            await Promise.all(
              [...retainedMeters].map(async (ownedMeter) => {
                await ownedMeter.close();
                retainedMeters.delete(ownedMeter);
              }),
            );
          })(),
        ]),
        5000,
      );
      if (retainedMeters.size || meterCreating || actual.size) throw new PlaybackMeterError();
      cleanupIncomplete = false;
      room = null;
      fixture = null;
      bound = null;
      currentTurn = null;
      turnStarted = false;
      connection = 'Disconnected';
    } catch {
      cleanupIncomplete = true;
      connection = 'Cleanup incomplete';
      notice('Media cleanup is incomplete. Reload before joining another session.');
    } finally {
      owned?.removeAllListeners();
      closing = null;
      render();
    }
  })();
  render();
  return closing;
}
contextRefresh.addEventListener('click', () => void refreshContext());
contextForget.addEventListener('click', () => {
  if (!room && !joining && !closing && actual.size === 0) {
    currentContext.forget();
    smsKnown = false;
    rehydrationRequired = false;
    render();
  }
});
smsButton.addEventListener('click', () => void deliverDemoSms());
playbackReports.addEventListener('change', render);
controls.join!.addEventListener('click', () => {
  void join();
});
controls.end!.addEventListener('click', () => {
  void end();
});
controls.send!.addEventListener('click', () => {
  void send(false);
});
controls.retry!.addEventListener('click', () => {
  void send(true);
});
controls.publish!.addEventListener('click', () => {
  void publishFixture();
});
controls.start!.addEventListener('click', () => {
  void turn('p2.start_turn');
});
controls.commit!.addEventListener('click', () => {
  void turn('p2.commit_turn');
});
controls.interrupt!.addEventListener('click', () => {
  if (activeResponse) void interruptResponse(activeResponse);
  else void turn('p2.interrupt');
});
controls['enable-audio']!.addEventListener('click', () => {
  if (room)
    void deadline(trackActual(Promise.all([room.startAudio(), meter?.resume()]))).catch(() => {
      notice('Output playback is blocked. Check browser audio permission.');
    });
});
window.addEventListener('pagehide', () => {
  access.value = '';
  currentContext.forget();
  void end();
});
render();
