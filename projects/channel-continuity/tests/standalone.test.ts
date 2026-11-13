import { describe, expect, it } from 'vitest';
import { produceTextEvent } from '../src/index.js';
import { ChannelError, type StoredMessage } from '../src/postgres.js';
import {
  createStandaloneExample,
  StandaloneError,
  type StandaloneBinding,
  type StandalonePorts,
  type StandaloneCase,
} from '../src/standalone.js';
const BINDING: StandaloneBinding = {
  providerScope: { tenantId: 'tenant-a', provider: 'fake_sms', providerAccountId: 'carrier-a' },
  accountScope: { tenantId: 'tenant-a', accountId: 'account-a' },
  conversationId: 'conversation-a',
  caseId: 'case-a',
};
const RECEIPT = Object.freeze({
  receiptId: '12345678-1234-4234-8234-123456789abc',
  eventId: 'event-a',
  messageId: 'message-a',
  acceptanceSequence: '1',
  acceptedAt: '2030-01-01T00:00:00.000Z',
});
const KEY = '22345678-1234-4234-8234-123456789abc';
const MESSAGE: StoredMessage = {
  receipt: RECEIPT,
  event: produceTextEvent(
    {
      eventId: RECEIPT.eventId,
      providerScope: BINDING.providerScope,
      accountScope: BINDING.accountScope,
      conversationId: BINDING.conversationId,
      caseId: BINDING.caseId,
      receivedAt: RECEIPT.acceptedAt,
      channel: 'sms',
      messageId: RECEIPT.messageId,
      senderId: 'sender-a',
      body: 'Read-only synthetic request',
    },
    { providerScope: BINDING.providerScope, accountScope: BINDING.accountScope },
  ).event,
  operationKey: KEY,
  processingState: 'pending',
  associationVersion: '1',
};
const CURRENT: StandaloneCase = {
  scope: BINDING.accountScope,
  caseId: BINDING.caseId,
  revision: '1',
  source: 'synthetic_read_only',
};
function fixtures(overrides: Partial<StandalonePorts> = {}) {
  const calls: string[] = [];
  const ports: StandalonePorts = {
    inbox: {
      async acceptSms() {
        calls.push('accept');
        return { receipt: RECEIPT, replayed: false };
      },
      async inspect() {
        calls.push('inspect');
        return MESSAGE;
      },
    },
    cases: {
      async inspect() {
        calls.push('case');
        return CURRENT;
      },
    },
    agent: {
      async preview(input) {
        calls.push('agent');
        return {
          kind: 'investigation',
          source: 'scripted',
          caseRevision: input.currentCase.revision,
        };
      },
    },
    operations: {
      async inspectPending(input) {
        calls.push('operation_inspection');
        return { operationKey: input.operationKey, state: 'not_executed', durable: false };
      },
    },
    ...overrides,
  };
  return { ports, calls };
}
async function rejected(work: Promise<unknown>, code: string): Promise<void> {
  try {
    await work;
    throw new Error('Expected rejection');
  } catch (error) {
    expect(error).toBeInstanceOf(StandaloneError);
    expect((error as StandaloneError).code).toBe(code);
    expect((error as Error).message).toBe(code);
  }
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
const tick = () => new Promise<void>((resolve) => setImmediate(resolve));
function blockFor(milliseconds: number): void {
  const end = performance.now() + milliseconds;
  while (performance.now() < end) {
    /* Deliberately delay timers with a finite trusted test callback. */
  }
}

describe('explicit standalone input and read-only preview', () => {
  it('refuses every nonpending dispatch state before advertising not_executed', async () => {
    const f = fixtures();
    const example = createStandaloneExample(f.ports, BINDING);
    for (const processingState of [
      'running',
      'dispatched',
      'blocked',
      'exhausted',
      'uncertain',
    ] as const) {
      f.ports.inbox.inspect = async () => ({ ...MESSAGE, processingState });
      await rejected(example.preview('token', RECEIPT.receiptId), 'InvalidAdapterResult');
    }
    expect(f.calls).not.toContain('operation_inspection');
    f.ports.inbox.inspect = async () => MESSAGE;
    expect((await example.preview('token', RECEIPT.receiptId)).execution).toBe('not_executed');
    await example.close();
  });
  it('requires all adapters before any intake and preserves a useful valid path', async () => {
    const f = fixtures();
    for (const name of ['inbox', 'cases', 'agent', 'operations']) {
      const incomplete = { ...f.ports };
      delete (incomplete as unknown as Record<string, unknown>)[name];
      expect(() => createStandaloneExample(incomplete as StandalonePorts, BINDING)).toThrow(
        'MissingAdapter',
      );
    }
    expect(f.calls).toEqual([]);
    const example = createStandaloneExample(f.ports, BINDING);
    expect(
      await example.accept(Buffer.from('fixture'), { timestamp: '0', signature: 'fixture' }),
    ).toEqual({ receipt: RECEIPT, replayed: false });
    const preview = await example.preview('synthetic-token', RECEIPT.receiptId);
    expect(f.calls).toEqual(['accept', 'inspect', 'case', 'agent', 'operation_inspection']);
    expect(preview).toMatchObject({
      receipt: RECEIPT,
      operationKey: KEY,
      processingState: 'pending',
      execution: 'not_executed',
      operation: { operationKey: KEY, state: 'not_executed', durable: false },
    });
    expect(Object.isFrozen(preview)).toBe(true);
    expect(example.activePreviews).toBe(0);
    await example.close();
  });
  it('keeps observed acceptance separate from a failed later adapter preview', async () => {
    const f = fixtures({
      agent: {
        async preview() {
          throw new Error('PRIVATE_ADAPTER_SENTINEL');
        },
      },
    });
    const example = createStandaloneExample(f.ports, BINDING);
    const accepted = await example.accept(Buffer.from('fixture'), {
      timestamp: '0',
      signature: 'fixture',
    });
    await rejected(
      example.preview('synthetic-token', accepted.receipt.receiptId),
      'PreviewUnavailable',
    );
    expect(accepted.receipt).toEqual(RECEIPT);
    expect(f.calls.filter((name) => name === 'accept')).toHaveLength(1);
    expect(f.calls).not.toContain('operation_inspection');
    await example.close();
  });
  it('preserves safe intake outcomes and never interprets unknown acknowledgement as rejection', async () => {
    const unknown = fixtures({
      inbox: {
        async acceptSms() {
          throw new Error('PRIVATE_STORAGE_SENTINEL');
        },
        async inspect() {
          return MESSAGE;
        },
      },
    });
    const example = createStandaloneExample(unknown.ports, BINDING);
    await expect(
      example.accept(Buffer.from('fixture'), { timestamp: '0', signature: 'fixture' }),
    ).rejects.toMatchObject({ code: 'AcknowledgementUnknown', message: 'AcknowledgementUnknown' });
    await example.close();
    const conflict = fixtures({
      inbox: {
        async acceptSms() {
          throw new ChannelError('IdentityConflict');
        },
        async inspect() {
          return MESSAGE;
        },
      },
    });
    const other = createStandaloneExample(conflict.ports, BINDING);
    await expect(
      other.accept(Buffer.from('fixture'), { timestamp: '0', signature: 'fixture' }),
    ).rejects.toMatchObject({ code: 'IdentityConflict' });
    await other.close();
  });
  it.each([
    { ...CURRENT, scope: { ...CURRENT.scope, accountId: 'another-account' } },
    { ...CURRENT, caseId: 'another-case' },
    { ...CURRENT, revision: '0' },
    { ...CURRENT, source: 'unverified' },
  ])(
    'rejects mismatched or unqualified case reply %# without progressing agent/operation',
    async (reply) => {
      const f = fixtures({
        cases: {
          async inspect() {
            return reply as StandaloneCase;
          },
        },
      });
      const example = createStandaloneExample(f.ports, BINDING);
      await rejected(example.preview('synthetic-token', RECEIPT.receiptId), 'InvalidAdapterResult');
      expect(f.calls).not.toContain('agent');
      expect(f.calls).not.toContain('operation_inspection');
      await example.close();
    },
  );
  it('rejects wrong agent revision and operation key/claimed execution', async () => {
    const wrongAgent = fixtures({
      agent: {
        async preview() {
          return { kind: 'investigation', source: 'scripted', caseRevision: '2' };
        },
      },
    });
    const a = createStandaloneExample(wrongAgent.ports, BINDING);
    await rejected(a.preview('token', RECEIPT.receiptId), 'InvalidAdapterResult');
    await a.close();
    for (const reply of [
      { operationKey: RECEIPT.receiptId, state: 'not_executed', durable: false },
      { operationKey: KEY, state: 'executed', durable: true },
    ]) {
      const f = fixtures({
        operations: {
          async inspectPending() {
            return reply as unknown as Awaited<
              ReturnType<StandalonePorts['operations']['inspectPending']>
            >;
          },
        },
      });
      const b = createStandaloneExample(f.ports, BINDING);
      await rejected(b.preview('token', RECEIPT.receiptId), 'InvalidAdapterResult');
      await b.close();
    }
  });
  it('checks inbox receipt identity and scope before calling case adapters', async () => {
    const f = fixtures({
      inbox: {
        async acceptSms() {
          return { receipt: RECEIPT, replayed: false };
        },
        async inspect() {
          return { ...MESSAGE, receipt: { ...RECEIPT, receiptId: KEY } };
        },
      },
    });
    const example = createStandaloneExample(f.ports, BINDING);
    await rejected(example.preview('token', RECEIPT.receiptId), 'InvalidAdapterResult');
    expect(f.calls).toEqual([]);
    await example.close();
  });
  it('rejects reply getters without invoking arbitrary serialization', async () => {
    let invoked = false;
    const bad = Object.defineProperty({ ...CURRENT }, 'revision', {
      enumerable: true,
      get() {
        invoked = true;
        throw new Error('PRIVATE_GETTER_SENTINEL');
      },
    });
    const f = fixtures({
      cases: {
        async inspect() {
          return bad;
        },
      },
    });
    const example = createStandaloneExample(f.ports, BINDING);
    await rejected(example.preview('token', RECEIPT.receiptId), 'InvalidAdapterResult');
    expect(invoked).toBe(false);
    await example.close();
  });
  it('retains timed-out adapter ownership, rejects saturation and permits later valid progress', async () => {
    const entered = deferred<void>(),
      release = deferred<StandaloneCase>();
    let first = true;
    const f = fixtures({
      cases: {
        async inspect() {
          if (first) {
            first = false;
            entered.resolve();
            return await release.promise;
          }
          return CURRENT;
        },
      },
    });
    const example = createStandaloneExample(f.ports, BINDING, {
      maxPreviews: 1,
      previewTimeoutMs: 20,
      cleanupTimeoutMs: 100,
    });
    const pending = example.preview('token', RECEIPT.receiptId);
    await entered.promise;
    await rejected(pending, 'PreviewUnavailable');
    expect(example.activePreviews).toBe(1);
    await rejected(example.preview('token', RECEIPT.receiptId), 'Overloaded');
    release.resolve(CURRENT);
    await tick();
    expect(example.activePreviews).toBe(0);
    expect(f.calls).not.toContain('agent');
    expect((await example.preview('token', RECEIPT.receiptId)).execution).toBe('not_executed');
    await example.close();
  });
  it('reports incomplete cleanup rather than freeing an ignored adapter slot', async () => {
    const entered = deferred<void>(),
      release = deferred<StandaloneCase>();
    const f = fixtures({
      cases: {
        async inspect() {
          entered.resolve();
          return await release.promise;
        },
      },
    });
    const example = createStandaloneExample(f.ports, BINDING, {
      maxPreviews: 1,
      previewTimeoutMs: 20,
      cleanupTimeoutMs: 20,
    });
    const pending = example.preview('token', RECEIPT.receiptId);
    await entered.promise;
    await rejected(pending, 'PreviewUnavailable');
    await rejected(example.close(), 'CleanupIncomplete');
    expect(example.activePreviews).toBe(1);
    release.resolve(CURRENT);
    await tick();
    expect(example.activePreviews).toBe(0);
    await rejected(example.preview('token', RECEIPT.receiptId), 'Closed');
  });
  it('rejects late success when a bounded callback delays the deadline timer', async () => {
    const f = fixtures({
      cases: {
        async inspect() {
          blockFor(35);
          return CURRENT;
        },
      },
    });
    const example = createStandaloneExample(f.ports, BINDING, {
      maxPreviews: 1,
      previewTimeoutMs: 20,
      cleanupTimeoutMs: 100,
    });
    await rejected(example.preview('token', RECEIPT.receiptId), 'PreviewUnavailable');
    expect(f.calls).not.toContain('agent');
    await example.close();
  });
  it('rejects late cleanup settlement even when its timer was delayed', async () => {
    const entered = deferred<void>();
    const f = fixtures({
      cases: {
        async inspect(_reference, signal) {
          entered.resolve();
          return await new Promise<StandaloneCase>((resolve) =>
            signal.addEventListener(
              'abort',
              () => {
                blockFor(35);
                resolve(CURRENT);
              },
              { once: true },
            ),
          );
        },
      },
    });
    const example = createStandaloneExample(f.ports, BINDING, {
      maxPreviews: 1,
      previewTimeoutMs: 500,
      cleanupTimeoutMs: 20,
    });
    const pending = example.preview('token', RECEIPT.receiptId);
    const observed = pending.catch((error) => error);
    await entered.promise;
    const close = example.close();
    expect(example.close()).toBe(close);
    await rejected(close, 'CleanupIncomplete');
    expect(await observed).toMatchObject({ code: 'PreviewUnavailable' });
    expect(example.activePreviews).toBe(0);
  });
});
