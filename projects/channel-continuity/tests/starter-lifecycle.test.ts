/** Actual starter ownership over mocked public dependencies; no PostgreSQL qualification. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mkdtempSync, chmodSync, realpathSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const boundary = vi.hoisted(() => ({
  clients: [] as { user: string; end: ReturnType<typeof vi.fn> }[],
  events: [] as string[],
  installed: vi.fn<() => Promise<void>>(),
  history: vi.fn<() => Promise<unknown>>(),
  inboxClose: vi.fn<() => Promise<void>>(),
  caseInspect: vi.fn<() => Promise<unknown>>(),
  caseClose: vi.fn<() => Promise<void>>(),
  route: vi.fn<() => Promise<unknown>>(),
  routerClose: vi.fn<() => Promise<void>>(),
  gatewayListen: vi.fn<() => Promise<{ host: '127.0.0.1'; port: number }>>(),
  gatewayClose: vi.fn<() => Promise<void>>(),
  outboxSend: vi.fn<() => Promise<unknown>>(),
  outboxClose: vi.fn<() => Promise<void>>(),
  constructors: { inbox: 0, case: 0, router: 0, gateway: 0 },
  profileDigest: '',
  definitionDigest: '',
}));
vi.mock('pg', () => ({
  default: {
    Client: class {
      readonly user: string;
      readonly end = vi.fn(async () => {
        boundary.events.push('mutex-end');
      });
      constructor(config: { user: string }) {
        this.user = config.user;
        boundary.clients.push(this);
      }
      on() {
        return this;
      }
      async connect() {
        boundary.events.push('mutex-connect');
      }
      async query(text: string) {
        if (text.includes('current_user')) return { rows: [{ name: this.user }] };
        if (text.includes('SELECT version,profile_id'))
          return {
            rows: [
              {
                version: 1,
                profile_id: '11111111-1111-4111-8111-111111111111',
                config_digest: boundary.profileDigest,
                definition_digest: boundary.definitionDigest,
              },
            ],
          };
        if (text.includes('pg_try_advisory_lock')) return { rows: [{ acquired: true }] };
        if (text.includes('pg_advisory_unlock')) return { rows: [{ pg_advisory_unlock: true }] };
        throw new Error('Unexpected synthetic query');
      }
    },
  },
}));
vi.mock('@livekit-ecosystem/channel-continuity/migrations', () => ({
  installChannelSchema: () => boundary.installed(),
  upgradeChannelSchemaV2: async () => {},
  upgradeChannelSchemaV3: async () => {},
  upgradeChannelSchemaV4: async () => {},
  upgradeChannelSchemaV5: async () => {},
  upgradeChannelSchemaV6: async () => {},
  upgradeChannelSchemaV7: async () => {},
}));
vi.mock('@livekit-ecosystem/channel-continuity/postgres', async () => {
  const real = await vi.importActual<
    typeof import('@livekit-ecosystem/channel-continuity/postgres')
  >('@livekit-ecosystem/channel-continuity/postgres');
  return {
    ...real,
    ChannelInbox: class {
      constructor() {
        boundary.constructors.inbox++;
      }
      history() {
        return boundary.history();
      }
      close() {
        boundary.events.push('inbox-close');
        return boundary.inboxClose();
      }
    },
  };
});
vi.mock('@livekit-ecosystem/channel-continuity/reference-case', () => ({
  installReferenceCaseSchema: async () => {},
  ReferenceCaseAuthority: class {
    constructor() {
      boundary.constructors.case++;
    }
    inspect() {
      return boundary.caseInspect();
    }
    close() {
      boundary.events.push('case-close');
      return boundary.caseClose();
    }
  },
}));
vi.mock('@livekit-ecosystem/channel-continuity/routing', async () => {
  const real = await vi.importActual<
    typeof import('@livekit-ecosystem/channel-continuity/routing')
  >('@livekit-ecosystem/channel-continuity/routing');
  return {
    ...real,
    RevisionRouter: class {
      constructor() {
        boundary.constructors.router++;
      }
      route() {
        return boundary.route();
      }
      close() {
        boundary.events.push('router-close');
        return boundary.routerClose();
      }
    },
  };
});
vi.mock('@livekit-ecosystem/channel-continuity/gateway', async () => {
  const real = await vi.importActual<
    typeof import('@livekit-ecosystem/channel-continuity/gateway')
  >('@livekit-ecosystem/channel-continuity/gateway');
  return {
    ...real,
    ChannelGateway: class {
      constructor() {
        boundary.constructors.gateway++;
      }
      listen() {
        return boundary.gatewayListen();
      }
      close() {
        boundary.events.push('gateway-close');
        return boundary.gatewayClose();
      }
      metrics() {
        return { active: 0, sockets: 0, handlers: 0 };
      }
    },
  };
});
vi.mock('@livekit-ecosystem/channel-continuity/outbox', async () => {
  const real = await vi.importActual<typeof import('@livekit-ecosystem/channel-continuity/outbox')>(
    '@livekit-ecosystem/channel-continuity/outbox',
  );
  return {
    ...real,
    ChannelOutbox: class {
      send() {
        return boundary.outboxSend();
      }
      close() {
        return boundary.outboxClose();
      }
    },
  };
});

import {
  createStandaloneApplication,
  createStandaloneOwner,
} from '../examples/standalone/application.js';
import {
  parseConfig,
  profileDigest,
  StarterError,
  writePrivateJson,
} from '../examples/standalone/config.js';
import { EXTERNAL_DEFINITION_DIGEST } from '../examples/standalone/receipt-store.js';
import { main } from '../examples/standalone-channel.js';
import { ExternalOperationClient } from '../examples/standalone/external-http.js';
import { RoutingError } from '@livekit-ecosystem/channel-continuity/routing';
import { ChannelError } from '@livekit-ecosystem/channel-continuity/postgres';

const ownerId = '11111111111141118111111111111111';
const receiptId = '22222222-2222-4222-8222-222222222222';
const request = {
  schemaVersion: 1,
  kind: 'booking_investigation',
  bookingReference: 'DEMO-1',
  newCheckIn: '2030-01-02',
  investigationConsent: true,
} as const;
function config() {
  return {
    schemaVersion: 1,
    profileId: '11111111-1111-4111-8111-111111111111',
    postgres: { host: '127.0.0.1', port: 5432, database: 'livekit_lab' },
    schemas: {
      inbox: 'p2_inbox_' + ownerId,
      case: 'p2_case_' + ownerId,
      external: 'p2_demo_' + ownerId,
    },
    bindings: [
      {
        alias: 'primary',
        providerScope: { tenantId: 'tenant', provider: 'fake_sms', providerAccountId: 'carrier' },
        accountScope: { tenantId: 'tenant', accountId: 'account' },
        caseId: 'case',
        conversationId: 'conversation',
        senderId: 'sender',
        initialCase: { revision: '0', request },
      },
    ],
    endpoints: { gateway: 12001, external: 12002 },
    limits: { maxInbox: 64, externalReceipts: 16 },
  };
}
function runtime() {
  return {
    schemaVersion: 1,
    role: 'runtime',
    profileId: config().profileId,
    postgresPassword: 'password-private-'.repeat(3),
    bindings: [
      {
        alias: 'primary',
        accountToken: 'a'.repeat(43),
        publisherToken: 'b'.repeat(43),
        recoveryToken: 'c'.repeat(43),
      },
    ],
    providerHmac: Buffer.alloc(32, 1).toString('base64url'),
    callbackHmac: Buffer.alloc(32, 2).toString('base64url'),
    externalBearers: [
      {
        alias: 'primary',
        operation: 'd'.repeat(43),
        ordinary: 'e'.repeat(43),
        idempotent: 'f'.repeat(43),
      },
    ],
  };
}
function owner() {
  return {
    schemaVersion: 1,
    role: 'owner',
    profileId: config().profileId,
    postgresPassword: 'owner-private-'.repeat(3),
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void;
  const promise = new Promise<T>((ok, bad) => {
    resolve = ok;
    reject = bad;
  });
  return { promise, resolve, reject };
}
function observed<T>(promise: Promise<T>) {
  return promise.then(
    (value) => ({ status: 'fulfilled' as const, value }),
    (error) => ({ status: 'rejected' as const, error }),
  );
}
async function flush() {
  for (let index = 0; index < 20; index++) await Promise.resolve();
}
const directories: string[] = [];
beforeEach(() => {
  vi.clearAllMocks();
  boundary.clients.length = 0;
  boundary.events.length = 0;
  boundary.constructors = { inbox: 0, case: 0, router: 0, gateway: 0 };
  boundary.profileDigest = profileDigest(parseConfig(config()));
  boundary.definitionDigest = EXTERNAL_DEFINITION_DIGEST;
  vi.spyOn(ExternalOperationClient.prototype, 'preflight').mockResolvedValue(undefined);
  boundary.installed.mockRejectedValue(new StarterError('Unavailable'));
  boundary.history.mockResolvedValue({ messages: [] });
  boundary.inboxClose.mockResolvedValue();
  boundary.caseInspect.mockResolvedValue({
    scope: { tenantId: 'tenant', accountId: 'account' },
    caseId: 'case',
    revision: '1',
    request,
    cancelled: false,
    committed: false,
  });
  boundary.caseClose.mockResolvedValue();
  boundary.route.mockResolvedValue({ status: 'revised', receiptId });
  boundary.routerClose.mockResolvedValue();
  boundary.gatewayListen.mockResolvedValue({ host: '127.0.0.1', port: 12001 });
  boundary.gatewayClose.mockResolvedValue();
  boundary.outboxSend.mockResolvedValue({
    status: 'unknown',
    outboundId: receiptId,
    attemptId: null,
  });
  boundary.outboxClose.mockResolvedValue();
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  for (const path of directories.splice(0)) rmSync(path, { recursive: true, force: true });
});

describe('public starter application ownership (mocked dependency I/O)', () => {
  it('keeps import/construction/plan inert and rejects foreign credential roles before allocation', async () => {
    const application = createStandaloneApplication(config(), runtime());
    const bootstrap = createStandaloneOwner(config(), owner());
    expect(boundary.clients).toHaveLength(0);
    expect(boundary.constructors.inbox).toBe(0);
    expect(() => createStandaloneOwner(config(), runtime())).toThrow(StarterError);
    expect(() => createStandaloneApplication(config(), owner())).toThrow(StarterError);
    const output: string[] = [];
    const sink = vi.spyOn(process.stdout, 'write').mockImplementation((value) => {
      output.push(String(value));
      return true;
    });
    try {
      expect(await main(['plan'])).toBe(0);
    } finally {
      sink.mockRestore();
    }
    expect(JSON.parse(output.join('')).setupStarted).toBe(false);
    expect(boundary.clients).toHaveLength(0);
    await application.close();
    await bootstrap.close();
  });

  it('retains exactly one owner close observation while a public migration is actually pending', async () => {
    vi.useFakeTimers();
    const held = deferred<void>();
    boundary.installed.mockReturnValue(held.promise);
    const value = createStandaloneOwner(config(), owner());
    const work = observed(value.bootstrap());
    await flush();
    expect(boundary.installed).toHaveBeenCalledTimes(1);
    expect(boundary.clients).toHaveLength(1);
    const closing = value.close();
    const closeResult = observed(closing);
    expect(value.close()).toBe(closing);
    await vi.advanceTimersByTimeAsync(2000);
    expect((await closeResult).status).toBe('rejected');
    expect(boundary.clients[0]!.end).not.toHaveBeenCalled();
    expect(value.close()).toBe(closing);
    expect(boundary.installed).toHaveBeenCalledTimes(1);
    held.reject(new StarterError('Unavailable'));
    await work;
    await flush();
    await expect(value.close()).resolves.toBeUndefined();
    expect(boundary.clients[0]!.end).toHaveBeenCalledTimes(1);
  });

  it('withholds the mode mutex when a public migration reports unresolved cleanup', async () => {
    boundary.installed.mockRejectedValue(new StarterError('CleanupIncomplete'));
    const value = createStandaloneOwner(config(), owner());
    await expect(value.bootstrap()).rejects.toMatchObject({ code: 'CleanupIncomplete' });
    await expect(value.close()).rejects.toMatchObject({ code: 'CleanupIncomplete' });
    expect(boundary.clients[0]!.end).not.toHaveBeenCalled();
    await expect(value.bootstrap()).rejects.toMatchObject({ code: 'Closed' });
  });

  it('preserves a primary migration error while its known cleanup cause withholds the mutex', async () => {
    const primary = new ChannelError('SchemaMismatch');
    Object.defineProperty(primary, 'cause', { value: new ChannelError('CleanupIncomplete') });
    boundary.installed.mockRejectedValue(primary);
    const value = createStandaloneOwner(config(), owner());
    await expect(value.bootstrap()).rejects.toMatchObject({ code: 'SchemaMismatch' });
    await expect(value.close()).rejects.toMatchObject({ code: 'CleanupIncomplete' });
    expect(boundary.clients[0]!.end).not.toHaveBeenCalled();
  });

  it('retains the real route cleanup before closing shared inbox/case/mutex owners', async () => {
    vi.useFakeTimers();
    const held = deferred<void>();
    boundary.routerClose.mockReturnValue(held.promise);
    const value = createStandaloneApplication(config(), runtime());
    const route = observed(value.route('primary', receiptId));
    await flush();
    expect(boundary.routerClose).toHaveBeenCalledTimes(1);
    expect(boundary.inboxClose).not.toHaveBeenCalled();
    expect(boundary.caseClose).not.toHaveBeenCalled();
    expect(boundary.clients[0]!.end).not.toHaveBeenCalled();
    const closing = value.close(),
      outcome = observed(closing);
    await vi.advanceTimersByTimeAsync(2000);
    expect((await outcome).status).toBe('rejected');
    expect(value.close()).toBe(closing);
    await expect(value.history('primary')).rejects.toMatchObject({ code: 'Closed' });
    expect(value.metrics().commandsActive).toBe(1);
    held.resolve();
    await route;
    await flush();
    await value.close();
    expect(value.metrics()).toEqual({
      commandsActive: 0,
      retainedGraphs: 0,
      gatewayActive: false,
      closing: true,
    });
    expect(boundary.inboxClose).toHaveBeenCalledTimes(1);
    expect(boundary.caseClose).toHaveBeenCalledTimes(1);
    expect(boundary.events.indexOf('mutex-end')).toBeGreaterThan(
      boundary.events.indexOf('case-close'),
    );
  });

  it('preserves the original command failure across a failed dependent close and useful close retry', async () => {
    boundary.route.mockRejectedValue(new RoutingError('RevisionConflict'));
    boundary.routerClose
      .mockRejectedValueOnce(new StarterError('CleanupIncomplete'))
      .mockResolvedValue(undefined);
    const value = createStandaloneApplication(config(), runtime());
    await expect(value.route('primary', receiptId)).rejects.toMatchObject({
      code: 'RevisionConflict',
    });
    expect(boundary.inboxClose).not.toHaveBeenCalled();
    expect(boundary.caseClose).not.toHaveBeenCalled();
    await value.close();
    expect(boundary.routerClose).toHaveBeenCalledTimes(2);
    expect(boundary.inboxClose).toHaveBeenCalledTimes(1);
    expect(value.metrics().retainedGraphs).toBe(0);
  });

  it('rejects new commands while an actual prior history read still owns its graph', async () => {
    const held = deferred<unknown>();
    boundary.history.mockReturnValue(held.promise);
    const value = createStandaloneApplication(config(), runtime());
    const pending = observed(value.history('primary'));
    await flush();
    await expect(value.history('primary')).rejects.toMatchObject({ code: 'Overloaded' });
    expect(boundary.constructors.inbox).toBe(1);
    expect(boundary.history).toHaveBeenCalledTimes(1);
    held.resolve({ messages: [] });
    expect((await pending).status).toBe('fulfilled');
    await value.close();
    expect(value.metrics().commandsActive).toBe(0);
  });

  it('does not create a late gateway after close is requested during a real public case read', async () => {
    const held = deferred<unknown>();
    boundary.caseInspect.mockReturnValue(held.promise);
    const value = createStandaloneApplication(config(), runtime());
    const starting = observed(value.startGateway());
    await flush();
    expect(boundary.caseInspect).toHaveBeenCalledTimes(1);
    const closing = value.close();
    held.resolve({
      scope: { tenantId: 'tenant', accountId: 'account' },
      caseId: 'case',
      revision: '1',
      request,
      cancelled: false,
      committed: false,
    });
    const outcome = await starting;
    expect(outcome.status).toBe('rejected');
    // In-flight startup reports Unavailable after its fresh closing check.
    // The invariant is that no new gateway is admitted after that check.
    if (outcome.status === 'rejected') expect(outcome.error).toMatchObject({ code: 'Unavailable' });
    await closing;
    expect(boundary.constructors.gateway).toBe(0);
    expect(boundary.caseClose).toHaveBeenCalledTimes(1);
    expect(boundary.clients[0]!.end).toHaveBeenCalledTimes(1);
  });

  it('refuses startup before constructing case/gateway owners when the actual source profile is denied', async () => {
    vi.mocked(ExternalOperationClient.prototype.preflight).mockRejectedValue(
      new StarterError('SchemaMismatch'),
    );
    const value = createStandaloneApplication(config(), runtime());
    await expect(value.startGateway()).rejects.toMatchObject({ code: 'SchemaMismatch' });
    await value.close();
    expect(boundary.constructors.case).toBe(0);
    expect(boundary.constructors.gateway).toBe(0);
    expect(boundary.clients[0]!.end).toHaveBeenCalledTimes(1);
  });

  it('retains ignored source-profile startup work beyond the caller deadline and never binds a late gateway', async () => {
    vi.useFakeTimers();
    const held = deferred<void>();
    vi.mocked(ExternalOperationClient.prototype.preflight).mockReturnValue(held.promise);
    const value = createStandaloneApplication(config(), runtime());
    const starting = observed(value.startGateway());
    await flush();
    expect(ExternalOperationClient.prototype.preflight).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5000);
    const result = await starting;
    expect(result.status).toBe('rejected');
    if (result.status === 'rejected') expect(result.error).toMatchObject({ code: 'Unavailable' });
    expect(value.metrics().retainedGraphs).toBe(1);
    expect(boundary.clients[0]!.end).not.toHaveBeenCalled();
    expect(boundary.constructors.case).toBe(0);
    expect(boundary.constructors.gateway).toBe(0);
    const closing = value.close(),
      closeResult = observed(closing);
    await vi.advanceTimersByTimeAsync(2000);
    expect((await closeResult).status).toBe('rejected');
    expect(value.close()).toBe(closing);
    held.resolve();
    // A timed-out observation remains rejected while its actual close drains.
    // Observe the actual retained graph, then ask the public owner again.
    await vi.waitFor(() => expect(value.metrics().retainedGraphs).toBe(0));
    await value.close();
    expect(boundary.clients[0]!.end).toHaveBeenCalledTimes(1);
    expect(value.metrics().retainedGraphs).toBe(0);
    expect(boundary.constructors.gateway).toBe(0);
  });

  it('refuses explicit dispatch when the actual external profile is denied', async () => {
    vi.mocked(ExternalOperationClient.prototype.preflight).mockRejectedValue(
      new StarterError('SchemaMismatch'),
    );
    const value = createStandaloneApplication(config(), runtime());
    await expect(value.dispatch('primary', receiptId)).rejects.toMatchObject({
      code: 'SchemaMismatch',
    });
    await value.close();
    expect(boundary.constructors.inbox).toBe(0);
    expect(boundary.constructors.case).toBe(0);
  });

  it('fences CLI startup immediately when SIGTERM arrives during retained profile I/O', async () => {
    const directory = realpathSync(mkdtempSync(join(tmpdir(), 'starter-cli-startup-')));
    chmodSync(directory, 0o700);
    directories.push(directory);
    const configPath = join(directory, 'config.json'),
      credentialsPath = join(directory, 'credentials.json');
    writePrivateJson(configPath, config());
    writePrivateJson(credentialsPath, runtime());
    const held = deferred<void>();
    vi.mocked(ExternalOperationClient.prototype.preflight).mockReturnValue(held.promise);
    const sink = vi.spyOn(process.stdout, 'write').mockReturnValue(true);
    const pending = observed(
      main(['serve', '--config', configPath, '--credentials', credentialsPath]),
    );
    try {
      await vi.waitFor(() =>
        expect(ExternalOperationClient.prototype.preflight).toHaveBeenCalledTimes(1),
      );
      process.emit('SIGTERM');
      held.resolve();
      await pending;
      expect(boundary.constructors.case).toBe(0);
      expect(boundary.constructors.gateway).toBe(0);
    } finally {
      held.resolve();
      await pending;
      sink.mockRestore();
    }
  });

  it('keeps an observed ordinary send unknown in actual CLI stdout without private configuration/body values', async () => {
    const directory = realpathSync(mkdtempSync(join(tmpdir(), 'starter-cli-lifecycle-')));
    chmodSync(directory, 0o700);
    directories.push(directory);
    const configPath = join(directory, 'config.json'),
      credentialsPath = join(directory, 'credentials.json'),
      inputPath = join(directory, 'input.json');
    writePrivateJson(configPath, config());
    writePrivateJson(credentialsPath, runtime());
    writePrivateJson(inputPath, {
      bindingAlias: 'primary',
      outboundId: receiptId,
      capability: 'ordinary_fake_sms_v1',
    });
    const lines: string[] = [];
    const sink = vi.spyOn(process.stdout, 'write').mockImplementation((value) => {
      lines.push(String(value));
      return true;
    });
    let code: number;
    try {
      code = await main([
        'send',
        '--config',
        configPath,
        '--credentials',
        credentialsPath,
        '--input',
        inputPath,
      ]);
    } finally {
      sink.mockRestore();
    }
    expect(code).toBe(1);
    const raw = lines.join(''),
      result = JSON.parse(raw);
    expect(result).toMatchObject({
      command: 'send',
      status: 'unknown',
      code: 'OutcomeUnknown',
      cleanupComplete: true,
      result: { status: 'unknown' },
    });
    for (const value of [
      runtime().postgresPassword,
      runtime().providerHmac,
      runtime().callbackHmac,
      ...Object.values(runtime().bindings[0]!).filter((x) => x !== 'primary'),
      ...Object.values(runtime().externalBearers[0]!).filter((x) => x !== 'primary'),
    ])
      expect(raw).not.toContain(value);
    expect(boundary.outboxSend).toHaveBeenCalledTimes(1);
    expect(boundary.outboxClose).toHaveBeenCalledTimes(1);
  });
});
