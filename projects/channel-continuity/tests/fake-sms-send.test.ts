import { createServer, type ServerResponse } from 'node:http';
import { createServer as createRawServer } from 'node:net';
import type { Socket } from 'node:net';
import { randomUUID } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { FakeSmsSendClient } from '../src/fake-sms-send.js';
import { sendRequest, sha } from '../src/outbox-types.js';
const SCOPE = { tenantId: 'tenant-a', provider: 'fake_sms', providerAccountId: 'carrier-a' },
  AUTH = 'Bearer ' + 'a'.repeat(43);
const INPUT = sendRequest({
  schemaVersion: 1,
  outboundId: randomUUID(),
  responseId: 'response-a',
  body: 'Hello',
  scope: { tenantId: 'tenant-a', accountId: 'account-a' },
  caseId: 'case-a',
  conversationId: 'conversation-a',
  attemptId: randomUUID(),
  providerOperationKey: randomUUID(),
  providerScope: SCOPE,
  senderId: 'sender-a',
  associationVersion: '1',
  routeVersion: '1',
});
function result(input = INPUT) {
  return {
    schemaVersion: 1,
    status: 'known',
    result: {
      schemaVersion: 1,
      status: 'accepted_by_provider',
      attemptId: input.attemptId,
      requestDigest: sha(JSON.stringify(input)),
      providerMessageId: 'provider-a',
    },
  };
}
function reply(response: ServerResponse, value: unknown) {
  const body = Buffer.from(JSON.stringify(value));
  response.writeHead(200, {
    'Content-Type': 'application/json',
    'Content-Length': String(body.length),
    Connection: 'close',
  });
  response.end(body);
}
async function peer(raw: boolean, handler: (socket: Socket) => void) {
  const sockets = new Set<Socket>(),
    closures: Promise<void>[] = [],
    server = raw ? createRawServer(handler) : createRawServer(handler);
  server.on('connection', (s) => {
    sockets.add(s);
    closures.push(
      new Promise((resolve) =>
        s.once('close', () => {
          sockets.delete(s);
          resolve();
        }),
      ),
    );
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const addr = server.address();
  if (!addr || typeof addr === 'string') throw new Error();
  const client = new FakeSmsSendClient({ host: '127.0.0.1', port: addr.port }, AUTH, SCOPE, {
    timeoutMs: 100,
    cleanupMs: 200,
  });
  return {
    client,
    async close() {
      await client.close();
      for (const s of sockets) s.destroy();
      await new Promise<void>((resolve) => server.close(() => resolve()));
      await Promise.all(closures);
      expect(sockets.size).toBe(0);
    },
  };
}
describe('ordinary authenticated local fake sends', () => {
  it('sends exact original bytes including maximal escaped body via one local request', async () => {
    const input = sendRequest({ ...INPUT, body: '\n'.repeat(4096) });
    let calls = 0;
    const server = createServer({ maxHeaderSize: 4096 }, (req, res) => {
      calls++;
      expect(req.url).toBe('/v1/sms/send');
      expect(req.headers.authorization).toBe(AUTH);
      const chunks: Buffer[] = [];
      req.on('data', (b: Buffer) => chunks.push(b));
      req.on('end', () => {
        expect(JSON.parse(Buffer.concat(chunks).toString())).toEqual(input);
        reply(res, result(input));
      });
    });
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
    const addr = server.address();
    if (!addr || typeof addr === 'string') throw new Error();
    const client = new FakeSmsSendClient({ host: '127.0.0.1', port: addr.port }, AUTH, SCOPE);
    try {
      expect((await client.send(input, new AbortController().signal)).status).toBe(
        'accepted_by_provider',
      );
      expect(calls).toBe(1);
    } finally {
      await client.close();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
  it.each([
    'missing_connection',
    'keep_alive',
    'duplicate_header',
    'wrong_attempt',
    'wrong_digest',
    'unknown_state',
    'oversized',
    'redirect',
    'transport',
    'duplicate_json',
  ])('treats unvalidated possible send as unknown with zero retries: %s', async (kind) => {
    let calls = 0;
    const f = await peer(true, (socket) => {
      socket.once('data', () => {
        calls++;
        if (kind === 'transport') {
          socket.destroy();
          return;
        }
        let value = result();
        if (kind === 'wrong_attempt')
          value = { ...value, result: { ...value.result, attemptId: randomUUID() } };
        if (kind === 'wrong_digest')
          value = { ...value, result: { ...value.result, requestDigest: 'f'.repeat(64) } };
        if (kind === 'unknown_state')
          value = { ...value, result: { ...value.result, status: 'delivered' } };
        let body = JSON.stringify(value);
        if (kind === 'duplicate_json')
          body = body.replace('"schemaVersion":1', '"schemaVersion":1,"schemaVersion":1');
        if (kind === 'oversized') body = 'x'.repeat(8193);
        const status = kind === 'redirect' ? '302 Found' : '200 OK',
          connection =
            kind === 'missing_connection'
              ? ''
              : kind === 'keep_alive'
                ? 'Connection: keep-alive\r\n'
                : 'Connection: close\r\n',
          extra =
            kind === 'duplicate_header'
              ? 'Content-Length: ' + Buffer.byteLength(body) + '\r\n'
              : '';
        socket.end(
          `HTTP/1.1 ${status}\r\nContent-Type: application/json\r\nContent-Length: ${Buffer.byteLength(body)}\r\n${connection}${extra}\r\n${body}`,
        );
      });
    });
    try {
      await expect(f.client.send(INPUT, new AbortController().signal)).rejects.toThrow(
        'OutcomeUnknown',
      );
      expect(calls).toBe(1);
    } finally {
      await f.close();
    }
  });
  it('denies wrong integration before a socket and closes idempotently', async () => {
    const f = await peer(true, () => {
      throw new Error('network forbidden');
    });
    try {
      await expect(
        f.client.send(
          { ...INPUT, providerScope: { ...SCOPE, providerAccountId: 'other' } },
          new AbortController().signal,
        ),
      ).rejects.toThrow('AccessDenied');
      expect(f.client.metrics().started).toBe(0);
      await f.client.close();
    } finally {
      await f.close();
    }
  });
});
