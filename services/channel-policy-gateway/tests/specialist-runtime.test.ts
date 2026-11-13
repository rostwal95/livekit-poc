/** Actual public SDK server/client loopback composition; no SQL, model, provider or fixture service. */
import { createServer, Server } from 'node:http';
import { connect } from 'node:net';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  FixedPolicySpecialistClient,
  produceFixedPolicyRequest,
} from '@livekit-ecosystem/delegation-specialist/fixed-policy';
import { ScriptedPolicySpecialistRuntime } from '../src/specialist-runtime.js';
import { configuration, evidence, bearer } from './specialist-fixtures.js';
import type { SpecialistConfiguration } from '../src/specialist-config.js';
const owners = new Set<ScriptedPolicySpecialistRuntime>(),
  clients = new Set<FixedPolicySpecialistClient>();
afterEach(async () => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  for (const c of clients) await c.close();
  clients.clear();
  for (const x of owners) await x.close();
  owners.clear();
});
async function reserve() {
  const peer = createServer();
  await new Promise<void>((r, j) => {
    peer.once('error', j);
    peer.listen(0, '127.0.0.1', r);
  });
  const a = peer.address();
  if (!a || typeof a === 'string') throw new Error('fixture');
  return { peer, port: a.port };
}
async function stop(peer: Server) {
  await new Promise<void>((r, j) => peer.close((e) => (e ? j(e) : r())));
}
function runtime(c: SpecialistConfiguration) {
  const x = new ScriptedPolicySpecialistRuntime(c, { bearer });
  owners.add(x);
  return x;
}
let serial = 0;
function request(c: SpecialistConfiguration, facts = 1) {
  serial++;
  return produceFixedPolicyRequest({
    schema_version: 1,
    kind: 'delegation.request',
    capability: 'booking.evaluate_policy',
    input_schema_version: 2,
    scope: { tenant_id: c.scope.tenantId, account_id: c.scope.accountId },
    delegation_id: 'delegation_' + serial,
    case_id: 'case_demo',
    request_revision: 1,
    context_snapshot: {
      policy_version: 'notice_v1',
      policy_source_id: c.evidence[0]!.reference.source_id,
      facts_source_id: c.evidence[facts]!.reference.source_id,
    },
    evidence: [c.evidence[0]!.reference, c.evidence[facts]!.reference],
    deadline_at_ms: Date.now() + 3000,
    result_route: { conversation_id: 'conversation_demo' },
    attempt: { attempt_id: 'attempt_' + serial, number: 1 },
  });
}
describe('scripted specialist actual owner composition', () => {
  it('constructs inertly and prestart close does not create any listener or socket', async () => {
    const listen = vi.spyOn(Server.prototype, 'listen'),
      x = runtime(configuration());
    expect(x.metrics()).toMatchObject({ serverOwners: 0, active: 0 });
    expect(listen).not.toHaveBeenCalled();
    await x.close();
    expect(listen).not.toHaveBeenCalled();
    await expect(x.start()).rejects.toMatchObject({ code: 'closed' });
  });
  it('binds the exact configured port and runs the genuine v2 handler with independent public factual verification', async () => {
    const held = await reserve();
    await stop(held.peer);
    const c = configuration(held.port),
      x = runtime(c),
      endpoint = await x.start();
    expect(endpoint.port).toBe(c.port);
    const client = new FixedPolicySpecialistClient(endpoint, 'Bearer ' + bearer);
    clients.add(client);
    const records = c.evidence.map((e) => ({
      scope: { tenant_id: c.scope.tenantId, account_id: c.scope.accountId },
      reference: e.reference,
      body: Buffer.from(e.bodyBase64, 'base64'),
    }));
    const observed = await client.invokeObserved(request(c), records);
    expect(observed.applicability).toBe('candidate');
    expect(observed.result).toMatchObject({
      eligible: true,
      uncertainty: 'none',
      producer: { producer_id: 'deterministic_notice_v1', model_id: null, model_version: null },
    });
    expect(observed.result.fact_refs[0]!.days_before_arrival).toBe(10);
    expect(x.metrics().evaluated).toBe(1);
    await client.close();
    await x.close();
    expect(x.metrics()).toMatchObject({
      closed: true,
      serverOwners: 0,
      active: 0,
      sockets: 0,
      requests: 0,
    });
  });
  it('dedupes one shared policy while both revision-specific fact sources remain independently usable', async () => {
    const held = await reserve();
    await stop(held.peer);
    const base = configuration(held.port),
      c = {
        ...base,
        evidence: [
          ...base.evidence,
          evidence('facts_notice_r2', {
            schema_version: 1,
            kind: 'booking.notice_facts',
            observations: [{ fact_id: 'notice_days', days_before_arrival: 5 }],
            note: 'New immutable fact source.',
          }),
        ],
      },
      x = runtime(c),
      client = new FixedPolicySpecialistClient(await x.start(), 'Bearer ' + bearer);
    clients.add(client);
    expect((await client.invoke(request(c, 1))).eligible).toBe(true);
    expect((await client.invoke(request(c, 2))).eligible).toBe(false);
    expect(x.metrics().evaluated).toBe(2);
  });
  it('authenticates the configured scope and separate service principal without exposing private data', async () => {
    const held = await reserve();
    await stop(held.peer);
    const c = configuration(held.port),
      x = runtime(c),
      endpoint = await x.start(),
      wrong = new FixedPolicySpecialistClient(endpoint, 'Bearer ' + 'z'.repeat(43)),
      right = new FixedPolicySpecialistClient(endpoint, 'Bearer ' + bearer);
    clients.add(wrong);
    clients.add(right);
    await expect(wrong.invoke(request(c))).rejects.toMatchObject({ code: 'unauthorized' });
    await expect(
      right.invoke(request({ ...c, scope: { ...c.scope, accountId: 'foreign' } })),
    ).rejects.toMatchObject({ code: 'unauthorized' });
    expect(x.metrics().evaluated).toBe(0);
    expect((await right.invoke(request(c))).eligible).toBe(true);
  });
  it('fails a busy configured port without fallback and retains the original listener owner', async () => {
    const held = await reserve(),
      x = runtime(configuration(held.port));
    try {
      await expect(x.start()).rejects.toMatchObject({
        code: 'unavailable',
        message: 'unavailable',
      });
      await x.close();
      expect(held.peer.listening).toBe(true);
      expect(x.metrics()).toMatchObject({ closed: true, sockets: 0, serverOwners: 0 });
    } finally {
      await stop(held.peer);
    }
  });
  it('closes real abandoned partial-header sockets before reporting completion', async () => {
    const held = await reserve();
    await stop(held.peer);
    const x = runtime(configuration(held.port)),
      endpoint = await x.start(),
      socket = connect(endpoint),
      closed = new Promise<void>((r) => socket.once('close', () => r()));
    socket.on('error', () => {});
    try {
      await new Promise<void>((r, j) => {
        socket.once('connect', r);
        socket.once('error', j);
      });
      socket.write('POST / HTTP/1.1\r\n');
      await vi.waitFor(() => expect(x.metrics().sockets).toBe(1));
      await x.close();
      await closed;
      expect(x.metrics()).toMatchObject({ closed: true, sockets: 0, serverOwners: 0 });
    } finally {
      socket.destroy();
    }
  });
  it('retains a late bind through startup/close timeouts and makes progress after actual settlement', async () => {
    const held = await reserve();
    await stop(held.peer);
    vi.useFakeTimers();
    const original = Server.prototype.listen;
    let release: (() => void) | undefined;
    const spy = vi.spyOn(Server.prototype, 'listen').mockImplementation(function (
      this: Server,
      ...args: Parameters<Server['listen']>
    ) {
      release = () => {
        Reflect.apply(original, this, args);
      };
      return this;
    });
    const x = runtime(configuration(held.port)),
      starting = x.start().catch((e) => e);
    await vi.advanceTimersByTimeAsync(1);
    const closing = x.close().catch((e) => e);
    await vi.advanceTimersByTimeAsync(2001);
    expect(await starting).toMatchObject({ code: 'unavailable' });
    expect(await closing).toMatchObject({ code: 'cleanup_incomplete' });
    expect(x.metrics()).toMatchObject({ starting: 1, closed: false, serverOwners: 1 });
    spy.mockRestore();
    vi.useRealTimers();
    release!();
    await vi.waitFor(() => expect(x.metrics().starting).toBe(0));
    await x.close();
    expect(x.metrics()).toMatchObject({ closed: true, serverOwners: 0, sockets: 0 });
  });
});
