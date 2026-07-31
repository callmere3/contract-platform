"""
/notifications — вкладка "Уведомления" (только admin, см. CAN_VIEW_NOTIFICATIONS).

Предложения дозаполнить/поправить карточку контрагента значениями, которые
менеджер вписал в форму генерации (заводятся автоматически, см.
app/suggestions.py: capture_suggestions). Админ применяет предложение к
карточке галочкой или отклоняет крестиком.

  GET  /notifications              — список видимых pending-предложений
  GET  /notifications/count        — счётчик для бейджа в шапке
  POST /notifications/{id}/apply   — применить к карточке (прямая запись колонки)
  POST /notifications/{id}/dismiss — отклонить (больше не всплывает)

Как показывать каждую запись — actionable (✓/✗) или просто ⚠-предупреждение —
решается ЗДЕСЬ, на момент показа, против ТЕКУЩЕГО состояния карточки, а не
замораживается при захвате: карточку могли дозаполнить другим путём между
генерацией и разбором. Логика в _classify:

  - поле карточки пусто, значение валидно      -> severity=suggestion (✓/✗)
  - поле пусто, значение кривое (формат/длина)  -> severity=warning ("проверьте
                                                   документ"), применить нельзя
  - поле заполнено, значение совпадает          -> скрываем (уже дозаполнено)
  - поле заполнено, значение расходится          -> severity=warning
                                                   ("расходится с карточкой"),
                                                   исправлять НЕ предлагаем

Применение пишет ОДНУ колонку напрямую и НЕ трогает title/номер (их пересчёта
нет вовсе, см. update_contragent) — для name это принципиально: имя правим,
подпись оставляем как в базе.
"""
import uuid
from datetime import date as _date, datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import get_current_user, require_role
from app.context_builder import parse_date
from app.db import get_session
from app.models import CardSuggestion, Contragent, User
from app.roles import CAN_VIEW_NOTIFICATIONS
from app.suggestions import current_value
from app.tags import normalize_reg_number

notifications_router = APIRouter(prefix="/notifications", tags=["notifications"])

FIELD_LABELS = {
    "reg_number": "Рег. номер",
    "royalty_percent": "Роялти, %",
    "name": "ФИО / название",
    "contract_number": "Номер договора",
    "contract_date": "Дата договора",
}


def _evaluate(field: str, value: str, contragent: Contragent, db: Session):
    """
    Проверяет значение под тип контрагента. Возвращает (ok, error, coerced):
    ok — валидно ли применять; error — текст для ⚠, если нет; coerced — то,
    что реально писать в колонку при применении (нормализованный вид).
    """
    if field in ("name", "contract_number"):
        return (True, None, value)  # свободный текст — любое непустое годится
    if field == "reg_number":
        try:
            norm = normalize_reg_number(value, contragent.type)
        except HTTPException as e:
            return (False, str(e.detail), None)
        if not norm:
            return (False, "пустой рег. номер", None)
        conflict = (
            db.query(Contragent.title)
            .filter(Contragent.reg_number == norm, Contragent.id != contragent.id)
            .first()
        )
        if conflict:
            return (False, f"уже у контрагента «{conflict[0]}»", None)
        return (True, None, norm)
    if field == "royalty_percent":
        try:
            d = Decimal(str(value).replace(",", "."))
        except (InvalidOperation, ValueError):
            return (False, "не число", None)
        if not (0 <= d <= 100):
            return (False, "должно быть от 0 до 100", None)
        return (True, None, d)
    if field == "contract_date":
        parsed = parse_date(value)
        if not parsed:
            return (False, "не распознать дату", None)
        day, month, year_full = parsed
        try:
            return (True, None, _date(int(year_full), int(month), int(day)))
        except ValueError:
            return (False, "некорректная дата", None)
    return (False, "неизвестное поле", None)


def _display(field: str, value: str | None) -> str | None:
    """Человекочитаемый вид значения: дату ISO -> ДД.ММ.ГГГГ, остальное как есть."""
    if value and field == "contract_date":
        try:
            y, m, d = value.split("-")
            return f"{d}.{m}.{y}"
        except ValueError:
            return value
    return value


def _visible_pending(db: Session) -> list[dict]:
    """
    Видимые во вкладке pending-предложения: скрываем те, что карточка уже
    удовлетворила тем же значением (см. докстринг модуля). Общая сборка для
    списка и счётчика — предложений мало, второй проход не дорог.
    """
    rows = (
        db.query(CardSuggestion, Contragent, User.full_name)
        .join(Contragent, Contragent.id == CardSuggestion.contragent_id)
        .outerjoin(User, User.id == CardSuggestion.suggested_by)
        .filter(CardSuggestion.status == "pending")
        .order_by(CardSuggestion.created_at.desc())
        .all()
    )
    items: list[dict] = []
    for s, c, full_name in rows:
        current = current_value(s.field, c)
        if not current:
            ok, error, _ = _evaluate(s.field, s.value, c, db)
            severity, reason = ("suggestion", None) if ok else ("warning", error)
        elif current == s.value:
            continue  # карточку уже дозаполнили тем же значением — скрываем
        else:
            severity, reason = "warning", "расходится с карточкой"
        items.append(
            {
                "id": str(s.id),
                "contragent_id": str(s.contragent_id),
                "contragent_title": c.title,
                "field": s.field,
                "field_label": FIELD_LABELS.get(s.field, s.field),
                "value": s.value,
                "value_display": _display(s.field, s.value),
                "severity": severity,
                "reason": reason,
                "card_current_display": _display(s.field, current) if current else None,
                "suggested_by": full_name or s.suggested_by_username,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
        )
    return items


@notifications_router.get("", dependencies=[Depends(require_role(*CAN_VIEW_NOTIFICATIONS))])
def list_notifications(db: Session = Depends(get_session)) -> list[dict]:
    return _visible_pending(db)


@notifications_router.get(
    "/count", dependencies=[Depends(require_role(*CAN_VIEW_NOTIFICATIONS))]
)
def notifications_count(db: Session = Depends(get_session)) -> dict:
    """Счётчик для бейджа: всего видимых pending и из них actionable (✓/✗)."""
    items = _visible_pending(db)
    return {
        "pending": len(items),
        "actionable": sum(1 for i in items if i["severity"] == "suggestion"),
    }


def _load_pending(suggestion_id: uuid.UUID, db: Session) -> CardSuggestion:
    s = db.get(CardSuggestion, suggestion_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Предложение не найдено")
    if s.status != "pending":
        raise HTTPException(status_code=400, detail="Предложение уже обработано")
    return s


@notifications_router.post(
    "/{suggestion_id}/apply", dependencies=[Depends(require_role(*CAN_VIEW_NOTIFICATIONS))]
)
def apply_notification(
    suggestion_id: uuid.UUID,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Применяет предложение к карточке: пишет ОДНУ колонку напрямую (title/номер
    не трогаются — их пересчёта нет). Применять можно только когда поле карточки
    сейчас ПУСТО и значение проходит проверку — иначе это расхождение, а его
    исправлять не предлагаем (409/400).
    """
    s = _load_pending(suggestion_id, db)
    c = db.get(Contragent, s.contragent_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Контрагент не найден")

    now = datetime.now(timezone.utc)
    current = current_value(s.field, c)
    if current:
        if current == s.value:
            # карточку уже дозаполнили тем же значением — считаем применённым
            s.status, s.resolved_by, s.resolved_at = "applied", current_user.id, now
            db.commit()
            return {"status": "applied", "already": True}
        raise HTTPException(
            status_code=409,
            detail="Поле карточки уже заполнено другим значением — это расхождение, применять нельзя",
        )

    ok, error, coerced = _evaluate(s.field, s.value, c, db)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Значение не проходит проверку: {error}")

    setattr(c, s.field, coerced)  # имя колонки == s.field (см. CardSuggestion.field)
    s.status, s.resolved_by, s.resolved_at = "applied", current_user.id, now
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Рег. номер уже занят другим контрагентом")

    log_action(
        db, current_user, "contragent.suggestion_apply",
        entity_type="contragent", entity_id=c.id,
        meta={"field": s.field, "value": s.value},
    )
    return {"status": "applied"}


@notifications_router.post(
    "/{suggestion_id}/dismiss", dependencies=[Depends(require_role(*CAN_VIEW_NOTIFICATIONS))]
)
def dismiss_notification(
    suggestion_id: uuid.UUID,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    s = _load_pending(suggestion_id, db)
    s.status, s.resolved_by, s.resolved_at = "dismissed", current_user.id, datetime.now(timezone.utc)
    db.commit()
    return {"status": "dismissed"}
