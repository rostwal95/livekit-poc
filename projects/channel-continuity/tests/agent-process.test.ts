/** Real owned Node workers plus strict protocol negatives; no database/provider calls. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mkdtempSync, readFileSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { produceTextEvent } from '../src/index.js';
import { AgentProcess, type AgentProcessEvent } from '../src/agent-process.js';
import { parseRequest, request, parseResponse, response, scopes } from '../src/agent-protocol.js';
import { prepareDispatch } from '../src/dispatch-types.js';
import type { StoredMessage } from '../src/postgres.js';
const spawnControl = vi.hoisted(() => ({ failNext: false }));
vi.mock('node:child_process', async (original) => {
  const actual = await original<typeof import('node:child_process')>();
  return {
    ...actual,
    spawn: (...args: Parameters<typeof actual.spawn>) => {
      if (spawnControl.failNext) {
        spawnControl.failNext = false;
        throw new Error('PRIVATE_SPAWN_FAILURE');
      }
      return actual.spawn(...args);
    },
  };
});
const SCOPE = { tenantId: 'tenant-a', accountId: 'account-a' };
const MODULE = fileURLToPath(new URL('./fixtures/agent-wire-worker.mjs', import.meta.url));
const input = () => ({
  message: {
    receipt: {
      receiptId: '12345678-1234-4234-8234-123456789abc',
      eventId: 'event',
      messageId: 'message',
      acceptanceSequence: '1',
      acceptedAt: '2026-11-11T00:00:00.000Z',
    },
    event: produceTextEvent(
      {
        providerScope: {
          tenantId: 'tenant-a',
          provider: 'fake_sms',
          providerAccountId: 'carrier-a',
        },
        accountScope: SCOPE,
        eventId: 'event',
        conversationId: 'conversation-a',
        channel: 'sms',
        messageId: 'message',
        senderId: 'sender',
        body: 'Inert input',
        receivedAt: '2026-11-11T00:00:00.000Z',
        caseId: 'case-a',
      },
      {
        providerScope: {
          tenantId: 'tenant-a',
          provider: 'fake_sms',
          providerAccountId: 'carrier-a',
        },
        accountScope: SCOPE,
      },
    ).event,
    operationKey: '22345678-1234-4234-8234-123456789abc',
    processingState: 'running',
    associationVersion: '1',
  } as StoredMessage,
  currentCase: {
    scope: SCOPE,
    caseId: 'case-a',
    revision: '1',
    source: 'synthetic_read_only' as const,
  },
});
const agents = new Set<AgentProcess>(),
  directories = new Set<string>();
function agent(
  mode = 'normal',
  extra: Partial<ConstructorParameters<typeof AgentProcess>[0]> = {},
) {
  const value = new AgentProcess({
    modulePath: MODULE,
    allowedScopes: [SCOPE],
    timeoutMs: 500,
    environment: { P2_AGENT_MODE: mode },
    ...extra,
  });
  agents.add(value);
  return value;
}
function directory() {
  const dir = mkdtempSync(join(tmpdir(), 'p2-agent-test-'));
  directories.add(dir);
  return dir;
}
async function until(predicate: () => boolean) {
  const deadline = performance.now() + 1500;
  while (!predicate()) {
    if (performance.now() >= deadline) throw new Error('fixture_deadline');
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}
function gone(pid: number) {
  try {
    process.kill(pid, 0);
    return false;
  } catch (error) {
    return Boolean(error && typeof error === 'object' && 'code' in error && error.code === 'ESRCH');
  }
}
afterEach(async () => {
  for (const value of agents) await value.close();
  agents.clear();
  for (const dir of directories) rmSync(dir, { recursive: true, force: true });
  directories.clear();
});
describe('AgentProcess', () => {
  it('imports/constructs without spawning and validates a normal independently owned worker', async () => {
    const events: AgentProcessEvent[] = [],
      value = agent('normal', {
        // The file's first spawn pays the cold Node start-up on a loaded host.
        timeoutMs: 1500,
        observer: (event) => {
          events.push(event);
        },
      });
    expect(value.metrics().started).toBe(0);
    expect(await value.prepare(input(), new AbortController().signal)).toEqual({
      kind: 'investigation',
      source: 'scripted',
      caseRevision: '1',
    });
    expect(value.metrics().active).toBe(0);
    expect(events.map((event) => event.event)).toEqual(['started', 'settled']);
    expect(gone(events[0]!.pid)).toBe(true);
  });
  it('contains an OS spawn failure without leaking details or occupying capacity', async () => {
    const value = agent();
    spawnControl.failNext = true;
    await expect(value.prepare(input(), new AbortController().signal)).rejects.toMatchObject({
      code: 'DispatchUnavailable',
      message: 'DispatchUnavailable',
    });
    expect(value.metrics().active).toBe(0);
    expect((await value.prepare(input(), new AbortController().signal)).kind).toBe('investigation');
  });
  it('snapshots scope/message context before worker I/O and never inherits ambient selectors', async () => {
    const before = process.env.P2_RUNTIME_PASSWORD;
    process.env.P2_RUNTIME_PASSWORD = 'PRIVATE_PARENT_ONLY';
    try {
      expect((await agent('env').prepare(input(), new AbortController().signal)).source).toBe(
        'scripted',
      );
    } finally {
      if (before === undefined) delete process.env.P2_RUNTIME_PASSWORD;
      else process.env.P2_RUNTIME_PASSWORD = before;
    }
    const value = agent(),
      data = input(),
      pending = value.prepare(data, new AbortController().signal);
    Object.defineProperty(data.currentCase, 'revision', { value: '2' });
    expect((await pending).caseRevision).toBe('1');
  });
  it('rejects wrong worker scope/revision/digest and malformed/oversized output while subsequent work progresses', async () => {
    for (const mode of [
      'wrong-digest',
      'wrong-revision',
      'malformed',
      'oversize',
      'stderr',
      'exit',
    ]) {
      const value = agent(mode);
      await expect(value.prepare(input(), new AbortController().signal)).rejects.toMatchObject({
        code: mode === 'exit' ? 'DispatchUnavailable' : 'OperationConflict',
      });
      await value.close();
      expect(value.metrics().active).toBe(0);
    }
    expect((await agent().prepare(input(), new AbortController().signal)).kind).toBe(
      'investigation',
    );
  });
  it('bounds active workers and aborts/reaps an actual held process before freeing its slot', async () => {
    const dir = directory(),
      marker = join(dir, 'held'),
      controller = new AbortController(),
      events: AgentProcessEvent[] = [];
    const value = agent('hold', {
      timeoutMs: 1500,
      environment: { P2_AGENT_MODE: 'hold', P2_AGENT_MARKER: marker },
      observer: (event) => {
        events.push(event);
      },
    });
    const pending = value.prepare(input(), controller.signal);
    const failed = expect(pending).rejects.toMatchObject({ code: 'DispatchUnavailable' });
    await until(() => existsSync(marker));
    expect(value.metrics().active).toBe(1);
    await expect(value.prepare(input(), new AbortController().signal)).rejects.toMatchObject({
      code: 'Overloaded',
    });
    controller.abort();
    await failed;
    await value.close();
    expect(value.metrics().active).toBe(0);
    expect(gone(Number(readFileSync(marker, 'utf8')))).toBe(true);
    expect(events[1]!.signal).toBe('SIGTERM');
  });
  it('hard-kills a worker that ignores TERM and confirms actual process exit', async () => {
    const dir = directory(),
      marker = join(dir, 'held');
    const value = agent('ignore', {
      timeoutMs: 150,
      environment: { P2_AGENT_MODE: 'ignore', P2_AGENT_MARKER: marker },
    });
    await expect(value.prepare(input(), new AbortController().signal)).rejects.toMatchObject({
      code: 'DispatchUnavailable',
    });
    await value.close();
    expect(gone(Number(readFileSync(marker, 'utf8')))).toBe(true);
    expect(value.metrics().active).toBe(0);
  });
  it('kills and observes the entire owned process group including an actual descendant', async () => {
    const dir = directory(),
      parent = join(dir, 'parent'),
      descendant = join(dir, 'descendant'),
      controller = new AbortController();
    const value = agent('descendant', {
      timeoutMs: 1500,
      environment: {
        P2_AGENT_MODE: 'descendant',
        P2_AGENT_MARKER: parent,
        P2_AGENT_DESCENDANT: descendant,
      },
    });
    const pending = value.prepare(input(), controller.signal),
      failed = expect(pending).rejects.toMatchObject({ code: 'DispatchUnavailable' });
    await until(() => existsSync(descendant));
    controller.abort();
    await failed;
    await value.close();
    expect(gone(Number(readFileSync(parent, 'utf8')))).toBe(true);
    expect(gone(Number(readFileSync(descendant, 'utf8')))).toBe(true);
  });
  it('denies wrong parent scope/configuration and contains throwing observers without changing success', async () => {
    const data = input();
    data.currentCase.scope = { tenantId: 'tenant-b', accountId: 'account-b' };
    await expect(agent().prepare(data, new AbortController().signal)).rejects.toMatchObject({
      code: 'OperationConflict',
    });
    for (const change of [
      { modulePath: 'relative.mjs' },
      { allowedScopes: [] },
      { environment: { NODE_OPTIONS: 'bad' } },
      { maxActive: 3 },
      { timeoutMs: 0 },
    ])
      expect(
        () => new AgentProcess({ modulePath: MODULE, allowedScopes: [SCOPE], ...change }),
      ).toThrow();
    const value = agent('normal', {
      observer() {
        throw new Error('PRIVATE_OBSERVER');
      },
    });
    expect((await value.prepare(input(), new AbortController().signal)).kind).toBe('investigation');
    expect(value.metrics().telemetryFailures).toBe(2);
  });
  it('rejects late success and prevents input after a blocking diagnostic callback consumed the budget', async () => {
    const dir = directory(),
      marker = join(dir, 'unexpected-model');
    const value = agent('normal', {
      timeoutMs: 20,
      environment: { P2_AGENT_MARKER: marker },
      observer(event) {
        if (event.event === 'started') {
          const until = performance.now() + 40;
          while (performance.now() < until) {
            /* trusted diagnostic fixture blocks synchronously */
          }
        }
      },
    });
    await expect(value.prepare(input(), new AbortController().signal)).rejects.toMatchObject({
      code: 'DispatchUnavailable',
    });
    await value.close();
    expect(existsSync(marker)).toBe(false);
    expect(value.metrics().active).toBe(0);
  });
  it('rejects overdue delivery after a synchronous settled observer without erasing validated worker truth', async () => {
    const events: AgentProcessEvent[] = [];
    const value = agent('normal', {
      timeoutMs: 200,
      observer(event) {
        events.push(event);
        if (event.event === 'settled') {
          const end = performance.now() + 250;
          while (performance.now() < end) {
            /* actual completed worker, delayed caller observation */
          }
        }
      },
    });
    await expect(value.prepare(input(), new AbortController().signal)).rejects.toMatchObject({
      code: 'DispatchUnavailable',
    });
    expect(events[1]!.code).toBe('ok');
    expect(value.metrics().succeeded).toBe(1);
    expect(value.metrics().waiterRejected).toBe(1);
    expect(value.metrics().active).toBe(0);
  });
  it('retains an owned process through temporary signal failure and later close observes actual cleanup', async () => {
    const dir = directory(),
      marker = join(dir, 'held'),
      controller = new AbortController();
    const value = agent('ignore', {
      timeoutMs: 1500,
      cleanupTimeoutMs: 20,
      environment: { P2_AGENT_MODE: 'ignore', P2_AGENT_MARKER: marker },
    });
    const pending = value.prepare(input(), controller.signal),
      rejected = expect(pending).rejects.toMatchObject({ code: 'DispatchUnavailable' });
    await until(() => existsSync(marker));
    const pid = Number(readFileSync(marker, 'utf8')),
      kill = process.kill.bind(process);
    let deny = true;
    const mocked = vi.spyOn(process, 'kill').mockImplementation((selected, signal) => {
      if (selected === -pid && deny) {
        if (signal === 0) return true;
        throw Object.assign(new Error('PRIVATE_SIGNAL_FAILURE'), { code: 'EPERM' });
      }
      return kill(selected, signal);
    });
    try {
      controller.abort();
      await rejected;
      expect(value.metrics().active).toBe(1);
      await expect(value.prepare(input(), new AbortController().signal)).rejects.toMatchObject({
        code: 'Overloaded',
      });
      await expect(value.close()).rejects.toMatchObject({ code: 'CleanupIncomplete' });
      expect(value.metrics().active).toBe(1);
      deny = false;
      await until(() => value.metrics().active === 0);
      await value.close();
      expect(gone(pid)).toBe(true);
    } finally {
      deny = false;
      mocked.mockRestore();
      await value.close();
    }
  });
  it('bounds observer notifications and rejects sparse or duplicate scope inventories', async () => {
    expect(() =>
      agent('normal', { allowedScopes: Array<{ tenantId: string; accountId: string }>(1) }),
    ).toThrow();
    expect(() => agent('normal', { allowedScopes: [SCOPE, SCOPE] })).toThrow();
    const value = agent('normal', { observer: () => new Promise<void>(() => undefined) });
    for (let count = 0; count < 5; count++)
      await value.prepare(input(), new AbortController().signal);
    expect(value.metrics().observerPending).toBe(8);
    expect(value.metrics().observerDropped).toBe(2);
    expect(value.metrics().active).toBe(0);
  });
  it('rejects duplicate-key/noncanonical/wrong-scope protocol input and binds valid responses to all context', () => {
    const data = input(),
      context = prepareDispatch(data.message, data.currentCase, {
        kind: 'investigation',
        source: 'scripted',
        caseRevision: '1',
      }).submission,
      wire = request(context);
    expect(parseRequest(wire.raw, scopes([SCOPE])).context).toEqual(context);
    expect(() =>
      parseRequest(wire.raw, scopes([{ tenantId: 'tenant-b', accountId: 'account-b' }])),
    ).toThrow();
    expect(() =>
      parseRequest(Buffer.from('{"schemaVersion":1,"schemaVersion":1}\n'), scopes([SCOPE])),
    ).toThrow();
    const raw = response(
      wire.inputDigest,
      { kind: 'investigation', source: 'scripted', caseRevision: '1' },
      '1',
    );
    expect(parseResponse(raw, wire.inputDigest, '1').source).toBe('scripted');
    expect(() => parseResponse(raw, '0'.repeat(64), '1')).toThrow();
  });
});
