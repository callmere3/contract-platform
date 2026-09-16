# -*- coding: utf-8 -*-
"""
Импорт номенклатуры: выгрузка Dista (.xlsx) → таблицы tracks и track_rights.

Запуск ВНУТРИ контейнера api (там есть и openpyxl, и доступ к базе):

    docker compose cp "выгрузка 16.09.26.xlsx" api:/tmp/tracks.xlsx
    docker compose exec -T -e PYTHONPATH=/app api \
        python ops/import_tracks.py /tmp/tracks.xlsx --source "выгрузка 16.09.26.xlsx"

РАЗБИРАЕТ ФАЙЛ НЕ САМ, а общим модулем `app/nomenclature_import.py` — тем же,
которым пользуется импорт из интерфейса. Свой читатель здесь был и убран:
разойдись они хоть в округлении доли или в том, какое поле обязательно, и
каталог, залитый скриптом, отличался бы от залитого из интерфейса. Такое
расхождение обнаруживается через месяцы.

А ВОТ ПОЛИТИКА РАЗНАЯ, и это осознанно. Импорт из интерфейса — ежедневная
калитка: строка с ошибкой (доли не сходятся, пустое обязательное поле) не
проходит. Скрипт — заливка исторических данных «как есть»: он про ошибки
РАССКАЗЫВАЕТ, но грузит всё, потому что чинить 121 тысячу строк задним числом
всё равно придётся в Dista, а каталог нужен уже сейчас. Нужна строгость —
флаг --strict.

КЛЮЧ — АРТИКУЛ. Строка с известным артикулом обновляет трек и ЗАМЕЩАЕТ состав
его прав целиком, а не дополняет: строка выгрузки несёт полное состояние
трека, и при слиянии ошибочно заведённого правообладателя нельзя было бы
убрать никогда.

ЧЕГО СКРИПТ НЕ ДЕЛАЕТ БЕЗ ПРОСЬБЫ: не архивирует треки, которых нет в файле.
Ежедневная выгрузка — это несколько десятков строк, а не каталог целиком, и
архивирование по умолчанию снесло бы в архив всё остальное. Для полной
выгрузки есть флаг --archive-missing.

--dry-run читает файл и печатает, что получилось бы, ничего не записывая.
"""
import argparse
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone

import openpyxl
from sqlalchemy import delete, insert, select, update

from app.db import SessionLocal
from app.models import Track, TrackRight
from app.nomenclature_import import read_rows

BATCH = 2000


def main() -> int:
    parser = argparse.ArgumentParser(description="Импорт номенклатуры из выгрузки Dista")
    parser.add_argument("path", help="путь к .xlsx внутри контейнера")
    parser.add_argument("--source", default=None, help="имя файла для записи в трек")
    parser.add_argument("--dry-run", action="store_true", help="только посчитать")
    parser.add_argument(
        "--archive-missing",
        action="store_true",
        help="пометить архивными треки, которых нет в файле (только для ПОЛНОЙ выгрузки)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="не грузить строки с ошибками (как импорт из интерфейса)",
    )
    args = parser.parse_args()

    source = args.source or args.path.rsplit("/", 1)[-1]
    stats = Counter()

    db = SessionLocal()
    try:
        existing = dict(db.execute(select(Track.sku, Track.id)).all())
        print(f"в базе уже {len(existing)} треков")

        seen: set[str] = set()
        new_tracks: list[dict] = []
        updates: list[dict] = []
        rights_rows: list[dict] = []
        touched: list[uuid.UUID] = []
        now = datetime.now(timezone.utc)

        def flush() -> None:
            """Пишем накопленное: сначала треки, потом их права."""
            nonlocal new_tracks, updates, rights_rows, touched
            if args.dry_run:
                new_tracks, updates, rights_rows, touched = [], [], [], []
                return
            if new_tracks:
                db.execute(insert(Track), new_tracks)
            if updates:
                db.execute(update(Track), updates)
            if touched:
                # Права замещаются целиком: сносим прежние и кладём пришедшие.
                db.execute(delete(TrackRight).where(TrackRight.track_id.in_(touched)))
            if rights_rows:
                db.execute(insert(TrackRight), rights_rows)
            db.commit()
            new_tracks, updates, rights_rows, touched = [], [], [], []

        wb = openpyxl.load_workbook(args.path, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        problems: list[str] = []

        for parsed in read_rows(ws):
            stats["read"] += 1
            track, rights = parsed.track, parsed.rights
            if parsed.errors:
                stats["с ошибками"] += 1
                if len(problems) < 20:
                    problems.append(
                        f"строка {parsed.row_num} ({track.get('sku')}): "
                        + "; ".join(parsed.errors)
                    )
                if args.strict:
                    stats["пропущено по --strict"] += 1
                    continue
            sku = track["sku"]
            if not sku:
                # Без артикула строку некуда записать — пропускаем всегда,
                # независимо от --strict.
                stats["без артикула"] += 1
                continue
            if sku in seen:
                # Артикул в файле обязан быть уникальным. Если нет — берём
                # последнюю строку и говорим об этом вслух.
                stats["дублей артикула в файле"] += 1
            seen.add(sku)

            track_id = existing.get(sku)
            if track_id is None:
                track_id = uuid.uuid4()
                existing[sku] = track_id
                new_tracks.append(
                    {
                        "id": track_id,
                        **track,
                        "source_file": source,
                        "imported_at": now,
                        "archived_at": None,
                    }
                )
                stats["заведено"] += 1
            else:
                updates.append(
                    {
                        "id": track_id,
                        **track,
                        "source_file": source,
                        "imported_at": now,
                        # Трек, вернувшийся в выгрузку, перестаёт быть архивным.
                        "archived_at": None,
                    }
                )
                stats["обновлено"] += 1

            touched.append(track_id)
            for right in rights:
                rights_rows.append({"id": uuid.uuid4(), "track_id": track_id, **right})
            stats["строк прав"] += len(rights)

            if stats["read"] % BATCH == 0:
                flush()
                print(f"  обработано {stats['read']}…", flush=True)

        flush()

        archived = 0
        if args.archive_missing and not args.dry_run:
            missing = [
                track_id for sku, track_id in existing.items() if sku not in seen
            ]
            if missing:
                db.execute(
                    update(Track)
                    .where(Track.id.in_(missing), Track.archived_at.is_(None))
                    .values(archived_at=now)
                )
                db.commit()
                archived = len(missing)

        print()
        print("=== Результат ===")
        print(f"строк прочитано      : {stats['read']}")
        print(f"треков заведено      : {stats['заведено']}")
        print(f"треков обновлено     : {stats['обновлено']}")
        print(f"строк прав записано  : {stats['строк прав']}")
        print(f"строк с ошибками     : {stats['с ошибками']}"
              + (" (пропущены: --strict)" if args.strict else " (загружены как есть)"))
        for key in ("без артикула", "дублей артикула в файле"):
            if stats[key]:
                print(f"{key:<21}: {stats[key]}")
        if problems:
            print()
            print("первые ошибки:")
            for line in problems:
                print("  " + line)
        if args.archive_missing:
            print()
            print(f"помечено архивными   : {archived}")
        if args.dry_run:
            print("(--dry-run: в базу ничего не записано)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
