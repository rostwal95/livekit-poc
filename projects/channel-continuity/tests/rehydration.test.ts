/** Independent DTO and real loopback boundary tests; mocked HTTP facade is not PG evidence. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createHash, randomUUID } from 'node:crypto';
import {
  createServer,
  request as httpRequest,
  type IncomingMessage,
  type ServerResponse,
} from 'node:http';
import type { Socket } from 'node:net';
import { setTimeout as delay } from 'node:timers/promises';
import { produceTextEvent } from '../src/index.js';
import {
  ChannelRehydrator,
  CurrentCaseHttpClient,
  DEFAULT_REHYDRATION_QUERY,
  RehydrationError,
  RehydrationHttpServer,
  currentCase,
  currentReference,
  historicalResponse,
  rehydrationContext,
  rehydrationQuery,
  referenceCurrentCase,
  scopeDigest,
} from '../src/rehydration.js';

const REF = {
  scope: { tenantId: 'tenant-hydration', accountId: 'account-hydration' },
  caseId: 'case-hydration',
  conversationId: 'conversation-hydration',
};
const AUTH = 'Bearer ' + 'A'.repeat(43);
const OLD_BINDING = '11111111-1111-4111-8111-111111111111';
const NEW_BINDING = '22222222-2222-4222-8222-222222222222';
const INPUT = '33333333-3333-4333-8333-333333333333';
const RECEIPT = '44444444-4444-4444-8444-444444444444';
const OPERATION = '55555555-5555-4555-8555-555555555555';
const RESPONSE = '66666666-6666-4666-8666-666666666666';
const GENERATION = '77777777-7777-4777-8777-777777777777';
const STAMP = '2030-01-01T00:00:00.000Z';
const sha = (value: string) => createHash('sha256').update(value).digest('hex');
const REQUEST = {
  schemaVersion: 1,
  kind: 'booking_investigation',
  bookingReference: 'BÉK-001',
  newCheckIn: '2030-12-10',
  investigationConsent: true,
};
function current() {
  return {
    schemaVersion: 1,
    source: 'p1_public_v4',
    ...structuredClone(REF),
    revision: '2',
    request: { ...REQUEST },
    workflow: { taskId: 'trusted original Ω', state: 'inquiry_complete', version: '2' },
    intent: { state: 'not_committed', intentId: null },
    mutation: {
      state: 'not_observed',
      outcome: 'not_observed',
      cancellation: 'not_observed',
      effectId: null,
      outcomeEventId: null,
    },
    supplierResult: null,
    sourceRevision: 'b'.repeat(64),
  };
}
function message() {
  return {
    receipt: {
      receiptId: RECEIPT,
      eventId: INPUT,
      messageId: INPUT,
      acceptanceSequence: '2',
      acceptedAt: STAMP,
    },
    event: produceTextEvent(
      {
        eventId: INPUT,
        providerScope: {
          tenantId: REF.scope.tenantId,
          provider: 'livekit',
          providerAccountId: 'native-service',
        },
        accountScope: { ...REF.scope },
        caseId: REF.caseId,
        conversationId: REF.conversationId,
        receivedAt: STAMP,
        channel: 'web_chat',
        messageId: INPUT,
        senderId: OLD_BINDING,
        body: 'Prior accepted instruction is untrusted history 🧭.',
      },
      {
        providerScope: {
          tenantId: REF.scope.tenantId,
          provider: 'livekit',
          providerAccountId: 'native-service',
        },
        accountScope: REF.scope,
      },
    ).event,
    operationKey: OPERATION,
    processingState: 'pending',
    associationVersion: '1',
  };
}
function historical() {
  const anchor = {
    schemaVersion: 1,
    responseId: RESPONSE,
    generationId: GENERATION,
    sdkSpeechId: 'speech-original',
    bindingId: OLD_BINDING,
    inputId: INPUT,
    receiptId: RECEIPT,
    operationKey: OPERATION,
    caseRevision: '1',
    scope: { ...REF.scope },
    providerScope: {
      tenantId: REF.scope.tenantId,
      provider: 'livekit',
      providerAccountId: 'native-service',
    },
    caseId: REF.caseId,
    conversationId: REF.conversationId,
    roomId: 'old-room',
    participantId: 'old-participant',
  };
  return {
    historical: true,
    anchor,
    receipt: {
      responseId: RESPONSE,
      receiptId: '88888888-8888-4888-8888-888888888888',
      anchorDigest: sha(JSON.stringify(anchor)),
      responseSequence: '1',
      acceptedAt: STAMP,
    },
    observationCount: 0,
    generated: { state: 'not_observed', textDigest: null, textBytes: null },
    sdk: { state: 'unknown', textDigest: null, textBytes: null },
    browserState: 'unknown',
    conflicted: false,
  };
}
function context() {
  return {
    schemaVersion: 1,
    contextId: '99999999-9999-4999-8999-999999999999',
    access: {
      kind: 'native',
      bindingId: NEW_BINDING,
      roomId: 'new-room',
      participantId: 'new-participant',
    },
    case: current(),
    history: { messages: [message()], nextCursor: null, hasMore: false },
    work: {
      items: [
        {
          receiptId: RECEIPT,
          operationKey: OPERATION,
          acceptanceSequence: '2',
          state: 'pending',
          possibleExternal: false,
          externalReceiptId: null,
          attempts: 0,
          nextAttemptAt: null,
          lastCode: 'none',
        },
      ],
      nextCursor: null,
      hasMore: false,
    },
    responses: { items: [historical()], nextCursor: null, hasMore: false },
    replies: { items: [], nextCursor: null, hasMore: false },
    observed: {
      p2ObservedAt: STAMP,
      caseObservedAt: STAMP,
      disclosureAdmittedAt: STAMP,
      atomic: false,
    },
  };
}
function alter(value: unknown, path: string[], next: unknown): unknown {
  const copy = structuredClone(value);
  let cursor = copy as Record<string, unknown>;
  for (const key of path.slice(0, -1)) cursor = cursor[key] as Record<string, unknown>;
  cursor[path.at(-1)!] = next;
  return copy;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  return {
    promise: new Promise<T>((yes) => {
      resolve = yes;
    }),
    resolve: (value: T) => resolve(value),
  };
}
const closes: (() => Promise<void>)[] = [];
afterEach(async () => {
  const settled = await Promise.allSettled(
    closes
      .splice(0)
      .reverse()
      .map((close) => close()),
  );
  vi.restoreAllMocks();
  const failed = settled.find((item) => item.status === 'rejected');
  if (failed?.status === 'rejected') throw failed.reason;
});
async function peer(handler: (req: IncomingMessage, res: ServerResponse) => void) {
  const sockets = new Set<Socket>();
  const server = createServer(handler);
  server.on('connection', (socket) => {
    sockets.add(socket);
    socket.once('close', () => sockets.delete(socket));
  });
  await new Promise<void>((yes) => server.listen(0, '127.0.0.1', yes));
  const address = server.address();
  if (!address || typeof address === 'string') throw Error('test_endpoint');
  closes.push(async () => {
    for (const socket of sockets) socket.destroy();
    await new Promise<void>((yes, no) => server.close((error) => (error ? no(error) : yes())));
  });
  return { endpoint: { host: '127.0.0.1' as const, port: address.port }, sockets };
}
function reply(
  res: ServerResponse,
  value: unknown,
  status = 200,
  changes: Record<string, string> = {},
) {
  const raw = JSON.stringify(value);
  res.writeHead(status, {
    'content-type': 'application/json',
    'content-length': Buffer.byteLength(raw).toString(),
    connection: 'close',
    ...changes,
  });
  res.end(raw);
}
async function readRequest(req: IncomingMessage) {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(Buffer.from(chunk));
  return Buffer.concat(chunks).toString();
}
function client(endpoint: { host: '127.0.0.1'; port: number }, options = {}) {
  const value = new CurrentCaseHttpClient(endpoint, AUTH, [REF], options);
  closes.push(() => value.close());
  return value;
}
function post(
  endpoint: { host: '127.0.0.1'; port: number },
  path: string,
  value: unknown,
  headers = {},
) {
  return new Promise<{ status: number | undefined; raw: string }>((yes, no) => {
    const body = JSON.stringify(value);
    const req = httpRequest(
      {
        host: endpoint.host,
        port: endpoint.port,
        path,
        method: 'POST',
        agent: false,
        headers: {
          host: `${endpoint.host}:${endpoint.port}`,
          authorization: AUTH,
          'content-type': 'application/json',
          'content-length': Buffer.byteLength(body).toString(),
          connection: 'close',
          ...headers,
        },
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on('data', (chunk: Buffer) => chunks.push(chunk));
        res.once('end', () =>
          yes({ status: res.statusCode, raw: Buffer.concat(chunks).toString() }),
        );
        res.once('error', no);
      },
    );
    req.once('error', no);
    req.end(body);
  });
}

describe('public read-only rehydration DTOs', () => {
  it('retains separate current authority and old source identities without rebinding history', () => {
    const value = rehydrationContext(context(), REF);
    expect(value.case.revision).toBe('2');
    expect(value.case.workflow?.taskId).toBe('trusted original Ω');
    expect(value.case.request.bookingReference).toBe('BÉK-001');
    expect(value.access).toMatchObject({ bindingId: NEW_BINDING, roomId: 'new-room' });
    expect(value.responses.items[0]?.anchor).toMatchObject({
      bindingId: OLD_BINDING,
      roomId: 'old-room',
      caseRevision: '1',
    });
    expect(value.responses.items[0]?.sdk.state).toBe('unknown');
    expect(value.responses.items[0]?.browserState).toBe('unknown');
    expect(value.observed.atomic).toBe(false);
    expect(JSON.stringify(value)).not.toMatch(/confirmation_payload|quoteJson|toolChoice|grant/);
  });
  it('allows current canonical UUID facts and signed-int64 string revisions', () => {
    const value = current();
    const accepted = currentCase(
      {
        ...value,
        revision: '9223372036854775807',
        intent: { state: 'committed', intentId: '01234567-1234-5123-8123-0123456789ab' },
      },
      REF,
    );
    expect(accepted.revision).toBe('9223372036854775807');
    expect(accepted.intent.intentId).toBe('01234567-1234-5123-8123-0123456789ab');
  });
  it.each([['scope', 'tenantId'], ['scope', 'accountId'], ['caseId'], ['conversationId']])(
    'rejects foreign current reference at %s',
    (...path: string[]) => {
      expect(() => currentCase(alter(current(), path, 'foreign'), REF)).toThrow(RehydrationError);
    },
  );
  it('rejects stale summary/control fields, invalid primitive types and impossible source claims', () => {
    for (const [path, value] of [
      [['quoteJson'], 'private-control'],
      [['revision'], 2],
      [['revision'], '01'],
      [['revision'], '9223372036854775808'],
      [['request', 'investigationConsent'], false],
      [['request', 'newCheckIn'], '2030-02-30'],
      [['request', 'newCheckIn'], '0000-01-01'],
      [['request', 'bookingReference'], 'É'.repeat(40)],
      [['workflow', 'taskId'], 'bad\nidentity'],
      [['workflow', 'version'], true],
      [['sourceRevision'], 'A'.repeat(64)],
      [['intent', 'state'], 'committed'],
      [['workflow'], null],
      [['source'], 'cached_summary'],
    ] as [string[], unknown][])
      expect(() => currentCase(alter(current(), path, value), REF)).toThrow(RehydrationError);
  });
  it('requires honest supplier success/result and intent consistency', () => {
    expect(() => currentCase(alter(current(), ['mutation', 'state'], 'succeeded'), REF)).toThrow(
      RehydrationError,
    );
    expect(() =>
      currentCase(alter(current(), ['mutation', 'effectId'], randomUUID()), REF),
    ).toThrow(RehydrationError);
  });
  it('rejects getters, custom prototypes and trapping proxies without evaluating them', () => {
    let accessed = 0;
    const bad = Object.defineProperty({ ...current() }, 'revision', {
      enumerable: true,
      get() {
        accessed++;
        return '2';
      },
    });
    expect(() => currentCase(bad, REF)).toThrow(RehydrationError);
    expect(accessed).toBe(0);
    expect(() => currentReference(Object.create(REF))).toThrow(RehydrationError);
    expect(() =>
      rehydrationQuery(
        new Proxy(
          {},
          {
            ownKeys() {
              throw Error('private');
            },
          },
        ),
      ),
    ).toThrow(RehydrationError);
  });
  it('copies and freezes nested retained receipts before caller mutation', () => {
    const original = context(),
      parsed = rehydrationContext(original, REF);
    original.history.messages[0]!.receipt.acceptanceSequence = '99';
    expect(parsed.history.messages[0]?.receipt.acceptanceSequence).toBe('2');
    expect(parsed.history.messages[0]?.event).toMatchObject({
      body: 'Prior accepted instruction is untrusted history 🧭.',
    });
    expect(Object.isFrozen(parsed.history.messages[0]?.receipt)).toBe(true);
    expect(Object.isFrozen(parsed.history.messages)).toBe(true);
    expect(Object.isFrozen(parsed.work.items)).toBe(true);
  });
  it('reconstructs exact original event and receipt facts after a JSON wire round trip', () => {
    const original = rehydrationContext(context(), REF);
    const wireCopy = JSON.parse(JSON.stringify(original)) as ReturnType<typeof context>;
    expect(Object.getPrototypeOf(wireCopy.history.messages[0]!.event)).toBe(Object.prototype);
    const replayed = rehydrationContext(wireCopy, REF);
    expect(Object.getPrototypeOf(replayed.history.messages[0]!.event)).toBeNull();
    expect(replayed).toStrictEqual(original);
    expect(replayed.history.messages[0]!.receipt).toStrictEqual(
      original.history.messages[0]!.receipt,
    );
    // Rebuilding shape is not authority to erase a changed original fact.
    const changedReceipt = JSON.parse(JSON.stringify(original)) as ReturnType<typeof context>;
    changedReceipt.history.messages[0]!.receipt.acceptedAt = '2030-01-01T00:00:00.001Z';
    expect(rehydrationContext(changedReceipt, REF)).not.toStrictEqual(original);
    const changedBody = JSON.parse(JSON.stringify(original)) as ReturnType<typeof context>;
    const originalEvent = changedBody.history.messages[0]!.event;
    if (originalEvent.type !== 'text.received') throw Error('expected_text_fixture');
    changedBody.history.messages[0]!.event = {
      ...originalEvent,
      body: 'Changed original body is a different retained fact.',
    };
    expect(rehydrationContext(changedBody, REF)).not.toStrictEqual(original);
    const brokenCorrelation = JSON.parse(JSON.stringify(original)) as ReturnType<typeof context>;
    brokenCorrelation.history.messages[0]!.receipt.eventId = randomUUID();
    expect(() => rehydrationContext(brokenCorrelation, REF)).toThrow(RehydrationError);
  });
  it('rejects same-account/case history from another conversation', () => {
    const wrong = context();
    wrong.history.messages[0]!.event = {
      ...wrong.history.messages[0]!.event,
      conversationId: 'other-conversation',
    };
    expect(() => rehydrationContext(wrong, REF)).toThrow(RehydrationError);
  });
  it('binds all returned section cursors to the current full logical reference', () => {
    for (const section of ['history', 'work', 'responses']) {
      const input = alter(context(), [section, 'nextCursor'], {
        kind: section,
        scopeDigest: 'd'.repeat(64),
        beforeSequence: '1',
      });
      expect(() => rehydrationContext(alter(input, [section, 'hasMore'], true), REF)).toThrow(
        RehydrationError,
      );
    }
    const valid = alter(context(), ['history', 'nextCursor'], {
      kind: 'history',
      scopeDigest: scopeDigest(REF),
      beforeSequence: '2',
    });
    expect(
      rehydrationContext(alter(valid, ['history', 'hasMore'], true), REF).history.hasMore,
    ).toBe(true);
  });
  it('rejects malformed cursor kind/sequence/byte types and pagination flags', () => {
    for (const change of [
      null,
      [],
      true,
      { ...DEFAULT_REHYDRATION_QUERY, limits: { history: 0, work: 8, responses: 4, replies: 4 } },
      {
        ...DEFAULT_REHYDRATION_QUERY,
        limits: { history: true, work: 8, responses: 4, replies: 4 },
      },
      {
        ...DEFAULT_REHYDRATION_QUERY,
        historyCursor: { kind: 'responses', scopeDigest: 'a'.repeat(64), beforeSequence: '1' },
      },
      {
        ...DEFAULT_REHYDRATION_QUERY,
        historyCursor: { kind: 'history', scopeDigest: 'a'.repeat(64), beforeSequence: 1 },
      },
    ])
      expect(() => rehydrationQuery(change)).toThrow(RehydrationError);
    expect(() => rehydrationContext(alter(context(), ['work', 'hasMore'], true), REF)).toThrow(
      RehydrationError,
    );
  });
  it('rejects accessor/sparse/overridden arrays without invoking custom map', () => {
    let called = 0;
    const sparse = new Array(1);
    const mapped = Object.assign([message()], {
      map() {
        called++;
        return [];
      },
    });
    const getter = [message()];
    Object.defineProperty(getter, '0', {
      get() {
        called++;
        return message();
      },
      enumerable: true,
    });
    for (const value of [sparse, mapped, getter])
      expect(() =>
        rehydrationContext(alter(context(), ['history', 'messages'], value), REF),
      ).toThrow(RehydrationError);
    expect(called).toBe(0);
  });
  it('caps complete records and full UTF8 sections instead of silently truncating facts', () => {
    expect(() =>
      rehydrationContext(
        alter(context(), ['history', 'messages'], Array.from({ length: 9 }, message)),
        REF,
      ),
    ).toThrow(RehydrationError);
    const giant = alter(
      context(),
      ['history', 'messages', '0', 'event', 'body'],
      '界'.repeat(20000),
    );
    expect(() => rehydrationContext(giant, REF)).toThrow(RehydrationError);
    expect(() => rehydrationContext(alter(context(), ['observed', 'atomic'], true), REF)).toThrow(
      RehydrationError,
    );
  });
  it('recomputes historical anchor/receipt binding and rejects forged source control', () => {
    const valid = historical();
    expect(historicalResponse(valid, REF).anchor.bindingId).toBe(OLD_BINDING);
    for (const [path, value] of [
      [['receipt', 'responseId'], randomUUID()],
      [['receipt', 'anchorDigest'], 'c'.repeat(64)],
      [['anchor', 'providerScope', 'tenantId'], 'foreign'],
      [['anchor', 'roomId'], 'other-room'],
      [['historical'], false],
      [['sdk', 'state'], 'played'],
      [['generated', 'textDigest'], 'a'.repeat(64)],
    ] as [string[], unknown][])
      expect(() => historicalResponse(alter(valid, path, value), REF)).toThrow(RehydrationError);
  });
  it('keeps standalone authority honest without inventing a committed intent', async () => {
    const inspect = vi.fn(async () => ({
      scope: REF.scope,
      caseId: REF.caseId,
      revision: '3',
      request: { ...REQUEST, bookingReference: 'DEMO-BK-001' } as {
        schemaVersion: 1;
        kind: 'booking_investigation';
        bookingReference: string;
        newCheckIn: string;
        investigationConsent: true;
      },
      cancelled: false,
      committed: false,
    }));
    const adapter = referenceCurrentCase({ inspect });
    const value = await adapter.inspect(REF, new AbortController().signal);
    expect(value).toMatchObject({
      source: 'standalone_reference_v1',
      workflow: null,
      supplierResult: null,
      revision: '3',
      intent: { state: 'not_committed', intentId: null },
    });
    expect(inspect).toHaveBeenCalledOnce();
  });
});

describe('actual current-case loopback HTTP client', () => {
  it('sends exact trusted selectors and returns a copied source-qualified case', async () => {
    const seen = deferred<{ path: string | undefined; auth: string | undefined; body: unknown }>();
    const local = await peer((req, res) => {
      void readRequest(req).then((raw) => {
        seen.resolve({ path: req.url, auth: req.headers.authorization, body: JSON.parse(raw) });
        reply(res, { schemaVersion: 1, status: 'known', case: current() });
      });
    });
    const reader = client(local.endpoint);
    const value = await reader.inspect(REF, new AbortController().signal);
    expect(value.request.bookingReference).toBe('BÉK-001');
    expect(await seen.promise).toEqual({
      path: '/v1/current-case/inspect',
      auth: AUTH,
      body: { schemaVersion: 1, ...REF },
    });
    await reader.close();
    expect(reader.metrics().active).toBe(0);
  });
  it('snapshots endpoint and allowlist and denies another conversation without I/O', async () => {
    let calls = 0;
    const local = await peer((_req, res) => {
      calls++;
      reply(res, { schemaVersion: 1, status: 'known', case: current() });
    });
    const allowed = [structuredClone(REF)],
      endpoint = { ...local.endpoint };
    const reader = new CurrentCaseHttpClient(endpoint, AUTH, allowed);
    closes.push(() => reader.close());
    allowed[0]!.caseId = 'changed';
    endpoint.port = 1;
    expect((await reader.inspect(REF, new AbortController().signal)).caseId).toBe(REF.caseId);
    await expect(
      reader.inspect({ ...REF, conversationId: 'foreign' }, new AbortController().signal),
    ).rejects.toMatchObject({ code: 'access_denied' });
    expect(calls).toBe(1);
  });
  it.each([
    ['AccessDenied', 'access_denied'],
    ['InvalidCommand', 'invalid_query'],
    ['Overloaded', 'overloaded'],
    ['Unavailable', 'context_unavailable'],
  ])('maps fixed %s response honestly', async (code, expected) => {
    const local = await peer((_req, res) =>
      reply(res, { schemaVersion: 1, status: 'unavailable', code }),
    );
    await expect(
      client(local.endpoint).inspect(REF, new AbortController().signal),
    ).rejects.toMatchObject({ code: expected });
  });
  it.each(['mismatch', 'extra', 'boolean', 'status', 'content-type', 'missing-close', 'oversized'])(
    'rejects malformed %s response',
    async (kind) => {
      const local = await peer((_req, res) => {
        if (kind === 'status')
          return reply(res, { schemaVersion: 1, status: 'known', case: current() }, 302);
        if (kind === 'content-type')
          return reply(res, { schemaVersion: 1, status: 'known', case: current() }, 200, {
            'content-type': 'text/plain',
          });
        if (kind === 'missing-close') {
          const raw = JSON.stringify({ schemaVersion: 1, status: 'known', case: current() });
          res.writeHead(200, {
            'content-type': 'application/json',
            'content-length': Buffer.byteLength(raw),
            connection: 'keep-alive',
          });
          res.end(raw);
          return;
        }
        if (kind === 'oversized') {
          reply(res, { padding: 'x'.repeat(9000) });
          return;
        }
        const value = kind === 'mismatch' ? alter(current(), ['caseId'], 'foreign') : current();
        reply(res, {
          schemaVersion: kind === 'boolean' ? true : 1,
          status: 'known',
          case: value,
          ...(kind === 'extra' ? { quote: 'private' } : {}),
        });
      });
      await expect(
        client(local.endpoint).inspect(REF, new AbortController().signal),
      ).rejects.toMatchObject({ code: 'context_unavailable' });
    },
  );
  it('aborts the actual socket and permits later useful reads only after settlement', async () => {
    const entered = deferred<void>();
    let held = true;
    const local = await peer((_req, res) => {
      entered.resolve();
      if (!held) reply(res, { schemaVersion: 1, status: 'known', case: current() });
    });
    const reader = client(local.endpoint, { timeoutMs: 1000, maxActive: 1 });
    const signal = new AbortController();
    const waiting = reader.inspect(REF, signal.signal);
    const rejected = expect(waiting).rejects.toMatchObject({ code: 'context_unavailable' });
    await entered.promise;
    signal.abort();
    await rejected;
    for (let n = 0; n < 100 && reader.metrics().active !== 0; n++) await delay(5);
    expect(reader.metrics().active).toBe(0);
    held = false;
    expect((await reader.inspect(REF, new AbortController().signal)).revision).toBe('2');
  });
  it('bounds timeouts, close and active requests with no automatic retry', async () => {
    let calls = 0;
    const local = await peer(() => {
      calls++;
    });
    const reader = client(local.endpoint, { timeoutMs: 20, maxActive: 1 });
    await expect(reader.inspect(REF, new AbortController().signal)).rejects.toMatchObject({
      code: 'context_unavailable',
    });
    await reader.close();
    expect(reader.metrics().active).toBe(0);
    expect(calls).toBe(1);
    await expect(reader.inspect(REF, new AbortController().signal)).rejects.toMatchObject({
      code: 'context_unavailable',
    });
  });
  it('rejects endpoint/credential/allowlist options without invoking accessors', () => {
    let calls = 0;
    const options = Object.defineProperty({}, 'timeoutMs', {
      enumerable: true,
      get() {
        calls++;
        return 20;
      },
    });
    expect(
      () => new CurrentCaseHttpClient({ host: '127.0.0.1', port: 1 }, AUTH, [REF], options),
    ).toThrow(RehydrationError);
    expect(calls).toBe(0);
    expect(
      () => new CurrentCaseHttpClient({ host: 'localhost', port: 1 } as never, AUTH, [REF]),
    ).toThrow(RehydrationError);
    expect(
      () =>
        new CurrentCaseHttpClient({ host: '127.0.0.1', port: 1 }, 'Bearer ' + 'a'.repeat(42), [
          REF,
        ]),
    ).toThrow(RehydrationError);
    expect(() => new CurrentCaseHttpClient({ host: '127.0.0.1', port: 1 }, AUTH, [])).toThrow(
      RehydrationError,
    );
  });
});

describe('actual rehydration receiving HTTP with explicit mocked read facade', () => {
  function facade(
    native = vi.fn(async () => rehydrationContext(context(), REF)),
    sms = vi.fn(async () => rehydrationContext(context(), REF)),
  ) {
    const server = new RehydrationHttpServer({ native, sms } as unknown as ChannelRehydrator);
    closes.push(() => server.close());
    return { server, native, sms };
  }
  it('receives native query and original bearer without changing model scope', async () => {
    const f = facade(),
      endpoint = await f.server.start();
    const response = await post(endpoint, '/v1/rehydration/native', {
      schemaVersion: 1,
      query: DEFAULT_REHYDRATION_QUERY,
    });
    expect(response.status).toBe(200);
    expect(JSON.parse(response.raw).status).toBe('known');
    expect(f.native).toHaveBeenCalledWith(AUTH.slice(7), DEFAULT_REHYDRATION_QUERY);
    expect(f.sms).not.toHaveBeenCalled();
    await f.server.close();
    expect(f.server.metrics()).toMatchObject({ sockets: 0, handlers: 0 });
  });
  it('receives exact base64 SMS bytes and source HMAC separately without accepting input', async () => {
    const f = facade(),
      endpoint = await f.server.start();
    const raw = Buffer.from('{"original":"☃"}');
    const headers = { timestamp: '1893456000', signature: 'hmac-proof' };
    const response = await post(endpoint, '/v1/rehydration/sms', {
      schemaVersion: 1,
      rawSms: raw.toString('base64'),
      headers,
      query: DEFAULT_REHYDRATION_QUERY,
    });
    expect(JSON.parse(response.raw).status).toBe('known');
    expect(f.sms).toHaveBeenCalledWith(raw, headers, DEFAULT_REHYDRATION_QUERY);
    expect(f.native).not.toHaveBeenCalled();
  });
  it('rejects missing native bearer, control fields and noncanonical base64 before facade', async () => {
    const f = facade(),
      endpoint = await f.server.start();
    for (const [path, body, headers] of [
      [
        '/v1/rehydration/native',
        { schemaVersion: 1, query: DEFAULT_REHYDRATION_QUERY },
        { authorization: '' },
      ],
      [
        '/v1/rehydration/native',
        { schemaVersion: 1, query: DEFAULT_REHYDRATION_QUERY, caseId: 'foreign' },
        {},
      ],
      [
        '/v1/rehydration/sms',
        {
          schemaVersion: 1,
          rawSms: '@@@',
          headers: { timestamp: 'x', signature: 'y' },
          query: DEFAULT_REHYDRATION_QUERY,
        },
        {},
      ],
    ] as [string, unknown, Record<string, string>][]) {
      const response = await post(endpoint, path, body, headers);
      expect(JSON.parse(response.raw).status).toBe('unavailable');
    }
    expect(f.native).not.toHaveBeenCalled();
    expect(f.sms).not.toHaveBeenCalled();
  });
  it('denies a different loopback Host rather than trusting a shape-only label', async () => {
    const f = facade(),
      endpoint = await f.server.start();
    const response = await post(
      endpoint,
      '/v1/rehydration/native',
      { schemaVersion: 1, query: DEFAULT_REHYDRATION_QUERY },
      { host: '127.0.0.1:1' },
    );
    expect(JSON.parse(response.raw).status).toBe('unavailable');
    expect(f.native).not.toHaveBeenCalled();
  });
  it('contains malformed dependency error codes instead of reflecting private values', async () => {
    const native = vi.fn(async () => {
      throw new RehydrationError('SENTINEL_PRIVATE_DEPENDENCY_CODE' as never);
    });
    const f = facade(native),
      endpoint = await f.server.start();
    const response = await post(endpoint, '/v1/rehydration/native', {
      schemaVersion: 1,
      query: DEFAULT_REHYDRATION_QUERY,
    });
    expect(JSON.parse(response.raw)).toEqual({
      schemaVersion: 1,
      status: 'unavailable',
      code: 'context_unavailable',
    });
    expect(response.raw).not.toContain('SENTINEL_PRIVATE');
  });
  it('keeps a held actual facade task owned through close until settlement', async () => {
    const entered = deferred<void>(),
      release = deferred<void>();
    const native = vi.fn(async () => {
      entered.resolve();
      await release.promise;
      return rehydrationContext(context(), REF);
    });
    const f = facade(native),
      endpoint = await f.server.start();
    const waiting = post(endpoint, '/v1/rehydration/native', {
      schemaVersion: 1,
      query: DEFAULT_REHYDRATION_QUERY,
    }).catch(() => undefined);
    await entered.promise;
    let closed = false;
    const closing = f.server.close().then(() => {
      closed = true;
    });
    await delay(20);
    expect(closed).toBe(false);
    expect(f.server.metrics().handlers).toBe(1);
    release.resolve();
    await closing;
    await waiting;
    expect(f.server.metrics()).toMatchObject({ handlers: 0, sockets: 0 });
  });
});
