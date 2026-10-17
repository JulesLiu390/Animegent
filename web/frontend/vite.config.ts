import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 后端地址：前端通过开发服务器代理访问 /api 和 /files，局域网里的其他设备打开页面也能用
const backend = process.env.ANIMEGENT_BACKEND || 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: backend, changeOrigin: true },
      '/files': { target: backend, changeOrigin: true },
    },
  },
})
