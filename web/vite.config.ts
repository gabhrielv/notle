import { defineConfig } from 'vite'
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
})
