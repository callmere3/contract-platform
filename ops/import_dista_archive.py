# -*- coding: utf-8 -*-
"""
Перенос архива Dista в нашу базу (26.09.2026, решение владельца).

Файлы готовит `ops/dista_export.py` на ПК (база Dista — Firebird, и открыть
её можно только там). Здесь их разбирают ВНУТРИ контейнера api — там есть
и модели, и доступ к базе. Папка ops в контейнер не смонтирована, поэтому
скрипт и файлы копируются во временную папку контейнера:

    docker compose cp ops/import_dista_archive.py api:/tmp/dista/
    docker compose cp /root/dista/. api:/tmp/dista/
    docker compose exec -T -e PYTHONPATH=/app api \\
        python /tmp/dista/import_dista_archive.py /tmp/dista --part accruals --dry-run

Части (`--part`, можно несколько): accruals, rights, reports. Без
`--dry-run` пишет в базу. ПОВТОРНЫЙ ПРОГОН НИЧЕГО НЕ ЗАДВАИВАЕТ: начисления
и отчёты узнаются по номеру документа Dista (`dista_doc_id`), история прав
трека из Dista заменяется целиком.

СВЯЗКИ — ПО КОДАМ, а не по именам: FACES.ID у Dista — это наш `dista_id`
у контрагентов и площадок, GOODS.CODE — артикул трека (проверено по
выгрузкам Dista). Не нашлось — считаем и называем в итоге.

ЧТО ДЕЛАЕТСЯ С КАЖДОЙ ЧАСТЬЮ:

- accruals → `royalty_accruals`. Только история: балансы и ведомости это
  не трогает (решение владельца).

- rights → `track_right_history`, ПРЕЖНИЕ составы (всё, кроме последнего
  состава Dista: он у нас уже лежит текущим). Берём только то, что
  действовало ДО нашей даты прав (`tracks.rights_since`), и срок обрезаем
  по ней: история не должна спорить с текущим составом.

- reports → `partner_reports` (source='dista') + строки. ОТЧЁТ, КОТОРЫЙ У
  НАС УЖЕ ЗАГРУЖЕН ФАЙЛОМ, НЕ ПЕРЕНОСИТСЯ: та же площадка, тот же период и
  итог в пределах 2% (Dista выбрасывала строки, которых нет в каталоге, и
  её итог чуть меньше нашего) — иначе деньги в ведомости «по дате
  формирования» легли бы дважды. Такие перечисляются в итоге. Строка с
  артикулом, которого нет в номенклатуре, уходит в «Вне каталога», как при
  обычной загрузке, артикул сохраняется.
"""
import argparse
import gzip
import json
import os
import sys
import uuid
from collections import Counter
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, insert, select

from app.db import SessionLocal
from app.models import (
    Contragent, Partner, PartnerReport, RoyaltyAccrual, Track, TrackRightHistory,
)
from app.partner_reports import PRECISION, report_region
from app.routers_partner_reports import OUTSIDE_SKU, _store_rows, outside_track_id

DUPLICATE_TOLERANCE = Decimal("0.02")


class Row:
    """Строка отчёта для _store_rows. С __slots__: у Believe их сотни тысяч в документе."""
    __slots__ = ("row_num", "sku", "title", "artist", "quantity", "amount_author",
                 "amount_related", "content_type", "usage_type", "usage_kind", "territory")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


def _dec(text) -> Decimal | None:
    if text in (None, ""):
        return None
    return Decimal(str(text)).quantize(PRECISION)


def _lines(path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def import_accruals(db, folder, dry, stats):
    cards = dict(db.execute(select(Contragent.dista_id, Contragent.id)
                            .where(Contragent.dista_id.isnot(None))).all())
    have = set(db.scalars(select(RoyaltyAccrual.dista_doc_id)
                          .where(RoyaltyAccrual.dista_doc_id.isnot(None))))
    rows = []
    for a in _lines(os.path.join(folder, "accruals.jsonl")):
        if a["doc_id"] in have:
            stats["начислений уже было"] += 1
            continue
        cid = cards.get(str(a["face_id"]))
        stats["начислений без нашей карточки" if cid is None else "начислений с карточкой"] += 1
        rows.append({
            "id": uuid.uuid4(), "contragent_id": cid, "holder_name": a["holder"][:255],
            "period_from": date.fromisoformat(a["period_from"]),
            "period_to": date.fromisoformat(a["period_to"]),
            "accrued_on": date.fromisoformat(a["accrued_on"][:10]),
            "royalty": _dec(a["royalty"]), "realization": _dec(a["realization"]),
            "commission": _dec(a["commission"]), "note": a.get("note"),
            "source": "dista", "dista_doc_id": a["doc_id"],
        })
    if rows and not dry:
        db.execute(insert(RoyaltyAccrual), rows)
        db.commit()
    stats["начислений записано"] += 0 if dry else len(rows)


def import_rights(db, folder, dry, stats):
    cards = dict(db.execute(select(Contragent.dista_id, Contragent.id)
                            .where(Contragent.dista_id.isnot(None))).all())
    tracks = {sku: (tid, since) for sku, tid, since in
              db.execute(select(Track.sku, Track.id, Track.rights_since))}
    rows, touched = [], []
    for g in _lines(os.path.join(folder, "rights.jsonl")):
        found = tracks.get(g["sku"])
        if found is None:
            stats["треков истории нет в номенклатуре"] += 1
            continue
        tid, since = found
        versions = sorted(g["versions"], key=lambda v: v["dt"])
        latest = date.fromisoformat(versions[-1]["dt"][:10])
        if since != latest:
            # Наша дата прав разошлась с последним составом Dista: берём
            # только то, что было ДО нашей даты, и обрезаем срок по ней.
            stats["дата прав у нас не как в Dista"] += 1
        limit = since or latest
        added = 0
        for v, nxt in zip(versions, versions[1:]):
            vfrom = date.fromisoformat(v["dt"][:10])
            vto = min(date.fromisoformat(nxt["dt"][:10]), limit)
            if vfrom >= vto:
                continue
            slots = Counter()
            for r in v["rights"]:
                slots[r["type"]] += 1
                cid = cards.get(str(r["face_id"])) if r["face_id"] is not None else None
                if cid is None:
                    stats["прав истории без нашей карточки"] += 1
                rows.append({
                    "id": uuid.uuid4(), "track_id": tid, "valid_from": vfrom, "valid_to": vto,
                    "right_type": r["type"], "slot": slots[r["type"]],
                    "owner": (r["owner"] or "—")[:255], "contragent_id": cid,
                    "share": _dec(r["share"]).quantize(Decimal("0.01")) if r["share"] is not None else None,
                    "royalty": _dec(r["royalty"]).quantize(Decimal("0.01")) if r["royalty"] is not None else None,
                    "source": "dista",
                })
            added += 1
        if added:
            touched.append(tid)
            stats["треков с историей"] += 1
            stats["прежних составов"] += added
    if not dry and touched:
        # Повторный прогон заменяет историю Dista целиком — и только её:
        # версии, которые завёл импорт или правка у нас, не трогаем.
        for i in range(0, len(touched), 1000):
            db.execute(delete(TrackRightHistory).where(
                TrackRightHistory.track_id.in_(touched[i:i + 1000]),
                TrackRightHistory.source == "dista"))
        for i in range(0, len(rows), 5000):
            db.execute(insert(TrackRightHistory), rows[i:i + 5000])
        db.commit()
    stats["строк истории прав"] += len(rows)


def _read_rows(folder):
    """Строки отчётов по одному документу за раз — файл упорядочен по документу."""
    with gzip.open(os.path.join(folder, "rows.tsv.gz"), "rt", encoding="utf-8") as fh:
        doc, batch = None, []
        for line in fh:
            c = line.rstrip("\n").split("\t")
            if c[0] != doc and batch:
                yield int(doc), batch
                batch = []
            doc = c[0]
            batch.append(c)
        if batch:
            yield int(doc), batch


def import_reports(db, folder, dry, stats, only_doc=None):
    partners = {pid_code: (pid, name) for pid_code, pid, name in
                db.execute(select(Partner.dista_id, Partner.id, Partner.name)
                           .where(Partner.dista_id.isnot(None)))}
    tracks = dict(db.execute(select(Track.sku, Track.id)).all())
    have = set(db.scalars(select(PartnerReport.dista_doc_id)
                          .where(PartnerReport.dista_doc_id.isnot(None))))
    ours = {}
    names = {pid: name for _, (pid, name) in partners.items()}
    for pid, pf, pt, ta, tr, cur in db.execute(
        select(PartnerReport.partner_id, PartnerReport.period_from, PartnerReport.period_to,
               PartnerReport.total_author, PartnerReport.total_related, PartnerReport.currency)
        .where(PartnerReport.source.is_(None))
    ):
        # Регион (у Believe RU/KZ/AE) — по валюте ИСХОДНОГО файла, как в
        # списке отчётов: у нас KZ и AE до привязки лежат в валюте, и по
        # сумме их с рублями Dista не сравнить.
        region = report_region(names.get(pid, ""), cur)
        ours.setdefault((pid, pf, pt), []).append((Decimal(ta or 0) + Decimal(tr or 0), region))
    heads = {h["doc_id"]: h for h in _lines(os.path.join(folder, "reports.jsonl"))}
    outside = None if dry else outside_track_id(db)
    skipped_dupes = []

    for doc_id, cells in _read_rows(folder):
        if only_doc and doc_id != only_doc:
            continue
        h = heads.get(doc_id)
        if h is None:
            continue
        if doc_id in have:
            stats["отчётов уже было"] += 1
            continue
        partner = partners.get(str(h["face_id"]))
        if partner is None:
            stats["отчётов без площадки в справочнике"] += 1
            print(f"  нет площадки с кодом {h['face_id']} ({h['partner']}) — отчёт {doc_id} пропущен")
            continue
        pid, pname = partner
        pf, pt = date.fromisoformat(h["period_from"][:10]), date.fromisoformat(h["period_to"][:10])

        rows, ta, tr, qty, un_n, un_sum = [], Decimal(0), Decimal(0), Decimal(0), 0, Decimal(0)
        track_by_row = {}
        for c in cells:
            n = int(c[1])
            a, r = _dec(c[4]), _dec(c[5])
            q = Decimal(c[3]).quantize(Decimal("0.01"))
            sku = c[2] or None
            # Dista сама складывала строки с неизвестным артикулом на свой
            # товар «0000001 Вне каталога» — у нас это тот же приёмник, и
            # считать такую строку разнесённой нельзя.
            tid = tracks.get(sku) if sku and sku != OUTSIDE_SKU else None
            if tid is None:
                un_n += 1
                un_sum += a + r
                tid = outside
            track_by_row[n] = tid
            ta += a
            tr += r
            qty += q
            rows.append(Row(
                row_num=n, sku=sku, title=None, artist=None, quantity=q,
                amount_author=a, amount_related=r,
                content_type=c[6] or None, usage_type=c[7] or None,
                usage_kind=c[8] or None, territory=c[9] or None,
            ))
        total = ta + tr
        same = ours.get((pid, pf, pt), [])
        # Регион отчёта Dista — из пометки «RU 06.26» (у Believe).
        dregion = (h.get("remark") or "")[:2].upper() if report_region(pname, "RUB") else None
        dupe = next((t for t, reg in same
                     if (dregion and reg == dregion)
                     or (total and abs(t - total) / total <= DUPLICATE_TOLERANCE)), None)
        if dupe is None and same:
            print(f"  ВНИМАНИЕ: {pname} {pf}—{pt} ({h.get('remark') or 'без пометки'}): у нас есть "
                  f"отчёт за тот же период с другим итогом ({', '.join(f'{t:.2f} {r or ""}' for t, r in same)}), "
                  f"в Dista {total:.2f} — переносим")
        if dupe is not None:
            stats["отчётов уже загружено у нас файлом"] += 1
            skipped_dupes.append(f"{pname} {pf}—{pt}: Dista {total:.2f}, у нас {dupe:.2f}")
            continue
        stats["отчётов перенесено"] += 1
        stats["строк перенесено"] += len(rows)
        stats["строк вне каталога"] += un_n
        if dry:
            continue
        label = " · ".join(x for x in (f"Dista РН №{h['number']}", h.get("remark")) if x)
        report = PartnerReport(
            id=uuid.uuid4(), partner_id=pid, period_from=pf, period_to=pt,
            file_name=label[:255], rows_count=len(rows), unmatched_count=un_n,
            unmatched_amount=un_sum.quantize(Decimal("0.0001")), problem_count=0,
            total_quantity=qty, total_author=ta.quantize(Decimal("0.01")),
            total_related=tr.quantize(Decimal("0.01")), source="dista", dista_doc_id=doc_id,
        )
        db.add(report)
        db.flush()
        _store_rows(db, report.id, rows, track_by_row)
        db.commit()
        print(f"  {pt} {pname}: {len(rows)} строк", flush=True)

    if skipped_dupes:
        print("Не перенесены — уже загружены у нас файлом:")
        for line in skipped_dupes:
            print("  " + line)


def main():
    p = argparse.ArgumentParser(description="Перенос архива Dista")
    p.add_argument("folder")
    p.add_argument("--part", choices=["accruals", "rights", "reports"], action="append", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--doc", type=int, help="перенести один отчёт (для пробы)")
    a = p.parse_args()
    stats = Counter()
    db = SessionLocal()
    try:
        if "accruals" in a.part:
            import_accruals(db, a.folder, a.dry_run, stats)
        if "rights" in a.part:
            import_rights(db, a.folder, a.dry_run, stats)
        if "reports" in a.part:
            import_reports(db, a.folder, a.dry_run, stats, a.doc)
    finally:
        db.close()
    print("=== Итог ===" + (" (--dry-run: ничего не записано)" if a.dry_run else ""))
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
