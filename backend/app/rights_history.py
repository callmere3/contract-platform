"""
История прав на трек: прежние составы и выбор состава для расчёта
(26.09.2026, решение владельца после разбора базы Dista).

Текущий состав живёт в `track_rights` и действует с `tracks.rights_since`;
прежние — в `track_right_history` со сроком [valid_from, valid_to). Здесь
две вещи, и обе нужны в нескольких местах, поэтому они не в роутерах:

- `archive_superseded` — перед тем как импорт или правка карточки ЗАМЕСТИТ
  состав, прежний уходит в историю. Зовут его все три пути записи прав:
  импорт из интерфейса, `ops/import_tracks.py` и правка карточки. Разойдись
  они — история писалась бы через раз.
- `RightsTimeline` — какой состав брать для строки отчёта площадки.
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.models import Track, TrackRight, TrackRightHistory

CENT = Decimal("0.01")
# PostgreSQL принимает не больше 65 535 параметров в запросе, а треков в
# квартале с архивом Dista — 86 тысяч: списки id режем пачками.
ID_BATCH = 10000


def chunks(ids, size: int = ID_BATCH):
    ids = list(ids)
    for i in range(0, len(ids), size):
        yield ids[i:i + size]


def _num(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(CENT)


def _composition(rows) -> frozenset:
    """Состав прав как множество — порядок мест смысла не несёт."""
    return frozenset(
        (r["right_type"], (r["owner"] or "").strip().casefold(), _num(r["share"]), _num(r["royalty"]))
        for r in rows
    )


def archive_superseded(db: Session, incoming: dict, source: str) -> int:
    """
    Перед заменой прав: прежний состав трека — в историю.

    `incoming` — {track_id: (новая дата прав, [новые права как словари с
    right_type, owner, share, royalty])}. Уходит в историю, только если
    ДАТА ПРАВ СДВИНУЛАСЬ ВПЕРЁД И СОСТАВ ПОМЕНЯЛСЯ:

    - та же дата — это правка того же состава (опечатка в доле), а не новая
      версия: историю им засорять незачем, и расчёт прошлого периода должен
      взять исправленное;
    - дата назад или пустая — версией это не назвать, заменяем как раньше;
    - состав тот же, а дата новая — Dista переставила дату, деньги от этого
      не меняются.

    Возвращает, сколько треков ушло в историю. Писать ДО удаления прав.
    """
    ids = [tid for tid in incoming if tid is not None]
    if not ids:
        return 0
    since = dict(db.execute(select(Track.id, Track.rights_since).where(Track.id.in_(ids))).all())
    current: dict = {}
    for r in db.scalars(select(TrackRight).where(TrackRight.track_id.in_(ids))):
        current.setdefault(r.track_id, []).append(r)

    rows = []
    moved = 0
    for tid, (new_since, new_rights) in incoming.items():
        old_since = since.get(tid)
        was = current.get(tid)
        if not was or old_since is None or new_since is None or new_since <= old_since:
            continue
        old = [
            {"right_type": r.right_type, "owner": r.owner, "share": r.share, "royalty": r.royalty}
            for r in was
        ]
        if _composition(old) == _composition(new_rights):
            continue
        moved += 1
        for r in was:
            rows.append({
                "id": uuid.uuid4(), "track_id": tid,
                "valid_from": old_since, "valid_to": new_since,
                "right_type": r.right_type, "slot": r.slot, "owner": r.owner,
                "contragent_id": r.contragent_id, "share": r.share, "royalty": r.royalty,
                "source": source,
            })
    if rows:
        db.execute(insert(TrackRightHistory), rows)
    return moved


class RightsTimeline:
    """
    Какой состав прав действовал на дату — для расчёта ведомостей.

    ПРАВИЛО — СОСТАВ НА КОНЕЦ ПЕРИОДА ОТЧЁТА ПЛОЩАДКИ (так считала Dista,
    проверено по её начислениям). Текущий действует с `rights_since`; раньше
    — версия из истории, чей срок накрывает дату. Дата раньше всех версий —
    самая ранняя версия (у Dista так же: состав «с 01.01.2000» и есть
    «всегда»). У трека без истории — всегда текущий, и это почти все треки.

    Держит доли и ставки ПО ВЕРСИЯМ для нужных пар (трек, правообладатель);
    ключ версии — `None` у текущей и `valid_from` у прежних.
    """

    def __init__(self, db: Session, track_ids, contragent_ids, since: dict):
        self.since = since
        self.versions: dict = {}   # track_id -> [(valid_from, valid_to)] по возрастанию
        self.shares: dict = {}     # (track_id, contragent_id, version) -> {type: [share, royalty]}

        contragent_ids = set(contragent_ids)
        spans: dict = {}
        for batch in chunks(track_ids):
            for tid, cid, rtype, share, royalty in db.execute(
                select(TrackRight.track_id, TrackRight.contragent_id, TrackRight.right_type,
                       TrackRight.share, TrackRight.royalty)
                .where(TrackRight.track_id.in_(batch), TrackRight.contragent_id.isnot(None))
                .order_by(TrackRight.slot)
            ):
                if cid in contragent_ids:
                    self._add((tid, cid, None), rtype, share, royalty)

            for tid, vfrom, vto, cid, rtype, share, royalty in db.execute(
                select(TrackRightHistory.track_id, TrackRightHistory.valid_from,
                       TrackRightHistory.valid_to, TrackRightHistory.contragent_id,
                       TrackRightHistory.right_type, TrackRightHistory.share,
                       TrackRightHistory.royalty)
                .where(TrackRightHistory.track_id.in_(batch))
                .order_by(TrackRightHistory.slot)
            ):
                # Сроки версий — по ВСЕМ правообладателям трека: какая версия
                # действовала, не зависит от того, чья доля нас интересует.
                spans.setdefault(tid, set()).add((vfrom, vto))
                if cid in contragent_ids:
                    self._add((tid, cid, vfrom), rtype, share, royalty)
        for tid, s in spans.items():
            self.versions[tid] = sorted(s)

    def _add(self, key, rtype, share, royalty):
        # Несколько мест одного человека на одно право (бывает при слиянии
        # дублей): доли складываются, ставка берётся первая.
        slot = self.shares.setdefault(key, {}).setdefault(rtype, [Decimal(0), None])
        slot[0] += Decimal(share or 0)
        if slot[1] is None and royalty is not None:
            slot[1] = Decimal(royalty)

    def version(self, track_id, on: date | None):
        spans = self.versions.get(track_id)
        if not spans or on is None:
            return None
        start = self.since.get(track_id)
        if start is None or on >= start:
            return None
        for vfrom, vto in reversed(spans):
            if vfrom <= on < vto:
                return vfrom
        # Дата в дыре между версиями — последняя начавшаяся; раньше всех —
        # самая ранняя.
        started = [vfrom for vfrom, _ in spans if vfrom <= on]
        return started[-1] if started else spans[0][0]

    def rights(self, track_id, contragent_id, on: date | None) -> dict:
        return self.shares.get((track_id, contragent_id, self.version(track_id, on)), {})
