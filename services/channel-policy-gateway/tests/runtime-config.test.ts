import { mkdtempSync, chmodSync, writeFileSync, symlinkSync, linkSync, rmSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { Socket } from 'node:net';
import { ChannelInbox, SeededAccounts } from '@livekit-ecosystem/channel-continuity/postgres';
import { createFakeSmsIntegration } from '@livekit-ecosystem/channel-continuity/security';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  parseRuntimeConfiguration,
  parseRuntimeConfigurationBytes,
  parseRuntimeCredentials,
  parseRuntimeEnvironment,
  readRuntimeConfiguration,
  publicSimulationHmacKey,
} from '../src/runtime-config.js';
import { configuration, credentials, environment } from './runtime-fixtures.js';
const temporary: string[] = [];
function directory() {
  const p = mkdtempSync('/private/tmp/joined-runtime-config-');
  chmodSync(p, 0o700);
  temporary.push(p);
  return p;
}
const encoded = () => Buffer.from(JSON.stringify(configuration()) + '\n');
afterEach(() => {
  for (const p of temporary.splice(0)) rmSync(p, { recursive: true, force: true });
});
describe('runtime-only closed configuration', () => {
  it('copies and freezes the exact non-secret route, source and fixed port configuration', () => {
    const raw = configuration(),
      parsed = parseRuntimeConfiguration(raw);
    (raw.route as { caseId: string }).caseId = 'changed';
    expect(parsed.route.caseId).toBe('case_demo');
    expect(Object.isFrozen(parsed.route.scope)).toBe(true);
    expect(Object.isFrozen(parsed.originEndpoints.native)).toBe(true);
    expect(JSON.stringify(parsed)).not.toContain('synthetic_password');
  });
  it.each([0, -1, 65536, 1.5, NaN, Infinity])('rejects invalid listen port %s', (port) => {
    const c = configuration();
    expect(() =>
      parseRuntimeConfiguration({ ...c, listen: { ...c.listen, readPort: port } }),
    ).toThrow(/^invalid_configuration$/);
  });
  it('requires distinct fixed service ports and runtime-only DB role', () => {
    const c = configuration();
    expect(() =>
      parseRuntimeConfiguration({ ...c, listen: { ...c.listen, readPort: c.caseEndpoint.port } }),
    ).toThrow('invalid_configuration');
    expect(() =>
      parseRuntimeConfiguration({ ...c, postgres: { ...c.postgres, user: 'continuity_migrator' } }),
    ).toThrow('invalid_configuration');
    expect(() =>
      parseRuntimeConfiguration({
        ...c,
        providers: { ...c.providers, sms: { ...c.providers.sms, tenantId: 'foreign' } },
      }),
    ).toThrow('invalid_configuration');
  });
  it('rejects unknown/config accessor fields without invoking getters', () => {
    const c = configuration(),
      get = vi.fn(() => {
        throw new Error('PRIVATE_GETTER');
      });
    Object.defineProperty(c, 'route', { get, enumerable: true });
    expect(() => parseRuntimeConfiguration(c)).toThrow('invalid_configuration');
    expect(get).not.toHaveBeenCalled();
    expect(() => parseRuntimeConfiguration({ ...configuration(), private: 'PRIVATE' })).toThrow(
      'invalid_configuration',
    );
  });
  it('validates compact JSON UTF-8, duplicate keys, numeric forms, whitespace and bounds', () => {
    expect(parseRuntimeConfigurationBytes(encoded()).route.caseId).toBe('case_demo');
    for (const raw of [
      Buffer.from('{"schemaVersion":1,' + encoded().toString().slice(1)),
      Buffer.from(encoded().toString().replace('"schemaVersion":1', '"schemaVersion":1e0')),
      Buffer.from(JSON.stringify(configuration(), null, 2) + '\n'),
      Buffer.from([0xff]),
      Buffer.alloc(8193, 0x20),
    ])
      expect(() => parseRuntimeConfigurationBytes(raw)).toThrow('invalid_configuration');
  });
  it('accepts a closed exotic environment via own data descriptors, never ambient secrets', () => {
    const e = Object.assign(
      Object.create({ exotic: true }) as Record<string, string>,
      environment(),
    );
    expect(parseRuntimeEnvironment(e)).toEqual(credentials());
    const getter = vi.fn(() => {
      throw new Error('PRIVATE_KEY');
    });
    Object.defineProperty(e, 'OPENAI_API_KEY', { get: getter, enumerable: true });
    expect(() => parseRuntimeEnvironment(e)).toThrow('invalid_configuration');
    expect(getter).not.toHaveBeenCalled();
  });
  it('contains own environment accessors and capability role collisions', () => {
    const e = environment(),
      get = vi.fn(() => {
        throw new Error('PRIVATE_KEY');
      });
    Object.defineProperty(e, 'P2_DEMO_WORKER_BEARER', { get, enumerable: true });
    expect(() => parseRuntimeEnvironment(e)).toThrow('invalid_configuration');
    expect(get).not.toHaveBeenCalled();
    const c = credentials();
    expect(() => parseRuntimeCredentials({ ...c, smsOriginBearer: c.nativeOriginBearer })).toThrow(
      'invalid_configuration',
    );
    expect(() => parseRuntimeCredentials({ ...c, caseAuthorization: 'PRIVATE' })).toThrow(
      'invalid_configuration',
    );
  });
  it('reads only owned private regular NL1 files under canonical private directories', () => {
    const d = directory(),
      p = join(d, 'runtime.json');
    writeFileSync(p, encoded(), { mode: 0o600 });
    expect(readRuntimeConfiguration(p)).toEqual(configuration());
    chmodSync(p, 0o644);
    expect(() => readRuntimeConfiguration(p)).toThrow('invalid_configuration');
    chmodSync(p, 0o600);
    chmodSync(d, 0o755);
    expect(() => readRuntimeConfiguration(p)).toThrow('invalid_configuration');
  });
  it('rejects symbolic/hard links and FIFO without blocking or reading it', () => {
    const d = directory(),
      p = join(d, 'runtime.json');
    writeFileSync(p, encoded(), { mode: 0o600 });
    symlinkSync(p, join(d, 'link'));
    expect(() => readRuntimeConfiguration(join(d, 'link'))).toThrow('invalid_configuration');
    linkSync(p, join(d, 'hard'));
    expect(() => readRuntimeConfiguration(p)).toThrow('invalid_configuration');
    const fifo = join(d, 'fifo');
    execFileSync('/usr/bin/mkfifo', [fifo]);
    chmodSync(fifo, 0o600);
    expect(() => readRuntimeConfiguration(fifo)).toThrow('invalid_configuration');
  });

  it('matches the public SDK password unit/UTF-8 contract before any pool can connect', async () => {
    for (const password of [
      'x'.repeat(31),
      'x'.repeat(129),
      'x'.repeat(31) + '\ud800',
      'x'.repeat(31) + '\udfff',
    ])
      expect(() =>
        parseRuntimeCredentials({ ...credentials(), postgresPassword: password }),
      ).toThrow('invalid_configuration');
    const connect = vi.spyOn(Socket.prototype, 'connect').mockImplementation(function (
      this: Socket,
    ) {
      throw new Error('NO_NETWORK');
    });
    try {
      for (const password of ['x'.repeat(32), 'x'.repeat(128), 'é'.repeat(30) + '🧭']) {
        const parsed = parseRuntimeCredentials({ ...credentials(), postgresPassword: password }),
          c = configuration();
        const inbox = new ChannelInbox(
          { ...c.postgres, password: parsed.postgresPassword },
          createFakeSmsIntegration(c.providers.sms, publicSimulationHmacKey()),
          new SeededAccounts([
            {
              token: parsed.accountToken,
              ...c.route.scope,
              caseId: c.route.caseId,
              conversationId: c.route.conversationId,
            },
          ]),
          {},
          () => {},
        );
        await inbox.close();
      }
      expect(connect).not.toHaveBeenCalled();
    } finally {
      connect.mockRestore();
    }
  });
  it('returns a detached explicitly public synthetic HMAC key', () => {
    const a = publicSimulationHmacKey();
    a.fill(0);
    expect(publicSimulationHmacKey()).toEqual(Buffer.alloc(32, 0x4f));
  });
});
