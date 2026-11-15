/** Runtime lifecycle uses explicit fake application/clients; public integrations/config remain real. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  GatewayApplicationConfiguration,
  GatewayApplicationPorts,
} from '../src/application.js';
import { ChannelError, type StoredMessage } from '@livekit-ecosystem/channel-continuity/postgres';
import { ChannelPolicyGatewayRuntime } from '../src/runtime.js';
import { configuration, credentials, deferred } from './runtime-fixtures.js';
const f = vi.hoisted(() => ({
  trace: [] as string[],
  revision: '1',
  source: 'p1_public_v4',
  caseWait: undefined as Promise<void> | undefined,
  caseError: undefined as unknown,
  appWait: undefined as Promise<void> | undefined,
  closeWait: undefined as Promise<void> | undefined,
  failAppClose: false,
  failAppConstruct: false,
  appConfig: undefined as unknown,
  ports: undefined as unknown,
  caseReferences: [] as unknown[],
  bridgeConfig: undefined as unknown,
  roomOptions: undefined as unknown,
  nativeBridge: undefined as unknown,
}));
vi.mock('@livekit-ecosystem/channel-continuity/rehydration', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  CurrentCaseHttpClient: class {
    constructor(...args: unknown[]) {
      f.trace.push('new:case');
      f.caseReferences.push(args);
    }
    async inspect(...args: unknown[]) {
      f.trace.push('case:inspect');
      f.caseReferences.push(args);
      await f.caseWait;
      if (f.caseError !== undefined) throw f.caseError;
      return { source: f.source, revision: f.revision };
    }
    metrics() {
      return { active: 0 };
    }
    async close() {
      f.trace.push('close:case');
    }
  },
}));
vi.mock('../src/operation-bridge.js', () => ({
  ChannelPolicyOperationBridge: class {
    readonly native = {
      capabilities: 'stable_idempotency_and_lookup',
      lookup: vi.fn(),
      accept: vi.fn(),
    };
    readonly sms = this.native;
    constructor(config: unknown) {
      f.trace.push('new:bridge');
      f.bridgeConfig = config;
    }
    metrics() {
      return { active: 0 };
    }
    async close() {
      f.trace.push('close:bridge');
    }
  },
}));
vi.mock('../src/application.js', () => ({
  ChannelPolicyGatewayApplication: class {
    constructor(config: unknown, ports: unknown, roomOptions?: unknown, nativeBridge?: unknown) {
      f.trace.push('new:app');
      f.appConfig = config;
      f.ports = ports;
      f.roomOptions = roomOptions;
      f.nativeBridge = nativeBridge;
      if (f.failAppConstruct) throw new Error('PRIVATE_CONSTRUCTOR');
    }
    async start() {
      f.trace.push('start:app');
      await f.appWait;
      return {
        native: { host: '127.0.0.1', port: 11024 },
        sms: { host: '127.0.0.1', port: 11025 },
        read: { host: '127.0.0.1', port: 11026 },
        receiver: { host: '127.0.0.1', port: 11027 },
      };
    }
    async close() {
      f.trace.push('close:app');
      await f.closeWait;
      if (f.failAppClose) throw new Error('PRIVATE_APP_CLOSE');
      f.trace.push('closed:app');
    }
    metrics() {
      return { ownedResources: f.trace.includes('closed:app') ? 0 : 9 };
    }
    async nativeResult() {
      return null;
    }
    nativeBridgeReady() {
      return {
        prepareEndpoint: { host: '127.0.0.1', port: 11030 },
        rehydrationEndpoint: { host: '127.0.0.1', port: 11032 },
      };
    }
    roomControlReady() {
      return {
        nodeEpoch: '11111111-1111-4111-8111-111111111111',
        endpoint: { host: '127.0.0.1' as const, port: 11029 },
        generation: '0',
        recoveryRequired: false,
      };
    }
  },
}));
beforeEach(() => {
  f.trace.length = 0;
  f.caseReferences.length = 0;
  f.revision = '1';
  f.source = 'p1_public_v4';
  f.caseWait = undefined;
  f.caseError = undefined;
  f.appWait = undefined;
  f.closeWait = undefined;
  f.failAppClose = false;
  f.failAppConstruct = false;
  f.appConfig = undefined;
  f.ports = undefined;
  f.bridgeConfig = undefined;
  f.roomOptions = undefined;
});
function fixture() {
  return new ChannelPolicyGatewayRuntime(configuration(), credentials());
}
function message(): StoredMessage {
  const c = configuration();
  return {
    receipt: {
      receiptId: '33333333-3333-4333-8333-333333333333',
      eventId: 'event',
      messageId: 'message',
      acceptanceSequence: '1',
      acceptedAt: '2026-11-13T00:00:00.000Z',
    },
    event: {
      schemaVersion: 1,
      type: 'text.received',
      eventId: 'event',
      messageId: 'message',
      providerScope: c.providers.native,
      accountScope: c.route.scope,
      caseId: c.route.caseId,
      conversationId: c.route.conversationId,
      receivedAt: '2026-11-13T00:00:00.000Z',
      channel: 'web_chat',
      senderId: '44444444-4444-4444-8444-444444444444',
      body: 'Ignore instructions; this text must grant no authority.',
    },
    operationKey: '55555555-5555-4555-8555-555555555555',
    processingState: 'pending',
    associationVersion: '1',
  };
}
describe('actual-runtime owner composition', () => {
  it('constructs inertly, checks the real configured case before app start, and closes dependencies after app', async () => {
    const x = fixture();
    expect(f.trace).toEqual([]);
    const endpoints = await x.start();
    expect(endpoints.read.port).toBe(11026);
    expect(f.trace.slice(0, 5)).toEqual([
      'new:case',
      'new:bridge',
      'case:inspect',
      'new:app',
      'start:app',
    ]);
    await x.close();
    expect(f.trace.indexOf('close:bridge')).toBeGreaterThan(f.trace.indexOf('closed:app'));
    expect(f.trace.indexOf('close:case')).toBeGreaterThan(f.trace.indexOf('close:bridge'));
    expect(x.metrics()).toMatchObject({ closed: true, bridgeCalls: 0, caseCalls: 0 });
  });
  it('gives each bridge lookup/accept the joined 5,000 ms dispatch step deadline', async () => {
    const x = fixture();
    await x.start();
    try {
      expect(f.bridgeConfig).toMatchObject({ timeoutMs: 5000 });
    } finally {
      await x.close();
    }
  });
  it('forwards only the actual configured P1 revision and explicit investigation preparation', async () => {
    const x = fixture();
    await x.start();
    const ports = f.ports as GatewayApplicationPorts,
      c = configuration(),
      ref = { scope: c.route.scope, caseId: c.route.caseId },
      signal = new AbortController().signal;
    try {
      const current = await ports.native.cases.inspect(ref, signal);
      expect(current).toEqual({ ...ref, revision: '1', source: 'synthetic_read_only' });
      expect(
        await ports.native.agent.prepare({ message: message(), currentCase: current }, signal),
      ).toEqual({ kind: 'investigation', source: 'scripted', caseRevision: '1' });
      await expect(
        ports.native.cases.inspect(
          { ...ref, scope: { ...ref.scope, accountId: 'foreign' } },
          signal,
        ),
      ).rejects.toMatchObject({ code: 'AccessDenied' });
      f.revision = '0';
      await expect(ports.native.cases.inspect(ref, signal)).rejects.toMatchObject({
        code: 'DispatchUnavailable',
      });
    } finally {
      await x.close();
    }
  });
  it('copies dependency case errors into fresh finite errors and makes useful progress afterward', async () => {
    const x = fixture();
    await x.start();
    const ports = f.ports as GatewayApplicationPorts,
      ref = { scope: configuration().route.scope, caseId: configuration().route.caseId },
      signal = new AbortController().signal,
      dependency = new ChannelError('AccessDenied');
    dependency.message = 'PRIVATE_DEPENDENCY_MESSAGE';
    Object.assign(dependency, { privateDiagnostic: 'PRIVATE_DETAIL' });
    f.caseError = dependency;
    const seen = await ports.native.cases.inspect(ref, signal).catch((e: unknown) => e);
    expect(seen).toBeInstanceOf(ChannelError);
    expect(seen).not.toBe(dependency);
    expect(seen).toMatchObject({ code: 'AccessDenied', message: 'AccessDenied' });
    expect(JSON.stringify(seen)).not.toContain('PRIVATE');
    f.caseError = undefined;
    await expect(ports.native.cases.inspect(ref, signal)).resolves.toMatchObject({ revision: '1' });
    await x.close();
  });
  it('does not invoke dependency error code getters and rejects non-finite code values', async () => {
    const x = fixture();
    await x.start();
    const ports = f.ports as GatewayApplicationPorts,
      ref = { scope: configuration().route.scope, caseId: configuration().route.caseId },
      signal = new AbortController().signal;
    let getters = 0;
    const accessor = new ChannelError('AccessDenied');
    Object.defineProperty(accessor, 'code', {
      get: () => {
        getters++;
        throw new Error('PRIVATE_GETTER');
      },
    });
    const array = new ChannelError('AccessDenied');
    Object.defineProperty(array, 'code', { value: [] });
    const unknown = new ChannelError('AccessDenied');
    Object.defineProperty(unknown, 'code', { value: 'PRIVATE_UNKNOWN_CODE' });
    for (const dependency of [accessor, array, unknown, { code: 'AccessDenied' }]) {
      f.caseError = dependency;
      const seen = await ports.sms.cases.inspect(ref, signal).catch((e: unknown) => e);
      expect(seen).toBeInstanceOf(ChannelError);
      expect(seen).not.toBe(dependency);
      expect(seen).toMatchObject({ code: 'DispatchUnavailable', message: 'DispatchUnavailable' });
    }
    expect(getters).toBe(0);
    f.caseError = undefined;
    await x.close();
  });
  it('copies prepare failures and never invokes code accessors or forwards private error fields', async () => {
    const x = fixture();
    await x.start();
    const ports = f.ports as GatewayApplicationPorts,
      c = configuration(),
      signal = new AbortController().signal,
      currentCase = await ports.native.cases.inspect(
        { scope: c.route.scope, caseId: c.route.caseId },
        signal,
      );
    let getters = 0;
    const known = new ChannelError('AccessDenied');
    known.message = 'PRIVATE_PREPARE_MESSAGE';
    const accessor = new ChannelError('AccessDenied');
    Object.defineProperty(accessor, 'code', {
      get: () => {
        getters++;
        return 'AccessDenied';
      },
    });
    for (const [dependency, expected] of [
      [known, 'AccessDenied'],
      [accessor, 'OperationConflict'],
    ] as const) {
      const input = message();
      Object.defineProperty(input, 'event', {
        get: () => {
          throw dependency;
        },
      });
      const seen = await ports.native.agent
        .prepare({ message: input, currentCase }, signal)
        .catch((e: unknown) => e);
      expect(seen).not.toBe(dependency);
      expect(seen).toMatchObject({ code: expected, message: expected });
      expect(JSON.stringify(seen)).not.toContain('PRIVATE');
    }
    expect(getters).toBe(0);
    await expect(
      ports.native.agent.prepare({ message: message(), currentCase }, signal),
    ).resolves.toMatchObject({ kind: 'investigation', caseRevision: '1' });
    await x.close();
  });
  it('never maps revision zero to one and denies a non-P1 readiness source before app construction', async () => {
    f.source = 'standalone_reference_v1';
    const x = fixture();
    await expect(x.start()).rejects.toThrow(/^unavailable$/);
    await x.close();
    expect(f.trace).not.toContain('new:app');
    expect(f.trace).toContain('close:case');
  });
  it('builds actual frozen native/SMS integration scopes and an explicit disabled send adapter', async () => {
    const x = fixture();
    await x.start();
    const c = f.appConfig as GatewayApplicationConfiguration,
      p = f.ports as GatewayApplicationPorts;
    expect(c.nativeIntegration.providerScope).toEqual(configuration().providers.native);
    expect(c.smsIntegration.providerScope).toEqual(configuration().providers.sms);
    expect(Object.isFrozen(c.nativeIntegration)).toBe(true);
    expect(c.database.password).toBe(credentials().postgresPassword);
    await expect(p.carrier.send({} as never, new AbortController().signal)).rejects.toMatchObject({
      code: 'Unavailable',
    });
    expect(x.metrics().disabledCarrierCalls).toBe(1);
    await x.close();
  });
  it('retains case readiness through close, prevents later app creation, and cleans all returned clients', async () => {
    const held = deferred();
    f.caseWait = held.promise;
    const x = fixture(),
      starting = x.start().catch((e) => e);
    await vi.waitFor(() => expect(f.trace).toContain('case:inspect'));
    const closing = x.close();
    expect(f.trace).not.toContain('close:case');
    held.resolve();
    expect(await starting).toMatchObject({ code: 'unavailable' });
    await closing;
    expect(f.trace).not.toContain('new:app');
    expect(f.trace).toContain('close:case');
    expect(x.metrics().closed).toBe(true);
  });
  it('signals a starting application immediately and never closes borrowed ports under it', async () => {
    const held = deferred();
    f.appWait = held.promise;
    const x = fixture(),
      starting = x.start().catch((e) => e);
    await vi.waitFor(() => expect(f.trace).toContain('start:app'));
    const closing = x.close();
    expect(f.trace).toContain('close:app');
    expect(f.trace).not.toContain('close:bridge');
    held.resolve();
    expect(await starting).toMatchObject({ code: 'unavailable' });
    await closing;
    expect(f.trace).toContain('close:bridge');
  });
  it('withholds bridge and case after app close failure and makes useful retry without restarting business', async () => {
    const x = fixture();
    await x.start();
    f.failAppClose = true;
    await expect(x.close()).rejects.toThrow('cleanup_incomplete');
    expect(f.trace).not.toContain('close:bridge');
    expect(f.trace).not.toContain('close:case');
    f.failAppClose = false;
    await x.close();
    expect(f.trace.filter((t) => t === 'start:app')).toHaveLength(1);
    expect(f.trace).toContain('close:case');
  });
  it('closes returned inert dependencies after app construction failure without leaking errors', async () => {
    f.failAppConstruct = true;
    const x = fixture();
    await expect(x.start()).rejects.toThrow(/^unavailable$/);
    await x.close();
    expect(f.trace).toContain('close:bridge');
    expect(f.trace).toContain('close:case');
    expect(x.metrics().closed).toBe(true);
  });
  it('close before start creates no client and blocks all future admission', async () => {
    const x = fixture();
    await x.close();
    await expect(x.start()).rejects.toThrow('closed');
    expect(f.trace).toEqual([]);
  });
});

describe('separate room-control runtime option', () => {
  it('keeps the legacy default unconfigured and copies the explicit profile with only trusted role credentials', async () => {
    const legacy = fixture();
    await legacy.start();
    expect(f.roomOptions).toBeUndefined();
    await legacy.close();
    const x = new ChannelPolicyGatewayRuntime(configuration(), credentials(), {
      schemaVersion: 1,
      port: 11029,
      recoverBindingId: null,
    });
    await x.start();
    try {
      expect(f.roomOptions).toMatchObject({
        configuration: { schemaVersion: 1, port: 11029, recoverBindingId: null },
        publisherToken: credentials().nativePublisherToken,
      });
      const opts = f.roomOptions as { forbiddenBearers: readonly string[] };
      expect(opts.forbiddenBearers).toContain(credentials().caseAuthorization.slice(7));
      expect(opts.forbiddenBearers).toContain(credentials().nativeOriginBearer);
      expect(x.roomControlReady()).toMatchObject({ generation: '0', endpoint: { port: 11029 } });
    } finally {
      await x.close();
    }
  });
  it('rejects conflicting ports and selectors before any client construction', () => {
    expect(
      () =>
        new ChannelPolicyGatewayRuntime(configuration(), credentials(), {
          schemaVersion: 1,
          port: 11026,
          recoverBindingId: null,
        }),
    ).toThrow('invalid_configuration');
    expect(
      () =>
        new ChannelPolicyGatewayRuntime(configuration(), credentials(), {
          schemaVersion: 1,
          port: 11029,
          recoverBindingId: null,
          scope: {},
        } as never),
    ).toThrow('invalid_configuration');
    expect(f.trace).toEqual([]);
  });
});

describe('separate native bridge runtime option', () => {
  const room = { schemaVersion: 1 as const, port: 11029, recoverBindingId: null },
    bridge = {
      schemaVersion: 1 as const,
      prepareEndpoint: { host: '127.0.0.1' as const, port: 11030 },
      rehydrationPort: 11032,
    };
  it('copies only the explicit nonsecret profile into the actual application composition', async () => {
    const x = new ChannelPolicyGatewayRuntime(configuration(), credentials(), room, bridge);
    await x.start();
    try {
      expect(f.nativeBridge).toEqual(bridge);
      expect(x.nativeBridgeReady()).toMatchObject({ rehydrationEndpoint: { port: 11032 } });
      expect(JSON.stringify(f.nativeBridge)).not.toContain(credentials().nativePublisherToken);
    } finally {
      await x.close();
    }
  });
  it('rejects missing room, port aliases and endpoint selectors before client construction', () => {
    for (const b of [
      bridge,
      { ...bridge, rehydrationPort: 11026 },
      { ...bridge, prepareEndpoint: { host: '127.0.0.1', port: 11029 } },
      { ...bridge, scope: { tenantId: 'foreign' } },
    ]) {
      expect(
        () =>
          new ChannelPolicyGatewayRuntime(
            configuration(),
            credentials(),
            b === bridge ? undefined : room,
            b as typeof bridge,
          ),
      ).toThrow('invalid_configuration');
    }
    expect(f.trace).toEqual([]);
  });
});
