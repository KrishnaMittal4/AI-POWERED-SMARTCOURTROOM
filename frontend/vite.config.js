import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // In production (Vercel) VITE_API_BASE is injected from env variables.
  // In local dev it falls back to http://localhost:8000 (see src files).
  server: {
    port: 5173,
  },
  build: {
    sourcemap: false,       // smaller bundle for production
    chunkSizeWarningLimit: 600,
  },
})
