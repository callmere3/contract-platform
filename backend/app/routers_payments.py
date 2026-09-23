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
    Порядковый номер каждого поступления ВНУТРИ СВОЕГО МЕСЯЦА.

    НУМЕРУЕМ ПО ПОРЯДКУ ЗАВЕДЕНИЯ (`created_at`), а не по дате платежа
    (просьба владельца 23.09.2026: «по порядку как заведены»). Это важно:
    номером ссылаются из вкладки «Отчёты», и номер, который меняется от того,
    что у соседней строки поправили дату, ссылкой быть не может. По дате
    строки только ПОКАЗЫВАЮТСЯ.

    Считаем в Python, а не оконной функцией: `date_trunc` есть в PostgreSQL и
    нет в SQLite, на котором гоняются проверки, а строк тут десятки — их
    заводят руками по выписке.
    """
    rows = db.execute(
        select(PartnerPayment.id, PartnerPayment.occurred_on, PartnerPayment.created_at)
    ).all()
    by_month: dict = {}
    for payment_id, occurred_on, created_at in rows:
        key = (occurred_on.year, occurred_on.month)
        by_month.setdefault(key, []).append((created_at, payment_id))
    numbers = {}
    for items in by_month.values():
        # created_at может совпасть у строк, заведённых подряд, поэтому вторым
        # ключом идёт id — иначе порядок «плавал» бы от запроса к запросу.
        for i, (_, payment_id) in enumerate(sorted(items, key=lambda x: (x[0], str(x[1]))), 1):
            numbers[payment_id] = i
    return numbers


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

def _match_partners(db: Session, rows: list) -> dict:
    """
    Имя из выписки → площадка справочника, если нашлась.

    Разбор живёт в `app/partner_names.py`: там же объяснено, почему способов
    четыре и почему неоднозначность считается отказом. Здесь только запрос к
    справочнику.
    """
    index = PartnerIndex(db.execute(select(Partner.id, Partner.name)).all())
    # Ключ — НОМЕР СТРОКИ, а не имя: у Apple одно и то же имя плательщика
    # ведёт к разным площадкам в зависимости от суммы платежа.
    return {
        row.line: index.match(row.partner_raw, row.amount)
        for row in rows
        if row.partner_raw
    }


def _existing_keys(db: Session, rows: list) -> set:
    """
    Что уже заведено — чтобы повторный импорт того же файла не задвоил строки.

    Ключ — дата, сумма и описание: своего номера у платежа в файле нет, а эти
    три вместе повторяются только у настоящего дубля. Совпало — строку
    пропускаем и говорим об этом; молча пройти мимо нельзя, иначе человек
    решит, что импорт не сработал.
    """
    dates = {row.occurred_on for row in rows if row.occurred_on}
    if not dates:
        return set()
    found = db.execute(
        select(PartnerPayment.occurred_on, PartnerPayment.amount, PartnerPayment.description)
        .where(PartnerPayment.occurred_on.in_(dates))
    ).all()
    return {
        _key(occurred_on, amount, description)
        for occurred_on, amount, description in found
    }


def _key(occurred_on, amount, description) -> tuple:
    """
    Ключ дубля. Сумма ОКРУГЛЯЕТСЯ ДО КОПЕЕК, и это не мелочь: в файле она
    записана со всей точностью деления («642390.4048780487»), а в базе колонка
    двузначная. Без округления повторный импорт считал дублями только те
    строки, где копейки и так сошлись, — на образце 44 из 69, а остальные
    заводились по второму разу.
    """
    return (
        occurred_on,
        str(Decimal(amount).quantize(Decimal("0.01"))) if amount is not None else "",
        (description or "").strip(),
    )


def _row_key(row) -> tuple:
    return _key(row.occurred_on, row.amount, row.description)


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
    return rows, _match_partners(db, rows), _existing_keys(db, rows), name


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
    rows, matched, seen, name = _prepare(db, file, pasted)
    partners = {pid: pname for pid, pname in db.execute(select(Partner.id, Partner.name))}
    preview, duplicates = [], 0
    for row in rows:
        partner_id = matched.get(row.line)
        duplicate = _row_key(row) in seen
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
    rows, matched, seen, name = _prepare(db, file, pasted)
    created = skipped = duplicates = 0
    for row in rows:
        if row.problems:
            skipped += 1
            continue
        if skip_duplicates and _row_key(row) in seen:
            duplicates += 1
            continue
        partner_id = matched.get(row.line)
        db.add(
            PartnerPayment(
                id=uuid.uuid4(),
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
        seen.add(_row_key(row))      # дубль внутри самого файла — тоже дубль
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
