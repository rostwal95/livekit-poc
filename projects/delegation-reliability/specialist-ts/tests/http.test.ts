/** Real loopback sockets; scripted facts do not replace transport or lifetime assertions. */
import { readFileSync } from 'node:fs';
import { createServer, ServerResponse, type Server as HttpServer } from 'node:http';
import { connect, type Socket } from 'node:net';
import { setImmediate as immediate, setTimeout as delay } from 'node:timers/promises';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  CAPABILITY,
  canonical,
  EvidenceRegistry,
  LocalTrust,
  matchResult,
  produceRequest,
  SpecialistClient,
  SpecialistHttpError,
  SpecialistServer,
  tokenDigest,
} from '../src/index.js';
import type {
  DelegationRequest,
  Endpoint,
  PrincipalGrant,
  SpecialistEvent,
  SpecialistServerOptions,
} from '../src/index.js';
const fixture = JSON.parse(
  readFileSync(new URL('../../../../contracts/delegation/v1.json', import.meta.url), 'utf8'),
) as {
  producer_input: Record<string, unknown>;
  policy_body: string;
  result: Record<string, unknown>;
};
const TOKEN = 'A'.repeat(43),
  OTHER = 'B'.repeat(43),
  RESULT = 'C'.repeat(43),
  CANCEL = 'D'.repeat(43),
  INVOKE = 'E'.repeat(43),
  NO_EVIDENCE = 'F'.repeat(43);
const HEADER = 'Bearer ' + TOKEN;
let serial = 0;
function request(remaining = 3000, changes: Record<string, unknown> = {}): DelegationRequest {
  serial++;
  return produceRequest({
    ...structuredClone(fixture.producer_input),
    delegation_id: 'http_delegation_' + serial,
    attempt: { attempt_id: 'http_attempt_' + serial, number: 1 },
    deadline_at_ms: Date.now() + remaining,
    ...changes,
  });
}
function configured(input: DelegationRequest) {
  const grants = (
    token: string,
    invoke: boolean,
    result: boolean,
    cancel: boolean,
    evidence = true,
  ): PrincipalGrant => ({
    principal_id: 'principal_' + token[0]!.toLowerCase(),
    token_sha256: tokenDigest(token),
    scopes: [
      {
        scope: input.scope,
        invoke_capabilities: invoke ? [CAPABILITY] : [],
        result_capabilities: result ? [CAPABILITY] : [],
        cancel_capabilities: cancel ? [CAPABILITY] : [],
        evidence_sources: evidence ? [input.context_snapshot.policy_source_id] : [],
      },
    ],
  });
  return {
    trust: new LocalTrust([
      grants(TOKEN, true, true, true),
      grants(OTHER, true, true, true),
      grants(RESULT, false, true, false),
      grants(CANCEL, false, false, true),
      grants(INVOKE, true, false, false),
      grants(NO_EVIDENCE, true, true, false, false),
    ]),
    evidence: new EvidenceRegistry([
      { scope: input.scope, reference: input.evidence[0]!, body: Buffer.from(fixture.policy_body) },
    ]),
  };
}
const services = new Set<SpecialistServer>(),
  clients = new Set<SpecialistClient>(),
  sockets = new Set<Socket>(),
  peers = new Set<HttpServer>(),
  releases = new Set<() => void>();
const events: SpecialistEvent[] = [];
function barrier() {
  let release!: () => void, enter!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const entered = new Promise<void>((resolve) => {
    enter = resolve;
  });
  releases.add(release);
  return {
    release,
    entered,
    async hook() {
      enter();
      await held;
    },
  };
}
async function start(input: DelegationRequest, options: Partial<SpecialistServerOptions> = {}) {
  const server = new SpecialistServer({
    ...configured(input),
    observer: (event) => {
      events.push(event);
    },
    ...options,
  });
  services.add(server);
  return { server, endpoint: await server.listen() };
}
function client(endpoint: Endpoint, token = TOKEN, timeoutMs = 1000, maxActive = 4) {
  const selected = new SpecialistClient(endpoint, 'Bearer ' + token, { timeoutMs, maxActive });
  clients.add(selected);
  return selected;
}
async function until(check: () => boolean, milliseconds = 1000): Promise<void> {
  const end = performance.now() + milliseconds;
  while (!check()) {
    if (performance.now() > end) throw new Error('fixture_condition_not_observed');
    await delay(2);
  }
}
async function open(endpoint: Endpoint): Promise<Socket> {
  const socket = connect(endpoint.port, endpoint.host);
  sockets.add(socket);
  socket.once('close', () => sockets.delete(socket));
  await new Promise<void>((resolve, reject) => {
    socket.once('connect', resolve);
    socket.once('error', reject);
  });
  return socket;
}
async function exchange(endpoint: Endpoint, bytes: string | Buffer): Promise<string> {
  const socket = await open(endpoint);
  const chunks: Buffer[] = [];
  let size = 0;
  return await new Promise<string>((resolve, reject) => {
    const timer = setTimeout(() => {
      socket.destroy();
      reject(new Error('fixture_socket_timeout'));
    }, 2000);
    socket.on('data', (chunk) => {
      const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      size += bytes.length;
      if (size > 16384) {
        socket.destroy();
        reject(new Error('fixture_response_limit'));
      } else chunks.push(bytes);
    });
    socket.once('error', () => undefined);
    socket.once('close', () => {
      clearTimeout(timer);
      resolve(Buffer.concat(chunks).toString('utf8'));
    });
    socket.write(bytes);
  });
}
function head(
  endpoint: Endpoint,
  body: Uint8Array,
  extra = '',
  path = '/v1/invoke',
  auth = HEADER,
): string {
  return `POST ${path} HTTP/1.1\r\nHost: 127.0.0.1:${endpoint.port}\r\nAuthorization: ${auth}\r\nContent-Type: application/json\r\nContent-Length: ${body.length}\r\n${extra}\r\n`;
}
async function fake(
  handler: Parameters<typeof createServer>[0] extends never
    ? never
    : (
        request: import('node:http').IncomingMessage,
        response: import('node:http').ServerResponse,
      ) => void,
): Promise<Endpoint> {
  const server = createServer(handler);
  peers.add(server);
  server.on('connection', (socket) => {
    sockets.add(socket);
    socket.once('close', () => sockets.delete(socket));
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('fixture_address');
  return { host: '127.0.0.1', port: address.port };
}
afterEach(async () => {
  for (const release of releases) release();
  releases.clear();
  for (const socket of sockets) socket.destroy();
  for (const selected of clients) await selected.close();
  clients.clear();
  for (const service of services) await service.close();
  services.clear();
  for (const peer of peers) await new Promise<void>((resolve) => peer.close(() => resolve()));
  peers.clear();
  events.length = 0;
});

describe('bounded actual specialist HTTP invocation', () => {
  it('returns a source-bound candidate through real sockets and retires ephemeral history', async () => {
    const input = request();
    const { server, endpoint } = await start(input);
    const caller = client(endpoint);
    const result = await caller.invoke(input);
    expect(matchResult(input, result, Date.now())).toBe('candidate');
    expect(result.eligible).toBe(true);
    expect(result.producer.model_id).toBe(null);
    await expect(caller.status(input)).rejects.toMatchObject({ code: 'unknown_attempt' });
    expect(server.metrics().completed).toBe(1);
    expect(server.metrics().disconnects).toBe(0);
    expect(server.metrics().active).toBe(0);
  });
  it('keeps result and cancel grants distinct while held work remains an observation', async () => {
    const input = request();
    const held = barrier();
    const { server, endpoint } = await start(input, { hooks: { beforeEvaluate: held.hook } });
    const pending = client(endpoint)
      .invoke(input)
      .catch((error) => error);
    await held.entered;
    const observed = await client(endpoint, RESULT).status(input);
    expect(observed.state).toBe('running');
    expect(observed.durable).toBe(false);
    expect(observed.cancel_requested).toBe(false);
    await expect(client(endpoint, CANCEL).status(input)).rejects.toMatchObject({
      code: 'unauthorized',
    });
    await expect(client(endpoint, RESULT).cancel(input)).rejects.toMatchObject({
      code: 'unauthorized',
    });
    const cancelled = await client(endpoint, CANCEL).cancel(input);
    expect(cancelled.cancel_requested).toBe(true);
    expect(server.metrics().active).toBe(1);
    expect((await pending).code).toBe('request_aborted');
    held.release();
    await until(() => server.metrics().active === 0);
  });
  it('rejects invoke-only, result-only, missing evidence and forged scope before work', async () => {
    const input = request();
    const { server, endpoint } = await start(input);
    for (const token of [INVOKE, RESULT, NO_EVIDENCE])
      await expect(client(endpoint, token).invoke(input)).rejects.toMatchObject({
        code: 'unauthorized',
      });
    const forged = request(3000, {
      scope: { tenant_id: 'forged_tenant', account_id: 'forged_account' },
    });
    await expect(client(endpoint).invoke(forged)).rejects.toMatchObject({ code: 'unauthorized' });
    expect(server.metrics().invoked).toBe(0);
    expect((await client(endpoint).invoke(input)).eligible).toBe(true);
  });
  it('bounds attempts per principal and admits another principal plus later progress', async () => {
    const input = request();
    let first = true;
    const held = barrier();
    const { server, endpoint } = await start(input, {
      limits: { maxActive: 2, maxPerPrincipal: 1 },
      hooks: {
        async beforeEvaluate() {
          if (first) {
            first = false;
            await held.hook();
          }
        },
      },
    });
    const pending = client(endpoint).invoke(input);
    await held.entered;
    await expect(client(endpoint).invoke(request())).rejects.toMatchObject({ code: 'capacity' });
    expect((await client(endpoint, OTHER).invoke(request())).eligible).toBe(true);
    expect(server.metrics().active).toBe(1);
    held.release();
    await pending;
    expect((await client(endpoint).invoke(request())).eligible).toBe(true);
  });
  it('enforces trusted deadline and retains an uncooperative hook until actual settlement', async () => {
    const input = request(80);
    const held = barrier();
    const { server, endpoint } = await start(input, {
      limits: { maxActive: 1, maxPerPrincipal: 1, invokeMs: 80, closeMs: 30 },
      hooks: { beforeEvaluate: held.hook },
    });
    const pending = client(endpoint)
      .invoke(input)
      .catch((error) => error);
    await held.entered;
    expect((await pending).code).toBe('deadline_exceeded');
    expect(server.metrics().active).toBe(1);
    const observation = await client(endpoint).status(input);
    expect(observation.deadline_exceeded).toBe(true);
    expect(observation.state).toBe('running');
    await expect(client(endpoint, OTHER).invoke(request())).rejects.toMatchObject({
      code: 'capacity',
    });
    await expect(server.close()).rejects.toMatchObject({ code: 'cleanup_incomplete' });
    expect(server.metrics().active).toBe(1);
    held.release();
    await until(() => server.metrics().active === 0);
    await server.close();
    const freshInput = request();
    const fresh = await start(freshInput);
    expect((await client(fresh.endpoint).invoke(freshInput)).eligible).toBe(true);
  });
  it('marks caller abort separately and releases only after the held operation settles', async () => {
    const input = request();
    const held = barrier();
    const { server, endpoint } = await start(input, { hooks: { beforeEvaluate: held.hook } });
    const controller = new AbortController();
    const pending = client(endpoint)
      .invoke(input, { signal: controller.signal })
      .catch((error) => error);
    await held.entered;
    controller.abort();
    expect((await pending).code).toBe('request_aborted');
    await until(() => server.metrics().disconnects === 1);
    expect((await client(endpoint).status(input)).transport_disconnected).toBe(true);
    expect(server.metrics().active).toBe(1);
    held.release();
    await until(() => server.metrics().active === 0);
  });
  it('rejects expired and overly distant deadlines without creating an attempt', async () => {
    const input = request();
    const { server, endpoint } = await start(input);
    for (const value of [request(-1), request(61000)])
      await expect(client(endpoint).invoke(value)).rejects.toMatchObject({ code: 'expired' });
    expect(server.metrics().invoked).toBe(0);
  });
  it('contains sync and async observer failure without reflecting private input or errors', async () => {
    const input = request(3000, {
      context_snapshot: {
        ...(fixture.producer_input.context_snapshot as object),
        note: 'PRIVATE_NOTE_SENTINEL',
      },
    });
    const recorded: SpecialistEvent[] = [];
    const { server, endpoint } = await start(input, {
      observer: async (event) => {
        recorded.push(event);
        throw new Error('PRIVATE_OBSERVER_SENTINEL');
      },
    });
    expect((await client(endpoint).invoke(input)).eligible).toBe(true);
    await immediate();
    expect(server.metrics().observerFailures).toBeGreaterThan(0);
    expect(JSON.stringify(recorded)).not.toContain('PRIVATE_');
    expect(JSON.stringify(recorded)).not.toContain(TOKEN);
    for (const event of recorded)
      expect(Object.keys(event).sort()).toEqual(['code', 'event', 'operation']);
  });
  it('contains unexpected evaluator defects and still allows a later useful invocation', async () => {
    const input = request();
    let failed = false;
    const { server, endpoint } = await start(input, {
      hooks: {
        beforeEvaluate() {
          if (!failed) {
            failed = true;
            throw new Error('PRIVATE_HOOK_SENTINEL');
          }
        },
      },
    });
    const body = canonical(input);
    const failedResponse = await exchange(
      endpoint,
      Buffer.concat([Buffer.from(head(endpoint, body)), Buffer.from(body)]),
    );
    expect(failedResponse).toMatch(/^HTTP\/1\.1 500 /);
    expect(failedResponse).toContain('\"code\":\"internal_error\"');
    expect(failedResponse).not.toContain('PRIVATE_HOOK_SENTINEL');
    expect((await client(endpoint).invoke(request())).eligible).toBe(true);
    expect(JSON.stringify(events)).not.toContain('PRIVATE_HOOK_SENTINEL');
    expect(server.metrics().active).toBe(0);
  });
});

describe('actual HTTP framing and socket limits', () => {
  it.each([
    'Authorization: Bearer ' + OTHER + '\r\n',
    'Content-Type: application/json\r\n',
    'Content-Encoding: gzip\r\n',
    'Transfer-Encoding: chunked\r\n',
  ])('rejects duplicate or unsupported framing %s', async (extra) => {
    const input = request();
    const { server, endpoint } = await start(input);
    const body = canonical(input);
    const response = await exchange(
      endpoint,
      Buffer.concat([Buffer.from(head(endpoint, body, extra)), Buffer.from(body)]),
    );
    expect(response === '' || response.includes('specialist.http_error')).toBe(true);
    expect(server.metrics().invoked).toBe(0);
  });
  it('rejects excess raw fields even when a valid authorization precedes the extra fields', async () => {
    const input = request();
    const { server, endpoint } = await start(input);
    const body = canonical(input);
    const extra = Array.from(
      { length: 20 },
      (_, index) => `Connection: close\r\nX-Extra-${index}: value\r\n`,
    ).join('');
    await exchange(
      endpoint,
      Buffer.concat([Buffer.from(head(endpoint, body, extra)), Buffer.from(body)]),
    );
    expect(server.metrics().invoked).toBe(0);
  });
  it('rejects oversized declared/actual body, malformed JSON and unsupported fields before evaluation', async () => {
    const input = request();
    const { server, endpoint } = await start(input);
    for (const raw of [
      '{',
      JSON.stringify({ ...input, principal_id: 'forged' }),
      ' '.repeat(16385),
    ]) {
      const body = Buffer.from(raw);
      await exchange(endpoint, Buffer.concat([Buffer.from(head(endpoint, body)), body]));
    }
    expect(server.metrics().invoked).toBe(0);
    expect((await client(endpoint).invoke(input)).eligible).toBe(true);
  });
  it('bounds incomplete header and body lifetime without admitting work', async () => {
    const input = request();
    const { server, endpoint } = await start(input, { limits: { headerMs: 40, bodyMs: 40 } });
    await exchange(endpoint, 'POST /v1/invoke HTTP/1.1\r\nHost: 127.0.0.1');
    const body = canonical(input);
    const response = await exchange(endpoint, head(endpoint, body) + '{');
    expect(response === '' || response.includes('body_timeout')).toBe(true);
    await until(() => server.metrics().sockets === 0);
    expect(server.metrics().invoked).toBe(0);
    expect((await client(endpoint).invoke(input)).eligible).toBe(true);
  });
  it('contains truncated bodies, Expect and upgrade requests', async () => {
    const input = request();
    const { server, endpoint } = await start(input);
    const body = canonical(input);
    const socket = await open(endpoint);
    socket.resume();
    socket.end(head(endpoint, body) + '{');
    await until(() => socket.destroyed);
    await exchange(endpoint, head(endpoint, body, 'Expect: 100-continue\r\n'));
    await exchange(
      endpoint,
      'GET /v1/invoke HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n',
    );
    expect(server.metrics().invoked).toBe(0);
  });
  it('bounds raw slow-header connections independently of active attempts', async () => {
    const input = request();
    const { server, endpoint } = await start(input, {
      limits: { maxConnections: 2, headerMs: 60 },
    });
    const one = await open(endpoint),
      two = await open(endpoint);
    await until(() => server.metrics().sockets === 2);
    const third = await open(endpoint);
    third.write('P');
    await until(() => third.destroyed);
    expect(server.metrics().sockets).toBeLessThanOrEqual(2);
    one.destroy();
    two.destroy();
    await until(() => server.metrics().sockets === 0);
    expect((await client(endpoint).invoke(input)).eligible).toBe(true);
  });
  it('never dispatches a pipelined second request and normal keepalive intent is closed', async () => {
    const input = request();
    const { server, endpoint } = await start(input);
    const body = canonical(input);
    const bytes = Buffer.concat([
      Buffer.from(head(endpoint, body, 'Connection: keep-alive\r\n')),
      Buffer.from(body),
    ]);
    await exchange(endpoint, Buffer.concat([bytes, bytes]));
    expect(server.metrics().invoked).toBeLessThanOrEqual(1);
    await until(() => server.metrics().active === 0);
    expect((await client(endpoint).invoke(request())).eligible).toBe(true);
  });
});

describe('typed client response and ownership guards', () => {
  it.each(['redirect', 'oversized', 'malformed', 'wrong_attempt'])(
    'rejects a %s response without following or inventing a result',
    async (mode) => {
      const input = request();
      let calls = 0;
      const endpoint = await fake((_request, response) => {
        calls++;
        let body = Buffer.from('{}');
        let status = 200;
        if (mode === 'redirect') status = 302;
        else if (mode === 'oversized') body = Buffer.alloc(8193, 32);
        else if (mode === 'wrong_attempt')
          body = Buffer.from(
            JSON.stringify({
              ...fixture.result,
              scope: input.scope,
              delegation_id: input.delegation_id,
              case_id: input.case_id,
              request_revision: input.request_revision,
              input_fingerprint: input.input_fingerprint,
              attempt_id: 'forged_attempt',
            }),
          );
        response.writeHead(status, {
          'content-type': 'application/json',
          'content-length': body.length,
          location: 'https://external.invalid',
          connection: 'close',
        });
        response.end(body);
      });
      await expect(client(endpoint).invoke(input)).rejects.toBeInstanceOf(SpecialistHttpError);
      expect(calls).toBe(1);
    },
  );
  it('aborts slow/truncated response streams under a total client deadline', async () => {
    const input = request();
    const endpoint = await fake((_request, response) => {
      response.writeHead(200, { 'content-type': 'application/json', 'content-length': 100 });
      response.write('{');
    });
    const caller = client(endpoint, TOKEN, 40);
    await expect(caller.invoke(input)).rejects.toMatchObject({ code: 'deadline_exceeded' });
    await caller.close();
    expect(caller.active).toBe(0);
  });
  it('bounds client admission, propagates close and rejects new use after close', async () => {
    const input = request();
    const held = barrier();
    const { server, endpoint } = await start(input, { hooks: { beforeEvaluate: held.hook } });
    const caller = client(endpoint, TOKEN, 1000, 1);
    const pending = caller.invoke(input).catch((error) => error);
    await held.entered;
    await expect(caller.invoke(request())).rejects.toMatchObject({ code: 'client_capacity' });
    await caller.close();
    await pending;
    expect(caller.active).toBe(0);
    await expect(caller.invoke(request())).rejects.toMatchObject({ code: 'client_closed' });
    held.release();
    await until(() => server.metrics().active === 0);
    await caller.close();
    await server.close();
    await server.close();
  });
  it('permits no arbitrary destination, malformed authorization or pre-aborted invocation', async () => {
    expect(
      () =>
        new SpecialistClient({ host: 'external.invalid', port: 80 } as unknown as Endpoint, HEADER),
    ).toThrow();
    const input = request();
    const { endpoint } = await start(input);
    expect(() => new SpecialistClient(endpoint, 'Bearer PRIVATE_HEADER_SENTINEL')).toThrow(
      SpecialistHttpError,
    );
    const controller = new AbortController();
    controller.abort();
    const caller = client(endpoint);
    await expect(caller.invoke(input, { signal: controller.signal })).rejects.toMatchObject({
      code: 'request_aborted',
    });
    expect(caller.active).toBe(0);
  });
});

describe('deadline and request ownership regressions', () => {
  it('rejects a fifth allowed raw header instead of truncating it', async () => {
    const input = request();
    const { server, endpoint } = await start(input, { limits: { headerFields: 4 } });
    const body = canonical(input);
    const rejected = await exchange(
      endpoint,
      Buffer.concat([
        Buffer.from(head(endpoint, body, 'Connection: close\r\n')),
        Buffer.from(body),
      ]),
    );
    expect(rejected).toContain('invalid_http');
    expect(server.metrics().invoked).toBe(0);
    const valid = await exchange(
      endpoint,
      Buffer.concat([Buffer.from(head(endpoint, body)), Buffer.from(body)]),
    );
    expect(valid).toMatch(/^HTTP\/1\.1 200 /);
  });
  it('bounds HTTP body readers independently from attempt capacity and recovers', async () => {
    const input = request();
    const { server, endpoint } = await start(input, { limits: { maxRequests: 1, bodyMs: 100 } });
    const socket = await open(endpoint);
    socket.resume();
    socket.write(head(endpoint, canonical(input)) + '{');
    await until(() => server.metrics().requests === 1);
    expect(server.metrics().active).toBe(0);
    await expect(client(endpoint).invoke(request())).rejects.toMatchObject({ code: 'capacity' });
    socket.destroy();
    await until(() => server.metrics().requests === 0);
    expect((await client(endpoint).invoke(request())).eligible).toBe(true);
  });
  it('close waits for actual incomplete-body request and socket cleanup', async () => {
    const input = request();
    const { server, endpoint } = await start(input);
    const socket = await open(endpoint);
    socket.resume();
    socket.write(head(endpoint, canonical(input)) + '{');
    await until(() => server.metrics().requests === 1);
    await server.close();
    expect(server.metrics().requests).toBe(0);
    expect(server.metrics().sockets).toBe(0);
    expect(server.metrics().active).toBe(0);
    await server.close();
  });
  it('rejects late evaluator success even when the timeout callback cannot run yet', async () => {
    const input = request();
    const { server, endpoint } = await start(input, {
      limits: { invokeMs: 20 },
      hooks: {
        beforeEvaluate() {
          const stop = performance.now() + 40;
          while (performance.now() < stop) {
            /* Controlled event-loop stall proves the post-await clock guard. */
          }
        },
      },
    });
    await expect(client(endpoint).invoke(input)).rejects.toMatchObject({
      code: 'deadline_exceeded',
    });
    await until(() => server.metrics().active === 0);
    expect(server.metrics().completed).toBe(0);
  });
  it('rejects a late real response when the client timer callback is deliberately delayed', async () => {
    const originalTimer = globalThis.setTimeout;
    const input = request();
    const endpoint = await fake((_request, response) => {
      originalTimer(() => {
        const body = Buffer.from(
          JSON.stringify({
            ...fixture.result,
            scope: input.scope,
            delegation_id: input.delegation_id,
            case_id: input.case_id,
            request_revision: input.request_revision,
            input_fingerprint: input.input_fingerprint,
            attempt_id: input.attempt.attempt_id,
            completed_at_ms: Date.now(),
          }),
        );
        response.writeHead(200, {
          'content-type': 'application/json',
          'content-length': body.length,
          connection: 'close',
        });
        response.end(body);
      }, 40);
    });
    const selected = client(endpoint, TOKEN, 20);
    const delayed = vi
      .spyOn(globalThis, 'setTimeout')
      .mockImplementation(((
        handler: (...args: unknown[]) => void,
        milliseconds?: number,
        ...args: unknown[]
      ) => originalTimer(handler, (milliseconds ?? 0) + 200, ...args)) as typeof setTimeout);
    try {
      await expect(selected.invoke(input)).rejects.toMatchObject({ code: 'deadline_exceeded' });
    } finally {
      delayed.mockRestore();
    }
  });
});

describe('startup and reentrant shutdown ownership', () => {
  it('owns a pending bind and rejects concurrent startup safely', async () => {
    const input = request();
    const service = new SpecialistServer({ ...configured(input), observer() {} });
    services.add(service);
    const starting = service.listen();
    await expect(service.listen()).rejects.toMatchObject({ code: 'closing' });
    const stopped = service.close();
    await expect(starting).rejects.toMatchObject({ code: 'closing' });
    await stopped;
    expect(service.metrics().sockets).toBe(0);
    expect(service.metrics().active).toBe(0);
    await expect(service.listen()).rejects.toMatchObject({ code: 'closing' });
  });
  it('publishes one successful close promise and emits one closed observation', async () => {
    const input = request();
    const { server } = await start(input);
    const first = server.close(),
      second = server.close();
    expect(second).toBe(first);
    await first;
    expect(server.close()).toBe(first);
    expect(events.filter((event) => event.event === 'closed')).toHaveLength(1);
  });
  it('does not execute a hook when the admission observer synchronously closes the server', async () => {
    const input = request();
    let hookCalls = 0;
    let stopped: Promise<void> | undefined;
    const service = new SpecialistServer({
      ...configured(input),
      observer(event) {
        if (event.event === 'attempt_started') stopped = service.close();
      },
      hooks: {
        beforeEvaluate() {
          hookCalls++;
        },
      },
    });
    services.add(service);
    const endpoint = await service.listen();
    const outcome = await client(endpoint)
      .invoke(input)
      .catch((error) => error);
    expect(outcome).toBeInstanceOf(SpecialistHttpError);
    expect(stopped).toBeDefined();
    await stopped;
    expect(hookCalls).toBe(0);
    expect(service.metrics().active).toBe(0);
    expect(service.metrics().requests).toBe(0);
  });
  it('shares close during a synchronous abort callback and retains an uncooperative permit', async () => {
    const input = request();
    const held = barrier();
    let nested: Promise<void> | undefined;
    const service = new SpecialistServer({
      ...configured(input),
      limits: { closeMs: 30 },
      observer() {},
      hooks: {
        async beforeEvaluate({ signal }) {
          signal.addEventListener('abort', () => {
            nested = service.close();
          });
          await held.hook();
        },
      },
    });
    services.add(service);
    const endpoint = await service.listen();
    const pending = client(endpoint)
      .invoke(input)
      .catch((error) => error);
    await held.entered;
    const first = service.close();
    expect(nested).toBe(first);
    await expect(first).rejects.toMatchObject({ code: 'cleanup_incomplete' });
    expect(service.metrics().active).toBe(1);
    held.release();
    await pending;
    await until(() => service.metrics().active === 0);
    await service.close();
  });
});

describe('response error containment', () => {
  it('contains an owned response write error over a real socket and preserves useful progress', async () => {
    const input = request();
    const { server, endpoint } = await start(input);
    const original = ServerResponse.prototype.end;
    let injected = false;
    const fault = vi.spyOn(ServerResponse.prototype, 'end').mockImplementation(function (
      this: ServerResponse,
      ...args: unknown[]
    ) {
      if (!injected && this.statusCode === 200) {
        injected = true;
        queueMicrotask(() => this.emit('error', new Error('PRIVATE_RESPONSE_SENTINEL')));
        return this;
      }
      return Reflect.apply(original, this, args);
    } as typeof original);
    try {
      await expect(client(endpoint).invoke(input)).rejects.toBeInstanceOf(SpecialistHttpError);
    } finally {
      fault.mockRestore();
    }
    expect(injected).toBe(true);
    await until(() => server.metrics().requests === 0 && server.metrics().active === 0);
    expect((await client(endpoint).invoke(request())).eligible).toBe(true);
    expect(JSON.stringify(events)).not.toContain('PRIVATE_RESPONSE_SENTINEL');
  });
});
