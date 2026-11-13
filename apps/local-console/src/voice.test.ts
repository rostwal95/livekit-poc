import { describe, expect, it, vi } from 'vitest';
import { ParticipantKind } from 'livekit-client';
import { parseTaskHint, parseTurnReply, parseVoiceSession, requestVoiceSession, VoiceController, NativeMicrophoneOwner, assertNativeMicrophonePermission, readObservedVoiceText, transcriptionRejectionReasons, nativeMediaReadyAttribute, nativeRpcResponseTimeout, readNativeVoiceText, voiceInferenceLabel } from './voice';
import type { VoiceMethod, VoiceRoomCallbacks, VoiceRoomPort, VoiceSessionRequest, SpeechState, VoiceInferenceMode } from './voice';
const TASK = '11111111-1111-4111-8111-111111111111', OTHER = '99999999-9999-4999-8999-999999999999';
const TOKEN = 'private-ui-test-operator-token', ID = '22222222-2222-4222-8222-222222222222';
const request: VoiceSessionRequest = { room: `business-${ID}`, identity: `browser-${ID}`, task_id: TASK, invocation_id: ID };
const session = () => ({ url: 'ws://127.0.0.1:7880', token: 'private-room-jwt', room: request.room, identity: request.identity, expires_in: 180, agent_name: 'local-business-agent', agent_dispatched: true, mode: 'scripted' });
function deferred<T>() { let resolve!: (value: T) => void, reject!: (error: unknown) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
function setup(initialSpeech: SpeechState = 'listening', initialIoReady = true, mode: VoiceInferenceMode = 'scripted') {
  const callbacks: VoiceRoomCallbacks[] = [], rooms: VoiceRoomPort[] = [];
  const fetcher = vi.fn<typeof fetch>(async (_url, init) => { const body = JSON.parse(String(init?.body)) as VoiceSessionRequest; return Response.json({ ...session(), mode, room: body.room, identity: body.identity }); });
  const observed = vi.fn<(id: string) => Promise<void>>(async () => undefined), changed = vi.fn();
  const factory = vi.fn((events: VoiceRoomCallbacks, _source: 'scripted' | 'microphone', expectedMode: VoiceInferenceMode = 'scripted'): VoiceRoomPort => {
    callbacks.push(events);
    const room = { connect: vi.fn(async () => { events.agent('native-agent'); events.sessionReady(initialIoReady, expectedMode); events.speech(initialSpeech); }), disconnect: vi.fn(async () => undefined), setMicrophoneEnabled: vi.fn(async (_enabled: boolean) => undefined), performRpc: vi.fn(async (_destination: string, method: VoiceMethod, _payload: string) => JSON.stringify({ schema_version: 1, status: method === 'business.start_turn' ? 'turn_started' : method === 'business.commit_turn' ? 'turn_committed' : 'speech_interrupted' })), sendText: vi.fn(async (_text: string) => undefined), startAudio: vi.fn(async () => undefined) };
    rooms.push(room); return room;
  });
  let roomNumber = 0; const roomId = vi.fn(() => `aaaaaaaa-aaaa-4aaa-8aaa-${(++roomNumber).toString(16).padStart(12, '0')}`);
  const controller = new VoiceController(factory, changed, observed, fetcher, roomId);
  const current = () => ({ events: callbacks.at(-1)!, room: rooms.at(-1)! });
  return { controller, fetcher, factory, callbacks, rooms, current, observed, changed, roomId };
}
const tick = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };

describe('scripted native session boundary', () => {
  it('binds native room, identity, scripted mode and exact agent dispatch', () => { expect(parseVoiceSession(session(), request).mode).toBe('scripted'); expect(Object.isFrozen(parseVoiceSession(session(), request))).toBe(true); });
  it.each([
    { ...session(), room: 'business-foreign' }, { ...session(), identity: 'browser-other' }, { ...session(), mode: 'inference' }, { ...session(), agent_name: 'local-diagnostic-agent' }, { ...session(), expires_in: 301 }, { ...session(), expires_in: 0 }, { ...session(), url: 'https://localhost' }, { ...session(), url: 'ws://user:secret@localhost' }, { ...session(), url: 'ws://localhost?token=secret' }, { ...session(), extra: 'unbounded' }, { ...session(), token: 'x'.repeat(8193) },
  ])('rejects unbound credentials or unsupported session metadata', (item) => { expect(() => parseVoiceSession(item, request)).toThrow(); });
  it('sends credentials only in a bounded same-origin session request header', async () => { const fetcher = vi.fn<typeof fetch>(async () => Response.json(session())); await requestVoiceSession(request, TOKEN, new AbortController().signal, fetcher); const [url, init] = fetcher.mock.calls[0]!; expect(url).toBe('/api/business/session'); expect(init).toMatchObject({ credentials: 'omit', cache: 'no-store', method: 'POST' }); expect(init?.headers).toEqual({ Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' }); expect(init?.body).not.toContain(TOKEN); });
  it('fails closed before fetching an invalid task or operator token', async () => { const fetcher = vi.fn<typeof fetch>(); await expect(requestVoiceSession({ ...request, task_id: 'not-a-task' }, TOKEN, new AbortController().signal, fetcher)).rejects.toThrow(); await expect(requestVoiceSession(request, 'short', new AbortController().signal, fetcher)).rejects.toThrow(); expect(fetcher).not.toHaveBeenCalled(); });
  it.each([401, 403])('classifies denied access without exposing server text', async (status) => { const fetcher = vi.fn<typeof fetch>(async () => new Response('private-server-secret', { status })); await expect(requestVoiceSession(request, TOKEN, new AbortController().signal, fetcher)).rejects.toMatchObject({ code: 'unauthorized' }); });
  it('bounds the grant response and hides transport/error bodies', async () => { const fetcher = vi.fn<typeof fetch>(async () => new Response('x'.repeat(20_000))); await expect(requestVoiceSession(request, TOKEN, new AbortController().signal, fetcher)).rejects.toMatchObject({ code: 'unavailable' }); });
  it.each([['business.start_turn', 'turn_started'], ['business.commit_turn', 'turn_committed'], ['business.commit_turn', 'no_audio'], ['business.interrupt', 'speech_interrupted']] as const)('accepts exact %s acknowledgement %s', (method, status) => { expect(parseTurnReply(JSON.stringify({ schema_version: 1, status }), method)).toBe(status); });
  it.each(['{"schema_version":1,"status":"interrupted"}', '{"schema_version":2,"status":"speech_interrupted"}', '{"schema_version":1,"status":"speech_interrupted","quote":"approve"}', '{"schema_version":1,"status":"speech_interrupted","status":"speech_interrupted"}', 'x'.repeat(129)])('rejects RPC observations that could invent acknowledgement', (value) => { expect(() => parseTurnReply(value, 'business.interrupt')).toThrow(); });
  it('accepts only bounded strict task hints without carrying business state', () => { const encode = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)); expect(parseTaskHint(encode({ schema_version: 1, task_id: TASK }))).toBe(TASK); for (const value of [{ schema_version: 1, task_id: TASK, state: 'succeeded' }, { schema_version: 2, task_id: TASK }, { schema_version: 1, task_id: 'bad' }]) expect(parseTaskHint(encode(value))).toBeNull(); expect(parseTaskHint(new Uint8Array([255]))).toBeNull(); expect(parseTaskHint(new Uint8Array(513))).toBeNull(); });
});

describe('voice controller lifecycle and independent business authority', () => {
  it('requires a current verified-task-shaped identity, never auto-enables microphone', async () => { const s = setup(); await s.controller.connect('missing', TOKEN); expect(s.fetcher).not.toHaveBeenCalled(); await s.controller.connect(TASK, TOKEN); expect(s.controller.state.connection).toBe('connected'); expect(s.controller.state.agent_id).toBe('native-agent'); expect(s.current().room.setMicrophoneEnabled).not.toHaveBeenCalled(); expect(JSON.stringify(s.controller.state)).not.toContain(TOKEN); });
  it('starts and commits manual audio input using exact bounded native RPCs', async () => { const s = setup(); await s.controller.connect(TASK, TOKEN); await s.controller.microphone(true); await s.controller.turn('start'); expect(s.controller.state.turn).toBe('capturing'); await s.controller.turn('commit'); expect(s.controller.state.turn).toBe('committed'); expect(s.current().room.performRpc).toHaveBeenNthCalledWith(1, 'native-agent', 'business.start_turn', '{"schema_version":1}'); expect(s.current().room.performRpc).toHaveBeenNthCalledWith(2, 'native-agent', 'business.commit_turn', '{"schema_version":1}'); });
  it('requires microphone for starting and capture for committing', async () => { const s = setup(); await s.controller.connect(TASK, TOKEN); await s.controller.turn('start'); await s.controller.turn('commit'); expect(s.current().room.performRpc).not.toHaveBeenCalled(); });
  it('keeps no-audio distinct from a committed turn', async () => { const s = setup(); await s.controller.connect(TASK, TOKEN); await s.controller.microphone(true); await s.controller.turn('start'); vi.mocked(s.current().room.performRpc).mockResolvedValueOnce('{"schema_version":1,"status":"no_audio"}'); await s.controller.turn('commit'); expect(s.controller.state.turn).toBe('idle'); expect(s.controller.state.message).toContain('No audio'); });
  it('keeps capture uncertainty visible if enable and cleanup acknowledgements both fail', async () => { const s = setup(); await s.controller.connect(TASK, TOKEN); vi.mocked(s.current().room.setMicrophoneEnabled).mockRejectedValue(new Error('capture unavailable')); await s.controller.microphone(true); expect(s.controller.state.microphone_uncertain).toBe(true); await s.controller.turn('start'); expect(s.current().room.performRpc).not.toHaveBeenCalled(); });
  it('does not hide uncertain cleanup as confirmed microphone shutdown', async () => { const s = setup(); await s.controller.connect(TASK, TOKEN); await s.controller.microphone(true); vi.mocked(s.current().room.disconnect).mockRejectedValueOnce(new Error('cleanup unavailable')); await s.controller.disconnect(); expect(s.controller.state.microphone_uncertain).toBe(true); expect(s.controller.state.message).toContain('cleanup could not be confirmed'); });
  it('uses native status text without any business mutation request', async () => { const s = setup(); await s.controller.connect(TASK, TOKEN); await s.controller.status(); expect(s.current().room.sendText).toHaveBeenCalledExactlyOnceWith('status'); expect(s.fetcher).toHaveBeenCalledTimes(1); expect(s.observed).not.toHaveBeenCalled(); });
  it('end and interrupt never submit cancellation, even when business work is accepted', async () => { const s = setup(); await s.controller.connect(TASK, TOKEN); await s.controller.interrupt(); expect(s.controller.state.turn).toBe('interrupted'); await s.controller.disconnect(); expect(s.fetcher).toHaveBeenCalledTimes(1); expect(s.current().room.disconnect).toHaveBeenCalledTimes(1); expect(s.controller.state.connection).toBe('disconnected'); });
  it('uses actual speech and playback observations independently', async () => { const s = setup(); await s.controller.connect(TASK, TOKEN); s.current().events.speech('speaking'); expect(s.controller.state.playback).toBe('unavailable'); s.current().events.playback('playing'); expect(s.controller.state.playback).toBe('playing'); s.current().events.speech('idle'); expect(s.controller.state.playback).toBe('playing'); });
  it('keeps a failed playback gesture blocked and permits explicit retry', async () => { const s = setup(); await s.controller.connect(TASK, TOKEN); vi.mocked(s.current().room.startAudio).mockRejectedValueOnce(new Error('private-device-error')); await s.controller.enablePlayback(); expect(s.controller.state.playback).toBe('blocked'); await s.controller.enablePlayback(); expect(s.current().room.startAudio).toHaveBeenCalledTimes(2); expect(s.controller.state.playback).toBe('blocked'); });
  it('uses a fresh media room and participant after End while preserving the durable task', async () => { const s = setup(); await s.controller.connect(TASK, TOKEN); await s.controller.disconnect(); await s.controller.connect(TASK, TOKEN); const bodies = s.fetcher.mock.calls.map(([, init]) => String(init?.body)); const first = JSON.parse(bodies[0]!) as VoiceSessionRequest, second = JSON.parse(bodies[1]!) as VoiceSessionRequest; expect(second.invocation_id).not.toBe(first.invocation_id); expect(second.room).not.toBe(first.room); expect(second.identity).not.toBe(first.identity); expect(second.task_id).toBe(first.task_id); });
  it('creates a fresh room request when the bound durable task changes', async () => { const s = setup(); await s.controller.connect(TASK, TOKEN); await s.controller.connect(OTHER, TOKEN); const next = JSON.parse(String(s.fetcher.mock.calls[1]![1]?.body)) as VoiceSessionRequest; expect(next.task_id).toBe(OTHER); expect(s.rooms[0]!.disconnect).toHaveBeenCalledTimes(1); });
  it('mutes an already-published microphone while agent is absent or media reconnects', async () => { const s = setup(); await s.controller.connect(TASK, TOKEN); await s.controller.microphone(true); s.current().events.agent(null); s.current().events.reconnecting(); await s.controller.microphone(false); expect(s.controller.state.microphone).toBe(false); expect(s.current().room.setMicrophoneEnabled).toHaveBeenLastCalledWith(false); await s.controller.microphone(true); expect(s.current().room.setMicrophoneEnabled).toHaveBeenCalledTimes(2); });
  it('closes a late room connect without allowing resurrection after end', async () => { const s = setup(), connecting = deferred<void>(); s.factory.mockImplementationOnce((events) => { s.callbacks.push(events); const room: VoiceRoomPort = { connect: vi.fn(() => connecting.promise), disconnect: vi.fn(async () => undefined), setMicrophoneEnabled: vi.fn(), performRpc: vi.fn(), sendText: vi.fn(), startAudio: vi.fn() }; s.rooms.push(room); return room; }); const join = s.controller.connect(TASK, TOKEN); await vi.waitFor(() => expect(s.factory).toHaveBeenCalledTimes(1)); await s.controller.disconnect(); connecting.resolve(); await join; s.current().events.agent('late-agent'); expect(s.controller.state.connection).toBe('disconnected'); expect(s.controller.state.agent_id).toBeNull(); expect(s.current().room.disconnect).toHaveBeenCalled(); });
  it('ignores a late HTTP grant after disconnection before creating a room', async () => { const s = setup(), grant = deferred<Response>(); s.fetcher.mockImplementationOnce(() => grant.promise); const join = s.controller.connect(TASK, TOKEN); await s.controller.disconnect(); grant.resolve(Response.json(session())); await join; expect(s.factory).not.toHaveBeenCalled(); expect(s.controller.state.connection).toBe('disconnected'); });
  it('cleans up a denied microphone and avoids leaking device exception text', async () => { const s = setup(); await s.controller.connect(TASK, TOKEN); vi.mocked(s.current().room.setMicrophoneEnabled).mockRejectedValueOnce(new DOMException('private-device-secret', 'NotAllowedError')); await s.controller.microphone(true); expect(s.controller.state.microphone).toBe(false); expect(s.current().room.setMicrophoneEnabled).toHaveBeenLastCalledWith(false); expect(s.controller.state.message).not.toContain('private-device-secret'); });
  it('mutes a late microphone grant after the voice session has ended', async () => { const s = setup(), grant = deferred<void>(); await s.controller.connect(TASK, TOKEN); vi.mocked(s.current().room.setMicrophoneEnabled).mockImplementationOnce(() => grant.promise); const enable = s.controller.microphone(true); await s.controller.disconnect(); grant.resolve(); await enable; expect(s.current().room.setMicrophoneEnabled).toHaveBeenLastCalledWith(false); expect(s.controller.state.microphone).toBe(false); });
  it('preserves active audio capture across speech-only interruption and still commits it', async () => {
    const s = setup(); await s.controller.connect(TASK, TOKEN); await s.controller.microphone(true); await s.controller.turn('start');
    await s.controller.interrupt(); expect(s.controller.state.turn).toBe('capturing');
    await s.controller.turn('start'); expect(s.current().room.performRpc).toHaveBeenCalledTimes(2);
    await s.controller.turn('commit'); expect(s.controller.state.turn).toBe('committed'); expect(s.current().room.performRpc).toHaveBeenLastCalledWith('native-agent', 'business.commit_turn', '{"schema_version":1}');
  });
  it.each(['before', 'after'] as const)('accepts pending start acknowledgement %s the speech interrupt acknowledgement', async (order) => {
    const s = setup(), starting = deferred<string>(), interruption = deferred<string>(); await s.controller.connect(TASK, TOKEN); await s.controller.microphone(true);
    vi.mocked(s.current().room.performRpc).mockImplementationOnce(() => starting.promise).mockImplementationOnce(() => interruption.promise);
    const start = s.controller.turn('start'), interrupt = s.controller.interrupt(); expect(s.controller.state.turn).toBe('starting');
    if (order === 'before') { starting.resolve('{"schema_version":1,"status":"turn_started"}'); await start; expect(s.controller.state.turn).toBe('capturing'); }
    else { interruption.resolve('{"schema_version":1,"status":"speech_interrupted"}'); await interrupt; expect(s.controller.state.turn).toBe('starting'); expect(s.controller.state.rpc_busy).toBe(true); await s.controller.turn('start'); expect(s.current().room.performRpc).toHaveBeenCalledTimes(2); }
    starting.resolve('{"schema_version":1,"status":"turn_started"}'); interruption.resolve('{"schema_version":1,"status":"speech_interrupted"}'); await Promise.all([start, interrupt]);
    expect(s.controller.state.turn).toBe('capturing'); expect(s.controller.state.rpc_busy).toBe(false); await s.controller.turn('commit'); expect(s.controller.state.turn).toBe('committed');
  });
  it.each(['turn_committed', 'no_audio'] as const)('preserves the pending commit result %s across speech-only interruption', async (status) => {
    const s = setup(), committed = deferred<string>(); await s.controller.connect(TASK, TOKEN); await s.controller.microphone(true); await s.controller.turn('start');
    vi.mocked(s.current().room.performRpc).mockImplementationOnce(() => committed.promise); const commit = s.controller.turn('commit'); await s.controller.interrupt(); expect(s.controller.state.turn).toBe('committing'); expect(s.controller.state.rpc_busy).toBe(true);
    committed.resolve(JSON.stringify({ schema_version: 1, status })); await commit; expect(s.controller.state.turn).toBe(status === 'no_audio' ? 'idle' : 'committed'); expect(s.controller.state.rpc_busy).toBe(false);
  });
  it('does not turn a speech-only acknowledgement failure into lost audio capture', async () => {
    const s = setup(); await s.controller.connect(TASK, TOKEN); await s.controller.microphone(true); await s.controller.turn('start'); vi.mocked(s.current().room.performRpc).mockRejectedValueOnce(new Error('lost interrupt reply'));
    await s.controller.interrupt(); expect(s.controller.state.turn).toBe('capturing'); expect(s.controller.state.message).toContain('acknowledgement is unknown'); await s.controller.turn('commit'); expect(s.controller.state.turn).toBe('committed');
  });
  it('does not claim RPC failure when acknowledgement is lost', async () => { const s = setup(); await s.controller.connect(TASK, TOKEN); vi.mocked(s.current().room.performRpc).mockRejectedValueOnce(new Error('private-rpc-secret')); await s.controller.interrupt(); expect(s.controller.state.turn).toBe('unknown'); expect(s.controller.state.message).not.toContain('private-rpc-secret'); });
  it('fences a stale turn reply when the selected agent leaves', async () => { const s = setup(), reply = deferred<string>(); await s.controller.connect(TASK, TOKEN); await s.controller.microphone(true); vi.mocked(s.current().room.performRpc).mockImplementationOnce(() => reply.promise); const start = s.controller.turn('start'); s.current().events.agent(null); reply.resolve('{"schema_version":1,"status":"turn_started"}'); await start; expect(s.controller.state.turn).toBe('unknown'); expect(s.controller.state.agent_id).toBeNull(); });
  it('bounds hint refreshes and accepts only the room-bound current task', async () => { const s = setup(), refreshed = deferred<void>(); await s.controller.connect(TASK, TOKEN); s.observed.mockImplementationOnce(() => refreshed.promise); s.current().events.taskHint(OTHER); for (let n = 0; n < 1000; n += 1) s.current().events.taskHint(TASK); await tick(); expect(s.observed).toHaveBeenCalledExactlyOnceWith(TASK); refreshed.resolve(); await tick(); });
  it('contains scoped-refresh and rendering exceptions without inventing case state', async () => { const s = setup(); s.changed.mockImplementation(() => { throw new Error('render'); }); s.observed.mockRejectedValueOnce(new Error('scope unavailable')); await s.controller.connect(TASK, TOKEN); s.current().events.taskHint(TASK); await tick(); expect(s.controller.state.connection).toBe('connected'); expect(s.controller.state.message).toContain('could not yet be refreshed'); });
  it('bounds transcripts to 40 entries and rejects oversize UTF-8', async () => { const s = setup(); await s.controller.connect(TASK, TOKEN); for (let n = 0; n < 1000; n += 1) s.current().events.text(`line ${n}`); s.current().events.text('😀'.repeat(5000)); expect(s.controller.state.entries).toHaveLength(40); expect(s.controller.state.entries[0]).toBe('line 960'); expect(Object.isFrozen(s.controller.state.entries)).toBe(true); });
  it('bounds status and autoplay operations while unresolved', async () => { const s = setup(), status = deferred<void>(), audio = deferred<void>(); await s.controller.connect(TASK, TOKEN); vi.mocked(s.current().room.sendText).mockImplementationOnce(() => status.promise); vi.mocked(s.current().room.startAudio).mockImplementationOnce(() => audio.promise); const sent = s.controller.status(), started = s.controller.enablePlayback(); await s.controller.status(); await s.controller.enablePlayback(); expect(s.current().room.sendText).toHaveBeenCalledTimes(1); expect(s.current().room.startAudio).toHaveBeenCalledTimes(1); status.resolve(); audio.resolve(); await sent; await started; expect(s.controller.state.status_busy).toBe(false); });
  it('serializes duplicate disconnect cleanup and prevents use after disposal', async () => { const s = setup(), closing = deferred<void>(); await s.controller.connect(TASK, TOKEN); vi.mocked(s.current().room.disconnect).mockImplementationOnce(() => closing.promise); const end = s.controller.disconnect(), dispose = s.controller.dispose(); expect(s.current().room.disconnect).toHaveBeenCalledTimes(1); closing.resolve(); await end; await dispose; await s.controller.connect(TASK, TOKEN); expect(s.fetcher).toHaveBeenCalledTimes(1); expect(s.controller.state.connection).toBe('disconnected'); });
  it('preserves genuine unavailable state when grant API fails', async () => { const s = setup(); s.fetcher.mockRejectedValue(new Error('private-http-secret')); await s.controller.connect(TASK, TOKEN); expect(s.controller.state.connection).toBe('error'); expect(s.controller.state.turn).toBe('idle'); expect(s.controller.state.message).not.toContain('private-http-secret'); expect(s.factory).not.toHaveBeenCalled(); });
  it('classifies operator denial and does not create media resources', async () => { const s = setup(); s.fetcher.mockResolvedValueOnce(new Response('', { status: 403 })); await s.controller.connect(TASK, TOKEN); expect(s.controller.state.message).toContain('Operator access was denied'); expect(s.factory).not.toHaveBeenCalled(); });
  it('isolates late old-room callbacks after reconnecting', async () => { const s = setup(); await s.controller.connect(TASK, TOKEN); const old = s.current().events; await s.controller.disconnect(); await s.controller.connect(TASK, TOKEN); old.disconnected(); old.text('late'); old.playback('playing'); expect(s.controller.state.connection).toBe('connected'); expect(s.controller.state.entries).toEqual([]); expect(s.controller.state.playback).toBe('unavailable'); });
});


describe('bounded native microphone ownership', () => {
  it('reports unknown on no acknowledgement and retains one underlying capture reservation', async () => {
    vi.useFakeTimers();
    try { const capture = deferred<void>(), invoke = vi.fn((_enabled: boolean) => capture.promise), stop = vi.fn(), owner = new NativeMicrophoneOwner(invoke, stop);
      const result = owner.set(true); const rejected = expect(result).rejects.toMatchObject({ code: 'unknown' }); await vi.advanceTimersByTimeAsync(5000); await rejected;
      await expect(owner.set(true)).rejects.toMatchObject({ code: 'unknown' }); await expect(owner.set(false)).rejects.toMatchObject({ code: 'unknown' }); expect(invoke).toHaveBeenCalledTimes(1); expect(stop).toHaveBeenCalled(); owner.close();
    } finally { vi.useRealTimers(); }
  });
  it('stops and mutes late capture before releasing its reservation', async () => {
    vi.useFakeTimers();
    try { const capture = deferred<void>(), muted = deferred<void>(), invoke = vi.fn<(enabled: boolean) => Promise<void>>().mockImplementationOnce(() => capture.promise).mockImplementationOnce(() => muted.promise).mockResolvedValue(undefined), stop = vi.fn(), owner = new NativeMicrophoneOwner(invoke, stop);
      const result = owner.set(true); const rejected = expect(result).rejects.toMatchObject({ code: 'unknown' }); await vi.advanceTimersByTimeAsync(5000); await rejected;
      capture.resolve(); await tick(); expect(invoke).toHaveBeenNthCalledWith(2, false); expect(stop).toHaveBeenCalled(); await expect(owner.set(true)).rejects.toMatchObject({ code: 'unknown' });
      muted.resolve(); await tick(); await owner.set(true); expect(invoke).toHaveBeenNthCalledWith(3, true); owner.close();
    } finally { vi.useRealTimers(); }
  });
  it('cleans up a capture acknowledgement arriving after End and prohibits new capture', async () => {
    const capture = deferred<void>(), invoke = vi.fn<(enabled: boolean) => Promise<void>>().mockImplementationOnce(() => capture.promise).mockResolvedValue(undefined), stop = vi.fn(), owner = new NativeMicrophoneOwner(invoke, stop);
    const result = owner.set(true); await tick(); owner.close(); await expect(owner.set(true)).rejects.toMatchObject({ code: 'unknown' }); capture.resolve(); await result; expect(invoke).toHaveBeenLastCalledWith(false); expect(stop).toHaveBeenCalled();
  });
  it('does not begin capture after the owner has already closed', async () => {
    const invoke = vi.fn(async (_enabled: boolean) => undefined), owner = new NativeMicrophoneOwner(invoke, vi.fn()); owner.close(); const result = owner.set(true); await expect(result).rejects.toMatchObject({ code: 'unknown' }); expect(invoke).not.toHaveBeenCalled();
  });
  it('bounds an unacknowledged mute and keeps its uncertainty reserved', async () => {
    vi.useFakeTimers();
    try { const mute = deferred<void>(), invoke = vi.fn<(enabled: boolean) => Promise<void>>().mockResolvedValueOnce(undefined).mockImplementationOnce(() => mute.promise), stop = vi.fn(), owner = new NativeMicrophoneOwner(invoke, stop); await owner.set(true);
      const result = owner.set(false); const rejected = expect(result).rejects.toMatchObject({ code: 'unknown' }); await vi.advanceTimersByTimeAsync(5000); await rejected; expect(stop).toHaveBeenCalled(); await expect(owner.set(true)).rejects.toMatchObject({ code: 'unknown' }); expect(invoke).toHaveBeenCalledTimes(2); owner.close();
    } finally { vi.useRealTimers(); }
  });
  it('bounds End without falsely confirming cleanup when its adapter never acknowledges', async () => {
    vi.useFakeTimers();
    try { const s = setup(), closed = deferred<void>(); await s.controller.connect(TASK, TOKEN); vi.mocked(s.current().room.disconnect).mockImplementationOnce(() => closed.promise); const ending = s.controller.disconnect(); await vi.advanceTimersByTimeAsync(5000); await ending; expect(s.controller.state.connection).toBe('disconnected'); expect(s.controller.state.microphone_uncertain).toBe(true); expect(s.controller.state.message).toContain('cleanup could not be confirmed'); closed.resolve();
    } finally { vi.useRealTimers(); }
  });
});


describe('actual browser microphone permission boundary', () => {
  it('rejects an actual denied permission state before starting native capture', async () => {
    const query = vi.fn<Permissions['query']>(async () => ({ state: 'denied' }) as PermissionStatus), capture = vi.fn(async () => undefined);
    const owner = new NativeMicrophoneOwner(async (enabled) => { if (enabled) await assertNativeMicrophonePermission({ query }); await capture(); }, vi.fn());
    await expect(owner.set(true)).rejects.toMatchObject({ code: 'permission' }); expect(capture).not.toHaveBeenCalled(); expect(query).toHaveBeenCalledWith({ name: 'microphone' }); owner.close();
  });
  it.each(['granted', 'prompt'] as const)('lets actual capture decide the %s state', async (state) => { await expect(assertNativeMicrophonePermission({ query: vi.fn(async () => ({ state }) as PermissionStatus) })).resolves.toBeUndefined(); });
  it('preserves unknown when the permission query is unsupported instead of inventing denial', async () => { await expect(assertNativeMicrophonePermission(undefined)).resolves.toBeUndefined(); await expect(assertNativeMicrophonePermission({ query: vi.fn(async () => { throw new TypeError('unsupported permission'); }) })).resolves.toBeUndefined(); });
});


describe('unresolved media ownership across reconnect', () => {
  it('blocks new rooms after End until the prior real native cleanup settles', async () => {
    vi.useFakeTimers();
    try { const s = setup(), actualCleanup = deferred<void>(); await s.controller.connect(TASK, TOKEN); const room = s.current().room; room.whenClosed = () => actualCleanup.promise; vi.mocked(room.disconnect).mockImplementationOnce(() => actualCleanup.promise);
      const end = s.controller.disconnect(); await vi.advanceTimersByTimeAsync(5000); await end; expect(s.controller.state.microphone_uncertain).toBe(true);
      await s.controller.connect(TASK, TOKEN); await s.controller.connect(OTHER, TOKEN); expect(s.fetcher).toHaveBeenCalledTimes(1); expect(s.controller.state.message).toContain('cleanup is unresolved');
      actualCleanup.resolve(); await tick(); expect(s.controller.state.microphone_uncertain).toBe(false); await s.controller.connect(TASK, TOKEN); expect(s.fetcher).toHaveBeenCalledTimes(2);
    } finally { vi.useRealTimers(); }
  });
  it('keeps a rejected real cleanup blocked until the page is reloaded', async () => {
    const s = setup(), actualCleanup = deferred<void>(); await s.controller.connect(TASK, TOKEN); const room = s.current().room; room.whenClosed = () => actualCleanup.promise; vi.mocked(room.disconnect).mockImplementationOnce(() => actualCleanup.promise);
    const end = s.controller.disconnect(); actualCleanup.reject(new Error('cleanup unavailable')); await end; await s.controller.connect(TASK, TOKEN); expect(s.fetcher).toHaveBeenCalledTimes(1); expect(s.controller.state.microphone_uncertain).toBe(true);
  });
});


describe('explicit local audio input source', () => {
  it('defaults to scripted input and passes the selected source to the native adapter', async () => { const s = setup(); await s.controller.connect(TASK, TOKEN); expect(s.controller.state.input_source).toBe('scripted'); expect(s.factory.mock.calls[0]?.[1]).toBe('scripted'); });
  it('allows physical microphone only as an explicit source choice', async () => { const s = setup(); await s.controller.connect(TASK, TOKEN, 'microphone'); expect(s.controller.state.input_source).toBe('microphone'); expect(s.factory.mock.calls[0]?.[1]).toBe('microphone'); expect(s.current().room.setMicrophoneEnabled).not.toHaveBeenCalled(); });
  it('starts source acquisition synchronously inside the explicit publication action', async () => { const invoke = vi.fn(async (_enabled: boolean) => undefined), owner = new NativeMicrophoneOwner(invoke, vi.fn()); const published = owner.set(true); expect(invoke).toHaveBeenCalledExactlyOnceWith(true); await published; owner.close(); });
});


describe('unexpected native disconnect source ownership', () => {
  it('retains pending cleanup when native disconnection arrives without an End action', async () => {
    const s = setup(), actualCleanup = deferred<void>(); await s.controller.connect(TASK, TOKEN); s.current().room.whenClosed = () => actualCleanup.promise; s.current().events.disconnected();
    expect(s.controller.state.microphone_uncertain).toBe(true); await s.controller.connect(TASK, TOKEN); expect(s.fetcher).toHaveBeenCalledTimes(1); actualCleanup.resolve(); await tick(); expect(s.controller.state.microphone_uncertain).toBe(false); await s.controller.connect(TASK, TOKEN); expect(s.fetcher).toHaveBeenCalledTimes(2);
  });
});


describe('fresh native room observations', () => {
  it('clears prior room transcripts so stale output cannot qualify a reconnected consumer', async () => {
    const s = setup(); await s.controller.connect(TASK, TOKEN); s.current().events.text('The workflow panel shows the latest durable state.'); expect(s.controller.state.entries).toHaveLength(1);
    await s.controller.disconnect(); await s.controller.connect(TASK, TOKEN); expect(s.controller.state.entries).toEqual([]); await s.controller.status(); expect(s.controller.state.entries).toEqual([]);
    s.current().events.text('The workflow panel shows the latest durable state.'); expect(s.controller.state.entries).toHaveLength(1);
  });
});


describe('frozen native media invocation intent', () => {
  it('retries an unknown initial mint with the original invocation ID and exact request body', async () => {
    const s = setup(); for (let attempt = 0; attempt < 3; attempt += 1) s.fetcher.mockRejectedValueOnce(new Error('mint acknowledgement lost')); await s.controller.connect(TASK, TOKEN); const first = String(s.fetcher.mock.calls[0]?.[1]?.body); expect((JSON.parse(first) as VoiceSessionRequest).invocation_id).toMatch(/^[0-9a-f-]{36}$/);
    await s.controller.connect(TASK, TOKEN); expect(s.fetcher).toHaveBeenCalledTimes(4); expect(String(s.fetcher.mock.calls[3]?.[1]?.body)).toBe(first);
  });
  it('freezes a fresh media context after End and retries that exact context', async () => {
    const s = setup(); await s.controller.connect(TASK, TOKEN); await s.controller.disconnect(); for (let attempt = 0; attempt < 3; attempt += 1) s.fetcher.mockRejectedValueOnce(new Error('restart acknowledgement lost')); await s.controller.connect(TASK, TOKEN); const restart = String(s.fetcher.mock.calls[1]?.[1]?.body); const original = JSON.parse(String(s.fetcher.mock.calls[0]?.[1]?.body)) as VoiceSessionRequest; const restarted = JSON.parse(restart) as VoiceSessionRequest; expect(restarted.invocation_id).not.toBe(original.invocation_id); expect(restarted.room).not.toBe(original.room); expect(restarted.identity).not.toBe(original.identity); expect(restarted.task_id).toBe(original.task_id);
    await s.controller.connect(TASK, TOKEN); expect(s.fetcher).toHaveBeenCalledTimes(5); expect(String(s.fetcher.mock.calls[4]?.[1]?.body)).toBe(restart);
  });
  it('requests a fresh media context after native disconnection while preserving the durable task', async () => {
    const s = setup(); await s.controller.connect(TASK, TOKEN); const first = JSON.parse(String(s.fetcher.mock.calls[0]?.[1]?.body)) as VoiceSessionRequest; s.current().events.disconnected(); await tick(); await s.controller.connect(TASK, TOKEN); const next = JSON.parse(String(s.fetcher.mock.calls[1]?.[1]?.body)) as VoiceSessionRequest; expect(next.invocation_id).not.toBe(first.invocation_id); expect(next.room).not.toBe(first.room); expect(next.identity).not.toBe(first.identity); expect(next.task_id).toBe(first.task_id);
  });
});


describe('native connection acknowledgement uncertainty', () => {
  it('retains the invocation when initial room connection fails before a confirmed session', async () => {
    const s = setup(); s.factory.mockImplementationOnce((events) => {
      s.callbacks.push(events); const room: VoiceRoomPort = { connect: vi.fn(async () => { events.disconnected(); throw new Error('connection outcome unknown'); }), disconnect: vi.fn(async () => undefined), setMicrophoneEnabled: vi.fn(), performRpc: vi.fn(), sendText: vi.fn(), startAudio: vi.fn() }; s.rooms.push(room); return room;
    });
    await s.controller.connect(TASK, TOKEN); await tick(); const first = String(s.fetcher.mock.calls[0]?.[1]?.body); await s.controller.connect(TASK, TOKEN); expect(String(s.fetcher.mock.calls[1]?.[1]?.body)).toBe(first);
  });
  it('rejects a noncanonical invocation before any credential-bearing request', async () => {
    const fetcher = vi.fn<typeof fetch>(); await expect(requestVoiceSession({ ...request, invocation_id: 'not-an-invocation' }, TOKEN, new AbortController().signal, fetcher)).rejects.toThrow(); expect(fetcher).not.toHaveBeenCalled();
  });
});


describe('bounded native session mint reconciliation', () => {
  it.each([503, 504])('retries HTTP %s with the identical invocation/body and creates only one actual room', async (status) => {
    const s = setup(), cancel = vi.fn(async () => undefined); s.fetcher.mockResolvedValueOnce(new Response(new ReadableStream({ cancel }), { status })); await s.controller.connect(TASK, TOKEN);
    expect(s.fetcher).toHaveBeenCalledTimes(2); expect(s.fetcher.mock.calls[1]?.[1]?.body).toBe(s.fetcher.mock.calls[0]?.[1]?.body); expect(cancel).toHaveBeenCalledTimes(1); expect(s.factory).toHaveBeenCalledTimes(1); expect(s.controller.state.connection).toBe('connected');
  });
  it('retries a network-unknown mint with the same request and creates only one room', async () => {
    const s = setup(); s.fetcher.mockRejectedValueOnce(new TypeError('network outcome unknown')); await s.controller.connect(TASK, TOKEN); expect(s.fetcher).toHaveBeenCalledTimes(2); expect(s.fetcher.mock.calls[1]?.[1]?.body).toBe(s.fetcher.mock.calls[0]?.[1]?.body); expect(s.factory).toHaveBeenCalledTimes(1);
  });
  it('exhausts three attempts and retains the frozen request for an explicit retry', async () => {
    const s = setup(); for (let attempt = 0; attempt < 3; attempt += 1) s.fetcher.mockResolvedValueOnce(new Response('not ready', { status: 503 })); await s.controller.connect(TASK, TOKEN);
    expect(s.fetcher).toHaveBeenCalledTimes(3); expect(s.factory).not.toHaveBeenCalled(); expect(s.controller.state.connection).toBe('error'); const first = s.fetcher.mock.calls[0]?.[1]?.body;
    await s.controller.connect(TASK, TOKEN); expect(s.fetcher).toHaveBeenCalledTimes(4); for (const call of s.fetcher.mock.calls) expect(call[1]?.body).toBe(first); expect(s.factory).toHaveBeenCalledTimes(1);
  });
  it('does not retry any 4xx response or create a room', async () => {
    for (const status of [400, 401, 403, 404, 409, 422, 429]) { const s = setup(); s.fetcher.mockResolvedValueOnce(new Response('rejected', { status })); await s.controller.connect(TASK, TOKEN); expect(s.fetcher).toHaveBeenCalledTimes(1); expect(s.factory).not.toHaveBeenCalled(); }
  });
  it('aborts during retry delay without another HTTP request or room selection', async () => {
    vi.useFakeTimers();
    try { const s = setup(); s.fetcher.mockResolvedValueOnce(new Response('cold start', { status: 503 })); const connect = s.controller.connect(TASK, TOKEN); await vi.advanceTimersByTimeAsync(0); expect(s.fetcher).toHaveBeenCalledTimes(1); await s.controller.disconnect(); await vi.advanceTimersByTimeAsync(100); await connect; expect(s.fetcher).toHaveBeenCalledTimes(1); expect(s.factory).not.toHaveBeenCalled(); expect(s.controller.state.connection).toBe('disconnected'); }
    finally { vi.useRealTimers(); }
  });
  it('serializes the binding once so caller mutation cannot change a retried invocation', async () => {
    const candidate = { ...request }, fetcher = vi.fn<typeof fetch>(async (_url, init) => { if (fetcher.mock.calls.length === 1) { candidate.invocation_id = OTHER; return new Response('cold start', { status: 503 }); } const body = JSON.parse(String(init?.body)) as VoiceSessionRequest; return Response.json({ ...session(), room: body.room, identity: body.identity }); });
    await requestVoiceSession(candidate, TOKEN, new AbortController().signal, fetcher); expect(fetcher.mock.calls[1]?.[1]?.body).toBe(fetcher.mock.calls[0]?.[1]?.body); expect(String(fetcher.mock.calls[1]?.[1]?.body)).toContain(ID);
  });
});


describe('fresh media rooms after confirmed conversation end', () => {
  it('does not create the next context until unresolved cleanup actually completes', async () => {
    vi.useFakeTimers();
    try { const s = setup(), closed = deferred<void>(); await s.controller.connect(TASK, TOKEN); const room = s.current().room; room.whenClosed = () => closed.promise; vi.mocked(room.disconnect).mockImplementationOnce(() => closed.promise);
      const end = s.controller.disconnect(); await vi.advanceTimersByTimeAsync(5000); await end; expect(s.roomId).toHaveBeenCalledTimes(1); await s.controller.connect(TASK, TOKEN); expect(s.roomId).toHaveBeenCalledTimes(1);
      closed.resolve(); await tick(); expect(s.roomId).toHaveBeenCalledTimes(1); await s.controller.connect(TASK, TOKEN); expect(s.roomId).toHaveBeenCalledTimes(2); const bodies = s.fetcher.mock.calls.map((call) => JSON.parse(String(call[1]?.body)) as VoiceSessionRequest); expect(bodies[1]?.room).not.toBe(bodies[0]?.room); expect(bodies[1]?.task_id).toBe(bodies[0]?.task_id);
    } finally { vi.useRealTimers(); }
  });
  it('keeps automatic native transport reconnection inside the exact current context', async () => {
    const s = setup(); await s.controller.connect(TASK, TOKEN); s.current().events.reconnecting(); s.current().events.reconnected(); expect(s.controller.state.connection).toBe('connected'); expect(s.fetcher).toHaveBeenCalledTimes(1); expect(s.roomId).toHaveBeenCalledTimes(1); expect(s.factory).toHaveBeenCalledTimes(1);
  });
});


describe('repeated End while prior capture cleanup is unresolved', () => {
  it('does not turn an unconfirmed source off merely because Forget is called again', async () => {
    vi.useFakeTimers();
    try { const s = setup(), closed = deferred<void>(); await s.controller.connect(TASK, TOKEN); const room = s.current().room; room.whenClosed = () => closed.promise; vi.mocked(room.disconnect).mockImplementationOnce(() => closed.promise); const ending = s.controller.disconnect(); await vi.advanceTimersByTimeAsync(5000); await ending;
      s.controller.forget(); await tick(); expect(s.controller.state.microphone_uncertain).toBe(true); expect(s.controller.state.message).toContain('cleanup remains unresolved'); await s.controller.connect(TASK, TOKEN); expect(s.roomId).toHaveBeenCalledTimes(1);
      closed.resolve(); await tick(); expect(s.controller.state.microphone_uncertain).toBe(false);
    } finally { vi.useRealTimers(); }
  });
});


describe('observed native AgentSession readiness', () => {
  it.each(['initializing', 'unknown'] as const)('blocks publication, input RPC and status while the selected agent is %s', async (initial) => {
    const s = setup(initial); await s.controller.connect(TASK, TOKEN); expect(s.controller.state.connection).toBe('connected'); expect(s.controller.state.agent_id).toBe('native-agent');
    await s.controller.microphone(true); await s.controller.turn('start'); await s.controller.turn('commit'); await s.controller.interrupt(); await s.controller.status(); expect(s.current().room.setMicrophoneEnabled).not.toHaveBeenCalled(); expect(s.current().room.performRpc).not.toHaveBeenCalled(); expect(s.current().room.sendText).not.toHaveBeenCalled();
    s.current().events.speech('listening'); await s.controller.status(); expect(s.current().room.sendText).toHaveBeenCalledExactlyOnceWith('status'); await s.controller.microphone(true); await s.controller.turn('start'); expect(s.current().room.performRpc).toHaveBeenCalledExactlyOnceWith('native-agent', 'business.start_turn', '{"schema_version":1}');
  });
  it('does not let a replacement agent inherit the previous selected agent readiness', async () => {
    const s = setup(); await s.controller.connect(TASK, TOKEN); s.current().events.agent('new-native-agent'); expect(s.controller.state.speech).toBe('unknown'); await s.controller.status(); expect(s.current().room.sendText).not.toHaveBeenCalled(); s.current().events.speech('idle'); await s.controller.status(); expect(s.current().room.sendText).not.toHaveBeenCalled(); s.current().events.sessionReady(true); await s.controller.status(); expect(s.current().room.sendText).toHaveBeenCalledExactlyOnceWith('status');
  });
  it('keeps mute and End available when a formerly ready agent becomes unready', async () => {
    const s = setup(); await s.controller.connect(TASK, TOKEN); await s.controller.microphone(true); s.current().events.speech('initializing'); await s.controller.microphone(false); expect(s.current().room.setMicrophoneEnabled).toHaveBeenLastCalledWith(false); await s.controller.status(); expect(s.current().room.sendText).not.toHaveBeenCalled(); await s.controller.disconnect(); expect(s.controller.state.connection).toBe('disconnected'); expect(s.current().room.disconnect).toHaveBeenCalledTimes(1);
  });
});


describe('safe page transcription transport counters', () => {
  it('separates received/rejected/read-completed transport from accepted displayed text', async () => {
    const s = setup(); await s.controller.connect(TASK, TOKEN); const events = s.current().events; events.diagnostic('streams_received'); events.diagnostic('sender_rejected'); events.diagnostic('read_completed'); events.diagnostic('completed_bytes', 12); events.text('actual output');
    expect(s.controller.state.text_diagnostics).toMatchObject({ streams_received: 1, sender_rejected: 1, read_completed: 1, completed_bytes: 12, callback_accepted: 1 }); expect(s.controller.state.entries).toEqual(['actual output']); expect(Object.isFrozen(s.controller.state.text_diagnostics)).toBe(true);
  });
  it('counts rejected or stale callbacks without exposing their text or changing current authority', async () => {
    const s = setup(); await s.controller.connect(TASK, TOKEN); const old = s.current().events; old.text(''); old.text('x'.repeat(16_385)); expect(s.controller.state.text_diagnostics.callback_rejected).toBe(2); await s.controller.disconnect(); await s.controller.connect(TASK, TOKEN); old.text('stale room output'); expect(s.controller.state.text_diagnostics.callback_stale).toBe(1); expect(s.controller.state.entries).toEqual([]); expect(s.controller.state.connection).toBe('connected');
  });
  it('ignores out-of-bound counter increments instead of accepting arbitrary diagnostic data', async () => {
    const s = setup(); await s.controller.connect(TASK, TOKEN); const events = s.current().events; events.diagnostic('completed_bytes', -1); events.diagnostic('completed_bytes', Number.MAX_SAFE_INTEGER); events.diagnostic('completed_bytes', Number.NaN); expect(s.controller.state.text_diagnostics.completed_bytes).toBe(0); expect(s.controller.state.entries).toEqual([]);
  });
});


describe('actual bounded transcription chunk observations', () => {
  it('counts UTF-8 chunks before EOF while preserving the received text', async () => {
    const observed = vi.fn(), completed = deferred<void>(); async function* stream() { yield 'a'; yield '😀'; await completed.promise; }
    const reading = readObservedVoiceText(stream(), observed); await vi.waitFor(() => expect(observed).toHaveBeenCalledTimes(2)); expect(observed.mock.calls.flat()).toEqual([1, 4]); completed.resolve(); await expect(reading).resolves.toBe('a😀');
  });
  it('closes an oversized reader and caps observed bytes at the existing stream budget', async () => {
    let closed = false; const observed = vi.fn(); async function* stream() { try { yield 'x'.repeat(16_385); } finally { closed = true; } }
    await expect(readObservedVoiceText(stream(), observed)).rejects.toThrow(); expect(observed).toHaveBeenCalledExactlyOnceWith(16_384); expect(closed).toBe(true);
  });
});


describe('profile-specific native transcription stream ownership', () => {
  function pendingReader() {
    let finish = () => {}, closed = false;
    const reader = { withAbortSignal(signal: AbortSignal): AsyncIterable<string> { return (async function* () {
      try {
        if (signal.aborted) throw signal.reason;
        yield 'first';
        await new Promise<void>((resolve, reject) => {
          const remove = () => signal.removeEventListener('abort', abort);
          const abort = () => { remove(); reject(signal.reason); };
          finish = () => { remove(); resolve(); };
          signal.addEventListener('abort', abort, { once: true });
          if (signal.aborted) abort();
        });
        yield ' final';
      } finally { closed = true; }
    })(); } };
    return { reader, finish: () => finish(), closed: () => closed };
  }
  it('allows a legitimate 20-second real utterance, then releases its deadline after EOF', async () => {
    vi.useFakeTimers();
    try {
      const p = pendingReader(), observed = vi.fn(), ended = vi.fn();
      const reading = readNativeVoiceText(p.reader, new AbortController().signal, observed, 'local_real'); void reading.then(ended);
      await tick(); await vi.advanceTimersByTimeAsync(20_000); expect(ended).not.toHaveBeenCalled(); expect(observed).toHaveBeenCalledExactlyOnceWith(5);
      p.finish(); await expect(reading).resolves.toBe('first final'); expect(p.closed()).toBe(true); expect(vi.getTimerCount()).toBe(0);
    } finally { vi.useRealTimers(); }
  });
  it.each([['scripted', 10_000], ['local_real', 40_000], ['provider_real', 40_000]] as const)('enforces the finite %s whole-stream deadline', async (mode, seconds) => {
    vi.useFakeTimers();
    try {
      const p = pendingReader(), reading = readNativeVoiceText(p.reader, new AbortController().signal, vi.fn(), mode);
      const rejected = expect(reading).rejects.toMatchObject({ name: 'TimeoutError' });
      await tick(); await vi.advanceTimersByTimeAsync(seconds - 1); expect(p.closed()).toBe(false);
      await vi.advanceTimersByTimeAsync(1); await rejected; expect(p.closed()).toBe(true); expect(vi.getTimerCount()).toBe(0);
    } finally { vi.useRealTimers(); }
  });
  it.each(['scripted', 'local_real', 'provider_real'] as const)('aborts a %s reader immediately when its room lifetime ends', async (mode) => {
    vi.useFakeTimers();
    try {
      const p = pendingReader(), lifetime = new AbortController(), reading = readNativeVoiceText(p.reader, lifetime.signal, vi.fn(), mode);
      const rejected = expect(reading).rejects.toMatchObject({ name: 'AbortError' }); await tick(); lifetime.abort(); await rejected;
      expect(p.closed()).toBe(true); expect(vi.getTimerCount()).toBe(0);
    } finally { vi.useRealTimers(); }
  });
  it('preserves the byte cap for a real reader and releases its deadline on rejection', async () => {
    vi.useFakeTimers();
    try {
      let closed = false;
      const reader = { withAbortSignal(_signal: AbortSignal): AsyncIterable<string> { return (async function* () { try { yield 'x'.repeat(16_385); } finally { closed = true; } })(); } };
      const observed = vi.fn(); await expect(readNativeVoiceText(reader, new AbortController().signal, observed, 'local_real')).rejects.toThrow();
      expect(closed).toBe(true); expect(observed).toHaveBeenCalledExactlyOnceWith(16_384); expect(vi.getTimerCount()).toBe(0);
    } finally { vi.useRealTimers(); }
  });
});


describe('numeric transcription sender rejection reasons', () => {
  it('distinguishes a represented local user transcript without exposing identities', () => {
    expect(transcriptionRejectionReasons(false, undefined, 'selected-agent', 'local-browser', 'local-browser')).toEqual(['sender_rejected_missing', 'sender_rejected_identity_mismatch', 'sender_rejected_local']);
  });
  it('distinguishes closure, absent selection and a known non-agent sender', () => {
    expect(transcriptionRejectionReasons(true, { identity: 'peer', kind: ParticipantKind.STANDARD }, null, 'peer', 'local-browser')).toEqual(['sender_rejected_closed', 'sender_rejected_non_agent', 'sender_rejected_no_selection']);
  });
  it('does not label the selected native agent as rejected', () => {
    expect(transcriptionRejectionReasons(false, { identity: 'selected-agent', kind: ParticipantKind.AGENT }, 'selected-agent', 'selected-agent', 'local-browser')).toEqual([]);
  });
});


describe('ownership after initial connection cleanup times out', () => {
  it('retains the actual cleanup barrier and permits exact-invocation retry only after it settles', async () => {
    vi.useFakeTimers();
    try { const s = setup(), actualClosed = deferred<void>(); s.factory.mockImplementationOnce((): VoiceRoomPort => ({ connect: vi.fn(async () => { throw new Error('connection failed'); }), disconnect: vi.fn(() => actualClosed.promise), whenClosed: () => actualClosed.promise, setMicrophoneEnabled: vi.fn(), performRpc: vi.fn(), sendText: vi.fn(), startAudio: vi.fn() }));
      const connecting = s.controller.connect(TASK, TOKEN); await vi.advanceTimersByTimeAsync(5000); await connecting; expect(s.controller.state.connection).toBe('error'); expect(s.controller.state.microphone_uncertain).toBe(true); const original = s.fetcher.mock.calls[0]?.[1]?.body;
      await s.controller.connect(TASK, TOKEN); expect(s.factory).toHaveBeenCalledTimes(1); expect(s.fetcher).toHaveBeenCalledTimes(1); actualClosed.resolve(); await tick(); expect(s.controller.state.microphone_uncertain).toBe(false);
      await s.controller.connect(TASK, TOKEN); expect(s.controller.state.connection).toBe('connected'); expect(s.factory).toHaveBeenCalledTimes(2); expect(s.fetcher.mock.calls[1]?.[1]?.body).toBe(original); expect(s.roomId).toHaveBeenCalledTimes(1);
    } finally { vi.useRealTimers(); }
  });
});


describe('public actual RoomIO subscription readiness', () => {
  it('keeps a present Listening agent unusable until the producer reports actual I/O readiness', async () => {
    const s = setup('listening', false); await s.controller.connect(TASK, TOKEN); expect(s.controller.state.speech).toBe('listening'); expect(s.controller.state.session_ready).toBe(false);
    await s.controller.microphone(true); await s.controller.status(); await s.controller.turn('start'); await s.controller.interrupt(); expect(s.current().room.setMicrophoneEnabled).not.toHaveBeenCalled(); expect(s.current().room.sendText).not.toHaveBeenCalled(); expect(s.current().room.performRpc).not.toHaveBeenCalled();
    s.current().events.sessionReady(true); await s.controller.status(); expect(s.current().room.sendText).toHaveBeenCalledExactlyOnceWith('status'); await s.controller.microphone(true); await s.controller.turn('start'); expect(s.controller.state.turn).toBe('capturing');
  });
  it('resets I/O readiness on a new selected agent and after End', async () => {
    const s = setup(); await s.controller.connect(TASK, TOKEN); expect(s.controller.state.session_ready).toBe(true); s.current().events.agent('replacement-agent'); expect(s.controller.state.session_ready).toBe(false); s.current().events.speech('listening'); await s.controller.status(); expect(s.current().room.sendText).not.toHaveBeenCalled(); s.current().events.sessionReady(true); await s.controller.status(); expect(s.current().room.sendText).toHaveBeenCalledTimes(1); await s.controller.disconnect(); expect(s.controller.state.session_ready).toBe(false);
  });
  it('permits stopping published input and End when the observed I/O barrier is lost', async () => {
    const s = setup(); await s.controller.connect(TASK, TOKEN); await s.controller.microphone(true); s.current().events.sessionReady(false); await s.controller.status(); expect(s.current().room.sendText).not.toHaveBeenCalled(); await s.controller.microphone(false); expect(s.current().room.setMicrophoneEnabled).toHaveBeenLastCalledWith(false); await s.controller.disconnect(); expect(s.controller.state.connection).toBe('disconnected');
  });
  it.each([undefined, '', 'false', 'TRUE', 'true ', '1'])('does not infer readiness from public attribute %s', (value) => { expect(nativeMediaReadyAttribute(value === undefined ? {} : { 'continuity.session_ready': value })).toBe(false); });
  it('accepts only the exact public true attribute while ignoring unrelated fields', () => { expect(nativeMediaReadyAttribute({ 'continuity.session_ready': 'true', 'continuity.inference_mode': 'scripted', 'lk.agent.state': 'listening' })).toBe(true); expect(nativeMediaReadyAttribute({ 'lk.agent.state': 'listening' })).toBe(false); });
});

describe('trusted inference profile and native readiness binding', () => {
  it('labels the configured cloud profile without implying native readiness or changing input source', async () => {
    expect(voiceInferenceLabel(null)).toBe('VOICE · JOIN TO VERIFY PROFILE');
    expect(voiceInferenceLabel('provider_real')).toBe('Cloud providers (Deepgram/OpenAI/ElevenLabs)');
    const s = setup('listening', false, 'provider_real'); await s.controller.connect(TASK, TOKEN);
    expect(s.controller.state.inference_mode).toBe('provider_real'); expect(s.controller.state.session_ready).toBe(false);
    expect(s.controller.state.input_source).toBe('scripted'); expect(s.current().room.setMicrophoneEnabled).not.toHaveBeenCalled();
    await s.controller.status(); expect(s.current().room.sendText).not.toHaveBeenCalled();
    s.current().events.sessionReady(true, 'provider_real'); await s.controller.status(); expect(s.current().room.sendText).toHaveBeenCalledOnce();
    await s.controller.disconnect(); expect(s.controller.state.inference_mode).toBeNull();
  });
  it.each(['scripted', 'local_real'] as const)('blocks a %s participant in a provider session while keeping mute and End available', async (observed) => {
    const s = setup('listening', true, 'provider_real'); await s.controller.connect(TASK, TOKEN); await s.controller.microphone(true);
    s.current().events.sessionReady(true, observed); expect(s.controller.state.session_ready).toBe(false);
    await s.controller.turn('start'); await s.controller.interrupt(); await s.controller.status();
    expect(s.current().room.performRpc).not.toHaveBeenCalled(); expect(s.current().room.sendText).not.toHaveBeenCalled();
    await s.controller.microphone(false); expect(s.current().room.setMicrophoneEnabled).toHaveBeenLastCalledWith(false);
    await s.controller.disconnect(); expect(s.controller.state.connection).toBe('disconnected'); expect(s.fetcher).toHaveBeenCalledTimes(1);
  });
  it('hides provider failures and credentials without falling back to another inference profile', async () => {
    const s = setup('listening', true, 'provider_real'); s.factory.mockImplementationOnce(() => { throw new Error('private-provider-key-sentinel'); });
    await s.controller.connect(TASK, TOKEN); expect(s.controller.state.connection).toBe('error'); expect(s.controller.state.inference_mode).toBeNull();
    expect(JSON.stringify(s.controller.state)).not.toContain('private-provider-key-sentinel'); expect(JSON.stringify(s.controller.state)).not.toContain(TOKEN);
    expect(s.factory).toHaveBeenCalledTimes(1); expect(s.fetcher).toHaveBeenCalledTimes(1);
  });
  it.each(['scripted', 'local_real', 'provider_real'] as const)('accepts exactly the server-declared %s profile', (mode) => {
    const parsed = parseVoiceSession({ ...session(), mode }, request);
    expect(parsed.mode).toBe(mode); expect(Object.isFrozen(parsed)).toBe(true);
  });
  it.each([undefined, null, '', 'real', 'LOCAL_REAL', 'local_real ', 'PROVIDER_REAL', 'provider_real ', 'cloud', true, 1, {}])('rejects an unknown minted profile %j', (mode) => {
    expect(() => parseVoiceSession({ ...session(), mode }, request)).toThrow();
  });
  it('does not select or verify a profile before an authenticated mint acknowledgement', async () => {
    const s = setup('listening', true, 'local_real'), mint = deferred<Response>();
    s.fetcher.mockImplementationOnce(() => mint.promise);
    expect(s.controller.state.inference_mode).toBeNull(); const joining = s.controller.connect(TASK, TOKEN);
    expect(s.controller.state.inference_mode).toBeNull(); expect(s.factory).not.toHaveBeenCalled();
    const body = JSON.parse(String(s.fetcher.mock.calls[0]?.[1]?.body));
    mint.resolve(Response.json({ ...session(), mode: 'local_real', room: body.room, identity: body.identity })); await joining;
    expect(s.controller.state.inference_mode).toBe('local_real'); expect(s.factory.mock.calls[0]?.[2]).toBe('local_real');
    expect(s.controller.state.session_ready).toBe(true); expect(s.controller.state.input_source).toBe('scripted');
  });
  it.each(['scripted', 'local_real', 'provider_real'] as const)('runs an explicit input turn for the matched %s profile without changing business authority', async (mode) => {
    const s = setup('listening', true, mode); await s.controller.connect(TASK, TOKEN);
    await s.controller.microphone(true); await s.controller.turn('start'); await s.controller.turn('commit'); await s.controller.interrupt();
    expect(vi.mocked(s.current().room.performRpc).mock.calls.map((call) => call[1])).toEqual(['business.start_turn', 'business.commit_turn', 'business.interrupt']);
    expect(s.controller.state.turn).toBe('interrupted'); expect(s.fetcher).toHaveBeenCalledTimes(1);
  });
  it('requires SDK readiness and an explicit matching native profile for local-real controls', async () => {
    const s = setup('initializing', true, 'local_real'); await s.controller.connect(TASK, TOKEN);
    await s.controller.status(); expect(s.current().room.sendText).not.toHaveBeenCalled();
    s.current().events.sessionReady(true); s.current().events.speech('listening'); await s.controller.status();
    expect(s.controller.state.session_ready).toBe(false); expect(s.current().room.sendText).not.toHaveBeenCalled();
    s.current().events.sessionReady(true, 'local_real'); await s.controller.status(); expect(s.current().room.sendText).toHaveBeenCalledOnce();
  });
  it('does not retain a late authenticated profile after End aborts its pending mint', async () => {
    const s = setup('listening', true, 'local_real'), mint = deferred<Response>(); s.fetcher.mockImplementationOnce(() => mint.promise);
    const joining = s.controller.connect(TASK, TOKEN), body = JSON.parse(String(s.fetcher.mock.calls[0]?.[1]?.body));
    await s.controller.disconnect(); mint.resolve(Response.json({ ...session(), mode: 'local_real', room: body.room, identity: body.identity })); await joining;
    expect(s.controller.state.inference_mode).toBeNull(); expect(s.controller.state.connection).toBe('disconnected'); expect(s.factory).not.toHaveBeenCalled();
  });
  it('rejects mismatched observed agent profiles while retaining mute and End', async () => {
    const s = setup('listening', true, 'local_real'); await s.controller.connect(TASK, TOKEN); await s.controller.microphone(true);
    s.current().events.sessionReady(true, 'scripted'); expect(s.controller.state.session_ready).toBe(false);
    await s.controller.status(); await s.controller.turn('start'); await s.controller.interrupt();
    expect(s.current().room.sendText).not.toHaveBeenCalled(); expect(s.current().room.performRpc).not.toHaveBeenCalled();
    await s.controller.microphone(false); expect(s.current().room.setMicrophoneEnabled).toHaveBeenLastCalledWith(false);
    s.current().events.sessionReady(true, 'local_real'); await s.controller.status(); expect(s.current().room.sendText).toHaveBeenCalledOnce();
    await s.controller.disconnect(); expect(s.controller.state.inference_mode).toBeNull();
  });
  it('requires an exact profile attribute and readiness value, including for scripted sessions', () => {
    const ready = { 'continuity.session_ready': 'true' };
    expect(nativeMediaReadyAttribute(ready)).toBe(false);
    for (const mode of ['scripted', 'local_real', 'provider_real'] as const) {
      expect(nativeMediaReadyAttribute({ ...ready, 'continuity.inference_mode': mode }, mode)).toBe(true);
      expect(nativeMediaReadyAttribute({ ...ready, 'continuity.inference_mode': mode }, mode === 'scripted' ? 'local_real' : 'scripted')).toBe(false);
    }
    for (const value of ['', 'real', 'local_real ', 'LOCAL_REAL']) expect(nativeMediaReadyAttribute({ ...ready, 'continuity.inference_mode': value }, 'local_real')).toBe(false);
  });
  it('does not enable controls from a readiness callback without the selected agent', async () => {
    const s = setup('listening', true, 'local_real'); await s.controller.connect(TASK, TOKEN);
    s.current().events.agent(null); s.current().events.sessionReady(true, 'local_real'); s.current().events.speech('listening');
    await s.controller.status(); expect(s.controller.state.session_ready).toBe(false); expect(s.current().room.sendText).not.toHaveBeenCalled();
  });
  it('fences late old-profile readiness callbacks and clears the verified profile on End and failed mint', async () => {
    const s = setup('listening', true, 'local_real'); await s.controller.connect(TASK, TOKEN); const old = s.current().events;
    await s.controller.disconnect(); old.agent('late'); old.sessionReady(true, 'local_real'); old.speech('listening');
    expect(s.controller.state.inference_mode).toBeNull(); expect(s.controller.state.session_ready).toBe(false);
    s.fetcher.mockResolvedValueOnce(Response.json({ ...session(), mode: 'unknown' })); await s.controller.connect(TASK, TOKEN);
    expect(s.controller.state.inference_mode).toBeNull(); expect(s.controller.state.session_ready).toBe(false);
  });
  it('retains the minted profile over transport reconnect without accepting a different native profile', async () => {
    const s = setup('listening', true, 'local_real'); await s.controller.connect(TASK, TOKEN); s.current().events.reconnecting();
    expect(s.controller.state.inference_mode).toBe('local_real'); s.current().events.sessionReady(true, 'scripted'); s.current().events.reconnected();
    await s.controller.status(); expect(s.current().room.sendText).not.toHaveBeenCalled(); expect(s.fetcher).toHaveBeenCalledTimes(1);
    s.current().events.sessionReady(true, 'local_real'); await s.controller.status(); expect(s.current().room.sendText).toHaveBeenCalledOnce();
  });
  it('extends only explicitly real profile commit acknowledgement, preserving scripted and interruption budgets', () => {
    for (const mode of ['local_real', 'provider_real'] as const) expect(nativeRpcResponseTimeout('business.commit_turn', mode)).toBe(12000);
    for (const method of ['business.start_turn', 'business.commit_turn', 'business.interrupt'] as const) expect(nativeRpcResponseTimeout(method, 'scripted')).toBe(8000);
    for (const method of ['business.start_turn', 'business.interrupt'] as const) for (const mode of ['local_real', 'provider_real'] as const) expect(nativeRpcResponseTimeout(method, mode)).toBe(8000);
  });
});
