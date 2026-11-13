/** Actual control/read loopback framing; P2 backing ports are explicit in-memory fakes. */
import { createServer, request, Server } from 'node:http';
import { connect, type Socket } from 'node:net';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { NativeRoomHttp } from '../src/native-room-http.js';
import { NativeRoomError } from '../src/native-room-contract.js';
import {
  fixture,
  opening,
  command,
  reading,
  view,
  deferred,
  post,
  publisher,
  port,
} from './native-room-fixtures.js';
const fixtures: Awaited<ReturnType<typeof fixture>>[] = [];
const releases: (() => void)[] = [];
const hosts: NativeRoomHttp[] = [];
const sockets: Socket[] = [];
async function setup() {
  const f = await fixture();
  fixtures.push(f);
  return f;
}
async function socket(p: number) {
  return new Promise<Socket>((r, j) => {
    const s = connect({ host: '127.0.0.1', port: p });
    sockets.push(s);
    s.on('error', () => {});
    s.once('connect', () => r(s));
    s.once('error', j);
  });
}
afterEach(async () => {
  for (const r of releases.splice(0)) r();
  for (const s of sockets.splice(0)) s.destroy();
  for (const h of hosts.splice(0)) await h.close();
  for (const f of fixtures.splice(0)) await f.cleanup();
  vi.restoreAllMocks();
});
describe('fixed-profile G internal room HTTP', () => {
  it('opens/observes/closes with publisher auth and never echoes a native or view bearer', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch),
      endpoint = f.ready.endpoint;
    const accepted = await post(endpoint.port, 'open', a);
    expect(accepted.status).toBe(200);
    expect(accepted.value).toMatchObject({ state: 'ready', generation: '1' });
    expect(accepted.raw.toString()).not.toContain(a.binding.nativeBearer);
    expect(accepted.raw.toString()).not.toContain(a.roomViewBearer);
    expect((await post(endpoint.port, 'observe', command(a))).value).toMatchObject({
      state: 'ready',
    });
    expect((await post(endpoint.port, 'close', command(a))).value).toMatchObject({
      state: 'closed',
      globalReaderDrained: false,
    });
  });
  it('keeps publisher/room-view roles separate and rejects private selectors before effects', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch),
      p = f.ready.endpoint.port;
    expect((await post(p, 'open', a, a.roomViewBearer)).status).toBe(401);
    expect(f.state.published).toHaveLength(0);
    expect((await post(p, 'open', { ...a, scope: { tenantId: 'foreign' } })).status).toBe(400);
    await post(p, 'open', a);
    expect((await post(p, 'native-result', reading(a), publisher)).status).toBe(401);
    expect(f.state.native).toHaveLength(0);
  });
  it('returns a bare exact native view or null and blocks stale generation reads', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch),
      p = f.ready.endpoint.port;
    await post(p, 'open', a);
    const r = reading(a);
    const absent = await post(p, 'native-result', r, a.roomViewBearer);
    expect(absent.status).toBe(200);
    expect(absent.raw.toString()).toBe('null');
    f.state.view = view(r.deliveryId);
    const present = await post(p, 'native-result', r, a.roomViewBearer);
    expect(present.value).toEqual(f.state.view);
    await post(p, 'close', command(a));
    const b = opening(f.ready.nodeEpoch, '1', 'b');
    await post(p, 'open', b);
    expect((await post(p, 'native-result', r, a.roomViewBearer)).status).toBe(401);
  });
  it('rejects duplicates, proxy headers and excessive bodies without grant publication', async () => {
    const f = await setup(),
      a = opening(f.ready.nodeEpoch),
      p = f.ready.endpoint.port;
    const raw = JSON.stringify(a);
    expect((await post(p, 'open', '{"schemaVersion":1,' + raw.slice(1))).status).toBe(400);
    expect((await post(p, 'open', a, publisher, { 'x-forwarded-for': 'PRIVATE' })).status).toBe(
      400,
    );
    expect((await post(p, 'open', 'x'.repeat(1025))).status).toBe(400);
    expect(f.state.published).toHaveLength(0);
  });
  it('retains an abandoned admitted handler/grant and later observes the original publication', async () => {
    const f = await setup(),
      hold = deferred();
    releases.push(hold.resolve);
    f.state.publishHold = hold.promise;
    const a = opening(f.ready.nodeEpoch),
      raw = Buffer.from(JSON.stringify(a)),
      req = request({
        host: '127.0.0.1',
        port: f.ready.endpoint.port,
        path: '/v1/channel-policy/rooms/open',
        method: 'POST',
        headers: {
          authorization: 'Bearer ' + publisher,
          'content-type': 'application/json',
          'content-length': raw.length,
          connection: 'close',
        },
      });
    req.on('error', () => {});
    req.end(raw);
    await vi.waitFor(() => expect(f.state.published).toHaveLength(1));
    req.destroy();
    expect(f.manager.metrics()).toMatchObject({ grantCalls: 1, roomOwners: 1, httpHandlers: 1 });
    hold.resolve();
    await vi.waitFor(() => expect(f.manager.metrics().httpHandlers).toBe(0));
    expect(f.manager.observe(command(a))).toMatchObject({ state: 'ready' });
  });
  it('holds at most four full admitted handlers while one actual publication is retained', async () => {
    const f = await setup(),
      hold = deferred();
    releases.push(hold.resolve);
    f.state.publishHold = hold.promise;
    const a = opening(f.ready.nodeEpoch),
      p = f.ready.endpoint.port,
      calls = Array.from({ length: 4 }, () => post(p, 'open', a));
    await vi.waitFor(() => expect(f.manager.metrics().httpHandlers).toBe(4));
    await expect(post(p, 'open', a)).rejects.toBeInstanceOf(Error);
    expect(f.manager.metrics()).toMatchObject({ httpHandlers: 4, grantCalls: 1 });
    hold.resolve();
    expect((await Promise.all(calls)).every((c) => c.status === 200)).toBe(true);
    expect(f.state.published).toHaveLength(1);
  });
  it('bounds idle sockets at eight and closes every actual partial header socket', async () => {
    const f = await setup(),
      p = f.ready.endpoint.port;
    for (let i = 0; i < 8; i++) {
      const s = await socket(p);
      s.write('POST / HTTP/1.1\r\n');
    }
    await vi.waitFor(() => expect(f.manager.metrics().httpSockets).toBe(8));
    const ninth = connect({ host: '127.0.0.1', port: p });
    sockets.push(ninth);
    ninth.on('error', () => {});
    await new Promise<void>((r) => ninth.once('close', () => r()));
    expect(f.manager.metrics().httpSockets).toBe(8);
    await f.manager.close();
    expect(f.manager.metrics()).toMatchObject({ closed: true, httpSockets: 0, httpHandlers: 0 });
  });
  it('rechecks disclosure after a delayed port result before serializing any old-room bytes', async () => {
    let disclose = true;
    const h = new NativeRoomHttp(
      {
        async open() {
          throw new NativeRoomError('unavailable');
        },
        observe() {
          throw new NativeRoomError('unavailable');
        },
        async closeRoom() {
          throw new NativeRoomError('unavailable');
        },
        async recover() {
          throw new NativeRoomError('unavailable');
        },
        async nativeResult() {
          queueMicrotask(() => {
            disclose = false;
          });
          return view('11111111-1111-4111-8111-111111111111');
        },
        assertDisclosure() {
          if (!disclose) throw new NativeRoomError('unauthorized');
        },
      },
      publisher,
    );
    hosts.push(h);
    const p = await port();
    await h.start(p);
    const a = opening('11111111-1111-4111-8111-111111111111'),
      result = await post(p, 'native-result', reading(a), a.roomViewBearer);
    expect(result.status).toBe(401);
    expect(result.value).toEqual({ schemaVersion: 1, status: 'unavailable', code: 'unauthorized' });
    expect(result.raw.toString()).not.toContain('result_sha256');
  });
  it('retains a late actual listener through close and releases its exact port after startup settles', async () => {
    const address = await port(),
      original = Server.prototype.listen;
    let release: (() => void) | undefined;
    const spy = vi.spyOn(Server.prototype, 'listen').mockImplementation(function (
      this: Server,
      ...args: Parameters<Server['listen']>
    ) {
      release = () => {
        Reflect.apply(original, this, args);
      };
      return this;
    });
    const unavailable = () => {
      throw new NativeRoomError('unavailable');
    };
    const host = new NativeRoomHttp(
      {
        open: async () => unavailable(),
        observe: unavailable,
        closeRoom: async () => unavailable(),
        recover: async () => unavailable(),
        nativeResult: async () => unavailable(),
        assertDisclosure: unavailable,
      },
      publisher,
    );
    hosts.push(host);
    const starting = host.start(address).catch((e) => e);
    let settled = false;
    const closing = host.close().then(() => {
      settled = true;
    });
    await Promise.resolve();
    expect(settled).toBe(false);
    spy.mockRestore();
    release!();
    await closing;
    expect(await starting).toMatchObject({ code: 'closed' });
    expect(host.metrics()).toMatchObject({ httpSockets: 0, httpHandlers: 0 });
    const reused = createServer();
    await new Promise<void>((r, j) => {
      reused.once('error', j);
      reused.listen(address, '127.0.0.1', r);
    });
    await new Promise<void>((r) => reused.close(() => r()));
  });
});
