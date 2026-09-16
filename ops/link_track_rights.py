# -*- coding: utf-8 -*-
"""
Разовая привязка уже залитых прав к карточкам контрагентов.

    docker compose cp ops/link_track_rights.py api:/tmp/link.py
    docker compose exec -T -e PYTHONPATH=/app api python /tmp/link.py --dry-run
    docker compose exec -T -e PYTHONPATH=/app api python /tmp/link.py

До появления `track_rights.contragent_id` правообладатель жил в каталоге
строкой. Новые импорты ссылку проставляют сами, а вот 244 тысячи строк,
залитых раньше, нужно связать один раз — этим и занят скрипт.

КАК ИЩЕТСЯ КАРТОЧКА: сперва точное совпадение имени с титлом, потом
совпадение после нормализации («Князева А.А. (ИП)» против «Князева А. А.
(ИП)» — разница в одном пробеле). Приблизительные совпадения — префикс,
опечатка — здесь НЕ используются: они годятся, чтобы спросить человека в
предпросмотре импорта, но не чтобы молча привязать деньги к чужой карточке.

--create-missing заводит карточку на имя, которому ничего не нашлось. Титл
берётся из каталога как есть, остальное пусто — карточка честно светится
неполной, пока её не дозаполнят. Без флага такие имена просто перечисляются
в итогах и остаются без ссылки.

Повторный запуск безопасен: скрипт каждый раз пересчитывает связь заново.
"""
import argparse
import sys
import uuid

from sqlalchemy import func, select, update

from app.db import SessionLocal
from app.models import Contragent, TrackRight
from app.nomenclature_import import normalize_owner


def main() -> int:
    parser = argparse.ArgumentParser(description="Привязка прав к карточкам контрагентов")
    parser.add_argument("--dry-run", action="store_true", help="только посчитать")
    parser.add_argument(
        "--create-missing",
        action="store_true",
        help="завести карточки на имена, которым ничего не нашлось",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        cards = db.execute(select(Contragent.title, Contragent.id)).all()
        by_title = {title: cid for title, cid in cards}
        by_norm: dict[str, uuid.UUID] = {}
        for title, cid in cards:
            by_norm.setdefault(normalize_owner(title), cid)

        owners = db.execute(
            select(TrackRight.owner, func.count()).group_by(TrackRight.owner)
        ).all()
        print(f"карточек: {len(cards)}, имён в каталоге: {len(owners)}")

        exact = normed = 0
        exact_rows = normed_rows = 0
        missing: list[tuple[str, int]] = []
        plan: dict[str, uuid.UUID] = {}

        for name, count in owners:
            card_id = by_title.get(name)
            if card_id is not None:
                exact += 1
                exact_rows += count
            else:
                card_id = by_norm.get(normalize_owner(name))
                if card_id is not None:
                    normed += 1
                    normed_rows += count
                    print(f"  по нормализации: {name} -> найдена карточка ({count} строк)")
            if card_id is None:
                missing.append((name, count))
                continue
            plan[name] = card_id

        created = 0
        if missing and args.create_missing and not args.dry_run:
            for name, _count in missing:
                card_id = uuid.uuid4()
                db.add(Contragent(id=card_id, title=name))
                plan[name] = card_id
                created += 1
            db.flush()

        updated_rows = 0
        if not args.dry_run:
            # По одному запросу на имя, а не по строке: имён семь сотен, строк
            # четверть миллиона.
            for name, card_id in plan.items():
                result = db.execute(
                    update(TrackRight)
                    .where(TrackRight.owner == name)
                    .values(contragent_id=card_id)
                )
                updated_rows += result.rowcount or 0
            db.commit()

        linked = db.scalar(
            select(func.count())
            .select_from(TrackRight)
            .where(TrackRight.contragent_id.is_not(None))
        )
        total = db.scalar(select(func.count()).select_from(TrackRight))

        print()
        print("=== Результат ===")
        print(f"имён совпало точно     : {exact} ({exact_rows} строк)")
        print(f"имён по нормализации   : {normed} ({normed_rows} строк)")
        print(f"имён без карточки      : {len(missing)} ({sum(c for _, c in missing)} строк)")
        for name, count in sorted(missing, key=lambda x: -x[1])[:20]:
            print(f"    {name:<40} {count:>6} строк")
        if args.create_missing:
            print(f"заведено карточек      : {created}")
        print(f"строк обновлено        : {updated_rows}")
        print(f"со ссылкой в базе      : {linked} из {total}")
        if args.dry_run:
            print("(--dry-run: в базу ничего не записано)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
