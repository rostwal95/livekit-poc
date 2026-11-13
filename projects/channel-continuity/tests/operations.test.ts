import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  request as httpRequest,
  createServer,
  ClientRequest,
  ServerResponse,
  type IncomingHttpHeaders,
} from 'node:http';
import type { Socket } from 'node:net';
import { setTimeout as delay } from 'node:timers/promises';
import type { ChannelInbox } from '../src/postgres.js';
import { OperationsReader, OperationsReadServer, OperationsHttpClient } from '../src/operations.js';
import { RehydrationStore } from '../src/rehydration-store.js';
import { currentCase, RehydrationError } from '../src/rehydration-types.js';
import {
  registerRehydrationInbox,
  type RehydrationInboxAccess,
  type RehydrationTx,
} from '../src/rehydration-access.js';
import { createFakeSmsIntegration } from '../src/security.js';
import { OperationsTelemetry } from '../src/operations-telemetry.js';
import {
  OperationsError,
  operationsJson,
  operationsMetrics,
  operationsRecord,
  operationsTelemetrySnapshot,
  OPERATIONS_METRICS,
} from '../src/operations-types.js';

const one = '11111111-1111-4111-8111-111111111111';
const two = '22222222-2222-4222-8222-222222222222';
afterEach(() => vi.useRealTimers());
const fakeClock = () =>
  vi.useFakeTimers({ toFake: ['Date', 'performance', 'setTimeout', 'clearTimeout'] });

describe('operations schemas and safe diagnostics', () => {
  it('contains unsupported error codes and freezes the role vocabulary', () => {
    const error = new OperationsError('PRIVATE_DEPENDENCY_DETAIL' as never);
    expect(error.code).toBe('unavailable');
    expect(() => Object.defineProperty(error, 'code', { get: () => 'private' })).toThrow();
    expect(Object.isFrozen(OPERATIONS_METRICS)).toBe(true);
    expect(Object.isFrozen(OPERATIONS_METRICS.inbox)).toBe(true);
  });
  it('never invokes record accessors or accepts array/prototype selectors', () => {
    let called = 0;
    expect(() =>
      operationsRecord(
        {
          get code() {
            called++;
            return 'private';
          },
        },
        ['code'],
      ),
    ).toThrow(OperationsError);
    expect(called).toBe(0);
    expect(() => operationsRecord([], [])).toThrow(OperationsError);
    expect(() => operationsRecord(Object.create({ code: 'known' }), ['code'])).toThrow(
      OperationsError,
    );
  });
  it.each(['{"x":1,"x":2}', '{"nested":{"x":1,"x":2}}', '{"x":1e999}', '{"x":"\\ud800"}'])(
    'rejects ambiguous/nonfinite/nonUnicode JSON %s',
    (raw) => {
      expect(() => operationsJson(new TextEncoder().encode(raw), 1000)).toThrow(OperationsError);
    },
  );
  it('rejects byte overflow before decoding and preserves exact Unicode strings', () => {
    const raw = new TextEncoder().encode('{"text":"界🙂"}');
    expect(operationsJson(raw, raw.length)).toEqual({ text: '界🙂' });
    expect(() => operationsJson(raw, raw.length - 1)).toThrow(OperationsError);
    expect(() => operationsJson(new Uint8Array([0xc3, 0x28]), 2)).toThrow(OperationsError);
  });
  it('rejects unknown/nonfinite metric names and values without coercing getters', () => {
    expect(() => operationsMetrics('inbox', { arbitrary_customer_id: 1 })).toThrow(OperationsError);
    for (const value of [NaN, Infinity, -1, -0, 1.5, Number.MAX_SAFE_INTEGER + 1])
      expect(() => operationsMetrics('inbox', { active: value })).toThrow(OperationsError);
    let called = 0;
    expect(() =>
      operationsMetrics('inbox', {
        get active() {
          called++;
          return 1;
        },
      }),
    ).toThrow(OperationsError);
    expect(called).toBe(0);
  });
});

describe('actual callback/getter ownership and read-span producers', () => {
  it('retains eight returned sink promises through incomplete close and releases only on actual settlement', async () => {
    fakeClock();
    const releases: (() => void)[] = [];
    const telemetry = new OperationsTelemetry(
      [],
      () => new Promise<void>((resolve) => releases.push(resolve)),
    );
    const observe = telemetry.observer('inbox');
    for (let n = 0; n < 12; n++)
      observe({ event: 'completed', operation: 'inspect', code: 'accepted' });
    expect(releases).toHaveLength(8);
    expect(telemetry.metrics()).toMatchObject({ observerPending: 8, observerDropped: 4 });
    const first = telemetry.close();
    expect(telemetry.close()).toBe(first);
    const rejected = expect(first).rejects.toMatchObject({ code: 'unavailable' });
    await vi.advanceTimersByTimeAsync(1001);
    await rejected;
    expect(telemetry.metrics().observerPending).toBe(8);
    releases.forEach((release) => release());
    await telemetry.close();
    expect(telemetry.metrics().observerPending).toBe(0);
  });
  it('reserves before a reentrant sink and contains sync and async exporter failures', async () => {
    let observer: ReturnType<OperationsTelemetry['observer']>;
    const releases: (() => void)[] = [];
    let calls = 0;
    const telemetry = new OperationsTelemetry([], () => {
      calls++;
      if (calls < 20) observer({ event: 'completed', code: 'known' });
      return new Promise<void>((resolve) => releases.push(resolve));
    });
    observer = telemetry.observer('rehydration');
    observer({ event: 'completed', code: 'known' });
    expect(calls).toBe(8);
    expect(telemetry.metrics().observerPending).toBe(8);
    releases.forEach((release) => release());
    await telemetry.close();
    const broken = new OperationsTelemetry([], () => {
      throw Error('PRIVATE_SINK_SENTINEL');
    });
    broken.observer('inbox')({ event: 'completed', code: 'known' });
    expect(broken.metrics()).toMatchObject({ observerFailures: 1, observerPending: 0 });
    expect(JSON.stringify(broken.snapshot(one))).not.toContain('PRIVATE_SINK_SENTINEL');
    await broken.close();
    const asynchronous = new OperationsTelemetry([], () => Promise.reject(Error('PRIVATE_ASYNC')));
    asynchronous.observer('inbox')({ event: 'completed', code: 'known' });
    await asynchronous.close();
    expect(asynchronous.metrics()).toMatchObject({ observerFailures: 1, observerPending: 0 });
  });
  it('holds one ignored asynchronous getter per source across repeated snapshots', async () => {
    fakeClock();
    let calls = 0;
    let release!: (value: unknown) => void;
    const held = new Promise<unknown>((resolve) => {
      release = resolve;
    });
    const telemetry = new OperationsTelemetry([
      {
        source: 'inbox',
        read: () => {
          calls++;
          return held;
        },
      },
    ]);
    for (let n = 0; n < 20; n++) expect(telemetry.snapshot(one).sources[0]?.state).toBe('pending');
    expect(calls).toBe(1);
    expect(telemetry.metrics().getterPending).toBe(1);
    const closing = telemetry.close();
    const rejected = expect(closing).rejects.toMatchObject({ code: 'unavailable' });
    await vi.advanceTimersByTimeAsync(1001);
    await rejected;
    expect(telemetry.metrics().getterPending).toBe(1);
    release({ accepted: 2, active: 0 });
    await telemetry.close();
    expect(telemetry.metrics().getterPending).toBe(0);
  });
  it('marks getter faults unavailable without substituting zero metrics', async () => {
    const telemetry = new OperationsTelemetry([
      {
        source: 'inbox',
        read: () => {
          throw Error('PRIVATE_GETTER');
        },
      },
    ]);
    const view = telemetry.snapshot(one);
    expect(view.sources[0]).toMatchObject({ state: 'unavailable', values: [] });
    expect(telemetry.metrics().getterFailures).toBe(1);
    expect(JSON.stringify(view)).not.toContain('PRIVATE_GETTER');
    expect(operationsTelemetrySnapshot(view, one)).toEqual(view);
    await telemetry.close();
  });
  it('measures the actual caller span beyond five seconds and keeps the original request correlation outside metric values', async () => {
    fakeClock();
    const telemetry = new OperationsTelemetry();
    const end = telemetry.begin(one, 'context');
    await vi.advanceTimersByTimeAsync(6001);
    end('unknown', 'waiter_abandoned');
    const view = telemetry.snapshot(two),
      span = view.observations[0]!;
    expect(span).toMatchObject({
      kind: 'read_span',
      requestId: one,
      status: 'unknown',
      durationMs: 6001,
    });
    expect(view.scope).toBe('process');
    expect(JSON.stringify(telemetry.metrics())).not.toContain(one);
    expect(operationsTelemetrySnapshot(view, two)).toEqual(view);
    await telemetry.close();
  });
  it('bounds locally retained display observations while continuing useful producer events', async () => {
    const telemetry = new OperationsTelemetry();
    const observer = telemetry.observer('inbox');
    for (let n = 0; n < 50; n++)
      observer({ event: 'completed', operation: 'history', code: 'known' });
    expect(telemetry.snapshot(one).observations).toHaveLength(32);
    expect(telemetry.metrics()).toMatchObject({
      spansRetained: 32,
      observationsDropped: 18,
      observerDropped: 0,
    });
    await telemetry.close();
  });
});

// These socket tests run the real reader/server/client with an explicitly mocked
// persistence snapshot. They do not qualify SQL authorization or storage.
const REF = Object.freeze({
  scope: { tenantId: 'ops-tenant', accountId: 'ops-account' },
  caseId: 'ops-case',
  conversationId: 'ops-conversation',
});
const AUTH = 'Bearer ' + 'A'.repeat(43),
  BINDING = '33333333-3333-4333-8333-333333333333';
function readFixture() {
  const inbox = {} as ChannelInbox;
  const now = new Date().toISOString();
  const grant = {
    ...REF,
    bindingId: BINDING,
    roomId: 'ops-room',
    participantId: 'ops-person',
    admittedAt: now,
  };
  registerRehydrationInbox(inbox, {
    schema: 'ops_unit',
    databaseIdentity: JSON.stringify(['127.0.0.1', 1, 'livekit_lab', 'ops_unit']),
    native: { currentBearer: async () => grant } as unknown as RehydrationInboxAccess['native'],
    communication: {} as RehydrationInboxAccess['communication'],
    transaction: async (_protected, action) => action({} as RehydrationTx),
  });
  const authority = currentCase(
    {
      schemaVersion: 1,
      source: 'p1_public_v4',
      ...REF,
      revision: '0',
      request: {
        schemaVersion: 1,
        kind: 'booking_investigation',
        bookingReference: 'OPS-01',
        newCheckIn: '2030-12-10',
        investigationConsent: true,
      },
      workflow: { taskId: 'public task Ω', state: 'ready', version: '0' },
      intent: { state: 'not_committed', intentId: null },
      mutation: {
        state: 'not_observed',
        outcome: 'not_observed',
        cancellation: 'not_observed',
        effectId: null,
        outcomeEventId: null,
      },
      supplierResult: null,
      sourceRevision: 'b'.repeat(64),
    },
    REF,
  );
  const snapshot = {
    ref: REF,
    access: {
      kind: 'native' as const,
      bindingId: BINDING,
      roomId: 'ops-room',
      participantId: 'ops-person',
    },
    history: { messages: [], nextCursor: null, hasMore: false },
    work: { items: [], nextCursor: null, hasMore: false },
    responses: { items: [], nextCursor: null, hasMore: false },
    replies: { items: [], nextCursor: null, hasMore: false },
    p2ObservedAt: now,
  };
  vi.spyOn(RehydrationStore.prototype, 'snapshot').mockResolvedValue(snapshot);
  vi.spyOn(RehydrationStore.prototype, 'disclose').mockResolvedValue(now);
  let inspect: () => Promise<typeof authority> = async () => authority;
  const reader = new OperationsReader(
    inbox,
    { inspect: () => inspect() },
    createFakeSmsIntegration(
      { tenantId: 'ops-tenant', provider: 'fake_sms', providerAccountId: 'ops-sms' },
      Buffer.alloc(32, 2),
    ),
    {
      profileId: one,
      sourceId: 'unit-source',
      reference: REF,
      bindingId: BINDING,
      nativeToken: 'N'.repeat(43),
      cursorKey: Buffer.alloc(32, 3),
    },
  );
  return {
    reader,
    authority,
    setInspect(value: typeof inspect) {
      inspect = value;
    },
  };
}
async function rawRead(
  port: number,
  path: string,
  headers: Record<string, string> = {},
  method = 'GET',
) {
  return new Promise<{ status: number; headers: IncomingHttpHeaders; body: unknown }>(
    (resolve, reject) => {
      const req = httpRequest(
        {
          host: '127.0.0.1',
          port,
          path,
          method,
          agent: false,
          headers: {
            Host: `127.0.0.1:${port}`,
            Connection: 'close',
            Authorization: AUTH,
            'x-p2-request-id': one,
            ...headers,
          },
        },
        (res) => {
          const chunks: Buffer[] = [];
          res.on('data', (chunk: Buffer) => chunks.push(chunk));
          res.once('end', () => {
            try {
              resolve({
                status: res.statusCode!,
                headers: res.headers,
                body: JSON.parse(Buffer.concat(chunks).toString()) as unknown,
              });
            } catch (error) {
              reject(error);
            }
          });
          res.once('error', reject);
        },
      );
      req.once('error', reject);
      req.end();
    },
  );
}
async function waitUntil(check: () => boolean) {
  for (let n = 0; n < 100; n++) {
    if (check()) return;
    await delay(2);
  }
  throw Error('unit prerequisite not reached');
}
afterEach(() => vi.restoreAllMocks());
describe('operations read actual loopback and retained work', () => {
  it('returns correlated read-only revision-zero context and real process samples', async () => {
    const { reader } = readFixture(),
      telemetry = new OperationsTelemetry([
        { source: 'inbox', read: () => ({ accepted: 3, active: 0 }) },
      ]);
    const server = new OperationsReadServer(reader, telemetry, AUTH),
      endpoint = await server.start();
    const client = new OperationsHttpClient(endpoint, AUTH, { reference: REF, bindingId: BINDING });
    try {
      const value = await client.context();
      expect(value.context.case.revision).toBe('0');
      expect(value.context.observed.atomic).toBe(false);
      expect(value.cursors.history).toBeNull();
      const sample = await client.telemetry();
      expect(sample.scope).toBe('process');
      expect(sample.sources[0]!.values).toEqual([
        { name: 'accepted', value: 3 },
        { name: 'active', value: 0 },
      ]);
      expect(sample.observations.some((o) => o.operation === 'context' && o.code === 'known')).toBe(
        true,
      );
      expect(reader.metrics().known).toBe(1);
    } finally {
      await client.close();
      await server.close();
      await reader.close();
      await telemetry.close();
    }
    expect(client.metrics().active).toBe(0);
    expect(server.metrics().sockets).toBe(0);
  });
  it.each([
    ['/v1/operations/context?scope=foreign', {}, 'GET', 400, 'invalid_query'],
    ['/v1/operations/context?section=history&section=work', {}, 'GET', 400, 'invalid_query'],
    ['/v1/operations/telemetry?section=work', {}, 'GET', 400, 'invalid_query'],
    ['/v1/operations/context', {}, 'POST', 400, 'invalid_query'],
    ['/v1/operations/context', { Host: '127.0.0.1:1' }, 'GET', 400, 'invalid_query'],
    [
      '/v1/operations/context',
      { Authorization: 'Bearer ' + 'Z'.repeat(43) },
      'GET',
      403,
      'access_denied',
    ],
    ['/v1/operations/context', { 'Content-Length': '1' }, 'GET', 400, 'invalid_query'],
  ] as const)(
    'rejects fixed method/authority/framing %s %j',
    async (path, headers, method, status, code) => {
      const { reader } = readFixture(),
        telemetry = new OperationsTelemetry(),
        server = new OperationsReadServer(reader, telemetry, AUTH);
      const { port } = await server.start();
      try {
        const reply = await rawRead(port, path, headers, method);
        expect(reply.status).toBe(status);
        expect(reply.body).toMatchObject({ code, requestId: one });
        expect(reply.headers['cache-control']).toBe('no-store');
        expect(reader.metrics().started).toBe(0);
      } finally {
        await server.close();
        await reader.close();
        await telemetry.close();
      }
    },
  );
  it('denies context after final fence while independent operator diagnostics remain eligible', async () => {
    const { reader } = readFixture(),
      telemetry = new OperationsTelemetry([{ source: 'inbox', read: () => ({ active: 0 }) }]);
    vi.spyOn(RehydrationStore.prototype, 'disclose').mockRejectedValue(
      new RehydrationError('access_denied'),
    );
    const server = new OperationsReadServer(reader, telemetry, AUTH),
      endpoint = await server.start(),
      client = new OperationsHttpClient(endpoint, AUTH, { reference: REF, bindingId: BINDING });
    try {
      await expect(client.context()).rejects.toMatchObject({ code: 'access_denied' });
      expect((await client.telemetry()).sources[0]!.state).toBe('observed');
    } finally {
      await client.close();
      await server.close();
      await reader.close();
      await telemetry.close();
    }
  });
  it('retains both ignored case reads after abort and incomplete close, then drains', async () => {
    const { reader, authority, setInspect } = readFixture();
    let release: () => void = () => {};
    const held = new Promise<typeof authority>((resolve) => {
      release = () => resolve(authority);
    });
    setInspect(() => held);
    const a = new AbortController(),
      b = new AbortController();
    const x = reader.read(one, undefined, a.signal).catch((error) => error as OperationsError),
      y = reader.read(two, undefined, b.signal).catch((error) => error as OperationsError);
    await waitUntil(() => vi.mocked(RehydrationStore.prototype.snapshot).mock.calls.length === 2);
    a.abort();
    b.abort();
    expect(await x).toMatchObject({ code: 'unavailable' });
    expect(await y).toMatchObject({ code: 'unavailable' });
    expect(reader.metrics().active).toBe(2);
    await expect(reader.read(one)).rejects.toMatchObject({ code: 'overloaded' });
    const close = reader.close();
    expect(reader.close()).toBe(close);
    await expect(close).rejects.toMatchObject({ code: 'unavailable' });
    expect(reader.metrics().active).toBe(2);
    release();
    await reader.close();
    expect(reader.metrics().active).toBe(0);
    // Closing never renews authority/admission; a separately owned reader makes useful progress.
    const fresh = readFixture();
    expect((await fresh.reader.read(one)).status).toBe('known');
    await fresh.reader.close();
  });
  it('held telemetry exporter cannot block ordinary actual HTTP reads or server close', async () => {
    const { reader } = readFixture();
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const telemetry = new OperationsTelemetry(
        [{ source: 'inbox', read: () => ({ active: 0 }) }],
        () => held,
      ),
      server = new OperationsReadServer(reader, telemetry, AUTH),
      endpoint = await server.start(),
      client = new OperationsHttpClient(endpoint, AUTH, { reference: REF, bindingId: BINDING });
    try {
      for (let n = 0; n < 12; n++) await client.context();
      expect(telemetry.metrics().observerPending).toBe(8);
      expect(telemetry.metrics().observerDropped).toBe(4);
      await client.close();
      await server.close();
      await reader.close();
      expect(server.metrics().handlers).toBe(0);
      const close = telemetry.close();
      await expect(close).rejects.toMatchObject({ code: 'unavailable' });
      release();
      await telemetry.close();
    } finally {
      release();
      await client.close();
      await server.close();
      await reader.close();
      await telemetry.close();
    }
  });
});

describe('HTTP transport observation versus retained reader admission', () => {
  it('bounds even an unauthenticated response flush and later makes useful progress', async () => {
    const { reader } = readFixture(),
      telemetry = new OperationsTelemetry(),
      server = new OperationsReadServer(reader, telemetry, AUTH),
      endpoint = await server.start();
    let response: ServerResponse | undefined;
    const held = vi.spyOn(ServerResponse.prototype, 'end').mockImplementation(function (
      this: ServerResponse,
    ) {
      response = this;
      return this;
    });
    try {
      await expect(
        rawRead(endpoint.port, '/v1/operations/context', { Authorization: 'wrong' }),
      ).rejects.toBeDefined();
      await waitUntil(() => server.metrics().handlers === 0 && server.metrics().sockets === 0);
      expect(response?.listeners('finish').some((fn) => fn.name === 'finished')).toBe(false);
      expect(response?.listeners('close').some((fn) => fn.name === 'closed')).toBe(false);
      held.mockRestore();
      const client = new OperationsHttpClient(endpoint, AUTH, {
        reference: REF,
        bindingId: BINDING,
      });
      try {
        expect((await client.context()).status).toBe('known');
      } finally {
        await client.close();
      }
    } finally {
      held.mockRestore();
      await server.close();
      await reader.close();
      await telemetry.close();
    }
  });
  it('separates transport hard refusal from typed retained-read overload', async () => {
    const { reader, authority, setInspect } = readFixture();
    let release: () => void = () => {};
    const held = new Promise<typeof authority>((resolve) => {
      release = () => resolve(authority);
    });
    setInspect(() => held);
    const telemetry = new OperationsTelemetry(),
      server = new OperationsReadServer(reader, telemetry, AUTH),
      endpoint = await server.start(),
      client = new OperationsHttpClient(endpoint, AUTH, { reference: REF, bindingId: BINDING }),
      other = new OperationsHttpClient(endpoint, AUTH, { reference: REF, bindingId: BINDING });
    const a = new AbortController(),
      b = new AbortController();
    const first = client.context(undefined, a.signal).catch((error) => error as OperationsError),
      second = client.context(undefined, b.signal).catch((error) => error as OperationsError);
    try {
      await waitUntil(() => reader.metrics().active === 2 && server.metrics().handlers === 2);
      await expect(other.context()).rejects.toMatchObject({ code: 'unavailable' });
      a.abort();
      b.abort();
      await Promise.all([first, second]);
      await waitUntil(() => server.metrics().handlers === 0);
      expect(reader.metrics().active).toBe(2);
      await expect(other.context()).rejects.toMatchObject({ code: 'overloaded' });
      release();
      await waitUntil(() => reader.metrics().active === 0);
      setInspect(async () => authority);
      expect((await other.context()).status).toBe('known');
    } finally {
      release();
      await client.close();
      await other.close();
      await server.close();
      await reader.close();
      await telemetry.close();
    }
  });
});

describe('receiving operations client distrusts peer framing', () => {
  it('rejects an oversized valid error before decode and accepts later bounded diagnostics', async () => {
    let oversized = true;
    const sockets = new Set<Socket>();
    const peer = createServer((req, res) => {
      const id = req.headers['x-p2-request-id'] as string;
      const body = oversized
        ? ' '.repeat(1100) +
          JSON.stringify({
            schemaVersion: 1,
            status: 'unavailable',
            requestId: id,
            code: 'unavailable',
            retry: 'same_read',
          })
        : JSON.stringify({
            schemaVersion: 1,
            status: 'known',
            scope: 'process',
            requestId: id,
            observedAt: new Date().toISOString(),
            sources: [],
            observations: [],
          });
      res.writeHead(oversized ? 503 : 200, {
        'Content-Type': 'application/json',
        'Content-Length': String(Buffer.byteLength(body)),
        Connection: 'close',
        'Cache-Control': 'no-store',
        'x-p2-request-id': id,
      });
      res.end(body);
    });
    peer.on('connection', (socket) => {
      sockets.add(socket);
      socket.once('close', () => sockets.delete(socket));
    });
    await new Promise<void>((resolve) => peer.listen(0, '127.0.0.1', resolve));
    const address = peer.address();
    if (!address || typeof address === 'string') throw Error();
    const client = new OperationsHttpClient({ host: '127.0.0.1', port: address.port }, AUTH, {
      reference: REF,
      bindingId: BINDING,
    });
    try {
      await expect(client.telemetry()).rejects.toMatchObject({ code: 'unavailable' });
      oversized = false;
      expect((await client.telemetry()).status).toBe('known');
    } finally {
      await client.close();
      for (const socket of sockets) socket.destroy();
      await new Promise<void>((resolve) => peer.close(() => resolve()));
    }
  });
  it('keeps a returned request owned when end throws and actual destroy is ignored', async () => {
    const sockets = new Set<Socket>();
    const peer = createServer();
    peer.on('connection', (socket) => {
      sockets.add(socket);
      socket.once('close', () => sockets.delete(socket));
    });
    await new Promise<void>((resolve) => peer.listen(0, '127.0.0.1', resolve));
    const address = peer.address();
    if (!address || typeof address === 'string') throw Error();
    const client = new OperationsHttpClient({ host: '127.0.0.1', port: address.port }, AUTH, {
      reference: REF,
      bindingId: BINDING,
    });
    const owned: ClientRequest[] = [],
      originalDestroy = ClientRequest.prototype.destroy;
    const end = vi.spyOn(ClientRequest.prototype, 'end').mockImplementation(function (
      this: ClientRequest,
    ) {
      owned.push(this);
      throw Error('private');
    });
    const destroy = vi.spyOn(ClientRequest.prototype, 'destroy').mockImplementation(function (
      this: ClientRequest,
    ) {
      return this;
    });
    try {
      await expect(client.telemetry()).rejects.toMatchObject({ code: 'unavailable' });
      await waitUntil(() => sockets.size === 1);
      expect(client.metrics().active).toBe(1);
      await expect(client.close()).rejects.toMatchObject({ code: 'unavailable' });
      expect(client.metrics().active).toBe(1);
      end.mockRestore();
      destroy.mockRestore();
      for (const req of owned) originalDestroy.call(req);
      await client.close();
      expect(client.metrics().active).toBe(0);
    } finally {
      end.mockRestore();
      destroy.mockRestore();
      for (const req of owned) originalDestroy.call(req);
      await client.close();
      for (const socket of sockets) socket.destroy();
      await new Promise<void>((resolve) => peer.close(() => resolve()));
    }
  });
});

it('separates actual read owners from completed caller spans in finite process metrics', () => {
  expect(
    operationsMetrics('operations', {
      active: 0,
      readerActive: 2,
      readerStarted: 2,
      readerKnown: 0,
      readerWaiterRejected: 2,
    }),
  ).toEqual([
    { name: 'active', value: 0 },
    { name: 'readerActive', value: 2 },
    { name: 'readerKnown', value: 0 },
    { name: 'readerStarted', value: 2 },
    { name: 'readerWaiterRejected', value: 2 },
  ]);
});
