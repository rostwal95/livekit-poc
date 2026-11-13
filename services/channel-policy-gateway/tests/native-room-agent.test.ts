import { randomUUID } from 'node:crypto';
import { afterEach, describe, it, expect, vi } from 'vitest';
import { NativeAgentHttpClient } from '@livekit-ecosystem/channel-continuity/native';
import { NativeRoomManager } from '../src/native-room-manager.js';
import { NativeRoomAgent } from '../src/native-room-agent.js';
import {
  bridgeFixture,
  opening,
  command,
  attach,
  input,
  provider,
  deferred,
  until,
  route,
} from './native-bridge-fixtures.js';
import { post, fixture as defaultFixture } from './native-room-fixtures.js';
const fixtures: Awaited<ReturnType<typeof bridgeFixture>>[] = [];
const releases: (() => void)[] = [];
async function setup() {
  const f = await bridgeFixture();
  fixtures.push(f);
  return f;
}
afterEach(async () => {
  for (const release of releases.splice(0)) release();
  for (const f of fixtures.splice(0)) await f.close();
  vi.restoreAllMocks();
});
describe('current room genuine native prepare client', () => {
  it('copies a failed actual client close into a finite error and retries the same stopped owner', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch),
      original = NativeAgentHttpClient.prototype.close;
    let closes = 0;
    vi.spyOn(NativeAgentHttpClient.prototype, 'close').mockImplementation(async function (
      this: NativeAgentHttpClient,
    ) {
      if (++closes === 1) throw new Error('PRIVATE_CLIENT_CLOSE');
      await original.call(this);
    });
    const owner = new NativeRoomAgent(route, f.configuration, attach(a));
    try {
      await expect(owner.close()).rejects.toThrow('CleanupIncomplete');
      expect(owner.metrics()).toMatchObject({ closed: false, closing: true });
      await expect(
        owner.prepare(input(a.binding.bindingId), new AbortController().signal, () => {}),
      ).rejects.toThrow('DispatchUnavailable');
      await owner.close();
      expect(owner.metrics().closed).toBe(true);
      expect(closes).toBe(2);
      expect(f.w.state.requests).toHaveLength(0);
    } finally {
      await owner.close();
    }
  });

  it('keeps dormant preparation on the deterministic path before full application readiness without grant/client I/O', async () => {
    const f = await setup(),
      manager = new NativeRoomManager(
        route,
        {
          configuration: {
            schemaVersion: 1,
            port: f.configuration.rehydrationPort,
            recoverBindingId: null,
          },
          publisherToken: 'p'.repeat(43),
          forbiddenBearers: [],
        },
        {
          publish: async () => {
            throw new Error('UNEXPECTED_BIND');
          },
          revoke: async () => {
            throw new Error('UNEXPECTED_REVOKE');
          },
          native: async () => {
            throw new Error('UNEXPECTED_NATIVE');
          },
          ready: () => false,
        },
        { ...f.configuration, rehydrationPort: f.ready.endpoint.port },
      );
    try {
      expect(
        await manager.prepareNative(input(randomUUID()), new AbortController().signal, provider),
      ).toBeNull();
      expect(manager.metrics()).toMatchObject({
        nativeAgentOwners: 0,
        grantCalls: 0,
        httpSockets: 0,
      });
      expect(manager.ready()).toBeNull();
    } finally {
      await manager.close();
    }
  });

  it('copies a late current-owner callback failure and retains useful future progress', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch),
      owner = new NativeRoomAgent(route, f.configuration, attach(a));
    let checks = 0;
    try {
      await expect(
        owner.prepare(input(a.binding.bindingId), new AbortController().signal, () => {
          if (++checks === 2) throw new Error('PRIVATE_LATE_OWNER');
        }),
      ).rejects.toThrow('DispatchUnavailable');
      await until(() => owner.metrics().clientActive === 0);
      expect(
        await owner.prepare(input(a.binding.bindingId), new AbortController().signal, () => {}),
      ).toMatchObject({ caseRevision: '1' });
    } finally {
      await owner.close();
    }
  });

  it('attaches once through actual G HTTP, replays exact configuration and executes actual digest-bound public client', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch);
    await f.manager.open(a);
    const request = attach(a);
    const [first, second] = await Promise.all([
      post(f.ready.endpoint.port, 'attach-agent', request),
      post(f.ready.endpoint.port, 'attach-agent', request),
    ]);
    expect(first.status).toBe(200);
    expect(first.value).toEqual(second.value);
    expect(first.value).toEqual({
      ...command(a),
      bindingId: a.binding.bindingId,
      state: 'attached',
    });
    expect(first.raw.toString()).not.toContain(request.prepareBearer);
    expect(f.manager.metrics().nativeAgentOwners).toBe(1);
    expect(f.w.state.requests).toHaveLength(0);
    const value = input(a.binding.bindingId);
    expect(await f.manager.prepareNative(value, new AbortController().signal, provider)).toEqual({
      kind: 'investigation',
      source: 'scripted',
      caseRevision: '1',
    });
    const received = f.w.state.requests[0]!;
    expect(received.authorization).toBe('Bearer ' + request.prepareBearer);
    expect(received.value).toMatchObject({
      schemaVersion: 1,
      kind: 'agent.prepare',
      context: {
        scope: route.scope,
        caseId: route.caseId,
        operationKey: value.message.operationKey,
        message: { senderId: a.binding.bindingId, receiptId: value.message.receipt.receiptId },
      },
    });
  });
  it('preserves default G unknown-route behavior and requires bridge/current attachment before worker I/O', async () => {
    const normal = await defaultFixture();
    try {
      expect(
        (
          await post(
            normal.ready.endpoint.port,
            'attach-agent',
            attach(opening(normal.ready.nodeEpoch)),
          )
        ).status,
      ).toBe(400);
    } finally {
      await normal.cleanup();
    }
    const f = await setup();
    expect(
      await f.manager.prepareNative(input(randomUUID()), new AbortController().signal, provider),
    ).toBeNull();
    const a = opening(f.ready.nodeEpoch);
    await f.manager.open(a);
    await expect(
      f.manager.prepareNative(input(a.binding.bindingId), new AbortController().signal, provider),
    ).rejects.toMatchObject({ code: 'DispatchUnavailable' });
    expect(
      await f.manager.prepareNative(input(randomUUID()), new AbortController().signal, provider),
    ).toBeNull();
    expect(f.w.state.requests).toHaveLength(0);
  });
  it('rejects wrong epoch/generation/binding/role and changed attachment without client renewal', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch);
    await f.manager.open(a);
    const original = attach(a);
    for (const wrong of [
      { ...original, nodeEpoch: randomUUID() },
      { ...original, generation: '2' },
      { ...original, bindingId: randomUUID() },
      { ...original, prepareBearer: a.roomViewBearer },
      { ...original, prepareBearer: a.binding.nativeBearer },
      { ...original, prepareBearer: 'a'.repeat(43) },
    ])
      await expect(f.manager.attachAgent(wrong)).rejects.toThrow();
    await f.manager.attachAgent(original);
    await expect(
      f.manager.attachAgent({ ...original, prepareBearer: 't'.repeat(43) }),
    ).rejects.toMatchObject({ code: 'conflict' });
    expect(f.manager.metrics().nativeAgentOwners).toBe(1);
    expect(f.w.state.requests).toHaveLength(0);
  });
  it('copies original accepted input before await and rejects foreign source/case/getters with no worker effect', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch);
    await f.manager.open(a);
    await f.manager.attachAgent(attach(a));
    const held = deferred();
    releases.push(held.resolve);
    f.w.state.hold = held.promise;
    const value = input(a.binding.bindingId),
      pending = f.manager.prepareNative(value, new AbortController().signal, provider);
    await until(() => f.w.state.requests.length === 1);
    (value.message.event as { body: string }).body = 'changed after await';
    held.resolve();
    expect((await pending)?.caseRevision).toBe('1');
    expect(f.w.state.requests[0]!.value.context.message.body).toBe('investigate');
    const foreign = input(a.binding.bindingId);
    await expect(
      f.manager.prepareNative(foreign, new AbortController().signal, {
        ...provider,
        providerAccountId: 'foreign',
      }),
    ).rejects.toThrow();
    let reads = 0;
    await expect(
      f.manager.prepareNative(
        {
          get message() {
            reads++;
            return foreign.message;
          },
          currentCase: foreign.currentCase,
        },
        new AbortController().signal,
        provider,
      ),
    ).rejects.toThrow();
    expect(reads).toBe(0);
    expect(f.w.state.requests).toHaveLength(1);
  });
  it('rejects wrong worker digest/revision and allows fresh useful progress with no fallback', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch);
    await f.manager.open(a);
    await f.manager.attachAgent(attach(a));
    f.w.state.wrongDigest = true;
    await expect(
      f.manager.prepareNative(input(a.binding.bindingId), new AbortController().signal, provider),
    ).rejects.toMatchObject({ code: 'DispatchUnavailable' });
    f.w.state.wrongDigest = false;
    await until(() => f.manager.metrics().nativeAgentClientActive === 0);
    f.w.state.wrongRevision = true;
    await expect(
      f.manager.prepareNative(input(a.binding.bindingId), new AbortController().signal, provider),
    ).rejects.toMatchObject({ code: 'DispatchUnavailable' });
    f.w.state.wrongRevision = false;
    await until(() => f.manager.metrics().nativeAgentClientActive === 0);
    expect(
      (
        await f.manager.prepareNative(
          input(a.binding.bindingId),
          new AbortController().signal,
          provider,
        )
      )?.caseRevision,
    ).toBe('1');
    expect(f.w.state.requests).toHaveLength(3);
  });
  it('keeps one actual prepare slot and blocks B through timed-out retained client close; late A cannot succeed', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch);
    await f.manager.open(a);
    const work = deferred(),
      close = deferred();
    releases.push(work.resolve, close.resolve);
    f.w.state.hold = work.promise;
    const original = NativeAgentHttpClient.prototype.close;
    vi.spyOn(NativeAgentHttpClient.prototype, 'close').mockImplementation(async function (
      this: NativeAgentHttpClient,
    ) {
      await close.promise;
      await original.call(this);
    });
    await f.manager.attachAgent(attach(a));
    const first = f.manager
      .prepareNative(input(a.binding.bindingId), new AbortController().signal, provider)
      .catch((e) => e);
    await until(() => f.w.state.requests.length === 1);
    await expect(
      f.manager.prepareNative(input(a.binding.bindingId), new AbortController().signal, provider),
    ).rejects.toMatchObject({ code: 'Overloaded' });
    const closing = f.manager.closeRoom(command(a)).catch((e) => e);
    work.resolve();
    expect(await first).toMatchObject({ code: 'DispatchUnavailable' });
    expect(await closing).toMatchObject({ code: 'cleanup_incomplete' });
    expect(f.manager.metrics()).toMatchObject({ roomOwners: 1, nativeAgentOwners: 1 });
    const b = opening(f.ready.nodeEpoch, '1', 'b');
    await expect(f.manager.open(b)).rejects.toMatchObject({ code: 'conflict' });
    await expect(f.manager.attachAgent(attach(a))).rejects.toMatchObject({ code: 'closed' });
    close.resolve();
    await f.manager.closeRoom(command(a));
    expect(f.revoked).toEqual([a.binding.bindingId]);
    await f.manager.open(b);
    await f.manager.attachAgent({ ...attach(b, '2'), prepareBearer: 't'.repeat(43) });
    f.w.state.hold = undefined;
    expect(
      (
        await f.manager.prepareNative(
          input(b.binding.bindingId),
          new AbortController().signal,
          provider,
        )
      )?.caseRevision,
    ).toBe('1');
    expect(f.w.state.requests).toHaveLength(2);
  });
  it('expires a held current operation without letting its late reply become a prepared decision', async () => {
    const f = await setup(),
      base = opening(f.ready.nodeEpoch),
      a = {
        ...base,
        binding: { ...base.binding, expiresAt: new Date(Date.now() + 80).toISOString() },
      };
    await f.manager.open(a);
    await f.manager.attachAgent(attach(a));
    const held = deferred();
    releases.push(held.resolve);
    f.w.state.hold = held.promise;
    const pending = f.manager
      .prepareNative(input(a.binding.bindingId), new AbortController().signal, provider)
      .catch((e) => e);
    await until(() => f.w.state.requests.length === 1);
    await new Promise((r) => setTimeout(r, 100));
    held.resolve();
    expect(await pending).toMatchObject({ code: 'DispatchUnavailable' });
    await f.manager.closeRoom(command(a));
    expect(f.manager.metrics().nativeAgentOwners).toBe(0);
  });
  it('the direct public client owner preserves pre-I/O denial and a closed owner cannot create a fresh call', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch),
      owner = new NativeRoomAgent(route, f.configuration, attach(a));
    try {
      const foreign = input(randomUUID());
      await expect(
        owner.prepare(foreign, new AbortController().signal, () => {}),
      ).rejects.toMatchObject({ code: 'AccessDenied' });
      expect(f.w.state.requests).toHaveLength(0);
      await owner.close();
      await expect(
        owner.prepare(input(a.binding.bindingId), new AbortController().signal, () => {}),
      ).rejects.toMatchObject({ code: 'DispatchUnavailable' });
    } finally {
      await owner.close();
    }
  });
});
