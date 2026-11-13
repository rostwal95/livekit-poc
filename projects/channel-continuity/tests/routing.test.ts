import { describe, expect, it } from 'vitest';
import { randomUUID } from 'node:crypto';
import {
  RevisionRouter,
  RoutingError,
  encodeRevisionCommand,
  type CaseAuthorityPort,
  type CaseSnapshot,
  type InvestigationRequest,
} from '../src/routing.js';
import { produceTextEvent } from '../src/index.js';
import type { StoredMessage } from '../src/postgres.js';
const REF = { scope: { tenantId: 'tenant-a', accountId: 'account-a' }, caseId: 'case-a' };
const REQUEST: InvestigationRequest = {
  schemaVersion: 1,
  kind: 'booking_investigation',
  bookingReference: 'DEMO-BK-001',
  newCheckIn: '2030-12-11',
  investigationConsent: true,
};
function command(expectedRevision = '0') {
  return encodeRevisionCommand({
    schemaVersion: 1,
    kind: 'case.revise_investigation',
    expectedRevision,
    request: REQUEST,
  });
}
function current(revision = '1'): CaseSnapshot {
  return { ...REF, revision, request: REQUEST, cancelled: false, committed: false };
}
function input(body = command()): StoredMessage {
  const event = produceTextEvent(
    {
      providerScope: { tenantId: 'tenant-a', provider: 'fake_sms', providerAccountId: 'carrier-a' },
      accountScope: REF.scope,
      caseId: REF.caseId,
      conversationId: 'conversation-a',
      eventId: 'event-a',
      messageId: 'message-a',
      senderId: 'sender-a',
      channel: 'sms',
      receivedAt: '2030-01-01T00:00:00.000Z',
      occurredAt: '2099-01-01T00:00:00.000Z',
      body,
    },
    {
      providerScope: { tenantId: 'tenant-a', provider: 'fake_sms', providerAccountId: 'carrier-a' },
      accountScope: REF.scope,
    },
  ).event;
  return {
    event,
    receipt: {
      receiptId: randomUUID(),
      eventId: 'event-a',
      messageId: 'message-a',
      acceptanceSequence: '1',
      acceptedAt: '2030-01-01T00:00:00.000Z',
    },
    operationKey: randomUUID(),
    processingState: 'pending',
    associationVersion: '1',
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  return {
    promise: new Promise<T>((r) => {
      resolve = r;
    }),
    resolve: (value: T) => resolve(value),
  };
}
function fixture(message = input(), authority?: Partial<CaseAuthorityPort>, options = {}) {
  let revised = 0,
    inspected = 0,
    authenticated = 0;
  const router = new RevisionRouter(
    {
      async inspect(token, receiptId) {
        authenticated++;
        if (token !== 'trusted-account' || receiptId !== message.receipt.receiptId)
          throw new Error('sentinel-secret');
        return message;
      },
    },
    {
      async inspect(ref, signal) {
        inspected++;
        return authority?.inspect ? authority.inspect(ref, signal) : current();
      },
      async revise(change, signal) {
        revised++;
        return authority?.revise ? authority.revise(change, signal) : current();
      },
    },
    [REF],
    { observer: () => {}, ...options },
  );
  return {
    router,
    message,
    route: () => router.route('trusted-account', message.receipt.receiptId),
    calls: () => ({ revised, inspected, authenticated }),
  };
}
describe('accepted investigation revision routing', () => {
  it('routes exactly accepted body and verified destination; timestamps do not select revision', async () => {
    const f = fixture(input(), {
      async revise(change) {
        expect(change).toEqual({ ...REF, expectedRevision: '0', request: REQUEST });
        expect(Object.isFrozen(change)).toBe(true);
        return current();
      },
    });
    try {
      expect(await f.route()).toEqual({
        receiptId: f.message.receipt.receiptId,
        operationKey: f.message.operationKey,
        eventId: 'event-a',
        messageId: 'message-a',
        channel: 'sms',
        status: 'revised',
        case: current(),
      });
      expect(f.calls()).toEqual({ revised: 1, inspected: 0, authenticated: 1 });
    } finally {
      await f.router.close();
    }
  });
  it('preserves a known unchanged request without inventing a revision transition', async () => {
    const f = fixture(input(command('1')));
    try {
      expect((await f.route()).status).toBe('unchanged');
    } finally {
      await f.router.close();
    }
  });
  it('keeps conflict distinct and performs no refresh or retry without explicit inspect', async () => {
    const f = fixture(input(), {
      async revise() {
        throw new RoutingError('RevisionConflict');
      },
    });
    try {
      expect((await f.route()).status).toBe('revision_conflict');
      expect(f.calls().revised).toBe(1);
      expect(f.calls().inspected).toBe(0);
      expect(await f.router.inspect('trusted-account', f.message.receipt.receiptId)).toEqual(
        current(),
      );
      expect(f.calls().inspected).toBe(1);
    } finally {
      await f.router.close();
    }
  });
  it.each([
    'yes',
    '{}',
    command().replace('"schemaVersion":1', '"schemaVersion":2'),
    command().replace('"expectedRevision":"0"', '"expectedRevision":0'),
    command().replace('"expectedRevision":"0"', '"expectedRevision":"00"'),
    command().replace('"case.revise_investigation"', '"case.confirm"'),
    command().replace(
      '"kind":"case.revise_investigation"',
      '"kind":"case.revise_investigation","scope":{"tenantId":"other"}',
    ),
    '{"schemaVersion":1,' + command().slice(1),
  ])('clarifies unsupported or ambiguous data without an authority call: %s', async (body) => {
    const f = fixture(input(body));
    try {
      const result = await f.route();
      expect(result.status).toBe(body === command() ? 'revised' : 'clarification_required');
      expect(f.calls().revised).toBe(body === command() ? 1 : 0);
    } finally {
      await f.router.close();
    }
  });
  it('requires actual input authentication before authority access or disclosure', async () => {
    const f = fixture();
    try {
      await expect(f.router.route('forged-account', f.message.receipt.receiptId)).rejects.toEqual(
        new RoutingError('AccessDenied'),
      );
      expect(f.calls().revised).toBe(0);
    } finally {
      await f.router.close();
    }
  });
  it('rejects a cross-account accepted value independently of the input adapter', async () => {
    const message = input();
    const bad = {
      ...message,
      event: { ...message.event, accountScope: { tenantId: 'tenant-a', accountId: 'other' } },
    } as StoredMessage;
    const f = fixture(bad);
    try {
      await expect(f.route()).rejects.toEqual(new RoutingError('AccessDenied'));
      expect(f.calls().revised).toBe(0);
    } finally {
      await f.router.close();
    }
  });
  it('treats mismatched or unexpected responses after possible revision as unknown', async () => {
    const f = fixture(input(), {
      async revise() {
        return { ...current(), caseId: 'different' };
      },
    });
    try {
      expect((await f.route()).status).toBe('outcome_unknown');
      expect(f.calls().revised).toBe(1);
    } finally {
      await f.router.close();
    }
  });
  it('contains dependency exception text and never retries an unknown command', async () => {
    const f = fixture(input(), {
      async revise() {
        throw new Error('sentinel-secret-and-url');
      },
    });
    try {
      expect(JSON.stringify(await f.route())).not.toContain('sentinel');
      expect(f.calls().revised).toBe(1);
      expect(f.router.metrics().unknown).toBe(1);
    } finally {
      await f.router.close();
    }
  });
  it('retains actual ignored adapter ownership after timeout and incomplete close', async () => {
    const held = deferred<CaseSnapshot>(),
      entered = deferred<void>();
    const f = fixture(
      input(),
      {
        async revise() {
          entered.resolve();
          return held.promise;
        },
      },
      { maxActive: 1, timeoutMs: 30, cleanupMs: 20 },
    );
    const pending = f.route();
    await entered.promise;
    expect((await pending).status).toBe('outcome_unknown');
    expect(f.router.metrics().active).toBe(1);
    await expect(f.route()).rejects.toEqual(new RoutingError('Overloaded'));
    await expect(f.router.close()).rejects.toEqual(new RoutingError('CleanupIncomplete'));
    expect(f.router.metrics().active).toBe(1);
    held.resolve(current());
    await f.router.close();
    expect(f.router.metrics().active).toBe(0);
    await expect(f.route()).rejects.toEqual(new RoutingError('Closed'));
  });
  it('keeps abort-before-call safe and abort-after-call uncertain', async () => {
    const f = fixture(),
      before = new AbortController();
    before.abort();
    await expect(
      f.router.route('trusted-account', f.message.receipt.receiptId, before.signal),
    ).rejects.toEqual(new RoutingError('Unavailable'));
    expect(f.calls().authenticated).toBe(0);
    await f.router.close();
    const held = deferred<CaseSnapshot>(),
      entered = deferred<void>(),
      g = fixture(input(), {
        async revise() {
          entered.resolve();
          return held.promise;
        },
      });
    const after = new AbortController(),
      pending = g.router.route('trusted-account', g.message.receipt.receiptId, after.signal);
    await entered.promise;
    after.abort();
    expect((await pending).status).toBe('outcome_unknown');
    expect(g.router.metrics().active).toBe(1);
    held.resolve(current());
    await g.router.close();
  });
  it('contains malformed adapter error codes without executing code accessors', async () => {
    let accessed = false;
    const error = new RoutingError('RevisionConflict');
    Object.defineProperty(error, 'code', {
      get: () => {
        accessed = true;
        throw new Error('sentinel-private');
      },
    });
    const f = fixture(input(), {
      async revise() {
        throw error;
      },
    });
    try {
      expect((await f.route()).status).toBe('outcome_unknown');
      expect(accessed).toBe(false);
    } finally {
      await f.router.close();
    }
  });
  it('does not deliver overdue known success after a blocking observer', async () => {
    const f = fixture(input(), undefined, {
      timeoutMs: 20,
      observer: () => {
        const end = performance.now() + 25;
        while (performance.now() < end) {
          /* controlled observer */
        }
      },
    });
    try {
      expect((await f.route()).status).toBe('outcome_unknown');
      expect(f.router.metrics().revised).toBe(1);
    } finally {
      await f.router.close();
    }
  });
  it('rejects malformed abort signals before allocating or authenticating', async () => {
    const f = fixture();
    expect(() =>
      f.router.route('trusted-account', f.message.receipt.receiptId, {} as AbortSignal),
    ).toThrow(new RoutingError('InvalidCommand'));
    expect(f.router.metrics().active).toBe(0);
    expect(f.calls().authenticated).toBe(0);
    const real = new AbortController().signal;
    Object.defineProperty(real, 'addEventListener', {
      value: () => {
        throw new Error('must-not-call');
      },
    });
    expect(
      (await f.router.route('trusted-account', f.message.receipt.receiptId, real)).status,
    ).toBe('revised');
    await f.router.close();
  });
  it('does not coerce a malformed processing state object', async () => {
    let coerced = false;
    const message = input();
    const state = {
      toString() {
        coerced = true;
        return 'pending';
      },
    };
    const f = fixture({ ...message, processingState: state } as unknown as StoredMessage);
    try {
      await expect(f.route()).rejects.toEqual(new RoutingError('Unavailable'));
      expect(coerced).toBe(false);
      expect(f.calls().revised).toBe(0);
    } finally {
      await f.router.close();
    }
  });
  it('does not execute getters in adapter event data', async () => {
    const message = input();
    let accessed = false;
    const event = { ...message.event };
    Object.defineProperty(event, 'body', {
      get: () => {
        accessed = true;
        return command();
      },
      enumerable: true,
    });
    const f = fixture({ ...message, event } as StoredMessage);
    try {
      await expect(f.route()).rejects.toEqual(new RoutingError('Unavailable'));
      expect(accessed).toBe(false);
      expect(f.calls().revised).toBe(0);
    } finally {
      await f.router.close();
    }
  });
  it('contains throwing and bounded asynchronous telemetry', async () => {
    const f = fixture(input(), undefined, {
      observer: () => {
        throw new Error('secret');
      },
    });
    try {
      expect((await f.route()).status).toBe('revised');
      expect(f.router.metrics().telemetryFailures).toBe(1);
    } finally {
      await f.router.close();
    }
  });
});
