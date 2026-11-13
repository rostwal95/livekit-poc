/** Explicit opt-in prepared-read PG fixture. Synthetic planning/operation ports; no P1/RTC/providers. */
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { isAbsolute, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import pg from 'pg';
import {
  ChannelInbox,
  SeededAccounts,
  type DatabaseSettings,
} from '@livekit-ecosystem/channel-continuity/postgres';
import {
  NativeChannelInbox,
  createNativeIntegration,
} from '@livekit-ecosystem/channel-continuity/native';
import {
  ChannelDispatcher,
  type DispatchPorts,
  type PreparedDispatch,
} from '@livekit-ecosystem/channel-continuity/dispatch';
import {
  createFakeSmsIntegration,
  signFakeSms,
} from '@livekit-ecosystem/channel-continuity/security';
import {
  installChannelSchema,
  upgradeChannelSchemaV2,
  upgradeChannelSchemaV3,
  upgradeChannelSchemaV4,
  upgradeChannelSchemaV5,
  upgradeChannelSchemaV6,
  upgradeChannelSchemaV7,
  upgradeChannelSchemaV8,
} from '@livekit-ecosystem/channel-continuity/migrations';
import {
  OriginBudget,
  OriginFixtureError,
  isEntrypoint,
  parsePrepared,
  proofPublished,
  readProof,
  safeCode,
  writeProof,
} from './pg_channel_origin_cases.js';
export const PREPARED_READ_MODES = ['setup', 'read', 'cleanup'] as const;
export const PREPARED_READ_GROUPS = [
  'known_unprepared_null',
  'exact_native_and_signed_sms_plans',
  'equal_read_replay_at_capacity',
  'retained_read_after_source_revocation',
  'foreign_unknown_scope_provider_denied',
  'independent_whole_schema_no_write_oracle',
  'actual_held_read_close_pending',
  'final_settlement_and_owned_cleanup',
] as const;
type Mode = (typeof PREPARED_READ_MODES)[number];
const PREFIX = 'P2_PREPARED_',
  BASE = ['PATH', 'LANG', 'CI', 'NO_COLOR', '__CF_USER_TEXT_ENCODING'],
  TOKENS = [
    'ACCOUNT_TOKEN',
    'FOREIGN_ACCOUNT_TOKEN',
    'NATIVE_PUBLISHER_TOKEN',
    'NATIVE_BEARER',
  ] as const;
function need(value: unknown): asserts value {
  if (!value) throw new OriginFixtureError('invalid_fixture');
}
function fields(value: unknown, names: readonly string[]): Record<string, unknown> {
  need(
    value !== null &&
      typeof value === 'object' &&
      !Array.isArray(value) &&
      [null, Object.prototype].includes(Object.getPrototypeOf(value)),
  );
  const own = Reflect.ownKeys(value);
  need(own.length === names.length && own.every((k) => typeof k === 'string' && names.includes(k)));
  const result: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
  for (const name of names) {
    const d = Object.getOwnPropertyDescriptor(value, name);
    need(d && 'value' in d && d.enumerable);
    result[name] = d.value;
  }
  return result;
}
const uuid = (v: unknown): string => {
  need(
    typeof v === 'string' &&
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])/.test(v),
  );
  return v;
};
const identifier = (v: unknown): string => {
  need(typeof v === 'string' && /^[a-z][a-z0-9_-]{0,63}(?![\s\S])/.test(v));
  return v;
};
export type PreparedReadEnvironment = Readonly<{
  mode: Mode;
  directory: string;
  schema: string;
  port: number;
  ownerPassword?: string;
  runtimePassword?: string;
  tokens: Readonly<Record<(typeof TOKENS)[number], string>>;
}>;
export function parsePreparedReadEnvironment(
  mode: unknown,
  input: unknown,
): PreparedReadEnvironment {
  try {
    need(typeof mode === 'string' && PREPARED_READ_MODES.includes(mode as Mode));
    const m = mode as Mode,
      required = [
        'DIRECTORY',
        'SCHEMA',
        'PG_PORT',
        ...TOKENS,
        ...(m !== 'read' ? ['OWNER_PASSWORD'] : []),
        ...(m !== 'cleanup' ? ['RUNTIME_PASSWORD'] : []),
      ].map((k) => PREFIX + k);
    need(input !== null && typeof input === 'object');
    const keys = Reflect.ownKeys(input);
    need(keys.every((k) => typeof k === 'string' && [...BASE, ...required].includes(k)));
    const copied: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
    for (const key of keys as string[]) {
      const d = Object.getOwnPropertyDescriptor(input, key);
      need(d && 'value' in d && d.enumerable);
      copied[key] = d.value;
    }
    need(required.every((k) => Object.hasOwn(copied, k)));
    need(
      copied.CI === '1' &&
        copied.NO_COLOR === '1' &&
        typeof copied.PATH === 'string' &&
        copied.PATH.length > 0 &&
        copied.PATH.length <= 8192 &&
        typeof copied.LANG === 'string' &&
        copied.LANG.length > 0 &&
        copied.LANG.length <= 64,
    );
    if (Object.hasOwn(copied, '__CF_USER_TEXT_ENCODING'))
      need(
        typeof copied.__CF_USER_TEXT_ENCODING === 'string' &&
          copied.__CF_USER_TEXT_ENCODING.length <= 64,
      );
    const directory = copied[PREFIX + 'DIRECTORY'],
      schema = copied[PREFIX + 'SCHEMA'],
      port = copied[PREFIX + 'PG_PORT'];
    need(
      typeof directory === 'string' &&
        isAbsolute(directory) &&
        resolve(directory) === directory &&
        !/[\u0000-\u001f\u007f]/.test(directory) &&
        directory.length <= 4096,
    );
    need(typeof schema === 'string' && /^p2_prepared_[0-9a-f]{32}(?![\s\S])/.test(schema));
    need(
      typeof port === 'string' && /^[1-9][0-9]{0,4}(?![\s\S])/.test(port) && Number(port) <= 65535,
    );
    const tokens = Object.fromEntries(
      TOKENS.map((key) => {
        const v = copied[PREFIX + key];
        need(typeof v === 'string' && /^[A-Za-z0-9_-]{43}(?![\s\S])/.test(v));
        return [key, v];
      }),
    ) as Record<(typeof TOKENS)[number], string>;
    need(new Set(Object.values(tokens)).size === TOKENS.length);
    const password = (key: string) => {
      const value = copied[PREFIX + key];
      need(
        typeof value === 'string' &&
          value.length >= 32 &&
          value.length <= 128 &&
          !/[\u0000-\u001f\u007f]/.test(value),
      );
      return value;
    };
    return Object.freeze({
      mode: m,
      directory,
      schema,
      port: Number(port),
      tokens: Object.freeze(tokens),
      ...(m !== 'read' ? { ownerPassword: password('OWNER_PASSWORD') } : {}),
      ...(m !== 'cleanup' ? { runtimePassword: password('RUNTIME_PASSWORD') } : {}),
    });
  } catch {
    throw new OriginFixtureError('invalid_environment');
  }
}
export type PreparedReadFixture = Readonly<{
  schema_version: 1;
  scope: Readonly<{ tenantId: string; accountId: string }>;
  case_id: string;
  conversation_id: string;
  binding_id: string;
  input_ids: Readonly<{ unprepared: string; native: string; sms: string }>;
  parent_expires_at_ms: number;
}>;
export function parsePreparedReadFixture(value: unknown, now = Date.now()): PreparedReadFixture {
  const x = fields(value, [
      'schema_version',
      'scope',
      'case_id',
      'conversation_id',
      'binding_id',
      'input_ids',
      'parent_expires_at_ms',
    ]),
    scope = fields(x.scope, ['tenantId', 'accountId']),
    ids = fields(x.input_ids, ['unprepared', 'native', 'sms']);
  need(
    x.schema_version === 1 &&
      typeof x.parent_expires_at_ms === 'number' &&
      Number.isSafeInteger(x.parent_expires_at_ms) &&
      x.parent_expires_at_ms > now &&
      x.parent_expires_at_ms <= now + 180000,
  );
  const inputIds = Object.freeze({
      unprepared: uuid(ids.unprepared),
      native: uuid(ids.native),
      sms: uuid(ids.sms),
    }),
    binding = uuid(x.binding_id);
  need(new Set([binding, ...Object.values(inputIds)]).size === 4);
  return Object.freeze({
    schema_version: 1,
    scope: Object.freeze({
      tenantId: identifier(scope.tenantId),
      accountId: identifier(scope.accountId),
    }),
    case_id: identifier(x.case_id),
    conversation_id: identifier(x.conversation_id),
    binding_id: binding,
    input_ids: inputIds,
    parent_expires_at_ms: x.parent_expires_at_ms,
  });
}
type Closeable = { close(): Promise<void> };
class Context {
  readonly budget: OriginBudget;
  readonly owners = new Set<Closeable>();
  constructor(
    readonly env: PreparedReadEnvironment,
    readonly f: PreparedReadFixture,
  ) {
    this.budget = new OriginBudget(f.parent_expires_at_ms);
  }
  check() {
    if (this.env.mode === 'cleanup') this.budget.checkCleanup();
    else this.budget.checkBusiness();
  }
  save(name: string, value: unknown) {
    this.budget.checkCleanup();
    writeProof(this.env.directory, name, value);
  }
  async wait(name: string, shape: Record<string, unknown>, cleanup = false) {
    while (!proofPublished(this.env.directory, name)) {
      if (cleanup) this.budget.checkCleanup();
      else this.check();
      await delay(5);
    }
    if (cleanup) this.budget.checkCleanup();
    else this.check();
    assert.deepEqual(readProof(this.env.directory, name), shape);
  }
  db(owner = false): DatabaseSettings {
    this.check();
    const password = owner ? this.env.ownerPassword : this.env.runtimePassword;
    need(password);
    return {
      host: '127.0.0.1',
      port: this.env.port,
      database: 'livekit_lab',
      user: owner ? 'continuity_migrator' : 'livekit_lab',
      password,
      schema: this.env.schema,
    };
  }
  own<T extends Closeable>(owner: T): T {
    this.owners.add(owner);
    return owner;
  }
  async close(owner: Closeable) {
    await owner.close();
    this.owners.delete(owner);
  }
  async finish() {
    const outcomes = await Promise.allSettled([...this.owners].map((owner) => this.close(owner)));
    if (outcomes.some((x) => x.status === 'rejected') || this.owners.size)
      throw new OriginFixtureError('cleanup_incomplete');
  }
  accounts() {
    return new SeededAccounts([
      {
        token: this.env.tokens.ACCOUNT_TOKEN,
        ...this.f.scope,
        caseId: this.f.case_id,
        conversationId: this.f.conversation_id,
      },
      {
        token: this.env.tokens.FOREIGN_ACCOUNT_TOKEN,
        tenantId: this.f.scope.tenantId,
        accountId: 'foreign_account',
        caseId: 'foreign_case',
        conversationId: 'foreign_conversation',
      },
    ]);
  }
  provider(native: boolean) {
    return {
      tenantId: this.f.scope.tenantId,
      provider: native ? 'livekit' : 'fake_sms',
      providerAccountId: native ? 'prepared_rtc' : 'prepared_sms',
    };
  }
  integration(native: boolean) {
    return native
      ? createNativeIntegration(this.provider(true), [
          {
            token: this.env.tokens.NATIVE_PUBLISHER_TOKEN,
            scope: this.f.scope,
            caseId: this.f.case_id,
            conversationId: this.f.conversation_id,
          },
        ])
      : createFakeSmsIntegration(this.provider(false), Buffer.alloc(32, 0x52));
  }
  dispatcher(native: boolean, ports: DispatchPorts) {
    return this.own(
      new ChannelDispatcher(this.db(), this.integration(native), this.accounts(), ports, {
        observer: () => {},
      }),
    );
  }
}
export function syntheticPorts(
  c: Pick<Context, 'check'>,
  plans?: Map<string, PreparedDispatch>,
): DispatchPorts {
  return {
    cases: {
      async inspect(ref) {
        if (!plans) throw new OriginFixtureError('unexpected_outcome');
        c.check();
        return { ...ref, revision: '1', source: 'synthetic_read_only' };
      },
    },
    agent: {
      async prepare(v) {
        if (!plans) throw new OriginFixtureError('unexpected_outcome');
        c.check();
        return { kind: 'investigation', source: 'scripted', caseRevision: v.currentCase.revision };
      },
    },
    operations: {
      capabilities: 'stable_idempotency_and_lookup',
      async lookup() {
        throw new OriginFixtureError('unexpected_outcome');
      },
      async accept() {
        throw new OriginFixtureError('unexpected_outcome');
      },
      ...(plans
        ? {
            async lookup() {
              c.check();
              return { status: 'absent' } as const;
            },
            async accept(plan: PreparedDispatch) {
              c.check();
              need(!plans.has(plan.submission.operationKey));
              plans.set(plan.submission.operationKey, plan);
              return {
                operationKey: plan.submission.operationKey,
                scope: plan.submission.scope,
                payloadDigest: plan.payloadDigest,
                receiptId: randomUUID(),
              };
            },
          }
        : {}),
    },
  };
}
function nativeInput(c: Context, which: 'unprepared' | 'native') {
  return {
    schemaVersion: 1 as const,
    inputId: c.f.input_ids[which],
    channel: 'web_chat' as const,
    body: which === 'native' ? 'Read the original policy: café 🧭.' : 'Retain without preparing.',
    roomId: 'prepared_room',
    participantId: 'prepared_participant',
  };
}
async function expectCode(action: () => Promise<unknown>, code: string) {
  let observed = 'not_rejected';
  try {
    await action();
  } catch (error) {
    observed = safeCode(error);
  }
  assert.equal(observed, code);
  return observed;
}
async function setup(c: Context) {
  await installChannelSchema(c.db(true), {
    maxInbox: 3,
    maxChallenges: 4,
    maxAssociations: 4,
    maxSenders: 4,
  });
  await upgradeChannelSchemaV2(c.db(true), {
    maxActive: 2,
    maxAttempts: 3,
    leaseMs: 500,
    retryDelayMs: 20,
  });
  await upgradeChannelSchemaV3(c.db(true), { maxReplies: 4, maxRoutes: 4, maxAttempts: 3 });
  await upgradeChannelSchemaV4(c.db(true));
  await upgradeChannelSchemaV5(c.db(true));
  await upgradeChannelSchemaV6(c.db(true));
  await upgradeChannelSchemaV7(c.db(true));
  const receiver = uuid(await upgradeChannelSchemaV8(c.db(true))),
    inbox = c.own(new NativeChannelInbox(c.db(), c.integration(true), c.accounts(), {}, () => {})),
    sms = c.own(new ChannelInbox(c.db(), c.integration(false), c.accounts(), {}, () => {})),
    plans = new Map<string, PreparedDispatch>(),
    native = c.dispatcher(true, syntheticPorts(c, plans)),
    smsDispatch = c.dispatcher(false, syntheticPorts(c, plans));
  c.check();
  await inbox.bind(c.env.tokens.NATIVE_PUBLISHER_TOKEN, {
    bindingId: c.f.binding_id,
    bearer: c.env.tokens.NATIVE_BEARER,
    roomId: 'prepared_room',
    participantId: 'prepared_participant',
    expiresAt: new Date(c.f.parent_expires_at_ms).toISOString(),
  });
  c.check();
  const unprepared = await inbox.accept(c.env.tokens.NATIVE_BEARER, nativeInput(c, 'unprepared'));
  c.check();
  const n = await inbox.accept(c.env.tokens.NATIVE_BEARER, nativeInput(c, 'native'));
  const sign = (body: string, event: string) =>
    signFakeSms(
      {
        schemaVersion: 1,
        eventId: event,
        messageId: event,
        senderId: 'prepared_sms_sender',
        body,
        occurredAt: new Date().toISOString(),
      },
      Buffer.alloc(32, 0x52),
      Math.floor(Date.now() / 1000),
      c.provider(false),
    );
  c.check();
  const challenge = await sms.createChallenge(c.env.tokens.ACCOUNT_TOKEN, 'prepared_sms_sender'),
    link = sign('LINK ' + challenge.challengeId + ' ' + challenge.secret, 'prepared_link');
  c.check();
  await sms.completeAssociation(link.raw, link.headers);
  const signed = sign('Review the signed SMS policy.', c.f.input_ids.sms);
  c.save('prepared-sms-source.json', {
    schema_version: 1,
    raw_utf8: Buffer.from(signed.raw).toString('utf8'),
    headers: signed.headers,
  });
  c.check();
  const accepted = await sms.acceptSms(signed.raw, signed.headers);
  c.check();
  const s = await sms.inspect(c.env.tokens.ACCOUNT_TOKEN, accepted.receipt.receiptId);
  c.check();
  assert.equal((await native.step(c.env.tokens.ACCOUNT_TOKEN, n.receiptId)).status, 'dispatched');
  c.check();
  assert.equal(
    (await smsDispatch.step(c.env.tokens.ACCOUNT_TOKEN, s.receipt.receiptId)).status,
    'dispatched',
  );
  c.check();
  const capacity = await expectCode(
    () =>
      inbox.accept(c.env.tokens.NATIVE_BEARER, {
        ...nativeInput(c, 'native'),
        inputId: randomUUID(),
      }),
    'Overloaded',
  );
  c.check();
  const nativeRevocation = await inbox.revoke(c.env.tokens.NATIVE_PUBLISHER_TOKEN, c.f.binding_id);
  c.check();
  const smsRevocation = await sms.revokeAssociation(
    c.env.tokens.ACCOUNT_TOKEN,
    'prepared_sms_sender',
  );
  need(smsRevocation.revoked);
  need(plans.size === 2);
  c.save('prepared-setup.json', {
    schema_version: 1,
    receiver_id: receiver,
    inputs: {
      unprepared: { receiptId: unprepared.receiptId, operationKey: unprepared.operationKey },
      native: { receiptId: n.receiptId, operationKey: n.operationKey },
      sms: { receiptId: s.receipt.receiptId, operationKey: s.operationKey },
    },
    plans: { native: plans.get(n.operationKey), sms: plans.get(s.operationKey) },
    capacity_code: capacity,
    revocations: { native: nativeRevocation, sms: smsRevocation },
    synthetic_ports: true,
  });
}
export function parsePreparedSetup(value: unknown) {
  const x = fields(value, [
      'schema_version',
      'receiver_id',
      'inputs',
      'plans',
      'capacity_code',
      'revocations',
      'synthetic_ports',
    ]),
    i = fields(x.inputs, ['unprepared', 'native', 'sms']),
    p = fields(x.plans, ['native', 'sms']);
  need(x.schema_version === 1 && x.capacity_code === 'Overloaded' && x.synthetic_ports === true);
  const input = (v: unknown) => {
    const r = fields(v, ['receiptId', 'operationKey']);
    return { receiptId: uuid(r.receiptId), operationKey: uuid(r.operationKey) };
  };
  const revocations = fields(x.revocations, ['native', 'sms']),
    nativeRevocation = fields(revocations.native, ['bindingId', 'revokedAt']),
    smsRevocation = fields(revocations.sms, ['revoked', 'associationVersion']);
  uuid(nativeRevocation.bindingId);
  need(
    typeof nativeRevocation.revokedAt === 'string' &&
      Number.isFinite(Date.parse(nativeRevocation.revokedAt)) &&
      new Date(nativeRevocation.revokedAt).toISOString() === nativeRevocation.revokedAt,
  );
  need(
    smsRevocation.revoked === true &&
      typeof smsRevocation.associationVersion === 'string' &&
      /^[1-9][0-9]{0,18}(?![\s\S])/.test(smsRevocation.associationVersion),
  );
  const inputs = Object.freeze({
      unprepared: Object.freeze(input(i.unprepared)),
      native: Object.freeze(input(i.native)),
      sms: Object.freeze(input(i.sms)),
    }),
    plans = Object.freeze({ native: parsePrepared(p.native), sms: parsePrepared(p.sms) });
  need(new Set(Object.values(inputs).flatMap((v) => [v.receiptId, v.operationKey])).size === 6);
  for (const label of ['native', 'sms'] as const) {
    need(
      plans[label].submission.operationKey === inputs[label].operationKey &&
        plans[label].submission.message.receiptId === inputs[label].receiptId,
    );
  }
  return Object.freeze({ receiver: uuid(x.receiver_id), inputs, plans });
}
async function read(c: Context) {
  const previous = parsePreparedSetup(readProof(c.env.directory, 'prepared-setup.json')),
    native = c.dispatcher(true, syntheticPorts(c)),
    sms = c.dispatcher(false, syntheticPorts(c));
  c.check();
  assert.equal(
    await native.readPrepared(c.env.tokens.ACCOUNT_TOKEN, previous.inputs.unprepared.receiptId),
    null,
  );
  for (const [owner, label] of [
    [native, 'native'],
    [sms, 'sms'],
  ] as const) {
    c.check();
    assert.deepEqual(
      await owner.readPrepared(c.env.tokens.ACCOUNT_TOKEN, previous.inputs[label].receiptId),
      previous.plans[label],
    );
    c.check();
    assert.deepEqual(
      await owner.readPrepared(c.env.tokens.ACCOUNT_TOKEN, previous.inputs[label].receiptId),
      previous.plans[label],
    );
  }
  const codes: Record<string, string> = {};
  for (const [label, action] of [
    [
      'foreign',
      () =>
        native.readPrepared(c.env.tokens.FOREIGN_ACCOUNT_TOKEN, previous.inputs.native.receiptId),
    ],
    ['unknown', () => native.readPrepared(c.env.tokens.ACCOUNT_TOKEN, randomUUID())],
    [
      'wrong_provider',
      () => native.readPrepared(c.env.tokens.ACCOUNT_TOKEN, previous.inputs.sms.receiptId),
    ],
  ] as const) {
    c.check();
    codes[label] = await expectCode(action, 'NotFound');
  }
  c.save('prepared-controls-complete.json', { schema_version: 1, complete: true });
  c.save('prepared-read-ready.json', { schema_version: 1, pid: process.pid });
  await c.wait('prepared-hold-ready.json', { schema_version: 1, hold: true });
  c.check();
  let readSettled = false,
    closeSettled = false,
    readError: unknown,
    closeError: unknown;
  const actual = native
    .readPrepared(c.env.tokens.ACCOUNT_TOKEN, previous.inputs.native.receiptId)
    .then(
      (v) => {
        readSettled = true;
        return v;
      },
      (e) => {
        readSettled = true;
        readError = e;
        return null;
      },
    );
  c.save('prepared-read-callers-started.json', { schema_version: 1, callerCount: 1 });
  await c.wait('prepared-close-read.json', { schema_version: 1, close: true }, true);
  const closing = c.close(native).then(
    () => {
      closeSettled = true;
    },
    (e) => {
      closeSettled = true;
      closeError = e;
    },
  );
  await delay(25);
  need(!readSettled && !closeSettled);
  const closedCode = await expectCode(
    () => native.readPrepared(c.env.tokens.ACCOUNT_TOKEN, previous.inputs.native.receiptId),
    'StorageUnavailable',
  );
  c.save('prepared-close-pending.json', {
    schema_version: 1,
    pending_read: true,
    pending_close: true,
    subsequent_read_code: closedCode,
  });
  const plan = await actual;
  await closing;
  if (readError) throw readError;
  if (closeError) throw closeError;
  assert.deepEqual(plan, previous.plans.native);
  need(readSettled && closeSettled);
  await c.close(sms);
  c.save('prepared-read.json', {
    schema_version: 1,
    status: 'passed',
    fixture_groups: PREPARED_READ_GROUPS.filter(
      (x) =>
        x !== 'independent_whole_schema_no_write_oracle' &&
        x !== 'final_settlement_and_owned_cleanup',
    ),
    codes,
    held_read_settled: readSettled,
    close_settled: closeSettled,
    retained_owners: c.owners.size,
    synthetic_ports: true,
    actual_database_write_assertions: 0,
  });
}
async function ownerSql<T>(c: Context, fn: (db: pg.Client) => Promise<T>) {
  const db = new pg.Client({
    ...c.db(true),
    ssl: false,
    connectionTimeoutMillis: 1500,
    query_timeout: 3000,
    options: '-c search_path=pg_catalog -c statement_timeout=2500 -c lock_timeout=1500',
  });
  try {
    await db.connect();
    return await fn(db);
  } finally {
    await db.end();
  }
}
async function cleanup(c: Context) {
  const previous = parsePreparedSetup(readProof(c.env.directory, 'prepared-setup.json'));
  assert.equal(await upgradeChannelSchemaV8(c.db(true)), previous.receiver);
  await ownerSql(c, async (db) => {
    const row = await db.query(
      "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=$1",
      [c.env.schema],
    );
    need(
      row.rowCount === 1 &&
        row.rows[0]?.owner === 'continuity_migrator' &&
        row.rows[0]?.marker === 'p2-channel-schema-v8',
    );
    await db.query('DROP SCHEMA "' + c.env.schema + '" CASCADE');
    assert.equal(
      (await db.query('SELECT 1 FROM pg_namespace WHERE nspname=$1', [c.env.schema])).rowCount,
      0,
    );
  });
  c.save('prepared-cleanup.json', {
    schema_version: 1,
    namespace_absent: true,
    receiver_id: previous.receiver,
  });
}
export async function runPreparedRead(mode: unknown, environment: unknown) {
  const env = parsePreparedReadEnvironment(mode, environment),
    fixture = parsePreparedReadFixture(readProof(env.directory, 'prepared-fixture.json')),
    c = new Context(env, fixture);
  let primary: unknown,
    failed = false;
  try {
    if (env.mode === 'setup') await setup(c);
    else if (env.mode === 'read') await read(c);
    else await cleanup(c);
  } catch (error) {
    primary = error;
    failed = true;
  } finally {
    try {
      await c.finish();
    } catch (error) {
      if (!failed) {
        primary = error;
        failed = true;
      }
    }
  }
  if (failed) throw primary;
}
if (isEntrypoint(import.meta.url, process.argv)) {
  const mode = process.argv[2];
  try {
    await runPreparedRead(mode, process.env);
    process.stdout.write(JSON.stringify({ schema_version: 1, status: 'passed', mode }) + '\n');
  } catch (error) {
    process.stdout.write(
      JSON.stringify({
        schema_version: 1,
        status: 'failed',
        mode: PREPARED_READ_MODES.includes(mode as Mode) ? mode : 'invalid',
        code: safeCode(error),
      }) + '\n',
    );
    process.exitCode = 1;
  }
}
