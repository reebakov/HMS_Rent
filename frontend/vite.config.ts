import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
    restoreMocks: true,
    // тесты с десятками кликов через userEvent на слабом раннере CI (2 ядра + coverage) идут 5-6 с
    testTimeout: 30_000,
    hookTimeout: 30_000,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'text-summary', 'lcov'],
      all: true,
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.test.*', 'src/test/**', '**/*.d.ts', 'src/main.tsx'],
    },
  },
  server: {
    port: 5173,
    proxy: {
      // в dev-режиме все запросы /api уходят на FastAPI
      '/api': { target: process.env.VITE_API_PROXY ?? 'http://localhost:8000', changeOrigin: true },
    },
  },
})
