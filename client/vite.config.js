import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Proxy /api to the FastAPI server so the browser never needs its address (or CORS).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
