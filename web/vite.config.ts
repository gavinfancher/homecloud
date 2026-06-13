import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev, proxy API + forward-auth calls to the local controller so the SPA
// runs same-origin (no CORS). Override the target with CONTROLLER_URL.
const controller = process.env.CONTROLLER_URL ?? 'http://localhost:8080'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: controller, changeOrigin: true },
      '/auth': { target: controller, changeOrigin: true },
    },
  },
})
