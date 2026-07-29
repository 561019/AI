import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const platformProxyTarget = env.VITE_PLATFORM_PROXY_TARGET || 'http://127.0.0.1:8100'

  return {
    plugins: [vue()],
    server: {
      host: '0.0.0.0',
      proxy: {
        '/api': {
          target: platformProxyTarget,
          changeOrigin: true,
        },
      },
    },
    build: {
      rollupOptions: {
        input: {
          workbench: fileURLToPath(new URL('./index.html', import.meta.url)),
          platform: fileURLToPath(new URL('./platform.html', import.meta.url)),
        },
      },
    },
  }
})
