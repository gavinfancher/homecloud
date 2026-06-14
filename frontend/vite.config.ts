import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev, proxy API + forward-auth calls to the local controller so the SPA
// runs same-origin (no CORS). Override the target with CONTROLLER_URL.
const controller = process.env.CONTROLLER_URL ?? 'http://localhost:8080'
const pkg = JSON.parse(readFileSync('./package.json', 'utf8')) as { version: string }

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  server: {
    proxy: {
      '/api': { target: controller, changeOrigin: true },
      '/auth': { target: controller, changeOrigin: true },
    },
  },
})
