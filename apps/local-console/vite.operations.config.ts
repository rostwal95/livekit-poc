import { defineConfig } from 'vite';
import { resolve } from 'node:path';
// A trusted process option, never an operator-supplied URL or browser credential.
const port = process.env.P2_OPERATIONS_API_PORT;
if (port !== undefined && (!/^[1-9][0-9]{0,4}(?![\s\S])/.test(port) || Number(port) > 65535))
  throw new Error('A bounded literal loopback operations port is required.');
export default defineConfig({
  server: {
    host: '127.0.0.1',
    strictPort: true,
    allowedHosts: ['127.0.0.1'],
    ...(port
      ? {
          proxy: {
            '^/p2-operations/': {
              target: `http://127.0.0.1:${port}`,
              changeOrigin: true,
              rewrite: (path: string) => path.replace(/^\/p2-operations\//, '/v1/operations/'),
            },
          },
        }
      : {}),
  },
  build: {
    outDir: 'dist-operations',
    sourcemap: false,
    target: 'es2022',
    rollupOptions: { input: resolve(import.meta.dirname, 'p2-operations.html') },
  },
});
