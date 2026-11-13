/** Actual fixed-port binding and owned late startup. No specialist fixture imports. */
import { createServer, Server } from 'node:http';
import { connect } from 'node:net';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  CAPABILITY,
  EvidenceRegistry,
  LocalTrust,
  SpecialistServer,
  tokenDigest,
} from '../src/index.js';
function server(closeMs = 1000) {
  return new SpecialistServer({
    trust: new LocalTrust([
      {
        principal_id: 'listen_test',
        token_sha256: tokenDigest('a'.repeat(43)),
        scopes: [
          {
            scope: { tenant_id: 'tenant_demo', account_id: 'account_demo' },
            invoke_capabilities: [CAPABILITY],
            result_capabilities: [CAPABILITY],
            cancel_capabilities: [CAPABILITY],
            evidence_sources: [],
          },
        ],
      },
    ]),
    evidence: new EvidenceRegistry([]),
    limits: { closeMs },
    observer: () => {},
  });
}
async function reserve() {
  const peer = createServer();
  await new Promise<void>((r, j) => {
    peer.once('error', j);
    peer.listen(0, '127.0.0.1', r);
  });
  const address = peer.address();
  if (!address || typeof address === 'string') throw new Error('fixture');
  return { peer, port: address.port };
}
async function stop(peer: Server) {
  await new Promise<void>((r, j) => peer.close((e) => (e ? j(e) : r())));
}
afterEach(() => {
  vi.restoreAllMocks();
});
describe('public specialist fixed-port listen', () => {
  it('preserves noarg and explicit zero ephemeral binding', async () => {
    for (const port of [undefined, 0]) {
      const s = server();
      try {
        const e = port === undefined ? await s.listen() : await s.listen(port);
        expect(e.host).toBe('127.0.0.1');
        expect(e.port).toBeGreaterThan(0);
      } finally {
        await s.close();
      }
    }
  });
  it('validates supplied ports before listen and allows useful valid progress afterward', async () => {
    const spy = vi.spyOn(Server.prototype, 'listen'),
      s = server();
    try {
      for (const port of [-1, 65536, 1.5, NaN, Infinity, true, null, '11028', 2 ** 53])
        await expect(s.listen(port as number)).rejects.toMatchObject({ code: 'invalid_http' });
      expect(spy).not.toHaveBeenCalled();
      await s.listen(0);
      expect(spy).toHaveBeenCalledTimes(1);
    } finally {
      await s.close();
    }
  });
  it('keeps an occupied listener intact, reports finite failure, and can retry the exact port without stale callbacks', async () => {
    const held = await reserve(),
      s = server();
    let peerOpen = true;
    try {
      await expect(s.listen(held.port)).rejects.toMatchObject({
        code: 'connection_failed',
        message: 'connection_failed',
      });
      expect(held.peer.listening).toBe(true);
      expect(s.metrics().sockets).toBe(0);
      await stop(held.peer);
      peerOpen = false;
      expect((await s.listen(held.port)).port).toBe(held.port);
      await s.close();
      const reuse = createServer();
      await new Promise<void>((r, j) => {
        reuse.once('error', j);
        reuse.listen(held.port, '127.0.0.1', r);
      });
      await stop(reuse);
    } finally {
      if (peerOpen) await stop(held.peer);
      await s.close();
    }
  });
  it('settles close racing an actual fixed bind and releases the exact port', async () => {
    const held = await reserve();
    await stop(held.peer);
    const s = server(),
      starting = s.listen(held.port).catch((e) => e),
      closing = s.close();
    await closing;
    expect(await starting).toMatchObject({ code: 'closing' });
    expect(s.metrics()).toMatchObject({ active: 0, sockets: 0, requests: 0 });
    const reuse = createServer();
    await new Promise<void>((r, j) => {
      reuse.once('error', j);
      reuse.listen(held.port, '127.0.0.1', r);
    });
    await stop(reuse);
  });
  it('retains a delayed bind after incomplete close and useful retry observes actual settlement', async () => {
    const held = await reserve();
    await stop(held.peer);
    const original = Server.prototype.listen;
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
    const s = server(20),
      starting = s.listen(held.port).catch((e) => e);
    await expect(s.close()).rejects.toMatchObject({ code: 'cleanup_incomplete' });
    expect(release).toBeTypeOf('function');
    spy.mockRestore();
    release!();
    expect(await starting).toMatchObject({ code: 'closing' });
    await s.close();
    expect(s.metrics()).toMatchObject({ active: 0, sockets: 0, requests: 0 });
  });
  it('contains synchronous bind failures without private messages and permits a fresh useful bind', async () => {
    const s = server(),
      spy = vi.spyOn(Server.prototype, 'listen').mockImplementation(() => {
        throw new Error('PRIVATE_BIND');
      });
    await expect(s.listen(11028)).rejects.toMatchObject({
      code: 'connection_failed',
      message: 'connection_failed',
    });
    spy.mockRestore();
    await s.listen(0);
    await s.close();
  });
  it('denies all later listen after prestart close', async () => {
    const s = server();
    await s.close();
    await expect(s.listen(11028)).rejects.toMatchObject({ code: 'closing' });
  });
  it('closes actual abandoned partial-header sockets on a fixed endpoint', async () => {
    const held = await reserve();
    await stop(held.peer);
    const s = server();
    await s.listen(held.port);
    const socket = connect({ host: '127.0.0.1', port: held.port }),
      closed = new Promise<void>((r) => socket.once('close', () => r()));
    socket.on('error', () => {});
    try {
      await new Promise<void>((r, j) => {
        socket.once('connect', r);
        socket.once('error', j);
      });
      socket.write('POST /v1/specialist/invoke HTTP/1.1\r\n');
      await vi.waitFor(() => expect(s.metrics().sockets).toBe(1));
      await s.close();
      await closed;
      expect(s.metrics()).toMatchObject({ active: 0, sockets: 0, requests: 0 });
    } finally {
      socket.destroy();
      await s.close();
    }
  });
});
