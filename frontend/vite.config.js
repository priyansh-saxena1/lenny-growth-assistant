import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // Needed to serve the dev server through a proxying host with its own
    // domain (Colab's port-forward, ngrok, etc.) — without this Vite rejects
    // the request because the Host header doesn't match localhost.
    allowedHosts: true,
    port: 5173,
    // Dev-only proxy so the browser talks to one origin and we don't depend on
    // CORS being right while iterating.
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } },
  },
})
