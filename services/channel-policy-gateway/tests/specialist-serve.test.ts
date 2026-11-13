/** Explicit role lifecycle; fake runtime is declared, no provider or SQL I/O. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { main, runSpecialistRuntime } from '../src/specialist-serve.js';
import { configuration, bearer, deferred } from './specialist-fixtures.js';
const f = vi.hoisted(() => ({
  constructed: 0,
  started: 0,
  closed: 0,
  reads: 0,
  startError: false,
  startWait: undefined as Promise<void> | undefined,
  closeWait: undefined as Promise<void> | undefined,
  configuration: undefined as unknown,
}));
vi.mock('../src/specialist-runtime.js', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ScriptedPolicySpecialistRuntime: class {
    constructor() {
      f.constructed++;
    }
    async start() {
      f.started++;
      if (f.startError) throw new Error('PRIVATE_START');
      await f.startWait;
      return { host: '127.0.0.1', port: 11028 };
    }
    async close() {
      f.closed++;
      await f.closeWait;
    }
    metrics() {
      return { closed: true, serverOwners: 0, active: 0, sockets: 0 };
    }
  },
}));
vi.mock('../src/specialist-config.js', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  readSpecialistConfiguration: () => {
    f.reads++;
    return f.configuration;
  },
}));
const baseline = new Set(process.stdout.listeners('error'));
let output: string[] = [];
beforeEach(() => {
  f.constructed = f.started = f.closed = f.reads = 0;
  f.startError = false;
  f.startWait = f.closeWait = undefined;
  f.configuration = configuration();
  output = [];
  vi.spyOn(process.stdout, 'write').mockImplementation((chunk) => {
    output.push(String(chunk));
    return true;
  });
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  for (const listener of process.stdout.listeners('error'))
    if (!baseline.has(listener)) process.stdout.off('error', listener);
});
describe('explicit scripted specialist entrypoint', () => {
  it('plans without examining environment/files or constructing a server', async () => {
    const env = new Proxy(
        {},
        {
          ownKeys() {
            throw new Error('PRIVATE_ENV');
          },
        },
      ),
      once = vi.spyOn(process, 'once');
    expect(await main(['--plan'], env)).toBe(0);
    expect(f.constructed + f.reads).toBe(0);
    expect(once).not.toHaveBeenCalled();
    expect(JSON.parse(output[0]!)).toMatchObject({
      label: 'scripted',
      specialistInputVersion: 2,
      p1IssuanceVerified: false,
      providerCalls: false,
      sql: false,
      onePrincipalMaximumActive: 2,
    });
  });
  it('rejects unknown args without echoing values or reading configuration', async () => {
    expect(await main(['PRIVATE_ARGUMENT'], {})).toBe(1);
    expect(f.reads + f.constructed).toBe(0);
    expect(output.join('')).not.toContain('PRIVATE');
  });
  it('enforces the separate specialist environment role before runtime construction', async () => {
    expect(
      await main(['--config', '/private/tmp/role/config.json'], {
        P3_DEMO_SPECIALIST_BEARER: bearer,
        OPENAI_API_KEY: 'PRIVATE_PROVIDER',
      }),
    ).toBe(1);
    expect(f.constructed).toBe(0);
    expect(output.join('')).not.toContain('PRIVATE');
    expect(JSON.parse(output[0]!)).toMatchObject({ code: 'invalid_configuration' });
  });
  it('starts and stops through scoped signal handlers without printing credentials', async () => {
    const once = vi.spyOn(process, 'once').mockImplementation((event, listener) => {
      if (event === 'SIGTERM') queueMicrotask(() => listener());
      return process;
    });
    expect(
      await main(['--config', '/private/tmp/role/config.json'], {
        P3_DEMO_SPECIALIST_BEARER: bearer,
      }),
    ).toBe(0);
    expect(once).toHaveBeenCalledWith('SIGTERM', expect.any(Function));
    expect(output.map((x) => JSON.parse(x).status)).toEqual(['closed']);
    expect(output.join('')).not.toContain(bearer);
  });
  it('publishes the actual fixed endpoint and closes after a trusted stop', async () => {
    const controller = new AbortController(),
      running = runSpecialistRuntime(configuration(), { bearer }, controller.signal);
    await vi.waitFor(() => expect(output.some((x) => JSON.parse(x).status === 'ready')).toBe(true));
    controller.abort();
    await running;
    expect(output.map((x) => JSON.parse(x).status)).toEqual(['ready', 'closed']);
    expect(JSON.parse(output[0]!)).toMatchObject({
      label: 'scripted',
      endpoint: { host: '127.0.0.1', port: 11028 },
    });
  });
  it('does not start an already stopped role', async () => {
    const controller = new AbortController();
    controller.abort();
    await runSpecialistRuntime(configuration(), { bearer }, controller.signal);
    expect(f.started).toBe(0);
    expect(f.closed).toBe(1);
    expect(JSON.parse(output[0]!)).toMatchObject({ cleanupComplete: true });
  });
  it('anchors10s shutdown at first stop while startup and actual close remain held', async () => {
    vi.useFakeTimers();
    const startup = deferred(),
      closing = deferred();
    f.startWait = startup.promise;
    f.closeWait = closing.promise;
    const controller = new AbortController();
    let done = false;
    const running = runSpecialistRuntime(configuration(), { bearer }, controller.signal)
      .catch((e) => e)
      .finally(() => {
        done = true;
      });
    await Promise.resolve();
    controller.abort();
    expect(f.closed).toBe(1);
    await vi.advanceTimersByTimeAsync(9999);
    expect(done).toBe(false);
    await vi.advanceTimersByTimeAsync(2);
    expect(await running).toMatchObject({ code: 'cleanup_incomplete' });
    expect(output).toEqual([]);
    startup.resolve();
    closing.resolve();
  });
  it('retains startup even when close settles first and emits no false cleanup', async () => {
    vi.useFakeTimers();
    const startup = deferred();
    f.startWait = startup.promise;
    const controller = new AbortController(),
      running = runSpecialistRuntime(configuration(), { bearer }, controller.signal).catch(
        (e) => e,
      );
    await Promise.resolve();
    controller.abort();
    await vi.advanceTimersByTimeAsync(10001);
    expect(await running).toMatchObject({ code: 'cleanup_incomplete' });
    expect(output).toEqual([]);
    startup.resolve();
  });
  it('allows useful late settlement within the original deadline and suppresses late ready', async () => {
    vi.useFakeTimers();
    const startup = deferred(),
      closing = deferred();
    f.startWait = startup.promise;
    f.closeWait = closing.promise;
    const controller = new AbortController(),
      running = runSpecialistRuntime(configuration(), { bearer }, controller.signal);
    await Promise.resolve();
    controller.abort();
    await vi.advanceTimersByTimeAsync(6000);
    startup.resolve();
    closing.resolve();
    await running;
    expect(output.map((x) => JSON.parse(x).status)).toEqual(['closed']);
    expect(f.started).toBe(1);
  });
  it('preserves startup failure when later close is incomplete and never exposes private exception text', async () => {
    vi.useFakeTimers();
    f.startError = true;
    const closing = deferred();
    f.closeWait = closing.promise;
    const running = runSpecialistRuntime(
      configuration(),
      { bearer },
      new AbortController().signal,
    ).catch((e) => e);
    await vi.advanceTimersByTimeAsync(10001);
    expect(await running).toMatchObject({ code: 'unavailable' });
    expect(output).toEqual([]);
    closing.resolve();
  });
  it('contains synchronous output failures while still draining the owned runtime', async () => {
    vi.spyOn(process.stdout, 'write').mockImplementation(() => {
      throw new Error('PRIVATE_OUTPUT');
    });
    const controller = new AbortController();
    controller.abort();
    await runSpecialistRuntime(configuration(), { bearer }, controller.signal);
    expect(f.closed).toBe(1);
  });
});
