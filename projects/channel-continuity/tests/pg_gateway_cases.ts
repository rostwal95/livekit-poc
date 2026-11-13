/** Actual owned gateway processes and sockets, actual PostgreSQL, synthetic adapters. */
import assert from 'node:assert/strict';
import { fork, type ChildProcess } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { request } from 'node:http';
import {
  ChannelGateway,
  type GatewayEndpoint,
} from '@livekit-ecosystem/channel-continuity/gateway';
import { upgradeChannelSchemaV2 } from '@livekit-ecosystem/channel-continuity/migrations';
import {
  createFakeSmsIntegration,
  type SignedFakeSms,
} from '@livekit-ecosystem/channel-continuity/security';
import type { DatabaseSettings } from '@livekit-ecosystem/channel-continuity/postgres';
import { operationFixture, operations, standardPorts, type Context } from './pg_dispatch_cases.js';
const SCOPE = { tenantId: 'tenant-a', provider: 'fake_sms', providerAccountId: 'carrier-a' };
const TOKEN_A = 'synthetic-account-a-' + 'a'.repeat(40),
  TOKEN_B = 'synthetic-account-b-' + 'b'.repeat(40);
const SEEDS = [
  {
    token: TOKEN_A,
    tenantId: 'tenant-a',
    accountId: 'account-a',
    conversationId: 'conversation-a',
    caseId: 'case-a',
  },
  {
    token: TOKEN_B,
    tenantId: 'tenant-a',
    accountId: 'account-b',
    conversationId: 'conversation-b',
    caseId: 'case-b',
  },
];
const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
type Message = Readonly<{
  type: string;
  port?: number;
  active?: number;
  handlers?: number;
  sockets?: number;
  driver?: number;
}>;
function message(child: ChildProcess, type: string): Promise<Message> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error('gateway_message_timeout'));
    }, 7000);
    const cleanup = () => {
      clearTimeout(timer);
      child.off('message', received);
      child.off('exit', exited);
    };
    const exited = () => {
      cleanup();
      reject(new Error('gateway_early_exit'));
    };
    const received = (value: unknown) => {
      if (!value || typeof value !== 'object' || !('type' in value) || value.type !== type) return;
      cleanup();
      resolve(value as Message);
    };
    child.on('message', received);
    child.once('exit', exited);
  });
}
async function exited(
  child: ChildProcess,
): Promise<{ code: number | null; signal: NodeJS.Signals | null }> {
  if (child.exitCode !== null || child.signalCode !== null)
    return { code: child.exitCode, signal: child.signalCode };
  return await new Promise((resolve, reject) => {
    child.once('exit', (code, signal) => resolve({ code, signal }));
    child.once('error', reject);
  });
}
async function start(c: Context, schema: string, operationSchema: string, hold = false) {
  const base = Object.fromEntries(
    ['PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL']
      .filter((key) => process.env[key] !== undefined)
      .map((key) => [key, process.env[key]!]),
  );
  const child = fork(
    fileURLToPath(new URL('./pg_inbox_cases.js', import.meta.url)),
    ['--child-gateway'],
    {
      env: {
        ...base,
        P2_POSTGRES_PORT: process.env.P2_POSTGRES_PORT!,
        P2_RUNTIME_PASSWORD: process.env.P2_RUNTIME_PASSWORD!,
        P2_CHILD_SCHEMA: schema,
        P2_OPERATION_SCHEMA: operationSchema,
        P2_GATEWAY_HOLD_ACK: hold ? '1' : '0',
      },
      stdio: ['ignore', 'ignore', 'ignore', 'ipc'],
      execArgv: [],
    },
  );
  c.children.add(child);
  const ready = await message(child, 'ready');
  assert.ok(ready.port && ready.port > 0);
  return { child, endpoint: { host: '127.0.0.1', port: ready.port } as GatewayEndpoint };
}
async function stop(c: Context, child: ChildProcess) {
  const closed = message(child, 'closed');
  child.send({ type: 'stop' });
  const metrics = await closed;
  assert.equal(metrics.active, 0);
  assert.equal(metrics.handlers, 0);
  assert.equal(metrics.sockets, 0);
  assert.equal(metrics.driver, 0);
  assert.deepEqual(await exited(child), { code: 0, signal: null });
  c.children.delete(child);
}
export async function call(
  endpoint: GatewayEndpoint,
  path: string,
  signed?: SignedFakeSms,
  token?: string,
): Promise<{ status: number; data: Record<string, unknown> }> {
  return await new Promise((resolve, reject) => {
    const req = request(
      {
        host: endpoint.host,
        port: endpoint.port,
        path,
        method: signed ? 'POST' : 'GET',
        headers: {
          Connection: 'close',
          ...(signed
            ? {
                'Content-Type': 'application/json',
                'Content-Length': String(signed.raw.byteLength),
                'X-P2-Timestamp': signed.headers.timestamp,
                'X-P2-Signature': signed.headers.signature,
              }
            : {}),
          ...(token ? { Authorization: 'Bearer ' + token } : {}),
        },
      },
      (res) => {
        const chunks: Buffer[] = [];
        let bytes = 0;
        res.on('data', (chunk: Buffer) => {
          bytes += chunk.length;
          if (bytes > 16384) {
            req.destroy();
            reject(new Error('gateway_response_limit'));
            return;
          }
          chunks.push(chunk);
        });
        res.on('end', () => {
          try {
            resolve({
              status: res.statusCode!,
              data: JSON.parse(Buffer.concat(chunks).toString()) as Record<string, unknown>,
            });
          } catch (error) {
            reject(error);
          }
        });
      },
    );
    req.setTimeout(5000, () => req.destroy(new Error('gateway_request_timeout')));
    req.on('error', reject);
    req.end(signed?.raw);
  });
}
export async function observed(
  endpoint: GatewayEndpoint,
  id: string,
  token = TOKEN_A,
  state = 'dispatched',
) {
  for (let i = 0; i < 150; i++) {
    const value = await call(endpoint, '/receipts/' + id, undefined, token);
    assert.equal(value.status, 200);
    if (value.data.state === state) return value.data;
    await delay(20);
  }
  throw new Error('gateway_progress_timeout');
}
export function gatewayCases(c: Context): ReadonlyArray<readonly [string, () => Promise<void>]> {
  return [
    [
      'gateway_normal_authenticated_http_progress',
      async () => {
        const f = await c.fixture();
        await upgradeChannelSchemaV2(c.connection(f.schema, true));
        await c.bind(f.inbox, TOKEN_A, 'gateway-normal');
        const op = await operationFixture(c, f.schema);
        const running = await start(c, f.schema, op.schema);
        const signed = c.signed('gateway-normal-event', 'gateway-normal');
        const rejected = await call(running.endpoint, '/webhooks/fake-sms', {
          ...signed,
          headers: { ...signed.headers, signature: 'invalid' },
        });
        assert.equal(rejected.status, 401);
        const accepted = await call(running.endpoint, '/webhooks/fake-sms', signed);
        assert.equal(accepted.status, 200);
        assert.equal(accepted.data.replayed, false);
        const receipt = accepted.data.receipt as { receiptId: string };
        const current = await observed(running.endpoint, receipt.receiptId);
        assert.equal(current.state, 'dispatched');
        assert.equal(current.attempts, 1);
        assert.equal(await op.count(), 1);
        assert.equal((await call(running.endpoint, '/receipts/' + receipt.receiptId)).status, 401);
        assert.equal(
          (await call(running.endpoint, '/receipts/' + receipt.receiptId, undefined, TOKEN_B))
            .status,
          404,
        );
        const replay = await call(running.endpoint, '/webhooks/fake-sms', signed);
        assert.equal(replay.data.replayed, true);
        assert.deepEqual(replay.data.receipt, accepted.data.receipt);
        const actual = await f.inbox.inspect(TOKEN_A, receipt.receiptId);
        assert.equal(actual.operationKey, current.operationKey);
        await stop(c, running.child);
      },
    ],
    [
      'gateway_sigkill_after_flushed_ack_recovers_original',
      async () => {
        const f = await c.fixture();
        await upgradeChannelSchemaV2(c.connection(f.schema, true));
        await c.bind(f.inbox, TOKEN_A, 'gateway-kill');
        const op = await operationFixture(c, f.schema);
        const running = await start(c, f.schema, op.schema, true),
          acknowledged = message(running.child, 'acknowledged');
        const signed = c.signed('gateway-kill-event', 'gateway-kill'),
          accepted = await call(running.endpoint, '/webhooks/fake-sms', signed);
        assert.equal(accepted.status, 200);
        await acknowledged;
        const receipt = accepted.data.receipt as { receiptId: string },
          original = await f.inbox.inspect(TOKEN_A, receipt.receiptId);
        assert.equal(original.processingState, 'pending');
        assert.equal(await op.count(), 0);
        await c.sql(c.connection(f.schema, true), async (client) => {
          assert.equal(
            (await client.query(`SELECT count(*)::int AS count FROM "${f.schema}".dispatch_plans`))
              .rows[0]!.count,
            0,
          );
        });
        const dead = exited(running.child);
        assert.equal(running.child.kill('SIGKILL'), true);
        assert.equal((await dead).signal, 'SIGKILL');
        c.children.delete(running.child);
        c.terminated();
        const fresh = await start(c, f.schema, op.schema);
        const recovered = await observed(fresh.endpoint, receipt.receiptId);
        assert.equal(recovered.operationKey, original.operationKey);
        assert.equal(recovered.attempts, 1);
        assert.equal(await op.count(), 1);
        const replay = await call(fresh.endpoint, '/webhooks/fake-sms', signed);
        assert.deepEqual(replay.data.receipt, accepted.data.receipt);
        assert.equal(replay.data.replayed, true);
        await stop(c, fresh.child);
        const again = await start(c, f.schema, op.schema);
        const same = await observed(again.endpoint, receipt.receiptId);
        assert.equal(same.operationKey, recovered.operationKey);
        assert.equal(same.externalReceiptId, recovered.externalReceiptId);
        assert.equal(same.attempts, 1);
        assert.equal(await op.count(), 1);
        await stop(c, again.child);
      },
    ],
    [
      'gateway_persisted_selection_progresses_after_blocked_scope',
      async () => {
        const f = await c.fixture();
        await upgradeChannelSchemaV2(c.connection(f.schema, true));
        await c.bind(f.inbox, TOKEN_A, 'gateway-blocked');
        const blocked = await f.inbox.acceptSms(
          ...(() => {
            const s = c.signed('gateway-blocked-event', 'gateway-blocked');
            return [s.raw, s.headers] as const;
          })(),
        );
        await f.inbox.revokeAssociation(TOKEN_A, 'gateway-blocked');
        await c.bind(f.inbox, TOKEN_A, 'gateway-valid');
        const good = await f.inbox.acceptSms(
          ...(() => {
            const s = c.signed('gateway-valid-event', 'gateway-valid');
            return [s.raw, s.headers] as const;
          })(),
        );
        await c.bind(f.inbox, TOKEN_B, 'gateway-other');
        const other = await f.inbox.acceptSms(
          ...(() => {
            const s = c.signed('gateway-other-event', 'gateway-other');
            return [s.raw, s.headers] as const;
          })(),
        );
        const op = await operationFixture(c, f.schema),
          running = await start(c, f.schema, op.schema);
        assert.equal(
          (await observed(running.endpoint, blocked.receipt.receiptId, TOKEN_A, 'blocked'))
            .attempts,
          0,
        );
        await observed(running.endpoint, good.receipt.receiptId);
        await observed(running.endpoint, other.receipt.receiptId, TOKEN_B);
        assert.equal(await op.count(), 2);
        await stop(c, running.child);
      },
    ],
  ];
}
export async function childGateway(): Promise<void> {
  assert.equal(process.env.P2_MIGRATION_PASSWORD, undefined);
  assert.equal(process.env.NODE_OPTIONS, undefined);
  const schema = process.env.P2_CHILD_SCHEMA!,
    operationSchema = process.env.P2_OPERATION_SCHEMA!;
  assert.match(schema, /^p2_inbox_[a-f0-9]{32}$/);
  assert.match(operationSchema, /^p2_operation_[a-f0-9]{32}$/);
  const database: DatabaseSettings = {
    host: '127.0.0.1',
    port: Number(process.env.P2_POSTGRES_PORT),
    database: 'livekit_lab',
    user: 'livekit_lab',
    password: process.env.P2_RUNTIME_PASSWORD!,
    schema,
  };
  const op = operations(database, operationSchema);
  const gateway = new ChannelGateway({
    database,
    integration: createFakeSmsIntegration(SCOPE, Buffer.alloc(32, 0x61)),
    accounts: SEEDS,
    ports: standardPorts(op.port),
    options: {
      pollMs: 20,
      batchSize: 1,
      cleanupMs: 5000,
      ...(process.env.P2_GATEWAY_HOLD_ACK === '1'
        ? {
            harnessAfterAcknowledgement: async () => {
              await send({ type: 'acknowledged' });
              await new Promise<never>(() => undefined);
            },
          }
        : {}),
    },
  });
  const endpoint = await gateway.listen();
  await send({ type: 'ready', port: endpoint.port });
  process.once('message', (value) => {
    if (!value || typeof value !== 'object' || !('type' in value) || value.type !== 'stop') {
      process.exitCode = 1;
      return;
    }
    void (async () => {
      await gateway.close();
      const metrics = gateway.metrics();
      await send({
        type: 'closed',
        active: metrics.active!,
        handlers: metrics.handlers!,
        sockets: metrics.sockets!,
        driver: metrics.driver!,
      });
      process.disconnect?.();
    })().catch(() => {
      process.exitCode = 1;
      process.disconnect?.();
    });
  });
}
async function send(value: Message): Promise<void> {
  await new Promise<void>((resolve, reject) =>
    process.send!(value, (error) => (error ? reject(error) : resolve())),
  );
}
