/** Actual gateway survives independent model-process death; synthetic model and operation fixture. */
import assert from 'node:assert/strict';
import { mkdtemp, readFile, readdir, rm, unlink, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, isAbsolute } from 'node:path';
import {
  AgentProcess,
  type AgentProcessEvent,
} from '@livekit-ecosystem/channel-continuity/agent-process';
import { ChannelGateway } from '@livekit-ecosystem/channel-continuity/gateway';
import { upgradeChannelSchemaV2 } from '@livekit-ecosystem/channel-continuity/migrations';
import { createFakeSmsIntegration } from '@livekit-ecosystem/channel-continuity/security';
import { operationFixture, standardPorts, type Context } from './pg_dispatch_cases.js';
import { call, observed } from './pg_gateway_cases.js';
const TOKEN = 'synthetic-account-a-' + 'a'.repeat(40);
const SCOPE = { tenantId: 'tenant-a', accountId: 'account-a' };
const agents = new Set<AgentProcess>(),
  gateways = new Set<ChannelGateway>(),
  directories = new Set<string>();
const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
async function wait(predicate: () => Promise<boolean>) {
  const deadline = performance.now() + 5000;
  while (!(await predicate())) {
    if (performance.now() >= deadline) throw new Error('agent_barrier_timeout');
    await delay(10);
  }
}
export function agentCases(c: Context): ReadonlyArray<readonly [string, () => Promise<void>]> {
  return [
    [
      'gateway_agent_sigkill_expired_claim_replay',
      async () => {
        const f = await c.fixture();
        // Test policy only: expire while the first model is genuinely processing, before its1500ms process budget.
        await upgradeChannelSchemaV2(c.connection(f.schema, true), {
          maxActive: 2,
          maxAttempts: 3,
          leaseMs: 750,
          retryDelayMs: 20,
        });
        await c.bind(f.inbox, TOKEN, 'agent-held-sender');
        const op = await operationFixture(c, f.schema),
          directory = await mkdtemp(join(tmpdir(), 'p2-agent-pg-'));
        directories.add(directory);
        const hold = join(directory, 'hold'),
          marker = join(directory, 'held');
        await writeFile(hold, 'held', { flag: 'wx', mode: 0o600 });
        const modulePath = process.env.P2_AGENT_WORKER_MODULE;
        assert.ok(modulePath && isAbsolute(modulePath));
        const events: AgentProcessEvent[] = [];
        const agent = new AgentProcess({
          modulePath,
          allowedScopes: [SCOPE],
          timeoutMs: 1500,
          environment: {
            P2_AGENT_DIAGNOSTICS: directory,
            P2_AGENT_HOLD_FILE: hold,
            P2_AGENT_HELD_MARKER: marker,
          },
          observer: (event) => {
            events.push(event);
          },
        });
        agents.add(agent);
        const ports = standardPorts(op.port),
          gateway = new ChannelGateway({
            database: c.connection(f.schema),
            integration: createFakeSmsIntegration(
              { tenantId: 'tenant-a', provider: 'fake_sms', providerAccountId: 'carrier-a' },
              Buffer.alloc(32, 0x61),
            ),
            accounts: [
              { token: TOKEN, ...SCOPE, conversationId: 'conversation-a', caseId: 'case-a' },
            ],
            ports: { ...ports, agent: agent.port },
            options: { observer: () => undefined },
          });
        gateways.add(gateway);
        const endpoint = await gateway.listen(),
          signed = c.signed('agent-kill-event', 'agent-held-sender');
        const accepted = await call(endpoint, '/webhooks/fake-sms', signed);
        assert.equal(accepted.status, 200);
        const receipt = accepted.data.receipt as { receiptId: string },
          original = await f.inbox.inspect(TOKEN, receipt.receiptId);
        await wait(async () => existsSync(marker));
        const pid = Number(await readFile(marker, 'utf8'));
        assert.equal(events.find((event) => event.event === 'started')?.pid, pid);
        assert.ok(pid > 1);
        assert.equal(agent.metrics().active, 1);
        assert.equal((await call(endpoint, '/health')).status, 200);
        await wait(
          async () =>
            await c.sql(c.connection(f.schema), async (client) => {
              const result = await client.query(
                `SELECT claim_until<=clock_timestamp() AS expired FROM "${f.schema}".processing_intents WHERE receipt_id=$1`,
                [receipt.receiptId],
              );
              return result.rows[0]?.expired === true;
            }),
        );
        await c.sql(c.connection(f.schema), async (client) => {
          assert.equal(
            (await client.query(`SELECT count(*)::int AS count FROM "${f.schema}".dispatch_plans`))
              .rows[0]!.count,
            0,
          );
        });
        assert.equal(await op.count(), 0);
        // The hold selector is trusted fixture setup, never a field in accepted input.
        await unlink(hold);
        process.kill(pid, 'SIGKILL');
        await wait(async () =>
          events.some(
            (event) => event.event === 'settled' && event.pid === pid && event.signal === 'SIGKILL',
          ),
        );
        c.terminated();
        const recovered = await observed(endpoint, receipt.receiptId, TOKEN);
        assert.equal(recovered.operationKey, original.operationKey);
        assert.equal(recovered.attempts, 2);
        assert.equal(recovered.possibleExternal, true);
        assert.equal(await op.count(), 1);
        const replay = await call(endpoint, '/webhooks/fake-sms', signed);
        assert.equal(replay.data.replayed, true);
        assert.deepEqual(replay.data.receipt, accepted.data.receipt);
        const current = await f.inbox.inspect(TOKEN, receipt.receiptId);
        assert.deepEqual(current.receipt, original.receipt);
        assert.deepEqual(current.event, original.event);
        assert.equal(current.operationKey, original.operationKey);
        const models = await Promise.all(
          (await readdir(directory))
            .filter((name) => /^model-[0-9]+\.json$/.test(name))
            .map(
              async (name) =>
                JSON.parse(await readFile(join(directory, name), 'utf8')) as Record<
                  string,
                  unknown
                >,
            ),
        );
        assert.equal(models.length, 2);
        assert.notEqual(models[0]!.pid, models[1]!.pid);
        for (const model of models) {
          assert.deepEqual(model.scope, SCOPE);
          assert.equal(model.caseId, 'case-a');
          assert.equal(model.caseRevision, '1');
          assert.equal(model.operationKey, original.operationKey);
          assert.equal(model.receiptId, receipt.receiptId);
          assert.equal(model.inputDigest, models[0]!.inputDigest);
        }
        const history = recovered.history as Array<{ epoch: string; disposition: string }>;
        assert.equal(history.length, 2);
        assert.notEqual(history[0]!.epoch, history[1]!.epoch);
        assert.equal(history[1]!.disposition, 'accepted');
        const before = agent.metrics().started;
        await delay(150);
        assert.equal(agent.metrics().started, before);
        assert.equal(await op.count(), 1);
        await gateway.close();
        await agent.close();
        assert.equal(agent.metrics().active, 0);
        assert.equal(gateway.metrics().driver, 0);
        assert.equal(gateway.metrics().sockets, 0);
      },
    ],
  ];
}
export async function cleanupAgents(): Promise<boolean> {
  let complete = true;
  for (const gateway of gateways) {
    try {
      await gateway.close();
    } catch {
      complete = false;
    }
  }
  gateways.clear();
  for (const agent of agents) {
    try {
      await agent.close();
      if (agent.metrics().active !== 0) complete = false;
    } catch {
      complete = false;
    }
  }
  agents.clear();
  if (complete) {
    for (const directory of directories) await rm(directory, { recursive: true, force: true });
    directories.clear();
  }
  return complete;
}
