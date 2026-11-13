/** Independent native capability/codec and actual loopback transport assertions; no PostgreSQL. */
import { createHash } from 'node:crypto';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import type { Socket } from 'node:net';
import { setTimeout as delay } from 'node:timers/promises';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  createNativeIntegration,
  NativeAgentHttpClient,
  NativeChannelInbox,
  NativeError,
  NativeGateway,
  type NativeAllowedBinding,
  type NativeIntegration,
  type NativePublisher,
} from '../src/native.js';
import { nativeInput, nativeLimits, publication } from '../src/native-types.js';
import { produceTextEvent } from '../src/index.js';
import { ChannelError, SeededAccounts, type StoredMessage } from '../src/postgres.js';
import type { DispatchPorts } from '../src/dispatch-types.js';

const SCOPE = { tenantId: 'tenant-native', accountId: 'account-native' };
const PROVIDER = {
  tenantId: SCOPE.tenantId,
  provider: 'livekit',
  providerAccountId: 'native-local',
};
const BINDING = '11111111-1111-4111-8111-111111111111';
const INPUT = '22222222-2222-4222-8222-222222222222';
const RECEIPT = '33333333-3333-4333-8333-333333333333';
const OPERATION = '44444444-4444-4444-8444-444444444444';
const AUTHORIZATION = 'Bearer ' + 'A'.repeat(43);
const ACCOUNT_TOKEN = 'B'.repeat(43);
const BINDING_TOKEN = 'C'.repeat(43);
const publisher = (): NativePublisher => ({
  token: 'D'.repeat(43),
  scope: { ...SCOPE },
  caseId: 'case-native',
  conversationId: 'conversation-native',
});
const binding = (): NativeAllowedBinding => ({
  bindingId: BINDING,
  scope: { ...SCOPE },
  caseId: 'case-native',
  conversationId: 'conversation-native',
});
const database = {
  host: '127.0.0.1',
  port: 1,
  database: 'livekit_lab',
  user: 'livekit_lab',
  password: 'S'.repeat(43),
  schema: 'p2_native_' + 'a'.repeat(32),
};
const account = () =>
  new SeededAccounts([
    {
      token: ACCOUNT_TOKEN,
      ...SCOPE,
      caseId: 'case-native',
      conversationId: 'conversation-native',
    },
  ]);
type PrepareInput = Parameters<DispatchPorts['agent']['prepare']>[0];
function context(
  body = 'Investigate 🧭 e\u0301',
  changes: Partial<StoredMessage> = {},
): PrepareInput {
  const message: StoredMessage = {
    receipt: {
      receiptId: RECEIPT,
      eventId: INPUT,
      messageId: INPUT,
      acceptanceSequence: '9223372036854775807',
      acceptedAt: '2030-01-01T00:00:00.000Z',
    },
    event: produceTextEvent(
      {
        eventId: INPUT,
        providerScope: { ...PROVIDER },
        accountScope: { ...SCOPE },
        conversationId: 'conversation-native',
        caseId: 'case-native',
        receivedAt: '2030-01-01T00:00:00.000Z',
        channel: 'web_chat',
        messageId: INPUT,
        senderId: BINDING,
        body,
      },
      { providerScope: PROVIDER, accountScope: SCOPE },
    ).event,
    operationKey: OPERATION,
    processingState: 'pending',
    associationVersion: '1',
    ...changes,
  };
  return {
    message,
    currentCase: {
      scope: { ...SCOPE },
      caseId: 'case-native',
      revision: '9223372036854775807',
      source: 'synthetic_read_only',
    },
  };
}
function wireInput() {
  return {
    schemaVersion: 1 as const,
    inputId: INPUT,
    channel: 'web_chat' as const,
    body: 'Investigate',
    roomId: 'native-room',
    participantId: 'native-browser',
  };
}
function publishInput() {
  return {
    bindingId: BINDING,
    bearer: BINDING_TOKEN,
    roomId: 'native-room',
    participantId: 'native-browser',
    expiresAt: '2030-01-01T00:04:00.000Z',
  };
}
const signal = () => new AbortController().signal;
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}
async function waitFor(predicate: () => boolean): Promise<void> {
  const end = performance.now() + 2000;
  while (!predicate()) {
    if (performance.now() >= end) throw new Error('owned_test_wait_timeout');
    await delay(2);
  }
}
async function bytes(request: IncomingMessage): Promise<Buffer> {
  const chunks: Buffer[] = [];
  let length = 0;
  for await (const value of request) {
    const chunk = Buffer.from(value as Buffer);
    length += chunk.byteLength;
    if (length > 32768) throw new Error('test_request_bound');
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}
function answer(response: ServerResponse, body: unknown, status = 200): void {
  const raw = Buffer.from(JSON.stringify(body));
  response.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': String(raw.byteLength),
    Connection: 'close',
  });
  response.end(raw);
}
function known(raw: Buffer, changes: Record<string, unknown> = {}) {
  const parsed = JSON.parse(raw.toString('utf8')) as { context: { caseRevision: string } };
  return {
    schemaVersion: 1,
    kind: 'agent.prepared',
    inputDigest: createHash('sha256').update(raw).digest('hex'),
    decision: {
      kind: 'investigation',
      source: 'scripted',
      caseRevision: parsed.context.caseRevision,
    },
    ...changes,
  };
}
async function fixture(
  handler: (request: IncomingMessage, response: ServerResponse) => void | Promise<void>,
  options = {},
) {
  const sockets = new Set<Socket>();
  const closed: Promise<void>[] = [];
  const errors: unknown[] = [];
  const server = createServer((request, response) => {
    void Promise.resolve(handler(request, response)).catch((error: unknown) => {
      errors.push(error);
      response.destroy();
    });
  });
  server.on('connection', (socket) => {
    sockets.add(socket);
    closed.push(
      new Promise<void>((resolve) => {
        socket.once('close', () => {
          sockets.delete(socket);
          resolve();
        });
      }),
    );
    socket.on('error', () => undefined);
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('test_endpoint');
  const client = new NativeAgentHttpClient(
    { host: '127.0.0.1', port: address.port },
    AUTHORIZATION,
    [binding()],
    { timeoutMs: 250, cleanupMs: 250, ...options },
  );
  return {
    client,
    server,
    port: address.port,
    sockets,
    async close() {
      let first: unknown;
      try {
        await client.close();
      } catch (error) {
        first = error;
      } finally {
        for (const socket of sockets) socket.destroy();
        await new Promise<void>((resolve) => server.close(() => resolve()));
        await Promise.all(closed);
      }
      expect(sockets.size).toBe(0);
      expect(client.metrics().active).toBe(0);
      expect(errors).toEqual([]);
      if (first) throw first;
    },
  };
}
afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('native opaque capabilities and exact input data', () => {
  it('copies and freezes trusted provider scope instead of accepting caller labels as authority', () => {
    const provider = { ...PROVIDER };
    const allowed = publisher();
    const value = createNativeIntegration(provider, [allowed]);
    provider.provider = 'fake_sms';
    (allowed.scope as { accountId: string }).accountId = 'other-account';
    expect(value.providerScope).toEqual(PROVIDER);
    expect(Object.isFrozen(value)).toBe(true);
    expect(Object.isFrozen(value.providerScope)).toBe(true);
    expect(Object.keys(value)).toEqual(['providerScope']);
    expect(JSON.stringify(value)).not.toContain(allowed.token);
  });
  it('rejects a structurally forged capability before any inbox or gateway resource opens', () => {
    const forged = { providerScope: { ...PROVIDER } } as NativeIntegration;
    expect(() => new NativeChannelInbox(database, forged, account())).toThrow(NativeError);
    expect(
      () =>
        new NativeGateway({
          database,
          integration: forged,
          accounts: [],
          ports: {} as DispatchPorts,
        }),
    ).toThrow(NativeError);
  });
  it.each([
    { ...PROVIDER, provider: 'fake_sms' },
    { ...PROVIDER, tenantId: '' },
    { ...PROVIDER, extra: true },
  ])('rejects unsupported provider identity or extra scope fields', (provider) => {
    expect(() => createNativeIntegration(provider, [publisher()])).toThrow(NativeError);
  });
  it('rejects mismatched tenant, duplicate publisher credentials and over-cap authority inventory', () => {
    expect(() =>
      createNativeIntegration(PROVIDER, [
        { ...publisher(), scope: { ...SCOPE, tenantId: 'other' } },
      ]),
    ).toThrow(NativeError);
    expect(() => createNativeIntegration(PROVIDER, [publisher(), publisher()])).toThrow(
      NativeError,
    );
    expect(() => createNativeIntegration(PROVIDER, [])).toThrow(NativeError);
    expect(() =>
      createNativeIntegration(
        PROVIDER,
        Array.from({ length: 65 }, (_, n) => ({
          ...publisher(),
          token: String(n).padStart(43, 'A'),
        })),
      ),
    ).toThrow(NativeError);
  });
  it('never evaluates publisher accessors, array getters or custom iteration', () => {
    let reads = 0;
    const entry = publisher();
    Object.defineProperty(entry, 'token', {
      enumerable: true,
      get: () => {
        reads++;
        throw new Error('SECRET_SENTINEL');
      },
    });
    expect(() => createNativeIntegration(PROVIDER, [entry])).toThrow(NativeError);
    expect(reads).toBe(0);
    const list: NativePublisher[] = [];
    Object.defineProperty(list, '0', {
      enumerable: true,
      get: () => {
        reads++;
        return publisher();
      },
    });
    expect(() => createNativeIntegration(PROVIDER, list)).toThrow(NativeError);
    expect(reads).toBe(0);
    const overridden = [publisher()];
    Object.defineProperty(overridden, 'map', {
      value: () => {
        reads++;
        throw new Error('SECRET_SENTINEL');
      },
      enumerable: true,
    });
    expect(() => createNativeIntegration(PROVIDER, overridden)).toThrow(NativeError);
    expect(reads).toBe(0);
  });
  it('keeps publisher and account credentials distinct without connecting to PostgreSQL', async () => {
    const same = publisher();
    const integration = createNativeIntegration(PROVIDER, [same]);
    expect(
      () =>
        new NativeChannelInbox(
          database,
          integration,
          new SeededAccounts([
            {
              token: same.token,
              ...SCOPE,
              caseId: 'case-native',
              conversationId: 'conversation-native',
            },
          ]),
        ),
    ).toThrow(ChannelError);
    const inbox = new NativeChannelInbox(database, integration, account());
    try {
      await expect(
        inbox.bind(same.token, { ...publishInput(), bearer: ACCOUNT_TOKEN }),
      ).rejects.toEqual(new ChannelError('AccessDenied'));
    } finally {
      await inbox.close();
    }
  });
  it('retains exact Unicode text bytes and accepts the UTF-8 boundary', () => {
    const raw = { ...wireInput(), body: 'é'.repeat(1024) };
    const parsed = nativeInput(raw);
    raw.body = 'mutated';
    expect(Buffer.byteLength(parsed.body)).toBe(2048);
    expect(parsed.body).toBe('é'.repeat(1024));
    expect(Object.isFrozen(parsed)).toBe(true);
    expect(nativeInput({ ...wireInput(), channel: 'voice_transcript' }).channel).toBe(
      'voice_transcript',
    );
  });
  it.each(['', 'é'.repeat(1025), 'x'.repeat(2049), '\ud800', '\udfff', 'x\ud800y'])(
    'rejects empty/over-limit/malformed UTF-8 input case %#',
    (body) => {
      expect(() => nativeInput({ ...wireInput(), body })).toThrow(NativeError);
    },
  );
  it.each([
    { ...wireInput(), schemaVersion: true },
    { ...wireInput(), inputId: 'AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA' },
    { ...wireInput(), inputId: 'not-an-id' },
    { ...wireInput(), channel: 'sms' },
    { ...wireInput(), tenantId: 'other' },
    { ...wireInput(), roomId: '../room' },
    { ...wireInput(), participantId: true },
  ])('rejects closed native wire shape, IDs, modalities and authority selectors', (value) => {
    expect(() => nativeInput(value)).toThrow(NativeError);
  });
  it('snapshots publication and validates limits without evicting protected binding identities', () => {
    const raw = publishInput();
    const parsed = publication(raw);
    raw.participantId = 'mutated';
    expect(parsed.participantId).toBe('native-browser');
    expect(Object.isFrozen(parsed)).toBe(true);
    expect(nativeLimits({ maxBindings: 1 })).toEqual({ maxBindings: 1 });
    expect(nativeLimits({ maxBindings: 1024 })).toEqual({ maxBindings: 1024 });
    for (const value of [0, -1, true, NaN, Infinity, 1025, '64'])
      expect(() => nativeLimits({ maxBindings: value })).toThrow(NativeError);
    expect(() => publication({ ...publishInput(), expiresAt: '2030-02-30T00:00:00.000Z' })).toThrow(
      NativeError,
    );
    expect(() => publication({ ...publishInput(), bearer: 'short' })).toThrow(NativeError);
  });
});

describe('native actual local agent HTTP boundary', () => {
  it('sends one authenticated compact request with complete immutable context and exact reply digest', async () => {
    let count = 0;
    const received: unknown[] = [];
    const f = await fixture(async (request, response) => {
      count++;
      expect(request.method).toBe('POST');
      expect(request.url).toBe('/v1/native/prepare');
      expect(request.headers.authorization).toBe(AUTHORIZATION);
      expect(request.headers.connection).toBe('close');
      expect(request.headers['transfer-encoding']).toBeUndefined();
      const raw = await bytes(request);
      expect(raw.byteLength).toBe(Number(request.headers['content-length']));
      received.push(JSON.parse(raw.toString()));
      answer(response, known(raw));
    });
    try {
      const value = context();
      const snapshot = structuredClone(value);
      expect(await f.client.port.prepare(value, signal())).toEqual({
        kind: 'investigation',
        source: 'scripted',
        caseRevision: snapshot.currentCase.revision,
      });
      expect(received).toHaveLength(1);
      const wire = received[0] as {
        schemaVersion: number;
        kind: string;
        context: {
          scope: unknown;
          operationKey: string;
          caseRevision: string;
          message: { body: string; senderId: string };
        };
      };
      expect(wire.schemaVersion).toBe(1);
      expect(wire.kind).toBe('agent.prepare');
      expect(wire.context.scope).toEqual(SCOPE);
      expect(wire.context.operationKey).toBe(OPERATION);
      expect(wire.context.caseRevision).toBe('9223372036854775807');
      expect(wire.context.message.body).toBe(
        snapshot.message.event.type === 'text.received' ? snapshot.message.event.body : '',
      );
      expect(wire.context.message.senderId).toBe(BINDING);
      expect(count).toBe(1);
      expect(f.client.metrics()).toMatchObject({ started: 1, known: 1 });
      expect(Object.isFrozen(f.client.metrics())).toBe(true);
    } finally {
      await f.close();
    }
  });
  it('copies allowed binding and request data before awaiting I/O', async () => {
    const reached = deferred<void>();
    const release = deferred<void>();
    const captured: { value: Buffer | null } = { value: null };
    const f = await fixture(async (request, response) => {
      captured.value = await bytes(request);
      reached.resolve();
      await release.promise;
      answer(response, known(captured.value));
    });
    const allowed = binding();
    const client = new NativeAgentHttpClient({ host: '127.0.0.1', port: f.port }, AUTHORIZATION, [
      allowed,
    ]);
    try {
      (allowed.scope as { accountId: string }).accountId = 'changed';
      const value = context();
      const pending = client.port.prepare(value, signal());
      await reached.promise;
      (value.currentCase.scope as { accountId: string }).accountId = 'mutated';
      if (value.message.event.type === 'text.received')
        (value.message as { event: StoredMessage['event'] }).event = {
          ...value.message.event,
          body: 'mutated',
        };
      release.resolve();
      expect(await pending).toMatchObject({ caseRevision: '9223372036854775807' });
      expect(captured.value?.toString()).toContain('Investigate');
      expect(captured.value?.toString()).not.toContain('mutated');
    } finally {
      release.resolve();
      await client.close();
      await f.close();
    }
  });
  it.each(['scope', 'case', 'conversation', 'sender', 'provider', 'channel'])(
    'denies unbound %s before any socket is opened',
    async (kind) => {
      let calls = 0;
      const f = await fixture((_req, response) => {
        calls++;
        response.destroy();
      });
      try {
        const value = context();
        if (value.message.event.type !== 'text.received') throw new Error('test_event');
        const changed = {
          ...value.message.event,
          ...(kind === 'scope'
            ? { accountScope: { ...SCOPE, accountId: 'other' } }
            : kind === 'case'
              ? { caseId: 'case-other' }
              : kind === 'conversation'
                ? { conversationId: 'conversation-other' }
                : kind === 'sender'
                  ? { senderId: OPERATION }
                  : kind === 'provider'
                    ? { providerScope: { ...PROVIDER, provider: 'fake_sms' } }
                    : { channel: 'sms' }),
        };
        await expect(
          f.client.port.prepare(
            { ...value, message: { ...value.message, event: changed as StoredMessage['event'] } },
            signal(),
          ),
        ).rejects.toBeInstanceOf(ChannelError);
        expect(calls).toBe(0);
        expect(f.client.metrics().started).toBe(0);
      } finally {
        await f.close();
      }
    },
  );
  it.each([
    'digest',
    'revision',
    'scope',
    'decision',
    'extra',
    'duplicate',
    'malformed',
    'oversized',
    'status',
    'redirect',
    'chunked',
    'missing-close',
  ])('rejects unvalidated %s with no hidden retry', async (kind) => {
    let calls = 0;
    const f = await fixture(async (request, response) => {
      calls++;
      const raw = await bytes(request);
      const valid = known(raw);
      if (kind === 'oversized') {
        response.writeHead(200, {
          'Content-Type': 'application/json',
          'Content-Length': '8193',
          Connection: 'close',
        });
        response.end('x'.repeat(8193));
        return;
      }
      if (kind === 'redirect') {
        response.writeHead(302, { Location: 'http://127.0.0.1:1/private' });
        response.end();
        return;
      }
      if (kind === 'status') {
        answer(response, valid, 503);
        return;
      }
      if (kind === 'chunked') {
        response.writeHead(200, { 'Content-Type': 'application/json', Connection: 'close' });
        response.end(JSON.stringify(valid));
        return;
      }
      if (kind === 'missing-close') {
        const body = Buffer.from(JSON.stringify(valid));
        response.socket?.end(
          `HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${body.length}\r\n\r\n${body.toString()}`,
        );
        return;
      }
      if (kind === 'duplicate' || kind === 'malformed') {
        const text =
          kind === 'duplicate'
            ? JSON.stringify(valid).replace(
                '"schemaVersion":1',
                '"schemaVersion":1,"schemaVersion":1',
              )
            : '{"SECRET_SENTINEL":';
        const body = Buffer.from(text);
        response.writeHead(200, {
          'Content-Type': 'application/json',
          'Content-Length': body.length,
          Connection: 'close',
        });
        response.end(body);
        return;
      }
      answer(response, {
        ...valid,
        ...(kind === 'digest'
          ? { inputDigest: '0'.repeat(64) }
          : kind === 'revision'
            ? { decision: { kind: 'investigation', source: 'scripted', caseRevision: '1' } }
            : kind === 'scope'
              ? { scope: { tenantId: 'other', accountId: 'other' } }
              : kind === 'decision'
                ? {
                    decision: {
                      kind: 'charge',
                      source: 'scripted',
                      caseRevision: '9223372036854775807',
                    },
                  }
                : { extra: 'SECRET_SENTINEL' }),
      });
    });
    try {
      const pending = f.client.port.prepare(context(), signal());
      await expect(pending).rejects.toEqual(new ChannelError('DispatchUnavailable'));
      expect(calls).toBe(1);
      expect(f.client.metrics().known).toBe(0);
    } finally {
      await f.close();
    }
  });
  it('does not use ambient proxy variables or leak authentication to another local peer', async () => {
    let proxyCalls = 0;
    const proxy = await fixture((_request, response) => {
      proxyCalls++;
      response.destroy();
    });
    const f = await fixture(async (request, response) =>
      answer(response, known(await bytes(request))),
    );
    try {
      for (const key of ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy'])
        vi.stubEnv(key, 'http://127.0.0.1:' + proxy.port);
      vi.stubEnv('NO_PROXY', '');
      expect(await f.client.port.prepare(context(), signal())).toMatchObject({
        kind: 'investigation',
      });
      expect(proxyCalls).toBe(0);
    } finally {
      await f.close();
      await proxy.close();
    }
  });
  it('retains an aborted call slot until actual socket closure, then permits useful work', async () => {
    const reached = deferred<void>();
    let calls = 0;
    const f = await fixture(async (request, response) => {
      calls++;
      const raw = await bytes(request);
      if (calls === 1) {
        reached.resolve();
        return;
      }
      answer(response, known(raw));
    });
    const controller = new AbortController();
    try {
      const pending = f.client.port.prepare(context(), controller.signal);
      const rejected = expect(pending).rejects.toEqual(new ChannelError('DispatchUnavailable'));
      await reached.promise;
      controller.abort();
      expect(f.client.metrics().active).toBe(1);
      const blocked = f.client.port.prepare(context(), signal());
      await expect(blocked).rejects.toEqual(new ChannelError('DispatchUnavailable'));
      await rejected;
      await waitFor(() => f.client.metrics().active === 0);
      expect(await f.client.port.prepare(context(), signal())).toMatchObject({
        kind: 'investigation',
      });
      expect(calls).toBe(2);
      expect(f.client.metrics().started).toBe(2);
    } finally {
      await f.close();
    }
  });
  it('times out a partial reply, closes actual resources and never silently retries', async () => {
    let calls = 0;
    const f = await fixture(
      async (request, response) => {
        calls++;
        await bytes(request);
        response.writeHead(200, {
          'Content-Type': 'application/json',
          'Content-Length': '100',
          Connection: 'close',
        });
        response.write('{');
      },
      { timeoutMs: 60 },
    );
    try {
      await expect(f.client.port.prepare(context(), signal())).rejects.toEqual(
        new ChannelError('DispatchUnavailable'),
      );
      await waitFor(() => f.client.metrics().active === 0);
      expect(calls).toBe(1);
    } finally {
      await f.close();
    }
  });
  it('rejects invalid or already-aborted signals before network admission and closes permanently', async () => {
    let calls = 0;
    const f = await fixture((_request, response) => {
      calls++;
      response.destroy();
    });
    try {
      const aborted = new AbortController();
      aborted.abort();
      await expect(f.client.port.prepare(context(), aborted.signal)).rejects.toEqual(
        new ChannelError('DispatchUnavailable'),
      );
      await expect(f.client.port.prepare(context(), {} as AbortSignal)).rejects.toEqual(
        new ChannelError('DispatchUnavailable'),
      );
      expect(calls).toBe(0);
      await f.client.close();
      await expect(f.client.port.prepare(context(), signal())).rejects.toEqual(
        new ChannelError('DispatchUnavailable'),
      );
      expect(calls).toBe(0);
    } finally {
      await f.close();
    }
  });
  it('rejects malformed endpoints, credentials, bound inventory and resource limits synchronously', () => {
    const endpoint = { host: '127.0.0.1' as const, port: 12345 };
    for (const changed of [
      { ...endpoint, host: 'localhost' },
      { ...endpoint, port: 0 },
      { ...endpoint, port: NaN },
      { ...endpoint, extra: true },
    ])
      expect(
        () => new NativeAgentHttpClient(changed as typeof endpoint, AUTHORIZATION, [binding()]),
      ).toThrow(ChannelError);
    for (const auth of ['token', 'Bearer short', AUTHORIZATION + '\n'])
      expect(() => new NativeAgentHttpClient(endpoint, auth, [binding()])).toThrow(ChannelError);
    for (const bound of [
      [],
      [binding(), binding()],
      [{ ...binding(), bindingId: 'bad' }],
      [{ ...binding(), injected: true }],
    ])
      expect(
        () => new NativeAgentHttpClient(endpoint, AUTHORIZATION, bound as NativeAllowedBinding[]),
      ).toThrow(ChannelError);
    for (const options of [
      { timeoutMs: 19 },
      { timeoutMs: 5001 },
      { maxActive: 0 },
      { maxActive: 5 },
      { cleanupMs: 0 },
      { timeoutMs: NaN },
      {
        observer: () => {
          throw new Error('SECRET_SENTINEL');
        },
      },
    ])
      expect(
        () => new NativeAgentHttpClient(endpoint, AUTHORIZATION, [binding()], options),
      ).toThrow(ChannelError);
  });
});
