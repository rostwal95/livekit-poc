/** Real source producer to new app wire; fake persistence, no PostgreSQL qualification. */
import { describe, expect, it, vi } from 'vitest';
import { randomUUID } from 'node:crypto';
import { request, createServer } from 'node:http';
import { Socket } from 'node:net';
import type { OperationClientConfig } from '../examples/standalone/application.js';
import { produceTextEvent } from '@livekit-ecosystem/channel-continuity';
import type { StoredMessage } from '@livekit-ecosystem/channel-continuity/postgres';
import { prepareDispatch } from '../src/dispatch-types.js';
import {
  ExternalHttpServer,
  ExternalOperationClient,
  type ExternalLedgerPort,
} from '../examples/standalone/external-http.js';
import {
  parseConfig,
  digest,
  parseCredentials,
  type RuntimeCredentials,
  type ExternalCredentials,
} from '../examples/standalone/config.js';
function inputs() {
  const tenantId = 't'.repeat(128),
    accountId = 'a'.repeat(128);
  const cfg = parseConfig({
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
        providerScope: { tenantId, provider: 'fake_sms', providerAccountId: 'p'.repeat(128) },
        accountScope: { tenantId, accountId },
        caseId: 'c'.repeat(128),
        conversationId: 'v'.repeat(128),
        senderId: 's'.repeat(128),
        initialCase: {
          revision: '0',
          request: {
            schemaVersion: 1,
            kind: 'booking_investigation',
            bookingReference: 'D'.repeat(64),
            newCheckIn: '2030-01-01',
            investigationConsent: true,
          },
        },
      },
    ],
    endpoints: { gateway: 12001, external: 12002 },
    limits: { maxInbox: 64, externalReceipts: 16 },
  });
  const bearers = [
    {
      alias: 'primary',
      operation: 'd'.repeat(43),
      ordinary: 'e'.repeat(43),
      idempotent: 'f'.repeat(43),
    },
  ];
  const runtime = parseCredentials(
    {
      schemaVersion: 1,
      role: 'runtime',
      profileId: cfg.profileId,
      postgresPassword: 'p'.repeat(40),
      bindings: [
        {
          alias: 'primary',
          accountToken: 'a'.repeat(40),
          publisherToken: 'b'.repeat(40),
          recoveryToken: 'c'.repeat(40),
        },
      ],
      providerHmac: Buffer.alloc(32, 1).toString('base64url'),
      callbackHmac: Buffer.alloc(32, 2).toString('base64url'),
      externalBearers: bearers,
    },
    cfg,
  ) as RuntimeCredentials;
  const external = parseCredentials(
    {
      schemaVersion: 1,
      role: 'external',
      profileId: cfg.profileId,
      postgresPassword: 'p'.repeat(40),
      bearers,
    },
    cfg,
  ) as ExternalCredentials;
  return { cfg, runtime, external };
}
function narrowConfig(port: number) {
  return {
    schemaVersion: 1 as const,
    profileId: '11111111-1111-4111-8111-111111111111',
    endpoint: { host: '127.0.0.1' as const, port },
    bindings: [
      {
        alias: 'primary',
        accountScope: { tenantId: 't'.repeat(128), accountId: 'a'.repeat(128) },
        caseId: 'c'.repeat(128),
        conversationId: 'v'.repeat(128),
        senderId: 's'.repeat(128),
        operationBearer: 'd'.repeat(43),
      },
    ],
  } satisfies OperationClientConfig;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
function operationLedger(accept: ExternalLedgerPort['accept']): ExternalLedgerPort {
  return {
    async preflight() {},
    async close() {},
    accept,
    async lookup() {
      return { status: 'absent' };
    },
    async ordinarySend() {
      throw Error('unused');
    },
    async idempotentSend() {
      throw Error('unused');
    },
    async idempotentLookup() {
      throw Error('unused');
    },
  };
}
function prepared(content: string) {
  const b = inputs().cfg.bindings[0]!,
    receiptId = randomUUID();
  const message: StoredMessage = {
    receipt: {
      receiptId,
      eventId: 'e'.repeat(128),
      messageId: 'm'.repeat(128),
      acceptanceSequence: '9223372036854775807',
      acceptedAt: '2030-01-01T00:00:00.000Z',
    },
    event: produceTextEvent(
      {
        eventId: 'e'.repeat(128),
        providerScope: b.providerScope,
        accountScope: b.accountScope,
        caseId: b.caseId,
        conversationId: b.conversationId,
        receivedAt: '2030-01-01T00:00:00.000Z',
        channel: 'sms',
        messageId: 'm'.repeat(128),
        senderId: b.senderId,
        body: content,
      },
      { providerScope: b.providerScope, accountScope: b.accountScope },
    ).event,
    operationKey: randomUUID(),
    processingState: 'pending',
    associationVersion: '1',
  };
  return prepareDispatch(
    message,
    {
      scope: b.accountScope,
      caseId: b.caseId,
      revision: '9223372036854775807',
      source: 'synthetic_read_only',
    },
    { kind: 'investigation', source: 'scripted', caseRevision: '9223372036854775807' },
  );
}
describe('entire existing prepared-message domain', () => {
  it.each(
    ['', '\u0000'.repeat(4096), '🧭'.repeat(1024)].flatMap((content) =>
      ['legacy', 'narrow'].map((mode) => ({ mode, content })),
    ),
  )(
    '$mode retains valid empty/escaped/Unicode source content through bounded HTTP ($#)',
    async ({ mode, content }) => {
      const { cfg, runtime, external } = inputs();
      let calls = 0;
      const ledger: ExternalLedgerPort = {
        async preflight() {},
        async close() {},
        async accept(p) {
          calls++;
          return {
            operationKey: p.submission.operationKey,
            scope: p.submission.scope,
            payloadDigest: p.payloadDigest,
            receiptId: randomUUID(),
          };
        },
        async lookup() {
          return { status: 'absent' };
        },
        async ordinarySend() {
          throw new Error('not called');
        },
        async idempotentSend() {
          throw new Error('not called');
        },
        async idempotentLookup() {
          throw new Error('not called');
        },
      };
      const server = new ExternalHttpServer(cfg, external, ledger);
      let client: ExternalOperationClient | undefined;
      try {
        const endpoint = await server.start(0);
        client =
          mode === 'legacy'
            ? new ExternalOperationClient(
                parseConfig({ ...cfg, endpoints: { ...cfg.endpoints, external: endpoint.port } }),
                runtime,
              )
            : new ExternalOperationClient(narrowConfig(endpoint.port));
        await client.preflight('primary', new AbortController().signal);
        expect(
          await client.lookup(
            {
              operationKey: prepared('').submission.operationKey,
              scope: cfg.bindings[0]!.accountScope,
              payloadDigest: 'a'.repeat(64),
            },
            new AbortController().signal,
          ),
        ).toEqual({ status: 'absent' });
        const p = prepared(content),
          wire = JSON.stringify({
            schemaVersion: 1,
            canonicalPayload: p.canonicalPayload,
            payloadDigest: p.payloadDigest,
          });
        expect(Buffer.byteLength(p.canonicalPayload)).toBeLessThanOrEqual(32768);
        expect(Buffer.byteLength(wire)).toBeLessThanOrEqual(32768);
        if (content.startsWith('\u0000')) {
          const overhead = Buffer.byteLength(wire) - 7 * 4096;
          expect(overhead).toBeGreaterThan(1000);
          expect(overhead + 7 * 4096).toBeLessThanOrEqual(32768);
        }
        const result = await client.accept(p, new AbortController().signal);
        expect(result).toMatchObject({
          operationKey: p.submission.operationKey,
          payloadDigest: p.payloadDigest,
        });
        expect(calls).toBe(1);
      } finally {
        await client?.close();
        await server.close();
      }
    },
  );
  it('accepts the exact request ceiling and rejects32769 bytes before physical acceptance', async () => {
    const { cfg, external } = inputs();
    let calls = 0;
    const ledger: ExternalLedgerPort = {
      async preflight() {},
      async close() {},
      async accept(p) {
        calls++;
        return {
          operationKey: p.submission.operationKey,
          scope: p.submission.scope,
          payloadDigest: p.payloadDigest,
          receiptId: randomUUID(),
        };
      },
      async lookup() {
        return { status: 'absent' };
      },
      async ordinarySend() {
        throw Error();
      },
      async idempotentSend() {
        throw Error();
      },
      async idempotentLookup() {
        throw Error();
      },
    };
    const server = new ExternalHttpServer(cfg, external, ledger);
    const post = async (port: number, bytes: Buffer) =>
      new Promise<number>((resolve, reject) => {
        const req = request(
          {
            host: '127.0.0.1',
            port,
            path: '/v1/investigations/accept',
            method: 'POST',
            agent: false,
            headers: {
              host: '127.0.0.1:' + port,
              authorization: 'Bearer ' + 'd'.repeat(43),
              connection: 'close',
              'content-type': 'application/json',
              'content-length': bytes.length,
            },
          },
          (res) => {
            res.resume();
            res.on('end', () => resolve(res.statusCode!));
            res.on('error', reject);
          },
        );
        req.on('error', reject);
        req.setTimeout(2000, () => req.destroy(Error('owned test timeout')));
        req.end(bytes);
      });
    try {
      const endpoint = await server.start(0),
        p = prepared('');
      const base = JSON.stringify({
        schemaVersion: 1,
        canonicalPayload: p.canonicalPayload,
        payloadDigest: p.payloadDigest,
      });
      const exact = Buffer.from(base + ' '.repeat(32768 - Buffer.byteLength(base)));
      expect(exact.length).toBe(32768);
      expect(await post(endpoint.port, exact)).toBe(200);
      expect(calls).toBe(1);
      expect(await post(endpoint.port, Buffer.concat([exact, Buffer.from(' ')]))).toBe(400);
      expect(calls).toBe(1);
      expect(await post(endpoint.port, Buffer.from(base))).toBe(200);
      expect(calls).toBe(2);
    } finally {
      await server.close();
    }
  });
});

describe('operation-only configured public client', () => {
  it('needs no ambient/carrier/database configuration or constructor I/O and rejects closed-schema violations', async () => {
    const connect = vi.spyOn(Socket.prototype, 'connect').mockImplementation(() => {
      throw Error('NO_IMPLICIT_IO');
    });
    const config = narrowConfig(12002);
    let client: ExternalOperationClient | undefined;
    try {
      client = new ExternalOperationClient(config);
      expect(client.capabilities).toBe('stable_idempotency_and_lookup');
      const maximum = new ExternalOperationClient({
        ...config,
        bindings: Array.from({ length: 64 }, (_, index) => ({
          ...config.bindings[0]!,
          alias: 'binding_' + index,
          accountScope: { tenantId: 'tenant', accountId: 'account_' + index },
        })),
      });
      await maximum.close();
      const invalid: unknown[] = [
        { ...config, schemaVersion: true },
        { ...config, postgresPassword: 'PRIVATE_SENTINEL' },
        { ...config, endpoint: { host: 'localhost', port: 12002 } },
        { ...config, endpoint: { host: '127.0.0.1', port: true } },
        { ...config, endpoint: { host: '127.0.0.1', port: 0 } },
        { ...config, endpoint: { host: '127.0.0.1', port: 65536 } },
        { ...config, bindings: [] },
        { ...config, bindings: Array(65).fill(config.bindings[0]) },
        {
          ...config,
          bindings: [config.bindings[0], { ...config.bindings[0], alias: 'different' }],
        },
        {
          ...config,
          bindings: [
            config.bindings[0],
            { ...config.bindings[0], accountScope: { tenantId: 'other', accountId: 'other' } },
          ],
        },
        { ...config, bindings: [{ ...config.bindings[0], operationBearer: 'x'.repeat(42) }] },
        {
          ...config,
          bindings: [{ ...config.bindings[0], providerScope: { provider: 'fake_sms' } }],
        },
        { ...config, bindings: Array(1) },
      ];
      const getter = vi.fn(() => {
        throw Error('PRIVATE_SENTINEL');
      });
      invalid.push(
        Object.defineProperty({ ...config }, 'profileId', { enumerable: true, get: getter }),
      );
      invalid.push(
        new Proxy(config, {
          ownKeys() {
            throw Error('PRIVATE_SENTINEL');
          },
        }),
      );
      for (const raw of invalid) {
        try {
          new ExternalOperationClient(raw as OperationClientConfig);
          throw Error('accepted_invalid');
        } catch (error) {
          expect(error).toMatchObject({
            code: 'InvalidConfiguration',
            message: 'InvalidConfiguration',
          });
        }
      }
      expect(getter).not.toHaveBeenCalled();
      expect(connect).not.toHaveBeenCalled();
    } finally {
      await client?.close();
      connect.mockRestore();
    }
  });

  it('snapshots the narrow route, endpoint and publisher before caller mutation, then performs useful reads', async () => {
    const { cfg, external } = inputs();
    const server = new ExternalHttpServer(
      cfg,
      external,
      operationLedger(async (input) => ({
        operationKey: input.submission.operationKey,
        scope: input.submission.scope,
        payloadDigest: input.payloadDigest,
        receiptId: randomUUID(),
      })),
    );
    let client: ExternalOperationClient | undefined;
    try {
      const endpoint = await server.start(0),
        config = narrowConfig(endpoint.port);
      client = new ExternalOperationClient(config);
      config.endpoint.port = 1;
      config.profileId = randomUUID();
      config.bindings[0]!.operationBearer = 'x'.repeat(43);
      config.bindings[0]!.caseId = 'foreign';
      config.bindings[0]!.accountScope.accountId = 'foreign';
      await client.preflight('primary', new AbortController().signal);
      const input = prepared('original narrow route');
      expect(await client.accept(input, new AbortController().signal)).toMatchObject({
        operationKey: input.submission.operationKey,
        payloadDigest: input.payloadDigest,
      });
      expect(
        await client.lookup(
          {
            operationKey: input.submission.operationKey,
            scope: input.submission.scope,
            payloadDigest: input.payloadDigest,
          },
          new AbortController().signal,
        ),
      ).toEqual({ status: 'absent' });
    } finally {
      await client?.close();
      await server.close();
    }
  });

  it('contains lookup/accept descriptors and foreign traps before any HTTP or sentinel disclosure', async () => {
    const connect = vi.spyOn(Socket.prototype, 'connect').mockImplementation(() => {
      throw Error('NO_HTTP');
    });
    const client = new ExternalOperationClient(narrowConfig(12002)),
      input = prepared('PRIVATE_BODY_SENTINEL');
    const lookup = {
      operationKey: input.submission.operationKey,
      scope: input.submission.scope,
      payloadDigest: input.payloadDigest,
    };
    const getter = vi.fn(() => {
      throw Error('PRIVATE_GETTER_SENTINEL');
    });
    try {
      for (const raw of [
        Object.defineProperty({ ...lookup }, 'scope', { enumerable: true, get: getter }),
        {
          ...lookup,
          scope: new Proxy(lookup.scope, {
            ownKeys() {
              throw Error('PRIVATE_TRAP_SENTINEL');
            },
          }),
        },
      ])
        expect(() => client.lookup(raw, new AbortController().signal)).toThrowError(
          'InvalidConfiguration',
        );
      for (const raw of [
        Object.defineProperty({ ...input }, 'submission', { enumerable: true, get: getter }),
        {
          ...input,
          submission: new Proxy(input.submission, {
            getOwnPropertyDescriptor() {
              throw Error('PRIVATE_TRAP_SENTINEL');
            },
          }),
        },
      ])
        expect(() => client.accept(raw, new AbortController().signal)).toThrowError(
          'InvalidConfiguration',
        );
      expect(getter).not.toHaveBeenCalled();
      expect(connect).not.toHaveBeenCalled();
      expect(() =>
        client.lookup(
          { ...lookup, scope: { tenantId: 'foreign', accountId: 'foreign' } },
          new AbortController().signal,
        ),
      ).toThrowError('AccessDenied');
      const submission = {
        ...input.submission,
        message: { ...input.submission.message, body: '🧭'.repeat(1024) + 'a' },
      };
      const canonicalPayload = JSON.stringify(submission);
      expect(() =>
        client.accept(
          { submission, canonicalPayload, payloadDigest: digest(canonicalPayload) },
          new AbortController().signal,
        ),
      ).toThrowError('InvalidCommand');
      expect(client.metrics().active).toBe(0);
    } finally {
      await client.close();
      connect.mockRestore();
    }
  });

  it('keeps malformed/wrong receipt acceptance unknown and lookup unavailable, then accepts the exact receipt', async () => {
    let wrong = true,
      calls = 0;
    const peer = createServer((req, res) => {
      const chunks: Buffer[] = [];
      req.on('data', (part: Buffer) => chunks.push(part));
      req.on('end', () => {
        calls++;
        const raw = JSON.parse(Buffer.concat(chunks).toString()) as {
          operationKey?: string;
          scope?: unknown;
          payloadDigest: string;
          canonicalPayload?: string;
        };
        const submission = raw.canonicalPayload
          ? (JSON.parse(raw.canonicalPayload) as { operationKey: string; scope: unknown })
          : raw;
        const receipt = {
          operationKey: submission.operationKey,
          scope: submission.scope,
          payloadDigest: wrong ? 'f'.repeat(64) : raw.payloadDigest,
          receiptId: randomUUID(),
        };
        const reply = Buffer.from(
          JSON.stringify(
            req.url?.endsWith('/lookup')
              ? { schemaVersion: 1, status: 'known', observation: { status: 'accepted', receipt } }
              : { schemaVersion: 1, status: 'known', receipt },
          ),
        );
        res.writeHead(200, {
          'content-type': 'application/json',
          'content-length': reply.length,
          connection: 'close',
          'cache-control': 'no-store',
        });
        res.end(reply);
      });
    });
    peer.maxConnections = 2;
    peer.setTimeout(2000, (socket) => socket.destroy());
    let client: ExternalOperationClient | undefined;
    try {
      await new Promise<void>((resolve) => peer.listen(0, '127.0.0.1', resolve));
      const endpoint = peer.address();
      if (!endpoint || typeof endpoint === 'string') throw Error('missing listener');
      client = new ExternalOperationClient(narrowConfig(endpoint.port));
      const input = prepared('exact original'),
        lookup = {
          operationKey: input.submission.operationKey,
          scope: input.submission.scope,
          payloadDigest: input.payloadDigest,
        };
      await expect(client.accept(input, new AbortController().signal)).rejects.toMatchObject({
        code: 'OutcomeUnknown',
        message: 'OutcomeUnknown',
      });
      await expect(client.lookup(lookup, new AbortController().signal)).rejects.toMatchObject({
        code: 'Unavailable',
        message: 'Unavailable',
      });
      wrong = false;
      await expect(client.accept(input, new AbortController().signal)).resolves.toMatchObject(
        lookup,
      );
      expect(calls).toBe(3);
    } finally {
      await client?.close();
      await new Promise<void>((resolve, reject) =>
        peer.close((error) => (error ? reject(error) : resolve())),
      );
    }
  });

  it('retains both actual socket slots after abort and incomplete close until physical socket settlement', async () => {
    const { cfg, external } = inputs(),
      entered = deferred<void>(),
      release = deferred<void>();
    let arrived = 0,
      hold = true;
    const server = new ExternalHttpServer(
      cfg,
      external,
      operationLedger(async (input) => {
        if (++arrived === 2) entered.resolve();
        await release.promise;
        return {
          operationKey: input.submission.operationKey,
          scope: input.submission.scope,
          payloadDigest: input.payloadDigest,
          receiptId: randomUUID(),
        };
      }),
    );
    const endpoint = await server.start(0),
      client = new ExternalOperationClient(narrowConfig(endpoint.port));
    const physical = new Set<Socket>(),
      destroy = Socket.prototype.destroy;
    const spy = vi.spyOn(Socket.prototype, 'destroy').mockImplementation(function (
      this: Socket,
      error?: Error,
    ) {
      if (hold && this.remotePort === endpoint.port) {
        physical.add(this);
        return this;
      }
      return destroy.call(this, error);
    });
    const aborts = [new AbortController(), new AbortController()];
    const outcomes = aborts.map((controller) =>
      client.accept(prepared('held'), controller.signal).then(
        () => 'known',
        (error: unknown) => error,
      ),
    );
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        entered.promise,
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(Error('entry deadline')), 1500);
        }),
      ]);
      if (timer) clearTimeout(timer);
      for (const controller of aborts) controller.abort();
      expect(await Promise.all(outcomes)).toEqual([
        expect.objectContaining({ code: 'OutcomeUnknown' }),
        expect.objectContaining({ code: 'OutcomeUnknown' }),
      ]);
      expect(client.metrics().active).toBe(2);
      await expect(client.preflight('primary', new AbortController().signal)).rejects.toMatchObject(
        { code: 'Overloaded' },
      );
      await expect(client.close()).rejects.toMatchObject({ code: 'CleanupIncomplete' });
      expect(client.metrics().active).toBe(2);
      expect(physical.size).toBe(2);
      hold = false;
      for (const socket of physical) destroy.call(socket);
      release.resolve();
      await vi.waitFor(() => expect(client.metrics().active).toBe(0));
      await client.close();
      await expect(
        client.lookup(
          {
            operationKey: randomUUID(),
            scope: cfg.bindings[0]!.accountScope,
            payloadDigest: 'a'.repeat(64),
          },
          new AbortController().signal,
        ),
      ).rejects.toMatchObject({ code: 'Closed' });
    } finally {
      if (timer) clearTimeout(timer);
      hold = false;
      release.resolve();
      for (const controller of aborts) controller.abort();
      for (const socket of physical) destroy.call(socket);
      spy.mockRestore();
      await Promise.all(outcomes);
      await client.close();
      await server.close();
    }
  });
});
