"""
Генерация отчётов правообладателям (24.09.2026, просьба владельца: «как окно
генерации в Dista»). Расчёт и сборка файлов — в `app/royalty_reports.py`.

Два шага, как у загрузки отчётов: `preview` показывает, кому и сколько
насчитано (и какие отчёты площадок пропущены), `generate` отдаёт файлы. Один
правообладатель и один вид отчёта — это один .xlsx, иначе .zip.
"""
import uuid
from datetime import date

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
    Settings,
    build_files,
    cents,
    compute,
    pending_reports,
    period_slug,
    zip_files,
)
from app.routers_templates import _content_disposition

royalty_reports_router = APIRouter(
    prefix="/royalty-reports",
    tags=["royalty-reports"],
    dependencies=[Depends(require_role(*CAN_GENERATE_ROYALTY_REPORTS))],
)

# Предел числа правообладателей в одной генерации: у каждого в файле могут
# быть десятки тысяч строк, а сервер один и памяти у него немного.
MAX_CONTRAGENTS = 300


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


def _settings(body: RoyaltyRequest) -> Settings:
    if body.period_to < body.period_from:
        raise HTTPException(400, "Конец периода раньше начала")
    if body.date_basis not in ("period", "uploaded"):
        raise HTTPException(400, "date_basis: «period» или «uploaded»")
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
        name = f"Отчеты правообладателям {period_slug(s)}.zip"
        content, media = zip_files(files), "application/zip"
    return Response(
        content, media_type=media,
        headers={"Content-Disposition": _content_disposition(name)},
    )
