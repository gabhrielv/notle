// `defineConfig` comes from vitest rather than from vite: it is the same
// function with the `test` key typed, and Vite's own signature rejects that key.
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// In production one Worker serves both this bundle and the API from the same
// origin, so the front only ever uses relative paths. Locally the two are
// separate processes, and this proxy is what keeps those paths working against
// `wrangler dev` without a build time switch in the code.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8787',
    },
  },

  // The tests here are of pure functions: gesture arithmetic and an event
  // queue. None of them touch the DOM, so the node environment serves and
  // avoids dragging jsdom into a project that has two runtime dependencies.
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
