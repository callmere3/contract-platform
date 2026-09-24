"""
Генерация отчётов правообладателям (24.09.2026, просьба владельца: «как окно
генерации в Dista»). Расчёт и сборка файлов — в `app/royalty_reports.py`.

Два шага, как у загрузки отчётов: `preview` показывает, кому и сколько
насчитано (и какие отчёты площадок пропущены), `generate` отдаёт файлы. Один
правообладатель и один вид отчёта — это один .xlsx, иначе .zip.
"""
import threading
import time
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import get_current_user, require_role
from app.db import get_session
from app.models import User
from app.roles import CAN_GENERATE_ROYALTY_REPORTS
from app.royalty_reports import (
    SUMMARY_BY,
    SUMMARY_COLUMNS,
    Settings,
    build_files,
    cents,
    compute,
    pending_reports,
    unlinked_reports,
    summary,
    summary_file_name,
    summary_totals,
    summary_table_xlsx,
    zip_files,
    zip_name,
)
from app.routers_templates import _content_disposition

royalty_reports_router = APIRouter(
    prefix="/royalty-reports",
    tags=["royalty-reports"],
    dependencies=[Depends(require_role(*CAN_GENERATE_ROYALTY_REPORTS))],
)

# Предел числа правообладателей в одной генерации — защита от «все за три
# года», а не норматив. Замер на проде (II кв. 2026): 579 правообладателей,
# 158 тыс. строк детализации, расчёт 21 с при пике памяти 461 МБ; самые
# крупные файлы собираются за секунды. Квартал целиком в предел влезает.
MAX_CONTRAGENTS = 1000


class RoyaltyRequest(BaseModel):
    period_from: date
    period_to: date
    date_basis: str = "period"
    # Пустой список — «все»: у правообладателей это те, кому есть что начислить.
    contragent_ids: list[uuid.UUID] = []
    partner_ids: list[uuid.UUID] = []
    track_ids: list[uuid.UUID] = []
    group_detail: bool = True
    kinds: list[str] = ["summary", "detailed"]
    # Для сводных отчётов: по чему сводка — holder, track или partner.
    by: str = "holder"
    # Построенная сводка, которую выгружаем (см. _snapshots).
    snapshot: str | None = None


def _settings(body: RoyaltyRequest) -> Settings:
    if body.period_to < body.period_from:
        raise HTTPException(400, "Конец периода раньше начала")
    if body.date_basis not in ("period", "report"):
        raise HTTPException(400, "date_basis: «period» или «report»")
    return Settings(
        period_from=body.period_from,
        period_to=body.period_to,
        date_basis=body.date_basis,
        contragent_ids=list(body.contragent_ids) or None,
        partner_ids=list(body.partner_ids) or None,
        track_ids=list(body.track_ids) or None,
        group_detail=body.group_detail,
    )


def _money(value) -> str:
    return f"{cents(value):.2f}"


@royalty_reports_router.post("/preview")
def preview(body: RoyaltyRequest, db: Session = Depends(get_session)) -> dict:
    """Кому и сколько насчитано — без файлов."""
    s = _settings(body)
    results = compute(db, s)
    return {
        "contragents": [
            {
                "id": r.contragent_id,
                "title": r.title,
                "tracks": r.tracks,
                "lines": len(r.lines),
                "quantity": _money(r.quantity),
                "realization": _money(r.realization),
                "reward_author": _money(r.reward_author),
                "reward_related": _money(r.reward_related),
                "reward": _money(r.reward),
            }
            for r in results
        ],
        "totals": {
            "contragents": len(results),
            "quantity": _money(sum((r.quantity for r in results), 0)),
            "realization": _money(sum((r.realization for r in results), 0)),
            "reward": _money(sum((r.reward for r in results), 0)),
        },
        # Валютные отчёты без курса: в расчёт не вошли, и человек должен это
        # видеть ДО того, как отправит отчёт правообладателю.
        "skipped_reports": pending_reports(db, s),
        # Отчёты без поступления: в ведомость по дате реализации не попали.
        "unlinked_reports": unlinked_reports(db, s),
    }


@royalty_reports_router.post("/generate")
def generate(
    body: RoyaltyRequest,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Файлы отчётов: один .xlsx или .zip со всеми."""
    s = _settings(body)
    kinds = [k for k in body.kinds if k in ("summary", "detailed")]
    if not kinds:
        raise HTTPException(400, "Выберите вид отчёта: сводный или детализированный")
    results = compute(db, s)
    if not results:
        raise HTTPException(404, "За этот период начислений нет — формировать нечего")
    if len(results) > MAX_CONTRAGENTS:
        raise HTTPException(
            400,
            f"Правообладателей {len(results)} — это больше {MAX_CONTRAGENTS} за раз. "
            "Выберите часть из них.",
        )
    files = build_files(results, s, kinds)
    log_action(
        db, current_user, "royalty_report.generate", entity_type="royalty_report",
        meta={
            "period": [s.period_from.isoformat(), s.period_to.isoformat()],
            "date_basis": s.date_basis,
            "contragents": [r.title for r in results][:50],
            "count": len(results),
            "kinds": kinds,
            "reward": _money(sum((r.reward for r in results), 0)),
        },
    )
    db.commit()
    if len(files) == 1:
        name, content = files[0]
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        name = zip_name(s, results)
        content, media = zip_files(files), "application/zip"
    return Response(
        content, media_type=media,
        headers={"Content-Disposition": _content_disposition(name)},
    )


def _summary_by(body: RoyaltyRequest) -> str:
    if body.by not in SUMMARY_BY:
        raise HTTPException(400, "by: holder, track или partner")
    return body.by


def _cell(value):
    """Число наружу — строкой (как деньги во всём ML Finance), остальное как есть."""
    return f"{cents(value):.2f}" if isinstance(value, Decimal) else value


# ПОСТРОЕННАЯ СВОДКА ЗАПОМИНАЕТСЯ, И ВЫГРУЗКА БЕРЁТ ЕЁ, А НЕ СЧИТАЕТ ЗАНОВО
# (вопрос владельца 24.09.2026). Расчёт по всем правообладателям квартала —
# около 25 секунд, и платить их дважды за «посмотреть» и «выгрузить» незачем.
# К тому же выгружается ровно то, что было на экране: если между кнопками
# кто-то загрузит отчёт, файл не разойдётся с увиденным.
#
# Снимок привязан к НАСТРОЙКАМ: выгрузка с другими настройками снимок не
# возьмёт и посчитает заново. Живёт полчаса, держим несколько последних.
SNAPSHOT_TTL = 1800
SNAPSHOT_KEEP = 5
SUMMARY_SHOWN = 10
_snapshots: dict = {}
_snapshots_lock = threading.Lock()


def _settings_key(body: RoyaltyRequest) -> str:
    data = body.model_dump(exclude={"snapshot", "kinds", "group_detail"}, mode="json")
    for k in ("contragent_ids", "partner_ids", "track_ids"):
        data[k] = sorted(data[k])
    return repr(sorted(data.items()))


def _remember(body: RoyaltyRequest, rows: list) -> str:
    token = uuid.uuid4().hex
    now = time.monotonic()
    with _snapshots_lock:
        for k in [k for k, v in _snapshots.items() if now - v[0] > SNAPSHOT_TTL]:
            _snapshots.pop(k, None)
        _snapshots[token] = (now, _settings_key(body), rows)
        for k in sorted(_snapshots, key=lambda k: _snapshots[k][0])[:-SNAPSHOT_KEEP]:
            _snapshots.pop(k, None)
    return token


def _recall(body: RoyaltyRequest) -> list | None:
    if not body.snapshot:
        return None
    with _snapshots_lock:
        found = _snapshots.get(body.snapshot)
    if found is None or time.monotonic() - found[0] > SNAPSHOT_TTL:
        return None
    return found[2] if found[1] == _settings_key(body) else None


@royalty_reports_router.post("/summary")
def summary_view(body: RoyaltyRequest, db: Session = Depends(get_session)) -> dict:
    """
    Сводный отчёт на экран: по правообладателю, объекту или площадке
    (24.09.2026). На экран — ТОП-10 по вознаграждению и итог по всем
    строкам (просьба владельца): остальное — в файле. Вся сводка
    запоминается, и выгрузка берёт её по `snapshot`.
    """
    s = _settings(body)
    by = _summary_by(body)
    rows = summary(db, s, by)
    return {
        "by": by,
        "snapshot": _remember(body, rows),
        "columns": [{"field": f, "title": t, "money": m} for f, t, m in SUMMARY_COLUMNS[by]],
        "rows": [{k: _cell(v) for k, v in r.items()} for r in rows[:SUMMARY_SHOWN]],
        "total_rows": len(rows),
        "totals": {k: _cell(v) for k, v in summary_totals(rows, by).items()},
        "skipped_reports": pending_reports(db, s),
        "unlinked_reports": unlinked_reports(db, s),
    }


@royalty_reports_router.post("/summary/export")
def summary_export(
    body: RoyaltyRequest,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Сводка файлом .xlsx — построенная, если она есть, иначе считается заново."""
    s = _settings(body)
    by = _summary_by(body)
    rows = _recall(body)
    from_snapshot = rows is not None
    if rows is None:
        rows = summary(db, s, by)
    if not rows:
        raise HTTPException(404, "За этот период строк нет — выгружать нечего")
    log_action(
        db, current_user, "royalty_report.summary", entity_type="royalty_report",
        meta={"by": by, "period": [s.period_from.isoformat(), s.period_to.isoformat()],
              "rows": len(rows), "from_snapshot": from_snapshot},
    )
    db.commit()
    return Response(
        summary_table_xlsx(rows, s, by),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": _content_disposition(summary_file_name(s, by))},
    )
