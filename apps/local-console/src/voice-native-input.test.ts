import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createNativeVoiceRoom } from './voice';
import type { VoiceRoomCallbacks, VoiceRoomPort } from './voice';

const sdk = vi.hoisted(() => {
  class FakeLocalTrack {
    constructor(readonly mediaStreamTrack: { readyState: string; stop(): void }) {}
    stop(): void { this.mediaStreamTrack.stop(); }
  }
  const rooms: FakeRoom[] = [];
  class FakeRoom {
    readonly handlers = new Map<string, (...args: unknown[]) => void>();
    readonly remoteParticipants = new Map<string, { identity: string; kind: string; attributes: Record<string, string>; audioTrackPublications: Map<string, never> }>();
    readonly localParticipant = { identity: 'browser', publishTrack: vi.fn<() => Promise<void>>(async () => undefined), unpublishTrack: vi.fn<() => Promise<void>>(async () => undefined), performRpc: vi.fn(async () => '{"schema_version":1,"status":"turn_started"}'), sendText: vi.fn(async () => undefined) };
    readonly connect = vi.fn(async () => undefined); readonly disconnect = vi.fn(async () => undefined); readonly startAudio = vi.fn(async () => undefined);
    readonly registerTextStreamHandler = vi.fn(); readonly unregisterTextStreamHandler = vi.fn(); readonly removeAllListeners = vi.fn();
    constructor() { rooms.push(this); }
    on(event: string, handler: (...args: unknown[]) => void): this { this.handlers.set(event, handler); return this; }
    emit(event: string, ...args: unknown[]): void { this.handlers.get(event)?.(...args); }
  }
  return { rooms, FakeRoom, FakeLocalTrack, createLocalAudioTrack: vi.fn() };
});
const fixture = vi.hoisted(() => ({ create: vi.fn() }));
vi.mock('./scripted-input', () => ({ createScriptedInput: fixture.create }));
vi.mock('livekit-client', () => ({
  Room: sdk.FakeRoom, LocalAudioTrack: sdk.FakeLocalTrack, createLocalAudioTrack: sdk.createLocalAudioTrack,
  ParticipantKind: { AGENT: 'agent' }, DataPacket_Kind: { RELIABLE: 0 }, Track: { Source: { Microphone: 'microphone' }, Kind: { Audio: 'audio' } },
  RoomEvent: Object.fromEntries(['LocalTrackPublished', 'ParticipantConnected', 'ParticipantDisconnected', 'ParticipantAttributesChanged', 'TrackSubscribed', 'TrackUnsubscribed', 'DataReceived', 'AudioPlaybackStatusChanged', 'MediaDevicesError', 'Reconnecting', 'Reconnected', 'Disconnected'].map((name) => [name, name])),
}));
function deferred<T>() { let resolve!: (value: T) => void, reject!: (error: Error) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
function input() {
  const track = { kind: 'audio', readyState: 'live', stop: vi.fn(() => { track.readyState = 'ended'; }) };
  return { track, replay: vi.fn(), close: vi.fn(async () => { track.stop(); }) };
}
function callbacks(): VoiceRoomCallbacks { return { agent: vi.fn(), speech: vi.fn(), sessionReady: vi.fn(), playback: vi.fn(), text: vi.fn(), taskHint: vi.fn(), disconnected: vi.fn(), reconnecting: vi.fn(), reconnected: vi.fn(), mediaError: vi.fn(), diagnostic: vi.fn() }; }
const payload = '{"schema_version":1}', ack = '{"schema_version":1,"status":"turn_started"}';
async function setup(source: 'scripted' | 'microphone' = 'scripted') {
  const first = input(); fixture.create.mockResolvedValueOnce(first);
  const port = createNativeVoiceRoom(callbacks(), {} as HTMLElement, source, 'provider_real'), room = sdk.rooms.at(-1)!;
  const agent = { identity: 'native-agent', kind: 'agent', attributes: { 'continuity.session_ready': 'true', 'continuity.inference_mode': 'provider_real', 'lk.agent.state': 'listening' }, audioTrackPublications: new Map<string, never>() };
  room.remoteParticipants.set(agent.identity, agent); await port.connect('ws://localhost', 'token');
  return { first, port, room, agent };
}
async function start(port: VoiceRoomPort): Promise<string> { return await port.performRpc('native-agent', 'business.start_turn', payload); }
beforeEach(() => { sdk.rooms.length = 0; fixture.create.mockReset(); sdk.createLocalAudioTrack.mockReset(); });
afterEach(() => { vi.unstubAllGlobals(); });

describe('native scripted source starts only after the validated manual-turn acknowledgement', () => {
  it('publishes a silent owned track, then rewinds only after the actual RPC resolves', async () => {
    const s = await setup(), reply = deferred<string>(); await s.port.setMicrophoneEnabled(true);
    expect(s.first.replay).not.toHaveBeenCalled(); expect(s.room.localParticipant.publishTrack).toHaveBeenCalledExactlyOnceWith(s.first.track, { source: 'microphone' });
    s.room.localParticipant.performRpc.mockReturnValueOnce(reply.promise); const turning = start(s.port);
    expect(s.first.replay).not.toHaveBeenCalled(); expect(s.room.localParticipant.performRpc).toHaveBeenCalledExactlyOnceWith({ destinationIdentity: 'native-agent', method: 'business.start_turn', payload, responseTimeout: 8000 });
    reply.resolve(ack); await expect(turning).resolves.toBe(ack); expect(s.first.replay).toHaveBeenCalledOnce(); await s.port.disconnect();
  });
  it('rejects start before actual publication completes', async () => {
    const s = await setup(), publication = deferred<void>(); s.room.localParticipant.publishTrack.mockReturnValueOnce(publication.promise);
    const publishing = s.port.setMicrophoneEnabled(true); await Promise.resolve(); await Promise.resolve();
    await expect(start(s.port)).rejects.toMatchObject({ code: 'unknown' }); expect(s.room.localParticipant.performRpc).not.toHaveBeenCalled(); expect(s.first.replay).not.toHaveBeenCalled();
    publication.resolve(); await publishing; await start(s.port); expect(s.first.replay).toHaveBeenCalledOnce(); await s.port.disconnect();
  });
  it.each(['{"schema_version":1,"status":"turn_started","extra":true}', '{"schema_version":true,"status":"turn_started"}', '{"schema_version":1,"status":"turn_committed"}', 'not-json'])('does not replay a malformed or wrong acknowledgement %s', async (reply) => {
    const s = await setup(); await s.port.setMicrophoneEnabled(true); s.room.localParticipant.performRpc.mockResolvedValueOnce(reply);
    await expect(start(s.port)).rejects.toMatchObject({ code: 'unknown' }); expect(s.first.replay).not.toHaveBeenCalled(); await s.port.disconnect();
  });
  it('does not replay when the RPC rejects', async () => {
    const s = await setup(); await s.port.setMicrophoneEnabled(true); s.room.localParticipant.performRpc.mockRejectedValueOnce(new Error('private failure'));
    await expect(start(s.port)).rejects.toThrow(); expect(s.first.replay).not.toHaveBeenCalled(); await s.port.disconnect();
  });
  it('fences a late reply after mute and replacement without starting either input', async () => {
    const s = await setup(), reply = deferred<string>(), replacement = input(); await s.port.setMicrophoneEnabled(true);
    s.room.localParticipant.performRpc.mockReturnValueOnce(reply.promise); const turning = start(s.port);
    await s.port.setMicrophoneEnabled(false); fixture.create.mockResolvedValueOnce(replacement); await s.port.setMicrophoneEnabled(true);
    reply.resolve(ack); await expect(turning).rejects.toMatchObject({ code: 'unknown' }); expect(s.first.replay).not.toHaveBeenCalled(); expect(replacement.replay).not.toHaveBeenCalled();
    await start(s.port); expect(replacement.replay).toHaveBeenCalledOnce(); await s.port.disconnect();
  });
  it.each(['end', 'agent', 'reconnect', 'readiness', 'mode', 'sdk_initializing', 'sdk_unknown'] as const)('fences the late acknowledgement after %s', async (change) => {
    const s = await setup(), reply = deferred<string>(); await s.port.setMicrophoneEnabled(true); s.room.localParticipant.performRpc.mockReturnValueOnce(reply.promise); const turning = start(s.port);
    if (change === 'end') await s.port.disconnect();
    if (change === 'agent') { s.room.emit('ParticipantDisconnected', s.agent); s.room.emit('ParticipantConnected', s.agent); }
    if (change === 'reconnect') { s.room.emit('Reconnecting'); s.room.emit('Reconnected'); }
    if (change === 'readiness') s.agent.attributes['continuity.session_ready'] = 'false';
    if (change === 'mode') s.agent.attributes['continuity.inference_mode'] = 'scripted';
    if (change === 'sdk_initializing') s.agent.attributes['lk.agent.state'] = 'initializing';
    if (change === 'sdk_unknown') s.agent.attributes['lk.agent.state'] = 'unknown';
    reply.resolve(ack); await expect(turning).rejects.toMatchObject({ code: 'unknown' }); expect(s.first.replay).not.toHaveBeenCalled(); await s.port.disconnect();
  });
  it.each(['continuity.session_ready', 'continuity.inference_mode', 'lk.agent.state'] as const)('does not revive a pending start after observed %s loss and restoration', async (attribute) => {
    const s = await setup(), reply = deferred<string>(); await s.port.setMicrophoneEnabled(true); s.room.localParticipant.performRpc.mockReturnValueOnce(reply.promise); const turning = start(s.port);
    const original = s.agent.attributes[attribute]!; s.agent.attributes[attribute] = attribute === 'continuity.session_ready' ? 'false' : attribute === 'continuity.inference_mode' ? 'scripted' : 'initializing';
    s.room.emit('ParticipantAttributesChanged', { [attribute]: s.agent.attributes[attribute] }, s.agent);
    s.agent.attributes[attribute] = original; s.room.emit('ParticipantAttributesChanged', { [attribute]: original }, s.agent);
    reply.resolve(ack); await expect(turning).rejects.toMatchObject({ code: 'unknown' }); expect(s.first.replay).not.toHaveBeenCalled();
    await start(s.port); expect(s.first.replay).toHaveBeenCalledOnce(); await s.port.disconnect();
  });
  it('does not let an older start acknowledgement rewind a newer active turn', async () => {
    const s = await setup(), older = deferred<string>(), newer = deferred<string>(); await s.port.setMicrophoneEnabled(true);
    s.room.localParticipant.performRpc.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
    const first = start(s.port), second = start(s.port); newer.resolve(ack); await second; expect(s.first.replay).toHaveBeenCalledOnce();
    older.resolve(ack); await expect(first).rejects.toMatchObject({ code: 'unknown' }); expect(s.first.replay).toHaveBeenCalledOnce(); await s.port.disconnect();
  });
  it('keeps physical microphone capture and RPC behavior independent of the WAV', async () => {
    const physical = input(); sdk.createLocalAudioTrack.mockResolvedValueOnce(new sdk.FakeLocalTrack(physical.track)); vi.stubGlobal('navigator', { permissions: { query: vi.fn(async () => ({ state: 'granted' })) } });
    const s = await setup('microphone'); await s.port.setMicrophoneEnabled(true); await start(s.port);
    expect(fixture.create).not.toHaveBeenCalled(); expect(sdk.createLocalAudioTrack).toHaveBeenCalledOnce(); expect(s.first.replay).not.toHaveBeenCalled(); await s.port.disconnect(); expect(physical.track.readyState).toBe('ended');
  });
  it('commit and interruption never restart the scripted waveform', async () => {
    const s = await setup(); await s.port.setMicrophoneEnabled(true); await start(s.port);
    s.room.localParticipant.performRpc.mockResolvedValueOnce('{"schema_version":1,"status":"turn_committed"}'); await s.port.performRpc('native-agent', 'business.commit_turn', payload);
    s.room.localParticipant.performRpc.mockResolvedValueOnce('{"schema_version":1,"status":"speech_interrupted"}'); await s.port.performRpc('native-agent', 'business.interrupt', payload);
    expect(s.first.replay).toHaveBeenCalledOnce(); await s.port.disconnect();
  });
});
