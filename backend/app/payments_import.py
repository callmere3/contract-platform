"""
Разбор файла поступлений (ML Finance → «Поступления» → импорт).

ОТКУДА ФАЙЛ. Это рабочая таблица владельца: книга Excel, где каждый ЛИСТ —
месяц квартала («июль», «август», «сентябрь»), а строки заполняются по
банковской выписке. Импорт нужен затем, чтобы не перебивать её руками в
таблицу сервиса.

КОЛОНКИ ПОЗИЦИОННЫЕ, а не по названиям, — и это вынужденно. В образце шапка
есть только у первого листа, да и в ней подписаны четыре колонки из
шестнадцати: остальные («номер платёжки», «валюта», «сумма в валюте», «тип
прав», «заведено») стоят пустыми. Искать такие по имени нечего, поэтому здесь
единственное место в проекте, где порядок столбцов зашит. Строка-шапка
узнаётся по содержимому и пропускается.

ЧТО В КОЛОНКАХ (проверено на «поступления 3 квартал 2026.xlsx», 70 строк):

    0  № по порядку              пропускаем: нумерацию считает сервер
    1  дата поступления          дата или «03.07.2026»
    2  номер платёжного документа
    3  валюта либо банк          «доллар», но и «кредит европа»
    4  партнёр                   имя из выписки, часто длиннее справочника
    6  сумма в валюте            «8247.81» или «$16 803,73»
    7  описание платежа
    8  тип прав                  «права» / «цифра»
   11  сумма поступления         уже в рублях
   12  курс                      НЕ ИСПОЛЬЗУЕТСЯ: суммы и так в рублях
   13  НДС КОЭФФИЦИЕНТОМ         1.22, 1.03, 1
   14  сумма завода
   15  заведено                  «да», иногда «синхра»

НДС В ФАЙЛЕ — КОЭФФИЦИЕНТ, А У НАС ПРОЦЕНТЫ. «1.22» значит 22%, «1» — что
налога нет. Различаем по величине: всё, что не больше двух, — коэффициент,
остальное уже проценты. Однозначного признака тут нет и быть не может (1.22
теоретически и 1.22%), но ставки НДС в районе единицы не бывает, а
коэффициента больше двух — тем более.
"""
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import openpyxl

# Позиции колонок. Всё, чего нет в этом списке, мы не читаем.
COL_DATE = 1
COL_DOC = 2
COL_CURRENCY = 3
COL_PARTNER = 4
COL_CURRENCY_AMOUNT = 6
COL_DESCRIPTION = 7
COL_AMOUNT = 11
COL_VAT = 13
COL_TRANSFER = 14
COL_TRANSFERRED = 15
MIN_COLUMNS = 12

# Слова, которые в колонке «валюта» и правда валюта: там же встречается
# название банка («кредит европа»), и подписывать им сумму нельзя.
CURRENCIES = {
    "доллар": "USD", "долл": "USD", "usd": "USD", "$": "USD",
    "евро": "EUR", "eur": "EUR", "€": "EUR",
    "тенге": "KZT", "kzt": "KZT",
    "рубль": "RUB", "руб": "RUB", "rub": "RUB",
}
# «Заведено» отмечено словом «да». Встречается и «синхра» — это не «да», а
# пометка о характере сделки, и считать её подтверждением нельзя: молча
# проставить галочку «заведено» там, где её не ставили, хуже, чем не
# проставить. В предпросмотре такие строки видно.
YES = {"да", "yes", "истина", "true", "+", "1"}

MONEY_NOISE = ("\xa0", " ", " ", "₽", "$", "€", "руб.", "руб", "р.")
MAX_ROWS = 5000


@dataclass
class ImportRow:
    """Строка файла, приведённая к полям таблицы поступлений."""

    line: int
    sheet: str
    occurred_on: date | None = None
    partner_raw: str = ""
    description: str = ""
    amount: Decimal | None = None
    currency_amount: Decimal | None = None
    currency: str | None = None
    vat_rate: Decimal | None = None
    transfer_amount: Decimal | None = None
    transferred: bool = False
    problems: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _clean(value) -> str:
    return " ".join(str(value if value is not None else "").split())


def parse_money(value) -> Decimal | None:
    """«$16 803,73» → Decimal. Мусор вокруг числа отбрасываем, как в форме."""
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return Decimal(str(value))
    text = _clean(value).lower()
    for noise in MONEY_NOISE:
        text = text.replace(noise, "")
    text = text.replace(",", ".")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_date(value) -> date | None:
    """Дата из ячейки: настоящая дата, «03.07.2026» или «2026-07-03»."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _clean(value)
    if not text:
        return None
    for pattern in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    # «2026-07-01 14:22:18» — дата со временем, пришедшая строкой
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        return date(*map(int, match.groups()))
    return None


def vat_percent(value) -> Decimal | None:
    """
    НДС из файла → проценты. «1.22» → 22, «1» → 0, «22» → 22.

    См. пояснение в заголовке модуля: в этой таблице ставка записана
    коэффициентом, а у нас хранится процентами.
    """
    number = parse_money(value)
    if number is None:
        return None
    if number <= 2:
        return (number - Decimal(1)) * Decimal(100)
    return number


def _currency(value) -> str | None:
    key = _clean(value).lower().rstrip(".")
    return CURRENCIES.get(key)


def read_table(content: bytes, filename: str) -> list:
    """Файл → список (имя листа, строка). Excel читаем ПО ВСЕМ ЛИСТАМ."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        out = []
        for sheet in wb.sheetnames:
            for row in wb[sheet].iter_rows(values_only=True):
                out.append((sheet, list(row)))
        wb.close()
        return out
    # Текст из буфера обмена: Excel кладёт таблицу с табуляцией.
    text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
    return [("вставка", row) for row in csv.reader(io.StringIO(text), delimiter="\t")]


def parse_rows(content, filename: str) -> list:
    """
    Файл или вставка → строки поступлений.

    Строка без даты и без сумм пропускается молча: это шапка, подпись или
    пустая полоса между месяцами. А вот строка, где дата есть, но разобрать её
    не вышло, попадает в список с пометкой — молча терять деньги нельзя.
    """
    rows = []
    for line, (sheet, raw) in enumerate(read_table(content, filename), 1):
        if len(raw) < MIN_COLUMNS:
            continue
        cell = lambda i: raw[i] if i < len(raw) else None      # noqa: E731

        occurred_on = parse_date(cell(COL_DATE))
        amount = parse_money(cell(COL_AMOUNT))
        partner = _clean(cell(COL_PARTNER))
        if occurred_on is None and amount is None and not partner:
            continue                                   # пустая или служебная
        if occurred_on is None and str(_clean(cell(COL_DATE))).lower().startswith("дата"):
            continue                                   # шапка

        row = ImportRow(line=line, sheet=sheet)
        row.occurred_on = occurred_on
        row.partner_raw = partner
        row.description = _clean(cell(COL_DESCRIPTION))[:2000]
        row.amount = amount
        # ВАЛЮТНАЯ СУММА — ТОЛЬКО У ВАЛЮТНЫХ СТРОК. В файле колонка заполнена
        # всегда, но у рублёвых платежей она дословно повторяет сумму
        # поступления, и переносить её значило бы завести в таблице второе
        # такое же число «для справки» — справки в нём никакой.
        row.currency = _currency(cell(COL_CURRENCY))
        if row.currency and row.currency != "RUB":
            row.currency_amount = parse_money(cell(COL_CURRENCY_AMOUNT))
        else:
            row.currency = None
        row.vat_rate = vat_percent(cell(COL_VAT))
        row.transfer_amount = parse_money(cell(COL_TRANSFER))
        row.transferred = _clean(cell(COL_TRANSFERRED)).lower() in YES

        # Номер платёжного документа в нашей таблице отдельного поля не имеет,
        # но в описании он полезен: по нему строку находят в выписке.
        doc = _clean(cell(COL_DOC))
        if doc and doc not in row.description:
            row.description = (f"{doc} · {row.description}" if row.description else doc)[:2000]

        if row.occurred_on is None:
            row.problems.append("не разобрана дата поступления")
        if row.amount is None and row.transfer_amount is None:
            row.problems.append("нет ни суммы поступления, ни суммы завода")
        if row.vat_rate is not None and (row.vat_rate < 0 or row.vat_rate > 100):
            row.problems.append("ставка НДС вне 0–100%")
            row.vat_rate = None
        rows.append(row)
    return rows
