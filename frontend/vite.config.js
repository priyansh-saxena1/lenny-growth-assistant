import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Dev-only proxy so the browser talks to one origin and we don't depend on
    // CORS being right while iterating.
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } },
  },
})
