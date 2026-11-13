import { EventEmitter } from 'node:events';
import type { PoolClient } from 'pg';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { ChannelInbox, SeededAccounts, ChannelError } from '../src/postgres.js';
import {
  DEFAULT_LIMITS,
  config,
  limits,
  settings,
  watchClient,
  watchPool,
  PgClient,
  PgPool,
} from '../src/database.js';
import { closeMigrationClient } from '../src/migrations.js';
import { createFakeSmsIntegration } from '../src/security.js';
const db = {
  host: '127.0.0.1',
  port: 15432,
  database: 'livekit_lab',
  user: 'livekit_lab',
  password: 'synthetic'.repeat(5),
  schema: 'p2_fixture',
};
const scope = { tenantId: 'tenant-a', provider: 'fake_sms', providerAccountId: 'carrier-a' };
const seed = {
  token: 'synthetic_account_'.repeat(3),
  tenantId: 'tenant-a',
  accountId: 'account-a',
  conversationId: 'conversation-a',
};
afterEach(() => vi.restoreAllMocks());
describe('offline database configuration and lifecycle boundaries', () => {
  test('connection policy is explicit, local, bounded and ignores extra environment-like fields', () => {
    const fixed = settings(db, 'livekit_lab');
    expect(Object.isFrozen(fixed)).toBe(true);
    const connection = config(fixed);
    expect(connection.max).toBe(2);
    expect(connection.connectionTimeoutMillis).toBe(1500);
    expect(connection.ssl).toBe(false);
    for (const changed of [
      { host: 'remote.example' },
      { schema: 'unsafe;drop' },
      { user: 'livekit_lab_admin' },
      { database: 'another' },
      { password: 'short' },
      { port: NaN },
      { port: true },
      { schema: 'bad\n' },
    ])
      expect(() => settings({ ...db, ...changed } as typeof db, 'livekit_lab')).toThrow(
        ChannelError,
      );
  });
  test('an unexpected disconnect on a pooled or direct client never becomes an unhandled error', async () => {
    const pool = watchPool(new PgPool(config(settings(db, 'livekit_lab'))));
    const checkedOut = new EventEmitter() as unknown as PoolClient;
    pool.emit('connect', checkedOut);
    expect(() => checkedOut.emit('error', new Error('terminating connection'))).not.toThrow();
    const direct = watchClient(new PgClient(config(settings(db, 'livekit_lab'))));
    expect(() => direct.emit('error', new Error('terminating connection'))).not.toThrow();
    await pool.end();
  });
  test('owner limits are bounded and equivalent independent of property insertion order', () => {
    expect(
      limits({ maxSenders: 128, maxAssociations: 256, maxChallenges: 512, maxInbox: 1000 }),
    ).toEqual(DEFAULT_LIMITS);
    for (const value of [0, 10001, NaN, true, 1.5])
      expect(() => limits({ ...DEFAULT_LIMITS, maxInbox: value } as typeof DEFAULT_LIMITS)).toThrow(
        ChannelError,
      );
  });
  test('seeded account configuration is immutable and scope cannot be supplied by a token holder', () => {
    const directory = new SeededAccounts([seed]);
    const account = directory.authenticate(seed.token, 'tenant-a');
    expect(Object.isFrozen(account)).toBe(true);
    expect(JSON.stringify(directory)).not.toContain(seed.token);
    expect(() => directory.authenticate(seed.token, 'tenant-b')).toThrow('AccessDenied');
    expect(() => directory.authenticate('wrong', 'tenant-a')).toThrow('AccessDenied');
    expect(() => new SeededAccounts([seed, seed])).toThrow('AccessDenied');
  });
  test('empty close is idempotent, rejects later work and never opens a connection', async () => {
    const connect = vi.spyOn(PgPool.prototype, 'connect').mockImplementation(() => {
      throw new Error('offline_network_forbidden');
    });
    const box = new ChannelInbox(
      db,
      createFakeSmsIntegration(scope, new Uint8Array(32).fill(7)),
      new SeededAccounts([seed]),
      {},
      () => {},
    );
    await Promise.all([box.close(), box.close()]);
    await expect(box.createChallenge(seed.token, 'sender-a')).rejects.toThrow('StorageUnavailable');
    expect(box.metrics().active).toBe(0);
    expect(connect).not.toHaveBeenCalled();
  });
  test.each(['sync', 'async'] as const)(
    '%s telemetry failure is contained after actual clean resource closure',
    async (mode) => {
      const connect = vi.spyOn(PgPool.prototype, 'connect').mockImplementation(() => {
        throw new Error('offline_network_forbidden');
      });
      const observer =
        mode === 'sync'
          ? () => {
              throw new Error('PRIVATE_SENTINEL');
            }
          : async () => {
              throw new Error('PRIVATE_SENTINEL');
            };
      const box = new ChannelInbox(
        db,
        createFakeSmsIntegration(scope, new Uint8Array(32).fill(7)),
        new SeededAccounts([seed]),
        {},
        observer,
      );
      await box.close();
      await new Promise<void>((resolve) => setImmediate(resolve));
      expect(box.metrics().telemetryFailures).toBe(1);
      expect(connect).not.toHaveBeenCalled();
    },
  );
});

describe('owner-client cleanup contract', () => {
  test('close rejection cannot certify success and preserves an existing safe failure', async () => {
    await expect(
      closeMigrationClient({
        async end() {
          throw Error('PRIVATE_CLOSE');
        },
      }),
    ).rejects.toThrow('CleanupIncomplete');
    const primary = new ChannelError('SchemaMismatch');
    await closeMigrationClient(
      {
        async end() {
          throw Error('PRIVATE_CLOSE');
        },
      },
      primary,
    );
    expect(primary.code).toBe('SchemaMismatch');
    expect(primary.cause).toBeInstanceOf(ChannelError);
    expect(String(primary.cause)).not.toContain('PRIVATE_CLOSE');
  });
  test('unresolved end has a finite deadline without creating another cleanup loop', async () => {
    vi.useFakeTimers();
    try {
      const result = expect(
        closeMigrationClient({
          end() {
            return new Promise<void>(() => {});
          },
        }),
      ).rejects.toThrow('CleanupIncomplete');
      await vi.advanceTimersByTimeAsync(1501);
      await result;
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
});
