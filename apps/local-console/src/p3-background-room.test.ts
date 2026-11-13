import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const sdk = vi.hoisted(() => {
  const rooms: FakeRoom[] = [];
  class FakeRoom {
    name = 'p3_native_demo';
    readonly handlers = new Map<string, (...args: unknown[]) => void>();
    readonly remoteParticipants = new Map<
      string,
      { identity: string; kind: string; attributes: Record<string, string> }
    >();
    readonly localParticipant = {
      identity: 'p3_viewer_demo',
      sendText: vi.fn<() => Promise<void>>(async () => undefined),
    };
    readonly connect = vi.fn<() => Promise<void>>(async () => undefined);
    readonly disconnect = vi.fn<() => Promise<void>>(async () => undefined);
    readonly registerTextStreamHandler = vi.fn();
    readonly unregisterTextStreamHandler = vi.fn();
    readonly removeAllListeners = vi.fn();
    constructor() {
      rooms.push(this);
    }
    on(event: string, handler: (...args: unknown[]) => void): this {
      this.handlers.set(event, handler);
      return this;
    }
    emit(event: string, ...args: unknown[]) {
      this.handlers.get(event)?.(...args);
    }
  }
  return { rooms, FakeRoom };
});
vi.mock('livekit-client', () => ({
  Room: sdk.FakeRoom,
  ParticipantKind: { AGENT: 'agent' },
  RoomEvent: Object.fromEntries(
    [
      'ParticipantConnected',
      'ParticipantAttributesChanged',
      'ParticipantDisconnected',
      'Reconnecting',
      'Reconnected',
      'Disconnected',
    ].map((name) => [name, name]),
  ),
}));
import { NativeBackgroundPort, selectedNativeReady } from './p3-background-room';
import { parseNativeSession } from './p3-background-wire';
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}
const tick = async () => {
  for (let i = 0; i < 12; i++) await Promise.resolve();
};
const hash = '1'.repeat(64),
  token = 'x'.repeat(43);
function session() {
  return {
    schema_version: 1,
    kind: 'native-policy.session',
    session_id: '33333333-3333-4333-8333-333333333333',
    binding: {
      scope: { tenant_id: 'tenant_demo', account_id: 'account_demo' },
      case_id: 'case_demo',
      delegation_id: 'delegation_demo',
      request_revision: 1,
      input_fingerprint: hash,
      sources: [
        {
          role: 'policy',
          source_id: 'policy_source',
          version: 'record_v9',
          sha256: hash,
          byte_length: 128,
        },
        {
          role: 'facts',
          source_id: 'facts_source',
          version: 'record_v7',
          sha256: hash,
          byte_length: 96,
        },
      ],
    },
    server_url: 'ws://127.0.0.1:17880',
    room_name: 'p3_native_demo',
    participant_identity: 'p3_viewer_demo',
    agent_identity: 'p3_agent_demo',
    rtc_token: 'aaa.bbb.ccc',
    profile: 'p3_native_policy_text_v1',
    inference_mode: 'scripted',
    expires_at_ms: 1794480060000,
  };
}
function observation() {
  return {
    schema_version: 1,
    kind: 'native-policy.observation',
    binding: session().binding,
    state: 'no_work',
    work: null,
    attempt: null,
    result: null,
    applicability: null,
    tool_waiter: 'idle',
    owned_run: false,
    error: null,
    consistency: 'as_of_non_atomic',
    app_read_completed_at_ms: 1794480000101,
  };
}
function agent() {
  return {
    identity: 'p3_agent_demo',
    kind: 'agent',
    attributes: {
      'p3.native_policy.ready': 'true',
      'p3.native_policy.profile': 'p3_native_policy_text_v1',
      'p3.native_policy.session_id': session().session_id,
      'p3.inference_mode': 'scripted',
      'lk.agent.state': 'listening',
    },
  };
}
function response(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}
function setup() {
  const callbacks = { ready: vi.fn(), text: vi.fn(), connection: vi.fn() },
    fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(response(session()));
  const port = new NativeBackgroundPort(token, callbacks, fetcher);
  return { port, callbacks, fetcher };
}
async function joined() {
  const s = setup();
  await s.port.join(new AbortController().signal);
  const room = sdk.rooms.at(-1)!;
  room.remoteParticipants.set('p3_agent_demo', agent());
  room.emit('ParticipantConnected');
  return { ...s, room };
}
function stream(chunks: readonly string[]) {
  return {
    async *withAbortSignal(_signal: AbortSignal) {
      yield* chunks;
    },
  };
}
beforeEach(() => {
  sdk.rooms.length = 0;
});
afterEach(() => vi.useRealTimers());
describe('standalone P3 native TEXT adapter', () => {
  it('mints with empty POST and a memory-only operator capability, then sends only lk.chat', async () => {
    const s = await joined();
    expect(s.fetcher).toHaveBeenCalledWith(
      '/v1/p3-native/session',
      expect.objectContaining({
        method: 'POST',
        credentials: 'omit',
        cache: 'no-store',
        redirect: 'error',
        headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
      }),
    );
    expect(s.fetcher.mock.calls[0]?.[1]).not.toHaveProperty('body');
    await s.port.sendText('hello');
    expect(s.room.localParticipant.sendText).toHaveBeenCalledExactlyOnceWith('hello', {
      topic: 'lk.chat',
    });
    expect(s.room.connect).toHaveBeenCalledWith(
      'ws://127.0.0.1:17880',
      'aaa.bbb.ccc',
      expect.objectContaining({ autoSubscribe: false }),
    );
    await s.port.close();
  });
  it('uses detached fetch invocation, preserving the real browser native receiver boundary', async () => {
    const fetcher: typeof fetch = async function (this: unknown) {
      expect(this).toBeUndefined();
      return response(session());
    };
    const s = setup(),
      port = new NativeBackgroundPort(token, s.callbacks, fetcher);
    await port.join(new AbortController().signal);
    await port.close();
  });
  it.each([
    'p3.native_policy.ready',
    'p3.native_policy.profile',
    'p3.native_policy.session_id',
    'p3.inference_mode',
    'lk.agent.state',
  ])('requires exact selected AGENT attribute %s', async (key) => {
    const s = await joined();
    expect(s.callbacks.ready).toHaveBeenLastCalledWith(true);
    s.room.remoteParticipants.get('p3_agent_demo')!.attributes[key] = 'foreign';
    s.room.emit('ParticipantAttributesChanged');
    expect(s.callbacks.ready).toHaveBeenLastCalledWith(false);
    await expect(s.port.sendText('no')).rejects.toMatchObject({ code: 'closed' });
    await s.port.close();
  });
  it('does not select another native agent or a matching-identity non-agent', () => {
    const expected = parseNativeSession(session());
    expect(
      selectedNativeReady(expected, { ...agent(), identity: 'other' } as never, 'agent' as never),
    ).toBe(false);
    expect(
      selectedNativeReady(expected, { ...agent(), kind: 'standard' } as never, 'agent' as never),
    ).toBe(false);
  });
  it('reads only the exact configured binding and rejects a foreign observation', async () => {
    const s = await joined();
    s.fetcher.mockResolvedValueOnce(
      response({ ...observation(), binding: { ...session().binding, case_id: 'foreign' } }),
    );
    await expect(s.port.read(new AbortController().signal)).rejects.toMatchObject({
      code: 'invalid',
    });
    s.fetcher.mockResolvedValueOnce(response(observation()));
    expect(await s.port.read(new AbortController().signal)).toEqual(observation());
    expect(s.fetcher).toHaveBeenLastCalledWith(
      '/v1/p3-native/observation',
      expect.objectContaining({
        method: 'GET',
        credentials: 'omit',
        cache: 'no-store',
        redirect: 'error',
        headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
      }),
    );
    expect(s.fetcher.mock.calls.at(-1)?.[1]).not.toHaveProperty('body');
    await s.port.close();
  });
  it('enforces one actual read until an ignored fetch settles', async () => {
    const s = await joined(),
      held = deferred<Response>();
    s.fetcher.mockReturnValueOnce(held.promise);
    const first = s.port.read(new AbortController().signal);
    await expect(s.port.read(new AbortController().signal)).rejects.toMatchObject({
      code: 'overloaded',
    });
    held.resolve(response(observation()));
    await first;
    await s.port.close();
  });
  it('rejects padded error responses at256bytes and then permits a later bounded read', async () => {
    const s = await joined();
    s.fetcher.mockResolvedValueOnce(
      new Response(
        ' '.repeat(257) +
          JSON.stringify({ schema_version: 1, kind: 'native-policy.error', code: 'unavailable' }),
        {
          status: 503,
          headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
        },
      ),
    );
    await expect(s.port.read(new AbortController().signal)).rejects.toMatchObject({
      code: 'invalid',
    });
    s.fetcher.mockResolvedValueOnce(response(observation()));
    await s.port.read(new AbortController().signal);
    await s.port.close();
  });
  it('cancels a body on header rejection rather than leaving a response owner detached', async () => {
    const s = await joined(),
      cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({ cancel });
    s.fetcher.mockResolvedValueOnce(
      new Response(body, { headers: { 'Content-Type': 'text/html', 'Cache-Control': 'no-store' } }),
    );
    await expect(s.port.read(new AbortController().signal)).rejects.toMatchObject({
      code: 'invalid',
    });
    expect(cancel).toHaveBeenCalledOnce();
    await s.port.close();
  });
  it('does not release close while mint ignores cancellation, and never creates a late room', async () => {
    const s = setup(),
      held = deferred<Response>();
    s.fetcher.mockReset().mockReturnValueOnce(held.promise);
    const joining = s.port.join(new AbortController().signal);
    const caught = joining.catch((e: unknown) => e);
    let closed = false;
    const closing = s.port.close().then(() => {
      closed = true;
    });
    await tick();
    expect(closed).toBe(false);
    held.resolve(response(session()));
    expect(await caught).toMatchObject({ code: 'closed' });
    await closing;
    expect(sdk.rooms).toHaveLength(0);
  });
  it('retains a late room connect through actual disconnection', async () => {
    const s = setup(),
      held = deferred<void>();
    const joining = s.port.join(new AbortController().signal);
    await joining;
    const room = sdk.rooms.at(-1)!;
    // Start a second isolated adapter with its actual connect held before invocation.
    const other = setup();
    const heldRoom = new sdk.FakeRoom();
    heldRoom.connect.mockReturnValueOnce(held.promise);
    const port = new NativeBackgroundPort(
      token,
      other.callbacks,
      other.fetcher,
      () => heldRoom as never,
    );
    const late = port.join(new AbortController().signal),
      caught = late.catch((e: unknown) => e);
    await vi.waitFor(() => expect(heldRoom.connect).toHaveBeenCalledOnce());
    let closed = false;
    const ending = port.close().then(() => {
      closed = true;
    });
    await tick();
    expect(closed).toBe(false);
    held.resolve();
    expect(await caught).toMatchObject({ code: 'closed' });
    await ending;
    expect(heldRoom.disconnect.mock.calls.length).toBeGreaterThanOrEqual(2);
    await joining;
    await s.port.close();
    expect(room.removeAllListeners).toHaveBeenCalled();
  });
  it('accepts bounded text only from the exact ready agent and fences streams across reconnect', async () => {
    const s = await joined(),
      handler = s.room.registerTextStreamHandler.mock.calls[0]![1] as (
        reader: unknown,
        info: { identity: string },
      ) => void;
    handler(stream(['first ', 'answer']), { identity: 'p3_agent_demo' });
    await tick();
    expect(s.callbacks.text).toHaveBeenCalledExactlyOnceWith('first answer');
    const held = deferred<void>();
    handler(
      {
        async *withAbortSignal() {
          await held.promise;
          yield 'stale';
        },
      },
      { identity: 'p3_agent_demo' },
    );
    s.room.emit('Reconnecting');
    s.room.emit('Reconnected');
    held.resolve();
    await tick();
    expect(s.callbacks.text).toHaveBeenCalledOnce();
    await s.port.close();
  });
  it('keeps at most two incoming text readers and ends the room on overflow without spawning cleanup work', async () => {
    const s = await joined(),
      handler = s.room.registerTextStreamHandler.mock.calls[0]![1] as (
        reader: unknown,
        info: { identity: string },
      ) => void,
      held = deferred<void>();
    const reader = {
      async *withAbortSignal() {
        await held.promise;
        yield 'late';
      },
    };
    handler(reader, { identity: 'p3_agent_demo' });
    handler(reader, { identity: 'p3_agent_demo' });
    handler(reader, { identity: 'p3_agent_demo' });
    expect(s.callbacks.connection).toHaveBeenLastCalledWith('disconnected');
    const closing = s.port.close();
    held.resolve();
    await closing;
    expect(s.callbacks.text).not.toHaveBeenCalled();
  });
  it('rejects oversized agent text and clears owned stream deadline timers', async () => {
    vi.useFakeTimers();
    const s = await joined(),
      handler = s.room.registerTextStreamHandler.mock.calls[0]![1] as (
        reader: unknown,
        info: { identity: string },
      ) => void;
    handler(stream(['x'.repeat(16385)]), { identity: 'p3_agent_demo' });
    await tick();
    expect(s.callbacks.text).not.toHaveBeenCalled();
    await s.port.close();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe('SDK code is loaded only by an owned explicit Join', () => {
  it('does not invoke the loader, mint or create a room on construction', async () => {
    const s = setup(),
      loader = vi.fn(async () => await import('livekit-client'));
    const port = new NativeBackgroundPort(token, s.callbacks, s.fetcher, undefined, loader);
    expect(loader).not.toHaveBeenCalled();
    expect(s.fetcher).not.toHaveBeenCalled();
    expect(sdk.rooms).toHaveLength(0);
    await port.close();
    expect(loader).not.toHaveBeenCalled();
  });
  it('retains held import ownership across close and does not create or join a late room', async () => {
    const s = setup(),
      held = deferred<typeof import('livekit-client')>(),
      loader = vi.fn(() => held.promise);
    const port = new NativeBackgroundPort(token, s.callbacks, s.fetcher, undefined, loader);
    const joining = port.join(new AbortController().signal),
      observed = joining.catch((e: unknown) => e);
    await vi.waitFor(() => expect(loader).toHaveBeenCalledOnce());
    await expect(port.join(new AbortController().signal)).rejects.toMatchObject({ code: 'closed' });
    let closed = false;
    const closing = port.close().then(() => {
      closed = true;
    });
    await tick();
    expect(closed).toBe(false);
    held.resolve(await import('livekit-client'));
    expect(await observed).toMatchObject({ code: 'closed' });
    await closing;
    expect(sdk.rooms).toHaveLength(0);
    expect(s.fetcher).toHaveBeenCalledOnce();
  });
  it('contains import failure and permits a new independent client to make useful progress', async () => {
    const s = setup(),
      loader = vi.fn(async () => {
        throw new Error('PRIVATE_SENTINEL');
      });
    const port = new NativeBackgroundPort(token, s.callbacks, s.fetcher, undefined, loader);
    await expect(port.join(new AbortController().signal)).rejects.toMatchObject({
      code: 'unavailable',
    });
    await port.close();
    const fresh = await joined();
    await fresh.port.sendText('hello');
    expect(fresh.room.localParticipant.sendText).toHaveBeenCalledOnce();
    await fresh.port.close();
  });
});
