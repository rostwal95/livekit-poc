/** Actual local HTTP regression: API proxy cannot capture the native HTML entry. */
import { afterEach, expect, it, vi } from 'vitest';
import { createServer as createHttpServer } from 'node:http';
import { createServer as createViteServer } from 'vite';
import type { ViteDevServer } from 'vite';
import { resolve } from 'node:path';
import type { AddressInfo } from 'node:net';

afterEach(() => {
  vi.unstubAllEnvs();
});

it('serves native HTML locally and proxies only the application API namespace', async () => {
  const received: string[] = [];
  const backend = createHttpServer((request, response) => {
    received.push(request.url ?? '');
    response.writeHead(401, { 'Content-Type': 'application/json', Connection: 'close' });
    response.end('{"status":"unavailable"}');
  });
  await new Promise<void>((done, reject) => {
    backend.once('error', reject);
    backend.listen(0, '127.0.0.1', done);
  });
  const target = `http://127.0.0.1:${(backend.address() as AddressInfo).port}`;
  vi.stubEnv('P2_NATIVE_HTTP_ORIGIN', target);
  let server: ViteDevServer | undefined;
  try {
    server = await createViteServer({
      configFile: resolve(import.meta.dirname, '../vite.native.config.ts'),
      root: resolve(import.meta.dirname, '..'),
      logLevel: 'silent',
      server: { host: '127.0.0.1', port: 0, strictPort: true },
    });
    await server.listen();
    const origin = `http://127.0.0.1:${(server.httpServer!.address() as AddressInfo).port}`;
    const page = await fetch(origin + '/p2-native.html', { signal: AbortSignal.timeout(5000) });
    expect(page.status).toBe(200);
    expect(page.headers.get('Content-Type')).toContain('text/html');
    expect(await page.text()).toContain('id="native-app"');
    expect(received).toEqual([]);
    const api = await fetch(origin + '/p2/session', {
      method: 'POST',
      body: '{}',
      signal: AbortSignal.timeout(5000),
    });
    expect(api.status).toBe(401);
    expect(await api.json()).toEqual({ status: 'unavailable' });
    expect(received).toEqual(['/p2/session']);
  } finally {
    try {
      await server?.close();
    } finally {
      backend.closeAllConnections();
      await new Promise<void>((done, reject) =>
        backend.close((error) => (error ? reject(error) : done())),
      );
    }
  }
}, 20000);
