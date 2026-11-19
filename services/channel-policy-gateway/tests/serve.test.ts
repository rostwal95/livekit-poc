import { mkdtempSync, chmodSync, writeFileSync, rmSync } from 'node:fs';
/** Entrypoint lifecycle controls use a fake runtime; no serving/PG/provider I/O. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { main, runGatewayRuntime } from '../src/serve.js';
import { configuration, credentials, deferred, environment } from './runtime-fixtures.js';
const f = vi.hoisted(() => ({
  constructed: 0,
  started: 0,
  closed: 0,
  quiesced: 0,
  quiesceWait: undefined as Promise<void> | undefined,
  startError: false,
  closeWait: undefined as Promise<void> | undefined,
  startWait: undefined as Promise<void> | undefined,
  reads: 0,
  config: undefined as unknown,
  roomArgument: undefined as unknown,
  nativeBridgeArgument: undefined as unknown,
}));
vi.mock('../src/runtime.js', () => ({
  ChannelPolicyGatewayRuntime: class {
    constructor(_c: unknown, _k: unknown, room?: unknown, bridge?: unknown) {
      f.constructed++;
      f.roomArgument = room;
      f.nativeBridgeArgument = bridge;
    }
    async start() {
      f.started++;
      if (f.startError) throw new Error('PRIVATE_START');
      await f.startWait;
      return {
        native: { host: '127.0.0.1', port: 11024 },
        sms: { host: '127.0.0.1', port: 11025 },
        read: { host: '127.0.0.1', port: 11026 },
        receiver: { host: '127.0.0.1', port: 11027 },
      };
    }
    async close() {
      f.closed++;
      await f.closeWait;
    }
    async quiesceDispatch() {
      f.quiesced++;
      await f.quiesceWait;
    }
    metrics() {
      return { closed: true, applicationOwners: 0 };
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
        endpoint: { host: '127.0.0.1', port: 11029 },
        generation: '0',
        recoveryRequired: false,
      };
    }
  },
}));
vi.mock('../src/runtime-config.js', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  readRuntimeConfiguration: () => {
    f.reads++;
    return f.config;
  },
}));
let output: string[] = [];
const baseline = new Set(process.stdout.listeners('error'));
beforeEach(() => {
  f.constructed = f.started = f.closed = f.reads = 0;
  f.startError = false;
  f.startWait = f.closeWait = undefined;
  f.quiesceWait = undefined;
  f.quiesced = 0;
  f.config = configuration();
  f.roomArgument = undefined;
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
describe('explicit serving entrypoint', () => {
  it('acknowledges only settled requested dispatch quiescence while room-control runtime remains alive', async () => {
    const controller = new AbortController(),
      control = new EventTarget(),
      held = deferred();
    f.quiesceWait = held.promise;
    const run = runGatewayRuntime(
      configuration(),
      credentials(),
      controller.signal,
      undefined,
      undefined,
      control,
    );
    control.dispatchEvent(new Event('quiesce')); // Before ready grants no acknowledgement.
    await vi.waitFor(() => expect(output.some((s) => JSON.parse(s).status === 'ready')).toBe(true));
    expect(f.quiesced).toBe(0);
    control.dispatchEvent(new Event('quiesce'));
    await vi.waitFor(() => expect(f.quiesced).toBe(1));
    control.dispatchEvent(new Event('quiesce'));
    expect(f.quiesced).toBe(1);
    expect(output.map((s) => JSON.parse(s).status)).toEqual(['ready']);
    expect(f.closed).toBe(0);
    held.resolve();
    await vi.waitFor(() => expect(output).toHaveLength(2));
    expect(JSON.parse(output[1]!)).toEqual({
      schemaVersion: 1,
      status: 'dispatch_quiesced',
      mode: 'scripted_readonly_policy',
      pid: process.pid,
      profileId: configuration().route.profileId,
      nodeEpoch: '11111111-1111-4111-8111-111111111111',
    });
    expect(f.closed).toBe(0);
    controller.abort();
    await run;
    expect(output.map((s) => JSON.parse(s).status)).toEqual([
      'ready',
      'dispatch_quiesced',
      'closed',
    ]);
  });
  it('plans without inspecting environment, files, signals or runtime constructors', async () => {
    const env = new Proxy(
        {},
        {
          ownKeys() {
            throw new Error('PRIVATE_ENV');
          },
        },
      ),
      signals = vi.spyOn(process, 'once');
    expect(await main(['--plan'], env)).toBe(0);
    expect(f.constructed + f.reads).toBe(0);
    expect(signals).not.toHaveBeenCalled();
    expect(JSON.parse(output[0]!)).toMatchObject({
      status: 'planned',
      providerCalls: false,
      operationCallOwners: 2,
    });
  });
  it('rejects unknown argv without echoing private arguments or reading configuration', async () => {
    expect(await main(['--PRIVATE_ARGUMENT'], {})).toBe(1);
    expect(f.constructed + f.reads).toBe(0);
    expect(output.join('')).not.toContain('PRIVATE');
    expect(JSON.parse(output[0]!)).toMatchObject({
      status: 'unavailable',
      code: 'invalid_configuration',
    });
  });

  it('runs the configured role with exact credentials and scoped signal handlers', async () => {
    const once = vi.spyOn(process, 'once').mockImplementation((event, listener) => {
      if (event === 'SIGTERM') queueMicrotask(() => listener());
      return process;
    });
    expect(await main(['--config', '/private/tmp/role/runtime.json'], environment())).toBe(0);
    expect(f.reads).toBe(1);
    expect(f.constructed).toBe(1);
    expect(once).toHaveBeenCalledWith('SIGTERM', expect.any(Function));
    expect(output.map((line) => JSON.parse(line).status)).toEqual(['closed']);
    expect(output.join('')).not.toContain(credentials().workerBearer);
  });
  it('does not start when already aborted and reports actual closed state only after drain', async () => {
    const controller = new AbortController();
    controller.abort();
    await runGatewayRuntime(configuration(), credentials(), controller.signal);
    expect(f.started).toBe(0);
    expect(f.closed).toBeGreaterThan(0);
    expect(output.map((x) => JSON.parse(x).status)).toEqual(['closed']);
  });
  it('publishes fixed ready endpoints and drains after a trusted signal', async () => {
    const controller = new AbortController(),
      run = runGatewayRuntime(configuration(), credentials(), controller.signal);
    await vi.waitFor(() => expect(output.some((s) => JSON.parse(s).status === 'ready')).toBe(true));
    controller.abort();
    await run;
    expect(output.map((x) => JSON.parse(x).status)).toEqual(['ready', 'closed']);
    expect(output.join('')).not.toContain(credentials().postgresPassword);
  });
  it('retains a late startup through requested stop and emits no late readiness', async () => {
    const held = deferred();
    f.startWait = held.promise;
    const controller = new AbortController(),
      run = runGatewayRuntime(configuration(), credentials(), controller.signal);
    await vi.waitFor(() => expect(f.started).toBe(1));
    controller.abort();
    held.resolve();
    await run;
    expect(output.map((x) => JSON.parse(x).status)).toEqual(['closed']);
  });
  it('anchors shutdown at first stop while startup and actual close remain held', async () => {
    vi.useFakeTimers();
    const startup = deferred(),
      closing = deferred();
    f.startWait = startup.promise;
    f.closeWait = closing.promise;
    const controller = new AbortController();
    let settled = false;
    const observed = runGatewayRuntime(configuration(), credentials(), controller.signal)
      .catch((e: unknown) => e)
      .finally(() => {
        settled = true;
      });
    await Promise.resolve();
    expect(f.started).toBe(1);
    controller.abort();
    expect(f.closed).toBeGreaterThan(0);
    await vi.advanceTimersByTimeAsync(9999);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(2);
    expect(settled).toBe(true);
    expect(await observed).toMatchObject({ code: 'cleanup_incomplete' });
    expect(output).toEqual([]);
    startup.resolve();
    closing.resolve();
    await Promise.resolve();
    expect(output).toEqual([]);
  });
  it('retains startup even if close settles first and cannot claim cleanup at the deadline', async () => {
    vi.useFakeTimers();
    const startup = deferred();
    f.startWait = startup.promise;
    const controller = new AbortController(),
      observed = runGatewayRuntime(configuration(), credentials(), controller.signal).catch(
        (e: unknown) => e,
      );
    await Promise.resolve();
    controller.abort();
    await vi.advanceTimersByTimeAsync(10001);
    expect(await observed).toMatchObject({ code: 'cleanup_incomplete' });
    expect(f.closed).toBeGreaterThan(0);
    expect(output).toEqual([]);
    startup.resolve();
    await Promise.resolve();
  });
  it('uses the original stop deadline for useful late startup and close progress without late readiness', async () => {
    vi.useFakeTimers();
    const startup = deferred(),
      closing = deferred();
    f.startWait = startup.promise;
    f.closeWait = closing.promise;
    const controller = new AbortController(),
      observed = runGatewayRuntime(configuration(), credentials(), controller.signal);
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(4000);
    controller.abort();
    expect(f.closed).toBeGreaterThan(0);
    await vi.advanceTimersByTimeAsync(6000);
    startup.resolve();
    await vi.advanceTimersByTimeAsync(1000);
    closing.resolve();
    await observed;
    expect(output.map((s) => JSON.parse(s).status)).toEqual(['closed']);
    expect(f.started).toBe(1);
  });
  it('preserves initial startup failure and performs dependent close before finite diagnostics', async () => {
    f.startError = true;
    await expect(
      runGatewayRuntime(configuration(), credentials(), new AbortController().signal),
    ).rejects.toThrow(/^unavailable$/);
    expect(f.closed).toBeGreaterThan(0);
    expect(output.join('')).not.toContain('PRIVATE');
    expect(output.map((s) => JSON.parse(s).status)).toEqual(['closed']);
  });
  it('never reports complete cleanup while an actual runtime close remains held', async () => {
    vi.useFakeTimers();
    const held = deferred();
    f.closeWait = held.promise;
    const controller = new AbortController();
    controller.abort();
    const observed = runGatewayRuntime(configuration(), credentials(), controller.signal).catch(
      (e) => e,
    );
    await vi.advanceTimersByTimeAsync(10001);
    expect(await observed).toMatchObject({ code: 'cleanup_incomplete' });
    expect(output).toEqual([]);
    held.resolve();
  });
  it('keeps first startup failure when its later bounded cleanup is also incomplete', async () => {
    vi.useFakeTimers();
    f.startError = true;
    const held = deferred();
    f.closeWait = held.promise;
    const observed = runGatewayRuntime(
      configuration(),
      credentials(),
      new AbortController().signal,
    ).catch((e) => e);
    await vi.advanceTimersByTimeAsync(10001);
    expect(await observed).toMatchObject({ code: 'unavailable' });
    expect(output).toEqual([]);
    held.resolve();
  });
});

describe('explicit separate room-control CLI file', () => {
  it('loads private room-control config only for the explicit option and advertises metadata without capabilities', async () => {
    const d = mkdtempSync('/private/tmp/room-control-cli-');
    chmodSync(d, 0o700);
    const p = d + '/room.json';
    writeFileSync(p, '{"schemaVersion":1,"port":11029,"recoverBindingId":null}\n', { mode: 0o600 });
    vi.spyOn(process, 'once').mockImplementation((event, listener) => {
      if (event === 'SIGTERM') setTimeout(() => listener(), 10);
      return process;
    });
    try {
      expect(
        await main(
          ['--config', '/private/tmp/role/runtime.json', '--room-control', p],
          environment(),
        ),
      ).toBe(0);
      expect(f.roomArgument).toEqual({ schemaVersion: 1, port: 11029, recoverBindingId: null });
      const ready = output.map((v) => JSON.parse(v)).find((v) => v.status === 'ready');
      expect(ready.roomControl).toMatchObject({
        generation: '0',
        endpoint: { port: 11029 },
        recoveryRequired: false,
      });
      expect(Object.keys(ready.endpoints).sort()).toEqual(['native', 'read', 'receiver', 'sms']);
      expect(output.join('')).not.toContain(credentials().nativePublisherToken);
    } finally {
      rmSync(d, { recursive: true, force: true });
    }
  });
  it('denies unknown room fields and malformed option order before runtime admission', async () => {
    const d = mkdtempSync('/private/tmp/room-control-cli-');
    chmodSync(d, 0o700);
    const p = d + '/room.json';
    writeFileSync(p, '{"schemaVersion":1,"port":11029,"recoverBindingId":null,"scope":{}}\n', {
      mode: 0o600,
    });
    try {
      expect(
        await main(
          ['--config', '/private/tmp/role/runtime.json', '--room-control', p],
          environment(),
        ),
      ).toBe(1);
      expect(f.constructed + f.reads).toBe(0);
      expect(JSON.parse(output[0]!).code).toBe('invalid_configuration');
      expect(
        await main(
          ['--room-control', p, '--config', '/private/tmp/role/runtime.json'],
          environment(),
        ),
      ).toBe(1);
      expect(f.constructed + f.reads).toBe(0);
    } finally {
      rmSync(d, { recursive: true, force: true });
    }
  });
});

describe('separate private native bridge CLI option', () => {
  it('requires room control, reads a private nonsecret profile and advertises safe actual endpoints', async () => {
    const d = mkdtempSync('/private/tmp/native-bridge-cli-');
    chmodSync(d, 0o700);
    const room = d + '/room.json',
      bridge = d + '/bridge.json',
      profile = {
        schemaVersion: 1,
        prepareEndpoint: { host: '127.0.0.1', port: 11030 },
        rehydrationPort: 11032,
      };
    writeFileSync(room, '{"schemaVersion":1,"port":11029,"recoverBindingId":null}\n', {
      mode: 0o600,
    });
    writeFileSync(bridge, JSON.stringify(profile) + '\n', { mode: 0o600 });
    try {
      expect(
        await main(
          ['--config', '/private/tmp/role/runtime.json', '--native-bridge', bridge],
          environment(),
        ),
      ).toBe(1);
      expect(f.constructed + f.reads).toBe(0);
      output.length = 0;
      setImmediate(() => process.emit('SIGTERM'));
      expect(
        await main(
          [
            '--config',
            '/private/tmp/role/runtime.json',
            '--room-control',
            room,
            '--native-bridge',
            bridge,
          ],
          environment(),
        ),
      ).toBe(0);
      expect(f.nativeBridgeArgument).toEqual(profile);
      const ready = output.map((v) => JSON.parse(v)).find((v) => v.status === 'ready');
      expect(ready.nativeBridge).toEqual({
        prepareEndpoint: profile.prepareEndpoint,
        rehydrationEndpoint: { host: '127.0.0.1', port: 11032 },
      });
      expect(Object.keys(ready.endpoints).sort()).toEqual(['native', 'read', 'receiver', 'sms']);
      expect(output.join('')).not.toContain(credentials().nativePublisherToken);
    } finally {
      rmSync(d, { recursive: true, force: true });
    }
  });
  it('rejects credentials/selectors in the nonsecret bridge file before runtime/environment admission', async () => {
    const d = mkdtempSync('/private/tmp/native-bridge-cli-');
    chmodSync(d, 0o700);
    const room = d + '/room.json',
      bridge = d + '/bridge.json';
    writeFileSync(room, '{"schemaVersion":1,"port":11029,"recoverBindingId":null}\n', {
      mode: 0o600,
    });
    writeFileSync(
      bridge,
      '{"schemaVersion":1,"prepareEndpoint":{"host":"127.0.0.1","port":11030},"rehydrationPort":11032,"prepareBearer":"PRIVATE_SENTINEL"}\n',
      { mode: 0o600 },
    );
    try {
      expect(
        await main(
          [
            '--config',
            '/private/tmp/role/runtime.json',
            '--room-control',
            room,
            '--native-bridge',
            bridge,
          ],
          environment(),
        ),
      ).toBe(1);
      expect(f.constructed + f.reads).toBe(0);
      expect(output.join('')).not.toContain('PRIVATE_SENTINEL');
    } finally {
      rmSync(d, { recursive: true, force: true });
    }
  });
});
