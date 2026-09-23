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

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import get_current_user, require_role
from app.db import get_session
from app.models import Partner, PartnerPayment, PartnerReport, User
from app.partner_names import PartnerIndex, clean_name
from app.payments_import import parse_rows
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
# Ставки — курс и НДС. Наружу уходят без хвоста нулей и в итогах не
# складываются: это не деньги. Разбираются РАЗНЫМИ функциями — курс это
# множитель, а НДС с 23.09.2026 проценты («22» — это 22%).
RATE_FIELDS = ("rate", "vat_rate")
TEXT_FIELDS = ("description",)
MAX_DESCRIPTION = 2000
# Предел на импорт: квартал — это семь десятков строк, тысячи означают,
# что выбрали не тот файл.
MAX_IMPORT_ROWS = 5000
# Что может стоять в «заведено». Пусто — тоже ответ: «ещё не заведено».
TRANSFER_STATUSES = ("да", "синхра")


def _money(value) -> str | None:
    return None if value is None else f"{Decimal(value):.2f}"


def _rate(value) -> str | None:
    """Курс наружу — без хвоста нулей: «92.5», а не «92.500000»."""
    if value is None:
        return None
    text = format(Decimal(value).normalize(), "f")
    return text


# Что отбрасываем в сумме перед разбором: человек копирует её из выписки или
# из письма площадки, а там сумма записана вместе со знаком валюты — «116
# 300,00 ₽». Стирать его руками в каждой ячейке (просьба владельца 23.09.2026)
# — ровно та работа, которую должна делать машина.
MONEY_NOISE = (" ", " ", " ", "₽", "руб.", "руб", "р.")


def _parse_money(value, label: str) -> Decimal | None:
    """
    «10 000,50 ₽» → Decimal. Принимаем как напечатали: пробелы (в том числе
    неразрывные), запятая и знак рубля — обычный способ записать сумму.
    """
    text = str(value if value is not None else "").strip().lower()
    for noise in MONEY_NOISE:
        text = text.replace(noise, "")
    text = text.replace(",", ".")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        raise HTTPException(400, f"{label}: «{value}» — это не число")


def _parse_percent(value) -> Decimal | None:
    """
    НДС — СТАВКА В ПРОЦЕНТАХ: «22», «22%», «22,5» → 22 (уточнение владельца
    23.09.2026).

    Коэффициент («1.22») человек не набирает: он знает ставку, а не множитель.
    Знак процента принимаем и отбрасываем — его пишут по привычке, и отвергать
    из-за него строку было бы придиркой.
    """
    text = str(value if value is not None else "").replace(" ", " ").strip()
    text = text.replace("%", "").replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        percent = Decimal(text)
    except InvalidOperation:
        raise HTTPException(400, f"НДС: «{value}» — это не число")
    if percent < 0 or percent > 100:
        raise HTTPException(400, f"НДС: «{value}» — ставка бывает от 0 до 100%")
    return percent


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


def payment_numbers(db: Session) -> dict:
    """
    Номер каждого поступления ВНУТРИ СВОЕГО МЕСЯЦА.

    НОМЕР БЕРЁТСЯ ИЗ ФАЙЛА и лежит в колонке (просьба владельца 24.09.2026:
    «нумерация должна совпадать с файлом экселя»). Считать его мы пробовали —
    по порядку заведения, — и это молча ломалось: весь файл заводится одним
    импортом, `created_at` у всех строк одинаковый, и порядок внутри месяца
    оставался на усмотрение сортировки по id. А номером ссылаются из вкладки
    «Отчёты» и называют строку вслух, глядя в ту самую выписку.

    Здесь остаётся ЗАПАСНОЙ ХОД для строк без номера: они получают свободные
    номера вслед за занятыми, по порядку заведения. Это строки, заведённые до
    появления колонки; новым номер проставляется при записи (`next_number`),
    чтобы он не менялся от появления соседей.
    """
    rows = db.execute(
        select(
            PartnerPayment.id,
            PartnerPayment.occurred_on,
            PartnerPayment.created_at,
            PartnerPayment.number,
        )
    ).all()
    by_month: dict = {}
    for payment_id, occurred_on, created_at, number in rows:
        key = (occurred_on.year, occurred_on.month)
        by_month.setdefault(key, []).append((created_at, payment_id, number))

    numbers = {}
    for items in by_month.values():
        taken = {number for _, _, number in items if number}
        nameless = sorted(
            ((created_at, payment_id) for created_at, payment_id, number in items
             if not number),
            # created_at совпадает у строк одного импорта, поэтому вторым
            # ключом идёт id — иначе порядок «плавал» бы от запроса к запросу.
            key=lambda x: (x[0], str(x[1])),
        )
        numbers.update({pid: number for _, pid, number in items if number})
        free = 1
        for _, payment_id in nameless:
            while free in taken:
                free += 1
            numbers[payment_id] = free
            taken.add(free)
    return numbers


def _numbers_in_month(db: Session, occurred_on: date) -> set:
    """Номера, уже занятые в месяце этой даты."""
    return set(
        db.execute(
            select(PartnerPayment.number).where(
                PartnerPayment.number.isnot(None),
                PartnerPayment.occurred_on >= occurred_on.replace(day=1),
                PartnerPayment.occurred_on < _next_month(occurred_on),
            )
        ).scalars()
    )


def next_number(db: Session, occurred_on: date) -> int:
    """
    Первый свободный номер в месяце этой даты — для строки, заведённой руками.

    Именно свободный, а не «последний плюс один»: строки удаляют, и номер
    удалённой должен вернуться в оборот, иначе нумерация месяца разойдётся с
    выпиской, где она сплошная.
    """
    taken = _numbers_in_month(db, occurred_on)
    number = 1
    while number in taken:
        number += 1
    return number


def _next_month(day: date) -> date:
    """Первое число следующего месяца — граница отбора «в этом месяце»."""
    return date(day.year + day.month // 12, day.month % 12 + 1, 1)


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


def _expected_transfer(payment: PartnerPayment):
    """
    Сколько ДОЛЖНО завестись: сумма поступления / (1 + НДС/100).

    КУРСА В ФОРМУЛЕ НЕТ (уточнение владельца 23.09.2026): все суммы приходят
    сразу в рублях, пересчитывать нечего. Валютная сумма у строки есть, но она
    справочная.

    Пусто, если не заполнена сама сумма: считать не из чего. А вот пустой НДС
    не помеха — у платежа без налога ставка нулевая, и требовать её заполнения
    значило бы просить набрать очевидное.
    """
    if payment.amount is None:
        return None
    vat = payment.vat_rate or Decimal(0)
    try:
        value = payment.amount / (Decimal(1) + vat / Decimal(100))
    except (InvalidOperation, ZeroDivisionError):
        return None
    return _money(value.quantize(Decimal("0.01")))


# НА СКОЛЬКО СУММА ЗАВОДА МОЖЕТ РАЗОЙТИСЬ С ФОРМУЛОЙ И ЭТО НЕ ОШИБКА.
#
# Копейка набегает сама собой: мы храним деньги с точностью до копеек и делим
# УЖЕ ОКРУГЛЁННУЮ сумму, а в исходной таблице делили полную. Настоящий случай
# (владелец, 24.09.2026): в строке 898 038,99 ₽ и завод 871 882,52 — обратное
# умножение даёт 898 039,00, то есть исходная сумма была на копейку больше.
# Показывать из-за этого «≠» значит приучить не обращать на него внимания.
TRANSFER_TOLERANCE = Decimal("0.01")


def _transfer_mismatch(payment: PartnerPayment):
    """
    Разошлась ли сумма завода с формулой больше, чем на копейку.

    Считает СЕРВЕР, а не экран: деньги уходят строками, и сравнивать их через
    Number() — тот же способ получить 1234.0999999999999, от которого мы
    бережёмся везде.
    """
    expected = _expected_transfer(payment)
    if expected is None or payment.transfer_amount is None:
        return None
    return abs(Decimal(expected) - payment.transfer_amount) > TRANSFER_TOLERANCE


def _out(payment: PartnerPayment, partner_name: str | None, linked: int = 0,
         number: int | None = None) -> dict:
    return {
        "id": str(payment.id),
        # Порядковый номер в своём месяце — им ссылаются из вкладки «Отчёты»
        # (см. payment_numbers).
        "number": number,
        "occurred_on": payment.occurred_on.isoformat(),
        "partner_id": str(payment.partner_id) if payment.partner_id else None,
        # Как строка подписана: имя из справочника либо набранное руками.
        "partner": partner_name or payment.partner_name,
        # Отдельно — набранное руками: полю ввода надо знать, что показывать,
        # когда площадки в справочнике нет.
        "partner_name": payment.partner_name,
        "description": payment.description,
        "amount": _money(payment.amount),
        # Справочная валютная сумма — ТЕКСТОМ, вместе с валютой: «8 247,81
        # доллар». В расчётах не участвует.
        "currency_amount": payment.currency_amount,
        "rate": _rate(payment.rate),
        "vat_rate": _rate(payment.vat_rate),
        "transfer_amount": _money(payment.transfer_amount),
        # Пусто, «да» или «синхра» — см. пояснение в модели.
        "transfer_status": payment.transfer_status,
        "actual_amount": _money(payment.actual_amount),
        # РАСХОЖДЕНИЕ — то, ради чего таблицу и ведут: сколько собирались
        # завести против того, сколько насчитали отчёты. Считает СЕРВЕР, как и
        # итоги: в JSON суммы уходят строками, и складывать их на экране
        # нельзя. Пусто, пока не заполнены оба числа: разница с неизвестным —
        # не ноль и не «весь завод», а просто «ещё не с чем сверять».
        "difference": _difference(payment),
        # СКОЛЬКО ДОЛЖНО ЗАВЕСТИСЬ ПО ФОРМУЛЕ: поступление / курс / (1+НДС).
        # Считает сервер — на экране деньги не делят, они там строки.
        "expected_transfer": _expected_transfer(payment),
        # Разошлось ли с формулой заметно — решает сервер: см. TRANSFER_TOLERANCE.
        "transfer_mismatch": _transfer_mismatch(payment),
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
        was = payment.occurred_on
        payment.occurred_on = _parse_date(body["occurred_on"], "Дата поступления")
        touched.append("occurred_on")
        # ПЕРЕЕХАЛА В ДРУГОЙ МЕСЯЦ — НУЖЕН СВОЙ НОМЕР: нумерация у каждого
        # месяца своя, и принесённый номер там наверняка уже занят. Внутри
        # месяца дату правят свободно, номер при этом не трогаем — им уже
        # могли назвать строку.
        if was and (was.year, was.month) != (
            payment.occurred_on.year, payment.occurred_on.month
        ):
            payment.number = next_number(db, payment.occurred_on)
            touched.append("number")
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
            # Выбор из справочника главнее набранного руками: иначе строка
            # оказалась бы подписана дважды и по-разному.
            payment.partner_name = None
        else:
            # Пусто — «ещё не разобрались, чей платёж», а не ошибка.
            payment.partner_id = None
        touched.append("partner_id")
    if "partner_name" in body:
        # ПЛОЩАДКА, КОТОРОЙ НЕТ В СПРАВОЧНИКЕ: мелкие партнёры по
        # синхронизации. Имя набирают руками, и ссылка на справочник при этом
        # снимается — иначе строка была бы подписана дважды.
        name = str(body["partner_name"] or "").strip()
        if len(name) > 200:
            raise HTTPException(400, "Название площадки слишком длинное")
        payment.partner_name = name or None
        if name:
            payment.partner_id = None
        touched.append("partner_name")
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
    if "currency_amount" in body:
        # Как написали, так и храним: поле справочное, разбирать его не на что.
        note = " ".join(str(body["currency_amount"] or "").split())
        if len(note) > 64:
            raise HTTPException(400, "Сумма в валюте: слишком длинная запись")
        payment.currency_amount = note or None
        touched.append("currency_amount")
    if "rate" in body:
        payment.rate = _parse_money(body["rate"], "Курс")
        touched.append("rate")
    if "vat_rate" in body:
        payment.vat_rate = _parse_percent(body["vat_rate"])
        touched.append("vat_rate")
    if "transfer_status" in body:
        status = " ".join(str(body["transfer_status"] or "").split()).lower()
        if status and status not in TRANSFER_STATUSES:
            raise HTTPException(
                400, "Заведено: допустимо «%s» или пусто" % "», «".join(TRANSFER_STATUSES)
            )
        payment.transfer_status = status or None
        touched.append("transfer_status")
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

    # ПОРЯДОК — ПО ЗАНЕСЕНИЮ, А НЕ ПО ДАТЕ (просьба владельца 23.09.2026).
    # Таблицу заполняют по выписке сверху вниз, и строка должна оставаться
    # там, куда её завели: пересортировка по дате перекладывает уже
    # заполненные строки под руками, а номер (см. payment_numbers) считается
    # как раз по занесению — иначе он не совпадал бы с тем, что на экране.
    rows = db.execute(
        query.order_by(PartnerPayment.created_at, PartnerPayment.id)
    ).all()
    linked = _linked_reports(db, [p.id for p, _ in rows])
    numbers = payment_numbers(db)
    payments = [_out(p, name, linked.get(p.id, 0), numbers.get(p.id)) for p, name in rows]

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
            "not_transferred": sum(1 for p, _ in rows if not p.transfer_status),
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
    occurred_on = _parse_date(
        body.get("occurred_on") or date.today().isoformat(), "Дата поступления"
    )
    payment = PartnerPayment(
        id=uuid.uuid4(),
        occurred_on=occurred_on,
        # Номер проставляем СРАЗУ, а не считаем при показе: иначе он менялся
        # бы от появления соседей, а им называют строку и ссылаются на неё из
        # вкладки «Отчёты».
        number=next_number(db, occurred_on),
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
    return {"payment": _out(payment, partner.name if partner else None,
                            number=payment_numbers(db).get(payment.id))}


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
            # НОМЕР ОБЯЗАТЕЛЕН И ЗДЕСЬ: страница подставляет ответ на место
            # строки, и без номера он пропадал из таблицы до перезагрузки.
            payment_numbers(db).get(payment.id),
        )
    }


# --------------------------------------------------------------- импорт

def _match_partners(rows: list, index: PartnerIndex) -> dict:
    """
    Имя из выписки → площадка справочника, если нашлась.

    Разбор живёт в `app/partner_names.py`: там же объяснено, почему способов
    четыре и почему неоднозначность считается отказом. Здесь только запрос к
    справочнику.
    """
    # Ключ — НОМЕР СТРОКИ, а не имя: у Apple одно и то же имя плательщика
    # ведёт к разным площадкам в зависимости от суммы платежа.
    return {
        row.line: index.match(row.partner_raw, row.amount)
        for row in rows
        if row.partner_raw
    }


def _existing(db: Session, rows: list, index: PartnerIndex) -> dict:
    """
    Что уже заведено — чтобы повторный импорт того же файла не задвоил строки.

    СВЕРКА ПО ДАТЕ, ПЛОЩАДКЕ И СУММЕ (просьба владельца 24.09.2026, после того
    как в таблице нашлись дубли). Описание в неё НЕ входит: его пишет банк, и
    у одного и того же платежа оно гуляет — во второй выгрузке к нему спереди
    приклеился номер документа («NT-054905 · MAY 2026 YOUTUBE ROYALTY»), и все
    восемь строк прошли как новые. Дата, площадка и сумма вместе повторяются
    только у настоящего дубля: два платежа от одной площадки в один день на ту
    же копейку — это и есть один платёж, занесённый дважды.

    Возвращаем не множество ключей, а пары «дата + сумма» → список площадок:
    площадки сравниваются не буква в букву (см. `_partner_same`).
    """
    dates = {row.occurred_on for row in rows if row.occurred_on}
    if not dates:
        return {}
    found = db.execute(
        select(
            PartnerPayment.occurred_on,
            PartnerPayment.partner_id,
            PartnerPayment.partner_name,
            PartnerPayment.amount,
        ).where(PartnerPayment.occurred_on.in_(dates))
    ).all()
    seen: dict = {}
    for occurred_on, partner_id, partner_name, amount in found:
        key = (occurred_on, _amount_key(amount))
        seen.setdefault(key, []).append(
            _partner_key(partner_id, partner_name, index)
        )
    return seen


def _amount_key(amount) -> str:
    """
    Сумма для сверки, ОКРУГЛЁННАЯ ДО КОПЕЕК. Это не мелочь: в файле она
    записана со всей точностью деления («642390.4048780487»), а в базе колонка
    двузначная. Без округления повторный импорт считал дублями только те
    строки, где копейки и так сошлись, — на образце 44 из 69, а остальные
    заводились по второму разу.
    """
    if amount is None:
        return ""
    return str(Decimal(amount).quantize(Decimal("0.01")))


def _partner_key(partner_id, partner_name, index: PartnerIndex) -> str:
    """
    Чей это платёж, одной строкой.

    Площадка справочника узнаётся по id, мелкий партнёр — по очищенному имени.
    Имя прогоняется через ТО ЖЕ сопоставление, что и при импорте: строку могли
    завести, когда площадки в справочнике ещё не было, и тогда у неё в базе имя
    текстом, а у новой строки — id.
    """
    if partner_id:
        return "id:%s" % partner_id
    found = index.match(partner_name) if partner_name else None
    if found:
        return "id:%s" % found
    return clean_name(partner_name or "").casefold()


def _partner_same(one: str, other: str) -> bool:
    """
    Одна ли это площадка.

    У площадки справочника сравниваются id, а у имени текстом — СЛОВА, и
    ОДНО ИМЯ МОЖЕТ БЫТЬ НАЧАЛОМ ДРУГОГО: в базе лежит «Муз ТВ», потому что
    владелец укоротил имя руками, а из файла приедет «Муз ТВ Операционная
    компания». Буквальное сравнение завело бы третью строку тому же платежу.

    Послабление безопасно ровно потому, что площадка здесь — не единственный
    признак: дата и сумма до копейки уже совпали. Два РАЗНЫХ плательщика,
    приславших в один день одинаковую до копейки сумму, да ещё и названных
    так, что одно имя начинает другое, — это не тот случай, ради которого
    стоит городить точность.
    """
    if one.startswith("id:") or other.startswith("id:"):
        return one == other
    first, second = one.split(), other.split()
    if not first or not second:
        return one == other
    short, long = sorted((first, second), key=len)
    return long[: len(short)] == short


def _is_duplicate(seen: dict, row, partner_id, index: PartnerIndex) -> bool:
    """Есть ли уже такая строка. `seen` пополняется в `_remember`."""
    key = (row.occurred_on, _amount_key(row.amount))
    mine = _partner_key(partner_id, row.partner_raw, index)
    return any(_partner_same(mine, other) for other in seen.get(key, ()))


def _remember(seen: dict, row, partner_id, index: PartnerIndex) -> None:
    """Запомнить только что заведённую строку: дубль внутри файла — тоже дубль."""
    key = (row.occurred_on, _amount_key(row.amount))
    seen.setdefault(key, []).append(
        _partner_key(partner_id, row.partner_raw, index)
    )


def _preview(row, partner_id, partner_name, duplicate: bool) -> dict:
    return {
        "line": row.line,
        "sheet": row.sheet,
        "occurred_on": row.occurred_on.isoformat() if row.occurred_on else None,
        "partner": partner_name,
        "partner_known": partner_id is not None,
        "partner_raw": row.partner_raw,
        "description": row.description,
        "amount": _money(row.amount),
        # Текстом, как в файле: «8 247,81 доллар».
        "currency_amount": row.currency_amount,
        "vat_rate": _rate(row.vat_rate),
        "transfer_amount": _money(row.transfer_amount),
        "transfer_status": row.transfer_status,
        "duplicate": duplicate,
        "problems": row.problems,
    }


def _read_import(file, pasted: str) -> tuple:
    if file is not None and file.filename:
        name = file.filename
        if not name.lower().endswith((".xlsx", ".xlsm", ".csv", ".txt", ".tsv")):
            raise HTTPException(400, "Ожидается файл .xlsx или текстовый")
        return file.file.read(), name
    if pasted.strip():
        return pasted, "вставка"
    raise HTTPException(400, "Нечего разбирать: выберите файл или вставьте строки")


def _prepare(db: Session, file, pasted: str) -> tuple:
    content, name = _read_import(file, pasted)
    rows = parse_rows(content, name)
    if not rows:
        raise HTTPException(400, "В файле не нашлось ни одной строки поступления")
    if len(rows) > MAX_IMPORT_ROWS:
        raise HTTPException(400, f"Строк больше {MAX_IMPORT_ROWS} — похоже, это не тот файл")
    # Справочник площадок читается ОДИН раз: он нужен и сопоставлению имён,
    # и ключу дубля — в нём теперь есть площадка.
    index = PartnerIndex(db.execute(select(Partner.id, Partner.name)).all())
    matched = _match_partners(rows, index)
    return rows, matched, _existing(db, rows, index), name, index


@payments_router.post(
    "/import/check", dependencies=[Depends(require_role(*CAN_MANAGE_PAYMENTS))]
)
def import_check(
    file: UploadFile | None = File(default=None),
    pasted: str = Form(default=""),
    db: Session = Depends(get_session),
) -> dict:
    """
    Разобрать файл или вставку БЕЗ записи: показать, что получится.

    ДВА ШАГА, как у номенклатуры, и по той же причине: файл собран руками, в
    нём попадаются пустые строки, подписи и «синхра» вместо «да». Увидеть это
    надо до того, как строки лягут в таблицу, а не после.
    """
    rows, matched, seen, name, index = _prepare(db, file, pasted)
    partners = {pid: pname for pid, pname in db.execute(select(Partner.id, Partner.name))}
    preview, duplicates = [], 0
    for row in rows:
        partner_id = matched.get(row.line)
        duplicate = _is_duplicate(seen, row, partner_id, index)
        duplicates += duplicate
        preview.append(
            # Показываем то же имя, что и запишем: очищенное от формы
            # собственности и реквизитов. Иначе предпросмотр обещает одно, а
            # в таблице оказывается другое.
            _preview(row, partner_id,
                     partners.get(partner_id) or clean_name(row.partner_raw) or None,
                     duplicate)
        )
    return {
        "file_name": name,
        "rows": preview,
        "totals": {
            "rows": len(rows),
            "ok": sum(1 for r in rows if r.ok),
            "problems": sum(1 for r in rows if r.problems),
            "duplicates": duplicates,
            # Сколько имён не нашлось в справочнике: они лягут текстом, и это
            # нормально — мелких партнёров там и не должно быть.
            "unknown_partners": sum(
                1 for r in rows if r.partner_raw and not matched.get(r.line)
            ),
            "amount": _money(sum((r.amount or Decimal(0) for r in rows), Decimal(0))),
            "transfer_amount": _money(
                sum((r.transfer_amount or Decimal(0) for r in rows), Decimal(0))
            ),
        },
    }


@payments_router.post(
    "/import/apply", dependencies=[Depends(require_role(*CAN_MANAGE_PAYMENTS))]
)
def import_apply(
    file: UploadFile | None = File(default=None),
    pasted: str = Form(default=""),
    skip_duplicates: bool = Form(default=True),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Записать разобранное. Строки с замечаниями не пишутся вовсе.

    Дубли по умолчанию пропускаются: файл обычно заливают повторно, чтобы
    добрать новые строки, а не чтобы завести те же второй раз.
    """
    rows, matched, seen, name, index = _prepare(db, file, pasted)
    created = skipped = duplicates = 0
    taken: dict = {}                     # месяц → уже занятые в нём номера
    for row in rows:
        if row.problems:
            skipped += 1
            continue
        partner_id = matched.get(row.line)
        if skip_duplicates and _is_duplicate(seen, row, partner_id, index):
            duplicates += 1
            continue
        # НОМЕР ИЗ ФАЙЛА, и он же главный: с ним человек смотрит на выписку.
        # Занят или не разобран — берём следующий свободный в этом месяце;
        # занятые копим на месте, потому что в базе строки ещё нет.
        month = (row.occurred_on.year, row.occurred_on.month)
        used = taken.setdefault(month, _numbers_in_month(db, row.occurred_on))
        number = row.number
        if number is None or number in used:
            number = 1
            while number in used:
                number += 1
        used.add(number)
        db.add(
            PartnerPayment(
                id=uuid.uuid4(),
                number=number,
                occurred_on=row.occurred_on,
                partner_id=partner_id,
                # Имя из выписки, если площадки нет в справочнике: мелкие
                # партнёры по синхронизации туда и не попадут.
                # Не строка выписки целиком, а очищенное имя: «Муз ТВ
                # Операционная компания» вместо «ООО "Муз ТВ Операционная
                # компания" Р/С 40702810…». Просьба владельца 23.09.2026.
                partner_name=None if partner_id else (clean_name(row.partner_raw) or None),
                description=row.description or None,
                amount=row.amount,
                currency_amount=row.currency_amount,
                vat_rate=row.vat_rate,
                transfer_amount=row.transfer_amount,
                transfer_status=row.transfer_status,
                created_by=current_user.id,
            )
        )
        _remember(seen, row, partner_id, index)
        created += 1
    log_action(
        db, current_user, "payment.import", entity_type="payment",
        meta={"file": name, "created": created, "skipped": skipped,
              "duplicates": duplicates},
    )
    db.commit()
    return {"created": created, "skipped": skipped, "duplicates": duplicates}


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
