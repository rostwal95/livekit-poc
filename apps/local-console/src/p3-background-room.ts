/** One native RTC TEXT room and one privileged read owner. No audio or business commands. */
import type { RemoteParticipant, Room } from 'livekit-client';
type NativeSdk = Pick<typeof import('livekit-client'), 'Room' | 'RoomEvent' | 'ParticipantKind'>;
import { BackgroundError, safeBackgroundCode } from './p3-background-policy';
import type { BackgroundCallbacks, BackgroundPort } from './p3-background-policy';
import {
  nativeErrorCode,
  parseNativeJson,
  parseNativeObservation,
  parseNativeSession,
  P3_PROFILE,
} from './p3-background-wire';
import type { NativeObservation, NativeSession } from './p3-background-wire';
const encoder = new TextEncoder();
const TOKEN = /^[A-Za-z0-9_-]{43}(?![\s\S])/u;
const STATES = ['idle', 'listening', 'thinking', 'speaking'];
interface TextReader extends AsyncIterable<string> {
  withAbortSignal(signal: AbortSignal): AsyncIterable<string>;
}
export function selectedNativeReady(
  session: Pick<NativeSession, 'agent_identity' | 'session_id'>,
  participant: Pick<RemoteParticipant, 'identity' | 'kind' | 'attributes'> | undefined,
  agentKind: RemoteParticipant['kind'],
): boolean {
  return (
    !!participant &&
    participant.identity === session.agent_identity &&
    participant.kind === agentKind &&
    participant.attributes['p3.native_policy.ready'] === 'true' &&
    participant.attributes['p3.native_policy.profile'] === P3_PROFILE &&
    participant.attributes['p3.native_policy.session_id'] === session.session_id &&
    participant.attributes['p3.inference_mode'] === 'scripted' &&
    STATES.includes(participant.attributes['lk.agent.state'] ?? '')
  );
}
export class NativeBackgroundPort implements BackgroundPort<NativeObservation> {
  #credential: string;
  #session: Omit<NativeSession, 'rtc_token'> | null = null;
  #room: Room | null = null;
  #closing = false;
  #joined = false;
  #joining = false;
  #read = false;
  #agentEpoch = 0;
  #agentKind: RemoteParticipant['kind'] | null = null;
  #readers = 0;
  #lifetime = new AbortController();
  #operations = new Set<Promise<void>>();
  #bodyReaders = new Set<ReadableStreamDefaultReader<Uint8Array>>();
  #closePass: Promise<void> | null = null;
  constructor(
    token: string,
    readonly callbacks: BackgroundCallbacks,
    readonly fetcher: typeof fetch = fetch,
    readonly createRoom: (() => Room) | undefined = undefined,
    readonly loadSdk: () => Promise<NativeSdk> = async () => {
      const { Room, RoomEvent, ParticipantKind } = await import('livekit-client');
      return { Room, RoomEvent, ParticipantKind };
    },
  ) {
    if (!TOKEN.test(token)) throw new BackgroundError('invalid');
    this.#credential = token;
  }
  #track<T>(operation: () => Promise<T>): Promise<T> {
    let release!: () => void;
    const completion = new Promise<void>((resolve) => {
      release = resolve;
    });
    this.#operations.add(completion);
    let actual: Promise<T>;
    try {
      actual = Promise.resolve(operation());
    } catch (error) {
      actual = Promise.reject(error);
    }
    actual.then(
      () => {
        this.#operations.delete(completion);
        release();
      },
      () => {
        this.#operations.delete(completion);
        release();
      },
    );
    return actual.catch((error: unknown) => {
      throw new BackgroundError(safeBackgroundCode(error, 'unavailable'));
    });
  }
  async #http(
    method: 'POST' | 'GET',
    path: string,
    maximum: number,
    signal: AbortSignal,
  ): Promise<unknown> {
    if (this.#closing || !this.#credential) throw new BackgroundError('closed');
    const request = this.fetcher; // Keep native Window.fetch detached from this application object.
    const response = await request(path, {
      method,
      headers: { Authorization: `Bearer ${this.#credential}`, Accept: 'application/json' },
      credentials: 'omit',
      cache: 'no-store',
      redirect: 'error',
      signal: AbortSignal.any([signal, this.#lifetime.signal]),
    });
    if (!response.body) throw new BackgroundError('invalid');
    const limit = response.status === 200 ? maximum : 256,
      length = response.headers.get('Content-Length');
    const reader = response.body.getReader(),
      decoder = new TextDecoder('utf-8', { fatal: true });
    let bytes = 0,
      text = '',
      done = false;
    this.#bodyReaders.add(reader);
    try {
      if (
        !/^application\/json(?:\s*;\s*charset=utf-8)?$/iu.test(
          response.headers.get('Content-Type') ?? '',
        ) ||
        response.headers.get('Cache-Control') !== 'no-store' ||
        response.redirected ||
        (length !== null &&
          (!/^(0|[1-9][0-9]*)(?![\s\S])/u.test(length) ||
            !Number.isSafeInteger(Number(length)) ||
            Number(length) > limit))
      )
        throw new BackgroundError('invalid');
      while (true) {
        const part = await reader.read();
        if (part.done) {
          done = true;
          break;
        }
        bytes += part.value.byteLength;
        if (bytes > limit) throw new BackgroundError('invalid');
        try {
          text += decoder.decode(part.value, { stream: true });
        } catch {
          throw new BackgroundError('invalid');
        }
      }
      try {
        text += decoder.decode();
      } catch {
        throw new BackgroundError('invalid');
      }
    } finally {
      try {
        await reader.cancel();
        done = true;
      } catch {
        /* An unresolved body remains retained for close retry. */
      }
      if (done) {
        this.#bodyReaders.delete(reader);
        reader.releaseLock();
      }
    }
    const value = parseNativeJson(text, limit);
    if (response.status !== 200) throw new BackgroundError(nativeErrorCode(value, response.status));
    return value;
  }
  join(signal: AbortSignal): Promise<void> {
    if (this.#closing || this.#joining || this.#room || this.#session)
      return Promise.reject(new BackgroundError('closed'));
    this.#joining = true;
    return this.#track(async () => {
      const { rtc_token: rtcToken, ...session } = parseNativeSession(
        await this.#http('POST', '/v1/p3-native/session', 8192, signal),
      );
      this.#session = session;
      if (!this.#closing)
        this.callbacks.session?.({
          sessionId: session.session_id,
          caseId: session.binding.case_id,
          delegationId: session.binding.delegation_id,
          requestRevision: session.binding.request_revision,
          inputFingerprint: session.binding.input_fingerprint,
        });
      if (this.#closing || signal.aborted) throw new BackgroundError('closed');
      // The existing join reservation owns module loading too; Forget cannot admit a late room.
      const sdk = await this.loadSdk();
      if (this.#closing || signal.aborted) throw new BackgroundError('closed');
      this.#agentKind = sdk.ParticipantKind.AGENT;
      const { RoomEvent } = sdk;
      const room = this.createRoom?.() ?? new sdk.Room({ adaptiveStream: false, dynacast: false });
      this.#room = room;
      if (this.#closing || signal.aborted) {
        await room.disconnect(true);
        throw new BackgroundError('closed');
      }
      const observe = (): void => {
        if (!this.#closing)
          this.callbacks.ready(
            this.#joined &&
              selectedNativeReady(
                session,
                room.remoteParticipants.get(session.agent_identity),
                sdk.ParticipantKind.AGENT,
              ),
          );
      };
      room.on(RoomEvent.ParticipantConnected, observe);
      room.on(RoomEvent.ParticipantAttributesChanged, observe);
      room.on(RoomEvent.ParticipantDisconnected, (participant) => {
        if (participant.identity === session.agent_identity) {
          this.#agentEpoch++;
          this.callbacks.ready(false);
        }
      });
      room.on(RoomEvent.Reconnecting, () => {
        if (!this.#closing) {
          this.#agentEpoch++;
          this.#joined = false;
          this.callbacks.ready(false);
          this.callbacks.connection('reconnecting');
        }
      });
      room.on(RoomEvent.Reconnected, () => {
        if (!this.#closing) {
          this.#joined = true;
          this.callbacks.connection('connected');
          observe();
        }
      });
      room.on(RoomEvent.Disconnected, () => {
        if (!this.#closing) {
          this.#joined = false;
          this.callbacks.ready(false);
          this.callbacks.connection('disconnected');
        }
      });
      room.registerTextStreamHandler('lk.transcription', (reader, info) => {
        if (this.#closing) return;
        if (
          !this.#joined ||
          info.identity !== session.agent_identity ||
          !selectedNativeReady(
            session,
            room.remoteParticipants.get(info.identity),
            sdk.ParticipantKind.AGENT,
          ) ||
          this.#readers >= 2
        ) {
          // Stop the room admission once, rather than creating unbounded rejected-reader cleanup tasks.
          this.callbacks.ready(false);
          this.callbacks.connection('disconnected');
          return;
        }
        this.#readers++;
        const epoch = this.#agentEpoch;
        void this.#track(async () => {
          const deadline = new AbortController(),
            timer = setTimeout(() => deadline.abort(), 10000);
          let text = '',
            bytes = 0;
          try {
            for await (const chunk of (reader as TextReader).withAbortSignal(
              AbortSignal.any([this.#lifetime.signal, deadline.signal]),
            )) {
              if (typeof chunk !== 'string') throw new BackgroundError('invalid');
              bytes += encoder.encode(chunk).byteLength;
              if (bytes > 16384) throw new BackgroundError('invalid');
              text += chunk;
            }
            if (
              !this.#closing &&
              this.#joined &&
              epoch === this.#agentEpoch &&
              selectedNativeReady(
                session,
                room.remoteParticipants.get(info.identity),
                sdk.ParticipantKind.AGENT,
              ) &&
              text.length > 0
            )
              this.callbacks.text(text);
          } finally {
            clearTimeout(timer);
            this.#readers--;
          }
        }).catch(() => undefined);
      });
      await room.connect(session.server_url, rtcToken, {
        autoSubscribe: false,
        rtcConfig: { iceServers: [] },
        websocketTimeout: 10000,
        peerConnectionTimeout: 10000,
      });
      if (this.#closing || signal.aborted) {
        await room.disconnect(true);
        throw new BackgroundError('closed');
      }
      if (
        room.name !== session.room_name ||
        room.localParticipant.identity !== session.participant_identity
      )
        throw new BackgroundError('invalid');
      this.#joined = true;
      observe();
    });
  }
  sendText(text: string): Promise<void> {
    const room = this.#room,
      session = this.#session;
    if (
      this.#closing ||
      !this.#joined ||
      !room ||
      !session ||
      this.#agentKind === null ||
      !selectedNativeReady(
        session,
        room.remoteParticipants.get(session.agent_identity),
        this.#agentKind,
      )
    )
      return Promise.reject(new BackgroundError('closed'));
    if (!text.trim() || encoder.encode(text).byteLength > 4096)
      return Promise.reject(new BackgroundError('invalid'));
    return this.#track(async () => {
      await room.localParticipant.sendText(text, { topic: 'lk.chat' });
    });
  }
  read(signal: AbortSignal): Promise<NativeObservation> {
    if (this.#closing || !this.#session) return Promise.reject(new BackgroundError('closed'));
    if (this.#read) return Promise.reject(new BackgroundError('overloaded'));
    this.#read = true;
    const binding = this.#session.binding;
    return this.#track(async () => {
      try {
        return parseNativeObservation(
          await this.#http('GET', '/v1/p3-native/observation', 4096, signal),
          binding,
        );
      } finally {
        this.#read = false;
      }
    });
  }
  clearCredential(): void {
    this.#credential = '';
  }
  close(): Promise<void> {
    this.#closing = true;
    this.#joined = false;
    this.#credential = '';
    this.#lifetime.abort();
    if (this.#closePass) return this.#closePass;
    const room = this.#room;
    const pass = (async () => {
      const outcomes = await Promise.allSettled([
        Promise.resolve().then(() => room?.disconnect(true)),
        ...this.#operations,
      ]);
      if (outcomes.some((outcome) => outcome.status === 'rejected'))
        throw new BackgroundError('cleanup_incomplete');
      // A connect that ignored cancellation may have completed after the first disconnect.
      if (room) await room.disconnect(true);
      for (const reader of this.#bodyReaders) {
        try {
          await reader.cancel();
          reader.releaseLock();
          this.#bodyReaders.delete(reader);
        } catch {
          throw new BackgroundError('cleanup_incomplete');
        }
      }
      if (this.#operations.size > 0 || this.#readers > 0)
        throw new BackgroundError('cleanup_incomplete');
      room?.unregisterTextStreamHandler('lk.transcription');
      room?.removeAllListeners();
      this.#room = null;
      this.#session = null;
    })();
    this.#closePass = pass;
    void pass.catch(() => {
      if (this.#closePass === pass) this.#closePass = null;
    });
    return pass;
  }
}
