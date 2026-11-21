/** One genuine P2 v1 SDK activation. No optional response/publication authority. */
import type { Room, RemoteParticipant, RemoteTrack } from 'livekit-client';
import { createScriptedInput } from './scripted-input';
import type { ScriptedInputOptions, ScriptedInputSource } from './scripted-input';
import {
  nativeReady,
  NATIVE_INPUT_ATTRIBUTE,
  parseNativeTurnReply,
  turnPayload,
} from './p2-native-policy';
import type { NativeMode, NativeSession, FrozenNativeInput, TurnMethod } from './p2-native-policy';
import { JoinedUiError } from './channel-policy-contract';
import { observed } from './channel-policy-client';
import { safeCode } from './channel-policy-wire';
type Sdk = Pick<
  typeof import('livekit-client'),
  'Room' | 'RoomEvent' | 'ParticipantKind' | 'DataPacket_Kind' | 'Track'
>;
export interface RoomCallbacks {
  connection(value: 'connected' | 'reconnecting' | 'disconnected'): void;
  native(
    identity: string | null,
    kind: 'agent' | 'other',
    attributes: Readonly<Record<string, string>>,
  ): void;
  data(topic: 'p2.acceptance' | 'p2.generation', raw: Uint8Array): void;
  /** Accumulated agent transcript for one stream; live while the stream stays open. */
  text(value: string, stream: number, live: boolean): void;
  playback(playing: boolean): void;
  changed(): void;
}
/** Live browser capture with the scripted source's shape; replay is a no-op. */
export async function createMicrophoneInput(
  options: ScriptedInputOptions = {},
): Promise<ScriptedInputSource> {
  if (options.signal?.aborted) throw new JoinedUiError('unavailable');
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  });
  const [track] = stream.getAudioTracks();
  for (const extra of stream.getTracks()) if (extra !== track) extra.stop();
  if (!track || options.signal?.aborted) {
    track?.stop();
    throw new JoinedUiError('unavailable');
  }
  return Object.freeze({
    track,
    replay: () => undefined,
    close: async () => track.stop(),
  });
}
export interface JoinedRoomOptions {
  readonly mode?: NativeMode;
}
export class JoinedRoom {
  #session: NativeSession;
  #mode: NativeMode;
  #room: Room | null = null;
  #sdk: Sdk | null = null;
  #closing = false;
  #joined = false;
  #agentEpoch = 0;
  #lifetime = new AbortController();
  #actual = new Set<Promise<unknown>>();
  #closeActual: Promise<void> | null = null;
  #fixture: ScriptedInputSource | null = null;
  #sourceBusy = false;
  #turnBusy = false;
  #interruptBusy = false;
  #sendBusy = false;
  #audioBusy = false;
  #readers = 0;
  #streams = 0;
  #turn: string | null = null;
  #outputs = new Map<RemoteTrack, HTMLMediaElement>();
  #playing = new Set<HTMLMediaElement>();
  constructor(
    session: NativeSession,
    readonly callbacks: RoomCallbacks,
    readonly audioHost: HTMLElement,
    readonly loadSdk: () => Promise<Sdk> = async () => {
      const { Room, RoomEvent, ParticipantKind, DataPacket_Kind, Track } =
        await import('livekit-client');
      return { Room, RoomEvent, ParticipantKind, DataPacket_Kind, Track };
    },
    readonly sourceFactory: typeof createScriptedInput = createScriptedInput,
    options: JoinedRoomOptions = {},
  ) {
    this.#session = Object.freeze({ ...session });
    this.#mode = options.mode === 'provider_real' ? 'provider_real' : 'scripted';
  }
  get mode(): NativeMode {
    return this.#mode;
  }
  whenClosed(): Promise<void> {
    return this.#closeActual ?? Promise.reject(new JoinedUiError('cleanup_incomplete'));
  }
  get controlsPending(): boolean {
    return this.#sourceBusy || this.#turnBusy || this.#sendBusy;
  }
  get pendingCount(): number {
    return this.#actual.size;
  }
  get voicePrepared(): boolean {
    return this.#fixture !== null;
  }
  get turnInput(): string | null {
    return this.#turn;
  }
  #full(): boolean {
    return this.#actual.size >= 8;
  }
  #track<T>(operation: () => Promise<T>): Promise<T> {
    if (this.#full()) return Promise.reject(new JoinedUiError('capacity'));
    let actual: Promise<T>;
    try {
      actual = Promise.resolve(operation());
    } catch (error) {
      actual = Promise.reject(error);
    }
    this.#actual.add(actual);
    void actual.then(
      () => this.#actual.delete(actual),
      () => this.#actual.delete(actual),
    );
    return actual.catch((error) => {
      throw safeCode(error);
    });
  }
  #selected(participant: RemoteParticipant | undefined): boolean {
    return (
      !!participant &&
      this.#sdk !== null &&
      participant.kind === this.#sdk.ParticipantKind.AGENT &&
      participant.identity === this.#session.agentId
    );
  }
  #ready(): boolean {
    const p = this.#room?.remoteParticipants.get(this.#session.agentId);
    return (
      !this.#closing &&
      this.#selected(p) &&
      nativeReady(
        this.#joined,
        this.#session,
        p?.identity ?? null,
        'agent',
        p?.attributes ?? {},
        this.#mode,
      )
    );
  }
  #subscribe(participant: RemoteParticipant | undefined): void {
    if (this.#closing || !this.#selected(participant)) return;
    let count = 0;
    for (const publication of participant!.audioTrackPublications.values())
      if (++count <= 2) publication.setSubscribed(true);
  }
  #observe(): void {
    if (this.#closing) return;
    const p = this.#room?.remoteParticipants.get(this.#session.agentId);
    this.callbacks.native(
      p?.identity ?? null,
      this.#selected(p) ? 'agent' : 'other',
      Object.freeze({ ...p?.attributes }),
    );
    this.callbacks.changed();
  }
  connect(signal: AbortSignal): Promise<void> {
    if (this.#closing || this.#room || this.#actual.size)
      return Promise.reject(new JoinedUiError('conflict'));
    return observed(
      this.#track(async () => {
        const sdk = await this.loadSdk();
        if (this.#closing || signal.aborted) throw new JoinedUiError('unavailable');
        this.#sdk = sdk;
        const room = new sdk.Room({ adaptiveStream: false, dynacast: false });
        this.#room = room;
        const E = sdk.RoomEvent;
        room.on(E.ParticipantConnected, (p) => {
          this.#subscribe(p);
          this.#observe();
        });
        room.on(E.TrackPublished, (_publication, p) => this.#subscribe(p));
        room.on(E.ParticipantAttributesChanged, () => this.#observe());
        room.on(E.ParticipantDisconnected, (p) => {
          if (this.#selected(p)) {
            ++this.#agentEpoch;
            this.#observe();
          }
        });
        room.on(E.Reconnecting, () => {
          if (!this.#closing) {
            ++this.#agentEpoch;
            this.#joined = false;
            this.callbacks.connection('reconnecting');
            this.#observe();
          }
        });
        room.on(E.Reconnected, () => {
          if (!this.#closing) {
            this.#joined = true;
            this.callbacks.connection('connected');
            this.#observe();
          }
        });
        room.on(E.Disconnected, () => {
          if (!this.#closing) {
            this.#joined = false;
            this.callbacks.connection('disconnected');
            this.#observe();
          }
        });
        room.on(E.TrackSubscribed, (track, _publication, p) => {
          if (!this.#closing && this.#selected(p)) this.#attach(track);
        });
        room.on(E.TrackUnsubscribed, (track) => this.#detach(track));
        room.on(E.DataReceived, (bytes, p, kind, topic) => {
          if (
            !this.#closing &&
            this.#selected(p) &&
            kind === sdk.DataPacket_Kind.RELIABLE &&
            (topic === 'p2.acceptance' || topic === 'p2.generation')
          ) {
            if (bytes.byteLength > (topic === 'p2.acceptance' ? 2048 : 1024)) return;
            this.callbacks.data(topic, bytes.slice());
          }
        });
        room.registerTextStreamHandler('lk.transcription', (reader, source) => {
          // Foreign senders, including the SDK's user transcript sent on this
          // browser's behalf, unready agents and excess streams are released
          // without changing state.
          if (
            this.#closing ||
            !this.#ready() ||
            !this.#selected(room.remoteParticipants.get(source.identity)) ||
            this.#readers >= 2 ||
            this.#actual.size >= 8
          ) {
            void reader[Symbol.asyncIterator]()
              .return()
              .catch(() => undefined);
            return;
          }
          ++this.#readers;
          const epoch = this.#agentEpoch;
          const stream = ++this.#streams;
          const current = (): boolean => this.#ready() && epoch === this.#agentEpoch;
          let shown = '';
          const report = (text: string, live: boolean): void => {
            if (!current() || !text.trim() || new TextEncoder().encode(text).length > 16384) return;
            shown = live ? text : '';
            try {
              this.callbacks.text(text, stream, live);
            } catch {
              // A rejected display update must not leak this reader's slot.
            }
          };
          // The bounded reader still owns limits and deadlines; this only tees chunks.
          void this.#track(async () => {
            try {
              if (this.#closing) throw new JoinedUiError('unavailable');
              const deadline = AbortSignal.timeout(
                this.#mode === 'provider_real' ? 40_000 : 10_000,
              );
              const source = reader.withAbortSignal(
                AbortSignal.any([this.#lifetime.signal, deadline]),
              );
              const encoder = new TextEncoder();
              let bytes = 0;
              let text = '';
              for await (const chunk of source) {
                bytes += encoder.encode(chunk).byteLength;
                if (bytes > 16_384) throw new JoinedUiError('invalid');
                text += chunk;
                report(text, true);
              }
              report(text, false);
            } finally {
              if (shown) report(shown, false);
              --this.#readers;
              this.callbacks.changed();
            }
          }).catch(() => undefined);
        });
        await room.connect(this.#session.url, this.#session.token, {
          autoSubscribe: false,
          rtcConfig: { iceServers: [] },
          websocketTimeout: 10000,
          peerConnectionTimeout: 10000,
        });
        if (this.#closing || signal.aborted) {
          await room.disconnect(true);
          throw new JoinedUiError('unavailable');
        }
        if (
          room.name !== this.#session.roomId ||
          room.localParticipant.identity !== this.#session.participantId
        )
          throw new JoinedUiError('invalid');
        this.#joined = true;
        this.callbacks.connection('connected');
        this.#observe();
        for (const p of room.remoteParticipants.values())
          if (this.#selected(p)) {
            this.#subscribe(p);
            for (const publication of p.audioTrackPublications.values())
              if (publication.track) this.#attach(publication.track);
          }
      }),
      12000,
      () => new JoinedUiError('unknown'),
    );
  }
  #attach(track: RemoteTrack): void {
    if (
      !this.#sdk ||
      track.kind !== this.#sdk.Track.Kind.Audio ||
      this.#outputs.has(track) ||
      this.#outputs.size >= 2
    )
      return;
    const element = track.attach();
    element.setAttribute('aria-hidden', 'true');
    element.hidden = true;
    this.#outputs.set(track, element);
    this.audioHost.append(element);
    const changed = (): void => {
      if (this.#closing) return;
      if (!element.paused && element.readyState >= 2) this.#playing.add(element);
      else this.#playing.delete(element);
      this.callbacks.playback(this.#playing.size > 0);
    };
    element.addEventListener('playing', changed);
    element.addEventListener('pause', changed);
    element.addEventListener('ended', changed);
    changed();
  }
  #detach(track: RemoteTrack): void {
    const element = this.#outputs.get(track);
    if (!element) return;
    track.detach(element);
    element.remove();
    this.#outputs.delete(track);
    this.#playing.delete(element);
    if (!this.#closing) this.callbacks.playback(this.#playing.size > 0);
  }
  sendText(input: FrozenNativeInput): Promise<void> {
    if (!this.#ready() || this.#sendBusy || input.channel !== 'web_chat' || input.body === null)
      return Promise.reject(new JoinedUiError('unavailable'));
    // Admit before setting the busy flag; only an admitted operation resets it.
    if (this.#full()) return Promise.reject(new JoinedUiError('capacity'));
    this.#sendBusy = true;
    return observed(
      this.#track(async () => {
        try {
          await this.#room!.localParticipant.sendText(input.body!, {
            topic: 'lk.chat',
            attributes: { [NATIVE_INPUT_ATTRIBUTE]: input.inputId },
          });
        } finally {
          this.#sendBusy = false;
          this.callbacks.changed();
        }
      }),
      8000,
      () => new JoinedUiError('unknown'),
    );
  }
  prepareVoice(): Promise<void> {
    if (!this.#ready() || this.#sourceBusy || this.#fixture)
      return Promise.reject(new JoinedUiError('unavailable'));
    if (this.#full()) return Promise.reject(new JoinedUiError('capacity'));
    this.#sourceBusy = true;
    let admitted = true;
    // Starts synchronously in this explicit user gesture, before any unrelated await.
    return observed(
      this.#track(async () => {
        try {
          const source = await this.sourceFactory({
            signal: this.#lifetime.signal,
          });
          this.#fixture = source;
          if (!admitted || this.#closing || !this.#ready()) {
            source.track.stop();
            await source.close();
            this.#fixture = null;
            throw new JoinedUiError('unavailable');
          }
          await this.#room!.localParticipant.publishTrack(source.track, {
            source: this.#sdk!.Track.Source.Microphone,
          });
          if (!admitted || this.#closing) {
            source.track.stop();
            throw new JoinedUiError('unavailable');
          }
        } finally {
          this.#sourceBusy = false;
          this.callbacks.changed();
        }
      }),
      5000,
      () => {
        admitted = false;
        this.#fixture?.track.stop();
        return new JoinedUiError('unknown');
      },
    );
  }
  turn(method: TurnMethod, inputId: string | null): Promise<string> {
    const interrupt = method === 'p2.interrupt';
    if (
      !this.#ready() ||
      (interrupt ? this.#interruptBusy : this.#turnBusy) ||
      (!interrupt && (!this.#fixture || this.#fixture.track.readyState !== 'live'))
    )
      return Promise.reject(new JoinedUiError('unavailable'));
    if (this.#full()) return Promise.reject(new JoinedUiError('capacity'));
    const payload = turnPayload(method, inputId);
    if (interrupt) this.#interruptBusy = true;
    else this.#turnBusy = true;
    const source = this.#fixture;
    let admitted = true;
    // Real recognition commits wait for provider transcription (agent budget 11 s).
    const timeoutMs = method === 'p2.commit_turn' && this.#mode === 'provider_real' ? 12000 : 8000;
    return observed(
      this.#track(async () => {
        try {
          const raw = await this.#room!.localParticipant.performRpc({
            destinationIdentity: this.#session.agentId,
            method,
            payload,
            responseTimeout: timeoutMs,
          });
          const status = parseNativeTurnReply(raw, method, inputId);
          if (!admitted || !this.#ready()) throw new JoinedUiError('unknown');
          if (method === 'p2.start_turn') {
            if (this.#fixture !== source || !source) throw new JoinedUiError('unknown');
            source.replay();
            this.#turn = inputId;
          } else if (method === 'p2.commit_turn') this.#turn = null;
          return status;
        } finally {
          if (interrupt) this.#interruptBusy = false;
          else this.#turnBusy = false;
          this.callbacks.changed();
        }
      }),
      timeoutMs,
      () => {
        admitted = false;
        return new JoinedUiError('unknown');
      },
    );
  }
  enableAudio(): Promise<void> {
    if (this.#closing || !this.#room || this.#audioBusy)
      return Promise.reject(new JoinedUiError('unavailable'));
    if (this.#full()) return Promise.reject(new JoinedUiError('capacity'));
    this.#audioBusy = true;
    return observed(
      this.#track(async () => {
        try {
          await this.#room!.startAudio();
        } finally {
          this.#audioBusy = false;
        }
      }),
      5000,
      () => new JoinedUiError('unknown'),
    );
  }
  close(): Promise<void> {
    this.#closing = true;
    this.#session = Object.freeze({ ...this.#session, token: '' });
    this.#joined = false;
    this.#lifetime.abort();
    ++this.#agentEpoch;
    this.#fixture?.track.stop();
    for (const track of [...this.#outputs.keys()]) this.#detach(track);
    if (!this.#closeActual) {
      const close = (async () => {
        const room = this.#room;
        const early = Promise.resolve().then(() => room?.disconnect(true));
        await Promise.allSettled([early, ...this.#actual]);
        // Late module/connect/publish allocation is now settled and still belongs to this owner.
        if (this.#room) await this.#room.disconnect(true);
        if (this.#fixture) {
          await this.#fixture.close();
          this.#fixture = null;
        }
        if (this.#actual.size || this.#readers || this.#outputs.size)
          throw new JoinedUiError('cleanup_incomplete');
        this.#room?.unregisterTextStreamHandler('lk.transcription');
        this.#room?.removeAllListeners();
        this.#room = null;
        this.#turn = null;
      })();
      this.#closeActual = close;
      void close.catch(() => {
        if (this.#closeActual === close) this.#closeActual = null;
      });
    }
    return observed(this.#closeActual, 5000, () => new JoinedUiError('cleanup_incomplete'));
  }
}
