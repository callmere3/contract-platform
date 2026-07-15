#!/usr/bin/env bash
#
# Собирает React-фронт и кладёт сборку в backend/static/app/.
#
# Почему именно туда: backend/static уже смонтирован в контейнер api как
# volume (см. docker-compose.yml), поэтому сборка попадает внутрь сразу,
# без пересборки образа и рестарта контейнера.
#
# Что этот скрипт НЕ делает и делать не должен:
#   - не трогает backend/static/index.html (рабочий интерфейс на "/"),
#     пишет только в подпапку app/;
#   - не коммитит и не пушит ничего сам.
#
# Использование (из папки frontend):
#     ./deploy.sh
#
set -euo pipefail

cd "$(dirname "$0")"

TARGET="../backend/static/app"

echo "==> Сборка фронта"
npm run build

echo "==> Выкладка в $TARGET"
# Полностью заменяем предыдущую сборку: у файлов в assets/ имена с хешами,
# и без очистки там копились бы все старые версии бандла до бесконечности.
rm -rf "$TARGET"
mkdir -p "$TARGET"
cp -r dist/* "$TARGET/"

echo "==> Готово. Файлы:"
ls -la "$TARGET"
echo
echo "Дальше: закоммитить backend/static/app и запушить в оба remote —"
echo "post-receive хук разложит их на сервере сам."
