import { afterEach, describe, expect, it } from 'vitest';
import {
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  chmodSync,
  symlinkSync,
  linkSync,
  rmSync,
  readFileSync,
  statSync,
  realpathSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  canonicalJson,
  parseConfig,
  parseCredentials,
  parseJson,
  readPrivateJson,
  writePrivateJson,
  safeStarterCode,
  StarterError,
} from '../examples/standalone/config.js';

const inputs = () => ({
  schemaVersion: 1,
  profileId: '11111111-1111-4111-8111-111111111111',
  postgres: { host: '127.0.0.1', port: 5432, database: 'livekit_lab' },
  schemas: {
    inbox: 'p2_inbox_' + 'a'.repeat(32),
    case: 'p2_case_' + 'a'.repeat(32),
    external: 'p2_demo_' + 'a'.repeat(32),
  },
  bindings: [
    {
      alias: 'primary',
      providerScope: { tenantId: 't', provider: 'fake_sms', providerAccountId: 'carrier' },
      accountScope: { tenantId: 't', accountId: 'a' },
      caseId: 'case',
      conversationId: 'conversation',
      senderId: 'sender',
      initialCase: {
        revision: '0',
        request: {
          schemaVersion: 1,
          kind: 'booking_investigation',
          bookingReference: 'DEMO-1',
          newCheckIn: '2030-01-01',
          investigationConsent: true,
        },
      },
    },
  ],
  endpoints: { gateway: 12001, external: 12002 },
  limits: { maxInbox: 64, externalReceipts: 16 },
});
const credentials = () => ({
  schemaVersion: 1,
  role: 'runtime',
  profileId: inputs().profileId,
  postgresPassword: 'p'.repeat(40),
  bindings: [
    {
      alias: 'primary',
      accountToken: 'a'.repeat(40),
      publisherToken: 'b'.repeat(40),
      recoveryToken: 'c'.repeat(40),
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
});
const bytes = (s: string) => Buffer.from(s, 'utf8');
const owned: string[] = [];
afterEach(() => {
  for (const p of owned.splice(0)) rmSync(p, { recursive: true, force: true });
});
function directory(): string {
  const p = realpathSync(mkdtempSync(join(tmpdir(), 'starter-unit-')));
  chmodSync(p, 0o700);
  owned.push(p);
  return p;
}

describe('standalone configuration authority and snapshots', () => {
  it('snapshots a fixed binding and distinct source credentials without reading setup', () => {
    const input = inputs(),
      secret = credentials(),
      config = parseConfig(input),
      c = parseCredentials(secret, config);
    input.bindings[0]!.accountScope.accountId = 'changed';
    secret.bindings[0]!.accountToken = 'z'.repeat(40);
    expect(config.bindings[0]!.accountScope.accountId).toBe('a');
    expect(c.role === 'runtime' && c.bindings[0]!.accountToken).toBe('a'.repeat(40));
    expect(Object.isFrozen(config.bindings)).toBe(true);
    expect(Object.isFrozen(config.bindings[0]!.initialCase.request)).toBe(true);
    expect(parseConfig(JSON.parse(JSON.stringify(config)))).toEqual(config);
  });
  it.each([null, [], true, 'runtime', { role: 'runtime' }])(
    'returns a fixed error for malformed credential boundary %j',
    (v) => {
      expect(() => parseCredentials(v, parseConfig(inputs()))).toThrow(StarterError);
    },
  );
  it('never invokes record or array accessors while validating trusted configuration', () => {
    const input = inputs();
    let calls = 0;
    Object.defineProperty(input.bindings, '0', {
      enumerable: true,
      configurable: true,
      get() {
        calls++;
        return {};
      },
    });
    expect(() => parseConfig(input)).toThrow(StarterError);
    expect(calls).toBe(0);
    const c = credentials();
    Object.defineProperty(c, 'role', {
      enumerable: true,
      get() {
        calls++;
        return 'runtime';
      },
    });
    expect(() => parseCredentials(c, parseConfig(inputs()))).toThrow(StarterError);
    expect(calls).toBe(0);
  });
  it('rejects foreign tuples, dynamic modules and role confusion', () => {
    const input = inputs();
    input.bindings[0]!.accountScope.tenantId = 'foreign';
    expect(() => parseConfig(input)).toThrow(StarterError);
    expect(() => parseConfig({ ...inputs(), module: './untrusted.js' })).toThrow(StarterError);
    expect(() =>
      parseCredentials({ ...credentials(), role: 'owner' }, parseConfig(inputs())),
    ).toThrow(StarterError);
    expect(() =>
      parseConfig({ ...inputs(), postgres: { ...inputs().postgres, host: 'example.invalid' } }),
    ).toThrow(StarterError);
  });
  it('never reflects fabricated error getters or unknown runtime codes', () => {
    let calls = 0;
    const fake = Object.create(StarterError.prototype) as StarterError;
    Object.defineProperty(fake, 'code', {
      get() {
        calls++;
        return 'SENTINEL_PRIVATE';
      },
    });
    expect(safeStarterCode(fake)).toBeUndefined();
    expect(calls).toBe(0);
    const known = new StarterError('AccessDenied');
    expect(safeStarterCode(known)).toBe('AccessDenied');
    expect(() =>
      Object.defineProperty(known, 'code', {
        get() {
          calls++;
          return 'SENTINEL_PRIVATE';
        },
      }),
    ).toThrow();
    expect(safeStarterCode(new StarterError('SENTINEL_PRIVATE' as never))).toBe('Unavailable');
    expect(calls).toBe(0);
  });
  it('rejects duplicate account and provider capability tokens', () => {
    const c = credentials();
    c.bindings[0]!.accountToken = c.externalBearers[0]!.ordinary;
    expect(() => parseCredentials(c, parseConfig(inputs()))).toThrow(StarterError);
  });
  it('rejects invalid calendar days and a supplied initial business commitment', () => {
    const c = inputs();
    c.bindings[0]!.initialCase.request.newCheckIn = '2030-02-31';
    expect(() => parseConfig(c)).toThrow(StarterError);
    expect(() =>
      parseConfig({
        ...inputs(),
        bindings: [
          {
            ...inputs().bindings[0],
            initialCase: { ...inputs().bindings[0]!.initialCase, committed: true },
          },
        ],
      }),
    ).toThrow(StarterError);
  });
});
describe('strict private JSON and file boundary', () => {
  it.each([
    '{"a":1,"a":2}',
    '{"a":1,"\\u0061":2}',
    '{"n":1e999}',
    '{"n":9007199254740993}',
    '{"x":"\\ud800"}',
    '[1,]',
    '{"x":true}x',
    '\ufeff{}',
  ])('rejects duplicate/noncanonical or unbounded input %s', (s) => {
    expect(() => parseJson(bytes(s))).toThrow(StarterError);
  });
  it('preserves actual Unicode and exact decimal strings, rejecting malformed UTF8', () => {
    expect(parseJson(bytes('{"body":"गंतव्य 🐈","revision":"9223372036854775807"}'))).toEqual({
      body: 'गंतव्य 🐈',
      revision: '9223372036854775807',
    });
    expect(() => parseJson(Uint8Array.from([0xc3, 0x28]))).toThrow(StarterError);
    expect(() => parseJson(bytes('[]'), 1)).toThrow(StarterError);
  });
  it('writes only exclusive private facts and rejects overwrite/symlink/hardlink/unsafe modes', () => {
    const dir = directory(),
      p = join(dir, 'proof.json');
    writePrivateJson(p, { fact: 'original' });
    expect(statSync(p).mode & 0o777).toBe(0o600);
    expect(readPrivateJson(p)).toEqual({ fact: 'original' });
    expect(() => writePrivateJson(p, { fact: 'changed' })).toThrow(StarterError);
    expect(readFileSync(p, 'utf8')).toContain('original');
    const symlink = join(dir, 'symlink');
    symlinkSync(p, symlink);
    expect(() => readPrivateJson(symlink)).toThrow(StarterError);
    const hardlink = join(dir, 'hardlink');
    linkSync(p, hardlink);
    expect(() => readPrivateJson(hardlink)).toThrow(StarterError);
    rmSync(hardlink);
    chmodSync(p, 0o644);
    expect(() => readPrivateJson(p)).toThrow(StarterError);
  });
  it('rejects a readable private file under a shared or symlinked parent', () => {
    const dir = directory(),
      p = join(dir, 'config');
    writeFileSync(p, '{}', { mode: 0o600 });
    chmodSync(dir, 0o755);
    expect(() => readPrivateJson(p)).toThrow(StarterError);
    chmodSync(dir, 0o700);
    const outside = directory(),
      link = join(outside, 'alias');
    symlinkSync(dir, link);
    expect(() => readPrivateJson(join(link, 'config'))).toThrow(StarterError);
    mkdirSync(join(dir, 'nested'), { mode: 0o700 });
  });
});
describe('catalog representation correlation', () => {
  it('accepts JSONB object key order while preserving every table, column and constraint', () => {
    const observed = {
      owner: 'continuity_migrator',
      relations: [
        {
          name: 'receipts',
          columns: [['id', 'uuid', true, null]],
          constraints: ['PRIMARY KEY (id)'],
        },
      ],
      functions: [],
    };
    const jsonb = {
      functions: [],
      relations: [
        {
          constraints: ['PRIMARY KEY (id)'],
          columns: [['id', 'uuid', true, null]],
          name: 'receipts',
        },
      ],
      owner: 'continuity_migrator',
    };
    expect(canonicalJson(jsonb)).toBe(canonicalJson(observed));
    expect(
      canonicalJson({
        ...jsonb,
        relations: [{ ...jsonb.relations[0], columns: [['id', 'text', true, null]] }],
      }),
    ).not.toBe(canonicalJson(observed));
    expect(
      canonicalJson({ ...jsonb, relations: [{ ...jsonb.relations[0], constraints: [] }] }),
    ).not.toBe(canonicalJson(observed));
  });
  it('never sorts arrays or executes catalog accessors', () => {
    expect(canonicalJson([1, 2])).not.toBe(canonicalJson([2, 1]));
    let calls = 0;
    const v = Object.defineProperty({}, 'value', {
      enumerable: true,
      get() {
        calls++;
        return 1;
      },
    });
    expect(() => canonicalJson(v)).toThrow(StarterError);
    expect(calls).toBe(0);
  });
});
