import { afterEach, describe, expect, it, vi } from 'vitest';
import { ParticipantKind, RoomEvent, DataPacket_Kind, Track } from 'livekit-client';
import { JoinedRoom } from './channel-policy-room';
import type { RoomCallbacks } from './channel-policy-room';
import type { NativeSession } from './p2-native-policy';
import type { ScriptedInputSource } from './scripted-input';
const ID = '11111111-1111-4111-8111-111111111111';
const SESSION: NativeSession = {
  schemaVersion: 1,
  url: 'ws://127.0.0.1:7880',
  token: 'abc.def.ghi',
  roomId: 'room-a',
  participantId: 'browser-a',
  agentId: 'agent-a',
  bindingId: ID,
};
function held<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}
const tick = async () => {
  for (let i = 0; i < 12; i++) await Promise.resolve();
};
function setup() {
  const events = new Map<string, (...args: unknown[]) => void>(),
    connect = vi.fn<() => Promise<void>>(async () => undefined),
    disconnect = vi.fn<() => Promise<void>>(async () => undefined),
    rpc = vi.fn(async () => '{"schemaVersion":1,"status":"speech_interrupted","inputId":null}');
  const participant = {
    identity: 'agent-a',
    kind: ParticipantKind.AGENT,
    attributes: {
      'p2.session_ready': 'true',
      'p2.inference_mode': 'scripted',
      'lk.agent.state': 'listening',
    },
    audioTrackPublications: new Map(),
  };
  const local = {
    identity: 'browser-a',
    sendText: vi.fn(async () => undefined),
    performRpc: rpc,
    publishTrack: vi.fn(async () => undefined),
  };
  let rooms = 0;
  class FakeRoom {
    constructor() {
      rooms++;
    }
    name = 'room-a';
    localParticipant = local;
    remoteParticipants = new Map([['agent-a', participant]]);
    connect = connect;
    disconnect = disconnect;
    on(event: string, callback: (...args: unknown[]) => void) {
      events.set(event, callback);
      return this;
    }
    registerTextStreamHandler = vi.fn();
    unregisterTextStreamHandler = vi.fn();
    removeAllListeners = vi.fn();
    startAudio = vi.fn(async () => undefined);
  }
  const sdk = {
    Room: FakeRoom,
    RoomEvent,
    ParticipantKind,
    DataPacket_Kind,
    Track,
  } as unknown as Awaited<
    ReturnType<ConstructorParameters<typeof JoinedRoom>[3] & (() => Promise<unknown>)>
  >;
  const load = vi.fn(async () => sdk) as unknown as NonNullable<
    ConstructorParameters<typeof JoinedRoom>[3]
  >;
  const callbacks: RoomCallbacks = {
    connection: vi.fn(),
    native: vi.fn(),
    data: vi.fn(),
    text: vi.fn(),
    playback: vi.fn(),
    changed: vi.fn(),
  };
  const source: ScriptedInputSource = {
    track: {
      kind: 'audio',
      readyState: 'live',
      stop: vi.fn(),
    } as unknown as MediaStreamTrack,
    replay: vi.fn(),
    close: vi.fn(async () => undefined),
  };
  const sourceFactory = vi.fn(async () => source);
  const port = new JoinedRoom(
    SESSION,
    callbacks,
    { append: vi.fn() } as unknown as HTMLElement,
    load,
    sourceFactory,
  );
  return {
    port,
    callbacks,
    events,
    connect,
    disconnect,
    rpc,
    participant,
    local,
    source,
    sourceFactory,
    load,
    rooms: () => rooms,
  };
}
afterEach(() => vi.useRealTimers());
describe('joined actual SDK boundary adapter with controlled SDK peers', () => {
  it('constructs without SDK load, media or source I/O, then uses fixed native connection', async () => {
    const s = setup();
    expect(s.rooms()).toBe(0);
    expect(s.load).not.toHaveBeenCalled();
    expect(s.sourceFactory).not.toHaveBeenCalled();
    await s.port.connect(new AbortController().signal);
    expect(s.connect).toHaveBeenCalledWith(
      SESSION.url,
      SESSION.token,
      expect.objectContaining({ autoSubscribe: false }),
    );
    await s.port.close();
    expect(s.port.pendingCount).toBe(0);
  });
  it('does not allocate a late Room after End while genuine module-load ownership is held', async () => {
    const s = setup(),
      gate = held<Awaited<ReturnType<typeof s.load>>>();
    vi.mocked(s.load).mockReturnValueOnce(gate.promise);
    const connect = s.port.connect(new AbortController().signal);
    void connect.catch(() => undefined);
    const close = s.port.close();
    gate.resolve(await s.load());
    await close;
    expect(s.rooms()).toBe(0);
    await expect(connect).rejects.toBeDefined();
    expect(s.port.pendingCount).toBe(0);
  });
  it('retains actual connect through failed close observation, then closes its late allocation', async () => {
    vi.useFakeTimers();
    const s = setup(),
      gate = held<void>();
    s.connect.mockReturnValueOnce(gate.promise);
    const connecting = s.port.connect(new AbortController().signal);
    void connecting.catch(() => undefined);
    await tick();
    const closing = s.port.close();
    const outcome = Promise.allSettled([closing]);
    await vi.advanceTimersByTimeAsync(5001);
    expect((await outcome)[0]?.status).toBe('rejected');
    expect(s.port.pendingCount).toBe(1);
    gate.resolve();
    await s.port.whenClosed();
    expect(s.port.pendingCount).toBe(0);
    expect(s.disconnect.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(s.callbacks.connection).not.toHaveBeenCalledWith('connected');
  });
  it('sends original text ID through actual public sendText signature and has no authority RPC', async () => {
    const s = setup();
    await s.port.connect(new AbortController().signal);
    await s.port.sendText({
      inputId: ID,
      channel: 'web_chat',
      body: 'Inspect the current case',
    });
    expect(s.local.sendText).toHaveBeenCalledWith('Inspect the current case', {
      topic: 'lk.chat',
      attributes: { 'p2.input_id': ID },
    });
    expect(s.rpc).not.toHaveBeenCalled();
    await s.port.close();
  });
  it('admits only selected reliable bounded acceptance/generation packets, never optional response IDs', async () => {
    const s = setup();
    await s.port.connect(new AbortController().signal);
    const data = s.events.get(RoomEvent.DataReceived)!;
    data(
      new Uint8Array([1]),
      { ...s.participant, identity: 'foreign' },
      DataPacket_Kind.RELIABLE,
      'p2.acceptance',
    );
    data(new Uint8Array([1]), s.participant, DataPacket_Kind.LOSSY, 'p2.acceptance');
    data(new Uint8Array(2049), s.participant, DataPacket_Kind.RELIABLE, 'p2.acceptance');
    data(new Uint8Array([1]), s.participant, DataPacket_Kind.RELIABLE, 'p2.response');
    expect(s.callbacks.data).not.toHaveBeenCalled();
    data(new Uint8Array([1]), s.participant, DataPacket_Kind.RELIABLE, 'p2.acceptance');
    expect(s.callbacks.data).toHaveBeenCalledTimes(1);
    await s.port.close();
    data(new Uint8Array([1]), s.participant, DataPacket_Kind.RELIABLE, 'p2.acceptance');
    expect(s.callbacks.data).toHaveBeenCalledTimes(1);
  });
  it('publishes a silent declared fixture only on explicit gesture and replays only after verified Start ACK', async () => {
    const s = setup();
    await s.port.connect(new AbortController().signal);
    expect(s.sourceFactory).not.toHaveBeenCalled();
    await s.port.prepareVoice();
    expect(s.source.replay).not.toHaveBeenCalled();
    s.rpc.mockResolvedValueOnce(
      JSON.stringify({ schemaVersion: 1, status: 'turn_started', inputId: ID }),
    );
    expect(await s.port.turn('p2.start_turn', ID)).toBe('turn_started');
    expect(s.source.replay).toHaveBeenCalledTimes(1);
    expect(s.port.turnInput).toBe(ID);
    expect(s.local.publishTrack).toHaveBeenCalledWith(s.source.track, {
      source: Track.Source.Microphone,
    });
    await s.port.close();
    expect(s.source.track.stop).toHaveBeenCalled();
    expect(s.source.close).toHaveBeenCalled();
  });
  it('never publishes a source that arrives after its5s observer deadline', async () => {
    vi.useFakeTimers();
    const s = setup(),
      gate = held<ScriptedInputSource>();
    await s.port.connect(new AbortController().signal);
    s.sourceFactory.mockReturnValueOnce(gate.promise);
    const prepared = s.port.prepareVoice();
    const outcome = Promise.allSettled([prepared]);
    await vi.advanceTimersByTimeAsync(5001);
    expect((await outcome)[0]?.status).toBe('rejected');
    expect(s.port.pendingCount).toBe(1);
    gate.resolve(s.source);
    await tick();
    expect(s.local.publishTrack).not.toHaveBeenCalled();
    expect(s.source.track.stop).toHaveBeenCalled();
    expect(s.source.close).toHaveBeenCalled();
    expect(s.port.voicePrepared).toBe(false);
    await s.port.close();
  });
  it('does not replay recorded audio after a late Start RPC ACK beyond8s', async () => {
    vi.useFakeTimers();
    const s = setup();
    await s.port.connect(new AbortController().signal);
    await s.port.prepareVoice();
    const gate = held<string>();
    s.rpc.mockReturnValueOnce(gate.promise);
    const turn = s.port.turn('p2.start_turn', ID),
      outcome = Promise.allSettled([turn]);
    await vi.advanceTimersByTimeAsync(8001);
    expect((await outcome)[0]?.status).toBe('rejected');
    expect(s.port.controlsPending).toBe(true);
    gate.resolve(JSON.stringify({ schemaVersion: 1, status: 'turn_started', inputId: ID }));
    await tick();
    expect(s.source.replay).not.toHaveBeenCalled();
    expect(s.port.turnInput).toBeNull();
    await s.port.close();
  });
  it('uses only caller-bound p2.interrupt and can interrupt while a commit is actually held', async () => {
    const s = setup();
    await s.port.connect(new AbortController().signal);
    await s.port.prepareVoice();
    const gate = held<string>();
    s.rpc.mockReturnValueOnce(gate.promise);
    const commit = s.port.turn('p2.commit_turn', ID);
    expect(await s.port.turn('p2.interrupt', null)).toBe('speech_interrupted');
    expect(s.rpc).toHaveBeenLastCalledWith({
      destinationIdentity: 'agent-a',
      method: 'p2.interrupt',
      payload: '{"schemaVersion":1}',
      responseTimeout: 8000,
    });
    gate.resolve(
      JSON.stringify({
        schemaVersion: 1,
        status: 'turn_committed',
        inputId: ID,
      }),
    );
    await commit;
    await s.port.close();
  });
  it('retains a failed source cleanup owner and never claims whenClosed success', async () => {
    const s = setup();
    await s.port.connect(new AbortController().signal);
    await s.port.prepareVoice();
    s.sourceFactory.mockResolvedValue(s.source);
    vi.mocked(s.source.close).mockRejectedValueOnce(new Error('PRIVATE'));
    await expect(s.port.close()).rejects.toBeDefined();
    expect(s.port.voicePrepared).toBe(true);
    await s.port.close();
    expect(s.port.voicePrepared).toBe(false);
    await s.port.whenClosed();
  });
});
