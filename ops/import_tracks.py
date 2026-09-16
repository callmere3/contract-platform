# -*- coding: utf-8 -*-
"""
Импорт номенклатуры: выгрузка Dista (.xlsx) → таблицы tracks и track_rights.

Запуск ВНУТРИ контейнера api (там есть и openpyxl, и доступ к базе):

    docker compose cp "выгрузка 16.09.26.xlsx" api:/tmp/tracks.xlsx
    docker compose exec -T -e PYTHONPATH=/app api \\
        python ops/import_tracks.py /tmp/tracks.xlsx --source "выгрузка 16.09.26.xlsx"

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
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import openpyxl
from sqlalchemy import delete, insert, select, update

from app.db import SessionLocal
from app.models import Track, TrackRight

# Колонки выгрузки — по номерам, а не по подписям: подписи в файле
# нестабильны («Роялти(%) авт. прав 1» с пробелом, «Роялти авт.прав 2» без
# процента), а порядок Dista держит.
COL_DATE = 0
COL_SKU = 1
COL_CODE = 2
COL_TITLE = 3
COL_ARTIST = 4
COL_AUTHORS = 5
COL_SHARE_AUTHOR = 6
COL_SHARE_RELATED = 7
COL_CATALOG = 8
COL_ALBUM = 9
COL_GENRE = 10
COL_ROYALTY = 11

# (вид права, слот, колонка владельца, колонка доли, колонка роялти).
# Третий слот в файле стоит ПОСЛЕ вторых смежных — порядок колонок в выгрузке
# исторический, и переставлять его нельзя, можно только читать как есть.
RIGHT_SLOTS = (
    ("author", 1, 12, 13, 14),
    ("author", 2, 15, 16, 17),
    ("author", 3, 24, 25, 26),
    ("related", 1, 18, 19, 20),
    ("related", 2, 21, 22, 23),
    ("related", 3, 27, 28, 29),
)

BATCH = 2000
MAX_LEN = {
    "sku": 32,
    "code": 64,
    "title": 300,
    "artist": 300,
    "catalog": 255,
    "album": 300,
    "genre": 120,
    "owner": 255,
}


def text(value, field: str | None = None) -> str | None:
    """Ячейка → строка без хвостовых пробелов; пустая ячейка → None."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if field and len(s) > MAX_LEN[field]:
        # Обрезаем, а не падаем: потерять одну длинную подпись не так страшно,
        # как не импортировать каталог. Случаи печатаются в итогах.
        s = s[: MAX_LEN[field]]
    return s


def decimal_percent(value) -> Decimal | None:
    """
    «Доля авторских прав» и «Роялти» из выгрузки — уже проценты: '100',
    '33,33', '80'. Запятая в них русская, точку Decimal ждёт сам.
    """
    if value is None:
        return None
    s = str(value).strip().replace(",", ".").replace("%", "")
    if not s:
        return None
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def fraction_percent(value, stats: dict) -> Decimal | None:
    """
    Доля и ставка правообладателя лежат ДОЛЯМИ ЕДИНИЦЫ: 1 = 100%, 0.8 = 80%.
    Приводим к процентам здесь, один раз, чтобы каждое место показа не
    множило на сто самостоятельно.

    Значение больше единицы считаем уже процентом и не трогаем: в выгрузке от
    16.09.2026 таких нет, но если Dista однажды сменит формат, каталог не
    должен молча получить доли по 8000%.
    """
    if value is None:
        return None
    try:
        number = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    if number > 1:
        stats["already_percent"] += 1
        return number.quantize(Decimal("0.01"))
    return (number * 100).quantize(Decimal("0.01"))


def read_rows(path: str, stats: dict):
    """Строки файла → (данные трека, список прав). Шапки пропускаются."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = ws.iter_rows(values_only=True)
    next(rows, None)  # первая строка — шапка

    for row in rows:
        if not row or len(row) < 30:
            stats["short_rows"] += 1
            continue
        sku = text(row[COL_SKU], "sku")
        # Шапка повторяется внутри файла (в выгрузке от 16.09.2026 — один
        # раз): экспорт грида Dista подмешивает её к данным.
        if not sku or sku == "Артикул":
            stats["skipped"] += 1
            continue

        title = text(row[COL_TITLE], "title")
        if not title:
            stats["no_title"] += 1
            title = "(без названия)"

        raw_date = row[COL_DATE]
        rights_since = raw_date.date() if isinstance(raw_date, datetime) else None
        if raw_date is not None and rights_since is None:
            stats["bad_date"] += 1

        track = {
            "sku": sku,
            "code": text(row[COL_CODE], "code"),
            "title": title,
            "artist": text(row[COL_ARTIST], "artist"),
            "authors": text(row[COL_AUTHORS]),
            "share_author": decimal_percent(row[COL_SHARE_AUTHOR]),
            "share_related": decimal_percent(row[COL_SHARE_RELATED]),
            "catalog": text(row[COL_CATALOG], "catalog"),
            "album": text(row[COL_ALBUM], "album"),
            "genre": text(row[COL_GENRE], "genre"),
            "royalty_percent": decimal_percent(row[COL_ROYALTY]),
            "rights_since": rights_since,
        }

        rights = []
        for right_type, slot, col_owner, col_share, col_royalty in RIGHT_SLOTS:
            owner = text(row[col_owner], "owner")
            if not owner:
                continue
            rights.append(
                {
                    "right_type": right_type,
                    "slot": slot,
                    "owner": owner,
                    "share": fraction_percent(row[col_share], stats),
                    "royalty": fraction_percent(row[col_royalty], stats),
                }
            )
        if not rights:
            stats["no_rights"] += 1

        yield track, rights


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
    args = parser.parse_args()

    source = args.source or args.path.rsplit("/", 1)[-1]
    stats = {
        "read": 0,
        "created": 0,
        "updated": 0,
        "rights": 0,
        "skipped": 0,
        "short_rows": 0,
        "no_title": 0,
        "no_rights": 0,
        "bad_date": 0,
        "already_percent": 0,
        "dupes_in_file": 0,
    }

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

        for track, rights in read_rows(args.path, stats):
            stats["read"] += 1
            sku = track["sku"]
            if sku in seen:
                # Артикул в файле обязан быть уникальным. Если нет — берём
                # последнюю строку и говорим об этом вслух.
                stats["dupes_in_file"] += 1
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
                stats["created"] += 1
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
                stats["updated"] += 1

            touched.append(track_id)
            for right in rights:
                rights_rows.append({"id": uuid.uuid4(), "track_id": track_id, **right})
            stats["rights"] += len(rights)

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
        print(f"треков заведено      : {stats['created']}")
        print(f"треков обновлено     : {stats['updated']}")
        print(f"строк прав записано  : {stats['rights']}")
        print(f"пропущено строк      : {stats['skipped']} (шапки и строки без артикула)")
        print(f"треков без прав      : {stats['no_rights']}")
        print(f"дублей артикула      : {stats['dupes_in_file']}")
        print(f"без названия         : {stats['no_title']}")
        print(f"кривая дата прав     : {stats['bad_date']}")
        print(f"доля/ставка > 1      : {stats['already_percent']} (прочитаны как проценты)")
        if args.archive_missing:
            print(f"помечено архивными   : {archived}")
        if args.dry_run:
            print("(--dry-run: в базу ничего не записано)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
