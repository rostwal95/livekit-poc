import { createHash, randomUUID } from 'node:crypto';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { createServer as createRawServer, type Server, type Socket } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { IdempotentFakeSmsClient } from '../src/idempotent-fake-sms.js';
import { sendRequest, type SendRequest } from '../src/outbox-types.js';
import {
  operationFrom,
  operationDigest,
  type ProviderOperation,
} from '../src/send-policy-types.js';

const PROVIDER = Object.freeze({
  tenantId: 'tenant-http',
  provider: 'fake_sms',
  providerAccountId: 'provider-http',
});
const AUTH = 'Bearer ' + 'h'.repeat(43);
const SIGNAL = () => new AbortController().signal;
const digest = (value: unknown) => createHash('sha256').update(JSON.stringify(value)).digest('hex');
function input(): SendRequest {
  return sendRequest({
    schemaVersion: 1,
    outboundId: randomUUID(),
    responseId: 'response-http',
    body: 'Original reply',
    scope: { tenantId: PROVIDER.tenantId, accountId: 'account-http' },
    caseId: 'case-http',
    conversationId: 'conversation-http',
    attemptId: randomUUID(),
    providerOperationKey: randomUUID(),
    providerScope: PROVIDER,
    senderId: 'sender-http',
    associationVersion: '1',
    routeVersion: '1',
  });
}
type Wire = {
  schemaVersion: 1;
  operation: ProviderOperation;
  operationDigest: string;
  attempt: {
    attemptId: string;
    requestDigest: string;
    associationVersion: string;
    routeVersion: string;
  };
};
function reconstruct(wire: Wire): SendRequest {
  const op = wire.operation;
  return sendRequest({
    schemaVersion: 1,
    outboundId: op.outboundId,
    responseId: op.responseId,
    body: op.body,
    scope: op.scope,
    caseId: op.caseId,
    conversationId: op.conversationId,
    attemptId: wire.attempt.attemptId,
    providerOperationKey: op.providerOperationKey,
    providerScope: op.providerScope,
    senderId: op.senderId,
    associationVersion: wire.attempt.associationVersion,
    routeVersion: wire.attempt.routeVersion,
  });
}
function accepted(request: SendRequest) {
  const op = operationFrom(request, 'idempotent_fake_sms_v1');
  return {
    schemaVersion: 1,
    status: 'known',
    providerOperationKey: op.providerOperationKey,
    operationDigest: operationDigest(op),
    result: {
      schemaVersion: 1,
      attemptId: request.attemptId,
      requestDigest: digest(request),
      status: 'accepted_by_provider',
      providerMessageId: 'message-http',
    },
  };
}
function observed(op: ProviderOperation, state = 'accepted_by_provider') {
  return {
    schemaVersion: 1,
    status: 'known',
    observation: {
      schemaVersion: 1,
      providerScope: op.providerScope,
      providerOperationKey: op.providerOperationKey,
      operationDigest: operationDigest(op),
      state,
      providerMessageId: state === 'accepted_by_provider' ? 'message-http' : null,
    },
  };
}
function reply(response: ServerResponse, value: unknown): void {
  const raw = Buffer.from(JSON.stringify(value));
  response.writeHead(200, {
    'Content-Type': 'application/json',
    'Content-Length': String(raw.length),
    Connection: 'close',
  });
  response.end(raw);
}
async function body(request: IncomingMessage): Promise<Buffer> {
  const chunks: Buffer[] = [];
  let bytes = 0;
  for await (const chunk of request) {
    const raw = Buffer.from(chunk as Uint8Array);
    bytes += raw.length;
    if (bytes > 32768) throw new Error('fixture_request_bound');
    chunks.push(raw);
  }
  return Buffer.concat(chunks);
}
async function fixture(
  server: Server,
  options = { timeoutMs: 1000, cleanupMs: 200, maxActive: 2 },
) {
  const sockets = new Set<Socket>();
  const closures: Promise<void>[] = [];
  server.on('connection', (socket) => {
    sockets.add(socket);
    closures.push(
      new Promise<void>((resolve) =>
        socket.once('close', () => {
          sockets.delete(socket);
          resolve();
        }),
      ),
    );
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('fixture_address');
  const endpoint = { host: '127.0.0.1' as const, port: address.port };
  const client = new IdempotentFakeSmsClient(endpoint, AUTH, PROVIDER, options);
  return {
    client,
    endpoint,
    async close() {
      try {
        await client.close();
      } finally {
        for (const socket of sockets) socket.destroy();
        await new Promise<void>((resolve, reject) =>
          server.close((error) => (error ? reject(error) : resolve())),
        );
        await Promise.all(closures);
        expect(sockets.size).toBe(0);
      }
    },
  };
}
async function until(settled: () => boolean): Promise<void> {
  const deadline = performance.now() + 1500;
  while (!settled()) {
    if (performance.now() >= deadline) throw new Error('fixture_settlement_bound');
    await new Promise<void>((resolve) => setTimeout(resolve, 2));
  }
}

describe('explicit idempotent fake HTTP consumer', () => {
  it('transmits a maximal escaped body once and independently reconstructs the attempt digest', async () => {
    const request = sendRequest({ ...input(), body: '\n'.repeat(4096) });
    const observations: {
      path: string | undefined;
      authorization: string | undefined;
      bytes: Buffer;
      wire: Wire;
    }[] = [];
    const server = createServer((incoming, response) => {
      void body(incoming).then(
        (raw) => {
          const wire = JSON.parse(raw.toString()) as Wire;
          observations.push({
            path: incoming.url,
            authorization: incoming.headers.authorization,
            bytes: raw,
            wire,
          });
          reply(response, accepted(reconstruct(wire)));
        },
        () => response.destroy(),
      );
    });
    const f = await fixture(server);
    try {
      expect((await f.client.send(request, SIGNAL())).status).toBe('accepted_by_provider');
      expect(observations).toHaveLength(1);
      const observation = observations[0]!;
      expect(observation.path).toBe('/v1/idempotent-sms/send');
      expect(observation.authorization).toBe(AUTH);
      expect(observation.bytes.length).toBeLessThanOrEqual(32768);
      expect(Object.keys(observation.wire)).toEqual([
        'schemaVersion',
        'operation',
        'operationDigest',
        'attempt',
      ]);
      expect(Object.keys(observation.wire.attempt)).toEqual([
        'attemptId',
        'requestDigest',
        'associationVersion',
        'routeVersion',
      ]);
      expect(reconstruct(observation.wire)).toEqual(request);
      expect(observation.wire.operationDigest).toBe(digest(observation.wire.operation));
      expect(observation.wire.attempt.requestDigest).toBe(digest(request));
      expect(observation.bytes.toString().match(/"body":/g)).toHaveLength(1);
    } finally {
      await f.close();
    }
  });

  it('retains one persisted fake acceptance after a dropped response and a fresh explicit same-key attempt', async () => {
    const directory = await mkdtemp(join(tmpdir(), 'p2-idempotent-http-'));
    const ledger = join(directory, 'acceptance.json');
    const first = input();
    const second = sendRequest({
      ...first,
      attemptId: randomUUID(),
      associationVersion: '3',
      routeVersion: '4',
    });
    const received: Wire[] = [];
    let physicalAcceptances = 0;
    const server = createServer((incoming, response) => {
      void body(incoming)
        .then(async (raw) => {
          const wire = JSON.parse(raw.toString()) as Wire;
          received.push(wire);
          const stored = JSON.stringify({
            operation: wire.operation,
            operationDigest: wire.operationDigest,
            providerMessageId: 'message-http',
          });
          if (received.length === 1) {
            await writeFile(ledger, stored, { flag: 'wx', mode: 0o600 });
            physicalAcceptances++;
            response.destroy();
          } else {
            expect(await readFile(ledger, 'utf8')).toBe(stored);
            reply(response, accepted(reconstruct(wire)));
          }
        })
        .catch(() => response.destroy());
    });
    const f = await fixture(server);
    let fresh: IdempotentFakeSmsClient | undefined;
    try {
      await expect(f.client.send(first, SIGNAL())).rejects.toThrow('OutcomeUnknown');
      expect(received).toHaveLength(1);
      await f.client.close();
      fresh = new IdempotentFakeSmsClient(f.endpoint, AUTH, PROVIDER);
      const result = await fresh.send(second, SIGNAL());
      expect(result.status).toBe('accepted_by_provider');
      if (result.status !== 'accepted_by_provider') throw new Error('fixture_expected_acceptance');
      expect(result.providerMessageId).toBe('message-http');
      expect(received).toHaveLength(2);
      expect(received[0]!.operation).toEqual(received[1]!.operation);
      expect(received[0]!.operationDigest).toBe(received[1]!.operationDigest);
      expect(received[0]!.attempt.attemptId).not.toBe(received[1]!.attempt.attemptId);
      expect(received[0]!.attempt.requestDigest).not.toBe(received[1]!.attempt.requestDigest);
      expect(physicalAcceptances).toBe(1);
      expect(JSON.parse(await readFile(ledger, 'utf8')).providerMessageId).toBe('message-http');
      expect(f.client.metrics().started).toBe(1);
      expect(fresh.metrics().started).toBe(1);
    } finally {
      await fresh?.close();
      await f.close();
      await rm(directory, { recursive: true, force: true });
    }
  });

  it.each(['accepted_by_provider', 'definitive_not_accepted', 'absent', 'unknown'])(
    'uses the bounded original-operation lookup wire and preserves reported %s',
    async (state) => {
      const op = operationFrom(input(), 'idempotent_fake_sms_v1');
      const seen: unknown[] = [];
      const server = createServer((incoming, response) => {
        void body(incoming).then(
          (raw) => {
            seen.push(JSON.parse(raw.toString()));
            expect(incoming.url).toBe('/v1/idempotent-sms/lookup');
            reply(response, observed(op, state));
          },
          () => response.destroy(),
        );
      });
      const f = await fixture(server);
      try {
        const value = await f.client.lookup(op, SIGNAL());
        expect(value.state).toBe(state);
        expect(seen).toEqual([
          {
            schemaVersion: 1,
            providerScope: PROVIDER,
            providerOperationKey: op.providerOperationKey,
            operationDigest: operationDigest(op),
          },
        ]);
        expect(f.client.metrics().started).toBe(1);
      } finally {
        await f.close();
      }
    },
  );

  it('snapshots caller operation and request values before network awaits', async () => {
    const original = input();
    const mutable = {
      ...original,
      scope: { ...original.scope },
      providerScope: { ...original.providerScope },
    };
    const op = {
      ...operationFrom(original, 'idempotent_fake_sms_v1'),
      scope: { ...original.scope },
      providerScope: { ...original.providerScope },
    };
    const seen: unknown[] = [];
    const server = createServer((incoming, response) => {
      void body(incoming).then(
        (raw) => {
          const wire = JSON.parse(raw.toString()) as Wire;
          seen.push(wire);
          reply(
            response,
            incoming.url?.endsWith('/send')
              ? accepted(original)
              : observed(operationFrom(original, 'idempotent_fake_sms_v1')),
          );
        },
        () => response.destroy(),
      );
    });
    const f = await fixture(server);
    try {
      const send = f.client.send(mutable, SIGNAL());
      mutable.body = 'Changed after invocation';
      mutable.scope.accountId = 'other';
      await send;
      const lookup = f.client.lookup(op, SIGNAL());
      op.body = 'Changed operation';
      op.providerScope.providerAccountId = 'other';
      await lookup;
      expect((seen[0] as Wire).operation.body).toBe(original.body);
      expect((seen[0] as Wire).operation.scope).toEqual(original.scope);
      expect(seen[1]).toEqual({
        schemaVersion: 1,
        providerScope: PROVIDER,
        providerOperationKey: original.providerOperationKey,
        operationDigest: operationDigest(operationFrom(original, 'idempotent_fake_sms_v1')),
      });
    } finally {
      await f.close();
    }
  });

  it.each([
    'key',
    'operation_digest',
    'attempt',
    'request_digest',
    'message',
    'schema',
    'duplicate_json',
    'redirect',
    'oversized',
    'private_error',
  ])('keeps unvalidated send response unknown with zero automatic retry: %s', async (kind) => {
    const request = input();
    let calls = 0;
    const server = createRawServer((socket) =>
      socket.once('data', () => {
        calls++;
        const value = accepted(request);
        if (kind === 'key') value.providerOperationKey = randomUUID();
        if (kind === 'operation_digest') value.operationDigest = '0'.repeat(64);
        if (kind === 'attempt') value.result.attemptId = randomUUID();
        if (kind === 'request_digest') value.result.requestDigest = '0'.repeat(64);
        if (kind === 'message') value.result.providerMessageId = '';
        const unsafe: unknown =
          kind === 'schema'
            ? { ...value, schemaVersion: true }
            : kind === 'private_error'
              ? { error: 'PRIVATE_PROVIDER_RESPONSE_SENTINEL' }
              : value;
        let raw = JSON.stringify(unsafe);
        if (kind === 'duplicate_json')
          raw = raw.replace('"schemaVersion":1', '"schemaVersion":1,"schemaVersion":1');
        if (kind === 'oversized') raw = 'x'.repeat(8193);
        socket.end(
          `HTTP/1.1 ${kind === 'redirect' ? '307 Temporary Redirect' : '200 OK'}\r\nContent-Type: application/json\r\nContent-Length: ${Buffer.byteLength(raw)}\r\nConnection: close\r\n\r\n${raw}`,
        );
      }),
    );
    const f = await fixture(server);
    try {
      await expect(f.client.send(request, SIGNAL())).rejects.toMatchObject({
        code: 'OutcomeUnknown',
        message: 'OutcomeUnknown',
      });
      expect(calls).toBe(1);
      expect(f.client.metrics().started).toBe(1);
    } finally {
      await f.close();
    }
  });

  it.each(['scope', 'key', 'digest', 'accepted_without_message', 'unknown_with_message', 'extra'])(
    'rejects misbound or inconsistent lookup evidence: %s',
    async (kind) => {
      const op = operationFrom(input(), 'idempotent_fake_sms_v1');
      let calls = 0;
      const server = createServer((_incoming, response) => {
        calls++;
        const value = observed(op);
        if (kind === 'scope')
          value.observation.providerScope = { ...PROVIDER, providerAccountId: 'foreign' };
        if (kind === 'key') value.observation.providerOperationKey = randomUUID();
        if (kind === 'digest') value.observation.operationDigest = 'f'.repeat(64);
        if (kind === 'accepted_without_message') value.observation.providerMessageId = null;
        if (kind === 'unknown_with_message') value.observation.state = 'unknown';
        reply(
          response,
          kind === 'extra' ? { ...value, private: 'PRIVATE_LOOKUP_RESPONSE_SENTINEL' } : value,
        );
      });
      const f = await fixture(server);
      try {
        await expect(f.client.lookup(op, SIGNAL())).rejects.toMatchObject({
          code: 'OutcomeUnknown',
          message: 'OutcomeUnknown',
        });
        expect(calls).toBe(1);
      } finally {
        await f.close();
      }
    },
  );

  it('shares actual send/lookup capacity, closes aborted sockets and makes later useful progress', async () => {
    const request = input();
    const op = operationFrom(request, 'idempotent_fake_sms_v1');
    const responses: { path: string | undefined; response: ServerResponse }[] = [];
    let received!: () => void;
    const both = new Promise<void>((resolve) => {
      received = resolve;
    });
    const server = createServer((incoming, response) => {
      responses.push({ path: incoming.url, response });
      if (responses.length === 2) received();
      if (responses.length > 2) reply(response, observed(op));
    });
    const f = await fixture(server);
    const abort = new AbortController();
    try {
      const sending = f.client.send(request, abort.signal);
      const looking = f.client.lookup(op, SIGNAL());
      const rejected = expect(sending).rejects.toThrow('OutcomeUnknown');
      await both;
      expect(f.client.metrics().active).toBe(2);
      await expect(f.client.send(request, SIGNAL())).rejects.toThrow('OutcomeUnknown');
      expect(f.client.metrics().started).toBe(2);
      abort.abort();
      await rejected;
      const lookupResponse = responses.find((row) => row.path?.endsWith('/lookup'))!;
      reply(lookupResponse.response, observed(op, 'absent'));
      expect((await looking).state).toBe('absent');
      await until(() => f.client.metrics().active === 0);
      expect((await f.client.lookup(op, SIGNAL())).state).toBe('accepted_by_provider');
      expect(f.client.metrics().started).toBe(3);
    } finally {
      await f.close();
    }
  });

  it('rejects foreign scope, ordinary capability, getters and forged signals before any socket', async () => {
    const request = input();
    const op = operationFrom(request, 'idempotent_fake_sms_v1');
    let calls = 0;
    let getter = false;
    const f = await fixture(
      createRawServer(() => {
        calls++;
      }),
    );
    try {
      await expect(
        f.client.send(
          { ...request, providerScope: { ...PROVIDER, providerAccountId: 'foreign' } },
          SIGNAL(),
        ),
      ).rejects.toThrow('AccessDenied');
      await expect(
        f.client.lookup({ ...op, capability: 'ordinary_fake_sms_v1' }, SIGNAL()),
      ).rejects.toThrow('AccessDenied');
      await expect(
        f.client.lookup(
          {
            ...op,
            providerScope: { ...PROVIDER, tenantId: 'foreign' },
            scope: { ...op.scope, tenantId: 'foreign' },
          },
          SIGNAL(),
        ),
      ).rejects.toThrow('AccessDenied');
      const malicious = Object.defineProperty({ ...request }, 'body', {
        enumerable: true,
        get() {
          getter = true;
          throw new Error('PRIVATE_ACCESSOR_SENTINEL');
        },
      });
      await expect(f.client.send(malicious, SIGNAL())).rejects.toMatchObject({
        code: 'InvalidCommand',
        message: 'InvalidCommand',
      });
      const forged = Object.defineProperty({}, 'aborted', {
        get() {
          getter = true;
          throw new Error('PRIVATE_SIGNAL_SENTINEL');
        },
      }) as AbortSignal;
      await expect(f.client.send(request, forged)).rejects.toThrow('OutcomeUnknown');
      const aborted = new AbortController();
      aborted.abort();
      await expect(f.client.lookup(op, aborted.signal)).rejects.toThrow('OutcomeUnknown');
      expect(getter).toBe(false);
      expect(calls).toBe(0);
      expect(f.client.metrics().started).toBe(0);
      await f.client.close();
      await expect(f.client.send(request, SIGNAL())).rejects.toThrow('OutcomeUnknown');
      expect(calls).toBe(0);
    } finally {
      await f.close();
    }
  });

  it('validates finite construction options without evaluating accessors', () => {
    let getter = false;
    const endpoint = { host: '127.0.0.1' as const, port: 1 };
    for (const options of [
      { timeoutMs: 0 },
      { cleanupMs: 2001 },
      { maxActive: 5 },
      { maxActive: true },
      { hidden: 'PRIVATE_OPTIONS_SENTINEL' },
    ]) {
      expect(() => new IdempotentFakeSmsClient(endpoint, AUTH, PROVIDER, options as never)).toThrow(
        'InvalidCommand',
      );
    }
    const unsafe = Object.defineProperty({}, 'timeoutMs', {
      enumerable: true,
      get() {
        getter = true;
        throw new Error('PRIVATE_OPTIONS_SENTINEL');
      },
    });
    expect(() => new IdempotentFakeSmsClient(endpoint, AUTH, PROVIDER, unsafe)).toThrow(
      'InvalidCommand',
    );
    expect(
      () =>
        new IdempotentFakeSmsClient(
          { host: 'example.invalid', port: 443 } as never,
          AUTH,
          PROVIDER,
        ),
    ).toThrow('InvalidCommand');
    expect(() => new IdempotentFakeSmsClient(endpoint, 'bad', PROVIDER)).toThrow('InvalidCommand');
    expect(getter).toBe(false);
  });
});
