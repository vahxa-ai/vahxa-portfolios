import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In dev, Vite serves the React app and proxies /api to FastAPI (uvicorn portal.main:app --port 8080).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: { '/api': 'http://127.0.0.1:8080' },
  },
})
