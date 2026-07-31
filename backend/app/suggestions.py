"""
Захват предложений дозаполнить карточку контрагента (вкладка "Уведомления").

Вызывается из generate_document сразу после log_generation: смотрит, какие
поля формы связаны с карточкой (maps_to='contragent.*' + дата договора), и
если менеджер вписал значение, отличное от того, что сейчас в карточке —
кладёт pending-запись в card_suggestions. Дальше админ во вкладке
"Уведомления" применяет её к карточке или отклоняет (см. routers_notifications).

Как и audit.log_*, работает в своём try/except и НЕ должен ронять генерацию:
не записалось предложение — документ всё равно отдаётся пользователю.

ЧТО захватываем (см. CardSuggestion.field):
  reg_number, royalty_percent, name, contract_number  — по maps_to;
  contract_date                                        — по метке c_date
                                                         (у неё maps_to нет,
                                                         это встроенное поле
                                                         даты договора).
Никнейм НЕ захватываем (у контрагента их несколько — не "недостающее поле").
title/номер тоже не трогаем как источник — их меняет только импорт.

КОГДА: значение из формы непусто И отличается от текущего в карточке. Это
покрывает оба случая сразу — и "поле пустое, менеджер вписал" (карточку можно
дозаполнить), и "поле заполнено, но менеджер вписал ДРУГОЕ" (расхождение,
которое во вкладке подсветится как ⚠). Что из этого actionable, а что просто
предупреждение — решается на момент показа против текущей карточки, не здесь
(см. routers_notifications._visible_pending).

Валидность значения (правильная длина reg_number, число у роялти, парсится ли
дата) ЗДЕСЬ НЕ ПРОВЕРЯЕТСЯ намеренно: кривой ввод тоже надо показать админу
(⚠ "проверьте документ"), а не молча отбросить. Проверка — при показе.
"""
import logging
import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.models import CardSuggestion, Contragent, User

logger = logging.getLogger("suggestions")

# maps_to метки -> колонка карточки, которую она заполняет.
FIELD_BY_MAPS_TO = {
    "contragent.reg_number": "reg_number",
    "contragent.royalty_percent": "royalty_percent",
    "contragent.name": "name",
    "contragent.contract_number": "contract_number",
}
# Дата договора приходит не через maps_to, а фиксированной меткой c_date
# (см. routers_templates.get_template_fields) — обрабатывается по имени метки.
CONTRACT_DATE_PLACEHOLDER = "c_date"


def _royalty_canon(raw) -> str | None:
    """
    Каноничная форма процента для сравнения и хранения: '65.00' и 65 и '65,0'
    -> '65'; дробное сохраняем как есть ('65.5'). Нечисловое возвращаем как
    строку (не None!) — чтобы кривой ввод дошёл до вкладки и подсветился ⚠,
    а не потерялся. Пустое -> None (нечего предлагать).
    """
    s = str(raw).strip().replace(",", ".")
    if not s:
        return None
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        return s
    return str(int(d)) if d == d.to_integral_value() else str(d.normalize())


def _submitted_value(field: str, raw) -> str | None:
    """Значение из формы в каноничном для колонки виде; None — если пусто/непригодно."""
    if raw is None:
        return None
    if field == "royalty_percent":
        return _royalty_canon(raw)
    s = str(raw).strip()
    if not s or len(s) > 255:  # >255 не влезет в value String(255) — это заведомо мусор
        return None
    return s


def current_value(field: str, contragent: Contragent) -> str:
    """Текущее значение колонки карточки в том же каноничном виде ('' если пусто)."""
    if field == "reg_number":
        return contragent.reg_number or ""
    if field == "name":
        return contragent.name or ""
    if field == "contract_number":
        return contragent.contract_number or ""
    if field == "royalty_percent":
        return _royalty_canon(contragent.royalty_percent) or "" if contragent.royalty_percent is not None else ""
    if field == "contract_date":
        return contragent.contract_date.isoformat() if contragent.contract_date else ""
    return ""


def capture_suggestions(
    db: Session,
    user: User,
    contragent: Contragent,
    data: dict,
    fields: list[tuple[str, str]],
    source_generation_id: uuid.UUID | None,
) -> None:
    """
    fields — [(placeholder, maps_to), ...] меток шаблона. data — payload формы.
    """
    try:
        seen: set[tuple[str, str]] = set()
        for placeholder, maps_to in fields:
            field = FIELD_BY_MAPS_TO.get(maps_to)
            if field is None and placeholder == CONTRACT_DATE_PLACEHOLDER:
                field = "contract_date"
            if field is None:
                continue

            value = _submitted_value(field, data.get(placeholder))
            if value is None or value == current_value(field, contragent):
                continue

            key = (field, value)
            if key in seen:
                continue
            seen.add(key)

            # Дедуп по тройке (контрагент, поле, значение), учитывая И pending,
            # И dismissed: pending — второй менеджер вписал то же самое, не плодим;
            # dismissed — админ это значение уже отклонил, оно НЕ должно всплывать
            # снова (см. докстринг CardSuggestion). applied сюда не входит намеренно:
            # если применённое значение потом ушло из карточки, а менеджер вписал
            # его опять — предложить заново уместно (проверка value==current выше
            # такой случай не отсекает, т.к. в карточке уже другое значение).
            already = (
                db.query(CardSuggestion.id)
                .filter(
                    CardSuggestion.contragent_id == contragent.id,
                    CardSuggestion.field == field,
                    CardSuggestion.value == value,
                    CardSuggestion.status.in_(("pending", "dismissed")),
                )
                .first()
            )
            if already:
                continue

            db.add(
                CardSuggestion(
                    contragent_id=contragent.id,
                    field=field,
                    value=value,
                    suggested_by=user.id,
                    suggested_by_username=user.username,
                    source_generation_id=source_generation_id,
                    status="pending",
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Не удалось записать card_suggestions для contragent=%s", contragent.id)
