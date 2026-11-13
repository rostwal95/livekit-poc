/** Actual loopback framing and lifecycle; receiver ports are explicit fakes, with no PG. */
import { createHash, randomUUID } from 'node:crypto';
import { createServer, request, Server } from 'node:http';
import { connect, type Socket } from 'node:net';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  encodeResultIntent,
  ResultReceiverError,
  type P1ResultIntent,
  type P1ResultReceipt,
} from '@livekit-ecosystem/channel-continuity/result-receiver';
import { ChannelPolicyResultHttp } from '../src/result-http.js';
const token = 'p'.repeat(43);
const owned: ChannelPolicyResultHttp[] = [];
function intent(): P1ResultIntent {
  const raw = Buffer.from('Opaque café 🧭 result');
  return {
    delivery_id: randomUUID(),
    scope: { tenant_id: 'tenant', account_id: 'account' },
    work_id: randomUUID(),
    attempt_id: randomUUID(),
    result_sha256: createHash('sha256').update(raw).digest('hex'),
    receiver_id: randomUUID(),
    recipient_id: 'recipient',
    body: raw.toString('base64'),
    prepared_at_ms: 1900000000000,
  };
}
function receipt(i: P1ResultIntent): P1ResultReceipt {
  return {
    delivery_id: i.delivery_id,
    receipt_id: randomUUID(),
    receiver_id: i.receiver_id,
    recipient_id: i.recipient_id,
    result_sha256: i.result_sha256,
    accepted_at_ms: 1900000000001,
  };
}
function fixture(cleanup = 40) {
  const accepted = vi.fn(async (_token: string, value: P1ResultIntent) => receipt(value));
  const found = vi.fn(
    async (_token: string, _value: P1ResultIntent): Promise<P1ResultReceipt | null> => null,
  );
  const server = new ChannelPolicyResultHttp({ accept: accepted, find: found }, token, cleanup);
  owned.push(server);
  return { server, accepted, found };
}
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
function post(
  port: number,
  raw: Buffer,
  path = '/v1/p2-result-receiver/accept',
  headers: Record<string, string | string[]> = {},
): Promise<{
  status: number;
  headers: Readonly<Record<string, unknown>>;
  raw: Buffer;
  value: unknown;
}> {
  return new Promise((resolve, reject) => {
    const req = request(
      {
        host: '127.0.0.1',
        port,
        path,
        method: 'POST',
        agent: false,
        headers: {
          authorization: 'Bearer ' + token,
          'content-type': 'application/json',
          'content-length': raw.length,
          connection: 'close',
          ...headers,
        },
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on('data', (chunk) => chunks.push(Buffer.from(chunk)));
        res.once('error', reject);
        res.once('end', () => {
          try {
            const body = Buffer.concat(chunks);
            resolve({
              status: res.statusCode!,
              headers: res.headers,
              raw: body,
              value: JSON.parse(body.toString()),
            });
          } catch (e) {
            reject(e);
          }
        });
      },
    );
    req.once('error', reject);
    req.setTimeout(1500, () => req.destroy(new Error('TEST_TIMEOUT')));
    req.end(raw);
  });
}
async function socket(port: number): Promise<Socket> {
  return new Promise((resolve, reject) => {
    const s = connect({ host: '127.0.0.1', port });
    s.on('error', () => {});
    s.once('connect', () => resolve(s));
    s.once('error', reject);
  });
}
afterEach(async () => {
  for (const owner of owned.splice(0)) await owner.close().catch(() => {});
  vi.restoreAllMocks();
});
describe('P3-compatible stable result HTTP', () => {
  it('constructs without binding or receiving and closes before start', async () => {
    const listen = vi.spyOn(Server.prototype, 'listen'),
      x = fixture();
    expect(listen).not.toHaveBeenCalled();
    expect(x.accepted).not.toHaveBeenCalled();
    await x.server.close();
    expect(x.server.metrics()).toMatchObject({ handlers: 0, sockets: 0, closing: true });
    await expect(x.server.start()).rejects.toMatchObject({ code: 'Closed' });
  });
  it('matches the frozen canonical accept/find wire and response headers', async () => {
    const x = fixture(),
      i = intent(),
      r = receipt(i);
    x.accepted.mockResolvedValue(r);
    x.found.mockResolvedValue(r);
    const e = await x.server.start();
    for (const operation of ['accept', 'find']) {
      const answer = await post(
        e.port,
        Buffer.from(encodeResultIntent(i)),
        '/v1/p2-result-receiver/' + operation,
        { accept: 'application/json', 'accept-encoding': 'gzip, deflate' },
      );
      expect(answer).toMatchObject({
        status: 200,
        value: { schemaVersion: 1, status: 'accepted', receipt: r },
        headers: {
          'content-type': 'application/json',
          'cache-control': 'no-store',
          connection: 'close',
        },
      });
      expect(answer.headers['content-length']).toBe(String(answer.raw.length));
      expect(answer.headers['transfer-encoding']).toBeUndefined();
      expect(answer.headers['content-encoding']).toBeUndefined();
    }
    expect(x.accepted).toHaveBeenCalledWith(token, i);
    expect(x.found).toHaveBeenCalledWith(token, i);
    expect(x.server.metrics()).toMatchObject({ completed: 2, handlers: 0 });
  });
  it('returns missing only for known find and contains an impossible null accept', async () => {
    const x = fixture(),
      i = intent(),
      e = await x.server.start();
    expect(
      await post(e.port, Buffer.from(encodeResultIntent(i)), '/v1/p2-result-receiver/find'),
    ).toMatchObject({ status: 200, value: { schemaVersion: 1, status: 'missing', receipt: null } });
    x.accepted.mockResolvedValue(null as unknown as P1ResultReceipt);
    expect(await post(e.port, Buffer.from(encodeResultIntent(i)))).toMatchObject({
      status: 503,
      value: { error: 'Unavailable' },
    });
  });
  it('rejects wrong bearer, unknown/proxy/duplicate framing and private native-read routes before receiver entry', async () => {
    const x = fixture(),
      e = await x.server.start(),
      raw = Buffer.from(encodeResultIntent(intent()));
    for (const headers of [
      { authorization: 'Bearer ' + 'x'.repeat(43) },
      { 'x-forwarded-host': 'attacker' },
      { authorization: ['Bearer ' + token, 'Bearer ' + token] },
      { 'content-encoding': 'gzip' },
    ]) {
      const answer = await post(e.port, raw, '/v1/p2-result-receiver/accept', headers);
      expect([400, 403]).toContain(answer.status);
    }
    expect(await post(e.port, raw, '/v1/p2-result-receiver/native-read')).toMatchObject({
      status: 400,
    });
    expect(x.accepted).not.toHaveBeenCalled();
    expect(x.found).not.toHaveBeenCalled();
  });
  it('rejects noncanonical/duplicate/malformed UTF-8/oversized intents before receiver entry', async () => {
    const x = fixture(),
      e = await x.server.start(),
      raw = encodeResultIntent(intent());
    const inputs = [
      Buffer.from(raw + ' '),
      Buffer.from('{"delivery_id":"duplicate",' + raw.slice(1)),
      Buffer.from([0xff, 0xfe]),
      Buffer.alloc(16385, 0x20),
    ];
    for (const body of inputs)
      expect(await post(e.port, body)).toMatchObject({
        status: 400,
        value: { error: 'InvalidCommand' },
      });
    expect(x.accepted).not.toHaveBeenCalled();
  });
  it('revalidates receiver receipt joins and hides dependency messages and accessors', async () => {
    const x = fixture(),
      i = intent(),
      e = await x.server.start(),
      raw = Buffer.from(encodeResultIntent(i));
    x.accepted.mockResolvedValue({ ...receipt(i), result_sha256: '0'.repeat(64) });
    expect(await post(e.port, raw)).toMatchObject({ status: 503, value: { error: 'Unavailable' } });
    const getter = vi.fn(() => {
        throw new Error('PRIVATE_GETTER');
      }),
      error = new ResultReceiverError('Unavailable');
    Object.defineProperty(error, 'code', { get: getter });
    x.accepted.mockRejectedValue(error);
    const answer = await post(e.port, raw);
    expect(answer).toMatchObject({
      status: 503,
      value: { schemaVersion: 1, status: 'error', error: 'Unavailable' },
    });
    expect(answer.raw.toString()).not.toContain('PRIVATE');
    expect(getter).not.toHaveBeenCalled();
  });
  it.each([
    ['AccessDenied', 403],
    ['IdentityConflict', 409],
    ['Overloaded', 429],
    ['AcknowledgementUnknown', 503],
    ['Unavailable', 503],
  ] as const)('keeps finite %s receiver errors on the frozen wire', async (code, status) => {
    const x = fixture(),
      e = await x.server.start();
    x.accepted.mockRejectedValue(new ResultReceiverError(code));
    expect(await post(e.port, Buffer.from(encodeResultIntent(intent())))).toMatchObject({
      status,
      value: { schemaVersion: 1, status: 'error', error: code },
    });
  });
  it('retains four complete handler lifetimes after client abandonment and permits close retry only after settlement', async () => {
    const x = fixture(),
      held = deferred<P1ResultReceipt>(),
      i = intent();
    x.accepted.mockReturnValue(held.promise);
    const e = await x.server.start();
    const sockets: Socket[] = [];
    try {
      const raw = Buffer.from(encodeResultIntent(i));
      for (let n = 0; n < 4; n++) {
        const s = await socket(e.port);
        s.write(
          Buffer.concat([
            Buffer.from(
              'POST /v1/p2-result-receiver/accept HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer ' +
                token +
                '\r\nContent-Type: application/json\r\nContent-Length: ' +
                raw.length +
                '\r\nConnection: close\r\n\r\n',
            ),
            raw,
          ]),
        );
        sockets.push(s);
      }
      await vi.waitFor(() => expect(x.accepted).toHaveBeenCalledTimes(4));
      expect(await post(e.port, raw)).toMatchObject({
        status: 429,
        value: { error: 'Overloaded' },
      });
      for (const s of sockets) s.destroy();
      await vi.waitFor(() => expect(x.server.metrics().sockets).toBe(0));
      await expect(x.server.close()).rejects.toMatchObject({ code: 'CleanupIncomplete' });
      expect(x.server.metrics().handlers).toBe(4);
      held.resolve(receipt(i));
      await vi.waitFor(() => expect(x.server.metrics().handlers).toBe(0));
      await x.server.close();
      expect(x.server.metrics()).toMatchObject({ handlers: 0, sockets: 0 });
    } finally {
      for (const s of sockets) s.destroy();
      held.resolve(receipt(i));
    }
  });
  it('owns eight partial-header sockets, denies a ninth, and drains actual socket close observers', async () => {
    const x = fixture(),
      e = await x.server.start(),
      sockets: Socket[] = [];
    try {
      for (let n = 0; n < 8; n++) {
        const s = await socket(e.port);
        s.write('POST /v1/p2-result-receiver/accept HTTP/1.1\r\n');
        sockets.push(s);
      }
      await vi.waitFor(() => expect(x.server.metrics().sockets).toBe(8));
      const ninth = await socket(e.port);
      const dropped = new Promise<void>((r) => ninth.once('close', () => r()));
      ninth.resume();
      await dropped;
      await x.server.close();
      expect(x.server.metrics()).toMatchObject({ handlers: 0, sockets: 0 });
      expect(x.accepted).not.toHaveBeenCalled();
    } finally {
      for (const s of sockets) s.destroy();
    }
  });
  it('cleans failed bind listeners and allows a useful fresh start retry', async () => {
    const blocker = createServer();
    await new Promise<void>((r) => blocker.listen(0, '127.0.0.1', () => r()));
    const address = blocker.address();
    if (!address || typeof address === 'string') throw new Error('TEST_ADDRESS');
    const x = fixture();
    await expect(x.server.start(address.port)).rejects.toMatchObject({ code: 'Unavailable' });
    await new Promise<void>((r, reject) => blocker.close((e) => (e ? reject(e) : r())));
    const e = await x.server.start(address.port);
    expect(e.port).toBe(address.port);
    expect(
      await post(e.port, Buffer.from(encodeResultIntent(intent())), '/v1/p2-result-receiver/find'),
    ).toMatchObject({ status: 200 });
  });
  it('retains close across a late actual bind and drains the eventual listener', async () => {
    const original = Server.prototype.listen;
    let server: Server | undefined,
      args: unknown[] = [];
    const delayed = vi.spyOn(Server.prototype, 'listen').mockImplementation(function (
      this: Server,
      ...input: unknown[]
    ) {
      server = this;
      args = input;
      return this;
    });
    const x = fixture(),
      starting = x.server.start();
    await expect(x.server.close()).rejects.toMatchObject({ code: 'CleanupIncomplete' });
    delayed.mockRestore();
    if (!server) throw new Error('TEST_BIND');
    Reflect.apply(original, server, args);
    const endpoint = await starting;
    await x.server.close();
    expect(x.server.metrics()).toMatchObject({ sockets: 0, handlers: 0 });
    await expect(
      post(endpoint.port, Buffer.from(encodeResultIntent(intent()))),
    ).rejects.toBeDefined();
  });
  it('does not admit a late header when its timer callback has not yet run', async () => {
    const now = performance.now.bind(performance);
    let offset = 0;
    vi.spyOn(performance, 'now').mockImplementation(() => now() + offset);
    const x = fixture(),
      e = await x.server.start(),
      s = await socket(e.port);
    try {
      const closed = new Promise<void>((resolve) => s.once('close', () => resolve()));
      s.resume();
      offset = 2000;
      s.write(
        'POST /v1/p2-result-receiver/accept HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 2\r\n\r\n{}',
      );
      await closed;
      expect(x.accepted).not.toHaveBeenCalled();
      expect(x.server.metrics().handlers).toBe(0);
    } finally {
      s.destroy();
      offset = 0;
    }
  });
  it('rejects receiver accessors before server construction without evaluating them', () => {
    const getter = vi.fn(() => {
      throw new Error('PRIVATE_GETTER');
    });
    const receiver = { find: async () => null };
    Object.defineProperty(receiver, 'accept', { get: getter, enumerable: true });
    expect(() => new ChannelPolicyResultHttp(receiver as never, token)).toThrow('InvalidCommand');
    expect(getter).not.toHaveBeenCalled();
  });
});
