import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  BrowserOperationsClient,
  OperationsController,
  OperationsUiError,
  parseOperationsContext,
  parseOperationsFailure,
  parseOperationsTelemetry,
} from './p2-operations-policy';
import type {
  ClientMetrics,
  OperationsClient,
  OperationsView,
  OperationsTelemetrySnapshot,
} from './p2-operations-policy';
const uid = (n: number) => `${String(n).padStart(8, '0')}-1111-4111-8111-111111111111`;
const requestId = uid(99);
const token = 'a'.repeat(43);
const stamp = '2026-11-12T00:00:00.000Z';
const encode = (value: unknown) => new TextEncoder().encode(JSON.stringify(value));
function wire() {
  return {
    schemaVersion: 1,
    status: 'known',
    requestId,
    context: {
      schemaVersion: 1,
      contextId: uid(3),
      access: { kind: 'native', bindingId: uid(2), roomId: 'room-B', participantId: 'browser-B' },
      case: {
        schemaVersion: 1,
        source: 'standalone_reference_v1',
        scope: { tenantId: 'tenant-demo', accountId: 'account-demo' },
        caseId: 'case-demo',
        conversationId: 'conversation-demo',
        revision: '0',
        sourceRevision: 'a'.repeat(64),
        request: {
          schemaVersion: 1,
          kind: 'booking_investigation',
          bookingReference: 'DEMO-1',
          newCheckIn: '2030-12-10',
          investigationConsent: true,
        },
        workflow: null,
        intent: { state: 'not_committed', intentId: null },
        mutation: {
          state: 'not_observed',
          outcome: 'not_observed',
          cancellation: 'not_observed',
          effectId: null,
          outcomeEventId: null,
        },
        supplierResult: null,
      },
      history: { messages: [message(11)], nextCursor: null, hasMore: false },
      work: { items: [], nextCursor: null, hasMore: false },
      responses: { items: [], nextCursor: null, hasMore: false },
      replies: { items: [], nextCursor: null, hasMore: false },
      observed: {
        p2ObservedAt: stamp,
        caseObservedAt: stamp,
        disclosureAdmittedAt: stamp,
        atomic: false,
      },
    },
    cursors: { history: null as string | null, work: null, responses: null, replies: null },
  };
}
function message(n: number) {
  return {
    receipt: {
      receiptId: uid(n),
      eventId: uid(n + 100),
      messageId: uid(n + 100),
      acceptanceSequence: String(n),
      acceptedAt: stamp,
    },
    event: {
      schemaVersion: 1,
      type: 'text.received',
      eventId: uid(n + 100),
      providerScope: {
        tenantId: 'tenant-demo',
        provider: 'livekit',
        providerAccountId: 'local-native',
      },
      accountScope: { tenantId: 'tenant-demo', accountId: 'account-demo' },
      conversationId: 'conversation-demo',
      caseId: 'case-demo',
      receivedAt: stamp,
      channel: 'voice_transcript',
      messageId: uid(n + 100),
      senderId: uid(1),
      body: 'Untrusted historical <script>data</script>',
    },
    operationKey: uid(n + 200),
    processingState: 'pending',
    associationVersion: '1',
  };
}
const cursor = 'eA.' + 'b'.repeat(43);
function telemetryWire() {
  return {
    schemaVersion: 1,
    status: 'known',
    scope: 'process',
    requestId,
    observedAt: stamp,
    sources: [],
    observations: [],
  };
}
const view = () => parseOperationsContext(encode(wire()), requestId);
const telemetry = () => parseOperationsTelemetry(encode(telemetryWire()), requestId);
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
}
function response(value: unknown, id = requestId, status = 200) {
  return new Response(encode(value), {
    status,
    headers: { 'content-type': 'application/json', 'x-p2-request-id': id },
  });
}
function client(fetcher: typeof fetch, changed = () => {}) {
  return new BrowserOperationsClient(token, changed, fetcher, () => requestId);
}
class FakeClient implements OperationsClient {
  active = 0;
  started = 0;
  settled = 0;
  contextStarted = 0;
  telemetryStarted = 0;
  abandoned = 0;
  contextImpl: () => Promise<OperationsView> = async () => view();
  telemetryImpl: () => Promise<OperationsTelemetrySnapshot> = async () => telemetry();
  closeImpl: () => Promise<void> = async () => {};
  closeCalls = 0;
  context() {
    this.contextStarted++;
    return this.run(this.contextImpl);
  }
  telemetry() {
    this.telemetryStarted++;
    return this.run(this.telemetryImpl);
  }
  async run<T>(work: () => Promise<T>): Promise<T> {
    this.active++;
    this.started++;
    try {
      return await work();
    } finally {
      this.active--;
      this.settled++;
    }
  }
  metrics(): ClientMetrics {
    return {
      active: this.active,
      started: this.started,
      settled: this.settled,
      contextStarted: this.contextStarted,
      telemetryStarted: this.telemetryStarted,
      abandoned: this.abandoned,
    };
  }
  close() {
    this.closeCalls++;
    return this.closeImpl();
  }
}
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});
describe('operations strict read boundary', () => {
  it('preserves revision zero, separate as-of times and original inert history', () => {
    const v = view();
    expect(v.context.case.revision).toBe('0');
    expect(v.context.observed.atomic).toBe(false);
    expect(v.context.history.messages[0]!.event.body).toContain('<script>');
    expect(Object.isFrozen(v.context.case)).toBe(true);
  });
  it.each(['bindingId', 'roomId', 'participantId'] as const)(
    'pins original authenticated native %s',
    (key) => {
      const a = wire();
      const b = view().context;
      a.context.access[key] = key === 'bindingId' ? uid(44) : 'other';
      expect(() =>
        parseOperationsContext(encode(a), requestId, {
          ...b.access,
          scope: b.case.scope,
          caseId: b.case.caseId,
          conversationId: b.case.conversationId,
        }),
      ).toThrow();
    },
  );
  it.each(['schemaVersion', 'status', 'requestId', 'context', 'cursors'])(
    'requires exact envelope %s',
    (key) => {
      const a: Record<string, unknown> = wire();
      delete a[key];
      expect(() => parseOperationsContext(encode(a), requestId)).toThrow();
    },
  );
  it('rejects duplicate keys, malformed UTF8, primitives and control fields', () => {
    for (const raw of [
      new TextEncoder().encode('{"schemaVersion":1,"schemaVersion":1}'),
      new Uint8Array([0xff]),
      encode(null),
      encode({ ...wire(), quote: { explicit: true } }),
    ])
      expect(() => parseOperationsContext(raw, requestId)).toThrow();
  });
  it('binds both scope and conversation to the original read', () => {
    const b = view().context;
    for (const change of [
      { scope: { ...b.case.scope, accountId: 'other' } },
      { conversationId: 'other' },
    ])
      expect(() =>
        parseOperationsContext(encode(wire()), requestId, {
          ...b.access,
          scope: b.case.scope,
          caseId: b.case.caseId,
          conversationId: b.case.conversationId,
          ...change,
        }),
      ).toThrow();
  });
  it('rejects malformed, extra, oversized and aggregate-over-budget cursors', () => {
    for (const changed of [
      { history: 'bad' },
      { unknown: null },
      { history: 'x'.repeat(2049) },
      Object.fromEntries(
        ['history', 'work', 'responses', 'replies'].map((k) => [
          k,
          'e'.repeat(2000) + '.' + 'b'.repeat(43),
        ]),
      ),
    ]) {
      const a = wire();
      Object.assign(a.cursors, changed);
      expect(() => parseOperationsContext(encode(a), requestId)).toThrow();
    }
  });
  it('accepts exact bounded opaque cursor without pretending to verify its MAC', () => {
    const a = wire();
    a.cursors.history = cursor;
    expect(parseOperationsContext(encode(a), requestId).cursors.history).toBe(cursor);
  });
  it('rejects original legacy size excess even inside total frame bound', () => {
    const a = wire();
    a.context.history.messages[0]!.event.body = 'x'.repeat(66000);
    expect(() => parseOperationsContext(encode(a), requestId)).toThrow();
  });
  it('requires correlated telemetry, exact process scope and finite metrics', () => {
    for (const a of [
      { ...telemetryWire(), requestId: uid(1) },
      { ...telemetryWire(), scope: 'case' },
      {
        ...telemetryWire(),
        sources: [{ source: 'unknown', state: 'observed', observedAt: stamp, values: [] }],
      },
      { ...telemetryWire(), observations: [null] },
    ])
      expect(() => parseOperationsTelemetry(encode(a), requestId)).toThrow();
  });
  it('retains unavailable metric sources without inventing zeros', () => {
    const a = telemetryWire();
    const raw = {
      ...a,
      sources: [{ source: 'inbox', state: 'unavailable', observedAt: stamp, values: [] }],
    };
    expect(parseOperationsTelemetry(encode(raw), requestId).sources[0]!.values).toEqual([]);
  });
  it('requires exact finite error/retry correlation', () => {
    const failure = {
      schemaVersion: 1,
      status: 'unavailable',
      requestId,
      code: 'access_denied',
      retry: 'authenticate',
    };
    expect(parseOperationsFailure(encode(failure), requestId).code).toBe('access_denied');
    for (const change of [
      { retry: 'same_read' },
      { requestId: uid(1) },
      { message: 'raw-error' },
      { code: 'untrusted' },
    ])
      expect(parseOperationsFailure(encode({ ...failure, ...change }), requestId).code).toBe(
        'unavailable',
      );
  });
});
describe('browser actual HTTP ownership', () => {
  it.each(['default', 'injected'] as const)(
    'calls captured fetch without a client receiver (%s)',
    async (mode) => {
      const receivers: unknown[] = [];
      const nativeLike: typeof fetch = async function (this: unknown) {
        receivers.push(this);
        if (this !== undefined) throw new TypeError('Native fetch receiver rejected');
        return response(wire());
      };
      if (mode === 'default') vi.stubGlobal('fetch', nativeLike);
      const c =
        mode === 'default'
          ? new BrowserOperationsClient(
              token,
              () => {},
              undefined,
              () => requestId,
            )
          : client(nativeLike);
      try {
        await expect(c.context({ section: 'history', cursor: null })).resolves.toMatchObject({
          status: 'known',
        });
        expect(receivers).toEqual([undefined]);
        expect(c.metrics().active).toBe(0);
      } finally {
        await c.close();
        vi.unstubAllGlobals();
      }
    },
  );
  it('sends read-only scoped same-origin headers and verifies actual response', async () => {
    const spy = vi.fn<typeof fetch>(async () => response(wire()));
    const c = client(spy);
    await c.context({ section: 'history', cursor: null });
    expect(spy.mock.calls[0]![0]).toBe('/p2-operations/context?section=history');
    const init = spy.mock.calls[0]![1]!;
    expect(init.method).toBe('GET');
    expect(init.body).toBeUndefined();
    expect(init.credentials).toBe('omit');
    expect(init.headers).toMatchObject({
      authorization: 'Bearer ' + token,
      'x-p2-request-id': requestId,
    });
    await c.close();
  });
  it('retains timed-out actual work, rejects a same-kind retry and progresses after release', async () => {
    vi.useFakeTimers();
    const held = deferred<Response>();
    const c = client(
      vi
        .fn<typeof fetch>()
        .mockImplementationOnce(() => held.promise)
        .mockResolvedValue(response(wire())),
    );
    const first = c.context({ section: 'history', cursor: null });
    const expected = expect(first).rejects.toMatchObject({ code: 'unavailable' });
    await vi.advanceTimersByTimeAsync(4000);
    await expected;
    expect(c.metrics().active).toBe(1);
    await expect(c.context({ section: 'history', cursor: null })).rejects.toMatchObject({
      code: 'overloaded',
    });
    held.resolve(response(wire()));
    await vi.advanceTimersByTimeAsync(0);
    expect(c.metrics().active).toBe(0);
    await c.context({ section: 'history', cursor: null });
    await c.close();
  });
  it('bounds close observation while retaining ignored body cancellation through retry', async () => {
    vi.useFakeTimers();
    const cancel = deferred<void>();
    const stream = new ReadableStream<Uint8Array>({ cancel: () => cancel.promise });
    const c = client(
      async () => new Response(stream, { headers: { 'content-type': 'text/plain' } }),
    );
    const read = c.telemetry();
    const readFailed = expect(read).rejects.toMatchObject({ code: 'invalid_response' });
    await vi.advanceTimersByTimeAsync(0);
    const close = c.close();
    const closed = expect(close).rejects.toMatchObject({ code: 'cleanup_incomplete' });
    await vi.advanceTimersByTimeAsync(1000);
    await closed;
    expect(c.metrics().active).toBe(1);
    cancel.resolve();
    await readFailed;
    await c.close();
    expect(c.metrics().active).toBe(0);
  });
  it('contains renderer failure and settles owned work without unhandled derived rejection', async () => {
    const c = client(
      async () => response(wire()),
      () => {
        throw new Error('renderer');
      },
    );
    await c.context({ section: 'history', cursor: null });
    await c.close();
    expect(c.metrics().settled).toBe(1);
  });
  it.each(['header', 'body', 'redirect'] as const)(
    'rejects mismatched %s identity',
    async (mode) => {
      const r = response(
        mode === 'body' ? { ...wire(), requestId: uid(1) } : wire(),
        mode === 'header' ? uid(1) : requestId,
      );
      if (mode === 'redirect') Object.defineProperty(r, 'redirected', { value: true });
      const c = client(async () => r);
      await expect(c.context({ section: 'history', cursor: null })).rejects.toMatchObject({
        code: 'invalid_response',
      });
      await c.close();
    },
  );
  it('requires the fixed HTTP status to match the safe error code', async () => {
    const error = {
      schemaVersion: 1,
      status: 'unavailable',
      requestId,
      code: 'access_denied',
      retry: 'authenticate',
    };
    const c = client(async () => response(error, requestId, 503));
    await expect(c.telemetry()).rejects.toMatchObject({ code: 'invalid_response' });
    await c.close();
    const denied = client(async () => response(error, requestId, 403));
    await expect(denied.telemetry()).rejects.toMatchObject({ code: 'access_denied' });
    await denied.close();
  });
  it('caps two actual requests and independently permits context and telemetry', async () => {
    const a = deferred<Response>();
    const b = deferred<Response>();
    const c = client(
      vi
        .fn<typeof fetch>()
        .mockImplementationOnce(() => a.promise)
        .mockImplementationOnce(() => b.promise),
    );
    const x = c.context({ section: 'history', cursor: null });
    const y = c.telemetry();
    await expect(c.telemetry()).rejects.toMatchObject({ code: 'overloaded' });
    a.resolve(response(wire()));
    b.resolve(response(telemetryWire()));
    await Promise.all([x, y]);
    expect(c.metrics().active).toBe(0);
    await c.close();
  });
  it('external waiter abandonment retains the actual request until it settles', async () => {
    const a = deferred<Response>();
    const c = client(async () => a.promise);
    const abort = new AbortController();
    const read = c.context({ section: 'history', cursor: null }, abort.signal);
    abort.abort();
    await expect(read).rejects.toMatchObject({ code: 'unavailable' });
    expect(c.metrics().active).toBe(1);
    a.resolve(response(wire()));
    await c.close();
  });
});
describe('operations controller lifetime and actual read states', () => {
  it('retains the real browser client after bounded Forget and reconnects only after actual reader release', async () => {
    vi.useFakeTimers();
    const cancellation = deferred<void>();
    const held = new ReadableStream<Uint8Array>({ cancel: () => cancellation.promise });
    let first = true;
    const factory = vi.fn((_token: string, changed: () => void) =>
      client(async (url) => {
        if (String(url).includes('/context') && first) {
          first = false;
          return new Response(held, { headers: { 'content-type': 'text/plain' } });
        }
        return response(String(url).includes('/context') ? wire() : telemetryWire());
      }, changed),
    );
    const c = new OperationsController(() => {}, factory);
    const initial = c.connect(token);
    await vi.advanceTimersByTimeAsync(0);
    const forgotten = expect(c.forget()).rejects.toMatchObject({ code: 'cleanup_incomplete' });
    await vi.advanceTimersByTimeAsync(1000);
    await forgotten;
    expect(c.snapshot()).toMatchObject({
      view: null,
      telemetry: null,
      ownedClient: 1,
      actualRequests: 1,
      cleanupComplete: false,
    });
    await expect(c.connect(token)).rejects.toMatchObject({ code: 'overloaded' });
    cancellation.resolve();
    await initial;
    await c.forget();
    expect(c.snapshot().ownedClient).toBe(0);
    await c.connect(token);
    expect(c.snapshot().view).not.toBeNull();
    expect(factory).toHaveBeenCalledTimes(2);
    await c.forget();
  });

  it('forgets private facts immediately but retains one held close owner and fences late reads', async () => {
    const a = deferred<OperationsView>();
    const end = deferred<void>();
    const f = new FakeClient();
    f.contextImpl = () => a.promise;
    f.closeImpl = () => end.promise;
    const factory = vi.fn(() => f);
    const c = new OperationsController(() => {}, factory);
    const connect = c.connect(token);
    const close = c.forget();
    expect(c.snapshot()).toMatchObject({
      view: null,
      telemetry: null,
      ownedClient: 1,
      phase: 'closing',
    });
    await expect(c.connect(token)).rejects.toMatchObject({ code: 'overloaded' });
    a.resolve(view());
    await connect;
    expect(c.snapshot().view).toBeNull();
    expect(factory).toHaveBeenCalledTimes(1);
    end.resolve();
    await close;
    expect(c.snapshot()).toMatchObject({ ownedClient: 0, cleanupComplete: true });
    f.contextImpl = async () => view();
    await c.connect(token);
    expect(factory).toHaveBeenCalledTimes(2);
    await c.forget();
  });
  it('retains a failed close owner and permits explicit cleanup retry then useful progress', async () => {
    const f = new FakeClient();
    f.closeImpl = async () => {
      if (f.closeCalls === 1) throw new Error('held');
    };
    const c = new OperationsController(
      () => {},
      () => f,
    );
    await c.connect(token);
    await expect(c.forget()).rejects.toMatchObject({ code: 'cleanup_incomplete' });
    expect(c.snapshot().ownedClient).toBe(1);
    await expect(c.connect(token)).rejects.toMatchObject({ code: 'overloaded' });
    await c.forget();
    await c.connect(token);
    expect(c.snapshot().view).not.toBeNull();
    await c.forget();
  });
  it('preserves current facts as historical on failed read and clears that state on successful Retry', async () => {
    const f = new FakeClient();
    const c = new OperationsController(
      () => {},
      () => f,
    );
    await c.connect(token);
    f.contextImpl = async () => {
      throw new OperationsUiError('unavailable');
    };
    await c.refresh();
    expect(c.snapshot()).toMatchObject({
      phase: 'unavailable',
      contextHistorical: true,
      polling: false,
    });
    f.contextImpl = async () => view();
    await c.retry();
    expect(c.snapshot()).toMatchObject({ phase: 'ready', contextHistorical: false });
    await c.forget();
  });
  it('pauses every poll on context denial and fences a concurrent late diagnostic result', async () => {
    const f = new FakeClient();
    const c = new OperationsController(
      () => {},
      () => f,
    );
    await c.connect(token);
    const old = c.snapshot().telemetry;
    const late = deferred<OperationsTelemetrySnapshot>();
    f.telemetryImpl = () => late.promise;
    f.contextImpl = async () => {
      throw new OperationsUiError('access_denied');
    };
    const next = c.refresh();
    await Promise.resolve();
    await Promise.resolve();
    late.resolve({ ...telemetry(), observedAt: '2026-11-12T00:01:00.000Z' });
    await next;
    expect(c.snapshot()).toMatchObject({
      phase: 'denied',
      polling: false,
      contextHistorical: true,
      diagnosticsHistorical: true,
    });
    expect(c.snapshot().telemetry).toBe(old);
    await expect(c.refresh()).rejects.toMatchObject({ code: 'access_denied' });
    await c.forget();
  });
  it('keeps process telemetry failure separate from retained case facts', async () => {
    const f = new FakeClient();
    const c = new OperationsController(
      () => {},
      () => f,
    );
    await c.connect(token);
    f.telemetryImpl = async () => {
      throw new OperationsUiError('unavailable');
    };
    await c.refresh();
    expect(c.snapshot().view).not.toBeNull();
    expect(c.snapshot().telemetryError).toBe('unavailable');
    expect(c.snapshot().diagnosticsHistorical).toBe(true);
    await c.forget();
  });
  it('loads immutable older receipt pages separately and rejects changed original facts', async () => {
    const f = new FakeClient();
    const a = wire();
    a.cursors.history = cursor;
    f.contextImpl = async () => parseOperationsContext(encode(a), requestId);
    const c = new OperationsController(
      () => {},
      () => f,
    );
    await c.connect(token);
    const b = wire();
    b.context.history.messages = [message(10)];
    f.contextImpl = async () => parseOperationsContext(encode(b), requestId);
    await c.older('history');
    expect(c.snapshot().rows.history.map((x) => x.value.receipt.receiptId)).toEqual([
      uid(11),
      uid(10),
    ]);
    expect(c.snapshot().polling).toBe(false);
    const changed = wire();
    changed.cursors.history = cursor;
    changed.context.history.messages[0]!.event.body = 'changed';
    f.contextImpl = async () => parseOperationsContext(encode(a), requestId);
    await c.refresh();
    f.contextImpl = async () => parseOperationsContext(encode(changed), requestId);
    await c.older('history');
    expect(c.snapshot().error?.code).toBe('invalid_response');
    await c.forget();
  });
  it('invalidates older page cursors when the case source revision changed', async () => {
    const f = new FakeClient();
    const a = wire();
    a.cursors.history = cursor;
    f.contextImpl = async () => parseOperationsContext(encode(a), requestId);
    const c = new OperationsController(
      () => {},
      () => f,
    );
    await c.connect(token);
    a.context.case.sourceRevision = 'b'.repeat(64);
    await c.older('history');
    expect(c.snapshot().error?.code).toBe('cursor_stale');
    await c.forget();
  });
  it('runs at most thirty two-second polling ticks with no queued overlaps', async () => {
    vi.useFakeTimers();
    const f = new FakeClient();
    const c = new OperationsController(
      () => {},
      () => f,
    );
    await c.connect(token);
    await vi.advanceTimersByTimeAsync(1999);
    expect(f.contextStarted).toBe(1);
    await vi.advanceTimersByTimeAsync(60001);
    expect(c.snapshot()).toMatchObject({ ticks: 30, ticksRemaining: 0, polling: false });
    expect(f.contextStarted).toBe(31);
    expect(vi.getTimerCount()).toBe(0);
    await c.forget();
  });
  it('never queues a polling tick behind a held current read', async () => {
    vi.useFakeTimers();
    const f = new FakeClient();
    const c = new OperationsController(
      () => {},
      () => f,
    );
    await c.connect(token);
    const held = deferred<OperationsView>();
    f.contextImpl = () => held.promise;
    const read = c.refresh();
    await vi.advanceTimersByTimeAsync(60000);
    expect(f.contextStarted).toBe(2);
    expect(c.snapshot()).toMatchObject({ ticks: 30, polling: false });
    held.resolve(view());
    await read;
    expect(f.contextStarted).toBe(2);
    await c.forget();
  });
  it('continues cleanup when the view callback throws and clears private facts first', async () => {
    const f = new FakeClient();
    const c = new OperationsController(
      () => {
        throw new Error('view');
      },
      () => f,
    );
    await c.connect(token);
    await c.forget();
    expect(c.snapshot()).toMatchObject({ view: null, telemetry: null, ownedClient: 0 });
    expect(f.closeCalls).toBe(1);
  });
});
