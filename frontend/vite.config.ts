import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3100,  // 修改为 3100 端口
    proxy: {
      '/api': {
        target: 'http://localhost:8088',
        changeOrigin: true,
      },
      '/auth': {
        target: 'http://localhost:8088',
        changeOrigin: true,
      },
    },
  },
})
