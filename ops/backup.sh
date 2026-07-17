#!/bin/bash
#
# Ежедневный бэкап contract-platform — СЛОЙ 1: копия на самом VPS.
#
# От чего спасает: «выполнился не тот SQL», кривая миграция, случайно
# удалённая карточка (DELETE у контрагента физический и безвозвратный,
# мягкого удаления нет). Восстановление — секунды, ходить никуда не надо.
#
# От чего НЕ спасает: смерть диска, обнуление провайдером, взлом сервера.
# Лежит на той же машине, что и оригинал, — поэтому это только первый слой.
# Второй: restic на ПК забирает эти файлы к себе (ops/pull-backup.ps1).
#
# Ставится в cron root'а:
#   0 3 * * * /root/contract-platform/ops/backup.sh >> /var/log/contracts-backup.log 2>&1
#
# ВАЖНО про формат. Дамп в plain и tar без сжатия — намеренно. Файлы
# забирает restic, а он дедуплицирует: от сжатия один изменённый байт
# меняет весь файл целиком, и дедупликация перестаёт работать — каждая
# копия ложится в репозиторий заново. Сжатие берёт на себя restic. Цена
# решения — ~25 МБ на диске за 14 дней при 13 ГБ свободных.
#
set -euo pipefail

REPO_DIR=/root/contract-platform
DIR=/root/backups
KEEP_DAYS=14
DATE=$(date +%F)

# В дампе паспортные данные и банковские реквизиты контрагентов, в env-* —
# пароль БД, root-ключ MinIO и JWT-секрет. Всё создаётся с правами 600.
umask 077

cd "$REPO_DIR"
mkdir -p "$DIR"
chmod 700 "$DIR"

# Всё пишется в .part и переименовывается только после успеха: mv в пределах
# одной ФС атомарен, поэтому файл БЕЗ .part — гарантированно целый. Так
# вчерашняя рабочая копия переживает обрыв на полпути (кончилось место,
# упал контейнер): при set -e скрипт умрёт до mv, а .part перезапишется на
# следующем запуске. Резервная копия не должна оставаться без резерва в
# момент собственного создания.

# 1. База
docker compose exec -T db pg_dump -U contracts_app --format=plain contracts \
  > "$DIR/db-$DATE.sql.part"
mv -f "$DIR/db-$DATE.sql.part" "$DIR/db-$DATE.sql"

# 2. Шаблоны — обычными .docx, через S3-API самого приложения.
#
# Не tar'ом volume'а minio, хотя так проще. MinIO хранит объекты не файлами,
# а в своём формате: <uuid>.docx/xl.meta, причём мелкие объекты вшиты прямо
# внутрь метаданных (проверено 17.07.2026: part.1 не существует, всё в
# xl.meta). Копия volume'а — это байты, которые можно вернуть только в
# MinIO той же версии; достать оттуда договор руками нельзя. А шаблоны —
# это юридические документы компании, и бэкап, который нельзя открыть, для
# них бессмысленен.
#
# Ходим через app.storage: у контейнера api уже есть boto3, ключи и бакет —
# ни mc, ни отдельного образа, ни второй копии credentials не нужно.
# Плата за это — зависимость от живого api: если он лежит, бэкап шаблонов в
# этот день не сделается, и set -e остановит скрипт. Это осознанно: дамп
# базы (шаг 1) к этому моменту уже сохранён, а тихий недобэкап опаснее
# шумного отказа.
docker compose exec -T api python - > "$DIR/templates-$DATE.tar.part" <<'PY'
import sys, io, tarfile
from app.storage import s3_client
from app.config import settings

tar = tarfile.open(fileobj=sys.stdout.buffer, mode="w|")
pages = s3_client.get_paginator("list_objects_v2").paginate(Bucket=settings.minio_bucket)
for page in pages:
    for obj in page.get("Contents", []):
        body = s3_client.get_object(Bucket=settings.minio_bucket, Key=obj["Key"])["Body"].read()
        info = tarfile.TarInfo(obj["Key"])
        info.size = len(body)
        tar.addfile(info, io.BytesIO(body))
tar.close()
PY
mv -f "$DIR/templates-$DATE.tar.part" "$DIR/templates-$DATE.tar"

# 3. Расшифровка: в бакете шаблоны названы uuid'ами, человеческое имя живёт
# в БД. Без этого файла восстановленный архив — четырнадцать безымянных
# .docx, и чтобы понять, где какой, придётся сначала поднимать Postgres.
docker compose exec -T db psql -U contracts_app -d contracts -t -A -F'	' \
  > "$DIR/templates-$DATE.txt" <<'SQL'
select storage_key, coalesce(doc_type, '-'), name from templates order by name;
SQL

# 4. .env — пароль БД, root-ключ MinIO, JWT-секрет. Без него восстановление
# превращается в угадайку: дамп разворачивать некуда и нечем.
cp "$REPO_DIR/.env" "$DIR/env-$DATE.txt"

# 5. Ротация. Заодно подчищает .part, оставшиеся от давних сорванных
# запусков.
find "$DIR" -maxdepth 1 -type f -mtime "+$KEEP_DAYS" -delete

echo "$(date '+%F %T') OK  db=$(du -h "$DIR/db-$DATE.sql" | cut -f1)" \
     "шаблоны=$(du -h "$DIR/templates-$DATE.tar" | cut -f1)" \
     "($(tar -tf "$DIR/templates-$DATE.tar" | wc -l) шт.)" \
     "всего=$(du -sh "$DIR" | cut -f1)" \
     "файлов=$(find "$DIR" -maxdepth 1 -type f | wc -l)"
