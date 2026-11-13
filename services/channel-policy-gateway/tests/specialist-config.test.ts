import { chmodSync, linkSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  parseSpecialistConfiguration,
  parseSpecialistConfigurationBytes,
  parseSpecialistCredentials,
  parseSpecialistEnvironment,
  readSpecialistConfiguration,
  specialistFailureCode,
  SpecialistRuntimeError,
} from '../src/specialist-config.js';
import { configuration, evidence, bearer } from './specialist-fixtures.js';
const dirs: string[] = [];
function directory() {
  const d = mkdtempSync('/private/tmp/scripted-specialist-');
  chmodSync(d, 0o700);
  dirs.push(d);
  return d;
}
afterEach(() => {
  for (const d of dirs.splice(0)) rmSync(d, { recursive: true, force: true });
  vi.restoreAllMocks();
});
describe('closed scripted specialist configuration', () => {
  it('copies immutable scope/records and keeps credentials outside JSON', () => {
    const input = configuration(),
      parsed = parseSpecialistConfiguration(input);
    (input.scope as { tenantId: string }).tenantId = 'changed';
    expect(parsed.scope.tenantId).toBe('tenant_demo');
    expect(Object.isFrozen(parsed.evidence[0]!.reference)).toBe(true);
    expect(Object.isFrozen(parsed.evidence)).toBe(true);
    expect(JSON.stringify(parsed)).not.toContain(bearer);
  });
  it('rejects wrong profile, ports and scope before any serving', () => {
    for (const c of [
      { ...configuration(), label: 'model' },
      { ...configuration(), schemaVersion: 2 },
      { ...configuration(), port: 0 },
      { ...configuration(), port: 65536 },
      { ...configuration(), port: NaN },
      { ...configuration(), scope: { tenantId: 'foreign/tenant', accountId: 'a' } },
    ])
      expect(() => parseSpecialistConfiguration(c)).toThrow('invalid_configuration');
  });
  it('rejects accessors, prototypes, symbols and unknown credential/config fields without getter execution', () => {
    const get = vi.fn(() => {
        throw new Error('PRIVATE');
      }),
      c = configuration();
    Object.defineProperty(c, 'scope', { enumerable: true, get });
    expect(() => parseSpecialistConfiguration(c)).toThrow('invalid_configuration');
    expect(get).not.toHaveBeenCalled();
    expect(() => parseSpecialistConfiguration({ ...configuration(), bearer })).toThrow(
      'invalid_configuration',
    );
    expect(() =>
      parseSpecialistConfiguration(Object.assign(Object.create({}), configuration())),
    ).toThrow('invalid_configuration');
    expect(() => parseSpecialistCredentials({ bearer, [Symbol('private')]: 1 })).toThrow(
      'invalid_configuration',
    );
  });
  it('validates exact digest/length/media and padded base64 without rewriting original evidence', () => {
    const c = configuration(),
      e = c.evidence[0]!;
    for (const item of [
      { ...e, bodyBase64: e.bodyBase64.replace(/=+$/, '') + ' ' },
      { ...e, reference: { ...e.reference, sha256: '0'.repeat(64) } },
      { ...e, reference: { ...e.reference, byte_length: e.reference.byte_length + 1 } },
      { ...e, reference: { ...e.reference, width: 1 } },
      { ...e, reference: { ...e.reference, media_type: 'image/png' } },
    ])
      expect(() => parseSpecialistConfiguration({ ...c, evidence: [item] })).toThrow(
        'invalid_configuration',
      );
    expect(parseSpecialistConfiguration(c).evidence[0]!.bodyBase64).toBe(e.bodyBase64);
  });
  it('bounds records/bodies and rejects duplicate scoped source IDs even at another version', () => {
    const c = configuration(),
      e = c.evidence[0]!;
    expect(() =>
      parseSpecialistConfiguration({
        ...c,
        evidence: [e, { ...e, reference: { ...e.reference, version: 'source_v2' } }],
      }),
    ).toThrow('invalid_configuration');
    const records = Array.from({ length: 32 }, (_, i) =>
      evidence('source_' + i, { note: 'bounded' }),
    );
    expect(parseSpecialistConfiguration({ ...c, evidence: records }).evidence).toHaveLength(32);
    expect(() =>
      parseSpecialistConfiguration({ ...c, evidence: [...records, evidence('extra', {})] }),
    ).toThrow('invalid_configuration');
    expect(() => parseSpecialistConfiguration({ ...c, evidence: [] })).toThrow(
      'invalid_configuration',
    );
    expect(() =>
      parseSpecialistConfiguration({
        ...c,
        evidence: [evidence('large', { note: 'x'.repeat(4096) })],
      }),
    ).toThrow('invalid_configuration');
  });
  it('denies sparse/accessor arrays without invoking array getters', () => {
    const c = configuration(),
      items = [c.evidence[0]!],
      get = vi.fn(() => c.evidence[0]);
    Object.defineProperty(items, '0', { get, enumerable: true });
    expect(() => parseSpecialistConfiguration({ ...c, evidence: items })).toThrow(
      'invalid_configuration',
    );
    expect(get).not.toHaveBeenCalled();
    expect(() => parseSpecialistConfiguration({ ...c, evidence: new Array(2) })).toThrow(
      'invalid_configuration',
    );
  });
  it('parses only compact canonical UTF8 JSON plus newline, rejecting duplicates and alternate numbers', () => {
    const raw = JSON.stringify(configuration());
    expect(parseSpecialistConfigurationBytes(Buffer.from(raw + '\n')).port).toBe(11028);
    for (const b of [
      Buffer.from(raw),
      Buffer.from('{"schemaVersion":1,' + raw.slice(1) + '\n'),
      Buffer.from(raw.replace('"schemaVersion":1', '"schemaVersion":1e0') + '\n'),
      Buffer.from(JSON.stringify(configuration(), null, 2) + '\n'),
      Buffer.from([255]),
      Buffer.alloc(262145, 32),
    ])
      expect(() => parseSpecialistConfigurationBytes(b)).toThrow('invalid_configuration');
  });
  it('accepts the one specialist environment role through own data descriptors', () => {
    const e = Object.assign(Object.create({ exotic: true }) as Record<string, string>, {
      PATH: '/usr/bin:/bin',
      P3_DEMO_SPECIALIST_BEARER: bearer,
    });
    expect(parseSpecialistEnvironment(e)).toEqual({ bearer });
    expect(() => parseSpecialistEnvironment({})).toThrow('invalid_configuration');
    expect(() =>
      parseSpecialistEnvironment({ ...e, P3_DEMO_SPECIALIST_BEARER: 'Bearer ' + bearer }),
    ).toThrow('invalid_configuration');
  });
  it('rejects all PG/native/provider roles before reading getters', () => {
    for (const key of [
      'P2_DEMO_POSTGRES_PASSWORD',
      'P2_DEMO_NATIVE_PUBLISHER_TOKEN',
      'OPENAI_API_KEY',
      'P3_DEMO_WORKER_BEARER',
    ]) {
      const e = { P3_DEMO_SPECIALIST_BEARER: bearer },
        get = vi.fn(() => {
          throw new Error('PRIVATE_SECRET');
        });
      Object.defineProperty(e, key, { get, enumerable: true });
      expect(() => parseSpecialistEnvironment(e)).toThrow('invalid_configuration');
      expect(get).not.toHaveBeenCalled();
    }
    const e = { P3_DEMO_SPECIALIST_BEARER: bearer },
      get = vi.fn(() => bearer);
    Object.defineProperty(e, 'P3_DEMO_SPECIALIST_BEARER', { get, enumerable: true });
    expect(() => parseSpecialistEnvironment(e)).toThrow('invalid_configuration');
    expect(get).not.toHaveBeenCalled();
  });
  it('supports actual process.env in an isolated synthetic role without reading real credentials', () => {
    const file = new URL('../src/specialist-config.ts', import.meta.url).href;
    const raw = execFileSync(
      process.execPath,
      [
        '--input-type=module',
        '-e',
        `import {parseSpecialistEnvironment} from ${JSON.stringify(file)};const c=parseSpecialistEnvironment(process.env);console.log(c.bearer==='s'.repeat(43)?'passed':'failed')`,
      ],
      {
        env: {
          PATH: '/opt/homebrew/bin:/usr/bin:/bin',
          LANG: 'en_US.UTF-8',
          CI: '1',
          NO_COLOR: '1',
          P3_DEMO_SPECIALIST_BEARER: bearer,
        },
        encoding: 'utf8',
        timeout: 5000,
      },
    );
    expect(raw.trim()).toBe('passed');
  });
  it('reads only private NL1 regular files under canonical private directories', () => {
    const d = directory(),
      p = join(d, 'specialist.json');
    writeFileSync(p, JSON.stringify(configuration()) + '\n', { mode: 0o600 });
    expect(readSpecialistConfiguration(p).port).toBe(11028);
    chmodSync(p, 0o644);
    expect(() => readSpecialistConfiguration(p)).toThrow('invalid_configuration');
    chmodSync(p, 0o600);
    chmodSync(d, 0o755);
    expect(() => readSpecialistConfiguration(p)).toThrow('invalid_configuration');
  });
  it('denies symbolic/hard links and FIFO without waiting on content', () => {
    const d = directory(),
      p = join(d, 'specialist.json');
    writeFileSync(p, JSON.stringify(configuration()) + '\n', { mode: 0o600 });
    symlinkSync(p, join(d, 'alias'));
    expect(() => readSpecialistConfiguration(join(d, 'alias'))).toThrow('invalid_configuration');
    linkSync(p, join(d, 'hard'));
    expect(() => readSpecialistConfiguration(p)).toThrow('invalid_configuration');
    execFileSync('/usr/bin/mkfifo', [join(d, 'fifo')]);
    expect(() => readSpecialistConfiguration(join(d, 'fifo'))).toThrow('invalid_configuration');
    expect(() =>
      readSpecialistConfiguration('/tmp/' + d.split('/').at(-1) + '/specialist.json'),
    ).toThrow('invalid_configuration');
  });
  it('copies finite own error codes without invoking error getters or private messages', () => {
    const error = new SpecialistRuntimeError('closed');
    error.message = 'PRIVATE';
    expect(specialistFailureCode(error)).toBe('closed');
    const get = vi.fn(() => {
      throw new Error('PRIVATE');
    });
    Object.defineProperty(error, 'code', { get });
    expect(specialistFailureCode(error)).toBe('unavailable');
    expect(get).not.toHaveBeenCalled();
    expect(specialistFailureCode({ code: 'closed', message: 'PRIVATE' })).toBe('unavailable');
    expect(new SpecialistRuntimeError([] as never).message).toBe('unavailable');
  });
});
