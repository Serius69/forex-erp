import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
// Las variables VITE_* se exponen automáticamente en import.meta.env
// NO necesitamos loadEnv ni define aquí — Vite lo hace por nosotros.
export default defineConfig({
  plugins: [react()],

  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },

  server: {
    host:      '0.0.0.0',
    port:       5173,
    strictPort: true,

    // Proxy para desarrollo local sin Docker
    proxy: {
      '/api': {
        target:       'http://localhost:8000',
        changeOrigin: true,
        secure:       false,
      },
      '/ws': {
        target:       'ws://localhost:8000',
        ws:           true,
        changeOrigin: true,
      },
      '/media': {
        target:       'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },

  build: {
    outDir:        'dist',
    sourcemap:     false,
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        // Dividir vendors grandes en chunks separados
        manualChunks: {
          'vendor-react':  ['react', 'react-dom', 'react-router-dom'],
          'vendor-mui':    ['@mui/material', '@mui/icons-material', '@emotion/react', '@emotion/styled'],
          'vendor-charts': ['recharts', 'chart.js', 'react-chartjs-2'],
          'vendor-redux':  ['@reduxjs/toolkit', 'react-redux'],
        },
      },
    },
  },
})
