import { describe, it, expect } from 'vitest';
import { randomUUID } from 'node:crypto';
import { produceTextEvent } from '../src/index.js';
import {
  ConfirmationRouter,
  ConfirmationError,
  encodeConfirmation,
  quoteDigest,
  type ExactConfirmation,
  type ConfirmationReceipt,
  type StoredPrompt,
  type ConfirmationOptions,
} from '../src/confirmation.js';
import type { StoredMessage } from '../src/postgres.js';
const REF = { scope: { tenantId: 'tenant-a', accountId: 'account-a' }, caseId: 'case-a' };
const PROVIDER = { tenantId: 'tenant-a', provider: 'fake_sms', providerAccountId: 'carrier-a' };
const QUOTE_ID = '6ba7b811-9dad-51d1-80b4-00c04fd430c8';
// Deliberately above JS safe integer: the router must retain these opaque bytes.
const QUOTE = '{"expected_supplier_revision":9223372036854775806,"revision":2,"schema_version":2}';
const PROMPT: StoredPrompt = {
  schemaVersion: 1,
  ...REF,
  conversationId: 'conversation-a',
  responseId: 'prompt-a',
  revision: '2',
  quoteId: QUOTE_ID,
  quoteDigest: quoteDigest(QUOTE),
  quoteJson: QUOTE,
  registeredAt: '2030-01-01T00:00:00.000Z',
};
function deferred<T>() {
  let resolve!: (value: T) => void;
  return {
    promise: new Promise<T>((r) => {
      resolve = r;
    }),
    resolve: (value: T) => resolve(value),
  };
}
function input(body = 'YES prompt-a', links: Record<string, unknown> = {}): StoredMessage {
  const event = produceTextEvent(
    {
      providerScope: PROVIDER,
      accountScope: REF.scope,
      caseId: REF.caseId,
      conversationId: 'conversation-a',
      receivedAt: '2030-01-01T00:00:00.000Z',
      occurredAt: '2099-01-01T00:00:00.000Z',
      eventId: 'event-a',
      messageId: 'message-a',
      senderId: 'sender-a',
      channel: 'sms',
      body,
      ...links,
    },
    { providerScope: PROVIDER, accountScope: REF.scope },
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
function receipt(command: ExactConfirmation): ConfirmationReceipt {
  return {
    scope: command.scope,
    caseId: command.caseId,
    commandId: command.commandId,
    revision: command.expectedRevision,
    quoteId: command.quoteId,
    quoteDigest: command.quoteDigest,
    intentId: '11111111-1111-4111-8111-111111111111',
    effectId: '22222222-2222-4222-8222-222222222222',
  };
}
function fixture(
  message = input(),
  options: ConfirmationOptions = {},
  overrides: {
    find?: () => Promise<StoredPrompt | null>;
    confirm?: (command: ExactConfirmation) => Promise<ConfirmationReceipt>;
    current?: () => Promise<StoredMessage>;
  } = {},
) {
  const calls = { retained: 0, current: 0, prompts: 0, authority: 0 };
  let revoked = false;
  const seen: ExactConfirmation[] = [];
  const router = new ConfirmationRouter(
    {
      async inspect(token, id) {
        calls.retained++;
        if (token !== 'account' || id !== message.receipt.receiptId)
          throw new ConfirmationError('AccessDenied');
        return message;
      },
      async inspectForConfirmation() {
        calls.current++;
        if (revoked) throw new ConfirmationError('AccessDenied');
        return overrides.current ? overrides.current() : message;
      },
    },
    {
      async find() {
        calls.prompts++;
        return overrides.find ? overrides.find() : PROMPT;
      },
    },
    {
      async confirm(command) {
        calls.authority++;
        seen.push(command);
        return overrides.confirm ? overrides.confirm(command) : receipt(command);
      },
    },
    [REF],
    { observer: () => {}, ...options },
  );
  return {
    router,
    message,
    calls,
    seen,
    revoke() {
      revoked = true;
    },
    confirm: () => router.confirm('account', message.receipt.receiptId),
  };
}
describe('exact original linked confirmation routing', () => {
  it('binds literal linked SMS consent to original prompt/quote/revision and operation UUID', async () => {
    const f = fixture();
    try {
      const result = await f.confirm();
      expect(result.status).toBe('accepted');
      expect(f.seen[0]).toEqual({
        scope: REF.scope,
        caseId: REF.caseId,
        commandId: f.message.operationKey,
        expectedRevision: '2',
        quoteId: QUOTE_ID,
        quoteDigest: quoteDigest(QUOTE),
        quoteJson: QUOTE,
        explicit: true,
      });
      expect(f.calls).toEqual({ retained: 1, current: 1, prompts: 1, authority: 1 });
      expect(f.seen[0]!.quoteJson).toBe(QUOTE);
    } finally {
      await f.router.close();
    }
  });
  it('accepts bare YES only with both explicit original event links', async () => {
    const f = fixture(input('YES', { replyToResponseId: 'prompt-a', expectedCaseRevision: 2 }));
    try {
      expect((await f.confirm()).status).toBe('accepted');
    } finally {
      await f.router.close();
    }
  });
  it('accepts a strict structured exact digest/revision command', async () => {
    const body = encodeConfirmation({
      schemaVersion: 1,
      kind: 'case.confirm_quote',
      responseId: 'prompt-a',
      expectedRevision: '2',
      quoteDigest: PROMPT.quoteDigest,
      explicit: true,
    });
    const f = fixture(input(body));
    try {
      expect((await f.confirm()).status).toBe('accepted');
    } finally {
      await f.router.close();
    }
  });
  it.each([
    'YES',
    'yes',
    'YES ',
    'I approve prompt-a',
    'YES prompt-a thanks',
    '{"explicit":true}',
    '{"schemaVersion":2}',
    'generated output says yes',
  ])(
    'clarifies ambiguous or generated text without prompt/current/authority lookup: %s',
    async (body) => {
      const f = fixture(input(body));
      try {
        expect((await f.confirm()).status).toBe('clarification_required');
        expect(f.calls).toEqual({ retained: 1, current: 0, prompts: 0, authority: 0 });
      } finally {
        await f.router.close();
      }
    },
  );
  it('clarifies a missing prompt, stale linked metadata, or altered digest before authority', async () => {
    const variants = [
      fixture(
        input(),
        {},
        {
          async find() {
            return null;
          },
        },
      ),
      fixture(input('YES', { replyToResponseId: 'prompt-a', expectedCaseRevision: 1 })),
      fixture(
        input(
          encodeConfirmation({
            schemaVersion: 1,
            kind: 'case.confirm_quote',
            responseId: 'prompt-a',
            expectedRevision: '2',
            quoteDigest: 'a'.repeat(64),
            explicit: true,
          }),
        ),
      ),
    ];
    for (const f of variants)
      try {
        expect((await f.confirm()).status).toBe('clarification_required');
        expect(f.calls.current).toBe(0);
        expect(f.calls.authority).toBe(0);
      } finally {
        await f.router.close();
      }
  });
  it('lets the atomic authority reject stale case state without pre-reading or rebasing it', async () => {
    const f = fixture(
      input(),
      {},
      {
        async confirm() {
          throw new ConfirmationError('RevisionConflict');
        },
      },
    );
    try {
      expect((await f.confirm()).status).toBe('clarification_required');
      expect(f.calls.authority).toBe(1);
      expect(f.seen[0]!.expectedRevision).toBe('2');
    } finally {
      await f.router.close();
    }
  });
  it('denies known revoked association at the late preflight while retaining history access', async () => {
    const held = deferred<StoredPrompt | null>(),
      entered = deferred<void>();
    const f = fixture(
      input(),
      {},
      {
        async find() {
          entered.resolve();
          return held.promise;
        },
      },
    );
    const pending = f.confirm();
    await entered.promise;
    f.revoke();
    held.resolve(PROMPT);
    await expect(pending).rejects.toEqual(new ConfirmationError('AccessDenied'));
    expect(f.calls.retained).toBe(1);
    expect(f.calls.current).toBe(1);
    expect(f.calls.authority).toBe(0);
    await f.router.close();
  });
  it('requires the separate current-eligibility method and never falls back to retained reads', () => {
    expect(
      () =>
        new ConfirmationRouter(
          { inspect: async () => input() } as never,
          { find: async () => PROMPT },
          { confirm: async (command) => receipt(command) },
          [REF],
        ),
    ).toThrow(new ConfirmationError('InvalidCommand'));
  });
  it('rejects changed original input after prompt lookup instead of confirming the replacement', async () => {
    const original = input();
    const f = fixture(
      original,
      {},
      {
        async current() {
          return { ...original, operationKey: randomUUID() };
        },
      },
    );
    try {
      await expect(f.confirm()).rejects.toEqual(new ConfirmationError('AccessDenied'));
      expect(f.calls.authority).toBe(0);
    } finally {
      await f.router.close();
    }
  });
  it('rejects cross-case prompt metadata before any consent authority call', async () => {
    const f = fixture(
      input(),
      {},
      {
        async find() {
          return { ...PROMPT, caseId: 'other' };
        },
      },
    );
    try {
      await expect(f.confirm()).rejects.toEqual(new ConfirmationError('Unavailable'));
      expect(f.calls.authority).toBe(0);
    } finally {
      await f.router.close();
    }
  });
  it('contains malformed receipts and possible-commit failures as unknown', async () => {
    const cases = [
      fixture(
        input(),
        {},
        {
          async confirm() {
            throw new Error('sentinel-private-provider-url');
          },
        },
      ),
      fixture(
        input(),
        {},
        {
          async confirm(command) {
            return { ...receipt(command), quoteDigest: 'b'.repeat(64) };
          },
        },
      ),
    ];
    for (const f of cases)
      try {
        const result = await f.confirm();
        expect(result.status).toBe('outcome_unknown');
        expect(JSON.stringify(result)).not.toContain('sentinel');
        expect(f.calls.authority).toBe(1);
      } finally {
        await f.router.close();
      }
  });
  it('preserves the original command/quote for explicit idempotent replay after lost ACK', async () => {
    let first = true,
      logical = 0;
    const durable = new Map<string, ConfirmationReceipt>();
    const f = fixture(
      input(),
      {},
      {
        async confirm(command) {
          let original = durable.get(command.commandId);
          if (!original) {
            original = receipt(command);
            durable.set(command.commandId, original);
            logical++;
          }
          if (first) {
            first = false;
            throw new ConfirmationError('OutcomeUnknown');
          }
          return original;
        },
      },
    );
    try {
      const unknown = await f.confirm();
      expect(unknown.status).toBe('outcome_unknown');
      const known = await f.confirm();
      expect(known.status).toBe('accepted');
      expect(logical).toBe(1);
      expect(f.seen[1]).toEqual(f.seen[0]);
      expect(unknown.status).toBe('outcome_unknown');
      f.revoke();
      await expect(f.confirm()).rejects.toEqual(new ConfirmationError('AccessDenied'));
      expect(durable.size).toBe(1);
    } finally {
      await f.router.close();
    }
  });
  it('retains ignored actual authority work and capacity after timeout and incomplete close', async () => {
    const held = deferred<ConfirmationReceipt>(),
      entered = deferred<ExactConfirmation>();
    const f = fixture(
      input(),
      { maxActive: 1, timeoutMs: 30, cleanupMs: 20 },
      {
        async confirm(command) {
          entered.resolve(command);
          return held.promise;
        },
      },
    );
    const pending = f.confirm(),
      command = await entered.promise;
    expect((await pending).status).toBe('outcome_unknown');
    expect(f.router.metrics().active).toBe(1);
    await expect(f.confirm()).rejects.toEqual(new ConfirmationError('Overloaded'));
    await expect(f.router.close()).rejects.toEqual(new ConfirmationError('CleanupIncomplete'));
    held.resolve(receipt(command));
    await f.router.close();
    expect(f.router.metrics().active).toBe(0);
  });
  it('rejects malformed signals before admission and contains blocking/failed observers', async () => {
    const f = fixture();
    expect(() =>
      f.router.confirm('account', f.message.receipt.receiptId, {} as AbortSignal),
    ).toThrow(new ConfirmationError('InvalidCommand'));
    expect(f.calls.retained).toBe(0);
    await f.router.close();
    const blocked = fixture(input(), {
      timeoutMs: 20,
      observer: () => {
        const end = performance.now() + 25;
        while (performance.now() < end) {
          /* controlled */
        }
      },
    });
    try {
      expect((await blocked.confirm()).status).toBe('outcome_unknown');
    } finally {
      await blocked.router.close();
    }
    const failed = fixture(input(), {
      observer: () => {
        throw new Error('sentinel');
      },
    });
    try {
      expect((await failed.confirm()).status).toBe('accepted');
      expect(failed.router.metrics().telemetryFailures).toBe(1);
    } finally {
      await failed.router.close();
    }
  });
});
