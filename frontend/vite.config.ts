import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Node's process without pulling in @types/node for one env read.
const nodeEnv =
  (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env ?? {}

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        // Override with VITE_API_TARGET if the backend runs on another port
        // (e.g. when port 8000 is taken, start it with ATLAS_API_PORT=8010).
        target: nodeEnv.VITE_API_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    restoreMocks: true,
    unstubGlobals: true,
  },
})
