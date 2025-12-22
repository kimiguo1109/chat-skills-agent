import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 28010,
    host: '0.0.0.0',
    allowedHosts: ['chatweb.studyx.ai', 'chatapp.studyx.ai', 'localhost', '127.0.0.1', '35.83.184.237'],
    proxy: {
      '/api': {
        target: 'http://localhost:28011',
        changeOrigin: true,
      },
      '/auth': {
        target: 'http://localhost:28011',
        changeOrigin: true,
      },
    },
  },
})
