/** Pure origin-fixture guards: no database, compiler, child, provider or listener. */
import { describe, expect, it, vi } from 'vitest';
import * as fs from 'node:fs';
import { createHash } from 'node:crypto';
import {
  readFileSync,
  realpathSync,
  mkdtempSync,
  chmodSync,
  rmSync,
  writeFileSync,
  symlinkSync,
  linkSync,
  statSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { Server, Socket } from 'node:net';
import pg from 'pg';
import {
  ORIGIN_MODES,
  OriginFixtureError,
  OriginBudget,
  Context,
  parseEnvironment,
  parseFixture,
  parseReady,
  parseSetup,
  parsePrepared,
  parseNativeView,
  safeCode,
  isEntrypoint,
  readProof,
  proofPublished,
  writeProof,
  run,
} from './pg_channel_origin_cases.js';

vi.mock('node:fs', async (importOriginal) => {
  const actual = await importOriginal<typeof import('node:fs')>();
  return { ...actual, linkSync: vi.fn(actual.linkSync), openSync: vi.fn(actual.openSync) };
});
const actualFS = await vi.importActual<typeof import('node:fs')>('node:fs');

const SCHEMA = 'p2_origin_' + 'a'.repeat(32),
  A = '11111111-1111-4111-8111-111111111111',
  B = '22222222-2222-4222-8222-222222222222',
  C = '33333333-3333-4333-8333-333333333333',
  D = '44444444-4444-4444-8444-444444444444',
  E = '55555555-5555-4555-8555-555555555555';
const NOW = 2000000000000;
function environment(mode = 'race'): Record<string, string> {
  return {
    PATH: '/pinned/bin',
    LANG: 'en_US.UTF-8',
    CI: '1',
    NO_COLOR: '1',
    P2_ORIGIN_DIRECTORY: '/private/tmp/origin-fixture',
    P2_ORIGIN_SCHEMA: SCHEMA,
    P2_ORIGIN_PG_PORT: '5432',
    ...Object.fromEntries(
      [
        'ACCOUNT_TOKEN',
        'NATIVE_PUBLISHER_TOKEN',
        'PUBLISHER_TOKEN',
        'NATIVE_A_BEARER',
        'NATIVE_B_BEARER',
        'OPERATION_TOKEN',
      ].map((k, n) => ['P2_ORIGIN_' + k, String(n).repeat(43)]),
    ),
    P2_ORIGIN_CASE_AUTHORIZATION: 'Bearer ' + 'c'.repeat(43),
    ...(mode === 'setup' || mode === 'cleanup'
      ? { P2_ORIGIN_OWNER_PASSWORD: 'synthetic-owner-password-0000000000' }
      : {}),
    ...(mode !== 'cleanup'
      ? { P2_ORIGIN_RUNTIME_PASSWORD: 'synthetic-runtime-password-0000000000' }
      : {}),
  };
}
const fixture = () => ({
  schema_version: 1,
  scope: { tenantId: 'origin_tenant', accountId: 'origin_account' },
  case_id: 'origin_case',
  conversation_id: 'origin_conversation',
  recipient_id: 'origin_recipient',
  p2_schema: SCHEMA,
  case_endpoint: { host: '127.0.0.1', port: 12345 },
  native_binding_ids: { a: A, b: B },
  parent_expires_at_ms: NOW + 179000,
});
const setup = () => ({
  schema_version: 1,
  receiver_id: E,
  inputs: { original: { receiptId: A, operationKey: B }, ack: { receiptId: C, operationKey: D } },
});
const goldens = JSON.parse(
  readFileSync(
    new URL('../../../contracts/delegation/channel-policy-v3.json', import.meta.url),
    'utf8',
  ),
) as {
  p2_cases: Array<{
    name: string;
    submission: unknown;
    payload_canonical: string;
    payload_sha256: string;
  }>;
};
function privateState(work: (directory: string) => void) {
  const dir = realpathSync(mkdtempSync(join(tmpdir(), 'origin-fixture-')));
  chmodSync(dir, 0o700);
  try {
    work(dir);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

describe('origin fixture pure configuration and evidence contracts', () => {
  it('imports and validates configuration without opening database, listener or process', async () => {
    const pool = vi.spyOn(pg.Pool.prototype, 'connect').mockImplementation(() => {
        throw Error('NO_DB');
      }),
      client = vi.spyOn(pg.Client.prototype, 'connect').mockImplementation(() => {
        throw Error('NO_DB');
      }),
      listen = vi.spyOn(Server.prototype, 'listen').mockImplementation(() => {
        throw Error('NO_LISTEN');
      });
    try {
      vi.resetModules();
      const imported = await import('./pg_channel_origin_cases.js');
      expect(imported.ORIGIN_MODES).toEqual(ORIGIN_MODES);
      expect(imported.parseEnvironment('race', environment()).mode).toBe('race');
      expect(pool).not.toHaveBeenCalled();
      expect(client).not.toHaveBeenCalled();
      expect(listen).not.toHaveBeenCalled();
    } finally {
      pool.mockRestore();
      client.mockRestore();
      listen.mockRestore();
    }
  });
  it.each(ORIGIN_MODES)('validates exact role credentials before I/O: %s', (mode) => {
    const env = parseEnvironment(mode, environment(mode));
    expect(env.mode).toBe(mode);
    expect(Object.isFrozen(env)).toBe(true);
    expect(Object.isFrozen(env.tokens)).toBe(true);
    expect('ownerPassword' in env).toBe(['setup', 'cleanup'].includes(mode));
    expect('runtimePassword' in env).toBe(mode !== 'cleanup');
  });
  it('accepts guarded real process.env descriptors without reading ambient names or values', () => {
    const synthetic = environment('setup'),
      descriptor = vi.fn((_target: NodeJS.ProcessEnv, key: string | symbol) =>
        Object.getOwnPropertyDescriptor(synthetic, key),
      ),
      guarded = new Proxy(process.env, {
        ownKeys: () => Reflect.ownKeys(synthetic),
        getOwnPropertyDescriptor: descriptor,
        get() {
          throw Error('NO_ENV_VALUE_READ');
        },
      });
    // Preserve the real Node host object's prototype; no ambient key values or
    // descriptors are read, printed, copied, modified, or retained.
    expect(Object.getPrototypeOf(guarded)).toBe(Object.getPrototypeOf(process.env));
    expect(parseEnvironment('setup', guarded)).toMatchObject({ mode: 'setup', schema: SCHEMA });
    expect(descriptor).toHaveBeenCalledTimes(Reflect.ownKeys(synthetic).length);
    expect(Object.keys(parseEnvironment('setup', guarded).tokens)).toHaveLength(6);
  });
  it('rejects unknown environment keys before evaluating any data descriptor', () => {
    const descriptor = vi.fn(() => {
        throw Error('NO_DESCRIPTOR_READ');
      }),
      guarded = new Proxy(process.env, {
        ownKeys: () => [...Object.keys(environment()), 'UNDECLARED_PRIVATE_KEY'],
        getOwnPropertyDescriptor: descriptor,
        get() {
          throw Error('NO_ENV_VALUE_READ');
        },
      });
    expect(() => parseEnvironment('race', guarded)).toThrowError('invalid_environment');
    expect(descriptor).not.toHaveBeenCalled();
    const prototype = { inherited: 'unused' };
    expect(() =>
      parseFixture(
        Object.assign(Object.create(prototype), fixture()),
        parseEnvironment('race', environment()),
        NOW,
      ),
    ).toThrowError('invalid_fixture');
  });
  it('snapshots the configured tokens and endpoints without caller-owned references', () => {
    const raw = environment(),
      parsed = parseEnvironment('race', raw);
    raw.P2_ORIGIN_ACCOUNT_TOKEN = 'z'.repeat(43);
    raw.P2_ORIGIN_DIRECTORY = '/private/tmp/changed';
    expect(parsed.tokens.ACCOUNT_TOKEN).toBe('0'.repeat(43));
    expect(parsed.directory).toBe('/private/tmp/origin-fixture');
    const input = fixture(),
      value = parseFixture(input, parsed, NOW);
    input.scope.accountId = 'changed';
    input.native_binding_ids.a = C;
    input.case_endpoint.port = 1;
    expect(value.scope.accountId).toBe('origin_account');
    expect(value.native_binding_ids.a).toBe(A);
    expect(value.case_endpoint.port).toBe(12345);
    expect(Object.isFrozen(value.scope)).toBe(true);
    expect(Object.isFrozen(value.native_binding_ids)).toBe(true);
    expect(Object.isFrozen(value.case_endpoint)).toBe(true);
  });
  it('rejects all undeclared or role-inappropriate environment selectors', () => {
    for (const key of [
      'OPENAI_API_KEY',
      'DEEPGRAM_API_KEY',
      'HTTP_PROXY',
      'HTTPS_PROXY',
      'ALL_PROXY',
      'PGHOST',
      'PGOPTIONS',
      'PGSERVICE',
      'NODE_OPTIONS',
      'PYTHONPATH',
      'HOME',
      'TMPDIR',
      'P2_ORIGIN_UNKNOWN',
      'P2_ORIGIN_OWNER_PASSWORD',
    ])
      expect(() =>
        parseEnvironment('race', { ...environment(), [key]: 'PRIVATE_SENTINEL' }),
      ).toThrowError('invalid_environment');
    for (const mode of ['setup', 'race', 'cleanup']) {
      const env = environment(mode);
      delete (env as Record<string, unknown>)[
        mode === 'cleanup' ? 'P2_ORIGIN_OWNER_PASSWORD' : 'P2_ORIGIN_RUNTIME_PASSWORD'
      ];
      expect(() => parseEnvironment(mode, env)).toThrowError('invalid_environment');
    }
    expect(() =>
      parseEnvironment('cleanup', {
        ...environment('cleanup'),
        P2_ORIGIN_RUNTIME_PASSWORD: 'synthetic-runtime-password-0000000000',
      }),
    ).toThrowError('invalid_environment');
  });
  it('rejects malformed values, newline suffixes and an absent mode with finite diagnostics', () => {
    for (const [key, value] of [
      ['P2_ORIGIN_DIRECTORY', 'relative'],
      ['P2_ORIGIN_DIRECTORY', '/private/tmp/a/../b'],
      ['P2_ORIGIN_DIRECTORY', '/private/tmp/a\n'],
      ['P2_ORIGIN_SCHEMA', SCHEMA + '\n'],
      ['P2_ORIGIN_PG_PORT', '05432'],
      ['P2_ORIGIN_PG_PORT', '65536'],
      ['P2_ORIGIN_PG_PORT', true],
      ['P2_ORIGIN_ACCOUNT_TOKEN', 'q'.repeat(42)],
      ['P2_ORIGIN_ACCOUNT_TOKEN', 'q'.repeat(43) + '\n'],
      ['P2_ORIGIN_CASE_AUTHORIZATION', 'Bearer short'],
      ['CI', '0'],
    ] as const) {
      expect(() => parseEnvironment('race', { ...environment(), [key]: value })).toThrowError(
        'invalid_environment',
      );
    }
    for (const mode of [undefined, 'missing', true])
      expect(() => parseEnvironment(mode, environment())).toThrowError('invalid_mode');
  });
  it('does not evaluate ordinary environment getters or reflect trap diagnostics', () => {
    const getter = vi.fn(() => {
        throw Error('PRIVATE_GETTER');
      }),
      value = Object.defineProperty({ ...environment() }, 'P2_ORIGIN_SCHEMA', {
        enumerable: true,
        get: getter,
      });
    expect(() => parseEnvironment('race', value)).toThrowError('invalid_environment');
    expect(getter).not.toHaveBeenCalled();
    expect(() =>
      parseEnvironment(
        'race',
        new Proxy(environment(), {
          ownKeys() {
            throw Error('PRIVATE_PROXY');
          },
        }),
      ),
    ).toThrowError('invalid_environment');
    const poisoned = new OriginFixtureError('invalid_mode');
    Object.defineProperty(poisoned, 'code', {
      get() {
        throw Error('PRIVATE_CODE_GETTER');
      },
    });
    expect(() =>
      parseEnvironment(
        'race',
        new Proxy(environment(), {
          ownKeys() {
            throw poisoned;
          },
        }),
      ),
    ).toThrowError('invalid_environment');
  });
  it('requires the original exact route, distinct native grants, positive finite parent deadline and loopback case port', () => {
    const env = parseEnvironment('race', environment());
    for (const patch of [
      { schema_version: true },
      { extra: 1 },
      { p2_schema: 'p2_origin_' + 'b'.repeat(32) },
      { scope: { tenantId: 'foreign\n', accountId: 'origin_account' } },
      { case_id: 'x'.repeat(65) },
      { case_id: 'origin_case\n' },
      { native_binding_ids: { a: A, b: A } },
      { case_endpoint: { host: 'localhost', port: 12345 } },
      { case_endpoint: { host: '127.0.0.1', port: true } },
      { parent_expires_at_ms: NOW },
      { parent_expires_at_ms: NOW + 180001 },
      { parent_expires_at_ms: true },
    ])
      expect(() => parseFixture({ ...fixture(), ...patch }, env, NOW)).toThrow();
    expect(
      parseFixture({ ...fixture(), parent_expires_at_ms: NOW + 180000 }, env, NOW)
        .parent_expires_at_ms,
    ).toBe(NOW + 180000);
  });
  it('keeps endpoint markers exact and rejects PID and port coercion', () => {
    const base = { schema_version: 1, pid: 123, host: '127.0.0.1', port: 12345 };
    expect(parseReady(base)).toEqual(base);
    for (const value of [
      { ...base, schema_version: true },
      { ...base, pid: 1 },
      { ...base, pid: '123' },
      { ...base, host: 'localhost' },
      { ...base, port: 65536 },
      { ...base, extra: 'PRIVATE_SENTINEL' },
    ])
      expect(() => parseReady(value)).toThrow();
  });
  it('retains source input/operation UUIDs without deriving work identity from them', () => {
    expect(parseSetup(setup())).toEqual(setup());
    for (const value of [
      { ...setup(), extra: 1 },
      { ...setup(), receiver_id: 'bad' },
      { ...setup(), inputs: { ...setup().inputs, ack: { receiptId: A, operationKey: D } } },
      { ...setup(), inputs: { ...setup().inputs, ack: { receiptId: C, operationKey: B } } },
    ])
      expect(() => parseSetup(value)).toThrow();
  });
  it('consumes all actual P2 golden canonical bytes including the independent maximum NUL frame', () => {
    for (const item of goldens.p2_cases) {
      const p = parsePrepared({
        submission: item.submission,
        canonicalPayload: item.payload_canonical,
        payloadDigest: item.payload_sha256,
      });
      expect(p.canonicalPayload).toBe(item.payload_canonical);
      expect(p.payloadDigest).toBe(item.payload_sha256);
      expect(p.submission).toEqual(item.submission);
      expect(Object.isFrozen(p.submission.message)).toBe(true);
    }
  });
  it('rejects coordinated malformed or changed prepared proof before external acceptance', () => {
    const g = goldens.p2_cases[0]!,
      p = {
        submission: g.submission,
        canonicalPayload: g.payload_canonical,
        payloadDigest: g.payload_sha256,
      };
    for (const value of [
      { ...p, payloadDigest: '0'.repeat(64) },
      { ...p, canonicalPayload: ' ' + p.canonicalPayload },
      { ...p, extra: 1 },
      { ...p, submission: { ...(p.submission as object), schemaVersion: true } },
      { ...p, submission: { ...(p.submission as object), caseRevision: '0' } },
      { ...p, submission: { ...(p.submission as object), caseRevision: '9223372036854775808' } },
    ])
      expect(() => parsePrepared(value)).toThrow();
  });
  it('validates native-view values independently of object key order and rejects forged route/receipt/observation', () => {
    const ref = {
        scope: { tenantId: 'origin_tenant', accountId: 'origin_account' },
        caseId: 'origin_case',
        conversationId: 'origin_conversation',
      },
      body = Buffer.from('{"status":"opaque"}'),
      sha = createHash('sha256').update(body).digest('hex'),
      intent = {
        delivery_id: A,
        scope: { tenant_id: ref.scope.tenantId, account_id: ref.scope.accountId },
        work_id: B,
        attempt_id: C,
        result_sha256: sha,
        receiver_id: D,
        recipient_id: 'origin_recipient',
        body: body.toString('base64'),
        prepared_at_ms: NOW - 2,
      },
      receipt = {
        delivery_id: A,
        receipt_id: E,
        receiver_id: D,
        recipient_id: 'origin_recipient',
        result_sha256: sha,
        accepted_at_ms: NOW - 1,
      },
      current = {
        schemaVersion: 1,
        source: 'p1_public_v4',
        ...ref,
        revision: '2',
        request: {
          schemaVersion: 1,
          kind: 'booking_investigation',
          bookingReference: 'DEMO0001',
          newCheckIn: '2030-01-01',
          investigationConsent: true,
        },
        workflow: { taskId: B, state: 'ready', version: '1' },
        intent: { state: 'not_committed', intentId: null },
        mutation: {
          state: 'not_observed',
          outcome: 'not_observed',
          cancellation: 'not_observed',
          effectId: null,
          outcomeEventId: null,
        },
        supplierResult: null,
        sourceRevision: 'a'.repeat(64),
      },
      seen = {
        p2ObservedAt: new Date(NOW).toISOString(),
        caseObservedAt: new Date(NOW + 1).toISOString(),
        disclosureAdmittedAt: new Date(NOW + 2).toISOString(),
        atomic: false,
      },
      value = { schemaVersion: 1, intent, receipt, case: current, observed: seen };
    const parsed = parseNativeView(value, ref);
    expect(parsed.intent).toEqual(intent);
    expect(parsed.receipt).toEqual(receipt);
    expect(parsed.case.revision).toBe('2');
    expect(parsed.observed.atomic).toBe(false);
    for (const mutant of [
      { ...value, observed: { ...seen, atomic: true } },
      { ...value, observed: { ...seen, debug: 'PRIVATE_SENTINEL' } },
      { ...value, receipt: { ...receipt, result_sha256: '0'.repeat(64) } },
      { ...value, case: { ...current, scope: { tenantId: 'foreign', accountId: 'foreign' } } },
      { ...value, intent: { ...intent, extra: 'PRIVATE_SENTINEL' } },
    ])
      expect(() => parseNativeView(mutant, ref)).toThrowError('invalid_proof');
  });
  it('contains hostile code accessors and unknown/raw error text', () => {
    const getter = vi.fn(() => {
      throw Error('PRIVATE_GETTER');
    });
    expect(safeCode(Object.defineProperty({}, 'code', { get: getter }))).toBe('component_failed');
    expect(getter).not.toHaveBeenCalled();
    expect(
      safeCode(
        new Proxy(
          {},
          {
            getOwnPropertyDescriptor() {
              throw Error('PRIVATE_PROXY');
            },
          },
        ),
      ),
    ).toBe('component_failed');
    expect(safeCode(Error('PRIVATE_SENTINEL'))).toBe('component_failed');
    expect(safeCode({ code: 'PRIVATE_SENTINEL' })).toBe('component_failed');
    expect(safeCode({ code: 'OutcomeUnknown' })).toBe('OutcomeUnknown');
    expect(safeCode(new OriginFixtureError('cleanup_incomplete'))).toBe('cleanup_incomplete');
  });
  it('runs only when the actual argv script URL matches and otherwise remains inert', () => {
    const file = resolve('/private/tmp/origin fixture.js'),
      url = pathToFileURL(file).href;
    expect(isEntrypoint(url, ['node', file])).toBe(true);
    expect(isEntrypoint(url, ['node', '/private/tmp/other.js'])).toBe(false);
    expect(isEntrypoint(url, ['node'])).toBe(false);
  });
  it('denies late NativeB business admission while retaining the fixed final cleanup window', async () => {
    const now = Date.now(),
      budget = new OriginBudget(now + 10000, now, 1000),
      cleanup = vi.fn(async () => {});
    expect(budget.businessDeadline).toBe(-9000);
    expect(budget.finalDeadline).toBe(11000);
    expect(() => budget.checkBusiness(1000)).toThrowError('deadline_exceeded');
    expect(() => budget.checkCleanup(1000)).not.toThrow();
    await cleanup();
    expect(cleanup).toHaveBeenCalledTimes(1);
    expect(() => budget.checkCleanup(11000)).toThrowError('cleanup_incomplete');
    expect(Object.isFrozen(budget)).toBe(true);
    const dir = realpathSync(mkdtempSync(join(tmpdir(), 'origin-late-')));
    chmodSync(dir, 0o700);
    const pool = vi.spyOn(pg.Pool.prototype, 'connect').mockImplementation(() => {
        throw Error('NO_LATE_DB');
      }),
      socket = vi.spyOn(Socket.prototype, 'connect').mockImplementation(() => {
        throw Error('NO_LATE_HTTP');
      });
    try {
      writeProof(dir, 'fixture.json', { ...fixture(), parent_expires_at_ms: now + 10000 });
      writeProof(dir, 'origin-case-advanced.json', { schema_version: 1, revision: 2 });
      await expect(
        run('native-read', { ...environment('native-read'), P2_ORIGIN_DIRECTORY: dir }),
      ).rejects.toMatchObject({ code: 'deadline_exceeded', message: 'deadline_exceeded' });
      expect(pool).not.toHaveBeenCalled();
      expect(socket).not.toHaveBeenCalled();
      expect(fs.readdirSync(dir).sort()).toEqual(['fixture.json', 'origin-case-advanced.json']);
    } finally {
      pool.mockRestore();
      socket.mockRestore();
      rmSync(dir, { recursive: true, force: true });
    }
  });
  it('denies late SDK read admission and completion while preserving cleanup observation', async () => {
    const now = Date.now();
    let clock = 1000;
    const timer = vi.spyOn(performance, 'now').mockImplementation(() => clock);
    try {
      const env = parseEnvironment('race', environment()),
        c = new Context(
          env,
          parseFixture({ ...fixture(), parent_expires_at_ms: now + 45000 }, env, now),
        ),
        read = vi.fn(async () => 'private-read-result');
      clock = c.budget.businessDeadline;
      await expect(c.readBusiness(read)).rejects.toMatchObject({ code: 'deadline_exceeded' });
      expect(read).not.toHaveBeenCalled();
      expect(() => c.observe()).not.toThrow();
      clock = c.budget.businessDeadline - 1;
      const late = vi.fn(async () => {
        clock = c.budget.businessDeadline;
        return 'late-read-result';
      });
      await expect(c.readBusiness(late)).rejects.toMatchObject({ code: 'deadline_exceeded' });
      expect(late).toHaveBeenCalledTimes(1);
      expect(() => c.observe()).not.toThrow();
    } finally {
      timer.mockRestore();
    }
  });
  it('retains an actual held close owner until settlement and never advertises complete cleanup', async () => {
    const dir = realpathSync(mkdtempSync(join(tmpdir(), 'origin-held-close-')));
    chmodSync(dir, 0o700);
    let release!: () => void;
    const held = new Promise<void>((ok) => {
      release = ok;
    });
    try {
      const env = parseEnvironment('race', { ...environment(), P2_ORIGIN_DIRECTORY: dir }),
        c = new Context(
          env,
          parseFixture({ ...fixture(), parent_expires_at_ms: Date.now() + 45000 }, env),
        ),
        owner = c.own({ close: vi.fn(() => held) }, 1),
        closing = c.close([owner], 'held-close.json');
      await Promise.resolve();
      expect(owner.close).toHaveBeenCalledTimes(1);
      expect(c.cleanupComplete()).toBe(false);
      expect(c.owned.has(owner)).toBe(true);
      expect(fs.existsSync(join(dir, 'held-close.json'))).toBe(false);
      release();
      expect(await closing).toBe(true);
      expect(c.cleanupComplete()).toBe(true);
      expect(readProof(dir, 'held-close.json')).toMatchObject({ cleanup_complete: true });
    } finally {
      release();
      rmSync(dir, { recursive: true, force: true });
    }
  });
  it('records result-host cleanup false after a failed dependent close and withholds storage teardown', async () => {
    // The inert-import control resets modules: compose every public SDK class
    // from the current module graph rather than mixing old/new class identities.
    const { ChannelResultReceiver, ChannelResultReader } =
        await import('@livekit-ecosystem/channel-continuity/result-receiver'),
      { ChannelOutbox } = await import('@livekit-ecosystem/channel-continuity/outbox'),
      { NativeChannelInbox } = await import('@livekit-ecosystem/channel-continuity/native'),
      { CurrentCaseHttpClient } = await import('@livekit-ecosystem/channel-continuity/rehydration'),
      { run: actualRun } = await import('./pg_channel_origin_cases.js');
    const dir = realpathSync(mkdtempSync(join(tmpdir(), 'origin-result-close-')));
    chmodSync(dir, 0o700);
    const connect = vi.spyOn(pg.Pool.prototype, 'connect').mockImplementation(() => {
        throw Error('NO_DB');
      }),
      socket = vi.spyOn(Socket.prototype, 'connect').mockImplementation(() => {
        throw Error('NO_SOCKET');
      }),
      listen = vi.spyOn(Server.prototype, 'listen').mockImplementation(function (
        this: Server,
        ...args: unknown[]
      ) {
        const ready = args.at(-1);
        if (typeof ready === 'function') queueMicrotask(() => ready());
        return this;
      }),
      address = vi
        .spyOn(Server.prototype, 'address')
        .mockReturnValue({ address: '127.0.0.1', family: 'IPv4', port: 12345 }),
      close = vi.spyOn(Server.prototype, 'close').mockImplementation(function (
        this: Server,
        callback?: (error?: Error) => void,
      ) {
        callback?.();
        return this;
      }),
      receiverClose = vi
        .spyOn(ChannelResultReceiver.prototype, 'close')
        .mockRejectedValue(new Error('PRIVATE_HELD_CLOSE')),
      readerClose = vi.spyOn(ChannelResultReader.prototype, 'close').mockResolvedValue(),
      outboxClose = vi.spyOn(ChannelOutbox.prototype, 'close').mockResolvedValue(),
      inboxClose = vi.spyOn(NativeChannelInbox.prototype, 'close').mockResolvedValue(),
      caseClose = vi.spyOn(CurrentCaseHttpClient.prototype, 'close').mockResolvedValue();
    try {
      writeProof(dir, 'fixture.json', { ...fixture(), parent_expires_at_ms: Date.now() + 45000 });
      writeProof(dir, 'p2-origin-setup.json', setup());
      writeProof(dir, 'origin-result-stop.json', { schema_version: 1, stop: true });
      await expect(
        actualRun('result-host', { ...environment('result-host'), P2_ORIGIN_DIRECTORY: dir }),
      ).rejects.toMatchObject({ code: 'cleanup_incomplete' });
      const proof = readProof(dir, 'origin-result-final.json');
      expect(proof).toMatchObject({
        handlers: 0,
        pending_tasks: 0,
        sockets: 0,
        cleanup_complete: false,
      });
      expect(receiverClose).toHaveBeenCalled();
      expect(readerClose).toHaveBeenCalledTimes(1);
      expect(outboxClose).not.toHaveBeenCalled();
      expect(inboxClose).not.toHaveBeenCalled();
      expect(caseClose).not.toHaveBeenCalled();
      expect(connect).not.toHaveBeenCalled();
      expect(socket).not.toHaveBeenCalled();
      expect(fs.existsSync(join(dir, 'origin-result-storage-ownership.json'))).toBe(false);
      expect(JSON.stringify(proof)).not.toContain('PRIVATE_HELD_CLOSE');
    } finally {
      for (const spy of [
        connect,
        socket,
        listen,
        address,
        close,
        receiverClose,
        readerClose,
        outboxClose,
        inboxClose,
        caseClose,
      ])
        spy.mockRestore();
      rmSync(dir, { recursive: true, force: true });
    }
  });
  it('rejects invalid configuration before any proof read or database ownership', async () => {
    await expect(run('invalid', {})).rejects.toMatchObject({
      code: 'invalid_mode',
      message: 'invalid_mode',
    });
    await expect(
      run('race', { ...environment(), OPENAI_API_KEY: 'PRIVATE_SENTINEL' }),
    ).rejects.toMatchObject({ code: 'invalid_environment', message: 'invalid_environment' });
  });
  it('preserves exact private bytes with exclusive writes and rejects unsafe proof names', () =>
    privateState((dir) => {
      const value = { schema_version: 1, status: 'observed' };
      writeProof(dir, 'proof.json', value);
      expect(readProof(dir, 'proof.json')).toEqual(value);
      expect(statSync(join(dir, 'proof.json')).mode & 0o777).toBe(0o600);
      expect(() => writeProof(dir, 'proof.json', { changed: true })).toThrowError('invalid_proof');
      expect(readProof(dir, 'proof.json')).toEqual(value);
      for (const name of ['../escape.json', '/absolute.json', 'proof.txt', 'a/b.json']) {
        expect(() => readProof(dir, name)).toThrow();
        expect(() => writeProof(dir, name, value)).toThrow();
      }
    }));
  it('publishes only complete fsynced bytes and removes only its owned pending link', () =>
    privateState((dir) => {
      const originalLink = actualFS.linkSync;
      let seen = false;
      const publish = vi.mocked(fs.linkSync).mockImplementation((source, target) => {
        expect(fs.existsSync(target)).toBe(false);
        expect(JSON.parse(fs.readFileSync(source, 'utf8'))).toEqual({
          schema_version: 1,
          status: 'complete',
        });
        expect(fs.statSync(source).mode & 0o777).toBe(0o600);
        seen = true;
        originalLink(source, target);
      });
      try {
        writeProof(dir, 'atomic.json', { schema_version: 1, status: 'complete' });
      } finally {
        publish.mockImplementation(actualFS.linkSync);
      }
      expect(seen).toBe(true);
      expect(fs.readdirSync(dir)).toEqual(['atomic.json']);
      expect(fs.statSync(join(dir, 'atomic.json')).nlink).toBe(1);
    }));
  it('preserves an existing final file and cleans up a failed exclusive publication', () =>
    privateState((dir) => {
      writeProof(dir, 'final.json', { original: true });
      const bytes = fs.readFileSync(join(dir, 'final.json'));
      expect(() => writeProof(dir, 'final.json', { changed: true })).toThrowError('invalid_proof');
      expect(fs.readFileSync(join(dir, 'final.json'))).toEqual(bytes);
      expect(fs.readdirSync(dir)).toEqual(['final.json']);
      const publish = vi.mocked(fs.linkSync).mockImplementation(() => {
        throw Error('PRIVATE_PUBLISH_FAILURE');
      });
      try {
        expect(() => writeProof(dir, 'failed.json', { valid: true })).toThrowError('invalid_proof');
      } finally {
        publish.mockImplementation(actualFS.linkSync);
      }
      expect(fs.readdirSync(dir)).toEqual(['final.json']);
      writeProof(dir, 'failed.json', { valid: true });
      expect(readProof(dir, 'failed.json')).toEqual({ valid: true });
    }));
  it('waits only for the hardlink publication window and keeps strict reads at one link', () =>
    privateState((dir) => {
      writeProof(dir, 'pending.json', { schema_version: 1 });
      fs.linkSync(join(dir, 'pending.json'), join(dir, 'visible.json'));
      expect(proofPublished(dir, 'visible.json')).toBe(false);
      expect(() => readProof(dir, 'visible.json')).toThrowError('invalid_proof');
      fs.unlinkSync(join(dir, 'pending.json'));
      expect(proofPublished(dir, 'visible.json')).toBe(true);
      expect(readProof(dir, 'visible.json')).toEqual({ schema_version: 1 });
      expect(proofPublished(dir, 'missing.json')).toBe(false);
      writeFileSync(join(dir, 'malformed.json'), '{', { mode: 0o600 });
      expect(proofPublished(dir, 'malformed.json')).toBe(true);
      expect(() => readProof(dir, 'malformed.json')).toThrowError('invalid_proof');
    }));
  it('never removes a pending path when exclusive creation did not establish ownership', () =>
    privateState((dir) => {
      const originalOpen = actualFS.openSync;
      const create = vi.mocked(fs.openSync).mockImplementation((path, flags, mode) => {
        if (typeof path === 'string' && path.endsWith('.pending')) {
          writeFileSync(path, 'original-unowned-by-publisher', { flag: 'wx', mode: 0o600 });
          throw Error('PRIVATE_CREATE_CONFLICT');
        }
        return originalOpen(path, flags, mode);
      });
      try {
        expect(() => writeProof(dir, 'absent.json', { valid: true })).toThrowError('invalid_proof');
      } finally {
        create.mockImplementation(actualFS.openSync);
      }
      const remaining = fs.readdirSync(dir);
      expect(remaining).toHaveLength(1);
      expect(remaining[0]).toMatch(/^\.origin-proof-.*\.pending$/);
      expect(fs.readFileSync(join(dir, remaining[0]!), 'utf8')).toBe(
        'original-unowned-by-publisher',
      );
      expect(fs.existsSync(join(dir, 'absent.json'))).toBe(false);
    }));
  it('rejects symlinks, hardlinks, unsafe file/directory modes and oversized state', () =>
    privateState((dir) => {
      writeProof(dir, 'source.json', { status: 'observed' });
      symlinkSync(join(dir, 'source.json'), join(dir, 'symlink.json'));
      expect(() => readProof(dir, 'symlink.json')).toThrowError('invalid_proof');
      linkSync(join(dir, 'source.json'), join(dir, 'hardlink.json'));
      expect(() => readProof(dir, 'hardlink.json')).toThrowError('invalid_proof');
      writeFileSync(join(dir, 'public.json'), '{}', { mode: 0o644 });
      expect(() => readProof(dir, 'public.json')).toThrowError('invalid_proof');
      expect(() => readProof(dir, 'public.json', Number.POSITIVE_INFINITY)).toThrow();
      expect(() => writeProof(dir, 'large.json', { raw: 'x'.repeat(65536) })).toThrowError(
        'invalid_proof',
      );
      chmodSync(dir, 0o755);
      expect(() => readProof(dir, 'source.json')).toThrowError('unsafe_path');
    }));
});
