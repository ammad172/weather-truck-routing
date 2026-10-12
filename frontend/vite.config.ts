import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // The MapLibre chunk is ~1.05 MB on its own (286 KB gzipped) and can't be split further.
    chunkSizeWarningLimit: 1100,
    rolldownOptions: {
      output: {
        // MapLibre is ~1 MB of the bundle and changes far less often than the app, so it gets its
        // own long-cached file: an app update doesn't make browsers download the map library again.
        codeSplitting: {
          groups: [
            { name: 'maplibre', test: /node_modules[\\/]maplibre-gl[\\/]/ },
            { name: 'react', test: /node_modules[\\/](react|react-dom|scheduler|@tanstack)[\\/]/ },
          ],
        },
      },
    },
  },
  server: {
    // In development the Django API runs separately; in production Django serves this build.
    // The e2e tests point it at their own Django server.
    proxy: { '/api': process.env.API_PROXY_TARGET ?? 'http://127.0.0.1:8000' },
  },
})
