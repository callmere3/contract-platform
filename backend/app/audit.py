"""
Запись в audit_log и generated_documents (этап 6/7, доступны на просмотр
Admin и Director).

Обе функции вызываются прямо из роутеров сразу после основного действия —
если сама запись в журнал не удастся, это не должно ронять запрос
пользователя (см. try/except внутри): лучше документ сгенерируется без
записи в историю, чем пользователь получит 500 из-за постороннего журнала.
"""
import logging
import uuid

from sqlalchemy.orm import Session

from app.models import AuditLog, GeneratedDocument, User
from app.request_context import in_http_request

logger = logging.getLogger("audit")

# Ключ и значение метки «запись сделана не человеком через интерфейс, а
# скриптом внутри контейнера» (E2E-прогон, отладка). Лежит в meta, а не в
# отдельной колонке: миграция ради служебного признака не нужна, а meta
# для этого и заведена (см. AuditLog в models.py). По этой метке
# list_audit_log прячет запись из журнала — см. routers_auth.py.
SOURCE_KEY = "via"
SOURCE_SCRIPT = "script"


def log_action(
    db: Session,
    user: User,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    meta: dict | None = None,
) -> None:
    """
    Запись в журнал действий.

    Действия, выполненные не через HTTP (скрипты в контейнере: E2E-прогоны,
    ручная отладка), помечаются meta.via='script' и в журнале не
    показываются. Запись при этом ВСЁ РАВНО СОЗДАЁТСЯ — специально: если
    определение источника однажды собьётся, в худшем случае в журнале
    появится лишняя строка, а не бесследно исчезнет настоящая. Тихо
    потерянное действие — куда худшая беда для журнала, чем видимый лишний
    шум. Полная выдача остаётся доступной через ?include_script=true.
    """
    if not in_http_request():
        meta = dict(meta or {})
        meta[SOURCE_KEY] = SOURCE_SCRIPT

    try:
        db.add(
            AuditLog(
                user_id=user.id,
                user_username=user.username,
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id) if entity_id is not None else None,
                meta=meta,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Не удалось записать audit_log: action=%s", action)


def log_generation(
    db: Session,
    user: User,
    template_id: uuid.UUID,
    template_name: str,
    format: str,
    payload: dict,
    contragent_id: uuid.UUID | None = None,
    contragent_title: str | None = None,
    nickname: str | None = None,
) -> uuid.UUID | None:
    """
    Возвращает id созданной записи истории (или None, если записать не
    удалось) — нужен захвату предложений в карточку (см. app/suggestions.py:
    source_generation_id), чтобы связать предложение с конкретной генерацией.
    """
    try:
        doc = GeneratedDocument(
            user_id=user.id,
            user_username=user.username,
            template_id=template_id,
            template_name=template_name,
            contragent_id=contragent_id,
            contragent_title=contragent_title,
            nickname=nickname,
            format=format,
            payload=payload,
        )
        db.add(doc)
        db.commit()
        return doc.id
    except Exception:
        db.rollback()
        logger.exception("Не удалось записать generated_documents: template_id=%s", template_id)
        return None
