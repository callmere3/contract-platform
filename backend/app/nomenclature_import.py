"""
Разбор и проверка выгрузки номенклатуры Dista — общий для двух входов:
серверного скрипта `ops/import_tracks.py` и импорта из интерфейса
(`routers_nomenclature.py`).

ОДИН ЧИТАТЕЛЬ НА ДВА ВХОДА — не ради экономии строк. Разойдись они хоть в
одной мелочи (в округлении доли, в пропуске шапки, в том, какое поле
обязательно), и каталог, залитый скриптом, отличался бы от залитого из
интерфейса. Такое расхождение обнаруживается через месяцы и не чинится.

ФОРМАТ ФАЙЛА — ровно тот, что отдаёт Dista: 30 колонок, порядок жёсткий.
Читаем ПО НОМЕРАМ, а не по подписям: подписи в выгрузке нестабильны
(«Роялти(%) авт. прав 1» с пробелом против «Роялти авт.прав 2» без процента),
а порядок Dista держит.

ЧТО ПРОВЕРЯЕТСЯ (правила владельца 17.09.2026):
  - обязательны: дата прав, артикул, наименование, исполнитель и обе общие
    доли. Код/ISRC, автор слов и музыки, альбом — необязательны: у альбома,
    который заведён отдельным артикулом, ни кода, ни авторов нет, а сингл
    просто не входит в альбом;
  - второго и третьего правообладателя может не быть — это норма, а не
    ошибка. Слот без владельца просто пропускается;
  - СУММА ДОЛЕЙ ПРАВООБЛАДАТЕЛЕЙ ОБЯЗАНА СОВПАДАТЬ С ОБЩЕЙ ДОЛЕЙ трека, и
    считается это отдельно по каждому виду прав: смежные и авторские
    независимы.

Каталог и жанр в обязательные НЕ ВКЛЮЧЕНЫ намеренно, хотя формально стоят в
файле до правообладателей: в боевой выгрузке от 16.09.2026 жанр пуст у 95.6%
строк, общая ставка роялти — у 75.4%, каталог — у 22.5%. Требовать их значило
бы отвергать почти весь настоящий каталог.
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

# Подписи колонок — в порядке файла. Используются экспортом; импорт читает по
# номерам (см. шапку модуля).
COLUMNS = (
    "Дата прав",
    "Артикул",
    "Код/ISRC/UPC",
    "Наименование",
    "Исполнитель",
    "Автор слов/музыки",
    "Доля авторских прав",
    "Доля смежных прав",
    "Каталог",
    "Альбом",
    "Жанр",
    "Роялти",
    "Владелец авт.прав 1",
    "Доля(%) авт.прав 1",
    "Роялти(%) авт. прав 1",
    "Владелец авт.прав 2",
    "Доля авт.прав 2",
    "Роялти авт.прав 2",
    "Владелец смж.прав 1",
    "Доля смж.прав 1",
    "Роялти смж.прав 1",
    "Владелец смж.прав 2",
    "Доля смж.прав 2",
    "Роялти смж.прав 2",
    "Владелец авт.прав 3",
    "Доля авт.прав 3",
    "Роялти авт. прав 3",
    "Владелец смж.прав 3",
    "Доля смж.прав 3",
    "Роялти смж.прав 3",
)

COL_DATE = 0
COL_SKU = 1
COL_CODE = 2
COL_TITLE = 3
COL_ARTIST = 4
COL_AUTHORS = 5
COL_SHARE_AUTHOR = 6
COL_SHARE_RELATED = 7
COL_CATALOG = 8
COL_ALBUM = 9
COL_GENRE = 10
COL_ROYALTY = 11

AUTHOR = "author"
RELATED = "related"

# (вид права, слот, колонка владельца, колонка доли, колонка роялти).
# Третий слот стоит ПОСЛЕ вторых смежных — порядок колонок в выгрузке
# исторический, и читать его надо как есть.
RIGHT_SLOTS = (
    (AUTHOR, 1, 12, 13, 14),
    (AUTHOR, 2, 15, 16, 17),
    (AUTHOR, 3, 24, 25, 26),
    (RELATED, 1, 18, 19, 20),
    (RELATED, 2, 21, 22, 23),
    (RELATED, 3, 27, 28, 29),
)

RIGHT_LABELS = {AUTHOR: "авторских", RELATED: "смежных"}

# Пороги поиска похожих имён. MIN_PREFIX — с какой длины имя вообще можно
# считать началом другого; TYPO_RATIO — насколько строки должны быть похожи,
# чтобы счесть разницу опечаткой (0.9 ≈ одна-две буквы на среднем имени).
MIN_PREFIX = 4
TYPO_RATIO = 0.9

MAX_LEN = {
    "sku": 32,
    "code": 64,
    "title": 300,
    "artist": 300,
    "catalog": 255,
    "album": 300,
    "genre": 120,
    "owner": 255,
}


@dataclass
class Row:
    """Разобранная строка файла: что в ней, что с ней не так."""

    row_num: int
    track: dict
    rights: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def text(value, field_name: str | None = None) -> str | None:
    """Ячейка → строка без хвостовых пробелов; пустая → None."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if field_name and len(s) > MAX_LEN[field_name]:
        # Обрезаем, а не роняем строку: потерять хвост длинной подписи не так
        # страшно, как не импортировать трек. Случай попадает в warnings.
        s = s[: MAX_LEN[field_name]]
    return s


def decimal_percent(value) -> Decimal | None:
    """Общие доли и ставка трека лежат процентами: '100', '33,33', '80'."""
    if value is None:
        return None
    s = str(value).strip().replace(",", ".").replace("%", "")
    if not s:
        return None
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def fraction_percent(value) -> tuple[Decimal | None, bool]:
    """
    Доля и ставка правообладателя лежат ДОЛЯМИ ЕДИНИЦЫ: 1 = 100%, 0.8 = 80%.
    Приводим к процентам здесь, один раз: иначе на сто умножало бы каждое
    место показа, и однажды кто-нибудь забыл бы.

    Второй элемент ответа — «значение было больше единицы». Такое считаем уже
    процентом и не трогаем: если Dista сменит формат, каталог не должен молча
    получить доли по 8000%.
    """
    if value is None:
        return None, False
    try:
        number = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None, False
    if number > 1:
        return number.quantize(Decimal("0.01")), True
    return (number * 100).quantize(Decimal("0.01")), False


def parse_date(value) -> date | None:
    """
    Дата прав. Excel обычно отдаёт её датой, но не всегда: в файле, собранном
    руками или прошедшем через выгрузку-перезагрузку, она вполне может лежать
    строкой «01.09.2026». Читать надо оба вида — иначе наш же экспорт не
    заливается обратно, а симметрия файла с импортом в этом и состоит.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def normalize_owner(name: str) -> str:
    """
    Ключ для поиска дублей правообладателя.

    Убирает ровно то, чем дубли отличаются на практике (проверено на боевом
    каталоге: 11 групп таких пар): регистр, лишние пробелы и точки, скобки с
    формой собственности, саму форму («ИП Жартун» против «Жартун»), приписку
    KZ («MVR Compani (TOO) KZ»). Буква «ё» приравнивается к «е» — в базе
    встречаются оба написания одной фамилии.

    Нормализация НАМЕРЕННО грубая: она не решает, а ПОДСКАЗЫВАЕТ. Решение
    всегда за человеком — он видит оба написания и выбирает.
    """
    s = (name or "").lower().replace("ё", "е")
    s = re.sub(r"\(.*?\)", " ", s)  # (СГ), (ИП), (ТОО), (Ghetto Records)
    s = re.sub(r"\b(kz|кз)\b", " ", s)
    s = re.sub(r"\b(ип|ооо|тоо|оао|зао|ао|сг|сз|фл)\b", " ", s)
    s = re.sub(r"[.,\-–—«»\"'`]", " ", s)
    return re.sub(r"\s+", "", s)


def _parse_rights(raw: tuple, row: Row) -> None:
    """Правообладатели строки. Пустой слот — норма, а не ошибка."""
    for right_type, slot, col_owner, col_share, col_royalty in RIGHT_SLOTS:
        owner = text(raw[col_owner], "owner")
        if not owner:
            continue
        share, share_big = fraction_percent(raw[col_share])
        royalty, royalty_big = fraction_percent(raw[col_royalty])
        label = RIGHT_LABELS[right_type]
        if share is None:
            row.errors.append(f"у {label} правообладателя «{owner}» не указана доля")
            continue
        if share_big or royalty_big:
            row.warnings.append(
                f"доля или ставка «{owner}» больше единицы — прочитаны как проценты"
            )
        row.rights.append(
            {
                "right_type": right_type,
                "slot": slot,
                "owner": owner,
                "share": share,
                "royalty": royalty,
            }
        )


def _check_shares(row: Row) -> None:
    """
    Сумма долей правообладателей обязана совпадать с общей долей трека —
    отдельно по авторским и отдельно по смежным (владелец, 17.09.2026).

    Виды прав независимы: у кавера фонограмма своя, а произведение чужое,
    поэтому складывать их доли между собой нельзя.
    """
    declared = {
        AUTHOR: row.track.get("share_author"),
        RELATED: row.track.get("share_related"),
    }
    for right_type, label in RIGHT_LABELS.items():
        total = sum(
            (r["share"] for r in row.rights if r["right_type"] == right_type),
            Decimal(0),
        )
        want = declared[right_type]
        if want is None:
            continue  # про пустую общую долю уже сказано в обязательных полях
        if total != want:
            row.errors.append(
                f"доли {label} прав не сходятся: общая {_num(want)}%, "
                f"у правообладателей {_num(total)}%"
            )


def _num(value: Decimal) -> str:
    """100.00 → «100», 33.33 → «33.33»: в сообщении об ошибке нули мешают."""
    return f"{value:.2f}".rstrip("0").rstrip(".") or "0"


def parse_row(raw: tuple, row_num: int) -> Row | None:
    """
    Строка файла → разобранная строка с ошибками и предупреждениями.

    None — строку надо пропустить молча: она пустая или это шапка. Шапка
    встречается и ВНУТРИ файла: экспорт грида Dista подмешивает её к данным
    (в выгрузке от 16.09.2026 — один раз).
    """
    if raw is None or all(v is None for v in raw):
        return None
    if len(raw) < len(COLUMNS):
        raw = tuple(raw) + (None,) * (len(COLUMNS) - len(raw))

    sku = text(raw[COL_SKU], "sku")
    if sku == "Артикул" or (sku is None and text(raw[COL_TITLE]) == "Наименование"):
        return None

    row = Row(row_num=row_num, track={})
    raw_date = raw[COL_DATE]
    rights_since = parse_date(raw_date)
    if raw_date is not None and rights_since is None:
        row.errors.append(f"дата прав не прочиталась: «{text(raw_date)}»")

    row.track = {
        "sku": sku,
        "code": text(raw[COL_CODE], "code"),
        "title": text(raw[COL_TITLE], "title"),
        "artist": text(raw[COL_ARTIST], "artist"),
        "authors": text(raw[COL_AUTHORS]),
        "share_author": decimal_percent(raw[COL_SHARE_AUTHOR]),
        "share_related": decimal_percent(raw[COL_SHARE_RELATED]),
        "catalog": text(raw[COL_CATALOG], "catalog"),
        "album": text(raw[COL_ALBUM], "album"),
        "genre": text(raw[COL_GENRE], "genre"),
        "royalty_percent": decimal_percent(raw[COL_ROYALTY]),
        "rights_since": rights_since,
    }

    # Обязательные поля. Код/ISRC, автор слов и музыки и альбом сюда не
    # входят: у альбома, заведённого отдельным артикулом, кода и авторов нет,
    # а сингл не входит ни в какой альбом.
    required = (
        ("sku", "артикул"),
        ("title", "наименование"),
        ("artist", "исполнитель"),
        ("share_author", "доля авторских прав"),
        ("share_related", "доля смежных прав"),
    )
    for key, label in required:
        if row.track.get(key) is None:
            row.errors.append(f"не заполнено обязательное поле: {label}")
    if rights_since is None and raw_date is None:
        row.errors.append("не заполнено обязательное поле: дата прав")

    _parse_rights(raw, row)
    _check_shares(row)

    # Артикула нет — строку не на что записать, и все прочие претензии к ней
    # бессмысленны.
    if row.track.get("sku") is None:
        row.errors = ["не заполнено обязательное поле: артикул"]
    return row


def read_rows(worksheet):
    """Лист Excel → разобранные строки. Первая строка — шапка файла."""
    for row_num, raw in enumerate(worksheet.iter_rows(values_only=True), start=1):
        if row_num == 1:
            continue
        parsed = parse_row(raw, row_num)
        if parsed is not None:
            yield parsed


class OwnerIndex:
    """
    Справочник известных имён правообладателей — чтобы узнавать своих.

    Строится из ДВУХ источников: титлов карточек контрагентов и имён, уже
    встречавшихся в каталоге. Контрагенты здесь главные — в боевом каталоге
    724 имени из 729 совпадают с титлом карточки буква в букву, — но и
    каталожные написания нужны: пока новое имя не завели карточкой, оно
    существует только там.
    """

    def __init__(self, known_names):
        self.known = set()
        self.by_norm: dict[str, str] = {}
        for name in known_names:
            if not name:
                continue
            self.known.add(name)
            self.by_norm.setdefault(normalize_owner(name), name)

    def match(self, name: str) -> tuple[str, str | None]:
        """
        Что мы знаем об имени из файла:
          ('exact', None)          — такое имя уже есть;
          ('similar', 'как у нас') — похоже на существующее — предложить замену;
          ('new', None)            — не видели, это новый правообладатель.

        Похожесть ищется тремя способами подряд, от точного к вольному:
          1. совпало после нормализации — разный регистр, пробелы, точки,
             форма собственности, приписка KZ («ИП Анненков М.В.» против
             «Анненков М.В. (ИП)»);
          2. одно имя — начало другого («ИП Погорельских» против
             «Погорельских А.А. (ИП)»: в карточке есть инициалы, в выгрузке
             нет);
          3. отличается на опечатку — сравнение по похожести строк
             («Густ Мьюзик» против «Густ Мьюзик»).

        Всё это ПОДСКАЗКА, а не решение: замену подтверждает человек, который
        видит оба написания. Поэтому пороги выбраны щедро — лучше лишний раз
        спросить, чем завести двойника, которого потом ищут по всему каталогу.
        """
        if name in self.known:
            return "exact", None

        norm = normalize_owner(name)
        if not norm:
            return "new", None

        exact_norm = self.by_norm.get(norm)
        if exact_norm:
            return "similar", exact_norm

        # Одно имя — начало другого. Короче четырёх букв не смотрим: на таких
        # огрызках совпадает что угодно.
        if len(norm) >= MIN_PREFIX:
            for other_norm, other in self.by_norm.items():
                if len(other_norm) < MIN_PREFIX:
                    continue
                if norm.startswith(other_norm) or other_norm.startswith(norm):
                    return "similar", other

        best, best_ratio = None, 0.0
        for other_norm, other in self.by_norm.items():
            # SequenceMatcher дорог, а имён в базе сотни: сначала отсекаем по
            # длине — опечатка не меняет длину строки вдвое.
            if abs(len(other_norm) - len(norm)) > 3:
                continue
            ratio = SequenceMatcher(None, norm, other_norm).ratio()
            if ratio > best_ratio:
                best, best_ratio = other, ratio
        if best is not None and best_ratio >= TYPO_RATIO:
            return "similar", best
        return "new", None
