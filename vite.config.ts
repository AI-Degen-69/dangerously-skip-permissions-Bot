import { cloudflare } from '@cloudflare/vite-plugin'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss(), cloudflare()],
  resolve: {
    tsconfigPaths: true,
    alias: {
      '@': decodeURIComponent(new URL('./src', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')),
    },
  },
  server: { port: 5173, strictPort: false },
})
