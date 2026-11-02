import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The built dashboard is served by the local Python server (metatron.product.server).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: '../src/metatron/product/web', emptyOutDir: true },
  server: { proxy: { '/api': 'http://127.0.0.1:8765' } },
})
