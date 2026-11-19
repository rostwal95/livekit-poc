/** Real loopback transport and retained lifecycle owners; persistence is explicitly mocked. */
import { request } from 'node:http';
import { randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const calls = vi.hoisted(() => ({
  accept: vi.fn(),
  history: vi.fn(),
  inspect: vi.fn(),
  reconcile: vi.fn(),
  step: vi.fn(),
}));
vi.mock('../src/postgres.js', async (original) => ({
  ...(await original<object>()),
  ChannelInbox: class {
    acceptNative = calls.accept;
    history = calls.history;
    async close() {}
  },
}));
vi.mock('../src/dispatch.js', () => ({
  ChannelDispatcher: class {
    async eligible() {
      return [];
    }
    inspect = calls.inspect;
    reconcile = calls.reconcile;
    step = calls.step;
    async close() {}
    async quiesce() {}
  },
}));
import { NativeGateway, createNativeIntegration } from '../src/native.js';
import type { DispatchPorts } from '../src/dispatch-types.js';
const provider = { tenantId: 'tenant', provider: 'livekit', providerAccountId: 'native' };
const scope = { tenantId: 'tenant', accountId: 'account' };
const bearer = 'b'.repeat(43),
  token = 'a'.repeat(43),
  binding = randomUUID();
const inputId = randomUUID(),
  receiptId = randomUUID(),
  operationKey = randomUUID();
const ack = {
  schemaVersion: 1,
  bindingId: binding,
  inputId,
  channel: 'web_chat',
  status: 'accepted',
  receiptId,
  operationKey,
  acceptanceSequence: '1',
  code: null,
};
const message = {
  receipt: { receiptId },
  operationKey,
  event: { type: 'text.received', channel: 'web_chat', senderId: binding, providerScope: provider },
};
function observation(state = 'dispatched', possibleExternal = true) {
  return {
    receiptId,
    operationKey,
    state,
    epoch: '1',
    attempts: 1,
    possibleExternal,
    externalReceiptId: state === 'dispatched' ? randomUUID() : null,
    nextAttemptAt: null,
    lastCode: 'none',
    history: [],
  };
}
function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
const gateways: NativeGateway[] = [];
function gateway() {
  const g = new NativeGateway({
    database: {
      host: '127.0.0.1',
      port: 1,
      database: 'livekit_lab',
      user: 'livekit_lab',
      password: 'synthetic',
      schema: 'p2_native_end_' + 'a'.repeat(32),
    },
    integration: createNativeIntegration(provider, [
      {
        token: 'p'.repeat(43),
        scope,
        caseId: 'case',
        conversationId: 'conversation',
      },
    ]),
    accounts: [{ token, ...scope, caseId: 'case', conversationId: 'conversation' }],
    ports: {
      cases: {
        async inspect() {
          throw Error('unused');
        },
      },
      agent: {
        async prepare() {
          throw Error('unused');
        },
      },
      operations: {
        capabilities: 'stable_idempotency_and_lookup',
        async lookup() {
          throw Error('unused');
        },
        async accept() {
          throw Error('unused');
        },
      },
    } as DispatchPorts,
    options: { pollMs: 20, cleanupMs: 200 },
  });
  gateways.push(g);
  return g;
}
async function post(port: number, credential = bearer) {
  const raw = Buffer.from(
    JSON.stringify({
      schemaVersion: 1,
      inputId,
      channel: 'web_chat',
      body: 'investigate',
      roomId: 'room',
      participantId: 'browser',
    }),
  );
  return await new Promise<{ status: number; body: any }>((resolve, reject) => {
    const req = request(
      {
        host: '127.0.0.1',
        port,
        method: 'POST',
        path: '/v1/native/accept',
        headers: {
          authorization: 'Bearer ' + credential,
          'content-type': 'application/json',
          'content-length': raw.length,
          connection: 'close',
        },
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on('data', (c: Buffer) => chunks.push(c));
        res.on('end', () =>
          resolve({ status: res.statusCode!, body: JSON.parse(Buffer.concat(chunks).toString()) }),
        );
      },
    );
    req.on('error', reject);
    req.end(raw);
  });
}
beforeEach(() => {
  vi.resetAllMocks();
  calls.accept.mockResolvedValue(ack);
  calls.history.mockResolvedValue({ messages: [message] });
  calls.inspect.mockImplementation(async () => observation());
  calls.reconcile.mockResolvedValue({ status: 'uncertain', receiptId, operationKey });
});
afterEach(async () => {
  for (const g of gateways.splice(0)) await g.close();
});
describe('room-specific native ingress and accepted-input drain', () => {
  it('reserves an accept owner before reentrant fencing and waits for its actual settlement', async () => {
    const g = gateway(),
      endpoint = await g.listen(),
      entered = deferred(),
      held = deferred();
    let fencing!: Promise<void>,
      settled = false;
    calls.accept.mockImplementation(() => {
      fencing = g.fenceNativeInput(bearer).then(() => {
        settled = true;
      });
      entered.resolve();
      return held.promise.then(() => ack);
    });
    const accepted = post(endpoint.port);
    await entered.promise;
    try {
      await delay(10);
      expect(settled).toBe(false);
      expect(await post(endpoint.port)).toMatchObject({ status: 400, body: { code: 'closed' } });
      expect(calls.accept).toHaveBeenCalledTimes(1);
    } finally {
      held.resolve();
    }
    expect((await accepted).body).toMatchObject({ receiptId, operationKey });
    await fencing;
    expect(settled).toBe(true);
    calls.accept.mockResolvedValue(ack);
    expect((await post(endpoint.port, 'c'.repeat(43))).status).toBe(200);
  });
  it('uses only original receipt lookup for possible acceptance and filters the exact native provider', async () => {
    const g = gateway();
    calls.history.mockResolvedValue({
      messages: [
        message,
        {
          ...message,
          receipt: { receiptId: randomUUID() },
          event: { ...message.event, providerScope: { ...provider, provider: 'fake_sms' } },
        },
      ],
    });
    let known = false;
    calls.inspect.mockImplementation(async () => observation(known ? 'dispatched' : 'uncertain'));
    calls.reconcile.mockImplementation(async () => {
      known = true;
    });
    await g.fenceNativeInput(bearer);
    await g.drainNativeInput(token, binding, bearer);
    expect(calls.reconcile).toHaveBeenCalledExactlyOnceWith(token, receiptId);
    expect(calls.inspect.mock.calls.every((args) => args[1] === receiptId)).toBe(true);
    expect(calls.step).not.toHaveBeenCalled();
    expect(calls.accept).not.toHaveBeenCalled();
  });
  it.each(['blocked', 'exhausted'])(
    'does not invent progress for an original %s input',
    async (state) => {
      const g = gateway();
      calls.inspect.mockResolvedValue(observation(state, false));
      await g.fenceNativeInput(bearer);
      await expect(g.drainNativeInput(token, binding, bearer)).rejects.toMatchObject({
        code: 'cleanup_incomplete',
      });
      expect(calls.reconcile).not.toHaveBeenCalled();
      expect(calls.step).not.toHaveBeenCalled();
    },
  );
  it('requires the existing fence and fails overflow instead of silently dropping accepted history', async () => {
    const g = gateway();
    await expect(g.drainNativeInput(token, binding, bearer)).rejects.toMatchObject({
      code: 'closing',
    });
    await g.fenceNativeInput(bearer);
    calls.history.mockResolvedValue({ messages: [message], nextCursor: '16' });
    await expect(g.drainNativeInput(token, binding, bearer)).rejects.toMatchObject({
      code: 'cleanup_incomplete',
    });
    expect(calls.inspect).not.toHaveBeenCalled();
  });
});
