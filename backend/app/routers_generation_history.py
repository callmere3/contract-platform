"""
GET /generation-history — журнал сгенерированных документов (Admin, Director).

Отдельно от /audit-log: тот — общий технический журнал действий (кто что
создал/удалил/поменял), этот — бизнес-витрина именно по документам: какой
контрагент, какой шаблон, кто сгенерировал. Payload формы, нужный для
пересоздания документа (этап 2), сюда не отдаётся — только то, что нужно
для списка.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_session
from app.models import GeneratedDocument
from app.roles import CAN_VIEW_GENERATION_HISTORY

generation_history_router = APIRouter(prefix="/generation-history", tags=["generation-history"])


@generation_history_router.get(
    "", dependencies=[Depends(require_role(*CAN_VIEW_GENERATION_HISTORY))]
)
def list_generation_history(
    limit: int = Query(100, le=500),
    contragent_id: str | None = None,
    db: Session = Depends(get_session),
) -> list[dict]:
    query = db.query(GeneratedDocument)
    if contragent_id is not None:
        query = query.filter(GeneratedDocument.contragent_id == contragent_id)

    entries = query.order_by(GeneratedDocument.created_at.desc()).limit(limit).all()
    return [
        {
            "id": str(e.id),
            "user_username": e.user_username,
            "template_id": str(e.template_id) if e.template_id else None,
            "template_name": e.template_name,
            "contragent_id": str(e.contragent_id) if e.contragent_id else None,
            "contragent_title": e.contragent_title,
            "format": e.format,
            "created_at": e.created_at.isoformat(),
        }
        for e in entries
    ]
