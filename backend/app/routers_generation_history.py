"""
/generation-history — журнал сгенерированных документов.

Admin/Director видят всё; Top-manager — только СВОИ документы (ограничение
серверное, по user_id, см. SEES_ALL_GENERATION_HISTORY).

  GET  /generation-history               — список (см. list_generation_history);
                                             ?filter_type=contragent|nickname|user
                                             + ?filter_value=... — единый фильтр
  GET  /generation-history/{id}           — одна запись + payload формы (для
                                             "Открыть форму": предзаполнить форму
                                             генерации данными из истории)
  GET  /generation-history/{id}/recreate  — воссоздать документ по сохранённому
                                             payload (?format=docx|pdf, этап 2)

Отдельно от /audit-log: тот — общий технический журнал действий (кто что
создал/удалил/поменял), этот — бизнес-витрина именно по документам: какой
контрагент, какой шаблон, кто сгенерировал.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role
from app.db import get_session
from app.models import GeneratedDocument, Template, User
from app.roles import CAN_VIEW_GENERATION_HISTORY, SEES_ALL_GENERATION_HISTORY
from app.routers_templates import build_document_response

generation_history_router = APIRouter(prefix="/generation-history", tags=["generation-history"])


# Единый фильтр вместо трёх отдельных полей: сначала выбирается ТИП
# (по какой колонке искать), затем вводится значение — один filter_type
# + filter_value вместо contragent_id/nickname/user_username по отдельности.
FILTER_COLUMNS = {
    "contragent": GeneratedDocument.contragent_title,
    "nickname": GeneratedDocument.nickname,
    "user": GeneratedDocument.user_username,
}


@generation_history_router.get(
    "", dependencies=[Depends(require_role(*CAN_VIEW_GENERATION_HISTORY))]
)
def list_generation_history(
    limit: int = Query(100, le=500),
    filter_type: str | None = Query(None, pattern="^(contragent|nickname|user)$"),
    filter_value: str | None = Query(None),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    # Джойним пользователя, чтобы показать его ИМЯ (full_name), а не логин.
    # outerjoin: если пользователь удалён (user_id стал NULL), запись всё
    # равно остаётся — имя тогда берём из снимка логина (user_username).
    query = db.query(GeneratedDocument, User.full_name).outerjoin(
        User, User.id == GeneratedDocument.user_id
    )
    # Top-manager видит только свои документы. Ограничение ЗДЕСЬ, а не только
    # в UI: иначе через filter_type=user он бы увидел чужие.
    if current_user.role not in SEES_ALL_GENERATION_HISTORY:
        query = query.filter(GeneratedDocument.user_id == current_user.id)
    if filter_type is not None and filter_value:
        like = f"%{filter_value}%"
        if filter_type == "user":
            # Ищем по тому, что видно в списке (имени), но и по логину —
            # на случай удалённого пользователя, у которого остался только он.
            query = query.filter(
                or_(User.full_name.ilike(like), GeneratedDocument.user_username.ilike(like))
            )
        else:
            column = FILTER_COLUMNS[filter_type]
            query = query.filter(column.ilike(like))

    rows = query.order_by(GeneratedDocument.created_at.desc()).limit(limit).all()
    return [
        {
            "id": str(e.id),
            # Имя пользователя; если пусто/пользователь удалён — логин-снимок.
            "user_display": full_name or e.user_username,
            "user_username": e.user_username,
            "template_id": str(e.template_id) if e.template_id else None,
            "template_name": e.template_name,
            "contragent_id": str(e.contragent_id) if e.contragent_id else None,
            "contragent_title": e.contragent_title,
            "nickname": e.nickname,
            "format": e.format,
            "created_at": e.created_at.isoformat(),
        }
        for e, full_name in rows
    ]


@generation_history_router.get(
    "/{entry_id}", dependencies=[Depends(require_role(*CAN_VIEW_GENERATION_HISTORY))]
)
def get_generation_entry(
    entry_id: uuid.UUID,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Одна запись истории вместе с payload формы — чтобы открыть форму
    генерации соответствующего шаблона и предзаполнить её этими данными
    ("Открыть форму" в истории). В списке payload не отдаётся (он большой и
    нужен не всегда), поэтому забираем его точечно по клику.

    Top-manager — только свою запись (как и везде, см.
    SEES_ALL_GENERATION_HISTORY); чужая для него 404.
    """
    entry = db.get(GeneratedDocument, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Запись в истории не найдена")
    if (
        current_user.role not in SEES_ALL_GENERATION_HISTORY
        and entry.user_id != current_user.id
    ):
        raise HTTPException(status_code=404, detail="Запись в истории не найдена")
    if entry.template_id is None:
        # Шаблон удалён (ondelete=SET NULL) — открывать форму нечем.
        raise HTTPException(
            status_code=404,
            detail="Шаблон, по которому создавался документ, был удалён — открыть форму нечем",
        )

    return {
        "id": str(entry.id),
        "template_id": str(entry.template_id),
        "contragent_id": str(entry.contragent_id) if entry.contragent_id else None,
        "payload": entry.payload,
    }


@generation_history_router.get(
    "/{entry_id}/recreate", dependencies=[Depends(require_role(*CAN_VIEW_GENERATION_HISTORY))]
)
def recreate_generated_document(
    entry_id: uuid.UUID,
    format: str = Query("docx", pattern="^(docx|pdf)$"),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
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

    # Top-manager может пересоздать только СВОЙ документ. 404 (а не 403) —
    # чужая запись для него "не существует", как и в списке.
    if (
        current_user.role not in SEES_ALL_GENERATION_HISTORY
        and entry.user_id != current_user.id
    ):
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

    # contragent_title — снимок на момент генерации, а не текущий титл
    # карточки: имя файла должно совпадать с тем, что скачали тогда, даже
    # если карточку с тех пор переименовали или удалили (тогда titl остался
    # только здесь, contragent_id обнулился по ondelete=SET NULL).
    return build_document_response(template, entry.payload, format, entry.contragent_title)
