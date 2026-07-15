import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Фронт отдаётся тем же FastAPI по пути /app (не заменяя рабочий index.html
// на корне — см. решение после инцидента 15.07). Поэтому:
//  - base: '/app/' — чтобы сборка ссылалась на /app/assets/*, а не /assets/*;
//  - basename роутера берётся из import.meta.env.BASE_URL (см. src/App.jsx).
//
// В dev-режиме (npm run dev) base остаётся '/', а запросы к API проксируются
// на боевой/локальный backend — чтобы не поднимать фронт внутри контейнера.
export default defineConfig(({ command }) => ({
  base: command === 'build' ? '/app/' : '/',
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // Все реальные эндпоинты API — проксируем на backend, чтобы в dev
      // не упираться в CORS и не хардкодить хост в коде (см. API = '' в
      // src/api/client.js).
      '/auth': { target: 'http://localhost:8000', changeOrigin: true },
      '/tags': { target: 'http://localhost:8000', changeOrigin: true },
      '/users': { target: 'http://localhost:8000', changeOrigin: true },
      '/audit-log': { target: 'http://localhost:8000', changeOrigin: true },
      '/contragents': { target: 'http://localhost:8000', changeOrigin: true },
      '/folders': { target: 'http://localhost:8000', changeOrigin: true },
      '/templates': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
}))
