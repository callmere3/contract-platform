#!/bin/bash
#
# Единственная команда, разрешённая ключу contracts-backup-pull.
#
# В /root/.ssh/authorized_keys этот ключ записан так:
#   command="/root/contract-platform/ops/serve-backup.sh",restrict ssh-ed25519 AAAA... contracts-backup-pull
#
# command= означает, что sshd подменяет ЛЮБУЮ запрошенную клиентом команду
# на эту, а то, что клиент просил, кладёт в $SSH_ORIGINAL_COMMAND. Ключ лежит
# на ПК без парольной фразы (иначе планировщик Windows не сможет им
# пользоваться — под ним нет ни ssh-agent, ни человека, чтобы фразу ввести),
# и это осознанный размен: ключ без фразы, но умеет он ровно одно — отдать
# бэкап в stdout. Утечёт файл ключа с ПК — root-шелла на сервере из него не
# сделать, restrict вдобавок отключает проброс портов, агента и pty.
#
# Отсюда же следует, почему тянем, а не толкаем: сервер не знает, где лежит
# копия, и не имеет к ней доступа. Взломавший сервер не сможет стереть
# бэкапы — обычный первый шаг шифровальщика.
#
# БЭКАП НА СЕРВЕРЕ НЕ ХРАНИТСЯ (решение владельца 26.09.2026). Раньше cron
# складывал дампы в /root/backups на 14 дней, а ПК их забирал. С архивом
# отчётов Dista база выросла до гигабайтов, и 14 копий на диске в 25 ГБ не
# помещаются. Теперь всё отдаётся ПОТОКОМ в момент, когда ПК просит: дамп
# идёт из pg_dump прямо в ssh и на диск сервера не пишется вовсе. Копии
# живут только на ПК, в restic (ops/pull-backup.ps1).
#
# Что отдаётся — выбирает клиент словом-командой (что угодно другое — отказ):
#   db         — дамп базы, plain SQL;
#   templates  — шаблоны .docx tar'ом (через app.storage, см. backup.sh);
#   meta       — tar из .env и расшифровки «uuid шаблона → название».
#
set -euo pipefail
cd /root/contract-platform

case "${SSH_ORIGINAL_COMMAND:-}" in
  db)
    exec docker compose exec -T db pg_dump -U contracts_app --format=plain contracts
    ;;
  templates)
    exec docker compose exec -T api python - <<'PY'
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
    ;;
  meta)
    # Два маленьких файла — во временную папку и tar'ом наружу. Папка
    # удаляется при любом исходе: в .env пароль БД и секреты.
    umask 077
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    cp .env "$tmp/env.txt"
    docker compose exec -T db psql -U contracts_app -d contracts -t -A -F'	' \
      -c "select storage_key, coalesce(doc_type, '-'), name from templates order by name" \
      > "$tmp/templates.txt"
    tar -C "$tmp" -cf - env.txt templates.txt
    ;;
  *)
    echo "serve-backup: неизвестная команда «${SSH_ORIGINAL_COMMAND:-}» (ждём db, templates или meta)" >&2
    exit 2
    ;;
esac
