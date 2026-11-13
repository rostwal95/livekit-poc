import { afterEach, describe, expect, it, vi } from 'vitest';
import { JoinedClient } from './channel-policy-client';
import { parseCase } from './channel-policy-wire';
const KEY = 'A'.repeat(43),
  TIME = '2026-11-13T12:00:00.000Z',
  value = { schemaVersion: 1, case: { revision: '1', observedAt: TIME } },
  BODY = { schemaVersion: 1 };
const response = (v: unknown = value) =>
  new Response(JSON.stringify(v), {
    status: 200,
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-store',
    },
  });
function held<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}
const tick = async () => {
  for (let i = 0; i < 8; i++) await Promise.resolve();
};
afterEach(() => vi.useRealTimers());
describe('joined browser HTTP ownership', () => {
  it('is inert and uses only fixed POST/auth/no-cookie/no-store transport', async () => {
    const fetcher = vi.fn<typeof fetch>(async () => response()),
      client = new JoinedClient(fetcher);
    expect(fetcher).not.toHaveBeenCalled();
    const got = await client.request('case', BODY, KEY, parseCase);
    expect(got.case.revision).toBe('1');
    const [path, options] = fetcher.mock.calls[0]!;
    expect(path).toBe('/v1/channel-policy-demo/case');
    expect(options).toMatchObject({
      method: 'POST',
      credentials: 'omit',
      cache: 'no-store',
      redirect: 'error',
      body: '{"schemaVersion":1}',
    });
    expect((options!.headers as Record<string, string>).Authorization).toBe('Bearer ' + KEY);
    expect(client.pendingCount).toBe(0);
    await client.close();
  });
  it('rejects invalid requests before fetch without evaluating getters', () => {
    const fetcher = vi.fn<typeof fetch>(),
      client = new JoinedClient(fetcher);
    let read = 0;
    expect(() =>
      client.begin(
        'case',
        {
          schemaVersion: 1,
          get secret() {
            read++;
            return KEY;
          },
        },
        KEY,
        parseCase,
      ),
    ).toThrow();
    expect(read).toBe(0);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('retains two actual ignored-abort fetches past15s and denies a third before I/O', async () => {
    vi.useFakeTimers();
    const one = held<Response>(),
      two = held<Response>();
    const fetcher = vi
        .fn<typeof fetch>()
        .mockReturnValueOnce(one.promise)
        .mockReturnValueOnce(two.promise),
      client = new JoinedClient(fetcher);
    const a = client.begin('case', BODY, KEY, parseCase),
      b = client.begin('case', BODY, KEY, parseCase);
    const outcomes = Promise.allSettled([a.result, b.result]);
    await vi.advanceTimersByTimeAsync(15001);
    expect((await outcomes).every((x) => x.status === 'rejected')).toBe(true);
    expect(client.pendingCount).toBe(2);
    expect(() => client.begin('case', BODY, KEY, parseCase)).toThrow();
    expect(fetcher).toHaveBeenCalledTimes(2);
    one.resolve(response());
    two.resolve(response());
    await Promise.all([a.settled, b.settled]);
    expect(client.pendingCount).toBe(0);
    await client.close();
  });
  it('retains an actual slow response body after observer abort until it really completes', async () => {
    vi.useFakeTimers();
    let control!: ReadableStreamDefaultController<Uint8Array>;
    const stream = new ReadableStream<Uint8Array>({
      start(c) {
        control = c;
      },
    });
    const fetcher = vi.fn<typeof fetch>(
        async () =>
          new Response(stream, {
            headers: {
              'Content-Type': 'application/json',
              'Cache-Control': 'no-store',
            },
          }),
      ),
      client = new JoinedClient(fetcher);
    const request = client.begin('case', BODY, KEY, parseCase);
    const outcome = Promise.allSettled([request.result]);
    await vi.advanceTimersByTimeAsync(15001);
    expect((await outcome)[0]?.status).toBe('rejected');
    expect(client.pendingCount).toBe(1);
    control.enqueue(new TextEncoder().encode(JSON.stringify(value)));
    control.close();
    expect((await request.actualResult).case.revision).toBe('1');
    await request.settled;
    expect(client.pendingCount).toBe(0);
    await client.close();
  });
  it('bounds close observation without releasing a still-owned fetch and allows useful settlement', async () => {
    vi.useFakeTimers();
    const gate = held<Response>(),
      client = new JoinedClient(vi.fn<typeof fetch>(() => gate.promise));
    const r = client.begin('case', BODY, KEY, parseCase);
    void r.result.catch(() => undefined);
    const close = client.close();
    const outcome = Promise.allSettled([close]);
    await vi.advanceTimersByTimeAsync(5001);
    expect((await outcome)[0]?.status).toBe('rejected');
    expect(client.pendingCount).toBe(1);
    expect(() => client.begin('case', BODY, KEY, parseCase)).toThrow();
    gate.resolve(response());
    await r.settled;
    await client.close();
    expect(client.pendingCount).toBe(0);
  });
  it('preserves a validated value despite reader cleanup failure and retains its slot for retry', async () => {
    const bytes = new TextEncoder().encode(JSON.stringify(value));
    let reads = 0,
      closes = 0;
    const reader = {
      read: async () =>
        ++reads === 1 ? { done: false, value: bytes } : { done: true, value: undefined },
      cancel: async () => undefined,
      releaseLock: () => {
        if (++closes === 1) throw new Error('PRIVATE');
      },
    };
    const fake = {
      status: 200,
      redirected: false,
      headers: new Headers({
        'Content-Type': 'application/json',
        'Cache-Control': 'no-store',
      }),
      body: { getReader: () => reader },
    } as unknown as Response;
    const fetcher = vi.fn<typeof fetch>(async () => fake),
      client = new JoinedClient(fetcher);
    const r = client.begin('case', BODY, KEY, parseCase);
    expect((await r.result).case.revision).toBe('1');
    await tick();
    expect(client.pendingCount).toBe(1);
    await client.close();
    await r.settled;
    expect(client.pendingCount).toBe(0);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it.each(['header', 'oversize', 'utf8', 'duplicate'])(
    'rejects unsafe %s responses with finite fresh errors',
    async (kind) => {
      let reply: Response;
      if (kind === 'header')
        reply = new Response('{}', {
          headers: { 'Content-Type': 'text/plain' },
        });
      else if (kind === 'oversize') reply = response('x'.repeat(16385));
      else if (kind === 'utf8')
        reply = new Response(new Uint8Array([255]), {
          headers: {
            'Content-Type': 'application/json',
            'Cache-Control': 'no-store',
          },
        });
      else
        reply = new Response('{"schemaVersion":1,"schemaVersion":1}', {
          headers: {
            'Content-Type': 'application/json',
            'Cache-Control': 'no-store',
          },
        });
      const client = new JoinedClient(vi.fn<typeof fetch>(async () => reply));
      await expect(client.request('case', BODY, KEY, parseCase)).rejects.toMatchObject({
        code: 'invalid',
      });
      await client.close();
    },
  );
});

describe('reserved original End HTTP capacity', () => {
  const owner = '11111111-1111-4111-8111-111111111111';
  const command = '22222222-2222-4222-8222-222222222222';
  const start = {
    schemaVersion: 1,
    ownerEpoch: owner,
    expectedGeneration: '0',
    commandId: command,
  };
  const end = {
    schemaVersion: 1,
    ownerEpoch: owner,
    generation: '1',
    originalStartCommandId: command,
  };
  it('reserves a third retained slot only for End while both ordinary observers expire', async () => {
    vi.useFakeTimers();
    const gates = [held<Response>(), held<Response>(), held<Response>()];
    const fetcher = vi
      .fn<typeof fetch>()
      .mockReturnValueOnce(gates[0]!.promise)
      .mockReturnValueOnce(gates[1]!.promise)
      .mockReturnValueOnce(gates[2]!.promise);
    const client = new JoinedClient(fetcher);
    const a = client.begin('start', start, KEY, () => true),
      b = client.begin('status', BODY, KEY, () => true);
    expect(() => client.begin('case', BODY, KEY, parseCase)).toThrow();
    const e = client.begin('end', end, KEY, () => true);
    const outcomes = Promise.allSettled([a.result, b.result, e.result]);
    expect(client.pendingCount).toBe(3);
    expect(() => client.begin('end', end, KEY, () => true)).toThrow();
    await vi.advanceTimersByTimeAsync(15001);
    expect((await outcomes).every((x) => x.status === 'rejected')).toBe(true);
    expect(client.pendingCount).toBe(3);
    expect(fetcher).toHaveBeenCalledTimes(3);
    for (const gate of gates) gate.resolve(response({}));
    await Promise.all([a.settled, b.settled, e.settled]);
    expect(client.pendingCount).toBe(0);
    await client.close();
  });
  it('keeps a validated End reader reserved through held cleanup and coalesces cleanup retry', async () => {
    const bytes = new TextEncoder().encode('{}'),
      cancel = held<void>();
    let reads = 0,
      releases = 0;
    const reader = {
      read: async () =>
        ++reads === 1 ? { done: false, value: bytes } : { done: true, value: undefined },
      cancel: vi.fn(() => cancel.promise),
      releaseLock: () => {
        if (++releases === 1) throw new Error('PRIVATE');
      },
    };
    const reply = {
      status: 200,
      redirected: false,
      headers: new Headers({ 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }),
      body: { getReader: () => reader },
    } as unknown as Response;
    const fetcher = vi.fn<typeof fetch>(async () => reply),
      client = new JoinedClient(fetcher);
    const request = client.begin('end', end, KEY, () => 'known');
    expect(await request.result).toBe('known');
    await tick();
    expect(client.pendingCount).toBe(1);
    expect(() => client.begin('end', end, KEY, () => true)).toThrow();
    const one = request.retryCleanup(),
      two = request.retryCleanup();
    await tick();
    expect(reader.cancel).toHaveBeenCalledTimes(1);
    expect(client.pendingCount).toBe(1);
    cancel.resolve();
    await Promise.all([one, two, request.settled]);
    expect(client.pendingCount).toBe(0);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await client.close();
  });
});
