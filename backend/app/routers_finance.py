"""
ML Finance — деньги по контрагентам (Admin и Director).

  GET    /finance/contragents            — список с балансами (те же фильтры,
                                            что в базе контрагентов ML Docs)
  GET    /finance/contragents/{id}       — карточка: ФИО, никнеймы, реквизиты,
                                            баланс и операции
  POST   /finance/contragents/{id}/operations — внести поступление или расход
  DELETE /finance/operations/{id}        — удалить операцию (только Admin)

БАЗА КОНТРАГЕНТОВ ОДНА. ML Finance не заводит своих карточек и не копирует
чужие: это тот же `contragents`, только показанный с другой стороны — деньги
вместо документов. Поэтому список здесь строится ТЕМ ЖЕ `search_contragents`,
что и «База контрагентов» в ML Docs, а не своим запросом: разойдись они в
поиске или пагинации — и один и тот же человек находился бы в одном продукте
и не находился в другом.

ПРАВКИ ОПЕРАЦИИ НЕТ, только удаление и внесение заново (и удаление — у
Admin). Денежная строка, которую можно молча переписать, не история, а
черновик; удалённая хотя бы исчезает целиком и на глазах.

КАТЕГОРИИ РАЗНЫЕ У ПОСТУПЛЕНИЙ И РАСХОДОВ (см. app/finance.py): приходят
только квартальные отчёты, уходят выплаты роялти и аванса. У поступления,
кроме того, ОБЯЗАТЕЛЕН период — за какой квартал (или за какие, если платёж
закрывает сразу несколько) пришли деньги: дата зачисления на это не отвечает,
за I квартал платят в апреле.

Что НЕ делает этот роутер: не считает роялти сам, не связывает операции с
документами и не сверяет период с отчётами площадок. Здесь ручной учёт — то,
что внесли, то и в балансе.
"""
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import get_current_user, require_role
from app.db import get_session
from app.finance import (
    CATEGORY_LABELS,
    INCOME,
    MAX_AMOUNT,
    MAX_YEAR,
    MIN_YEAR,
    OPERATION_KINDS,
    QUARTERS,
    balances,
    categories_for,
    money,
    period_label,
    totals,
)
from app.models import Contragent, FinanceOperation, TrackRight, User
from app.roles import (
    CAN_ADD_FINANCE_OPERATIONS,
    CAN_DELETE_FINANCE_OPERATIONS,
    CAN_USE_FINANCE,
)
from app.routers_contragents import search_contragents

finance_router = APIRouter(
    prefix="/finance",
    tags=["finance"],
    # Право стоит на ВСЁМ роутере, а не на каждом обработчике: забыть
    # Depends на одном новом эндпоинте — вопрос времени, а цена ошибки здесь
    # выше обычного.
    dependencies=[Depends(require_role(*CAN_USE_FINANCE))],
)


@finance_router.get("/contragents")
def list_with_balances(
    q: str | None = None,
    country: str | None = None,
    contragent_type: str | None = None,
    page: int = 1,
    page_size: int = 100,
    db: Session = Depends(get_session),
) -> dict:
    """
    Список контрагентов с балансом у каждого.

    Поиск, фильтры и пагинация — не свои, а вызов `search_contragents` из
    ML Docs: список контрагентов в двух продуктах обязан быть одним и тем же,
    включая то, по каким полям он ищет.

    Балансы добираются ОДНИМ запросом на всю страницу (`balances`), а не по
    запросу на строку: в базе 800+ карточек, на странице — сотня.
    """
    found = search_contragents(
        q=q,
        country=country,
        contragent_type=contragent_type,
        page=page,
        page_size=page_size,
        db=db,
    )

    items = found["contragents"]
    by_id = balances(db, [uuid.UUID(item["id"]) for item in items])
    for item in items:
        item["balance"] = money(by_id.get(uuid.UUID(item["id"]), Decimal("0")))

    return found


@finance_router.get("/contragents/{contragent_id}")
def finance_card(contragent_id: uuid.UUID, db: Session = Depends(get_session)) -> dict:
    """
    Карточка контрагента глазами финансов: ФИО, никнеймы, реквизиты, баланс и
    все операции.

    Набор полей другой, чем в карточке ML Docs, и это не упущение: там
    показывают то, что подставится в документ (тип договора, роялти, даты),
    здесь — то, по чему платят (реквизиты) и сколько уже прошло.

    Операции отдаём целиком, без пагинации: у одного контрагента их десятки.
    Появятся тысячи — здесь и добавится постраничность, а не раньше.
    """
    contragent = db.get(Contragent, contragent_id)
    if contragent is None:
        raise HTTPException(status_code=404, detail="Контрагент не найден")

    sums = totals(db, contragent_id)
    # Сколько треков каталога принадлежит этому контрагенту — по ССЫЛКЕ, а не
    # по совпадению имени: у карточки бывает несколько написаний в выгрузке
    # Dista, и счёт по титлу показал бы не все. DISTINCT обязателен: у трека
    # две строки прав на одного и того же человека (смежные и авторские) —
    # без него каждый трек считался бы дважды.
    tracks_count = (
        db.query(func.count(func.distinct(TrackRight.track_id)))
        .filter(TrackRight.contragent_id == contragent_id)
        .scalar()
        or 0
    )
    operations = (
        db.query(FinanceOperation)
        .filter(FinanceOperation.contragent_id == contragent_id)
        # Свежие сверху; при одной дате — в порядке внесения, чтобы список не
        # прыгал между обновлениями страницы.
        .order_by(FinanceOperation.occurred_on.desc(), FinanceOperation.created_at.desc())
        .all()
    )

    return {
        "id": str(contragent.id),
        "title": contragent.title,
        "name": contragent.name,
        "tracks_count": tracks_count,
        "country": contragent.country,
        "type": contragent.type,
        "reg_number": contragent.reg_number,
        "nicknames": [n.nickname for n in contragent.nicknames],
        "requisites": contragent.requisites or {},
        "balance": money(sums["balance"]),
        "income_total": money(sums["income"]),
        "expense_total": money(sums["expense"]),
        "operations": [_operation(row) for row in operations],
    }


@finance_router.post(
    "/contragents/{contragent_id}/operations",
    dependencies=[Depends(require_role(*CAN_ADD_FINANCE_OPERATIONS))],
)
def add_operation(
    contragent_id: uuid.UUID,
    kind: str = Form(...),
    amount: str = Form(...),
    category: str = Form(...),
    occurred_on: str = Form(...),
    document_number: str | None = Form(None),
    comment: str | None = Form(None),
    # Период поступления — за какие кварталы деньги. Строками, а не int:
    # пустое поле формы приходит как '', и объявленный int дал бы 422 с
    # техническим текстом вместо понятного «укажите период».
    period_year_from: str | None = Form(None),
    period_quarter_from: str | None = Form(None),
    period_year_to: str | None = Form(None),
    period_quarter_to: str | None = Form(None),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Внести поступление или расход.

    Сумма приходит СТРОКОЙ и разбирается в Decimal здесь: прими мы float,
    «1234.10» уже на входе стало бы 1234.0999999999999, и никакое округление
    потом этого не вернуло бы.

    Ноль и минус не принимаем. Знак задаётся видом операции (kind), а
    «расход на -500» — это поступление, записанное так, что ни один отчёт по
    расходам его правильно не посчитает.
    """
    if db.get(Contragent, contragent_id) is None:
        raise HTTPException(status_code=404, detail="Контрагент не найден")

    if kind not in OPERATION_KINDS:
        raise HTTPException(status_code=400, detail="Неизвестный вид операции")
    # Категория проверяется ПРОТИВ ВИДА операции, а не против общего списка:
    # «Выплата аванса» у поступления — не редкая ошибка, а бессмыслица,
    # которую потом ищут в отчёте.
    if category not in [code for code, _label in categories_for(kind)]:
        raise HTTPException(
            status_code=400, detail="Эта категория не подходит для такого вида операции"
        )

    value = _parse_amount(amount)
    when = _parse_date(occurred_on)
    period = _parse_period(
        kind, period_year_from, period_quarter_from, period_year_to, period_quarter_to
    )

    operation = FinanceOperation(
        contragent_id=contragent_id,
        kind=kind,
        amount=value,
        category=category,
        occurred_on=when,
        period_year_from=period[0],
        period_quarter_from=period[1],
        period_year_to=period[2],
        period_quarter_to=period[3],
        document_number=(document_number or "").strip() or None,
        comment=(comment or "").strip() or None,
        created_by=current_user.id,
        created_username=current_user.full_name or current_user.username,
    )
    db.add(operation)
    db.flush()

    # В журнал действий деньги пишем всегда: это единственное место, где
    # видно, кто внёс операцию, если саму строку потом удалят.
    log_action(
        db,
        current_user,
        "finance.operation.create",
        entity_type="contragent",
        entity_id=contragent_id,
        meta={
            "operation_id": str(operation.id),
            "kind": kind,
            "amount": money(value),
            "category": category,
        },
    )
    db.commit()

    return _operation(operation)


@finance_router.delete(
    "/operations/{operation_id}",
    dependencies=[Depends(require_role(*CAN_DELETE_FINANCE_OPERATIONS))],
)
def delete_operation(
    operation_id: uuid.UUID,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Удалить операцию — только Admin.

    Правки операции нет вовсе: ошибочную удаляют и вносят заново. Строка
    уходит физически, но в журнале действий остаётся и её внесение, и это
    удаление — с суммой, видом и категорией.
    """
    operation = db.get(FinanceOperation, operation_id)
    if operation is None:
        raise HTTPException(status_code=404, detail="Операция не найдена")

    log_action(
        db,
        current_user,
        "finance.operation.delete",
        entity_type="contragent",
        entity_id=operation.contragent_id,
        meta={
            "operation_id": str(operation.id),
            "kind": operation.kind,
            "amount": money(operation.amount),
            "category": operation.category,
        },
    )
    db.delete(operation)
    db.commit()
    return {"deleted": str(operation_id)}


def _operation(row: FinanceOperation) -> dict:
    return {
        "id": str(row.id),
        "kind": row.kind,
        # Сумма всегда положительная, знак несёт kind. Рядом — signed_amount
        # для показа: фронту не нужно знать правило знака, чтобы нарисовать
        # «−5 000».
        "amount": money(row.amount),
        "signed_amount": money(row.amount if row.kind == INCOME else -row.amount),
        "category": row.category,
        "category_label": CATEGORY_LABELS.get(row.category, row.category),
        "occurred_on": row.occurred_on.isoformat(),
        # Период — и числами (для будущих отчётов по кварталам), и готовой
        # подписью: формат периода собирает сервер, чтобы он не разъехался
        # между экраном и выгрузкой.
        "period_year_from": row.period_year_from,
        "period_quarter_from": row.period_quarter_from,
        "period_year_to": row.period_year_to,
        "period_quarter_to": row.period_quarter_to,
        "period_label": period_label(
            row.period_year_from,
            row.period_quarter_from,
            row.period_year_to,
            row.period_quarter_to,
        ),
        "document_number": row.document_number,
        "comment": row.comment,
        "created_by": row.created_username,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _parse_amount(raw: str) -> Decimal:
    """
    «1 234,50», «1234.5» → Decimal('1234.50').

    Пробелы (в том числе неразрывный из копипасты) и запятая вместо точки —
    это как люди пишут суммы, а не ошибка ввода. Требовать от бухгалтера
    печатать банковский формат значило бы ловить опечатки там, где их можно
    просто не создавать.
    """
    text = (raw or "").replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail="Сумма должна быть числом")

    if value <= 0:
        raise HTTPException(
            status_code=400,
            detail="Сумма должна быть больше нуля — знак задаёт вид операции",
        )
    if value > MAX_AMOUNT:
        raise HTTPException(status_code=400, detail="Сумма слишком велика — проверьте, нет ли лишнего нуля")
    return value.quantize(Decimal("0.01"))


def _parse_period(kind, year_from, quarter_from, year_to, quarter_to):
    """
    Период поступления → (год_с, квартал_с, год_по, квартал_по).

    У поступления период ОБЯЗАТЕЛЕН: поступление — это квартальный отчёт, и
    без квартала непонятно, за что пришли деньги (дата зачисления не отвечает
    на этот вопрос: за I квартал платят в апреле). У расхода периода нет
    вовсе — выплата относится к дню, а не к кварталу; переданный период это
    отвергает, а не проглатывает молча, иначе в базе завелись бы строки,
    смысл которых никто не объяснит.

    Конец не задан — значит, один квартал: пишем в «по» то же, что в «с», и
    читающему коду не приходится разбирать случай «пусто = один квартал».
    """
    given = [year_from, quarter_from, year_to, quarter_to]
    filled = [v for v in given if (v or "").strip()]

    if kind != INCOME:
        if filled:
            raise HTTPException(
                status_code=400, detail="Период указывается только у поступлений"
            )
        return (None, None, None, None)

    if not (year_from or "").strip() or not (quarter_from or "").strip():
        raise HTTPException(
            status_code=400, detail="Укажите период: за какой квартал поступление"
        )

    y1 = _parse_year(year_from)
    q1 = _parse_quarter(quarter_from)
    # Конец диапазона необязателен — «за один квартал» это обычный случай.
    y2 = _parse_year(year_to) if (year_to or "").strip() else y1
    q2 = _parse_quarter(quarter_to) if (quarter_to or "").strip() else q1

    if (y2, q2) < (y1, q1):
        raise HTTPException(
            status_code=400, detail="Конец периода раньше начала — проверьте кварталы"
        )
    return (y1, q1, y2, q2)


def _parse_year(raw: str) -> int:
    try:
        year = int(str(raw).strip())
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Год периода должен быть числом")
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise HTTPException(status_code=400, detail="Год периода выглядит опечаткой")
    return year


def _parse_quarter(raw: str) -> int:
    try:
        quarter = int(str(raw).strip())
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Квартал должен быть числом от 1 до 4")
    if quarter not in QUARTERS:
        raise HTTPException(status_code=400, detail="Квартал должен быть числом от 1 до 4")
    return quarter


def _parse_date(raw: str) -> date:
    """ISO-дата из формы (input type=date шлёт ГГГГ-ММ-ДД)."""
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверная дата операции")
