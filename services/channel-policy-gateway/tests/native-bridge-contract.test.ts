import {
  mkdtempSync,
  realpathSync,
  writeFileSync,
  chmodSync,
  symlinkSync,
  linkSync,
  rmSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  parseNativeBridgeConfiguration,
  readNativeBridgeConfiguration,
  parseRoomAttach,
  nativeBridgeInput,
} from '../src/native-bridge-contract.js';
import { opening, route, input, provider, attach } from './native-bridge-fixtures.js';
const configuration = {
  schemaVersion: 1,
  prepareEndpoint: { host: '127.0.0.1', port: 11030 },
  rehydrationPort: 11032,
};
const dirs: string[] = [];
afterEach(() => {
  for (const d of dirs.splice(0)) rmSync(d, { recursive: true, force: true });
});
describe('closed native bridge configuration and commands', () => {
  it('copies reflection failures into finite errors without dependency diagnostics', () => {
    const proxy = new Proxy(
      {},
      {
        getPrototypeOf() {
          throw new Error('PRIVATE_REFLECTION');
        },
      },
    );
    for (const parse of [parseNativeBridgeConfiguration, parseRoomAttach])
      expect(() => parse(proxy)).toThrow('invalid_input');
  });
  it('copies and freezes distinct fixed loopback endpoints and original attachment', () => {
    const c = parseNativeBridgeConfiguration(configuration);
    expect(c).toEqual(configuration);
    expect(Object.isFrozen(c.prepareEndpoint)).toBe(true);
    const a = attach(opening('11111111-1111-4111-8111-111111111111'));
    expect(parseRoomAttach(a)).toEqual(a);
    expect(Object.isFrozen(parseRoomAttach(a))).toBe(true);
  });
  it('rejects unknown selectors, non-loopback, port alias, coercion and getters before inspection', () => {
    let read = 0;
    for (const bad of [
      { ...configuration, tenantId: 'foreign' },
      { ...configuration, prepareEndpoint: { host: 'localhost', port: 11030 } },
      { ...configuration, rehydrationPort: 11030 },
      { ...configuration, rehydrationPort: true },
      {
        ...configuration,
        get prepareEndpoint() {
          read++;
          return configuration.prepareEndpoint;
        },
      },
    ])
      expect(() => parseNativeBridgeConfiguration(bad)).toThrow();
    expect(read).toBe(0);
  });
  it('requires exact generation/identity/capability command without endpoint or scope fields', () => {
    const a = attach(opening('11111111-1111-4111-8111-111111111111'));
    for (const bad of [
      { ...a, generation: '0' },
      { ...a, generation: '01' },
      { ...a, prepareBearer: 'short' },
      { ...a, endpoint: configuration.prepareEndpoint },
      { ...a, scope: route.scope },
    ])
      expect(() => parseRoomAttach(bad)).toThrow();
  });
  it('reads only an absolute private0600 single-link regular config beneath0700', () => {
    const d = mkdtempSync(join(realpathSync(tmpdir()), 'native-bridge-'));
    dirs.push(d);
    chmodSync(d, 0o700);
    const p = join(d, 'bridge.json');
    writeFileSync(p, JSON.stringify(configuration) + '\n', { mode: 0o600 });
    expect(readNativeBridgeConfiguration(p)).toEqual(configuration);
    chmodSync(p, 0o644);
    expect(() => readNativeBridgeConfiguration(p)).toThrow();
    chmodSync(p, 0o600);
    const alias = join(d, 'alias');
    linkSync(p, alias);
    expect(() => readNativeBridgeConfiguration(p)).toThrow();
    rmSync(alias);
    symlinkSync(p, alias);
    expect(() => readNativeBridgeConfiguration(alias)).toThrow();
    expect(() => readNativeBridgeConfiguration('relative.json')).toThrow();
  });
  it('rejects nonprivate directory, changed/duplicate JSON and permits original useful progress', () => {
    const d = mkdtempSync(join(realpathSync(tmpdir()), 'native-bridge-'));
    dirs.push(d);
    const p = join(d, 'bridge.json');
    writeFileSync(p, JSON.stringify(configuration), { mode: 0o600 });
    chmodSync(d, 0o755);
    expect(() => readNativeBridgeConfiguration(p)).toThrow();
    chmodSync(d, 0o700);
    writeFileSync(p, '{"schemaVersion":1,"schemaVersion":1}');
    expect(() => readNativeBridgeConfiguration(p)).toThrow();
    writeFileSync(p, JSON.stringify(configuration) + '\n');
    expect(readNativeBridgeConfiguration(p)).toEqual(configuration);
  });
  it('validates/copies stored native provider and exact case/receipt before routing', () => {
    const original = input('11111111-1111-4111-8111-111111111111'),
      copy = nativeBridgeInput(original, route, provider);
    expect(copy).toEqual(original);
    expect(copy).not.toBe(original);
    expect(Object.isFrozen(copy.message.event)).toBe(true);
    expect(() =>
      nativeBridgeInput(original, route, { ...provider, providerAccountId: 'other' }),
    ).toThrow();
    expect(() =>
      nativeBridgeInput(
        { ...original, currentCase: { ...original.currentCase, caseId: 'foreign' } },
        route,
        provider,
      ),
    ).toThrow();
  });
  it('does not invoke input getters/toJSON and changed receipt cannot pass as original', () => {
    const value = input('11111111-1111-4111-8111-111111111111');
    const getter = vi.fn(() => value.message);
    expect(() =>
      nativeBridgeInput(
        {
          get message() {
            return getter();
          },
          currentCase: value.currentCase,
        },
        route,
        provider,
      ),
    ).toThrow();
    expect(getter).not.toHaveBeenCalled();
    expect(() =>
      nativeBridgeInput(
        {
          ...value,
          message: {
            ...value.message,
            receipt: { ...value.message.receipt, eventId: 'different' },
          },
        },
        route,
        provider,
      ),
    ).toThrow();
  });
});
