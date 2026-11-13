import { describe, expect, it, vi } from 'vitest';
import {
  LabController, MAX_TEXT_BYTES, appendBounded, parseSession, readBoundedText,
  requestSession, validateMessage, validateSession,
} from './lab';
import type { LabCallbacks, RoomCallbacks, RoomPort, SessionRequest } from './lab';

const request: SessionRequest = { room: 'lab-test', identity: 'browser-test', dispatch_agent: true };
const secret = 'development-token-only';
const session = {
  url: 'ws://localhost:17880', token: 'opaque-room-token', room: 'lab-test',
  identity: 'browser-test', expires_in: 300, agent_name: 'local-transport-agent', agent_dispatched: true,
};
function response(): Response { return Response.json(session); }
function callbacks(): LabCallbacks {
  return { onEntry: vi.fn(), onState: vi.fn(), onMicrophone: vi.fn() };
}
function port(): RoomPort {
  return { connect: vi.fn(async () => undefined), disconnect: vi.fn(async () => undefined),
    sendText: vi.fn(async () => undefined), setMicrophoneEnabled: vi.fn(async () => undefined) };
}
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  return { promise: new Promise<T>((done) => { resolve = done; }), resolve };
}

describe('local boundary validation', () => {
  it('requires scoped names and a nonempty header-safe local credential', () => {
    expect(() => validateSession(request, secret)).not.toThrow();
    for (const bad of ['other-room', 'lab-UPPER', 'lab-', `lab-${'x'.repeat(49)}`]) {
      expect(() => validateSession({ ...request, room: bad }, secret)).toThrow();
    }
    expect(() => validateSession({ ...request, identity: 'admin' }, secret)).toThrow();
    expect(() => validateSession(request, `${secret}\n`)).toThrow();
    expect(() => validateSession(request, '')).toThrow();
  });

  it('limits UTF-8 bytes instead of counting only characters', () => {
    expect(validateMessage('  hello  ')).toBe('hello');
    expect(() => validateMessage(' ')).toThrow();
    expect(validateMessage('a'.repeat(MAX_TEXT_BYTES))).toHaveLength(MAX_TEXT_BYTES);
    expect(() => validateMessage('😀'.repeat(MAX_TEXT_BYTES / 4 + 1))).toThrow();
  });

  it('closes an oversized asynchronous stream', async () => {
    let closed = false;
    async function* stream(): AsyncGenerator<string> {
      try { yield '😀'; yield 'extra'; } finally { closed = true; }
    }
    await expect(readBoundedText(stream(), 4)).rejects.toThrow('limit');
    expect(closed).toBe(true);
  });

  it('retains a fixed number of log entries', () => {
    expect(appendBounded([1, 2, 3], 4, 2)).toEqual([3, 4]);
    expect(appendBounded([1, 2], 3, 1)).toEqual([3]);
    expect(() => appendBounded([], 1, 0)).toThrow();
  });

  it('rejects session scope mismatch and inappropriate transport URLs', () => {
    expect(parseSession(session, request)).toEqual(session);
    expect(() => parseSession({ ...session, room: 'lab-other' }, request)).toThrow();
    expect(() => parseSession({ ...session, url: 'https://example.test' }, request)).toThrow();
    expect(() => parseSession({ ...session, url: 'ws://user:password@localhost' }, request)).toThrow();
    expect(() => parseSession({ ...session, expires_in: 1000 }, request)).toThrow();
  });

  it('places the access token only in the header and sanitizes rejected responses', async () => {
    const fetcher = vi.fn(async () => response()) as unknown as typeof fetch;
    await requestSession(request, secret, new AbortController().signal, fetcher);
    const call = vi.mocked(fetcher).mock.calls[0];
    expect(call?.[0]).toBe('/api/session');
    expect(call?.[1]?.headers).toEqual({ 'Content-Type': 'application/json', Authorization: `Bearer ${secret}` });
    expect(call?.[1]?.body).not.toContain(secret);
    const denied = vi.fn(async () => new Response(`private ${secret}`, { status: 403 })) as unknown as typeof fetch;
    await expect(requestSession(request, secret, new AbortController().signal, denied)).rejects.toThrow('access was denied');
    await expect(requestSession(request, secret, new AbortController().signal, denied)).rejects.not.toThrow(secret);
  });
});

describe('room lifecycle', () => {
  it('does not enable the microphone during connect, and cleans up after disconnect', async () => {
    const room = port();
    const observer = callbacks();
    const controller = new LabController(() => room, observer, vi.fn(async () => response()) as unknown as typeof fetch);
    expect(await controller.connect(request, secret)).toBe(true);
    expect(room.setMicrophoneEnabled).not.toHaveBeenCalled();
    await controller.toggleMicrophone();
    expect(room.setMicrophoneEnabled).toHaveBeenCalledWith(true);
    await controller.disconnect();
    expect(room.disconnect).toHaveBeenCalledOnce();
    expect(controller.state).toBe('disconnected');
    expect(observer.onMicrophone).toHaveBeenLastCalledWith(false);
    await expect(controller.send('after disconnect')).rejects.toThrow('Connect');
  });

  it('cancels session intake without creating a room after disconnect', async () => {
    const pending = deferred<Response>();
    const factory = vi.fn(() => port());
    const controller = new LabController(factory, callbacks(), vi.fn(() => pending.promise) as unknown as typeof fetch);
    const connecting = controller.connect(request, secret);
    await controller.disconnect();
    pending.resolve(response());
    expect(await connecting).toBe(false);
    expect(factory).not.toHaveBeenCalled();
    expect(controller.state).toBe('disconnected');
  });

  it('closes a room when disconnect races with its connection', async () => {
    const connected = deferred<void>();
    const room = port();
    vi.mocked(room.connect).mockImplementation(() => connected.promise);
    const controller = new LabController(() => room, callbacks(), vi.fn(async () => response()) as unknown as typeof fetch);
    const connecting = controller.connect(request, secret);
    await vi.waitFor(() => expect(room.connect).toHaveBeenCalled());
    await controller.disconnect();
    connected.resolve();
    expect(await connecting).toBe(false);
    expect(room.disconnect).toHaveBeenCalled();
    expect(controller.state).toBe('disconnected');
  });

  it('ignores callbacks from an obsolete room and limits concurrent connection attempts', async () => {
    let oldCallbacks!: RoomCallbacks;
    const room = port();
    const observer = callbacks();
    const fetcher = vi.fn(async () => response()) as unknown as typeof fetch;
    const controller = new LabController((value) => { oldCallbacks = value; return room; }, observer, fetcher);
    await controller.connect(request, secret);
    expect(await controller.connect(request, secret)).toBe(false);
    expect(fetcher).toHaveBeenCalledOnce();
    await controller.disconnect();
    vi.mocked(observer.onEntry).mockClear();
    oldCallbacks.onText('obsolete');
    oldCallbacks.onDisconnected();
    expect(observer.onEntry).not.toHaveBeenCalled();
    expect(controller.state).toBe('disconnected');
  });

  it('does not report connected after the SDK disconnected during the handshake', async () => {
    const connected = deferred<void>();
    let incoming!: RoomCallbacks;
    const room = port();
    vi.mocked(room.connect).mockImplementation(() => connected.promise);
    const controller = new LabController((value) => { incoming = value; return room; }, callbacks(),
      vi.fn(async () => response()) as unknown as typeof fetch);
    const connecting = controller.connect(request, secret);
    await vi.waitFor(() => expect(room.connect).toHaveBeenCalled());
    incoming.onDisconnected();
    connected.resolve();
    expect(await connecting).toBe(false);
    expect(controller.state).toBe('disconnected');
    expect(room.disconnect).toHaveBeenCalled();
  });

  it('pauses sends during SDK reconnect while preserving an explicit disconnect path', async () => {
    let incoming!: RoomCallbacks;
    const room = port();
    const fetcher = vi.fn(async () => response()) as unknown as typeof fetch;
    const controller = new LabController((value) => { incoming = value; return room; }, callbacks(), fetcher);
    await controller.connect(request, secret);
    incoming.onReconnecting();
    expect(controller.state).toBe('reconnecting');
    expect(await controller.connect(request, secret)).toBe(false);
    await expect(controller.send('during reconnect')).rejects.toThrow('Connect');
    incoming.onReconnected();
    expect(controller.state).toBe('connected');
    await controller.send('resumed');
    expect(room.sendText).toHaveBeenCalledWith('resumed');
    await controller.disconnect();
  });

  it('disposes a failed room and never echoes raw SDK errors', async () => {
    const room = port();
    vi.mocked(room.connect).mockRejectedValue(new Error(`native failure ${secret}`));
    const observer = callbacks();
    const controller = new LabController(() => room, observer, vi.fn(async () => response()) as unknown as typeof fetch);
    expect(await controller.connect(request, secret)).toBe(false);
    expect(room.disconnect).toHaveBeenCalledOnce();
    expect(controller.state).toBe('error');
    expect(JSON.stringify(vi.mocked(observer.onEntry).mock.calls)).not.toContain(secret);
  });
});
