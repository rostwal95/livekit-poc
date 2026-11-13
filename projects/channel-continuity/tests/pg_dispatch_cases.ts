/** Real-PG dispatch cases: public package consumer plus a separate cooperating operation fixture. */
import assert from 'node:assert/strict';
import { fork, type ChildProcess } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import pg from 'pg';
import { awaitFixtureEntry, fixtureResult, observeFixtureWork } from './fixture-work.js';
import {
  ChannelDispatcher,
  type DispatchPorts,
  type PreparedDispatch,
  type OperationLookup,
  type OperationReceipt,
} from '@livekit-ecosystem/channel-continuity/dispatch';
import {
  SeededAccounts,
  type ChannelInbox,
  type DatabaseSettings,
} from '@livekit-ecosystem/channel-continuity/postgres';
import {
  upgradeChannelSchemaV2,
  type DispatchLimits,
} from '@livekit-ecosystem/channel-continuity/migrations';
import {
  createFakeSmsIntegration,
  type FakeSmsIntegration,
  type SignedFakeSms,
} from '@livekit-ecosystem/channel-continuity/security';
const SCOPE = { tenantId: 'tenant-a', provider: 'fake_sms', providerAccountId: 'carrier-a' };
const ACCOUNT = { tenantId: 'tenant-a', accountId: 'account-a' };
const TOKEN_A = 'synthetic-account-a-' + 'a'.repeat(40),
  TOKEN_B = 'synthetic-account-b-' + 'b'.repeat(40);
const SEEDS = [
  { token: TOKEN_A, ...ACCOUNT, conversationId: 'conversation-a', caseId: 'case-a' },
  {
    token: TOKEN_B,
    tenantId: 'tenant-a',
    accountId: 'account-b',
    conversationId: 'conversation-b',
    caseId: 'case-b',
  },
];
const POLICY: DispatchLimits = { maxActive: 2, maxAttempts: 3, leaseMs: 500, retryDelayMs: 20 };
const MARKER = 'p2-cooperating-operation-fixture-v1';
export type Context = Readonly<{
  fixture(): Promise<{
    schema: string;
    inbox: Pick<ChannelInbox, 'acceptSms' | 'inspect' | 'revokeAssociation' | 'history'>;
    integration: FakeSmsIntegration;
  }>;
  connection(schema: string, owner?: boolean): DatabaseSettings;
  sql<T>(settings: DatabaseSettings, operation: (client: pg.Client) => Promise<T>): Promise<T>;
  bind(inbox: unknown, token: string, sender: string): Promise<string>;
  signed(event: string, sender: string): SignedFakeSms;
  children: Set<ChildProcess>;
  terminated(): void;
}>;
const releases = new Set<() => void>();
const dispatchers = new Set<ChannelDispatcher>(),
  operationSchemas = new Set<string>();
function q(schema: string): string {
  assert.match(schema, /^p2_(inbox|operation)_[a-f0-9]{32}(?![\s\S])/);
  return '"' + schema + '"';
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  return {
    promise: new Promise<T>((done) => {
      resolve = done;
    }),
    resolve: (value: T) => resolve(value),
  };
}
const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
async function rejects(work: () => Promise<unknown>, code: string) {
  await assert.rejects(work, (error: unknown) =>
    Boolean(error && typeof error === 'object' && 'code' in error && error.code === code),
  );
}
function expectedReceipt(input: OperationLookup, receiptId: string): OperationReceipt {
  return {
    operationKey: input.operationKey,
    scope: { ...input.scope },
    payloadDigest: input.payloadDigest,
    receiptId,
  };
}
export function standardPorts(operations: DispatchPorts['operations']): DispatchPorts {
  return {
    cases: {
      async inspect(reference) {
        return { ...reference, revision: '1', source: 'synthetic_read_only' };
      },
    },
    agent: {
      async prepare(input) {
        return {
          kind: 'investigation',
          source: 'scripted',
          caseRevision: input.currentCase.revision,
        };
      },
    },
    operations,
  };
}
function dispatcher(
  c: Context,
  f: { schema: string; integration: FakeSmsIntegration },
  ports: DispatchPorts,
  options = {},
) {
  const d = new ChannelDispatcher(
    c.connection(f.schema),
    f.integration,
    new SeededAccounts(SEEDS),
    ports,
    options,
  );
  dispatchers.add(d);
  return d;
}
export async function operationFixture(c: Context, inboxSchema: string) {
  const schema = 'p2_operation_' + randomUUID().replaceAll('-', '');
  operationSchemas.add(schema);
  await c.sql(c.connection(inboxSchema, true), async (client) => {
    await client.query(`CREATE SCHEMA ${q(schema)} AUTHORIZATION continuity_migrator`);
    await client.query(
      `REVOKE ALL ON SCHEMA ${q(schema)} FROM PUBLIC;GRANT USAGE ON SCHEMA ${q(schema)} TO livekit_lab;COMMENT ON SCHEMA ${q(schema)} IS '${MARKER}'`,
    );
    await client.query(
      `CREATE TABLE ${q(schema)}.operations(operation_key uuid PRIMARY KEY,tenant_id text NOT NULL,account_id text NOT NULL,payload_digest text NOT NULL,payload_json text NOT NULL,receipt_id uuid NOT NULL UNIQUE);REVOKE ALL ON ${q(schema)}.operations FROM PUBLIC;GRANT SELECT,INSERT ON ${q(schema)}.operations TO livekit_lab`,
    );
  });
  return operations(c.connection(inboxSchema), schema);
}
export function operations(database: DatabaseSettings, schema: string) {
  async function query<T>(work: (client: pg.Client) => Promise<T>): Promise<T> {
    const client = new pg.Client({
      ...database,
      ssl: false,
      application_name: 'p2-cooperating-operation-fixture',
      connectionTimeoutMillis: 1000,
      query_timeout: 1500,
      options: '-c search_path=pg_catalog -c statement_timeout=1000 -c lock_timeout=500',
    });
    try {
      await client.connect();
      return await work(client);
    } finally {
      await client.end();
    }
  }
  const port: DispatchPorts['operations'] = {
    capabilities: 'stable_idempotency_and_lookup',
    async lookup(input) {
      return await query(async (client) => {
        const rows = (
          await client.query(`SELECT * FROM ${q(schema)}.operations WHERE operation_key=$1`, [
            input.operationKey,
          ])
        ).rows;
        if (rows.length === 0) return { status: 'absent' };
        const row = rows[0]!;
        assert.equal(row.tenant_id, input.scope.tenantId);
        assert.equal(row.account_id, input.scope.accountId);
        assert.equal(row.payload_digest, input.payloadDigest);
        return { status: 'accepted', receipt: expectedReceipt(input, row.receipt_id as string) };
      });
    },
    async accept(input) {
      return await query(async (client) => {
        await client.query(
          `INSERT INTO ${q(schema)}.operations VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(operation_key) DO NOTHING`,
          [
            input.submission.operationKey,
            input.submission.scope.tenantId,
            input.submission.scope.accountId,
            input.payloadDigest,
            input.canonicalPayload,
            randomUUID(),
          ],
        );
        const row = (
          await client.query(`SELECT * FROM ${q(schema)}.operations WHERE operation_key=$1`, [
            input.submission.operationKey,
          ])
        ).rows[0]!;
        assert.equal(row.tenant_id, input.submission.scope.tenantId);
        assert.equal(row.account_id, input.submission.scope.accountId);
        assert.equal(row.payload_digest, input.payloadDigest);
        assert.equal(row.payload_json, input.canonicalPayload);
        return expectedReceipt(
          {
            operationKey: input.submission.operationKey,
            scope: input.submission.scope,
            payloadDigest: input.payloadDigest,
          },
          row.receipt_id as string,
        );
      });
    },
  };
  return {
    schema,
    port,
    count: () =>
      query(async (client) =>
        Number(
          (await client.query(`SELECT count(*) AS count FROM ${q(schema)}.operations`)).rows[0]!
            .count,
        ),
      ),
  };
}
async function intake(
  c: Context,
  f: Awaited<ReturnType<Context['fixture']>>,
  event: string,
  sender: string,
) {
  const frame = c.signed(event, sender);
  return await f.inbox.acceptSms(frame.raw, frame.headers);
}
async function legacySnapshot(c: Context, schema: string) {
  return await c.sql(
    c.connection(schema, true),
    async (client) =>
      (
        await client.query(
          `SELECT i.*,p.operation_key,p.state FROM ${q(schema)}.inbox i JOIN ${q(schema)}.processing_intents p USING(receipt_id) ORDER BY acceptance_sequence`,
        )
      ).rows,
  );
}
async function plan(c: Context, schema: string, id: string): Promise<PreparedDispatch> {
  return await c.sql(c.connection(schema, true), async (client) => {
    const row = (
      await client.query(
        `SELECT payload_json,payload_digest FROM ${q(schema)}.dispatch_plans WHERE receipt_id=$1`,
        [id],
      )
    ).rows[0]!;
    return {
      submission: JSON.parse(row.payload_json as string) as PreparedDispatch['submission'],
      canonicalPayload: row.payload_json as string,
      payloadDigest: row.payload_digest as string,
    };
  });
}
export function dispatchCases(c: Context): ReadonlyArray<readonly [string, () => Promise<void>]> {
  return [
    [
      'dispatch_v2_upgrade_preserves_identity',
      async () => {
        const f = await c.fixture();
        await c.bind(f.inbox, TOKEN_A, 'upgrade-sender');
        const accepted = await intake(c, f, 'upgrade-event', 'upgrade-sender'),
          before = await legacySnapshot(c, f.schema);
        const op = await operationFixture(c, f.schema),
          d = dispatcher(c, f, standardPorts(op.port));
        await rejects(() => d.step(TOKEN_A, accepted.receipt.receiptId), 'UpgradeRequired');
        await c.sql(c.connection(f.schema, true), async (client) => {
          await client.query(`ALTER TABLE ${q(f.schema)}.inbox ADD COLUMN drift text`);
        });
        await rejects(
          () => upgradeChannelSchemaV2(c.connection(f.schema, true), POLICY),
          'SchemaMismatch',
        );
        assert.equal(
          await c.sql(
            c.connection(f.schema, true),
            async (client) =>
              (await client.query(`SELECT version FROM ${q(f.schema)}.schema_metadata`)).rows[0]!
                .version,
          ),
          1,
        );
        await c.sql(c.connection(f.schema, true), async (client) => {
          await client.query(`ALTER TABLE ${q(f.schema)}.inbox DROP COLUMN drift`);
        });
        await upgradeChannelSchemaV2(c.connection(f.schema, true), POLICY);
        await upgradeChannelSchemaV2(c.connection(f.schema, true), POLICY);
        await rejects(
          () => upgradeChannelSchemaV2(c.connection(f.schema, true), { ...POLICY, maxAttempts: 2 }),
          'SchemaMismatch',
        );
        assert.deepEqual(await legacySnapshot(c, f.schema), before);
        const replay = await intake(c, f, 'upgrade-event', 'upgrade-sender');
        assert.equal(replay.replayed, true);
        assert.deepEqual(replay.receipt, accepted.receipt);
        await c.sql(c.connection(f.schema), async (client) => {
          for (const statement of [
            `DELETE FROM ${q(f.schema)}.dispatch_plans`,
            `UPDATE ${q(f.schema)}.processing_intents SET operation_key=gen_random_uuid()`,
            `UPDATE ${q(f.schema)}.dispatch_settings SET max_attempts=5`,
            `ALTER TABLE ${q(f.schema)}.processing_intents ADD COLUMN forbidden text`,
          ])
            await assert.rejects(
              () => client.query(statement),
              (e: unknown) =>
                Boolean(e && typeof e === 'object' && 'code' in e && e.code === '42501'),
            );
        });
        assert.equal((await d.step(TOKEN_A, accepted.receipt.receiptId)).status, 'dispatched');
        assert.equal(
          (await f.inbox.inspect(TOKEN_A, accepted.receipt.receiptId)).processingState,
          'dispatched',
        );
      },
    ],
    [
      'dispatch_concurrency_scope_and_admission',
      async () => {
        const f = await c.fixture();
        await c.bind(f.inbox, TOKEN_A, 'concurrency-sender');
        const a = await intake(c, f, 'dispatch-a', 'concurrency-sender'),
          b = await intake(c, f, 'dispatch-b', 'concurrency-sender');
        await upgradeChannelSchemaV2(c.connection(f.schema, true), {
          ...POLICY,
          maxActive: 1,
          leaseMs: 5000,
        });
        const op = await operationFixture(c, f.schema),
          entered = deferred<void>(),
          release = deferred<void>();
        releases.add(() => release.resolve());
        let held = true,
          valid = false;
        const ports = standardPorts({
          ...op.port,
          async accept(input, signal) {
            entered.resolve();
            if (held) await release.promise;
            return await op.port.accept(input, signal);
          },
        });
        ports.cases.inspect = async (reference) => ({
          scope: valid ? reference.scope : { ...reference.scope, accountId: 'forged-account' },
          caseId: reference.caseId,
          revision: '1',
          source: 'synthetic_read_only',
        });
        const d = dispatcher(c, f, ports);
        await rejects(() => d.step(TOKEN_A, a.receipt.receiptId), 'OperationConflict');
        assert.equal(await op.count(), 0);
        valid = true;
        await delay(25);
        const work = observeFixtureWork(d.step(TOKEN_A, a.receipt.receiptId));
        try {
          await awaitFixtureEntry(entered.promise, work, 5000);
          const other = dispatcher(c, f, standardPorts(op.port));
          assert.equal((await other.step(TOKEN_A, a.receipt.receiptId)).status, 'busy');
          await rejects(() => other.step(TOKEN_A, b.receipt.receiptId), 'Overloaded');
          await rejects(() => other.inspect(TOKEN_B, a.receipt.receiptId), 'NotFound');
          held = false;
          release.resolve();
          assert.equal((await fixtureResult(work)).status, 'dispatched');
          assert.equal((await other.step(TOKEN_A, b.receipt.receiptId)).status, 'dispatched');
          assert.equal(await op.count(), 2);
          const observed = await d.inspect(TOKEN_A, a.receipt.receiptId);
          assert.equal(observed.attempts, 2);
          assert.equal(observed.history.length, 2);
          assert.equal(observed.history[0]!.disposition, 'operation_conflict');
          assert.equal(observed.history[1]!.disposition, 'accepted');
        } finally {
          held = false;
          release.resolve();
          await work;
        }
      },
    ],
    [
      'dispatch_lease_takeover_reuses_prepared_plan',
      async () => {
        const f = await c.fixture();
        await c.bind(f.inbox, TOKEN_A, 'takeover-sender');
        const a = await intake(c, f, 'takeover-event', 'takeover-sender');
        await upgradeChannelSchemaV2(c.connection(f.schema, true), POLICY);
        const op = await operationFixture(c, f.schema),
          entered = deferred<void>(),
          release = deferred<void>();
        releases.add(() => release.resolve());
        let caseReads = 0;
        const ports = standardPorts({
          ...op.port,
          async accept(input, signal) {
            const receipt = await op.port.accept(input, signal);
            entered.resolve();
            await release.promise;
            return receipt;
          },
        });
        ports.cases.inspect = async (reference) => {
          caseReads++;
          return { ...reference, revision: '1', source: 'synthetic_read_only' };
        };
        const first = dispatcher(c, f, ports),
          work = observeFixtureWork(first.step(TOKEN_A, a.receipt.receiptId));
        try {
          await awaitFixtureEntry(entered.promise, work, 5000);
          const frozen = await plan(c, f.schema, a.receipt.receiptId);
          await delay(550);
          const second = dispatcher(c, f, {
            ...standardPorts(op.port),
            cases: {
              async inspect() {
                throw new Error('MUST_REUSE_PREPARED_CASE');
              },
            },
            agent: {
              async prepare() {
                throw new Error('MUST_REUSE_PREPARED_AGENT');
              },
            },
          });
          const recovered = await second.step(TOKEN_A, a.receipt.receiptId);
          assert.equal(recovered.status, 'dispatched');
          release.resolve();
          await rejects(() => fixtureResult(work), 'DispatchClaimLost');
          assert.deepEqual(await plan(c, f.schema, a.receipt.receiptId), frozen);
          assert.equal(caseReads, 1);
          assert.equal(await op.count(), 1);
          const observation = await second.inspect(TOKEN_A, a.receipt.receiptId);
          assert.equal(observation.attempts, 2);
          assert.deepEqual(
            observation.history.map((item) => item.disposition),
            ['lease_expired', 'accepted'],
          );
          assert.equal(observation.operationKey, frozen.submission.operationKey);
        } finally {
          release.resolve();
          await work;
        }
      },
    ],
    [
      'dispatch_uncertainty_attempt_bound_and_reconciliation',
      async () => {
        const f = await c.fixture();
        await c.bind(f.inbox, TOKEN_A, 'unknown-sender');
        const a = await intake(c, f, 'unknown-event', 'unknown-sender');
        await upgradeChannelSchemaV2(c.connection(f.schema, true), POLICY);
        const op = await operationFixture(c, f.schema);
        let accepts = 0;
        const d = dispatcher(
          c,
          f,
          standardPorts({
            ...op.port,
            async accept() {
              accepts++;
              throw new Error('SYNTHETIC_PRIVATE_FAILURE');
            },
          }),
        );
        for (let index = 0; index < 3; index++) {
          await rejects(() => d.step(TOKEN_A, a.receipt.receiptId), 'DispatchUnavailable');
          await delay(25);
        }
        assert.equal((await d.step(TOKEN_A, a.receipt.receiptId)).status, 'uncertain');
        assert.equal(accepts, 3);
        let observed = await d.inspect(TOKEN_A, a.receipt.receiptId);
        assert.equal(observed.attempts, 3);
        assert.equal(observed.possibleExternal, true);
        assert.equal(observed.state, 'uncertain');
        assert.equal(observed.history.length, 3);
        await f.inbox.revokeAssociation(TOKEN_A, 'unknown-sender');
        await c.bind(f.inbox, TOKEN_B, 'unknown-sender');
        await rejects(() => d.inspect(TOKEN_B, a.receipt.receiptId), 'NotFound');
        await rejects(() => d.reconcile(TOKEN_B, a.receipt.receiptId), 'NotFound');
        assert.equal((await d.step(TOKEN_A, a.receipt.receiptId)).status, 'uncertain');
        assert.equal((await d.reconcile(TOKEN_A, a.receipt.receiptId)).status, 'uncertain');
        const frozen = await plan(c, f.schema, a.receipt.receiptId);
        assert.deepEqual(frozen.submission.scope, ACCOUNT);
        await op.port.accept(frozen, new AbortController().signal);
        await delay(25);
        assert.equal((await d.reconcile(TOKEN_A, a.receipt.receiptId)).status, 'dispatched');
        observed = await d.inspect(TOKEN_A, a.receipt.receiptId);
        assert.equal(observed.attempts, 3);
        assert.equal(observed.history.length, 3);
        assert.equal(observed.operationKey, frozen.submission.operationKey);
        assert.equal(accepts, 3);
        assert.equal(await op.count(), 1);
        const b = await intake(c, f, 'new-account-event', 'unknown-sender');
        assert.equal(
          (await f.inbox.inspect(TOKEN_B, b.receipt.receiptId)).processingState,
          'pending',
        );
        await rejects(() => f.inbox.inspect(TOKEN_B, a.receipt.receiptId), 'NotFound');
      },
    ],
    [
      'dispatch_process_kill_after_external_commit',
      async () => {
        const f = await c.fixture();
        await c.bind(f.inbox, TOKEN_A, 'kill-dispatch-sender');
        const a = await intake(c, f, 'kill-dispatch-event', 'kill-dispatch-sender');
        await upgradeChannelSchemaV2(c.connection(f.schema, true), POLICY);
        const op = await operationFixture(c, f.schema);
        const child = fork(
          fileURLToPath(import.meta.url).replace(
            /pg_dispatch_cases\.js(?![\s\S])/,
            'pg_inbox_cases.js',
          ),
          ['--child-dispatch'],
          {
            env: {
              PATH: process.env.PATH,
              P2_POSTGRES_PORT: process.env.P2_POSTGRES_PORT,
              P2_RUNTIME_PASSWORD: process.env.P2_RUNTIME_PASSWORD,
              P2_CHILD_SCHEMA: f.schema,
              P2_OPERATION_SCHEMA: op.schema,
              P2_DISPATCH_RECEIPT: a.receipt.receiptId,
            },
            stdio: ['ignore', 'ignore', 'ignore', 'ipc'],
          },
        );
        c.children.add(child);
        await new Promise<void>((resolve, reject) => {
          child.once('message', (value: unknown) => {
            if (
              value &&
              typeof value === 'object' &&
              'type' in value &&
              value.type === 'external_committed'
            )
              resolve();
            else reject(new Error('invalid_child'));
          });
          child.once('exit', () => reject(new Error('early_child_exit')));
          child.once('error', reject);
        });
        assert.equal(await op.count(), 1);
        const frozen = await plan(c, f.schema, a.receipt.receiptId);
        const exit = new Promise<NodeJS.Signals | null>((resolve, reject) => {
          child.once('exit', (_code, signal) => resolve(signal));
          child.once('error', reject);
        });
        assert.equal(child.kill('SIGKILL'), true);
        assert.equal(await exit, 'SIGKILL');
        c.children.delete(child);
        c.terminated();
        await delay(550);
        const fresh = dispatcher(c, f, {
          ...standardPorts(op.port),
          cases: {
            async inspect() {
              throw new Error('NO_RECOMPUTE');
            },
          },
          agent: {
            async prepare() {
              throw new Error('NO_RECOMPUTE');
            },
          },
        });
        assert.equal((await fresh.reconcile(TOKEN_A, a.receipt.receiptId)).status, 'dispatched');
        const replay = await intake(c, f, 'kill-dispatch-event', 'kill-dispatch-sender');
        assert.equal(replay.replayed, true);
        assert.deepEqual(replay.receipt, a.receipt);
        const observed = await fresh.inspect(TOKEN_A, a.receipt.receiptId);
        assert.equal(observed.operationKey, frozen.submission.operationKey);
        const external = await op.port.lookup(
          {
            operationKey: frozen.submission.operationKey,
            scope: ACCOUNT,
            payloadDigest: frozen.payloadDigest,
          },
          new AbortController().signal,
        );
        assert.equal(external.status, 'accepted');
        if (external.status === 'accepted')
          assert.equal(observed.externalReceiptId, external.receipt.receiptId);
        assert.equal(observed.state, 'dispatched');
        assert.equal(observed.attempts, 1);
        assert.equal(await op.count(), 1);
      },
    ],
  ];
}
export async function childDispatch(): Promise<void> {
  assert.equal(process.env.P2_MIGRATION_PASSWORD, undefined);
  const schema = process.env.P2_CHILD_SCHEMA!,
    operationSchema = process.env.P2_OPERATION_SCHEMA!,
    receiptId = process.env.P2_DISPATCH_RECEIPT!;
  q(schema);
  q(operationSchema);
  const db: DatabaseSettings = {
    host: '127.0.0.1',
    port: Number(process.env.P2_POSTGRES_PORT),
    database: 'livekit_lab',
    user: 'livekit_lab',
    password: process.env.P2_RUNTIME_PASSWORD!,
    schema,
  };
  const op = operations(db, operationSchema);
  const d = new ChannelDispatcher(
    db,
    createFakeSmsIntegration(SCOPE, Buffer.alloc(32, 0x61)),
    new SeededAccounts(SEEDS),
    standardPorts({
      ...op.port,
      async accept(input, signal) {
        await op.port.accept(input, signal);
        await new Promise<void>((resolve, reject) =>
          process.send!({ type: 'external_committed' }, (error) =>
            error ? reject(error) : resolve(),
          ),
        );
        return await new Promise<never>(() => undefined);
      },
    }),
  );
  await d.step(TOKEN_A, receiptId);
}
export async function cleanupDispatch(c: Context): Promise<boolean> {
  let complete = true;
  for (const release of releases) release();
  releases.clear();
  for (const d of dispatchers)
    try {
      await d.close();
    } catch {
      complete = false;
    }
  dispatchers.clear();
  for (const schema of operationSchemas)
    try {
      await c.sql(c.connection('p2_inbox_' + '0'.repeat(32), true), async (client) => {
        const row = (
          await client.query(
            "SELECT obj_description(oid,'pg_namespace') AS marker,pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname=$1",
            [schema],
          )
        ).rows[0];
        if (!row) return;
        assert.equal(row.marker, MARKER);
        assert.equal(row.owner, 'continuity_migrator');
        await client.query(`DROP SCHEMA ${q(schema)} CASCADE`);
        assert.equal(
          (await client.query('SELECT 1 FROM pg_namespace WHERE nspname=$1', [schema])).rowCount,
          0,
        );
      });
    } catch {
      complete = false;
    }
  operationSchemas.clear();
  return complete;
}
