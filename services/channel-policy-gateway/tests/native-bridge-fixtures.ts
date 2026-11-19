/** Actual public native HTTP client/worker sockets; P2 grant storage is explicitly fake. */
import { createHash, randomUUID } from 'node:crypto';
import { createServer } from 'node:http';
import type { Socket } from 'node:net';
import type { DispatchPorts } from '@livekit-ecosystem/channel-continuity/dispatch';
import { ChannelError } from '@livekit-ecosystem/channel-continuity/postgres';
import type { NativeBindingReceipt } from '@livekit-ecosystem/channel-continuity/native';
import { NativeRoomManager } from '../src/native-room-manager.js';
import type { NativeBridgeConfiguration, RoomAttach } from '../src/native-bridge-contract.js';
import { route, publisher, port, opening, command, deferred } from './native-room-fixtures.js';
export { route, publisher, port, opening, command, deferred };
export const provider = Object.freeze({
  tenantId: route.scope.tenantId,
  provider: 'livekit',
  providerAccountId: 'joined_rtc',
});
export async function worker() {
  const state = {
    requests: [] as {
      authorization: string | undefined;
      raw: Buffer;
      value: Record<string, any>;
    }[],
    hold: undefined as Promise<void> | undefined,
    wrongDigest: false,
    wrongRevision: false,
  };
  const sockets = new Set<Socket>(),
    tasks = new Set<Promise<void>>();
  const server = createServer((req, res) => {
    const actual = (async () => {
      const parts: Buffer[] = [];
      for await (const part of req) {
        parts.push(Buffer.from(part));
        if (parts.reduce((n, p) => n + p.length, 0) > 32768) throw new Error('fixture bodycap');
      }
      const raw = Buffer.concat(parts),
        value = JSON.parse(raw.toString()) as Record<string, any>;
      state.requests.push({ authorization: req.headers.authorization, raw, value });
      await state.hold;
      const body = Buffer.from(
        JSON.stringify({
          schemaVersion: 1,
          kind: 'agent.prepared',
          inputDigest: state.wrongDigest
            ? '0'.repeat(64)
            : createHash('sha256').update(raw).digest('hex'),
          decision: {
            kind: 'investigation',
            source: 'scripted',
            caseRevision: state.wrongRevision ? '2' : value.context.caseRevision,
          },
        }),
      );
      res.writeHead(200, {
        'content-type': 'application/json',
        'content-length': body.length,
        connection: 'close',
      });
      res.end(body);
    })().catch(() => {
      res.destroy();
    });
    tasks.add(actual);
    void actual.then(() => tasks.delete(actual));
  });
  server.on('connection', (s) => {
    sockets.add(s);
    s.once('close', () => sockets.delete(s));
  });
  await new Promise<void>((r, j) => {
    server.once('error', j);
    server.listen(0, '127.0.0.1', r);
  });
  const a = server.address();
  if (!a || typeof a === 'string') throw new Error('fixture');
  return {
    state,
    port: a.port,
    async close() {
      for (const s of sockets) s.destroy();
      await new Promise<void>((r) => server.close(() => r()));
      await Promise.allSettled([...tasks]);
    },
  };
}
export async function bridgeFixture() {
  const w = await worker(),
    configuration: NativeBridgeConfiguration = {
      schemaVersion: 1,
      prepareEndpoint: { host: '127.0.0.1', port: w.port },
      rehydrationPort: await port(),
    };
  const rows = new Map<string, NativeBindingReceipt>(),
    revoked: string[] = [];
  const manager = new NativeRoomManager(
    route,
    {
      configuration: { schemaVersion: 1, port: await port(), recoverBindingId: null },
      publisherToken: publisher,
      forbiddenBearers: ['a'.repeat(43)],
    },
    {
      async publish(x) {
        const receipt = Object.freeze({
          bindingId: x.bindingId,
          bindingDigest: createHash('sha256').update(JSON.stringify(x)).digest('hex'),
          publishedAt: new Date().toISOString(),
          expiresAt: x.expiresAt,
        });
        rows.set(x.bindingId, receipt);
        return receipt;
      },
      async revoke(id) {
        if (!rows.has(id)) throw new ChannelError('NotFound');
        revoked.push(id);
        return { bindingId: id, revokedAt: new Date().toISOString() };
      },
      async native() {
        return null;
      },
      async fenceInput() {},
      async drainInput() {},
      ready: () => true,
    },
    configuration,
  );
  const ready = await manager.start();
  return {
    manager,
    w,
    configuration,
    ready,
    revoked,
    async close() {
      await manager.close();
      await w.close();
    },
  };
}
export function attach(a: ReturnType<typeof opening>, generation = '1'): RoomAttach {
  return {
    ...command(a, generation),
    bindingId: a.binding.bindingId,
    prepareBearer: 's'.repeat(43),
  };
}
export function input(bindingId: string): Parameters<DispatchPorts['agent']['prepare']>[0] {
  const eventId = randomUUID(),
    messageId = randomUUID(),
    now = new Date().toISOString();
  return {
    message: {
      receipt: {
        receiptId: randomUUID(),
        eventId,
        messageId,
        acceptanceSequence: '1',
        acceptedAt: now,
      },
      event: {
        schemaVersion: 1,
        type: 'text.received',
        eventId,
        messageId,
        providerScope: provider,
        accountScope: route.scope,
        conversationId: route.conversationId,
        caseId: route.caseId,
        receivedAt: now,
        channel: 'web_chat',
        senderId: bindingId,
        body: 'investigate',
      },
      operationKey: randomUUID(),
      processingState: 'pending',
      associationVersion: '1',
    },
    currentCase: {
      scope: route.scope,
      caseId: route.caseId,
      revision: '1',
      source: 'synthetic_read_only',
    },
  };
}
export async function until(test: () => boolean) {
  for (let i = 0; i < 200; i++) {
    if (test()) return;
    await new Promise<void>((r) => setTimeout(r, 2));
  }
  throw new Error('fixture wait');
}
