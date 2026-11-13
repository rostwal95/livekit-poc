import { defineConfig } from 'vite';
import { resolve } from 'node:path';

const target = process.env.P2_NATIVE_HTTP_ORIGIN;
if (target !== undefined) {
  const url = new URL(target);
  if (
    url.protocol !== 'http:' ||
    url.hostname !== '127.0.0.1' ||
    url.username ||
    url.password ||
    url.pathname !== '/' ||
    url.search ||
    url.hash
  )
    throw new Error('A fixed loopback P2 application origin is required.');
}
export default defineConfig({
  server: {
    host: '127.0.0.1',
    strictPort: true,
    allowedHosts: ['127.0.0.1', 'localhost'],
    ...(target ? { proxy: { '^/p2/': { target, changeOrigin: false } } } : {}),
  },
  build: {
    outDir: 'dist-native',
    sourcemap: false,
    target: 'es2022',
    rollupOptions: { input: resolve(import.meta.dirname, 'p2-native.html') },
  },
});
