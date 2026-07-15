"""
/generation-history — журнал сгенерированных документов (Admin, Director).

  GET  /generation-history               — список (см. list_generation_history)
  GET  /generation-history/{id}/recreate  — воссоздать документ по сохранённому
                                             payload (?format=docx|pdf, этап 2)

Отдельно от /audit-log: тот — общий технический журнал действий (кто что
создал/удалил/поменял), этот — бизнес-витрина именно по документам: какой
контрагент, какой шаблон, кто сгенерировал.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_session
from app.models import GeneratedDocument, Template
from app.roles import CAN_VIEW_GENERATION_HISTORY
from app.routers_templates import build_document_response

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


@generation_history_router.get(
    "/{entry_id}/recreate", dependencies=[Depends(require_role(*CAN_VIEW_GENERATION_HISTORY))]
)
def recreate_generated_document(
    entry_id: uuid.UUID,
    format: str = Query("docx", pattern="^(docx|pdf)$"),
    db: Session = Depends(get_session),
) -> StreamingResponse:
    """
    Воссоздаёт документ на лету по сохранённому payload формы — файл нигде
    не хранился, поэтому это ровно такой же рендер, каким был оригинал, но
    выполненный сейчас (см. build_document_response в routers_templates.py).

    Если шаблон с тех пор удалили (template_id стал NULL по ondelete=SET
    NULL) или перезалили другим файлом — пересоздать нечем/результат будет
    отличаться от оригинала. Это осознанный компромисс, см. докстринг
    GeneratedDocument в app/models.py: хранить сам файл шаблона на каждую
    генерацию было бы избыточно.
    """
    entry = db.get(GeneratedDocument, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Запись в истории не найдена")

    if entry.template_id is None:
        raise HTTPException(
            status_code=404,
            detail="Шаблон, по которому создавался документ, был удалён — пересоздать нечем",
        )

    template = db.get(Template, entry.template_id)
    if template is None:
        raise HTTPException(
            status_code=404,
            detail="Шаблон, по которому создавался документ, был удалён — пересоздать нечем",
        )

    return build_document_response(template, entry.payload, format)
