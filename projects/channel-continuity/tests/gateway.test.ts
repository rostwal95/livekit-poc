/** Actual loopback socket/lifecycle tests with explicitly mocked persistence ports. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { request as httpRequest } from 'node:http';
import { connect } from 'node:net';
import { randomUUID } from 'node:crypto';
const calls = vi.hoisted(() => ({
  accept: vi.fn(),
  eligible: vi.fn(),
  step: vi.fn(),
  inspect: vi.fn(),
  inboxClose: vi.fn(),
  dispatcherClose: vi.fn(),
}));
const native = vi.hoisted(() => ({ servers: [] as import('node:http').Server[] }));
vi.mock('node:http', async (importOriginal) => {
  const original = await importOriginal<typeof import('node:http')>();
  return {
    ...original,
    createServer: (...args: Parameters<typeof original.createServer>) => {
      const server = original.createServer(...args);
      native.servers.push(server);
      return server;
    },
  };
});
vi.mock('../src/postgres.js', async (importOriginal) => {
  const original = await importOriginal<typeof import('../src/postgres.js')>();
  return {
    ...original,
    ChannelInbox: class {
      acceptSms = calls.accept;
      close = calls.inboxClose;
    },
  };
});
vi.mock('../src/dispatch.js', () => ({
  ChannelDispatcher: class {
    eligible = calls.eligible;
    step = calls.step;
    inspect = calls.inspect;
    close = calls.dispatcherClose;
  },
}));
import { ChannelGateway, type GatewayEndpoint } from '../src/gateway.js';
import { ChannelError } from '../src/public-types.js';
import { createFakeSmsIntegration, signFakeSms, WebhookError } from '../src/security.js';
const TOKEN = 'synthetic-' + 'a'.repeat(40),
  ID = randomUUID();
const PROVIDER = { tenantId: 'tenant-a', provider: 'fake_sms', providerAccountId: 'carrier-a' };
const integration = createFakeSmsIntegration(PROVIDER, Buffer.alloc(32, 1));
const receipt = {
  receiptId: ID,
  eventId: 'event',
  messageId: 'message',
  acceptanceSequence: '1',
  acceptedAt: '2026-11-10T00:00:00.000Z',
};
const gateways: ChannelGateway[] = [];
function gateway(options = {}, accountCount = 1) {
  const g = new ChannelGateway({
    database: {
      host: '127.0.0.1',
      port: 5432,
      database: 'livekit_lab',
      user: 'livekit_lab',
      password: 'synthetic',
      schema: 'p2_inbox_' + 'a'.repeat(32),
    },
    integration,
    accounts: Array.from({ length: accountCount }, (_, index) => ({
      token: index === 0 ? TOKEN : 'synthetic-' + index + 'b'.repeat(40),
      tenantId: 'tenant-a',
      accountId: 'account-' + index,
      conversationId: 'conversation-' + index,
      caseId: 'case-' + index,
    })),
    ports: {
      cases: {
        async inspect(input) {
          return { ...input, revision: '1', source: 'synthetic_read_only' };
        },
      },
      agent: {
        async prepare(input) {
          return {
            kind: 'investigation',
            source: 'scripted',
            caseRevision: input.currentCase.revision,
          };
        },
      },
      operations: {
        capabilities: 'stable_idempotency_and_lookup',
        async lookup() {
          return { status: 'absent' };
        },
        async accept() {
          throw new Error('unused');
        },
      },
    },
    options: { pollMs: 20, ...options },
  });
  gateways.push(g);
  return g;
}
function deferred() {
  let resolve!: () => void;
  return {
    promise: new Promise<void>((done) => {
      resolve = done;
    }),
    resolve: () => resolve(),
  };
}
const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 30));
function call(
  endpoint: GatewayEndpoint,
  method: string,
  path: string,
  raw?: Uint8Array,
  extra: Record<string, string> = {},
): Promise<{ status: number; body: Record<string, unknown> }> {
  return new Promise((resolve, reject) => {
    const request = httpRequest(
      {
        host: endpoint.host,
        port: endpoint.port,
        path,
        method,
        headers: {
          Connection: 'close',
          ...(raw
            ? { 'Content-Type': 'application/json', 'Content-Length': String(raw.length) }
            : {}),
          ...extra,
        },
      },
      (response) => {
        const chunks: Buffer[] = [];
        response.on('data', (data: Buffer) => chunks.push(data));
        response.on('end', () => {
          try {
            resolve({
              status: response.statusCode!,
              body: JSON.parse(Buffer.concat(chunks).toString()) as Record<string, unknown>,
            });
          } catch (error) {
            reject(error);
          }
        });
      },
    );
    request.on('error', reject);
    request.end(raw);
  });
}
function sms() {
  return signFakeSms(
    {
      schemaVersion: 1,
      eventId: 'event',
      messageId: 'message',
      senderId: 'sender',
      body: 'Test',
      occurredAt: '2026-11-10T00:00:00.000Z',
    },
    Buffer.alloc(32, 1),
    Math.floor(Date.now() / 1000),
    PROVIDER,
  );
}
function post(endpoint: GatewayEndpoint) {
  const signed = sms();
  return call(endpoint, 'POST', '/webhooks/fake-sms', signed.raw, {
    'X-P2-Timestamp': signed.headers.timestamp,
    'X-P2-Signature': signed.headers.signature,
  });
}
beforeEach(() => {
  native.servers.length = 0;
  for (const value of Object.values(calls)) value.mockReset();
  calls.accept.mockResolvedValue({ receipt, replayed: false });
  calls.eligible.mockResolvedValue([]);
  calls.step.mockResolvedValue({ status: 'dispatched' });
  calls.inspect.mockResolvedValue({ receiptId: ID, state: 'pending' });
  calls.inboxClose.mockResolvedValue(undefined);
  calls.dispatcherClose.mockResolvedValue(undefined);
});
afterEach(async () => {
  for (const g of gateways) await g.close();
  gateways.length = 0;
});
describe('bounded loopback gateway', () => {
  it('preflights before binding and committed raw intake precedes the actual ACK', async () => {
    const wait = deferred();
    calls.accept.mockImplementation(async () => {
      await wait.promise;
      return { receipt, replayed: false };
    });
    const g = gateway(),
      endpoint = await g.listen();
    let complete = false;
    const pending = post(endpoint).then((value) => {
      complete = true;
      return value;
    });
    await tick();
    expect(complete).toBe(false);
    expect(calls.accept).toHaveBeenCalledOnce();
    wait.resolve();
    const result = await pending;
    expect(result.status).toBe(200);
    expect(result.body.receipt).toEqual(receipt);
    const args = calls.accept.mock.calls[0]!;
    expect(args[0]).toBeInstanceOf(Uint8Array);
    expect(Object.keys(args[1] as object)).toEqual(['timestamp', 'signature']);
  });
  it('holds owned intake and polling after flushed ACK until trusted test barrier settles', async () => {
    const hold = deferred(),
      reached = deferred();
    const g = gateway({
        harnessAfterAcknowledgement: async () => {
          reached.resolve();
          await hold.promise;
        },
      }),
      endpoint = await g.listen();
    calls.eligible.mockResolvedValue([ID]);
    const accepted = await post(endpoint);
    expect(accepted.status).toBe(200);
    await reached.promise;
    await tick();
    expect(calls.step).not.toHaveBeenCalled();
    expect(g.metrics().intakes).toBe(1);
    hold.resolve();
    await tick();
    expect(calls.step).toHaveBeenCalledWith(TOKEN, ID);
  });
  it('normal ingress cannot starve already committed persisted work', async () => {
    const hold = deferred(),
      g = gateway(),
      endpoint = await g.listen();
    calls.accept.mockImplementation(async () => {
      await hold.promise;
      return { receipt, replayed: false };
    });
    const ingress = post(endpoint);
    for (let i = 0; i < 20 && g.metrics().intakes !== 1; i++) await tick();
    calls.eligible.mockResolvedValue([ID]);
    await tick();
    expect(calls.step).toHaveBeenCalledWith(TOKEN, ID);
    expect(g.metrics().intakes).toBe(1);
    hold.resolve();
    await ingress;
  });
  it('startup caller deadline retains actual preflight ownership until it settles', async () => {
    const hold = deferred();
    calls.eligible.mockImplementationOnce(async () => {
      await hold.promise;
      return [];
    });
    const g = gateway({ startupMs: 30, cleanupMs: 30 });
    await expect(g.listen()).rejects.toMatchObject({ code: 'storage_unavailable' });
    await expect(g.close()).rejects.toMatchObject({ code: 'cleanup_incomplete' });
    expect(calls.dispatcherClose).not.toHaveBeenCalled();
    hold.resolve();
    await tick();
    await g.close();
    expect(g.metrics().sockets).toBe(0);
  });
  it('a delayed listening event cannot leave a failed-start serving socket', async () => {
    const g = gateway({ startupMs: 30 });
    const server = native.servers.at(-1)!;
    let port = 0;
    server.prependOnceListener('listening', () => {
      const address = server.address();
      if (address && typeof address !== 'string') port = address.port;
      const until = performance.now() + 60;
      while (performance.now() < until) {
        /* trusted controlled event-loop delay */
      }
    });
    await expect(g.listen()).rejects.toMatchObject({ code: 'storage_unavailable' });
    await g.close();
    expect(port).toBeGreaterThan(0);
    expect(g.metrics().sockets).toBe(0);
    await expect(call({ host: '127.0.0.1', port }, 'GET', '/health')).rejects.toMatchObject({
      code: 'ECONNREFUSED',
    });
  });
  it('tick deadline stops further database scans and next tick rotates to another account', async () => {
    let scans = 0;
    calls.eligible.mockImplementation(async () => {
      scans++;
      if (scans === 4) {
        const until = performance.now() + 2050;
        while (performance.now() < until) {
          /* one controlled slow scan */
        }
      }
      return [];
    });
    const g = gateway({ pollMs: 50 }, 3);
    await g.listen();
    expect(scans).toBe(4);
    await new Promise<void>((resolve) => setTimeout(resolve, 70));
    expect(calls.eligible.mock.calls[4]![0]).toBe('synthetic-1' + 'b'.repeat(40));
    expect(scans).toBeGreaterThan(4);
    await g.close();
  });
  it('rejects missing signatures, framing, oversized bodies, routes and forged read credentials before use', async () => {
    const g = gateway(),
      endpoint = await g.listen();
    expect((await call(endpoint, 'POST', '/webhooks/fake-sms', Buffer.from('{}'))).status).toBe(
      401,
    );
    expect(
      (
        await call(endpoint, 'POST', '/webhooks/fake-sms', Buffer.alloc(32769), {
          'X-P2-Timestamp': '1',
          'X-P2-Signature': 'x',
        })
      ).status,
    ).toBe(413);
    expect((await call(endpoint, 'GET', '/receipts/' + ID)).status).toBe(401);
    expect((await call(endpoint, 'GET', '/unknown')).status).toBe(404);
    expect(calls.accept).not.toHaveBeenCalled();
    expect(calls.inspect).not.toHaveBeenCalled();
    expect((await call(endpoint, 'GET', '/health')).body.business_execution).toBe(false);
  });
  it('reports sanitized known/unknown failures and continues with subsequent input', async () => {
    const events: unknown[] = [],
      g = gateway({
        observer: (event: unknown) => {
          events.push(event);
          throw new Error('PRIVATE_TELEMETRY');
        },
      }),
      endpoint = await g.listen();
    calls.accept
      .mockRejectedValueOnce(new Error('PRIVATE_DATABASE'))
      .mockRejectedValueOnce(new ChannelError('IdentityConflict'))
      .mockRejectedValueOnce(new WebhookError());
    expect((await post(endpoint)).body.code).toBe('storage_unavailable');
    expect((await post(endpoint)).body.code).toBe('identity_conflict');
    expect((await post(endpoint)).body.code).toBe('unauthorized');
    expect((await post(endpoint)).status).toBe(200);
    expect(JSON.stringify(events)).not.toContain('PRIVATE_');
    expect(g.metrics().telemetryFailures).toBeGreaterThan(0);
  });
  it('holds four actual intake calls, rejects excess, then useful work progresses', async () => {
    const hold = deferred(),
      g = gateway(),
      endpoint = await g.listen();
    calls.accept.mockImplementation(async () => {
      await hold.promise;
      return { receipt, replayed: false };
    });
    const pending = Array.from({ length: 4 }, () => post(endpoint));
    for (let i = 0; i < 20 && g.metrics().active !== 4; i++) await tick();
    expect(g.metrics().active).toBe(4);
    expect((await post(endpoint)).status).toBe(429);
    expect(calls.accept).toHaveBeenCalledTimes(4);
    hold.resolve();
    await Promise.all(pending);
    expect((await post(endpoint)).status).toBe(200);
  });
  it('client disconnect does not release an accepted in-flight database call early', async () => {
    const hold = deferred(),
      g = gateway(),
      endpoint = await g.listen();
    calls.accept.mockImplementation(async () => {
      await hold.promise;
      return { receipt, replayed: false };
    });
    const signed = sms(),
      req = httpRequest(
        {
          host: endpoint.host,
          port: endpoint.port,
          path: '/webhooks/fake-sms',
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Content-Length': String(signed.raw.length),
            'X-P2-Timestamp': signed.headers.timestamp,
            'X-P2-Signature': signed.headers.signature,
          },
        },
        () => undefined,
      );
    req.on('error', () => undefined);
    req.end(signed.raw);
    for (let i = 0; i < 20 && calls.accept.mock.calls.length === 0; i++) await tick();
    req.destroy();
    await tick();
    expect(g.metrics().active).toBe(1);
    expect(g.metrics().intakes).toBe(1);
    hold.resolve();
    await tick();
    expect(g.metrics().active).toBe(0);
    expect((await post(endpoint)).status).toBe(200);
  });
  it('caps actual connections and expires idle partial headers with later useful progress', async () => {
    const g = gateway(),
      endpoint = await g.listen(),
      sockets = await Promise.all(
        Array.from(
          { length: 16 },
          () =>
            new Promise<ReturnType<typeof connect>>((resolve, reject) => {
              const s = connect(endpoint.port, endpoint.host, () => resolve(s));
              s.on('error', reject);
            }),
        ),
      );
    for (let i = 0; i < 20 && g.metrics().sockets !== 16; i++) await tick();
    expect(g.metrics().sockets).toBe(16);
    await new Promise<void>((resolve, reject) => {
      const extra = connect(endpoint.port, endpoint.host);
      extra.on('error', reject);
      extra.once('close', () => resolve());
    });
    await Promise.all(
      sockets.map((s) => new Promise<void>((resolve) => s.once('close', () => resolve()))),
    );
    for (let i = 0; i < 20 && g.metrics().sockets !== 0; i++) await tick();
    expect(g.metrics().sockets).toBe(0);
    expect((await call(endpoint, 'GET', '/health')).status).toBe(200);
  });
  it('rejects duplicate headers/pipelining and retires actual sockets before close', async () => {
    const g = gateway(),
      endpoint = await g.listen();
    await new Promise<void>((resolve, reject) => {
      const socket = connect(endpoint.port, endpoint.host, () =>
        socket.write('GET /health HTTP/1.1\r\nHost: x\r\nX-A: one\r\nX-A: two\r\n\r\n'),
      );
      socket.on('error', reject);
      let raw = '';
      socket.on('data', (data) => {
        raw += data.toString();
      });
      socket.on('close', () => {
        expect(raw).toContain('400');
        resolve();
      });
    });
    await g.close();
    expect(g.metrics().sockets).toBe(0);
    expect(g.metrics().handlers).toBe(0);
    expect(g.metrics().driver).toBe(0);
  });
  it('owns a held hook through incomplete close, then completes real cleanup after release', async () => {
    const hold = deferred(),
      reached = deferred();
    const g = gateway({
        cleanupMs: 30,
        harnessAfterAcknowledgement: async () => {
          reached.resolve();
          await hold.promise;
        },
      }),
      endpoint = await g.listen();
    await post(endpoint);
    await reached.promise;
    await expect(g.close()).rejects.toMatchObject({ code: 'cleanup_incomplete' });
    expect(g.metrics().intakes).toBe(1);
    hold.resolve();
    await tick();
    await g.close();
    expect(g.metrics().active).toBe(0);
    expect(calls.inboxClose).toHaveBeenCalledOnce();
  });
  it('owns concurrent bind/close and failed preflight without advertising ready state', async () => {
    const hold = deferred();
    calls.eligible.mockImplementationOnce(async () => {
      await hold.promise;
      return [];
    });
    const g = gateway(),
      start = g.listen();
    const rejected = expect(start).rejects.toMatchObject({ code: 'closing' });
    await expect(g.listen()).rejects.toMatchObject({ code: 'closing' });
    const closed = g.close();
    hold.resolve();
    await rejected;
    await closed;
    const bad = gateway();
    calls.eligible.mockRejectedValueOnce(new ChannelError('UpgradeRequired'));
    await expect(bad.listen()).rejects.toMatchObject({ code: 'UpgradeRequired' });
    await bad.close();
  });
  it('bounds configuration and uses only persisted eligible IDs, never accepted-response memory as a queue', async () => {
    expect(() => gateway({ pollMs: 0 })).toThrow();
    const g = gateway({ batchSize: 1 }),
      endpoint = await g.listen();
    await post(endpoint);
    await tick();
    expect(calls.step).not.toHaveBeenCalled();
    calls.eligible.mockResolvedValue([ID]);
    await tick();
    expect(calls.step).toHaveBeenCalledWith(TOKEN, ID);
  });
});
