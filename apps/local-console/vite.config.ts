import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    host: '0.0.0.0',
    port: 3000,
    strictPort: true,
    allowedHosts: ['localhost', '127.0.0.1'],
    proxy: { '/api': { target: 'http://127.0.0.1:18080', changeOrigin: false } },
  },
  build: { sourcemap: false, target: 'es2022' },
});
