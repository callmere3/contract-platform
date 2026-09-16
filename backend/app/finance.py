"""
ML Finance — деньги по контрагентам: справочник категорий и расчёт балансов.

Здесь ПРАВИЛА, в routers_finance.py — выдача. Разделение то же, что у кубка
(champion.py / routers_champion.py): правило «что такое баланс» не должно
жить в обработчике запроса, иначе второй потребитель посчитает иначе.

ЧТО ТАКОЕ БАЛАНС. Сумма поступлений минус сумма расходов по контрагенту, в
рублях. Знак не прячем: отрицательный баланс — обычное состояние (аванс
выплачен, роялти ещё не набежало), и подменять его на «долг 10 000» значило
бы решать за бухгалтера, кто кому должен.

ВАЛЮТА ОДНА — РУБЛЬ (решение владельца 16.09.2026). В базе есть и
казахстанские контрагенты, но суммы по ним приводят к рублям при вводе.
Отдельной колонки валюты нет СОЗНАТЕЛЬНО: колонка без курсов и даты курса
создаёт видимость мультивалютности, которой нет — складывать тенге с рублями
всё равно было бы нечем. Понадобится вторая валюта — это колонка `currency`
плюс отдельный баланс на каждую, а не пересчёт задним числом.

ДЕНЬГИ — Numeric, а не float. float(0.1) + float(0.2) != 0.3, и на сотне
операций это расходится в копейках, которые потом никто не найдёт.
"""
from decimal import Decimal

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models import FinanceOperation

# Вид операции. Строками, а не булевым «приход/расход»: третий вид (перевод,
# корректировка) добавится значением, а не переписыванием колонки.
INCOME = "income"
EXPENSE = "expense"
OPERATION_KINDS = (INCOME, EXPENSE)

# Категории операций — единственный источник правды, отдаётся фронту через
# GET /tags (как страны и типы контрагентов: справочники на фронте не
# хардкодятся). Код латиницей, подпись русская: подпись можно переписать, не
# трогая уже сохранённые строки.
#
# СПРАВОЧНИКА ДВА, по одному на вид операции (правка 16.09.2026). Деньги сюда
# приходят и уходят по разным поводам: приходят только квартальные отчёты
# площадок, уходят — выплаты артисту. Общий список означал бы, что «Выплату
# аванса» можно выбрать у поступления, а это не редкая ошибка, а бессмыслица,
# которую потом ищут в отчёте.
INCOME_CATEGORIES = (
    ("quarterly_report", "Квартальный отчёт"),
)
EXPENSE_CATEGORIES = (
    ("royalty_payout", "Выплата роялти"),
    ("advance_payout", "Выплата аванса"),
)

CATEGORIES_BY_KIND = {INCOME: INCOME_CATEGORIES, EXPENSE: EXPENSE_CATEGORIES}
# Подписи — общим словарём: по коду из уже сохранённой строки надо уметь
# получить подпись, не зная её вида.
CATEGORY_LABELS = dict(INCOME_CATEGORIES + EXPENSE_CATEGORIES)


def categories_for(kind: str) -> tuple:
    """Допустимые категории для вида операции; неизвестный вид — пустой набор."""
    return CATEGORIES_BY_KIND.get(kind, ())


# --- ПЕРИОД ПОСТУПЛЕНИЯ -----------------------------------------------------
#
# Поступление — это квартальный отчёт, и он относится к кварталу, а не к дате
# зачисления: деньги за I квартал приходят в апреле, а иногда одним платежом
# сразу за несколько кварталов. Поэтому у операции есть период — пара
# (год, квартал) начала и конца.
#
# Хранится ЧЕТЫРЬМЯ числами, а не строкой «2026-Q1» и не датами. Строку
# пришлось бы разбирать в каждом месте, где понадобится сравнение; даты
# выглядели бы точнее, чем есть на самом деле («с 01.01 по 31.03» — это не то,
# что человек вводил, и первый же отчёт по кварталам начал бы их обратно
# угадывать). Числа сравниваются и сортируются как есть: (год, квартал).
#
# У ОДНОГО квартала начало и конец совпадают — «пусто = один квартал» пришлось
# бы проверять в каждом читающем месте.
QUARTER_ROMAN = ("I", "II", "III", "IV")
QUARTERS = (1, 2, 3, 4)
# Границы года — защита от опечатки в четырёхзначном поле (2206 вместо 2026),
# а не попытка предсказать, сколько проживёт сервис.
MIN_YEAR = 2000
MAX_YEAR = 2100


def quarter_label(year: int, quarter: int) -> str:
    """«I кв. 2026»."""
    return "%s кв. %d" % (QUARTER_ROMAN[quarter - 1], year)


def period_label(year_from, quarter_from, year_to, quarter_to) -> str | None:
    """
    «I кв. 2026» или «IV кв. 2025 — I кв. 2026». None, если периода нет
    (у расходов его и не бывает).

    Подпись собирает СЕРВЕР, а не фронт: формат периода — такое же правило,
    как правило знака суммы, и разъезжаться ему в двух местах незачем.
    """
    if year_from is None or quarter_from is None:
        return None
    start = quarter_label(year_from, quarter_from)
    if (year_from, quarter_from) == (year_to, quarter_to):
        return start
    return "%s — %s" % (start, quarter_label(year_to, quarter_to))


# Потолок суммы одной операции. Не про безопасность, а про опечатку: лишний
# ноль в сумме искажает баланс до неузнаваемости, и заметить это потом
# труднее, чем не пустить сейчас.
MAX_AMOUNT = Decimal("99999999.99")


def signed(kind: str, amount: Decimal) -> Decimal:
    """Сумма со знаком: поступление плюсом, расход минусом."""
    return amount if kind == INCOME else -amount


def balances(db: Session, contragent_ids) -> dict:
    """
    {contragent_id: Decimal} — баланс по каждому из переданных контрагентов.

    ОДИН запрос на всю страницу списка, а не по запросу на строку: в базе
    800+ карточек, и на странице их сотня.

    В ответе только те, у кого есть хоть одна операция. У остальных баланс
    ноль, и звать его строкой из БД незачем — вызывающий подставляет
    Decimal('0') сам (см. _zero_if_missing в routers_finance.py).
    """
    ids = list(contragent_ids)
    if not ids:
        return {}

    rows = (
        db.query(
            FinanceOperation.contragent_id,
            # CASE вместо двух запросов: поступления плюсом, расходы минусом —
            # одной агрегацией.
            func.sum(_signed_column()),
        )
        .filter(FinanceOperation.contragent_id.in_(ids))
        .group_by(FinanceOperation.contragent_id)
        .all()
    )
    return {contragent_id: Decimal(str(total or 0)) for contragent_id, total in rows}


def totals(db: Session, contragent_id) -> dict:
    """
    {"income": Decimal, "expense": Decimal, "balance": Decimal} по одному
    контрагенту — для его карточки: там показывают не только итог, но и из
    чего он сложился.
    """
    income = (
        db.query(func.coalesce(func.sum(FinanceOperation.amount), 0))
        .filter(
            FinanceOperation.contragent_id == contragent_id,
            FinanceOperation.kind == INCOME,
        )
        .scalar()
    )
    expense = (
        db.query(func.coalesce(func.sum(FinanceOperation.amount), 0))
        .filter(
            FinanceOperation.contragent_id == contragent_id,
            FinanceOperation.kind == EXPENSE,
        )
        .scalar()
    )
    income = Decimal(str(income or 0))
    expense = Decimal(str(expense or 0))
    return {"income": income, "expense": expense, "balance": income - expense}


def _signed_column():
    """Сумма операции со знаком, выражением SQL (см. balances)."""
    return case(
        (FinanceOperation.kind == INCOME, FinanceOperation.amount),
        else_=-FinanceOperation.amount,
    )


def money(value: Decimal) -> str:
    """
    Сумма для JSON — строкой, а не float.

    float в JSON — это тот же двоичный дробный тип: 1234.10 уезжает в
    1234.0999999999999. Строку фронт показывает как есть и форматирует сам,
    ничего не пересчитывая.
    """
    return format(Decimal(value or 0).quantize(Decimal("0.01")), "f")
