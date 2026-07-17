#!/bin/bash
#
# Восстановление contract-platform из бэкапа — зеркало ops/backup.sh.
#
# Нужен в двух случаях:
#   1. Авария: снесли карточки, кривая миграция, умерла база.
#   2. Переезд на другой сервер. Дамп переносит ВСЁ: аккаунты вместе с
#      паролями (argon2-хэш самодостаточен, ничего не хранится снаружи
#      строки), историю генерации, журнал, папки и — главное — настройку
#      maps_to у меток шаблонов (template_fields, 166 строк). Ради последней
#      всё и затевалось: залив шаблоны заново, вы получите все метки с
#      maps_to="manual", и автоподстановка молча исчезнет.
#
# ЧТО ДЕЛАЕТ (по умолчанию — с боевыми данными):
#   - роняет схему public и разворачивает дамп заново;
#   - вычищает бакет MinIO и раскладывает шаблоны из архива.
# Это разрушительно и необратимо. Поэтому спрашивает подтверждение.
#
# ЧЕГО НЕ ДЕЛАЕТ:
#   - не восстанавливает .env. Курица и яйцо: без .env не поднимется ни
#     docker compose, ни база, класть его на место надо руками ДО запуска
#     (лежит рядом с дампом, env-<дата>.txt);
#   - не накатывает alembic. В дампе уже финальная схема и своя строка в
#     alembic_version — `upgrade head` после восстановления не нужен.
#
# Использование:
#   ops/restore.sh latest              — из самого свежего бэкапа
#   ops/restore.sh 2026-07-17          — из бэкапа за конкретный день
#   ops/restore.sh latest --yes        — без вопросов (для скриптов)
#
# ПРОВЕРКА БЭКАПА, не трогая боевые данные (так и надо это делать
# регулярно — бэкап, из которого ни разу не восстанавливали, это просто
# файл):
#   DB_NAME=contracts_test BUCKET=test-restore ops/restore.sh latest --yes
#
set -euo pipefail

REPO_DIR=/root/contract-platform
DIR=/root/backups

# Переопределяются окружением — ровно ради проверки на живом сервере без
# риска для боевых данных (см. шапку).
DB_NAME="${DB_NAME:-contracts}"
BUCKET="${BUCKET:-}"          # пусто = бакет из .env

DATE=""
ASSUME_YES=0

usage() {
    sed -n '2,45p' "$0" | sed 's/^# \?//'
    exit 1
}

for arg in "$@"; do
    case "$arg" in
        --yes) ASSUME_YES=1 ;;
        -h|--help) usage ;;
        -*) echo "Неизвестный ключ: $arg" >&2; exit 1 ;;
        *) DATE="$arg" ;;
    esac
done

[ -n "$DATE" ] || usage

cd "$REPO_DIR"

# --- 1. Найти файлы ---------------------------------------------------------

if [ "$DATE" = latest ]; then
    LAST=$(ls -t "$DIR"/db-*.sql 2>/dev/null | head -1 || true)
    [ -n "$LAST" ] || { echo "В $DIR нет ни одного дампа db-*.sql" >&2; exit 1; }
    DATE=$(basename "$LAST" .sql); DATE=${DATE#db-}
fi

DB_FILE="$DIR/db-$DATE.sql"
TAR_FILE="$DIR/templates-$DATE.tar"

for f in "$DB_FILE" "$TAR_FILE"; do
    [ -f "$f" ] || { echo "Нет файла: $f" >&2; exit 1; }
    [ -s "$f" ] || { echo "Файл пустой: $f" >&2; exit 1; }
done

# Дамп обязан заканчиваться маркером pg_dump. Обрезанный файл (кончилось
# место, оборвалась сеть при копировании) внешне выглядит нормальным, а
# psql проглотит его начало и оставит половину базы. Дешевле поймать здесь.
tail -5 "$DB_FILE" | grep -q "PostgreSQL database dump complete" \
    || { echo "ОШИБКА: $DB_FILE обрезан — нет маркера конца pg_dump." >&2; exit 1; }

TAR_COUNT=$(tar -tf "$TAR_FILE" | wc -l)

# --- 2. Подтверждение -------------------------------------------------------

IS_PROD=0
[ "$DB_NAME" = contracts ] && [ -z "$BUCKET" ] && IS_PROD=1

echo "Восстановление из бэкапа за $DATE"
echo "  дамп:     $DB_FILE ($(du -h "$DB_FILE" | cut -f1))"
echo "  шаблоны:  $TAR_FILE ($TAR_COUNT шт.)"
echo "  база:     $DB_NAME$([ "$IS_PROD" = 1 ] && echo '   <-- БОЕВАЯ')"
echo "  бакет:    ${BUCKET:-из .env}$([ "$IS_PROD" = 1 ] && echo '   <-- БОЕВОЙ')"

if [ "$IS_PROD" = 1 ]; then
    echo
    echo "Текущее состояние (будет ЗАТЁРТО):"
    docker compose exec -T db psql -U contracts_app -d "$DB_NAME" -t -A -F' | ' <<'SQL' 2>/dev/null || echo "  (база недоступна — видимо, её и восстанавливаем)"
select 'контрагентов: ' || (select count(*) from contragents)
     || ', пользователей: ' || (select count(*) from users)
     || ', шаблонов: ' || (select count(*) from templates)
     || ', история: ' || (select count(*) from generated_documents);
SQL
fi

if [ "$ASSUME_YES" != 1 ]; then
    echo
    read -r -p "Введите ВОССТАНОВИТЬ, чтобы продолжить: " CONFIRM
    [ "$CONFIRM" = "ВОССТАНОВИТЬ" ] || { echo "Отменено."; exit 1; }
fi

# --- 3. База ----------------------------------------------------------------

# api останавливаем только когда трогаем боевую базу: он держит соединения
# в пуле и пишет в неё, а DROP SCHEMA при живых сессиях не пройдёт. В режиме
# проверки (DB_NAME=contracts_test) сервис не трогаем вообще — проверка
# бэкапа не должна ронять прод.
if [ "$IS_PROD" = 1 ]; then
    echo "==> Останавливаю api"
    docker compose stop api >/dev/null
fi

# Базы может не быть (переезд на чистый сервер, режим проверки).
docker compose exec -T db psql -U contracts_app -d postgres -tAc \
    "select 1 from pg_database where datname='$DB_NAME'" | grep -q 1 \
    || { echo "==> Создаю базу $DB_NAME"; docker compose exec -T db createdb -U contracts_app "$DB_NAME"; }

echo "==> Чищу схему и разворачиваю дамп"
docker compose exec -T db psql -U contracts_app -d "$DB_NAME" -v ON_ERROR_STOP=1 --quiet <<SQL
-- Оборвать чужие сессии: одна забытая psql-консоль заблокирует DROP SCHEMA.
select pg_terminate_backend(pid) from pg_stat_activity
 where datname = '$DB_NAME' and pid <> pg_backend_pid();
-- В дампе нет ни одного DROP (проверено: pg_dump --format=plain без --clean),
-- он рассчитан на ПУСТУЮ базу. Без этого получим "relation already exists".
drop schema if exists public cascade;
create schema public;
SQL

# ON_ERROR_STOP=1 обязателен: без него psql проглотит ошибки, доедет до конца
# и вернёт 0 — получим наполовину восстановленную базу с рапортом об успехе.
docker compose exec -T db psql -U contracts_app -d "$DB_NAME" -v ON_ERROR_STOP=1 --quiet < "$DB_FILE"

# --- 4. Шаблоны в MinIO -----------------------------------------------------

# Через app.storage, как и в backup.sh: у контейнера api уже есть boto3,
# ключи и бакет. `run --rm` вместо `exec` намеренно — поднимает разовый
# контейнер, поэтому работает и при остановленном api (мы его только что
# остановили сами).
#
# Скрипт передаём через -c, а не heredoc'ом: stdin занят архивом.
PY_RESTORE=$(cat <<'PY'
import sys, tarfile
from app.storage import s3_client, ensure_bucket_exists
from app.config import settings

ensure_bucket_exists()

# Вычистить бакет. Восстановление обязано давать РОВНО состояние на момент
# бэкапа, а не смесь старого с новым: шаблон, удалённый после бэкапа,
# иначе воскрес бы и снова полез в подбор документов.
pages = s3_client.get_paginator("list_objects_v2").paginate(Bucket=settings.minio_bucket)
for key in [o["Key"] for page in pages for o in page.get("Contents", [])]:
    s3_client.delete_object(Bucket=settings.minio_bucket, Key=key)

tar = tarfile.open(fileobj=sys.stdin.buffer, mode="r|")
n = 0
for info in tar:
    if not info.isfile():
        continue
    s3_client.put_object(Bucket=settings.minio_bucket, Key=info.name,
                         Body=tar.extractfile(info).read())
    n += 1
print(n)
PY
)

echo "==> Возвращаю шаблоны в MinIO"
RUN_ENV=()
[ -n "$BUCKET" ] && RUN_ENV=(-e "MINIO_BUCKET=$BUCKET")
PUT_COUNT=$(docker compose run --rm -T "${RUN_ENV[@]}" api python -c "$PY_RESTORE" < "$TAR_FILE" | tail -1)

# --- 5. Поднять сервис ------------------------------------------------------

if [ "$IS_PROD" = 1 ]; then
    echo "==> Поднимаю api"
    docker compose start api >/dev/null
fi

# --- 6. Проверка ------------------------------------------------------------

# Восстановление без проверки — это надежда, а не восстановление.
echo
echo "=== Результат ==="
docker compose exec -T db psql -U contracts_app -d "$DB_NAME" -t -A -F' | ' <<'SQL'
select 'контрагентов: ' || (select count(*) from contragents)
     || ', пользователей: ' || (select count(*) from users)
     || ', шаблонов: ' || (select count(*) from templates)
     || ', история: ' || (select count(*) from generated_documents)
     || ', меток с maps_to: ' || (select count(*) from template_fields where maps_to <> 'manual')
     || ', схема: ' || (select version_num from alembic_version);
SQL

echo "шаблонов в бакете: $PUT_COUNT (в архиве было $TAR_COUNT)"
[ "$PUT_COUNT" = "$TAR_COUNT" ] || { echo "ОШИБКА: разошлось количество шаблонов!" >&2; exit 1; }

echo
if [ "$IS_PROD" = 1 ]; then
    echo "Готово. alembic накатывать НЕ надо — схема пришла из дампа."
    echo "Расшифровка uuid -> название: $DIR/templates-$DATE.txt"
else
    echo "Проверка прошла. Прибрать за собой:"
    echo "  docker compose exec -T db dropdb -U contracts_app $DB_NAME"
    [ -n "$BUCKET" ] && echo "  бакет $BUCKET удалить через веб-консоль MinIO (ssh -L 9001:localhost:9001)"
fi
