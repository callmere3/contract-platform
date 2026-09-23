"""
Поступления от площадок (ML Finance → «Поступления»).

  GET    /payments          — строки за период (обычно за месяц)
  POST   /payments          — завести строку
  PATCH  /payments/{id}     — поправить одно или несколько полей
  DELETE /payments/{id}     — убрать строку

ЧТО ЭТО. Отчёт площадки говорит, что она насчитала; поступление — что реально
дошло до счёта: когда, сколько, по какому курсу и сколько из этого завели.
Одним платежом закрывают несколько отчётов, а курс и завод к отчёту отношения
не имеют вовсе, поэтому таблица своя.

ПРАВКА ПРЯМО В ТАБЛИЦЕ, в отличие от денежных операций контрагента, где её
нет вовсе. Причина в самой строке: «заведено» и «сумма фактического завода»
проставляются ПОЗЖЕ платежа, иногда через недели. Это не запись в книге, а
живой лист, который дозаполняют, — запрет правок сделал бы его бесполезным.

PATCH ПРИНИМАЕТ ТОЛЬКО ПЕРЕДАННЫЕ ПОЛЯ и отличает «не прислали» от «прислали
пусто»: в таблице любое поле можно очистить, и очистка — такое же осмысленное
действие, как ввод. Поэтому тело разбирается вручную, а не через модель с
умолчаниями.

ДЕНЬГИ — строками в JSON и Numeric в базе, как во всём ML Finance: float
превращает 1234.10 в 1234.0999999999999.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import get_current_user, require_role
from app.db import get_session
from app.models import Partner, PartnerPayment, PartnerReport, User
from app.roles import CAN_MANAGE_PAYMENTS, CAN_VIEW_PAYMENTS

payments_router = APIRouter(
    prefix="/payments",
    tags=["payments"],
    dependencies=[Depends(require_role(*CAN_VIEW_PAYMENTS))],
)

# Поля, которые можно править, и как их читать. Список ОДИН на создание и
# правку: разойдись они, и через форму завелось бы то, чего правкой не
# поправить.
MONEY_FIELDS = ("amount", "transfer_amount", "actual_amount")
# Ставки — курс и НДС: множители, а не деньги. Наружу уходят без хвоста
# нулей и в итогах не складываются.
RATE_FIELDS = ("rate", "vat_rate")
TEXT_FIELDS = ("description",)
MAX_DESCRIPTION = 2000


def _money(value) -> str | None:
    return None if value is None else f"{Decimal(value):.2f}"


def _rate(value) -> str | None:
    """Курс наружу — без хвоста нулей: «92.5», а не «92.500000»."""
    if value is None:
        return None
    text = format(Decimal(value).normalize(), "f")
    return text


def _parse_money(value, label: str) -> Decimal | None:
    """
    «10 000,50» → Decimal. Принимаем как напечатали: пробелы (в том числе
    неразрывные) и запятая — обычный способ набрать сумму.
    """
    text = str(value if value is not None else "").replace("\xa0", " ").strip()
    text = text.replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        raise HTTPException(400, f"{label}: «{value}» — это не число")


def _parse_date(value, label: str) -> date:
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise HTTPException(400, f"{label}: «{value}» — это не дата")


def _linked_reports(db: Session, payment_ids: list) -> dict:
    """Сколько отчётов привязано к каждому платежу — одним запросом."""
    if not payment_ids:
        return {}
    rows = db.execute(
        select(PartnerReport.payment_id, func.count())
        .where(PartnerReport.payment_id.in_(payment_ids))
        .group_by(PartnerReport.payment_id)
    ).all()
    return {payment_id: count for payment_id, count in rows}


def _difference(payment: PartnerPayment):
    """
    Завод минус фактический завод, либо None.

    None, а не ноль, когда хоть одного числа нет: строку заводят по дате из
    выписки и дозаполняют позже, и «расхождение 116 300» у ещё не сверенной
    строки — это шум, а не находка.
    """
    if payment.transfer_amount is None or payment.actual_amount is None:
        return None
    return _money(payment.transfer_amount - payment.actual_amount)


def _out(payment: PartnerPayment, partner_name: str | None, linked: int = 0) -> dict:
    return {
        "id": str(payment.id),
        "occurred_on": payment.occurred_on.isoformat(),
        "partner_id": str(payment.partner_id) if payment.partner_id else None,
        "partner": partner_name,
        "description": payment.description,
        "amount": _money(payment.amount),
        "rate": _rate(payment.rate),
        "vat_rate": _rate(payment.vat_rate),
        "transfer_amount": _money(payment.transfer_amount),
        "transferred": payment.transferred,
        "actual_amount": _money(payment.actual_amount),
        # РАСХОЖДЕНИЕ — то, ради чего таблицу и ведут: сколько собирались
        # завести против того, сколько насчитали отчёты. Считает СЕРВЕР, как и
        # итоги: в JSON суммы уходят строками, и складывать их на экране
        # нельзя. Пусто, пока не заполнены оба числа: разница с неизвестным —
        # не ноль и не «весь завод», а просто «ещё не с чем сверять».
        "difference": _difference(payment),
        # Сколько отчётов привязано. Пока хоть один есть, фактический завод
        # СЧИТАЕТСЯ по ним, и руками его править нельзя — ни на экране, ни
        # через API: правку всё равно затёрло бы при следующей привязке.
        "linked_reports": linked,
    }


def _apply(payment: PartnerPayment, body: dict, db: Session) -> list[str]:
    """
    Присланные поля — в строку. Возвращает имена того, что тронули: по ним
    пишется журнал, и по ним же видно, что правка вообще была.
    """
    touched = []
    if "occurred_on" in body:
        payment.occurred_on = _parse_date(body["occurred_on"], "Дата поступления")
        touched.append("occurred_on")
    if "partner_id" in body:
        raw = str(body["partner_id"] or "").strip()
        if raw:
            try:
                partner_id = uuid.UUID(raw)
            except ValueError:
                raise HTTPException(400, "Партнёр: это не идентификатор")
            if db.get(Partner, partner_id) is None:
                raise HTTPException(404, "Партнёр не найден")
            payment.partner_id = partner_id
        else:
            # Пусто — «ещё не разобрались, чей платёж», а не ошибка.
            payment.partner_id = None
        touched.append("partner_id")
    for name in TEXT_FIELDS:
        if name in body:
            text = str(body[name] or "").strip()
            if len(text) > MAX_DESCRIPTION:
                raise HTTPException(400, "Описание платежа слишком длинное")
            setattr(payment, name, text or None)
            touched.append(name)
    for name in MONEY_FIELDS:
        if name in body:
            setattr(payment, name, _parse_money(body[name], "Сумма"))
            touched.append(name)
    for name in RATE_FIELDS:
        if name in body:
            setattr(payment, name, _parse_money(body[name], "Ставка"))
            touched.append(name)
    if "transferred" in body:
        payment.transferred = bool(body["transferred"])
        touched.append("transferred")
    return touched


@payments_router.get("")
def list_payments(
    date_from: str | None = None,
    date_to: str | None = None,
    partner_id: uuid.UUID | None = None,
    db: Session = Depends(get_session),
) -> dict:
    """
    Строки за период — обычно за месяц, который открыт на экране.

    Период задаётся ДАТАМИ, а не «годом и месяцем»: квартал и месяц наверху
    экрана — это отбор по дате поступления, и отдельного поля периода у
    строки нет. Так же сделан фильтр у отчётов.

    Итоги считаются здесь же: складывать столбец глазами человек не должен, а
    считать деньги на фронте нельзя — там они строки (см. докстринг модуля).
    """
    query = select(PartnerPayment, Partner.name).join(
        Partner, Partner.id == PartnerPayment.partner_id, isouter=True
    )
    if date_from:
        query = query.where(PartnerPayment.occurred_on >= _parse_date(date_from, "Начало"))
    if date_to:
        query = query.where(PartnerPayment.occurred_on <= _parse_date(date_to, "Конец"))
    if partner_id is not None:
        query = query.where(PartnerPayment.partner_id == partner_id)

    rows = db.execute(
        query.order_by(PartnerPayment.occurred_on, PartnerPayment.created_at)
    ).all()
    linked = _linked_reports(db, [p.id for p, _ in rows])
    payments = [_out(p, name, linked.get(p.id, 0)) for p, name in rows]

    def total(field):
        return sum((getattr(p, field) or Decimal(0) for p, _ in rows), Decimal(0))

    return {
        "payments": payments,
        "totals": {
            "amount": _money(total("amount")),
            "transfer_amount": _money(total("transfer_amount")),
            "actual_amount": _money(total("actual_amount")),
            # Итог расхождений — только по СВЕРЕННЫМ строкам, где есть оба
            # числа. Иначе в сумму попал бы завод строк, которые ещё не с чем
            # сравнивать, и итог показывал бы расхождение там, где его нет.
            "difference": _money(sum(
                (p.transfer_amount - p.actual_amount
                 for p, _ in rows
                 if p.transfer_amount is not None and p.actual_amount is not None),
                Decimal(0),
            )),
            # Сколько строк ещё не заведено: столбец с галочками читается
            # глазами плохо, а вопрос «что осталось» задают каждый раз.
            "not_transferred": sum(1 for p, _ in rows if not p.transferred),
        },
    }


@payments_router.post("", dependencies=[Depends(require_role(*CAN_MANAGE_PAYMENTS))])
def create_payment(
    body: dict = Body(default_factory=dict),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Завести строку.

    ОБЯЗАТЕЛЬНА ТОЛЬКО ДАТА: строку начинают с выписки, а чей это платёж и на
    какую сумму, дозаполняют следом. Требовать всё сразу значило бы заставить
    человека держать пустую строку в голове, пока он ищет недостающее.
    """
    payment = PartnerPayment(
        id=uuid.uuid4(),
        occurred_on=_parse_date(
            body.get("occurred_on") or date.today().isoformat(), "Дата поступления"
        ),
        created_by=current_user.id,
        created_at=datetime.now(timezone.utc),
    )
    _apply(payment, {k: v for k, v in body.items() if k != "occurred_on"}, db)
    db.add(payment)
    db.commit()

    partner = db.get(Partner, payment.partner_id) if payment.partner_id else None
    log_action(
        db, current_user, "payment.create", entity_type="payment", entity_id=payment.id,
        meta={
            "date": payment.occurred_on.isoformat(),
            "partner": partner.name if partner else None,
            "amount": str(payment.amount or ""),
        },
    )
    db.commit()
    return {"payment": _out(payment, partner.name if partner else None)}


@payments_router.patch(
    "/{payment_id}", dependencies=[Depends(require_role(*CAN_MANAGE_PAYMENTS))]
)
def update_payment(
    payment_id: uuid.UUID,
    body: dict = Body(default_factory=dict),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Поправить строку: приходят только те поля, которые человек тронул."""
    payment = db.get(PartnerPayment, payment_id)
    if payment is None:
        raise HTTPException(404, "Поступление не найдено")

    if "actual_amount" in body and _linked_reports(db, [payment.id]).get(payment.id):
        raise HTTPException(
            409,
            "Сумма фактического завода посчитана по привязанным отчётам — "
            "поправить её можно, только отвязав отчёт.",
        )
    touched = _apply(payment, body, db)
    if not touched:
        raise HTTPException(400, "Нечего менять")
    db.commit()

    partner = db.get(Partner, payment.partner_id) if payment.partner_id else None
    log_action(
        db, current_user, "payment.update", entity_type="payment", entity_id=payment.id,
        # Поля поимённо: по журналу должно быть видно, что именно поправили —
        # дату платежа или галочку «заведено».
        meta={"fields": sorted(touched), "date": payment.occurred_on.isoformat()},
    )
    db.commit()
    return {
        "payment": _out(
            payment,
            partner.name if partner else None,
            _linked_reports(db, [payment.id]).get(payment.id, 0),
        )
    }


@payments_router.delete(
    "/{payment_id}", dependencies=[Depends(require_role(*CAN_MANAGE_PAYMENTS))]
)
def delete_payment(
    payment_id: uuid.UUID,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Убрать строку целиком."""
    payment = db.get(PartnerPayment, payment_id)
    if payment is None:
        raise HTTPException(404, "Поступление не найдено")
    partner = db.get(Partner, payment.partner_id) if payment.partner_id else None
    meta = {
        "date": payment.occurred_on.isoformat(),
        "partner": partner.name if partner else None,
        "amount": str(payment.amount or ""),
    }
    db.delete(payment)
    db.commit()
    log_action(
        db, current_user, "payment.delete", entity_type="payment",
        entity_id=payment_id, meta=meta,
    )
    db.commit()
    return {"deleted": str(payment_id)}
