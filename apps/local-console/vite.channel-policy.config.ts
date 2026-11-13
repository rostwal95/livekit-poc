import { defineConfig } from 'vite';
import { resolve } from 'node:path';
export default defineConfig({
  server: {
    host: '127.0.0.1',
    port: 5179,
    strictPort: true,
    allowedHosts: ['127.0.0.1'],
    proxy: {
      '/v1/channel-policy-demo/': {
        target: 'http://127.0.0.1:11033',
        changeOrigin: true,
        configure(proxy) {
          proxy.on('proxyReq', (request) => request.setHeader('Connection', 'close'));
        },
      },
    },
  },
  build: {
    outDir: 'dist-channel-policy',
    sourcemap: false,
    target: 'es2022',
    rollupOptions: {
      input: resolve(import.meta.dirname, 'channel-policy.html'),
    },
  },
});
