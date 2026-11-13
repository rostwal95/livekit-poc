import { randomUUID } from 'node:crypto';
import { createServer, Server } from 'node:http';
import { NativeRoomManager } from '../src/native-room-manager.js';
import { route } from './native-room-fixtures.js';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ChannelError } from '@livekit-ecosystem/channel-continuity/postgres';
import { ResultReceiverError } from '@livekit-ecosystem/channel-continuity/result-receiver';
import {
  fixture,
  opening,
  command,
  reading,
  deferred,
  view,
  publisher,
} from './native-room-fixtures.js';
const fixtures: Awaited<ReturnType<typeof fixture>>[] = [];
const release: (() => void)[] = [];
async function setup(id: string | null = null) {
  const f = await fixture(id);
  fixtures.push(f);
  return f;
}
afterEach(async () => {
  for (const r of release.splice(0)) r();
  vi.useRealTimers();
  for (const f of fixtures.splice(0)) await f.cleanup();
});
describe('one retained G room owner', () => {
  it('reserves one generation before concurrent opens and replays original publication without new grant calls', async () => {
    const f = await setup(),
      hold = deferred();
    release.push(hold.resolve);
    f.state.publishHold = hold.promise;
    const a = opening(f.ready.nodeEpoch),
      first = f.manager.open(a);
    await expect(f.manager.open(opening(f.ready.nodeEpoch))).rejects.toMatchObject({
      code: 'conflict',
    });
    hold.resolve();
    const accepted = await first;
    expect(accepted).toMatchObject({ generation: '1', state: 'ready' });
    expect(await f.manager.open(a)).toEqual(accepted);
    expect(f.state.published).toHaveLength(1);
    await expect(
      f.manager.open({
        ...a,
        binding: {
          ...a.binding,
          expiresAt: new Date(Date.parse(a.binding.expiresAt) + 1000).toISOString(),
        },
      }),
    ).rejects.toMatchObject({ code: 'conflict' });
  });
  it('contains ambiguous publication and explicitly replays only original bytes/expiry after settlement', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch);
    f.state.publishError = new ChannelError('AcknowledgementUnknown');
    await expect(f.manager.open(a)).rejects.toMatchObject({ code: 'outcome_unknown' });
    expect(f.manager.observe(command(a))).toMatchObject({ state: 'publication_unknown' });
    expect(f.manager.metrics().roomOwners).toBe(1);
    f.state.publishError = undefined;
    const accepted = await f.manager.open(a);
    expect(accepted.state).toBe('ready');
    expect(f.state.published).toHaveLength(2);
    expect(f.state.published[1]).toEqual(f.state.published[0]);
    expect(accepted.publication).toEqual(f.state.rows.get(a.binding.bindingId));
  });
  it('coalesces concurrent exact reconciliation after an ambiguous publication into one new owned call', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch);
    f.state.publishError = new ChannelError('AcknowledgementUnknown');
    await expect(f.manager.open(a)).rejects.toMatchObject({ code: 'outcome_unknown' });
    f.state.publishError = undefined;
    const held = deferred();
    release.push(held.resolve);
    f.state.publishHold = held.promise;
    const first = f.manager.open(a),
      second = f.manager.open(a);
    held.resolve();
    expect(await first).toEqual(await second);
    expect(f.state.published).toHaveLength(2);
  });
  it('never republishes an old binding ID or swaps old native/view capabilities into B', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch);
    await f.manager.open(a);
    await f.manager.closeRoom(command(a));
    const b = opening(f.ready.nodeEpoch, '1', 'b');
    for (const bad of [
      { ...b, binding: { ...b.binding, bindingId: a.binding.bindingId } },
      { ...b, roomViewBearer: a.binding.nativeBearer },
      { ...b, binding: { ...b.binding, nativeBearer: a.roomViewBearer } },
    ])
      await expect(f.manager.open(bad)).rejects.toMatchObject({ code: 'invalid_input' });
    expect(f.state.published).toHaveLength(1);
    await f.manager.open(b);
    expect(f.state.published).toHaveLength(2);
  });
  it('retains held publication through waiter timeout and close, then revokes the late known grant', async () => {
    const f = await setup();
    vi.useFakeTimers();
    const hold = deferred();
    release.push(hold.resolve);
    f.state.publishHold = hold.promise;
    const a = opening(f.ready.nodeEpoch),
      pending = f.manager.open(a).catch((e) => e);
    await vi.advanceTimersByTimeAsync(1001);
    expect(await pending).toMatchObject({ code: 'outcome_unknown' });
    expect(f.manager.metrics()).toMatchObject({ grantCalls: 1, roomOwners: 1 });
    const closing = f.manager.closeRoom(command(a)).catch((e) => e);
    await vi.advanceTimersByTimeAsync(1001);
    expect(await closing).toMatchObject({ code: 'cleanup_incomplete' });
    await expect(f.manager.open(opening(f.ready.nodeEpoch, '1', 'b'))).rejects.toMatchObject({
      code: 'conflict',
    });
    hold.resolve();
    await vi.advanceTimersByTimeAsync(1);
    expect(f.manager.observe(command(a))).toMatchObject({
      state: 'closed',
      globalReaderDrained: false,
    });
    expect(f.state.revoked).toEqual([a.binding.bindingId]);
    expect(f.manager.metrics()).toMatchObject({ roomOwners: 0, grantCalls: 0 });
  });
  it('retains revoke uncertainty, makes exact cleanup progress and prevents reopening a closed command', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch);
    await f.manager.open(a);
    f.state.revokeError = new ChannelError('AcknowledgementUnknown');
    await expect(f.manager.closeRoom(command(a))).rejects.toMatchObject({
      code: 'cleanup_incomplete',
    });
    expect(f.manager.observe(command(a)).state).toBe('closing');
    await expect(f.manager.open(a)).rejects.toMatchObject({ code: 'closed' });
    f.state.revokeError = undefined;
    const closed = await f.manager.closeRoom(command(a));
    expect(closed).toMatchObject({
      state: 'closed',
      revocation: { state: 'revoked' },
      globalReaderDrained: false,
    });
    expect(await f.manager.open(a)).toEqual(closed);
    expect(f.state.published).toHaveLength(1);
    expect(f.state.revoked).toEqual([a.binding.bindingId, a.binding.bindingId]);
  });
  it('rejects wrong epochs/generation/role collisions before publication and read effects', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch);
    for (const bad of [
      { ...a, nodeEpoch: randomUUID() },
      { ...a, expectedGeneration: '1' },
      { ...a, roomViewBearer: publisher },
      { ...a, binding: { ...a.binding, nativeBearer: 'a'.repeat(43) } },
    ])
      await expect(f.manager.open(bad)).rejects.toBeInstanceOf(Error);
    expect(f.state.published).toHaveLength(0);
    await f.manager.open(a);
    await expect(f.manager.nativeResult(reading(a, '2'), a.roomViewBearer)).rejects.toMatchObject({
      code: 'unauthorized',
    });
    await expect(f.manager.nativeResult(reading(a), publisher)).rejects.toMatchObject({
      code: 'unauthorized',
    });
    expect(f.state.native).toHaveLength(0);
  });
  it('returns original opaque view and maps actual absence separately from operational failures', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch);
    await f.manager.open(a);
    const r = reading(a);
    expect(await f.manager.nativeResult(r, a.roomViewBearer)).toBeNull();
    f.state.view = view(r.deliveryId);
    expect((await f.manager.nativeResult(r, a.roomViewBearer))!.intent.body).toBe(
      f.state.view.intent.body,
    );
    f.state.nativeError = new ResultReceiverError('Overloaded');
    await expect(f.manager.nativeResult(r, a.roomViewBearer)).rejects.toMatchObject({
      code: 'capacity',
    });
    f.state.nativeError = new ResultReceiverError('AccessDenied');
    await expect(f.manager.nativeResult(r, a.roomViewBearer)).rejects.toMatchObject({
      code: 'unauthorized',
    });
    f.state.nativeError = new Error('PRIVATE');
    await expect(f.manager.nativeResult(r, a.roomViewBearer)).rejects.toMatchObject({
      code: 'unavailable',
      message: 'unavailable',
    });
  });
  it('keeps public reads after waiter timeout and discards late A instead of releasing its protocol owner', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch);
    await f.manager.open(a);
    vi.useFakeTimers();
    const hold = deferred();
    release.push(hold.resolve);
    f.state.nativeHold = hold.promise;
    const r = reading(a);
    f.state.view = view(r.deliveryId);
    const readingA = f.manager.nativeResult(r, a.roomViewBearer).catch((e) => e);
    await vi.advanceTimersByTimeAsync(1001);
    expect(await readingA).toMatchObject({ code: 'unavailable' });
    expect(f.manager.metrics().publicReadCalls).toBe(1);
    await expect(f.manager.nativeResult(r, a.roomViewBearer)).rejects.toMatchObject({
      code: 'capacity',
    });
    const closing = f.manager.closeRoom(command(a)).catch((e) => e);
    await vi.advanceTimersByTimeAsync(1001);
    expect(await closing).toMatchObject({ code: 'cleanup_incomplete' });
    hold.resolve();
    await vi.advanceTimersByTimeAsync(1);
    expect(f.manager.observe(command(a)).state).toBe('closed');
    expect(f.state.revoked).toHaveLength(1);
  });
  it('honestly permits B after global borrowed I/O outlives the settled A waiter, with bounded capacity', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch);
    await f.manager.open(a);
    f.state.nativeError = new ResultReceiverError('Unavailable');
    await expect(f.manager.nativeResult(reading(a), a.roomViewBearer)).rejects.toMatchObject({
      code: 'unavailable',
    });
    const closed = await f.manager.closeRoom(command(a));
    expect(closed.globalReaderDrained).toBe(false);
    const b = opening(f.ready.nodeEpoch, '1', 'b');
    await f.manager.open(b);
    f.state.nativeError = new ResultReceiverError('Overloaded');
    await expect(f.manager.nativeResult(reading(b, '2'), b.roomViewBearer)).rejects.toMatchObject({
      code: 'capacity',
    });
    await expect(f.manager.nativeResult(reading(a), a.roomViewBearer)).rejects.toMatchObject({
      code: 'unauthorized',
    });
    f.state.nativeError = undefined;
    expect(await f.manager.nativeResult(reading(b, '2'), b.roomViewBearer)).toBeNull();
    expect(f.manager.metrics().globalReaderDrainGuaranteed).toBe(false);
  });
  it('requires configured orphan recovery and makes NotFound absence safe only through the genuine public code', async () => {
    const id = randomUUID(),
      f = await setup(id),
      a = opening(f.ready.nodeEpoch);
    await expect(f.manager.open(a)).rejects.toMatchObject({ code: 'recovery_required' });
    const request = {
      schemaVersion: 1 as const,
      nodeEpoch: f.ready.nodeEpoch,
      expectedGeneration: '0',
      bindingId: id,
    };
    f.state.revokeError = { code: 'NotFound' };
    await expect(f.manager.recover(request)).rejects.toMatchObject({ code: 'cleanup_incomplete' });
    expect(f.manager.metrics().recoveryOwners).toBe(1);
    f.state.revokeError = undefined;
    const recovered = await f.manager.recover(request);
    expect(recovered).toMatchObject({ generation: '1', revocation: { state: 'absent' } });
    expect(await f.manager.recover(request)).toEqual(recovered);
    const b = opening(f.ready.nodeEpoch, '1', 'b');
    await f.manager.open(b);
    expect(f.state.revoked).toEqual([id, id]);
    await expect(
      f.manager.recover({ ...request, bindingId: randomUUID(), expectedGeneration: '2' }),
    ).rejects.toMatchObject({ code: 'conflict' });
  });
  it('expires the original room without renewing a publication or retaining an eligible old read', async () => {
    const f = await setup();
    vi.useFakeTimers();
    const a = opening(f.ready.nodeEpoch);
    await f.manager.open(a);
    await vi.advanceTimersByTimeAsync(30001);
    expect(f.manager.observe(command(a))).toMatchObject({ state: 'closed' });
    await expect(f.manager.nativeResult(reading(a), a.roomViewBearer)).rejects.toMatchObject({
      code: 'unauthorized',
    });
    expect(f.state.revoked).toEqual([a.binding.bindingId]);
    expect(f.state.published).toHaveLength(1);
  });
  it('fails a busy control port with no public grant call or fallback and drains its returned host', async () => {
    const peer = createServer();
    await new Promise<void>((r, j) => {
      peer.once('error', j);
      peer.listen(0, '127.0.0.1', r);
    });
    const address = peer.address();
    if (!address || typeof address === 'string') throw new Error('fixture');
    let calls = 0;
    const manager = new NativeRoomManager(
      route,
      {
        configuration: { schemaVersion: 1, port: address.port, recoverBindingId: null },
        publisherToken: publisher,
        forbiddenBearers: [],
      },
      {
        publish: async () => {
          calls++;
          throw new Error('unexpected');
        },
        revoke: async () => {
          calls++;
          throw new Error('unexpected');
        },
        native: async () => {
          calls++;
          return null;
        },
        ready: () => true,
      },
    );
    try {
      await expect(manager.start()).rejects.toMatchObject({ code: 'unavailable' });
      await manager.close();
      expect(peer.listening).toBe(true);
      expect(calls).toBe(0);
      expect(manager.metrics()).toMatchObject({ closed: true, httpSockets: 0, httpHandlers: 0 });
    } finally {
      await manager.close();
      await new Promise<void>((r) => peer.close(() => r()));
    }
  });
  it('rejects borrowed port accessors before listener creation', () => {
    const getter = vi.fn(() => {
        throw new Error('PRIVATE_GETTER');
      }),
      listen = vi.spyOn(Server.prototype, 'listen');
    const ports = {
      publish: async () => {
        throw new Error('unexpected');
      },
      revoke: async () => {
        throw new Error('unexpected');
      },
      native: async () => null,
      ready: () => true,
    };
    Object.defineProperty(ports, 'publish', { get: getter, enumerable: true });
    expect(
      () =>
        new NativeRoomManager(
          route,
          {
            configuration: { schemaVersion: 1, port: 11029, recoverBindingId: null },
            publisherToken: publisher,
            forbiddenBearers: [],
          },
          ports,
        ),
    ).toThrow('invalid_input');
    expect(getter).not.toHaveBeenCalled();
    expect(listen).not.toHaveBeenCalled();
  });
  it('blocks new reads once parent closes and revokes before reporting its own cleanup complete', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch);
    await f.manager.open(a);
    const hold = deferred();
    release.push(hold.resolve);
    f.state.revokeHold = hold.promise;
    const closing = f.manager.close();
    await expect(f.manager.nativeResult(reading(a), a.roomViewBearer)).rejects.toMatchObject({
      code: 'closed',
    });
    hold.resolve();
    await closing;
    expect(f.manager.metrics()).toMatchObject({
      closed: true,
      grantCalls: 0,
      roomOwners: 0,
      httpSockets: 0,
      httpHandlers: 0,
    });
    expect(f.state.revoked).toEqual([a.binding.bindingId]);
  });
});
