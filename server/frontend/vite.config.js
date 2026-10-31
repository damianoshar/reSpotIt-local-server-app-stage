import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev, proxy all backend routes to FastAPI on port 8000
const BACKEND = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Single rule — every backend route lives under /api/v1/*.
      '/api': { target: BACKEND, changeOrigin: true },
    },
  },
})
