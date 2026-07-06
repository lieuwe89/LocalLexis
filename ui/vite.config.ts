import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

// @ts-expect-error process is a nodejs global
const host = process.env.TAURI_DEV_HOST;

export default defineConfig(({ mode }) => {
  const isHub = mode === 'hub';
  return {
    plugins: [react()],
    resolve: {
      alias: {
        // The platform shim and app shell swap between native (tauri) and
        // browser (web/App.web) impls at build time. The web bundle then
        // contains zero @tauri-apps code.
        '@/platform': isHub
          ? resolve(__dirname, 'src/platform/web.ts')
          : resolve(__dirname, 'src/platform/tauri.ts'),
        ...(isHub ? { './App': resolve(__dirname, 'src/App.web.tsx') } : {}),
      },
    },

    // Vite options tailored for Tauri development and only applied in `tauri dev` or `tauri build`
    clearScreen: false,
    server: {
      port: 1420,
      strictPort: true,
      host: host || false,
      hmr: host
        ? {
            protocol: 'ws',
            host,
            port: 1421,
          }
        : undefined,
      watch: {
        ignored: ['**/src-tauri/**'],
      },
    },
    envPrefix: ['VITE_', 'TAURI_ENV_*'],
    build: {
      target:
        process.env.TAURI_ENV_PLATFORM === 'windows' ? 'chrome105' : 'safari13',
      minify: !process.env.TAURI_ENV_DEBUG ? 'esbuild' : false,
      sourcemap: !!process.env.TAURI_ENV_DEBUG,
      ...(isHub
        ? { outDir: resolve(__dirname, '../speechtotext/webui'), emptyOutDir: true }
        : {}),
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test-setup.ts'],
    },
  };
});
