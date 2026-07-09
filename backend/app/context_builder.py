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


def parse_day_month(c_date: str) -> tuple[str, str] | None:
    """
    Извлекает день и месяц из даты договора для сборки его номера.

        '«15» марта 2026 г.' -> ('15', '03')
        '15.03.2026'          -> ('15', '03')

    Нужно, чтобы номер договора не разошёлся с его датой.
    Возвращает None, если распознать не удалось.
    """
    if not c_date:
        return None

    # формат «15» марта 2026 г.
    m = re.search(r"«?(\d{1,2})»?\s+([а-яё]+)", c_date, re.IGNORECASE)
    if m:
        day = m.group(1).zfill(2)
        month = MONTHS_RU.get(m.group(2).lower())
        if month:
            return day, month

    # формат 15.03.2026 или 15/03/2026
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})[./]\d{2,4}\b", c_date)
    if m:
        return m.group(1).zfill(2), m.group(2).zfill(2)

    return None


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


def _normalize_performers(raw_performers) -> list[dict]:
    """
    Приводит исполнителей к списку {'nickname': ..., 'fio': ...}.

    Форма присылает list-поля как список объектов:
        [{"nickname": "IVAN", "fio": "Иванов И.И."}, ...]
    Поддерживается и старый вид (только ФИО строкой) — для обратной
    совместимости с кодом/тестами, где никнейм не передавали.
    """
    if not raw_performers:
        return []
    result = []
    for p in raw_performers:
        if isinstance(p, dict):
            nickname = str(p.get("nickname", "")).strip()
            fio = str(p.get("fio", "")).strip()
            if nickname or fio:
                result.append({"nickname": nickname, "fio": fio})
        elif p:
            result.append({"nickname": "", "fio": str(p).strip()})
    return result


def build_performer_note(
    performers: list[dict],
    nickname: str | None = None,
    group_name: str | None = None,
) -> str:
    """
    Формирует сноску про исполнителей (всегда присутствует).
    Формат: "никнейм - ФИО" — для КАЖДОГО исполнителя, без буквенных
    обозначений (буквы в колонке таблицы треков были ошибкой первой
    версии — юрист имел в виду именно никнейм-ФИО построчно).

      - один исполнитель            -> "Исполнитель: IVAN - Иванов И.И."
      - группа (указано group_name) -> "Исполнители в составе группы «X»: Иванов И.И., Петров П.П."
      - несколько без группы         -> "Исполнители: IVAN - Иванов И.И.; PETROV - Петров П.П."

    performers — список словарей {'nickname', 'fio'} (см. _normalize_performers).
    Каждая пара соответствует одному треку — колонка «Исполнитель» в
    таблице треков теперь заполняется никнеймом напрямую, а не буквой.
    """
    if not performers:
        return "Исполнитель: —"

    if len(performers) == 1:
        p = performers[0]
        fio = p["fio"]
        nick = p["nickname"] or nickname or ""
        if nick:
            return f"Исполнитель: {nick} - {fio}"
        return f"Исполнитель: {fio}"

    if group_name:
        fios = ", ".join(p["fio"] for p in performers)
        return f"Исполнители в составе группы «{group_name}»: {fios}"

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


def build_term_end(quarter, year) -> str:
    """
    Возвращает дату окончания Срока, напр. '31 декабря 2027 г.'

    quarter и year могут прийти как строки (HTML-форма всегда шлёт строки)
    или как числа (из кода/тестов) — приводим к int.
    """
    try:
        quarter = int(quarter)
        year = int(year)
    except (TypeError, ValueError):
        raise ValueError("Квартал и год должны быть числами")

    if quarter not in QUARTER_ENDS:
        raise ValueError("Квартал должен быть 1..4")
    return f"{QUARTER_ENDS[quarter]} {year} г."


def build_context(raw: dict) -> dict:
    """
    Превращает данные формы в готовый контекст для docxtpl.

    Ожидаемый вход (raw):
        name, inn, nickname, c_date, date

        Номер договора — три источника, по приоритету:
          1. contract — готовая строка целиком.
             Для приложений и актов номер берётся из договора того же
             контрагента. Когда появится справочник контрагентов (этап 4),
             номер будет подтягиваться оттуда автоматически.
          2. contract_day + contract_month — день и месяц заключения
             договора, вводятся вручную (текущий вариант).
          3. Если ни то, ни другое — день и месяц извлекаются из c_date.
          Плюс contract_year (по умолчанию '26') и doc_kind ('СГ').

        Инициалы в номере вычисляются из name автоматически:
        'Иванов Иван Иванович' + день 01, месяц 01 -> 'МЛ-01/01/26-ИИИ/СГ'

        name_short — если не задано, собирается из name ('И.И. Иванов')

        release_type: 'album' | 'ep' | 'none'
        release_name, release_year   (если release_type != 'none')
        tracks: [{title, music_author, lyrics_author, performer,
                  producer, share_author, share_related, has_profanity}]
        has_videoclip: bool
        videoclips: [{title, director, music_author, performer,
                      production, producer, share}]
        performers: ['Иванов И.И.', ...]
        group_name: str | None   (если исполнители — группа)
        term_quarter: 1..4
        term_year: int

    Сноска исполнителя строится как "никнейм - ФИО" для одиночного
    исполнителя (nickname берётся из того же поля, что и в преамбуле).
    """
    # Служебные поля: нужны только для вычислений, в шаблон не идут.
    # Всё остальное из raw попадёт в контекст как есть.
    SERVICE_KEYS = {
        "contract_day", "contract_month", "contract_year", "doc_kind",
        "performers", "group_name",
        "term_quarter", "term_year",
    }

    tracks = raw.get("tracks", [])
    full_name = raw.get("name", "")

    release_type = raw.get("release_type", "none")
    release_labels = {"album": "Альбом", "ep": "ЕР", "none": ""}

    # Номер договора. Три источника, в порядке приоритета:
    #   1. contract — готовая строка (для приложений/актов: берётся из
    #      договора контрагента; когда появится справочник — подтянется оттуда)
    #   2. contract_day + contract_month — ручной ввод дня и месяца
    #   3. извлечение дня/месяца из даты договора c_date (запасной вариант)
    # Инициалы всегда вычисляются из ФИО.
    contract = raw.get("contract")
    if not contract:
        day = raw.get("contract_day")
        month = raw.get("contract_month")

        if not (day and month):
            # пробуем достать день/месяц из даты договора
            parsed = parse_day_month(raw.get("c_date", ""))
            if parsed:
                day, month = parsed

        contract = build_contract_number(
            day=day or "01",
            month=month or "01",
            year=raw.get("contract_year", "26"),
            full_name=full_name,
            doc_kind=raw.get("doc_kind", "СГ"),
        )

    # Краткое имя для подписи — тоже из ФИО
    name_short = raw.get("name_short") or build_name_short(full_name)

    # ШАГ 1. Пропускаем все пользовательские поля как есть.
    # Это важно: договор содержит десятки простых меток (npd, birthday,
    # serial, number, pas_place, pas_date, kp, adress, phone, mail,
    # rs, bank, ks, bik, royalty, royalty_text ...). Перечислять их
    # вручную нельзя — при добавлении новой метки в шаблон её легко
    # забыть, и она молча подставится пустой строкой.
    context = {k: v for k, v in raw.items() if k not in SERVICE_KEYS}

    # ШАГ 2. Поверх кладём вычисляемые значения.
    context.update({
        "contract": contract,
        "name_short": name_short,

        # тип релиза
        "release_type": release_type,
        "release_label": release_labels.get(release_type, ""),
        "release_name": raw.get("release_name", ""),
        "release_year": raw.get("release_year", ""),

        # таблицы
        "tracks": tracks,
        "has_videoclip": bool(raw.get("has_videoclip")),
        "videoclips": raw.get("videoclips", []),

        # вычисляемые сноски
        "profanity_note": build_profanity_note(tracks),
        "performer_note": build_performer_note(
            _normalize_performers(raw.get("performers")),
            raw.get("nickname"),
            raw.get("group_name"),
        ),

        # срок действия
        "term_end": build_term_end(
            raw.get("term_quarter", 4), raw.get("term_year", 2027)
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
