"""
Подготовка контекста для сложных шаблонов (шаг 2.2).

Часть значений в приложении нельзя просто взять из формы — они вычисляются
из введённых данных. Например, сноска про ненормативную лексику зависит от
того, у каких именно треков стоит галочка НЛ. Эта логика живёт здесь, а не
в шаблоне: шаблон должен оставаться максимально простым и выводить готовые
строки через {{ profanity_note }}.

Функция build_context() принимает "сырые" данные от оператора и возвращает
готовый словарь для docxtpl.
"""
import re
from datetime import date as _date


def build_initials(full_name: str) -> str:
    """
    Извлекает инициалы из полного ФИО для номера договора.

        'Иванов Иван Иванович' -> 'ИИИ'
        'Ким Игорь'            -> 'КИ'   (без отчества)

    Берутся первые буквы каждого слова: фамилия, имя, отчество.
    """
    parts = [p for p in full_name.split() if p]
    return "".join(p[0].upper() for p in parts)


def build_contract_number(
    day: str,
    month: str,
    year: str,
    full_name: str,
    doc_kind: str = "СГ",
) -> str:
    """
    Собирает номер договора формата 'МЛ-01/01/26-ИИИ/СГ'.

        day       — день заключения договора, две цифры: '01'
        month     — месяц заключения договора, две цифры: '01'
        year      — год двумя цифрами: '26'
        full_name — ФИО контрагента (инициалы вычисляются автоматически)
        doc_kind  — тип договора: 'СГ' (самозанятый гражданин) и т.п.

    Для приложений и актов номер берётся из договора того же контрагента —
    отдельно вводить день/месяц не нужно, если номер известен (см. build_context).
    """
    initials = build_initials(full_name)
    # нормализуем к двум цифрам: 1 -> 01
    day = str(day).zfill(2)
    month = str(month).zfill(2)
    return f"МЛ-{day}/{month}/{year}-{initials}/{doc_kind}"


def build_name_short(full_name: str) -> str:
    """
    'Иванов Иван Иванович' -> 'И.И. Иванов'  (для строки подписи)
    """
    parts = [p for p in full_name.split() if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    surname = parts[0]
    inits = ".".join(p[0].upper() for p in parts[1:])
    return f"{inits}. {surname}"


MONTHS_RU = {
    "января": "01", "февраля": "02", "марта": "03", "апреля": "04",
    "мая": "05", "июня": "06", "июля": "07", "августа": "08",
    "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12",
}


MONTHS_RU_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def parse_date(value: str) -> tuple[str, str, str] | None:
    """
    Разбирает дату в любом из поддерживаемых форматов.
    Возвращает (день, месяц, год) строками с ведущими нулями: ('15','03','2026').

        '2026-03-15'          -> ('15','03','2026')   # из <input type="date">
        '«15» марта 2026 г.'  -> ('15','03','2026')
        '15.03.2026'           -> ('15','03','2026')

    Дата — единственный источник правды: из неё выводятся и номер договора
    (день/месяц/год), и текстовое представление в документе. Так они
    не могут разойтись.

    Возвращает None, если распознать не удалось.
    """
    if not value:
        return None
    value = value.strip()

    # ISO: 2026-03-15 (то, что присылает <input type="date">)
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
    if m:
        return m.group(3), m.group(2), m.group(1)

    # «15» марта 2026 г.
    m = re.search(r"«?(\d{1,2})»?\s+([а-яё]+)\s+(\d{4})", value, re.IGNORECASE)
    if m:
        month = MONTHS_RU.get(m.group(2).lower())
        if month:
            return m.group(1).zfill(2), month, m.group(3)

    # 15.03.2026 или 15/03/2026
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b", value)
    if m:
        return m.group(1).zfill(2), m.group(2).zfill(2), m.group(3)

    return None


def format_date_ru(value: str) -> str:
    """
    Приводит дату к виду, который печатается в документе:
        '2026-03-15' -> '«15» марта 2026 г.'

    Если дата не распознана, возвращает исходную строку как есть —
    чтобы оператор мог вписать нестандартный текст вручную.
    """
    parsed = parse_date(value)
    if not parsed:
        return value
    day, month, year = parsed
    month_name = MONTHS_RU_GENITIVE[int(month) - 1]
    return f"«{day}» {month_name} {year} г."


def parse_day_month(c_date: str) -> tuple[str, str] | None:
    """
    Совместимость: извлекает только день и месяц.
    Новый код должен использовать parse_date().
    """
    parsed = parse_date(c_date)
    return (parsed[0], parsed[1]) if parsed else None


def contract_date_iso(contract: str) -> str:
    """
    Извлекает дату договора из его номера в формате
    'МЛ-ДД/ММ/ГГ-ИИИ/СГ' (см. build_contract_number) и возвращает
    её в ISO ('2026-03-15'), чтобы прогнать дальше через
    parse_date()/format_date_ru() как обычную дату.

    Год в номере — две цифры; все договоры заключены в 2000+ году,
    поэтому 'ГГ' -> '20ГГ' без дополнительных уточнений.

    Используется для Приложения/Акта: номер договора вводится вручную
    (см. build_context), а дата ЭТОГО договора в нём уже зашита — вводить
    её отдельно не нужно, только повод для расхождения между номером
    и датой в тексте документа.

    '' , если номер не в ожидаемом формате (например, ещё не введён).
    """
    m = re.search(r"(\d{2})/(\d{2})/(\d{2})", contract or "")
    if not m:
        return ""
    day, month, yy = m.groups()
    return f"20{yy}-{month}-{day}"


def build_profanity_note(tracks: list[dict]) -> str:
    """
    Формирует текст сноски про ненормативную лексику.

    Логика (по требованиям юриста):
      - ни у одного трека нет НЛ  -> "нет"
      - у всех треков есть НЛ      -> "да"
      - частично                    -> "№1, 3 – нет, №2, 4 – да"
    """
    with_nl = [i + 1 for i, t in enumerate(tracks) if t.get("has_profanity")]
    without_nl = [i + 1 for i, t in enumerate(tracks) if not t.get("has_profanity")]

    if not with_nl:
        return "нет"
    if not without_nl:
        return "да"

    parts = []
    if without_nl:
        nums = ", ".join(f"№{n}" if i == 0 else str(n) for i, n in enumerate(without_nl))
        parts.append(f"{nums} – нет")
    if with_nl:
        nums = ", ".join(f"№{n}" if i == 0 else str(n) for i, n in enumerate(with_nl))
        parts.append(f"{nums} – да")
    return ", ".join(parts)


def _normalize_performers(raw_performers, is_group: bool = False) -> list[dict]:
    """
    Приводит исполнителей к списку {'nickname': ..., 'fio': ...},
    убирая дубли.

    Форма присылает list-поля как список объектов:
        [{"nickname": "IVAN", "fio": "Иванов И.И."}, ...]
    Поддерживается и старый вид (только ФИО строкой) — для обратной
    совместимости с кодом/тестами, где никнейм не передавали.

    Составной никнейм: в столбце «Исполнитель» таблицы треков запятая —
    всегда разделитель исполнителей («IVAN, PETROV» = два исполнителя),
    имён с запятой внутри не бывает. Обычно фронтенд уже расщепляет их
    по строкам, но если составной никнейм всё же дошёл сюда (например,
    из API напрямую), расщепляем его и здесь — каждый получает то же ФИО.
    В режиме группы никнейм — это название группы, его не расщепляем.

    Дедупликация: если у нескольких треков один и тот же исполнитель,
    в сноске он должен встретиться один раз.
      - обычный режим: ключ — никнейм (регистронезависимо), иначе ФИО.
        «2 трека одного исполнителя» дают одну запись.
      - режим группы (is_group=True): у всех участников никнейм общий
        (название группы), различаются они по ФИО — поэтому ключ здесь
        ФИО, иначе участники схлопнулись бы в одного.
    Сохраняется первое вхождение, порядок не меняется.
    """
    if not raw_performers:
        return []

    # разворачиваем составные никнеймы в отдельные записи (обычный режим)
    expanded = []
    for p in raw_performers:
        if isinstance(p, dict):
            nickname = str(p.get("nickname", "")).strip()
            fio = str(p.get("fio", "")).strip()
        elif p:
            nickname, fio = "", str(p).strip()
        else:
            continue
        if not is_group and "," in nickname:
            for part in nickname.split(","):
                part = part.strip()
                if part:
                    expanded.append((part, fio))
        else:
            expanded.append((nickname, fio))

    result = []
    seen = set()
    for nickname, fio in expanded:
        if not (nickname or fio):
            continue
        if is_group:
            key = fio.casefold() if fio else nickname.casefold()
        else:
            key = nickname.casefold() if nickname else fio.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append({"nickname": nickname, "fio": fio})
    return result


def build_performer_note(
    performers: list[dict],
    nickname: str | None = None,
    is_group: bool = False,
) -> str:
    """
    Формирует сноску про исполнителей (всегда присутствует).

    performers — список словарей {'nickname', 'fio'} (см. _normalize_performers),
    уже без дублей. Заполняется из уникальных исполнителей таблицы треков
    (колонка «Исполнитель» = никнейм), ФИО оператор дописывает вручную.

    Обычный режим (is_group=False) — формат "никнейм - ФИО" построчно:
      - один исполнитель      -> "Исполнитель: IVAN - Иванов И.И."
      - несколько             -> "Исполнители: IVAN - Иванов И.И.; PETROV - Петров П.П."

    Режим группы (is_group=True) — название группы берётся из никнейма
    (тот же столбец «Исполнитель» в треках), ФИО участников перечисляются:
      - "Исполнители в составе группы «THE X»: Иванов И.И., Петров П.П."
    """
    if not performers:
        return "Исполнитель: —"

    if is_group:
        # Название группы — из никнейма (столбец «Исполнитель» в треках).
        # У группы он общий, после дедупликации остаётся один; берём первый
        # непустой на случай, если оператор ввёл его не в каждой строке.
        group_name = next(
            (p["nickname"] for p in performers if p["nickname"]),
            nickname or "",
        )
        fios = ", ".join(p["fio"] for p in performers if p["fio"])
        if group_name:
            return f"Исполнители в составе группы «{group_name}»: {fios}"
        return f"Исполнители в составе группы: {fios}"

    if len(performers) == 1:
        p = performers[0]
        fio = p["fio"]
        nick = p["nickname"] or nickname or ""
        if nick:
            return f"Исполнитель: {nick} - {fio}"
        return f"Исполнитель: {fio}"

    pairs = [f"{p['nickname'] or '—'} - {p['fio']}" for p in performers]
    return f"Исполнители: {'; '.join(pairs)}"


# Даты окончания квартала — по требованию юриста Срок указывается
# до конца соответствующего квартала
QUARTER_ENDS = {
    1: "31 марта",
    2: "30 июня",
    3: "30 сентября",
    4: "31 декабря",
}


# --- Роялти прописью ---
# Менеджер вводит только процент числом (royalty, 0..100 целых).
# Текст прописью (royalty_text) вычисляется отсюда — раньше вводился
# отдельным полем вручную, теперь это computed-поле (см. COMPUTED_FIELDS
# в template_analysis.py), риск разойтись с числом исключён.

_UNITS_RU = ["ноль", "один", "два", "три", "четыре",
             "пять", "шесть", "семь", "восемь", "девять"]
_TEENS_RU = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать",
             "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
_TENS_RU = {
    2: "двадцать", 3: "тридцать", 4: "сорок", 5: "пятьдесят",
    6: "шестьдесят", 7: "семьдесят", 8: "восемьдесят", 9: "девяносто",
}


def num_to_words_ru(n: int) -> str:
    """
    Целое число 0..100 -> числительное прописью, мужской род
    ('один', 'два' — не 'одна'/'две'), т.к. согласуется со словом
    'процент' (м.р.): 21 -> 'двадцать один'.
    """
    if not (0 <= n <= 100):
        raise ValueError("num_to_words_ru принимает только 0..100")
    if n == 0:
        return _UNITS_RU[0]
    if n == 100:
        return "сто"
    if n < 10:
        return _UNITS_RU[n]
    if n < 20:
        return _TEENS_RU[n - 10]
    tens, unit = divmod(n, 10)
    word = _TENS_RU[tens]
    if unit:
        word += " " + _UNITS_RU[unit]
    return word


# Родительный падеж числительных — для оборотов вида «в течение 10
# (десяти) рабочих дней» («в течение» требует родительного падежа).
# Это ДРУГИЕ слова, не просто окончание: «пять» -> «пяти», не «пять» + и.
_UNITS_GEN_RU = ["ноля", "одного", "двух", "трёх", "четырёх",
                 "пяти", "шести", "семи", "восьми", "девяти"]
_TEENS_GEN_RU = ["десяти", "одиннадцати", "двенадцати", "тринадцати",
                 "четырнадцати", "пятнадцати", "шестнадцати",
                 "семнадцати", "восемнадцати", "девятнадцати"]
_TENS_GEN_RU = {
    2: "двадцати", 3: "тридцати", 4: "сорока", 5: "пятидесяти",
    6: "шестидесяти", 7: "семидесяти", 8: "восьмидесяти", 9: "девяноста",
}


def num_to_words_ru_genitive(n: int) -> str:
    """
    Целое число 0..100 -> числительное в родительном падеже:
    10 -> 'десяти', 15 -> 'пятнадцати', 21 -> 'двадцати одного'.
    Для оборотов «в течение N (...) дней», «не позднее N (...) дней» и т.п.
    """
    if not (0 <= n <= 100):
        raise ValueError("num_to_words_ru_genitive принимает только 0..100")
    if n == 0:
        return _UNITS_GEN_RU[0]
    if n == 100:
        return "ста"
    if n < 10:
        return _UNITS_GEN_RU[n]
    if n < 20:
        return _TEENS_GEN_RU[n - 10]
    tens, unit = divmod(n, 10)
    word = _TENS_GEN_RU[tens]
    if unit:
        word += " " + _UNITS_GEN_RU[unit]
    return word


def percent_word_ru(n: int) -> str:
    """
    Падеж слова 'процент' после числительного n:
        1, 21, 31...   -> 'процент'
        2-4, 22-24...  -> 'процента'
        0, 5-20, 25...  -> 'процентов'
    """
    if 11 <= n % 100 <= 14:
        return "процентов"
    last = n % 10
    if last == 1:
        return "процент"
    if 2 <= last <= 4:
        return "процента"
    return "процентов"


def build_royalty_text(royalty_raw) -> str:
    """
    '50' -> 'пятьдесят процентов', '1' -> 'один процент', '22' -> 'двадцать два процента'.

    Пустое значение -> '' (стандартная проверка обязательных полей перед
    рендерингом сама поймает незаполненный royalty — не дублируем ошибку тут).
    Некорректное значение (не целое 0..100) -> ValueError с понятным текстом,
    роутер превращает его в HTTP 400.
    """
    if royalty_raw is None or str(royalty_raw).strip() == "":
        return ""
    raw_str = str(royalty_raw).strip()
    try:
        n = int(raw_str)
    except ValueError:
        raise ValueError(
            f"Роялти должно быть целым числом от 0 до 100, получено: «{raw_str}»"
        )
    if not (0 <= n <= 100):
        raise ValueError(f"Роялти должно быть от 0 до 100, получено: {n}")
    return f"{num_to_words_ru(n)} {percent_word_ru(n)}"


# --- Суммы прописью (аванс, SMM) ---
# Оператор вводит полную сумму в рублях (напр. 150000). В договоре она
# печатается как «150 000» (разряды через пробел, build_amount_spaced)
# плюс пропись «сто пятьдесят тысяч» (build_amount_text). Слова «рублей»
# и «00 копеек» уже в тексте шаблона — здесь только число и его пропись.

# женский род для тысяч: «одна тысяча», «две тысячи»
_UNITS_F_RU = ["ноль", "одна", "две", "три", "четыре",
               "пять", "шесть", "семь", "восемь", "девять"]
_HUNDREDS_RU = {
    1: "сто", 2: "двести", 3: "триста", 4: "четыреста", 5: "пятьсот",
    6: "шестьсот", 7: "семьсот", 8: "восемьсот", 9: "девятьсот",
}


def _triple_to_words(n: int, feminine: bool = False) -> str:
    """Число 0..999 прописью. feminine — женский род единиц (для тысяч)."""
    units = _UNITS_F_RU if feminine else _UNITS_RU
    words = []
    h, rest = divmod(n, 100)
    if h:
        words.append(_HUNDREDS_RU[h])
    if rest:
        if rest < 10:
            words.append(units[rest])
        elif rest < 20:
            words.append(_TEENS_RU[rest - 10])
        else:
            tens, unit = divmod(rest, 10)
            words.append(_TENS_RU[tens])
            if unit:
                words.append(units[unit])
    return " ".join(words)


def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    """Русское склонение по числу: 1 тысяча / 2 тысячи / 5 тысяч."""
    if 11 <= n % 100 <= 14:
        return many
    last = n % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def amount_to_words_ru(n: int) -> str:
    """
    Целое 0..999_999_999 -> сумма прописью, напр.
        150000  -> 'сто пятьдесят тысяч'
        1000000 -> 'один миллион'
        2500    -> 'две тысячи пятьсот'
    Без слова «рублей» — оно уже в тексте шаблона.
    """
    if n == 0:
        return "ноль"
    if not (0 < n <= 999_999_999):
        raise ValueError("amount_to_words_ru: поддерживается 0..999 999 999")

    parts = []
    millions, rest = divmod(n, 1_000_000)
    thousands, units = divmod(rest, 1_000)

    if millions:
        parts.append(_triple_to_words(millions))
        parts.append(_plural_ru(millions, "миллион", "миллиона", "миллионов"))
    if thousands:
        parts.append(_triple_to_words(thousands, feminine=True))
        parts.append(_plural_ru(thousands, "тысяча", "тысячи", "тысяч"))
    if units:
        parts.append(_triple_to_words(units))

    return " ".join(parts)


def build_amount_spaced(amount_raw) -> str:
    """
    '150000' -> '150 000' (разряды через неразрывный пробел \\u00a0, чтобы
    Word не переносил число). '' -> ''.
    """
    if amount_raw is None or str(amount_raw).strip() == "":
        return ""
    n = _parse_amount(amount_raw)
    return f"{n:,}".replace(",", "\u00a0")


def build_amount_text(amount_raw) -> str:
    """
    '150000' -> 'сто пятьдесят тысяч'. '' -> ''.
    Первая буква строчная — в тексте договора идёт в скобках после числа.
    """
    if amount_raw is None or str(amount_raw).strip() == "":
        return ""
    n = _parse_amount(amount_raw)
    return amount_to_words_ru(n)


def build_count_text(count_raw) -> str:
    """
    Количество будущих треков/объектов прописью: '5' -> 'пять'.
    Переиспользует ту же функцию числительных, что и суммы (amount_to_words_ru)
    — она не привязана к деньгам, просто число словами. Единица измерения
    («Треков», «Объектов») уже в тексте шаблона рядом с меткой, здесь не
    добавляется. '' если не задано.
    """
    if count_raw is None or str(count_raw).strip() == "":
        return ""
    n = _parse_amount(count_raw)  # та же проверка: целое, неотрицательное
    return amount_to_words_ru(n)


def build_advance_days_text(advance_days_raw) -> str:
    """
    Срок выплаты аванса в родительном падеже: '10' -> 'десяти',
    '15' -> 'пятнадцати'. Для оборота «в течение N (...) рабочих дней».

    По умолчанию (если поле не заполнено оператором) — 10 рабочих дней,
    как было жёстко зашито в тексте юриста; оператор может изменить.
    """
    raw = advance_days_raw
    if raw is None or str(raw).strip() == "":
        raw = 10
    n = _parse_amount(raw)
    if n > 100:
        raise ValueError(f"Срок выплаты аванса слишком большой: {n} дней")
    return num_to_words_ru_genitive(n)


def resolve_penalty_raw(raw: dict) -> str:
    """
    Штраф за непереданный трек (шаблон СГ_аванс с обязательством на
    будущие треки, п.2.1.3).

    Если оператор вписал сумму в поле penalty явно — используем её как
    есть (ручной override, как и с advance_days). Если поле пустое —
    считаем по умолчанию как «сумма аванса / количество треков»
    (округление до целого рубля, обычное арифметическое) — логика в том,
    что штраф за один непереданный трек соразмерен доле аванса,
    приходящейся на этот трек. Оператор в любой момент может поправить
    вручную, если по факту согласована другая сумма.

    Пустая строка, если не заполнены advance/count (и то, и другое нужно
    для расчёта) — тогда find_missing_variables поймает penalty как
    незаполненное обязательное поле, а не молча подставит 0.
    """
    explicit = str(raw.get("penalty") or "").strip()
    if explicit:
        return explicit

    advance_raw = str(raw.get("advance") or "").strip()
    count_raw = str(raw.get("count") or "").strip()
    if not advance_raw or not count_raw:
        return ""

    try:
        advance_n = _parse_amount(advance_raw)
        count_n = _parse_amount(count_raw)
    except ValueError:
        return ""  # некорректный ввод в advance/count — не наше дело здесь,
                   # это поймает своя собственная валидация этих полей
    if count_n == 0:
        return ""
    return str(round(advance_n / count_n))


def _parse_amount(amount_raw) -> int:
    """Парсит сумму: убирает пробелы-разделители, проверяет целое >= 0."""
    s = str(amount_raw).strip().replace(" ", "").replace("\u00a0", "")
    try:
        n = int(s)
    except ValueError:
        raise ValueError(f"Сумма должна быть целым числом, получено: «{amount_raw}»")
    if n < 0:
        raise ValueError(f"Сумма не может быть отрицательной, получено: {n}")
    if n > 999_999_999:
        raise ValueError(f"Слишком большая сумма: {n}")
    return n


def build_term_end(document_date_raw) -> str:
    """
    Срок действия договора/приложения/акта — 5 лет от даты документа,
    округлённые ВВЕРХ до конца квартала, в котором окажется дата +5 лет.

    document_date_raw — дата САМОГО документа в любом формате, понятном
    parse_date() (ISO из календаря, «15» марта 2026 г., 15.03.2026).
    Для комбинированного Договора это c_date, для отдельных Приложения/
    Акта — их собственная date (см. build_context).

    Пример: документ от 01.12.2020 -> +5 лет = 01.12.2025, это Q4
    -> 'до 31 декабря 2025 г.' (год — год даты+5, а не год исходного
    документа: если оригинал в январе, а +5 лет улетает в декабрь того
    же +5 года, это всё ещё тот год, никакого дополнительного сдвига).

    '' если document_date_raw пуст или не распознан — find_missing_variables
    поймает это как незаполненное поле вместо того, чтобы молча
    посчитать срок от 01.01.1900.
    """
    parsed = parse_date(document_date_raw)
    if not parsed:
        return ""
    day, month, year = parsed
    base = _date(int(year), int(month), int(day))

    try:
        future = base.replace(year=base.year + 5)
    except ValueError:
        # 29 февраля — через 5 лет год не обязательно високосный
        future = base.replace(year=base.year + 5, day=28)

    quarter = (future.month - 1) // 3 + 1
    return f"{QUARTER_ENDS[quarter]} {future.year} г."


def build_context(raw: dict, doc_type: str | None = None) -> dict:
    """
    Превращает данные формы в готовый контекст для docxtpl.

    doc_type — тип шаблона ('contract' | 'appendix' | 'act' | None),
    от него зависит трактовка contract/c_date/date:

      doc_type == 'contract' (или None) — комбинированный Договор.
        Оператор вводит ОДНУ дату (c_date). Из неё вычисляются:
          - номер договора (contract), если не передан явно
          - date — печатается тем же значением, что и c_date
        (весь пакет подписывается одним днём, отдельной даты нет).

      doc_type in ('appendix', 'act') — отдельный файл Приложения/Акта,
        привязанный к УЖЕ СУЩЕСТВУЮЩЕМУ договору. Базы контрагентов пока
        нет (этап 4 не начат), поэтому номер вводится вручную — но дату
        того договора вводить второй раз не нужно, она уже зашита в
        номере (ДД/ММ/ГГ) и извлекается оттуда (contract_date_iso):
          - contract — номер существующего договора, вводится вручную
          - c_date   — дата существующего договора, ВЫЧИСЛЯЕТСЯ из
                        номера (не поле формы, скрыто из формы)
          - date     — дата САМОГО Приложения/Акта, отдельное поле,
                        вводится оператором, может не совпадать с c_date

    Ожидаемый вход (raw):
        name, inn, nickname, contract (для appendix/act), c_date (для
        комбинированного Договора), date (для appendix/act)

        name_short — если не задано, собирается из name ('И.И. Иванов')

        release_type: 'album' | 'ep' | 'none'
        release_name, release_year   (если release_type != 'none')
        tracks: [{title, music_author, lyrics_author, performer,
                  producer, share_author, share_related, has_profanity}]
        has_videoclip: bool
        videoclips: [{title, director, music_author, performer,
                      production, producer, share}]
        performers: [{nickname, fio}, ...]  (уникальные, из таблицы треков)
        is_group: bool   (True — исполнители образуют группу; её название
                          берётся из никнейма в столбце «Исполнитель»)
        (срок действия term_end вычисляется автоматически из даты
        документа, отдельно не вводится — см. build_term_end)

    Сноска исполнителя строится как "никнейм - ФИО" для одиночного
    исполнителя (nickname берётся из того же поля, что и в преамбуле).
    """
    # Служебные поля: нужны только для вычислений, в шаблон не идут.
    # Всё остальное из raw попадёт в контекст как есть.
    SERVICE_KEYS = {
        "contract_day", "contract_month", "contract_year", "doc_kind",
        "performers", "is_group",
    }

    tracks = raw.get("tracks", [])
    full_name = raw.get("name", "")

    release_type = raw.get("release_type", "none")
    release_labels = {"album": "Альбом", "ep": "ЕР", "none": ""}

    # Приложение/Акт — отдельный файл, привязанный к уже существующему
    # договору. Без базы контрагентов (этап 4) номер этого договора
    # взять неоткуда, кроме как спросить оператора напрямую — но ДАТУ
    # того договора спрашивать второй раз не нужно: она уже зашита в
    # номере (ДД/ММ/ГГ), парсим её оттуда (contract_date_iso).
    is_linked_doc = doc_type in ("appendix", "act")

    # --- Номер договора ---
    #   doc_type='contract' (или не задан) — комбинированный Договор:
    #     вычисляется из даты (c_date) + инициалов ФИО, если не передан
    #     явно готовой строкой (contract).
    #   doc_type='appendix'/'act' — номер УЖЕ существующего договора,
    #     вводится вручную. Дата этого номера ≠ дата самого Приложения/
    #     Акта (date) — поэтому не пересчитываем.
    contract = str(raw.get("contract") or "").strip()

    if is_linked_doc:
        # дата САМОГО договора — не вводится, извлекается из его номера
        c_date_raw = contract_date_iso(contract)
    else:
        c_date_raw = raw.get("c_date", "")
        parsed_c_date = parse_date(c_date_raw)
        if not contract:
            if parsed_c_date:
                day, month, year_full = parsed_c_date
                year = year_full[-2:]           # 2026 -> 26
            else:
                day = raw.get("contract_day", "01")
                month = raw.get("contract_month", "01")
                year = raw.get("contract_year", "26")

            contract = build_contract_number(
                day=day,
                month=month,
                year=year,
                full_name=full_name,
                doc_kind=raw.get("doc_kind", "СГ"),
            )
    # doc_type='appendix'/'act' и contract пуст (или не в ожидаемом
    # формате) — c_date_raw останется пустым, find_missing_variables
    # поймает это как незаполненное обязательное поле, вместо того
    # чтобы молча подставить пустую дату в документ.

    # дата САМОГО документа (Приложения/Акта) — только для linked_doc,
    # для комбинированного Договора date дублирует c_date (см. ниже)
    date_raw = raw.get("date", "")

    # Краткое имя для подписи — тоже из ФИО
    name_short = raw.get("name_short") or build_name_short(full_name)

    # ШАГ 1. Пропускаем все пользовательские поля как есть.
    # Это важно: договор содержит десятки простых меток (npd, birthday,
    # serial, number, pas_place, pas_date, kp, adress, phone, mail,
    # rs, bank, ks, bik, royalty ...). Перечислять их вручную нельзя —
    # при добавлении новой метки в шаблон её легко забыть, и она молча
    # подставится пустой строкой.
    context = {k: v for k, v in raw.items() if k not in SERVICE_KEYS}

    # ШАГ 2. Поверх кладём вычисляемые значения.
    context.update({
        "contract": contract,
        "name_short": name_short,

        # даты — в документ печатается русский формат, а не ISO из календаря.
        #   contract-пакет: оператор вводит c_date, date дублирует его
        #   (единая дата пакета).
        #   appendix/act: c_date вычислена из номера (contract_date_iso,
        #   см. выше) — дата уже существующего договора; date — отдельная
        #   дата САМОГО документа (Приложения/Акта), вводится оператором.
        "c_date": format_date_ru(c_date_raw),
        "date": format_date_ru(date_raw) if is_linked_doc else format_date_ru(c_date_raw),

        # тип релиза
        "release_type": release_type,
        "release_label": release_labels.get(release_type, ""),
        "release_name": raw.get("release_name", ""),
        "release_year": raw.get("release_year", ""),

        # роялти прописью — из числа (royalty), не вводится отдельно
        "royalty_text": build_royalty_text(raw.get("royalty")),

        # суммы аванса и SMM (шаблон СГ_аванс): число с пробелом-разделителем
        # + пропись. advance — сумма аванса (п.2.1.1), smm — сумма на SMM
        # мероприятия (п.2.1.2, показывается только при marketing=True).
        "advance": build_amount_spaced(raw.get("advance")),
        "advance_text": build_amount_text(raw.get("advance")),
        "smm": build_amount_spaced(raw.get("smm")),
        "smm_text": build_amount_text(raw.get("smm")),

        # штраф за непереданный трек (шаблон СГ_аванс с обязательством на
        # будущие треки, п.2.1.3) — по умолчанию считается как
        # advance/count (см. resolve_penalty_raw), оператор может
        # переопределить вручную
        "penalty": build_amount_spaced(resolve_penalty_raw(raw)),
        "penalty_text": build_amount_text(resolve_penalty_raw(raw)),

        # количество будущих треков/объектов прописью (тот же шаблон,
        # п.1.1 и п.2) — используем ту же функцию числительных, что и для
        # сумм, просто без денежной единицы (её в тексте шаблона нет,
        # там "Треков"/"Объектов" уже стоит рядом с меткой)
        "count_text": build_count_text(raw.get("count")),

        # срок выплаты аванса (шаблон СГ_аванс с обязательством на будущие
        # треки, п.2.2) — по умолчанию 10 рабочих дней, оператор может
        # поменять. И само число, и пропись дефолтятся на 10 одинаково,
        # чтобы не разойтись, если оператор оставил поле пустым.
        "advance_days": str(raw.get("advance_days") or "").strip() or "10",
        "advance_days_text": build_advance_days_text(raw.get("advance_days")),

        # срок предоставления исходников (шаблон СГ_аванс с обязательством
        # на будущие треки) — независимая дата, приходит из календаря в ISO,
        # печатается в тексте как «15» марта 2026 г., как и остальные даты
        "delivery_date": format_date_ru(raw.get("delivery_date", "")),

        # таблицы
        "tracks": tracks,
        "has_videoclip": bool(raw.get("has_videoclip")),
        "videoclips": raw.get("videoclips", []),

        # вычисляемые сноски
        "profanity_note": build_profanity_note(tracks),
        "performer_note": build_performer_note(
            _normalize_performers(
                raw.get("performers"), bool(raw.get("is_group"))
            ),
            raw.get("nickname"),
            bool(raw.get("is_group")),
        ),

        # срок действия — 5 лет от даты САМОГО документа, до конца квартала.
        # Для комбинированного Договора это c_date, для отдельных
        # Приложения/Акта — их собственная date (не дата договора-родителя).
        # срок действия — предзаполняется автоматически (5 лет от даты
        # документа, до конца квартала), но оператор может его поправить
        # в форме вручную — иногда срок отличается от стандартного
        # правила. Если поле заполнено — берём как есть; посчитанное
        # значение это только предложение по умолчанию, не жёсткая логика.
        "term_end": (
            str(raw.get("term_end") or "").strip()
            or build_term_end(date_raw if is_linked_doc else c_date_raw)
        ),
    })
    return context


def find_missing_variables(template_variables: set[str], context: dict) -> list[str]:
    """
    Возвращает метки шаблона, для которых в контексте нет значения
    (ключ отсутствует или значение пустое).

    Нужно, чтобы поймать ситуацию, когда шаблон содержит метку, а форма
    её не заполнила: docxtpl молча подставит пустую строку, и в договоре
    окажется «Дата рождения: » без значения.

    Вызывать перед render():

        vars_ = DocxTemplate(path).get_undeclared_template_variables()
        missing = find_missing_variables(vars_, ctx)
        if missing:
            raise ValueError(f"Не заполнены поля: {missing}")
    """
    missing = []
    for var in sorted(template_variables):
        if var not in context:
            missing.append(var)
            continue
        value = context[var]
        # пустая строка/None — тоже незаполненное поле.
        # False и 0 — валидные значения (флаги edo, has_videoclip)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(var)
    return missing
