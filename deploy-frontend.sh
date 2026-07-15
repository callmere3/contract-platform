#!/usr/bin/env bash
# Собирает frontend/ через разовый контейнер Node (без установки Node
# на хост/в рантайм-образ api) и кладёт результат в backend/static —
# та же папка, что уже смонтирована в docker-compose.yml как volume,
# поэтому пересборка/рестарт api не требуется.
#
# Запускать из корня репозитория: ./deploy-frontend.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "→ Сборка frontend (Node в разовом контейнере)…"
docker run --rm \
  -v "$(pwd)/frontend:/app" \
  -w /app \
  node:22-alpine \
  sh -c "npm ci && npm run build"

echo "→ Публикация в backend/static…"
rm -rf backend/static/*
cp -r frontend/dist/* backend/static/

echo "✓ Готово. backend/static обновлён, api подхватит изменения без рестарта."
