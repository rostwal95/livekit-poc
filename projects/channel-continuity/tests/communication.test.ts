/** Independent public reducer/capability tests and real HTTP with mocked persistence only. */
import { request as httpRequest, type ClientRequest } from 'node:http';
import { setTimeout as delay } from 'node:timers/promises';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const calls = vi.hoisted(() => ({
  constructed: vi.fn(),
  responses: vi.fn(),
  begin: vi.fn(),
  sdk: vi.fn(),
  browser: vi.fn(),
  inspect: vi.fn(),
  inboxClose: vi.fn(),
  eligible: vi.fn(),
  step: vi.fn(),
  dispatcherClose: vi.fn(),
}));
vi.mock('../src/postgres.js', async (original) => ({
  ...(await original<typeof import('../src/postgres.js')>()),
  ChannelInbox: class {
    constructor() {
      calls.constructed();
    }
    communicationBegin = calls.begin;
    communicationSdk = calls.sdk;
    communicationBrowser = calls.browser;
    communicationInspect = calls.inspect;
    communicationMetrics = () => Object.freeze({});
    communicationResponses = calls.responses;
    close = calls.inboxClose;
  },
}));
vi.mock('../src/dispatch.js', () => ({
  ChannelDispatcher: class {
    eligible = calls.eligible;
    step = calls.step;
    close = calls.dispatcherClose;
  },
}));
const created = vi.hoisted(() => ({ servers: [] as import('node:http').Server[] }));
vi.mock('node:http', async (original) => {
  const actual = await original<typeof import('node:http')>();
  return {
    ...actual,
    createServer: (...args: Parameters<typeof actual.createServer>) => {
      const server = actual.createServer(...args);
      created.servers.push(server);
      return server;
    },
  };
});
import {
  CommunicationGateway,
  CommunicationInbox,
  DEFAULT_COMMUNICATION_LIMITS,
  createCommunicationIntegration,
  reduceCommunicationEvidence,
  type CommunicationIntegration,
  type CommunicationGrant,
  type StoredObservation,
} from '../src/communication.js';
import { createNativeIntegration } from '../src/native.js';
import { ChannelError, SeededAccounts } from '../src/postgres.js';
import type { GatewayEndpoint } from '../src/gateway.js';

const uuid = (n: number) => `${n.toString().padStart(8, '0')}-1111-4111-8111-111111111111`;
const SCOPE = { tenantId: 'tenant', accountId: 'account' };
const PROVIDER = { tenantId: 'tenant', provider: 'livekit', providerAccountId: 'local' };
const PUBLISHER = 'P'.repeat(43),
  SDK = 'S'.repeat(43),
  BROWSER = 'B'.repeat(43),
  ACCOUNT = 'A'.repeat(43);
const DATABASE = {
  host: '127.0.0.1',
  port: 1,
  database: 'livekit_lab',
  user: 'livekit_lab',
  password: 'synthetic',
  schema: 'p2_inbox_' + 'a'.repeat(32),
};
const raw = (value: unknown) => Buffer.from(JSON.stringify(value));
const source = () =>
  createNativeIntegration(PROVIDER, [
    { token: 'N'.repeat(43), scope: SCOPE, caseId: 'case', conversationId: 'conversation' },
  ]);
const grant = (): CommunicationGrant => ({
  scope: { ...SCOPE },
  caseId: 'case',
  conversationId: 'conversation',
  publisherToken: PUBLISHER,
  sdkToken: SDK,
  browserToken: BROWSER,
});
const integration = () => createCommunicationIntegration(source(), [grant()]);
function receipt(eventId: string, responseId = uuid(1)) {
  return {
    responseId,
    eventId,
    receiptId: uuid(90),
    payloadDigest: 'a'.repeat(64),
    observationSequence: '1',
    acceptedAt: '2026-11-11T00:00:00.000Z',
  };
}
function generated(text = 'Complete generated text', eventId = uuid(10)): StoredObservation {
  return {
    source: 'agent_sdk',
    payload: {
      schemaVersion: 1,
      eventId,
      responseId: uuid(1),
      generationId: uuid(2),
      sdkSpeechId: 'speech_original',
      fact: { type: 'generated_complete', text },
    },
    receipt: receipt(eventId),
  };
}
function settled(
  state: 'completed' | 'interrupted' | 'unknown',
  sdkText: string | null = null,
  eventId = uuid(11),
): StoredObservation {
  return {
    source: 'agent_sdk',
    payload: {
      schemaVersion: 1,
      eventId,
      responseId: uuid(1),
      generationId: uuid(2),
      sdkSpeechId: 'speech_original',
      fact: { type: 'speech_settled', state, sdkText },
    },
    receipt: receipt(eventId),
  };
}
function browser(
  state: 'started' | 'partial' | 'interrupted' | 'completed',
  eventId = uuid(12),
  responseId = uuid(1),
): StoredObservation {
  return {
    source: 'browser_client',
    payload: { schemaVersion: 1, eventId, responseId, state, observedAudioMs: 500 },
    receipt: receipt(eventId, responseId),
  };
}
function unsafe(value: unknown): StoredObservation {
  return value as StoredObservation;
}
function anchor() {
  return {
    schemaVersion: 1,
    responseId: uuid(1),
    generationId: uuid(2),
    sdkSpeechId: 'speech_original',
    bindingId: uuid(3),
    inputId: uuid(4),
    receiptId: uuid(5),
    operationKey: uuid(6),
    caseRevision: '9223372036854775807',
  };
}
function responseReceipt() {
  return {
    responseId: uuid(1),
    receiptId: uuid(7),
    anchorDigest: 'b'.repeat(64),
    responseSequence: '1',
    acceptedAt: '2026-11-11T00:00:00.000Z',
  };
}
const gateways: CommunicationGateway[] = [];
function gateway(options: Record<string, unknown> = {}) {
  const g = new CommunicationGateway({
    database: DATABASE,
    integration: integration(),
    accounts: [{ token: ACCOUNT, ...SCOPE, caseId: 'case', conversationId: 'conversation' }],
    ports: {
      cases: {
        async inspect(input) {
          return { ...input, revision: '1', source: 'synthetic_read_only' };
        },
      },
      agent: {
        async prepare(input) {
          return {
            kind: 'investigation',
            source: 'scripted',
            caseRevision: input.currentCase.revision,
          };
        },
      },
      operations: {
        capabilities: 'stable_idempotency_and_lookup',
        async lookup() {
          return { status: 'absent' };
        },
        async accept() {
          throw new Error('unused');
        },
      },
    },
    options: { pollMs: 20, cleanupMs: 100, observer: () => {}, ...options },
  });
  gateways.push(g);
  return g;
}
function request(
  endpoint: GatewayEndpoint,
  path: string,
  body: Buffer,
  authorization = SDK,
  extra: Record<string, string> = {},
) {
  let req!: ClientRequest;
  const result = new Promise<{ status: number; body: Record<string, unknown>; bytes: number }>(
    (resolve, reject) => {
      req = httpRequest(
        {
          host: endpoint.host,
          port: endpoint.port,
          method: 'POST',
          path,
          agent: false,
          headers: {
            'Content-Type': 'application/json',
            'Content-Length': String(body.length),
            Authorization: `Bearer ${authorization}`,
            Connection: 'close',
            ...extra,
          },
        },
        (response) => {
          const chunks: Buffer[] = [];
          let bytes = 0;
          response.on('data', (chunk: Buffer) => {
            bytes += chunk.length;
            if (bytes > 65536) req.destroy(new Error('test_response_bound'));
            else chunks.push(chunk);
          });
          response.once('error', reject);
          response.once('end', () => {
            try {
              resolve({
                status: response.statusCode ?? 0,
                body: JSON.parse(Buffer.concat(chunks).toString('utf8')) as Record<string, unknown>,
                bytes,
              });
            } catch (error) {
              reject(error);
            }
          });
        },
      );
      req.once('error', reject);
      req.setTimeout(2000, () => req.destroy(new Error('test_http_timeout')));
      req.end(body);
    },
  );
  return { req, result };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}
async function until(test: () => boolean) {
  const end = performance.now() + 2000;
  while (!test()) {
    if (performance.now() >= end) throw new Error('test_wait_timeout');
    await delay(2);
  }
}
beforeEach(() => {
  vi.clearAllMocks();
  created.servers.length = 0;
  calls.responses.mockResolvedValue([]);
  calls.begin.mockResolvedValue(responseReceipt());
  calls.sdk.mockImplementation(async (_token, input: StoredObservation['payload']) =>
    receipt(input.eventId),
  );
  calls.browser.mockImplementation(async (_token, input: StoredObservation['payload']) =>
    receipt(input.eventId),
  );
  calls.inspect.mockResolvedValue({ opaque: 'test-persistence-view' });
  calls.eligible.mockResolvedValue([]);
  calls.step.mockResolvedValue({ status: 'idle' });
  calls.inboxClose.mockResolvedValue(undefined);
  calls.dispatcherClose.mockResolvedValue(undefined);
});
afterEach(async () => {
  for (const g of gateways.splice(0)) {
    await g.close();
    expect(g.metrics()).toMatchObject({ active: 0, handlers: 0, sockets: 0 });
  }
});

describe('public communication capability and source-qualified model boundary', () => {
  it('creates an opaque distinct native capability without exporting role tokens', () => {
    const native = source();
    const allowed = grant();
    const value = createCommunicationIntegration(native, [allowed]);
    expect(value).not.toBe(native);
    expect(value.providerScope).toEqual(PROVIDER);
    expect(Object.isFrozen(value)).toBe(true);
    expect(Object.keys(value)).toEqual(['providerScope']);
    expect(JSON.stringify(value)).not.toContain(PUBLISHER);
    expect(JSON.stringify(value)).not.toContain(SDK);
    expect(DEFAULT_COMMUNICATION_LIMITS).toEqual({
      maxResponses: 1024,
      maxObservations: 8192,
      maxObservationsPerResponse: 16,
    });
    expect(Object.isFrozen(DEFAULT_COMMUNICATION_LIMITS)).toBe(true);
  });
  it('rejects a forged communication capability before constructing inbox resources', () => {
    const forged = source() as CommunicationIntegration;
    expect(
      () =>
        new CommunicationInbox(
          DATABASE,
          forged,
          new SeededAccounts([
            { token: ACCOUNT, ...SCOPE, caseId: 'case', conversationId: 'conversation' },
          ]),
        ),
    ).toThrow();
    expect(calls.constructed).not.toHaveBeenCalled();
  });
  it.each(['publisherToken', 'sdkToken', 'browserToken'] as const)(
    'rejects %s reused from native publisher authority',
    (key) => {
      const allowed = { ...grant(), [key]: 'N'.repeat(43) };
      expect(() => createCommunicationIntegration(source(), [allowed])).toThrow();
    },
  );
  it('rejects overlapping role tokens and foreign tenant grants', () => {
    expect(() =>
      createCommunicationIntegration(source(), [{ ...grant(), sdkToken: PUBLISHER }]),
    ).toThrow();
    expect(() =>
      createCommunicationIntegration(source(), [
        { ...grant(), scope: { ...SCOPE, tenantId: 'foreign' } },
      ]),
    ).toThrow();
  });
  it('rejects accessor-bearing grants and sparse or overridden arrays without executing accessors', () => {
    const getter = vi.fn(() => SDK);
    const allowed = { ...grant() };
    Object.defineProperty(allowed, 'sdkToken', { get: getter });
    expect(() => createCommunicationIntegration(source(), [allowed])).toThrow();
    expect(getter).not.toHaveBeenCalled();
    const array = [grant()];
    Object.defineProperty(array, 'map', { get: getter });
    expect(() => createCommunicationIntegration(source(), array)).toThrow();
    expect(getter).not.toHaveBeenCalled();
    expect(() =>
      createCommunicationIntegration(source(), new Array<CommunicationGrant>(1)),
    ).toThrow();
  });
  it('keeps generated text, SDK partial observations and browser unknown as independent sources', () => {
    expect(
      reduceCommunicationEvidence([generated(), settled('interrupted', 'SDK synchronized text')]),
    ).toEqual({
      generatedText: 'Complete generated text',
      sdkState: 'interrupted',
      sdkText: 'SDK synchronized text',
      browserState: 'unknown',
      conflicted: false,
    });
    expect(reduceCommunicationEvidence([])).toEqual({
      generatedText: null,
      sdkState: 'unknown',
      sdkText: null,
      browserState: 'unknown',
      conflicted: false,
    });
  });
  it('does not infer a full SDK or browser output from full generated text or a large duration', () => {
    expect(reduceCommunicationEvidence([generated()])).toMatchObject({
      sdkState: 'unknown',
      browserState: 'unknown',
    });
    expect(reduceCommunicationEvidence([browser('partial')])).toMatchObject({
      generatedText: null,
      sdkState: 'unknown',
      browserState: 'partial',
    });
  });
  it('preserves completed_reported wording without any human acknowledgement field', () => {
    const value = reduceCommunicationEvidence([
      settled('completed', 'SDK text'),
      browser('completed'),
    ]);
    expect(value.browserState).toBe('completed_reported');
    expect(Object.hasOwn(value, 'humanAck')).toBe(false);
    expect(Object.isFrozen(value)).toBe(true);
  });
  it('folds report order conservatively and exposes contradictory source facts', () => {
    const rows = [generated(), settled('interrupted', 'Partial'), browser('completed')];
    expect(reduceCommunicationEvidence(rows)).toEqual(
      reduceCommunicationEvidence([...rows].reverse()),
    );
    expect(reduceCommunicationEvidence(rows)).toMatchObject({
      sdkState: 'interrupted',
      browserState: 'conflicted',
      conflicted: true,
    });
    expect(
      reduceCommunicationEvidence([generated('one'), generated('two', uuid(13))]),
    ).toMatchObject({ generatedText: null, conflicted: true });
  });
  it('retains SDK uncertainty and text separately, including incompatible synchronized texts', () => {
    expect(reduceCommunicationEvidence([settled('unknown')])).toMatchObject({
      sdkState: 'unknown',
      sdkText: null,
    });
    expect(
      reduceCommunicationEvidence([
        settled('completed', 'one'),
        settled('completed', 'two', uuid(14)),
      ]),
    ).toMatchObject({ sdkState: 'conflicted', sdkText: null, conflicted: true });
  });
  it.each(['receipt-response', 'receipt-event', 'mixed-response', 'browser-first'] as const)(
    'rejects browser identity mismatch: %s',
    (variant) => {
      const b = browser('completed');
      const changed =
        variant === 'receipt-response'
          ? unsafe({ ...b, receipt: { ...b.receipt, responseId: uuid(20) } })
          : variant === 'receipt-event'
            ? unsafe({ ...b, receipt: { ...b.receipt, eventId: uuid(20) } })
            : browser('completed', uuid(12), uuid(20));
      const rows = variant === 'browser-first' ? [changed, generated()] : [generated(), changed];
      expect(() => reduceCommunicationEvidence(rows)).toThrow();
    },
  );
  it.each(['generationId', 'sdkSpeechId', 'responseId'] as const)(
    'rejects mixed SDK %s before folding',
    (key) => {
      const g = generated();
      const value = unsafe({
        ...g,
        payload: { ...g.payload, [key]: key === 'sdkSpeechId' ? 'other_speech' : uuid(20) },
      });
      expect(() => reduceCommunicationEvidence([settled('completed'), value])).toThrow();
    },
  );
  it.each([true, -1, 0.1, 180001, NaN, Infinity])(
    'rejects invalid browser duration %s',
    (value) => {
      const b = browser('started');
      expect(() =>
        reduceCommunicationEvidence([
          unsafe({ ...b, payload: { ...b.payload, observedAudioMs: value } }),
        ]),
      ).toThrow();
    },
  );
  it('bounds generated text by UTF8 bytes and rejects lone UTF16 surrogates', () => {
    expect(reduceCommunicationEvidence([generated('🙂'.repeat(1024))]).generatedText).toBe(
      '🙂'.repeat(1024),
    );
    for (const text of ['🙂'.repeat(1024) + 'x', '', '\ud800'])
      expect(() => reduceCommunicationEvidence([generated(text)])).toThrow();
  });
  it('rejects mixed source claims, extra authority fields and excessive retained rows', () => {
    expect(() =>
      reduceCommunicationEvidence([unsafe({ ...generated(), source: 'publisher' })]),
    ).toThrow();
    expect(() =>
      reduceCommunicationEvidence([unsafe({ ...generated(), acknowledged: true })]),
    ).toThrow();
    expect(() =>
      reduceCommunicationEvidence(Array.from({ length: 65 }, () => generated())),
    ).toThrow();
  });
});

describe('actual communication HTTP receiving boundary with mocked persistence ports', () => {
  it('routes exact validated anchors and original role credentials over actual loopback HTTP', async () => {
    const g = gateway();
    const endpoint = await g.listen();
    expect(endpoint.host).toBe('127.0.0.1');
    const response = await request(endpoint, '/v1/native/responses', raw(anchor()), PUBLISHER)
      .result;
    expect(response.status).toBe(200);
    expect(response.body).toEqual({ schemaVersion: 1, status: 'known', result: responseReceipt() });
    expect(calls.begin).toHaveBeenCalledExactlyOnceWith(PUBLISHER, anchor());
    expect(Object.isFrozen(calls.begin.mock.calls[0]?.[1])).toBe(true);
    expect(calls.begin.mock.calls[0]?.[1].caseRevision).toBe('9223372036854775807');
  });
  it('keeps SDK and browser credentials and payload routes separate', async () => {
    const g = gateway();
    const endpoint = await g.listen();
    const sdk = generated();
    const b = browser('partial');
    expect(
      (await request(endpoint, '/v1/native/sdk-observations', raw(sdk.payload), SDK).result).status,
    ).toBe(200);
    expect(
      (await request(endpoint, '/v1/native/browser-observations', raw(b.payload), BROWSER).result)
        .status,
    ).toBe(200);
    expect(calls.sdk).toHaveBeenCalledExactlyOnceWith(SDK, sdk.payload);
    expect(calls.browser).toHaveBeenCalledExactlyOnceWith(BROWSER, b.payload);
    expect(
      (
        await request(
          endpoint,
          '/v1/native/response-inspect',
          raw({ schemaVersion: 1, responseId: uuid(1) }),
          ACCOUNT,
        ).result
      ).body,
    ).toMatchObject({ status: 'known' });
    expect(calls.inspect).toHaveBeenCalledExactlyOnceWith(ACCOUNT, uuid(1));
  });
  it.each(['duplicate', 'whitespace', 'utf8', 'oversized', 'extra-source'] as const)(
    'rejects malformed %s before any persistence call',
    async (variant) => {
      const g = gateway();
      const endpoint = await g.listen();
      const body =
        variant === 'duplicate'
          ? Buffer.from(
              JSON.stringify(anchor()).replace(
                '"schemaVersion":1',
                '"schemaVersion":1,"schemaVersion":1',
              ),
            )
          : variant === 'whitespace'
            ? Buffer.from(JSON.stringify(anchor()) + '\n')
            : variant === 'utf8'
              ? Buffer.from([255])
              : variant === 'oversized'
                ? Buffer.alloc(32769, 32)
                : raw({ ...anchor(), source: 'publisher' });
      const response = await request(endpoint, '/v1/native/responses', body, PUBLISHER).result;
      expect(response.status).toBe(400);
      expect(response.body).toEqual({
        schemaVersion: 1,
        status: 'rejected',
        code: 'invalid_input',
      });
      expect(calls.begin).not.toHaveBeenCalled();
    },
  );
  it('rejects malformed bearer framing before dispatch and maps source authorization denials safely', async () => {
    const g = gateway();
    const endpoint = await g.listen();
    const malformed = await request(endpoint, '/v1/native/responses', raw(anchor()), PUBLISHER, {
      Authorization: 'Basic synthetic',
    }).result;
    expect(malformed.status).toBe(403);
    expect(calls.begin).not.toHaveBeenCalled();
    calls.begin.mockRejectedValueOnce(new ChannelError('AccessDenied'));
    const denied = await request(endpoint, '/v1/native/responses', raw(anchor()), SDK).result;
    expect(denied.status).toBe(403);
    expect(denied.body).toEqual({ schemaVersion: 1, status: 'rejected', code: 'forbidden' });
    expect(JSON.stringify(denied.body)).not.toContain(SDK);
  });
  it('retains uncertain storage acknowledgements instead of representing a definitive rejection', async () => {
    const g = gateway();
    const endpoint = await g.listen();
    calls.sdk.mockRejectedValueOnce(new ChannelError('AcknowledgementUnknown'));
    const response = await request(
      endpoint,
      '/v1/native/sdk-observations',
      raw(generated().payload),
      SDK,
    ).result;
    expect(response.status).toBe(503);
    expect(response.body).toEqual({
      schemaVersion: 1,
      status: 'unknown',
      code: 'acknowledgement_unknown',
    });
    expect(calls.sdk).toHaveBeenCalledOnce();
  });
  it('keeps a disconnected caller handler owned until the actual persistence call settles', async () => {
    const gate = deferred<ReturnType<typeof responseReceipt>>();
    calls.begin.mockReturnValueOnce(gate.promise);
    const g = gateway({ cleanupMs: 20 });
    const endpoint = await g.listen();
    const pending = request(endpoint, '/v1/native/responses', raw(anchor()), PUBLISHER);
    const observed = pending.result.catch((error: unknown) => error);
    await until(() => calls.begin.mock.calls.length === 1);
    pending.req.destroy();
    await observed;
    expect(g.metrics().active).toBe(1);
    expect(g.metrics().handlers).toBe(1);
    await expect(g.close()).rejects.toMatchObject({ code: 'cleanup_incomplete' });
    expect(g.metrics().active).toBe(1);
    gate.resolve(responseReceipt());
    await until(() => g.metrics().active === 0);
    await g.close();
    expect(g.metrics()).toMatchObject({ active: 0, handlers: 0, sockets: 0 });
  });
  it('contains observer failure and permits later useful HTTP work', async () => {
    const observer = vi.fn(() => {
      throw new Error('synthetic_observer');
    });
    const g = gateway({ observer });
    const endpoint = await g.listen();
    expect(
      (await request(endpoint, '/v1/native/responses', raw(anchor()), PUBLISHER).result).status,
    ).toBe(200);
    expect(
      (await request(endpoint, '/v1/native/sdk-observations', raw(generated().payload), SDK).result)
        .status,
    ).toBe(200);
    expect(observer).toHaveBeenCalled();
    expect(g.metrics().telemetryFailures).toBeGreaterThan(0);
  });
});

describe('communication receiving bounds and later progress', () => {
  it('bounds serialized receipt and view replies without exposing oversized backend values', async () => {
    const g = gateway();
    const endpoint = await g.listen();
    calls.begin.mockResolvedValueOnce({ ...responseReceipt(), privateOverflow: 'z'.repeat(2048) });
    const receipt = await request(endpoint, '/v1/native/responses', raw(anchor()), PUBLISHER)
      .result;
    expect(receipt.status).toBe(503);
    expect(receipt.body).toEqual({
      schemaVersion: 1,
      status: 'unknown',
      code: 'acknowledgement_unknown',
    });
    expect(receipt.bytes).toBeLessThan(2048);
    calls.inspect.mockResolvedValueOnce({ privateOverflow: 'z'.repeat(65536) });
    const view = await request(
      endpoint,
      '/v1/native/response-inspect',
      raw({ schemaVersion: 1, responseId: uuid(1) }),
      ACCOUNT,
    ).result;
    expect(view.status).toBe(503);
    expect(view.body).toEqual({
      schemaVersion: 1,
      status: 'unknown',
      code: 'acknowledgement_unknown',
    });
    expect(view.bytes).toBeLessThan(2048);
  });
  it('allows later useful HTTP after a disconnected waiter settles without silently redoing that call', async () => {
    const gate = deferred<ReturnType<typeof responseReceipt>>();
    calls.begin.mockReturnValueOnce(gate.promise);
    const g = gateway();
    const endpoint = await g.listen();
    const first = request(endpoint, '/v1/native/responses', raw(anchor()), PUBLISHER);
    const observed = first.result.catch((error: unknown) => error);
    await until(() => calls.begin.mock.calls.length === 1);
    first.req.destroy();
    await observed;
    expect(g.metrics().active).toBe(1);
    gate.resolve(responseReceipt());
    await until(() => g.metrics().active === 0);
    const second = await request(endpoint, '/v1/native/responses', raw(anchor()), PUBLISHER).result;
    expect(second.status).toBe(200);
    expect(calls.begin).toHaveBeenCalledTimes(2);
  });
  it('rejects sparse and accessor-backed observation arrays without running caller methods', () => {
    const getter = vi.fn(() => generated());
    const rows = [generated()];
    Object.defineProperty(rows, '0', { get: getter });
    expect(() => reduceCommunicationEvidence(rows)).toThrow();
    expect(getter).not.toHaveBeenCalled();
    expect(() => reduceCommunicationEvidence(new Array<StoredObservation>(1))).toThrow();
  });
});

describe('communication-only v7 startup preflight ownership', () => {
  it('does not bind a listener when the genuine communication preflight port rejects an old schema', async () => {
    calls.responses.mockRejectedValueOnce(new ChannelError('UpgradeRequired'));
    const g = gateway();
    await expect(g.listen()).rejects.toMatchObject({ code: 'UpgradeRequired' });
    expect(calls.responses).toHaveBeenCalledExactlyOnceWith(ACCOUNT, { limit: 1 });
    expect(created.servers).toHaveLength(1);
    expect(created.servers[0]?.listening).toBe(false);
    await g.close();
    expect(g.metrics()).toMatchObject({ driver: 0, active: 0, sockets: 0 });
  });
  it('retains timed-out startup ownership and never binds after a late communication preflight settles', async () => {
    const gate = deferred<readonly never[]>();
    calls.responses.mockReturnValueOnce(gate.promise);
    const g = gateway({ startupMs: 20, cleanupMs: 20 });
    await expect(g.listen()).rejects.toMatchObject({ code: 'storage_unavailable' });
    expect(created.servers[0]?.listening).toBe(false);
    await expect(g.close()).rejects.toMatchObject({ code: 'cleanup_incomplete' });
    gate.resolve([]);
    await g.close();
    expect(created.servers[0]?.listening).toBe(false);
    expect(calls.responses).toHaveBeenCalledOnce();
    expect(g.metrics()).toMatchObject({ driver: 0, active: 0, sockets: 0 });
  });
});
