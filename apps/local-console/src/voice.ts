/** Native LiveKit conversation lifecycle. Media observations never grant business consent. */
import { createLocalAudioTrack, DataPacket_Kind, LocalAudioTrack, ParticipantKind, Room, RoomEvent, Track } from 'livekit-client';
import type { RemoteParticipant, RemoteTrack } from 'livekit-client';
import { boundedResponse, MAX_TEXT_BYTES, readBoundedText, validateMessage } from './lab';
import { validateOperatorToken } from './intake';
import { parseBusinessJson } from './business';
import { createScriptedInput } from './scripted-input';

const encoder = new TextEncoder();
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ROOM = /^business-[a-z0-9][a-z0-9-]{0,47}$/;
const IDENTITY = /^browser-[a-z0-9][a-z0-9-]{0,47}$/;
const PAYLOAD = '{"schema_version":1}';
export type VoiceInputSource = 'scripted' | 'microphone';
export type VoiceInferenceMode = 'scripted' | 'local_real' | 'provider_real';
export function voiceInferenceLabel(mode: VoiceInferenceMode | null): string { return mode === null ? 'VOICE · JOIN TO VERIFY PROFILE' : mode === 'provider_real' ? 'Cloud providers (Deepgram/OpenAI/ElevenLabs)' : mode === 'local_real' ? 'LOCAL REAL ASR / LLM / TTS' : 'SCRIPTED SPEECH · NO INFERENCE'; }
export type VoiceConnection = 'disconnected' | 'connecting' | 'connected' | 'reconnecting' | 'disconnecting' | 'error';
export type SpeechState = 'initializing' | 'idle' | 'listening' | 'thinking' | 'speaking' | 'unknown';
export type PlaybackState = 'unavailable' | 'ready' | 'playing' | 'paused' | 'blocked';
export type TurnState = 'idle' | 'starting' | 'capturing' | 'committing' | 'committed' | 'interrupting' | 'interrupted' | 'unknown';
export type VoiceMethod = 'business.start_turn' | 'business.commit_turn' | 'business.interrupt';
export interface VoiceSessionRequest { readonly room: string; readonly identity: string; readonly task_id: string; readonly invocation_id: string }
export interface VoiceSessionResponse { readonly url: string; readonly token: string; readonly room: string; readonly identity: string; readonly expires_in: number; readonly agent_name: 'local-business-agent'; readonly agent_dispatched: boolean; readonly mode: VoiceInferenceMode }
export interface VoiceTextDiagnostics {
  readonly sender_rejected_closed: number; readonly sender_rejected_missing: number; readonly sender_rejected_non_agent: number; readonly sender_rejected_no_selection: number; readonly sender_rejected_identity_mismatch: number; readonly sender_rejected_local: number;
  readonly streams_received: number; readonly chunks_received: number; readonly received_bytes: number; readonly sender_rejected: number; readonly capacity_rejected: number;
  readonly read_completed: number; readonly read_failed: number; readonly completed_bytes: number;
  readonly after_read_rejected: number; readonly callback_accepted: number; readonly callback_rejected: number; readonly callback_stale: number;
}
export type VoiceTextCounter = keyof VoiceTextDiagnostics;
const EMPTY_TEXT_DIAGNOSTICS: VoiceTextDiagnostics = Object.freeze({ sender_rejected_closed: 0, sender_rejected_missing: 0, sender_rejected_non_agent: 0, sender_rejected_no_selection: 0, sender_rejected_identity_mismatch: 0, sender_rejected_local: 0, streams_received: 0, chunks_received: 0, received_bytes: 0, sender_rejected: 0, capacity_rejected: 0, read_completed: 0, read_failed: 0, completed_bytes: 0, after_read_rejected: 0, callback_accepted: 0, callback_rejected: 0, callback_stale: 0 });
export interface VoiceRoomCallbacks {
  agent(identity: string | null): void;
  speech(state: SpeechState): void;
  sessionReady(ready: boolean, observedMode?: VoiceInferenceMode | null): void;
  playback(state: PlaybackState): void;
  text(value: string): void;
  taskHint(taskId: string): void;
  disconnected(): void;
  reconnecting(): void;
  reconnected(): void;
  mediaError(): void;
  diagnostic(counter: VoiceTextCounter, increment?: number): void;
}
export interface VoiceRoomPort {
  connect(url: string, token: string): Promise<void>;
  disconnect(): Promise<void>;
  whenClosed?(): Promise<void>;
  setMicrophoneEnabled(enabled: boolean): Promise<void>;
  performRpc(destination: string, method: VoiceMethod, payload: string): Promise<string>;
  sendText(text: string): Promise<void>;
  startAudio(): Promise<void>;
}
export interface VoiceState {
  readonly connection: VoiceConnection; readonly inference_mode: VoiceInferenceMode | null; readonly session_ready: boolean; readonly input_source: VoiceInputSource | null; readonly task_id: string | null; readonly room: string | null; readonly agent_id: string | null;
  readonly microphone: boolean; readonly microphone_uncertain: boolean; readonly microphone_busy: boolean; readonly rpc_busy: boolean; readonly interrupt_busy: boolean; readonly status_busy: boolean; readonly playback_busy: boolean;
  readonly speech: SpeechState; readonly playback: PlaybackState; readonly turn: TurnState; readonly message: string;
  readonly entries: readonly string[]; readonly text_diagnostics: VoiceTextDiagnostics;
}
export function nativeSessionReady(state: Pick<VoiceState, 'connection' | 'agent_id' | 'speech' | 'session_ready' | 'inference_mode'>): boolean { return state.connection === 'connected' && isVoiceInferenceMode(state.inference_mode) && state.agent_id !== null && state.session_ready === true && ['idle', 'listening', 'thinking', 'speaking'].includes(state.speech); }
export class VoiceError extends Error { constructor(readonly code: 'invalid' | 'unauthorized' | 'unavailable' | 'unknown' | 'permission', message: string) { super(message); } }
function reject(): never { throw new VoiceError('unknown', 'The conversation acknowledgement could not be verified.'); }
function record(value: unknown, fields: readonly string[]): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) return reject(); const item = value as Record<string, unknown>; if (Object.keys(item).length !== fields.length || fields.some((field) => !(field in item))) return reject(); return item; }
function validTask(value: string): void { if (!UUID.test(value)) throw new VoiceError('invalid', 'Load a verified durable task before joining the conversation.'); }
function isVoiceInferenceMode(value: unknown): value is VoiceInferenceMode { return value === 'scripted' || value === 'local_real' || value === 'provider_real'; }
export function parseVoiceSession(value: unknown, expected: VoiceSessionRequest): VoiceSessionResponse {
  const item = record(value, ['url', 'token', 'room', 'identity', 'expires_in', 'agent_name', 'agent_dispatched', 'mode']);
  if (typeof item.url !== 'string' || typeof item.token !== 'string' || !item.token || encoder.encode(item.token).length > 8192 || item.room !== expected.room || item.identity !== expected.identity || item.agent_name !== 'local-business-agent' || !isVoiceInferenceMode(item.mode) || typeof item.agent_dispatched !== 'boolean' || typeof item.expires_in !== 'number' || !Number.isInteger(item.expires_in) || item.expires_in < 1 || item.expires_in > 300) return reject();
  const url = new URL(item.url); if (!['ws:', 'wss:'].includes(url.protocol) || !url.hostname || url.username || url.password || url.search || url.hash) return reject();
  return Object.freeze(item) as unknown as VoiceSessionResponse;
}
function waitForSessionRetry(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = (): void => { clearTimeout(timer); signal.removeEventListener('abort', abort); reject(new DOMException('The session request was aborted.', 'AbortError')); };
    const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve(); }, 100);
    signal.addEventListener('abort', abort, { once: true }); if (signal.aborted) abort();
  });
}
export async function requestVoiceSession(request: VoiceSessionRequest, token: string, signal: AbortSignal, fetcher: typeof fetch = fetch): Promise<VoiceSessionResponse> {
  validTask(request.task_id); validateOperatorToken(token);
  if (!ROOM.test(request.room) || !IDENTITY.test(request.identity) || !UUID.test(request.invocation_id)) throw new VoiceError('invalid', 'Conversation room and participant identities are invalid.');
  const frozen = Object.freeze({ room: request.room, identity: request.identity, task_id: request.task_id, invocation_id: request.invocation_id });
  const body = JSON.stringify(frozen);
  try {
    for (let attempt = 0; attempt < 3; attempt += 1) {
      signal.throwIfAborted();
      let response: Response;
      try {
        response = await fetcher('/api/business/session', { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body, signal, credentials: 'omit', cache: 'no-store' });
      } catch (error) {
        if (signal.aborted || attempt === 2) throw error;
        await waitForSessionRetry(signal); continue;
      }
      if (signal.aborted || !response.ok) await response.body?.cancel().catch(() => undefined);
      signal.throwIfAborted();
      if (response.status === 401 || response.status === 403) throw new VoiceError('unauthorized', 'Operator access was denied. Enter the local token again.');
      if ([503, 504].includes(response.status) && attempt < 2) { await waitForSessionRetry(signal); continue; }
      if (!response.ok) throw new VoiceError('unavailable', 'The local voice agent could not be joined. Inspect stack readiness and the original case.');
      return parseVoiceSession(await boundedResponse(response), frozen);
    }
    throw new VoiceError('unavailable', 'The scoped media invocation could not be acknowledged. Retry its original identity.');
  } catch (error) { if (error instanceof VoiceError) throw error; throw new VoiceError('unavailable', 'The conversation could not be joined. Accepted business work remains independent.'); }
}
export function parseTurnReply(value: string, method: VoiceMethod): 'turn_started' | 'turn_committed' | 'no_audio' | 'speech_interrupted' {
  if (!value || encoder.encode(value).length > 128) return reject();
  const item = record(parseBusinessJson(value), ['schema_version', 'status']);
  const allowed = method === 'business.start_turn' ? ['turn_started'] : method === 'business.commit_turn' ? ['turn_committed', 'no_audio'] : ['speech_interrupted'];
  if (item.schema_version !== 1 || typeof item.status !== 'string' || !allowed.includes(item.status)) return reject();
  return item.status as 'turn_started' | 'turn_committed' | 'no_audio' | 'speech_interrupted';
}
export function parseTaskHint(payload: Uint8Array): string | null {
  if (!payload.byteLength || payload.byteLength > 512) return null;
  try { const item = record(parseBusinessJson(new TextDecoder('utf-8', { fatal: true }).decode(payload)), ['schema_version', 'task_id']); if (item.schema_version !== 1 || typeof item.task_id !== 'string' || !UUID.test(item.task_id)) return null; return item.task_id; } catch { return null; }
}
const INITIAL: VoiceState = Object.freeze({ connection: 'disconnected', inference_mode: null, session_ready: false, input_source: null, task_id: null, room: null, agent_id: null, microphone: false, microphone_uncertain: false, microphone_busy: false, rpc_busy: false, interrupt_busy: false, status_busy: false, playback_busy: false, speech: 'unknown', playback: 'unavailable', turn: 'idle', message: 'Load a durable case, then explicitly join its local voice session.', entries: Object.freeze([]), text_diagnostics: EMPTY_TEXT_DIAGNOSTICS });
export class VoiceController {
  private value: VoiceState = INITIAL;
  private currentRoom: VoiceRoomPort | null = null;
  private pending: AbortController | null = null;
  private generation = 0;
  private turnGeneration = 0;
  private context: VoiceSessionRequest | null = null;
  private disposed = false;
  private disconnecting: Promise<void> | null = null;
  private hintInFlight = false;
  private cleanupBarrier: Promise<void> | null = null;
  private endedContext = false;
  constructor(private readonly factory: (callbacks: VoiceRoomCallbacks, source: VoiceInputSource, expectedMode: VoiceInferenceMode) => VoiceRoomPort, private readonly changed: (state: VoiceState) => void, private readonly observedTask: (taskId: string) => Promise<void> | void, private readonly fetcher: typeof fetch = fetch, private readonly makeId: () => string = () => crypto.randomUUID(), private readonly makeInvocationId: () => string = () => crypto.randomUUID()) {}
  get state(): VoiceState { return this.value; }
  private publish(next: Partial<VoiceState>): void { this.value = Object.freeze({ ...this.value, ...next, entries: next.entries ? Object.freeze([...next.entries]) : this.value.entries }); try { this.changed(this.value); } catch { /* Presentation cannot own the RTC lifecycle. */ } }
  private diagnostic(counter: VoiceTextCounter, increment = 1): void {
    if (this.disposed || !Object.hasOwn(this.value.text_diagnostics, counter) || !Number.isSafeInteger(increment) || increment < 0 || increment > MAX_TEXT_BYTES) return;
    const value = Math.min(1_000_000_000, this.value.text_diagnostics[counter] + increment);
    this.publish({ text_diagnostics: Object.freeze({ ...this.value.text_diagnostics, [counter]: value }) });
  }
  private retainCleanup(room: VoiceRoomPort, closing: Promise<void>): void {
    const barrier = room.whenClosed?.() ?? closing; this.cleanupBarrier = barrier;
    void barrier.then(() => {
      if (this.cleanupBarrier !== barrier) return; this.cleanupBarrier = null;
      if (!this.disposed && ['disconnected', 'error'].includes(this.value.connection) && this.value.microphone_uncertain) this.publish({ microphone_uncertain: false, message: 'Prior media cleanup completed. You may explicitly rejoin the scoped task.' });
    }, () => { /* A failed real cleanup requires page reload; retain the barrier. */ });
  }
  private active(generation: number): boolean { return !this.disposed && generation === this.generation; }
  private entry(value: string): void { if (!value || encoder.encode(value).length > MAX_TEXT_BYTES) { this.diagnostic('callback_rejected'); return; } this.diagnostic('callback_accepted'); this.publish({ entries: [...this.value.entries, value].slice(-40) }); }
  private ready(): boolean { return nativeSessionReady(this.value) && this.currentRoom !== null; }
  async connect(taskId: string, token: string, source: VoiceInputSource = 'scripted'): Promise<void> {
    if (this.disposed || ['connecting', 'disconnecting'].includes(this.value.connection)) return;
    if (this.cleanupBarrier || this.value.microphone_uncertain) { this.publish({ message: 'Prior media cleanup is unresolved. Wait for its actual completion or reload this page and explicitly resume the task.' }); return; }
    try { validTask(taskId); validateOperatorToken(token); if (!['scripted', 'microphone'].includes(source)) throw new VoiceError('invalid', 'Choose a supported audio input source.'); } catch { this.publish({ message: 'Load a verified case and enter the local operator token before joining.' }); return; }
    if (this.value.connection === 'connected' && this.context?.task_id === taskId && this.value.input_source === source) return;
    if (this.currentRoom || this.pending) await this.disconnect();
    if (this.disposed) return;
    if (this.cleanupBarrier || this.value.microphone_uncertain) { this.publish({ message: 'Prior media cleanup is unresolved. Reload this page and explicitly resume the task.' }); return; }
    if (!this.context || this.context.task_id !== taskId || this.endedContext) { const id = this.makeId(); this.context = Object.freeze({ room: `business-${id}`, identity: `browser-${id}`, task_id: taskId, invocation_id: this.makeInvocationId() }); this.endedContext = false; }
    const generation = ++this.generation, request = this.context; this.hintInFlight = false;
    const pending = new AbortController(); this.pending = pending;
    this.publish({ connection: 'connecting', inference_mode: null, session_ready: false, entries: [], input_source: source, task_id: taskId, room: request.room, agent_id: null, speech: 'unknown', turn: 'idle', playback: 'unavailable', message: 'Joining the scoped native AgentSession…' });
    let room: VoiceRoomPort | null = null;
    try {
      const session = await requestVoiceSession(request, token, AbortSignal.any([pending.signal, AbortSignal.timeout(15_000)]), this.fetcher);
      if (!this.active(generation)) return;
      this.publish({ inference_mode: session.mode });
      room = this.factory({
        agent: (identity) => { if (!this.active(generation)) return; const changed = identity !== this.value.agent_id; if (changed) this.turnGeneration += 1; this.publish({ agent_id: identity, turn: ['starting', 'capturing', 'committing', 'interrupting'].includes(this.value.turn) ? 'unknown' : this.value.turn, speech: changed || !identity ? 'unknown' : this.value.speech, session_ready: changed || !identity ? false : this.value.session_ready, message: identity ? 'The native agent is present. Waiting for its verified profile and media readiness.' : 'The agent is absent. You can still stop an already-published audio input.' }); },
        speech: (state) => { if (this.active(generation)) { const wasReady = this.ready(); this.publish({ speech: state }); if (!wasReady && this.ready()) this.publish({ message: 'The verified native session is ready. Publish the selected input explicitly to begin.' }); } },
        sessionReady: (ready, observedMode = 'scripted') => {
          if (!this.active(generation)) return;
          const matches = isVoiceInferenceMode(observedMode) && observedMode === this.value.inference_mode;
          const wasReady = this.ready(); this.publish({ session_ready: this.value.agent_id !== null && ready === true && matches });
          if (observedMode !== null && !matches) { this.publish({ message: 'The native agent profile does not match the authenticated session. Wait or end voice; business work remains independent.' }); return; }
          if (!wasReady && this.ready()) this.publish({ message: 'The native media I/O is ready. Publish the selected input explicitly to begin.' });
          else if (wasReady && !this.ready()) this.publish({ message: 'The native media subscription is not ready. Stop active input or end voice while it recovers.' });
        },
        playback: (state) => { if (this.active(generation)) this.publish({ playback: state }); },
        text: (value) => { if (this.active(generation)) this.entry(value); else this.diagnostic('callback_stale'); },
        diagnostic: (counter, increment) => this.diagnostic(counter, increment),
        taskHint: (id) => {
          if (!this.active(generation) || id !== request.task_id || this.hintInFlight) return;
          this.hintInFlight = true;
          void Promise.resolve().then(() => { if (this.active(generation)) return this.observedTask(id); }).catch(() => { if (this.active(generation)) this.publish({ message: 'The task hint arrived; its scoped case could not yet be refreshed.' }); }).finally(() => { if (this.active(generation)) this.hintInFlight = false; });
        },
        disconnected: () => {
          if (!this.active(generation)) return;
          const previous = this.currentRoom; if (this.context && ['connected', 'reconnecting'].includes(this.value.connection)) this.endedContext = true; this.currentRoom = null; this.pending?.abort(); this.pending = null; this.generation += 1; this.turnGeneration += 1;
          if (previous) { try { const closing = previous.disconnect(); this.retainCleanup(previous, closing); void closing.catch(() => undefined); } catch { /* Keep the disconnected input uncertain until page reload. */ } }
          this.publish({ connection: 'disconnected', inference_mode: null, session_ready: false, agent_id: null, microphone: false, microphone_uncertain: previous !== null, microphone_busy: false, rpc_busy: false, interrupt_busy: false, status_busy: false, playback_busy: false, speech: 'unknown', playback: 'unavailable', turn: 'idle', message: 'Voice disconnected. Media cleanup must complete before another source; accepted business work continues independently.' });
        },
        reconnecting: () => { if (this.active(generation)) this.publish({ connection: 'reconnecting', message: 'Media is reconnecting. The durable case remains in PostgreSQL.' }); },
        reconnected: () => { if (this.active(generation)) this.publish({ connection: 'connected' }); },
        mediaError: () => { if (this.active(generation)) this.publish({ message: 'Microphone permission or capture is unavailable. Use scoped text/business controls; no cancellation was sent.' }); },
      }, source, session.mode);
      this.currentRoom = room;
      await room.connect(session.url, session.token);
      if (!this.active(generation)) { await room.disconnect().catch(() => undefined); return; }
      this.pending = null; this.publish({ connection: 'connected', message: nativeSessionReady({ ...this.value, connection: 'connected' }) ? 'Local voice session connected. Publish the selected input explicitly to begin.' : 'Room connected. Waiting for the verified native profile and media subscription.' });
    } catch (error) {
      let cleanupUncertain = false, retained = false;
      if (room) {
        try { const closing = room.disconnect(); this.retainCleanup(room, closing); retained = true; await voiceDeadline(closing); }
        catch { cleanupUncertain = !retained || this.cleanupBarrier !== null; }
      }
      if (!this.active(generation)) return;
      this.currentRoom = null; this.pending = null;
      this.publish({ connection: 'error', inference_mode: null, session_ready: false, agent_id: null, microphone: false, microphone_uncertain: cleanupUncertain || this.cleanupBarrier !== null, message: cleanupUncertain ? 'Connection failed and media cleanup is unconfirmed. Wait for actual completion or reload this page and explicitly resume the task.' : error instanceof VoiceError ? error.message : 'The conversation could not connect. Business work remains independent.' });
    }
  }
  async microphone(enabled: boolean): Promise<void> {
    if (this.disposed || this.value.microphone_busy || !this.currentRoom || (enabled && !this.ready()) || (enabled && this.value.microphone) || (!enabled && !this.value.microphone && !this.value.microphone_uncertain)) return;
    const generation = this.generation, room = this.currentRoom;
    this.publish({ microphone_busy: true });
    const operation = (async () => {
      try {
        await room.setMicrophoneEnabled(enabled);
        if (!this.active(generation) || this.currentRoom !== room) { if (enabled) await room.setMicrophoneEnabled(false).catch(() => undefined); return; }
        this.publish({ microphone: enabled, microphone_uncertain: false, message: enabled ? this.value.input_source === 'scripted' ? 'Prerecorded local WAV input publishing. Start and commit a turn explicitly.' : 'Microphone publishing. Start and commit a turn explicitly.' : 'Audio input stopped. Accepted business work is unchanged.' });
      }
      catch {
        let muted = false;
        if (enabled) { try { await room.setMicrophoneEnabled(false); muted = true; } catch { /* Keep capture uncertainty visible until mute/end is acknowledged. */ } }
        if (this.active(generation)) this.publish({ microphone: muted ? false : this.value.microphone, microphone_uncertain: !muted, message: enabled ? this.value.input_source === 'scripted' ? 'Prerecorded input capture or publication was not acknowledged. End voice to stop the owned local source; no business cancellation was sent.' : 'Microphone permission or capture was not acknowledged. End voice to stop local tracks; no business cancellation was sent.' : 'The microphone could not be muted. End the voice session to stop its local tracks.' });
      }
      finally { if (this.active(generation)) this.publish({ microphone_busy: false }); }
    })();
    await operation;
  }
  async turn(kind: 'start' | 'commit'): Promise<void> {
    if (this.disposed || !this.ready() || this.value.rpc_busy || this.value.interrupt_busy || (kind === 'start' && (!this.value.microphone || this.value.microphone_uncertain || this.value.turn === 'capturing')) || (kind === 'commit' && this.value.turn !== 'capturing')) return;
    const generation = this.generation, turnGeneration = ++this.turnGeneration, room = this.currentRoom!, agent = this.value.agent_id!;
    this.publish({ rpc_busy: true, turn: kind === 'start' ? 'starting' : 'committing', message: kind === 'start' ? 'Starting a manual input turn…' : 'Committing the captured input turn…' });
    try {
      const reply = parseTurnReply(await room.performRpc(agent, kind === 'start' ? 'business.start_turn' : 'business.commit_turn', PAYLOAD), kind === 'start' ? 'business.start_turn' : 'business.commit_turn');
      if (!this.active(generation) || this.turnGeneration !== turnGeneration) return;
      this.publish({ turn: reply === 'turn_started' ? 'capturing' : reply === 'no_audio' ? 'idle' : 'committed', message: reply === 'turn_started' ? 'Capturing a turn. Commit when the audio input is complete.' : reply === 'no_audio' ? 'No audio was captured. Start another turn when ready.' : 'Input turn committed. Any durable acceptance is verified separately through the case projection.' });
    } catch { if (this.active(generation) && this.turnGeneration === turnGeneration) this.publish({ turn: 'unknown', message: 'The turn acknowledgement is unknown. Inspect the durable case; interruption can stop speech without cancelling work.' }); }
    finally { if (this.active(generation)) this.publish({ rpc_busy: false }); }
  }
  async interrupt(): Promise<void> {
    if (this.disposed || !this.ready() || this.value.interrupt_busy) return;
    const generation = this.generation, turnGeneration = this.turnGeneration, room = this.currentRoom!, agent = this.value.agent_id!;
    // Native interruption affects speech only. It neither aborts capture nor invalidates
    // a pending start/commit acknowledgement, so keep that independent input state.
    const preserveInput = this.value.rpc_busy || ['starting', 'capturing', 'committing', 'unknown'].includes(this.value.turn);
    this.publish({ interrupt_busy: true, ...(preserveInput ? {} : { turn: 'interrupting' }), message: 'Requesting native speech interruption. Audio input and business cancellation remain separate controls.' });
    try {
      parseTurnReply(await room.performRpc(agent, 'business.interrupt', PAYLOAD), 'business.interrupt');
      if (this.active(generation) && this.turnGeneration === turnGeneration) this.publish({ ...(preserveInput ? {} : { turn: 'interrupted' }), message: preserveInput ? 'Speech interruption acknowledged. The captured or pending input turn is unchanged; commit active capture when ready.' : 'Speech interruption acknowledged. Accepted business work was not cancelled.' });
    } catch {
      if (this.active(generation) && this.turnGeneration === turnGeneration) this.publish({ ...(preserveInput ? {} : { turn: 'unknown' }), message: 'Speech interruption acknowledgement is unknown. The input turn is unchanged and the durable case remains authoritative.' });
    } finally { if (this.active(generation)) this.publish({ interrupt_busy: false }); }
  }
  async status(): Promise<void> {
    if (!this.ready() || this.disposed || this.value.status_busy) return;
    const generation = this.generation; this.publish({ status_busy: true });
    try { await this.currentRoom!.sendText('status'); if (this.active(generation)) this.publish({ message: 'Status requested through the native text input. Only scoped GET observations update the business panel.' }); }
    catch { if (this.active(generation)) this.publish({ message: 'Native status request was not acknowledged. Refresh the scoped case directly.' }); }
    finally { if (this.active(generation)) this.publish({ status_busy: false }); }
  }
  async enablePlayback(): Promise<void> {
    if (!this.currentRoom || this.disposed || this.value.playback_busy) return;
    const generation = this.generation; this.publish({ playback_busy: true });
    try { await this.currentRoom.startAudio(); }
    catch { if (this.active(generation)) this.publish({ playback: 'blocked', message: 'Browser playback is blocked. Use the explicit audio control or inspect browser permissions.' }); }
    finally { if (this.active(generation)) this.publish({ playback_busy: false }); }
  }
  async disconnect(): Promise<void> {
    if (this.disconnecting) return this.disconnecting;
    if (this.disposed && !this.currentRoom && !this.pending) return;
    this.generation += 1; this.turnGeneration += 1; if (this.context) this.endedContext = true; this.hintInFlight = false; this.pending?.abort(); this.pending = null;
    const room = this.currentRoom; this.currentRoom = null;
    this.publish({ connection: 'disconnecting', inference_mode: null, session_ready: false, agent_id: null, rpc_busy: false, interrupt_busy: false, status_busy: false, playback_busy: false, message: 'Ending voice and stopping local tracks. No business cancellation is sent.' });
    const operation = (async () => {
      let cleaned = true;
      try {
        if (room) {
          const closing = room.disconnect();
          this.retainCleanup(room, closing);
          await voiceDeadline(closing);
        }
      }
      catch { cleaned = false; this.publish({ message: 'Voice cleanup could not be confirmed. Reload this page and explicitly resume the task before publishing another source; business work remains independent.' }); }
      finally { const uncertain = !cleaned || this.cleanupBarrier !== null; this.publish({ connection: 'disconnected', inference_mode: null, session_ready: false, microphone: false, microphone_uncertain: uncertain, microphone_busy: false, speech: 'unknown', playback: 'unavailable', turn: 'idle', ...(cleaned ? { message: uncertain ? 'Prior media cleanup remains unresolved. Wait for actual completion or reload this page and explicitly resume the task.' : 'Voice disconnected. Local media cleanup completed. Accepted business work continues independently.' } : {}) }); }
    })();
    this.disconnecting = operation;
    try { await operation; } finally { if (this.disconnecting === operation) this.disconnecting = null; }
  }
  forget(): void { void this.disconnect(); }
  async dispose(): Promise<void> { if (this.disposed) return; this.disposed = true; await this.disconnect(); }

}

/** Bound acknowledgements without releasing ownership of a still-pending SDK operation. */
async function voiceDeadline(work: Promise<void>, expired: () => void = () => undefined): Promise<void> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_resolve, reject) => { timer = setTimeout(() => { expired(); reject(new VoiceError('unknown', 'The native media acknowledgement is unknown. End voice to release local resources.')); }, 5000); });
  try { await Promise.race([work, timeout]); } finally { if (timer !== undefined) clearTimeout(timer); }
}

/** Honor actual browser denial before capture; unsupported permission queries remain unknown. */
export async function assertNativeMicrophonePermission(permissions: Pick<Permissions, 'query'> | undefined): Promise<void> {
  if (!permissions) return;
  let result: PermissionStatus;
  try { result = await permissions.query({ name: 'microphone' as PermissionName }); }
  catch { return; }
  if (result.state === 'denied') throw new VoiceError('permission', 'The browser denied microphone capture.');
}

/** One underlying native microphone operation, including late cleanup, per room. */
export class NativeMicrophoneOwner {
  private pending: Promise<void> | null = null;
  private closed = false;
  private drain = false;
  constructor(private readonly invoke: (enabled: boolean) => Promise<void>, private readonly stopOwnedTracks: () => void) {}
  get mustStopTracks(): boolean { return this.closed || this.drain; }
  private stop(): void { try { this.stopOwnedTracks(); } catch { /* Acknowledgement remains unknown; cleanup never grants success. */ } }
  async set(enabled: boolean): Promise<void> {
    if (this.closed && enabled) throw new VoiceError('unknown', 'This voice session has ended.');
    if (this.pending) {
      if (!enabled) { this.drain = true; this.stop(); }
      throw new VoiceError('unknown', 'A prior native microphone operation is still unresolved. End voice before retrying.');
    }
    this.drain = this.closed;
    let native: Promise<void>;
    try { native = this.invoke(enabled); } catch (error) { native = Promise.reject(error); }
    const operation = native.then(async () => {
      if (enabled && this.mustStopTracks) { this.stop(); await this.invoke(false); this.stop(); }
    }).finally(() => { if (this.pending === operation) this.pending = null; });
    this.pending = operation;
    // The real operation retains its reservation after the acknowledgement deadline.
    // Its settlement still owns late capture cleanup, including after page/room end.
    await voiceDeadline(operation, () => { this.drain = true; this.stop(); });
  }
  whenDrained(): Promise<void> { return this.pending ? this.pending.then(() => undefined, () => undefined) : Promise.resolve(); }
  close(): void { this.closed = true; this.drain = true; this.stop(); }
}

/** The producer sets this public attribute only after actual RoomIO subscription readiness. */
export function nativeMediaReadyAttribute(attributes: Readonly<Record<string, string>>, expectedMode: VoiceInferenceMode = 'scripted'): boolean { return isVoiceInferenceMode(expectedMode) && attributes['continuity.session_ready'] === 'true' && attributes['continuity.inference_mode'] === expectedMode; }
function nativeInferenceMode(attributes: Readonly<Record<string, string>>): VoiceInferenceMode | null { const mode = attributes['continuity.inference_mode']; return isVoiceInferenceMode(mode) ? mode : null; }
export function nativeRpcResponseTimeout(method: VoiceMethod, mode: VoiceInferenceMode = 'scripted'): number { return method === 'business.commit_turn' && (mode === 'local_real' || mode === 'provider_real') ? 12000 : 8000; }

/** Numeric rejection reasons only; this helper never grants sender authority. */
export function transcriptionRejectionReasons(closed: boolean, participant: Pick<RemoteParticipant, 'kind' | 'identity'> | undefined, selected: string | null, identity: string, localIdentity: string): readonly VoiceTextCounter[] {
  const reasons: VoiceTextCounter[] = [];
  if (closed) reasons.push('sender_rejected_closed');
  if (!participant) reasons.push('sender_rejected_missing');
  else if (participant.kind !== ParticipantKind.AGENT) reasons.push('sender_rejected_non_agent');
  if (selected === null) reasons.push('sender_rejected_no_selection');
  else if (identity !== selected) reasons.push('sender_rejected_identity_mismatch');
  if (identity === localIdentity) reasons.push('sender_rejected_local');
  return reasons;
}

/** Observe actual chunks while preserving the existing bounded read/iterator cleanup. */
export async function readObservedVoiceText(stream: AsyncIterable<string>, observed: (bytes: number) => void): Promise<string> {
  let countedBytes = 0;
  async function* counted(): AsyncGenerator<string> {
    for await (const chunk of stream) {
      const bytes = Math.min(MAX_TEXT_BYTES - countedBytes, encoder.encode(chunk).length); countedBytes += bytes; observed(bytes); yield chunk;
    }
  }
  return await readBoundedText(counted(), MAX_TEXT_BYTES);
}

/** The SDK opens an agent delta stream before synchronized speech finishes. */
export async function readNativeVoiceText(reader: { withAbortSignal(signal: AbortSignal): AsyncIterable<string> }, lifetime: AbortSignal, observed: (bytes: number) => void, mode: VoiceInferenceMode = 'scripted'): Promise<string> {
  const deadline = new AbortController();
  const timer = setTimeout(() => deadline.abort(new DOMException('The native transcription stream exceeded its time budget.', 'TimeoutError')), mode === 'local_real' || mode === 'provider_real' ? 40_000 : 10_000);
  try { return await readObservedVoiceText(reader.withAbortSignal(AbortSignal.any([lifetime, deadline.signal])), observed); }
  finally { clearTimeout(timer); }
}

/** Room adapter owns native readers/audio elements; only the selected AGENT can refresh a case. */
export function createNativeVoiceRoom(callbacks: VoiceRoomCallbacks, audioHost: HTMLElement, source: VoiceInputSource = 'scripted', expectedMode: VoiceInferenceMode = 'scripted'): VoiceRoomPort {
  const room = new Room({ adaptiveStream: false, dynacast: false }), lifetime = new AbortController();
  let closed = false, selected: string | null = null, readers = 0, closing: Promise<void> | null = null;
  let inputEpoch = 0, agentEpoch = 0, startEpoch = 0, observedReady = false;
  const audio = new Map<string, { track: RemoteTrack; element: HTMLMediaElement }>();
  type OwnedInput = { track: LocalAudioTrack; close: () => Promise<void>; replay?: () => void; published: boolean; closing: Promise<void> | null };
  let input: OwnedInput | null = null;
  function stopInput(owned = input): void {
    inputEpoch += 1; startEpoch += 1;
    if (!owned) return;
    owned.track.stop();
    if (!owned.closing) { try { owned.closing = owned.close(); } catch (error) { owned.closing = Promise.reject(error); } void owned.closing.catch(() => undefined); }
  }
  const microphone = new NativeMicrophoneOwner(async (enabled) => {
    if (enabled) {
      let acquired: OwnedInput;
      if (source === 'scripted') {
        // This call creates/resumes AudioContext synchronously on the user's click.
        const scripted = await createScriptedInput({ signal: lifetime.signal });
        acquired = { track: new LocalAudioTrack(scripted.track, undefined, true), close: () => scripted.close(), replay: () => scripted.replay(), published: false, closing: null };
      } else {
        await assertNativeMicrophonePermission(navigator.permissions);
        if (microphone.mustStopTracks) throw new VoiceError('unknown', 'The capture request is no longer active.');
        const track = await createLocalAudioTrack(); acquired = { track, close: async () => { track.stop(); }, published: false, closing: null };
      }
      inputEpoch += 1; input = acquired;
      if (closed || microphone.mustStopTracks) { stopInput(acquired); await acquired.closing; if (input === acquired) input = null; throw new VoiceError('unknown', 'The capture request is no longer active.'); }
      await room.localParticipant.publishTrack(acquired.track.mediaStreamTrack, { source: Track.Source.Microphone });
      acquired.published = true;
    } else {
      const owned = input; if (!owned) return;
      stopInput(owned);
      await Promise.all([room.localParticipant.unpublishTrack(owned.track.mediaStreamTrack, true), owned.closing]);
      if (input === owned) input = null;
    }
  }, () => { stopInput(); });
  room.on(RoomEvent.LocalTrackPublished, (publication) => { if (microphone.mustStopTracks) publication.track?.stop(); });
  const selectedAgent = (participant: RemoteParticipant | undefined): boolean => !!participant && participant.kind === ParticipantKind.AGENT && participant.identity === selected;
  const activeAgent = (participant: RemoteParticipant | undefined): boolean => !!participant && selectedAgent(participant) && nativeMediaReadyAttribute(participant.attributes, expectedMode) && ['idle', 'listening', 'thinking', 'speaking'].includes(participant.attributes['lk.agent.state'] ?? '');
  function speech(participant: RemoteParticipant): void {
    const ready = activeAgent(participant);
    if (observedReady && !ready) { agentEpoch += 1; startEpoch += 1; }
    observedReady = ready;
    callbacks.sessionReady(nativeMediaReadyAttribute(participant.attributes, expectedMode), nativeInferenceMode(participant.attributes));
    const state = participant.attributes['lk.agent.state']; callbacks.speech(['initializing', 'idle', 'listening', 'thinking', 'speaking'].includes(state ?? '') ? state as SpeechState : 'unknown');
  }
  function observe(participant: RemoteParticipant): void { if (closed || participant.kind !== ParticipantKind.AGENT || selected !== null || !participant.identity || participant.identity.length > 256) return; agentEpoch += 1; selected = participant.identity; callbacks.agent(selected); speech(participant); }
  function removeAudio(sid: string): void { const entry = audio.get(sid); if (!entry) return; entry.track.detach(entry.element); entry.element.pause(); entry.element.remove(); audio.delete(sid); if (audio.size === 0) callbacks.playback('unavailable'); }
  function attach(track: RemoteTrack, participant: RemoteParticipant): void {
    if (closed || !selectedAgent(participant) || track.kind !== Track.Kind.Audio || !track.sid || audio.has(track.sid) || audio.size >= 2) return;
    const element = track.attach(); element.controls = true; element.autoplay = true; element.setAttribute('aria-label', 'Native agent audio output');
    element.addEventListener('playing', () => { if (!closed) callbacks.playback('playing'); }, { signal: lifetime.signal });
    element.addEventListener('pause', () => { if (!closed) callbacks.playback('paused'); }, { signal: lifetime.signal });
    element.addEventListener('error', () => { if (!closed) callbacks.playback('unavailable'); }, { signal: lifetime.signal });
    audio.set(track.sid, { track, element }); audioHost.append(element); callbacks.playback('ready');
  }
  room.registerTextStreamHandler('lk.transcription', (reader, info) => {
    callbacks.diagnostic('streams_received');
    const participant = room.remoteParticipants.get(info.identity);
    if (closed || !selectedAgent(participant)) { callbacks.diagnostic('sender_rejected'); for (const reason of transcriptionRejectionReasons(closed, participant, selected, info.identity, room.localParticipant.identity)) callbacks.diagnostic(reason); void reader[Symbol.asyncIterator]().return().catch(() => undefined); return; }
    if (readers >= 2) { callbacks.diagnostic('capacity_rejected'); void reader[Symbol.asyncIterator]().return().catch(() => undefined); return; }
    readers += 1;
    void readNativeVoiceText(reader, lifetime.signal, (bytes) => { callbacks.diagnostic('chunks_received'); callbacks.diagnostic('received_bytes', bytes); }, expectedMode).then((text) => {
      callbacks.diagnostic('read_completed'); callbacks.diagnostic('completed_bytes', encoder.encode(text).length);
      if (closed || !selectedAgent(room.remoteParticipants.get(info.identity))) { callbacks.diagnostic('after_read_rejected'); return; }
      callbacks.text(text);
    }).catch(() => { callbacks.diagnostic('read_failed'); }).finally(() => { readers -= 1; });
  });
  room.on(RoomEvent.ParticipantConnected, observe);
  room.on(RoomEvent.ParticipantDisconnected, (participant) => { if (participant.identity !== selected) return; agentEpoch += 1; selected = null; for (const sid of audio.keys()) removeAudio(sid); callbacks.agent(null); callbacks.speech('unknown'); for (const other of room.remoteParticipants.values()) observe(other); });
  room.on(RoomEvent.ParticipantAttributesChanged, (_changed, participant) => { if (participant instanceof Object && participant.kind === ParticipantKind.AGENT && participant.identity === selected) speech(participant as RemoteParticipant); });
  room.on(RoomEvent.TrackSubscribed, (track, _publication, participant) => { observe(participant); attach(track, participant); });
  room.on(RoomEvent.TrackUnsubscribed, (track) => { if (track.sid) removeAudio(track.sid); });
  room.on(RoomEvent.DataReceived, (payload, participant, kind, topic) => { if (closed || kind !== DataPacket_Kind.RELIABLE || topic !== 'continuity.observed' || !selectedAgent(participant)) return; const taskId = parseTaskHint(payload); if (taskId !== null) callbacks.taskHint(taskId); });
  room.on(RoomEvent.AudioPlaybackStatusChanged, (playing) => { if (!closed && !playing) callbacks.playback('blocked'); });
  room.on(RoomEvent.MediaDevicesError, () => { if (!closed) callbacks.mediaError(); });
  room.on(RoomEvent.Reconnecting, () => { agentEpoch += 1; if (!closed) callbacks.reconnecting(); });
  room.on(RoomEvent.Reconnected, () => { if (!closed) callbacks.reconnected(); });
  function cleanup(): void { if (closed) return; closed = true; microphone.close(); lifetime.abort(); room.unregisterTextStreamHandler('lk.transcription'); for (const sid of audio.keys()) removeAudio(sid); selected = null; }
  room.on(RoomEvent.Disconnected, () => { cleanup(); callbacks.disconnected(); });
  return {
    connect: async (url, token) => { await room.connect(url, token, { rtcConfig: { iceServers: [] }, websocketTimeout: 10_000, peerConnectionTimeout: 10_000 }); if (closed) return; for (const participant of room.remoteParticipants.values()) { observe(participant); if (selectedAgent(participant)) for (const publication of participant.audioTrackPublications.values()) if (publication.track) attach(publication.track, participant); } },
    disconnect: async () => {
      cleanup();
      if (!closing) closing = Promise.all([room.disconnect(true), microphone.whenDrained(), input?.closing ?? Promise.resolve()]).then(() => undefined).finally(() => { room.removeAllListeners(); });
      await voiceDeadline(closing);
    },
    whenClosed: () => closing ?? Promise.resolve(),
    setMicrophoneEnabled: (enabled) => microphone.set(enabled),
    performRpc: async (destinationIdentity, method, payload) => {
      if (closed || destinationIdentity !== selected || encoder.encode(payload).length > 128) throw new VoiceError('invalid', 'A current native agent and bounded turn payload are required.');
      const owned = input, capturedInput = inputEpoch, capturedAgent = agentEpoch;
      if (method === 'business.start_turn' || method === 'business.commit_turn') startEpoch += 1;
      const capturedStart = startEpoch;
      if (method === 'business.start_turn' && source === 'scripted' && (!owned?.published || owned.closing || microphone.mustStopTracks || owned.track.mediaStreamTrack.readyState !== 'live' || !activeAgent(room.remoteParticipants.get(destinationIdentity)))) throw new VoiceError('unknown', 'Publish the selected audio input before starting its turn.');
      const reply = await room.localParticipant.performRpc({ destinationIdentity, method, payload, responseTimeout: nativeRpcResponseTimeout(method, expectedMode) });
      if (method === 'business.start_turn' && source === 'scripted') {
        try { parseTurnReply(reply, method); } catch { throw new VoiceError('unknown', 'The native turn acknowledgement could not be verified.'); }
        const participant = room.remoteParticipants.get(destinationIdentity);
        if (closed || capturedInput !== inputEpoch || capturedAgent !== agentEpoch || capturedStart !== startEpoch || input !== owned || !owned?.published || owned.closing || microphone.mustStopTracks || owned.track.mediaStreamTrack.readyState !== 'live' || !activeAgent(participant) || !owned.replay) throw new VoiceError('unknown', 'The acknowledged audio turn is no longer active.');
        owned.replay();
      }
      return reply;
    },
    sendText: async (text) => { if (closed || !selected) throw new VoiceError('unavailable', 'The native agent is absent.'); await room.localParticipant.sendText(validateMessage(text), { topic: 'lk.chat' }); },
    startAudio: async () => { await room.startAudio(); await Promise.all([...audio.values()].map((entry) => entry.element.play())); },
  };
}
