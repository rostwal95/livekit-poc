/** Real producer envelopes and collector lifetime; no PG/provider qualification. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { OperationsTelemetry } from '../src/operations-telemetry.js';
import { request as httpRequest } from 'node:http';
import {
  CallbackInbox,
  createFakeSmsCallbackIntegration,
  signFakeSmsCallback,
} from '../src/callbacks.js';
import { CallbackStore } from '../src/callback-store.js';
import { ChannelOutbox } from '../src/outbox.js';
import { OutboxStore } from '../src/outbox-store.js';
import { ChannelInbox, SeededAccounts } from '../src/postgres.js';
import { ChannelGateway } from '../src/gateway.js';
import { ChannelDispatcher } from '../src/dispatch.js';
import { createFakeSmsIntegration, signFakeSms } from '../src/security.js';
import type { OperationsSource } from '../src/operations-types.js';
const ID = '11111111-1111-4111-8111-111111111111';
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
describe('existing producer event integration', () => {
  it.each([
    ['callbacks', { event: 'accepted', code: 'ok' }, 'accepted'],
    ['callbacks', { event: 'replayed', code: 'ok' }, 'replayed'],
    ['gateway', { event: 'http', code: 'accepted' }, 'accepted'],
    ['outbox', { event: 'completed', code: 'recovery_unknown' }, 'recovery_unknown'],
    ['gateway', { event: 'poll', code: 'not_due' }, 'not_due'],
    ['gateway', { event: 'poll', code: 'not_needed' }, 'not_needed'],
    ['gateway', { event: 'poll', code: 'busy' }, 'busy'],
    ['gateway', { event: 'http', code: 'communication_known' }, 'communication_known'],
    ['gateway', { event: 'http', code: 'storage_unavailable' }, 'storage_unavailable'],
    ['gateway', { event: 'close', code: 'closed' }, 'closed'],
    ['outbox', { event: 'completed', code: 'queued' }, 'queued'],
    ['outbox', { event: 'completed', code: 'route_selected' }, 'route_selected'],
    ['outbox', { event: 'completed', code: 'unknown' }, 'unknown'],
    ['outbox', { event: 'completed', code: 'accepted_by_provider' }, 'accepted_by_provider'],
    ['outbox', { event: 'completed', code: 'definitive_not_accepted' }, 'definitive_not_accepted'],
    ['outbox', { event: 'completed', code: 'lookup_started' }, 'lookup_started'],
    ['outbox', { event: 'completed', code: 'retry_started' }, 'retry_started'],
    ['outbox', { event: 'completed', code: 'recovery_known' }, 'recovery_known'],
    ['outbox', { event: 'completed', code: 'recovery_held' }, 'recovery_held'],
    ['outbox', { event: 'completed', code: 'recovery_conflicted' }, 'recovery_conflicted'],
    ['outbox', { event: 'completed', code: 'recovery_replayed' }, 'recovery_replayed'],
    ['callbacks', { event: 'rejected', code: 'webhook_rejected' }, 'webhook_rejected'],
    ['dispatch', { event: 'dispatch', code: 'StorageUnavailable' }, 'StorageUnavailable'],
    ['dispatch', { event: 'dispatch', code: 'DispatchClaimLost' }, 'DispatchClaimLost'],
    ['dispatch', { event: 'dispatch', code: 'timeout' }, 'timeout'],
    ['rehydration', { event: 'rejected', code: 'context_unavailable' }, 'context_unavailable'],
  ] as const)('retains the actual %s envelope %j', async (source, payload, code) => {
    const telemetry = new OperationsTelemetry();
    try {
      telemetry.observer(source as OperationsSource)(payload);
      expect(telemetry.snapshot(ID).observations[0]).toMatchObject({
        source,
        code,
        kind: 'producer_log',
        requestId: null,
      });
      expect(telemetry.metrics().observationsDropped).toBe(0);
    } finally {
      await telemetry.close();
    }
  });
  it('drops unsupported input and accessors without copying arbitrary data', async () => {
    const telemetry = new OperationsTelemetry();
    let touched = 0;
    try {
      const observe = telemetry.observer('callbacks');
      observe({ event: 'accepted', code: 'PRIVATE_SENTINEL' });
      observe({
        get event() {
          touched++;
          return 'accepted';
        },
        code: 'ok',
      });
      expect(touched).toBe(0);
      expect(telemetry.snapshot(ID).observations).toEqual([]);
      expect(JSON.stringify(telemetry.snapshot(ID))).not.toContain('PRIVATE_SENTINEL');
    } finally {
      await telemetry.close();
    }
  });
});
describe('reentrant close owns callbacks before invoking user code', () => {
  it('retains an exporter returned after reentrant close and recovers after actual settlement', async () => {
    vi.useFakeTimers({ toFake: ['Date', 'performance', 'setTimeout', 'clearTimeout'] });
    let release = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    let telemetry!: OperationsTelemetry, first: Promise<void> | undefined;
    telemetry = new OperationsTelemetry([], () => {
      first = telemetry.close();
      void first.catch(() => {});
      return held;
    });
    try {
      telemetry.observer('inbox')({ event: 'completed', operation: 'inspect', code: 'known' });
      expect(telemetry.metrics().observerPending).toBe(1);
      await vi.advanceTimersByTimeAsync(1001);
      await expect(first).rejects.toMatchObject({ code: 'unavailable' });
      release();
      await expect(telemetry.close()).resolves.toBeUndefined();
      expect(telemetry.metrics().observerPending).toBe(0);
    } finally {
      release();
      await telemetry.close().catch(() => {});
    }
  });
  it('retains the first reentrant getter and admits no later getter after close', async () => {
    vi.useFakeTimers({ toFake: ['Date', 'performance', 'setTimeout', 'clearTimeout'] });
    let release: (value: unknown) => void = () => {};
    const held = new Promise<unknown>((resolve) => {
      release = resolve;
    });
    let telemetry!: OperationsTelemetry,
      first: Promise<void> | undefined,
      later = 0;
    telemetry = new OperationsTelemetry([
      {
        source: 'inbox',
        read: () => {
          first = telemetry.close();
          void first.catch(() => {});
          return held;
        },
      },
      {
        source: 'inbox_telemetry',
        read: () => {
          later++;
          return { observerPending: 0 };
        },
      },
    ]);
    try {
      telemetry.snapshot(ID);
      expect(later).toBe(0);
      expect(telemetry.metrics().getterPending).toBe(1);
      await vi.advanceTimersByTimeAsync(1001);
      await expect(first).rejects.toMatchObject({ code: 'unavailable' });
      release({ active: 0 });
      await expect(telemetry.close()).resolves.toBeUndefined();
      expect(telemetry.metrics().getterPending).toBe(0);
    } finally {
      release({ active: 0 });
      await telemetry.close().catch(() => {});
    }
  });
});

const PROVIDER = {
    tenantId: 'producer-tenant',
    provider: 'fake_sms',
    providerAccountId: 'carrier',
  },
  SCOPE = { tenantId: PROVIDER.tenantId, accountId: 'account' },
  TOKEN = 'A'.repeat(43),
  PUBLISH = 'P'.repeat(43),
  KEY = Buffer.alloc(32, 7),
  DB = {
    host: '127.0.0.1',
    port: 15432,
    database: 'livekit_lab',
    user: 'livekit_lab',
    password: 'x'.repeat(40),
    schema: 'producer_unit',
  };
const accounts = () =>
  new SeededAccounts([{ ...SCOPE, token: TOKEN, caseId: 'case', conversationId: 'conversation' }]);
const stamp = '2030-01-01T00:00:00.000Z';
const receipt = {
  receiptId: ID,
  eventId: 'event',
  messageId: 'message',
  acceptanceSequence: '1',
  acceptedAt: stamp,
};
async function exchange(
  port: number,
  path: string,
  raw?: Uint8Array,
  headers: Record<string, string> = {},
) {
  return new Promise<number>((resolve, reject) => {
    const req = httpRequest(
      {
        host: '127.0.0.1',
        port,
        path,
        method: raw ? 'POST' : 'GET',
        agent: false,
        headers: {
          Connection: 'close',
          ...(raw
            ? { 'Content-Type': 'application/json', 'Content-Length': String(raw.length) }
            : {}),
          ...headers,
        },
      },
      (res) => {
        res.resume();
        res.once('end', () => resolve(res.statusCode!));
        res.once('error', reject);
      },
    );
    req.setTimeout(1000, () => req.destroy(Error('bounded_local_request')));
    req.once('error', reject);
    req.end(raw);
  });
}
describe('actual public producer emission with only persistence mocked', () => {
  it('records actual callback acceptance and original replay as separate safe events', async () => {
    const telemetry = new OperationsTelemetry();
    const original = {
      receiptId: ID,
      eventId: 'callback',
      attemptId: ID,
      payloadDigest: 'a'.repeat(64),
      acceptedAt: stamp,
    };
    vi.spyOn(CallbackStore.prototype, 'accept')
      .mockResolvedValueOnce({ created: true, receipt: original })
      .mockResolvedValueOnce({ created: false, receipt: original });
    const inbox = new CallbackInbox(
      DB,
      createFakeSmsCallbackIntegration(PROVIDER, KEY),
      accounts(),
      { observer: telemetry.observer('callbacks') },
    );
    try {
      const frame = signFakeSmsCallback(
        {
          schemaVersion: 1,
          eventId: 'callback',
          attemptId: ID,
          providerOperationKey: ID,
          requestDigest: 'b'.repeat(64),
          providerMessageId: 'provider-message',
          state: 'delivered',
          occurredAt: stamp,
        },
        KEY,
        Math.floor(Date.now() / 1000),
        PROVIDER,
      );
      expect(await inbox.accept(frame.raw, frame.headers)).toEqual(original);
      expect(await inbox.accept(frame.raw, frame.headers)).toEqual(original);
      expect(telemetry.snapshot(ID).observations.map((v) => v.code)).toEqual([
        'accepted',
        'replayed',
      ]);
    } finally {
      await inbox.close();
      await telemetry.close();
    }
  });
  it('records actual outbox queue and route selection without collapsing their causes', async () => {
    const telemetry = new OperationsTelemetry();
    vi.spyOn(OutboxStore.prototype, 'enqueue').mockResolvedValue({
      created: true,
      receipt: {
        receiverId: ID,
        receiptId: ID,
        outboundId: ID,
        intentDigest: 'a'.repeat(64),
        bodyDigest: 'b'.repeat(64),
        acceptedAt: stamp,
      },
    });
    vi.spyOn(OutboxStore.prototype, 'selectRoute').mockResolvedValue({
      version: '1',
      senderId: 'sender',
      associationVersion: '1',
      suppressed: false,
    });
    const box = new ChannelOutbox(
      DB,
      createFakeSmsIntegration(PROVIDER, KEY),
      accounts(),
      [{ scope: SCOPE, caseId: 'case', conversationId: 'conversation', token: PUBLISH }],
      { capabilities: 'ordinary_fake_sms_v1', send: () => Promise.reject(Error('not_called')) },
      { observer: telemetry.observer('outbox') },
    );
    try {
      await box.enqueue(PUBLISH, {
        schemaVersion: 1,
        outboundId: ID,
        responseId: 'response',
        body: 'synthetic notice',
      });
      await box.selectRoute(TOKEN, {
        senderId: 'sender',
        associationVersion: '1',
        expectedRouteVersion: '0',
      });
      expect(telemetry.snapshot(ID).observations.map((v) => v.code)).toEqual([
        'queued',
        'route_selected',
      ]);
    } finally {
      await box.close();
      await telemetry.close();
    }
  });
  it('records actual gateway HTTP acceptance and close over a real loopback socket', async () => {
    const telemetry = new OperationsTelemetry();
    vi.spyOn(ChannelDispatcher.prototype, 'eligible').mockResolvedValue([]);
    vi.spyOn(ChannelInbox.prototype, 'acceptSms').mockResolvedValue({ receipt, replayed: false });
    const gateway = new ChannelGateway({
      database: DB,
      integration: createFakeSmsIntegration(PROVIDER, KEY),
      accounts: [{ ...SCOPE, token: TOKEN, caseId: 'case', conversationId: 'conversation' }],
      ports: {
        cases: { inspect: () => Promise.reject(Error('not_called')) },
        agent: { prepare: () => Promise.reject(Error('not_called')) },
        operations: {
          capabilities: 'stable_idempotency_and_lookup',
          lookup: () => Promise.reject(Error('not_called')),
          accept: () => Promise.reject(Error('not_called')),
        },
      },
      options: { observer: telemetry.observer('gateway') },
    });
    try {
      const endpoint = await gateway.listen();
      const frame = signFakeSms(
        {
          schemaVersion: 1,
          eventId: 'event',
          messageId: 'message',
          senderId: 'sender',
          body: 'synthetic',
          occurredAt: stamp,
        },
        KEY,
        Math.floor(Date.now() / 1000),
        PROVIDER,
      );
      expect(
        await exchange(endpoint.port, '/webhooks/fake-sms', frame.raw, {
          'x-p2-timestamp': frame.headers.timestamp,
          'x-p2-signature': frame.headers.signature,
        }),
      ).toBe(200);
      expect(await exchange(endpoint.port, '/not-an-endpoint')).toBe(404);
    } finally {
      await gateway.close();
    }
    try {
      expect(telemetry.snapshot(ID).observations.map((v) => v.code)).toEqual([
        'accepted',
        'not_found',
        'closed',
      ]);
      expect(telemetry.metrics().observationsDropped).toBe(0);
    } finally {
      await telemetry.close();
    }
  });
});

describe('source-specific allowlist and thenable ownership', () => {
  it('drops known codes under the wrong producer shape and arbitrary operation labels', async () => {
    const telemetry = new OperationsTelemetry();
    try {
      telemetry.observer('callbacks')({ event: 'http', code: 'accepted' });
      telemetry.observer('outbox')({ event: 'completed', code: 'StorageUnavailable' });
      telemetry.observer('dispatch')({ event: 'dispatch', code: 'WebhookRejected' });
      telemetry.observer('gateway')({ event: 'poll', code: 'forbidden' });
      telemetry.observer('inbox')({
        event: 'completed',
        operation: 'PRIVATE_OPERATION',
        code: 'known',
      });
      expect(telemetry.snapshot(ID).observations).toEqual([]);
      expect(telemetry.metrics().observationsDropped).toBe(5);
      expect(JSON.stringify(telemetry.snapshot(ID))).not.toContain('PRIVATE_OPERATION');
    } finally {
      await telemetry.close();
    }
  });
  it('registers exporter ownership before invoking a returned thenable accessor', async () => {
    vi.useFakeTimers({ toFake: ['Date', 'performance', 'setTimeout', 'clearTimeout'] });
    let release = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    let first: Promise<void> | undefined, telemetry!: OperationsTelemetry;
    const returned: PromiseLike<void> = {
      get then() {
        first = telemetry.close();
        void first.catch(() => {});
        return held.then.bind(held);
      },
    };
    telemetry = new OperationsTelemetry([], () => returned);
    try {
      telemetry.observer('inbox')({ event: 'completed', operation: 'inspect', code: 'known' });
      expect(telemetry.metrics().observerPending).toBe(1);
      await vi.advanceTimersByTimeAsync(1001);
      await expect(first).rejects.toMatchObject({ code: 'unavailable' });
      release();
      await expect(telemetry.close()).resolves.toBeUndefined();
      expect(telemetry.metrics().observerPending).toBe(0);
    } finally {
      release();
      await telemetry.close().catch(() => {});
    }
  });
});

describe('producer failure status keeps cause semantics', () => {
  it('keeps closing, schema failure and lost claim apart from successful producer output', async () => {
    const telemetry = new OperationsTelemetry();
    try {
      telemetry.observer('gateway')({ event: 'http', code: 'closing' });
      telemetry.observer('dispatch')({ event: 'dispatch', code: 'SchemaMismatch' });
      telemetry.observer('dispatch')({ event: 'dispatch', code: 'DispatchClaimLost' });
      expect(
        telemetry.snapshot(ID).observations.map(({ code, status }) => ({ code, status })),
      ).toEqual([
        { code: 'closing', status: 'closed' },
        { code: 'SchemaMismatch', status: 'error' },
        { code: 'DispatchClaimLost', status: 'unknown' },
      ]);
    } finally {
      await telemetry.close();
    }
  });
});
