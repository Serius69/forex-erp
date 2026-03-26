import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  return {
    plugins: [react()],

    resolve: {
      alias: { '@': path.resolve(__dirname, './src') },
    },

    server: {
      host:      '0.0.0.0',
      port:       5173,
      strictPort: true,

      // Proxy para dev sin Docker (cuando corres Vite directamente)
      proxy: {
        '/api': {
          target:      'http://localhost:8000',
          changeOrigin: true,
          secure:       false,
        },
        '/ws': {
          target:  'ws://localhost:8000',
          ws:       true,
          changeOrigin: true,
        },
        '/media': {
          target:      'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },

    // Variables de entorno disponibles en el código
    define: {
      __API_BASE_URL__: JSON.stringify(env.VITE_API_BASE_URL || '/api'),
      __WS_BASE_URL__:  JSON.stringify(env.VITE_WS_BASE_URL  || '/ws'),
    },
  }
})