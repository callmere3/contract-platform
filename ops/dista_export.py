# -*- coding: utf-8 -*-
"""
Выгрузка архива из базы Dista (MEDIALAND.FDB) в файлы для переноса к нам
(26.09.2026, решение владельца после разбора базы Dista).

ЗАПУСКАЕТСЯ НА ПК, а не на сервере: база Dista — это Firebird 2.5, и
открыть её можно только встроенным Firebird (fbembed.dll) с Python-драйвером
`fdb`. На сервере ни того, ни другого нет и заводить незачем. Результат —
файлы в папке `--out`, их кладут на сервер и разбирают
`ops/import_dista_archive.py`.

КАК ОТКРЫТЬ БАЗУ (сделано на ПК владельца в D:\\dista_fdb):
- Firebird 2.5.9 x64 embedded (zip с github FirebirdSQL) → папка fb/;
- `pip install fdb`;
- у таблиц Dista есть вычисляемые колонки на её функциях из `fbfs25.dll`.
  Настоящая библиотека 32-битная и в 64-битный процесс не грузится, поэтому
  в fb/udf/ лежит своя заглушка с теми же функциями (собрана tcc из
  `D:\\dista_fdb\\fbfs25.c`). Без неё не открываются товары, документы и
  контрагенты — «function IFI is not defined». Работать только с КОПИЕЙ базы.

ЧТО ВЫГРУЖАЕТСЯ (всё — JSON Lines, строки отчётов — TSV в gzip):
- accruals.jsonl — начисления правообладателям («Акт приёмки-сдачи работ»,
  класс 61101) с парными «Сумма собранных прав» и «Удержание Лицензиата»
  (класс 93101). Пара находится по правообладателю, дате, периоду и сумме:
  собрано − удержано = начислено. Не нашлась однозначно — реализация и
  комиссия пустые.
- rights.jsonl — трек с несколькими составами прав: все составы с датами.
  Текущий у нас уже есть (выгрузка номенклатуры), загрузчик возьмёт прежние.
- reports.jsonl + rows.tsv.gz — отчёты площадок («Расходная накладная»,
  класс 41201) и их строки: артикул, количество, суммы авторских и смежных,
  четыре параметра. `--since` — с какой даты отчёта (по умолчанию 2025-01-01:
  вся история на нынешний сервер не помещается, решение владельца).

Коды Dista (FACES.ID) — это наш `dista_id` у контрагентов и площадок, а
GOODS.CODE — наш артикул: проверено по выгрузкам Dista.

    python ops/dista_export.py --db D:\\dista_fdb\\MEDIALAND.FDB \\
        --fb D:\\dista_fdb\\fb\\fbembed.dll --out D:\\dista_fdb\\out --since 2025-01-01
"""
import argparse
import collections
import gzip
import json
import os
import re
from datetime import date, datetime

import fdb

REPORT_CLASS, ACT_CLASS, PLAN_CLASS = 41201, 61101, 93101
AUTHOR_TYPE, RELATED_TYPE = 1, 2
PERIOD_RE = re.compile(r"период с (\d\d\.\d\d\.\d{4}) по (\d\d\.\d\d\.\d{4})")


def _d(text: str) -> str:
    return datetime.strptime(text, "%d.%m.%Y").date().isoformat()


def _json(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(value)


def accruals(cur, out):
    cur.execute(
        """select d.id, d.face_id, trim(f.name), d.dt, d.sum_n, d.ground, a.vn
           from docs d join faces f on f.id = d.face_id
           left join "PROP$ATTACH" a on a.obj_id = d.id and a.prop_id = 910
           where d.dociden in (?, ?)""", (ACT_CLASS, PLAN_CLASS))
    acts, plans = [], collections.defaultdict(lambda: {3: [], 4: []})
    for doc_id, face, name, dt, amount, ground, kind in cur.fetchall():
        m = PERIOD_RE.search(ground or "")
        if not m:
            continue
        key = (face, dt, m.group(1), m.group(2))
        if kind == 1:
            acts.append((doc_id, face, name, dt, amount or 0.0, ground, key))
        elif kind in (3, 4):
            plans[key][int(kind)].append(amount or 0.0)
    paired = 0
    with open(os.path.join(out, "accruals.jsonl"), "w", encoding="utf-8") as fh:
        for doc_id, face, name, dt, amount, ground, key in acts:
            group = plans.get(key, {3: [], 4: []})
            pick = None
            for c in group[3]:
                for w in group[4]:
                    if abs(c - w - amount) < 0.01:
                        pick = (c, w)
                        break
                if pick:
                    break
            if pick:
                group[3].remove(pick[0])
                group[4].remove(pick[1])
                paired += 1
            fh.write(json.dumps({
                "doc_id": doc_id, "face_id": face, "holder": name,
                "period_from": _d(key[2]), "period_to": _d(key[3]), "accrued_on": dt,
                "royalty": repr(amount), "realization": repr(pick[0]) if pick else None,
                "commission": repr(pick[1]) if pick else None, "note": ground,
            }, default=_json, ensure_ascii=False) + "\n")
    print(f"начислений: {len(acts)}, с реализацией и комиссией: {paired}")


def rights(cur, out):
    cur.execute(
        """select trim(g.code), r.id, r.dt, i.type_id, i.holder_id, trim(f.name), i.percent, i.royalty, i.nn
           from "MUSIC$GOOD_RIGHTS" r join goods g on g.id = r.good_id
           join "MUSIC$GOOD_RIGHT_ITEMS" i on i.right_id = r.id
           left join faces f on f.id = i.holder_id
           where r.good_id in (select good_id from "MUSIC$GOOD_RIGHTS" group by 1 having count(*) > 1)
           order by g.code, r.dt, r.id, i.type_id, i.nn, i.id""")
    goods = collections.OrderedDict()
    for sku, rid, dt, rtype, face, name, share, royalty, nn in cur.fetchall():
        versions = goods.setdefault(sku, collections.OrderedDict())
        v = versions.setdefault(rid, {"dt": dt, "rights": []})
        if rtype not in (AUTHOR_TYPE, RELATED_TYPE):
            continue
        v["rights"].append({
            "type": "author" if rtype == AUTHOR_TYPE else "related",
            "face_id": face, "owner": name or "", "share": share, "royalty": royalty,
        })
    with open(os.path.join(out, "rights.jsonl"), "w", encoding="utf-8") as fh:
        for sku, versions in goods.items():
            fh.write(json.dumps({"sku": sku, "versions": list(versions.values())},
                                default=_json, ensure_ascii=False) + "\n")
    print(f"треков с несколькими составами прав: {len(goods)}")


def reports(cur, out, since: date):
    names = {pid: vs for pid, vs in cur.execute(
        'select id, trim(vs) from "PROP$DATA" where prop_id in (902, 903, 904, 905)').fetchall()}
    cur.execute(
        """select d.id, d.face_id, trim(f.name), d.dt, d.dtx, trim(d.number), d.remark, d.state_code,
                  (select first 1 a.vd from "PROP$ATTACH" a where a.obj_id = d.id and a.prop_id = 901)
           from docs d join faces f on f.id = d.face_id
           where d.dociden = ? and d.dt >= ? order by d.id""", (REPORT_CLASS, since))
    docs = cur.fetchall()
    rows_total = 0
    with open(os.path.join(out, "reports.jsonl"), "w", encoding="utf-8") as fh, \
            gzip.open(os.path.join(out, "rows.tsv.gz"), "wt", encoding="utf-8", newline="\n") as gz:
        for doc_id, face, name, dt, dtx, number, remark, state, start in docs:
            period_from = start.date() if start else dt.replace(day=1)
            cur.execute(
                """select trim(g.code), di.quant, m.cr_sum_n, m.rr_sum_n,
                          m.content_type_id, m.use_type_id, m.use_kind_id, m.territory_id
                   from docitems di join "MUSIC$DOCITEMS" m on m.id = di.id
                   left join goods g on g.id = di.good_id
                   where di.document_id = ? order by di.id""", (doc_id,))
            n = 0
            for sku, qty, cr, rr, ct, ut, uk, terr in cur:
                n += 1
                cells = [str(doc_id), str(n), sku or "", repr(qty or 0.0), repr(cr or 0.0), repr(rr or 0.0),
                         *((names.get(x) or "") for x in (ct, ut, uk, terr))]
                gz.write("\t".join(c.replace("\t", " ").replace("\n", " ") for c in cells) + "\n")
            rows_total += n
            fh.write(json.dumps({
                "doc_id": doc_id, "face_id": face, "partner": name, "number": number,
                "period_from": period_from, "period_to": dt, "shipped_on": dtx,
                "remark": (remark or "").strip() or None, "state": state, "rows": n,
            }, default=_json, ensure_ascii=False) + "\n")
            print(f"  {dt} {name}: {n} строк", flush=True)
    print(f"отчётов: {len(docs)}, строк: {rows_total}")


def main():
    p = argparse.ArgumentParser(description="Выгрузка архива Dista для переноса")
    p.add_argument("--db", required=True)
    p.add_argument("--fb", required=True, help="путь к fbembed.dll")
    p.add_argument("--out", required=True)
    p.add_argument("--since", default="2025-01-01", help="отчёты с этой даты")
    p.add_argument("--only", choices=["accruals", "rights", "reports"], action="append")
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)
    con = fdb.connect(dsn=a.db, user="SYSDBA", password="masterkey",
                      fb_library_name=a.fb, charset="WIN1251")
    cur = con.cursor()
    parts = a.only or ["accruals", "rights", "reports"]
    if "accruals" in parts:
        accruals(cur, a.out)
    if "rights" in parts:
        rights(cur, a.out)
    if "reports" in parts:
        reports(cur, a.out, date.fromisoformat(a.since))
    con.close()


if __name__ == "__main__":
    main()
