/** Real inbox transaction/observer code over a synthetic driver/catalog; no PG evidence. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ChannelInbox, SeededAccounts } from '../src/postgres.js';
import { createFakeSmsIntegration } from '../src/security.js';
const driver = vi.hoisted(() => ({ query: vi.fn(), release: vi.fn(), end: vi.fn() }));
vi.mock('../src/database.js', async () => {
  const original = await vi.importActual<typeof import('../src/database.js')>('../src/database.js');
  return {
    ...original,
    validate: async () => ({
      maxInbox: 1000,
      maxChallenges: 512,
      maxAssociations: 256,
      maxSenders: 128,
    }),
    PgPool: class {
      on() {}
      async connect() {
        return { query: driver.query, release: driver.release };
      }
      async end() {
        driver.end();
      }
    },
  };
});
const account = 'a'.repeat(43);
function inbox(observer: (event: unknown) => void | Promise<void>) {
  return new ChannelInbox(
    {
      host: '127.0.0.1',
      port: 1,
      database: 'livekit_lab',
      user: 'livekit_lab',
      password: 'p'.repeat(43),
      schema: 'p2_observer_unit',
    },
    createFakeSmsIntegration(
      { tenantId: 'tenant', provider: 'fake_sms', providerAccountId: 'carrier' },
      Buffer.alloc(32, 7),
    ),
    new SeededAccounts([
      {
        token: account,
        tenantId: 'tenant',
        accountId: 'account',
        conversationId: 'conversation',
        caseId: 'case',
      },
    ]),
    {},
    observer,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  driver.query.mockImplementation(async (text: string) =>
    text.includes('clock_timestamp()')
      ? { rows: [{ now: new Date() }], rowCount: 1 }
      : { rows: [], rowCount: 0 },
  );
});
describe('bounded ordinary observer callbacks', () => {
  it('rejects a ninth actual held observer invocation while nine useful history reads settle', async () => {
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const observer = vi.fn(() => held);
    const value = inbox(observer);
    try {
      for (let index = 0; index < 9; index++)
        expect((await value.history(account)).messages).toEqual([]);
      expect(value.metrics().active).toBe(0);
      expect(observer).toHaveBeenCalledTimes(8);
    } finally {
      await value.close();
      release();
      await held;
    }
  });
  it('does not retain synchronous callbacks or change existing metrics fieldsets', async () => {
    const observer = vi.fn(() => {});
    const value = inbox(observer);
    try {
      for (let index = 0; index < 12; index++) await value.history(account);
      expect(observer).toHaveBeenCalledTimes(12);
      expect(value.telemetryMetrics()).toEqual({
        observerPending: 0,
        observerDropped: 0,
        observerFailures: 0,
      });
      expect(Object.keys(value.metrics()).sort()).toEqual([
        'accepted',
        'active',
        'dependencyErrors',
        'overloaded',
        'rejected',
        'replayed',
        'telemetryFailures',
      ]);
      expect(value.communicationMetrics()).toEqual({});
    } finally {
      await value.close();
    }
  });
  it('contains synchronous observer exceptions without changing read results or reflecting diagnostics', async () => {
    const events: unknown[] = [];
    const value = inbox((event) => {
      events.push(event);
      throw Error('SENTINEL_PRIVATE_BODY');
    });
    try {
      expect((await value.history(account)).messages).toEqual([]);
      expect(value.telemetryMetrics()).toEqual({
        observerPending: 0,
        observerDropped: 0,
        observerFailures: 1,
      });
      expect(value.metrics().telemetryFailures).toBe(1);
      expect(JSON.stringify(events)).not.toContain('SENTINEL');
      expect(events).toEqual([{ event: 'completed', operation: 'history', code: 'ok' }]);
    } finally {
      await value.close();
    }
  });
  it('retains rejected async callbacks until actual settlement and records one fixed failure', async () => {
    let reject!: (reason: Error) => void;
    const held = new Promise<void>((_resolve, no) => {
      reject = no;
    });
    const value = inbox(() => held);
    try {
      await value.history(account);
      expect(value.telemetryMetrics().observerPending).toBe(1);
      reject(Error('SENTINEL_PRIVATE_ASYNC'));
      await vi.waitFor(() =>
        expect(value.telemetryMetrics()).toEqual({
          observerPending: 0,
          observerDropped: 0,
          observerFailures: 1,
        }),
      );
      expect(value.metrics().dependencyErrors).toBe(0);
    } finally {
      await value.close();
    }
  });
  it('keeps application-owned callback work visible after SQL closes and never closes its transport', async () => {
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const closeTransport = vi.fn();
    const observer = Object.assign(
      vi.fn(() => held),
      { close: closeTransport },
    );
    const value = inbox(observer);
    for (let index = 0; index < 9; index++) await value.history(account);
    const closing = value.close();
    await closing;
    expect(driver.end).toHaveBeenCalledTimes(1);
    expect(value.metrics().active).toBe(0);
    expect(value.telemetryMetrics().observerPending).toBe(8);
    expect(closeTransport).not.toHaveBeenCalled();
    expect(value.close()).toBe(closing);
    await expect(value.history(account)).rejects.toMatchObject({ code: 'StorageUnavailable' });
    expect(observer).toHaveBeenCalledTimes(8);
    release();
    await held;
    await vi.waitFor(() => expect(value.telemetryMetrics().observerPending).toBe(0));
  });
  it('reserves each slot before calling the sink and does not invoke the ninth sink', async () => {
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const seen: number[] = [];
    let value!: ChannelInbox;
    value = inbox(() => {
      seen.push(value.telemetryMetrics().observerPending);
      return held;
    });
    try {
      for (let index = 0; index < 10; index++) await value.history(account);
      expect(seen).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
      expect(value.telemetryMetrics()).toEqual({
        observerPending: 8,
        observerDropped: 2,
        observerFailures: 0,
      });
    } finally {
      await value.close();
      release();
      await held;
    }
  });
  it('admits later useful notifications only after actual held returns settle', async () => {
    let release!: () => void;
    let held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const observer = vi.fn(() => held);
    const value = inbox(observer);
    try {
      for (let index = 0; index < 9; index++) await value.history(account);
      expect(observer).toHaveBeenCalledTimes(8);
      release();
      await held;
      await vi.waitFor(() => expect(value.telemetryMetrics().observerPending).toBe(0));
      held = new Promise<void>((resolve) => {
        release = resolve;
      });
      await value.history(account);
      expect(observer).toHaveBeenCalledTimes(9);
      expect(value.telemetryMetrics()).toEqual({
        observerPending: 1,
        observerDropped: 1,
        observerFailures: 0,
      });
    } finally {
      release();
      await held;
      await value.close();
    }
  });
  it('returns immutable detached finite telemetry snapshots', async () => {
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const value = inbox(() => held);
    const before = value.telemetryMetrics();
    try {
      await value.history(account);
      expect(Object.isFrozen(before)).toBe(true);
      expect(before.observerPending).toBe(0);
      expect(value.telemetryMetrics().observerPending).toBe(1);
      expect(Object.values(value.telemetryMetrics()).every(Number.isSafeInteger)).toBe(true);
    } finally {
      release();
      await held;
      await value.close();
    }
  });
  it('keeps a slot reserved while an observer-return thenable resolves or fails', async () => {
    let value!: ChannelInbox;
    const seen: number[] = [];
    const returned = {
      get then(): never {
        seen.push(value.telemetryMetrics().observerPending);
        throw Error('SENTINEL_THENABLE');
      },
    };
    value = inbox(() => returned as unknown as Promise<void>);
    try {
      expect((await value.history(account)).messages).toEqual([]);
      expect(seen).toEqual([1]);
      await vi.waitFor(() => expect(value.telemetryMetrics().observerPending).toBe(0));
      expect(value.telemetryMetrics().observerFailures).toBe(1);
    } finally {
      await value.close();
    }
  });
});
