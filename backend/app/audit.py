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

logger = logging.getLogger("audit")


def log_action(
    db: Session,
    user: User,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    meta: dict | None = None,
) -> None:
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
) -> None:
    try:
        db.add(
            GeneratedDocument(
                user_id=user.id,
                user_username=user.username,
                template_id=template_id,
                template_name=template_name,
                contragent_id=contragent_id,
                contragent_title=contragent_title,
                format=format,
                payload=payload,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Не удалось записать generated_documents: template_id=%s", template_id)
