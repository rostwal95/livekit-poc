import { defineConfig, type Connect, type Plugin } from 'vite';
import { resolve } from 'node:path';

/** The showcase origin's root opens the landing page that links both demos. */
const landingAtRoot = (): Plugin => {
  const rewrite: Connect.NextHandleFunction = (request, _response, next) => {
    if (request.url === '/' || request.url === '/index.html') request.url = '/landing.html';
    next();
  };
  return {
    name: 'landing-at-root',
    configureServer: (server) => void server.middlewares.use(rewrite),
    configurePreviewServer: (server) => void server.middlewares.use(rewrite),
  };
};

export default defineConfig({
  plugins: [landingAtRoot()],
  server: {
    host: '127.0.0.1',
    port: 5179,
    strictPort: true,
    allowedHosts: ['127.0.0.1'],
    proxy: {
      '/api/business/': {
        target: 'http://127.0.0.1:18080',
        changeOrigin: true,
      },
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
      input: {
        showcase: resolve(import.meta.dirname, 'channel-policy.html'),
        landing: resolve(import.meta.dirname, 'landing.html'),
        operator: resolve(import.meta.dirname, 'operator.html'),
      },
    },
  },
});
