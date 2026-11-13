import { createHash, randomUUID } from 'node:crypto';
import { describe, expect, it, vi } from 'vitest';
import { ChannelError, type StoredMessage } from '@livekit-ecosystem/channel-continuity/postgres';
import type {
  DispatchObservation,
  PreparedDispatch,
} from '@livekit-ecosystem/channel-continuity/dispatch';
import {
  ChannelPolicySourceReader,
  SourceReadError,
  type SourceReaderConfiguration,
  type SourceId,
} from '../src/source-reader.js';

const scope = Object.freeze({ tenantId: 'demo', accountId: 'traveller' });
const providers = Object.freeze({
  native: Object.freeze({ tenantId: 'demo', provider: 'livekit', providerAccountId: 'local_rtc' }),
  sms: Object.freeze({ tenantId: 'demo', provider: 'fake_sms', providerAccountId: 'local_sms' }),
});
function input(source: SourceId, seq: number, body = 'Review café 🧭.'): StoredMessage {
  const receiptId = randomUUID(),
    eventId = randomUUID(),
    messageId = randomUUID();
  return {
    receipt: {
      receiptId,
      eventId,
      messageId,
      acceptanceSequence: String(seq),
      acceptedAt: '2026-11-13T00:00:00.000Z',
    },
    event: {
      schemaVersion: 1,
      type: 'text.received',
      eventId,
      messageId,
      providerScope: providers[source],
      accountScope: scope,
      conversationId: 'conversation',
      caseId: 'case',
      receivedAt: '2026-11-13T00:00:00.000Z',
      channel: source === 'sms' ? 'sms' : 'web_chat',
      senderId: source === 'sms' ? 'signed_sender' : randomUUID(),
      body,
    },
    operationKey: randomUUID(),
    processingState: 'pending',
    associationVersion: '1',
  };
}
function observation(m: StoredMessage, workId: string | null = null): DispatchObservation {
  return {
    receiptId: m.receipt.receiptId,
    operationKey: m.operationKey,
    state: workId ? 'dispatched' : 'pending',
    epoch: '0',
    attempts: 0,
    possibleExternal: workId !== null,
    externalReceiptId: workId,
    nextAttemptAt: null,
    lastCode: 'pending',
    history: [],
  };
}
function prepared(m: StoredMessage): PreparedDispatch {
  if (m.event.type !== 'text.received') throw new Error('test_input');
  const submission = {
    schemaVersion: 1 as const,
    kind: 'investigation' as const,
    operationKey: m.operationKey,
    scope,
    caseId: 'case',
    caseRevision: '1',
    conversationId: 'conversation',
    message: {
      receiptId: m.receipt.receiptId,
      eventId: m.event.eventId,
      messageId: m.event.messageId,
      senderId: m.event.senderId,
      body: m.event.body,
    },
  };
  const canonicalPayload = JSON.stringify(submission);
  return {
    submission,
    canonicalPayload,
    payloadDigest: createHash('sha256').update(canonicalPayload).digest('hex'),
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
function fixture(messages: StoredMessage[] = [input('native', 1), input('sms', 2)]) {
  const state = new Map(messages.map((m) => [m.receipt.receiptId, observation(m)]));
  const plans = new Map(messages.map((m) => [m.receipt.receiptId, prepared(m)]));
  const history = vi.fn(async () => ({ messages }));
  const inspect = vi.fn(async (_token: string, id: string) => {
    const m = messages.find((m) => m.receipt.receiptId === id);
    if (!m) throw new ChannelError('NotFound');
    return m;
  });
  const nativeInspect = vi.fn(async (_token: string, id: string) => state.get(id)!);
  const smsInspect = vi.fn(async (_token: string, id: string) => state.get(id)!);
  const nativePrepared = vi.fn(async (_token: string, id: string) => plans.get(id) ?? null);
  const smsPrepared = vi.fn(async (_token: string, id: string) => plans.get(id) ?? null);
  const config: SourceReaderConfiguration = {
    profileId: randomUUID(),
    scope,
    caseId: 'case',
    conversationId: 'conversation',
    accountToken: 'a'.repeat(43),
    inbox: { history, inspect },
    sources: {
      native: {
        providerScope: providers.native,
        dispatch: { inspect: nativeInspect },
        prepared: { readPrepared: nativePrepared },
      },
      sms: {
        providerScope: providers.sms,
        dispatch: { inspect: smsInspect },
        prepared: { readPrepared: smsPrepared },
      },
    },
  };
  return {
    config,
    messages,
    state,
    plans,
    history,
    inspect,
    nativeInspect,
    smsInspect,
    nativePrepared,
    smsPrepared,
  };
}
describe('persisted source reads', () => {
  it('scans from zero, preserves a pending gap and discovers later actual work', async () => {
    const f = fixture();
    const current = f.messages[1]!;
    const work = randomUUID();
    f.state.set(current.receipt.receiptId, observation(current, work));
    const reader = new ChannelPolicySourceReader(f.config);
    const page = await reader.discover();
    expect(f.history).toHaveBeenCalledWith('a'.repeat(43), { after: '0', limit: 16 });
    expect(page.items.map((x) => [x.sourceBindingId, x.externalReceiptId])).toEqual([
      ['native', null],
      ['sms', work],
    ]);
    expect(page.overflow).toBe(false);
    expect(page.nextCursor).toBeNull();
    await reader.discover();
    expect(f.history).toHaveBeenCalledTimes(2);
    expect(Object.isFrozen(page.items)).toBe(true);
    await reader.close();
  });
  it.each(['native', 'sms'] as const)(
    'returns exact original %s frame without recalculation',
    async (source) => {
      const f = fixture(),
        m = f.messages.find((m) => m.event.providerScope.provider === providers[source].provider)!;
      const p = f.plans.get(m.receipt.receiptId)!;
      const reader = new ChannelPolicySourceReader(f.config);
      const actual = await reader.prepared(m.receipt.receiptId, source);
      expect(actual?.toString('utf8')).toBe(
        JSON.stringify({
          schemaVersion: 1,
          canonicalPayload: p.canonicalPayload,
          payloadDigest: p.payloadDigest,
        }),
      );
      expect(f.nativeInspect).not.toHaveBeenCalled();
      expect(f.smsInspect).not.toHaveBeenCalled();
      expect(f.history).not.toHaveBeenCalled();
      await reader.close();
    },
  );
  it('returns null for known unprepared input without manufacturing work', async () => {
    const f = fixture();
    f.plans.clear();
    const r = new ChannelPolicySourceReader(f.config);
    expect(await r.prepared(f.messages[0]!.receipt.receiptId, 'native')).toBeNull();
    expect(f.nativePrepared).toHaveBeenCalledOnce();
    expect(f.smsPrepared).not.toHaveBeenCalled();
    await r.close();
  });
  it('selects the owner from stored provider; an SMS label cannot route native data', async () => {
    const f = fixture();
    const r = new ChannelPolicySourceReader(f.config);
    await expect(r.prepared(f.messages[0]!.receipt.receiptId, 'sms')).rejects.toMatchObject({
      code: 'unauthorized',
    });
    expect(f.nativePrepared).not.toHaveBeenCalled();
    expect(f.smsPrepared).not.toHaveBeenCalled();
    await r.close();
  });
  it.each(['tenant', 'account', 'case', 'conversation', 'provider', 'channel'] as const)(
    'rejects foreign %s before source access',
    async (field) => {
      const original = input('native', 1);
      if (original.event.type !== 'text.received') throw Error('test');
      const e = { ...original.event };
      if (field === 'tenant') e.providerScope = { ...e.providerScope, tenantId: 'other' };
      if (field === 'account') e.accountScope = { ...scope, accountId: 'other' };
      if (field === 'case') e.caseId = 'other';
      if (field === 'conversation') e.conversationId = 'other';
      if (field === 'provider')
        e.providerScope = { ...e.providerScope, providerAccountId: 'other' };
      if (field === 'channel') e.channel = 'sms';
      const f = fixture([{ ...original, event: e }]);
      const r = new ChannelPolicySourceReader(f.config);
      await expect(r.discover()).rejects.toMatchObject({
        code: 'unauthorized',
      });
      expect(f.nativeInspect).not.toHaveBeenCalled();
      expect(f.smsInspect).not.toHaveBeenCalled();
      await r.close();
    },
  );
  it.each(['digest', 'body', 'operation', 'receipt', 'revision'] as const)(
    'rejects changed prepared %s',
    async (field) => {
      const f = fixture(),
        m = f.messages[0]!,
        p = prepared(m);
      const candidate = {
        ...p,
        submission: { ...p.submission, message: { ...p.submission.message } },
      };
      if (field === 'digest') candidate.payloadDigest = '0'.repeat(64);
      if (field === 'body') candidate.submission.message.body = 'changed';
      if (field === 'operation') candidate.submission.operationKey = randomUUID();
      if (field === 'receipt') candidate.submission.message.receiptId = randomUUID();
      if (field === 'revision') candidate.submission.caseRevision = '1000001';
      f.plans.set(m.receipt.receiptId, candidate);
      const r = new ChannelPolicySourceReader(f.config);
      await expect(r.prepared(m.receipt.receiptId, 'native')).rejects.toMatchObject({
        code: 'invalid_state',
      });
      await r.close();
    },
  );
  it('preserves scope/not-found errors and hides private dependency text', async () => {
    const f = fixture();
    const r = new ChannelPolicySourceReader(f.config);
    await expect(r.prepared(randomUUID(), 'native')).rejects.toMatchObject({
      code: 'not_found',
      message: 'not_found',
    });
    f.history.mockRejectedValueOnce(new Error('secret_sentinel'));
    await expect(r.discover()).rejects.toMatchObject({
      code: 'unavailable',
      message: 'unavailable',
    });
    f.history.mockRejectedValueOnce(new ChannelError('AccessDenied'));
    await expect(r.discover()).rejects.toMatchObject({ code: 'unauthorized' });
    await r.close();
  });
  it('reports an exact full-page overflow; does not silently omit further work', async () => {
    const f = fixture(Array.from({ length: 16 }, (_, n) => input(n % 2 ? 'sms' : 'native', n + 1)));
    const original = f.config.inbox.history;
    const history: typeof original = async (token, options) => ({
      ...(await original(token, options)),
      nextCursor: '16',
    });
    const r = new ChannelPolicySourceReader({ ...f.config, inbox: { ...f.config.inbox, history } });
    const page = await r.discover();
    expect(page.items).toHaveLength(16);
    expect(page.overflow).toBe(true);
    expect(page.nextCursor).toBe('16');
    await r.close();
  });
  it.each([
    'sequence',
    'duplicate',
    'receipt_join',
    'operation_join',
    'work_duplicate',
    'false_dispatch',
  ] as const)('rejects corrupt %s', async (field) => {
    const first = input('native', 1),
      second = input('sms', 2);
    const f = fixture([first, second]);
    if (field === 'sequence')
      f.messages[1] = { ...second, receipt: { ...second.receipt, acceptanceSequence: '1' } };
    if (field === 'duplicate') f.messages[1] = first;
    if (field === 'receipt_join')
      f.state.set(first.receipt.receiptId, { ...observation(first), receiptId: randomUUID() });
    if (field === 'operation_join')
      f.state.set(first.receipt.receiptId, { ...observation(first), operationKey: randomUUID() });
    if (field === 'work_duplicate') {
      const id = randomUUID();
      f.state.set(first.receipt.receiptId, observation(first, id));
      f.state.set(second.receipt.receiptId, observation(second, id));
    }
    if (field === 'false_dispatch')
      f.state.set(first.receipt.receiptId, { ...observation(first), state: 'dispatched' });
    const r = new ChannelPolicySourceReader(f.config);
    await expect(r.discover()).rejects.toMatchObject({ code: 'invalid_state' });
    await r.close();
  });
  it('retains both actual slots after caller timeouts and retries close after settlement', async () => {
    const f = fixture(),
      held = deferred<{ messages: StoredMessage[] }>();
    f.history.mockImplementation(() => held.promise);
    const r = new ChannelPolicySourceReader(f.config, 20, 20);
    const one = r.discover(),
      two = r.discover();
    await expect(r.discover()).rejects.toMatchObject({ code: 'capacity' });
    const outcomes = await Promise.allSettled([one, two]);
    expect(outcomes.every((x) => x.status === 'rejected')).toBe(true);
    expect(r.metrics().active).toBe(2);
    await expect(r.close()).rejects.toMatchObject({ code: 'cleanup_incomplete' });
    await expect(r.discover()).rejects.toMatchObject({ code: 'closed' });
    held.resolve({ messages: [] });
    await r.close();
    expect(r.metrics().active).toBe(0);
  });
  it('snapshots configured methods and rejects trailing line terminators', async () => {
    const f = fixture();
    const r = new ChannelPolicySourceReader(f.config);
    Object.defineProperty(f.config.inbox, 'history', {
      value: () => Promise.reject(new Error('replaced')),
    });
    await expect(r.discover()).resolves.toMatchObject({ overflow: false });
    await r.close();
    for (const suffix of ['\r', '\n', '\u2028', '\u2029']) {
      expect(
        () => new ChannelPolicySourceReader({ ...fixture().config, caseId: 'case' + suffix }),
      ).toThrow('invalid_input');
    }
  });
  it('rejects extra/accessor configuration and mutating source labels', () => {
    const f = fixture();
    expect(
      () =>
        new ChannelPolicySourceReader({ ...f.config, extra: true } as SourceReaderConfiguration),
    ).toThrow('invalid_input');
    const config = { ...f.config };
    Object.defineProperty(config, 'accountToken', {
      get: () => {
        throw Error('secret_sentinel');
      },
      enumerable: true,
    });
    expect(() => new ChannelPolicySourceReader(config)).toThrow('invalid_input');
    expect(
      () =>
        new ChannelPolicySourceReader({
          ...f.config,
          sources: { ...f.config.sources, native: f.config.sources.sms },
        }),
    ).toThrow('invalid_input');
  });
  it('rejects a coherently regenerated plan with noncanonical revision text', async () => {
    for (const revision of ['1\n', '1\r', '01', '1e0', '1.0']) {
      const f = fixture(),
        m = f.messages[0]!,
        p = prepared(m);
      const submission = { ...p.submission, caseRevision: revision };
      const canonicalPayload = JSON.stringify(submission);
      f.plans.set(m.receipt.receiptId, {
        submission,
        canonicalPayload,
        payloadDigest: createHash('sha256').update(canonicalPayload).digest('hex'),
      });
      const r = new ChannelPolicySourceReader(f.config);
      await expect(r.prepared(m.receipt.receiptId, 'native')).rejects.toMatchObject({
        code: 'invalid_state',
      });
      await r.close();
    }
  });
  it('contains private exceptions from injected nested method getters', () => {
    const f = fixture();
    const inbox = { ...f.config.inbox };
    Object.defineProperty(inbox, 'history', {
      get: () => {
        throw new Error('private_sentinel');
      },
    });
    expect(() => new ChannelPolicySourceReader({ ...f.config, inbox })).toThrow('invalid_input');
    const dispatch = { ...f.config.sources.native.dispatch };
    Object.defineProperty(dispatch, 'inspect', {
      get: () => {
        throw new Error('private_sentinel');
      },
    });
    expect(
      () =>
        new ChannelPolicySourceReader({
          ...f.config,
          sources: { ...f.config.sources, native: { ...f.config.sources.native, dispatch } },
        }),
    ).toThrow('invalid_input');
  });
  it('never invokes error-code getters or reflects malformed dependency codes', async () => {
    const f = fixture(),
      r = new ChannelPolicySourceReader(f.config);
    for (const kind of ['own_getter', 'p2_getter', 'list', 'unknown']) {
      const error =
        kind === 'p2_getter' ? new ChannelError('AccessDenied') : new SourceReadError('capacity');
      if (kind.endsWith('getter'))
        Object.defineProperty(error, 'code', {
          get: () => {
            throw new Error('private_sentinel');
          },
        });
      else
        Object.defineProperty(error, 'code', { value: kind === 'list' ? [] : 'private_sentinel' });
      f.history.mockRejectedValueOnce(error);
      await expect(r.discover()).rejects.toMatchObject({
        code: 'unavailable',
        message: 'unavailable',
      });
      expect(r.metrics().active).toBe(0);
    }
    await expect(r.discover()).resolves.toMatchObject({ overflow: false });
    await r.close();
  });
});
