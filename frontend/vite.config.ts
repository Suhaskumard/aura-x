/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { configDefaults } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: true,
    // 'forks' is vitest's own default and is stable on Node 22 / Windows;
    // 'threads' here intermittently fails with "Timeout waiting for worker
    // to respond", which aborts the whole run non-deterministically.
    pool: 'forks',
    // Playwright specs under e2e/ use the `.spec.ts` suffix, which Vitest's
    // default glob would otherwise pick up and fail to run.
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
})
