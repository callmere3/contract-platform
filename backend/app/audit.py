"""
Запись в audit_log (этап 6, доступен на просмотр Admin и Director).

log_action() вызывается прямо из роутеров сразу после db.commit() основного
действия — если сам audit_log не запишется, это не должно ронять запрос
пользователя (см. try/except внутри): лучше документ сгенерируется без
записи в лог, чем пользователь получит 500 из-за постороннего журнала.
"""
import logging

from sqlalchemy.orm import Session

from app.models import AuditLog, User

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
