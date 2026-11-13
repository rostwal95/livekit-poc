/** Genuine public facade/server/inbox constructors and real sockets; public native storage read is explicitly mocked, no PG. */
import { randomUUID } from 'node:crypto';
import { request } from 'node:http';
import { afterEach, describe, it, expect, vi } from 'vitest';
import {
  NativeChannelInbox,
  createNativeIntegration,
} from '@livekit-ecosystem/channel-continuity/native';
import { SeededAccounts } from '@livekit-ecosystem/channel-continuity/postgres';
import { createFakeSmsIntegration } from '@livekit-ecosystem/channel-continuity/security';
import {
  ChannelRehydrator,
  RehydrationHttpServer,
  DEFAULT_REHYDRATION_QUERY,
  type RehydrationContext,
} from '@livekit-ecosystem/channel-continuity/rehydration';
import { CurrentRoomRehydrator } from '../src/native-room-agent.js';
import {
  bridgeFixture,
  opening,
  command,
  provider,
  route,
  publisher,
  deferred,
  until,
} from './native-bridge-fixtures.js';
import { view } from './native-room-fixtures.js';
const fixtures: { cleanup: () => Promise<void> }[] = [];
const releases: (() => void)[] = [];
function context(a: ReturnType<typeof opening>): RehydrationContext {
  const now = new Date().toISOString();
  return {
    schemaVersion: 1,
    contextId: randomUUID(),
    access: {
      kind: 'native',
      bindingId: a.binding.bindingId,
      roomId: a.binding.roomId,
      participantId: a.binding.participantId,
    },
    case: view(randomUUID()).case,
    history: { messages: [], nextCursor: null, hasMore: false },
    work: { items: [], nextCursor: null, hasMore: false },
    responses: { items: [], nextCursor: null, hasMore: false },
    replies: { items: [], nextCursor: null, hasMore: false },
    observed: { p2ObservedAt: now, caseObservedAt: now, disclosureAdmittedAt: now, atomic: false },
  };
}
function read(
  port: number,
  bearer: string,
  body: unknown = { schemaVersion: 1, query: DEFAULT_REHYDRATION_QUERY },
) {
  const raw = Buffer.from(JSON.stringify(body));
  return new Promise<{ status: number; value: any; raw: string }>((r, j) => {
    const req = request(
      {
        host: '127.0.0.1',
        port,
        path: '/v1/rehydration/native',
        method: 'POST',
        agent: false,
        headers: {
          authorization: 'Bearer ' + bearer,
          'content-type': 'application/json',
          'content-length': raw.length,
          connection: 'close',
        },
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on('data', (b) => chunks.push(Buffer.from(b)));
        res.on('end', () => {
          const text = Buffer.concat(chunks).toString();
          r({ status: res.statusCode!, value: JSON.parse(text), raw: text });
        });
      },
    );
    req.once('error', j);
    req.end(raw);
  });
}
async function setup() {
  const f = await bridgeFixture(),
    a = opening(f.ready.nodeEpoch);
  await f.manager.open(a);
  const inbox = new NativeChannelInbox(
    {
      host: '127.0.0.1',
      port: 1,
      database: 'livekit_lab',
      user: 'livekit_lab',
      password: 'z'.repeat(43),
      schema: 'p2_bridge_context_unit',
    },
    createNativeIntegration(provider, [
      {
        token: publisher,
        scope: route.scope,
        caseId: route.caseId,
        conversationId: route.conversationId,
      },
    ]),
    new SeededAccounts([
      {
        token: 'a'.repeat(43),
        ...route.scope,
        caseId: route.caseId,
        conversationId: route.conversationId,
      },
    ]),
  );
  const cases = {
    inspect: vi.fn(async () => {
      throw new Error('UNEXPECTED_CASE_IO');
    }),
  };
  const facade = new CurrentRoomRehydrator(
    inbox,
    cases,
    createFakeSmsIntegration({ ...provider, provider: 'fake_sms' }, Buffer.alloc(32, 7)),
    { maxActive: 2, timeoutMs: 3000, cleanupMs: 1000 },
    f.manager.nativeContext.bind(f.manager),
  );
  const state = { value: context(a), hold: undefined as Promise<void> | undefined, calls: 0 };
  const spy = vi.spyOn(ChannelRehydrator.prototype, 'native').mockImplementation(async () => {
    state.calls++;
    await state.hold;
    return state.value;
  });
  const http = new RehydrationHttpServer(facade);
  await http.start(f.configuration.rehydrationPort);
  const result = {
    ...f,
    a,
    inbox,
    facade,
    http,
    state,
    spy,
    cases,
    async cleanup() {
      try {
        for (let i = 0; ; i++) {
          try {
            await http.close();
            break;
          } catch (error) {
            if (i >= 20) throw error;
            await new Promise((r) => setTimeout(r, 2));
          }
        }
      } finally {
        await f.manager.close();
        await facade.close();
        await inbox.close();
        await f.w.close();
      }
    },
  };
  fixtures.push(result);
  return result;
}
afterEach(async () => {
  for (const r of releases.splice(0)) r();
  for (const f of fixtures.splice(0)) await f.cleanup();
  vi.restoreAllMocks();
});
describe('borrowed public current-room rehydration composition', () => {
  it('serves the existing public context wire using genuine public owners without another pool', async () => {
    const f = await setup();
    expect(f.facade).toBeInstanceOf(ChannelRehydrator);
    const result = await read(f.configuration.rehydrationPort, f.a.binding.nativeBearer);
    expect(result.value).toEqual({ schemaVersion: 1, status: 'known', context: f.state.value });
    expect(f.state.calls).toBe(1);
    expect(f.cases.inspect).not.toHaveBeenCalled();
    expect(f.manager.metrics().contextCalls).toBe(0);
  });
  it('rejects old/wrong native role and body selectors before a public storage read, then progresses', async () => {
    const f = await setup();
    expect((await read(f.configuration.rehydrationPort, 'x'.repeat(43))).value).toMatchObject({
      status: 'unavailable',
      code: 'access_denied',
    });
    expect(
      (
        await read(f.configuration.rehydrationPort, f.a.binding.nativeBearer, {
          schemaVersion: 1,
          query: { ...DEFAULT_REHYDRATION_QUERY, scope: { tenantId: 'foreign' } },
        })
      ).value.status,
    ).toBe('unavailable');
    expect(f.state.calls).toBe(0);
    expect(
      (await read(f.configuration.rehydrationPort, f.a.binding.nativeBearer)).value.status,
    ).toBe('known');
  });
  it('retains two held public context calls and blocks B until late A responses are withheld', async () => {
    const f = await setup(),
      held = deferred();
    releases.push(held.resolve);
    f.state.hold = held.promise;
    const first = read(f.configuration.rehydrationPort, f.a.binding.nativeBearer),
      second = read(f.configuration.rehydrationPort, f.a.binding.nativeBearer);
    await until(() => f.state.calls === 2);
    expect(f.manager.metrics().contextCalls).toBe(2);
    await expect(read(f.configuration.rehydrationPort, f.a.binding.nativeBearer)).rejects.toThrow();
    const closing = f.manager.closeRoom(command(f.a)).catch((e) => e);
    expect(await closing).toMatchObject({ code: 'cleanup_incomplete' });
    const b = opening(f.ready.nodeEpoch, '1', 'b');
    await expect(f.manager.open(b)).rejects.toMatchObject({ code: 'conflict' });
    held.resolve();
    for (const response of await Promise.all([first, second])) {
      expect(response.value).toMatchObject({ status: 'unavailable', code: 'access_denied' });
      expect(response.raw).not.toContain(f.state.value.contextId);
    }
    await f.manager.closeRoom(command(f.a));
    expect(f.manager.metrics().contextCalls).toBe(0);
    await f.manager.open(b);
    f.state.hold = undefined;
    f.state.value = context(b);
    expect(
      (await read(f.configuration.rehydrationPort, f.a.binding.nativeBearer)).value.status,
    ).toBe('unavailable');
    expect(
      (await read(f.configuration.rehydrationPort, b.binding.nativeBearer)).value.context.access
        .bindingId,
    ).toBe(b.binding.bindingId);
  });
  it('withholds a context whose actual public read finishes after room expiry', async () => {
    const f = await setup();
    await f.manager.closeRoom(command(f.a));
    const a = opening(f.ready.nodeEpoch, '1', 'b');
    const expiring = {
      ...a,
      binding: { ...a.binding, expiresAt: new Date(Date.now() + 80).toISOString() },
    };
    await f.manager.open(expiring);
    f.state.value = context(expiring);
    const held = deferred();
    releases.push(held.resolve);
    f.state.hold = held.promise;
    const pending = read(f.configuration.rehydrationPort, expiring.binding.nativeBearer);
    await until(() => f.state.calls === 1);
    await new Promise((r) => setTimeout(r, 100));
    held.resolve();
    const response = await pending;
    expect(response.value).toMatchObject({ status: 'unavailable', code: 'access_denied' });
    expect(response.raw).not.toContain(f.state.value.contextId);
    await f.manager.closeRoom(command(expiring, '2'));
    expect(f.manager.metrics().contextCalls).toBe(0);
  });
});
