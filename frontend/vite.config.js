// import { defineConfig } from 'vite'
// import vue from '@vitejs/plugin-vue'

// // https://vite.dev/config/
// export default defineConfig({
//   plugins: [vue()],
// })







import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      // 🎯 核心通配网关：只要请求路径以 /api 开头，一律无缝转发给后端 FastAPI
      '/api': {
        target: 'http://127.0.0.1:8000', // 👈 确保指向你后端运行的真实端口
        changeOrigin: true,
        secure: false,
      }
    }
  }
})