import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import type { Socket } from 'node:net';
import { describe, expect, it } from 'vitest';
import { CaseAuthorityHttpClient, RoutingError, type CaseSnapshot } from '../src/routing.js';
const REF = { scope: { tenantId: 'tenant-a', accountId: 'account-a' }, caseId: 'case-a' };
const REQUEST = {
  schemaVersion: 1 as const,
  kind: 'booking_investigation' as const,
  bookingReference: 'DEMO-BK-001',
  newCheckIn: '2030-12-11',
  investigationConsent: true as const,
};
const CASE: CaseSnapshot = {
  ...REF,
  revision: '1',
  request: REQUEST,
  cancelled: false,
  committed: false,
};
const CHANGE = { ...REF, expectedRevision: '0', request: REQUEST };
function reply(response: ServerResponse, value: unknown) {
  const body = Buffer.from(JSON.stringify(value));
  response.writeHead(200, {
    'Content-Type': 'application/json',
    'Content-Length': String(body.byteLength),
    Connection: 'close',
  });
  response.end(body);
}
async function fixture(handler: (request: IncomingMessage, response: ServerResponse) => void) {
  const sockets = new Set<Socket>(),
    closed = new Set<Promise<void>>(),
    server = createServer(handler);
  server.on('connection', (socket) => {
    sockets.add(socket);
    closed.add(
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
  if (!address || typeof address === 'string') throw new Error('fixture');
  const client = new CaseAuthorityHttpClient(
    { host: '127.0.0.1', port: address.port },
    'Bearer ' + 'a'.repeat(43),
    [REF],
    { timeoutMs: 100, cleanupMs: 100 },
  );
  return {
    client,
    async close() {
      await client.close();
      for (const socket of sockets) socket.destroy();
      await new Promise<void>((resolve) => server.close(() => resolve()));
      await Promise.all([...closed]);
      expect(sockets.size).toBe(0);
    },
  };
}
describe('bounded explicit local case authority transport', () => {
  it('uses one authenticated POST and validates the complete known case', async () => {
    let calls = 0;
    const f = await fixture((request, response) => {
      calls++;
      expect(request.url).toBe('/v1/case/revise');
      expect(request.method).toBe('POST');
      expect(request.headers.authorization).toBe('Bearer ' + 'a'.repeat(43));
      const chunks: Buffer[] = [];
      request.on('data', (value: Buffer) => chunks.push(value));
      request.on('end', () => {
        expect(JSON.parse(Buffer.concat(chunks).toString())).toEqual({
          schemaVersion: 1,
          ...CHANGE,
        });
        reply(response, { schemaVersion: 1, status: 'known', case: CASE });
      });
    });
    try {
      expect(await f.client.revise(CHANGE, new AbortController().signal)).toEqual(CASE);
      expect(calls).toBe(1);
    } finally {
      await f.close();
    }
  });
  it('maps a validated conflict without a second request', async () => {
    let calls = 0;
    const f = await fixture((_, response) => {
      calls++;
      reply(response, { schemaVersion: 1, status: 'rejected', code: 'RevisionConflict' });
    });
    try {
      await expect(f.client.revise(CHANGE, new AbortController().signal)).rejects.toEqual(
        new RoutingError('RevisionConflict'),
      );
      expect(calls).toBe(1);
    } finally {
      await f.close();
    }
  });
  it.each([
    'mismatch',
    'duplicate',
    'oversized',
    'transport',
    'redirect',
    'unknown',
    'wrong_revision',
  ])('preserves uncertainty after a possible write: %s', async (kind) => {
    const f = await fixture((_, response) => {
      if (kind === 'transport') {
        response.destroy();
        return;
      }
      if (kind === 'redirect') {
        response.writeHead(302, { Location: 'http://sentinel-secret/' });
        response.end();
        return;
      }
      if (kind === 'oversized') {
        response.writeHead(200, { 'Content-Type': 'application/json', 'Content-Length': '9000' });
        response.end('x'.repeat(9000));
        return;
      }
      if (kind === 'duplicate') {
        const body =
          '{"schemaVersion":1,"status":"known","status":"known","case":' +
          JSON.stringify(CASE) +
          '}';
        response.writeHead(200, {
          'Content-Type': 'application/json',
          'Content-Length': String(Buffer.byteLength(body)),
        });
        response.end(body);
        return;
      }
      if (kind === 'unknown') {
        reply(response, { schemaVersion: 1, status: 'unknown', code: 'OutcomeUnknown' });
        return;
      }
      reply(response, {
        schemaVersion: 1,
        status: 'known',
        case: { ...CASE, ...(kind === 'mismatch' ? { caseId: 'other' } : { revision: '2' }) },
      });
    });
    try {
      await expect(f.client.revise(CHANGE, new AbortController().signal)).rejects.toEqual(
        new RoutingError('OutcomeUnknown'),
      );
    } finally {
      await f.close();
    }
  });
  it('does not coerce a JSON array into a fixed rejection code', async () => {
    const f = await fixture((_, response) =>
      reply(response, { schemaVersion: 1, status: 'rejected', code: ['RevisionConflict'] }),
    );
    try {
      await expect(f.client.revise(CHANGE, new AbortController().signal)).rejects.toEqual(
        new RoutingError('OutcomeUnknown'),
      );
    } finally {
      await f.close();
    }
  });
  it('does not disclose a case outside the independently configured scope', async () => {
    let calls = 0;
    const f = await fixture((_, response) => {
      calls++;
      reply(response, { schemaVersion: 1, status: 'known', case: CASE });
    });
    try {
      expect(() =>
        f.client.inspect(
          { ...REF, scope: { ...REF.scope, accountId: 'other' } },
          new AbortController().signal,
        ),
      ).toThrow(new RoutingError('AccessDenied'));
      expect(calls).toBe(0);
    } finally {
      await f.close();
    }
  });
  it('owns and closes both actual sockets at bounded capacity after stalled calls', async () => {
    let reached!: () => void,
      calls = 0;
    const entered = new Promise<void>((resolve) => {
      reached = resolve;
    });
    const f = await fixture(() => {
      calls++;
      if (calls === 2) reached();
    });
    const a = f.client.revise(CHANGE, new AbortController().signal),
      b = f.client.revise(CHANGE, new AbortController().signal);
    await entered;
    await expect(f.client.revise(CHANGE, new AbortController().signal)).rejects.toEqual(
      new RoutingError('Overloaded'),
    );
    await Promise.all([
      expect(a).rejects.toEqual(new RoutingError('OutcomeUnknown')),
      expect(b).rejects.toEqual(new RoutingError('OutcomeUnknown')),
    ]);
    await f.close();
    expect(f.client.metrics().active).toBe(0);
  });
  it('treats malformed inspection as unavailable and never retries', async () => {
    let calls = 0;
    const f = await fixture((_, response) => {
      calls++;
      reply(response, {
        schemaVersion: 1,
        status: 'known',
        case: { ...CASE, scope: { ...REF.scope, accountId: 'other' } },
      });
    });
    try {
      await expect(f.client.inspect(REF, new AbortController().signal)).rejects.toEqual(
        new RoutingError('Unavailable'),
      );
      expect(calls).toBe(1);
    } finally {
      await f.close();
    }
  });
  it('rejects a malformed signal before creating a request', async () => {
    let calls = 0;
    const f = await fixture(() => {
      calls++;
    });
    try {
      expect(() => f.client.revise(CHANGE, {} as AbortSignal)).toThrow(
        new RoutingError('InvalidCommand'),
      );
      expect(f.client.metrics().active).toBe(0);
      expect(calls).toBe(0);
    } finally {
      await f.close();
    }
  });
  it('rejects ambiguous endpoint and credential selectors before opening sockets', () => {
    expect(
      () =>
        new CaseAuthorityHttpClient(
          { host: 'localhost' as '127.0.0.1', port: 1234 },
          'Bearer ' + 'a'.repeat(43),
          [REF],
        ),
    ).toThrow();
    expect(
      () =>
        new CaseAuthorityHttpClient(
          { host: '127.0.0.1', port: 1234 },
          'Bearer ' + 'a'.repeat(43) + '\n',
          [REF],
        ),
    ).toThrow();
  });
});
