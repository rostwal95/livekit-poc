import { describe, expect, it } from 'vitest';
import { createHash, randomUUID } from 'node:crypto';
import { request, createServer } from 'node:http';
import {
  ExternalHttpServer,
  type ExternalLedgerPort,
} from '../examples/standalone/external-http.js';
import {
  parseConfig,
  parseCredentials,
  CloseObservation,
  type ExternalCredentials,
} from '../examples/standalone/config.js';
import { FakeSmsSendClient } from '@livekit-ecosystem/channel-continuity/fake-sms-send';
import { IdempotentFakeSmsClient } from '@livekit-ecosystem/channel-continuity/idempotent-fake-sms';
import type { CarrierResult, SendRequest } from '@livekit-ecosystem/channel-continuity/outbox';
import type { ProviderOperation } from '@livekit-ecosystem/channel-continuity/idempotent-fake-sms';
const sha = (s: string) => createHash('sha256').update(s).digest('hex');
const config = () =>
  parseConfig({
    schemaVersion: 1,
    profileId: '11111111-1111-4111-8111-111111111111',
    postgres: { host: '127.0.0.1', port: 5432, database: 'livekit_lab' },
    schemas: {
      inbox: 'p2_inbox_' + 'a'.repeat(32),
      case: 'p2_case_' + 'a'.repeat(32),
      external: 'p2_demo_' + 'a'.repeat(32),
    },
    bindings: [
      {
        alias: 'primary',
        providerScope: { tenantId: 't', provider: 'fake_sms', providerAccountId: 'carrier' },
        accountScope: { tenantId: 't', accountId: 'a' },
        caseId: 'case',
        conversationId: 'conversation',
        senderId: 'sender',
        initialCase: {
          revision: '0',
          request: {
            schemaVersion: 1,
            kind: 'booking_investigation',
            bookingReference: 'DEMO-1',
            newCheckIn: '2030-01-01',
            investigationConsent: true,
          },
        },
      },
    ],
    endpoints: { gateway: 12001, external: 12002 },
    limits: { maxInbox: 64, externalReceipts: 16 },
  });
const external = () =>
  parseCredentials(
    {
      schemaVersion: 1,
      role: 'external',
      profileId: config().profileId,
      postgresPassword: 'p'.repeat(40),
      bearers: [
        {
          alias: 'primary',
          operation: 'd'.repeat(43),
          ordinary: 'e'.repeat(43),
          idempotent: 'f'.repeat(43),
        },
      ],
    },
    config(),
  ) as ExternalCredentials;
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
function fixture() {
  const calls: SendRequest[] = [],
    operations = new Map<string, string>();
  let closed = 0;
  let ordinary: ExternalLedgerPort['ordinarySend'] = async (input) => {
    calls.push(input);
    return {
      schemaVersion: 1,
      attemptId: input.attemptId,
      requestDigest: sha(JSON.stringify(input)),
      status: 'accepted_by_provider',
      providerMessageId: randomUUID(),
    };
  };
  const port: ExternalLedgerPort = {
    async preflight() {},
    async close() {
      closed++;
    },
    async accept(input) {
      return {
        operationKey: input.submission.operationKey,
        scope: input.submission.scope,
        payloadDigest: input.payloadDigest,
        receiptId: randomUUID(),
      };
    },
    async lookup() {
      return { status: 'absent' };
    },
    ordinarySend(input) {
      return ordinary(input);
    },
    async idempotentSend(op, digest, attemptId, requestDigest) {
      const key = op.providerOperationKey + ':' + digest;
      if (!operations.has(key)) operations.set(key, randomUUID());
      return {
        schemaVersion: 1,
        attemptId,
        requestDigest,
        status: 'accepted_by_provider',
        providerMessageId: operations.get(key)!,
      };
    },
    async idempotentLookup(scope, key, dg) {
      const id = operations.get(key + ':' + dg);
      return {
        schemaVersion: 1,
        providerScope: scope,
        providerOperationKey: key,
        operationDigest: dg,
        state: id ? 'accepted_by_provider' : 'absent',
        providerMessageId: id ?? null,
      };
    },
  };
  return {
    port,
    calls,
    operations,
    closed: () => closed,
    setOrdinary: (fn: ExternalLedgerPort['ordinarySend']) => {
      ordinary = fn;
    },
  };
}
function send(): SendRequest {
  // Deliberately different insertion order: public clients must emit their own canonical request.
  return {
    body: 'bounded fixture reply',
    routeVersion: '1',
    associationVersion: '1',
    senderId: 'sender',
    responseId: 'response',
    conversationId: 'conversation',
    caseId: 'case',
    scope: { tenantId: 't', accountId: 'a' },
    providerScope: { tenantId: 't', provider: 'fake_sms', providerAccountId: 'carrier' },
    providerOperationKey: randomUUID(),
    attemptId: randomUUID(),
    outboundId: randomUUID(),
    schemaVersion: 1,
  };
}
async function post(
  port: number,
  token: string,
  path: string,
  body: unknown,
  host = '127.0.0.1:' + port,
) {
  const data = Buffer.from(JSON.stringify(body));
  return new Promise<{ status: number; body: string }>((resolve, reject) => {
    const req = request(
      {
        host: '127.0.0.1',
        port,
        path,
        method: 'POST',
        agent: false,
        headers: {
          host,
          authorization: 'Bearer ' + token,
          connection: 'close',
          'content-type': 'application/json',
          'content-length': data.length,
        },
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on('data', (c: Buffer) => chunks.push(c));
        res.on('error', reject);
        res.on('end', () =>
          resolve({ status: res.statusCode!, body: Buffer.concat(chunks).toString('utf8') }),
        );
      },
    );
    req.on('error', reject);
    req.setTimeout(2000, () => req.destroy(new Error('owned test deadline')));
    req.end(data);
  });
}
describe('actual public carrier clients and standalone HTTP', () => {
  it('ordinary equal physical calls remain distinct, with public canonical request digests', async () => {
    const f = fixture(),
      server = new ExternalHttpServer(config(), external(), f.port);
    const endpoint = await server.start(0),
      client = new FakeSmsSendClient(
        endpoint,
        'Bearer ' + 'e'.repeat(43),
        config().bindings[0]!.providerScope,
      );
    try {
      const input = send(),
        a = await client.send(input, new AbortController().signal),
        b = await client.send(input, new AbortController().signal);
      expect(f.calls).toHaveLength(2);
      expect(a).toMatchObject({ status: 'accepted_by_provider', attemptId: input.attemptId });
      expect(a.requestDigest).toBe(sha(JSON.stringify(f.calls[0])));
      expect(b.requestDigest).toBe(a.requestDigest);
      expect(
        a.status === 'accepted_by_provider' &&
          b.status === 'accepted_by_provider' &&
          a.providerMessageId,
      ).not.toBe(b.status === 'accepted_by_provider' && b.providerMessageId);
    } finally {
      await client.close();
      await server.close();
    }
    expect(f.closed()).toBe(1);
    expect(server.metrics()).toMatchObject({ active: 0, sockets: 0 });
  });
  it('idempotent public send+lookup correlate original operation and each actual attempt', async () => {
    const f = fixture(),
      server = new ExternalHttpServer(config(), external(), f.port);
    const endpoint = await server.start(0),
      client = new IdempotentFakeSmsClient(
        endpoint,
        'Bearer ' + 'f'.repeat(43),
        config().bindings[0]!.providerScope,
      );
    try {
      const input = send(),
        a = await client.send(input, new AbortController().signal),
        b = await client.send({ ...input, attemptId: randomUUID() }, new AbortController().signal);
      expect(f.operations.size).toBe(1);
      expect(a.status === 'accepted_by_provider' && a.providerMessageId).toBe(
        b.status === 'accepted_by_provider' && b.providerMessageId,
      );
      const operation: ProviderOperation = {
        schemaVersion: 1,
        capability: 'idempotent_fake_sms_v1',
        providerScope: input.providerScope,
        scope: input.scope,
        caseId: input.caseId,
        conversationId: input.conversationId,
        outboundId: input.outboundId,
        responseId: input.responseId,
        providerOperationKey: input.providerOperationKey,
        senderId: input.senderId,
        body: input.body,
      };
      const observation = await client.lookup(operation, new AbortController().signal);
      expect(observation).toMatchObject({
        state: 'accepted_by_provider',
        providerOperationKey: input.providerOperationKey,
        operationDigest: sha(JSON.stringify(operation)),
      });
    } finally {
      await client.close();
      await server.close();
    }
  });
  it('rejects wrong role/host/foreign body and malformed adapter output without leaking data, then progresses', async () => {
    const f = fixture();
    let malformed = true;
    f.setOrdinary(async (input) =>
      malformed
        ? ({ sentinel: 'DO_NOT_LEAK_PRIVATE_TEXT' } as unknown as CarrierResult)
        : {
            schemaVersion: 1,
            attemptId: input.attemptId,
            requestDigest: sha(JSON.stringify(input)),
            status: 'accepted_by_provider',
            providerMessageId: randomUUID(),
          },
    );
    const server = new ExternalHttpServer(config(), external(), f.port),
      endpoint = await server.start(0);
    try {
      expect((await post(endpoint.port, 'f'.repeat(43), '/v1/sms/send', send())).status).toBe(403);
      expect(
        (await post(endpoint.port, 'e'.repeat(43), '/v1/sms/send', send(), '127.0.0.1:1')).status,
      ).toBe(400);
      expect(
        (
          await post(endpoint.port, 'e'.repeat(43), '/v1/sms/send', {
            ...send(),
            caseId: 'foreign',
          })
        ).status,
      ).toBe(403);
      const rejected = await post(endpoint.port, 'e'.repeat(43), '/v1/sms/send', send());
      expect(rejected.status).not.toBe(200);
      expect(rejected.body).not.toContain('DO_NOT_LEAK');
      malformed = false;
      expect((await post(endpoint.port, 'e'.repeat(43), '/v1/sms/send', send())).status).toBe(200);
    } finally {
      await server.close();
    }
  });
  it('preserves the immutable public carrier header whitelist and later valid progress', async () => {
    let noStore = true,
      calls = 0;
    const peer = createServer({ maxHeaderSize: 4096 }, (req, res) => {
      const chunks: Buffer[] = [];
      let size = 0;
      req.on('data', (c: Buffer) => {
        size += c.length;
        if (size > 16384) req.destroy();
        else chunks.push(c);
      });
      req.on('end', () => {
        calls++;
        const wire = Buffer.concat(chunks),
          input = JSON.parse(wire.toString()) as SendRequest;
        const payload = Buffer.from(
          JSON.stringify({
            schemaVersion: 1,
            status: 'known',
            result: {
              schemaVersion: 1,
              attemptId: input.attemptId,
              requestDigest: sha(wire.toString()),
              status: 'accepted_by_provider',
              providerMessageId: randomUUID(),
            },
          }),
        );
        res.writeHead(200, {
          'content-type': 'application/json',
          'content-length': payload.length,
          connection: 'close',
          ...(noStore ? { 'cache-control': 'no-store' } : {}),
        });
        res.end(payload);
      });
    });
    peer.maxConnections = 2;
    peer.setTimeout(1000, (s) => s.destroy());
    let client: FakeSmsSendClient | undefined;
    try {
      await new Promise<void>((r) => peer.listen(0, '127.0.0.1', r));
      const address = peer.address();
      if (!address || typeof address === 'string') throw new Error('missing owned listener');
      client = new FakeSmsSendClient(
        { host: '127.0.0.1', port: address.port },
        'Bearer ' + 'e'.repeat(43),
        config().bindings[0]!.providerScope,
      );
      await expect(client.send(send(), new AbortController().signal)).rejects.toMatchObject({
        code: 'OutcomeUnknown',
      });
      noStore = false;
      await expect(client.send(send(), new AbortController().signal)).resolves.toMatchObject({
        status: 'accepted_by_provider',
      });
      expect(calls).toBe(2);
    } finally {
      await client?.close();
      await new Promise<void>((r, bad) => peer.close((e) => (e ? bad(e) : r())));
    }
  });
  it('retains actual held ledger work after client abort and withholds dependent close', async () => {
    const f = fixture(),
      entered = deferred<void>(),
      release = deferred<void>();
    f.setOrdinary(async (input) => {
      entered.resolve();
      await release.promise;
      return {
        schemaVersion: 1,
        attemptId: input.attemptId,
        requestDigest: sha(JSON.stringify(input)),
        status: 'accepted_by_provider',
        providerMessageId: randomUUID(),
      };
    });
    const server = new ExternalHttpServer(config(), external(), f.port),
      endpoint = await server.start(0);
    const client = new FakeSmsSendClient(
        endpoint,
        'Bearer ' + 'e'.repeat(43),
        config().bindings[0]!.providerScope,
      ),
      controller = new AbortController();
    const caller = client.send(send(), controller.signal);
    const outcome = caller.then(
      () => 'known',
      () => 'rejected',
    );
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        entered.promise,
        outcome.then(() => {
          throw new Error('caller settled before entry');
        }),
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new Error('owned entry deadline')), 2000);
        }),
      ]);
      if (timer) clearTimeout(timer);
      controller.abort();
      expect(await outcome).toBe('rejected');
      await client.close();
      expect(server.metrics().active).toBe(1);
      await expect(server.close()).rejects.toMatchObject({ code: 'CleanupIncomplete' });
      expect(f.closed()).toBe(0);
      release.resolve();
      // Actual server drain is independent of the abandoned client and remains bounded.
      const until = performance.now() + 2000;
      while (f.closed() === 0 && performance.now() < until)
        await new Promise<void>((r) => setTimeout(r, 5));
      await server.close();
      expect(f.closed()).toBe(1);
    } finally {
      if (timer) clearTimeout(timer);
      release.resolve();
      await outcome;
      await client.close();
      await server.close();
    }
  });
});
describe('bounded repeated close observations', () => {
  it('reuses one actual pass after deadline and completes only after real release', async () => {
    const guard = new CloseObservation(),
      held = deferred<void>();
    let invoked = 0;
    const first = guard.observe(async () => {
      invoked++;
      await held.promise;
    }, 20);
    await expect(first).rejects.toMatchObject({ code: 'CleanupIncomplete' });
    for (let i = 0; i < 16; i++)
      expect(
        guard.observe(async () => {
          invoked++;
        }, 20),
      ).toBe(first);
    expect(invoked).toBe(1);
    expect(guard.pending).toBe(true);
    held.resolve();
    await new Promise<void>((r) => setImmediate(r));
    await guard.observe(async () => {
      invoked++;
    });
    expect(invoked).toBe(1);
  });
  it('reserves observation before an actual close callback reenters', async () => {
    const guard = new CloseObservation(),
      held = deferred<void>();
    let first!: Promise<void>, nested!: Promise<void>;
    first = guard.observe(async () => {
      nested = guard.observe(async () => {
        throw new Error('must not enter');
      });
      await held.promise;
    });
    await new Promise<void>((r) => setImmediate(r));
    expect(nested).toBe(first);
    held.resolve();
    await first;
  });
});
