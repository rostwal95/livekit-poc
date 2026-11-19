import type { NativeBridgeConfiguration } from '../src/native-bridge-contract.js';
import { worker as nativeWorker } from './native-bridge-fixtures.js';
/** Public P2 owners are explicit fakes here; worker/result transports use actual loopback sockets. */
import { createHash, randomUUID } from 'node:crypto';
import { request, Server } from 'node:http';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createNativeIntegration } from '@livekit-ecosystem/channel-continuity/native';
import { createFakeSmsIntegration } from '@livekit-ecosystem/channel-continuity/security';
import type { StoredMessage } from '@livekit-ecosystem/channel-continuity/postgres';
import type {
  DispatchObservation,
  DispatchPorts,
  PreparedDispatch,
} from '@livekit-ecosystem/channel-continuity/dispatch';
import {
  ChannelPolicyGatewayApplication,
  type GatewayApplicationConfiguration,
  type GatewayApplicationPorts,
} from '../src/application.js';
import type { NativeRoomOptions } from '../src/native-room-contract.js';
import { opening, command, post as roomPost, port } from './native-room-fixtures.js';
const f = vi.hoisted(() => {
  const state = {
    trace: [] as string[],
    failConstruct: '',
    failClose: new Set<string>(),
    holds: new Map<string, Promise<void>>(),
    messages: [] as unknown[],
    observations: new Map<string, unknown>(),
    plans: new Map<string, unknown>(),
    calls: [] as unknown[][],
    nativeResult: null as unknown,
    nativePorts: undefined as unknown,
  };
  class Owner {
    readonly label: string;
    constructor(label: string) {
      this.label = label;
      state.trace.push('new:' + label);
      if (state.failConstruct === label) throw new Error('PRIVATE_CONSTRUCTOR');
    }
    async close() {
      state.trace.push('close:' + this.label);
      await state.holds.get('close:' + this.label);
      if (state.failClose.has(this.label)) throw new Error('PRIVATE_CLOSE');
      state.trace.push('closed:' + this.label);
    }
  }
  class Gateway extends Owner {
    async fenceNativeInput(bearer: string) {
      state.calls.push([this.label, 'fence_native', bearer]);
    }
    async drainNativeInput(token: string, binding: string, bearer: string) {
      state.calls.push([this.label, 'drain_native', token, binding, bearer]);
      await state.holds.get('drain_native');
    }
    async quiesceDispatch() {
      state.trace.push('quiesce:' + this.label);
      await state.holds.get('quiesce:' + this.label);
      if (state.failClose.has('quiesce:' + this.label)) throw new Error('PRIVATE_QUIESCE');
      state.trace.push('quiesced:' + this.label);
    }
    async listen(port: number) {
      state.trace.push('listen:' + this.label);
      await state.holds.get('listen:' + this.label);
      return Object.freeze({
        host: '127.0.0.1' as const,
        port: port || (this.label === 'native_gateway' ? 30101 : 30102),
      });
    }
    async inspectDispatch(token: string, id: string) {
      state.calls.push([this.label, 'inspect', token, id]);
      return state.observations.get(id);
    }
    async readPrepared(token: string, id: string) {
      state.calls.push([this.label, 'prepared', token, id]);
      return state.plans.get(id) ?? null;
    }
  }
  return { state, Owner, Gateway };
});
vi.mock('@livekit-ecosystem/channel-continuity/gateway', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ChannelGateway: class extends f.Gateway {
    constructor() {
      super('sms_gateway');
    }
  },
}));
vi.mock('@livekit-ecosystem/channel-continuity/native', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  NativeGateway: class extends f.Gateway {
    constructor(options: unknown) {
      super('native_gateway');
      f.state.nativePorts = (options as { ports: unknown }).ports;
    }
  },
  NativeChannelInbox: class extends f.Owner {
    constructor() {
      super('history');
    }
    async bind(token: string, input: { bindingId: string; expiresAt: string }) {
      f.state.calls.push(['native_bind', token, input]);
      f.state.trace.push('native_bind');
      await f.state.holds.get('native_bind');
      return {
        bindingId: input.bindingId,
        bindingDigest: 'a'.repeat(64),
        publishedAt: new Date().toISOString(),
        expiresAt: input.expiresAt,
      };
    }
    async revoke(token: string, id: string) {
      f.state.calls.push(['native_revoke', token, id]);
      f.state.trace.push('native_revoke');
      await f.state.holds.get('native_revoke');
      return { bindingId: id, revokedAt: new Date().toISOString() };
    }
    async history() {
      await f.state.holds.get('history');
      return { messages: f.state.messages };
    }
    async inspect(_token: string, id: string) {
      return f.state.messages.find((m) => (m as StoredMessage).receipt.receiptId === id);
    }
  },
}));
vi.mock('@livekit-ecosystem/channel-continuity/rehydration', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ChannelRehydrator: class extends f.Owner {
    constructor() {
      super('context_reader');
    }
    async native() {
      return { private: 'CONTEXT_TEST' };
    }
    async sms() {
      throw new Error('unused signedSMS fixture');
    }
  },
}));
vi.mock('@livekit-ecosystem/channel-continuity/outbox', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ChannelOutbox: class extends f.Owner {
    constructor() {
      super('outbox');
    }
  },
}));
vi.mock('@livekit-ecosystem/channel-continuity/result-receiver', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ChannelResultReceiver: class extends f.Owner {
    constructor() {
      super('result_receiver');
    }
    async accept() {
      throw new Error('PRIVATE_NOT_EXPECTED');
    }
    async find() {
      return null;
    }
  },
  ChannelResultReader: class extends f.Owner {
    constructor() {
      super('result_reader');
    }
    async native(...args: unknown[]) {
      f.state.calls.push(['native_result', ...args]);
      await f.state.holds.get('native_result');
      return f.state.nativeResult;
    }
  },
}));
const scope = { tenantId: 'tenant', accountId: 'account' };
const provider = {
  native: { tenantId: 'tenant', provider: 'livekit', providerAccountId: 'rtc' },
  sms: { tenantId: 'tenant', provider: 'fake_sms', providerAccountId: 'sms' },
};
const account = 'a'.repeat(43),
  worker = 'w'.repeat(43),
  publisher = 'p'.repeat(43);
function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
function fixture(
  options: Partial<GatewayApplicationConfiguration> = {},
  roomControl?: NativeRoomOptions,
  nativeBridge?: NativeBridgeConfiguration,
) {
  const c: GatewayApplicationConfiguration = {
    database: {
      host: '127.0.0.1',
      port: 15432,
      database: 'livekit_lab',
      user: 'livekit_lab',
      password: 'synthetic'.repeat(5),
      schema: 'p2_joined_unit',
    },
    route: {
      profileId: randomUUID(),
      receiverId: randomUUID(),
      scope,
      caseId: 'case',
      conversationId: 'conversation',
      recipientId: 'recipient',
    },
    accountToken: account,
    workerBearer: worker,
    resultPublisherToken: publisher,
    nativeIntegration: createNativeIntegration(provider.native, [
      { token: 'n'.repeat(43), scope, caseId: 'case', conversationId: 'conversation' },
    ]),
    smsIntegration: createFakeSmsIntegration(provider.sms, Buffer.alloc(32, 7)),
    profileInboxLimit: 16,
    startupMs: 1000,
    cleanupMs: 40,
    ...options,
  };
  const forbidden = vi.fn(async () => {
    throw new Error('PRIVATE_AUTHORITY_CALL');
  });
  const borrowedClose = vi.fn(async () => {});
  const port = {
    cases: { inspect: forbidden },
    agent: { prepare: forbidden },
    operations: {
      capabilities: 'stable_idempotency_and_lookup',
      lookup: forbidden,
      accept: forbidden,
    },
  } as DispatchPorts;
  const ports = {
    native: port,
    sms: port,
    cases: { inspect: forbidden, close: borrowedClose },
    carrier: { capabilities: 'ordinary_fake_sms_v1', send: forbidden, close: borrowedClose },
  } as GatewayApplicationPorts;
  return {
    configuration: c,
    ports,
    forbidden,
    borrowedClose,
    app: new ChannelPolicyGatewayApplication(c, ports, roomControl, nativeBridge),
  };
}
function input(source: 'native' | 'sms', sequence: number) {
  const id = randomUUID(),
    operationKey = randomUUID();
  const m: StoredMessage = {
    receipt: {
      receiptId: id,
      eventId: id,
      messageId: id,
      acceptanceSequence: String(sequence),
      acceptedAt: '2026-11-13T00:00:00.000Z',
    },
    event: {
      schemaVersion: 1,
      type: 'text.received',
      eventId: id,
      messageId: id,
      providerScope: provider[source],
      accountScope: scope,
      caseId: 'case',
      conversationId: 'conversation',
      receivedAt: '2026-11-13T00:00:00.000Z',
      channel: source === 'native' ? 'web_chat' : 'sms',
      senderId: source === 'native' ? randomUUID() : 'signed_sender',
      body: 'Review café 🧭.',
    },
    operationKey,
    processingState: 'pending',
    associationVersion: '1',
  };
  const submission = {
    schemaVersion: 1 as const,
    kind: 'investigation' as const,
    operationKey,
    scope,
    caseId: 'case',
    caseRevision: '1',
    conversationId: 'conversation',
    message: {
      receiptId: id,
      eventId: id,
      messageId: id,
      senderId: m.event.type === 'text.received' ? m.event.senderId : '',
      body: 'Review café 🧭.',
    },
  };
  const canonicalPayload = JSON.stringify(submission),
    p: PreparedDispatch = {
      submission,
      canonicalPayload,
      payloadDigest: createHash('sha256').update(canonicalPayload).digest('hex'),
    };
  const o: DispatchObservation = {
    receiptId: id,
    operationKey,
    state: 'pending',
    epoch: '0',
    attempts: 0,
    possibleExternal: false,
    externalReceiptId: null,
    nextAttemptAt: null,
    lastCode: 'pending',
    history: [],
  };
  f.state.messages.push(m);
  f.state.plans.set(id, p);
  f.state.observations.set(id, o);
  return m;
}
function post(
  port: number,
  path: string,
  body: Buffer,
  bearer = worker,
): Promise<{ status: number; value: unknown }> {
  return new Promise((resolve, reject) => {
    const req = request(
      {
        host: '127.0.0.1',
        port,
        path,
        method: 'POST',
        agent: false,
        headers: {
          authorization: 'Bearer ' + bearer,
          'content-type': 'application/json',
          'content-length': body.length,
          connection: 'close',
        },
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on('data', (c) => chunks.push(Buffer.from(c)));
        res.once('end', () => {
          try {
            const raw = Buffer.concat(chunks);
            resolve({
              status: res.statusCode!,
              value: raw.length ? JSON.parse(raw.toString()) : null,
            });
          } catch (e) {
            reject(e);
          }
        });
      },
    );
    req.setTimeout(1000, () => req.destroy(new Error('TEST_TIMEOUT')));
    req.once('error', reject);
    req.end(body);
  });
}
beforeEach(() => {
  f.state.trace.length = 0;
  f.state.calls.length = 0;
  f.state.messages.length = 0;
  f.state.observations.clear();
  f.state.plans.clear();
  f.state.holds.clear();
  f.state.failClose.clear();
  f.state.failConstruct = '';
  f.state.nativeResult = null;
});
describe('explicit public P2 application ownership', () => {
  it('quiesces both drivers while preserving source and result listeners and all owned storage', async () => {
    const x = fixture(),
      held = deferred();
    const endpoints = await x.app.start();
    f.state.holds.set('quiesce:native_gateway', held.promise);
    const stopping = x.app.quiesceDispatch().catch((error: unknown) => error);
    try {
      await vi.waitFor(() => expect(f.state.trace).toContain('quiesced:sms_gateway'));
      expect(await stopping).toMatchObject({ code: 'cleanup_incomplete' });
      expect(f.state.trace.filter((v) => v.startsWith('close:'))).toEqual([]);
      expect(
        await post(endpoints.read.port, '/v1/policy/discovery', Buffer.from('{"schemaVersion":1}')),
      ).toMatchObject({ status: 200, value: { items: [], overflow: false } });
      held.resolve();
      await x.app.quiesceDispatch();
      expect(x.app.metrics().ownedResources).toBe(9);
    } finally {
      held.resolve();
      await stopping.catch(() => {});
      await x.app.close();
    }
  });
  it('is inert through configuration, starts actual worker/result hosts, and closes all owned tiers', async () => {
    const x = fixture();
    expect(f.state.trace).toEqual([]);
    expect(x.app.metrics().ownedResources).toBe(0);
    const endpoints = await x.app.start();
    try {
      expect(Object.isFrozen(endpoints)).toBe(true);
      expect(
        await post(endpoints.read.port, '/v1/policy/discovery', Buffer.from('{"schemaVersion":1}')),
      ).toMatchObject({ status: 200, value: { items: [], overflow: false } });
      expect(
        await post(
          endpoints.receiver.port,
          '/v1/p2-result-receiver/native-read',
          Buffer.from('{}'),
          publisher,
        ),
      ).toMatchObject({ status: 400, value: { status: 'error', error: 'InvalidCommand' } });
      expect(f.state.trace.filter((s) => s.startsWith('new:'))).toHaveLength(6);
      expect(f.state.trace.indexOf('listen:native_gateway')).toBeGreaterThan(
        f.state.trace.indexOf('new:sms_gateway'),
      );
      expect(x.app.metrics().ownedResources).toBe(9);
      expect(x.forbidden).not.toHaveBeenCalled();
    } finally {
      await x.app.close();
    }
    expect(x.app.metrics()).toMatchObject({
      ownedResources: 0,
      starting: 0,
      closed: true,
      pendingNativeReads: 0,
      pendingClose: 0,
    });
    expect(f.state.trace.indexOf('close:outbox')).toBeGreaterThan(
      f.state.trace.indexOf('closed:result_reader'),
    );
    expect(x.borrowedClose).not.toHaveBeenCalled();
    await expect(
      post(endpoints.read.port, '/v1/policy/discovery', Buffer.from('{"schemaVersion":1}')),
    ).rejects.toBeDefined();
  });
  it('binds both real worker/result listeners before either gateway can auto-dispatch recovered input', async () => {
    const originalListen = Server.prototype.listen;
    const listeners: Server[] = [];
    const httpListen = vi.spyOn(Server.prototype, 'listen').mockImplementation(function (
      this: Server,
      ...args: unknown[]
    ) {
      listeners.push(this);
      return Reflect.apply(originalListen, this, args) as Server;
    });
    const originalGateway = f.Gateway.prototype.listen;
    const gatewayListen = vi
      .spyOn(f.Gateway.prototype, 'listen')
      .mockImplementation(async function (this: InstanceType<typeof f.Gateway>, port: number) {
        expect(listeners).toHaveLength(2);
        expect(listeners.every((server) => server.listening)).toBe(true);
        return await originalGateway.call(this, port);
      });
    const x = fixture();
    try {
      await x.app.start();
      expect(gatewayListen).toHaveBeenCalledTimes(2);
    } finally {
      await x.app.close();
      gatewayListen.mockRestore();
      httpListen.mockRestore();
    }
  });
  it('uses each real configured gateway delegate after stored source validation, including a pending gap', async () => {
    const a = input('native', 1),
      b = input('sms', 2),
      x = fixture();
    const endpoints = await x.app.start();
    try {
      expect(
        await post(endpoints.read.port, '/v1/policy/discovery', Buffer.from('{"schemaVersion":1}')),
      ).toMatchObject({
        status: 200,
        value: {
          items: [
            { receiptId: a.receipt.receiptId, sourceBindingId: 'native' },
            { receiptId: b.receipt.receiptId, sourceBindingId: 'sms' },
          ],
        },
      });
      expect(f.state.calls).toContainEqual([
        'native_gateway',
        'inspect',
        account,
        a.receipt.receiptId,
      ]);
      expect(f.state.calls).toContainEqual([
        'sms_gateway',
        'inspect',
        account,
        b.receipt.receiptId,
      ]);
      const wrong = await post(
        endpoints.read.port,
        '/v1/policy/prepared',
        Buffer.from(
          JSON.stringify({
            schemaVersion: 1,
            receiptId: a.receipt.receiptId,
            sourceBindingId: 'sms',
          }),
        ),
      );
      expect(wrong).toMatchObject({ status: 403 });
      expect(f.state.calls.some((c) => c[1] === 'prepared')).toBe(false);
      const frame = await post(
        endpoints.read.port,
        '/v1/policy/prepared',
        Buffer.from(
          JSON.stringify({
            schemaVersion: 1,
            receiptId: b.receipt.receiptId,
            sourceBindingId: 'sms',
          }),
        ),
      );
      expect(frame).toMatchObject({
        status: 200,
        value: {
          canonicalPayload: (f.state.plans.get(b.receipt.receiptId) as PreparedDispatch)
            .canonicalPayload,
        },
      });
      expect(f.state.calls).toContainEqual([
        'sms_gateway',
        'prepared',
        account,
        b.receipt.receiptId,
      ]);
      expect(x.forbidden).not.toHaveBeenCalled();
    } finally {
      await x.app.close();
    }
  });
  it('copies route/ports before startup and never invokes accessors or authority during validation', async () => {
    const x = fixture();
    (x.configuration.route.scope as { tenantId: string }).tenantId = 'foreign';
    expect(f.state.trace).toEqual([]);
    const e = await x.app.start();
    try {
      expect(
        await post(e.read.port, '/v1/policy/discovery', Buffer.from('{"schemaVersion":1}')),
      ).toMatchObject({ value: { scope: { tenantId: 'tenant' } } });
    } finally {
      await x.app.close();
      scope.tenantId = 'tenant';
    }
    const getter = vi.fn(() => {
      throw new Error('PRIVATE_GETTER');
    });
    const config = { ...x.configuration };
    Object.defineProperty(config, 'accountToken', { get: getter, enumerable: true });
    expect(() => new ChannelPolicyGatewayApplication(config, x.ports)).toThrow('invalid_input');
    expect(getter).not.toHaveBeenCalled();
    expect(x.forbidden).not.toHaveBeenCalled();
  });
  it.each([15, 17])('rejects a non-profile inbox cap %i before construction', async (cap) => {
    const x = fixture();
    await x.app.close();
    f.state.trace.length = 0;
    expect(
      () =>
        new ChannelPolicyGatewayApplication(
          { ...x.configuration, profileInboxLimit: cap as 16 },
          x.ports,
        ),
    ).toThrow('invalid_input');
    expect(f.state.trace).toEqual([]);
  });
  it('shares startup, rejects changed listen configuration, and never repeats owner construction', async () => {
    const x = fixture();
    try {
      const [a, b] = await Promise.all([x.app.start(), x.app.start()]);
      expect(a).toBe(b);
      await expect(x.app.start({ readPort: 12345 })).rejects.toThrow('invalid_input');
      expect(f.state.trace.filter((s) => s === 'new:history')).toHaveLength(1);
    } finally {
      await x.app.close();
    }
  });
  it('close before startup admission prevents all construction and future admission', async () => {
    const x = fixture(),
      starting = x.app.start();
    const observed = starting.catch((e) => e);
    await x.app.close();
    expect(await observed).toMatchObject({ code: 'unavailable' });
    expect(f.state.trace).toEqual([]);
    expect(x.app.metrics()).toMatchObject({ starting: 0, closed: true });
    await expect(x.app.start()).rejects.toThrow('closed');
  });
  it('retains late startup and permits truthful close retry after original deadline', async () => {
    const held = deferred();
    f.state.holds.set('listen:native_gateway', held.promise);
    const x = fixture({ startupMs: 30 });
    await expect(x.app.start()).rejects.toThrow('unavailable');
    await expect(x.app.close()).rejects.toThrow('cleanup_incomplete');
    expect(x.app.metrics()).toMatchObject({ starting: 1, closed: false, ownedResources: 9 });
    expect(f.state.trace.some((s) => s.startsWith('close:'))).toBe(false);
    held.resolve();
    await vi.waitFor(() => expect(x.app.metrics().starting).toBe(0));
    await x.app.close();
    expect(f.state.trace).not.toContain('listen:sms_gateway');
    expect(x.app.metrics().ownedResources).toBe(0);
  });
  it('cleans all returned inert owners after partial construction failure without exposing private text', async () => {
    f.state.failConstruct = 'outbox';
    const x = fixture();
    await expect(x.app.start()).rejects.toThrow(/^unavailable$/);
    await x.app.close();
    expect(f.state.trace).toEqual(['new:history', 'new:outbox', 'close:history', 'closed:history']);
    expect(x.app.metrics()).toMatchObject({ closed: true, ownedResources: 0 });
  });
  it('attempts independent reader cleanup but withholds every storage close until a failed reader succeeds', async () => {
    const x = fixture();
    await x.app.start();
    f.state.failClose.add('result_reader');
    await expect(x.app.close()).rejects.toThrow('cleanup_incomplete');
    expect(f.state.trace).toContain('closed:result_receiver');
    expect(f.state.trace).not.toContain('close:outbox');
    expect(f.state.trace).not.toContain('close:native_gateway');
    expect(x.app.metrics().closed).toBe(false);
    f.state.failClose.clear();
    await x.app.close();
    expect(f.state.trace).toContain('closed:outbox');
    expect(x.app.metrics().ownedResources).toBe(0);
  });
  it('keeps an admitted trusted native read owned, closes its reader before storage, and rejects a late body after close', async () => {
    const held = deferred();
    f.state.holds.set('native_result', held.promise);
    const x = fixture();
    await x.app.start();
    const grant = 'g'.repeat(43),
      delivery = randomUUID(),
      reading = x.app.nativeResult(grant, delivery);
    const outcome = reading.catch((e) => e);
    await vi.waitFor(() =>
      expect(f.state.calls).toContainEqual(['native_result', grant, delivery, undefined]),
    );
    await expect(x.app.nativeResult(grant, delivery)).rejects.toMatchObject({ code: 'Overloaded' });
    expect(f.state.calls.filter((c) => c[0] === 'native_result')).toHaveLength(1);
    await expect(x.app.close()).rejects.toThrow('cleanup_incomplete');
    expect(x.app.metrics().pendingNativeReads).toBe(1);
    expect(f.state.trace).toContain('closed:result_reader');
    expect(f.state.trace).not.toContain('close:outbox');
    held.resolve();
    expect(await outcome).toMatchObject({ code: 'closed' });
    await x.app.close();
    expect(x.app.metrics().pendingNativeReads).toBe(0);
    await expect(x.app.nativeResult(grant, delivery)).rejects.toThrow('closed');
  });
});

describe('optin room manager shares existing application owners', () => {
  it('keeps source reads and dispatch live while direct close drains accepted room input', async () => {
    const held = deferred(),
      x = fixture(
        {},
        {
          configuration: { schemaVersion: 1, port: await port(), recoverBindingId: null },
          publisherToken: 'n'.repeat(43),
          forbiddenBearers: [],
        },
      );
    const endpoints = await x.app.start(),
      ready = x.app.roomControlReady()!,
      opened = opening(ready.nodeEpoch),
      safe = { ...opened, binding: { ...opened.binding, nativeBearer: 'x'.repeat(43) } };
    await roomPost(ready.endpoint.port, 'open', safe, 'n'.repeat(43));
    f.state.holds.set('drain_native', held.promise);
    const closing = x.app.close().catch((error: unknown) => error);
    try {
      await vi.waitFor(() => expect(f.state.calls.some((v) => v[1] === 'drain_native')).toBe(true));
      expect(f.state.trace).not.toContain('quiesce:native_gateway');
      expect(f.state.trace).not.toContain('close:history');
      expect(
        await post(endpoints.read.port, '/v1/policy/discovery', Buffer.from('{"schemaVersion":1}')),
      ).toMatchObject({ status: 200, value: { items: [], overflow: false } });
      expect(await closing).toMatchObject({ code: 'cleanup_incomplete' });
      held.resolve();
      await vi.waitFor(() => expect(x.app.metrics().closed).toBe(true));
      expect(f.state.trace).toContain('quiesced:native_gateway');
    } finally {
      held.resolve();
      f.state.holds.delete('drain_native');
      await x.app.close();
    }
  });
  it('binds one additional listener while using the one existing native inbox/reader', async () => {
    const roomOptions: NativeRoomOptions = {
      configuration: { schemaVersion: 1, port: await port(), recoverBindingId: null },
      publisherToken: 'n'.repeat(43),
      forbiddenBearers: [account, worker, publisher],
    };
    const x = fixture({}, roomOptions);
    await x.app.start();
    try {
      const ready = x.app.roomControlReady()!;
      expect(ready.endpoint.port).toBe(roomOptions.configuration.port);
      expect(x.app.metrics().ownedResources).toBe(10);
      expect(f.state.trace.filter((v) => v === 'new:history')).toHaveLength(1);
      expect(f.state.trace.filter((v) => v === 'new:result_reader')).toHaveLength(1);
      const a = opening(ready.nodeEpoch);
      const safe = { ...a, binding: { ...a.binding, nativeBearer: 'x'.repeat(43) } };
      expect((await roomPost(ready.endpoint.port, 'open', safe, 'n'.repeat(43))).status).toBe(200);
      expect(f.state.calls.find((v) => v[0] === 'native_bind')?.[1]).toBe('n'.repeat(43));
      expect(
        (await roomPost(ready.endpoint.port, 'close', command(safe), 'n'.repeat(43))).status,
      ).toBe(200);
    } finally {
      await x.app.close();
    }
    expect(x.borrowedClose).not.toHaveBeenCalled();
  });
  it('withholds shared storage close while the child manager retains actual grant revocation', async () => {
    const x = fixture(
      {},
      {
        configuration: { schemaVersion: 1, port: await port(), recoverBindingId: null },
        publisherToken: 'n'.repeat(43),
        forbiddenBearers: [],
      },
    );
    const hold = deferred();
    try {
      await x.app.start();
      const ready = x.app.roomControlReady()!,
        a = opening(ready.nodeEpoch),
        safe = { ...a, binding: { ...a.binding, nativeBearer: 'x'.repeat(43) } };
      await roomPost(ready.endpoint.port, 'open', safe, 'n'.repeat(43));
      f.state.holds.set('native_revoke', hold.promise);
      const closing = x.app.close().catch((e) => e);
      await vi.waitFor(() => expect(f.state.trace).toContain('native_revoke'));
      expect(f.state.trace).not.toContain('close:history');
      expect(f.state.trace).not.toContain('close:outbox');
      expect(await closing).toMatchObject({ code: 'cleanup_incomplete' });
      hold.resolve();
      await vi.waitFor(() => expect(f.state.trace).toContain('closed:history'));
      await x.app.close();
      expect(f.state.trace.filter((v) => v === 'close:history')).toHaveLength(1);
      expect(x.borrowedClose).not.toHaveBeenCalled();
    } finally {
      hold.resolve();
      f.state.holds.delete('native_revoke');
      await x.app.close();
    }
  });
  it('rejects a role-colliding room controller before constructing any public owner', () => {
    expect(() =>
      fixture(
        {},
        {
          configuration: { schemaVersion: 1, port: 11029, recoverBindingId: null },
          publisherToken: account,
          forbiddenBearers: [],
        },
      ),
    ).toThrow('invalid_input');
    expect(f.state.trace).toEqual([]);
  });
});

describe('native bridge application ownership', () => {
  async function options() {
    return {
      configuration: { schemaVersion: 1 as const, port: await port(), recoverBindingId: null },
      publisherToken: 'n'.repeat(43),
      forbiddenBearers: [account, worker, publisher],
    };
  }
  it('owns the public context facade/server before gateway drive and routes only attached current native work to actual SDK HTTP', async () => {
    const w = await nativeWorker(),
      room = await options(),
      bridge: NativeBridgeConfiguration = {
        schemaVersion: 1,
        prepareEndpoint: { host: '127.0.0.1', port: w.port },
        rehydrationPort: await port(),
      },
      x = fixture({}, room, bridge);
    try {
      await x.app.start();
      expect(x.app.metrics().ownedResources).toBe(12);
      expect(x.app.nativeBridgeReady()).toEqual({
        prepareEndpoint: bridge.prepareEndpoint,
        rehydrationEndpoint: { host: '127.0.0.1', port: bridge.rehydrationPort },
      });
      expect(f.state.trace.filter((v) => v === 'new:history')).toHaveLength(1);
      expect(f.state.trace.filter((v) => v === 'new:context_reader')).toHaveLength(1);
      const ready = x.app.roomControlReady()!,
        base = opening(ready.nodeEpoch),
        a = { ...base, binding: { ...base.binding, nativeBearer: 'x'.repeat(43) } };
      await roomPost(ready.endpoint.port, 'open', a, 'n'.repeat(43));
      const stored = input('native', 1),
        message = {
          ...stored,
          event: { ...stored.event, senderId: a.binding.bindingId },
        } as StoredMessage,
        ports = f.state.nativePorts as DispatchPorts,
        currentCase = {
          scope,
          caseId: 'case',
          revision: '1',
          source: 'synthetic_read_only' as const,
        };
      await expect(
        ports.agent.prepare({ message, currentCase }, new AbortController().signal),
      ).rejects.toMatchObject({ code: 'DispatchUnavailable' });
      expect(x.forbidden).not.toHaveBeenCalled();
      expect(
        (
          await roomPost(
            ready.endpoint.port,
            'attach-agent',
            { ...command(a), bindingId: a.binding.bindingId, prepareBearer: 's'.repeat(43) },
            'n'.repeat(43),
          )
        ).status,
      ).toBe(200);
      expect(
        await ports.agent.prepare({ message, currentCase }, new AbortController().signal),
      ).toMatchObject({ caseRevision: '1' });
      expect(w.state.requests).toHaveLength(1);
      expect(x.forbidden).not.toHaveBeenCalled();
    } finally {
      await x.app.close();
      await w.close();
    }
    expect(x.borrowedClose).not.toHaveBeenCalled();
  });
  it('keeps shared storage alive until context reader close resolves, then retries actual owner', async () => {
    const room = await options(),
      x = fixture({}, room, {
        schemaVersion: 1,
        prepareEndpoint: { host: '127.0.0.1', port: await port() },
        rehydrationPort: await port(),
      });
    try {
      await x.app.start();
      f.state.failClose.add('context_reader');
      await expect(x.app.close()).rejects.toThrow('cleanup_incomplete');
      expect(f.state.trace).not.toContain('close:outbox');
      expect(x.app.metrics().closed).toBe(false);
      f.state.failClose.delete('context_reader');
      await x.app.close();
      expect(f.state.trace.indexOf('closed:context_reader')).toBeLessThan(
        f.state.trace.indexOf('close:history'),
      );
    } finally {
      f.state.failClose.clear();
      await x.app.close();
    }
  });
  it('rejects bridge without room control and conflicting listener ports before any owner/query', async () => {
    const bridge: NativeBridgeConfiguration = {
      schemaVersion: 1,
      prepareEndpoint: { host: '127.0.0.1', port: 11030 },
      rehydrationPort: 11032,
    };
    expect(() => fixture({}, undefined, bridge)).toThrow('invalid_input');
    const x = fixture({}, await options(), bridge);
    await expect(x.app.start({ nativePort: 11032 })).rejects.toThrow('invalid_input');
    expect(f.state.trace).toEqual([]);
    await x.app.close();
  });
  it('fails a busy context bind without starting gateways or losing partially constructed owners', async () => {
    const server = (await import('node:http')).createServer();
    await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
    const endpoint = server.address();
    if (!endpoint || typeof endpoint === 'string') throw new Error('fixture');
    const x = fixture({}, await options(), {
      schemaVersion: 1,
      prepareEndpoint: { host: '127.0.0.1', port: await port() },
      rehydrationPort: endpoint.port,
    });
    try {
      await expect(x.app.start()).rejects.toThrow('unavailable');
      await x.app.close();
      expect(f.state.trace).not.toContain('listen:native_gateway');
      expect(x.app.metrics().ownedResources).toBe(0);
      expect(x.app.nativeBridgeReady()).toBeNull();
    } finally {
      await x.app.close();
      await new Promise<void>((r) => server.close(() => r()));
    }
  });
});
