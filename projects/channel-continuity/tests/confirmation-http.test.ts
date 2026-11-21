import { describe, it, expect } from 'vitest';
import { createServer, type ServerResponse } from 'node:http';
import { createServer as createNetServer } from 'node:net';
import { CaseAuthorityHttpClient } from '../src/routing.js';
import type { Socket } from 'node:net';
import { randomUUID } from 'node:crypto';
import {
  ConfirmationHttpClient,
  ConfirmationError,
  quoteDigest,
  type ExactConfirmation,
  type ConfirmationReceipt,
} from '../src/confirmation.js';
const REF = { scope: { tenantId: 'tenant-a', accountId: 'account-a' }, caseId: 'case-a' };
const QUOTE =
  '{"expected_supplier_revision":9223372036854775806,"revision":9223372036854775807,"schema_version":2}';
const COMMAND: ExactConfirmation = {
  ...REF,
  commandId: randomUUID(),
  expectedRevision: '9223372036854775807',
  quoteId: '6ba7b811-9dad-51d1-80b4-00c04fd430c8',
  quoteDigest: quoteDigest(QUOTE),
  quoteJson: QUOTE,
  explicit: true,
};
const RECEIPT: ConfirmationReceipt = {
  ...REF,
  commandId: COMMAND.commandId,
  revision: COMMAND.expectedRevision,
  quoteId: COMMAND.quoteId,
  quoteDigest: COMMAND.quoteDigest,
  intentId: randomUUID(),
  effectId: randomUUID(),
};
function reply(response: ServerResponse, value: unknown) {
  const data = Buffer.from(JSON.stringify(value));
  response.writeHead(200, {
    'Content-Type': 'application/json',
    'Content-Length': String(data.byteLength),
    Connection: 'close',
  });
  response.end(data);
}
async function fixture(mode: string) {
  const sockets = new Set<Socket>();
  let calls = 0;
  const server = createServer((incoming, response) => {
    calls++;
    expect(incoming.url).toBe('/v1/case/confirm');
    expect(incoming.headers.authorization).toBe('Bearer ' + 'a'.repeat(43));
    const chunks: Buffer[] = [];
    incoming.on('data', (chunk: Buffer) => chunks.push(chunk));
    incoming.on('end', () => {
      const body = JSON.parse(Buffer.concat(chunks).toString()) as {
        quoteJson: string;
        expectedRevision: string;
      };
      expect(body.quoteJson).toBe(QUOTE);
      expect(body.expectedRevision).toBe(COMMAND.expectedRevision);
      if (mode === 'drop') {
        response.destroy();
        return;
      }
      if (['AccessDenied', 'IdentityConflict', 'RevisionConflict'].includes(mode)) {
        reply(response, { schemaVersion: 1, status: 'rejected', code: mode });
        return;
      }
      if (mode === 'malformed') {
        reply(response, {
          schemaVersion: 1,
          status: 'known',
          confirmation: { ...RECEIPT, quoteDigest: 'a'.repeat(64) },
        });
        return;
      }
      if (mode === 'array') {
        reply(response, { schemaVersion: 1, status: 'rejected', code: ['IdentityConflict'] });
        return;
      }
      if (mode === 'unknown') {
        reply(response, { schemaVersion: 1, status: 'unknown', code: 'OutcomeUnknown' });
        return;
      }
      if (mode === 'hold') return;
      reply(response, { schemaVersion: 1, status: 'known', confirmation: RECEIPT });
    });
  });
  server.on('connection', (socket) => {
    sockets.add(socket);
    socket.once('close', () => sockets.delete(socket));
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('fixture');
  const client = new ConfirmationHttpClient(
    { host: '127.0.0.1', port: address.port },
    'Bearer ' + 'a'.repeat(43),
    [REF],
    { timeoutMs: 80, cleanupMs: 100, maxActive: 1 },
  );
  return {
    client,
    calls: () => calls,
    async close() {
      await client.close();
      const serverClosed = new Promise<void>((resolve) => server.close(() => resolve()));
      const connectionsClosed = Array.from(sockets, (socket) => {
        const closed = new Promise<void>((resolve) => socket.once('close', () => resolve()));
        socket.destroy();
        return closed;
      });
      await Promise.all([serverClosed, ...connectionsClosed]);
      expect(sockets.size).toBe(0);
      expect(client.metrics().active).toBe(0);
    },
  };
}
describe('explicit exact confirmation HTTP capability', () => {
  it('preserves opaque int64 quote bytes and validates the complete stable receipt', async () => {
    const f = await fixture('known');
    try {
      expect(await f.client.confirm(COMMAND, new AbortController().signal)).toEqual(RECEIPT);
      expect(f.calls()).toBe(1);
    } finally {
      await f.close();
    }
  });
  it.each(['AccessDenied', 'IdentityConflict', 'RevisionConflict'])(
    'preserves a fixed validated rejection: %s',
    async (code) => {
      const f = await fixture(code);
      try {
        await expect(f.client.confirm(COMMAND, new AbortController().signal)).rejects.toEqual(
          new ConfirmationError(code as 'AccessDenied' | 'IdentityConflict' | 'RevisionConflict'),
        );
        expect(f.calls()).toBe(1);
      } finally {
        await f.close();
      }
    },
  );
  it.each(['drop', 'malformed', 'array', 'unknown', 'hold'])(
    'does not invent commitment after possible write: %s',
    async (mode) => {
      const f = await fixture(mode);
      try {
        await expect(f.client.confirm(COMMAND, new AbortController().signal)).rejects.toEqual(
          new ConfirmationError('OutcomeUnknown'),
        );
        expect(f.calls()).toBe(1);
      } finally {
        await f.close();
      }
    },
  );
  it.each(['confirm_missing', 'confirm_keep-alive', 'inspect_missing', 'inspect_keep-alive'])(
    'requires explicit Connection close before trusting a response: %s',
    async (kind) => {
      const sockets = new Set<Socket>();
      const closedSockets: Promise<void>[] = [];
      let sent = false;
      const server = createNetServer((socket) => {
        sockets.add(socket);
        closedSockets.push(
          new Promise<void>((resolve) =>
            socket.once('close', () => {
              sockets.delete(socket);
              resolve();
            }),
          ),
        );
        let raw = Buffer.alloc(0);
        socket.on('data', (chunk: Buffer) => {
          raw = Buffer.concat([raw, chunk]);
          const split = raw.indexOf('\r\n\r\n');
          if (split < 0 || sent) return;
          const size = Number(
            /content-length:\s*([0-9]+)/i.exec(raw.subarray(0, split).toString())?.[1],
          );
          if (!Number.isFinite(size) || raw.length < split + 4 + size) return;
          sent = true;
          const body = JSON.stringify(
            kind.startsWith('confirm')
              ? { schemaVersion: 1, status: 'known', confirmation: RECEIPT }
              : {
                  schemaVersion: 1,
                  status: 'known',
                  case: {
                    ...REF,
                    revision: '1',
                    request: {
                      schemaVersion: 1,
                      kind: 'booking_investigation',
                      bookingReference: 'DEMO-BK-001',
                      newCheckIn: '2030-12-10',
                      investigationConsent: true,
                    },
                    cancelled: false,
                    committed: false,
                  },
                },
          );
          socket.end(
            'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ' +
              String(Buffer.byteLength(body)) +
              '\r\n' +
              (kind.endsWith('keep-alive') ? 'Connection: keep-alive\r\n' : '') +
              '\r\n' +
              body,
          );
        });
      });
      await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
      const address = server.address();
      if (!address || typeof address === 'string') throw new Error('fixture');
      const endpoint = { host: '127.0.0.1' as const, port: address.port };
      const confirmation = new ConfirmationHttpClient(endpoint, 'Bearer ' + 'a'.repeat(43), [REF]);
      const inspection = new CaseAuthorityHttpClient(endpoint, 'Bearer ' + 'a'.repeat(43), [REF]);
      try {
        if (kind.startsWith('confirm'))
          await expect(confirmation.confirm(COMMAND, new AbortController().signal)).rejects.toEqual(
            new ConfirmationError('OutcomeUnknown'),
          );
        else
          await expect(inspection.inspect(REF, new AbortController().signal)).rejects.toMatchObject(
            { code: 'Unavailable' },
          );
        expect(sent).toBe(true);
      } finally {
        await confirmation.close();
        await inspection.close();
        for (const socket of sockets) socket.destroy();
        await Promise.all(closedSockets);
        await new Promise<void>((resolve) => server.close(() => resolve()));
        expect(sockets.size).toBe(0);
      }
    },
  );
  it('denies wrong scope and invalid signals before socket creation', async () => {
    const f = await fixture('known');
    try {
      await expect(
        f.client.confirm({ ...COMMAND, caseId: 'other' }, new AbortController().signal),
      ).rejects.toEqual(new ConfirmationError('AccessDenied'));
      await expect(f.client.confirm(COMMAND, {} as AbortSignal)).rejects.toEqual(
        new ConfirmationError('InvalidCommand'),
      );
      expect(f.calls()).toBe(0);
      expect(f.client.metrics().active).toBe(0);
    } finally {
      await f.close();
    }
  });
});
