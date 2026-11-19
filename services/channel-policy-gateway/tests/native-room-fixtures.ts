/** Explicit fake P2 grants/results, actual control sockets; no SQL/RTC/provider claim. */
import { createHash, randomUUID } from 'node:crypto';
import { createServer, request } from 'node:http';
import { ChannelError } from '@livekit-ecosystem/channel-continuity/postgres';
import type {
  NativePublication,
  NativeBindingReceipt,
} from '@livekit-ecosystem/channel-continuity/native';
import type { ResultNativeView } from '@livekit-ecosystem/channel-continuity/result-receiver';
import { NativeRoomManager } from '../src/native-room-manager.js';
import type {
  RoomOpen,
  RoomCommand,
  NativeRoomRoute,
  RoomRead,
} from '../src/native-room-contract.js';
export const publisher = 'p'.repeat(43);
export const route: NativeRoomRoute = {
  profileId: '11111111-1111-4111-8111-111111111111',
  receiverId: '22222222-2222-4222-8222-222222222222',
  scope: { tenantId: 'tenant_demo', accountId: 'account_demo' },
  caseId: 'case_demo',
  conversationId: 'conversation_demo',
  recipientId: 'recipient_demo',
};
export function deferred<T = void>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
export async function port() {
  const s = createServer();
  await new Promise<void>((r, j) => {
    s.once('error', j);
    s.listen(0, '127.0.0.1', r);
  });
  const a = s.address();
  if (!a || typeof a === 'string') throw new Error('fixture');
  await new Promise<void>((r) => s.close(() => r()));
  return a.port;
}
export async function fixture(recoverBindingId: string | null = null) {
  const state = {
    ready: true,
    published: [] as NativePublication[],
    revoked: [] as string[],
    fenced: [] as string[],
    drained: [] as string[],
    native: [] as [string, string][],
    publishHold: undefined as Promise<void> | undefined,
    revokeHold: undefined as Promise<void> | undefined,
    nativeHold: undefined as Promise<void> | undefined,
    drainHold: undefined as Promise<void> | undefined,
    drainError: undefined as unknown,
    publishError: undefined as unknown,
    revokeError: undefined as unknown,
    nativeError: undefined as unknown,
    view: null as ResultNativeView | null,
    rows: new Map<string, NativeBindingReceipt>(),
    revocations: new Map<string, string>(),
  };
  const manager = new NativeRoomManager(
    route,
    {
      configuration: { schemaVersion: 1, port: await port(), recoverBindingId },
      publisherToken: publisher,
      forbiddenBearers: ['a'.repeat(43), 'w'.repeat(43)],
    },
    {
      async publish(value) {
        state.published.push(value);
        await state.publishHold;
        let receipt = state.rows.get(value.bindingId);
        if (!receipt) {
          receipt = {
            bindingId: value.bindingId,
            bindingDigest: createHash('sha256').update(JSON.stringify(value)).digest('hex'),
            publishedAt: new Date().toISOString(),
            expiresAt: value.expiresAt,
          };
          state.rows.set(value.bindingId, receipt);
        }
        if (state.publishError !== undefined) throw state.publishError;
        return receipt;
      },
      async revoke(id) {
        state.revoked.push(id);
        await state.revokeHold;
        if (state.revokeError !== undefined) throw state.revokeError;
        if (!state.rows.has(id)) throw new ChannelError('NotFound');
        const revokedAt = state.revocations.get(id) ?? new Date().toISOString();
        state.revocations.set(id, revokedAt);
        return { bindingId: id, revokedAt };
      },
      async native(bearer, id) {
        state.native.push([bearer, id]);
        await state.nativeHold;
        if (state.nativeError !== undefined) throw state.nativeError;
        return state.view;
      },
      async fenceInput(binding) {
        state.fenced.push(binding.bindingId);
      },
      async drainInput(binding) {
        state.drained.push(binding.bindingId);
        await state.drainHold;
        if (state.drainError !== undefined) throw state.drainError;
      },
      ready: () => state.ready,
    },
  );
  const ready = await manager.start();
  return {
    manager,
    state,
    ready,
    async cleanup() {
      state.publishError = state.revokeError = state.nativeError = state.drainError = undefined;
      await manager.close();
    },
  };
}
export function opening(epoch: string, expectedGeneration = '0', letter = 'v'): RoomOpen {
  return {
    schemaVersion: 1,
    nodeEpoch: epoch,
    expectedGeneration,
    openId: randomUUID(),
    binding: {
      bindingId: randomUUID(),
      nativeBearer: (letter === 'v' ? 'n' : 'm').repeat(43),
      roomId: 'room_' + letter,
      participantId: 'participant_' + letter,
      agentId: 'agent_demo',
      expiresAt: new Date(Date.now() + 30000).toISOString(),
    },
    roomViewBearer: letter.repeat(43),
  };
}
export function command(value: RoomOpen, generation = '1'): RoomCommand {
  return { schemaVersion: 1, nodeEpoch: value.nodeEpoch, generation, openId: value.openId };
}
export function reading(value: RoomOpen, generation = '1', deliveryId = randomUUID()): RoomRead {
  return { schemaVersion: 1, nodeEpoch: value.nodeEpoch, generation, deliveryId };
}
export function view(deliveryId: string): ResultNativeView {
  const raw = Buffer.from([0, 255, 128, 65]),
    sha = createHash('sha256').update(raw).digest('hex'),
    intent = {
      delivery_id: deliveryId,
      scope: { tenant_id: route.scope.tenantId, account_id: route.scope.accountId },
      work_id: randomUUID(),
      attempt_id: randomUUID(),
      result_sha256: sha,
      receiver_id: route.receiverId,
      recipient_id: route.recipientId,
      body: raw.toString('base64'),
      prepared_at_ms: 1900000000000,
    };
  return {
    schemaVersion: 1,
    intent,
    receipt: {
      delivery_id: deliveryId,
      receipt_id: randomUUID(),
      receiver_id: route.receiverId,
      recipient_id: route.recipientId,
      result_sha256: sha,
      accepted_at_ms: 1900000000001,
    },
    case: {
      schemaVersion: 1,
      source: 'p1_public_v4',
      scope: { ...route.scope },
      caseId: route.caseId,
      conversationId: route.conversationId,
      revision: '1',
      request: {
        schemaVersion: 1,
        kind: 'booking_investigation',
        bookingReference: 'BOOK-01',
        newCheckIn: '2030-12-10',
        investigationConsent: true,
      },
      workflow: { taskId: randomUUID(), state: 'ready', version: '0' },
      intent: { state: 'not_committed', intentId: null },
      mutation: {
        state: 'not_observed',
        outcome: 'not_observed',
        cancellation: 'not_observed',
        effectId: null,
        outcomeEventId: null,
      },
      supplierResult: null,
      sourceRevision: 'a'.repeat(64),
    },
    observed: {
      p2ObservedAt: '2026-11-13T01:02:03.001Z',
      caseObservedAt: '2026-11-13T01:02:03.002Z',
      disclosureAdmittedAt: '2026-11-13T01:02:03.003Z',
      atomic: false,
    },
  };
}
export function post(
  port: number,
  path: string,
  value: unknown,
  token = publisher,
  extra: Record<string, string | string[]> = {},
): Promise<{ status: number; value: unknown; raw: Buffer }> {
  const raw = Buffer.from(typeof value === 'string' ? value : JSON.stringify(value));
  return new Promise((resolve, reject) => {
    const req = request(
      {
        host: '127.0.0.1',
        port,
        path: '/v1/channel-policy/rooms/' + path,
        method: 'POST',
        agent: false,
        headers: {
          authorization: 'Bearer ' + token,
          'content-type': 'application/json',
          'content-length': raw.length,
          connection: 'close',
          ...extra,
        },
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on('data', (part) => chunks.push(Buffer.from(part)));
        res.once('error', reject);
        res.once('end', () => {
          try {
            const raw = Buffer.concat(chunks);
            resolve({ status: res.statusCode!, value: JSON.parse(raw.toString()), raw });
          } catch (e) {
            reject(e);
          }
        });
      },
    );
    req.once('error', reject);
    req.setTimeout(2500, () => req.destroy(new Error('fixture_timeout')));
    req.end(raw);
  });
}
