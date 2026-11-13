import { randomUUID } from 'node:crypto';
import { request, Server } from 'node:http';
import { connect } from 'node:net';
import { setTimeout as delay } from 'node:timers/promises';
import { describe, expect, it, vi } from 'vitest';
import { ChannelPolicyReadHttp, type ReadEndpoint } from '../src/read-http.js';
import { SourceReadError, type DiscoveryPage } from '../src/source-reader.js';
const bearer = 't'.repeat(43);
const page: DiscoveryPage = Object.freeze({
  schemaVersion: 1,
  kind: 'channel.policy_discovery',
  profileId: randomUUID(),
  scope: Object.freeze({ tenantId: 'demo', accountId: 'traveller' }),
  caseId: 'case',
  conversationId: 'conversation',
  readCompletedAt: '2026-11-13T00:00:00.000Z',
  items: [],
  overflow: false,
  nextCursor: null,
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
function ports() {
  return {
    discover: vi.fn(async () => page),
    prepared: vi.fn(async (_id: string, _source: 'native' | 'sms'): Promise<Buffer | null> => null),
  };
}
function exchange(
  endpoint: ReadEndpoint,
  path: string,
  raw = '{"schemaVersion":1}',
  token = bearer,
): Promise<{ status: number; body: Buffer; headers: Record<string, unknown> }> {
  return new Promise((resolve, reject) => {
    const r = request(
      {
        ...endpoint,
        method: 'POST',
        path,
        headers: {
          authorization: 'Bearer ' + token,
          'content-type': 'application/json',
          'content-length': String(Buffer.byteLength(raw)),
          connection: 'close',
        },
      },
      (response) => {
        const chunks: Buffer[] = [];
        response.on('data', (chunk: Buffer) => chunks.push(chunk));
        response.on('error', reject);
        response.on('end', () =>
          resolve({
            status: response.statusCode!,
            body: Buffer.concat(chunks),
            headers: response.headers,
          }),
        );
      },
    );
    r.on('error', reject);
    r.end(raw);
  });
}
async function until(predicate: () => boolean): Promise<void> {
  const end = performance.now() + 1000;
  while (!predicate()) {
    if (performance.now() > end) throw Error('condition_timeout');
    await delay(1);
  }
}
describe('loopback worker reads', () => {
  it('returns closed discovery and exact prepared bytes with explicit no-plan status', async () => {
    const p = ports(),
      h = new ChannelPolicyReadHttp(p, bearer);
    const e = await h.start();
    try {
      const first = await exchange(e, '/v1/policy/discovery');
      expect(first.status).toBe(200);
      expect(first.body.toString()).toBe(JSON.stringify(page));
      expect(first.headers['cache-control']).toBe('no-store');
      const raw = JSON.stringify({
        schemaVersion: 1,
        receiptId: randomUUID(),
        sourceBindingId: 'native',
      });
      const absent = await exchange(e, '/v1/policy/prepared', raw);
      expect(absent.status).toBe(204);
      expect(absent.body.length).toBe(0);
      const frame = Buffer.from(
        '{"schemaVersion":1,"canonicalPayload":"café 🧭","payloadDigest":"opaque"}',
      );
      p.prepared.mockResolvedValueOnce(frame);
      const present = await exchange(e, '/v1/policy/prepared', raw);
      expect(present.status).toBe(200);
      expect(present.body.equals(frame)).toBe(true);
    } finally {
      await h.close();
    }
  });
  it.each([
    'wrong_auth',
    'unknown_route',
    'duplicate_key',
    'extra_scope',
    'invalid_source',
    'invalid_uuid',
    'whitespace',
  ])('rejects %s before public reads', async (mode) => {
    const p = ports(),
      h = new ChannelPolicyReadHttp(p, bearer),
      e = await h.start();
    let path = '/v1/policy/discovery',
      raw = '{"schemaVersion":1}',
      token = bearer;
    if (mode === 'wrong_auth') token = 'x'.repeat(43);
    if (mode === 'unknown_route') path += '/other';
    if (mode === 'duplicate_key') raw = '{"schemaVersion":0,"schemaVersion":1}';
    if (mode === 'extra_scope') raw = '{"schemaVersion":1,"tenantId":"other"}';
    if (mode === 'whitespace') raw = ' {"schemaVersion":1}';
    if (mode === 'invalid_source' || mode === 'invalid_uuid') {
      path = '/v1/policy/prepared';
      raw = JSON.stringify({
        schemaVersion: 1,
        receiptId: mode === 'invalid_uuid' ? 'bad' : randomUUID(),
        sourceBindingId: mode === 'invalid_source' ? 'other' : 'native',
      });
    }
    try {
      const result = await exchange(e, path, raw, token);
      expect(result.status).toBe(
        mode === 'wrong_auth' ? 403 : mode === 'unknown_route' ? 404 : 400,
      );
      expect(p.discover).not.toHaveBeenCalled();
      expect(p.prepared).not.toHaveBeenCalled();
    } finally {
      await h.close();
    }
  });
  it('retains four real handler lifetimes after all clients abandon them', async () => {
    const held = deferred<DiscoveryPage>(),
      p = ports();
    p.discover.mockImplementation(() => held.promise);
    const h = new ChannelPolicyReadHttp(p, bearer, 20),
      e = await h.start();
    const clients = Array.from({ length: 4 }, () => {
      const r = request({
        ...e,
        path: '/v1/policy/discovery',
        method: 'POST',
        headers: {
          authorization: 'Bearer ' + bearer,
          'content-type': 'application/json',
          'content-length': '19',
          connection: 'close',
        },
      });
      r.on('error', () => undefined);
      r.end('{"schemaVersion":1}');
      return r;
    });
    try {
      await until(() => p.discover.mock.calls.length === 4);
      clients.forEach((c) => c.destroy());
      const saturated = await exchange(e, '/v1/policy/discovery');
      expect(saturated.status).toBe(429);
      expect(p.discover).toHaveBeenCalledTimes(4);
      expect(h.metrics().handlers).toBe(4);
      await expect(h.close()).rejects.toMatchObject({ code: 'cleanup_incomplete' });
      expect(h.metrics().handlers).toBe(4);
      held.resolve(page);
      await h.close();
      expect(h.metrics().handlers).toBe(0);
    } finally {
      clients.forEach((c) => c.destroy());
      held.resolve(page);
      await h.close();
    }
  });
  it('sanitizes dependency errors and preserves explicit reader failure codes', async () => {
    const p = ports(),
      h = new ChannelPolicyReadHttp(p, bearer),
      e = await h.start();
    try {
      p.discover.mockRejectedValueOnce(new Error('secret_provider_sentinel'));
      const unknown = await exchange(e, '/v1/policy/discovery');
      expect(unknown.status).toBe(503);
      expect(unknown.body.toString()).toBe(
        '{"schemaVersion":1,"status":"unavailable","code":"unavailable"}',
      );
      p.discover.mockRejectedValueOnce(new SourceReadError('capacity'));
      expect((await exchange(e, '/v1/policy/discovery')).status).toBe(429);
      expect((await exchange(e, '/v1/policy/discovery')).status).toBe(200);
    } finally {
      await h.close();
    }
  });
  it('bounds framed response and request bytes independently', async () => {
    const p = ports(),
      h = new ChannelPolicyReadHttp(p, bearer),
      e = await h.start();
    const raw = JSON.stringify({
      schemaVersion: 1,
      receiptId: randomUUID(),
      sourceBindingId: 'sms',
    });
    try {
      p.prepared.mockResolvedValueOnce(Buffer.alloc(32768, 32));
      expect((await exchange(e, '/v1/policy/prepared', raw)).body.length).toBe(32768);
      p.prepared.mockResolvedValueOnce(Buffer.alloc(32769, 32));
      expect((await exchange(e, '/v1/policy/prepared', raw)).status).toBe(503);
      expect((await exchange(e, '/v1/policy/discovery', ' '.repeat(1025))).status).toBe(400);
      expect(p.discover).not.toHaveBeenCalled();
    } finally {
      await h.close();
    }
  });
  it('rejects duplicate authorization headers and closes idle sockets', async () => {
    const p = ports(),
      h = new ChannelPolicyReadHttp(p, bearer),
      e = await h.start();
    const socket = connect(e);
    const done = new Promise<string>((resolve, reject) => {
      let output = '';
      socket.setEncoding('utf8');
      socket.on('data', (chunk) => {
        output += chunk;
      });
      socket.once('end', () => resolve(output));
      socket.once('error', reject);
    });
    socket.end(
      'POST /v1/policy/discovery HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer ' +
        bearer +
        '\r\nAuthorization: Bearer ' +
        bearer +
        '\r\nContent-Type: application/json\r\nContent-Length: 19\r\nConnection: close\r\n\r\n{"schemaVersion":1}',
    );
    try {
      expect(await done).toContain('400 Bad Request');
      expect(p.discover).not.toHaveBeenCalled();
    } finally {
      socket.destroy();
      await h.close();
    }
  });
  it('owns startup and validates repeat port and close-before-start', async () => {
    const p = ports(),
      h = new ChannelPolicyReadHttp(p, bearer);
    const starting = h.start();
    const closed = h.close();
    await starting;
    await closed;
    await expect(h.start()).rejects.toMatchObject({ code: 'closed' });
    const fresh = new ChannelPolicyReadHttp(p, bearer);
    const e = await fresh.start();
    try {
      expect(await fresh.start(e.port)).toEqual(e);
      await expect(fresh.start(e.port === 65535 ? 1 : e.port + 1)).rejects.toMatchObject({
        code: 'invalid_input',
      });
    } finally {
      await fresh.close();
    }
  });
  it('contains nested getter exceptions before allocating a listener', () => {
    const p = ports();
    Object.defineProperty(p, 'discover', {
      get: () => {
        throw new Error('private_sentinel');
      },
    });
    expect(() => new ChannelPolicyReadHttp(p, bearer)).toThrow('invalid_input');
  });
  it('permits useful startup after an occupied-port failure', async () => {
    const p = ports(),
      occupied = new ChannelPolicyReadHttp(p, bearer),
      h = new ChannelPolicyReadHttp(p, bearer);
    const old = await occupied.start();
    try {
      await expect(h.start(old.port)).rejects.toMatchObject({
        code: 'unavailable',
        message: 'unavailable',
      });
      const e = await h.start();
      expect((await exchange(e, '/v1/policy/discovery')).status).toBe(200);
    } finally {
      await h.close();
      await occupied.close();
    }
  });
  it('normalizes synchronous listen errors and removes failed-start listeners', async () => {
    const p = ports(),
      h = new ChannelPolicyReadHttp(p, bearer);
    const spy = vi.spyOn(Server.prototype, 'listen').mockImplementationOnce(() => {
      throw new Error('private_sentinel');
    });
    try {
      await expect(h.start()).rejects.toMatchObject({
        code: 'unavailable',
        message: 'unavailable',
      });
    } finally {
      spy.mockRestore();
    }
    try {
      const e = await h.start();
      expect((await exchange(e, '/v1/policy/discovery')).status).toBe(200);
    } finally {
      await h.close();
    }
  });

  it('retains exactly eight idle sockets and closes a ninth before any header deadline', async () => {
    const p = ports(),
      h = new ChannelPolicyReadHttp(p, bearer),
      e = await h.start();
    const clients: ReturnType<typeof connect>[] = [];
    const started = performance.now(),
      admissionDeadline = started + 500;
    const beforeHeaderExpiry = async (predicate: () => boolean): Promise<void> => {
      while (!predicate()) {
        if (performance.now() >= admissionDeadline)
          throw new Error('socket_cap_not_observed_before_header_expiry');
        await delay(1);
      }
    };
    try {
      for (let n = 0; n < 8; n++) {
        const socket = connect(e);
        socket.on('error', () => undefined);
        clients.push(socket);
      }
      await beforeHeaderExpiry(() => h.metrics().sockets === 8);
      expect(h.metrics()).toMatchObject({ sockets: 8, handlers: 0, completed: 0, rejected: 0 });
      let ninthClosed = false;
      const ninth = connect(e);
      ninth.on('error', () => undefined);
      ninth.once('close', () => {
        ninthClosed = true;
      });
      clients.push(ninth);
      await beforeHeaderExpiry(() => ninthClosed);
      expect(h.metrics()).toMatchObject({ sockets: 8, handlers: 0, completed: 0, rejected: 0 });
      expect(p.discover).not.toHaveBeenCalled();
      expect(p.prepared).not.toHaveBeenCalled();
      await h.close();
      await beforeHeaderExpiry(() => clients.every((socket) => socket.closed));
      expect(performance.now() - started).toBeLessThan(900);
      expect(h.metrics()).toMatchObject({
        sockets: 0,
        handlers: 0,
        completed: 0,
        rejected: 0,
        closing: true,
      });
    } finally {
      clients.forEach((socket) => socket.destroy());
      await h.close();
    }
  });

  it('expires incomplete headers using an absolute socket timer', async () => {
    const p = ports(),
      h = new ChannelPolicyReadHttp(p, bearer),
      e = await h.start();
    const socket = connect(e);
    socket.on('error', () => undefined);
    const closed = new Promise<void>((resolve) => socket.once('close', () => resolve()));
    socket.write('POST /v1/policy/discovery HTTP/1.1\r\nHost:');
    try {
      await Promise.race([
        closed,
        delay(1800).then(() => {
          throw new Error('header_deadline_not_enforced');
        }),
      ]);
      expect(p.discover).not.toHaveBeenCalled();
      await until(() => h.metrics().sockets === 0);
      expect(h.metrics().sockets).toBe(0);
    } finally {
      socket.destroy();
      await h.close();
    }
  });
  it('contains hostile own-domain code accessors without reflecting dependency text', async () => {
    const p = ports(),
      h = new ChannelPolicyReadHttp(p, bearer),
      e = await h.start();
    const error = new SourceReadError('capacity');
    Object.defineProperty(error, 'code', {
      get: () => {
        throw new Error('private_sentinel');
      },
    });
    p.discover.mockRejectedValueOnce(error);
    try {
      const failed = await exchange(e, '/v1/policy/discovery');
      expect(failed.status).toBe(503);
      expect(failed.body.toString()).toBe(
        '{"schemaVersion":1,"status":"unavailable","code":"unavailable"}',
      );
      expect((await exchange(e, '/v1/policy/discovery')).status).toBe(200);
    } finally {
      await h.close();
    }
  });
});
