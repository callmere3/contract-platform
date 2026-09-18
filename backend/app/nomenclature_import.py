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

ДОЛИ И СТАВКИ — ПРОЦЕНТЫ 0–100. В файле они встречаются в двух видах, и
отличаются не величиной, а форматом ячейки: у Dista это процентный формат с
долей единицы внутри (0.8 = 80%), у файла, собранного руками, — обычное число
(70 = 70%). Решает формат; см. share_percent.

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

СВЕРКА ДОЛЕЙ ВЫКЛЮЧАЕТСЯ ТОЛЬКО ПРИ ИМПОРТЕ В неКАТАЛОГ (`check_sums=False`,
18.09.2026). Изъятые позиции приезжают из исторических списков, где доли с
общими не сходятся сплошь и рядом, и чинить их негде — в Dista этих треков уже
нет. Каталог проверяется строго, как и раньше: туда приезжают свежие выгрузки.

ЭТИ ЖЕ ПРАВИЛА ПРОВЕРЯЮТ РУЧНУЮ ПРАВКУ КАРТОЧКИ (`check_required` и
`check_shares`, вызываются из `routers_nomenclature.update_track`). Разойдись
они — и трек, который импорт принять отказывается, спокойно заводился бы
руками, чтобы назавтра быть затёртым тем же импортом.

Каталог и жанр в обязательные НЕ ВКЛЮЧЕНЫ намеренно, хотя формально стоят в
файле до правообладателей: в боевой выгрузке от 16.09.2026 жанр пуст у 95.6%
строк, общая ставка роялти — у 75.4%, каталог — у 22.5%. Требовать их значило
бы отвергать почти весь настоящий каталог.
"""
import csv
import io
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


def share_percent(value, percent_format: bool) -> Decimal | None:
    """
    Доля и ставка правообладателя → проценты (0–100).

    ВИДОВ ЗАПИСИ ТРИ, и отличаются они не величиной:
      - текст со знаком процента («80%») — так приходит вставка из буфера
        обмена: там нет ячеек, есть только то, что человек видел на экране;
      - выгрузка Dista: ячейка с процентным форматом («0%»), внутри лежит
        доля единицы — 1 значит 100%, 0.8 значит 80%;
      - файл, собранный руками: обычное число, и 100 значит 100%, 70 — 70%.

    Поэтому решает знак процента и формат ячейки, а не величина. Гадать по
    величине нельзя: 1 — это и 100%, и 1%, а вся разница между ними в
    оформлении. Так первый вариант импорта и сыпал предупреждениями на
    нормальном файле.
    """
    if value is None:
        return None
    raw = str(value).strip().replace(",", ".")
    if not raw:
        return None
    # Со знаком процента значение УЖЕ процент: так приходит текст из буфера
    # обмена («80%» — то, что человек видит в Excel и в гриде Dista), и
    # умножать его на сто нельзя, даже если ячейка была процентной.
    written_as_percent = raw.endswith("%")
    raw = raw.rstrip("%").strip()
    try:
        number = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if percent_format and not written_as_percent:
        number *= 100
    return number.quantize(Decimal("0.01"))


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


def _parse_rights(raw: tuple, percent_cols: set, row: Row) -> None:
    """Правообладатели строки. Пустой слот — норма, а не ошибка."""
    for right_type, slot, col_owner, col_share, col_royalty in RIGHT_SLOTS:
        owner = text(raw[col_owner], "owner")
        if not owner:
            continue
        share = share_percent(raw[col_share], col_share in percent_cols)
        royalty = share_percent(raw[col_royalty], col_royalty in percent_cols)
        label = RIGHT_LABELS[right_type]
        if share is None:
            row.errors.append(f"у {label} правообладателя «{owner}» не указана доля")
            continue
        if share > 100 or (royalty is not None and royalty > 100):
            row.errors.append(
                f"у {label} правообладателя «{owner}» доля или ставка больше 100%"
            )
            continue
        row.rights.append(
            {
                "right_type": right_type,
                "slot": slot,
                "owner": owner,
                "share": share,
                "royalty": royalty,
            }
        )


# Обязательные поля трека. Код/ISRC, автор слов и музыки и альбом сюда НЕ
# входят: у альбома, заведённого отдельным артикулом, ни кода, ни авторов нет,
# а сингл не входит ни в какой альбом. Каталог, жанр и общая ставка роялти —
# тоже: в боевой выгрузке они пусты у 22.5%, 95.6% и 75.4% строк.
REQUIRED_TRACK_FIELDS = (
    ("rights_since", "дата прав"),
    ("sku", "артикул"),
    ("title", "наименование"),
    ("artist", "исполнитель"),
    ("share_author", "доля авторских прав"),
    ("share_related", "доля смежных прав"),
)


def check_required(track: dict) -> list[str]:
    """
    Обязательные поля трека — ОДИН СПИСОК НА ДВА ВХОДА: файл и ручная правка
    карточки (17.09.2026).

    Разойдись они, и трек, который импорт отказывается принять, спокойно
    заводился бы руками, — а через день его снова затирал бы тот же импорт.
    """
    return [
        f"не заполнено обязательное поле: {label}"
        for key, label in REQUIRED_TRACK_FIELDS
        if track.get(key) is None
    ]


def check_shares(track: dict, rights: list) -> list[str]:
    """
    СВЕРКА ДОЛЕЙ СО СПРАВОЧНЫМИ: сумма долей правообладателей обязана
    совпадать с общей долей трека — отдельно по авторским и отдельно по
    смежным (правило владельца 17.09.2026).

    Виды прав независимы: у кавера фонограмма своя, а произведение чужое,
    поэтому складывать их доли между собой нельзя.

    Правило одно и то же для файла и для правки карточки руками — потому и
    живёт здесь, рядом с разбором файла, а не в роутере.
    """
    declared = {
        AUTHOR: track.get("share_author"),
        RELATED: track.get("share_related"),
    }
    problems = []
    for right_type, label in RIGHT_LABELS.items():
        total = sum(
            (r["share"] for r in rights if r["right_type"] == right_type),
            Decimal(0),
        )
        want = declared[right_type]
        if want is None:
            continue  # про пустую общую долю уже сказано в обязательных полях
        if total != want:
            problems.append(
                f"доли {label} прав не сходятся: общая {_num(want)}%, "
                f"у правообладателей {_num(total)}%"
            )
    return problems


def _num(value: Decimal) -> str:
    """100.00 → «100», 33.33 → «33.33»: в сообщении об ошибке нули мешают."""
    return f"{value:.2f}".rstrip("0").rstrip(".") or "0"


def parse_row(
    raw: tuple,
    row_num: int,
    percent_cols: set | None = None,
    check_sums: bool = True,
) -> Row | None:
    """
    Строка файла → разобранная строка с ошибками и предупреждениями.

    None — строку надо пропустить молча: она пустая или это шапка. Шапка
    встречается и ВНУТРИ файла: экспорт грида Dista подмешивает её к данным
    (в выгрузке от 16.09.2026 — один раз).
    """
    if raw is None or all(v is None for v in raw):
        return None
    percent_cols = percent_cols or set()
    if len(raw) < len(COLUMNS):
        raw = tuple(raw) + (None,) * (len(COLUMNS) - len(raw))

    sku = text(raw[COL_SKU], "sku")
    if sku == "Артикул" or text(raw[COL_TITLE]) == "Наименование":
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
        "share_author": share_percent(
            raw[COL_SHARE_AUTHOR], COL_SHARE_AUTHOR in percent_cols
        ),
        "share_related": share_percent(
            raw[COL_SHARE_RELATED], COL_SHARE_RELATED in percent_cols
        ),
        "catalog": text(raw[COL_CATALOG], "catalog"),
        "album": text(raw[COL_ALBUM], "album"),
        "genre": text(raw[COL_GENRE], "genre"),
        "royalty_percent": share_percent(raw[COL_ROYALTY], COL_ROYALTY in percent_cols),
        "rights_since": rights_since,
    }

    # Обязательные поля — общим списком (check_required): тот же, по которому
    # проверяется правка карточки руками.
    required_errors = check_required(row.track)
    if raw_date is not None and rights_since is None:
        # Про дату уже сказано точнее — «не прочиталась», а не «не заполнена».
        required_errors = [e for e in required_errors if "дата прав" not in e]
    row.errors.extend(required_errors)

    _parse_rights(raw, percent_cols, row)
    # СВЕРКА ДОЛЕЙ ОТКЛЮЧАЕМА, и ровно для одного случая — импорта в
    # неКаталог (просьба владельца 18.09.2026). Изъятые позиции приезжают из
    # исторических списков, где доли с общими не сходятся сплошь и рядом (в
    # боевом каталоге таких 48 тысяч строк), а чинить их негде: в Dista они
    # уже не живут. Требовать сходимости значило бы не дать залить список
    # вовсе. Для каталога правило остаётся строгим: туда приезжают свежие
    # выгрузки, и они его проходят.
    if check_sums:
        row.errors.extend(check_shares(row.track, row.rights))

    # Артикула нет — строку не на что записать, и все прочие претензии к ней
    # бессмысленны.
    if row.track.get("sku") is None:
        row.errors = ["не заполнено обязательное поле: артикул"]
    return row


def read_rows(worksheet, check_sums: bool = True):
    """
    Лист Excel → разобранные строки.

    Читаем ЯЧЕЙКАМИ, а не значениями: нужен ещё и формат — по нему видно,
    записана доля процентом («0%», внутри 0.8) или обычным числом (70).

    ШАПКУ УЗНАЁМ ПО СОДЕРЖИМОМУ, а не по номеру строки. Файл от Dista
    начинается с подписей колонок, а собранный руками — сразу с данных
    (пример владельца от 17.09.2026), и пропускать первую строку вслепую
    значит терять первый трек. Заодно так отсекается шапка, попавшая в
    середину файла: экспорт грида Dista её подмешивает.
    """
    for row_num, cells in enumerate(worksheet.iter_rows(), start=1):
        values = tuple(c.value for c in cells)
        percent_cols = {
            i for i, c in enumerate(cells) if "%" in (c.number_format or "")
        }
        parsed = parse_row(values, row_num, percent_cols, check_sums)
        if parsed is not None:
            yield parsed


def read_pasted(text_block: str, check_sums: bool = True):
    """
    Вставка из буфера обмена → разобранные строки.

    Excel и грид Dista кладут в буфер таблицу как ТЕКСТ С ТАБУЛЯЦИЯМИ: строки
    разделены переводом строки, ячейки — табуляцией, а ячейка с переводом
    строки внутри берётся в кавычки. Поэтому разбираем не split(), а
    csv-читателем: он про кавычки знает.

    Форматов ячеек тут нет и быть не может — в буфер попадает то, что человек
    видел на экране. Проценты поэтому приходят со знаком («80%»), и
    share_percent читает их как проценты.
    """
    rows = csv.reader(io.StringIO(text_block), delimiter="\t")
    for row_num, values in enumerate(rows, start=1):
        if not values:
            continue
        parsed = parse_row(
            tuple(v.strip() or None for v in values), row_num, set(), check_sums
        )
        if parsed is not None:
            yield parsed


class OwnerIndex:
    """
    Справочник известных имён правообладателей — чтобы узнавать своих и
    находить карточку контрагента, которой имя принадлежит.

    Строится из ДВУХ источников: титлов карточек контрагентов и имён, уже
    встречавшихся в каталоге. Контрагенты здесь главные — в боевом каталоге
    729 имён из 730 совпадают с титлом карточки буква в букву, — но и
    каталожные написания нужны: пока новое имя не завели карточкой, оно
    существует только там. У таких имён карточки нет, и `contragent_for`
    честно возвращает None.
    """

    def __init__(self, known_names, contragents=()):
        self.known = set()
        self.by_norm: dict[str, str] = {}
        # Имя → id карточки. Отдельно от by_norm: там любое известное
        # написание, здесь только те, за которыми стоит карточка.
        self.ids: dict[str, object] = {}
        self.ids_by_norm: dict[str, object] = {}
        for title, contragent_id in contragents:
            if not title:
                continue
            self.known.add(title)
            self.by_norm.setdefault(normalize_owner(title), title)
            self.ids.setdefault(title, contragent_id)
            self.ids_by_norm.setdefault(normalize_owner(title), contragent_id)
        for name in known_names:
            if not name:
                continue
            self.known.add(name)
            self.by_norm.setdefault(normalize_owner(name), name)

    def contragent_for(self, name: str):
        """
        Карточка, которой принадлежит имя: сперва точное совпадение с титлом,
        потом совпадение после нормализации («Князева А.А. (ИП)» против
        «Князева А. А. (ИП)» — разница в одном пробеле).

        Приблизительные совпадения (префикс, опечатка) СЮДА НЕ ВХОДЯТ: они
        годятся, чтобы спросить человека, но не чтобы молча привязать деньги
        к чужой карточке.
        """
        if name in self.ids:
            return self.ids[name]
        return self.ids_by_norm.get(normalize_owner(name))

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
