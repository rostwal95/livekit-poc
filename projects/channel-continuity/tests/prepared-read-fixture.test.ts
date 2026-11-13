/** Pure guards for the explicit opt-in PG fixture; never connect or compile on import. */
import { describe, expect, it, vi } from 'vitest';
import { mkdtempSync, realpathSync, chmodSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Server } from 'node:net';
import pg from 'pg';
import { preparedSubmission } from '../src/dispatch-types.js';
import {
  PREPARED_READ_MODES,
  PREPARED_READ_GROUPS,
  parsePreparedReadEnvironment,
  parsePreparedReadFixture,
  parsePreparedSetup,
  runPreparedRead,
  syntheticPorts,
} from './pg_prepared_read_cases.js';
import { writeProof } from './pg_channel_origin_cases.js';
const ID = Array.from(
    { length: 8 },
    (_, n) =>
      `${(n + 1).toString(16).padStart(8, '0')}-0000-4000-8000-${(n + 1).toString(16).padStart(12, '0')}`,
  ),
  SCHEMA = 'p2_prepared_' + 'a'.repeat(32);
function env(mode = 'read'): Record<string, string> {
  return {
    PATH: '/pinned/bin',
    LANG: 'en_US.UTF-8',
    CI: '1',
    NO_COLOR: '1',
    P2_PREPARED_DIRECTORY: '/private/tmp/prepared-fixture',
    P2_PREPARED_SCHEMA: SCHEMA,
    P2_PREPARED_PG_PORT: '15432',
    P2_PREPARED_ACCOUNT_TOKEN: 'a'.repeat(43),
    P2_PREPARED_FOREIGN_ACCOUNT_TOKEN: 'b'.repeat(43),
    P2_PREPARED_NATIVE_PUBLISHER_TOKEN: 'c'.repeat(43),
    P2_PREPARED_NATIVE_BEARER: 'd'.repeat(43),
    ...(mode !== 'read' ? { P2_PREPARED_OWNER_PASSWORD: 'synthetic-owner-'.repeat(3) } : {}),
    ...(mode !== 'cleanup' ? { P2_PREPARED_RUNTIME_PASSWORD: 'synthetic-runtime-'.repeat(3) } : {}),
  };
}
function fixture(now = Date.now()) {
  return {
    schema_version: 1,
    scope: { tenantId: 'tenant', accountId: 'account' },
    case_id: 'case',
    conversation_id: 'conversation',
    binding_id: ID[0]!,
    input_ids: { unprepared: ID[1]!, native: ID[2]!, sms: ID[3]! },
    parent_expires_at_ms: now + 170000,
  };
}
function proof() {
  const f = fixture(),
    inputs = {
      unprepared: { receiptId: ID[1]!, operationKey: ID[4]! },
      native: { receiptId: ID[2]!, operationKey: ID[5]! },
      sms: { receiptId: ID[3]!, operationKey: ID[6]! },
    },
    plan = (label: 'native' | 'sms') =>
      preparedSubmission({
        schemaVersion: 1,
        kind: 'investigation',
        operationKey: inputs[label].operationKey,
        scope: f.scope,
        caseId: f.case_id,
        caseRevision: '1',
        conversationId: f.conversation_id,
        message: {
          receiptId: inputs[label].receiptId,
          eventId: ID[7]!,
          messageId: ID[7]!,
          senderId: label === 'native' ? f.binding_id : 'prepared_sms_sender',
          body: 'Read only café 🧭.',
        },
      });
  return {
    schema_version: 1,
    receiver_id: ID[7]!,
    inputs,
    plans: { native: plan('native'), sms: plan('sms') },
    capacity_code: 'Overloaded',
    revocations: {
      native: { bindingId: f.binding_id, revokedAt: '2030-01-01T00:00:00.000Z' },
      sms: { revoked: true, associationVersion: '2' },
    },
    synthetic_ports: true,
  };
}
describe('prepared-read PG fixture pure boundary', () => {
  it('read-mode case, agent, lookup and accept callbacks all reject without consulting authority', async () => {
    const check = vi.fn(),
      ports = syntheticPorts({ check }),
      original = proof().plans.native;
    for (const callback of [
      () =>
        ports.cases.inspect(
          { scope: original.submission.scope, caseId: original.submission.caseId },
          new AbortController().signal,
        ),
      () =>
        ports.agent.prepare(
          {} as Parameters<typeof ports.agent.prepare>[0],
          new AbortController().signal,
        ),
      () =>
        ports.operations.lookup(
          {
            operationKey: original.submission.operationKey,
            scope: original.submission.scope,
            payloadDigest: original.payloadDigest,
          },
          new AbortController().signal,
        ),
      () => ports.operations.accept(original, new AbortController().signal),
    ])
      await expect(callback()).rejects.toMatchObject({ code: 'unexpected_outcome' });
    expect(check).not.toHaveBeenCalled();
  });
  it('setup still invokes the declared synthetic planning and cooperating operation ports', async () => {
    const check = vi.fn(),
      plans = new Map(),
      ports = syntheticPorts({ check }, plans),
      original = proof().plans.native,
      signal = new AbortController().signal;
    expect(
      await ports.cases.inspect(
        { scope: original.submission.scope, caseId: original.submission.caseId },
        signal,
      ),
    ).toMatchObject({ revision: '1', source: 'synthetic_read_only' });
    expect(
      await ports.agent.prepare(
        {
          currentCase: {
            scope: original.submission.scope,
            caseId: original.submission.caseId,
            revision: '1',
            source: 'synthetic_read_only',
          },
        } as Parameters<typeof ports.agent.prepare>[0],
        signal,
      ),
    ).toEqual({ kind: 'investigation', source: 'scripted', caseRevision: '1' });
    expect(
      await ports.operations.lookup(
        {
          operationKey: original.submission.operationKey,
          scope: original.submission.scope,
          payloadDigest: original.payloadDigest,
        },
        signal,
      ),
    ).toEqual({ status: 'absent' });
    expect(await ports.operations.accept(original, signal)).toMatchObject({
      operationKey: original.submission.operationKey,
      payloadDigest: original.payloadDigest,
    });
    expect(plans.get(original.submission.operationKey)).toBe(original);
    expect(check).toHaveBeenCalledTimes(4);
  });
  it.each(PREPARED_READ_MODES)('validates closed role credentials before I/O: %s', (mode) => {
    const e = parsePreparedReadEnvironment(mode, env(mode));
    expect(e.mode).toBe(mode);
    expect(Object.isFrozen(e)).toBe(true);
    expect(Object.isFrozen(e.tokens)).toBe(true);
    expect('ownerPassword' in e).toBe(mode !== 'read');
    expect('runtimePassword' in e).toBe(mode !== 'cleanup');
  });
  it('supports the real process.env host prototype through guarded synthetic descriptors only', () => {
    const synthetic = env(),
      get = vi.fn(() => {
        throw Error('PRIVATE_VALUE_GETTER');
      }),
      guarded = new Proxy(process.env, {
        ownKeys: () => Object.keys(synthetic),
        getOwnPropertyDescriptor: (_t, k) => Object.getOwnPropertyDescriptor(synthetic, k),
        get,
      });
    expect(parsePreparedReadEnvironment('read', guarded).schema).toBe(SCHEMA);
    expect(get).not.toHaveBeenCalled();
  });
  it('rejects unknown keys before descriptors and does not invoke accessors', () => {
    const descriptors = vi.fn(() => {
        throw Error('PRIVATE_DESCRIPTOR');
      }),
      bad = new Proxy(process.env, {
        ownKeys: () => [...Object.keys(env()), 'OPENAI_API_KEY'],
        getOwnPropertyDescriptor: descriptors,
      });
    expect(() => parsePreparedReadEnvironment('read', bad)).toThrowError('invalid_environment');
    expect(descriptors).not.toHaveBeenCalled();
    const getter = vi.fn(() => {
        throw Error('PRIVATE_GETTER');
      }),
      value = Object.defineProperty(env(), 'P2_PREPARED_SCHEMA', { enumerable: true, get: getter });
    expect(() => parsePreparedReadEnvironment('read', value)).toThrowError('invalid_environment');
    expect(getter).not.toHaveBeenCalled();
  });
  it('rejects role crossing, selectors, noncanonical paths and malformed secrets', () => {
    for (const bad of [
      { ...env(), P2_PREPARED_OWNER_PASSWORD: 'o'.repeat(43) },
      { ...env('cleanup'), P2_PREPARED_RUNTIME_PASSWORD: 'r'.repeat(43) },
      { ...env(), PGHOST: 'private' },
      { ...env(), P2_PREPARED_DIRECTORY: '/private/tmp/a/../b' },
      { ...env(), P2_PREPARED_PG_PORT: '015432' },
      { ...env(), P2_PREPARED_NATIVE_BEARER: 'a'.repeat(43) },
      { ...env(), P2_PREPARED_RUNTIME_PASSWORD: 'short' },
    ])
      expect(() => parsePreparedReadEnvironment('read', bad)).toThrowError('invalid_environment');
  });
  it('copies exact fixture identities and fixed final deadline without mutable references', () => {
    const now = Date.now(),
      input = fixture(now),
      actual = parsePreparedReadFixture(input, now);
    input.scope.accountId = 'changed';
    input.input_ids.native = ID[7]!;
    expect(actual.scope.accountId).toBe('account');
    expect(actual.input_ids.native).toBe(ID[2]);
    expect(actual.parent_expires_at_ms).toBe(now + 170000);
    expect(Object.isFrozen(actual.input_ids)).toBe(true);
    expect(PREPARED_READ_GROUPS).toHaveLength(8);
  });
  it('rejects unknown fixture fields, wrong IDs, duplicate identities and unbounded deadlines', () => {
    const now = Date.now(),
      f = fixture(now);
    for (const value of [
      { ...f, extra: true },
      { ...f, schema_version: true },
      { ...f, scope: { ...f.scope, token: 'private' } },
      { ...f, input_ids: { ...f.input_ids, native: f.binding_id } },
      { ...f, parent_expires_at_ms: now + 180001 },
      { ...f, parent_expires_at_ms: now },
      { ...f, parent_expires_at_ms: NaN },
    ])
      expect(() => parsePreparedReadFixture(value, now)).toThrowError('invalid_fixture');
  });
  it('validates actual prepared-proof linkage and revocation shapes without accepting injected fields', () => {
    const input = proof(),
      value = parsePreparedSetup(input);
    expect(value.plans.native.canonicalPayload).toBe(input.plans.native.canonicalPayload);
    expect(Object.isFrozen(value.inputs)).toBe(true);
    for (const bad of [
      { ...input, extra: true },
      {
        ...input,
        plans: { ...input.plans, native: { ...input.plans.native, payloadDigest: '0'.repeat(64) } },
      },
      {
        ...input,
        inputs: { ...input.inputs, native: { ...input.inputs.native, operationKey: ID[0]! } },
      },
      {
        ...input,
        revocations: { ...input.revocations, sms: { revoked: false, associationVersion: '2' } },
      },
      {
        ...input,
        revocations: {
          ...input.revocations,
          native: { ...input.revocations.native, secret: 'private' },
        },
      },
    ])
      expect(() => parsePreparedSetup(bad)).toThrow();
  });
  it('keeps import/rejected entry inert and denies late read admission before PG or listeners', async () => {
    const pool = vi.spyOn(pg.Pool.prototype, 'connect').mockImplementation(() => {
        throw Error('NO_DB');
      }),
      client = vi.spyOn(pg.Client.prototype, 'connect').mockImplementation(() => {
        throw Error('NO_DB');
      }),
      listen = vi.spyOn(Server.prototype, 'listen').mockImplementation(() => {
        throw Error('NO_LISTEN');
      }),
      directory = realpathSync(mkdtempSync(join(tmpdir(), 'prepared-pure-')));
    chmodSync(directory, 0o700);
    try {
      const imported = await import('./pg_prepared_read_cases.js');
      expect(imported.PREPARED_READ_MODES).toEqual(PREPARED_READ_MODES);
      await expect(runPreparedRead('invalid', {})).rejects.toMatchObject({
        code: 'invalid_environment',
      });
      writeProof(directory, 'prepared-fixture.json', {
        ...fixture(),
        parent_expires_at_ms: Date.now() + 10000,
      });
      writeProof(directory, 'prepared-setup.json', proof());
      await expect(
        runPreparedRead('read', { ...env(), P2_PREPARED_DIRECTORY: directory }),
      ).rejects.toMatchObject({ code: 'deadline_exceeded' });
      expect(pool).not.toHaveBeenCalled();
      expect(client).not.toHaveBeenCalled();
      expect(listen).not.toHaveBeenCalled();
    } finally {
      pool.mockRestore();
      client.mockRestore();
      listen.mockRestore();
      rmSync(directory, { recursive: true, force: true });
    }
  });
});
