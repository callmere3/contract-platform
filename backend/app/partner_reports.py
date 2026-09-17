"""
Разбор отчётов площадок (ML Finance → «Отчёты партнёров»).

ЗАЧЕМ ЭТО ВООБЩЕ: у каждой площадки свой файл. Где-то суммы авторских и
смежных лежат отдельными колонками, где-то есть только общая сумма и её надо
поделить, где-то сумма с НДС. В Dista это решалось строкой-формулой вида
`-;-;АРТИКУЛ;-;-;-;КОЛИЧЕСТВО;…` — то есть КОЛОНКИ ПО НОМЕРАМ, с пропусками
через точку с запятой. Стоит площадке переставить столбцы — формула молча
разъезжается, и это ровно то, от чего владелец просил уйти (17.09.2026).

ПОЭТОМУ ЗДЕСЬ КОЛОНКИ ИЩУТСЯ ПО НАЗВАНИЮ. Правило разбора — это «какой
столбец чем является», по именам из шапки, плюс при необходимости формула.
Переставили столбцы местами — разбор не заметит; переименовали — скажет, что
колонки нет, вместо того чтобы взять соседнюю.

ЧТО НА ВЫХОДЕ — ОДИН ФОРМАТ ДЛЯ ВСЕХ: артикул, количество, сумма авторских,
сумма смежных. Дальше по этим четырём числам считается роялти, и расчёту
незачем знать, как выглядел исходный файл (просьба владельца: «свести всё к
одному формату»).

УСТРОЙСТВО ПРАВИЛА (JSON в partner_report_rules.mapping):

    {
      "sku":            {"column": "Артикул"},
      "quantity":       {"column": "Количество"},
      "amount_author":  {"column": "Сумма авт."},
      "amount_related": {"formula": "[Сумма] - [Сумма авт.]"},
      "title":          {"column": "Наименование"}
    }

`column` — взять как есть, `formula` — посчитать по другим колонкам. Формула
намеренно бедная: числа, скобки, + - * / и ссылки на колонки в квадратных
скобках. Это не язык программирования в отчёте, а «сумма минус смежные»;
всё, что сложнее, лучше решать правилом, а не выражением.

НДС снимается ставкой (`vat_rate`), а не формулой в каждой колонке: «сумма с
НДС 20%» — свойство отчёта целиком, и повторять `/1.2` в двух местах значит
однажды поправить одно и забыть второе.
"""
import ast
import csv
import io
import re
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

import openpyxl

# Поля единого формата. `title` необязателен и нужен только человеку — чтобы в
# предпросмотре было видно, что за трек, если артикул не опознан.
MONEY_FIELDS = ("amount_author", "amount_related")
FIELDS = ("sku", "title", "quantity", *MONEY_FIELDS)
FIELD_LABELS = {
    "sku": "Артикул",
    "title": "Наименование",
    "quantity": "Количество",
    "amount_author": "Сумма авторских",
    "amount_related": "Сумма смежных",
}
# Без артикула строку не к чему привязать, без сумм она бессмысленна. Остальное
# необязательно: количество есть не во всех отчётах, название — тем более.
REQUIRED_FIELDS = ("sku",)

# Слова, по которым узнаётся ИТОГОВАЯ строка в конце отчёта. У МТС это
# «Итого:», «НДС 22%:», «Итого с НДС:» — строки без кода объекта, но с суммой в
# колонке денег. Не отсечь их значит посчитать выручку дважды и получить
# «строку без артикула» на весь отчёт.
#
# Признак — ВМЕСТЕ: нет артикула И где-то в строке стоит одно из этих слов.
# По одному слову нельзя: «Итого» законно встречается и в названии трека.
TOTALS_MARKERS = ("итого", "всего", "total", "ндс", "vat")

# Сколько первых строк просматриваем в поисках шапки. У площадок сверху бывает
# шапка-описание на несколько строк (в отчёте МТС, например, данные начинаются
# с восьмой), но не на полсотни.
MAX_HEADER_SCAN = 30

# ТОЧНОСТЬ СТРОКИ — ЧЕТЫРЕ ЗНАКА, а не копейки. Площадки считают дробно (у МТС
# строка «147.0456»), и округление каждой строки до копеек увело итог отчёта на
# 84 копейки от их же «Итого» — на 668 строках набежало. Округляем ОДИН РАЗ, на
# итогах: сверять с платежом человек будет именно их.
PRECISION = Decimal("0.0001")
CENTS = Decimal("0.01")


@dataclass
class ReportRow:
    """Строка отчёта, приведённая к единому формату."""

    row_num: int
    sku: str | None = None
    # Строка без артикула НЕ ошибка разбора: в отчёте МТС таких два десятка —
    # у площадки не проставлен код объекта. Деньги по ним пришли, и молча
    # выкинуть их нельзя; они грузятся и видны отдельным счётчиком.
    title: str | None = None
    quantity: Decimal | None = None
    amount_author: Decimal = Decimal(0)
    amount_related: Decimal = Decimal(0)
    problems: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass
class ParseResult:
    """Разобранный файл: шапка, строки, итоги и всё, что пошло не так."""

    columns: list
    header_row: int
    rows: list
    problems: list = field(default_factory=list)

    @property
    def totals(self) -> dict:
        # Суммы — по ВСЕМ строкам, а не только по беспроблемным: деньги в
        # отчёте есть, даже если у строки нет артикула, и итог должен сходиться
        # с платежом площадки.
        return {
            "rows": len(self.rows),
            "ok_rows": sum(1 for r in self.rows if r.ok),
            "no_sku": sum(1 for r in self.rows if not r.sku),
            "problem_rows": sum(1 for r in self.rows if r.problems),
            "quantity": sum((r.quantity or Decimal(0) for r in self.rows), Decimal(0)),
            "amount_author": rubles(sum((r.amount_author for r in self.rows), Decimal(0))),
            "amount_related": rubles(sum((r.amount_related for r in self.rows), Decimal(0))),
        }


# --------------------------------------------------------------------- чтение


def read_table(content: bytes, filename: str, sheet: str | None = None) -> list:
    """
    Файл → таблица (список строк, каждая — список ячеек).

    Excel и текст читаются по-разному, но дальше разбор один: правило не
    должно зависеть от того, прислала площадка .xlsx или .csv.
    """
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        ws = wb[sheet] if sheet and sheet in wb.sheetnames else wb[wb.sheetnames[0]]
        return [list(row) for row in ws.iter_rows(values_only=True)]

    text = content.decode("utf-8-sig", errors="replace")
    # Разделитель угадываем по первой непустой строке: у площадок встречаются
    # и табуляция, и точка с запятой, и запятая.
    sample = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = max(("\t", ";", ","), key=sample.count) if sample else ","
    return [list(row) for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def sheet_names(content: bytes, filename: str) -> list:
    """Листы книги — для выбора в интерфейсе. Для текста список пуст."""
    if not (filename or "").lower().endswith((".xlsx", ".xlsm")):
        return []
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    return list(wb.sheetnames)


def _clean(value) -> str:
    return " ".join(str(value if value is not None else "").split())


def normalize_header(value) -> str:
    """
    Ключ сравнения названий колонок: регистр и лишние пробелы значения не
    имеют, как и точки в сокращениях («Сумма авт.» и «Сумма авт»).
    """
    return _clean(value).lower().replace("ё", "е").rstrip(".").strip()


def guess_header_row(table: list) -> int:
    """
    Где шапка, если правила ещё нет: самая «широкая» текстовая строка сверху.

    Нужна ровно для первого файла нового партнёра — показать человеку список
    колонок, чтобы он собрал правило. Дальше шапку находят по именам из
    правила (find_header_row), и гадать больше не приходится.

    Считаем непустые ячейки и требуем, чтобы это был текст: у шапки их больше
    всего, а строки с данными начинаются ниже и часто содержат числа.
    """
    best_row, best_score = 0, -1
    for i, row in enumerate(table[:MAX_HEADER_SCAN]):
        cells = [c for c in row if _clean(c)]
        if len(cells) < 2:
            continue
        texts = sum(1 for c in cells if not isinstance(c, (int, float)) and parse_number(c) is None)
        score = texts * 10 + len(cells)
        if score > best_score:
            best_row, best_score = i, score
    return best_row


def read_columns(content: bytes, filename: str, sheet: str | None = None) -> tuple:
    """Названия колонок файла и номер строки с шапкой (0-based)."""
    table = read_table(content, filename, sheet)
    header_row = guess_header_row(table)
    columns = [_clean(c) for c in (table[header_row] if header_row < len(table) else [])]
    return columns, header_row


def find_header_row(table: list, wanted: list) -> int:
    """
    Номер строки с шапкой (0-based) — та, где нашлось больше всего нужных
    названий. Ищем по СОДЕРЖИМОМУ, а не по номеру: у площадок сверху бывает
    описание на несколько строк, и число этих строк меняется от файла к файлу.
    """
    wanted_keys = {normalize_header(w) for w in wanted if w}
    best_row, best_hits = 0, -1
    for i, row in enumerate(table[:MAX_HEADER_SCAN]):
        keys = {normalize_header(c) for c in row if _clean(c)}
        hits = len(wanted_keys & keys)
        if hits > best_hits:
            best_row, best_hits = i, hits
        if hits == len(wanted_keys) and wanted_keys:
            break
    return best_row


# ------------------------------------------------------------------- значения


def parse_number(value) -> Decimal | None:
    """
    Число из ячейки: и 1234.56 из Excel, и «1 234,56», и «1,234.56».

    Разделитель решается ПОСЛЕДНИМ знаком: в «1 234,56» это запятая, в
    «1,234.56» — точка. Гадать по стране бессмысленно — отчёты приходят и от
    российских площадок, и от зарубежных.
    """
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    raw = _clean(value).replace(" ", "").replace(" ", "")
    if not raw:
        return None
    raw = raw.replace("−", "-")          # минус из Word, не ASCII
    last_comma, last_dot = raw.rfind(","), raw.rfind(".")
    if last_comma > last_dot:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", "")
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


_FORMULA_REF = re.compile(r"\[([^\]]+)\]")
_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div,
    ast.USub, ast.UAdd, ast.Constant, ast.Name, ast.Load,
)


def formula_columns(expr: str) -> list:
    """Какие колонки упомянуты в формуле — чтобы проверить их наличие заранее."""
    return [m.strip() for m in _FORMULA_REF.findall(expr or "")]


def eval_formula(expr: str, values: dict):
    """
    Значение формулы вида «[Сумма] - [Сумма авт.]».

    Разрешены только числа, скобки и четыре действия: это не язык в отчёте, а
    способ получить сумму, которой в файле нет отдельной колонкой. Всё
    остальное (вызовы, атрибуты, имена) отвергается разбором, а не проверкой
    строки регуляркой — регулярка ловит то, о чём догадался автор, а список
    разрешённых узлов ловит всё остальное по умолчанию.

    None — если хоть одно слагаемое пустое: складывать «нет данных» с числом
    нельзя, такую строку честнее показать проблемной.
    """
    names = {}
    def replace(match):
        key = match.group(1).strip()
        var = "c%d" % len(names)
        names[var] = values.get(normalize_header(key))
        return var

    code = _FORMULA_REF.sub(replace, expr or "")
    if any(v is None for v in names.values()):
        return None
    try:
        tree = ast.parse(code, mode="eval")
    except SyntaxError:
        raise ValueError(f"не разобрать формулу: {expr!r}")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"в формуле нельзя использовать {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in names:
            raise ValueError(f"неизвестное имя в формуле: {node.id}")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise ValueError("в формуле допустимы только числа")
    env = {k: Decimal(str(v)) for k, v in names.items()}
    try:
        return eval(compile(tree, "<formula>", "eval"), {"__builtins__": {}}, env)  # noqa: S307
    except (ZeroDivisionError, InvalidOperation):
        return None


def money(value) -> Decimal:
    """Сумма строки — до четвёртого знака (см. PRECISION)."""
    return (value or Decimal(0)).quantize(PRECISION, rounding=ROUND_HALF_UP)


def rubles(value) -> Decimal:
    """Итог — до копейки: столько и переводят."""
    return (value or Decimal(0)).quantize(CENTS, rounding=ROUND_HALF_UP)


# -------------------------------------------------------------------- разбор


def mapping_columns(mapping: dict) -> list:
    """Все названия колонок, которые упоминает правило (прямо или в формуле)."""
    out = []
    for spec in (mapping or {}).values():
        if not isinstance(spec, dict):
            continue
        if spec.get("column"):
            out.append(spec["column"])
        out.extend(formula_columns(spec.get("formula", "")))
    return out


def parse_report(
    content: bytes,
    filename: str,
    mapping: dict,
    vat_rate=None,
    sheet: str | None = None,
    limit: int | None = None,
) -> ParseResult:
    """
    Файл площадки → строки единого формата.

    `vat_rate` — ставка НДС, которую надо ВЫЧЕСТЬ из сумм (20 → делим на 1.2).
    Свойство отчёта целиком, а не отдельной колонки: в одном файле сумма либо
    с налогом, либо без.

    `limit` — сколько строк разобрать (для предпросмотра). Итоги считаются по
    разобранному, и в предпросмотре это честно подписано.
    """
    table = read_table(content, filename, sheet)
    wanted = mapping_columns(mapping)
    # Пустое правило — шапку ищем по виду строки, а не по именам: именно так
    # читается первый файл нового партнёра, для которого правила ещё нет.
    header_row = find_header_row(table, wanted) if wanted else guess_header_row(table)
    columns = [_clean(c) for c in (table[header_row] if header_row < len(table) else [])]
    by_key = {}
    for i, name in enumerate(columns):
        if name:
            by_key.setdefault(normalize_header(name), i)

    result = ParseResult(columns=columns, header_row=header_row, rows=[])

    missing = sorted({c for c in wanted if normalize_header(c) not in by_key})
    if missing:
        result.problems.append(
            "в файле нет колонок: " + ", ".join(f"«{c}»" for c in missing)
        )
        return result
    for key in REQUIRED_FIELDS:
        if not (mapping or {}).get(key):
            result.problems.append(f"в правиле не задано поле «{FIELD_LABELS[key]}»")
            return result

    divisor = Decimal(1)
    if vat_rate:
        divisor = Decimal(1) + Decimal(str(vat_rate)) / Decimal(100)

    data = table[header_row + 1:]
    if limit is not None:
        data = data[:limit]

    for offset, raw in enumerate(data):
        row_num = header_row + 2 + offset        # как в Excel: с единицы, с шапкой
        if all(_clean(c) == "" for c in raw):
            continue
        values = {}
        for key, index in by_key.items():
            values[key] = raw[index] if index < len(raw) else None

        row = ReportRow(row_num=row_num)
        row.sku = _clean(values.get(normalize_header(mapping["sku"].get("column", "")))) or None
        title_spec = (mapping or {}).get("title") or {}
        if title_spec.get("column"):
            row.title = _clean(values.get(normalize_header(title_spec["column"]))) or None

        numbers = {k: parse_number(v) for k, v in values.items()}

        qty_spec = (mapping or {}).get("quantity") or {}
        if qty_spec.get("column"):
            row.quantity = numbers.get(normalize_header(qty_spec["column"]))
        elif qty_spec.get("formula"):
            row.quantity = _apply_formula(qty_spec["formula"], numbers, row, "количество")

        for money_key in MONEY_FIELDS:
            spec = (mapping or {}).get(money_key) or {}
            value = None
            if spec.get("column"):
                value = numbers.get(normalize_header(spec["column"]))
                if value is None and _clean(values.get(normalize_header(spec["column"]))):
                    row.problems.append(
                        f"{FIELD_LABELS[money_key].lower()}: «"
                        f"{_clean(values.get(normalize_header(spec['column'])))}» — это не число"
                    )
            elif spec.get("formula"):
                value = _apply_formula(
                    spec["formula"], numbers, row, FIELD_LABELS[money_key].lower()
                )
            setattr(row, money_key, money((value or Decimal(0)) / divisor))

        # Итоговая строка в конце файла — не данные: пропускаем целиком, иначе
        # её сумма удвоит отчёт.
        if not row.sku:
            text = " ".join(_clean(c).lower() for c in raw)
            if any(marker in text for marker in TOTALS_MARKERS):
                continue
        result.rows.append(row)

    return result


def _apply_formula(expr: str, numbers: dict, row: ReportRow, label: str):
    try:
        value = eval_formula(expr, numbers)
    except ValueError as exc:
        row.problems.append(f"{label}: {exc}")
        return None
    if value is None:
        row.problems.append(f"{label}: в формуле пустое значение")
    return value


MONTHS_RU = (
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
)
QUARTERS_RU = ("I", "II", "III", "IV")


def period_label(start, end) -> str:
    """
    Подпись периода отчёта: «Июль 2026», «III кв. 2026» или «01.06.2026 —
    15.07.2026».

    Собирает СЕРВЕР, как и подпись периода у поступлений: формат — правило, и
    разъезжаться ему между экраном, списком и будущей выгрузкой незачем.
    Месяц и квартал узнаются по датам, а не хранятся отдельным признаком:
    признак пришлось бы поддерживать в согласии с датами, а даты и так всё
    говорят.
    """
    if start is None or end is None:
        return ""
    import calendar

    last_day = calendar.monthrange(end.year, end.month)[1]
    whole_months = start.day == 1 and end.day == last_day and start.year == end.year
    if whole_months and start.month == end.month:
        return f"{MONTHS_RU[start.month - 1]} {start.year}"
    if whole_months and (start.month - 1) % 3 == 0 and end.month == start.month + 2:
        return f"{QUARTERS_RU[(start.month - 1) // 3]} кв. {start.year}"
    return f"{start:%d.%m.%Y} — {end:%d.%m.%Y}"


def suggest_mapping(columns: list) -> dict:
    """
    Догадка о правиле по названиям колонок — чтобы человеку не заполнять
    четыре поля с нуля на каждом новом партнёре.

    Это ПОДСКАЗКА: правило всё равно подтверждает человек, глядя на
    предпросмотр. Поэтому список синонимов короткий и без фантазии — то, что
    реально встречается в отчётах площадок.
    """
    hints = {
        "sku": ("артикул", "код", "sku", "код товара", "№", "номер"),
        "title": ("наименование", "название", "трек", "title", "track"),
        "quantity": ("количество", "прослушивания", "quantity", "streams", "кол-во"),
        "amount_author": ("сумма авт", "авторские", "сумма авторских", "author"),
        "amount_related": ("сумма смж", "смежные", "сумма смежных", "related", "master"),
    }
    mapping = {}
    used = set()
    for field_name, words in hints.items():
        for column in columns:
            key = normalize_header(column)
            if not key or column in used:
                continue
            if any(key == w or key.startswith(w) for w in words):
                mapping[field_name] = {"column": column}
                used.add(column)
                break
    return mapping
