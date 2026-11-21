/** Real public operation client + actual local HTTP. P2 source/P1 authority ports are explicit fakes. */
import { createHash, randomUUID } from 'node:crypto';
import { createServer } from 'node:http';
import type { Socket } from 'node:net';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ExternalOperationClient } from '../src/external-operation-client.js';
import type {
  PreparedDispatch,
  OperationLookup,
} from '@livekit-ecosystem/channel-continuity/dispatch';
import { ChannelPolicyReadHttp } from '../src/read-http.js';
import { ChannelPolicyOperationBridge } from '../src/operation-bridge.js';
import type { DiscoveryPage } from '../src/source-reader.js';
import { configuration, credentials, deferred } from './runtime-fixtures.js';
type Source = 'native' | 'sms';
const cleanups: (() => Promise<void>)[] = [];
afterEach(async () => {
  vi.restoreAllMocks();
  for (const close of cleanups.splice(0).reverse()) await close();
});
function plan(source: Source): PreparedDispatch {
  const c = configuration(),
    id = randomUUID();
  const submission = {
    schemaVersion: 1 as const,
    kind: 'investigation' as const,
    operationKey: randomUUID(),
    scope: c.route.scope,
    caseId: c.route.caseId,
    caseRevision: '1',
    conversationId: c.route.conversationId,
    message: {
      receiptId: id,
      eventId: id,
      messageId: id,
      senderId: source === 'native' ? randomUUID() : 'origin_sms_sender',
      body: 'Read café 🧭 only.',
    },
  };
  const canonicalPayload = JSON.stringify(submission);
  return {
    submission,
    canonicalPayload,
    payloadDigest: createHash('sha256').update(canonicalPayload).digest('hex'),
  };
}
function query(p: PreparedDispatch): OperationLookup {
  return {
    operationKey: p.submission.operationKey,
    scope: p.submission.scope,
    payloadDigest: p.payloadDigest,
  };
}
async function origin() {
  const state = {
    calls: [] as { path: string; token: string; body: Record<string, unknown> }[],
    receipts: new Map<string, unknown>(),
    wait: undefined as Promise<void> | undefined,
    fail: false,
  };
  const sockets = new Set<Socket>(),
    tasks = new Set<Promise<void>>();
  const server = createServer((req, res) => {
    const task = (async () => {
      try {
        const chunks: Buffer[] = [];
        for await (const chunk of req) chunks.push(Buffer.from(chunk as Buffer));
        const body = JSON.parse(Buffer.concat(chunks).toString()) as Record<string, unknown>;
        state.calls.push({ path: req.url ?? '', token: String(req.headers.authorization), body });
        if (state.wait) await state.wait;
        let result: unknown;
        if (req.url === '/v1/investigations/accept') {
          const value = JSON.parse(String(body.canonicalPayload)) as PreparedDispatch['submission'];
          const receipt = {
            operationKey: value.operationKey,
            scope: value.scope,
            payloadDigest: body.payloadDigest,
            receiptId: randomUUID(),
          };
          state.receipts.set(value.operationKey, receipt);
          result = { schemaVersion: 1, status: 'known', receipt };
        } else {
          const receipt = state.receipts.get(String(body.operationKey));
          result = {
            schemaVersion: 1,
            status: 'known',
            observation: receipt ? { status: 'accepted', receipt } : { status: 'absent' },
          };
        }
        const raw = Buffer.from(JSON.stringify(result));
        res.writeHead(state.fail ? 503 : 200, {
          'content-type': 'application/json',
          'content-length': raw.length,
          'cache-control': 'no-store',
          connection: 'close',
        });
        res.end(raw);
      } catch {
        res.destroy();
      }
    })();
    tasks.add(task);
    void task.finally(() => tasks.delete(task));
  });
  server.on('connection', (s) => {
    sockets.add(s);
    s.on('error', () => {});
    s.once('close', () => sockets.delete(s));
  });
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', () => r()));
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('TEST_ADDRESS');
  return {
    state,
    port: address.port,
    async close() {
      for (const socket of sockets) socket.destroy();
      await Promise.allSettled([...tasks]);
      await new Promise<void>((r, reject) => server.close((e) => (e ? reject(e) : r())));
    },
  };
}
async function fixture(timeoutMs = 1000) {
  const c = configuration(),
    k = credentials(),
    plans = new Map<string, { source: Source; plan: PreparedDispatch }>(),
    sourceCalls: string[] = [];
  const state = {
    preparedHold: undefined as Promise<void> | undefined,
    discoveryHold: undefined as Promise<void> | undefined,
    missing: false,
    overflow: false,
    wrongProfile: false,
    duplicateReceipt: false,
  };
  const worker = new ChannelPolicyReadHttp(
    {
      async discover() {
        sourceCalls.push('discovery');
        if (state.discoveryHold) await state.discoveryHold;
        const items = [...plans.values()].map(({ source, plan }, n) => ({
          receiptId: plan.submission.message.receiptId,
          operationKey: plan.submission.operationKey,
          acceptanceSequence: String(n + 1),
          sourceBindingId: source,
          state: 'pending' as const,
          possibleExternal: false,
          externalReceiptId: null,
        }));
        if (state.duplicateReceipt && items.length > 1) items[1]!.receiptId = items[0]!.receiptId;
        return {
          schemaVersion: 1,
          kind: 'channel.policy_discovery',
          profileId: state.wrongProfile ? randomUUID() : c.route.profileId,
          scope: c.route.scope,
          caseId: c.route.caseId,
          conversationId: c.route.conversationId,
          readCompletedAt: '2026-11-13T00:00:00.000Z',
          items,
          overflow: state.overflow,
          nextCursor: null,
        } satisfies DiscoveryPage;
      },
      async prepared(id, source) {
        sourceCalls.push('prepared:' + source);
        if (state.preparedHold) await state.preparedHold;
        const found = plans.get(id);
        if (state.missing || !found || found.source !== source) return null;
        return Buffer.from(
          JSON.stringify({
            schemaVersion: 1,
            canonicalPayload: found.plan.canonicalPayload,
            payloadDigest: found.plan.payloadDigest,
          }),
        );
      },
    },
    k.workerBearer,
    40,
  );
  const endpoint = await worker.start(),
    remote = await origin();
  const bridge = new ChannelPolicyOperationBridge({
    profileId: c.route.profileId,
    scope: c.route.scope,
    caseId: c.route.caseId,
    conversationId: c.route.conversationId,
    worker: { endpoint, bearer: k.workerBearer },
    origins: {
      native: { endpoint: { host: '127.0.0.1', port: remote.port }, bearer: k.nativeOriginBearer },
      sms: { endpoint: { host: '127.0.0.1', port: remote.port }, bearer: k.smsOriginBearer },
    },
    timeoutMs,
    cleanupMs: 40,
  });
  const releases: (() => void)[] = [];
  cleanups.push(async () => {
    for (const release of releases) release();
    await bridge.close();
    await worker.close();
    await remote.close();
  });
  return {
    bridge,
    worker,
    state,
    remote,
    sourceCalls,
    releases,
    add(source: Source) {
      const p = plan(source);
      plans.set(p.submission.message.receiptId, { source, plan: p });
      return p;
    },
  };
}
describe('source-attested fresh operation bridge', () => {
  it('lets a slow committed accept finish within the bridge budget rather than a 2 s client cap', async () => {
    const x = await fixture(3500);
    const p = x.add('sms');
    x.remote.state.wait = new Promise<void>((resolve) => setTimeout(resolve, 2300));
    const receipt = await x.bridge.sms.accept(p, new AbortController().signal);
    expect(receipt).toMatchObject({ operationKey: p.submission.operationKey });
    expect(x.remote.state.receipts.has(p.submission.operationKey)).toBe(true);
  }, 10000);
  it('derives distinct original native A/B and SMS senders without fake native metadata', async () => {
    const x = await fixture();
    expect(Object.getOwnPropertyDescriptor(x.bridge, 'native')?.writable).toBe(false);
    expect(Object.isFrozen(x.bridge.sms)).toBe(true);
    for (const source of ['native', 'sms', 'native'] as const) {
      const p = x.add(source);
      expect(await x.bridge[source].lookup(query(p), new AbortController().signal)).toEqual({
        status: 'absent',
      });
      const receipt = await x.bridge[source].accept(p, new AbortController().signal);
      expect(receipt).toMatchObject(query(p));
      expect(await x.bridge[source].lookup(query(p), new AbortController().signal)).toMatchObject({
        status: 'accepted',
        receipt,
      });
      const sent = x.remote.state.calls.find(
        (c) => c.path.endsWith('/accept') && String(c.body.canonicalPayload) === p.canonicalPayload,
      );
      expect(sent?.token).toBe(
        'Bearer ' +
          (source === 'native' ? credentials().nativeOriginBearer : credentials().smsOriginBearer),
      );
      expect(sent?.body).toEqual({
        schemaVersion: 1,
        canonicalPayload: p.canonicalPayload,
        payloadDigest: p.payloadDigest,
      });
    }
    await x.bridge.close();
    expect(x.bridge.metrics()).toMatchObject({ active: 0, sourceSockets: 0, operationCalls: 0 });
  });
  it('rejects wrong scope, changed body/digest and closed accessors before any I/O', async () => {
    const x = await fixture(),
      p = x.add('native'),
      signal = new AbortController().signal;
    await expect(
      x.bridge.native.lookup(
        { ...query(p), scope: { ...p.submission.scope, accountId: 'foreign' } },
        signal,
      ),
    ).rejects.toMatchObject({ code: 'AccessDenied' });
    await expect(
      x.bridge.native.accept({ ...p, payloadDigest: '0'.repeat(64) }, signal),
    ).rejects.toMatchObject({ code: 'OperationConflict' });
    const getter = vi.fn(() => {
        throw new Error('PRIVATE_GETTER');
      }),
      bad = { ...p };
    Object.defineProperty(bad, 'submission', { get: getter, enumerable: true });
    await expect(x.bridge.native.accept(bad, signal)).rejects.toMatchObject({
      code: 'OperationConflict',
    });
    expect(getter).not.toHaveBeenCalled();
    expect(x.sourceCalls).toEqual([]);
    expect(x.remote.state.calls).toEqual([]);
  });
  it('attests correct fixed role before constructing a sender-bound remote call', async () => {
    const x = await fixture(),
      p = x.add('native');
    await expect(x.bridge.sms.lookup(query(p), new AbortController().signal)).rejects.toMatchObject(
      { code: 'AccessDenied' },
    );
    await expect(x.bridge.sms.accept(p, new AbortController().signal)).rejects.toBeDefined();
    await expect(
      x.bridge.sms.accept(
        {
          ...p,
          submission: {
            ...p.submission,
            message: { ...p.submission.message, senderId: 'signed_sender' },
          },
        },
        new AbortController().signal,
      ),
    ).rejects.toBeDefined();
    expect(x.remote.state.calls).toEqual([]);
  });
  it.each(['missing', 'overflow', 'wrongProfile'] as const)(
    'never manufactures P1 absence for %s source attestation',
    async (flag) => {
      const x = await fixture(),
        p = x.add('native');
      x.state[flag] = true;
      await expect(
        x.bridge.native.lookup(query(p), new AbortController().signal),
      ).rejects.toBeDefined();
      expect(x.remote.state.calls).toEqual([]);
    },
  );
  it('returns remote accept ambiguity after possible I/O and never retries or creates a replacement operation', async () => {
    const x = await fixture(),
      p = x.add('native');
    x.remote.state.fail = true;
    await expect(x.bridge.native.accept(p, new AbortController().signal)).rejects.toMatchObject({
      code: 'AcknowledgementUnknown',
    });
    expect(x.remote.state.calls).toHaveLength(1);
    expect(x.remote.state.calls[0]?.body.canonicalPayload).toBe(p.canonicalPayload);
    expect(x.bridge.metrics().unknown).toBe(1);
  });
  it('shares exactly two actual call slots and preserves known receipts through held client close', async () => {
    const x = await fixture(),
      a = x.add('native'),
      b = x.add('sms'),
      held = deferred();
    x.releases.push(() => held.resolve());
    const original = ExternalOperationClient.prototype.close;
    const close = vi
      .spyOn(ExternalOperationClient.prototype, 'close')
      .mockImplementation(async function (this: ExternalOperationClient) {
        await original.call(this);
        await held.promise;
      });
    const receiptA = await x.bridge.native.accept(a, new AbortController().signal),
      receiptB = await x.bridge.sms.accept(b, new AbortController().signal);
    expect(receiptA.receiptId).not.toBe(receiptB.receiptId);
    await vi.waitFor(() => expect(close).toHaveBeenCalledTimes(2));
    expect(x.bridge.metrics().active).toBe(2);
    await expect(
      x.bridge.native.lookup(query(a), new AbortController().signal),
    ).rejects.toMatchObject({ code: 'Overloaded' });
    await expect(x.bridge.close()).rejects.toMatchObject({ code: 'CleanupIncomplete' });
    expect(x.bridge.metrics().active).toBe(2);
    held.resolve();
    await vi.waitFor(() => expect(x.bridge.metrics().active).toBe(0));
    await x.bridge.close();
    expect(x.remote.state.calls.filter((c) => c.path.endsWith('/accept'))).toHaveLength(2);
  });
  it('retains failed client close for useful retry without losing a known receipt or repeating business', async () => {
    const x = await fixture(),
      p = x.add('native'),
      original = ExternalOperationClient.prototype.close;
    const close = vi
      .spyOn(ExternalOperationClient.prototype, 'close')
      .mockRejectedValue(new Error('PRIVATE_CLOSE'));
    expect(await x.bridge.native.accept(p, new AbortController().signal)).toMatchObject(query(p));
    await vi.waitFor(() => expect(x.bridge.metrics().active).toBe(1));
    await expect(x.bridge.close()).rejects.toMatchObject({ code: 'CleanupIncomplete' });
    close.mockImplementation(original);
    await x.bridge.close();
    expect(x.bridge.metrics().active).toBe(0);
    expect(x.remote.state.calls).toHaveLength(1);
  });
  it('stops the next stage after source deadline and distinguishes borrowed server work from its actual client sockets', async () => {
    const x = await fixture(30),
      p = x.add('native'),
      held = deferred();
    x.releases.push(() => held.resolve());
    x.state.preparedHold = held.promise;
    const observed = x.bridge.native.accept(p, new AbortController().signal).catch((e) => e);
    await vi.waitFor(() => expect(x.sourceCalls).toContain('prepared:native'));
    expect(await observed).toMatchObject({ code: 'DispatchUnavailable' });
    await x.bridge.close();
    expect(x.bridge.metrics()).toMatchObject({ active: 0, sourceSockets: 0 });
    expect(x.worker.metrics().handlers).toBe(1);
    expect(x.remote.state.calls).toEqual([]);
    held.resolve();
    await vi.waitFor(() => expect(x.worker.metrics().handlers).toBe(0));
    expect(x.remote.state.calls).toEqual([]);
  });
  it('rejects a caller abort before I/O and preserves uncertainty once accept may have started', async () => {
    const x = await fixture(),
      p = x.add('native'),
      controller = new AbortController();
    controller.abort();
    await expect(x.bridge.native.accept(p, controller.signal)).rejects.toMatchObject({
      code: 'DispatchUnavailable',
    });
    expect(x.sourceCalls).toEqual([]);
    const held = deferred();
    x.releases.push(() => held.resolve());
    x.remote.state.wait = held.promise;
    const active = new AbortController(),
      observed = x.bridge.native.accept(p, active.signal).catch((e) => e);
    await vi.waitFor(() => expect(x.remote.state.calls).toHaveLength(1));
    active.abort();
    expect(await observed).toMatchObject({ code: 'AcknowledgementUnknown' });
    await x.bridge.close();
    expect(x.bridge.metrics()).toMatchObject({
      active: 0,
      sourceSockets: 0,
      operationCalls: 0,
      unknown: 1,
    });
    held.resolve();
  });
  it('recovers an ambiguous committed operation by lookup without another accept', async () => {
    const x = await fixture(),
      p = x.add('native'),
      held = deferred();
    x.releases.push(() => held.resolve());
    x.remote.state.wait = held.promise;
    const controller = new AbortController();
    const observed = x.bridge.native.accept(p, controller.signal).catch((error) => error);
    await vi.waitFor(() => expect(x.remote.state.calls).toHaveLength(1));
    controller.abort();
    expect(await observed).toMatchObject({ code: 'AcknowledgementUnknown' });
    held.resolve();
    x.remote.state.wait = undefined;
    await vi.waitFor(() =>
      expect(x.remote.state.receipts.has(p.submission.operationKey)).toBe(true),
    );
    await vi.waitFor(() => expect(x.bridge.metrics().active).toBe(0));
    expect(await x.bridge.native.lookup(query(p), new AbortController().signal)).toMatchObject({
      status: 'accepted',
      receipt: x.remote.state.receipts.get(p.submission.operationKey),
    });
    expect(x.remote.state.calls.filter((call) => call.path.endsWith('/accept'))).toHaveLength(1);
  });
  it('rejects duplicate durable source identities and makes progress after the source is repaired', async () => {
    const x = await fixture(),
      first = x.add('native');
    x.add('sms');
    x.state.duplicateReceipt = true;
    await expect(
      x.bridge.native.lookup(query(first), new AbortController().signal),
    ).rejects.toMatchObject({ code: 'OperationConflict' });
    expect(x.remote.state.calls).toEqual([]);
    x.state.duplicateReceipt = false;
    expect(await x.bridge.native.lookup(query(first), new AbortController().signal)).toEqual({
      status: 'absent',
    });
    expect(x.remote.state.calls).toHaveLength(1);
  });
});
